"""G4S fleet route audit, web app.

Run:  python3 -m uvicorn app.main:app --port 8000   (from the project folder)
Open: http://localhost:8000
"""
import json
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from urllib.parse import quote

from . import auth, config
from .analysis import VehicleAnalysis
from .geo import UAE, day_label
from .plan import load_plan
from .routes import planned_line
from .totalsecure import ProviderError

log = logging.getLogger("g4s")
app = FastAPI(title="G4S fleet route audit")
app.add_middleware(GZipMiddleware, minimum_size=2000)
auth.init()

# Open without signing in. Everything else needs an approved account; /admin needs the admin.
PUBLIC = ("/login", "/signup", "/setup", "/auth/", "/vendor/", "/app.css", "/auth.js")


@app.middleware("http")
async def gate(request: Request, call_next):
    path = request.url.path
    # CSRF: browsers only send this custom header from our own pages
    if request.method not in ("GET", "HEAD") and request.headers.get("x-g4s") != "1":
        return JSONResponse({"detail": "Request refused."}, 403)
    if path.startswith(PUBLIC):
        return await call_next(request)
    user = auth.session_user(request.cookies.get(auth.COOKIE))
    is_api = path.startswith("/api/") or path.startswith("/admin/api/")
    if not user:
        if is_api:
            return JSONResponse({"detail": "Sign in to continue."}, 401)
        nxt = path + ("?" + request.url.query if request.url.query else "")
        return RedirectResponse("/login?next=" + quote(nxt, safe=""), 303)
    if path.startswith("/admin") and user["role"] != "admin":
        return JSONResponse({"detail": "Admin only."}, 403) if is_api else RedirectResponse("/", 303)
    request.state.user = user
    return await call_next(request)


def _allowed(request):
    """None = every vehicle (admin); otherwise the vehicle numbers this account may see."""
    return auth.vehicles_for(request.state.user)


def _can_see(request, vno):
    allowed = _allowed(request)
    return allowed is None or vno in allowed


_ts = None


def _ts_client():
    """One Total Secure client for the app; its token renews itself in the background."""
    global _ts
    if _ts is None:
        from .totalsecure import Client, TokenStore, start_rotation
        _ts = Client(config.TS_URL, TokenStore())
        start_rotation(_ts)
    return _ts


if config.GPS_SOURCE == "totalsecure":
    try:
        _ts_client()   # start token renewal with the app, not on the first page view
    except ProviderError as e:
        log.warning("GPS provider: %s", e)


def _source():
    if config.GPS_SOURCE == "xlsx":
        from .sources.xlsx_source import XlsxRouteSource
        return XlsxRouteSource(config.SHEETS, config.CACHE)
    if config.GPS_SOURCE == "totalsecure":
        from .sources.totalsecure_source import TotalSecureSource, window
        return TotalSecureSource(_ts_client(), config.CACHE, *window())
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
            if not pts:
                continue
            self.analysis[vno] = VehicleAnalysis(veh, self.sites, pts, recs.get(vno, []))
        self.recs = recs
        self.extra = OrderedDict()   # (vehicle, date) -> analysis fetched on demand, None when no GPS
        self.extra_lock = threading.Lock()
        self.loaded_at = time.time()

    def analysis_for(self, vno, day):
        """The analysis holding `day`: the loaded window, or (Total Secure) that date fetched now
        with a day either side, so runs over midnight and trips after midnight come out the same."""
        a = self.analysis.get(vno)
        if a and day in a.days:
            return a
        lo, hi = calendar_range()
        if not (self.source.on_demand and vno in self.devices and vno in self.vehicles and lo <= day <= hi):
            return None
        key = (vno, day)
        with self.extra_lock:
            if key not in self.extra:
                d0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UAE)
                end = min(d0 + timedelta(days=2), datetime.now(timezone.utc))
                pts = self.source.positions(vno, (d0 - timedelta(days=1)).astimezone(timezone.utc), end)
                a = VehicleAnalysis(self.vehicles[vno], self.sites, pts, self.recs.get(vno, [])) if pts else None
                self.extra[key] = a if a and day in a.days else None
                while len(self.extra) > ON_DEMAND_KEEP:
                    self.extra.popitem(last=False)
            self.extra.move_to_end(key)
            return self.extra[key]


ON_DEMAND_KEEP = 40   # dates fetched on demand kept in memory; Refresh clears them


def calendar_range():
    """First and last date the date picker offers: the previous month and this month, up to today (UAE)."""
    today = datetime.now(UAE).date()
    first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    return first.isoformat(), today.isoformat()


REFRESH_MIN_S = 30   # spare the GPS provider: at most one refresh per 30 s
_state = None
_lock = threading.Lock()


def state() -> State:
    # built on first use; when the GPS provider fails nothing is kept, so the next request tries again
    global _state
    if _state is None:
        with _lock:
            if _state is None:
                _state = State()
    return _state


@app.exception_handler(ProviderError)
def provider_down(request, e):
    log.warning("GPS provider: %s", e)
    return JSONResponse({"detail": "GPS provider unavailable: %s" % e}, 503)


@app.get("/api/meta")
def meta(request: Request):
    st = state()
    out = []
    for vno, v in st.vehicles.items():
        if not _can_see(request, vno):
            continue
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
    token_warn = None   # admin only: days left when automatic renewal has been failing
    if request.state.user["role"] == "admin" and _ts is not None:
        from .totalsecure import WARN_DAYS
        left = _ts.store.days_left()
        if left is not None and left <= WARN_DAYS:
            token_warn = max(0, int(left))
    lo, hi = calendar_range()
    return {"vehicles": out, "source": st.source.name, "loaded_at": int(st.loaded_at), "token_warn_days": token_warn,
            "calendar": {"from": lo, "to": hi, "on_demand": st.source.on_demand},
            "fleet": hasattr(st.source, "fleet"),
            "rules": {k: getattr(config, k) for k in (
                "STOP_SPEED_KMH", "STOP_MIN_S", "GEOFENCE_M", "ACCOMMODATION_M", "OUTSIDE_STOP_MIN_S",
                "SPEED_LIMIT_KMH", "IDLE_MIN_S", "MATCH_WINDOW_MIN", "ON_TIME_MIN")}}


@app.post("/api/refresh")
def refresh():
    """Reload GPS (provider API or xlsx) and redo the analysis. Pages keep the old data
    until the new data is ready; if loading fails the old data stays."""
    global _state
    with _lock:
        if _state is None or time.time() - _state.loaded_at >= REFRESH_MIN_S:
            _state = State()
        return {"loaded_at": int(_state.loaded_at)}


@app.get("/api/fleet")
def fleet(request: Request):
    """All Total Secure devices at their latest position; other accounts see their assigned ones."""
    st = state()
    if not hasattr(st.source, "fleet"):
        raise HTTPException(404, "The Fleet view needs the Total Secure source.")
    allowed = _allowed(request)
    rows = [dict(r, in_plan=r["vehicle"] in st.vehicles, has_gps=r["vehicle"] in st.analysis)
            for r in st.source.fleet() if allowed is None or r["vehicle"] in allowed]
    return {"devices": rows, "at": int(time.time())}


def _assignable(st):
    """Vehicles the admin can give an account: the plan, plus every platform device."""
    out = [{"vehicle": vno, "branch": v.branch, "driver": v.driver, "has_gps": vno in st.analysis, "in_plan": True}
           for vno, v in sorted(st.vehicles.items())]
    if hasattr(st.source, "fleet"):
        seen = set(st.vehicles)
        for r in sorted(st.source.fleet(), key=lambda r: r["vehicle"]):
            if r["vehicle"] not in seen:
                seen.add(r["vehicle"])
                out.append({"vehicle": r["vehicle"], "branch": r["category"] or "device", "driver": "",
                            "has_gps": True, "in_plan": False})
    return out


@app.get("/api/sites")
def sites():
    return [{"id": s.id, "label": s.label, "lat": s.lat, "lon": s.lon,
             "accommodation": s.accommodation, "radius": s.radius} for s in state().sites.sites]


@app.get("/api/vehicles/{vno}/days/{day}")
def vehicle_day(vno: str, day: str, request: Request):
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(404, "Not a date: %s" % day)
    a = state().analysis_for(vno, day) if _can_see(request, vno) else None
    if not a:
        raise HTTPException(404, "No GPS for vehicle %s on %s." % (vno, day_label(day)))
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
def mileage(request: Request, vehicle: str = "all", emirate: str = "all", mode: str = "daily"):
    st = state()
    picked = [vno for vno, a in st.analysis.items()
              if _can_see(request, vno) and (vehicle in ("all", vno)) and (emirate == "all" or emirate in st.vehicles[vno].emirates)]
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


# ---------- accounts ----------
def _err(e: auth.AuthError):
    return JSONResponse({"detail": str(e)}, e.code)


def _set_session(resp, token):
    resp.set_cookie(auth.COOKIE, token, max_age=config.SESSION_DAYS * 86400, httponly=True,
                    samesite="lax", secure=config.BASE_URL.startswith("https"), path="/")


@app.post("/auth/login")
def do_login(request: Request, body: dict = Body(...)):
    try:
        token, u = auth.login(body.get("email"), body.get("password"), request.client.host if request.client else "")
    except auth.AuthError as e:
        return _err(e)
    resp = JSONResponse({"ok": True, "role": u["role"]})
    _set_session(resp, token)
    return resp


@app.post("/auth/signup")
def do_signup(body: dict = Body(...)):
    try:
        auth.signup(body.get("email"), body.get("password"), body.get("name"), body.get("company"), body.get("phone"))
    except auth.AuthError as e:
        return _err(e)
    return {"ok": True}


@app.get("/auth/setup-needed")
def setup_needed():
    return {"needed": not auth.admin_exists(), "email": config.ADMIN_EMAIL}


@app.post("/auth/setup")
def do_setup(request: Request, body: dict = Body(...)):
    try:
        auth.create_admin(body.get("password"), body.get("code"))
        token, _ = auth.login(config.ADMIN_EMAIL, body.get("password"), request.client.host if request.client else "")
    except auth.AuthError as e:
        return _err(e)
    resp = JSONResponse({"ok": True})
    _set_session(resp, token)
    return resp


@app.post("/auth/logout")
def do_logout(request: Request):
    auth.logout(request.cookies.get(auth.COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.get("/api/me")
def me(request: Request):
    u = request.state.user
    allowed = _allowed(request)
    return {"email": u["email"], "name": u["name"], "role": u["role"],
            "vehicles": "all" if allowed is None else sorted(allowed)}


@app.get("/admin/api/users")
def admin_users():
    return {"users": auth.list_users(), "vehicles": _assignable(state()), "admin_email": config.ADMIN_EMAIL}


@app.post("/admin/api/users/{uid}/decision")
def admin_decide(uid: int, body: dict = Body(...)):
    try:
        return auth.public(auth.decide(uid, body.get("approve") is True))
    except auth.AuthError as e:
        return _err(e)


@app.post("/admin/api/users/{uid}/vehicles")
def admin_vehicles(uid: int, body: dict = Body(...)):
    known = {v["vehicle"] for v in _assignable(state())}
    vs = [str(v) for v in body.get("vehicles", []) if str(v) in known]
    try:
        auth.set_vehicles(uid, vs)
    except auth.AuthError as e:
        return _err(e)
    return {"ok": True, "vehicles": sorted(vs)}


@app.post("/admin/api/users/{uid}/password")
def admin_password(uid: int, request: Request, body: dict = Body(...)):
    try:
        auth.set_password(uid, body.get("password"), keep_token=request.cookies.get(auth.COOKIE))
    except auth.AuthError as e:
        return _err(e)
    return {"ok": True}


@app.post("/admin/api/users/{uid}/delete")
def admin_delete(uid: int):
    try:
        auth.delete_user(uid)
    except auth.AuthError as e:
        return _err(e)
    return {"ok": True}


def _page(name):
    return FileResponse(config.WEB / name, headers={"Cache-Control": "no-store"})


@app.get("/login")
def login_page():
    return _page("login.html")


@app.get("/signup")
def signup_page():
    return _page("signup.html")


@app.get("/setup")
def setup_page():
    return _page("setup.html") if not auth.admin_exists() else RedirectResponse("/login", 303)


@app.get("/admin")
def admin_page():
    return _page("admin.html")


@app.get("/")
def index():
    return _page("index.html")


app.mount("/", StaticFiles(directory=config.WEB), name="web")
