# Packaging

## Build Inputs

Build on the target operating system with the intended Python architecture.
`WorkLogger.spec` collects the Python package, Qt runtime dependencies, holiday
modules, keyring backends, certificate data, and selected optional packages.
`scripts/build_resources.py` supplies an explicit application-resource manifest.

Direct runtime dependencies are pinned in `requirements.txt`, and the build
dependency is pinned in `requirements-build.txt`. Optional native inference has
its own `requirements-ai.txt`. Transitive dependencies and platform wheels are
not fully locked; record the complete environment for each distributed artifact:

```sh
python -m pip freeze
python -c "import sys, PySide6; from PySide6.QtCore import qVersion; print(sys.version); print(PySide6.__version__); print(qVersion())"
```

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

For a Windows artifact with a diagnostic console:

```powershell
python scripts/build.py --console
$env:WORKLOGGER_LANG = "en_US"
.\dist\WorkLogger\WorkLogger.exe --smoke-import
.\dist\WorkLogger\WorkLogger.exe --smoke-startup
```

The build replaces its generated output directory. Never store the only copy of
user data under `dist/`, and do not rebuild over a running executable. Regular
Windows distribution builds omit the diagnostic console.

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
installing `requirements-ai.txt`. Including it does not connect a generation service
in the default composition.

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
