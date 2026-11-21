"""Записывает фактические статусы зарегистрированных маршрутов при явном вызове pytest -p.

Путь JSON задаёт UX_ROUTE_REPORT. Наблюдатель не меняет отправленные запросы и ответы.
"""
from collections import defaultdict
import json
import os
from pathlib import Path
from threading import Lock

from flask import Flask, request


def pytest_configure(config):
    original = Flask.process_response
    report = defaultdict(lambda: defaultdict(set))
    lock = Lock()

    def observe(app, response):
        response = original(app, response)
        if request.url_rule:
            with lock:
                report[request.url_rule.rule][request.method].add(response.status_code)
        return response

    def finish():
        Flask.process_response = original
        by_path = {path: {method: sorted(statuses) for method, statuses in sorted(methods.items())}
                   for path, methods in sorted(report.items())}
        Path(os.environ["UX_ROUTE_REPORT"]).write_text(
            json.dumps(by_path, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    Flask.process_response = observe
    config.add_cleanup(finish)
