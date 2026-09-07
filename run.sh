#!/usr/bin/env bash
# Start Claude Center. Run ./setup.sh first.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Run ./setup.sh first."; exit 1; }
exec .venv/bin/python -m claudecenter
