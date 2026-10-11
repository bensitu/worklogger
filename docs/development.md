# Development

## Setup

Use Python 3.11 and a virtual environment. Run from the repository checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/i18n/i18n_compile.py
.\.venv\Scripts\python.exe -m worklogger.main
```

On macOS/Linux, use `.venv/bin/python`. Activation is optional.
Install `requirements-ai.txt` only for native local inference and
`requirements-build.txt` for packaging.

The runtime, optional inference, and build lists have separate responsibilities.
The `requirements/` JSON locks identify target environments, input fingerprints,
packages, and wheel hashes; companion TXT files install those exact wheels.
Do not merge them into normal runtime dependencies. See [packaging](packaging.md).

## Code Conventions

Read [architecture](architecture.md) and [contributing](../CONTRIBUTING.md).
Use explicit dependencies, immutable commands/queries, repository contracts,
`Result`, view models, controllers, and existing Qt signals.

Keep calculations out of widgets and storage algorithms out of composition.
Do not introduce speculative abstractions or duplicate established helpers.
Use descriptive English identifiers/comments and standard Python naming.
Remove unused scaffolding rather than preserving it for an unspecified feature.

Keep long operations off the UI thread. Honor cancellation, ownership, optimistic
updates, and disposal. Treat error codes as stable diagnostic identifiers.

## Interface Conventions

Use shared theme tokens, controls, fonts, and Lucide icons. Apply QSS at the
application boundary, not on individual widgets.

Ordinary framed actions use neutral text and outlines; primary actions use accent
backgrounds and white text. Destructive actions use the danger role.
Disabled states retain geometry and weight while using muted colors.
Selected navigation uses accent emphasis. Button icons follow their text color.

Qt object names use descriptive snake case and existing suffix conventions.
Icon-only actions need tooltips/accessibility names. Preserve keyboard navigation
and check long translated text. See [localization](localization.md).

## Data and Resources

Use synthetic accounts and temporary databases. Never commit databases, exports,
credentials, logs, model weights, or generated builds.

Stored formats need an explicit compatibility/backup plan and regression tests.
Keep CSV semantics stable and preserve unsupported sources without mutation.
Add resources to the packaging manifest and check frozen paths.
Public deployment flags are separate from account settings and secrets.

## Checks

Run the smallest relevant tests first, then broader checks as warranted:

```sh
python -m unittest tests.domain.test_worklog_rules -v
python scripts/i18n/i18n_check.py
python scripts/build.py --check
git diff --check
```

See [testing](testing.md) for discovery, visual checks, and fixture isolation.
Changing Python/Qt/native dependencies also requires a consistent target build
and artifact checks, not just a successful import.

## Documentation

Write user procedures or durable contributor contracts in English.
Keep deployment-specific paths, credentials, incident reports, development
milestones, one-off test results, and roadmaps out of public guides.
Add a guide only when its audience and responsibility cannot fit an existing one.
Published release history belongs in the changelog.
