# Architecture Quality

## Dependency Review

Domain code has no database, Qt, or infrastructure imports. Application operations
coordinate domain contracts without importing presentation or infrastructure.
SQLite, files, credentials, and Qt are adapter choices. The composition root is
allowed to construct those implementations, but must not implement their storage
algorithms.

The following concrete dependencies have been reduced:

| Previous relationship | Current boundary |
| --- | --- |
| Record widgets called the time service and maintained deletion state | Widgets invoke view-model operations; view models own draft/completed-record updates and elapsed-time state |
| View models required a concrete recorder service | `TimeEntryOperations` defines the injected application contract |
| Importing one view model eagerly loaded every other model and Qt themes | Public view-model exports are loaded on demand |
| Language and color validation depended on Qt-aware adapters | Pure language identifiers and appearance rules live in the domain |
| Calendar, reports, and analytics implementations shared one large module | Each page has a separate module; the public import facade retains caller compatibility |
| Startup contained SQLite copying and file replacement logic | A validated database-copy adapter owns that operation |
| Restore imported private migration details | Shared schema definitions and read-only inspection support both restore and upgrade |
| Every migration separately inspected and backed up the same database | One runner determines pending versions and creates one complete pre-change snapshot |
| Startup built every feature inline | Domain-focused composition functions construct recording, reporting, settings, and model workflows |
| One settings surface constructed all controls | Independent sections own widgets and receive explicit callback bindings |
| One settings controller owned every pending operation | Data, account, and update workflows have isolated dependencies and state |
| The main window directly coordinated calendar query results | A calendar coordinator updates views; the window keeps navigation and lifecycle |
| One worklog repository mixed all queries, writes, and mapping | A stable facade composes query/write components with shared schema mapping |

These changes preserve UI behavior and persisted identifiers. They do not add a
global service locator, a second event system, or an additional GUI framework.

## Upgrade Boundaries

Released database definitions from 3.0 and 3.3 are represented independently in
integration fixtures. They are not manufactured by first creating a current
database and renaming a single column. Coverage checks credentials, account IDs,
forced password changes, nullable work fields, overnight durations, settings,
reports, identity rows, snapshot rollback, and repeated startup.

Schema-version history remains authoritative. A supported old layout is converted
once; an unknown future version is rejected. Historical modules remain ordered
transformations, while obsolete preparation hooks have been removed. Credential
compatibility authenticates ciphertext before replacing it and preserves values
when authentication fails.

## Remaining Boundaries

- The desktop still uses SQLite and short-lived connections. A network storage
  implementation would need to preserve optimistic updates, overlap validation,
  and atomic timer transitions; replacing connection calls with HTTP calls alone
  would not satisfy the contract.
- Calendar presentation state still includes painting tokens. This is appropriate
  for Qt but is not a transport-independent web representation.
- Holiday availability is supplied by an infrastructure catalog. Settings views
  still consult that catalog; pure shape validation and actual country support
  are different responsibilities.
- Translation and resource helpers remain presentation adapter dependencies.
- Machine-bound credentials require their original OS keyring or key material.
  Database portability cannot make those credentials decryptable on another
  machine without an explicit secure key-transfer process.
- Previous global custom templates cannot be assigned to an account or chosen
  among competing templates automatically. The upgrade tool requires that choice.

Future work should follow measurable needs: batch read ports for large report
ranges, a distinct transport-facing calendar model when adding another frontend,
and account-scoped settings snapshots when repeated preference reads become a
measured bottleneck. UI rules and SQL must not be duplicated in those adapters.
