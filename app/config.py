"""Paths and analysis rules (README section 4)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Settings can live in a .env file next to run.sh (KEY=value per line, git ignored).
# Real environment variables win over the file.
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))
SHEETS = Path(os.environ.get("G4S_SHEETS", ROOT / "sheets"))
DATA = ROOT / "data"
CACHE = DATA / "cache"
WEB = ROOT / "web"

PLAN_XLSX = SHEETS / "Sample G4S Vehicle Schedule.xlsx"
PLAN_TAB = "Sheet1"
GEOFENCE_TAB = "Geofence Directory"

# GPS source: "xlsx" reads sheets/Route_*.xlsx, "totalsecure" calls the Total Secure API.
GPS_SOURCE = os.environ.get("G4S_GPS_SOURCE", "xlsx")
# Total Secure. The token is made with `python3 -m app.totalsecure token`, kept in TS_TOKEN_FILE
# (owner only, git ignored) and renewed by the app every 30 days. A G4S_TS_TOKEN left in .env is
# moved into that file on start and removed from .env.
TS_URL = os.environ.get("G4S_TS_URL", "https://tracking.totalsecureme.com/api")
TS_TOKEN = os.environ.get("G4S_TS_TOKEN", "")
TS_TOKEN_FILE = DATA / "secrets" / "totalsecure_token.json"
TS_DAYS = int(os.environ.get("G4S_TS_DAYS", "7"))   # load today plus this many UAE days before it ...
TS_FROM = os.environ.get("G4S_TS_FROM", "")         # ... or a fixed span of UAE days, YYYY-MM-DD,
TS_TO = os.environ.get("G4S_TS_TO", "")             # both ends included

# Accounts and email. SMTP settings come from the environment (see docs/APP.md);
# without them, emails are written to data/outbox/ instead of being sent.
ADMIN_EMAIL = os.environ.get("G4S_ADMIN_EMAIL", "oneringprotocol@gmail.com").lower()
BASE_URL = os.environ.get("G4S_BASE_URL", "http://localhost:8000").rstrip("/")
DB_FILE = DATA / "app.db"
OUTBOX = DATA / "outbox"
SESSION_DAYS = 7
PASSWORD_MIN = 10
SMTP_HOST = os.environ.get("G4S_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("G4S_SMTP_PORT", "465"))
SMTP_USER = os.environ.get("G4S_SMTP_USER", "")
SMTP_PASS = os.environ.get("G4S_SMTP_PASS", "")
SMTP_FROM = os.environ.get("G4S_SMTP_FROM", SMTP_USER)

UTC_OFFSET_H = 4                # GPS timestamps are UTC; UAE time is +4 h
STOP_SPEED_KMH = 3               # a stop is speed <= 3 km/h ...
STOP_MIN_S = 30                  # ... for 30 s or more
GEOFENCE_M = 300
ACCOMMODATION_M = 400
OUTSIDE_STOP_MIN_S = 120         # stop outside every known site for 2 min or more
PARKING_MIN_S = 20 * 60
SPEED_LIMIT_KMH = 100
IDLE_MIN_S = 10 * 60             # idling at accommodation over 10 min
MATCH_WINDOW_MIN = 150           # GPS departure within +-150 min of the plan
ON_TIME_MIN = 30                 # a stop counts as in window up to 30 min either side
GAP_S = 10 * 60                  # no GPS for 10 min or more is a gap; gaps are filled with an estimated track
EST_DWELL_S = 3 * 60             # estimated stop at each planned site inside a gap
NIGHT_FROM, NIGHT_TO = 22, 4     # departures from 22:00 to 03:59 are at night
SHORT_HOP_KM = 3
YARD_RADIUS_M = 1500             # runs that stay this close to home are accommodation moves
