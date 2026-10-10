# Database Upgrade

## Supported Sources

Schema version 15 creates the complete current structure directly. It accepts the
released unversioned 3.x layout verified against v3.3.3 and a complete current
database with ledger 14 or 15. A complete current database without its ledger can
be identified structurally. Earlier development-v4 versions are no longer
automatically upgraded. Missing columns, primary keys or foreign-key declarations,
unknown tables, executable schema objects and future ledgers are rejected.

Released import preserves account IDs, credentials, roles, work and report content,
quick entries, calendar events and provider metadata. It introduces canonical
login keys, independent daily memos, individual time-entry identities and initial
report versions. Display aliases start empty without affecting login IDs.
Historical clock durations and break deductions are retained without guessed
timezones or break periods.

Known released preferences map to current keys, including API address and model;
existing current keys take precedence. API configuration is retained without
automatically enabling paid external processing. OS keyring credentials and model
files are not part of database transfer and may require configuration again.
Normalized login-key collisions and ambiguous cross-account identities reject the
whole conversion rather than merging accounts.

## Startup and Snapshots

Current startup checks the actual structure even when no conversion is pending.
It does not replay development migrations or create unnecessary upgrade backups.
Supported populated sources receive one private `.bak_upgrade_*` snapshot while
the writer lock prevents concurrent changes. SQLite's backup API includes committed
WAL data. Conversion and the ledger update commit together; failures leave source
data available.

Frozen installations can adopt a supported database beside the executable when
the new user-data destination does not exist. Unsupported sources are retained,
not silently converted or reset.

## Explicit Upgrade Tool

Close the old application first and run from the project root:

```powershell
python scripts/upgrade_database.py --source "D:\OldWorkLogger\worklog.db" --destination "D:\UpdatedWorkLogger\worklog.db"
```

The destination must not exist. The source is read-only and remains unchanged.
Conversion runs on an unpublished copy, and only an integrity-checked result is
published. Output contains schema versions and record counts, not credentials
or work descriptions. Committed WAL data is included, not uncommitted changes.

Previous JSON templates can be imported with explicit ownership and language:

```powershell
python scripts/upgrade_database.py --source "D:\OldWorkLogger\worklog.db" --destination "D:\UpdatedWorkLogger\worklog.db" --template-file "D:\OldWorkLogger\templates\custom\Personal.json" --template-user "ExistingUser" --template-language "en_US"
```

Templates are bounded to 1 MiB and must use a supported report type. An existing
account/language/type template is not silently replaced. Original template and
model folders remain unchanged.

Released `enc1:` Fernet credentials can be decrypted only with their original
machine key and are rewritten securely after successful authentication.
Unknown or damaged values are retained for deliberate re-entry. Never include
machine keys, API credentials, recovery keys or OS keyring values in diagnostics.
