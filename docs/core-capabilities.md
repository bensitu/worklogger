# Core Capability Coverage

This guide records implementation coverage for the agreed personal recording and
reporting scope. It is not a release schedule. The separate product-direction
analysis remains an offline file and is not part of repository documentation.

## Connected Capabilities

| Capability | Current behavior |
| --- | --- |
| Data-location information | README identifies the packaged application-local user-data directory correctly |
| Project and work-item context | Optional account-owned catalogs, settings management, archival/completion, recorder choices, timer restoration, stable associations and saved labels |
| Record retrieval | Account-scoped date/type/context/text filters, unclassified selection, bounded chronological paging, background search and navigation to the existing editor |
| Project statistics | Selected date-range work/rest/leave totals by saved project and work-item identity, work-date counts and paged record drill-down |
| Interval correction | Transactional elapsed-minute splitting and adjacent compatible merging; ownership, expected versions, overlap and duration checks |
| Historical rest | Explicit whole-minute break placement with preview; no inferred boundaries or duplicate deduction |
| Recovery | Bounded reversible individual-record changes with stable IDs and newer revisions; confirmation and no timer restart |
| Timer reminders | Configurable nonblocking long/continuous-work-timer reminders, inline and optional tray notification, explicit long-timer end correction with timezone validation |
| Report context | Individual lines show project/work-item labels; the optional `projects_summary` variable groups recorded work without including rest or leave |
| Delivery | Selected day/month XLSX and paginated Unicode table PDF, separate work/rest/leave columns, reference metadata, safe text cells and atomic destinations |
| Compatibility | Existing type IDs, account credentials, clock/offset semantics and historical deductions remain; schema upgrades retain a complete pre-change snapshot |

Project codes and work-item source URLs can be edited in the catalog. This does
not yet provide complete historical source-link capture or project descriptions,
colors and effort estimates. A catalog is not a full task-management system.

CSV preserves context labels without assuming foreign IDs are valid in another
database. Mapping imported labels to local catalogs is explicit, not automatic.
Whole-database backups retain complete catalogs, associations, and record history.

Undo covers individual creates, edits, deletes, splits, merges and rest conversion.
It excludes bulk CSV replacement and database restore. No redo is exposed. History
eligibility is 30 days and storage is capped at 50 changes; expired snapshots are
removed during subsequent mutations, not from retained backup files.

Continuous-work-timer reminders evaluate one active work interval. They do not
reconstruct continuous work across earlier records or make employment-law claims.
Spreadsheet outputs contain snapshot totals, not a live recalculating model or
user-supplied template execution. PDF is a time-record table, not a chart export.

## Remaining Core Work

The following agreed capabilities are not implemented by the changes above:

- Daily timeline with distinct confirmed, active, planned and uncovered intervals.
- Weekly timesheet review and deliberate placement of duration-only drafts.
- Conflict-aware batch record association and reusable recent context.
- Bounded grouped template sections and comprehensive report provenance/source references.
- Distinct report revision history, immutable submitted snapshots and recovery.
- Explicit period finalization/reopening enforced beyond presentation controls.
- Explainable configurable working-time policies, with unknown/incomplete results.
- A skippable initial setup, isolated demonstration data and a visible data-directory action.
- Dependency environment locking, automated verification/distribution, signing and target-platform artifact checks.

These are separate remaining responsibilities. Existing code for an adapter,
documented design or a successful test run does not establish their completion.
Country-specific employment presets require applicability/source maintenance;
actual signing and non-Windows artifact validation require their target environment
and appropriate credentials.

## Conditional Extensions

Synchronization, billing, clients/tags, provider connectors, activity observation,
local inference servers, natural-language capture, assistant interfaces and
encryption remain outside the confirmed scope until separately authorized.
No remote request or paid-provider validation was added by this work.

## Verification Boundaries

Behavior and integration checks use isolated databases and synthetic records.
Relevant coverage includes migrations, ownership, archived context, timer capture,
revisions, overlap, undo, literal search, paging, exports and draft preservation.
Visual checks remain opt-in and were used for changed controls, five languages,
light/dark palettes and PDF rendering. Actual spreadsheet-application editing,
native tray notification and signed multi-platform artifacts are not certified by
these checks. See [testing](testing.md), [recording](time-recording.md),
[data formats](data-formats.md), [database](database.md), and [packaging](packaging.md).
