"""Browser acceptance for true Chromium zoom, contrast, keyboard and wide sheets.

Run with the application requirements, Playwright and Chromium installed:
python tests/browser_v2_visual.py --output /tmp/plankton-visual
"""
import argparse
import base64
from contextlib import closing
import json
import math
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from threading import Thread

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from browser_v2_ux import QuietLog


def luminance(color):
    channels = [int(channel) / 255 for channel in re.findall(r"\d+", color)[:3]]
    values = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(v * weight for v, weight in zip(values, [0.2126, 0.7152, 0.0722]))


def contrast(locator, pseudo=None):
    colors = locator.evaluate("""(el, pseudo) => {
      let ancestor = el;
      while (getComputedStyle(ancestor).backgroundColor === 'rgba(0, 0, 0, 0)') {
        ancestor = ancestor.parentElement;
      }
      const canvas = document.createElement('canvas').getContext('2d');
      return [getComputedStyle(el, pseudo).color, getComputedStyle(ancestor).backgroundColor].map(color => {
        canvas.fillStyle = color;
        canvas.fillRect(0, 0, 1, 1);
        return Array.from(canvas.getImageData(0, 0, 1, 1).data.slice(0, 3)).join(' ');
      });
    }""", pseudo)
    a, b = sorted(luminance(color) for color in colors)
    ratio = (b + 0.05) / (a + 0.05)
    assert ratio >= 4.5, (colors, ratio)
    return round(ratio, 2)


def open_project(page, project_id):
    switch = page.locator('form[action="/projects/select"]').first
    if not switch.locator("select").is_visible():
        sidebar = page.locator("#application-sidebar")
        if not sidebar.is_visible():
            page.locator("[data-navigation-toggle]").click()
        details = switch.locator("xpath=ancestor::details[1]")
        if details.count() and details.get_attribute("open") is None:
            details.locator("summary").first.click()
    switch.locator("select").select_option(str(project_id))
    if switch.locator('button[type="submit"]').is_visible() and page.locator('input[name=workspace_id]').first.input_value() != str(project_id):
        switch.locator('button[type="submit"]').click()
    expect(page.locator('input[name=workspace_id]').first).to_have_value(str(project_id))


def form_screenshot(page, origin, output):
    assert page.goto(origin + "/facts#event-entry").status == 200
    section = page.locator("#event-entry")
    section.evaluate("el => el.scrollIntoView({block: 'start', behavior: 'instant'})")
    page.screenshot(path=output / "fact-form-1366.png")


def check_profile(pw, chromium, profile, factor, origin, fixture, sheet, output):
    # Chromium's native zoom preference is logarithmic. The following checks
    # measure real layout and DPR after navigation to confirm it was applied.
    default = profile / "Default"
    default.mkdir(parents=True)
    prefs = {"partition": {"default_zoom_level": {"x": math.log(factor, 1.2)}}}
    (default / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")
    context = pw.chromium.launch_persistent_context(
        str(profile), executable_path=chromium, headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"], locale="ru-RU",
        viewport={"width": 1366, "height": 768},
    )
    try:
        page = context.pages[0]
        page.set_default_timeout(5000)
        page.goto(origin)
        open_project(page, fixture["project"])
        profiles = {"browser": context.new_cdp_session(page).send("Browser.getVersion")["product"],
                    "zoom": factor, "pages": {}}
        for path in ["/", "/projects", "/settings", "/facts", "/confirmations", "/work-orders/new", f"/timesheets/{sheet}"]:
            assert page.goto(origin + path).status == 200
            dimensions = page.evaluate("""() => ({
              window: outerWidth, layout: innerWidth,
              document: document.documentElement.scrollWidth, dpr: devicePixelRatio
            })""")
            assert abs(dimensions["dpr"] - factor) < .01, dimensions
            assert abs(dimensions["layout"] - dimensions["window"] / factor) <= 1, dimensions
            assert dimensions["document"] <= dimensions["layout"] + 1, (path, dimensions)
            profiles["pages"][path] = dimensions
        matrix = page.locator(".ts-matrix-scroll")
        expect(matrix).to_have_attribute("tabindex", "0")
        expect(matrix).to_have_attribute("role", "region")
        matrix.focus()
        assert matrix.evaluate("el => getComputedStyle(el).outlineWidth") != "0px"
        page.keyboard.press("ArrowRight")
        expect(matrix).not_to_have_js_property("scrollLeft", 0)
        profiles["matrix"] = matrix.evaluate("""el => ({
          container: el.clientWidth, content: el.scrollWidth, keyboardScroll: el.scrollLeft
        })""")
        if factor == 1:
            profiles["contrast"] = {"tableHeading": contrast(matrix.locator("th").first)}
            form_screenshot(page, origin, output)
            page.goto(origin + "/facts")
            form = page.locator("form.event-form")
            help_text = form.locator(".help:visible").first
            if help_text.count():
                profiles["contrast"]["help"] = contrast(help_text)
            prompt = form.locator("input[placeholder]:visible").first
            if prompt.count():
                profiles["contrast"]["placeholder"] = contrast(prompt, "::placeholder")
            submit = form.locator('button[type="submit"]').last
            profiles["contrast"]["primaryAction"] = contrast(submit)
            submit.focus()
            page.keyboard.press("Enter")
            assert form.evaluate("el => el.contains(document.activeElement) && !!document.activeElement.validationMessage")
            profiles["requiredFieldFeedback"] = True
            page.goto(origin + f"/confirmations?work_item_id={fixture['item']}")
            form.locator("[name=quantity_delta]").fill("2000")
            form.locator("[name=document_ref]").fill("Учебный акт")
            form.locator("[name=business_date]").fill("2026-10-20")
            form.locator('button[type="submit"]').click()
            expect(page.locator("#event-error")).to_contain_text("Подтверждение превышает факт")
            expect(form).to_have_attribute("aria-describedby", "event-error")
            expect(form.locator("[name=quantity_delta]")).to_have_value("2000")
            expect(form.locator("[name=document_ref]")).to_have_value("Учебный акт")
            profiles["serverErrorRetainsInput"] = True
            page.goto(origin + "/")
            page.keyboard.press("Tab")
            expect(page.locator(".skip-navigation")).to_be_focused()
            page.keyboard.press("Enter")
            assert page.url.endswith("#main")
            action = page.locator("[data-navigation-toggle]")
            picker = page.get_by_label("Тема оформления")
            root = page.locator("html")
            expect(picker).to_have_value("system")
            profiles["themes"] = {}
            for mode, canvas, surface in [("light", "rgb(247, 246, 239)", "rgb(216, 229, 222)"),
                                          ("dark", "rgb(11, 31, 27)", "rgb(31, 77, 70)")]:
                picker.select_option(mode)
                page.reload()
                expect(root).to_have_attribute("data-pl-brand-theme", mode)
                expect(page.locator("body")).to_have_css("background-color", canvas)
                expect(page.locator(".panel").first).to_have_css("background-color", surface)
                expect(picker).to_have_value(mode)
                primary = page.locator(".object-actions .primary-action")
                profiles["themes"][mode] = {
                    "primary": contrast(primary), "subtitle": contrast(page.locator(".subtitle")),
                    "queue": contrast(page.locator(".attention-list a").first),
                }
                faces = page.evaluate("""async () => {
                  await Promise.all([400,700].map(w => document.fonts.load(w + ' 14px "DejaVu Sans"', 'Планктон')));
                  return Array.from(document.fonts).filter(f=>f.status==='loaded').map(f=>[f.family,f.weight]);
                }""")
                assert {tuple(face) for face in faces} >= {("DejaVu Sans", "400"), ("DejaVu Sans", "700")}, faces
                profiles["fonts"] = faces
                page.screenshot(path=output / f"dashboard-{mode}.png")
            other = context.new_page()
            other.goto(origin)
            picker.select_option("light")
            expect(other.locator("html")).to_have_attribute("data-pl-brand-theme", "light")
            other.close()
            picker.select_option("system")
            page.emulate_media(color_scheme="dark")
            expect(root).to_have_attribute("data-pl-brand-theme", "dark")
            page.emulate_media(color_scheme="light")
            expect(root).to_have_attribute("data-pl-brand-theme", "light")
            page.emulate_media(forced_colors="active", reduced_motion="reduce")
            assert page.evaluate("matchMedia('(forced-colors: active)').matches")
            action.focus()
            assert action.evaluate("el => getComputedStyle(el).outlineStyle") != "none"
            page.screenshot(path=output / "dashboard-forced-colors.png")
            page.emulate_media(forced_colors="none", color_scheme="light")
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(origin + "/facts#event-entry")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=output / "fact-long-project-390.png")
        elif factor == 2:
            matrix.evaluate("el => el.scrollIntoView({block: 'start', behavior: 'instant'})")
            cdp = context.new_cdp_session(page)
            screen = cdp.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
            (output / "matrix-zoom-200.png").write_bytes(base64.b64decode(screen["data"]))
        return profiles
    finally:
        context.close()


def run(args):
    source = args.source.resolve()
    sys.path.insert(0, str(source / "tests"))
    sys.path.insert(0, str(source))
    from browser_stage42 import seed
    from app.database import connect
    from app.repositories.project_repository import ProjectRepository
    from app.repositories.timesheet_repository import TimesheetRepository
    from app.web import create_app

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="plankton-visual-") as tmp, sync_playwright() as pw:
        folder = Path(tmp)
        db = folder / "visual.sqlite3"
        fixture = seed(db)
        long_name = "Реконструкция" + "производственноэкспериментального" * 4 + " корпуса № 7"
        with closing(connect(db)) as con:
            ProjectRepository(con).update_project(fixture["project"], long_name, "УЧ-07")
            sheet = TimesheetRepository(con, fixture["project"]).create(fixture["contractor"], 2026, 10)
        app = create_app({"DATABASE": str(db)})
        server = make_server("127.0.0.1", 0, app, request_handler=QuietLog)
        origin = f"http://127.0.0.1:{server.server_port}"
        app.config["LOCAL_ORIGIN"] = origin
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            if args.comparison_only:
                browser = pw.chromium.launch(executable_path=args.chromium, args=["--no-sandbox"])
                try:
                    page = browser.new_page(viewport={"width": 1366, "height": 768}, locale="ru-RU")
                    page.goto(origin)
                    open_project(page, fixture["project"])
                    form_screenshot(page, origin, output)
                finally:
                    browser.close()
                return
            results = [check_profile(pw, args.chromium, folder / str(zoom), zoom, origin,
                                    fixture, sheet, output) for zoom in (1, 1.5, 2)]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        document = {"longNameLength": len(long_name), "profiles": results}
        (output / "results.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Проверено масштабов:", len(results), "Маршрутов на масштаб:", len(results[0]["pages"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--comparison-only", action="store_true", help="Снимок формы исходной версии")
    ap.add_argument("--chromium", default="/usr/bin/chromium")
    ap.add_argument("--output", type=Path, required=True)
    run(ap.parse_args())
