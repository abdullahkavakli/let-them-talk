#!/usr/bin/env bash
# Start the server (macOS, Linux or WSL), then open http://localhost:8765
cd "$(dirname "$0")" || exit 1
exec python3 server.py
