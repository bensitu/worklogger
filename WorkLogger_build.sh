#!/usr/bin/env bash
set -euo pipefail

SPEC=worklogger.spec
APP_NAME=WorkLogger
DIST_X86=dist_x86
DIST_ARM=dist_arm
BUILD_X86=build_x86
BUILD_ARM=build_arm
OUT_DIST=dist
OUT_APP="$OUT_DIST/${APP_NAME}.app"
VENV_X86=venv_x86
VENV_ARM=venv_arm
I18N_COMPILE_SCRIPT="scripts/i18n_compile.py"
I18N_LANGS=(en_US ja_JP ko_KR zh_CN zh_TW)
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"

log() {
  printf '[WorkLogger build] %s\n' "$*"
}

fail() {
  printf '[WorkLogger build][ERROR] %s\n' "$*" >&2
  exit 1
}

run_arch() {
  local target_arch="$1"
  shift
  arch "-${target_arch}" "$@"
}

print_python_identity() {
  local target_arch="$1"
  local python_exe="$2"
  run_arch "$target_arch" "$python_exe" -c 'import platform, sys; print(f"python={sys.executable}"); print(f"machine={platform.machine()}"); print(f"version={sys.version.split()[0]}")'
}

verify_python_support() {
  log "Checking Python interpreter architecture support: $PYTHON_BIN"
  [ -x "$PYTHON_BIN" ] || fail "Python executable is not runnable: $PYTHON_BIN"
  run_arch x86_64 "$PYTHON_BIN" -c 'import platform; raise SystemExit(0 if platform.machine()=="x86_64" else 1)' || fail "Python cannot run in x86_64 mode: $PYTHON_BIN"
  run_arch arm64 "$PYTHON_BIN" -c 'import platform; raise SystemExit(0 if platform.machine()=="arm64" else 1)' || fail "Python cannot run in arm64 mode: $PYTHON_BIN"
}

find_app_bundle() {
  local dist_dir="$1"
  find "$dist_dir" -maxdepth 4 -type d -name "${APP_NAME}.app" | head -n 1
}

verify_single_arch_executable() {
  local exe_path="$1"
  local expected_arch="$2"
  local archs
  archs="$(lipo -archs "$exe_path" 2>/dev/null || true)"
  [ -n "$archs" ] || fail "Cannot read Mach-O architectures: $exe_path"
  printf '[WorkLogger build] Executable architectures for %s: %s\n' "$exe_path" "$archs" >&2
  if [ "$archs" != "$expected_arch" ]; then
    fail "Expected $expected_arch executable, got '$archs' for $exe_path"
  fi
}

bootstrap_build_env() {
  local target_arch="$1"
  local venv_dir="$2"
  log "Bootstrapping venv (${target_arch}) at $venv_dir"
  run_arch "$target_arch" "$PYTHON_BIN" -m venv "$venv_dir"
  print_python_identity "$target_arch" "$venv_dir/bin/python"
  run_arch "$target_arch" "$venv_dir/bin/python" -m pip install --no-compile --upgrade pip setuptools wheel
  run_arch "$target_arch" "$venv_dir/bin/python" -m pip install --no-compile --no-cache-dir pyinstaller pillow certifi
  if [ -f requirements.txt ]; then
    run_arch "$target_arch" "$venv_dir/bin/python" -m pip install --no-compile --no-cache-dir -r requirements.txt
  fi
  run_arch "$target_arch" "$venv_dir/bin/python" -c 'import importlib.util, sys; req = ["PySide6", "holidays", "httpx", "httpcore", "anyio", "portalocker"]; miss = [m for m in req if importlib.util.find_spec(m) is None]; print("dependency_check=", "ok" if not miss else ",".join(miss)); sys.exit(1 if miss else 0)'
}

build_for_arch() {
  local target_arch="$1"
  local dist_dir="$2"
  local work_dir="$3"
  local venv_dir="$4"
  log "Starting ${target_arch} build"
  rm -rf "$dist_dir" "$work_dir" "$venv_dir"
  bootstrap_build_env "$target_arch" "$venv_dir"
  run_arch "$target_arch" "$venv_dir/bin/python" -m PyInstaller "$SPEC" --clean --noconfirm --distpath "$dist_dir" --workpath "$work_dir"
}

resolve_built_bundle() {
  local dist_dir="$1"
  local target_arch="$2"
  local app_bundle
  app_bundle="$(find_app_bundle "$dist_dir")"
  [ -n "$app_bundle" ] || fail "No ${APP_NAME}.app found under $dist_dir"
  local main_exe="$app_bundle/Contents/MacOS/${APP_NAME}"
  [ -f "$main_exe" ] || fail "Missing main executable: $main_exe"
  verify_single_arch_executable "$main_exe" "$target_arch"
  printf '%s\n' "$app_bundle"
}

merge_universal_bundle() {
  local x86_app="$1"
  local arm_app="$2"
  mkdir -p "$OUT_DIST"
  rm -rf "$OUT_APP"
  ditto "$arm_app" "$OUT_APP"

  log "Merging Mach-O binaries from x86_64 and arm64 bundles"
  local merged=0
  local skipped=0
  local f rel x86f
  while IFS= read -r -d '' f; do
    if ! file "$f" | grep -q "Mach-O"; then
      continue
    fi
    rel="${f#"$OUT_APP"/}"
    x86f="$x86_app/$rel"
    if [ ! -f "$x86f" ]; then
      continue
    fi
    if lipo -create "$f" "$x86f" -output "$f.tmp" 2>/dev/null; then
      mv "$f.tmp" "$f"
      merged=$((merged + 1))
    else
      rm -f "$f.tmp" || true
      skipped=$((skipped + 1))
    fi
  done < <(find "$OUT_APP" -type f -print0)
  log "Mach-O merge summary: merged=$merged skipped=$skipped"
}

log "WorkLogger universal build (x86_64 + arm64)"

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONUTF8=1

verify_python_support

log "Step 0: Compile gettext catalogs (.po -> .mo)"
"$PYTHON_BIN" "$I18N_COMPILE_SCRIPT"
for lang in "${I18N_LANGS[@]}"; do
  mo_path="worklogger/locales/${lang}/LC_MESSAGES/messages.mo"
  [ -f "$mo_path" ] || fail "Missing compiled catalog: $mo_path"
done

log "Step 1: Build x86_64 (Rosetta)"
build_for_arch "x86_64" "$DIST_X86" "$BUILD_X86" "$VENV_X86"
X86_APP="$(resolve_built_bundle "$DIST_X86" "x86_64")"
X86_MAIN="$X86_APP/Contents/MacOS/${APP_NAME}"

log "Step 2: Build arm64 (native)"
build_for_arch "arm64" "$DIST_ARM" "$BUILD_ARM" "$VENV_ARM"
ARM_APP="$(resolve_built_bundle "$DIST_ARM" "arm64")"
ARM_MAIN="$ARM_APP/Contents/MacOS/${APP_NAME}"

log "Step 3: Merge into universal app"
merge_universal_bundle "$X86_APP" "$ARM_APP"

MAIN_EXEC="$OUT_APP/Contents/MacOS/${APP_NAME}"
[ -f "$MAIN_EXEC" ] || fail "Missing merged executable: $MAIN_EXEC"

MAIN_ARCHS="$(lipo -archs "$MAIN_EXEC" 2>/dev/null || true)"
log "x86 executable: $(file "$X86_MAIN")"
log "arm executable: $(file "$ARM_MAIN")"
log "merged executable: $(file "$MAIN_EXEC")"
log "merged lipo info: $(lipo -info "$MAIN_EXEC")"

if [[ "$MAIN_ARCHS" != *"x86_64"* ]] || [[ "$MAIN_ARCHS" != *"arm64"* ]]; then
  fail "Merged executable is not universal: '$MAIN_ARCHS'"
fi

log "Universal app created at: $OUT_APP"
log "Next steps: codesign and notarize before distributing."
