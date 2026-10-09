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
before opening them in software that interprets formulas. Spreadsheet-sensitive
exported text is prefixed with an apostrophe; exports are still unencrypted.

## Authentication

- New passwords require at least eight characters.
- Account identifiers are compared using NFKC normalization and Unicode casefolding.
  The original display name and user ID remain stable when existing data is migrated.
- Password hashes use PBKDF2-HMAC-SHA256 with 600,000 iterations and a random
  16-byte salt. Supported older hashes are upgraded after successful verification.
- Recovery keys are generated separately and stored as hashes with separate salts.
  After registration, recovery, account creation, or a password change, a new key can be explicitly copied to the system
  clipboard or saved as a plain-text file. Export uses atomic replacement and
  does not log the key. The clipboard and exported file are outside application
  encryption; keep them private. Failed or cancelled exports leave the displayed
  key available and do not overwrite an existing file with an incomplete result.
  Administrator resets use separately labeled temporary-password copy/save
  actions, with the same explicit, unencrypted export behavior. Changing account
  selection or returning to account editing clears the visible credential.
- Administrator password resets invalidate recovery credentials and remembered
  sessions, return only the supplied temporary password, and always require a
  password change. The user receives a new recovery key only after changing the
  temporary password. No periodic password expiry is enforced.
- The first registered user is an administrator. Administrator operations check
  permissions and protect required account relationships in their handlers.
- Failed login counts are stored per canonical account key. Lockout thresholds are 5, 10, 15,
  and 20 failures, with delays of 30 seconds, 5 minutes, 30 minutes, and 24 hours.
  Counts restart after 24 hours without a failure. Unknown usernames are not
  stored, and records older than seven days are removed when the repository opens.
  Successful password and remembered-token authentication update the last login time.
- Remembered login tokens are stored as SHA-256-derived values in the database
  and expire after 30 days. Password workflows invalidate remembered credentials.

Do not use the reduced hashing iterations supplied by test fixtures in production.
There is no default administrator password or email-based account recovery.

## Credential Storage

Proxy passwords use `SystemCredentialStore`, which selects an approved OS keyring
backend and namespaces entries using the database path. There is no plaintext
fallback. If secure storage is unavailable, password entry is disabled and
existing values are retained in authenticated encrypted form until keyring storage
becomes available. Startup protects legacy plaintext for all accounts; an encryption
failure stops startup without discarding the original. Proxy passwords are excluded
from newly created backups, including SQLite free-page content. Private pre-change
migration snapshots may retain the original data and must be protected accordingly.
Moving the database can change the namespace and
require re-entering the proxy password.

Remembered login uses `FileRememberTokenSessionStore`. New values use Fernet from
`cryptography`; earlier authenticated ciphertext remains readable and is upgraded
after a successful read. Windows machine keys are protected by current-user DPAPI.
Other platforms use a private local key file, so access to both files can recover
the credential. Key creation is process-locked, and encrypted values are replaced
atomically. Missing or corrupt keys are reported rather than silently replaced.
File permissions remain best effort; protect the containing user profile.

The external API-key form uses `EncryptedSettingsKeyStore`, with keyring-first
behavior and encrypted-settings fallback. Its namespace includes the resolved
database path and account ID. Saving a key does not make a service request or
connect an inference engine. This does not mean that all application secrets or
the database are encrypted. The proxy workflow uses the stricter system-only
store instead.

## Network Exposure

Normal work recording does not require a network service. Manual update checks
contact GitHub. Model downloads contact the selected catalog URL. A connected
external AI adapter would transmit its supplied context and messages; the default
desktop does not connect that adapter.

Privacy switches default to including notes, calendar events, and quick logs in
built AI context. A failed settings read stops context construction, and categories
disabled by the user are not queried. Oversized context is rejected before sending.
An external integration must explicitly assess data disclosure and user consent
before enabling transmission. Do not claim that a configured proxy form changes
network routing; the HTTP adapters are not connected to those settings.

## Diagnostics

Runtime logging uses UTF-8 rotating files, up to 1,000,000 bytes per file with five
backups. Explicit credential values are redacted while diagnostic identifiers
remain visible. Exception formatting retains types and source locations but omits
arbitrary exception payloads. This is not sanitization of all possible private text.
Review logs before sharing them. Do not log passwords, recovery keys, tokens,
authorization headers, prompts containing private records, or downloaded secrets.

## Operational Precautions

Keep tested backups outside generated output directories. Verify database upgrades
on copies before using personal records. Restrict write access to application
resources and model catalogs. Do not package private files. Keep dependency
versions and native binaries consistent, and validate any dependency update before
shipping it. See [database handling](database.md) and [packaging](packaging.md).
