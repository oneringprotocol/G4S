"""G4S fleet route audit, web app.

Run:  python3 -m uvicorn app.main:app --port 8000   (from the project folder)
Open: http://localhost:8000
"""
import json
from datetime import datetime, timedelta
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .analysis import VehicleAnalysis
from .geo import day_label
from .plan import load_plan
from .routes import planned_line

app = FastAPI(title="G4S fleet route audit")
app.add_middleware(GZipMiddleware, minimum_size=2000)


def _source():
    if config.GPS_SOURCE == "xlsx":
        from .sources.xlsx_source import XlsxRouteSource
        return XlsxRouteSource(config.SHEETS, config.CACHE)
    raise RuntimeError("Unknown GPS source: %s" % config.GPS_SOURCE)


class State:
    def __init__(self):
        self.vehicles, self.sites = load_plan()
        self.source = _source()
        self.devices = {d.vehicle: d for d in self.source.devices()}
        recs = json.loads((config.DATA / "records.json").read_text()).get("vehicles", {})
        self.analysis = {}
        for vno, dev in self.devices.items():
            veh = self.vehicles.get(vno)
            if not veh:
                continue
            pts = self.source.positions(vno, dev.start, dev.end)
            self.analysis[vno] = VehicleAnalysis(veh, self.sites, pts, recs.get(vno, []))


@lru_cache(maxsize=1)
def state() -> State:
    return State()


def _analysis(vno):
    a = state().analysis.get(vno)
    if not a:
        raise HTTPException(404, "No GPS data for vehicle %s" % vno)
    return a


@app.get("/api/meta")
def meta():
    st = state()
    out = []
    for vno, v in st.vehicles.items():
        a = st.analysis.get(vno)
        dev = st.devices.get(vno)
        home = st.sites.by_id.get(v.home)
        item = {"vehicle": vno, "driver": v.driver, "type": v.type, "type_abbr": v.type_abbr,
                "branch": v.branch, "emirates": v.emirates,
                "home": home.label if home else None,
                "trips": len(v.trips), "has_gps": bool(a)}
        if a:
            days = a.days
            pct = [a.day(d)["kpi"] for d in days]
            val = sum(k["validated"] for k in pct)
            wd = sum(k["with_data"] for k in pct)
            item.update({"days": [{"day": d, "label": day_label(d)} for d in days],
                         "pct": round(100 * val / wd) if wd else None,
                         "gps_from": day_label(days[0]), "gps_to": day_label(days[-1]),
                         "device": dev.name})
        out.append(item)
    out.sort(key=lambda x: (not x["has_gps"], x["vehicle"]))
    return {"vehicles": out, "source": st.source.name,
            "rules": {k: getattr(config, k) for k in (
                "STOP_SPEED_KMH", "STOP_MIN_S", "GEOFENCE_M", "ACCOMMODATION_M", "OUTSIDE_STOP_MIN_S",
                "SPEED_LIMIT_KMH", "IDLE_MIN_S", "MATCH_WINDOW_MIN", "ON_TIME_MIN")}}


@app.get("/api/sites")
def sites():
    return [{"id": s.id, "label": s.label, "lat": s.lat, "lon": s.lon,
             "accommodation": s.accommodation, "radius": s.radius} for s in state().sites.sites]


@app.get("/api/vehicles/{vno}/days/{day}")
def vehicle_day(vno: str, day: str):
    a = _analysis(vno)
    if day not in a.days:
        raise HTTPException(404, "No GPS for %s on %s" % (vno, day))
    d = dict(a.day(day))
    v, S = a.v, state().sites
    home = S.by_id.get(v.home)
    d["vehicle"] = {"vehicle": v.vehicle, "driver": v.driver, "type": v.type, "type_abbr": v.type_abbr,
                    "branch": v.branch, "home": home.label if home else None,
                    "home_ll": [home.lat, home.lon] if home else None, "home_r": home.radius if home else None}
    lines = {}
    for tr in v.trips:
        lines[tr.n] = planned_line(home, [S.by_id[i] for i in tr.sites])
    d["planned_lines"] = lines
    d["plan_sites"] = sorted({i for tr in v.trips for i in tr.sites})
    return d


def _period(day, mode):
    d = datetime.strptime(day, "%Y-%m-%d")
    if mode == "weekly":
        start = d - timedelta(days=d.weekday())      # weeks start on Monday
        return start.strftime("%Y-%m-%d"), "Week of " + day_label(start.strftime("%Y-%m-%d"))
    if mode == "monthly":
        return d.strftime("%Y-%m"), d.strftime("%B %Y")
    return day, day_label(day)


@app.get("/api/mileage")
def mileage(vehicle: str = "all", emirate: str = "all", mode: str = "daily"):
    st = state()
    picked = [vno for vno, a in st.analysis.items()
              if (vehicle in ("all", vno)) and (emirate == "all" or emirate in st.vehicles[vno].emirates)]
    bars, unplanned, speeding, outside = {}, [], [], []
    totals = {"km": 0, "planned": 0, "unplanned": 0, "other": 0, "unplanned_trips": 0,
              "speeding": 0, "outside": 0, "outside_min": 0}
    for vno in picked:
        a = st.analysis[vno]
        for day in a.days:
            d = a.day(day)
            k = d["kpi"]
            key, label = _period(day, mode)
            b = bars.setdefault(key, {"key": key, "label": label, "planned": 0, "unplanned": 0,
                                      "other": 0, "unplanned_trips": 0, "unplanned_min": 0})
            b["planned"] += k["km_planned"]
            b["unplanned"] += k["km_unplanned"]
            b["other"] += k["km_other"]
            totals["km"] += k["km"]
            totals["planned"] += k["km_planned"]
            totals["unplanned"] += k["km_unplanned"]
            totals["other"] += k["km_other"]
            for r in d["runs"]:
                if r["kind"] == "unplanned":
                    b["unplanned_trips"] += 1
                    b["unplanned_min"] += (r["t1"] - r["t0"]) / 60
                    unplanned.append(dict(r, vehicle=vno, day=day, day_label=d["label"]))
            for s in d["speeding"]:
                speeding.append(dict(s, vehicle=vno, day=day, day_label=d["label"]))
            for o in d["outside"]:
                outside.append(dict(o, vehicle=vno, day=day, day_label=d["label"],
                                    key="%s_%s_%d" % (vno, day, o["t0"])))
    totals["unplanned_trips"] = len(unplanned)
    totals["speeding"] = len(speeding)
    totals["outside"] = len(outside)
    totals["outside_min"] = round(sum(o["dur_min"] for o in outside))
    for k in ("km", "planned", "unplanned", "other"):
        totals[k] = round(totals[k], 1)
    out_bars = []
    for b in sorted(bars.values(), key=lambda x: x["key"]):
        for k in ("planned", "unplanned", "other"):
            b[k] = round(b[k], 1)
        b["unplanned_min"] = round(b["unplanned_min"])
        out_bars.append(b)
    return {"vehicles": picked, "bars": out_bars, "totals": totals,
            "unplanned": unplanned, "speeding": speeding, "outside": outside}


@app.get("/")
def index():
    return FileResponse(config.WEB / "index.html")


app.mount("/", StaticFiles(directory=config.WEB), name="web")
