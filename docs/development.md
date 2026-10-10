# Development

## Environment

Run commands from the repository root. The verified environment is Python 3.11.9,
PySide6/Qt 6.11.0, and Windows. The build dependency file pins PyInstaller 6.22.3.
There is no package-install configuration such as `pyproject.toml`; run the module
from the checkout rather than using `pip install -e .`.

Use a virtual environment so dependency experiments do not replace system-wide
packages. The examples use Python 3.11 and the verified PySide6 version. Other
versions require testing; direct runtime dependencies are pinned.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt
python scripts/i18n/i18n_compile.py
python -m worklogger.main
```

Activation is optional. If PowerShell blocks activation, invoke
`.\.venv\Scripts\python.exe` explicitly. On macOS/Linux, create the environment
with `python3 -m venv .venv` and use `.venv/bin/python`.

## Desktop-Only Dependencies

The default requirements install the desktop without native model inference.
Local text processing uses the separate optional
requirements with a wheel appropriate to their CPU/GPU and operating system:

```sh
python -m pip install -r requirements-ai.txt
```

This includes `llama-cpp-python`; compiling it may require native build tools. CPU and GPU packages must
match the target machine and their provider's instructions. Merely installing
this package does not download or select a model. The desktop connects the native
adapter when a verified model is selected and the corresponding preferences are enabled.

## Runtime Checks

```sh
python -m worklogger.main --help
python -m worklogger.main --smoke-import
python -m worklogger.main --smoke-runtime
python -m worklogger.main --smoke-startup
```

`--smoke-runtime` and `--smoke-startup` perform the same temporary-database runtime
construction and refresh check. They do not exercise an interactive login, the
entire event loop, network services, or native OS dialogs. Runtime setup may still
initialize logging and read native language preferences. Use unit-test fixtures
when all machine-level state must be isolated.

In a terminal unable to encode the selected language, use `WORKLOGGER_LANG=en_US`
for command-line diagnostics. This does not replace testing GUI localization.

## Code Organization

Read [architecture](architecture.md) before adding a feature. Favor the existing
patterns: immutable commands/queries, handler constructors with explicit
dependencies, repository protocols, `Result`, view models, controllers, and Qt
signals. New shared abstractions should solve a concrete repeated need.

Application metadata is in `worklogger/__about__.py`. Stable application defaults
are in `worklogger/config/constants.py`. User settings belong in their repository,
not in source code or new machine-specific files.

Use English comments and neutral, descriptive names. Public documentation should
explain supported behavior and limitations. Standard technical identifiers such
as HTTP, SQLite, PKCE, GGUF, and gettext retain their usual meanings.

## Action Styling

Button roles are defined by the shared application stylesheet, not individual
color assignments. Primary actions use theme-colored backgrounds, white text and
weight 600. Ordinary and outline actions use neutral text and weight 500. Auxiliary
ghost actions use neutral text, transparent backgrounds and weight 400. Destructive
actions use danger-colored text and weight 500. Disabled actions use the disabled
palette while retaining their role's weight to prevent layout shifts.
Disabled ghost actions keep their transparent background and border; only the
foreground is muted. Their hover feedback uses a soft fill without introducing
an outline. Reserve this role for text links and controls embedded in record rows.
Standalone icon actions, including copy, reload, history, clear, undo and period
navigation, use the outline role. Their borders remain visible when disabled.

Navigation and view selectors use theme-color emphasis and weight 600 only when
selected. Record summaries retain weight 400; saved-report entries use 400 normally
and 500 when selected. Headings keep their separate hierarchy. Existing bundled
Noto families remain unchanged; Qt resolves requested emphasis against available
font faces. Font sizing and styling remain at the application stylesheet boundary.

Use `set_button_icon` for Lucide action icons. It reads the owning button's effective
text palette through a weak reference, so theme changes, disabled states, selected
navigation and late role assignments stay synchronized. Per-call accent overrides
are not supported for buttons. Provider logos and non-action status icons retain
their branded or semantic colors. Export-menu arrows use the native style palette.

Assign primary roles to save, creation, sign-in, apply and main timer actions.
Automatic recording's separate Save Content action is secondary; manual Save is
primary. Close and export actions do not become primary merely because they appear
in a footer. Refresh dynamic-property styling with the existing `refresh_style`
helper when switching a role on a live control.

Analytics period and action controls use one 44-logical-pixel toolbar height.
The note toolbar groups polishing and export before outlined copy and reload;
its icon buttons use 40-by-40 logical-pixel targets and matching keyboard order.
About intentionally omits a section subtitle. Its status area remains allocated
when empty, and update checks disable only the repeated-check action rather than
the presentation area, preserving both geometry and the application image colors.

Table and tree data views use the shared surface background rather than the page
background. Light mode uses white for both ordinary and alternating rows, including
the empty viewport. Dark mode uses dark surfaces and retains alternating-row contrast.
Selection highlighting remains controlled by the theme palette.

## Data Safety

Never use the development user's actual database as a writable test fixture.
Use temporary paths with `DesktopRuntimeConfig` or test repositories. Back up
before running a different application revision against real records. See
[database compatibility](database.md).

Ignored build outputs, database files, model files, and private configuration are
not release inputs. Some local documentation is also deliberately excluded from
version control; do not add it with a force option.

## Validation and Maintenance

- [Tests](testing.md) describe focused, full, visual, and persistence checks.
- [Localization](localization.md) explains extraction, translation, and compilation.
- [Packaging](packaging.md) covers resources and application builds.
- [Contributing](../CONTRIBUTING.md) defines review and reporting expectations.

When changing Python or Qt, create a separate environment, record the selected
versions, run the tests, inspect screenshots, rebuild on each target OS, and test
the resulting artifact. Do not equate successful source imports with a verified
desktop distribution.
