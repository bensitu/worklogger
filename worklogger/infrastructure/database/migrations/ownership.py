"""Normalize identity bindings and enforce account-owned record associations."""

import re

from worklogger.infrastructure.database.current_schema import TABLE_STATEMENTS, create_current_schema


def normalize_identities(connection):
    rows = [dict(row) for row in connection.execute("SELECT * FROM external_identities ORDER BY id")]
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "oauth_identities" in tables:
        for row in connection.execute("SELECT * FROM oauth_identities ORDER BY id"):
            value = dict(row)
            value.pop("id", None)
            value.update(broker="direct_oidc", issuer=value["provider"])
            rows.append(value)
    sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='external_identities'").fetchone()
    statement = TABLE_STATEMENTS["external_identities"].replace("IF NOT EXISTS external_identities(", "identities_import(", 1)
    connection.execute(statement)
    seen = {}
    columns = ("user_id", "provider", "subject", "email", "display_name", "created_at", "updated_at", "broker", "issuer")
    for row in rows:
        if row["provider"] == "google":
            if row["broker"] == "firebase":
                subject = _google_subject(row.get("federated_subject"))
                if subject:
                    row.update(subject=subject, broker="direct_oidc", issuer="https://accounts.google.com")
            elif row["issuer"] in ("google", "accounts.google.com", "https://accounts.google.com"):
                row.update(broker="direct_oidc", issuer="https://accounts.google.com")
        key = row["provider"], row["subject"]
        if key in seen:
            if seen[key] != (row["user_id"], row["issuer"], row["broker"]):
                raise ValueError("identity_subject_ambiguous")
            continue
        seen[key] = row["user_id"], row["issuer"], row["broker"]
        selected = ("id",) + columns if "id" in row else columns
        connection.execute("INSERT INTO identities_import(" + ",".join(selected) + ") VALUES(" +
                           ",".join("?" for _ in selected) + ")", tuple(row.get(name) for name in selected))
    connection.execute("DROP TABLE external_identities")
    connection.execute("ALTER TABLE identities_import RENAME TO external_identities")
    if sequence is not None:
        connection.execute("UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name='external_identities'", (sequence[0],))


def _google_subject(value):
    if not isinstance(value, str):
        return None
    prefix = "https://accounts.google.com/"
    subject = value[len(prefix):] if value.startswith(prefix) else value
    return subject if re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", subject) else None


def enforce_account_ownership(connection):
    normalize_identities(connection)
    sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='worklog'").fetchone()
    columns = [row[1] for row in connection.execute("PRAGMA table_info(worklog)")]
    quoted = ",".join('"' + name + '"' for name in columns)
    # Parent keys must exist before copying rows into composite foreign keys.
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS work_items_owner_project ON work_items(user_id,project_id,id)")
    connection.execute(TABLE_STATEMENTS["worklog"].replace("IF NOT EXISTS worklog(", "records_import(", 1))
    connection.execute(f"INSERT INTO records_import({quoted}) SELECT {quoted} FROM worklog")
    connection.execute("DROP TABLE worklog")
    connection.execute("ALTER TABLE records_import RENAME TO worklog")
    if sequence is not None:
        connection.execute("UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name='worklog'", (sequence[0],))
    connection.execute("DELETE FROM schema_migrations WHERE version IN (17,18)")
    create_current_schema(connection)
