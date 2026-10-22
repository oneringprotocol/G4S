"""GPS source interface.

Every source (xlsx export today, the GPS provider API later) returns the same
normalized points, so the analysis never knows where the data came from.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class GpsPoint:
    t: int            # unix seconds, UTC
    lat: float
    lon: float
    speed: float      # km/h
    valid: bool       # GPS fix valid (False = last known position repeated)
    ignition: Optional[bool] = None
    odometer: Optional[float] = None  # metres, as reported by the tracker


@dataclass
class DeviceInfo:
    vehicle: str          # fleet number, e.g. "15590"
    name: str             # provider device name
    start: datetime       # UTC
    end: datetime         # UTC


class GpsSource:
    """Base class. Subclasses: XlsxRouteSource, and later a provider API source."""

    name = "base"

    def devices(self) -> List[DeviceInfo]:
        raise NotImplementedError

    def positions(self, vehicle: str, start: datetime, end: datetime) -> List[GpsPoint]:
        """Points for one vehicle between start and end (UTC), sorted by time."""
        raise NotImplementedError
