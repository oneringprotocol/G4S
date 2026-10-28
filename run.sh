#!/bin/sh
# Start the G4S route audit web app on http://localhost:3000
# (scripts/service.sh keeps it running in the background and restarts it if it stops)
cd "$(dirname "$0")"
PORT="${PORT:-3000}"
if curl -s -o /dev/null -m 3 "http://127.0.0.1:$PORT/login.html"; then
    echo "The app is already running at http://localhost:$PORT"
    exit 0
fi
python3 -c "import fastapi, uvicorn, openpyxl" 2>/dev/null || python3 -m pip install --user -q fastapi uvicorn openpyxl
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
