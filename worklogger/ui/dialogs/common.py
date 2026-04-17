from __future__ import annotations
import datetime
from calendar import monthrange

from PySide6.QtWidgets import QMessageBox, QFrame

from utils.i18n import _, msg
from utils.formatters import format_quick_logs, format_cal_events
from utils.template_engine import render_template


def _div() -> QFrame:
    f = QFrame()
    f.setObjectName("divider")
    return f


def _localize_msgbox_buttons(box: QMessageBox, t: dict) -> QMessageBox:
    mapping = {
        QMessageBox.StandardButton.Yes: _("Yes"),
        QMessageBox.StandardButton.No: _("No"),
        QMessageBox.StandardButton.Save: _("Save"),
        QMessageBox.StandardButton.Discard: _("Discard"),
        QMessageBox.StandardButton.Cancel: _("Cancel"),
    }
    for button, label in mapping.items():
        btn = box.button(button)
        if btn:
            btn.setText(label)
    return box


def _get_ai_params(app, secondary: bool = False):
    return app.services.resolve_ai_params(secondary=secondary)


def _format_quick_logs(logs: list[dict], lang: str = "en", mode: str = "summary") -> str:
    return format_quick_logs(logs, lang, mode)


def _quick_logs_for_type(app, type_key: str) -> list[dict]:
    return app.services.quick_logs_for_type(app.selected, app.current, type_key)


def _append_quick_logs_block(base_text: str, app, type_key: str) -> str:
    if type_key not in {"daily", "weekly", "monthly"}:
        return base_text
    logs = _quick_logs_for_type(app, type_key)
    if not logs:
        return base_text
    title = _("Work Log")
    fmt_mode = "daily" if type_key == "daily" else "summary"
    block = _format_quick_logs(logs, app.lang, fmt_mode)
    if not block:
        return base_text
    trimmed = base_text.rstrip()
    joiner = "\n\n" if trimmed else ""
    return f"{trimmed}{joiner}## {title}\n{block}"


def _render_template_with_context(app, type_key: str, raw_tpl: str) -> str:
    ctx = _build_template_data(app, type_key)
    rendered = render_template(raw_tpl, ctx)
    return _append_quick_logs_block(rendered, app, type_key)


def _format_cal_events(events: list[dict]) -> str:
    return format_cal_events(events)


def _build_template_data(app, type_key: str) -> dict:
    sel = app.selected
    if type_key == "weekly":
        monday = sel - datetime.timedelta(days=sel.weekday())
        sunday = monday + datetime.timedelta(days=6)
        return {
            "start": monday.isoformat(), "end": sunday.isoformat(),
            "date_range": f"{monday.isoformat()} – {sunday.isoformat()}",
            "task_list": "- ", "total_hours": "", "overtime_hours": "",
            "issues": "- ", "next_plan": "- ",
        }
    if type_key == "monthly":
        y, m = app.current.year, app.current.month
        _, ld = monthrange(y, m)
        return {
            "year": y, "month": m,
            "date_range": f"{y}-{m:02d}-01 – {y}-{m:02d}-{ld:02d}",
            "task_list": "- ", "total_hours": "", "overtime_hours": "",
            "issues": "- ", "next_plan": "- ",
        }
    return {
        "date": f"{sel.year}/{sel.month:02d}/{sel.day:02d}",
        "task_list": "- ", "total_hours": "", "overtime_hours": "",
        "issues": "- ", "next_plan": "- ",
    }
