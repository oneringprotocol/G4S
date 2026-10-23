"""Fills GPS gaps with an estimated track, so every stop gets a status.

A gap is 10 min or more with no position. What we still know across it: where
the bus was before and after, and the odometer km it drove in between.

- Stationary gap: the bus stays where it was.
- Moving gap: the planned sites due at that time that the GPS never shows are
  placed on the road path from the last fix to the next one (OSRM, cached),
  in the order that drives the least. Sites are kept only while that path
  still fits the odometer km. The bus waits at the start, drives at its usual
  speed and stops a few minutes at each site, so the analysis sees ordinary
  stops. Estimated points carry inferred=True.
"""
import itertools
import statistics
from datetime import datetime, timedelta
from types import SimpleNamespace

from . import config as C
from .geo import UAE, day_key, dist_m
from .routes import road_path
from .sources.base import GpsPoint

STEP_S = 30          # one estimated point every 30 s
ROAD_FACTOR = 1.3    # road km per straight km when no road path is available
FIT = 0.7            # odometer reads ~15% under OSRM road km here (13 Oct: 34.7 vs 40.6), and site centres sit off the road


def _path_m(lls):
    return sum(dist_m(a[0], a[1], b[0], b[1]) for a, b in zip(lls, lls[1:]))


def _order(a, b, sites):
    """Visiting order from a to b that drives the least (straight line)."""
    if len(sites) > 7:
        left, out, cur = list(sites), [], a
        while left:
            nxt = min(left, key=lambda s: dist_m(cur[0], cur[1], s.lat, s.lon))
            out.append(nxt)
            left.remove(nxt)
            cur = (nxt.lat, nxt.lon)
        return out
    return list(min(itertools.permutations(sites),
                    key=lambda p: _path_m([a] + [(s.lat, s.lon) for s in p] + [b])))


def _road(lls):
    """Road line through the points, split into one leg per pair."""
    line = road_path(lls)
    if not line:
        return [[x, y] for x, y in zip(lls, lls[1:])], False
    legs, j, prev = [], 0, lls[0]
    for w in lls[1:-1]:   # cut the line at the vertex nearest each waypoint, moving forward
        k = min(range(j, len(line)), key=lambda i: dist_m(line[i][0], line[i][1], w[0], w[1]))
        legs.append([prev] + [tuple(p) for p in line[j:k + 1]] + [w])
        j, prev = k, w
    legs.append([prev] + [tuple(p) for p in line[j:]] + [lls[-1]])
    return legs, True


def _along(leg, f):
    """Point at fraction f of the leg's length."""
    total = _path_m(leg)
    if total == 0:
        return leg[0]
    goal, run = f * total, 0
    for a, b in zip(leg, leg[1:]):
        d = dist_m(a[0], a[1], b[0], b[1])
        if run + d >= goal and d > 0:
            g = (goal - run) / d
            return (a[0] + (b[0] - a[0]) * g, a[1] + (b[1] - a[1]) * g)
        run += d
    return leg[-1]


class GapFiller:
    def __init__(self, veh, sites, grid, pts):
        self.v, self.sites, self.grid, self.pts = veh, sites, grid, pts
        moving = [p.speed for p in pts if p.speed > 10]
        self.cruise = statistics.median(moving) if moving else 50.0
        from .analysis import _stops   # same stop rule as the analysis
        self.seen = [(s["t0"], s0.id) for s in _stops(pts)
                     for s0 in [grid.inside(s["lat"], s["lon"])] if s0]

    def _due_sites(self, t0, t1):
        """Planned sites due around the gap that the GPS never shows a stop at."""
        W = C.MATCH_WINDOW_MIN * 60
        out = []
        for key in {day_key(t0 - 86400), day_key(t0)}:
            d0 = datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=UAE)
            for tr in self.v.trips:
                hs, ms = map(int, tr.start.split(":"))
                he, me = map(int, (tr.end or tr.start).split(":"))
                ts = (d0 + timedelta(hours=hs, minutes=ms)).timestamp()
                te = (d0 + timedelta(hours=he, minutes=me)).timestamp()
                if hs < 4 and tr.n > 1:
                    ts, te = ts + 86400, te + 86400
                if te <= ts:
                    te += 86400
                if not (ts - C.ON_TIME_MIN * 60 <= t1 and te >= t0):   # the gap falls inside the planned trip
                    continue
                for sid in tr.sites:
                    if sid == self.v.home or sid in out:
                        continue
                    if any(sid == s and ts - W <= t <= te + W for t, s in self.seen):
                        continue
                    out.append(sid)
        return [self.sites.by_id[s] for s in out]

    def fill(self):
        pts, out = self.pts, []
        for a, b in zip(pts, pts[1:]):
            out.append(a)
            if b.t - a.t >= C.GAP_S:
                out += self._gap(a, b)
        if pts:
            out.append(pts[-1])
        return out

    def _point(self, t, ll, speed, odo, ign):
        return GpsPoint(int(t), round(ll[0], 6), round(ll[1], 6), round(speed, 1), False, ign, odo, True)

    def _gap(self, a, b):
        odo_m = (b.odometer - a.odometer) if a.odometer is not None and b.odometer is not None else None
        moved = dist_m(a.lat, a.lon, b.lat, b.lon) > 300 or (odo_m or 0) > 500
        T = b.t - a.t
        if not moved:
            return [self._point(t, (a.lat, a.lon), 0, a.odometer, None) for t in range(a.t + 60, b.t, 60)]

        A, B = (a.lat, a.lon), (b.lat, b.lon)
        sites = _order(A, B, self._due_sites(a.t, b.t))
        while True:   # drop the site that costs the most km until the path fits the odometer
            lls = [A] + [(s.lat, s.lon) for s in sites] + [B]
            legs, road = _road(lls)
            L = sum(_path_m(l) for l in legs) * (1 if road else ROAD_FACTOR)
            if not sites or odo_m is None or L * FIT <= odo_m:
                break
            sites.remove(max(sites, key=lambda s: L - _path_m([p for p in lls if p != (s.lat, s.lon)])))

        km = (odo_m if odo_m is not None else L) / 1000
        dwell = C.EST_DWELL_S
        drive = km / self.cruise * 3600
        if drive + dwell * len(sites) > T:
            dwell = min(dwell, max(C.STOP_MIN_S * 2, (T * 0.3) / max(len(sites), 1)))
            drive = T - dwell * len(sites)
        speed = min(km / max(drive, 1) * 3600, C.SPEED_LIMIT_KMH - 10)
        wait = T - drive - dwell * len(sites)

        out, t = [], a.t
        while t + 60 < a.t + wait:   # waiting at the last known position
            t += 60
            out.append(self._point(t, A, 0, a.odometer, None))
        t = a.t + wait
        lens = [_path_m(l) for l in legs]
        total = sum(lens) or 1
        done = 0
        for i, leg in enumerate(legs):
            leg_s = drive * lens[i] / total
            n = max(int(leg_s // STEP_S), 1)
            for k in range(1, n + 1):
                f = k / n
                odo = a.odometer + odo_m * (done + lens[i] * f) / total if odo_m is not None else None
                out.append(self._point(t + leg_s * f, _along(leg, f), speed, odo, True))
            t += leg_s
            done += lens[i]
            if i < len(sites):   # stopped at the site, one point a minute
                s, odo = sites[i], (a.odometer + odo_m * done / total if odo_m is not None else None)
                for k in range(0, int(dwell) + 1, 60):
                    out.append(self._point(t + k, (s.lat, s.lon), 0, odo, True))
                out.append(self._point(t + dwell, (s.lat, s.lon), 0, odo, True))
                t += dwell
        seen, keep = set(), []
        for p in out:
            if a.t < p.t < b.t and p.t not in seen:
                seen.add(p.t)
                keep.append(p)
        return keep
