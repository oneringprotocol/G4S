"""Mileage & excess use: periods, per day summaries and background loading.

Modes: daily = the last 7 days, weekly = the last 4 weeks (Monday to Sunday),
monthly = this month and the 2 before it, custom = any span of up to 31 days.
Every mode stays inside the data window: this month and the 2 months before it.

Days inside the loaded GPS window come straight from the loaded analysis.
Older days (Total Secure only) are fetched in the background a week at a time,
and each finished day's summary is kept in data/cache/mileage/, so a period is
slow only the first time it is opened. A summary is worked out again when the
vehicle's maintenance records or the analysis rules change.
"""
import hashlib
import json
import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone

from . import config, roads
from .analysis import VehicleAnalysis
from .geo import UAE, day_label

log = logging.getLogger("g4s.mileage")

RULES_VERSION = "1"            # bump when a change to the analysis changes km or events
CUSTOM_MAX_DAYS = 30           # custom periods: to minus from, at most 30 days
BLOCK_DAYS = 7                 # older days are analysed a week at a time (with a day either side)
_DIR = config.CACHE / "mileage"
_mem = {}                      # (vehicle, day) -> (signature, summary or None)
_queue, _queued, _lock = [], set(), threading.Lock()
_worker = None


# ---------- periods ----------
def today():
    return datetime.now(UAE).date()


def window():
    """First and last date of the data window: the 1st of the month 2 months back, and today (UAE)."""
    t = today()
    m = t.month - 2
    first = date(t.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)
    return first, t


def span(mode, frm=None, to=None):
    """(first day, last day) for a mode, inside the data window. ValueError for a bad custom span."""
    lo, t = window()
    if mode == "daily":
        a, b = t - timedelta(days=6), t
    elif mode == "weekly":
        a, b = t - timedelta(days=t.weekday() + 21), t
    elif mode == "monthly":
        a, b = lo, t
    elif mode == "custom":
        try:
            a, b = date.fromisoformat(frm or ""), date.fromisoformat(to or "")
        except ValueError:
            raise ValueError("Choose a from date and a to date.")
        if a > b:
            raise ValueError("The from date is after the to date.")
        if (b - a).days > CUSTOM_MAX_DAYS:
            raise ValueError("Choose dates no more than %d days apart." % CUSTOM_MAX_DAYS)
        if a < lo or b > t:
            raise ValueError("Choose dates from %s to %s." % (day_label(lo.isoformat()), day_label(t.isoformat())))
    else:
        raise ValueError("Unknown period.")
    return max(a, lo), b


def period_of(day, mode):
    """(key, label) of the bar a day belongs to."""
    d = date.fromisoformat(day)
    if mode == "weekly":
        m = d - timedelta(days=d.weekday())
        return m.isoformat(), "Week of " + day_label(m.isoformat())
    if mode == "monthly":
        return d.strftime("%Y-%m"), d.strftime("%B %Y")
    return day, day_label(day)


def days_between(a, b):
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


# ---------- one vehicle day ----------
def summarize(d):
    """What the mileage view needs from an analysed day."""
    k = d["kpi"]
    return {"km": k["km"], "planned": k["km_planned"], "unplanned": k["km_unplanned"], "other": k["km_other"],
            "label": d["label"], "runs": [r for r in d["runs"] if r["kind"] == "unplanned"],
            "speeding": d["speeding"], "outside": d["outside"]}


def _sig(recs):
    return hashlib.sha1((RULES_VERSION + json.dumps(recs, sort_keys=True)).encode()).hexdigest()[:16]


def _file(vno, day):
    return _DIR / ("%s_%s.json" % (vno, day))


def cached(vno, day, recs):
    """(True, summary or None) when known for these records, else (False, None)."""
    sig = _sig(recs)
    hit = _mem.get((vno, day))
    if hit and hit[0] == sig:
        return True, hit[1]
    f = _file(vno, day)
    if f.exists():
        try:
            data = json.loads(f.read_text())
            if data.get("sig") == sig:
                _mem[(vno, day)] = (sig, data["summary"])
                return True, data["summary"]
        except (OSError, ValueError):
            pass
    return False, None


def _store(vno, day, recs, summary):
    sig = _sig(recs)
    _mem[(vno, day)] = (sig, summary)
    # only finished days, and only once the highway data is in (it changes the stops outside geofences)
    if day < today().isoformat() and roads.version > 0:
        _DIR.mkdir(parents=True, exist_ok=True)
        tmp = _file(vno, day).with_suffix(".tmp")
        tmp.write_text(json.dumps({"sig": sig, "summary": summary}, separators=(",", ":")))
        os.replace(tmp, _file(vno, day))


# ---------- background loading of older days ----------
def request(st, items):
    """Queue (vehicle, day) pairs that are not cached yet; a single worker fetches them."""
    global _worker
    with _lock:
        for it in items:
            if it not in _queued:
                _queued.add(it)
                _queue.append(it)
        if _queue and (_worker is None or not _worker.is_alive()):
            _worker = threading.Thread(target=_work, args=(st,), name="mileage", daemon=True)
            _worker.start()


def _work(st):
    while True:
        with _lock:
            if not _queue:
                return
            vno = _queue[0][0]
            days = sorted(d for v, d in _queue if v == vno)[:BLOCK_DAYS]
            # one block: consecutive days of one vehicle, at most a week
            block = [days[0]]
            for d in days[1:]:
                if date.fromisoformat(d) - date.fromisoformat(block[-1]) == timedelta(days=1):
                    block.append(d)
                else:
                    break
        try:
            _load_block(st, vno, block)
        except Exception as e:   # provider down: leave the days unknown, the page asks again later
            log.warning("Mileage: could not load %s %s to %s: %s", vno, block[0], block[-1], e)
            with _lock:
                for d in block:
                    _queue.remove((vno, d))
                    _queued.discard((vno, d))
            return
        with _lock:
            for d in block:
                _queue.remove((vno, d))
                _queued.discard((vno, d))


def _load_block(st, vno, block):
    d0 = datetime.strptime(block[0], "%Y-%m-%d").replace(tzinfo=UAE)
    d1 = datetime.strptime(block[-1], "%Y-%m-%d").replace(tzinfo=UAE)
    end = min(d1 + timedelta(days=2), datetime.now(timezone.utc))
    pts = st.source.positions(vno, (d0 - timedelta(days=1)).astimezone(timezone.utc), end)
    recs = st.recs.get(vno, [])
    a = VehicleAnalysis(st.vehicles[vno], st.sites, pts, recs) if pts else None
    for day in block:
        _store(vno, day, recs, summarize(a.day(day)) if a and day in a.days else None)


def pending():
    with _lock:
        return len(_queue)
