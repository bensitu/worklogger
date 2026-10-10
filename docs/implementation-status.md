# Implementation Status

This document records verified behavior and remaining constraints in the current
desktop implementation. Decisions prioritize data preservation, explicit network
consent, predictable error results, and responsive editing.

## Recording and Presentation

| Concern | Current resolution |
| --- | --- |
| Administrator operations block interaction | User listing, creation, reset, changes, and deletion run on background workers; duplicate mutation and premature close are prevented. |
| Adjacent-month cells show incorrect hours | One range query covers all 42 visible dates and their weekly totals. |
| Report rewrite submission leaves controls locked | Submission failure restores controls and retains the draft. |
| Presentation names and login identifiers share one field | Separate editable Display name and read-only Login ID; fallback, authentication, and ownership remain independent. |
| Rejected history navigation leaves misleading selection | Selection returns to the report still open in the editor. |
| Removed users cause unrelated selection | Refresh preserves the selected user by ID; absent selections are cleared. |
| Fixed break validation describes the wrong constraint | A dedicated error describes a positive duration of at most four hours. |
| Notes prevent compact-window navigation silently | A translated prompt asks the user to close the note editor first. |

## Credentials and Storage

| Concern | Current resolution |
| --- | --- |
| Non-Windows machine-key file has weaker protection | This is an explicit local-security boundary, not equivalent to DPAPI. Private permissions and approved OS credential stores remain in use; possession of both files can recover remembered credentials. No incompatible key replacement was introduced. |
| Previous ciphertext derives a predictable key | Read-only compatibility remains necessary for older installations. Successful reads upgrade ciphertext or move the secret into approved storage; new writes never use this derivation. |
| Recovery attempts have no throttling | Recovery shares canonical account login failure limits and clears them after success. |
| Cross-device encrypted settings cannot be read | Settings show re-entry guidance and permit credential replacement without changing work records or regenerating an unreadable machine key. |

## Performance

| Concern | Current resolution |
| --- | --- |
| Routine settings saves repeatedly call keyring | Credential results are reused until explicit refresh or a successful credential write. |
| Report reads, saves, history, and exports are synchronous | These operations run through the page's background runner and busy-state handling. |
| SQLite connection setup and serialization add overhead | Retained intentionally: independent connection ownership, backup/restore coordination, permissions, and transactional safety take priority over an unmeasured pool redesign. |
| Timer ticks invalidate layouts and refresh controls | Ordinary ticks only update elapsed text; state transitions and Qt layout events update controls/layout. |
| Analytics reads entire histories and queries twelve months separately | Dashboard ranges are bounded to comparisons/trends; yearly chart input uses one range query. |
| Stylesheet templates are reread unnecessarily | The two immutable shared templates are cached. |
| Authentication hashing runs on the UI thread | Login, registration, recovery, and password changes run on workers. |
| Note initialization reads storage synchronously | Initial note loading uses its existing background workflow. |
| Main calendar navigation uses indexed synchronous reads | Retained for now. The visible range is bounded; no speculative connection pooling or concurrent-widget mutation was introduced. Measure large-account latency before moving the coordinated snapshot to a worker. |

## Integration and Compatibility

| Concern | Current resolution |
| --- | --- |
| Account proxy preferences do not route requests | Explicit HTTP CONNECT routing is connected to updates, model downloads/catalogs, and external AI, preserving TLS verification and public-target checks. |
| Calendar end-of-day notation cannot be copied | The calendar preserves `24:00`; copying into a time record converts it to next-day `00:00`, with the usual duration limit. This notation is not a valid wall-clock time for the general parser. |
| External AI settings do not activate a service | An account gateway is connected. New opt-in defaults to false; configuration alone never sends requests and local failure never triggers remote fallback. |
| Linux has no configured tray residency | Documented platform limitation, not a data or operation defect. Native Linux desktop integration remains unverified and unchanged. |
| macOS credential paths are nonstandard | New installations use Application Support. Existing key/session files remain together at their original location. |
| Compact-window dates ignore localization | The compact view now uses the shared translated date label. |

## Error Handling and Consistency

| Concern | Current resolution |
| --- | --- |
| Storage exceptions escape application results | Worklog, calendar, quick-log, identity, authentication, local-model, and template operations convert storage failures to safe typed results. |
| External account creation can leave an orphan | Account and identity insertion commit or roll back together; collision retry is bounded. |
| Corrupt storage has only generic startup feedback | Confirmed corruption receives specific translated recovery guidance. Original files are retained; startup never silently creates a replacement database. |
| Quick-log descriptions and templates have no upper bound | Descriptions are limited to 16,000 characters, notes/templates to 1 MiB UTF-8; invalid inputs do not write storage. |
| CSV conflict preview has no specific message | Conflicting dates have translated feedback without exposing an internal code. |
| Database-copy preparation temporarily removes its reserved file | Copying now replaces the still-reserved temporary destination with a consistent SQLite snapshot. |
| Injected model dialogs can run downloads synchronously | Every dialog has a runner by default; synchronous production fallback branches are removed. |

## Maintenance

| Concern | Current resolution |
| --- | --- |
| Unconnected event and static gateway abstractions | Event contracts and the static routing helper remain small public extension APIs. Desktop recording uses entry commands; desktop AI uses explicit account routing. Tests of an adapter do not imply a connected UI. |
| Theme arguments and incomplete stylesheets misrepresent behavior | Only complete light/dark templates remain; palette tokens supply every preset/custom theme. The unused theme argument is removed. |
| Template persistence depends on an assertion | Missing saved rows raise an explicit error, including optimized Python execution. |
| Main window reads sidebar internals | Navigation buttons are obtained through a public accessor. |
| URL port validation is an unexplained expression | Ports are explicitly required to be within 1 through 65535. |
| Standalone note-saving handler bypasses content limits | It now enforces the same 1 MiB limit as the memo workspace. The application API is retained. |
| Custom chart accents can make white labels unreadable | Text switches between black/white using relative luminance and contrast. |
| Hidden compact windows retain date polling | Date polling stops when hidden and resumes on display. Recording state remains independent of window visibility. |

## Verification Limits

The current default suite passed 420 tests. Focused Qt layout checks passed for
account administration, report/settings pages, recovery credentials, and model
details. Ruff undefined/unused checks, gettext catalog validation, and whitespace
checks also passed. Visual checks remain opt-in rather than part of default test
discovery.

Durable tests use temporary databases, synthetic credentials/text, injected HTTP
responses, and opt-in Qt layout checks. No live paid provider requests, real proxy
credentials, or personal database content were used. Provider/enterprise network
interoperability, macOS/Linux keyrings and residency, and packaged binaries still
require target-environment verification. See [testing](testing.md),
[integrations](integrations.md), and [security](security.md).
