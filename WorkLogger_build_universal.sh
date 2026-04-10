#!/bin/bash
set -euo pipefail

X86_APP="dist_x86/WorkLogger.app"
ARM_APP="dist_arm/WorkLogger.app"
OUT_APP="dist/WorkLogger_universal.app"

if [ ! -d “$X86_APP” ] || [ ! -d “$ARM_APP” ]; then
  echo “dist_x86/WorkLogger.app and dist_arm/WorkLogger.app must exist”
  exit 1
fi

rm -rf “$OUT_APP”
cp -R “$ARM_APP” “$OUT_APP”

echo “Starting to merge Mach-O binaries...”
# Iterate through all files under OUT_APP, check for Mach-O, and merge with the corresponding x86 file
find “$OUT_APP” -type f -print0 | while IFS= read -r -d ‘’ f; do
  if file “$f” | grep -q “Mach-O”; then
    x86f="${f/$OUT_APP/$X86_APP}"
    if [ -f “$x86f” ]; then
      echo “Merging: $f  <-  $x86f”
      lipo -create “$f” “$x86f” -output “$f.tmp”
      mv “$f.tmp” “$f”
    else
      echo “Skip (x86 missing): $f”
    fi
  fi
done

# Verify main executable architecture (example)
MAIN_EXEC="$OUT_APP/Contents/MacOS/WorkLogger"
if [ -f “$MAIN_EXEC” ]; then
  echo “Main executable information:”
  lipo -info “$MAIN_EXEC” || file “$MAIN_EXEC”
else
  echo “Main executable not found: $MAIN_EXEC (please check the name)”
fi

echo “Merge complete: $OUT_APP”
echo “Recommendation: Now codesign $OUT_APP and test it.”