# G4S route audit · web app

This is the web version of the fleet route audit. It follows `G4S_product_DESIGN_SYSTEM_1.md` and the rules in `G4S_product_README.md` section 4.

## Run

```bash
./run.sh                 # installs fastapi, uvicorn, openpyxl, then serves http://localhost:8000
G4S_TEST_EMAIL=... G4S_TEST_PASSWORD=... python3 tests/shots.py http://localhost:8000 tests/out   # headless walk-through (Brave or Chrome)
```

The first start parses the GPS export, which takes about 8 s, and caches it in `data/cache/`. Later starts take about 1 s.

## Accounts

Every page and API needs a signed-in, approved account.

| Step | What happens |
|---|---|
| First start | The server log prints a **setup code** (also in `data/setup_code.txt`). Open `/setup`, enter the code and choose the admin password. The admin email is fixed to `oneringprotocol@gmail.com` (`G4S_ADMIN_EMAIL`). The page works only once. |
| Create account | `/signup` (linked from the sign in page): full name, company, email, optional phone, password. The account starts as **waiting for approval** and cannot sign in. |
| Admin email | The admin gets an email with the details and a link to `/admin?review=<id>`. |
| Approve / reject | On `/admin` the admin ticks the vehicles the account may view, then approves or rejects. An approved user gets an email. **Remove access** signs the user out immediately. |
| Vehicle access | The admin sees every vehicle. Other accounts see only their assigned vehicles, in every view and API. With none assigned they see a "no vehicles assigned yet" note. |

Security details:
- Passwords are salted PBKDF2 SHA256 hashes (600,000 rounds), at least 10 characters with letters and numbers or symbols.
- Sessions are random tokens in an HttpOnly, SameSite=Lax cookie that lasts 7 days. Only their hash is stored.
- Every POST needs the `X-G4S` header, which blocks cross-site form posts.
- Sign in locks for 15 min after 5 failed attempts.
- Data lives in `data/app.db` (SQLite, git ignored).

**Email sending.** Set these before `./run.sh`:

```bash
export G4S_SMTP_HOST=smtp.gmail.com G4S_SMTP_PORT=465
export G4S_SMTP_USER=sender@gmail.com G4S_SMTP_PASS='<Google app password>'
export G4S_BASE_URL=https://audit.example.com      # used in the links inside emails
```

Without SMTP settings, emails are saved to `data/outbox/*.eml` and the server log says so. Approval still works from `/admin`.

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
  gapfill.py       fills GPS gaps with an estimated track before the analysis runs
  analysis.py      stops, runs, trip matching, stop status, km, outside stops, speeding, idling, replay events
  routes.py        planned route lines and estimated gap paths (OSRM road geometry, cached; straight lines offline)
  sources/         GPS sources (xlsx now, provider later)
web/               index.html, app.css, app.js, vendor/leaflet
data/              aliases, overrides, records, cache/
tests/shots.py     Playwright check: no page errors, no banned wording, no horizontal scroll at phone width
```

## Analysis notes

- **Km** comes from the tracker odometer, because it keeps counting while the GPS fix is lost. Straight-line distance is used only when the odometer is missing or not credible.
- **GPS gaps are filled, not shown.** A gap is 10 min or more with no position. `app/gapfill.py` rebuilds it before the analysis runs, so there is no "No GPS data" status anywhere:
  - If the bus did not move, it stays where it was.
  - If the bus moved, the planned sites due in that time that the GPS never shows are placed on the OSRM road path from the last fix to the next, in the order that drives the least. A site is kept only while the path still fits the odometer km: road km × 0.7 must be at most the odometer km, because the odometer reads about 15% under OSRM here. The bus waits at the start, drives at its usual speed and stops 3 min (`EST_DWELL_S`) at each site.
  - The analysis then treats these as ordinary stops. Estimated stop times show with **≈**, and the estimated path is a dotted orange line on the map.
  - Km is unchanged, because it still comes from the odometer.
- **Out of window** means the bus stopped at the site, but more than 30 min outside the planned time or on a different run.
- **Trip matching:**
  - A run matches a planned trip when its departure is within ±150 min of the plan time.
  - When several runs fit, the one that stopped at the trip group's sites wins.
  - A run already matched to another trip can only also cover this trip (chained) if it stopped at this trip's sites.
- **Accommodation moves** are runs that stay within 1.5 km of home. They are grey, not unplanned.
- **Planned route lines** visit the sites nearest first, because the plan lists who to serve, not the order.
