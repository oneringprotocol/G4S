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
| Passwords | Only the admin changes passwords: **Set password** on the Accounts page, for any approved account or the admin account itself. The user is signed out everywhere (the admin keeps the current session). There is no self service reset; the sign in page tells users to ask the admin. |
| Vehicle access | The admin sees every vehicle. Other accounts see only their assigned vehicles, in every view and API. With none assigned they see a "no vehicles assigned yet" note. With the Total Secure source the admin can also assign any platform device outside the plan (marked "Fleet tab only" on the Accounts page); an account with only such devices sees just the Fleet tab. |

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
| GPS | `sheets/Route_*.xlsx` (tracker "Route" report, UTC), or the Total Secure API (see below) | actual positions, speed, ignition, odometer |
| Plan names to sites | `data/plan_aliases.json` | group names such as "UTICO" mapped to directory sites |
| Directory fixes | `data/site_overrides.json` | README section 6 fixes |
| Maintenance records | `data/records.json` | replacement days (currently empty) |

With the xlsx source, to add GPS for another vehicle drop another `Route_<vehicle>_*.xlsx` in `sheets/` and restart. It is picked up automatically, and the vehicle dropdown enables it.

## GPS provider integration (Total Secure)

All GPS goes through `app/sources/base.py` (`GpsSource.devices()`, `GpsSource.positions(vehicle, start, end)`), so the analysis and UI do not know where points come from. Two sources exist, picked by `G4S_GPS_SOURCE`:

| `G4S_GPS_SOURCE` | Reads | Module |
|---|---|---|
| `xlsx` (default) | `sheets/Route_*.xlsx` exports | `app/sources/xlsx_source.py` |
| `totalsecure` | Total Secure platform API, `GET /api/reports/route` | `app/sources/totalsecure_source.py` |

The platform runs Traccar; its API reference is in `total secure api/openapi.yaml`. The xlsx export is the same Route report saved as a file, so both sources give identical points (checked on vehicle 15590, 11 to 17 Oct: same 91,116 points, same analysis). The API gives speed in knots; the app converts to km/h.

### Set up

1. Make an API token. Run this in your own terminal, not in a shared one or a chat:
   ```sh
   python3 -m app.totalsecure token
   ```
   It asks for the platform email and password, keeps them only in memory, signs out again, and saves the token to `data/secrets/totalsecure_token.json`. The token is never shown.
2. Put `G4S_GPS_SOURCE=totalsecure` in `.env`.
3. Check it: `python3 -m app.totalsecure check` lists the plan vehicles next to the platform device each one matched (the device name starts with the fleet number, e.g. `15590 - DF - SHJ/Rak`).
4. Restart the app.

Other commands: `python3 -m app.totalsecure status` (when the token was made, when it expires, next renewal) and `python3 -m app.totalsecure rotate` (renew now).

Settings (`.env`):

| Setting | Default | Meaning |
|---|---|---|
| `G4S_TS_URL` | `https://tracking.totalsecureme.com/api` | platform API address |
| `G4S_TS_DAYS` | 7 | load today plus this many UAE days before it |
| `G4S_TS_FROM`, `G4S_TS_TO` | empty | a fixed span of UAE days instead (`YYYY-MM-DD`, both included) |

Data loads on the first page view after a start (today plus `G4S_TS_DAYS` days). Any other date in the Date picker (previous month and this month, up to today in UAE time) is fetched when picked: that date plus one day either side, so runs over midnight and trips after midnight are complete, then analysed and kept in memory (last 40 dates; Refresh clears them). `GET /api/vehicles/{v}/days/{day}` refuses dates outside that range, so nobody can make the app pull older history. Estimated tracks in GPS gaps use the median speed of the data loaded with the date, so a date opened this way can differ from the same date inside the loaded week by seconds to about a minute in estimated times; stop counts and GPS measured km are the same. To get newer GPS, any signed in user can press **↻ Refresh** in the header (`POST /api/refresh`): it fetches again (with the xlsx source it re-reads `sheets/`), redoes the analysis and reloads the page on the same vehicle and day. Its tooltip shows when the data was loaded. A chip next to the page title shows the source: green **● Live Feed** for Total Secure, grey **Spreadsheet** for the xlsx export (hover for the load time). Pages keep showing the earlier data until the new data is ready; if the provider fails, the earlier data stays and the page says why. Refreshes closer than 30 s apart reuse the data just loaded, which spares the provider. Finished days come from the cache, so a refresh fetches only the current day.

### Security

- The app keeps only the token, never the password. Make it from a read-only platform account if Total Secure offers one; `token` warns when the account can change data.
- The token lives only in `data/secrets/totalsecure_token.json`: git ignored, file readable only by the account running the app (600, folder 700). It is never printed, logged, shown on a page, put in a URL or in an error message, and it is not in `.env`, so editing settings never puts it on screen. A `G4S_TS_TOKEN=` line found in `.env` (older setups) is moved into that file on start, removed from `.env`, and renewed at once.
- It is sent only in the `Authorization` header over https. Plain http is refused except to localhost, and redirects are refused so the token cannot be forwarded to another host.
- Every request has a 30 s timeout and up to 2 retries on network errors or 5xx answers.
- Finished days are cached in `data/cache/totalsecure/` (git ignored, readable only by the account running the app). Today is fetched again on each load.
- If the token is wrong, expired or the platform is down, pages show "GPS provider unavailable" with the reason, and the next request tries again. The app never falls back to old xlsx data silently.

### Token renewal (every 30 days, automatic)

The app renews the token itself; nobody needs to sign in again.

- Every 6 hours a background thread checks the token. When it is 30 days old it asks the platform for a new one valid for 45 days (`POST /api/session/token`, authorised by the current token), proves the new one works with a real request, saves it, and only then switches. Requests in flight keep using the old one, which stays valid, so a renewal never interrupts the app.
- If a renewal fails (platform down, network), nothing changes and it tries again 6 hours later. The 15 days between renewal (day 30) and expiry (day 45) leave about 60 tries.
- If fewer than 7 days are left, the admin sees **● Live Feed · access expires in N days** in amber next to the page title, and the server log says why renewal fails. `python3 -m app.totalsecure token` fixes it.
- The command line and the app share the token file under a lock, so a manual `rotate` and an automatic renewal never clash, and the app picks up a token renewed by the command line without a restart.
- After switching, the app revokes the old token (`POST /api/session/token/revoke`). **The platform runs Traccar 6.5, which has no revoke** (it answers 404; revoke arrived in 6.6), so on 6.5 old tokens stay valid until they expire, at most 45 days. Revoking starts working by itself once the platform is upgraded.

Limits that only Total Secure can lift: on Traccar 6.5 a token cannot be cancelled, and any valid token can create new ones. Ask them to (1) upgrade to Traccar 6.6 or later, so renewal also revokes, and (2) give the app its own read only account, so that disabling that one account cuts off every token it ever had without touching anyone's login.

### Fleet tab

`GET /api/fleet` returns every enabled platform device with its latest position (`/api/devices` and `/api/positions`, two calls, cached 30 s; Refresh starts a new cache). Only the fields the page shows are sent: fleet number, name, type, status, last update, position, speed (km/h), heading, engine state. The tracker IMEI, SIM phone number and contact fields never leave the server. The admin gets every device; other accounts only their assigned ones. With the xlsx source there is no Fleet tab and the endpoint answers 404.

### Adding more Total Secure data

`app/totalsecure.py` holds the client (auth, https, retries, safe errors) and is shared by every feed. Driver behaviour reports (for example `/reports/events`, `/drivers`) get their own module calling `Client.get()`, next to the GPS source, without touching it. The live WebSocket feed needs a session cookie rather than the token; `GET /api/session?token=...` returns one.

## Layout

```
app/
  main.py          API + static files     /api/meta  /api/sites  /api/vehicles/{v}/days/{day}  /api/mileage  /api/refresh  /api/fleet
  config.py        paths, analysis rules, Total Secure settings
  totalsecure.py   Total Secure API client, token store and 30 day renewal; `python3 -m app.totalsecure token|status|rotate|check`
  plan.py          Sheet1 + Geofence Directory parser
  gapfill.py       fills GPS gaps with an estimated track before the analysis runs
  analysis.py      stops, runs, trip matching, stop status, km, outside stops, speeding, idling, replay events
  roads.py         road type at short stops: highway, highway exit, highway roundabout (UAE road data from OpenStreetMap, cached 30 days)
  routes.py        planned route lines and estimated gap paths (OSRM road geometry, cached; straight lines offline)
  sources/         GPS sources: xlsx_source.py (exports), totalsecure_source.py (API)
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
- **Stops outside geofences** are stops of 2 min or more away from every site and the accommodation. A stop under 3 min (`HIGHWAY_STOP_MAX_S`) is left out when it is on a highway or a highway exit, or on a roundabout with a highway or exit within 300 m. That is traffic, not a chosen stop:
  - "Highway" means an OpenStreetMap motorway or trunk road, and "exit" means a motorway or trunk link, each within 30 m of the stop.
  - `app/roads.py` downloads every motorway, trunk road, exit and roundabout in the UAE from OpenStreetMap (Overpass API) in the background on start. The download takes about 4 min and is kept in `data/cache/highways.json` (about 7 MB) for 30 days.
  - Until the road data is ready, or with no network, nothing is left out. The day results are worked out again once it loads, and a failed download retries every 10 min.
- **Out of window** means the bus stopped at the site, but more than 30 min outside the planned time or on a different run.
- **Trip matching:**
  - A run matches a planned trip when its departure is within ±150 min of the plan time.
  - When several runs fit, the one that stopped at the trip group's sites wins.
  - A run already matched to another trip can only also cover this trip (chained) if it stopped at this trip's sites.
- **Accommodation moves** are runs that stay within 1.5 km of home. They are grey, not unplanned.
- **Planned route lines** visit the sites nearest first, because the plan lists who to serve, not the order.
