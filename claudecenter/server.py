"""Local server: watches your agents, rings your phone, relays the call.

Runs on your machine. Serves the web app over HTTP and talks to it over a
WebSocket on the same port. Audio is relayed between the phone and Gemini,
so your API key never leaves the machine.
"""
import asyncio
import json
import os
import pathlib
import time

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

from . import config, herdr
from .operator import Operator

WEB = pathlib.Path(__file__).resolve().parent / "web"

clients = set()
active = None            # the phone that most recently connected
pending = asyncio.Queue()
on_call = False
line = asyncio.Lock()    # one call at a time, like a real phone
last_call = 0.0


def waiting():
    """Agents that need you. Blocked ones are permission modals — skipped,
    because a modal cannot be answered by voice."""
    return [a for a in herdr.agents()
            if a["agent_status"] in herdr.ANSWERABLE
            and a["pane_id"] not in config.IGNORED_PANES]


class Session:
    """One connected phone.

    A single reader drains the socket and fans messages out by queue. If two
    coroutines call recv() on the same connection the library rejects it and
    the call dies silently.
    """

    def __init__(self, ws):
        self.ws = ws
        self.text = asyncio.Queue()
        self.audio = asyncio.Queue()

    async def read_loop(self):
        async for message in self.ws:
            if isinstance(message, bytes):
                await self.audio.put(message)
            else:
                try:
                    await self.text.put(json.loads(message))
                except json.JSONDecodeError:
                    pass

    async def send(self, kind, **fields):
        await self.ws.send(json.dumps({"t": kind, **fields}))

    async def expect(self, *kinds, timeout=None):
        while True:
            msg = await asyncio.wait_for(self.text.get(), timeout)
            if msg.get("t") == "hangup":
                raise ConnectionError("hung up")
            if not kinds or msg.get("t") in kinds:
                return msg


async def call(session, agent):
    """Ring, and if you pick up, a real-time conversation with the operator."""
    global on_call
    on_call = True
    pane = agent["pane_id"]
    who = herdr.title(agent)
    project = herdr.project(agent)
    print(f"  calling about {who} ({project})")
    delivered = None
    try:
        screen = await asyncio.to_thread(herdr.read_pane, pane)

        async def run_tool(name, args):
            nonlocal delivered
            if name == "send_instruction":
                text = args.get("instruction", "").strip()
                ok = await asyncio.to_thread(herdr.send_prompt, pane, text)
                delivered = text if ok else None
                print(f"  -> to the agent: {text!r} ({'ok' if ok else 'failed'})")
                await session.send("delivered", text=text, ok=ok)
                return {"result": "delivered" if ok else
                        "could not deliver, the agent is blocked"}
            if name == "read_screen":
                fresh = await asyncio.to_thread(herdr.read_pane, pane)
                print("  -> re-read the screen")
                return {"screen": fresh[-6000:]}
            if name == "end_call":
                print(f"  -> hanging up: {args.get('reason','')}")
                return {"result": "ok"}
            return {"error": "unknown tool"}

        async with Operator(who, project, screen, run_tool) as op:
            # The operator reads the context and prepares its opening line
            # WHILE the phone rings, so there is no dead air when you answer.
            answered = asyncio.Event()
            buffered = []

            async def relay():
                async for kind, data in op.events():
                    if kind == "audio":
                        if answered.is_set():
                            await session.ws.send(data)
                        else:
                            buffered.append(data)
                    elif kind == "interrupted" and answered.is_set():
                        await session.send("interrupt")

            talking = asyncio.create_task(relay())
            await op.open_call()

            await session.send("ring", who=who, pane=pane,
                               cwd=agent["cwd"].replace(os.path.expanduser("~"), "~"),
                               state=agent["agent_status"])
            print("  ringing")
            try:
                answer = await session.expect("accept", "reject", timeout=60)
            except BaseException:
                talking.cancel()
                raise
            if answer["t"] == "reject":
                talking.cancel()
                print("  rejected")
                return None
            print(f"  answered ({len(buffered)} chunks already waiting)")

            answered.set()
            await session.send("connected")
            for chunk in buffered:
                await session.ws.send(chunk)
            buffered.clear()

            async def from_phone():
                while True:
                    await op.send_audio(await session.audio.get())

            pump = asyncio.create_task(from_phone())
            # If the phone disconnects — Android freezes background tabs — the
            # call must end, or it stays alive forever and blocks the line.
            dropped = asyncio.create_task(session.ws.wait_closed())
            limit = asyncio.create_task(asyncio.sleep(config.MAX_CALL))
            try:
                done, _ = await asyncio.wait({talking, dropped, limit},
                                             return_when=asyncio.FIRST_COMPLETED)
                if dropped in done:
                    print("  the phone disconnected")
                elif limit in done:
                    print("  call ran too long, hanging up")
            finally:
                for task in (pump, talking, dropped, limit):
                    task.cancel()

        await session.send("ended", text=delivered, delivered=delivered is not None)
        return delivered
    except ConnectionError:
        print("  you hung up")
        return delivered
    except asyncio.TimeoutError:
        print("  no answer")
        try:
            await session.send("ended", text=None, delivered=False)
        except Exception:                              # noqa: BLE001
            pass
        return None
    except Exception as e:                             # noqa: BLE001
        print(f"  ! call failed: {type(e).__name__}: {e}")
        try:
            await session.send("ended", text=None, delivered=False)
        except Exception:                              # noqa: BLE001
            pass
        return None
    finally:
        on_call = False


async def watch():
    """Spot agents that got stuck and queue them up."""
    seen = {}
    if config.ONLY_NEW:
        for a in await asyncio.to_thread(herdr.agents):
            seen[a["pane_id"]] = a["state_change_seq"]
    while True:
        try:
            for a in await asyncio.to_thread(waiting):
                if seen.get(a["pane_id"]) == a["state_change_seq"]:
                    continue
                seen[a["pane_id"]] = a["state_change_seq"]
                await pending.put(a)
                print(f"  queued: {herdr.title(a)}")
        except Exception as e:                         # noqa: BLE001
            print(f"  ! watcher: {type(e).__name__}: {e}")
        await asyncio.sleep(config.POLL_SECONDS)


async def dispatch():
    """Call you about whoever is next, once the line is free and rested."""
    global last_call
    while True:
        await asyncio.sleep(1)
        if line.locked() or active is None or pending.empty():
            continue
        if time.time() - last_call < config.COOLDOWN:
            continue
        async with line:
            try:
                await call(active, await pending.get())
            except Exception as e:                     # noqa: BLE001
                print(f"  ! dispatch: {type(e).__name__}: {e}")
            last_call = time.time()


async def report():
    """Keep the queue counter on the phone's screen up to date."""
    while True:
        await asyncio.sleep(4)
        if active is None or on_call:
            continue
        try:
            await active.send("status",
                              waiting=len(await asyncio.to_thread(waiting)))
        except Exception:                              # noqa: BLE001
            pass


async def handle(ws):
    """One phone connection. Never touches the socket outside this loop."""
    global active, last_call
    session = Session(ws)
    active = session
    clients.add(ws)
    print(f"  phone connected ({len(clients)} online)")
    reader = asyncio.create_task(session.read_loop())
    try:
        await session.send("status",
                           waiting=len(await asyncio.to_thread(waiting)))
    except Exception:                                  # noqa: BLE001
        pass
    try:
        while not reader.done():
            try:
                msg = await asyncio.wait_for(session.text.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except ConnectionError:
                break
            if msg.get("t") == "call_next":
                if line.locked():
                    await session.send("notice", key="busy")
                    continue
                candidates = await asyncio.to_thread(waiting)
                if not candidates:
                    await session.send("notice", key="nobody")
                    continue
                async with line:
                    await call(session, candidates[0])
                    last_call = time.time()
    except Exception as e:                             # noqa: BLE001
        print(f"  ! session: {type(e).__name__}: {e}")
    finally:
        reader.cancel()
        clients.discard(ws)
        if active is session:
            active = None
        print(f"  phone disconnected ({len(clients)} online)")


def http(connection, request):
    """Serves the web app. Everything that is not a WebSocket lands here."""
    # The WebSocket handshake also arrives at "/". Answering it with HTML
    # means the connection is never established and the app stays mute.
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None

    path = request.path.split("?")[0]
    if path in ("/", "/index.html"):
        body = (WEB / "app.html").read_bytes()
        kind = "text/html; charset=utf-8"
    elif path == "/manifest.json":
        body = json.dumps({
            "name": "Claude Center", "short_name": "Claude Center",
            "start_url": "/", "display": "standalone",
            "background_color": "#141210", "theme_color": "#141210",
            "icons": [],
        }).encode()
        kind = "application/json"
    elif path == "/config.json":
        body = json.dumps({"lang": config.LANG}).encode()
        kind = "application/json"
    else:
        return connection.respond(404, "not found\n")
    return Response(200, "OK", Headers({
        "Content-Type": kind,
        "Content-Length": str(len(body)),
        "Cache-Control": "no-store",
    }), body)


async def main():
    problems = config.missing()
    if not herdr.available():
        problems.append(
            "Herdr was not found. Install it from https://herdr.dev — Claude "
            "Center reads your agents through it.")
    if problems:
        print("\n  Claude Center cannot start:\n")
        for p in problems:
            print(f"   • {p}")
        print()
        return

    if config.IGNORED_PANES:
        print(f"  ignoring panes: {', '.join(sorted(config.IGNORED_PANES))}")
    asyncio.create_task(watch())
    asyncio.create_task(dispatch())
    asyncio.create_task(report())
    print(f"\n  Claude Center is listening on http://localhost:{config.PORT}")
    print("  Open that address on your phone and leave the tab in front.\n")
    async with serve(handle, "0.0.0.0", config.PORT, process_request=http,
                     max_size=32 * 1024 * 1024):
        await asyncio.Future()


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  switchboard closed")
