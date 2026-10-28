"""Accounts: sign up, admin approval, sign in, sessions, vehicle access.

Storage is SQLite (data/app.db). Passwords are salted PBKDF2 SHA256 hashes.
Sessions are random tokens in an HttpOnly cookie; only their SHA256 is stored.

Account life cycle:
  sign up -> status 'pending' -> admin gets an email -> approve / reject in /admin
  Only 'approved' accounts can sign in. The admin account is created once at
  /setup with a one time setup code printed in the server log.
"""
import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
import threading
import time
from html import escape

from . import config, mailer

log = logging.getLogger("g4s.auth")
_lock = threading.Lock()
EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PBKDF2_ITER = 600_000
COOKIE = "g4s_session"


def _db():
    con = sqlite3.connect(config.DB_FILE, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init():
    config.DATA.mkdir(parents=True, exist_ok=True)
    with _db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            company TEXT,
            phone TEXT,
            pw_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',          -- 'admin' | 'user'
            status TEXT NOT NULL DEFAULT 'pending',     -- 'pending' | 'approved' | 'rejected'
            created_at INTEGER NOT NULL,
            decided_at INTEGER,
            last_login INTEGER);
        CREATE TABLE IF NOT EXISTS sessions(
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires INTEGER NOT NULL);
        DROP TABLE IF EXISTS password_resets;          -- self service reset was removed
        CREATE TABLE IF NOT EXISTS user_vehicles(
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            vehicle TEXT NOT NULL,
            PRIMARY KEY(user_id, vehicle));
        """)
        if "ops" not in [r["name"] for r in con.execute("PRAGMA table_info(users)")]:
            con.execute("ALTER TABLE users ADD COLUMN ops INTEGER NOT NULL DEFAULT 0")   # 1 = operations team
    if not admin_exists():
        log.warning("No admin account yet. Open %s/setup and use setup code: %s", config.BASE_URL, setup_code())


# ---------- passwords and tokens ----------
def hash_password(pw):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITER)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ITER, salt.hex(), dk.hex())


def check_password(pw, stored):
    try:
        _, it, salt, dk = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(got.hex(), dk)
    except Exception:
        return False


_DUMMY = hash_password(secrets.token_hex(8))   # equal timing for unknown emails


def password_problem(pw):
    if len(pw or "") < config.PASSWORD_MIN:
        return "Use at least %d characters." % config.PASSWORD_MIN
    if pw.isdigit() or pw.isalpha():
        return "Use a mix of letters and numbers or symbols."
    return None


def setup_code():
    """One time code that proves the person creating the admin can read the server log."""
    f = config.DATA / "setup_code.txt"
    if not f.exists():
        f.write_text(secrets.token_hex(4).upper())
        f.chmod(0o600)
    return f.read_text().strip()


# ---------- users ----------
def _row(r):
    return dict(r) if r else None


def user_by_email(email):
    with _db() as con:
        return _row(con.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone())


def user_by_id(uid):
    with _db() as con:
        return _row(con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


def admin_exists():
    with _db() as con:
        return con.execute("SELECT 1 FROM users WHERE role='admin'").fetchone() is not None


def public(u):
    return {k: u[k] for k in ("id", "email", "name", "company", "phone", "role", "status", "created_at", "decided_at", "last_login", "ops")}


class AuthError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def create_admin(password, code):
    if admin_exists():
        raise AuthError("The admin account already exists.", 409)
    if not hmac.compare_digest((code or "").strip().upper(), setup_code()):
        raise AuthError("The setup code is not correct. It is printed in the server log.", 403)
    p = password_problem(password)
    if p:
        raise AuthError(p)
    with _lock, _db() as con:
        con.execute("DELETE FROM users WHERE email=?", (config.ADMIN_EMAIL,))   # a pending sign up with the admin email
        con.execute("INSERT INTO users(email,name,company,pw_hash,role,status,created_at,decided_at) "
                    "VALUES(?,?,?,?,'admin','approved',?,?)",
                    (config.ADMIN_EMAIL, "Admin", "Swvl", hash_password(password), int(time.time()), int(time.time())))
    (config.DATA / "setup_code.txt").unlink(missing_ok=True)
    return user_by_email(config.ADMIN_EMAIL)


def signup(email, password, name, company, phone):
    email = (email or "").strip().lower()
    name, company, phone = (name or "").strip(), (company or "").strip(), (phone or "").strip()
    if not EMAIL_RX.match(email) or len(email) > 200:
        raise AuthError("Enter a valid email address.")
    if not name or len(name) > 120:
        raise AuthError("Enter your full name.")
    if not company or len(company) > 120:
        raise AuthError("Enter your company.")
    if len(phone) > 40:
        raise AuthError("The phone number is too long.")
    if email == config.ADMIN_EMAIL:
        raise AuthError("This email is reserved for the admin account.")
    p = password_problem(password)
    if p:
        raise AuthError(p)
    with _lock, _db() as con:
        old = con.execute("SELECT status FROM users WHERE email=?", (email,)).fetchone()
        if old and old["status"] != "rejected":
            raise AuthError("An account with this email already exists.", 409)
        if old:   # a rejected user may apply again
            con.execute("DELETE FROM users WHERE email=?", (email,))
        con.execute("INSERT INTO users(email,name,company,phone,pw_hash,created_at) VALUES(?,?,?,?,?,?)",
                    (email, name, company, phone, hash_password(password), int(time.time())))
    u = user_by_email(email)
    _notify_admin(u)
    return u


def _notify_admin(u):
    link = "%s/admin?review=%d" % (config.BASE_URL, u["id"])
    when = time.strftime("%a %d %b %Y %H:%M", time.localtime(u["created_at"]))
    rows = [("Name", u["name"]), ("Email", u["email"]), ("Company", u["company"]),
            ("Phone", u["phone"] or "not given"), ("Signed up", when)]
    text = ("A new account is waiting for your approval on G4S Route Audit.\n\n"
            + "\n".join("%s: %s" % r for r in rows)
            + "\n\nApprove or reject it here: %s\n\nThe account cannot sign in until you approve it.\n" % link)
    html = ("<p>A new account is waiting for your approval on <b>G4S Route Audit</b>.</p><table cellpadding='4'>"
            + "".join("<tr><td style='color:#7a7974'>%s</td><td><b>%s</b></td></tr>" % (k, escape(str(v))) for k, v in rows)
            + "</table><p><a href='%s' style='display:inline-block;background:#0a6b0a;color:#fff;padding:9px 16px;"
              "border-radius:8px;text-decoration:none;font-weight:600'>Review the account</a></p>"
              "<p style='color:#7a7974'>The account cannot sign in until you approve it.</p>" % escape(link))
    mailer.send(config.ADMIN_EMAIL, "New account to approve: %s (%s)" % (u["name"], u["company"]), text, html)


def decide(uid, approve):
    u = user_by_id(uid)
    if not u or u["role"] == "admin":
        raise AuthError("Account not found.", 404)
    status = "approved" if approve else "rejected"
    with _db() as con:
        con.execute("UPDATE users SET status=?, decided_at=? WHERE id=?", (status, int(time.time()), uid))
        if not approve:
            con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    if approve:
        mailer.send(u["email"], "Your G4S Route Audit account is approved",
                    "Hello %s,\n\nYour account is approved. Sign in here: %s/login\n" % (u["name"], config.BASE_URL))
    return user_by_id(uid)


def delete_user(uid):
    u = user_by_id(uid)
    if not u or u["role"] == "admin":
        raise AuthError("Account not found.", 404)
    with _db() as con:
        con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        con.execute("DELETE FROM user_vehicles WHERE user_id=?", (uid,))
        con.execute("DELETE FROM users WHERE id=?", (uid,))


def list_users():
    with _db() as con:
        users = [public(dict(r)) for r in con.execute("SELECT * FROM users ORDER BY status='pending' DESC, created_at DESC")]
        acc = {}
        for r in con.execute("SELECT user_id, vehicle FROM user_vehicles ORDER BY vehicle"):
            acc.setdefault(r["user_id"], []).append(r["vehicle"])
    for u in users:
        u["vehicles"] = acc.get(u["id"], [])
    return users


# ---------- password changes (admin only) ----------
def set_password(uid, password, keep_token=None):
    """The admin sets a new password for any account. The account is signed out
    everywhere, except the admin session that made the change."""
    p = password_problem(password)
    if p:
        raise AuthError(p)
    u = user_by_id(uid)
    if not u:
        raise AuthError("Account not found.", 404)
    with _db() as con:
        con.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(password), uid))
        con.execute("DELETE FROM sessions WHERE user_id=? AND token_hash != ?",
                    (uid, hashlib.sha256((keep_token or "").encode()).hexdigest()))


# ---------- vehicle access ----------
def vehicles_for(u):
    """None means all vehicles (admin); otherwise the set of vehicle numbers the user may see."""
    if u["role"] == "admin":
        return None
    with _db() as con:
        return {r["vehicle"] for r in con.execute("SELECT vehicle FROM user_vehicles WHERE user_id=?", (u["id"],))}


def set_vehicles(uid, vehicles):
    u = user_by_id(uid)
    if not u or u["role"] == "admin":
        raise AuthError("Account not found.", 404)
    with _db() as con:
        con.execute("DELETE FROM user_vehicles WHERE user_id=?", (uid,))
        con.executemany("INSERT INTO user_vehicles(user_id, vehicle) VALUES(?,?)",
                        [(uid, str(v)) for v in sorted(set(vehicles))])


def can_ops(u):
    """The Operations tab (internal vehicle directory and replacement log): admin and the operations team."""
    return u["role"] == "admin" or bool(u.get("ops"))


def set_ops(uid, on):
    u = user_by_id(uid)
    if not u or u["role"] == "admin":
        raise AuthError("Account not found.", 404)
    with _db() as con:
        con.execute("UPDATE users SET ops=? WHERE id=?", (1 if on else 0, uid))


# ---------- sign in and sessions ----------
_fails = {}   # (email, ip) -> [timestamps]


def login(email, password, ip):
    email = (email or "").strip().lower()
    key, now = (email, ip), time.time()
    recent = [t for t in _fails.get(key, []) if now - t < 900]
    if len(recent) >= 5:
        raise AuthError("Too many attempts. Try again in 15 minutes.", 429)
    u = user_by_email(email)
    ok = check_password(password or "", u["pw_hash"] if u else _DUMMY)
    if not u or not ok:
        _fails[key] = recent + [now]
        raise AuthError("Email or password is not correct.", 401)
    _fails.pop(key, None)
    if u["status"] == "pending":
        raise AuthError("Your account is waiting for admin approval. You will get an email once it is approved.", 403)
    if u["status"] != "approved":
        raise AuthError("Your account was not approved. Contact the admin for access.", 403)
    token = secrets.token_urlsafe(32)
    with _db() as con:
        con.execute("DELETE FROM sessions WHERE expires < ?", (int(now),))
        con.execute("INSERT INTO sessions VALUES(?,?,?)",
                    (hashlib.sha256(token.encode()).hexdigest(), u["id"], int(now + config.SESSION_DAYS * 86400)))
        con.execute("UPDATE users SET last_login=? WHERE id=?", (int(now), u["id"]))
    return token, u


def session_user(token):
    if not token:
        return None
    with _db() as con:
        r = con.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
                        "WHERE s.token_hash=? AND s.expires>? AND u.status='approved'",
                        (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
    return _row(r)


def logout(token):
    if token:
        with _db() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
