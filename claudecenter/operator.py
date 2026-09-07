"""The operator: a real-time voice conversation that has read the context.

This is the heart of Claude Center. When an agent gets stuck, the operator
reads its entire terminal output, then calls you and says one or two
sentences about it. If you ask a question it answers from that context. When
you decide, it hands the instruction back to the agent.

Audio streams both ways against the Gemini Live API — there is no
transcribe-then-synthesize step, which is why you can interrupt it mid-word.
"""
import base64
import json

import websockets

from . import config

WS_URL = ("wss://generativelanguage.googleapis.com/ws/"
          "google.ai.generativelanguage.v1beta.GenerativeService."
          "BidiGenerateContent?key={key}")

_SHARED = """\
You are the switchboard operator of a call center for AI coding agents. You
phone the developer when one of their agents gets stuck.

THE CALL
1. Open by naming the agent and, in one or two sentences, why it is stuck,
   ending with the concrete decision you need from them.
2. If they ask something, answer from the context below — you have read all
   of it. If the answer is not there, say so plainly and use read_screen to
   look again.
3. When they give a clear instruction, use send_instruction. Do not read the
   instruction back word for word first: send it and confirm briefly.
4. If they want to deal with it later, use end_call.

RULES
- TWO SENTENCES PER TURN MAXIMUM. Never speak for more than ten seconds
  straight. This is a phone call, not a report: if they want more, they'll ask.
- Never read file paths, commands, code or hashes out loud. Say them in words.
- No long greetings, no apologies, no filler like "perfect" or "great".
- Never invent anything that is not in the context. If you don't know, say so.
- They can interrupt you at any time. When they do, stop and listen.

STUCK AGENT: {who}
PROJECT: {project}

FULL SCREEN OF THE SESSION (your context — never read it out loud):
{screen}
"""

_STYLE = {
    "en": "You speak English. Direct, calm, conversational. Short sentences.",
    "es": ("Hablás español rioplatense de Buenos Aires, con voseo. Directa y "
           "tranquila, coloquial, como alguien que te avisa algo. Nada de "
           "acento neutro ni tono de locutora. Frases cortas."),
}

TOOLS = [{"functionDeclarations": [
    {"name": "send_instruction",
     "description": "Hand the developer's instruction to the stuck agent so it "
                    "can keep working. Use it once the decision is clear.",
     "parameters": {"type": "OBJECT", "properties": {
         "instruction": {"type": "STRING",
                         "description": "What the agent should do, imperative, "
                                        "with the detail the developer gave."}},
         "required": ["instruction"]}},
    {"name": "read_screen",
     "description": "Re-read the agent's terminal right now, in case it changed "
                    "or you are missing a detail the developer asked about.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "end_call",
     "description": "Hang up without sending anything to the agent.",
     "parameters": {"type": "OBJECT", "properties": {
         "reason": {"type": "STRING"}}}},
]}]

OPENING = {"en": "I picked up. Go ahead.", "es": "Atendí. Contame."}


class Operator:
    """One live call against Gemini."""

    def __init__(self, who, project, screen, run_tool, lang=None, voice=None):
        # run_tool(name, args) -> dict, executed locally against Herdr.
        self.who = who
        self.project = project
        self.screen = screen
        self.run_tool = run_tool
        self.lang = lang or config.LANG
        self.voice = voice or config.VOICE
        self.ws = None
        self.ended = False

    async def __aenter__(self):
        self.ws = await websockets.connect(
            WS_URL.format(key=config.GEMINI_API_KEY), max_size=None)
        instructions = (_STYLE.get(self.lang, _STYLE["en"]) + "\n\n" +
                        _SHARED.format(who=self.who, project=self.project,
                                       screen=self.screen[:12000]))
        await self.ws.send(json.dumps({"setup": {
            "model": config.MODEL,
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": self.voice}}}},
            "systemInstruction": {"parts": [{"text": instructions}]},
            "tools": TOOLS,
        }}))
        await self.ws.recv()          # setupComplete
        return self

    async def __aexit__(self, *exc):
        if self.ws:
            await self.ws.close()

    async def open_call(self):
        """Ask the operator to start talking."""
        await self.ws.send(json.dumps({"clientContent": {
            "turns": [{"role": "user",
                       "parts": [{"text": OPENING.get(self.lang, OPENING["en"])}]}],
            "turnComplete": True}}))

    async def send_audio(self, pcm16):
        """Your microphone, as raw 16 kHz PCM."""
        await self.ws.send(json.dumps({"realtimeInput": {"mediaChunks": [
            {"mimeType": f"audio/pcm;rate={config.INPUT_HZ}",
             "data": base64.b64encode(pcm16).decode()}]}}))

    async def events(self):
        """Yields ('audio', bytes) | ('interrupted', None) | ('tool', info)."""
        async for raw in self.ws:
            message = json.loads(raw)

            if "toolCall" in message:
                replies = []
                for call in message["toolCall"].get("functionCalls", []):
                    name, args = call["name"], call.get("args", {})
                    if name == "end_call":
                        self.ended = True
                    result = await self.run_tool(name, args)
                    replies.append({"id": call["id"], "name": name,
                                    "response": result})
                    yield ("tool", (name, args, result))
                await self.ws.send(json.dumps(
                    {"toolResponse": {"functionResponses": replies}}))
                continue

            content = message.get("serverContent", {})
            if content.get("interrupted"):
                yield ("interrupted", None)
            for part in content.get("modelTurn", {}).get("parts", []):
                if "inlineData" in part:
                    yield ("audio", base64.b64decode(part["inlineData"]["data"]))
            if content.get("turnComplete") and self.ended:
                return
