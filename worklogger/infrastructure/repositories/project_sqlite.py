"""Account-isolated work context with optimistic updates and archival."""

from dataclasses import replace
import json
import sqlite3
import unicodedata

from worklogger.domain.projects.models import Project, WorkItem


def normalized_name(value):
    return unicodedata.normalize("NFKC", value.strip()).casefold()


class SQLiteProjectRepository:
    def __init__(self, connection_factory):
        self._factory = connection_factory

    def catalog(self, user_id):
        with self._factory.transaction(write=False) as connection:
            rows = connection.execute("SELECT * FROM projects WHERE user_id=? ORDER BY archived,normalized_name,id", (user_id,)).fetchall()
            item_rows = connection.execute("SELECT * FROM work_items WHERE user_id=? ORDER BY archived,completed,normalized_title,id", (user_id,)).fetchall()
        projects = tuple(Project(row["id"], row["name"], row["code"], row["revision"], bool(row["archived"])) for row in rows)
        items = {project.id: [] for project in projects}
        for row in item_rows:
            items[row["project_id"]].append(WorkItem(row["id"], row["project_id"], row["title"], row["source_url"],
                                                   bool(row["completed"]), row["revision"], bool(row["archived"])))
        return projects, {key: tuple(value) for key, value in items.items()}

    def list_projects(self, user_id):
        with self._factory.connection() as connection:
            rows = connection.execute("SELECT * FROM projects WHERE user_id=? ORDER BY archived,normalized_name,id", (user_id,)).fetchall()
        return tuple(Project(row["id"], row["name"], row["code"], row["revision"], bool(row["archived"])) for row in rows)

    def list_work_items(self, user_id, project_id):
        with self._factory.connection() as connection:
            rows = connection.execute("SELECT * FROM work_items WHERE user_id=? AND project_id=? ORDER BY archived,completed,normalized_title,id",
                                      (user_id, project_id)).fetchall()
        return tuple(WorkItem(row["id"], row["project_id"], row["title"], row["source_url"],
                              bool(row["completed"]), row["revision"], bool(row["archived"])) for row in rows)

    def save_project(self, user_id, project, *, create):
        try:
            with self._factory.transaction() as connection:
                if create:
                    connection.execute("INSERT INTO projects(id,user_id,name,normalized_name,code) VALUES(?,?,?,?,?)",
                                       (project.id, user_id, project.name, normalized_name(project.name), project.code))
                    return project
                cursor = connection.execute("UPDATE projects SET name=?,normalized_name=?,code=?,archived=?,revision=revision+1 WHERE user_id=? AND id=? AND revision=?",
                    (project.name, normalized_name(project.name), project.code, int(project.archived), user_id, project.id, project.revision))
                if cursor.rowcount != 1:
                    raise ValueError("project_conflict")
                return replace(project, revision=project.revision + 1)
        except sqlite3.IntegrityError as error:
            if getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise ValueError("project_name_exists") from None
            raise

    def save_work_item(self, user_id, item, *, create):
        try:
            with self._factory.transaction() as connection:
                parent = connection.execute("SELECT archived FROM projects WHERE user_id=? AND id=?", (user_id, item.project_id)).fetchone()
                if parent is None or parent["archived"]:
                    raise ValueError("project_unavailable")
                if create:
                    connection.execute("INSERT INTO work_items(id,user_id,project_id,title,normalized_title,source_url,completed) VALUES(?,?,?,?,?,?,?)",
                        (item.id, user_id, item.project_id, item.title, normalized_name(item.title), item.source_url, int(item.completed)))
                    return item
                cursor = connection.execute("UPDATE work_items SET title=?,normalized_title=?,source_url=?,completed=?,archived=?,revision=revision+1 WHERE user_id=? AND id=? AND project_id=? AND revision=?",
                    (item.title, normalized_name(item.title), item.source_url, int(item.completed), int(item.archived), user_id, item.id, item.project_id, item.revision))
                if cursor.rowcount != 1:
                    raise ValueError("work_item_conflict")
                return replace(item, revision=item.revision + 1)
        except sqlite3.IntegrityError as error:
            if getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise ValueError("work_item_name_exists") from None
            raise


def validate_record_context(connection, record, *, historical=False):
    context = record.context
    previous = connection.execute("SELECT project_id,work_item_id FROM worklog WHERE user_id=? AND id=?",
                                  (record.user_id, record.id or 0)).fetchone()
    unchanged = previous is not None and (previous["project_id"], previous["work_item_id"]) == (context.project_id, context.work_item_id)
    if record.capture_id:
        timer = connection.execute("SELECT value FROM settings WHERE user_id=? AND key='time_entry_timer'", (record.user_id,)).fetchone()
        if timer:
            saved = json.loads(timer[0])
            captured = saved.get("context") or {}
            unchanged = unchanged or (saved.get("capture_id") == record.capture_id
                and (captured.get("project_id"), captured.get("work_item_id")) == (context.project_id, context.work_item_id))
    if context.project_id is not None:
        project = connection.execute("SELECT archived FROM projects WHERE user_id=? AND id=?", (record.user_id, context.project_id)).fetchone()
        if project is None or (project["archived"] and not (unchanged or historical)):
            raise ValueError("project_unavailable")
    if context.work_item_id is not None:
        item = connection.execute("SELECT archived FROM work_items WHERE user_id=? AND id=? AND project_id=?",
                                  (record.user_id, context.work_item_id, context.project_id)).fetchone()
        if item is None or (item["archived"] and not (unchanged or historical)):
            raise ValueError("work_item_unavailable")
