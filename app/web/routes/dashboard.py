from flask import Blueprint, render_template, request

from app.calculation_engine.historical import read_snapshot
from app.repositories.event_repository import EventRepository
from app.repositories.payroll_repository import PayrollRepository
from app.repositories.timesheet_repository import TimesheetRepository
from app.services.labor_productivity import LaborProductivityService
from app.services.progress_service import ProgressService
from app.web import current_project_id, get_db
from app.web.forms import report_dates

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    report_date, cutoff = report_dates(request.args)
    db, project_id = get_db(), current_project_id()
    historical = bool(request.args.get("report_date") or request.args.get("knowledge_cutoff"))
    with read_snapshot(db):
        context = ProgressService(db, project_id).dashboard(report_date, cutoff)
        events = EventRepository(db, project_id)
        recent = []
        for kind in ("fact", "confirmation"):
            rows = events.list_events(kind, report_date=report_date, knowledge_cutoff=cutoff, limit=4)
            recent.extend(dict(row, kind=kind) for row in rows)
        recent.sort(key=lambda row: (row["recorded_at"], row["id"]), reverse=True)
        if not historical:
            orders = db.execute("SELECT count(*) FROM work_orders WHERE project_id=? AND status='submitted'",
                                (project_id,)).fetchone()[0]
            review_orders = db.execute(
                "SELECT id,order_number FROM work_orders WHERE project_id=? AND status='submitted' "
                "ORDER BY shift_date,id LIMIT 3", (project_id,)).fetchall()
            sheets = TimesheetRepository(db, project_id).list_timesheets()
            periods = PayrollRepository(db, project_id).list_periods()
            # A project without a sheet for this month has no approved hours to distribute.
            has_sheet = any((s["year"], s["month"]) == (int(report_date[:4]), int(report_date[5:7]))
                            for s in sheets)
            summary = {"unallocated_hours": None, "conflict_count": 0}
            if has_sheet:
                report = LaborProductivityService(db, project_id).build(report_date[:8] + "01", report_date, cutoff)
                summary = report["summary"]
            open_sheets = [s for s in sheets if s["status"] in ("draft", "submitted")]
            open_periods = [p for p in periods if p["status"] in ("draft", "calculated", "submitted")]
            context.update(orders=orders, review_orders=review_orders,
                           sheets=len(open_sheets), open_sheets=open_sheets[:3],
                           periods=len(open_periods), open_periods=open_periods[:3],
                           hours=summary["unallocated_hours"], conflicts=summary["conflict_count"])
    return render_template("dashboard.html", report_date=report_date, cutoff=cutoff,
                           historical=historical, recent=recent[:4], **context)
