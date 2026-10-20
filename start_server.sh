#!/bin/bash
# Terminal 1 — run this first, then open Terminal 2 and 3 for the two clients.
# Leave this running for the whole demo; Ctrl+C stops the server.
cd "$(dirname "$0")"
python3 server.py
