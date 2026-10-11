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
Install `requirements-dev.txt` for contributor lint tooling; it is not a runtime
or release-build dependency.

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
Describe responsibilities and behavior with neutral, professional terminology.
Remove unused scaffolding rather than preserving it for an unspecified feature.

Keep long operations off the UI thread. Honor cancellation, ownership, optimistic
updates, and disposal. Treat error codes as stable diagnostic identifiers.

## Interface Conventions

Use shared theme tokens, controls, fonts, and Lucide icons. Apply QSS at the
application boundary, not on individual widgets.

Shared rules live in responsibility-specific fragments under
`presentation/theme/qss`. `stylesheets.py` defines their cascade order;
`background_images.qss` handles uploaded backgrounds and `materials.qss` contains
glass-specific effects. Define colors through theme tokens, not separate copies
of component styles. Keep role and state selectors explicit where their priority
is needed. Hover, selection, and disabled states must preserve dimensions and
typography.

Ordinary framed actions use neutral text and outlines; primary actions use accent
backgrounds and the highlighted text role. Destructive actions use the danger role.
Disabled states retain geometry and weight while using muted colors.
Selected navigation uses accent emphasis. Button icons follow their text color.

Qt object names use descriptive snake case and existing suffix conventions.
Icon-only actions need tooltips/accessibility names. Preserve keyboard navigation
and check long translated text. See [localization](localization.md).

## Theme Definitions

Add a `ThemeDefinition` to `config/themes.py` with a stable lowercase key,
a label marked with `N_`, light/dark `AccentColors`, and a `solid` or `glass`
material. Settings choices and configuration validation use this catalog;
customizable choices appear last. Translate new labels through the normal
gettext workflow.

`config/theme_colors.py` validates immutable color roles. Optional
`light_overrides` and `dark_overrides` use `SurfaceOverrides` to customize a few
surface or status colors without duplicating a material. Keep overrides limited
to genuine brand requirements and verify their contrast.

`theme/materials.py` defines reusable surfaces, calendar states, backdrop colors,
stylesheet fragments, and rendering capabilities. `palettes.py` combines these
with brand colors; `qt_palette.py` adapts resolved colors to Qt. Color resolution
and calendar rules do not require Qt. `stylesheets.py` renders shared tokens with
bounded caches. Effects
depend on material capabilities, not a theme's key. Reuse these profiles for
branded themes rather than copying QSS or adding theme-name checks to widgets.
Apply application themes through `ThemeEngine.apply_to`. Custom-painted controls
use `theme/context.py` to read resolved colors; do not infer mode or material from
widget backgrounds, which can be transparent.
Check both color modes, contrast, interaction states, theme switching and
resource packaging when changing a theme or material.

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
python -m ruff check worklogger scripts tests
python scripts/i18n/i18n_check.py
python scripts/build.py --check
git diff --check
```

See [testing](testing.md) for discovery, visual checks, and fixture isolation.
Changing Python/Qt/native dependencies also requires a consistent target build
and artifact checks, not just a successful import.
Continuous integration checks supported Python versions on Windows and Linux,
validates translations, runs ordinary tests and audits dependency vulnerabilities.
Native visual checks remain opt-in.

## Documentation

Write user procedures or durable contributor contracts in English.
Describe supported behavior and operating procedures in neutral, professional
language. Exclude deployment-specific paths, credentials, and temporary records.
Add a guide only when its audience and responsibility cannot fit an existing one.
Published release history belongs in the changelog.
