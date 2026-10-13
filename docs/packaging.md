# Packaging

Dependency input fingerprints normalize text line endings. Wheel hashes remain
byte-for-byte checksums for the declared target platform.

## Dependencies

Build on the target operating system and architecture in a clean environment.
`requirements.txt` supplies runtime dependencies, `requirements-build.txt`
supplies the pinned installer and build tools, and `requirements-ai.txt` supplies
the native inference dependencies required in every distribution.

Target locks under `requirements/` contain the exact Python/OS/architecture,
input hashes, package versions, and wheel hashes. The adjacent TXT is the
hash-pinned installation file. Use a lock matching the actual target; do not
reuse Windows wheels or a lock from another Python version.

To build and capture a complete Windows target:

```powershell
python -m venv .venv-release
.venv-release\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
.venv-release\Scripts\python.exe scripts/install_native_dependencies.py
.venv-release\Scripts\python.exe scripts/i18n/i18n_compile.py
.venv-release\Scripts\python.exe scripts/lock_environment.py release/windows-cpython311.lock.json --capture
.venv-release\Scripts\python.exe scripts/release_artifact.py --lock release/windows-cpython311.lock.json --build --archive
```

To capture a different target after reviewing its dependencies:

```sh
python scripts/lock_environment.py requirements/target.lock.json --capture
```

Install native inference with `scripts/install_native_dependencies.py` before
capturing a lock. The installer selects the pinned Metal wheel on macOS and the
pinned CPU wheel on Windows. On Linux it builds the pinned source distribution
against the target system's C library, using a portable CPU configuration.
Linux builds require a C++ compiler and build tools (`build-essential` on Ubuntu).
Lock capture retains compatible prefetched
wheels and records their hashes; publish those wheels with the lock when an
offline or hash-pinned rebuild is required. Legacy locks that omit
`requirements-ai.txt` must be regenerated on the target before distribution.
Review dependency updates and advisories; hashes establish artifact identity,
not security.

CI runs tests, native runtime verification, packaging, and extracted-archive
verification on Windows x64, Linux x64, and macOS ARM64 with Python 3.11 and 3.12.
Artifact names include the Python version to distinguish build environments.

## GitHub Releases

The **Build and Release WorkLogger** workflow is started manually from GitHub
Actions. Once the workflow is present on the repository's default branch,
choose **Run workflow**, select the source branch (normally `main`), and enter
the tag matching `APP_VERSION` in `worklogger/__about__.py`, such as `v4.0.0`.
Enable **validate_only** to run the full verification and prepare release files
without creating a tag or release.

The workflow reuses CI's six Python/platform combinations. It selects the
verified Python 3.12 Windows x64, Linux x64, and macOS ARM64 archives for
distribution. Before creating a tag, it checks the source commit, version,
dependency locks, native backend inclusion, runtime verification results, and
archive checksums. Release files include the archives, verification reports,
platform-specific dependency locks, and `SHA256SUMS`.

Only the publication job has repository write permission. It creates a draft
release with generated release notes; ordinary pushes and pull requests do not
create releases. Review the draft and platform signing requirements before
publishing it. Do not publish or modify assets while the workflow is running.

Runs for the same tag are serialized. A failed upload can be rerun for the same
commit without creating another draft. Artifact names distinguish run attempts;
partial reruns select the latest available platform artifacts from that run and
revalidate their commit identity. If required artifacts have expired, rerun the
complete workflow. A tag pointing elsewhere, an already published release, or
unexpected draft assets cause a failure rather than destructive replacement.

## Build Commands

```sh
python -m pip install -r requirements-build.txt
python scripts/install_native_dependencies.py
python scripts/build.py --check
python scripts/build.py
```

`--check` compiles/checks catalogs and validates resources/dependency availability.
Normal builds invoke `WorkLogger.spec`. Add `--lock <path>` to require an exact
locked environment. The native backend is always included;
`--with-local-inference` remains accepted for command compatibility. Add
`--console` for a diagnostic console.

Build options set `WORKLOGGER_BUILD_CONSOLE`. Close executables under `dist/` before
rebuilding and keep user data out of generated directories.

Native dependencies are selected from `requirements/native-artifacts.json` and
checked against its SHA-256 digests before pip processes them. Linux builds use
the verified source distribution; Windows and macOS use target-compatible wheels.
Update this manifest with publisher-provided checksums when changing the pinned
native dependency version. Generated target locks record the complete resolved
environment; they are build records, not a replacement for approved input hashes.

## Resources and Outputs

`scripts/build_resources.py` explicitly collects fonts, icons, QSS, five compiled
gettext catalogs, the model catalog, and public `worklogger.config.json`.
Private databases, exports, credentials, logs, and model weights do not belong
in a distribution.

PyInstaller also collects required holiday/timezone/certificate/keyring resources
and the native inference libraries. Keep a consistent PySide6/Shiboken/Qt set;
do not replace individual DLLs.

Linux with Python 3.11 uses PySide6 6.11.2 because the 6.12.0 Linux bindings can
corrupt singleton reference counts when emitting signals on Python below 3.12
([upstream report](https://qt-project.atlassian.net/browse/PYSIDE-3477)).
Other supported platform/Python combinations use PySide6 6.12.0.

Use a new virtual environment when upgrading the Qt dependency set. PySide6 6.12
distributes Qt PDF and Qt WebEngine as separate packages, which are included in
the target lock. In-place upgrades from older releases can remove overlapping
module files during package uninstallation. Verify `PySide6.QtPdf` imports before
building.

Windows/Linux builds produce an executable directory under `dist/WorkLogger/`.
The macOS specification creates an ARM64-only `WorkLogger.app` for Apple Silicon.
Build it with an ARM64 Python environment on macOS. Intel and Universal2 builds
are not supported by the current dependency set. CI builds the ARM64 application
and checks its architecture, signature integrity, and executable workflows.
Version resources use application metadata. On macOS,
`WORKLOGGER_CODESIGN_IDENTITY` and `WORKLOGGER_CODESIGN_ENTITLEMENTS` select
signing inputs. Protect publisher certificates and credentials.

## Verification and Delivery

`scripts/release_artifact.py` compares the artifact with its lock and resource/source
fingerprints, runs isolated executable checks, and creates a checksum inventory
and optional archive. Build metadata records source/dependency identity.

Use `--archive` to create a ZIP for Windows/macOS or a tar.gz for Linux. The
legacy `--zip` option is an alias. Archives preserve the platform bundle layout;
verification extracts them and repeats resource, import, startup and workflow
checks before delivery. macOS checks also require the ARM64 architecture, matching
bundle metadata, a valid signature, and Cocoa startup. Internal relative symbolic
links are retained; broken and external links are rejected.

CI runs these checks on Windows, Linux and macOS ARM64. It uploads the verified
archive, checksum inventory and captured target dependency lock. The default
build includes native inference. Both the build and extracted archive must pass
`--smoke-local-model-runtime`, which loads and initializes the real backend
without model weights. A distribution missing the backend cannot pass delivery
verification.

Check the executable directly when appropriate:

```powershell
.\dist\WorkLogger\WorkLogger.exe --smoke-import
.\dist\WorkLogger\WorkLogger.exe --smoke-startup
.\dist\WorkLogger\WorkLogger.exe --smoke-workflows
.\dist\WorkLogger\WorkLogger.exe --smoke-local-model-runtime
```

Before distribution, review resources, private-file exclusions, interactive
sign-in, data locations, exports, backup/restore, credential storage, and applicable
tray behavior on the target OS. Sign/notarize and package for the chosen delivery
method. Automated source or offscreen checks do not replace target artifact checks.
