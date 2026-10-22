# G4S product · Fleet route audit

An offline, single-file HTML report for G4S. It compares the **G4S route plan** with what the buses actually did according to their **GPS trackers**: planned stops validated, actual km, unplanned trips, idling, speeding and stops outside known sites.

The client opens one `.html` file in a browser. It needs no server and no internet, because the map tiles are embedded in the file.

Owner: Amr Rafat (Swvl) · Client: G4S UAE · Last build: 21 Oct 2026

---

## 1. Quick start (Claude Code in VS Code)

```bash
unzip G4S_product_source.zip -d g4s-product && cd g4s-product
pip install pandas numpy openpyxl pillow playwright
# Chromium for the tests (skip if already installed)
python3 -m playwright install chromium

# 1. Put the map tiles back (they are too big for the zip; they live inside the delivered reports)
python3 build/recover_tiles.py ~/Downloads/G4S_fleet_route_audit_ops_adjusted.html october/v2/hires/tiles_c.json
python3 build/recover_tiles.py ~/Downloads/G4S_fleet_route_audit_September.html  september/v2/hires/tiles_sep.json

# 2. Rebuild the combined September + October report
python3 build/merge_tiles.py
python3 build/assemble_both.py          # -> reports/G4S_fleet_route_audit_Sep_Oct.html

# 3. Test it (no page errors, no banned wording, month switch works)
python3 tests/check_report.py reports/G4S_fleet_route_audit_Sep_Oct.html
```

The processed data (`*/v2/out/all_data*.json`) is included. To make UI or wording changes you only need to edit `page2.html` and run the assemble step. Rerun the full pipeline (section 5) only when new GPS exports arrive.

---

## 2. Deliverables (in `~/Downloads`)

| File | Period | Notes |
|---|---|---|
| **G4S_fleet_route_audit_Sep_Oct.html** | Sep + Oct 2026 | **Current client version.** It has a Month dropdown in the header and 2 tabs (no Unplanned trips). It is adjusted for maintenance records. Size 27.6 MB |
| G4S_fleet_route_audit_October.html | 4 to 10 Oct | Compact (19.0 MB), 2 tabs |
| G4S_fleet_route_audit_ops_adjusted.html | 4 to 10 Oct | Full quality, 3 tabs, 30.6 MB |
| G4S_fleet_route_audit.html | 4 to 10 Oct | Not adjusted for maintenance records |
| G4S_fleet_route_audit_September.html | 6 to 30 Sep | 3 tabs, 29.3 MiB |
| *_no_unplanned.html | | Same as the matching file without the Unplanned trips tab |
| G4S_product_source.zip | | This kit |

**Browser:** the compact, September and combined files unpack their data with `DecompressionStream`. They need Chrome, Edge, Safari 16.4+ or Firefox 113+.

---

## 3. What the report shows

**Header:** vehicle, driver, type (DF = Dongfeng), branch, accommodation, GPS date range. The combined file also has a Month dropdown, which reloads the page with `?m=sep` or `?m=oct`. October is the default.

**Tab: Route check**
- A *Planned vs actual* / *▶ Replay* toggle, a Day dropdown and a Vehicle dropdown.
- **Tiles:**
  - planned stops validated;
  - actual km (GPS);
  - planned + unplanned trips;
  - stops outside geofences (click to see numbered purple pins and a fly-to list);
  - idling at accommodation over 10 min;
  - speeding over 100 km/h (click for a table of when, driver and where).
- The map shows the planned route (dashed) and the actual GPS route (orange). Geofences are drawn as 300 m circles.
- **Side panel:** total planned trips and stop visits for the day, plus a status per stop: Validated, Passed, Out of window or Not visited.
- **After hours:** planned and unplanned trips "at night".

**Tab: Mileage & excess use**
- Search by vehicle or by emirate (dropdowns), with navy totals.
- Planned (pastel green) and unplanned (pastel orange) stacked km bars by Daily / Weekly / Monthly.
- Unplanned trips table, speeding table and stops outside geofences. The stops table has a validation column per row, saved in the browser, and a CSV download.

**Tab: Unplanned trips** (removed from the client versions): a list of each unplanned departure with its map.

**Vehicles:**
- 15590 Sharjah / RAK
- 15993 Sharjah (Ajman accommodation)
- 65462 Dubai
- 73398 Abu Dhabi (Magenta)
- 48233 Dubai, September only (in the workshop from 18 Sep)

---

## 4. Rules

### Analysis rules
| Rule | Value |
|---|---|
| GPS timestamps | UTC in the export; **+4 h** is added (UAE time) |
| Stop | speed of 3 km/h or less for 30 s or more |
| Geofence radius | 300 m (accommodation 400 m) |
| Stop outside geofences | 2 min or more away from every known site |
| Parking | 20 min or more |
| Speeding | over 100 km/h |
| Run | accommodation to accommodation |
| Trip matching | GPS departure within ±150 min of the plan; one GPS run may cover several chained planned trips |
| Validated / Passed | Validated = stopped inside the geofence; Passed = drove through without stopping |
| Maintenance records (`ops.json`) | Trips run by a replacement vehicle are marked "Run by replacement" and taken out of the vehicle's plan. Drives to or from the workshop are not counted as unplanned. |

### Client wording (strict, the client sees this)
- **Never** show "Operations Sheet", "Ops Sheet" or "G4S Operations Sheet". Use "records" or "maintenance records". `opsword.py` (`scrub()`) enforces this, and no "Adjusted for ..." badge is shown.
- Say "accommodation", never "depot" or "Yard".
- Say "G4S route plan", never "Sheet 1".
- No hyphens or apostrophes in visible text. A `cleanText` MutationObserver strips them; use ▲/▼ for signs and "to" for ranges.
- No planned km anywhere; show actual km only.
- "Not confirmed" is shown as "Passed".
- "requested by the client or operations" is shown as "requested by the client".

### Map
- Only embedded tiles are used. Live OSM tiles are blocked (403) when the page is opened from `file://`.
- The map is framed to the window, with a zoom cap at the sharpest tile level.

---

## 5. Folder layout and pipeline

```
g4s-product/
├── README.md, CLAUDE.md
├── october/                 # 4 to 10 Oct 2026, run scripts from this folder
│   ├── geo.py, geo2.json, pack_patched.json, sheet1.txt   (first-report caches, 15590)
│   └── v2/
│       ├── config.py        # per-vehicle plan (from Sheet 1) + geofences
│       ├── geodir.json      # Geofence Directory (76 sites)
│       ├── ops.json         # maintenance / replacement records
│       ├── pack2.json       # cached OSRM routes + place names
│       ├── page2.html       # page template (HTML/CSS/JS, placeholders __DATA__ __IMGS__ __HIRES__)
│       ├── out/             # all_data_adj.json, all_data.json, all_imgs.json (processed data)
│       └── hires/           # tiles_c.json (recover with build/recover_tiles.py)
├── september/               # 6 to 30 Sep 2026, same layout, adds 48233 + jumpfilter.py
├── build/
│   ├── assemble_both.py     # combined Sep + Oct report  -> reports/
│   ├── merge_tiles.py       # union of both months' tiles, re-encoded WebP q20, images q50
│   ├── recomp.py            # re-encode a tile/image JSON at a WebP quality
│   ├── recover_tiles.py     # pull embedded tiles out of a delivered report
│   └── nounp.py             # strip the Unplanned trips tab from any built report
├── tests/check_report.py    # Playwright check of every tab / vehicle / day
└── reports/                 # build output
```

### Full pipeline (new GPS exports)
Run inside `october/` or `september/`:

```bash
python3 v2/extract.py "<GPS export>.xlsx"           # one sheet per vehicle -> v2/gps_<veh>.csv
# clean the GPS
python3 v2/fix_freeze.py v2/gps_<veh>.csv v2/clean_<veh>.csv     # October method (rebuilds frozen fixes)
cp v2/gps_<veh>.csv v2/clean_<veh>.csv && python3 v2/jumpfilter.py v2/clean_<veh>.csv   # September method (spike filter only; preferred)
# per vehicle
VNO=<veh> python3 v2/analyze_v.py                   # -> v2/out/analytics_<veh>.json
VNO=<veh> python3 v2/build_v.py                     # -> v2/out/page_<veh>.json
# all vehicles
python3 v2/combine.py                               # -> v2/out/all_data.json  (not adjusted)
ADJ=1 python3 v2/combine.py                         # -> v2/out/all_data_adj.json (maintenance-adjusted)
# single-month report
python3 v2/assemble_adj.py                          # October, adjusted   (assemble2.py = not adjusted)
python3 v2/assemble_sep.py                          # September
python3 v2/build_xlsx2.py                           # optional Excel stop audit
```

Then run `build/assemble_both.py` for the combined file, and `build/nounp.py in.html out.html` if you need a version without the Unplanned tab.

**Adding a vehicle or month:**
1. Add the vehicle to `VEH` in `v2/config.py` (driver, type, branch, home accommodation, planned sites from the Geofence Directory, groups and trip plan from Sheet 1).
2. Add it to `ORDER` in `combine.py` and `prep_requests.py`.
3. Add any maintenance records to `ops.json`.
4. New sites or areas may need OSRM routes and tiles: `prep_requests.py` writes `requests.json` / `hires_req.json`, which need fetching with network access.

### Size limits
- The device bridge cannot copy files over **30 MB** to the Mac, so keep client files under 30 MB.
- Size levers:
  - gzip+base64 the data (as `assemble_sep.py` / `assemble_both.py` do);
  - lower the tile WebP quality (`recomp.py`; q20 to q28 still reads well);
  - thin the GPS points in `combine.py`.

---

## 6. Data sources and known gaps

- **Plan:** *Sample G4S Vehicle Schedule.xlsx* → Sheet 1 (trips) + Geofence Directory (coordinates).
- **GPS:** tracker exports (one xlsx per vehicle or batch; the data starts at row 9).
- **September coverage:** exports seem capped at about 250k rows, so the start of the month is missing.

  | Vehicle | Days covered |
  |---|---|
  | 15590 | 11 to 30 Sep |
  | 15993 | 9 to 30 Sep |
  | 65462 | 6 to 29 Sep |
  | 73398 | 16 to 30 Sep |
  | 48233 | 6 to 30 Sep |

  Ask for exports split into smaller date ranges to cover 1 to 10 Sep.
- **Directory fixes:**
  - Jumeirah Saadiyat Island Resort: the directory value is a map-view link, so the GPS-derived point 24.5593, 54.4514 is used.
  - KC Ladies: missing from the directory, so 24.4031, 54.5752 is used.
  - Rosewood Hotel: listed twice, so 24.49974, 54.38758 is used.
- **No workshop geofences:**
  - The directory has no Abu Dhabi workshop. The only garage-like entry is World Auto International FZE in Sharjah.
  - The 15993 workshop was found from GPS (Dubai Investments Park).
  - Add workshop coordinates to `geodir.json` / `config.py` if the client provides them.
- 73398's "Total Workshop Days: 41" in the records does not match its dates; this is flagged and not used.

Project notes in Claude (project "G4S report"): `claude/G4S_product.md`, `claude/september_2026_route_audit.md`, `claude/fleet_route_audit_takeaways.md`.
