# G4S route audit · web app

This is the web version of the fleet route audit. It follows `G4S_product_DESIGN_SYSTEM_1.md` and the rules in `G4S_product_README.md` section 4.

## Run

```bash
./run.sh                 # installs fastapi, uvicorn, openpyxl, then serves http://localhost:8000
python3 tests/shots.py http://localhost:8000 tests/out   # headless walk-through (Brave or Chrome)
```

The first start parses the GPS export, which takes about 8 s, and caches it in `data/cache/`. Later starts take about 1 s.

## Data in

| Input | Where | Used for |
|---|---|---|
| G4S route plan | `sheets/Sample G4S Vehicle Schedule.xlsx`, tab `Sheet1` | vehicles, drivers, trips, times, staff counts |
| Geofence Directory | same file, tab `Geofence Directory` | site names and coordinates (300 m, accommodation 400 m) |
| GPS | `sheets/Route_*.xlsx` (tracker "Route" report, UTC) | actual positions, speed, ignition, odometer |
| Plan names to sites | `data/plan_aliases.json` | group names such as "UTICO" mapped to directory sites |
| Directory fixes | `data/site_overrides.json` | README section 6 fixes |
| Maintenance records | `data/records.json` | replacement days (currently empty) |

To add GPS for another vehicle, drop another `Route_<vehicle>_*.xlsx` in `sheets/` and restart. It is picked up automatically, and the vehicle dropdown enables it.

## GPS provider integration

All GPS goes through `app/sources/base.py` (`GpsSource.devices()`, `GpsSource.positions(vehicle, start, end)`). The xlsx reader is one implementation. To connect the provider:

1. Add `app/sources/<provider>_source.py` that returns the same `GpsPoint` list. The export looks like a Traccar route report, so a Traccar source would call `/api/devices` and `/api/reports/route`.
2. Select it in `app/main.py::_source()` and set `G4S_GPS_SOURCE=<provider>`.

Nothing in the analysis or UI changes.

## Layout

```
app/
  main.py          API + static files     /api/meta  /api/sites  /api/vehicles/{v}/days/{day}  /api/mileage
  config.py        paths and analysis rules
  plan.py          Sheet1 + Geofence Directory parser
  analysis.py      stops, runs, trip matching, stop status, km, outside stops, speeding, idling, replay events
  routes.py        planned route lines (OSRM road geometry, cached; straight lines offline)
  sources/         GPS sources (xlsx now, provider later)
web/               index.html, app.css, app.js, vendor/leaflet
data/              aliases, overrides, records, cache/
tests/shots.py     Playwright check: no page errors, no banned wording, no horizontal scroll at phone width
```

## Analysis notes

- **Km** comes from the tracker odometer, because it keeps counting while the GPS fix is lost. Straight-line distance is used only when the odometer is missing or not credible.
- **GPS gaps.** Planned stops that fall inside a gap of 10 min or more while the bus moved are shown as **No GPS data** (muted), not Not visited. They are left out of the validated percentage.
- **Out of window** means the bus stopped at the site, but more than 30 min outside the planned time or on a different run.
- **Trip matching:**
  - A run matches a planned trip when its departure is within ±150 min of the plan time.
  - When several runs fit, the one that stopped at the trip group's sites wins.
  - A run already matched to another trip can only also cover this trip (chained) if it stopped at this trip's sites.
- **Accommodation moves** are runs that stay within 1.5 km of home. They are grey, not unplanned.
- **Planned route lines** visit the sites nearest first, because the plan lists who to serve, not the order.
