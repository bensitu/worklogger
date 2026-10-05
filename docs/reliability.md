# Reliability and Compatibility

This guide summarizes current operational contracts and their limits. Detailed
formats and recovery procedures are in [database](database.md),
[data formats](data-formats.md), [security](security.md), and
[integrations](integrations.md). These contracts do not imply certification or
complete coverage of every operating-system configuration.

## Data Operations

| Topic | Current behavior |
| --- | --- |
| Database recovery | Lock, permission, and I/O failures leave the original database intact. Desktop startup never automatically replaces it; explicitly enabled maintenance recovery preserves confirmed corruption and its sidecars together. |
| Integrity checking | A factory checks integrity once on first successful open. Account settings are loaded in one query; period data uses bounded repository queries. |
| Administrative backup | Whole-database backup and restore require a current administrator. Personal exports remain account-scoped. Restore rejects unsupported tables, views, and triggers. |
| Export file selection | All existing page and compatibility-dialog file selectors use nonconflicting gettext names. Dialog fallbacks remain public presentation interfaces rather than being removed solely for duplication. |
| Desktop startup | Failures display translated messages; normal authentication cancellation is quiet. Packaged databases use user-data directories, and a database-specific lock prevents multiple desktop instances. |
| Restored account identity | Restore requires the signed-in account's username and ID to match the source. Successful replacement ends the session before further account operations. |
| Restore replacement | Source and target snapshots include committed WAL data. Replacement shares the connection lock, rejects a busy target, preserves the previous database, and blocks unresolved interrupted replacement. Backups are standalone rollback-journal files. |
| Calendar replacement | Replacement is transactional. Appending deduplicates matching date, time, and content instead of repeating imported entries. |
| CSV import | Size/row limits, language-aware encoding, finite numeric validation, strict work types, slash dates, preview, explicit overwrite permission, and a single batch transaction protect imported records. |
| Calendar interpretation | Mature iCalendar libraries handle UTC/named timezones, finite recurrence, exclusions, cancellations, multiple days, and nested alarms. Only source filenames are retained. |
| Recorded shift length | Automatic completion uses the captured date and real elapsed interval. Shifts outside the allowed 16-hour maximum are rejected rather than reduced to clock-only intervals. |

## Services and Configuration

| Topic | Current behavior |
| --- | --- |
| Login failure counters | Counts expire after inactivity, are capped, and are pruned. Unknown usernames are not stored. Canonical account keys prevent separate counters for equivalent identifiers. |
| Credential encryption | New encrypted values use Fernet. Legacy ciphertext remains readable and is upgraded. Keys are created atomically under a process lock; invalid keys are not silently replaced. Windows keys use current-user DPAPI. |
| Linux credential storage | Approved KWallet backends are accepted alongside the existing platform credential services. Actual availability still depends on the OS session. |
| External AI transport | HTTPS is required, redirects are rejected, and only connection-establishment failures are retried. Diagnostic error codes are bounded and response messages are not exposed. |
| Model transfer | Downloads require SHA-256, validate range/length responses and public destinations, lock partial files, support cancellation, and preserve existing destinations until validation succeeds. Invalid individual catalog entries are skipped. |
| Release transport | Certificate validation uses certifi. Response size and JSON object shape are checked, and destination/redirect addresses must be public. |
| Spreadsheet text | Formula-sensitive exported text is prefixed with an apostrophe. CSV remains an unencrypted interchange format, not a byte-for-byte archive of note text. |
| Diagnostic privacy | Logging redacts explicit credentials while preserving useful identifiers. Exception output includes type and source locations, not arbitrary payload text. |
| Federated identity | Helpers verify signed tokens, issuer, audience, lifetime, subject, nonce, and provider agreement. Account-name collisions and removal of the final usable login method are handled. Desktop provider login remains disconnected. |
| Schema compatibility | Migrations and their version records are transactional. Unknown or newer versions stop startup. Preparation snapshots preserve existing data before compatibility changes. |
| Account uniqueness | NFKC and Unicode casefolding define the unique account key. Display names and integer IDs are preserved; existing collisions stop migration instead of merging accounts. |
| Independent notes | Notes do not create empty work rows and survive work deletion. Concurrent editor writes compare loaded note content in the same transaction. |
| Reusable interfaces | Last-login timestamps are written, account deletion removes stale activity references, and unused periodic-expiry code was removed. Valid container, job, repository, and report contracts are retained for explicit composition. |
| Administrator password reset | Reset returns only a temporary password, invalidates existing recovery/session credentials, and requires the account owner to change the password and obtain a new recovery key. |
| Weekly periods | Reports, calendar views, AI context, and analytics buckets use the account's Sunday-first or Monday-first preference. |
| Holiday regions | Country detection uses bundled timezone data, with explicit country and subdivision selection. Unknown zones do not fall back to US holidays. |
| AI context | Repository reads are period-bounded. Disabled private categories are not fetched, settings failures stop construction, and oversized context is rejected before transmission. Chat cancellation has its own result. |
| Current date | Regular date refresh and the Today action update long-running views without discarding the selected date or unsaved editor state. |
| Automatic state | Account-scoped start/break boundaries and pending drafts survive reopening. Editing notes or browsing dates does not reset the timer; quarter-hour break rounding is explicit. Invalid persisted state requires deliberate replacement. |
| Report content | Generated labels use gettext, queries are period-bounded, multiline list content is indented, and daily/weekly/monthly ranges are validated against their types. |
| Model verification cost | Checksum results are cached by file path, timestamps, size, and expected digest. Changes invalidate the cached result. Verification is not a test of inference quality. |
| Icon rendering cost | SVG renderers and pixmaps are bounded and cached by asset, theme color, size, and device pixel ratio. |
| Translation activation | Catalog compilation is documented before tests and builds. Stable action identifiers control workflow logic. Explicit-language lookups reuse catalogs, and imports do not activate a language. |
| Distribution configuration | Direct dependencies are pinned, native inference is optional, metadata shares one application identity/version, and supported feature switches control desktop composition. Remote catalogs require an explicit HTTPS URL. Signing credentials remain external. |

## Boundary Conditions

| Topic | Current behavior |
| --- | --- |
| Time parsing | Decimal digit validation rejects unsupported numeric glyphs. Legacy dotted clock syntax requires two minute digits; ambiguous decimal-looking input is rejected. |
| Missing setting values | SQL NULL is returned as an absent value, not the string `None`. |
| Quick-log ownership | Updates and deletion require an existing account-owned record. Missing records return a failure rather than false success. |
| Saved report updates | Loading an existing report retains its ID. Changed content requires overwrite confirmation; creation time and ID are preserved. Independent drafts may intentionally create separate reports for the same period. |
| Event subscribers | One failed subscriber is logged without interrupting delivery to other subscribers or changing a completed save's outcome. |
| Invalid stored rows | Collection readers omit invalid rows and log counts without modifying the originals. Invalid optional timestamps are treated as absent. This is recoverability, not automatic data repair. |
| Background shutdown | The owned job pool receives cooperative cancellation, waits during shutdown, and suppresses callbacks to closed presentation objects. Blocking transports still finish within their configured timeouts. |
| Exported event identifiers | Work-event identifiers are stable for an account and date; summaries use the selected language. |
| Export replacement | CSV, iCalendar, PDF, and Markdown write through private temporary files and atomic replacement. Required extensions are appended instead of replacing a user-specified suffix. |
| PDF text | Qt rendering provides Unicode text and pagination without opening another window. The output is a text summary, not a chart image. |
| Model metadata replacement | JSON metadata uses private temporary files and atomic replacement. A failed remote refresh reports an error while cached local models remain readable. |
| Numeric preferences | Nonfinite values are rejected on write. Invalid stored values use documented defaults rather than silently selecting the upper limit. |
| Legacy proxy credentials | Startup encrypts existing plaintext for all accounts. New backups remove proxy credentials and free-page remnants. Private pre-change snapshots can contain the originals and must remain protected. |
| Model selection | Import and download must verify the file before updating the account's active model. |
| Daylight saving | New desktop entries retain offset-aware timestamps and measure duration in UTC. Older records keep their original clock-based semantics. Ambiguous manual times use the first occurrence; nonexistent times are rejected. |
| Language preference consistency | Failure to save the pre-login preference restores the previous account preference rather than reporting an unexplained partial update. |
| Account role labels | Administrator and user labels pass through gettext. |
| Static maintenance | Unused imports and fragile loop captures are removed. Identity configuration is cached by path, timestamp, and size while environment overrides remain live. |

## Verification and Limits

Functional coverage uses representative domain boundaries, temporary file databases,
transaction failures, persistence round trips, injected network responses, and
desktop workflow contracts. Visual checks remain optional and are used when
rendering changes require them; see [testing](testing.md).

Current verification uses Windows, Python 3.11.9, and PySide6/Qt 6.11.0. Source
test discovery, catalog/resource checks, the Windows diagnostic-console build,
packaged import/startup checks, and embedded version metadata have passed.
The changed holiday-settings controls were inspected in a narrow localized window
without horizontal overflow; this was not a full visual matrix. The native
macOS/Linux credential services, tray behavior, signing, notarization, and release
artifacts require target-platform verification. Direct dependency pins do not lock
every transitive package or platform wheel. Record the complete build environment.

The standard desktop still does not construct an AI generation engine or a complete
external-provider login workflow. Proxy preferences do not route outgoing HTTP
traffic. A nonempty repository catalog is not automatically copied into shared
runtime model storage. Existing user-edited catalog content is not changed by
configuration updates. These are explicit integration boundaries, not enabled
features inferred from an adapter's presence.
