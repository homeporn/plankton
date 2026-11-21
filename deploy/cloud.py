"""Сервер и обслуживание закрытого стенда. Локальный запуск имеет собственную точку входа."""
import argparse
import fcntl
import logging
import os
import signal
import socket
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from app.config import PROJECT_ROOT

DB = Path("/state/plankton.sqlite3")
SOCKET = "/run/plankton/app.sock"
MIGRATIONS = {p.name for p in (PROJECT_ROOT / "migrations").glob("*.sql")}
CORE_TABLES = {"buildings", "work_items", "plan_versions", "fact_events", "confirmation_events"}


def read_db(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)


def verify(db):
    if list(db.execute("PRAGMA integrity_check")) != [("ok",)]:
        raise ValueError("База не прошла проверку integrity_check")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("База не прошла проверку foreign_key_check")
    tables = {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not CORE_TABLES.issubset(tables):
        raise ValueError("Файл не содержит базовые таблицы приложения")
    applied = set()
    if "schema_migrations" in tables:
        applied = {name for (name,) in db.execute("SELECT name FROM schema_migrations")}
    if applied - MIGRATIONS:
        raise ValueError("В базе есть неизвестные миграции. Используйте совместимый образ и копию")
    return applied


def snapshot(source, destination):
    """Публикация проверенного снимка без замены существующей копии."""
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".partial-", delete=False) as f:
        temporary = Path(f.name)
    try:
        with closing(read_db(source)) as original, closing(sqlite3.connect(temporary)) as copy:
            original.backup(copy, pages=256, sleep=0.05)
            copy.execute("PRAGMA journal_mode=DELETE")
            verify(copy)
        with temporary.open("rb") as copy:
            os.fsync(copy.fileno())
        os.link(temporary, destination)
        folder_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(folder_fd)
        finally:
            os.close(folder_fd)
    finally:
        temporary.unlink(missing_ok=True)


def backup():
    folder = DB.parent / "backups"
    folder.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = folder / f"plankton-{stamp}-{uuid4().hex[:12]}.sqlite3"
    snapshot(DB, destination)
    print(destination.name)


def restore(source, folder):
    folder.mkdir(mode=0o700)
    try:
        snapshot(source, folder / DB.name)
    except Exception:
        if not any(folder.iterdir()):
            folder.rmdir()
        raise
    print(f"Восстановлена проверенная база {folder / DB.name}")


def origin():
    value = os.environ["DEMO_ORIGIN"]
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.path or parts.query or parts.fragment
            or not parts.port or not 1024 <= parts.port <= 65535):
        raise ValueError("DEMO_ORIGIN должен быть HTTPS-адресом стенда с портом 1024–65535")
    return value


def probe():
    host = urlsplit(origin()).netloc
    request = f"GET /healthz HTTP/1.0\r\nHost: {host}\r\n\r\n".encode("ascii")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(SOCKET)
        client.sendall(request)
        with client.makefile("rb") as response:
            if response.readline().split()[1:2] != [b"200"]:
                raise RuntimeError("Служба не прошла проверку готовности")


def serve():
    from waitress import serve as serve_wsgi
    from app.web import create_app, get_db

    external_origin = origin()
    secret = Path("/run/session.key").read_text(encoding="ascii").strip()
    if len(bytes.fromhex(secret)) < 32:
        raise ValueError("Секрет сессии должен содержать минимум 32 случайных байта")
    with (DB.parent / ".serve.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Этот каталог БД уже обслуживается другим процессом") from exc
        if DB.exists():
            with closing(read_db(DB)) as existing:
                applied = verify(existing)
            if applied != MIGRATIONS:
                backup()
        app = create_app(dict(DATABASE=str(DB), LOCAL_ORIGIN=external_origin, CLOUD_DEMO=True,
                              SECRET_KEY=secret, SESSION_COOKIE_SECURE=True,
                              SESSION_COOKIE_NAME="__Host-plankton-v2", DEBUG=False))
        with closing(sqlite3.connect(DB)) as db:
            if db.execute("PRAGMA journal_mode=WAL").fetchone() != ("wal",):
                raise RuntimeError("SQLite не смог включить WAL")

        @app.get("/healthz")
        def readiness():
            row = get_db().execute("SELECT count(*) FROM schema_migrations").fetchone()
            if row[0] != len(MIGRATIONS):
                return "migration pending\n", 503
            return "ok\n", 200, {"Content-Type": "text/plain; charset=utf-8"}

        # У Waitress штатное завершение и освобождение очереди по KeyboardInterrupt.
        def stop(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, stop)
        serve_wsgi(app, unix_socket=SOCKET, unix_socket_perms="600", threads=4,
                   url_scheme="https", clear_untrusted_proxy_headers=True,
                   max_request_body_size=5 * 1024 * 1024 + 64 * 1024)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("serve", "health", "backup"):
        sub.add_parser(name)
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("source", type=Path)
    restore_parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    if args.action == "restore":
        restore(args.source, args.folder)
    elif args.action == "backup":
        backup()
    elif args.action == "health":
        probe()
    else:
        logging.basicConfig(level=logging.INFO)
        serve()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        raise SystemExit(f"Ошибка облачного профиля: {error}") from None
