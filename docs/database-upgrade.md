# Database Upgrade

## Supported Sources

The current schema version is 10. The application supports the released 3.x
multi-account SQLite layouts and existing versioned 4.0 databases. It preserves
integer account IDs, password and recovery material, report content, previous
quick logs, calendar events, settings, and stored identity metadata.

The ordered migration chain adds missing authentication fields, canonical account
keys, independent daily notes, offset timestamp columns, and individually editable
periods. Migration 8 also maps previous preference names without replacing a newer
explicit preference. A recorded password-change requirement is retained and
subsequently acknowledged through the current account field. Nullable previous work values receive
their existing semantic defaults; old break deductions remain deductions rather
than guessed rest periods.

Migration 9 adds custom classification snapshots and the account-owned type catalog.
Built-in records keep their stored meaning. Without a migration ledger, an already
converted entry table is recognized structurally and is not rebuilt; entry IDs,
revisions, capture identifiers, snapshots, and independent memos remain intact.

Migration 10 adds an optional user display name with an empty default, preserving
login IDs, credentials, roles, and record ownership. Existing display-name values
are retained when recognizing a database without a version ledger. No alias is
guessed from identity-provider metadata; users choose it in Account settings.

Unknown versions, invalid foreign keys, executable stored schema objects, and
canonical account-name conflicts stop the upgrade. Accounts are not merged,
passwords are not reset, and incompatible identity links are not selected
arbitrarily. Existing broker and issuer metadata remains in the database.

## Automatic Startup

The runner reads the applied-version set and returns immediately when no upgrade
is pending. It does not run earlier preparation hooks, scan their data, or create
new compatibility backups on an updated database.

A populated database with pending transformations receives one private complete
`worklog.db.bak_upgrade_<timestamp>_<identifier>` snapshot before any schema change.
SQLite's backup API includes committed WAL data. Snapshot integrity is checked,
and all transformations and version-history writes share one transaction. A
failure retains the original schema and data; the snapshot remains available.

Frozen installations can adopt an existing database beside the executable when
the new user-data destination does not exist. The copy is validated and includes
WAL data. Use the explicit tool when installing into a different directory or
when choosing a source manually.

## Explicit Upgrade Tool

Run from the project root:

```powershell
python scripts/upgrade_database.py --source "D:\OldWorkLogger\worklog.db" --destination "D:\UpdatedWorkLogger\worklog.db"
```

The destination must not exist. The source is opened read-only and remains
unchanged. Migration runs on an unpublished private copy. Only a complete,
integrity-checked result is published, without overwriting a destination created
by another process. The JSON result contains applied version numbers and record
counts, not usernames, work descriptions, passwords, or credentials.

Close the old application first. Committed WAL data is included; an uncommitted
transaction is not part of the snapshot. Confirm the new application opens the
result successfully before removing any original installation or backup.

## Templates and Credentials

Previous JSON templates were shared files, without an owning account or language.
Import a selected template with explicit choices:

```powershell
python scripts/upgrade_database.py --source "D:\OldWorkLogger\worklog.db" --destination "D:\UpdatedWorkLogger\worklog.db" --template-file "D:\OldWorkLogger\templates\custom\Personal.json" --template-user "ExistingUser" --template-language "en_US"
```

The file is bounded to 1 MiB and must contain a supported report type and content.
An existing template for the selected account/language/type is not silently
replaced. Other template files, model files, and OS credentials are not copied or
deleted; retain the original folders. Database upgrade is not a model download or
a secure cross-machine credential-transfer operation.

Earlier `enc1:` Fernet values and previous authenticated settings values are read
compatibly and rewritten only after successful authenticated decryption. The
previous random machine key can be read from its secure OS backend or original
key file; the older deterministic-key format remains read-compatible. Unknown or
damaged ciphertext is retained. Never paste keyring values, machine keys, recovery
keys, or API credentials into diagnostic output.
