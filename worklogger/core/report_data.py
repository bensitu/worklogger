

from datetime import datetime


def format_task_list(tasks):
    return "\n".join([f"- {t}" for t in tasks]) if tasks else "- none"


def generate_report_data(records):
    """
    records: list of dict
    {
        "date": "2026-04-01",
        "hours": 8,
        "overtime": 1,
        "task": "Develop Feature A",
        "project": "Project A"
    }
    """

    total_hours = sum(r.get("hours", 0) for r in records)
    overtime_hours = sum(r.get("overtime", 0) for r in records)

    task_list = format_task_list([r.get("task", "") for r in records])

    project_map = {}
    for r in records:
        p = r.get("project", "Uncategorized")
        project_map[p] = project_map.get(p, 0) + r.get("hours", 0)

    project_summary = "\n".join(
        [f"- {k}: {v}h" for k, v in project_map.items()]
    )

    table_rows = "\n".join([
        f"| {r['date']} | {r.get('task', '')} | {r.get('hours', 0)} |"
        for r in records
    ])

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "date_range": f"{records[0]['date']} ~ {records[-1]['date']}" if records else "",
        "total_hours": total_hours,
        "overtime_hours": overtime_hours,
        "task_list": task_list,
        "project_summary": project_summary,
        "issues": "- None",
        "next_plan": "- None",
        "table_rows": table_rows,
        "invoice_rows": "",
        "client_name": "",
        "total_amount": "",
    }
