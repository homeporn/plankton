import secrets
from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.repositories.base import ValidationError
from app.repositories.event_repository import EventRepository
from app.repositories.work_repository import WorkRepository
from app.repositories.work_order_workflow_repository import WorkOrderWorkflowRepository, AssignmentOverrunError
from app.services.progress_service import ProgressService
from app.calculation_engine.historical import read_snapshot
from app.calculation_engine.models import Status
from app.time_utils import instant
from app.web import get_db, current_project_id, current_project, translate_error
from app.web.forms import InputError, business_date, discipline, integer, quantity, text
from app.web.views import work_context

bp = Blueprint("events", __name__)


def save_entry(repo, event_repo, direction, confirmation, forced_line_id):
    data = request.form
    item_id = integer(data, "work_item_id", "Учётная позиция")
    line_id = integer(data, 'work_order_line_id', 'Строка наряда', optional=True)
    if forced_line_id is not None and line_id != forced_line_id:
        raise InputError('Событие из наряда должно ссылаться на выбранную строку')
    if data.get('location_from_work') == '1' and not data.get('building_id') and not data.get('floor_id'):
        # The short form posts the canonical item. Resolve its location in this workspace.
        position = repo._item(item_id)
        building_id, floor_id = position['building_id'], position['floor_id']
    else:
        building_id = integer(data, "building_id", "Корпус")
        floor_id = integer(data, "floor_id", "Этаж")
    items = repo.list_work_items(discipline=direction.value, building_id=building_id, floor_id=floor_id)
    if item_id not in {row["id"] for row in items}:
        raise InputError("Позиция не относится к выбранному направлению, корпусу или этажу.")
    delta = quantity(data, "quantity_delta", "Объём", signed=True)
    correction = integer(data, "correction_of_id", "Исходное событие", optional=True)
    if delta == 0 or (delta < 0 and not correction):
        raise InputError("Объём должен быть ненулевым. Для уменьшения выберите исходное событие корректировки.")
    date = business_date(data, "business_date")
    if date > instant()[:10]:
        raise InputError("Дата события не может быть позже сегодняшней даты регистрации (UTC).")
    kwargs = dict(event_key=text(data, "event_key", "Ключ записи", limit=80),
                  correction_of_id=correction, comment=text(data, "comment", "Комментарий", required=False, limit=2000),
                  source_type="work_order" if forced_line_id else "manual", require_current_plan=True,
                  work_order_line_id=line_id,
                  plan_version_id=integer(data, "version_id", "Версия плана", optional=True))
    if confirmation:
        event_repo.add_confirmation(item_id, delta, date,
                                    document_ref=text(data, "document_ref", "Документ-основание", limit=200), **kwargs)
    else:
        event_repo.add_fact(item_id, delta, date, allow_assignment_overrun=data.get('allow_assignment_overrun') == '1',
                            overrun_reason=text(data, 'overrun_reason', 'Причина превышения', required=False, limit=2000), **kwargs)


def journal(kind, *, forced_line_id=None):
    repo, event_repo = WorkRepository(get_db(), current_project_id()), EventRepository(get_db(), current_project_id())
    direction = discipline(request.args if request.method == "GET" else request.form)
    confirmation = kind == "confirmation"
    endpoint = 'events.confirmations' if confirmation else 'events.facts'
    query = {key: value for key, value in request.args.items() if value and key in (
        "version_id", "report_date", "knowledge_cutoff", "building_id", "floor_id", "element", "work_type", "q")}
    query["discipline"] = direction.value
    search = text(request.args, 'q', 'Поиск работы', required=False, limit=160)
    submitted = request.form if request.method == 'POST' else {}
    error = None
    if request.method == "POST":
        if request.args.get("knowledge_cutoff") or (request.args.get("report_date") or instant()[:10]) != instant()[:10]:
            raise InputError("Для ввода откройте текущий срез.")
        try:
            save_entry(repo, event_repo, direction, confirmation, forced_line_id)
        except AssignmentOverrunError as exc:
            return render_template('event_overrun.html', message=str(exc), submitted=submitted), 400
        except ValidationError as exc:
            error = str(exc) if isinstance(exc, InputError) else translate_error(str(exc))
        else:
            flash("Подтверждение зарегистрировано." if confirmation else "Фактическое выполнение зарегистрировано.", "success")
            if forced_line_id:
                linked = WorkOrderWorkflowRepository(get_db(), current_project_id()).line(forced_line_id)
                return redirect(url_for('work_orders.detail', order_id=linked['work_order_id']), code=303)
            return redirect(url_for(endpoint, tab=request.args.get('tab', 'pending'), **query), code=303)
    with read_snapshot(get_db()):
        context = work_context(historical=True)
        filters, report, version = context["filters"], context["report"], context["version"]
        tab = request.args.get("tab", "pending")
        if tab not in ("pending", "all"):
            raise InputError("Выберите вкладку «Ожидают подтверждения» или «Все работы».")
        correction_mode = request.args.get("correction") == "1"
        service = ProgressService(get_db(), current_project_id())
        queue_rows = service.event_rows(report, filters=filters, confirmation=confirmation,
                                        pending_only=confirmation and tab == "pending")
        current = repo.get_active_plan_version(direction, report_date=instant()[:10], knowledge_cutoff=instant())
        read_only = (context["report_date"] != instant()[:10] or bool(request.args.get("knowledge_cutoff"))
                     or current_project()["status"] != "active"
                     or (not correction_mode and (not version or not current or version["id"] != current["id"])))
        if correction_mode:
            history = event_repo.list_events(kind, report_date=context["report_date"], knowledge_cutoff=context["cutoff"])
            ids = {row["work_item_id"] for row in history}
            items = [dict(item) for item in context["items"] if item["id"] in ids]
        else:
            active_buildings = {b["id"] for b in context["buildings"] if b["status"] == "active"}
            items = [row for row in queue_rows if row["result"].status in (Status.VALID, Status.WARNING)
                     and row["building_id"] in active_buildings and (not confirmation or row["pending"] > 0)]
        if search:
            words = search.casefold().split()
            def matches(row):
                name = " ".join(str(row[key]) for key in ("code", "name", "building_name", "floor_code", "element", "work_type")).casefold()
                return all(word in name for word in words)
            queue_rows = [row for row in queue_rows if matches(row)]
            items = [row for row in items if matches(row)]
        allowed_ids = {row["id"] for row in items}
        selected_id = integer(submitted or request.args, "work_item_id", "Учётная позиция", optional=True)
        selected_line = forced_line_id or integer(submitted or request.args, 'work_order_line_id', 'Строка наряда', optional=True)
        workflow = WorkOrderWorkflowRepository(get_db(), current_project_id())
        if selected_line:
            line = workflow.line(selected_line)
            if selected_id is not None and selected_id != line['work_item_id']:
                raise InputError('Наряд не содержит выбранную работу')
            selected_id = line['work_item_id']
        selected = next((row for row in items if row["id"] == selected_id), None)
        if selected_id and selected is None and not error:
            raise InputError("Выбранная работа недоступна в этом объекте, версии или срезе.")
        event_page=integer(request.args,"event_page","Страница журнала",optional=True) or 1
        journal_filters=dict(filters,discipline=direction.value)
        history_args = dict(work_item_id=selected_id, report_date=context["report_date"],
                            knowledge_cutoff=context["cutoff"], filters=journal_filters)
        rows = event_repo.list_events(kind, limit=50, offset=(event_page-1)*50, **history_args)
        event_count = event_repo.list_events(kind, count=True, **history_args)
        source_id = integer(submitted or request.args, "correction_of_id", "Исходное событие", optional=True)
        correction_choices = rows
        if correction_mode and source_id and all(event["id"] != source_id for event in rows):
            # A correction opened from a later journal page keeps its original source.
            original = next((event for event in history if event["id"] == source_id and event["work_item_id"] == selected_id), None)
            if original is not None:
                correction_choices = [original, *rows]
        context.update(confirmation=confirmation, events=rows, tab=tab, correction_mode=correction_mode,
                       read_only=read_only, selected=selected, query=query, search=search, allowed_ids=allowed_ids,
                       event_key=submitted.get('event_key') or secrets.token_urlsafe(24),
                       selected_order_line_id=selected_line, submitted=submitted, error=error,
                       source_id=source_id, correction_choices=correction_choices,
                       order_choices=workflow.choices(kind) if not read_only and not correction_mode else [],
                       from_work_order=forced_line_id is not None, journal_endpoint=endpoint)
        if forced_line_id is not None:
            context['order_choices'] = [c for c in context['order_choices'] if c['id'] == forced_line_id]
        if selected_line and not error and not any(c['id'] == selected_line for c in context['order_choices']):
            raise InputError('Выбранная строка наряда недоступна для этого события')
        from app.web.pagination import paginate
        context["queue_rows"] = paginate(queue_rows, "work_page")
        context["events"]=paginate(context["events"],"event_page",total_count=event_count)
        if selected:
            context["items"] = [selected]
        elif correction_mode:
            context["items"] = paginate(items, "position_page")
        else:
            context["items"] = [row for row in context["queue_rows"] if row["id"] in allowed_ids]
        if not selected and not error and not correction_mode and len(items) == 1 and context["items"]:
            context["selected"] = items[0]
        if confirmation and not correction_mode:
            shown = context["queue_rows"]
            item_ids = [row["id"] for row in shown]
            if selected and selected["id"] not in item_ids:
                item_ids.append(selected["id"])
            last_fact_dates = {}
            if item_ids:
                placeholders = ",".join("?" for _ in item_ids)
                last_fact_dates = dict(get_db().execute(
                    "SELECT work_item_id, MAX(work_date) FROM fact_events WHERE work_item_id IN (" + placeholders + ") "
                    "AND work_date<=? AND recorded_at<=? GROUP BY work_item_id",
                    [*item_ids, context["report_date"], context["cutoff"]]))
            context["last_fact_dates"] = last_fact_dates
        return render_template("events.html", **context), 400 if error else 200


@bp.route("/facts", methods=["GET", "POST"])
def facts():
    return journal("fact")


@bp.route("/confirmations", methods=["GET", "POST"])
def confirmations():
    return journal("confirmation")
