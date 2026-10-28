"""Compares GPS with the G4S route plan (README section 4 rules).

Pipeline for one vehicle over the whole GPS period:
  points -> GPS gaps filled with an estimated track (gapfill.py) -> segment km (odometer, else straight line) -> stops -> runs
  (accommodation to accommodation) -> site visits per run -> runs matched
  to planned trips per day -> stop status per planned site -> day summary.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

from . import config as C
from .geo import UAE, day_key, day_label, dist_m, hhmm, local
from .gapfill import GapFiller
from .plan import SiteIndex, Vehicle
from . import roads
from .sources.base import GpsPoint


class SiteGrid:
    """Fast 'which geofence is this point in' lookup (0.01 degree cells)."""

    def __init__(self, sites: SiteIndex):
        self.cells = defaultdict(list)
        for s in sites.sites:
            cx, cy = int(s.lat * 100), int(s.lon * 100)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    self.cells[(cx + dx, cy + dy)].append(s)

    def inside(self, lat, lon):
        best, bd = None, None
        for s in self.cells.get((int(lat * 100), int(lon * 100)), ()):
            d = dist_m(lat, lon, s.lat, s.lon)
            if d <= s.radius and (bd is None or d < bd):
                best, bd = s, d
        return best


def _segment_km(pts: List[GpsPoint]):
    """km between point i and i+1. Odometer when it is sane (it keeps counting
    while the GPS fix is lost), straight line otherwise."""
    out = []
    for a, b in zip(pts, pts[1:]):
        dt = max(b.t - a.t, 1)
        line = dist_m(a.lat, a.lon, b.lat, b.lon)
        odo = (b.odometer - a.odometer) if a.odometer is not None and b.odometer is not None else None
        if odo is not None and 0 <= odo <= dt * 200 / 3.6 + 100:
            out.append(odo / 1000)
        elif line / dt * 3.6 <= 200:
            out.append(line / 1000)
        else:
            out.append(0.0)
    out.append(0.0)
    return out


def _stops(pts):
    """Runs of points at <= 3 km/h lasting 30 s or more. A GPS gap with no
    movement and zero speed at both ends counts as part of the stop."""
    stops, i, n = [], 0, len(pts)
    while i < n:
        if pts[i].speed > C.STOP_SPEED_KMH:
            i += 1
            continue
        j = i
        while j + 1 < n and pts[j + 1].speed <= C.STOP_SPEED_KMH and \
                dist_m(pts[i].lat, pts[i].lon, pts[j + 1].lat, pts[j + 1].lon) < 150:
            j += 1
        if pts[j].t - pts[i].t >= C.STOP_MIN_S:
            stops.append({"i0": i, "i1": j, "t0": pts[i].t, "t1": pts[j].t,
                          "lat": pts[i].lat, "lon": pts[i].lon})
        i = j + 1
    return stops


def _fmt_min(m):
    m = int(round(m))
    return "%d min" % m if m < 60 else "%d h %02d min" % (m // 60, m % 60)


def _delta(m):
    m = int(round(m))
    if m == 0:
        return "on time"
    return ("▲%s" if m > 0 else "▼%s") % _fmt_min(abs(m))


class VehicleAnalysis:
    def __init__(self, veh: Vehicle, sites: SiteIndex, pts: List[GpsPoint], records=None):
        self.v, self.sites = veh, sites
        self.grid = SiteGrid(sites)
        self.pts = GapFiller(veh, sites, self.grid, pts).fill()
        self.records = records or []
        self.home = sites.by_id.get(veh.home)
        self._run()

    # ---------- whole period ----------
    def _run(self):
        pts = self.pts
        self.km = _segment_km(pts)
        self.site_at = [self.grid.inside(p.lat, p.lon) for p in pts]
        h = self.home
        self.at_home = [h is not None and dist_m(p.lat, p.lon, h.lat, h.lon) <= h.radius for p in pts]
        self.stops = _stops(pts)
        self.runs = self._runs()
        self.days = sorted({day_key(p.t) for p in pts})
        self._day_cache, self._roads_v = {}, roads.version

    def _runs(self):
        pts, home = self.pts, self.at_home
        raw, i, n = [], 0, len(pts)
        while i < n:
            if home[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and not home[j + 1]:
                j += 1
            raw.append([max(i - 1, 0), min(j + 1, n - 1)])   # include the last/first point at home
            i = j + 1
        merged = []
        for r in raw:   # a touch of the fence for under 90 s does not end a run
            if merged and pts[r[0]].t - pts[merged[-1][1]].t < 90:
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        runs = []
        for a, b in merged:
            km = sum(self.km[a:b])
            far = max(dist_m(pts[k].lat, pts[k].lon, self.home.lat, self.home.lon) for k in range(a, b + 1)) if self.home else 0
            if km < 0.3 and far < 600:
                continue
            runs.append(self._describe_run(len(runs), a, b, km, far))
        return runs

    def _describe_run(self, rid, a, b, km, far):
        pts = self.pts
        visits, cur = [], None
        for k in range(a, b + 1):
            s = self.site_at[k]
            if s is not None and s.id != (self.home.id if self.home else None):
                if cur and cur["site"] == s.id and pts[k].t - cur["t1"] < 180:
                    cur["t1"], cur["k1"] = pts[k].t, k
                else:
                    cur = {"site": s.id, "t0": pts[k].t, "t1": pts[k].t, "k0": k, "k1": k}
                    visits.append(cur)
        for vi in visits:
            st = [s for s in self.stops if s["i0"] <= vi["k1"] and s["i1"] >= vi["k0"]
                  and self.site_at[s["i0"]] is not None and self.site_at[s["i0"]].id == vi["site"]]
            vi["stop_s"] = sum(s["t1"] - s["t0"] for s in st)
            vi["stopped"] = bool(st)
            if st:
                vi["t0"], vi["t1"] = min(vi["t0"], st[0]["t0"]), max(vi["t1"], st[-1]["t1"])
        spd = max((p.speed for p in pts[a:b + 1]), default=0)
        workshop = any("workshop" in self.sites.by_id[v["site"]].name.lower() for v in visits)
        return {"id": rid, "a": a, "b": b, "dep": pts[a].t, "arr": pts[b].t,
                "km": km, "far_m": far, "visits": visits,
                "max_speed": spd, "workshop": workshop, "trips": []}

    # ---------- one day ----------
    def day(self, key):
        if self._roads_v != roads.version:   # road data just loaded: outside stops change
            self._day_cache, self._roads_v = {}, roads.version
        if key not in self._day_cache:
            self._day_cache[key] = self._day(key)
        return self._day_cache[key]

    def _record(self, key):
        for r in self.records:
            if r.get("from", "") <= key <= r.get("to", r.get("from", "")):
                return r
        return None

    def _match(self, key):
        """Planned trips of the day with their matched runs."""
        d0 = datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=UAE)
        lo, hi = (d0 - timedelta(hours=3)).timestamp(), (d0 + timedelta(hours=27)).timestamp()
        runs = [r for r in self.runs if lo <= r["dep"] < hi]
        used = defaultdict(list)
        plans = []
        for tr in self.v.trips:
            hs, ms = map(int, tr.start.split(":"))
            he, me = map(int, (tr.end or tr.start).split(":"))
            ts = (d0 + timedelta(hours=hs, minutes=ms)).timestamp()
            te = (d0 + timedelta(hours=he, minutes=me)).timestamp()
            if hs < 4 and tr.n > 1:      # a trip listed after midnight belongs to the night of this day
                ts += 86400
                te += 86400
            if te <= ts:
                te += 86400
            best, bs = None, None
            W = C.MATCH_WINDOW_MIN * 60
            for r in runs:
                if self.v.home is None:
                    continue
                stopped = sum(1 for v in r["visits"] if v["site"] in tr.sites and v["stopped"])
                passed = sum(1 for v in r["visits"] if v["site"] in tr.sites and not v["stopped"])
                dm = abs(r["dep"] - ts) / 60
                overlap = r["dep"] < te + W and r["arr"] > ts - W
                if not ((dm <= C.MATCH_WINDOW_MIN) or (overlap and stopped + passed)):
                    continue
                # a run already matched can cover a second (chained) trip only if it stopped at its sites,
                # and only when no unused run fits
                if r["id"] in used and not stopped:
                    continue
                score = stopped * 100 + passed * 20 - dm - (400 if r["id"] in used else 0)
                if bs is None or score > bs:
                    best, bs = r, score
            if best:
                used[best["id"]].append(tr.n)
            plans.append({"tr": tr, "ts": ts, "te": te, "run": best})
        return plans, runs, used

    def _status(self, p, site_id, all_runs):
        """Validated / Passed / Out of window / Not visited / No GPS data."""
        tr, ts, te, run = p["tr"], p["ts"], p["te"], p["run"]
        tol = C.ON_TIME_MIN * 60
        if run:
            vs = [v for v in run["visits"] if v["site"] == site_id]
            stopped = [v for v in vs if v["stopped"]]
            if stopped:
                v = stopped[0]
                inwin = ts - tol <= v["t0"] <= te + tol
                return ("Validated" if inwin else "Out", v)
            if vs:
                return ("Passed", vs[0])
        W = C.MATCH_WINDOW_MIN * 60
        for r in all_runs:
            for v in r["visits"]:
                if v["site"] == site_id and v["stopped"] and ts - W <= v["t0"] <= te + W:
                    return ("Out", v)
        return ("Not", None)

    def _day(self, key):
        v, S, pts = self.v, self.sites, self.pts
        d0 = datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=UAE)
        t0, t1 = d0.timestamp(), (d0 + timedelta(days=1)).timestamp()
        rec = self._record(key)
        plans, near_runs, used = self._match(key)

        # runs that belong to this day (by departure)
        day_runs = [r for r in self.runs if t0 <= r["dep"] < t1]
        matched_ids = {p["run"]["id"] for p in plans if p["run"]}

        # ---- trips and stops ----
        trips, counts = [], defaultdict(int)
        for p in plans:
            tr, run = p["tr"], p["run"]
            if not (t0 <= p["ts"] < t1 + 3 * 3600):
                continue
            replaced = bool(rec and rec.get("replaced_by"))
            stops = []
            for sid in tr.sites:
                if replaced:
                    st, info = "Repl", None
                else:
                    st, info = self._status(p, sid, near_runs)
                    counts[st] += 1
                s = S.by_id[sid]
                row = {"site": sid, "label": s.label, "status": st, "lat": s.lat, "lon": s.lon}
                if info and "t0" in info:
                    row["time"] = hhmm(info["t0"])
                    row["t"] = info["t0"]
                    if info.get("stop_s"):
                        row["dur_min"] = round(info["stop_s"] / 60, 1)
                    if self.pts[info["k0"]].inferred:
                        row["est"] = True
                stops.append(row)
            stops.sort(key=lambda r: (r.get("t") or 9e12))
            item = {"n": tr.n, "group": tr.group, "plan_start": tr.start, "plan_end": tr.end,
                    "staff_out": tr.staff_out, "staff_back": tr.staff_back,
                    "stops": stops, "replaced": replaced,
                    "validated": sum(1 for s in stops if s["status"] == "Validated"),
                    "night": local(p["ts"]).hour >= C.NIGHT_FROM or local(p["ts"]).hour < C.NIGHT_TO}
            if replaced:
                item["replaced_by"] = rec.get("replaced_by")
            if run and not replaced:
                shared = used[run["id"]]
                item.update({"run": run["id"], "dep": hhmm(run["dep"]), "arr": hhmm(run["arr"]),
                             "delta": _delta((run["dep"] - p["ts"]) / 60),
                             "delta_min": round((run["dep"] - p["ts"]) / 60),
                             "km": round(run["km"] / max(len(shared), 1), 1),
                             "chained": [n for n in shared if n != tr.n]})
            trips.append(item)

        # ---- runs of the day ----
        runs_out = []
        for r in day_runs:
            kind = "planned" if r["id"] in matched_ids else (
                "workshop" if r["workshop"] else
                "yard" if r["far_m"] < C.YARD_RADIUS_M else "unplanned")
            runs_out.append(self._run_out(r, kind, used.get(r["id"], []), trips))

        # ---- km ----
        km_total = sum(self.km[k] for k, p in enumerate(pts) if t0 <= p.t < t1)
        km_by = defaultdict(float)
        for r in runs_out:
            km_by[r["kind"]] += r["km"]
        km_planned = km_by["planned"]
        km_unpl = km_by["unplanned"]
        km_yard = max(km_total - km_planned - km_unpl - km_by["workshop"], 0)

        # ---- stops outside geofences ----
        outside = []
        for s in self.stops:
            if not (t0 <= s["t0"] < t1) or s["t1"] - s["t0"] < C.OUTSIDE_STOP_MIN_S:
                continue
            if self.site_at[s["i0"]] is not None or self.at_home[s["i0"]]:
                continue
            if s["t1"] - s["t0"] < C.HIGHWAY_STOP_MAX_S and roads.road_kind(s["lat"], s["lon"]):
                continue   # traffic on a highway, highway exit or highway roundabout
            ns, nd = S.nearest(s["lat"], s["lon"])
            run = self._run_at(s["t0"])
            outside.append({"n": len(outside) + 1, "t0": s["t0"], "time": hhmm(s["t0"]),
                            "end": hhmm(s["t1"]), "dur_min": round((s["t1"] - s["t0"]) / 60, 1),
                            "lat": s["lat"], "lon": s["lon"],
                            "near": ns.label, "near_km": round(nd / 1000, 1),
                            "during": self._during(run, runs_out)})

        # ---- speeding ----
        speeding, cur = [], None
        for k, p in enumerate(pts):
            if not (t0 <= p.t < t1):
                continue
            if p.speed > C.SPEED_LIMIT_KMH:
                if cur and p.t - cur["t1"] <= 60:
                    cur["t1"] = p.t
                    if p.speed > cur["max"]:
                        cur.update(max=p.speed, lat=p.lat, lon=p.lon)
                else:
                    cur = {"t0": p.t, "t1": p.t, "max": p.speed, "lat": p.lat, "lon": p.lon}
                    speeding.append(cur)
        for s in speeding:
            ns, nd = S.nearest(s["lat"], s["lon"])
            s.update(time=hhmm(s["t0"]), dur_s=s["t1"] - s["t0"], driver=v.driver,
                     near=ns.label, near_km=round(nd / 1000, 1),
                     during=self._during(self._run_at(s["t0"]), runs_out))

        # ---- idling at accommodation (ignition on, not moving) ----
        idling, cur = [], None
        for k, p in enumerate(pts):
            ok = t0 <= p.t < t1 and self.at_home[k] and p.ignition and p.speed <= C.STOP_SPEED_KMH
            if ok:
                cur = cur or {"t0": p.t}
                cur["t1"] = p.t
            elif cur:
                if cur["t1"] - cur["t0"] >= C.IDLE_MIN_S:
                    idling.append(cur)
                cur = None
        if cur and cur["t1"] - cur["t0"] >= C.IDLE_MIN_S:
            idling.append(cur)
        for i in idling:
            i.update(time=hhmm(i["t0"]), end=hhmm(i["t1"]), dur_min=round((i["t1"] - i["t0"]) / 60))

        planned_stops = sum(counts[k] for k in ("Validated", "Passed", "Out", "Not"))
        n_unpl = sum(1 for r in runs_out if r["kind"] == "unplanned")
        n_run = sum(1 for t in trips if t.get("run") is not None)
        out = {
            "day": key, "label": day_label(key),
            "record": rec,
            "kpi": {
                "validated": counts["Validated"], "planned_stops": planned_stops,
                "with_data": planned_stops,
                "pct": round(100 * counts["Validated"] / planned_stops) if planned_stops else None,
                "km": round(km_total, 1), "km_planned": round(km_planned, 1),
                "km_unplanned": round(km_unpl, 1), "km_other": round(km_yard + km_by["workshop"], 1),
                "trips_planned": len(trips), "trips_run": n_run, "trips_unplanned": n_unpl,
                "outside": len(outside), "outside_min": round(sum(o["dur_min"] for o in outside)),
                "idling": len(idling), "idling_min": sum(i["dur_min"] for i in idling),
                "speeding": len(speeding), "max_speed": max((s["max"] for s in speeding), default=None),
            },
            "counts": dict(counts),
            "trips": trips, "runs": runs_out, "outside": outside,
            "speeding": speeding, "idling": idling,
        }
        out["track"] = self._track(t0, t1, runs_out)
        out["events"] = self._events(out)
        return out

    def _run_at(self, t):
        for r in self.runs:
            if r["dep"] <= t <= r["arr"]:
                return r
        return None

    def _during(self, run, runs_out):
        if not run:
            return {"label": "Not on a trip", "kind": "none"}
        ro = next((x for x in runs_out if x["id"] == run["id"]), None)
        if ro and ro["kind"] == "planned":
            return {"label": "Trip " + " + ".join(str(n) for n in ro["trips"]), "kind": "planned", "run": run["id"]}
        if ro:
            return {"label": "Unplanned trip" if ro["kind"] == "unplanned" else "Accommodation move",
                    "kind": ro["kind"], "run": run["id"]}
        return {"label": "Not on a trip", "kind": "none"}

    def _run_out(self, r, kind, trip_ns, trips):
        dep, arr = r["dep"], r["arr"]
        h = local(dep).hour
        night = h >= C.NIGHT_FROM or h < C.NIGHT_TO
        dur = (arr - dep) / 60
        typ = "Short hop" if r["km"] < C.SHORT_HOP_KM else ("Late night" if night else "Daytime")
        longest = max(r["visits"], key=lambda v: v.get("stop_s", 0), default=None)
        st = [s for s in self.stops if dep <= s["t0"] <= arr and s["t1"] - s["t0"] >= C.OUTSIDE_STOP_MIN_S]
        lng = max(st, key=lambda s: s["t1"] - s["t0"], default=None)
        if kind == "planned":
            comment = "Planned trip %s." % " + ".join(map(str, trip_ns))
        elif kind == "workshop":
            comment = "Drive to or from the workshop. Not counted as unplanned."
        elif kind == "yard":
            comment = "Short move of %.1f km around the accommodation." % r["km"]
        else:
            before = [t for t in trips if t.get("arr") and t["plan_end"] <= hhmm(dep)]
            after = [t for t in trips if t["plan_start"] > hhmm(dep)]
            if night:
                comment = "Left at %s, late at night with no planned trip due." % hhmm(dep)
            elif before and after:
                comment = "Left at %s, between trip %d (ends %s) and trip %d (starts %s)." % (
                    hhmm(dep), before[-1]["n"], before[-1]["plan_end"], after[0]["n"], after[0]["plan_start"])
            else:
                comment = "Left at %s with no planned trip due." % hhmm(dep)
            comment += " Back at %s after %.1f km." % (hhmm(arr), r["km"])
            if lng:
                ns, nd = self.sites.nearest(lng["lat"], lng["lon"])
                comment += " Longest stop %s, %.1f km from %s." % (_fmt_min((lng["t1"] - lng["t0"]) / 60), nd / 1000, ns.label)
        return {"id": r["id"], "kind": kind, "type": typ if kind == "unplanned" else None,
                "dep": hhmm(dep), "arr": hhmm(arr), "t0": dep, "t1": arr,
                "dur": _fmt_min(dur), "km": round(r["km"], 1), "trips": trip_ns,
                "night": night, "max_speed": r["max_speed"], "comment": comment,
                "sites": [self.sites.by_id[v["site"]].label for v in r["visits"] if v["stopped"]]}

    def _track(self, t0, t1, runs_out):
        """Thinned track for the map: [t, lat, lon, speed, run id or -1, 1 if estimated]."""
        out, last = [], None
        rmap = [(r["t0"], r["t1"], r["id"]) for r in runs_out]
        for p in self.pts:
            if not (t0 <= p.t < t1):
                continue
            if last and last.inferred == p.inferred and dist_m(last.lat, last.lon, p.lat, p.lon) < 12 and p.t - last.t < 300:
                continue
            rid = next((i for a, b, i in rmap if a <= p.t <= b), -1)
            out.append([p.t, round(p.lat, 5), round(p.lon, 5), p.speed, rid, 1 if p.inferred else 0])
            last = p
        return out

    def _events(self, d):
        ev = []
        for r in d["runs"]:
            label = {"planned": "Trip " + " + ".join(map(str, r["trips"])),
                     "unplanned": "Unplanned trip", "yard": "Accommodation move",
                     "workshop": "Workshop drive"}[r["kind"]]
            ev.append({"t": r["t0"], "kind": r["kind"], "title": "Leaves accommodation · " + label,
                       "text": r["comment"]})
            ev.append({"t": r["t1"], "kind": r["kind"], "title": "Back at accommodation",
                       "text": "%s · %.1f km in %s." % (label, r["km"], r["dur"])})
        for t in d["trips"]:
            for s in t["stops"]:
                if s.get("t") and s["status"] in ("Validated", "Out"):
                    ev.append({"t": s["t"], "kind": "stop", "title": s["label"],
                               "text": "Trip %d stop%s." % (t["n"], ", %s min" % s["dur_min"] if s.get("dur_min") else ""),
                               "lat": s["lat"], "lon": s["lon"]})
        for o in d["outside"]:
            ev.append({"t": o["t0"], "kind": "outside", "title": "Stop outside geofences #%d" % o["n"],
                       "text": "%s min, %.1f km from %s." % (o["dur_min"], o["near_km"], o["near"]),
                       "lat": o["lat"], "lon": o["lon"]})
        for s in d["speeding"]:
            ev.append({"t": s["t0"], "kind": "speed", "title": "Speeding %d km/h" % s["max"],
                       "text": "Over %d km/h for %d s near %s." % (C.SPEED_LIMIT_KMH, max(s["dur_s"], 1), s["near"]),
                       "lat": s["lat"], "lon": s["lon"]})
        ev.sort(key=lambda e: e["t"])
        for e in ev:
            e["time"] = hhmm(e["t"])
        return ev

    # ---------- mileage ----------
    def mileage(self):
        out = []
        for key in self.days:
            k = self.day(key)["kpi"]
            out.append({"day": key, "planned": k["km_planned"], "unplanned": k["km_unplanned"],
                        "other": k["km_other"], "total": k["km"]})
        return out
