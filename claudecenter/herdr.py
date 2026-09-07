"""Thin wrapper over the Herdr CLI.

Herdr (https://herdr.dev) is a terminal workspace manager for AI coding
agents. It exposes a local socket API, and everything Claude Center needs
about your agents comes through these four commands.
"""
import json
import os
import shutil
import subprocess

BIN = (os.environ.get("HERDR_BIN_PATH")
       or shutil.which("herdr")
       or os.path.expanduser("~/.local/bin/herdr"))

# Agent states that mean the agent cannot move without you.
# "blocked" is a permission modal: it cannot be answered by voice, so the
# operator skips those and you resolve them in Herdr itself.
NEEDS_YOU = ("blocked", "idle", "done")
ANSWERABLE = ("idle", "done")


def available():
    return bool(BIN) and os.path.exists(BIN)


def _run(*args, timeout=15):
    try:
        out = subprocess.run([BIN, *args], capture_output=True, text=True,
                             timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return out if out.returncode == 0 else None


def _json(*args):
    out = _run(*args)
    if not out:
        return None
    try:
        return json.loads(out.stdout).get("result")
    except json.JSONDecodeError:
        return None


def agents():
    """Every agent Herdr knows about, with its state and working directory."""
    res = _json("agent", "list")
    return res.get("agents", []) if res else []


def read_pane(pane, lines=200):
    """The agent's terminal output — this is the operator's context."""
    out = _run("agent", "read", pane, "--source", "recent-unwrapped",
               "--lines", str(lines))
    if not out:
        return ""
    return "\n".join(l.rstrip() for l in out.stdout.splitlines() if l.strip())


def send_prompt(pane, text):
    """Submit a prompt to an agent. Returns True if it was accepted."""
    return _json("agent", "prompt", pane, text) is not None


def focus(pane):
    return _json("agent", "focus", pane) is not None


def title(agent):
    return (agent.get("terminal_title_stripped")
            or agent.get("cwd", "").rstrip("/").split("/")[-1]
            or "agent")


def project(agent):
    return os.path.basename(agent.get("cwd", "").rstrip("/")) or "your folder"
