# Packaging

Dependency-input fingerprints normalize text line endings. Wheel hashes remain
byte-for-byte checksums for the declared target platform.

## Application Downloads

Download the application from [GitHub Releases](https://github.com/bensitu/worklogger/releases/latest)
and follow the matching release notes. WorkLogger 4.0.0 uses the archive layouts
listed below; older versions can have different layouts and features.

### Continuous Integration Builds

To run a specific source revision without installing Python:

1. Open [Continuous Integration for develop](https://github.com/bensitu/worklogger/actions/workflows/ci.yml?query=branch%3Adevelop).
   Choose a successful run and check its source commit. Artifacts represent that
   commit, not later unpushed local changes.
2. Under Artifacts, choose the matching platform and Python 3.14 build when
   available, such as `WorkLogger-Windows-x64-Python-3.14-Attempt-1`. The attempt
   number varies. Downloading artifacts requires GitHub access, and older
   artifacts may have expired. Check the source revision and verification report
   before using a build.
3. Extract the downloaded artifact, then extract the application archive inside
   it. The JSON verification report and dependency locks are build records, not
   application launchers. Review the checksum and verification information below.
4. Launch the application for your platform:

| Target | Application Layout | Launch |
| --- | --- | --- |
| Windows x64 | ZIP containing `WorkLogger/` | `WorkLogger/WorkLogger.exe` |
| Linux x64 | tar.gz containing `WorkLogger/` | `WorkLogger/WorkLogger` on a compatible glibc desktop |
| macOS Apple Silicon | ZIP containing `WorkLogger.app` | Open the `.app` bundle |

Keep the complete Windows/Linux directory, including `_internal`, together.
Windows ARM64, macOS Intel, and Universal2 are not current build targets. Native
inference is included, but model weights must be downloaded or imported separately.
Linux still needs the system Qt libraries described in [development setup](development.md#setup).

Unsigned Windows builds and ad-hoc-signed macOS builds can trigger OS warnings.
Checksums and workflow signatures do not replace platform code signing or
notarization. Use trusted artifacts and follow your organization's installation
policy; do not disable security software to run them.

Back up an existing database before testing. Use a separate OS profile or machine
to keep development data separate from an established installation. Replacing an
executable does not select a fresh database, and database upgrades cannot be
downgraded. See [data locations](configuration.md#files-and-directories) and
[recovery](troubleshooting.md#missing-data-or-database-errors).

## Dependencies

Build on the target operating system and architecture in a clean environment.
`requirements.txt` supplies runtime dependencies, `requirements-build.txt`
supplies the pinned installer and build tools, and `requirements-ai.txt` supplies
the native inference dependencies required in every distribution.
Build requirements include `requirements-installer.txt`, which pins the shared
native-installer tools without adding them to normal runtime dependencies.

Generated target locks contain the exact Python/OS/architecture,
input hashes (including `-r` files), package versions, and wheel hashes. The adjacent
TXT is the hash-pinned installation file. Use a lock matching the actual target; do not
reuse Windows wheels or a lock from another Python version.

Resolved dependency hashes verify the downloaded wheel set, not an independent
publisher identity. Use trusted package indexes and review dependency changes
before capturing a target lock. Installation does not force-reinstall packaging
tools; explicitly supplied native wheels are replaced with hash verification so
switching backend build profiles does not retain an older same-version binary.

To build and capture a complete Windows target:

```powershell
py -3.14 -m venv .venv-release
.venv-release\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
.venv-release\Scripts\python.exe scripts/install_native_dependencies.py
.venv-release\Scripts\python.exe scripts/i18n/i18n_compile.py
.venv-release\Scripts\python.exe scripts/lock_environment.py release/windows-current.lock.json --capture
.venv-release\Scripts\python.exe scripts/prepare_native_model.py
$env:WORKLOGGER_VERIFY_MODEL_PATH = "$PWD/build/native-verification/stories260K.gguf"
.venv-release\Scripts\python.exe scripts/release_artifact.py --lock release/windows-current.lock.json --build --archive
```

To capture a different target after reviewing its dependencies:

```sh
python scripts/lock_environment.py release/target.lock.json --capture
```

Install native inference with `scripts/install_native_dependencies.py` before
capturing a lock. The installer selects the pinned CPU wheel on Windows and the
glibc-compatible CPU wheel on Linux. On macOS ARM64 it compiles the verified
source distribution with Metal enabled; Xcode command-line tools are required.
The native wheels use Python-version-independent `py3-none` tags; OS,
architecture, and minimum platform requirements still apply. Linux x64 wheels
require glibc 2.17 or later. Artifact selection uses the interpreter's supported
tags and never substitutes a musl wheel for a glibc environment.
For an explicit portable Linux source build, pass `--from-source`; this requires
a C++ compiler and build tools (`build-essential` on Ubuntu). Source compilation
is not an automatic fallback when an approved wheel is unavailable. Use separate
wheel directories for different native build profiles.
Lock capture retains compatible prefetched
wheels and records their hashes; publish those wheels with the lock when an
offline or hash-pinned rebuild is required. Legacy locks that omit
`requirements-ai.txt` must be regenerated on the target before distribution.
Review dependency updates and advisories; hashes establish artifact identity,
not security.

CI runs tests, native runtime verification, packaging, and extracted-archive
verification on Windows x64, Linux x64, and macOS ARM64 with Python 3.11 through 3.14.
Dependency vulnerability checks also run for each of these four Python versions
on Linux, including the native inference requirements.
Linux tests exercise the approved wheel; Linux distribution builds compile a
portable CPU backend without AVX, FMA, F16C, SSE4.2, or BMI2 requirements.
Artifact names include the Python version to distinguish build environments.
Failed artifact checks report the exit code, captured process output, and the
application log with credential redaction. Timeouts retain the same diagnostics.

## GitHub Releases

The **Build and Release WorkLogger** workflow is started manually from GitHub
Actions. Its entry point is `.github/workflows/release-build.yml`, matching the
repository's existing release workflow. Choose **Run workflow**, select the
source branch (normally `main`), and enter
the tag matching `APP_VERSION` in `worklogger/__about__.py`, such as `v4.1.0`.
Enable **validate_only** to run the full verification and prepare release files
without creating a tag or release.

The workflow reuses CI's twelve Python/platform combinations. It selects the
verified Python 3.14 Windows x64, Linux x64, and macOS ARM64 archives for
distribution. Python 3.14 jobs check for the latest stable patch available from
`actions/setup-python`, rather than relying only on the runner's cached version.
Exact patch versions are recorded in each target lock and verification report.
Python 3.11 through 3.13 remain compatibility targets and are not substituted for
missing 3.14 release artifacts. Before creating a tag, it checks the source commit, version,
dependency locks, native backend inclusion, runtime verification results, and
archive checksums. Release files include the archives, verification reports,
platform-specific dependency locks, `SHA256SUMS`, a Cosign verification bundle,
and a build-provenance bundle for that checksum manifest.

Only the publication job has `contents: write` permission. It creates a draft
release with generated release notes; ordinary pushes and pull requests do not
create releases. Review the draft and platform signing requirements before
publishing it. Do not publish or modify assets while the workflow is running.

Runs for the same tag are serialized. A failed upload can be rerun for the same
commit without creating another draft. Artifact names distinguish run attempts;
partial reruns select the latest available platform artifacts from that run and
revalidate their commit identity. If required artifacts have expired, rerun the
complete workflow. A tag pointing elsewhere, an already published release, or
unexpected draft assets cause a failure rather than destructive replacement.

## Verify Downloaded Files

Trusted-branch CI runs prepare the same signed distribution files without
creating a tag or release. The signing job receives OIDC and attestation write
permissions; test/build jobs do not. Pull requests do not sign distributions.

The checksum manifest uses Sigstore/Cosign keyless signing with the GitHub
workflow identity. Its bundle contains the signature, certificate, and transparency
log verification material. No persistent signing key is stored in the repository.
See the [Sigstore CI documentation](https://docs.sigstore.dev/quickstart/quickstart-ci/).

Use Cosign 3.1.3 or later for verification. Earlier versions can accept a legacy
bundle without enforcing the requested certificate identity. Distributions use
the standardized Sigstore bundle format; do not convert it to the legacy format.

For files produced by the release workflow on `main`, verify the expected
workflow identity before checking the archives:

```sh
cosign verify-blob SHA256SUMS --bundle SHA256SUMS.sigstore.json \
  --certificate-identity https://github.com/bensitu/worklogger/.github/workflows/release-build.yml@refs/heads/main \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
sha256sum --check SHA256SUMS
```

For ordinary CI artifacts, use `.github/workflows/ci.yml` instead of `release-build.yml`.
Use the branch or tag you explicitly trust; do not take the expected identity
from an untrusted download. For a known source revision, also supply
`--certificate-github-workflow-sha <full-commit-sha>`. GitHub CLI can verify the
separate provenance bundle with `gh attestation verify SHA256SUMS
--bundle SHA256SUMS.provenance.json --repo bensitu/worklogger`.

These signatures authenticate the manifest independently of the release asset
download channel. They do not replace Windows Authenticode, macOS Developer ID,
or notarization, and do not remove operating-system warnings for unsigned apps.
Local builds are not signed with the GitHub workflow identity.

## Dependency Installation

CI resolves runtime/build dependencies into a temporary wheel set before
installation. `scripts/install_dependencies.py` writes exact versions and wheel
SHA-256 hashes, then installs offline with `--require-hashes` and binary-only
packages. Native runtime dependencies follow the same process after the approved
native wheel or source artifact has been verified; existing runtime/build pins
constrain their resolution. Unexpected or duplicate wheel identities are rejected.

The resolved installation lock is in `build/dependencies.lock.txt`; the native
installation lock is in `build/native-dependencies.lock.txt`. The final captured
target lock remains the dependency record distributed with each build. Resolution
still trusts the configured package index, and isolated native source builds
also trust their build-system dependencies; a freshly generated hash is not an
independently reviewed publisher signature.

## Build Commands

```sh
python -m pip install -r requirements-build.txt
python -m pip install -r requirements.txt
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
checked against its SHA-256 digests before pip processes them. Wheels also pass
archive-integrity validation. Windows and Linux use approved wheels by default;
macOS builds its Metal backend from source. `--from-source` selects portable
source compilation on Linux. Native artifact inputs are included in target-lock
validation before release publication.
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
Signature integrity checks accept ad-hoc signing; they do not establish Developer
ID signing or Apple notarization.

CI runs these checks on Windows, Linux and macOS ARM64. It uploads the verified
archive, checksum inventory and captured target dependency lock. The default
build includes native inference. Both the build and extracted archive must pass
`--smoke-local-model-runtime`. CI supplies a small checksum-verified model through
`WORKLOGGER_VERIFY_MODEL_PATH` to check native text generation, CPU cancellation,
and model reloading. The model remains outside the distributed artifacts. Without
that variable, the command checks only backend initialization and availability.
A distribution missing the backend cannot pass delivery verification. See
[native inference checks](testing.md#native-inference-measurements) for local commands.

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
