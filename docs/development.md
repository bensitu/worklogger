# Development

## Environment

Run commands from the repository root. The verified environment is Python 3.11.9,
PySide6/Qt 6.11.0, and Windows. The build dependency file pins PyInstaller 6.22.3.
There is no package-install configuration such as `pyproject.toml`; run the module
from the checkout rather than using `pip install -e .`.

Use a virtual environment so dependency experiments do not replace system-wide
packages. The examples use Python 3.11 and the verified PySide6 version. Other
versions require testing; runtime dependencies are not all pinned.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt "PySide6==6.11.0"
python -m pip install -r requirements-build.txt
python scripts/i18n/i18n_compile.py
python -m worklogger.main
```

Activation is optional. If PowerShell blocks activation, invoke
`.\.venv\Scripts\python.exe` explicitly. On macOS/Linux, create the environment
with `python3 -m venv .venv` and use `.venv/bin/python`.

## Desktop-Only Dependencies

The default desktop does not construct a local inference engine. A development
environment that does not need native model inference can install the desktop
dependencies explicitly:

```sh
python -m pip install "PySide6==6.11.0" tzlocal holidays cryptography keyring certifi "PyJWT>=2.8.0" "httpx>=0.27.0" "portalocker>=2.8.0"
```

This intentionally omits `llama-cpp-python`. The repository's full requirements
include it; compiling it may require native build tools. CPU and GPU packages must
match the target machine and their provider's instructions. Merely installing
this package does not connect the application's local inference adapter.

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
