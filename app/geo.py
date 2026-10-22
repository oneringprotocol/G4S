"""Small geo and text helpers."""
import math
import re
from datetime import datetime, timedelta, timezone

from . import config

UAE = timezone(timedelta(hours=config.UTC_OFFSET_H))


def dist_m(lat1, lon1, lat2, lon2):
    r = math.radians
    a = (math.sin(r(lat2 - lat1) / 2) ** 2
         + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2)
    return 12742000 * math.asin(math.sqrt(a))


_DMS = re.compile(r"(\d+)°(\d+)'([\d.]+)\"?([NSEW])")


def parse_coords(s):
    """'25.1, 55.2' | '24.33,54.38,47586m' (map view link, altitude dropped) | DMS."""
    if s is None:
        return None
    s = str(s).strip()
    dms = _DMS.findall(s)
    if len(dms) == 2:
        out = []
        for d, m, sec, h in dms:
            v = int(d) + int(m) / 60 + float(sec) / 3600
            out.append(-v if h in "SW" else v)
        return tuple(out)
    nums = re.findall(r"-?\d+\.\d+", s)
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    return None


def local(t):
    return datetime.fromtimestamp(t, UAE)


def hhmm(t):
    return local(t).strftime("%H:%M")


def day_key(t):
    return local(t).strftime("%Y-%m-%d")


def day_label(key):
    d = datetime.strptime(key, "%Y-%m-%d")
    return d.strftime("%a ") + str(d.day) + d.strftime(" %b")


# Client wording (README section 4): applied to every name we show.
_WORDS = [
    (re.compile(r"accomm?odi?ation", re.I), "Accommodation"),
    (re.compile(r"\bdepot\b", re.I), "accommodation"),
    (re.compile(r"\byard\b", re.I), "accommodation"),
    (re.compile(r"\b(G4S )?op(eration)?s sheet\b", re.I), "records"),
    (re.compile(r"\bsheet ?1\b", re.I), "G4S route plan"),
]


def clean(s):
    if s is None:
        return s
    s = " ".join(str(s).split())
    for rx, rep in _WORDS:
        s = rx.sub(rep, s)
    s = re.sub(r"\s*[-‐-—]\s*", " ", s)   # no hyphens
    s = s.replace("'", "").replace("’", "")    # no apostrophes
    return " ".join(s.split())
