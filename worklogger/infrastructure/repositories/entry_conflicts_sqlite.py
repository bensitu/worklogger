"""Account-scoped overlap queries for record replacement previews."""

from datetime import date

from worklogger.domain.worklog.rules import entries_overlap
from worklogger.infrastructure.repositories._mapping import map_rows


def overlapping_entries(connection, storage, record):
    start = date.fromordinal(max(record.day.toordinal() - 3, date.min.toordinal()))
    end = date.fromordinal(min(record.day.toordinal() + 3, date.max.toordinal()))
    rows = connection.execute(storage.select + "WHERE w.user_id=? AND w.d BETWEEN ? AND ? ORDER BY w.d,w.start,w.id",
                              (record.user_id, start.isoformat(), end.isoformat())).fetchall()
    return tuple(item for item in map_rows(rows, storage.from_row)
                 if item.id != record.id and entries_overlap(item, record))
