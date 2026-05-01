# WorkLogger Release Build

WorkLogger release packages are built by GitHub Actions from version tags.
The workflow is reusable for any semantic version tag matching the `vX.Y.Z` pattern.

## Automated release flow

1. Merge the release-ready `develop` branch into `main`.
2. Create and push a semantic version tag that matches the release version.
3. The `Build and Release WorkLogger` workflow builds native Windows, macOS, and Linux packages.
4. The workflow uploads build artifacts and creates or updates a draft GitHub Release for that tag.
5. Review the draft release, test the assets, then publish it manually.

```bash
VERSION_TAG="vX.Y.Z"

git checkout develop
git pull origin develop

git checkout main
git pull origin main
git merge develop

git tag "$VERSION_TAG"
git push origin main
git push origin "$VERSION_TAG"
```

## Manual workflow test

The workflow can also be started from GitHub Actions with `workflow_dispatch`.
Enter the same release tag in the `version` input.

## Expected assets

- Windows: `WorkLogger.exe`
- macOS: `WorkLogger.app.zip`
- Linux: `WorkLogger.tar.gz`
- macOS DMG: `WorkLogger.dmg`, if a future build script creates one

## macOS signing note

The current workflow uses ad-hoc signing for bundle integrity only. Unsigned or non-notarized macOS builds can still trigger Gatekeeper warnings. Developer ID signing, notarization, and stapling should be handled as a separate release hardening task.

## Linux compatibility note

The Linux archive contains a PyInstaller onefile executable built on the current GitHub-hosted Ubuntu runner. It should be tested on the target Linux distributions before publishing the draft release.
