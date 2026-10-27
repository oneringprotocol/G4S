"""Total Secure tracking platform API client (the platform runs Traccar 6.5).

Shared by every Total Secure feed: GPS positions now (sources/totalsecure_source.py),
driver behaviour reports later.

Credentials: the app holds one API token, never the platform password. It lives in
data/secrets/totalsecure_token.json (owner only, git ignored) and is never printed,
logged or put in an error message, a URL or .env. Set it up once with

    python3 -m app.totalsecure token      # asks for email and password, saves the token

After that the app renews it by itself: every 30 days it asks the platform for a new
token valid for 45 days, checks that the new one works, then switches to it. The old
token keeps working until the switch, so a renewal never interrupts the app; a failed
renewal is retried every 6 hours, with 15 days to spare. Old tokens are revoked where
the platform supports it (Traccar 6.6 and later); on 6.5 they simply expire.

Requests are https only, redirects are refused (so the token cannot follow one to
another host), and every call has a timeout.
"""
import base64
import fcntl
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

log = logging.getLogger("g4s.totalsecure")

TIMEOUT_S = 30
RETRIES = 2              # extra tries on a network error or a 5xx answer
UA = "g4s-route-audit/1.0"
DAY = timedelta(days=1)
ROTATE_DAYS = 30         # make a new token every 30 days ...
TOKEN_DAYS = 45          # ... valid for 45, so a failing renewal has 15 days of retries
CHECK_S = 6 * 3600       # how often the app checks whether a renewal is due
WARN_DAYS = 7            # the admin sees a warning when the token has this little left


class ProviderError(Exception):
    """Safe to show to users: never holds the token, the password or a response body."""

    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None   # a 3xx then surfaces as an HTTPError instead of being followed


_opener = urllib.request.build_opener(_NoRedirect)


def _check_url(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" and u.hostname not in ("localhost", "127.0.0.1"):
        raise ProviderError("G4S_TS_URL must start with https://")


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _expiry_of(token):
    """Expiry written inside a Traccar token (base64 JSON {"u": user, "e": expiry}), or None."""
    for part in re.findall(r"eyJ[A-Za-z0-9_-]+", token):
        try:
            e = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("e")
            return _parse(e) if e else None
        except (ValueError, AttributeError):
            continue
    return None


# ---------- token store ----------

def _strip_env_token():
    """Remove G4S_TS_TOKEN from .env once the token is in the store."""
    env = config.ROOT / ".env"
    if not env.exists():
        return
    lines = env.read_text().splitlines(keepends=True)
    keep = [l for l in lines if not l.strip().startswith("G4S_TS_TOKEN")]
    if keep != lines:
        tmp = env.with_name(".env.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("".join(keep))
        os.replace(tmp, env)
    os.environ.pop("G4S_TS_TOKEN", None)
    config.TS_TOKEN = ""


class TokenStore:
    """The API token on disk, re-read whenever the file changes (so the app and the
    command line always agree). A token still found in .env is moved here, removed
    from .env, and renewed straight away because it was visible there."""

    def __init__(self, path=None):
        self.path = Path(path or config.TS_TOKEN_FILE)
        self._mtime, self._data = None, {}

    def _load(self):
        if not self.path.exists() and config.TS_TOKEN:
            t = config.TS_TOKEN
            exp = _expiry_of(t)
            self.save({"token": t, "created": _iso(_now()), "expires": _iso(exp) if exp else None, "from_env": True})
            _strip_env_token()
        try:
            m = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            self._mtime, self._data = None, {}
            return self._data
        if m != self._mtime:
            self._data, self._mtime = json.loads(self.path.read_text()), m
        return self._data

    def token(self):
        return self._load().get("token", "")

    def info(self):
        """Everything but the token itself."""
        d = self._load()
        return {k: d.get(k) for k in ("created", "expires", "from_env")}

    def days_left(self):
        exp = self.info()["expires"]
        return (_parse(exp) - _now()).total_seconds() / 86400 if exp else None

    def due(self):
        d = self._load()
        if not d.get("token"):
            return False
        if d.get("from_env"):
            return True
        left = self.days_left()
        return _now() - _parse(d["created"]) >= ROTATE_DAYS * DAY or (left is not None and left <= TOKEN_DAYS - ROTATE_DAYS)

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)

    @contextmanager
    def lock(self):
        """One renewal at a time, across the app and the command line."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(self.path.with_suffix(".lock"), "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield


# ---------- client ----------

class Client:
    def __init__(self, base_url, store, timeout=TIMEOUT_S):
        _check_url(base_url)
        self.base = base_url.rstrip("/")
        self.store = store
        self.timeout = timeout
        if not store.token():
            raise ProviderError("Total Secure is not set up: run python3 -m app.totalsecure token (see docs/APP.md).")

    def __repr__(self):
        return "Client(%s)" % self.base

    def _send(self, path, params=None, form=None, token=None, raw=False):
        url = self.base + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        for attempt in range(RETRIES + 1):
            tok = token or self.store.token()
            headers = {"Authorization": "Bearer " + tok, "Accept": "application/json", "User-Agent": UA}
            if data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            try:
                with _opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=self.timeout) as r:
                    body = r.read()
                    return body.decode().strip() if raw else json.loads(body)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    if token is None and self.store.token() != tok:
                        continue   # renewed meanwhile: try again with the new token
                    raise ProviderError("Total Secure refused the API token (expired or revoked). "
                                        "Set it up again with: python3 -m app.totalsecure token", e.code) from None
                if e.code < 500 or attempt == RETRIES:
                    raise ProviderError("Total Secure answered %d for %s" % (e.code, path), e.code) from None
            except (urllib.error.URLError, OSError, ValueError) as e:
                if attempt == RETRIES:
                    raise ProviderError("Could not reach Total Secure (%s)" % type(e).__name__) from None
            time.sleep(2 * (attempt + 1))
        raise ProviderError("Total Secure refused the API token")

    def get(self, path, params=None):
        return self._send(path, params)

    def devices(self):
        return self.get("/devices")

    def route(self, device_id, start, end):
        """Positions of one device from start to end (UTC), as in the tracker "Route" report."""
        return self.get("/reports/route", {"deviceId": device_id, "from": _iso(start), "to": _iso(end)})


# ---------- renewal ----------

def rotate(client, force=False):
    """Swap the token for a new one. True when it did. The old token stays in use until
    the new one has answered a request and is saved, so nothing fails meanwhile."""
    store = client.store
    with store.lock():
        if not force and not store.due():
            return False
        old = store.token()
        exp = _now() + TOKEN_DAYS * DAY
        new = client._send("/session/token", form={"expiration": _iso(exp)}, raw=True)
        if not new or new == old:
            raise ProviderError("Total Secure did not give a new token")
        client._send("/devices", token=new)   # prove it works before switching
        store.save({"token": new, "created": _iso(_now()), "expires": _iso(_expiry_of(new) or exp)})
    try:
        client._send("/session/token/revoke", form={"token": old}, token=new, raw=True)
    except ProviderError as e:
        if e.status == 404:
            log.info("Total Secure cannot revoke tokens (Traccar before 6.6); the old one expires on its own")
        else:
            log.warning("Old Total Secure token not revoked (%s); it expires on its own", e)
    log.info("Total Secure token renewed; valid until %s", store.info()["expires"])
    return True


_rotating = threading.Lock()
_started = False


def start_rotation(client):
    """Background thread in the app: checks every 6 hours and renews when due."""
    global _started
    with _rotating:
        if _started:
            return
        _started = True

    def loop():
        while True:
            try:
                rotate(client)
            except Exception as e:
                log.warning("Total Secure token renewal failed, will retry in 6 h: %s",
                            e if isinstance(e, ProviderError) else type(e).__name__)
            time.sleep(CHECK_S)

    threading.Thread(target=loop, name="totalsecure-token", daemon=True).start()


# ---------- command line ----------

def _post(url, form, cookie=None):
    headers = {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), headers=headers)
    return _opener.open(req, timeout=TIMEOUT_S)


def _make_token():
    import getpass
    base = config.TS_URL.rstrip("/")
    _check_url(base)
    email = input("Total Secure email: ").strip()
    password = getpass.getpass("Password (not shown, not saved): ")
    try:
        with _post(base + "/session", {"email": email, "password": password}) as r:
            user = json.loads(r.read())
            cookie = next((c.split(";")[0] for c in r.headers.get_all("Set-Cookie") or []
                           if c.startswith("JSESSIONID=")), None)
    except urllib.error.HTTPError as e:
        sys.exit("Sign in failed (%d). Check the email and password." % e.code)
    finally:
        password = None
    if not cookie:
        sys.exit("Sign in worked but no session cookie came back.")
    exp = _now() + TOKEN_DAYS * DAY
    try:
        with _post(base + "/session/token", {"expiration": _iso(exp)}, cookie) as r:
            token = r.read().decode().strip()
    finally:
        req = urllib.request.Request(base + "/session", method="DELETE", headers={"Cookie": cookie, "User-Agent": UA})
        try:
            _opener.open(req, timeout=TIMEOUT_S).close()
        except urllib.error.URLError:
            pass
    store = TokenStore()
    with store.lock():
        store.save({"token": token, "created": _iso(_now()), "expires": _iso(exp)})
    _strip_env_token()
    if user.get("administrator") or not user.get("readonly"):
        print("Note: this account can change data on the platform. Ask Total Secure for a "
              "read-only account for the app if they offer one.", file=sys.stderr)
    print("Saved. The token is valid until %s and the app renews it every %d days. "
          "Restart the app to use it." % (exp.date(), ROTATE_DAYS))


def _status():
    store = TokenStore()
    i = store.info()
    if not store.token():
        sys.exit("No token yet. Run: python3 -m app.totalsecure token")
    left = store.days_left()
    nxt = "now (it was visible in .env)" if i["from_env"] else (
        _parse(i["created"]) + ROTATE_DAYS * DAY).date()
    print("Token saved %s, valid until %s (%s days left). Next renewal: %s." % (
        i["created"][:10], (i["expires"] or "unknown")[:10], "?" if left is None else int(left), nxt))


def _check():
    from .plan import load_plan
    devices = Client(config.TS_URL, TokenStore()).devices()
    plan, _ = load_plan()
    names = {str(d.get("name") or "").split(" ")[0]: d.get("name") for d in devices}
    print("Token works. %d devices on the platform." % len(devices))
    for vno in plan:
        print("  %-6s %s" % (vno, names.get(vno) or "no device with this fleet number"))


def main(argv):
    import argparse
    p = argparse.ArgumentParser(prog="python3 -m app.totalsecure")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("token", help="sign in once and save a new API token (replaces the current one)")
    sub.add_parser("rotate", help="renew the token now instead of waiting for the 30 days")
    sub.add_parser("status", help="when the token was made, when it expires, next renewal")
    sub.add_parser("check", help="test the token and match platform devices to the plan")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if a.cmd == "token":
            _make_token()
        elif a.cmd == "rotate":
            rotate(Client(config.TS_URL, TokenStore()), force=True)
            _status()
        elif a.cmd == "status":
            _status()
        else:
            _check()
    except ProviderError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main(sys.argv[1:])
