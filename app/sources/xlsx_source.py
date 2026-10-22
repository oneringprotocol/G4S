"""Reads tracker "Route" report exports (one sheet per device, data from row 9).

Header block:
    Report type: Route
    Device:      15590 - DF - SHJ/Rak
    Period:      2026-10-10 20:00:00 - 2026-10-17 19:59:59   (UTC)
Columns: Valid, Time (UTC), Latitude, Longitude, Altitude, Speed ("12.3 km/h"),
Address, Attributes ("key=value  key=value ...").

Parsing 90k rows takes a few seconds, so each file is cached as JSON next to
the other caches and refreshed when the xlsx changes.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from .base import DeviceInfo, GpsPoint, GpsSource

_ATTR = re.compile(r"(\w+)=(\S+)")


def _utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _parse_sheet(ws) -> Dict:
    meta, pts = {}, []
    for row in ws.iter_rows(values_only=True):
        if not row or row[0] is None and not pts:
            continue
        head = row[0]
        if isinstance(head, str) and head.endswith(":"):
            meta[head[:-1].lower()] = row[1]
            continue
        if head == "Valid":
            continue
        if not isinstance(head, bool) or row[2] is None:
            continue
        attrs = dict(_ATTR.findall(row[7] or ""))
        speed = float(str(row[5]).split()[0]) if row[5] else 0.0
        pts.append([
            int(_utc(row[1]).timestamp()),
            round(float(row[2]), 6),
            round(float(row[3]), 6),
            round(speed, 1),
            1 if head else 0,
            {"true": 1, "false": 0}.get(attrs.get("ignition"), -1),
            float(attrs["odometer"]) if "odometer" in attrs else None,
        ])
    pts.sort(key=lambda p: p[0])
    device = str(meta.get("device", ws.title))
    start, end = [s.strip() for s in str(meta.get("period", " - ")).split(" - ")][:2]
    return {
        "device": device,
        "vehicle": device.split()[0],
        "start": start,
        "end": end,
        "points": pts,
    }


class XlsxRouteSource(GpsSource):
    name = "xlsx"

    def __init__(self, folder: Path, cache: Path):
        self.folder = Path(folder)
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        for f in sorted(self.folder.glob("Route_*.xlsx")):
            cf = self.cache / (f.stem + ".json")
            if cf.exists() and cf.stat().st_mtime >= f.stat().st_mtime:
                sheets = json.loads(cf.read_text())
            else:
                import openpyxl
                wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
                sheets = [_parse_sheet(ws) for ws in wb.worksheets]
                wb.close()
                tmp = cf.with_suffix(".tmp")
                tmp.write_text(json.dumps(sheets, separators=(",", ":")))
                os.replace(tmp, cf)
            for s in sheets:
                cur = self._data.get(s["vehicle"])
                if cur:  # several exports for one vehicle: merge and de-duplicate by time
                    merged = {p[0]: p for p in cur["points"] + s["points"]}
                    cur["points"] = [merged[k] for k in sorted(merged)]
                    cur["start"] = min(cur["start"], s["start"])
                    cur["end"] = max(cur["end"], s["end"])
                else:
                    self._data[s["vehicle"]] = s

    def devices(self) -> List[DeviceInfo]:
        return [DeviceInfo(v, d["device"], _utc(d["start"]), _utc(d["end"]))
                for v, d in sorted(self._data.items())]

    def positions(self, vehicle, start, end) -> List[GpsPoint]:
        d = self._data.get(str(vehicle))
        if not d:
            return []
        a, b = int(start.timestamp()), int(end.timestamp())
        return [GpsPoint(p[0], p[1], p[2], p[3], bool(p[4]),
                         None if p[5] < 0 else bool(p[5]), p[6])
                for p in d["points"] if a <= p[0] < b]
