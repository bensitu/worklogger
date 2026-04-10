#!/usr/bin/env bash
set -euo pipefail

echo "WorkLogger – universal build (x86_64 + arm64)"

# Config
SPEC=worklogger.spec
APP_NAME=WorkLogger
DIST_X86=dist_x86
DIST_ARM=dist_arm
BUILD_X86=build_x86
BUILD_ARM=build_arm
OUT_DIST=dist
OUT_APP="$OUT_DIST/${APP_NAME}.app"

# Ensure directories exist
mkdir -p "$DIST_X86" "$DIST_ARM" "$OUT_DIST"

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONUTF8=1

echo "Step 1: Build x86_64 (via Rosetta)"
rm -rf "$DIST_X86" "$BUILD_X86" venv_x86
arch -x86_64 /usr/bin/python3 -m venv venv_x86
source venv_x86/bin/activate
pip install --upgrade pip setuptools wheel
# try to prefer binary wheels to avoid compiling
pip install --no-cache-dir --only-binary=:all: pyinstaller pillow || pip install --no-cache-dir pyinstaller pillow
if [ -f requirements.txt ]; then
  pip install --no-cache-dir -r requirements.txt || true
fi
venv_x86/bin/pyinstaller "$SPEC" --clean --noconfirm --distpath "$DIST_X86" --workpath "$BUILD_X86"
deactivate || true

echo "Step 2: Build arm64 (native)"
rm -rf "$DIST_ARM" "$BUILD_ARM" venv_arm
python3 -m venv venv_arm
source venv_arm/bin/activate
pip install --upgrade pip setuptools wheel
pip install --no-cache-dir pyinstaller pillow || pip install --no-cache-dir --only-binary=:all: pyinstaller pillow
if [ -f requirements.txt ]; then
  pip install --no-cache-dir -r requirements.txt || true
fi
venv_arm/bin/pyinstaller "$SPEC" --clean --noconfirm --distpath "$DIST_ARM" --workpath "$BUILD_ARM"
deactivate || true

echo "Step 3: Merge into universal app"
if [ ! -d "$DIST_ARM/${APP_NAME}.app" ]; then
  echo "ERROR: arm app not found at $DIST_ARM/${APP_NAME}.app" >&2
  exit 1
fi
if [ ! -d "$DIST_X86/${APP_NAME}.app" ]; then
  echo "ERROR: x86 app not found at $DIST_X86/${APP_NAME}.app" >&2
  exit 1
fi

rm -rf "$OUT_APP"
cp -R "$DIST_ARM/${APP_NAME}.app" "$OUT_APP"

echo "Merging Mach-O binaries (will skip files with incompatible architectures)..."
find "$OUT_APP" -type f -print0 | while IFS= read -r -d '' f; do
  # process only Mach-O files
  if file "$f" | grep -q "Mach-O"; then
    x86f="${f/$OUT_APP/$DIST_X86/${APP_NAME}.app}"
    if [ -f "$x86f" ]; then
      # attempt to lipo-create; skip on failure
      if lipo -create "$f" "$x86f" -output "$f.tmp" 2>/dev/null; then
        mv "$f.tmp" "$f"
      else
        echo "Skipping (lipo failed or identical archs): $f" >&2
        rm -f "$f.tmp" || true
      fi
    fi
  fi
done

MAIN_EXEC="$OUT_APP/Contents/MacOS/${APP_NAME}"
if [ -f "$MAIN_EXEC" ]; then
  echo "Main executable arch info:"
  lipo -info "$MAIN_EXEC" || file "$MAIN_EXEC"
fi

echo "Universal app created at: $OUT_APP"
echo "Next steps: codesign and notarize before distributing."
