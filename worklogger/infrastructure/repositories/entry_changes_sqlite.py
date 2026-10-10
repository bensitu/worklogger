"""Reversible record snapshots with conflict checks and bounded retention."""

import json
from worklogger.domain.worklog.editing import EntryChangeInfo


class SQLiteEntryChanges:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def rows(connection, user_id, identities):
        result = []
        for identity in identities:
            row = connection.execute("SELECT * FROM worklog WHERE user_id=? AND id=?", (user_id, identity)).fetchone()
            if row is not None:
                result.append(dict(row))
        return result

    def remember(self, connection, user_id, operation, before, after):
        if not self.storage.change_history:
            return
        before_json, after_json = json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)
        if len(before_json) > 1024 * 1024 or len(after_json) > 1024 * 1024:
            raise ValueError("record_change_too_large")
        connection.execute("INSERT INTO entry_changes(user_id,operation,before_json,after_json,expected_json) VALUES(?,?,?,?,?)",
                           (user_id, operation, before_json, after_json, after_json))
        connection.execute("DELETE FROM entry_changes WHERE user_id=? AND (created_at<datetime('now','-30 days') OR id NOT IN (SELECT id FROM entry_changes WHERE user_id=? ORDER BY id DESC LIMIT 50))",
                           (user_id, user_id))

    def latest(self, user_id):
        if not self.storage.change_history:
            return None
        with self.storage.connection_factory.connection() as connection:
            row = connection.execute("SELECT id,operation,before_json,after_json FROM entry_changes WHERE user_id=? AND undone=0 AND created_at>=datetime('now','-30 days') ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if row is None:
            return None
        snapshots = self._decode(row["after_json"]) or self._decode(row["before_json"])
        if not snapshots or snapshots[0].get("user_id") != user_id:
            raise ValueError("record_change_invalid")
        return EntryChangeInfo(row["id"], row["operation"], self.storage.from_row(snapshots[0]))

    @staticmethod
    def _decode(value):
        if len(value) > 1024 * 1024:
            raise ValueError("record_change_invalid")
        try:
            snapshots = json.loads(value)
        except (TypeError, ValueError):
            raise ValueError("record_change_invalid") from None
        if not isinstance(snapshots, list) or len(snapshots) > 3 or any(not isinstance(row, dict) for row in snapshots):
            raise ValueError("record_change_invalid")
        return snapshots

    def load(self, connection, user_id, change_id):
        row = connection.execute("SELECT * FROM entry_changes WHERE user_id=? AND id=? AND undone=0 AND created_at>=datetime('now','-30 days')", (user_id, change_id)).fetchone()
        latest = connection.execute("SELECT id FROM entry_changes WHERE user_id=? AND undone=0 AND created_at>=datetime('now','-30 days') ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if row is None or latest is None or latest[0] != change_id:
            raise ValueError("record_change_conflict")
        before, after = self._decode(row["before_json"]), self._decode(row["expected_json"])
        if not isinstance(before, list) or not isinstance(after, list) or len(before) > 3 or len(after) > 3:
            raise ValueError("record_change_invalid")
        for snapshot in (*before, *after):
            if not isinstance(snapshot, dict) or snapshot.get("user_id") != user_id or type(snapshot.get("id")) is not int or snapshot["id"] < 1:
                raise ValueError("record_change_invalid")
        if self.rows(connection, user_id, [snapshot["id"] for snapshot in after]) != after:
            raise ValueError("record_change_conflict")
        after_ids = {snapshot["id"] for snapshot in after}
        for snapshot in before:
            if snapshot["id"] not in after_ids and connection.execute("SELECT 1 FROM worklog WHERE id=?", (snapshot["id"],)).fetchone():
                raise ValueError("record_change_conflict")
        return before, after

    def complete_undo(self, connection, user_id, change_id, restored):
        connection.execute("UPDATE entry_changes SET undone=1 WHERE user_id=? AND id=?", (user_id, change_id))
        restored_by_id = {row["id"]: row for row in restored}
        rows = connection.execute("SELECT id,expected_json FROM entry_changes WHERE user_id=? AND undone=0 AND created_at>=datetime('now','-30 days')", (user_id,)).fetchall()
        for row in rows:
            expected = self._decode(row["expected_json"])
            changed = False
            for index, snapshot in enumerate(expected):
                current = restored_by_id.get(snapshot.get("id"))
                if current is not None and {key: value for key, value in current.items() if key != "revision"} == {key: value for key, value in snapshot.items() if key != "revision"}:
                    expected[index] = current
                    changed = True
            if changed:
                connection.execute("UPDATE entry_changes SET expected_json=? WHERE user_id=? AND id=?",
                                   (json.dumps(expected, ensure_ascii=False), user_id, row["id"]))
