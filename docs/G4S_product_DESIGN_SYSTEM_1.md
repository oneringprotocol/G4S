# G4S product · Design system

The UI and UX rules for the G4S fleet route audit reports. All styling lives in one place: the `<style>` block of `september/v2/page2.html` (the master template; copy it to `october/v2/` after edits). The JavaScript in the same file draws the map, charts and tables.

---

## 1. Design principles

1. **The client reads it alone.** The report is opened by G4S without us in the room. Every number needs a label, a unit and a one-line meaning. Status words ("Validated", "Passed") are defined on screen in the side panel.
2. **Evidence first.** Every claim can be traced to the map. Tiles open tables, table rows open the map, and pins fly to the stop.
3. **Calm, not alarming.** Soft pastels, no red walls. Bad news is pale orange, good news is pale green. Strong red is kept for "Not visited" and "Not authorised" only.
4. **One question per screen.** *Route check* answers "did the bus do the plan today?". *Mileage & excess use* answers "how much driving was outside the plan, and where?"
5. **Neutral client wording.** No internal sources ("Operations Sheet"), no jargon ("depot", "Yard", "Sheet 1"), no hyphens or apostrophes, no planned km. See README section 4.
6. **Works offline, anywhere.** It is a single HTML file with embedded tiles and no external fonts or scripts. It works in light and dark mode and adapts down to tablet width.

---

## 2. Foundations

### 2.1 Color tokens (CSS custom properties on `:root`)

Always use tokens, never raw hex values in components. Every token has a dark-mode value. The dark set applies when `prefers-color-scheme: dark` or `data-theme="dark"`. The theme button cycles Auto / Light / Dark and remembers the choice (`localStorage g4s-theme`).

**Neutrals**

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f4f4f2` | `#121211` | page background |
| `--surface` | `#fcfcfb` | `#1a1a19` | cards, header, tables |
| `--surface-2` | `#f0efec` | `#242422` | table heads, hover, fact boxes |
| `--line` | `#e2e1dc` | `#33332f` | all borders and dividers (1 px) |
| `--ink` | `#0b0b0b` | `#f0efec` | primary text, selected states |
| `--ink-2` | `#52514e` | `#c3c2b7` | secondary text, labels |
| `--ink-3` | `#7a7974` | `#8f8e86` | captions, units, hints |
| `--navy` | `#1f3a6b` | `#9db8ea` | totals, "Total number of trips" headers, vehicle type badge |
| `--glass` | `rgba(252,252,251,.82)` | `rgba(26,26,25,.80)` | map legend and toasts (with 6 px blur) |

**Status (each status has a strong color, a background tint and an ink color for text on the tint)**

| Status | Strong | Background | Ink | Meaning in the report |
|---|---|---|---|---|
| good | `--good #0ca30c` | `--good-bg #e3f5e3` | `--good-ink #0a6b0a` | Validated, planned trip |
| warn | `--warn #fab219` | `--warn-bg #fdf1d6` | `--warn-ink #8a5a00` | Passed (drove through), timing |
| serious | `--serious #ec835a` | `--serious-bg #fde6dc` | `--serious-ink #9a3d17` | Out of window, check, maintenance return |
| crit | `--crit #d03b3b` | `--crit-bg #fbe1e1` | `--crit-ink #9b2323` | Not visited, unplanned, workshop day |
| muted | — | `--muted-bg #ecebf3` | `--muted-ink #4b4a63` | No data / gap |

**Positive / negative text (tile lines)**

| Token | Light | Use |
|---|---|---|
| `--good-txt` | `#3e9a62` (pale green) | a line that is good news |
| `--bad-txt` | `#d9803f` (pale orange) | a line that is bad news |
| `--pg-bg` / `--pg-ink` | `#d6f2df` / `#1d6b3b` | "planned" pill (pastel green) |
| `--po-bg` / `--po-ink` | `#fde0cb` / `#8a4313` | "unplanned" pill (pastel orange) |

**Charts (Mileage & excess use)**

| Token | Light | Use |
|---|---|---|
| `--x2-svc` | `#a9cdf5` pastel blue | km on planned trips; km buttons; focus ring |
| `--x2-unp` | `#f9c29a` pastel orange | unplanned km |
| `--x2-yard` | `#cfcfd6` grey | accommodation moves |
| `--x2-plan` | `#ef8f8f` | speeding tile border |

**Map**

| Token | Light | Use |
|---|---|---|
| `--plan1 … --plan9` | blue `#2a78d6`, violet `#6250d6`, green `#1baf7a`, amber `#eda100`, pink `#e87ba4`, green `#008300`, red `#e34948`, teal `#3a8fb7`, brown `#8a6d3b` | one color per planned trip group (dashed line) |
| `--act` | `#eb6834` orange | actual GPS route (solid line), clickable tile border |
| `--fence` / `--fence-fill` | `#1f9d55` / green 16% | planned geofence circle (300 m) |
| `--other-fill` | grey 10% | other directory sites |
| `--stop-fill` | `#f9c9a6` | actual stop dot |
| `--zone-line` / `--zone-fill` | `#8b6fd6` / violet 32% | stops outside geofences (numbered purple pins) |
| `--trail-svc` / `--trail-oth` | `#7fd394` / `#f5b183` | replay trail on a planned trip / off-plan |

**Rules:**
- Text on a tint always uses the matching `-ink` token, which meets WCAG AA contrast.
- Never use color alone: every status chip also has a word and an icon (✓ ↷ ⏱ ✕).
- Planned is always green; unplanned is always orange. This holds in tiles, pills, bars and replay trails.

### 2.2 Typography

- **Font:** `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`, so there are no web fonts and the file stays offline-safe.
- **Base:** 14 px with line-height 1.45.
- **Numbers:** always `font-variant-numeric: tabular-nums`, so columns and counters line up.

| Role | Size / weight | Where |
|---|---|---|
| Page title (`h1`) | 17 px / 650 | "Route audit · Vehicle 73398" |
| Tile value (Mileage tab) | 26 px / 700 | big numbers |
| KPI value (Route check) | 20 px / 700 | 5 tiles above the map |
| Panel total | 20 px / 800, navy | "Total planned trips today" |
| Card title (`h3`) | 15 px / 600 | section cards |
| Section label (`h2`) | 12.5 px / 650, uppercase, letter-spacing .05em, `--ink-3` | "PLANNED STOPS BY TRIP · SAT 10 OCT" |
| Body / table | 12.5 to 13 px | tables, captions |
| Chip / badge | 10.5 to 11.5 px / 600 to 700 | status pills |

### 2.3 Spacing, radius, elevation

- **Spacing scale:** 2 · 4 · 6 · 8 · 10 · 12 · 14 · 16 · 18 px. Page gutters are 16 to 18 px, and the gap between cards is 10 to 12 px.
- **Radius:**

  | Radius | Used for |
  |---|---|
  | 8 px | buttons, inputs, small controls |
  | 10 px | KPI tiles, trip cards, popups, dropdowns |
  | 12 px | cards, tiles, tables |
  | 14 px | map and side panel |
  | 999 px | chips, pills, segmented controls |

- **Elevation:** almost flat. Cards use a 1 px `--line` border.
  - Shadows are only for floating things: the map controls, legend, popups and toasts use `--shadow` (`0 6px 24px rgba(0,0,0,.10)`).
  - The map and side panel have a hairline `0 1px 3px` shadow.
- **Max width:** the Mileage tab content is centered at 1180 px. Route check is full-bleed so the map uses the window.

### 2.4 Iconography

The report uses Unicode glyphs only, with no icon font: ▶ play · ↗ "open / show on map" · ✓ validated · ↷ passed · ⏱ out of window · ✕ not visited · 🔧 maintenance · ▲ ▼ up/down versus a reference · ◐ theme.

Vehicle type is a 34 px navy square with the abbreviation, e.g. **DF** for Dongfeng. Use abbreviations, not pictures.

---

## 3. Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ Header: title · subtitle (driver · type · branch · accommodation ·   │
│         GPS date range)                 [Month ▾]  [◐ Auto]          │
│ Tabs:  Route check | Mileage & excess use                            │
├──────────────────────────────────────────────────────────────────────┤
│ Day bar: [Planned vs actual | ▶ Replay]  Day [Sat 10 Oct ▾]   source │
├───────────────────────────────────────────────┬──────────────────────┤
│ Vehicle [DF][73398 · Abu Dhabi · 81% ▾] driver│ Side panel (420 px)  │
│ [KPI][KPI][KPI][KPI][KPI]                     │ Totals (navy)        │
│ ┌───────────────── Map ──────────────────┐    │ Status legend table  │
│ │ +/−/⤢              Legend (glass)      │    │ Trip cards           │
│ │                                        │    │  stop rows + chips   │
│ └────────────────────────────────────────┘    │                      │
└───────────────────────────────────────────────┴──────────────────────┘
```

- Route check fills the viewport (`height: calc(100vh − 150px)`, min 520 px). The page never scrolls behind the map; only the side panel scrolls.
- **Below 980 px:**
  - the map stacks above the side panel (map 72vh);
  - KPI and tile grids drop to 2 columns;
  - the legend hides;
  - gutters are 16 px.
- Below 900 px the Mileage tiles drop to 2 columns.

---

## 4. Components

### Header
- **Title:** `Route audit · Vehicle <no>` on Route check, `Fleet route audit · Mileage & excess use` on the Mileage tab.
- **Subtitle:** one line of context: driver · type · branch · based at <accommodation> · GPS <from> to <to> vs G4S route plan.
- **Right side:** the Month dropdown (combined file only), then the theme button.

### Tabs
- These are text tabs with a 2 px underline in `--ink` on the active tab, and inactive tabs in `--ink-2`.
- The tab rail scrolls horizontally on small screens.
- *Route check · replay* exists as a hidden tab and is reached through the segmented toggle, not the tab rail.

### Segmented control (`.seg` / `.sbtn`)
- This is a pill group. The active segment is filled `--ink` with `--surface` text.
- It is used for *Planned vs actual / ▶ Replay* and for *Daily / Weekly / Monthly*.

### Dropdowns (`.dd select`, `#vsel`, `#daysel`, `#msel`)
- 13.5 to 14 px, weight 600 to 700, 10 px radius, room for the arrow on the right. Focus shows a 2 px pastel-blue outline.
- **Vehicle dropdown:** each option reads `73398 · Abu Dhabi · 81% stops validated`, so the user sees the score before choosing. It sits next to the navy **DF** badge and the driver name.
- **Day dropdown:** days with maintenance get a suffix (`· 🔧 Maintenance · replaced by 26514`). The control gets a dashed red border on a workshop day, or a dashed orange border on the return day.
- **Mileage tab:** "Search by vehicle" and "Search by Emirate" dropdowns, with a small navy count pill (`.emcount`) for the number of vehicles.

### KPI tiles (Route check, `.kpi`)
- There are five tiles above the map: planned stops validated · actual km (GPS) · planned + unplanned trips · stops outside geofences · idling at accommodation over 10 min.
- Each tile has three parts: a value (20 px), a label, and a sub line in `--ink-3`.
- Clickable tiles show a pointer and a darker border on hover. The active tile gets a 2 px violet ring, for example while the purple pins are shown.

### Summary tiles (Mileage tab, `.tile`)
- The value is 26 px. Each piece of information sits on **its own line** (`.s.tl`).
  - Good lines are pale green (`.pos`), bad lines pale orange (`.neg`), links `--ink-2`.
  - Example: **483 km** / *463 km on planned trips* (green) / *11 km unplanned* (orange).
- A clickable tile (`.tile.click`) has an orange border and opens its table. The speeding tile has a coral border and opens the speeding table.

### Side panel (Route check)
1. **Totals block:** "Total planned trips today" and "Planned stop visits", each with a big navy number right-aligned.
2. **Status legend table:** STATUS · MEANING · STOPS. This defines every chip on screen, and the counts for the day sit on the right.
3. **Trip cards (`.trip`):** a dashed swatch in the trip color, `Trip n · Group name`, a validated count, and a meta line (`Plan 05:00 to 07:30 · Actual 04:46 to 07:16 (▼14 min) · 129.4 km`). Below that, one row per stop with time and status chip.
   - Clicking a card selects it (1 px ink ring) and frames that run on the map.
   - Clicking a stop row flies the map to that stop.
   - A trip run by a replacement is faded (opacity .75) and has a dashed grey chip "Run by replacement".

### Status chips (`.chip.st-*`)

| Chip | Class | Colors |
|---|---|---|
| ✓ Validated | `st-Validated` | good-bg / good-ink |
| ↷ Passed | `st-Passed` | warn-bg / warn-ink |
| ⏱ Out of window | `st-Out` | serious-bg / serious-ink |
| ✕ Not visited | `st-Not` | crit-bg / crit-ink |
| Parked, not on a trip | `st-Gap` | muted |
| Run by replacement / At the workshop | `st-Repl` | surface-2, dashed border |

**Trip badges** (`.badge`, uppercase 10.5 px) are used in the replay and the tables: Planned (green), Unplanned (red), Timing (amber), Check (orange), No data (muted).

**Pills:** planned trips are `.ahp` (pastel green) and unplanned trips are `.ahu` (pastel orange). The header for them, "Total number of trips", is navy.

### Map
- The map is a custom canvas map with embedded tiles: drag to pan, wheel or ± buttons to zoom, ⤢ to fit the day.
  - Zoom is capped at the sharpest embedded tile level, so it never shows blurry or blank tiles.
  - Panning is bounded to the area that has tiles.
- **Layers:**
  - Planned routes are 3 px dashed lines, one color per trip group.
  - The actual GPS route is a solid orange line with a light casing so it reads on any tile.
  - Geofences are green circles with a 16% fill; other directory sites are grey.
  - Actual stops are peach dots.
  - Stops outside geofences are numbered purple pins (22 px circle, white border).
- **Legend:** top right, glass with blur, one row per layer. It is hidden on small screens.
- **Popups:** click any stop or site to see the name, time, duration and status. There is a close ✕, and only one popup is open at a time.
- **Credit:** "© OpenStreetMap contributors" stays bottom right, always.

### Stops outside geofences panel (`.ozpanel`)
- Clicking the KPI tile opens a floating list over the map with a violet border, one row per stop: number · time · place · duration.
- Clicking a row flies to that pin and highlights it. ✕ closes the panel.

### Tables (`table`, `.x2t`)
- 12.5 px, tabular numbers, 1 px row lines, `--surface-2` header.
- The first column is left-aligned. Other columns are centered on the Mileage tab and right-aligned elsewhere. Cells are vertically centered.
- Long tables scroll inside a 620 px box with a **sticky header and sticky total row**.
- **km button (`.kmbtn`):** pastel-blue pill `53.6 km ▶`. Clicking it replays that trip on the Route check replay.
- **Comment column:** plain-language reason, for example "Left at 22:42, late at night with no planned trip due."
- **Type chips:**

  | Chip | Color |
  |---|---|
  | Unexplained / Late night | red tint |
  | Daytime | orange tint |
  | Short hop | grey |

### Client validation (stops outside geofences table)
- Each row has a dropdown and a free-text comment. The dropdown options are:
  - to validate
  - Approved, passenger pick-up / drop-off
  - Approved, client errand
  - Approved, fuel / rest break
  - Not authorised
  - Need more information
- The dropdown takes a color once chosen: green for Approved, red for Not authorised, amber for Need more information.
- Answers are saved in the viewer's browser (`localStorage g4s_oz_validation`). The header counts "n reviewed", and **Download CSV** exports the rows with answers to send back.
- **Show ↗** on each row opens the stop on the Route check map.

### Charts (Mileage & excess use)
- Hand-drawn SVG with stacked bars: planned (pastel blue / green) + unplanned (pastel orange). There are no red reference lines or planned km.
  - Bars have rounded tops (4 px).
  - In-bar labels are 12 px bold; side labels use `--ink-2`.
- Daily / Weekly / Monthly segmented control.
- **Hover tooltip (`.svgtip`):** period, km per layer, and for unplanned km the number of trips and time.
- **Legend:** small rounded squares under the chart.

### Replay (Route check ▶ Replay)
- **Control bar:**
  - **▶ Play**: the primary black button. Space bar toggles it.
  - **Clock**: 22 px tabular.
  - **Speed**: 60× · 180× · **360×** (default) · 900× · 1800×.
  - **Follow bus**: checkbox, on.
  - **Explain movement (one pop-up at a time)**: checkbox, on.
- **Scrubber:** a full-width slider. Under it, a colored band shows planned (green) and off-plan (orange) time, with hour ticks.
- **Narration card:** top left of the map, with a 4 px left border in the event color.
  - It shows a title, one or two sentences, a footer (time · km · speed) and a thin progress bar.
  - It cross-fades (.25 s) when the event changes.
- **Event list:** time · colored dot · title. Past events dim to 62%, and the current event gets a border. Click an event to jump there.
- **Toasts / callouts:** short glass cards that point to a place, with a soft ripple at the spot. The ripple and transitions are off when `prefers-reduced-motion` is set.

### Notes and banners
- **Maintenance note (`.opsnote`):** a full-width strip under the day bar on a workshop or return day.
  - Red tint means the vehicle is in the workshop; orange tint means it is back from the workshop.
  - Text example: "In the workshop (clutch issue, since 30 Sep), replaced by 25199."
- **Source note (`.opsrc`):** right end of the day bar, 11 px `--ink-3`, e.g. "Records: no maintenance or replacement this week".

---

## 5. UX patterns

### Navigation model
- **Month → Tab → Day → Vehicle.** Each filter is a dropdown in a fixed place, and changing one keeps the others when possible.
  - The **Month** dropdown reloads the file with `?m=sep` / `?m=oct`; October is the default.
  - The day list always shows only days that have GPS for that vehicle.
- The report **opens on Route check**, on the latest day, for the first vehicle. The client sees a map and a score straight away, not a table.

### Drill-down ("overview → evidence")
| From | Click | Goes to |
|---|---|---|
| KPI "stops outside geofences" | tile | purple pins + fly-to list on the map |
| Speeding tile | tile | speeding table (when, driver on roster, where, during which trip) |
| Mileage tile / bar | tile or bar | matching table below |
| km button in a table | `53.6 km ▶` | Route check replay of that trip |
| "Show ↗" / "Show on map ↗" | button | Route check map centered on that stop |
| Trip card / stop row | card or row | map frames the run / flies to the stop |

Every drill-down is one click, and the user can always go back by changing a dropdown.

### Explaining instead of accusing
- Every unplanned trip or out-of-geofence stop gets a plain **comment** and a **"During"** chip (which planned trip it was on, or "Not on a trip").
- Maintenance is explained, not punished:
  - trips run by replacements are taken out of the vehicle's plan;
  - workshop drives are not counted as unplanned;
  - the day is marked 🔧.
- The client can **validate** each stop and add a comment, so the report becomes a two-way review.

### Defining every term on screen
- The side panel status table defines Validated, Passed, Out of window and Not visited every time it is shown.
- Units always sit next to the number (km, min, km/h). Time ranges use "to" (`18:42 to 18:48`) and differences use ▲/▼ (`▼14 min`).
- Times are UAE local time (GPS UTC + 4 h). Dates are written `Sat 10 Oct`.

### Feedback and states
- **Hover:** a `--surface-2` background on rows, cards and clickable tiles.
- **Selected:** an ink ring (1 px border + 1 px shadow), or a violet ring for map-linked tiles.
- **Empty:** a short note, for example "No stops outside geofences in this selection."
- **Loading:** "Loading data…" while the packed data unpacks (about 1 s). On old browsers the message changes to the browser requirement.
- **Pending answers:** client validation drafts persist per browser. Nothing is sent anywhere; the CSV is the hand-off.

### Accessibility
- Color is never the only signal: chips carry words and icons, and lines are both dashed (planned) and solid (actual).
- Status text uses `-ink` tokens on tints, which is AA contrast in both themes. `forced-colors` mode adds chip borders.
- Tabs use `role="tab"` / `tablist`; dropdowns have `aria-label`; a 2 px focus outline is shown on dropdowns.
- `prefers-reduced-motion` turns off the ripple and the card transitions.
- Space plays or pauses the replay, except while typing in a field.

### Writing style (client-facing copy)
- Short, factual sentences in present tense: "Left at 22:42, late at night with no planned trip due."
- No hyphens or apostrophes. A `cleanText` observer strips stray ones at runtime; still, write without them.
- **Words to use / avoid:**

  | Use | Avoid |
  |---|---|
  | accommodation | depot, Yard |
  | G4S route plan | Sheet 1 |
  | records, maintenance records | Operations Sheet, Ops Sheet |
  | Passed | Not confirmed |
  | actual km | plan km (do not show) |
  | at night | after hours (as a label) |

---

## 6. Adding something new: checklist

- [ ] Uses existing tokens only, and looks right in light **and** dark (toggle ◐).
- [ ] Planned = green, unplanned = orange; status chips reuse `.chip.st-*` or `.badge.b-*`.
- [ ] Numbers are tabular, with units; each piece of information is on its own line in tiles.
- [ ] Anything summarized can be clicked through to the map.
- [ ] Every new term is defined on screen.
- [ ] Copy passes the wording rules. Add any new banned phrase to `opsword.py` / `ren()`.
- [ ] Works at 980 px and phone width (2-column grids, no horizontal page scroll).
- [ ] `python3 tests/check_report.py <report>` passes, and the file stays under 30 MB.
