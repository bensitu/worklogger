WorkLogger

## Highlights

- Add highlights for this release.

## Changelog

- Link or summarize key items from `CHANGELOG.md`.

## macOS Install Note (No Apple Developer ID)

If macOS shows "Apple cannot verify" after downloading from Releases, run:

```bash
mv ~/Downloads/WorkLogger.app /Applications/WorkLogger.app
xattr -dr com.apple.quarantine /Applications/WorkLogger.app
open /Applications/WorkLogger.app
```

## Linux Install Note

The Linux archive contains a onefile executable:

```bash
tar -xzf WorkLogger.tar.gz
chmod +x WorkLogger
./WorkLogger
```

Test the Linux asset on the target distributions before publishing the release.

## Downloads

- macOS: `WorkLogger.app.zip`
- Windows: `WorkLogger.exe`
- Linux: `WorkLogger.tar.gz`
