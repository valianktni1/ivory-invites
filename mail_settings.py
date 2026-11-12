import hashlib
import hmac
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from contextlib import contextmanager
from pathlib import Path

DIRECTORY = Path(os.environ.get("INVITES_SETTINGS", Path(__file__).resolve().parent / ".settings"))
DEFAULT_USER = "admin@ivorydigital.uk"
DEFAULT_HOST = os.environ.get("INVITES_SMTP_HOST", "smtp.hostinger.com")
DEFAULT_PORT = int(os.environ.get("INVITES_SMTP_PORT", "465"))
CODE_AGE = 20 * 60


class MailSettingsError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status


@contextmanager
def store():
    DIRECTORY.mkdir(parents=True, mode=0o700, exist_ok=True)
    connection = sqlite3.connect(DIRECTORY / "mail.sqlite3", timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def setup():
    with store() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS smtp (
                id INTEGER PRIMARY KEY CHECK (id = 1), host TEXT NOT NULL, port INTEGER NOT NULL,
                encryption TEXT NOT NULL, username TEXT NOT NULL, password TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS setup_code (
                id INTEGER PRIMARY KEY CHECK (id = 1), digest BLOB NOT NULL, expires INTEGER NOT NULL
            );
        """)


def credentials():
    with store() as connection:
        row = connection.execute("SELECT host, port, encryption, username, password FROM smtp WHERE id = 1").fetchone()
    if row:
        return dict(row)
    return dict(host=DEFAULT_HOST, port=DEFAULT_PORT, encryption="ssl", username=DEFAULT_USER,
                password=os.environ.get("INVITES_SMTP_PASSWORD", ""))


def public_config():
    config = credentials()
    return dict(host=config["host"], port=config["port"], encryption=config["encryption"],
                username=config["username"], configured=bool(config["password"]))


def new_code():
    code = secrets.token_urlsafe(24)
    with store() as connection:
        connection.execute("INSERT OR REPLACE INTO setup_code VALUES (1, ?, ?)",
                           (digest(code), int(time.time()) + CODE_AGE))
    return code


def digest(code):
    return hashlib.sha256(code.encode("utf-8")).digest()


def require_code(connection, code):
    row = connection.execute("SELECT digest, expires FROM setup_code WHERE id = 1").fetchone()
    if (not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", code) or row is None
            or row["expires"] <= time.time() or not hmac.compare_digest(row["digest"], digest(code))):
        raise MailSettingsError("The setup code is invalid or expired. Generate a new code on TrueNAS.", 403)


@contextmanager
def connected(config):
    ssl_context = ssl.create_default_context()
    args = (config["host"], config["port"])
    client = (smtplib.SMTP_SSL(*args, timeout=8, context=ssl_context)
              if config["encryption"] == "ssl" else smtplib.SMTP(*args, timeout=8))
    with client as mail:
        if config["encryption"] == "starttls":
            mail.starttls(context=ssl_context)
        mail.login(config["username"], config["password"])
        yield mail


def configure(data, *, bootstrap=False):
    code = data.get("code")
    if bootstrap:
        with store() as connection:
            require_code(connection, code)
    host = data.get("host")
    username = data.get("username")
    password = data.get("password")
    encryption = data.get("encryption")
    port = data.get("port")
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
        raise MailSettingsError("Enter an SMTP server hostname.")
    if type(port) is not int or not 1 <= port <= 65535 or encryption not in ("ssl", "starttls"):
        raise MailSettingsError("Choose a valid port and encryption method.")
    if not isinstance(username, str) or not 1 <= len(username) <= 254 or not username.isprintable():
        raise MailSettingsError("Enter the SMTP username.")
    if not isinstance(password, str) or not 1 <= len(password) <= 512 or not password.isprintable():
        raise MailSettingsError("Enter the mailbox password.")
    config = dict(host=host, port=port, encryption=encryption, username=username, password=password)
    try:
        with connected(config):
            pass
    except smtplib.SMTPAuthenticationError as error:
        raise MailSettingsError("The mail server rejected the username or password.", 422) from error
    except (OSError, smtplib.SMTPException) as error:
        raise MailSettingsError("Could not connect securely to the SMTP server. Check the host, port and encryption.", 422) from error
    with store() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if bootstrap:
            require_code(connection, code)
        connection.execute("INSERT OR REPLACE INTO smtp VALUES (1, :host, :port, :encryption, :username, :password)",
                           config)
        connection.execute("DELETE FROM setup_code WHERE id = 1")
