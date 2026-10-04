#!/usr/bin/env bash
# Thin wrapper: model-setup is implemented once, in Python (scripts/model_setup.py), for every OS.
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "model-setup needs Python 3 (standard library only, nothing to pip install)."
  echo "Install it:  macOS: brew install python   Debian/Ubuntu: sudo apt install python3   or https://www.python.org/downloads/"
  exit 1
fi
exec "$PY" "$(cd "$(dirname "$0")" && pwd)/../model_setup.py" "$@"
