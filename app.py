import base64
import json
import os
import re
import secrets
import smtplib
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import accounts
import mail_settings

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("INVITES_DATA", ROOT / "data"))
ORIGIN = os.environ.get("PUBLIC_ORIGIN", "http://localhost:30112").rstrip("/")
SECURE = ORIGIN.startswith("https://")
MAIL_WORKERS = ThreadPoolExecutor(max_workers=2)
MAIL_SLOTS = threading.BoundedSemaphore(10)
TOKEN = r"[A-Za-z0-9_-]{20,64}"
TEMPLATES = {
    "wedding": dict(title="Amelia & Oliver", intro="Together with their families",
                    date="2027-06-19", time="14:00", venue="A country house in Cheshire",
                    message="Join us for a summer wedding and an evening of dancing.",
                    colour="#4c5631", meal="Roast chicken\nMushroom wellington", song=True),
    "birthday": dict(title="Leo turns 6!", intro="You're invited", date="2027-07-11",
                     time="13:00", venue="The party garden", colour="#315238",
                     message="Come stomp, roar and celebrate with us!", meal="", song=False),
    "black-tie": dict(title="Thea & Rowan", intro="Together with their families",
                      date="2027-10-16", time="17:00", venue="The Ballroom", colour="#34352f",
                      message="Join us for our wedding ceremony, dinner and dancing. Black tie.",
                      meal="Roast chicken\nWild mushroom risotto", song=True),
    "disco": dict(title="Frankie turns 30", intro="You're invited", date="2027-09-04",
                  time="19:30", venue="The Glitter Room", colour="#673584",
                  message="Come for a drink, stay for a dance. A little sparkle is very welcome.",
                  meal="", song=True),
}
DEMO_KEYS = "|".join(re.escape(key) for key in TEMPLATES)
STATIC_TYPES = {"app.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
                "wedding.webp": "image/webp", "birthday.webp": "image/webp"}
HOST_PAGES = {"/", "/editor", "/admin", "/admin/mail", "/admin/mail-setup",
              "/account/signup", "/account/setup", "/account/forgot", "/account/reset"}
UK = ZoneInfo("Europe/London")


class ClientError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status


@contextmanager
def db():
    connection = sqlite3.connect(DATA / "invites.sqlite3", timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def setup():
    DATA.mkdir(parents=True, exist_ok=True)
    with db() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, details TEXT NOT NULL, photo BLOB
            );
            CREATE TABLE IF NOT EXISTS households (
                token TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id),
                label TEXT NOT NULL, names TEXT NOT NULL, reply TEXT, replied_at TEXT
            );
            CREATE INDEX IF NOT EXISTS households_by_event ON households(event_id);
        """)
        accounts.migrate(connection)


def string(data, key, limit, required=False):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ClientError(f"Check the {key} field.")
    value = value.strip()
    if required and not value:
        raise ClientError(f"Enter {key}.")
    return value


def event_details(data):
    template = string(data, "template", 20, True)
    colour = string(data, "colour", 7, True)
    if template not in TEMPLATES or not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
        raise ClientError("Choose a design and a valid colour.")
    day = string(data, "date", 10, True)
    clock = string(data, "time", 5)
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError
        date.fromisoformat(day)
        if clock:
            datetime.strptime(clock, "%H:%M")
            if not re.fullmatch(r"\d{2}:\d{2}", clock):
                raise ValueError
    except ValueError as error:
        raise ClientError("Enter a valid date and time.") from error
    return dict(template=template, colour=colour, date=day, time=clock,
                title=string(data, "title", 90, True), intro=string(data, "intro", 90),
                venue=string(data, "venue", 180, True), message=string(data, "message", 1200),
                meal="\n".join(line.strip() for line in string(data, "meal", 500).splitlines() if line.strip()),
                song=data.get("song") is True)


def photo_bytes(data):
    encoded = data.get("photo")
    if encoded is None:
        return None
    if not isinstance(encoded, str) or len(encoded) > 1_000_000:
        raise ClientError("Choose a smaller photo.")
    try:
        photo = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ClientError("Choose a valid photo.") from error
    if not photo.startswith(b"\xff\xd8\xff") or not photo.endswith(b"\xff\xd9"):
        raise ClientError("Choose a JPEG photo.")
    return photo


def event_row(connection, event_id, account_id=None):
    if account_id is None:
        row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    else:
        row = connection.execute("SELECT * FROM events WHERE id = ? AND account_id = ?",
                                 (event_id, account_id)).fetchone()
    if row is None:
        raise ClientError("Invitation not found.", 404)
    return row


def guest_row(connection, token):
    row = connection.execute("""
        SELECT h.*, e.details, e.photo IS NOT NULL AS has_photo
        FROM households h JOIN events e ON e.id = h.event_id
        LEFT JOIN accounts a ON a.id = e.account_id
        WHERE h.token = ? AND (e.account_id IS NULL OR a.access IN ('free', 'paid'))
    """, (token,)).fetchone()
    if row is None:
        raise ClientError("Invitation link not found.", 404)
    return row


def guest_details(connection, token):
    if token in TEMPLATES:
        return dict(event=dict(TEMPLATES[token], template=token), demo=True,
                    label="The Smith family" if token in {"wedding", "black-tie"} else "Sam & Jamie",
                    names=["Sam", "Jamie"], answered=False)
    row = guest_row(connection, token)
    return dict(event=json.loads(row["details"]), demo=False, label=row["label"],
                names=json.loads(row["names"]), answered=row["reply"] is not None,
                photo=f"/photo/{token}" if row["has_photo"] else "")


def household_details(row):
    return dict(token=row["token"], label=row["label"], names=json.loads(row["names"]),
                reply=json.loads(row["reply"]) if row["reply"] else None)


def save_reply(connection, token, data):
    guest = guest_details(connection, token)
    answers = data.get("people")
    if not isinstance(answers, list) or len(answers) != len(guest["names"]):
        raise ClientError("Reply for each guest.")
    event = guest["event"]
    meals = set(event["meal"].splitlines())
    people = []
    for name, answer in zip(guest["names"], answers):
        if not isinstance(answer, dict) or answer.get("status") not in ("yes", "no"):
            raise ClientError("Choose attending or unable to attend for each guest.")
        attending = answer["status"] == "yes"
        meal = string(answer, "meal", 500) if attending else ""
        if meal and meal not in meals:
            raise ClientError("Choose one of the listed meals.")
        people.append(dict(name=name, status=answer["status"], meal=meal,
                           dietary=string(answer, "dietary", 160) if attending and meals else ""))
    reply = dict(people=people, song=string(data, "song", 120)
                 if event["song"] and any(p["status"] == "yes" for p in people) else "")
    if not guest["demo"]:
        connection.execute("UPDATE households SET reply = ?, replied_at = CURRENT_TIMESTAMP WHERE token = ?",
                           (json.dumps(reply), token))


def calendar(event):
    def escape(value):
        return (value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
                .replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,"))
    if event["time"]:
        local = datetime.fromisoformat(f'{event["date"]}T{event["time"]}').replace(tzinfo=UK)
        start = "DTSTART:" + local.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    else:
        start = "DTSTART;VALUE=DATE:" + event["date"].replace("-", "")
    return "\r\n".join(("BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Ivory Digital//Ivory Invites//EN",
                        "BEGIN:VEVENT", f'UID:{event["calendar_id"]}@ivory-invites',
                        "DTSTAMP:" + datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ"),
                        start, "SUMMARY:" + escape(event["title"]), "LOCATION:" + escape(event["venue"]),
                        "DESCRIPTION:" + escape(event["message"]), "END:VEVENT", "END:VCALENDAR", ""))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Guest and editor URLs can carry private identifiers.
        pass

    def send(self, body, content_type, status=200, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob: data:; "
                         "style-src 'self' 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def json(self, value, status=200, headers=()):
        self.send(json.dumps(value).encode(), "application/json", status, headers)

    def session_token(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            return cookies["ivory"].value
        except (KeyError, CookieError):
            return ""

    @staticmethod
    def cookie(value, max_age):
        secure = "; Secure" if SECURE else ""
        return ("Set-Cookie", f"ivory={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}")

    def read_json(self):
        if self.headers.get("Origin") not in (None, ORIGIN):
            raise ClientError("Open Ivory Invites at its configured address.", 403)
        if self.headers.get_content_type() != "application/json":
            raise ClientError("Expected JSON.", 415)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1_100_000:
                raise ClientError("The request is too large or empty.", 413)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, UnicodeError) as error:
            raise ClientError("The request could not be read.") from error

    def account_route(self, path, data):
        email = accounts.email_address(data.get("email"))
        if path in ("/api/account/signup", "/api/account/forgot"):
            if path.endswith("/signup") and email != accounts.OWNER_EMAIL:
                self.json({"ok": True}, 202)
                return
            if not mail_settings.public_config()["configured"]:
                raise ClientError("Account email has not been configured.", 503)
            accounts.limit("mail", email)
            if not MAIL_SLOTS.acquire(blocking=False):
                raise ClientError("Account email is busy. Try again shortly.", 503)
            purpose = "signup" if path.endswith("/signup") else "reset"
            task = MAIL_WORKERS.submit(accounts.deliver_link, db, email, purpose, ORIGIN)
            task.add_done_callback(lambda _: MAIL_SLOTS.release())
            self.json({"ok": True}, 202)
            return
        logging_in = path == "/api/login"
        accounts.limit("login" if logging_in else "setup", email)
        password = accounts.password_value(data.get("password"), new=not logging_in)
        with db() as connection:
            if logging_in:
                session = accounts.login(connection, email, password)
            else:
                purpose = "signup" if path.endswith("/setup") else "reset"
                session = accounts.complete(connection, email, password, data.get("token"), purpose)
            accounts.end_session(connection, self.session_token())
        cookie = self.cookie(session or "", accounts.SESSION_AGE if session else 0)
        self.json({"ok": True}, headers=[cookie])

    def admin_action(self, path, data):
        with db() as connection:
            self.require_admin(connection, self.require_host(connection))
            email = accounts.email_address(data.get("email"))
            access = data.get("access")
            if email == accounts.OWNER_EMAIL or access not in accounts.ACCESS:
                raise ClientError("Choose a customer email and an access level.")
            if path == "/api/admin/access":
                accounts.change_access(connection, email, access)
            else:
                if not mail_settings.public_config()["configured"]:
                    raise ClientError("Set up SMTP in Admin before sending a setup link.", 503)
                token = accounts.prepare_customer(connection, email, access)
        if path == "/api/admin/access":
            self.json({"ok": True})
            return
        try:
            accounts.send_link(email, "signup", token, ORIGIN)
        except (OSError, smtplib.SMTPException) as error:
            with db() as connection:
                connection.execute("DELETE FROM account_links WHERE token_hash = ?", (accounts.token_hash(token),))
            raise ClientError("Email could not be sent. Check the mailbox settings, then try again.", 502) from error
        with db() as connection:
            connection.execute("UPDATE customer_invites SET sent_at = strftime('%s','now') WHERE email = ?", (email,))
        self.json({"ok": True})

    def do_GET(self):
        self.handle_request(False)

    def do_POST(self):
        self.handle_request(True)

    def handle_request(self, writing):
        try:
            path = urlsplit(self.path).path
            if writing:
                self.write_route(path, self.read_json())
            else:
                self.read_route(path)
        except (ClientError, accounts.AccountError, mail_settings.MailSettingsError) as error:
            self.json({"error": error.message}, error.status)
        except (BrokenPipeError, ConnectionResetError):
            return

    def read_route(self, path):
        if path == "/health":
            self.json({"ok": True})
            return
        if path.startswith("/static/") and path[8:] in STATIC_TYPES:
            name = path[8:]
            self.send((ROOT / "static" / name).read_bytes(), STATIC_TYPES[name])
            return
        if path in HOST_PAGES or re.fullmatch(fr"/(?:invite/{TOKEN}|demo/(?:{DEMO_KEYS}))", path):
            self.send((ROOT / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        match = re.fullmatch(fr"/(api/guest|calendar|photo)/({TOKEN}|{DEMO_KEYS})", path)
        if match:
            action, token = match.groups()
            with db() as connection:
                if action == "photo":
                    row = guest_row(connection, token)
                    photo = event_row(connection, row["event_id"])["photo"]
                    if not photo:
                        raise ClientError("Photo not found.", 404)
                    self.send(photo, "image/jpeg")
                    return
                guest = guest_details(connection, token)
                if action == "calendar":
                    event = guest["event"]
                    event["calendar_id"] = token if guest["demo"] else guest_row(connection, token)["event_id"]
                    self.send(calendar(event).encode(), "text/calendar; charset=utf-8",
                              headers=[("Content-Disposition", 'attachment; filename="invitation.ics"')])
                else:
                    self.json(guest)
            return
        if path == "/api/session":
            with db() as connection:
                account_id = accounts.session_account(connection, self.session_token())
                profile = accounts.profile(connection, account_id) if account_id is not None else None
                if profile:
                    result = dict(signedIn=True, admin=profile["email"] == accounts.OWNER_EMAIL,
                                  access=profile["access"])
                else:
                    owner = connection.execute("SELECT 1 FROM accounts WHERE email = ?",
                                               (accounts.OWNER_EMAIL,)).fetchone()
                    result = dict(signedIn=False, ownerSetup=owner is None)
            self.json(result)
            return
        with db() as connection:
            account_id = self.require_host(connection)
            if path == "/api/admin/customers":
                self.require_admin(connection, account_id)
                self.json(accounts.customers(connection))
                return
            if path == "/api/admin/mail":
                self.require_admin(connection, account_id)
                self.json(mail_settings.public_config())
                return
            if path == "/api/events":
                rows = connection.execute("SELECT id, details FROM events WHERE account_id = ? ORDER BY rowid DESC",
                                          (account_id,))
                self.json([dict(id=row["id"], **json.loads(row["details"])) for row in rows])
                return
            match = re.fullmatch(fr"/api/events/({TOKEN})(/photo)?", path)
            if match:
                event_id, photo_request = match.groups()
                event = event_row(connection, event_id, account_id)
                if photo_request:
                    if not event["photo"]:
                        raise ClientError("Photo not found.", 404)
                    self.send(event["photo"], "image/jpeg")
                    return
                can_share = accounts.profile(connection, account_id)["access"] != "trial"
                rows = connection.execute("SELECT * FROM households WHERE event_id = ? ORDER BY rowid",
                                          (event_id,)) if can_share else ()
                self.json(dict(id=event_id, **json.loads(event["details"]),
                               hasPhoto=event["photo"] is not None,
                               canShare=can_share,
                               households=[household_details(row) for row in rows]))
                return
        raise ClientError("Page not found.", 404)

    def require_host(self, connection):
        account_id = accounts.session_account(connection, self.session_token())
        if account_id is None:
            raise ClientError("Sign in to manage invitations.", 401)
        return account_id

    @staticmethod
    def require_admin(connection, account_id):
        if accounts.profile(connection, account_id)["email"] != accounts.OWNER_EMAIL:
            raise ClientError("Administrator access is required.", 403)

    def write_route(self, path, data):
        if path in {"/api/login", "/api/account/signup", "/api/account/setup",
                    "/api/account/forgot", "/api/account/reset"}:
            self.account_route(path, data)
            return
        if path in {"/api/admin/invite", "/api/admin/access"}:
            self.admin_action(path, data)
            return
        if path in {"/api/admin/mail", "/api/admin/mail/setup"}:
            bootstrap = path.endswith("/setup")
            if bootstrap:
                accounts.limit("mail-setup", "setup")
            else:
                with db() as connection:
                    self.require_admin(connection, self.require_host(connection))
            mail_settings.configure(data, bootstrap=bootstrap)
            self.json({"ok": True})
            return
        match = re.fullmatch(fr"/api/guest/({TOKEN}|{DEMO_KEYS})", path)
        if match:
            with db() as connection:
                if match[1] not in TEMPLATES:
                    connection.execute("BEGIN IMMEDIATE")
                save_reply(connection, match[1], data)
            self.json({"ok": True})
            return
        if path == "/api/logout":
            with db() as connection:
                accounts.end_session(connection, self.session_token())
            self.json({"ok": True}, headers=[self.cookie("", 0)])
            return
        match = re.fullmatch(fr"/api/events(?:/({TOKEN})(/households)?)?", path)
        if not match:
            raise ClientError("Page not found.", 404)
        event_id, household = match.groups()
        with db() as connection:
            if household:
                connection.execute("BEGIN IMMEDIATE")
            account_id = self.require_host(connection)
            if event_id:
                event_row(connection, event_id, account_id)
            if household:
                if accounts.profile(connection, account_id)["access"] == "trial":
                    raise ClientError("Trial access is for designing and previewing invitations.", 403)
                label = string(data, "household name", 100, True)
                names = [name.strip() for name in string(data, "guest names", 800, True).splitlines()
                         if name.strip()]
                if not 1 <= len(names) <= 12 or any(len(name) > 80 for name in names):
                    raise ClientError("Enter one to twelve guest names, one per line.")
                token = secrets.token_urlsafe(24)
                connection.execute("INSERT INTO households (token, event_id, label, names) VALUES (?, ?, ?, ?)",
                                   (token, event_id, label, json.dumps(names)))
                response = {"token": token}
            else:
                details = json.dumps(event_details(data))
                photo = photo_bytes(data)
                if event_id:
                    connection.execute("UPDATE events SET details = ? WHERE id = ?", (details, event_id))
                    if photo is not None or data.get("removePhoto") is True:
                        connection.execute("UPDATE events SET photo = ? WHERE id = ?", (photo, event_id))
                else:
                    event_id = secrets.token_urlsafe(20)
                    connection.execute("INSERT INTO events (id, details, photo, account_id) VALUES (?, ?, ?, ?)",
                                       (event_id, details, photo, account_id))
                response = {"id": event_id}
        self.json(response)


if __name__ == "__main__":
    os.umask(0o077)
    mail_settings.setup()
    if sys.argv[1:] == ["mail-setup-code"]:
        print(mail_settings.new_code())
        sys.exit(0)
    setup()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "30112"))), Handler).serve_forever()
