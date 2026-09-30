#!/usr/bin/env bash
# Start the Agent Organizer server (run inside WSL), then open http://localhost:8765
cd "$(dirname "$0")" || exit 1
exec python3 server.py
