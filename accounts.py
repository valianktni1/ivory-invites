import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
import time
from collections import deque
from email.message import EmailMessage
from pathlib import Path

SENDER = "admin@ivorydigital.uk"
OWNER_EMAIL = os.environ.get("INVITES_OWNER_EMAIL", SENDER).strip().lower()
SMTP_HOST = os.environ.get("INVITES_SMTP_HOST", "smtp.hostinger.com")
SMTP_PORT = int(os.environ.get("INVITES_SMTP_PORT", "465"))
SMTP_PASSWORD_FILE = os.environ.get("INVITES_SMTP_PASSWORD_FILE")
SMTP_PASSWORD = (Path(SMTP_PASSWORD_FILE).read_text().removesuffix("\n") if SMTP_PASSWORD_FILE
                 else os.environ.get("INVITES_SMTP_PASSWORD", ""))
SESSION_AGE = 12 * 60 * 60
LINK_AGE = 30 * 60
TOKEN = r"[A-Za-z0-9_-]{43}"
EMAIL = r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+"
LIMIT_LOCK = threading.Lock()
HASH_SLOTS = threading.BoundedSemaphore(3)
LIMITS = {"login": (8, 120), "mail": (2, 24), "setup": (10, 60)}
ATTEMPTS = {name: deque() for name in LIMITS}
ACCESS = ("free", "trial", "paid")


class AccountError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status


def migrate(connection):
    connection.executescript("""
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,
            salt BLOB NOT NULL, password_hash BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS account_links (
            token_hash BLOB PRIMARY KEY, email TEXT NOT NULL,
            purpose TEXT NOT NULL, expires INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS account_sessions (
            token_hash BLOB PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
            expires INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS account_sessions_by_owner ON account_sessions(account_id);
        CREATE TABLE IF NOT EXISTS customer_invites (
            email TEXT PRIMARY KEY, access TEXT NOT NULL, sent_at INTEGER
        );
    """)
    if "access" not in {row["name"] for row in connection.execute("PRAGMA table_info(accounts)")}:
        connection.execute("ALTER TABLE accounts ADD COLUMN access TEXT NOT NULL DEFAULT 'trial'")
    connection.execute("UPDATE accounts SET access = 'free' WHERE email = ?", (OWNER_EMAIL,))
    if "account_id" not in {row["name"] for row in connection.execute("PRAGMA table_info(events)")}:
        connection.execute("ALTER TABLE events ADD COLUMN account_id INTEGER REFERENCES accounts(id)")
    connection.execute("CREATE INDEX IF NOT EXISTS events_by_owner ON events(account_id)")


def email_address(value):
    email = value.strip().lower() if isinstance(value, str) else ""
    if not 3 <= len(email) <= 254 or not re.fullmatch(EMAIL, email):
        raise AccountError("Enter a valid email address.")
    return email


def password_value(value, new=False):
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or not value.isprintable():
        raise AccountError("Enter a valid password.")
    if new and (len(value) < 8 or not any(not c.isalnum() and not c.isspace() for c in value)):
        raise AccountError("Use at least 8 characters and include a special character.")
    return value


def limit(action, email):
    per_email, total = LIMITS[action]
    with LIMIT_LOCK:
        history = ATTEMPTS[action]
        now = time.monotonic()
        while history and history[0][0] <= now - 60:
            history.popleft()
        if len(history) >= total or sum(address == email for _, address in history) >= per_email:
            raise AccountError("Too many attempts. Try again in a minute.", 429)
        history.append((now, email))


def password_hash(password, salt):
    if not HASH_SLOTS.acquire(timeout=2):
        raise AccountError("Sign-in is busy. Try again shortly.", 503)
    try:
        return hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=3,
                              maxmem=64 * 1024 * 1024)
    finally:
        HASH_SLOTS.release()


def token_hash(token):
    return hashlib.sha256(token.encode("ascii")).digest()


def session_account(connection, token):
    if not re.fullmatch(TOKEN, token):
        return None
    row = connection.execute(
        "SELECT account_id FROM account_sessions WHERE token_hash = ? AND expires > ?",
        (token_hash(token), int(time.time()))).fetchone()
    return row["account_id"] if row else None


def start_session(connection, account_id):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    connection.execute("DELETE FROM account_sessions WHERE expires <= ?", (now,))
    connection.execute("INSERT INTO account_sessions VALUES (?, ?, ?)",
                       (token_hash(token), account_id, now + SESSION_AGE))
    return token


def end_session(connection, token):
    if re.fullmatch(TOKEN, token):
        connection.execute("DELETE FROM account_sessions WHERE token_hash = ?", (token_hash(token),))


def login(connection, email, password):
    row = connection.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
    salt = row["salt"] if row else bytes(16)
    expected = row["password_hash"] if row else bytes(64)
    verified = hmac.compare_digest(password_hash(password, salt), expected)
    if row is None or not verified:
        raise AccountError("The email or password is incorrect.", 401)
    # A reset that completed during hashing must invalidate this login attempt.
    connection.execute("BEGIN IMMEDIATE")
    current = connection.execute("SELECT password_hash FROM accounts WHERE id = ?", (row["id"],)).fetchone()
    if current is None or not hmac.compare_digest(current["password_hash"], expected):
        raise AccountError("The email or password is incorrect.", 401)
    return start_session(connection, row["id"])


def issue_link(connection, email, purpose):
    connection.execute("BEGIN IMMEDIATE")
    account = connection.execute("SELECT id FROM accounts WHERE email = ?", (email,)).fetchone()
    if (purpose == "reset") != bool(account):
        return None
    if purpose == "signup" and email != OWNER_EMAIL and customer_invite(connection, email) is None:
        return None
    return create_link(connection, email, purpose)


def create_link(connection, email, purpose):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    connection.execute("DELETE FROM account_links WHERE expires <= ?", (now,))
    connection.execute("INSERT INTO account_links VALUES (?, ?, ?, ?)",
                       (token_hash(token), email, purpose, now + LINK_AGE))
    return token


def require_link(connection, digest, email, purpose):
    row = connection.execute("""
        SELECT 1 FROM account_links WHERE token_hash = ? AND email = ? AND purpose = ? AND expires > ?
    """, (digest, email, purpose, int(time.time()))).fetchone()
    if row is None:
        raise AccountError("This link has expired, has been used, or belongs to a different email address.")


def complete(connection, email, password, token, purpose):
    if not isinstance(token, str) or not re.fullmatch(TOKEN, token):
        raise AccountError("Open the link from your email and try again.")
    digest = token_hash(token)
    require_link(connection, digest, email, purpose)
    salt = secrets.token_bytes(16)
    hashed = password_hash(password, salt)
    connection.execute("BEGIN IMMEDIATE")
    require_link(connection, digest, email, purpose)
    account = connection.execute("SELECT id FROM accounts WHERE email = ?", (email,)).fetchone()
    if purpose == "signup" and account is None:
        invite = customer_invite(connection, email)
        if email != OWNER_EMAIL and invite is None:
            raise AccountError("This setup link is no longer valid.")
        account_id = connection.execute(
            "INSERT INTO accounts (email, salt, password_hash, access) VALUES (?, ?, ?, ?)",
            (email, salt, hashed, "free" if email == OWNER_EMAIL else invite["access"])).lastrowid
        if email == OWNER_EMAIL:
            connection.execute("UPDATE events SET account_id = ? WHERE account_id IS NULL", (account_id,))
        connection.execute("DELETE FROM customer_invites WHERE email = ?", (email,))
        session = start_session(connection, account_id)
    elif purpose == "reset" and account:
        connection.execute("UPDATE accounts SET salt = ?, password_hash = ? WHERE id = ?",
                           (salt, hashed, account["id"]))
        connection.execute("DELETE FROM account_sessions WHERE account_id = ?", (account["id"],))
        session = None
    else:
        raise AccountError("This link is no longer valid.")
    connection.execute("DELETE FROM account_links WHERE email = ?", (email,))
    return session


def customer_invite(connection, email):
    return connection.execute("SELECT * FROM customer_invites WHERE email = ?", (email,)).fetchone()


def profile(connection, account_id):
    return connection.execute("SELECT email, access FROM accounts WHERE id = ?", (account_id,)).fetchone()


def customers(connection):
    rows = connection.execute("""
        SELECT email, access, 'active' AS status FROM accounts WHERE email != ?
        UNION ALL
        SELECT email, access, CASE WHEN sent_at IS NULL THEN 'unsent' ELSE 'invited' END
        FROM customer_invites ORDER BY email
    """, (OWNER_EMAIL,))
    return [dict(row) for row in rows]


def prepare_customer(connection, email, access):
    connection.execute("BEGIN IMMEDIATE")
    if connection.execute("SELECT 1 FROM accounts WHERE email = ?", (email,)).fetchone():
        raise AccountError("This customer already has an account. Use Change access.", 409)
    connection.execute("""
        INSERT INTO customer_invites (email, access) VALUES (?, ?)
        ON CONFLICT(email) DO UPDATE SET access = excluded.access
    """, (email, access))
    return create_link(connection, email, "signup")


def change_access(connection, email, access):
    updated = connection.execute("UPDATE accounts SET access = ? WHERE email = ?", (access, email))
    if not updated.rowcount:
        updated = connection.execute("UPDATE customer_invites SET access = ? WHERE email = ?", (access, email))
    if not updated.rowcount:
        raise AccountError("Customer not found.", 404)


def send_link(email, purpose, token, origin):
    message = EmailMessage()
    message["From"] = SENDER
    message["To"] = email
    action = "Finish creating your account" if purpose == "signup" else "Reset your password"
    message["Subject"] = action + " | Ivory Invites"
    path = "/account/setup" if purpose == "signup" else "/account/reset"
    message.set_content(f"{action} by opening this link and entering your email address:\n\n"
                        f"{origin}{path}#{token}\n\n"
                        "The link is single-use and expires in 30 minutes. "
                        "If you did not request it, you can ignore this email.")
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10, context=ssl.create_default_context()) as mail:
        mail.login(SENDER, SMTP_PASSWORD)
        mail.send_message(message)


def deliver_link(db, email, purpose, origin):
    try:
        with db() as connection:
            token = issue_link(connection, email, purpose)
        if token:
            send_link(email, purpose, token, origin)
    except (OSError, smtplib.SMTPException, sqlite3.Error) as error:
        logging.error("Ivory Invites could not send an account email (%s).", type(error).__name__)
