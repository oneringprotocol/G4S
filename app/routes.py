"""Planned route lines: accommodation -> sites -> accommodation, on roads.

Sites are visited nearest first (the plan lists who to serve, not the order).
Road geometry comes from the public OSRM server and is cached on disk; with no
network the line falls back to straight dashes between the sites.
"""
import json
import subprocess
import threading
import urllib.request
from types import SimpleNamespace

from . import config
from .geo import dist_m

_FILE = config.CACHE / "routes.json"
_lock = threading.Lock()
_cache = json.loads(_FILE.read_text()) if _FILE.exists() else {}


def order_sites(home, sites):
    left, out, cur = list(sites), [], home
    while left:
        nxt = min(left, key=lambda s: dist_m(cur.lat, cur.lon, s.lat, s.lon))
        out.append(nxt)
        left.remove(nxt)
        cur = nxt
    return out


def _osrm(points):
    coords = ";".join("%.6f,%.6f" % (p.lon, p.lat) for p in points)
    url = "https://router.project-osrm.org/route/v1/driving/%s?overview=simplified&geometries=geojson" % coords
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "g4s-route-audit/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
    except Exception:
        # the macOS system Python ships an old LibreSSL that fails the TLS handshake; curl does not
        out = subprocess.run(["curl", "-s", "-m", "10", "-A", "g4s-route-audit/1.0", url],
                             capture_output=True, timeout=15)
        data = json.loads(out.stdout or b"{}")
    if data.get("code") != "Ok":
        return None
    return [[round(lat, 5), round(lon, 5)] for lon, lat in data["routes"][0]["geometry"]["coordinates"]]


def road_path(lls):
    """Road line through [lat, lon] points in order, or None when OSRM cannot be reached."""
    key = "path|" + "|".join("%.5f,%.5f" % tuple(ll) for ll in lls)
    if key in _cache:
        return _cache[key]
    try:
        line = _osrm([SimpleNamespace(lat=ll[0], lon=ll[1]) for ll in lls])
    except Exception:
        line = None
    if line:
        with _lock:
            _cache[key] = line
            _FILE.write_text(json.dumps(_cache, separators=(",", ":")))
    return line


def planned_line(home, sites):
    if not home or not sites:
        return {"line": [], "road": False}
    pts = [home] + order_sites(home, sites) + [home]
    key = "|".join(p.id + "@%.5f,%.5f" % (p.lat, p.lon) for p in pts)
    if key in _cache:
        return {"line": _cache[key], "road": True}
    try:
        line = _osrm(pts)
    except Exception:
        line = None
    if line:
        with _lock:
            _cache[key] = line
            _FILE.write_text(json.dumps(_cache, separators=(",", ":")))
        return {"line": line, "road": True}
    return {"line": [[p.lat, p.lon] for p in pts], "road": False}
