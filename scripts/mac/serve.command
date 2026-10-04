#!/usr/bin/env bash
# Double-click launcher for macOS (opens in Terminal). Runs the shared Linux/macOS script.
exec "$(cd "$(dirname "$0")" && pwd)/../unix/serve.sh"
