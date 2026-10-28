"""Road type at a stop: highway, highway exit or highway roundabout.

Short stops on these roads are traffic (queues, merging, roundabout entries),
not a driver choosing to stop, so the analysis leaves them out of the stops
outside geofences.

Road data is every motorway, trunk road, their exits (links) and every
roundabout in the UAE from OpenStreetMap (public Overpass API). The download
takes a few minutes, so it runs in the background on start and is kept in
data/cache/highways.json for 30 days. Until it is ready road_kind() returns
None, nothing is left out, and `version` changes once it loads so cached
day results are worked out again.
"""
import json
import math
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from collections import defaultdict

from . import config

_FILE = config.CACHE / "highways.json"
_SERVERS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter")
_BBOX = "22.5,51.4,26.2,56.5"   # the UAE
_MAX_AGE_S = 30 * 86400
_RETRY_S = 10 * 60
_CELL = 0.005                   # grid cell in degrees, about 500 m

_MAIN = ("motorway", "trunk")
_LINK = ("motorway_link", "trunk_link")

version = 0                     # bumped each time road data loads
_index = None                   # (segments, grid) once loaded
_started = False
_lock = threading.Lock()


def _download():
    q = ('[out:json][timeout:600][bbox:%s];(way[highway~"^(motorway|trunk)(_link)?$"];'
         'way[highway][junction~"^(roundabout|circular)$"];);out tags geom;' % _BBOX)
    body = urllib.parse.urlencode({"data": q})
    for url in _SERVERS:
        # curl, because the macOS system Python ships an old LibreSSL that fails the TLS handshake
        out = subprocess.run(["curl", "-s", "-m", "700", "-A", "g4s-route-audit/1.0", "--data", body, url],
                             capture_output=True, timeout=720)
        try:
            elements = json.loads(out.stdout)["elements"]
        except Exception:
            continue   # busy or unreachable, try the next server
        ways = []
        for e in elements:
            tags = e.get("tags", {})
            kind = ("r" if tags.get("junction") in ("roundabout", "circular") else
                    "m" if tags.get("highway") in _MAIN else "l")
            ways.append([kind, [round(c, 5) for g in e.get("geometry") or [] for c in (g["lat"], g["lon"])]])
        return ways
    raise RuntimeError("no Overpass server answered")


def _build(ways):
    segs, grid = [], defaultdict(list)
    for kind, flat in ways:
        for k in range(0, len(flat) - 2, 2):
            a_lat, a_lon, b_lat, b_lon = flat[k:k + 4]
            n = len(segs)
            segs.append((kind, a_lat, a_lon, b_lat, b_lon))
            for cx in range(int(min(a_lat, b_lat) / _CELL), int(max(a_lat, b_lat) / _CELL) + 1):
                for cy in range(int(min(a_lon, b_lon) / _CELL), int(max(a_lon, b_lon) / _CELL) + 1):
                    grid[(cx, cy)].append(n)
    return segs, grid


def _load():
    global _index, version
    while True:
        try:
            if _FILE.exists() and time.time() - _FILE.stat().st_mtime < _MAX_AGE_S:
                ways = json.loads(_FILE.read_text())
            else:
                ways = _download()
                tmp = _FILE.with_suffix(".tmp")
                tmp.write_text(json.dumps(ways, separators=(",", ":")))
                os.replace(tmp, _FILE)
            _index = _build(ways)
            version += 1
            time.sleep(max(_FILE.stat().st_mtime + _MAX_AGE_S - time.time(), _RETRY_S))   # until the data is 30 days old
        except Exception:
            time.sleep(_RETRY_S)


def start():
    """Load (or download) the road data in the background. Safe to call often."""
    global _started
    with _lock:
        if not _started:
            _started = True
            threading.Thread(target=_load, name="roads", daemon=True).start()


def road_kind(lat, lon):
    """'highway', 'highway exit', 'highway roundabout', '' (another road)
    or None (road data not loaded yet)."""
    if _index is None:
        return None
    segs, grid = _index
    kx, ky = 111320 * math.cos(math.radians(lat)), 110540
    near = {}   # kind -> metres to the nearest segment of that kind
    cx, cy = int(lat / _CELL), int(lon / _CELL)
    for c in [(cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]:
        for n in grid.get(c, ()):
            kind, a_lat, a_lon, b_lat, b_lon = segs[n]
            ax, ay = (a_lon - lon) * kx, (a_lat - lat) * ky
            dx, dy = (b_lon - a_lon) * kx, (b_lat - a_lat) * ky
            L = dx * dx + dy * dy
            t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L)) if L else 0.0
            d = math.hypot(ax + t * dx, ay + t * dy)
            if d < near.get(kind, float("inf")):
                near[kind] = d
    far = float("inf")
    if near.get("m", far) <= config.HIGHWAY_NEAR_M:
        return "highway"
    if near.get("l", far) <= config.HIGHWAY_NEAR_M:
        return "highway exit"
    if near.get("r", far) <= config.HIGHWAY_NEAR_M and min(near.get("m", far), near.get("l", far)) <= config.HIGHWAY_ROUNDABOUT_M:
        return "highway roundabout"
    return ""
