#!/bin/bash
set -e
echo "WorkLogger – PyInstaller build"
pyinstaller worklogger.spec --clean --noconfirm
echo "Done. Binary: dist/WorkLogger"
