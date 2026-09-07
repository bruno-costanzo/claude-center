#!/usr/bin/env bash
# One-time setup for Claude Center.
set -euo pipefail
cd "$(dirname "$0")"

echo "→ Creating the virtual environment"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "→ Created .env — open it and paste your GEMINI_API_KEY"
  echo "  Get a free key at https://aistudio.google.com/apikey"
else
  echo "→ .env already exists, leaving it alone"
fi

if ! command -v herdr >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/herdr" ]; then
  echo
  echo "! Herdr is not installed. Claude Center reads your agents through it."
  echo "  Install it from https://herdr.dev and run your agents inside it."
fi

echo
echo "Done. Start it with:  ./run.sh"
