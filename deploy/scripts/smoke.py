"""Сквозная проверка Docker с отдельной синтетической БД и случайным loopback-портом."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
from http.client import HTTPSConnection
from http.cookies import SimpleCookie
import json
import netrc
import os
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import subprocess
import tarfile
import tempfile
from urllib.parse import urlencode
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_suite(folder, chromium):
    project = "plankton-test-" + uuid4().hex[:8]
    tag = project + ":v2"
    next_tag = project + ":update"
    host = "127.0.0.1"
    with socket.socket() as s:
        s.bind((host, 0))
        port = s.getsockname()[1]
    origin = f"https://{host}:{port}"
    state, access, settings = folder / "data", folder / "access", folder / "v2.env"
    db = state / "plankton.sqlite3"
    proxy_setting = next(line for line in (ROOT / ".env.example").read_text().splitlines() if line.startswith("PROXY_IMAGE="))
    settings.write_text(proxy_setting + "\n" + f"COMPOSE_PROJECT_NAME={project}\nSTATE_DIR='{state}'\nCONFIG_DIR='{access}'\n"
                        f"DEMO_HOST={host}\nDEMO_PORT={port}\nDEMO_UID={os.getuid()}\n"
                        f"DEMO_GID={os.getgid()}\nAPP_IMAGE={tag}\n")
    env = dict(os.environ, PLANKTON_ENV=str(settings))
    compose = ["docker", "compose", "--env-file", str(settings), "-p", project, "-f", str(ROOT / "docker-compose.yml")]
    ops = [str(ROOT / "deploy/scripts/ops.sh")]

    def run(*args, quiet=False, check=True):
        return subprocess.run([str(a) for a in args], cwd=ROOT, env=env, text=True, check=check,
                              stdout=subprocess.PIPE if quiet else None)

    def output(*args):
        return run(*args, quiet=True).stdout.strip()

    def inspect(service):
        container = output(*compose, "ps", "--all", "-q", service)
        return json.loads(output("docker", "inspect", container))[0]

    def query(path, sql):
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            return conn.execute(sql).fetchall()

    def count(path=db):
        return query(path, "SELECT count(*) FROM projects WHERE code LIKE 'CLOUDTEST-%'")[0][0]

    run(*ops, "init")
    cert = ssl.create_default_context(cafile=access / "ca.crt")
    login, _, password = netrc.netrc(str(access / "client.netrc")).authenticators(host)
    basic = "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode()

    def request(path, method="GET", fields=None, headers=None, auth=True):
        sent = {"Authorization": basic} if auth else {}
        sent.update(headers or {})
        body = None
        if fields is not None:
            body = urlencode(fields)
            sent["Content-Type"] = "application/x-www-form-urlencoded"
        with closing(HTTPSConnection(host, port, context=cert, timeout=15)) as conn:
            conn.request(method, path, body, sent)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode("utf-8")

    def form():
        status, headers, html = request("/projects/new")
        require(status == 200, "HTTPS страница формы")
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        cookies = SimpleCookie(headers["Set-Cookie"])
        session = cookies["__Host-plankton-v2"]
        require(session["secure"] and session["httponly"] and session["samesite"] == "Strict", "свойства cookie")
        return dict(csrf_token=token, workspace_id="1"), dict(Origin=origin, Cookie=f"{session.key}={session.value}")

    def create(i):
        fields, headers = form()
        fields.update(name=f"Синтетический объект {i}", code=f"CLOUDTEST-{i}", building_count="0")
        return request("/projects/new", "POST", fields, headers)[0]

    def smoke_browser():
        from playwright.sync_api import sync_playwright
        pubkey = subprocess.check_output(["openssl", "x509", "-in", access / "proxy/server.crt", "-pubkey", "-noout"])
        der = subprocess.check_output(["openssl", "pkey", "-pubin", "-outform", "DER"], input=pubkey)
        fingerprint = base64.b64encode(sha256(der).digest()).decode()
        attempted = []

        def observe(route):
            if route.request.url.startswith(origin + "/"):
                route.continue_()
            else:
                attempted.append(route.request.url)
                route.abort()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chromium, headless=True,
                                         args=["--disable-background-networking", "--ignore-certificate-errors-spki-list=" + fingerprint])
            context = browser.new_context(http_credentials=dict(username=login, password=password, origin=origin))
            context.route("**/*", observe)
            page = context.new_page()
            for path in ("/", "/projects", "/timesheets", "/payroll", "/analytics"):
                response = page.goto(origin + path, wait_until="networkidle")
                require(response.status == 200 and page.locator("h1").is_visible(), "страница за TLS в Chromium")
            loaded = page.evaluate("""async () => {
                await document.fonts.ready;
                const fonts = await Promise.all([400, 700].map(w => document.fonts.load(w + ' 16px "DejaVu Sans"', 'Планктон')));
                return fonts.every(faces => faces.length && faces.every(face => face.status === 'loaded'));
            }""")
            require(loaded, "оба начертания шрифта из комплекта бренда")
            require(not attempted, "внешние запросы из браузера")
            browser.close()
        print("PASS Chromium открыл пять страниц через TLS-прокси, загрузил оба TTF, внешних запросов со страниц нет")

    def smoke_http():
        require(request("/healthz")[::2] == (200, "ok\n"), "готовность через HTTPS")
        require(request("/healthz", auth=False)[0] == 401, "доступ без пароля")
        require(request("/projects", headers={"Host": "foreign.invalid",
                        "X-Forwarded-Host": f"{host}:{port}", "X-Forwarded-For": host})[0] == 403, "Host")
        require(request("/healthz", headers={"X-Forwarded-Proto": "http", "Forwarded": "for=198.51.100.1"})[0] == 200,
                "недоверенные forwarded не влияют на схему и peer")
        fields, headers = form()
        for mutation, wrong in (({"csrf_token": "bad"}, {}), ({"workspace_id": "2"}, {}),
                                ({}, {"Origin": "https://foreign.invalid"}), ({}, {"Origin": "null"})):
            status = request("/projects/new", "POST", dict(fields, **mutation), dict(headers, **wrong))[0]
            require(status == 403, "защита изменяющих запросов")
        require(request("/shutdown", "POST", fields, headers)[0] == 404, "локальное выключение")
        require(request("/projects/new", "POST", dict(fields, value="x" * 140000), headers)[0] == 413, "лимит форм")
        require(request("/projects/new", "POST", dict(fields, value="x" * (6*1024*1024)), headers)[0] == 413, "лимит proxy")
        for path in ("/state/plankton.sqlite3", "/backups/", "/.env", "/run/session.key"):
            require(request(path)[0] == 404, "служебный файл через HTTP")

    try:
        run(*ops, "build")
        run(*ops, "start")
        smoke_http()
        if chromium:
            smoke_browser()
        app, proxy = inspect("app"), inspect("proxy")
        require(app["HostConfig"]["NetworkMode"] == "none" and not app["HostConfig"]["PortBindings"], "сеть WSGI")
        require(proxy["HostConfig"]["PortBindings"] == {"8443/tcp": [{"HostIp": host, "HostPort": str(port)}]}, "порт прокси")
        require(all(item["Config"]["User"] == f"{os.getuid()}:{os.getgid()}" for item in (app, proxy)), "непривилегированный UID")
        require(query(db, "PRAGMA journal_mode") == [("wal",)], "WAL")
        require(query(db, "SELECT count(*) FROM schema_migrations") == [(len(list((ROOT / "migrations").glob("*.sql"))),)], "миграции")
        require("Закрытый демонстрационный стенд" in request("/settings")[2], "обозначение режима")
        require('action="/shutdown"' not in request("/")[2], "отсутствие локального выключения")
        print("PASS первый старт, миграции, TLS, Basic, cookie, CSRF, Host, Origin, контекст, лимиты, закрытые пути и сеть")

        with closing(sqlite3.connect(db)) as reader:
            reader.execute("BEGIN")
            reader.execute("SELECT count(*) FROM projects").fetchone()
            with ThreadPoolExecutor(max_workers=4) as pool:
                require(list(pool.map(create, range(8))) == [303] * 8, "параллельные записи")
            require(count() == 8 and Path(str(db) + "-wal").stat().st_size > 0, "подтверждённые записи в WAL")
            backup = state / "backups" / output(*ops, "backup").splitlines()[-1]
            require(count(backup) == 8 and query(backup, "PRAGMA integrity_check") == [("ok",)]
                    and not query(backup, "PRAGMA foreign_key_check"), "снимок открытого WAL")
        print("PASS восемь параллельных HTTP-записей, backup во время открытого WAL, integrity и FK")

        # Загруженные в образ файлы проверяются во всех слоях рабочего каталога.
        archive = folder / "image.tar"
        run("docker", "image", "save", "-o", archive, tag)
        forbidden = (".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".pem", ".key", ".netrc", ".env")
        required = {"opt/plankton/deploy/cloud.py", "opt/plankton/app/web/templates/base.html", "opt/plankton/migrations/001_initial.sql"}
        brand = "opt/plankton/app/web/static/brand-kit/"
        required.update(brand + asset for asset in ("css/brand.css", "assets/fonts/DejaVuSans.ttf",
                        "assets/fonts/DejaVuSans-Bold.ttf", "assets/fonts/LICENSE-DejaVu.txt"))
        payload = set()
        with tarfile.open(archive) as outer:
            layers = json.load(outer.extractfile("manifest.json"))[0]["Layers"]
            for name in layers:
                with tarfile.open(fileobj=outer.extractfile(name), mode="r|*") as layer:
                    for member in layer:
                        path = member.name.removeprefix("./")
                        if path.startswith(("opt/plankton/", "state/", "run/access/", "run/plankton/")) and member.isfile():
                            require(not path.endswith(forbidden) and "/backups/" not in path, "посторонний файл образа")
                            payload.add(path)
        require(required <= payload, "ресурсы приложения")
        archive.unlink()
        print("PASS проверены слои образа, миграции, ресурсы, отсутствие файлов данных и секретов поставки")

        run(*ops, "stop")
        require(all(inspect(name)["State"]["ExitCode"] == 0 for name in ("app", "proxy")), "штатное завершение")
        run(*ops, "start")
        require(inspect("app")["Id"] == app["Id"] and count() == 8, "рестарт процесса")
        # Образ с тем же приложением и другой меткой выпуска даёт отдельный image ID.
        subprocess.run(["docker", "build", "-t", next_tag, "-"], check=True, text=True,
                       input=f"FROM {tag}\nLABEL org.opencontainers.image.revision=smoke-update\n")
        settings.write_text(settings.read_text().replace(f"APP_IMAGE={tag}", f"APP_IMAGE={next_tag}"))
        for _ in range(2):
            previous_id = inspect("app")["Id"]
            run(*ops, "update")
            require(inspect("app")["Id"] != previous_id and count() == 8, "обновление с пересозданием")
        require(inspect("app")["Image"] != app["Image"], "переход на другой image ID")
        require(len(list((state / "backups").glob("*.sqlite3"))) >= 3, "версии копий")
        restored = folder / "restored"
        run(*ops, "restore", backup, restored)
        require(run(*ops, "restore", backup, restored, check=False).returncode != 0, "перезапись восстановленного каталога")
        future = folder / "future.sqlite3"
        with closing(sqlite3.connect(backup)) as original, closing(sqlite3.connect(future)) as copy:
            original.backup(copy)
            copy.execute("INSERT INTO schema_migrations(name) VALUES ('unknown-stage.sql')")
            copy.commit()
        rejected = folder / "rejected"
        require(run(*ops, "restore", future, rejected, check=False).returncode != 0 and not rejected.exists(),
                "отказ от неизвестной версии без публикации результата")
        run(*ops, "stop")
        settings.write_text(settings.read_text().replace(f"STATE_DIR='{state}'", f"STATE_DIR='{restored}'")
                            .replace(f"APP_IMAGE={next_tag}", f"APP_IMAGE={tag}"))
        run(*ops, "start")
        require(inspect("app")["Image"] == app["Image"], "возврат предыдущего образа")
        require(count(restored / db.name) == 8 and "CLOUDTEST-7" in request("/projects")[2], "открытие восстановленного стенда")
        print("PASS SIGTERM/SIGQUIT, рестарт, два обновления, отдельный восстановленный стенд с восемью объектами")

        run(*ops, "stop")
        legacy = folder / "pre-013"
        legacy.mkdir(mode=0o700)
        code = """from pathlib import Path
import shutil
from app import database
from tempfile import TemporaryDirectory
with TemporaryDirectory() as t:
    database.PROJECT_ROOT = Path(t)
    migrations = Path(t) / 'migrations'
    migrations.mkdir()
    for source in sorted(Path('migrations').glob('*.sql'))[:12]:
        shutil.copyfile(source,migrations/source.name)
    db = database.initialize('/legacy/plankton.sqlite3')
    db.execute("UPDATE projects SET name='Синтетическое наследие' WHERE id=1")
    db.close()
"""
        run("docker", "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{legacy}:/legacy", "--entrypoint", "python", tag, "-c", code)
        settings.write_text(settings.read_text().replace(f"STATE_DIR='{restored}'", f"STATE_DIR='{legacy}'"))
        require(query(legacy / db.name, "SELECT count(*) FROM schema_migrations") == [(12,)], "исходная версия базы")
        run(*ops, "start")
        require("Синтетическое наследие" in request("/projects")[2], "данные после миграции")
        copies = list((legacy / "backups").glob("plankton-*.sqlite3"))
        require(len(copies) == 1 and query(copies[0], "SELECT count(*) FROM schema_migrations") == [(12,)], "копия до миграции")
        print("PASS совместимая база 012 мигрирована с сохранением объекта и проверенной копии старой схемы")
    finally:
        run(*compose, "down", "--timeout", "40", check=False)
        run("docker", "image", "rm", next_tag, tag, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="Существующий каталог, видимый локальному Docker")
    parser.add_argument("--chromium", help="Исполняемый файл Chromium, дополнительно нужен Python-пакет Playwright")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="plankton-smoke-", dir=args.workspace) as temp:
        run_suite(Path(temp).resolve(), args.chromium)
