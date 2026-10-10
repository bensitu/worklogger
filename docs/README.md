# Documentation

These guides describe the behavior implemented in the repository. They distinguish
desktop features from adapters that require additional runtime configuration.

## Using WorkLogger

| Guide | Contents |
| --- | --- |
| [User guide](user-guide.md) | Accounts, time entry, reports, analytics, settings |
| [Time recording](time-recording.md) | Multiple periods, timer transitions, editing, compatibility, improvement options |
| [Notes](daily-notes.md) | Memos, history references, recoverable drafts, sharing choices |
| [Database upgrade](database-upgrade.md) | Released-source compatibility, safe copying, explicit upgrade tool, templates and credentials |
| [Configuration](configuration.md) | Defaults, language selection, file locations, environment variables |
| [Data formats](data-formats.md) | CSV, iCalendar, Markdown, PDF, and backup scope |
| [Templates](templates.md) | Report variables, rendering, custom templates |
| [Troubleshooting](troubleshooting.md) | Startup, fonts, language, holidays, data, credentials, console errors |

## Maintaining WorkLogger

| Guide | Contents |
| --- | --- |
| [Architecture](architecture.md) | Dependencies, startup, workflows, state, background jobs |
| [Architecture quality](architecture-quality.md) | Dependency review, implemented boundaries, migration improvements, remaining constraints |
| [Database](database.md) | Tables, ownership, migrations, backup and restore |
| [Integrations](integrations.md) | AI, model management, identities, holidays, networking |
| [Local Models](local-models.md) | Hugging Face choices, metadata, memory estimates, runtime compatibility |
| [Localization](localization.md) | Catalog workflow, locale resolution, Qt dialog translation |
| [Development](development.md) | Environment setup, dependencies, coding conventions |
| [Testing](testing.md) | Test organization, isolated fixtures, rendering, verification |
| [Packaging](packaging.md) | Build commands, bundled resources, platform requirements |
| [Security](security.md) | Credential handling, storage boundaries, network behavior |
| [Reliability](reliability.md) | Operational contracts, compatibility decisions, verification limits |
| [Implementation status](implementation-status.md) | Verified fixes, retained design choices, platform and integration limits |
| [Core capability coverage](core-capabilities.md) | Connected recording/reporting improvements, remaining core work and verification limits |

Repository policies: [contributing](../CONTRIBUTING.md),
[security reporting](../SECURITY.md), [conduct](../CODE_OF_CONDUCT.md),
[changes](../CHANGELOG.md), and [license](../LICENSE).
