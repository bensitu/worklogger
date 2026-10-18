"""Select CSV replacement targets without deleting unrelated time records."""

from datetime import timezone

def matching_period(left, right):
    if left.is_note_only or right.is_note_only:
        return False
    if (left.start_time, left.end_time) != (right.start_time, right.end_time):
        return False
    if all(moment is not None for moment in (left.started_at, left.ended_at, right.started_at, right.ended_at)):
        return (left.started_at.astimezone(timezone.utc), left.ended_at.astimezone(timezone.utc)) == (
            right.started_at.astimezone(timezone.utc), right.ended_at.astimezone(timezone.utc))
    return True


def remove_import_targets(connection, storage, user_id, day, entries, replace_dates):
    rows = connection.execute("SELECT * FROM worklog WHERE user_id=? AND d=? ORDER BY id",
                              (user_id, day.isoformat())).fetchall()
    if replace_dates:
        targets = rows
    else:
        targets = []
        decoded = [(row, storage.from_row(row)) for row in rows]
        for incoming in entries:
            matches = [row for row, record in decoded if matching_period(incoming, record)]
            if len(matches) > 1:
                raise ValueError("csv_import_conflict")
            targets.extend(matches)
    if len(targets) > 250:
        raise ValueError("record_change_too_large")
    for row in targets:
        connection.execute("DELETE FROM worklog WHERE user_id=? AND id=?", (user_id, row["id"]))
    return [dict(row) for row in targets]
