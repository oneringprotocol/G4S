"""Total Secure tracking platform API client (the platform runs Traccar).

Shared by every Total Secure feed: GPS positions now (sources/totalsecure_source.py),
driver behaviour reports later.

Credentials: the app holds one API token (G4S_TS_TOKEN in .env, git ignored), never
the platform password. Make the token with

    python3 -m app.totalsecure token

which asks for the email and password, keeps them only in memory, and prints a token
to paste into .env. Check it with `python3 -m app.totalsecure check`.

The token travels only in the Authorization header: never in a URL, a log line or an
error message. Requests are https only, redirects are refused (so the token cannot
follow one to another host), and every call has a timeout.
"""
import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config

log = logging.getLogger("g4s.totalsecure")

TIMEOUT_S = 30
RETRIES = 2          # extra tries on a network error or a 5xx answer
UA = "g4s-route-audit/1.0"


class ProviderError(Exception):
    """Safe to show to users: never holds the token, the password or a response body."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None   # a 3xx then surfaces as an HTTPError instead of being followed


_opener = urllib.request.build_opener(_NoRedirect)


def _check_url(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" and u.hostname not in ("localhost", "127.0.0.1"):
        raise ProviderError("G4S_TS_URL must start with https://")


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Client:
    def __init__(self, base_url, token, timeout=TIMEOUT_S):
        _check_url(base_url)
        if not token:
            raise ProviderError("Total Secure is not set up: G4S_TS_TOKEN is empty (see docs/APP.md).")
        self.base = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout

    def __repr__(self):
        return "Client(%s)" % self.base

    def get(self, path, params=None):
        url = self.base + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + self._token, "Accept": "application/json", "User-Agent": UA})
        for attempt in range(RETRIES + 1):
            try:
                with _opener.open(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise ProviderError("Total Secure refused the API token (expired or revoked). "
                                        "Make a new one with: python3 -m app.totalsecure token") from None
                if e.code < 500 or attempt == RETRIES:
                    raise ProviderError("Total Secure answered %d for %s" % (e.code, path)) from None
            except (urllib.error.URLError, OSError, ValueError) as e:
                if attempt == RETRIES:
                    raise ProviderError("Could not reach Total Secure (%s)" % type(e).__name__) from None
            time.sleep(2 * (attempt + 1))

    def devices(self):
        return self.get("/devices")

    def route(self, device_id, start, end):
        """Positions of one device from start to end (UTC), as in the tracker "Route" report."""
        return self.get("/reports/route", {"deviceId": device_id, "from": _iso(start), "to": _iso(end)})


# ---------- command line: make or check the API token ----------

def _post(url, form, cookie=None):
    headers = {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), headers=headers)
    return _opener.open(req, timeout=TIMEOUT_S)


def _make_token(days):
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
    expires = datetime.now(timezone.utc) + timedelta(days=days)
    try:
        with _post(base + "/session/token", {"expiration": _iso(expires)}, cookie) as r:
            token = r.read().decode().strip()
    finally:
        req = urllib.request.Request(base + "/session", method="DELETE", headers={"Cookie": cookie, "User-Agent": UA})
        try:
            _opener.open(req, timeout=TIMEOUT_S).close()
        except urllib.error.URLError:
            pass
    if user.get("administrator") or not user.get("readonly"):
        print("\nNote: this account can change data on the platform. Ask Total Secure for a "
              "read-only account for the app if they offer one.", file=sys.stderr)
    print("\nToken (valid until %s). Put this line in .env, then restart the app:\n" % expires.date())
    print("G4S_TS_TOKEN=" + token)


def _check():
    from .plan import load_plan
    devices = Client(config.TS_URL, config.TS_TOKEN).devices()
    plan, _ = load_plan()
    names = {str(d.get("name") or "").split(" ")[0]: d.get("name") for d in devices}
    print("Token works. %d devices on the platform." % len(devices))
    for vno in plan:
        print("  %-6s %s" % (vno, names.get(vno) or "no device with this fleet number"))


def main(argv):
    import argparse
    p = argparse.ArgumentParser(prog="python3 -m app.totalsecure")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("token", help="sign in once and print an API token for .env")
    t.add_argument("--days", type=int, default=90, help="token lifetime in days (default 90)")
    sub.add_parser("check", help="test the token in .env and match devices to the plan")
    a = p.parse_args(argv)
    try:
        _make_token(a.days) if a.cmd == "token" else _check()
    except ProviderError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main(sys.argv[1:])
