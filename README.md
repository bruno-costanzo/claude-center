<div align="center">

# 📞 Claude Center

**A virtual call center for your AI coding agents.**
When one gets stuck, your phone rings. You answer, talk it through, hang up,
and it keeps working.

[Español](README.es.md) · [How it works](#how-it-works) · [Install](#install) · [Cost](#what-it-costs)

<img src="docs/screenshot-idle.png" alt="Claude Center" width="330">


</div>

---

> To confirm that programmers are now a gig-economy underclass doomed to talk to
> ten chatbots for the rest of our lives, this is a virtual phone your agents
> call when they need something. You unblock them, hang up, and wait for the
> next call.

## The problem

If you run several coding agents at once, you are the bottleneck. They stop —
waiting on a decision, a preference, a "yes, do that" — and then they sit
there. You find out minutes or hours later, when you go looking.

Claude Center flips it around: **the agent calls you.**

## What a call is like

Your phone rings with a real incoming-call screen. You answer, and an operator
tells you, in one or two sentences, which agent is stuck and why — ending in
the decision it needs from you.

The operator has read that agent's **entire terminal session** before calling.
So you can ask questions and it answers. You can interrupt it mid-sentence and
it stops. When you decide, it hands your instruction to the agent, confirms,
and hangs up. The agent keeps working.

It is a voice conversation, not a menu and not a voicemail.

## How it works

```
   Herdr                    your machine                    your phone
 ┌─────────┐            ┌──────────────────┐            ┌──────────────┐
 │ agent 1 │            │                  │            │              │
 │ agent 2 │──stuck?───▶│  Claude Center   │──ring─────▶│  📞 web app  │
 │ agent 3 │            │                  │◀──voice───▶│              │
 │  …      │◀─instruction─                 │            └──────────────┘
 └─────────┘            └────────┬─────────┘
                                 │ audio in / audio out
                                 ▼
                        ┌──────────────────┐
                        │ Gemini Live API  │  ← the operator's voice and ears
                        └──────────────────┘
```

1. **A watcher polls Herdr** every few seconds and notices agents that stopped
   and need you.
2. **It opens a Gemini Live session** with that agent's full terminal output as
   context, and asks the operator to prepare its opening line — *while your
   phone is still ringing*, so there is no dead air when you answer.
3. **Audio streams both ways** between your phone and Gemini, relayed through
   your machine. There is no transcribe-then-synthesize step, which is why
   interruption works.
4. **The operator has tools**: it can hand an instruction back to the agent,
   re-read the agent's screen if you ask something it doesn't know, or hang up.

Your API key stays on your machine. The phone only ever talks to your machine.

## Requirements

- **[Herdr](https://herdr.dev)** — the terminal workspace manager your agents
  run inside. Claude Center reads their state through its socket API.
- **Python 3.10+**
- **A Gemini API key** — free to create at
  [aistudio.google.com/apikey](https://aistudio.google.com/apikey). It needs
  access to the Live API (native audio) models.
- **A phone on the same network, or a tunnel** — see [Reaching your
  phone](#reaching-your-phone).

## Install

```bash
git clone https://github.com/bruno-costanzo/claude-center.git
cd claude-center
./setup.sh
```

Then open `.env` and paste your key:

```
GEMINI_API_KEY=your-key-here
CC_LANG=en          # or "es" for rioplatense Spanish
```

Start it **from inside a Herdr pane** — that way it knows which session is its
own and never calls you about itself:

```bash
./run.sh
```

You should see:

```
  Claude Center is listening on http://localhost:8765
```

## Reaching your phone

Browsers only grant microphone access over HTTPS, so `http://<your-lan-ip>`
will not work. Two ways around it:

**A tunnel** (simplest, works from anywhere):

```bash
cloudflared tunnel --url http://localhost:8765
```

That prints an `https://….trycloudflare.com` address. Open it on your phone.

**Tailscale** also works if you serve it over HTTPS with `tailscale serve`.

## Using it

Open the address on your phone and **leave the tab in the foreground**. Tap the
button once — that single tap is what unlocks browser audio and asks for
notification permission.

From then on it rings on its own whenever an agent gets stuck. The button also
lets you pull the next call manually.

When it rings: **answer**, listen, talk. Interrupt whenever you want. Say what
the agent should do. It confirms and hangs up.

## Configuration

Everything lives in `.env`.

| Variable | Default | What it does |
|---|---|---|
| `GEMINI_API_KEY` | — | **Required.** Your Google AI Studio key. |
| `CC_LANG` | `en` | `en` or `es`. Sets the operator's language and the app's. |
| `CC_VOICE` | `Callirrhoe` | Any Gemini Live voice: `Kore`, `Aoede`, `Leda`, `Autonoe`, `Despina`, `Puck`, `Charon`, `Orus`, `Iapetus`. |
| `CC_PORT` | `8765` | Port the local server listens on. |
| `CC_COOLDOWN` | `90` | Seconds between calls, so it doesn't drain the queue at once. |
| `CC_MAX_CALL` | `300` | Hard limit for one call, in seconds. |
| `CC_IGNORE` | — | Comma-separated Herdr pane IDs to never call about. |
| `CC_ONLY_NEW` | — | Set to `1` to ignore agents already waiting at startup. |

The app has a language toggle in the top-right corner too; your choice sticks
per device.

## What it costs

Only the Gemini Live API, billed by audio.

| | Audio in | Audio out |
|---|---|---|
| `gemini-2.5-flash-native-audio` | ~$0.005 / min | ~$0.018 / min |

A two-minute call is around **two to four cents**. Twenty calls a day lands
somewhere near **$7–15 a month**. Everything else — the server, the web app,
the watcher — runs on your machine for free.

## Limitations

Worth knowing before you install it:

- **The tab has to stay in the foreground.** Android and iOS freeze background
  tabs, so it will not ring with the phone locked. Web Push with a service
  worker would fix this and is not built yet.
- **Agents blocked on a permission prompt are skipped.** A modal cannot be
  answered by voice, so those stay for you to resolve in Herdr.
- **One call at a time**, like a real phone. The rest queue up.
- **Developed on macOS.** Nothing is macOS-specific, but Linux is untested.

## Troubleshooting

**It never rings.** Check the server log — every step is printed there. If you
see `queued:` lines but no `ringing`, the phone is not connected: reload the
page and confirm it says *online*.

**It rings but there is no sound.** The tap on the button is what unlocks audio
in the browser. Tap it once before expecting a call.

**It calls me about the Claude Center session itself.** Start it from inside a
Herdr pane so `HERDR_PANE_ID` is set, or add its pane to `CC_IGNORE`.

**`Herdr was not found`.** Install it from [herdr.dev](https://herdr.dev) and
make sure `herdr` is on your `PATH`.

## Project layout

```
claudecenter/
├── config.py      settings from .env, and what to do when they're missing
├── herdr.py       thin wrapper over the Herdr CLI
├── operator.py    the Gemini Live session: prompt, tools, audio events
├── server.py      the watcher, the switchboard, the WebSocket relay
└── web/app.html   the phone: call screens, ringtone, live audio
```

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, sell it, whatever.
