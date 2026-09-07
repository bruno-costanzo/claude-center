"""Configuration, read from the environment or a local .env file."""
import os
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def _load_env():
    """Load .env into os.environ without overriding real env vars."""
    f = RAIZ / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env()


def _int(name, default):
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
LANG = (os.environ.get("CC_LANG") or "en").strip().lower()
VOICE = os.environ.get("CC_VOICE") or "Callirrhoe"
PORT = _int("CC_PORT", 8765)
COOLDOWN = _int("CC_COOLDOWN", 90)
MAX_CALL = _int("CC_MAX_CALL", 300)
ONLY_NEW = os.environ.get("CC_ONLY_NEW") == "1"

# The Gemini model that speaks and listens in real time.
MODEL = os.environ.get("CC_MODEL", "models/gemini-2.5-flash-native-audio-latest")

# Audio formats the Live API requires. Change these and you must change the
# browser client too — they are two halves of the same contract.
INPUT_HZ = 16000
OUTPUT_HZ = 24000

# Panes we never call about. The pane running Claude Center adds itself here,
# otherwise the operator would call you about its own session and your spoken
# answer would land in it as a prompt.
IGNORED_PANES = {
    p.strip() for p in
    [os.environ.get("HERDR_PANE_ID", ""), *os.environ.get("CC_IGNORE", "").split(",")]
    if p.strip()
}

# How often to poll Herdr for stuck agents, in seconds.
POLL_SECONDS = 5


def missing():
    """Human-readable list of what still needs configuring."""
    problems = []
    if not GEMINI_API_KEY:
        problems.append(
            "GEMINI_API_KEY is not set. Get a free key at "
            "https://aistudio.google.com/apikey and put it in .env")
    if LANG not in ("en", "es"):
        problems.append(f"CC_LANG must be 'en' or 'es', got {LANG!r}")
    return problems
