#!/bin/sh
# Start the G4S route audit web app on http://localhost:8000
cd "$(dirname "$0")"
python3 -m pip install --user -q fastapi uvicorn openpyxl
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
