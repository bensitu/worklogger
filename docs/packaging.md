# Packaging

Dependency input fingerprints normalize text line endings. Wheel hashes remain
byte-for-byte checksums for the declared target platform.

## Dependencies

Build on the target operating system and architecture in a clean environment.
`requirements.txt` supplies runtime dependencies, `requirements-build.txt`
supplies the pinned installer and build tools, and `requirements-ai.txt` supplies
optional native inference.

Target locks under `requirements/` contain the exact Python/OS/architecture,
input hashes, package versions, and wheel hashes. The adjacent TXT is the
hash-pinned installation file. Use a lock matching the actual target; do not
reuse Windows wheels or a lock from another Python version.

For the supplied Windows target:

```powershell
python -m venv .venv-release
.venv-release\Scripts\python.exe -m pip install --require-hashes -r requirements/windows-cpython311.lock.txt
.venv-release\Scripts\python.exe scripts/lock_environment.py requirements/windows-cpython311.lock.json
.venv-release\Scripts\python.exe scripts/release_artifact.py --lock requirements/windows-cpython311.lock.json --build --zip
```

To capture a different target after reviewing its dependencies:

```sh
python scripts/lock_environment.py requirements/target.lock.json --capture
```

Install native inference first and add `--with-local-inference` when capturing
a lock for that build. Review dependency updates and advisories; hashes establish
artifact identity, not security.

## Build Commands

```sh
python -m pip install -r requirements-build.txt
python scripts/build.py --check
python scripts/build.py
```

`--check` compiles/checks catalogs and validates resources/dependency availability.
Normal builds invoke `WorkLogger.spec`. Add `--lock <path>` to require an exact
locked environment. Add `--with-local-inference` to include the native backend,
or `--console` for a diagnostic console.

Build options set `WORKLOGGER_BUILD_CONSOLE` and
`WORKLOGGER_BUILD_LOCAL_INFERENCE`. Close executables under `dist/` before
rebuilding and keep user data out of generated directories.

## Resources and Outputs

`scripts/build_resources.py` explicitly collects fonts, icons, QSS, five compiled
gettext catalogs, the model catalog, and public `worklogger.config.json`.
Private databases, exports, credentials, logs, and model weights do not belong
in a distribution.

PyInstaller also collects required holiday/timezone/certificate/keyring resources
and selected optional native libraries. Keep a consistent PySide6/Shiboken/Qt set;
do not replace individual DLLs.

Use a new virtual environment when upgrading the Qt dependency set. PySide6 6.12
distributes Qt PDF and Qt WebEngine as separate packages, which are included in
the target lock. In-place upgrades from older releases can remove overlapping
module files during package uninstallation. Verify `PySide6.QtPdf` imports before
building.

Windows/Linux builds produce an executable directory under `dist/WorkLogger/`.
The macOS specification creates `WorkLogger.app`.
Version resources use application metadata. On macOS,
`WORKLOGGER_CODESIGN_IDENTITY` and `WORKLOGGER_CODESIGN_ENTITLEMENTS` select
signing inputs. Protect publisher certificates and credentials.

## Verification and Delivery

`scripts/release_artifact.py` compares the artifact with its lock and resource/source
fingerprints, runs isolated executable checks, and creates a checksum inventory
and optional archive. Build metadata records source/dependency identity.

Check the executable directly when appropriate:

```powershell
.\dist\WorkLogger\WorkLogger.exe --smoke-import
.\dist\WorkLogger\WorkLogger.exe --smoke-startup
.\dist\WorkLogger\WorkLogger.exe --smoke-workflows
```

Before distribution, review resources, private-file exclusions, interactive
sign-in, data locations, exports, backup/restore, credential storage, and applicable
tray behavior on the target OS. Sign/notarize and package for the chosen delivery
method. Automated source or offscreen checks do not replace target artifact checks.
