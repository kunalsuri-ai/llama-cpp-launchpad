#!/usr/bin/env bash
# Double-click launcher for macOS (opens in Terminal). Runs the shared Linux/macOS model-setup script.
exec "$(cd "$(dirname "$0")" && pwd)/../unix/model-setup.sh" "$@"
