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
OUT_ZIP="$OUT_DIST/${APP_NAME}.app.zip"
CODESIGN_IDENTITY="${CODESIGN_IDENTITY:--}"
VENV_X86="$SCRIPT_DIR/venv_x86"
VENV_ARM="$SCRIPT_DIR/venv_arm"
I18N_COMPILE_SCRIPT="$SCRIPT_DIR/scripts/i18n/i18n_compile.py"
I18N_LANGS=(en_US ja_JP ko_KR zh_CN zh_TW)
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
PYTHON_BIN_X86_64="${PYTHON_BIN_X86_64:-$PYTHON_BIN}"
PYTHON_BIN_ARM64="${PYTHON_BIN_ARM64:-$PYTHON_BIN}"
LOG_DIR="$SCRIPT_DIR/build_logs"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build_macos_${TIMESTAMP}.log"
TEMP_DIRS=("$DIST_X86" "$DIST_ARM" "$BUILD_X86" "$BUILD_ARM")
BUILD_START_EPOCH="$(date +%s)"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

log() {
  local now elapsed
  now="$(date '+%Y-%m-%d %H:%M:%S')"
  elapsed="$(($(date +%s) - BUILD_START_EPOCH))"
  printf '[WorkLogger build][%s][+%ss] %s\n' "$now" "$elapsed" "$*"
}

fail() {
  printf '[WorkLogger build][ERROR] %s\n' "$*" >&2
  exit 1
}

python_bin_for_arch() {
  local target_arch="$1"
  case "$target_arch" in
    x86_64) printf '%s\n' "$PYTHON_BIN_X86_64" ;;
    arm64) printf '%s\n' "$PYTHON_BIN_ARM64" ;;
    *) fail "Unsupported macOS target architecture: $target_arch" ;;
  esac
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
    set +e
    "$@"
    local rc=$?
    set -e
    if [ "$rc" -eq 0 ]; then
      log "OK   : ${desc}"
      return 0
    fi
    if [ "$attempt" -ge "$max_attempts" ]; then
      fail "${desc} failed after ${attempt} attempts (exit=${rc})."
    fi
    log "WARN : ${desc} failed (exit=${rc}). Retrying in ${delay_seconds}s."
    sleep "$delay_seconds"
    attempt=$((attempt + 1))
  done
}

run_for_debug() {
  local desc="$1"
  shift
  log "DEBUG: ${desc}"
  "$@" || log "WARN : Debug command failed: ${desc}"
}

run_with_heartbeat() {
  local desc="$1"
  local interval_seconds="$2"
  shift 2
  local started pid rc elapsed child_pids next_heartbeat

  started="$(date +%s)"
  next_heartbeat="$interval_seconds"
  "$@" &
  pid=$!

  while kill -0 "$pid" 2>/dev/null; do
    sleep 2 || true
    elapsed="$(($(date +%s) - started))"
    if kill -0 "$pid" 2>/dev/null; then
      if [ "$elapsed" -ge "$next_heartbeat" ]; then
        log "DEBUG: ${desc} still running after ${elapsed}s (pid=${pid})"
        ps -o pid,ppid,etime,command -p "$pid" 2>/dev/null || true
        child_pids="$(pgrep -P "$pid" 2>/dev/null | paste -sd, - || true)"
        if [ -n "$child_pids" ]; then
          ps -o pid,ppid,etime,command -p "$child_pids" 2>/dev/null || true
        fi
        next_heartbeat="$((next_heartbeat + interval_seconds))"
      fi
    fi
  done

  set +e
  wait "$pid"
  rc=$?
  set -e
  elapsed="$(($(date +%s) - started))"
  log "DEBUG: ${desc} finished after ${elapsed}s (exit=${rc})"
  return "$rc"
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

print_packaging_debug() {
  local target_arch="$1"
  local python_exe="$2"

  log "DEBUG: Python packaging environment (${target_arch})"
  run_arch "$target_arch" "$python_exe" - <<'PY'
import os
import platform
import sys
import sysconfig

print(f"sys.executable={sys.executable}")
print(f"sys.version={sys.version.split()[0]}")
print(f"platform.machine={platform.machine()}")
print(f"platform.platform={platform.platform()}")
print(f"macosx_deployment_target={sysconfig.get_config_var('MACOSX_DEPLOYMENT_TARGET')}")
print(f"platform_tag={sysconfig.get_platform()}")
print(f"base_prefix={sys.base_prefix}")
print(f"prefix={sys.prefix}")
print(f"CMAKE_BUILD_PARALLEL_LEVEL={os.environ.get('CMAKE_BUILD_PARALLEL_LEVEL', '')}")
try:
    from packaging import tags
    head = []
    for index, tag in enumerate(tags.sys_tags()):
        if index >= 12:
            break
        head.append(str(tag))
    print(f"compatible_tags_head={','.join(head)}")
except Exception as exc:
    print(f"compatible_tags_head_error={exc!r}")
PY
  run_arch "$target_arch" "$python_exe" -m pip --version || true
}

probe_llama_binary_wheel() {
  local target_arch="$1"
  local python_exe="$2"
  local label="$3"
  local llama_requirement="$4"
  shift 4
  local probe_dir="$SCRIPT_DIR/.tmp_llama_probe_${target_arch}_${label}_${TIMESTAMP}"

  safe_remove_path "$probe_dir"
  mkdir -p "$probe_dir"
  log "DEBUG: Probe llama-cpp-python binary wheel (${target_arch}, ${label}): $llama_requirement"
  if run_arch "$target_arch" "$python_exe" -m pip download \
    --no-deps \
    --no-cache-dir \
    --only-binary llama-cpp-python \
    -d "$probe_dir" \
    "$@" \
    "$llama_requirement"; then
    find "$probe_dir" -maxdepth 1 -type f -name "*.whl" -exec basename {} \;
  else
    log "WARN : No compatible llama-cpp-python binary wheel found (${target_arch}, ${label}); pip may build from source."
  fi
  safe_remove_path "$probe_dir"
}

print_llama_install_debug() {
  local target_arch="$1"
  local python_exe="$2"
  local venv_dir="$3"

  log "DEBUG: Installed llama-cpp-python metadata (${target_arch})"
  run_arch "$target_arch" "$python_exe" -m pip show llama-cpp-python || true
  run_arch "$target_arch" "$python_exe" - <<'PY' || true
import importlib.util

spec = importlib.util.find_spec("llama_cpp")
print(f"llama_cpp_importable={spec is not None}")
if spec is not None:
    print(f"llama_cpp_origin={spec.origin}")
PY
  find "$venv_dir" -path "*llama_cpp*" -type f \( -name "*.so" -o -name "*.dylib" \) -print -exec file {} \; 2>/dev/null || true
}

llama_cmake_args_for_arch() {
  local target_arch="$1"
  local base_args="${CMAKE_ARGS:-}"
  local package_args="-DLLAMA_OPENSSL=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_SERVER=OFF -DCMAKE_OSX_ARCHITECTURES=${target_arch}"

  if [ -n "$base_args" ]; then
    printf '%s %s\n' "$base_args" "$package_args"
  else
    printf '%s\n' "$package_args"
  fi
}

install_llama_runtime() {
  local target_arch="$1"
  local python_exe="$2"
  local llama_requirement="$3"
  local llama_cmake_args

  llama_cmake_args="$(llama_cmake_args_for_arch "$target_arch")"
  log "DEBUG: llama-cpp-python CMAKE_ARGS (${target_arch}): ${llama_cmake_args}"
  CMAKE_ARGS="$llama_cmake_args" \
    ARCHFLAGS="-arch ${target_arch}" \
    run_arch "$target_arch" "$python_exe" -m pip install --verbose --no-compile "$llama_requirement"
}

package_version_for_arch() {
  local target_arch="$1"
  local python_exe="$2"
  local package_name="$3"

  run_arch "$target_arch" "$python_exe" - "$package_name" <<'PY'
import sys
from importlib.metadata import PackageNotFoundError, version

try:
    print(version(sys.argv[1]))
except PackageNotFoundError:
    print("")
PY
}

verify_llama_version_match() {
  local x86_version arm_version
  x86_version="$(package_version_for_arch x86_64 "$VENV_X86/bin/python" "llama-cpp-python")"
  arm_version="$(package_version_for_arch arm64 "$VENV_ARM/bin/python" "llama-cpp-python")"

  log "DEBUG: llama-cpp-python version check: x86_64=${x86_version:-missing} arm64=${arm_version:-missing}"
  [ -n "$x86_version" ] || fail "llama-cpp-python is missing from the x86_64 build environment."
  [ -n "$arm_version" ] || fail "llama-cpp-python is missing from the arm64 build environment."
  if [ "$x86_version" != "$arm_version" ]; then
    fail "Refusing to merge universal app with mismatched llama-cpp-python versions: x86_64=${x86_version}, arm64=${arm_version}."
  fi
}

verify_prerequisites() {
  [ "$(uname -s)" = "Darwin" ] || fail "WorkLogger_build_macOS.sh only supports macOS."
  [ -n "$PYTHON_BIN_ARM64" ] || fail "arm64 Python was not found. Install Python 3.10+ or set PYTHON_BIN_ARM64."
  [ -n "$PYTHON_BIN_X86_64" ] || fail "x86_64 Python was not found. Install Python 3.10+ or set PYTHON_BIN_X86_64."
  [ -x "$PYTHON_BIN_ARM64" ] || fail "arm64 Python executable is not runnable: $PYTHON_BIN_ARM64"
  [ -x "$PYTHON_BIN_X86_64" ] || fail "x86_64 Python executable is not runnable: $PYTHON_BIN_X86_64"
  [ -f "$SPEC" ] || fail "Spec file not found: $SPEC"
  [ -f "$I18N_COMPILE_SCRIPT" ] || fail "i18n compile script not found: $I18N_COMPILE_SCRIPT"

  require_cmd arch
  require_cmd lipo
  require_cmd ditto
  require_cmd file
  require_cmd find

  log "Checking Python interpreter architecture support: arm64=$PYTHON_BIN_ARM64 x86_64=$PYTHON_BIN_X86_64"
  run_arch x86_64 "$PYTHON_BIN_X86_64" -c 'import platform, sys; raise SystemExit(0 if sys.version_info >= (3, 10) and platform.machine()=="x86_64" else 1)' || fail "Python cannot run in x86_64 mode with Python 3.10+. Install Rosetta-compatible Python or set PYTHON_BIN_X86_64."
  run_arch arm64 "$PYTHON_BIN_ARM64" -c 'import platform, sys; raise SystemExit(0 if sys.version_info >= (3, 10) and platform.machine()=="arm64" else 1)' || fail "Python cannot run in arm64 mode with Python 3.10+. Install arm64 Python or set PYTHON_BIN_ARM64."
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
  local filtered_requirements_file="$SCRIPT_DIR/.tmp_requirements_macos_${target_arch}_${TIMESTAMP}.txt"
  local llama_requirement_file="$SCRIPT_DIR/.tmp_llama_requirement_macos_${target_arch}_${TIMESTAMP}.txt"
  local llama_requirement="llama-cpp-python>=0.2.90"
  local source_python
  source_python="$(python_bin_for_arch "$target_arch")"

  if [ ! -x "$venv_python" ]; then
    log "RUN  : Create venv (${target_arch}) at $venv_dir"
    run_arch "$target_arch" "$source_python" -m venv "$venv_dir"
    log "OK   : Create venv (${target_arch})"
  else
    log "OK   : Reusing venv (${target_arch}) at $venv_dir"
  fi

  print_python_identity "$target_arch" "$venv_python"

  retry 3 5 "Upgrade pip/setuptools/wheel (${target_arch})" \
    run_arch "$target_arch" "$venv_python" -m pip install --no-compile --upgrade pip setuptools wheel
  print_packaging_debug "$target_arch" "$venv_python"
  retry 3 5 "Install build dependencies (${target_arch})" \
    run_arch "$target_arch" "$venv_python" -m pip install --no-compile --no-cache-dir pyinstaller pillow certifi
  if [ -f "$requirements_file" ]; then
    awk '
      /^[[:space:]]*llama-cpp-python([[:space:]]|[<>=!~]|$)/ {
        print > "/dev/stderr"
        next
      }
      { print }
    ' "$requirements_file" 2>"$llama_requirement_file" >"$filtered_requirements_file"

    if [ -s "$llama_requirement_file" ]; then
      llama_requirement="$(head -n 1 "$llama_requirement_file" | xargs)"
    fi
    safe_remove_path "$llama_requirement_file"

    log "DEBUG: Local-model runtime requirement (${target_arch}): $llama_requirement"
    probe_llama_binary_wheel "$target_arch" "$venv_python" "pypi" "$llama_requirement"
    probe_llama_binary_wheel "$target_arch" "$venv_python" "cpu_index" "$llama_requirement" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu

    retry 3 5 "Install application requirements (${target_arch}, excluding local-model runtime)" \
      run_arch "$target_arch" "$venv_python" -m pip install --no-compile --no-cache-dir -r "$filtered_requirements_file"
    safe_remove_path "$filtered_requirements_file"

    # Install separately so CI logs show whether llama-cpp-python is using a wheel or building from source.
    # Do not use --no-cache-dir here; source builds are expensive and should populate pip's wheel cache.
    log "DEBUG: Installing llama-cpp-python separately (${target_arch}); source builds can take a long time on GitHub macOS runners."
    retry 1 5 "Install local-model runtime (${target_arch})" \
      run_with_heartbeat "Install local-model runtime (${target_arch})" 120 \
      install_llama_runtime "$target_arch" "$venv_python" "$llama_requirement"
    print_llama_install_debug "$target_arch" "$venv_python" "$venv_dir"
  fi

  run_arch "$target_arch" "$venv_python" -c 'import importlib.util, sys; req = ["PySide6", "holidays", "httpx", "httpcore", "anyio", "portalocker", "keyring", "cryptography", "llama_cpp"]; miss = [m for m in req if importlib.util.find_spec(m) is None]; print("dependency_check=", "ok" if not miss else ",".join(miss)); sys.exit(1 if miss else 0)' \
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

cleanup_source_cache_artifacts() {
  log "RUN  : Cleanup Python cache and test artifacts before packaging"
  find "$SCRIPT_DIR" \
    \( -path "$SCRIPT_DIR/.git" -o \
       -path "$VENV_X86" -o \
       -path "$VENV_ARM" -o \
       -path "$SCRIPT_DIR/.venv" -o \
       -path "$SCRIPT_DIR/.venv_build" \) -prune -o \
    -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
  find "$SCRIPT_DIR" \
    \( -path "$SCRIPT_DIR/.git" -o \
       -path "$VENV_X86" -o \
       -path "$VENV_ARM" -o \
       -path "$SCRIPT_DIR/.venv" -o \
       -path "$SCRIPT_DIR/.venv_build" \) -prune -o \
    -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true
  safe_remove_path "$SCRIPT_DIR/tests/_artifacts"
  find "$SCRIPT_DIR/tests" -maxdepth 1 -type f \
    \( -name "_tmp_export.csv" -o -name "_tmp_*.csv" -o -name "_tmp_*.db" \) \
    -delete 2>/dev/null || true
  log "OK   : Cleanup Python cache and test artifacts before packaging"
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

package_release_zip() {
  [ -d "$OUT_APP" ] || fail "Cannot package missing app bundle: $OUT_APP"
  mkdir -p "$OUT_DIST"
  safe_remove_path "$OUT_ZIP"

  log "RUN  : Package macOS release zip (preserve symlinks/permissions)"
  ditto -c -k --sequesterRsrc --keepParent "$OUT_APP" "$OUT_ZIP"
  [ -f "$OUT_ZIP" ] || fail "Release zip was not created: $OUT_ZIP"
  log "OK   : Package macOS release zip"
}

resign_merged_bundle() {
  [ -d "$OUT_APP" ] || fail "Cannot sign missing app bundle: $OUT_APP"

  log "RUN  : Re-sign merged app bundle (identity: $CODESIGN_IDENTITY)"
  if [ "$CODESIGN_IDENTITY" = "-" ]; then
    # Ad-hoc signature keeps bundle integrity after lipo merge.
    codesign --force --deep --sign - "$OUT_APP"
  else
    # Developer ID signature for distribution (requires local cert).
    codesign --force --deep --options runtime --timestamp --sign "$CODESIGN_IDENTITY" "$OUT_APP"
  fi
  log "OK   : Re-sign merged app bundle"
}

verify_codesign_integrity() {
  [ -d "$OUT_APP" ] || fail "Cannot verify missing app bundle: $OUT_APP"

  log "RUN  : Verify code signature integrity"
  codesign --verify --deep --strict --verbose=1 "$OUT_APP" \
    || fail "Code signature verification failed for $OUT_APP"
  log "OK   : Verify code signature integrity"
}

log "============================================================"
log "WorkLogger macOS universal build started"
log "Project root : $SCRIPT_DIR"
log "Spec file    : $SPEC"
log "Log file     : $LOG_FILE"
log "Target app   : $OUT_APP"
log "Python arm64 : $PYTHON_BIN_ARM64"
log "Python x86_64: $PYTHON_BIN_X86_64"
log "============================================================"

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONUTF8=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INPUT=1
export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-$(sysctl -n hw.logicalcpu 2>/dev/null || printf '2')}"

run_for_debug "macOS version" sw_vers
run_for_debug "Kernel and machine" uname -a
run_for_debug "Xcode version" xcodebuild -version
run_for_debug "clang version" clang --version
run_for_debug "CMake version" cmake --version
run_for_debug "Ninja version" ninja --version

verify_prerequisites

cleanup_source_cache_artifacts

log "RUN  : Compile gettext catalogs (.po -> .mo)"
run_arch arm64 "$PYTHON_BIN_ARM64" "$I18N_COMPILE_SCRIPT"
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

verify_llama_version_match

log "Step 3/3: Merge into universal app"
merge_universal_bundle "$X86_APP" "$ARM_APP"
validate_final_artifact
resign_merged_bundle
verify_codesign_integrity

MAIN_EXEC="$OUT_APP/Contents/MacOS/${APP_NAME}"
log "x86 executable   : $(file "$X86_MAIN")"
log "arm executable   : $(file "$ARM_MAIN")"
log "merged executable: $(file "$MAIN_EXEC")"
log "merged lipo info : $(lipo -info "$MAIN_EXEC")"

cleanup_temporary_dirs

package_release_zip

log "SUCCESS: Universal app created at: $OUT_APP"
log "SUCCESS: Release zip created at: $OUT_ZIP"
log "SUCCESS: Detailed log saved to: $LOG_FILE"
log "SUCCESS: Upload the generated .app.zip to GitHub Releases (do not upload the .app directory directly)."
if [ "$CODESIGN_IDENTITY" = "-" ]; then
  log "SUCCESS: Bundle integrity is valid with ad-hoc signing."
  log "SUCCESS: For Gatekeeper-friendly public distribution, re-run with CODESIGN_IDENTITY='Developer ID Application: ...' and notarize."
  log "SUCCESS: Without Developer ID, users can run: xattr -dr com.apple.quarantine /Applications/${APP_NAME}.app"
else
  log "SUCCESS: Developer ID signing applied (identity: $CODESIGN_IDENTITY)."
  log "SUCCESS: Next step for trusted distribution is notarization + stapling."
fi
