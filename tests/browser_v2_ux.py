"""Замер пользовательских путей в Chromium на выделенной синтетической БД.

python tests/browser_v2_ux.py --output /tmp/ux-v2
--source указывает на распакованный git archive для повторного замера старой версии.
Нужны зависимости приложения, Playwright и Chromium. Порт выбирает ОС.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class QuietLog(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        pass


class Journey:
    """Записывает явные действия и окончательные HTTP-ответы основного документа."""

    def __init__(self, page, origin):
        self.page = page
        self.origin = origin
        self.steps = []
        self.pages = []
        page.on("response", self.response)
        page.on("dialog", self.dialog)

    def response(self, response):
        req = response.request
        if req.is_navigation_request() and req.frame == self.page.main_frame and response.status == 200:
            self.pages.append(urlsplit(response.url).path)

    def dialog(self, dialog):
        self.steps.append(["диалог", dialog.message])
        dialog.accept()

    def begin(self, path="/"):
        assert self.page.goto(self.origin + path).status == 200
        self.pages = [urlsplit(self.page.url).path]
        self.steps = []

    def click(self, locator, name):
        self.steps.append(["кнопка/ссылка", name])
        locator.click()

    def choose(self, locator, value, name):
        self.steps.append(["выбор", name])
        locator.select_option(str(value))

    def fill(self, locator, value, name):
        self.steps.append(["ввод", name])
        locator.fill(value)

    def section(self, path):
        page = self.page
        direct = page.locator('.object-actions a[href="' + path + '"]')
        if direct.count():
            self.click(direct, direct.inner_text())
            return
        # В исходной версии форма нового наряда доступна из реестра.
        directory = "/work-orders" if path == "/work-orders/new" else path
        link = page.locator('.application-navigation a[href="' + directory + '"]')
        group = link.locator("xpath=ancestor::details")
        if not link.is_visible():
            self.click(group.locator("summary"), group.locator("summary").inner_text())
        self.click(link, link.inner_text())
        if directory != path:
            self.click(page.locator('main a[href="' + path + '"]').first, "Создать наряд")

    def result(self):
        counts = Counter(t for t, _ in self.steps)
        return dict(действия=len(self.steps), переходы=len(self.pages)-1, экраны=len(self.pages),
                    нажатия=counts["кнопка/ссылка"] + counts["диалог"] + counts["выбор"],
                    выбор=counts["выбор"], ввод=counts["ввод"], диалоги=counts["диалог"],
                    страницы=self.pages.copy(), шаги=self.steps.copy())


def collect(source, output, chromium):
    sys.path.insert(0, str(source))
    # Переиспользуется стенд этапа 4.2. Ни одна строка не берётся из пользовательской БД.
    sys.path.insert(1, str(source / "tests"))
    from browser_stage42 import seed
    from app.database import connect
    from app.repositories.work_repository import WorkRepository
    from app.repositories.timesheet_repository import TimesheetRepository
    from app.web import create_app

    result = {"маршруты": {}, "проверки": [], "сценарии": {}, "экраны": {}, "ошибки_JS": [], "HTTP_ошибки": [], "внешние_запросы": []}
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="plankton-v2-ux-") as folder:
        db_path = Path(folder) / "synthetic.sqlite3"
        f = seed(db_path)
        past = date.today().replace(day=1) - timedelta(days=1)
        day = past.replace(day=12).isoformat()
        contractor = str(f["contractor"])
        with closing(connect(db_path)) as db:
            empty_building = WorkRepository(db, f["project"]).add_building("UX", "Пустой корпус проверки")
            sheet = TimesheetRepository(db, f["project"]).create(f["contractor"], past.year, past.month)

        def total(table):
            assert table in ("fact_events", "confirmation_events", "work_orders", "timesheet_entries")
            with closing(connect(db_path)) as db:
                return db.execute("SELECT count(*) FROM " + table).fetchone()[0]

        app = create_app(dict(DATABASE=str(db_path)))
        server = make_server("127.0.0.1", 0, app, request_handler=QuietLog)
        origin = f"http://127.0.0.1:{server.server_port}"
        app.config["LOCAL_ORIGIN"] = origin
        adapter = app.url_map.bind("127.0.0.1")

        def response_status(response):
            path = urlsplit(response.url).path
            method = response.request.method
            rule, _ = adapter.match(path, method=method, return_rule=True)
            statuses = result["маршруты"].setdefault(rule.rule, {}).setdefault(method, [])
            if response.status not in statuses:
                statuses.append(response.status)
                statuses.sort()
            if response.status >= 400:
                result["HTTP_ошибки"].append([response.status, path])
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=chromium, headless=True,
                                             args=["--no-sandbox", "--disable-dev-shm-usage"])
                result["браузер"] = "Chromium " + browser.version

                def start():
                    ctx = browser.new_context(viewport={"width": 1366, "height": 768}, accept_downloads=True)
                    def guard(route):
                        if route.request.url.startswith(origin + "/"):
                            route.continue_()
                        else:
                            result["внешние_запросы"].append(route.request.url)
                            route.abort()
                    ctx.route("**/*", guard)
                    p = ctx.new_page()
                    p.set_default_timeout(4000)
                    p.on("pageerror", lambda err: result["ошибки_JS"].append(str(err)))
                    p.on("response", response_status)
                    p.goto(origin)
                    project_selector = p.locator('form[action="/projects/select"] select[name=project_id]').first
                    if not project_selector.is_visible():
                        p.locator('form[action="/projects/select"]').first.locator("xpath=ancestor::details/summary").click()
                    project_selector.select_option(str(f["project"]))
                    submit = project_selector.locator("xpath=ancestor::form").locator("button")
                    if submit.is_visible() and urlsplit(p.url).path == "/":
                        submit.click()
                    expect(p.locator("input[name=workspace_id]").first).to_have_value(str(f["project"]))
                    return p, Journey(p, origin)

                def record(name):
                    expect(page.locator("input[name=workspace_id]").first).to_have_value(str(f["project"]))
                    result["сценарии"][name] = journey.result()
                    page.context.close()

                for path, table in [("/facts", "fact_events"), ("/confirmations", "confirmation_events")]:
                    page, journey = start()
                    journey.begin()
                    before = total(table)
                    journey.section(path)
                    form = page.locator("form.event-form")
                    if page.locator(".object-actions").count():  # Только сводка содержит быстрые действия.
                        raise AssertionError("Ожидалась форма журнала")
                    work = form.locator("select[name=work_item_id]")
                    if form.locator("select[data-building][required]").count():
                        queue = page.locator('[data-queue-item="{}"] a'.format(f["item"])).first
                        journey.click(queue, "Выбрать строку очереди")
                    elif work.input_value() != str(f["item"]):
                        journey.choose(work, f["item"], "Работа")
                    expect(work).to_have_value(str(f["item"]))
                    journey.fill(form.locator("[name=quantity_delta]"), "5", "Объём")
                    if path == "/confirmations":
                        journey.fill(form.locator("[name=document_ref]"), "Акт UX-5", "Документ-основание")
                    journey.click(form.locator("[type=submit]"), "Сохранить запись")
                    assert total(table) == before + 1
                    with closing(connect(db_path)) as db:
                        saved = db.execute("SELECT work_order_line_id,quantity_delta FROM " +
                                           table + " ORDER BY id DESC LIMIT 1").fetchone()
                        assert saved[0] is None and float(saved[1]) == 5
                    record(path)

                page, journey = start()
                journey.begin()
                journey.section("/work-orders/new")
                order = page.locator("#work-order-form")
                order.wait_for(state="visible")
                if not order.locator("[data-order-line]").count():
                    journey.click(order.locator("#add-order-line"), "Добавить работу")
                row = order.locator("[data-order-line]").first
                work = row.locator("select[name=work_item_id]")
                option = work.locator('option[value="{}"]'.format(f["item"]))
                for key, attribute in (("building","building"), ("floor","floor"), ("element","element"),
                                       ("work-type","work-type")):
                    choice = row.locator("select[data-" + key + "][required]")
                    if choice.count() and choice.is_visible() and not choice.input_value():
                        journey.choose(choice, option.get_attribute("data-" + attribute), key)
                journey.choose(work, f["item"], "Работа")
                journey.fill(row.locator("[name=planned_quantity]"), "12", "Объём задания")
                for name, value, title in [("contractor_id", contractor, "Подрядчик"),
                    ("issued_by_employee_id", f["employees"][0], "Мастер"),
                    ("foreman_employee_id", f["employees"][1], "Бригадир"),
                    ("brigade_id", f["brigade"], "Исполнители")]:
                    field = order.locator("select[name=" + name + "]")
                    if not field.is_visible():
                        toggle = field.locator('xpath=ancestor::details[not(@open)][1]/summary')
                        journey.click(toggle, toggle.inner_text())
                    if field.input_value() != str(value):
                        journey.choose(field, value, title)
                sources = [total(k) for k in ("fact_events", "confirmation_events", "timesheet_entries")]
                journey.click(order.locator('[type=submit]'), "Сохранить черновик")
                issue = page.locator('form[action$="/issue"] button')
                expect(issue).to_be_visible()
                journey.click(issue, "Выдать наряд")
                assert [total(k) for k in ("fact_events", "confirmation_events", "timesheet_entries")] == sources
                with closing(connect(db_path)) as db:
                    assert db.execute("SELECT status FROM work_orders ORDER BY id DESC LIMIT 1").fetchone()[0] == "issued"
                record("выдать наряд")

                page, journey = start()
                journey.begin()
                journey.section("/timesheets")
                journey.click(page.locator(f'[data-timesheet="{sheet}"] a[href*="/timesheets/{sheet}"]').first, "Открыть табель")
                cell = page.locator(f'button.ts-cell[data-employee="{f["employees"][0]}"][data-date="{day}"]')
                journey.click(cell, "Ячейка работника")
                editor = page.locator("#cell-editor form")
                expect(editor.locator("[name=code]")).to_have_value("Я")
                journey.fill(editor.locator("[name=hours]"), "6", "Фактические часы")
                journey.click(editor.locator('button[type=submit]:not([name])'), "Сохранить запись")
                with closing(connect(db_path)) as db:
                    assert TimesheetRepository(db, f["project"]).report(sheet)["total_hours"] == 6
                record("ячейка табеля")

                for path in ("/labor", "/payroll"):
                    page, journey = start()
                    journey.begin()
                    journey.section(path)
                    assert urlsplit(page.url).path == path
                    record(path)

                page, journey = start()
                journey.begin("/timesheets?contractor_id=" + contractor)
                journey.click(page.locator('main a[href^="/timesheets/new"]').first, "Создать табель")
                form = page.locator("form.ts-form")
                field = form.locator("select[name=contractor_id]")
                if field.input_value() != contractor:
                    journey.choose(field, contractor, "Подрядчик из реестра")
                journey.click(form.locator("button"), "Создать черновик")
                expect(page.locator("#timesheet-matrix")).to_be_visible()
                record("табель из отфильтрованного реестра")

                page, journey = start()
                journey.begin("/labor/works?contractor_id=" + contractor)
                switch = page.locator('main a[href*="mode=confirmed"][href^="/labor/works?"]')
                if switch.count():
                    journey.click(switch.first, "Подтверждено")
                else:
                    field = page.locator("form select[name=mode]")
                    journey.choose(field, "confirmed", "Подтверждено")
                    journey.click(field.locator("xpath=ancestor::form").locator("button"), "Применить")
                args = parse_qs(urlsplit(page.url).query)
                assert args["mode"] == ["confirmed"] and args["contractor_id"] == [contractor]
                record("смена журнала выработки")

                page, journey = start()
                journey.begin("/payroll?contractor_id=" + contractor)
                new_period = page.locator('main a[href^="/payroll/periods/new"]')
                if not new_period.count():
                    journey.click(page.locator('main a[href="/payroll/periods"]').first, "Расчётные периоды")
                journey.click(new_period.first, "Создать период")
                form = page.locator("form.payroll-form")
                field = form.locator("[name=contractor_id]")
                if field.input_value() != contractor:
                    journey.choose(field, contractor, "Подрядчик из сводки")
                journey.fill(form.locator("[name=norm_hours]"), "160", "Норма часов месяца")
                journey.click(form.locator("button"), "Создать период")
                assert urlsplit(page.url).path.split("/")[-1].isdigit()
                record("расчётный период из сводки")

                page, journey = start()
                pages = [("/", "dashboard"), ("/facts", "facts"), ("/confirmations", "confirmations"),
                         ("/work-orders/new", "work-order"), (f"/timesheets/{sheet}", "timesheet"),
                         ("/labor", "labor"), ("/payroll", "payroll")]
                for width, height in ((1366, 768), (390, 844)):
                    page.set_viewport_size(dict(width=width, height=height))
                    for path, slug in pages:
                        assert page.goto(origin + path).status == 200
                        key = f"{slug}-{width}"
                        result["экраны"][key] = page.evaluate("""() => ({
                          ширина: innerWidth, ширина_документа: document.documentElement.scrollWidth,
                          поля: Array.from(document.querySelectorAll('main input:not([type=hidden]), main textarea, main select'))
                            .filter(e => e.checkVisibility()).length,
                          меню: document.querySelectorAll('.application-navigation [data-nav-group]').length
                        })""")
                        page.screenshot(path=output / (key + ".png"), animations="disabled")

                page.set_viewport_size(dict(width=1366,height=768))
                page.goto(origin + "/facts?knowledge_cutoff=2026-10-21T00:00:00Z")
                assert not page.locator("form.event-form").count()
                page.goto(origin + "/analytics/export")
                with page.expect_download() as dl:
                    page.locator("[data-export-xlsx]").click()
                with dl.value.path().open("rb") as downloaded:
                    assert downloaded.read(4) == b"PK\x03\x04"
                result["xlsx"] = dl.value.suggested_filename
                result["исторический_журнал_без_формы"] = True
                with closing(connect(db_path)) as db:
                    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                    assert not db.execute("PRAGMA foreign_key_check").fetchall()
                # Дополнительные позитивные варианты, редко достижимые в старых HTTP-тестах.
                project = f["project"]
                employee = f["employees"][-1]
                assert page.goto(origin + "/analytics/groups/new").status == 200
                edit_employee = f"/personnel/employees/{employee}/edit"
                assert page.goto(origin + edit_employee).status == 200
                long_name = "Учебный " + "ДлиннаяФамилия" * 6
                page.locator('main input[name="full_name"]').fill(long_name)
                page.locator('main form[method=post] button[type=submit]').click()
                assert page.goto(origin + edit_employee).status == 200
                expect(page.locator('main input[name="full_name"]')).to_have_value(long_name)
                page.goto(origin + f"/personnel/workers/{employee}")
                assignment = page.locator('main form[action$="/assignment"]')
                assignment.locator('select[name=brigade_id]').select_option(str(f["brigade"]))
                assignment.locator('button').click()
                expiry = page.locator('main form[action$="/project-end"]')
                expiry.locator('button').click()
                assert not result["HTTP_ошибки"], result["HTTP_ошибки"]
                result["проверки"].append("Кириллица, длинное ФИО сохранено и повторно открыто, назначена бригада, завершена доступность работника")
                delete_path = f"/projects/{project}/buildings/{empty_building}/delete"
                assert page.goto(origin + delete_path).status == 200
                delete_form = page.locator('main form.delete-building-form')
                # Нативная валидация должна оставить корпус на месте до осознанного согласия.
                delete_form.locator('button').click()
                assert delete_form.locator('input:invalid[name=confirm_delete]').count() == 1
                delete_form.locator('input[name=confirm_delete]').check()
                delete_form.locator('button').click()
                assert urlsplit(page.url).path == f"/projects/{project}"
                with closing(connect(db_path)) as db:
                    assert db.execute("SELECT count(*) FROM buildings WHERE id=?", (empty_building,)).fetchone()[0] == 0
                result["проверки"].append("Удаление пустого учебного корпуса блокируется без явного согласия и возвращает в карточку после подтверждения")

                # Первая вкладка сохраняет форму, во второй меняется объект.
                page.goto(origin + f"/facts?work_item_id={f['item']}")
                stale = page.locator("form.event-form")
                stale.locator("[name=quantity_delta]").fill("1")
                other = page.context.new_page()
                other.goto(origin + "/projects")
                project_form = other.locator('main form[action="/projects/select"]').filter(
                    has=other.locator('input[name=project_id][value="1"]'))
                project_form.locator("button").click()
                before = total("fact_events")
                stale.locator("button[type=submit]").click()
                assert result["HTTP_ошибки"] == [[403, "/facts"]]
                assert total("fact_events") == before
                result["проверки"].append("Старая вкладка после смены объекта получила 403 без записи факта")
                other.close()
                result["ожидаемые_HTTP_ошибки"] = [[403, "/facts"]]
                assert not (result["ошибки_JS"] or result["внешние_запросы"])
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: row["действия"] for name,row in result["сценарии"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--chromium", default="/usr/bin/chromium")
    options = ap.parse_args()
    collect(options.source.resolve(), options.output.resolve(), options.chromium)
