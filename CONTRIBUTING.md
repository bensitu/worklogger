# Contributing

## Preparation

Read the [architecture](docs/architecture.md), [development instructions](docs/development.md),
and [code of conduct](CODE_OF_CONDUCT.md). Use a virtual environment and synthetic
or temporary data. Do not include personal databases, credentials, exports,
downloaded models, or generated distributions in a contribution.

## Design and Code

- Keep domain calculations independent of Qt, SQLite, and network clients.
- Put application orchestration in use-case handlers and external integrations in
  infrastructure adapters. Assemble dependencies in `worklogger/bootstrap.py`.
- Keep widgets responsible for presentation; use view models for state and
  workflow controllers for dialogs and background operations.
- Follow existing `Result` and error-code handling. Do not silently weaken input
  validation, account checks, backup validation, or credential storage.
- Write documentation, comments, identifiers, and test descriptions in neutral,
  professional English. Describe observable responsibilities and behavior rather
  than development chronology or private project terminology.
- Use descriptive module names, `snake_case` functions, and `PascalCase` classes.
  Retain standard library terminology and externally defined protocol names.
- Keep changes focused. Add comments only when the reasoning is not evident from
  the implementation. Update the relevant guide when behavior changes.

## User Interface and Translations

Use the existing theme tokens, widgets, icons, and fonts. Apply application QSS at
the application boundary rather than introducing per-widget stylesheets. New Qt
object names must be descriptive and follow the existing suffix conventions.

New user-visible strings must use gettext. Update all five catalogs, compile them,
and run the checks in [localization](docs/localization.md). Verify long labels,
dark mode, keyboard navigation, error display, and supported display scaling.

## Persistent Data

Changing stored names or formats requires an explicit compatibility strategy,
ordered migration, backup behavior, and tests using previous database layouts.
Do not modify a user's database to prepare a test. Preserve CSV column semantics
and clearly document any changed import or export behavior.

## Validation

Run the smallest relevant tests first. Maintain durable behavior and integration
coverage rather than duplicating implementation details or retaining temporary
diagnostic reproductions. Expand verification when shared behavior, persistence,
or compatibility changes; the complete suite is not required for every small edit.

The default suite excludes visual checks. Run the relevant optional checks for
layout, theme, font, image, or Qt rendering changes. See [testing](docs/testing.md)
for commands and limitations. Useful broader verification commands include:

```sh
python scripts/i18n/i18n_check.py
python -m unittest discover -s tests -t . -v
python scripts/build.py --check
git diff --check
```

Describe the change, its user impact, commands run, and any checks that were not
performed. Include before/after screenshots for visual changes, using synthetic
accounts and records. Do not describe untested platforms as verified.

## Reporting Problems

For non-sensitive defects, use the repository's issue tracker and include the
application version, OS, Python/PySide6 versions, reproducible steps, expected
behavior, and actual behavior. Remove personal information from attachments.
For credential or data exposure, follow [the security policy](SECURITY.md) instead.
