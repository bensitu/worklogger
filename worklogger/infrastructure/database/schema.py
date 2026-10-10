"""Supported stored tables shared by upgrade and recovery adapters."""

PREVIOUS_ACTIVITY_TABLE = "audit_events"
SUPPORTED_TABLES = frozenset({
    "users", "login_attempts", "worklog", "quick_logs", "settings", "reports",
    "report_templates", "calendar_events", "external_identities", "oauth_identities",
    "activity_events", "schema_migrations", "daily_notes", "work_types", "projects", "work_items", "entry_changes", PREVIOUS_ACTIVITY_TABLE,
})
