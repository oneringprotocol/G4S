"""Paths and analysis rules (README section 4)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEETS = Path(os.environ.get("G4S_SHEETS", ROOT / "sheets"))
DATA = ROOT / "data"
CACHE = DATA / "cache"
WEB = ROOT / "web"

PLAN_XLSX = SHEETS / "Sample G4S Vehicle Schedule.xlsx"
PLAN_TAB = "Sheet1"
GEOFENCE_TAB = "Geofence Directory"

# GPS source: "xlsx" reads sheets/Route_*.xlsx. A provider API source plugs in here later.
GPS_SOURCE = os.environ.get("G4S_GPS_SOURCE", "xlsx")

UTC_OFFSET_H = 4                 # GPS timestamps are UTC; UAE time is +4 h
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
GAP_S = 10 * 60                  # no GPS for 10 min or more is a gap
NIGHT_FROM, NIGHT_TO = 22, 4     # departures from 22:00 to 03:59 are at night
SHORT_HOP_KM = 3
YARD_RADIUS_M = 1500             # runs that stay this close to home are accommodation moves
