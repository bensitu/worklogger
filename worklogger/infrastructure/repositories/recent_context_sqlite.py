"""Bounded account-local identifiers for successful context selections."""

import json
from worklogger.domain.projects.models import WorkContext

KEY = "recent_work_contexts"


def recent_pairs(text):
    try:
        values = json.loads(text or "[]")
        if not isinstance(values, list) or len(values) > 8:
            return ()
        result = []
        for pair in values:
            if not isinstance(pair, list) or len(pair) != 2:
                return ()
            context = WorkContext(*pair)
            if context.project_id is not None and pair not in result:
                result.append(pair)
        return tuple(result)
    except (TypeError, ValueError):
        return ()


def remember_context(connection, user_id, context):
    if context.project_id is None:
        return
    row = connection.execute("SELECT value FROM settings WHERE user_id=? AND key=?", (user_id, KEY)).fetchone()
    pair = [context.project_id, context.work_item_id]
    values = [pair] + [previous for previous in recent_pairs(row[0] if row else None) if previous != pair]
    connection.execute("INSERT INTO settings(user_id,key,value) VALUES(?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                       (user_id, KEY, json.dumps(values[:8])))
