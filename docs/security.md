# Security and Privacy

This document describes implemented boundaries and limitations. It is not a claim
of certification or a guarantee against a compromised operating-system account.
Report vulnerabilities through [the security policy](../SECURITY.md).

## Local Data Boundary

WorkLogger stores application data in a local SQLite file. Accounts provide
application-level separation, not isolation from someone who can read or modify
the database file directly. Use operating-system permissions and disk encryption
where needed. Backups contain all accounts and are equally sensitive.

Reports, notes, CSV, iCalendar, and PDF exports are unencrypted. Imported or
generated content must be treated as untrusted text. Inspect spreadsheet exports
before opening them in software that interprets formulas.

## Authentication

- New passwords require at least eight characters.
- Password hashes use PBKDF2-HMAC-SHA256 with 600,000 iterations and a random
  16-byte salt. Supported older hashes are upgraded after successful verification.
- Recovery keys are generated separately and stored as hashes with separate salts.
- The first registered user is an administrator. Administrator operations check
  permissions and protect required account relationships in their handlers.
- Failed login counts are stored per username. Lockout thresholds are 5, 10, 15,
  and 20 failures, with delays of 30 seconds, 5 minutes, 30 minutes, and 24 hours.
- Remembered login tokens are stored as SHA-256-derived values in the database
  and expire after 30 days. Password workflows invalidate remembered credentials.

Do not use the reduced hashing iterations supplied by test fixtures in production.
There is no default administrator password or email-based account recovery.

## Credential Storage

Proxy passwords use `SystemCredentialStore`, which selects an approved OS keyring
backend and namespaces entries using the database path. There is no plaintext
fallback. If secure storage is unavailable, password entry is disabled and
existing values are retained. Moving the database can change the namespace and
require re-entering the proxy password.

Remembered login uses `FileRememberTokenSessionStore`. Its encrypted file is
protected by `HmacSecretBox` and a local machine-key file. This is an application
implementation based on HMAC-derived primitives, not OS-backed protection. An
attacker with both files can recover the session credential. File permissions are
best effort; protect the containing user profile.

`EncryptedSettingsKeyStore` is an additional adapter with keyring-first behavior
and encrypted-settings fallback. Its existence does not mean that all application
secrets or the database are encrypted. The default proxy workflow uses the stricter
system-only store instead.

## Network Exposure

Normal work recording does not require a network service. Manual update checks
contact GitHub. Model downloads contact the selected catalog URL. A connected
external AI adapter would transmit its supplied context and messages; the default
desktop does not connect that adapter.

Privacy switches default to including notes, calendar events, and quick logs in
built AI context. A failed settings read currently falls back to these defaults.
An external integration must explicitly assess data disclosure and user consent
before enabling transmission. Do not claim that a configured proxy form changes
network routing; the HTTP adapters are not connected to those settings.

## Diagnostics

Runtime logging uses UTF-8 rotating files, up to 1,000,000 bytes per file with five
backups. The filter rejects messages containing selected credential-related words,
but it is not comprehensive sanitization of arbitrary text or exception details.
Review logs before sharing them. Do not log passwords, recovery keys, tokens,
authorization headers, prompts containing private records, or downloaded secrets.

## Operational Precautions

Keep tested backups outside generated output directories. Verify database upgrades
on copies before using personal records. Restrict write access to application
resources and model catalogs. Do not package private files. Keep dependency
versions and native binaries consistent, and validate any dependency update before
shipping it. See [database handling](database.md) and [packaging](packaging.md).
