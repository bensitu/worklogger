# Packaging

## Build Inputs

Build on the target operating system with the intended Python architecture.
`WorkLogger.spec` collects the Python package, Qt runtime dependencies, holiday
modules, keyring backends, certificate data, and selected optional packages.
`scripts/build_resources.py` supplies an explicit application-resource manifest.

Direct runtime dependencies are pinned in `requirements.txt`, and the build
dependency is pinned in `requirements-build.txt`. Optional native inference has
its own `requirements-ai.txt`. The Windows AMD64 CPython 3.11.9 build environment,
including transitive dependencies and bootstrap tools, is captured in
`requirements/windows-cpython311.lock.json` and its hash-pinned `.txt` companion.
Other Python versions, architectures and operating systems require their own lock
and actual artifact verification; do not reuse Windows wheels on those targets.

Install in an isolated environment and verify the exact target, input fingerprints
and installed package set before building:

```powershell
python -m venv .venv-release
.venv-release\Scripts\python.exe -m pip install --require-hashes -r requirements/windows-cpython311.lock.txt
.venv-release\Scripts\python.exe scripts/lock_environment.py requirements/windows-cpython311.lock.json
.venv-release\Scripts\python.exe scripts/release_artifact.py --lock requirements/windows-cpython311.lock.json --build --zip
```

The last command runs the default behavior suite, builds the regular windowed
application, verifies its resources and isolated executable checks, and creates an
archive plus a SHA-256 inventory in `release/`. Visual checks are not part of every
build. Artifacts include `build-info.json` with application version, source digest,
repository revision, dependency versions, lock fingerprint and native-inference
inclusion. The digest identifies source content even when changes are not committed.
The `source_dirty` field identifies builds with uncommitted repository changes.
Build metadata and the repository's GPL license are included by `WorkLogger.spec`.

To capture a new target lock after deliberately resolving and reviewing dependency
updates in a clean environment:

```sh
python scripts/lock_environment.py requirements/target.lock.json --capture
```

This downloads target wheels, records their hashes, and creates the paired install
file. It does not certify dependency security or permit skipping review. For a native
inference lock, install `requirements-ai.txt` first and use `--with-local-inference`
when capturing; native wheel availability must be verified on that target.
For diagnostic environment information:

```sh
python -m pip freeze
python -c "import sys, PySide6; from PySide6.QtCore import qVersion; print(sys.version); print(PySide6.__version__); print(qVersion())"
```

Timesheet XLSX export uses the pinned openpyxl and et-xmlfile packages. The build
checks their availability and includes their modules. PDF generation reuses Qt;
neither export requires a spreadsheet application or a remote service. Install
the updated requirements in source environments before using XLSX export.

## Commands

```sh
python -m pip install -r requirements-build.txt
python scripts/build.py --check
python scripts/build.py
```

The script compiles gettext catalogs, checks them, validates resources, and invokes
PyInstaller with the repository specification. `--check` validates translations,
resources, and required Python module availability, but does not verify native
library loading or the resulting artifact.
Use `--lock requirements/windows-cpython311.lock.json` to require the locked build
environment. A native-inference build also requires that dependency in its lock.

For a Windows artifact with a diagnostic console:

```powershell
python scripts/build.py --console
$env:WORKLOGGER_LANG = "en_US"
.\dist\WorkLogger\WorkLogger.exe --smoke-import
.\dist\WorkLogger\WorkLogger.exe --smoke-startup
.\dist\WorkLogger\WorkLogger.exe --smoke-workflows
```

The build replaces its generated output directory. Never store the only copy of
user data under `dist/`, and do not rebuild over a running executable. Regular
Windows distribution builds omit the diagnostic console.
The workflow check creates a temporary older daily-record database, upgrades a copy,
verifies credentials, recording/context operations, project accounting, report
versions, XLSX/PDF readability and a complete backup. It does not use personal
accounts or make provider requests. These executable checks are also required for
windowed builds and rely on process exit status, not console availability.

The verification script rejects private database/sidecar/model/session files in the
artifact. It does not certify an interactive login, system credential-store access,
tray delivery, a real local model or external provider. Signing, notarization and
non-Windows target checks remain separate release requirements.

## Resources

The resource manifest includes application assets, QSS, and compiled catalogs for
all five languages, plus the public `model_catalog.json` under
`worklogger/assets/models`. It rejects AVIF files; the login bitmap is WebP. UI SVG files,
their license notice, bundled OpenType fonts and notices, and platform icons must
remain available at runtime.

| Platform | Application icon behavior |
| --- | --- |
| Windows | `.ico` executable icon and runtime window icon |
| macOS | `.icns` bundle icon and runtime application icon |
| Linux | Runtime icon asset; desktop integration requires distribution-specific handling |

No user database, model weight file, session credential, or personal export belongs
in the artifact. `tzdata` is required for country mapping and timezone rules.
Native inference is excluded unless `--with-local-inference` is supplied after
installing `requirements-ai.txt`. Builds with this option support the desktop's
local rewriting service after a verified model is selected. Builds without it
retain model-file management but report that native inference is unavailable.

## Platform Outputs

- Windows: `dist/WorkLogger/WorkLogger.exe` and its adjacent runtime directory.
- Linux: the `dist/WorkLogger/` executable directory produced by PyInstaller.
- macOS: the specification also defines `WorkLogger.app` with a bundle identifier
  matching `APP_ID`, application version, and high-resolution display metadata.
  Windows embeds version resources from the same application metadata.

On macOS, `WORKLOGGER_CODESIGN_IDENTITY` optionally selects the signing identity,
and `WORKLOGGER_CODESIGN_ENTITLEMENTS` supplies an entitlement-file path. PyInstaller
propagates these settings to collected binaries and the application bundle. Without
an identity, its default local signing is not a distributable Developer ID signature.
Submit the signed bundle using `xcrun notarytool` with a locally configured credential
profile, then staple the accepted ticket with `xcrun stapler`. Windows distribution
requires Authenticode signing with the publisher's certificate after building.
Certificates and notarization credentials must never be committed.

The specification does not perform installer creation, notarization, Windows
signing, Linux desktop registration, or release upload. Arrange these separately for the
chosen distribution method. Test data-location permissions on each platform,
especially inside a macOS bundle; see [configuration](configuration.md).

## Verification Checklist

1. Run relevant tests and inspect localized light/dark screenshots.
2. Build from a known environment and review missing-library warnings.
3. Run import and runtime checks from the produced artifact.
4. Start interactively with an isolated data directory/account.
5. Verify login, input methods, icons, WebP, fonts, holiday data, saves, exports,
   backup/restore, credential storage, and platform residency.
6. Exercise compatible older databases on copies and retain the originals.
7. Confirm that the artifact contains no private files and includes resource licenses.

Do not replace individual Qt DLLs inside an existing artifact. Rebuild with a
consistent PySide6/Shiboken/Qt set when changing Qt versions.
