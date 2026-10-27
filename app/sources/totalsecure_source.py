"""GPS from the Total Secure platform (/api/reports/route).

The Route_*.xlsx export is this same report saved as a file, so the points match it:
fixTime (UTC), latitude, longitude, valid, and the ignition and odometer attributes.
The API gives speed in knots; the export showed km/h.

Fetched one UAE day per request per vehicle. Finished days are cached in
data/cache/totalsecure/ (git ignored, owner only); the current day is fetched again
on every load.
"""
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from .. import config
from .base import DeviceInfo, GpsPoint, GpsSource

log = logging.getLogger("g4s.totalsecure")

KNOTS_KMH = 1.852
DAY = timedelta(days=1)
SETTLE = timedelta(hours=1)   # late points still arrive for a while after a day ends
WORKERS = 4
FLEET_TTL_S = 30              # the fleet view asks the platform at most every 30 s


def window(now=None):
    """UTC start and end of the UAE days to load: G4S_TS_FROM..G4S_TS_TO if set,
    else today plus the G4S_TS_DAYS days before it."""
    off = timedelta(hours=config.UTC_OFFSET_H)
    now = now or datetime.now(timezone.utc)
    if config.TS_FROM:
        day = lambda s: datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc) - off
        return day(config.TS_FROM), min(day(config.TS_TO or config.TS_FROM) + DAY, now)
    local = now + off
    today = local.replace(hour=0, minute=0, second=0, microsecond=0) - off
    return today - config.TS_DAYS * DAY, now


def _ts(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def _row(p):
    a = p.get("attributes") or {}
    ign, odo = a.get("ignition"), a.get("odometer")
    return [
        _ts(p["fixTime"]),
        round(float(p["latitude"]), 6),
        round(float(p["longitude"]), 6),
        round(float(p.get("speed") or 0) * KNOTS_KMH, 1),
        1 if p.get("valid") else 0,
        -1 if ign is None else int(bool(ign)),
        float(odo) if odo is not None else None,
    ]


class TotalSecureSource(GpsSource):
    name = "totalsecure"
    on_demand = True

    def __init__(self, client, cache: Path, start: datetime, end: datetime):
        self.client = client
        self.start, self.end = start, end
        self.cache = Path(cache) / "totalsecure"
        self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._ids = {}   # fleet number -> (device id, device name)
        self._fleet, self._fleet_at, self._fleet_lock = None, 0, threading.Lock()
        for d in client.devices():
            name = str(d.get("name") or "")
            vehicle = name.split(" ")[0]
            if d.get("disabled") or not vehicle:
                continue
            if vehicle in self._ids:
                log.warning("Two Total Secure devices for vehicle %s; using %s", vehicle, self._ids[vehicle][1])
                continue
            self._ids[vehicle] = (d["id"], name)

    def fleet(self):
        """Every device on the platform with its latest position, for the Fleet tab. Only the
        fields the page shows: no tracker IMEI, phone or contact details."""
        with self._fleet_lock:
            if self._fleet is None or time.time() - self._fleet_at >= FLEET_TTL_S:
                pos = {p.get("deviceId"): p for p in self.client.get("/positions")}
                rows = []
                for d in self.client.devices():
                    if d.get("disabled"):
                        continue
                    name = str(d.get("name") or "")
                    p = pos.get(d.get("id")) or {}
                    a = p.get("attributes") or {}
                    rows.append({
                        "id": d.get("id"),
                        "vehicle": name.split(" ")[0] or str(d.get("id")),
                        "name": name,
                        "category": d.get("category"),
                        "status": d.get("status") if d.get("status") in ("online", "offline") else "unknown",
                        "last": _ts(d["lastUpdate"]) if d.get("lastUpdate") else None,
                        "lat": p.get("latitude"), "lon": p.get("longitude"),
                        "speed": round(float(p.get("speed") or 0) * KNOTS_KMH, 1) if p else None,
                        "course": p.get("course"),
                        "fix": _ts(p["fixTime"]) if p.get("fixTime") else None,
                        "ignition": a.get("ignition"),
                    })
                self._fleet, self._fleet_at = rows, time.time()
            return self._fleet

    def devices(self) -> List[DeviceInfo]:
        return [DeviceInfo(v, n, self.start, self.end) for v, (_, n) in sorted(self._ids.items())]

    def _chunk(self, device_id, a, b):
        cf = self.cache / ("%s_%s.json" % (device_id, a.strftime("%Y%m%dT%H%M")))
        final = b - a == DAY and b + SETTLE <= datetime.now(timezone.utc)
        if final and cf.exists():
            return json.loads(cf.read_text())
        lo, hi = a.timestamp(), b.timestamp()   # the API includes both ends; keep [a, b) so days never overlap
        rows = [r for r in map(_row, self.client.route(device_id, a, b)) if lo <= r[0] < hi]
        rows.sort(key=lambda r: r[0])
        if final:
            tmp = cf.with_suffix(".tmp")
            tmp.write_text(json.dumps(rows, separators=(",", ":")))
            os.chmod(tmp, 0o600)
            os.replace(tmp, cf)
        return rows

    def positions(self, vehicle, start, end) -> List[GpsPoint]:
        dev = self._ids.get(str(vehicle))
        if not dev:
            return []
        spans, a = [], start
        while a < end:
            spans.append((a, min(a + DAY, end)))
            a += DAY
        with ThreadPoolExecutor(WORKERS) as ex:
            chunks = list(ex.map(lambda s: self._chunk(dev[0], *s), spans))
        # trackers sometimes send two points with the same time; both are kept, as in the export
        return [GpsPoint(p[0], p[1], p[2], p[3], bool(p[4]), None if p[5] < 0 else bool(p[5]), p[6])
                for rows in chunks for p in rows]
