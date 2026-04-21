#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="WorkLogger"
SPEC="$SCRIPT_DIR/worklogger.spec"
DIST_X86="$SCRIPT_DIR/dist_x86"
DIST_ARM="$SCRIPT_DIR/dist_arm"
BUILD_X86="$SCRIPT_DIR/build_x86"
BUILD_ARM="$SCRIPT_DIR/build_arm"
OUT_DIST="$SCRIPT_DIR/dist"
OUT_APP="$OUT_DIST/${APP_NAME}.app"
VENV_X86="$SCRIPT_DIR/venv_x86"
VENV_ARM="$SCRIPT_DIR/venv_arm"
I18N_COMPILE_SCRIPT="$SCRIPT_DIR/scripts/i18n/i18n_compile.py"
I18N_LANGS=(en_US ja_JP ko_KR zh_CN zh_TW)
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
LOG_DIR="$SCRIPT_DIR/build_logs"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build_macos_${TIMESTAMP}.log"
TEMP_DIRS=("$DIST_X86" "$DIST_ARM" "$BUILD_X86" "$BUILD_ARM")

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

log() {
  printf '[WorkLogger build] %s\n' "$*"
}

fail() {
  printf '[WorkLogger build][ERROR] %s\n' "$*" >&2
  exit 1
}

assert_path_in_project() {
  local target="$1"
  [ -n "$target" ] || fail "Received empty path for guarded operation."
  case "$target" in
    "$SCRIPT_DIR" | "$SCRIPT_DIR"/*) ;;
    *) fail "Refusing to operate on path outside project root: $target" ;;
  esac
}

safe_remove_path() {
  local target="$1"
  assert_path_in_project "$target"
  rm -rf "$target"
}

on_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '[WorkLogger build][ERROR] Build failed (exit=%s). Detailed log: %s\n' "$rc" "$LOG_FILE" >&2
    printf '[WorkLogger build][ERROR] Temporary directories were preserved for debugging.\n' >&2
  fi
}
trap on_exit EXIT

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail "Missing required command: $cmd"
}

retry() {
  local max_attempts="$1"
  local delay_seconds="$2"
  local desc="$3"
  shift 3
  local attempt=1
  while true; do
    log "RUN  : ${desc} (attempt ${attempt}/${max_attempts})"
    if "$@"; then
      log "OK   : ${desc}"
      return 0
    fi
    local rc=$?
    if [ "$attempt" -ge "$max_attempts" ]; then
      fail "${desc} failed after ${attempt} attempts (exit=${rc})."
    fi
    log "WARN : ${desc} failed (exit=${rc}). Retrying in ${delay_seconds}s."
    sleep "$delay_seconds"
    attempt=$((attempt + 1))
  done
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

verify_prerequisites() {
  [ "$(uname -s)" = "Darwin" ] || fail "WorkLogger_build.sh only supports macOS."
  [ -n "$PYTHON_BIN" ] || fail "python3 was not found. Install Python 3.10+ or set PYTHON_BIN."
  [ -x "$PYTHON_BIN" ] || fail "Python executable is not runnable: $PYTHON_BIN"
  [ -f "$SPEC" ] || fail "Spec file not found: $SPEC"
  [ -f "$I18N_COMPILE_SCRIPT" ] || fail "i18n compile script not found: $I18N_COMPILE_SCRIPT"

  require_cmd arch
  require_cmd lipo
  require_cmd ditto
  require_cmd file
  require_cmd find

  log "Checking Python interpreter architecture support: $PYTHON_BIN"
  run_arch x86_64 "$PYTHON_BIN" -c 'import platform; raise SystemExit(0 if platform.machine()=="x86_64" else 1)' || fail "Python cannot run in x86_64 mode. Install Rosetta-compatible Python."
  run_arch arm64 "$PYTHON_BIN" -c 'import platform; raise SystemExit(0 if platform.machine()=="arm64" else 1)' || fail "Python cannot run in arm64 mode."
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
  log "Executable architectures for $exe_path: $archs"
  if [ "$archs" != "$expected_arch" ]; then
    fail "Expected ${expected_arch} executable, got '${archs}' for ${exe_path}"
  fi
}

bootstrap_build_env() {
  local target_arch="$1"
  local venv_dir="$2"
  local venv_python="$venv_dir/bin/python"
  local requirements_file="$SCRIPT_DIR/requirements.txt"
  local filtered_requirements="$SCRIPT_DIR/.tmp_requirements_build_${target_arch}.txt"

  if [ ! -x "$venv_python" ]; then
    log "RUN  : Create venv (${target_arch}) at $venv_dir"
    run_arch "$target_arch" "$PYTHON_BIN" -m venv "$venv_dir"
    log "OK   : Create venv (${target_arch})"
  else
    log "OK   : Reusing venv (${target_arch}) at $venv_dir"
  fi

  print_python_identity "$target_arch" "$venv_python"

  retry 3 5 "Upgrade pip/setuptools/wheel (${target_arch})" \
    run_arch "$target_arch" "$venv_python" -m pip install --no-compile --upgrade pip setuptools wheel
  retry 3 5 "Install build dependencies (${target_arch})" \
    run_arch "$target_arch" "$venv_python" -m pip install --no-compile --no-cache-dir pyinstaller pillow certifi
  if [ -f "$requirements_file" ]; then
    local excluded_reqs=()
    : > "$filtered_requirements"
    while IFS= read -r line || [ -n "$line" ]; do
      local trimmed="${line#"${line%%[![:space:]]*}"}"
      if [[ "$trimmed" == llama-cpp-python* ]]; then
        excluded_reqs+=("$trimmed")
        continue
      fi
      printf '%s\n' "$line" >> "$filtered_requirements"
    done < "$requirements_file"

    [ -s "$filtered_requirements" ] || fail "No build-safe requirements remain after filtering optional native packages."

    if [ "${#excluded_reqs[@]}" -gt 0 ]; then
      local excluded_joined
      excluded_joined="$(IFS=', '; echo "${excluded_reqs[*]}")"
      log "WARN : Excluding optional native package(s) from build bootstrap (${target_arch}): ${excluded_joined}"
      log "WARN : Local-model runtime can still install llama-cpp-python on demand."
    fi

    retry 3 5 "Install application requirements (${target_arch}, build-safe subset)" \
      run_arch "$target_arch" "$venv_python" -m pip install --no-compile --no-cache-dir -r "$filtered_requirements"
    safe_remove_path "$filtered_requirements"
  fi

  run_arch "$target_arch" "$venv_python" -c 'import importlib.util, sys; req = ["PySide6", "holidays", "httpx", "httpcore", "anyio", "portalocker"]; miss = [m for m in req if importlib.util.find_spec(m) is None]; print("dependency_check=", "ok" if not miss else ",".join(miss)); sys.exit(1 if miss else 0)' \
    || fail "Dependency verification failed for ${target_arch} build venv."
}

build_for_arch() {
  local target_arch="$1"
  local dist_dir="$2"
  local work_dir="$3"
  local venv_dir="$4"
  local venv_python="$venv_dir/bin/python"

  log "RUN  : Prepare directories for ${target_arch} build"
  safe_remove_path "$dist_dir"
  safe_remove_path "$work_dir"
  log "OK   : Prepare directories for ${target_arch} build"

  bootstrap_build_env "$target_arch" "$venv_dir"

  log "RUN  : PyInstaller build (${target_arch})"
  run_arch "$target_arch" "$venv_python" -m PyInstaller "$SPEC" --clean --noconfirm --distpath "$dist_dir" --workpath "$work_dir"
  log "OK   : PyInstaller build (${target_arch})"
}

resolve_built_bundle() {
  local dist_dir="$1"
  local target_arch="$2"
  local app_bundle
  app_bundle="$(find_app_bundle "$dist_dir")"
  [ -n "$app_bundle" ] || fail "No ${APP_NAME}.app found under $dist_dir"
  local main_exe="$app_bundle/Contents/MacOS/${APP_NAME}"
  [ -f "$main_exe" ] || fail "Missing main executable: $main_exe"
  # Keep stdout clean for command substitution callers.
  # `verify_single_arch_executable` emits diagnostic logs via `log()`,
  # so redirect them to stderr to avoid contaminating the returned path.
  verify_single_arch_executable "$main_exe" "$target_arch" >&2
  printf '%s\n' "$app_bundle"
}

merge_universal_bundle() {
  local x86_app="$1"
  local arm_app="$2"

  mkdir -p "$OUT_DIST"
  safe_remove_path "$OUT_APP"
  ditto "$arm_app" "$OUT_APP"

  log "RUN  : Merge Mach-O binaries from x86_64 and arm64 bundles"
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
  log "OK   : Mach-O merge summary: merged=${merged} skipped=${skipped}"
}

cleanup_temporary_dirs() {
  log "RUN  : Cleanup temporary architecture build directories"
  for temp_dir in "${TEMP_DIRS[@]}"; do
    safe_remove_path "$temp_dir"
  done
  log "OK   : Cleanup temporary architecture build directories"
}

validate_final_artifact() {
  local main_exec="$OUT_APP/Contents/MacOS/${APP_NAME}"
  [ -d "$OUT_APP" ] || fail "Final app bundle is missing: $OUT_APP"
  [ -f "$main_exec" ] || fail "Merged executable is missing: $main_exec"

  local archs
  archs="$(lipo -archs "$main_exec" 2>/dev/null || true)"
  [ -n "$archs" ] || fail "Unable to inspect merged executable architecture: $main_exec"
  if [[ "$archs" != *"x86_64"* ]] || [[ "$archs" != *"arm64"* ]]; then
    fail "Merged executable is not universal: '$archs'"
  fi
}

log "============================================================"
log "WorkLogger macOS universal build started"
log "Project root : $SCRIPT_DIR"
log "Spec file    : $SPEC"
log "Log file     : $LOG_FILE"
log "Target app   : $OUT_APP"
log "============================================================"

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONUTF8=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INPUT=1

verify_prerequisites

log "RUN  : Compile gettext catalogs (.po -> .mo)"
"$PYTHON_BIN" "$I18N_COMPILE_SCRIPT"
for lang in "${I18N_LANGS[@]}"; do
  mo_path="$SCRIPT_DIR/worklogger/locales/${lang}/LC_MESSAGES/messages.mo"
  [ -f "$mo_path" ] || fail "Missing compiled catalog: $mo_path"
done
log "OK   : Compile gettext catalogs"

log "Step 1/3: Build x86_64 (Rosetta)"
build_for_arch "x86_64" "$DIST_X86" "$BUILD_X86" "$VENV_X86"
X86_APP="$(resolve_built_bundle "$DIST_X86" "x86_64")"
X86_MAIN="$X86_APP/Contents/MacOS/${APP_NAME}"

log "Step 2/3: Build arm64 (native)"
build_for_arch "arm64" "$DIST_ARM" "$BUILD_ARM" "$VENV_ARM"
ARM_APP="$(resolve_built_bundle "$DIST_ARM" "arm64")"
ARM_MAIN="$ARM_APP/Contents/MacOS/${APP_NAME}"

log "Step 3/3: Merge into universal app"
merge_universal_bundle "$X86_APP" "$ARM_APP"
validate_final_artifact

MAIN_EXEC="$OUT_APP/Contents/MacOS/${APP_NAME}"
log "x86 executable   : $(file "$X86_MAIN")"
log "arm executable   : $(file "$ARM_MAIN")"
log "merged executable: $(file "$MAIN_EXEC")"
log "merged lipo info : $(lipo -info "$MAIN_EXEC")"

cleanup_temporary_dirs

log "SUCCESS: Universal app created at: $OUT_APP"
log "SUCCESS: Detailed log saved to: $LOG_FILE"
log "SUCCESS: Next steps for distribution are codesign and notarization."
