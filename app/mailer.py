"""Outgoing email.

Sends through SMTP when G4S_SMTP_HOST is set (port 465 = SSL, 587 = STARTTLS).
The macOS system Python cannot always complete a TLS handshake, so curl is the
fallback. With no SMTP settings the message is saved to data/outbox/ as .eml.
Sending runs in a background thread so a slow mail server never blocks a request.
"""
import logging
import smtplib
import subprocess
import tempfile
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import config

log = logging.getLogger("g4s.mail")


def _message(to, subject, text, html=None):
    m = EmailMessage()
    m["From"] = "G4S Route Audit <%s>" % (config.SMTP_FROM or "no-reply@localhost")
    m["To"] = to
    m["Subject"] = subject
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid()
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype="html")
    return m


def _smtp(m):
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, 465, timeout=20) as s:
            s.login(config.SMTP_USER, config.SMTP_PASS)
            s.send_message(m)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASS)
            s.send_message(m)


def _curl(m, to):
    scheme = "smtps" if config.SMTP_PORT == 465 else "smtp"
    with tempfile.NamedTemporaryFile(suffix=".eml") as f:
        f.write(bytes(m))
        f.flush()
        cmd = ["curl", "-sS", "--url", "%s://%s:%d" % (scheme, config.SMTP_HOST, config.SMTP_PORT),
               "--user", "%s:%s" % (config.SMTP_USER, config.SMTP_PASS),
               "--mail-from", config.SMTP_FROM, "--mail-rcpt", to, "--upload-file", f.name]
        if scheme == "smtp":
            cmd.insert(2, "--ssl-reqd")
        out = subprocess.run(cmd, capture_output=True, timeout=40)
        if out.returncode:
            raise RuntimeError(out.stderr.decode(errors="replace").strip())


def _save(m):
    config.OUTBOX.mkdir(parents=True, exist_ok=True)
    f = config.OUTBOX / ("%d_%s.eml" % (time.time() * 1000, m["To"].replace("@", "_at_")))
    f.write_bytes(bytes(m))
    return f


def _deliver(m, to):
    if not config.SMTP_HOST:
        f = _save(m)
        log.warning("SMTP not configured: email to %s saved to %s", to, f)
        return
    try:
        _smtp(m)
    except Exception as e:
        log.info("smtplib failed (%s), trying curl", e)
        try:
            _curl(m, to)
        except Exception as e2:
            f = _save(m)
            log.error("Email to %s could not be sent (%s); saved to %s", to, e2, f)
            return
    log.info("Email sent to %s: %s", to, m["Subject"])


def send(to, subject, text, html=None):
    m = _message(to, subject, text, html)
    threading.Thread(target=_deliver, args=(m, to), daemon=True).start()
