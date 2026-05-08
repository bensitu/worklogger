#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="WorkLogger"
SPEC="$SCRIPT_DIR/worklogger.spec"
DIST_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"
VENV_DIR="$SCRIPT_DIR/.venv_build_linux"
VENV_PYTHON="$VENV_DIR/bin/python"
I18N_COMPILE_SCRIPT="$SCRIPT_DIR/scripts/i18n/i18n_compile.py"
LOG_DIR="$SCRIPT_DIR/build_logs"
WARN_FILE="$LOG_DIR/warn-worklogger.txt"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build_linux_${TIMESTAMP}.log"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
TARGET_BIN="$DIST_DIR/$APP_NAME"

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

python_identity_json() {
  local python_exe="$1"
  "$python_exe" - <<'PY'
import json
import platform
import struct
import sys
import sysconfig

print(json.dumps({
    "executable": sys.executable,
    "version": sys.version.split()[0],
    "major": sys.version_info.major,
    "minor": sys.version_info.minor,
    "abi_tag": f"cp{sys.version_info.major}{sys.version_info.minor}",
    "bits": struct.calcsize("P") * 8,
    "machine": platform.machine(),
    "platform": sysconfig.get_platform(),
}))
PY
}

json_field() {
  local json_value="$1"
  local field_name="$2"
  JSON_VALUE="$json_value" "$PYTHON_BIN" -c 'import json, os, sys; print(json.loads(os.environ["JSON_VALUE"])[sys.argv[1]])' "$field_name"
}

format_python_identity() {
  local json_value="$1"
  JSON_VALUE="$json_value" "$PYTHON_BIN" - <<'PY'
import json
import os

data = json.loads(os.environ["JSON_VALUE"])
print(
    f"version={data['version']} platform={data['platform']} "
    f"bits={data['bits']} exe={data['executable']}"
)
PY
}

venv_matches_host_python() {
  local host_json="$1"
  local venv_json

  if ! venv_json="$(python_identity_json "$VENV_PYTHON" 2>&1)"; then
    log "WARN : Existing build virtual environment cannot be inspected. Recreating it. Output: $venv_json"
    return 1
  fi
  if HOST_JSON="$host_json" VENV_JSON="$venv_json" "$PYTHON_BIN" - <<'PY'
import json
import os
import sys

host = json.loads(os.environ["HOST_JSON"])
venv = json.loads(os.environ["VENV_JSON"])
keys = ("major", "minor", "bits", "platform")
raise SystemExit(0 if all(host[key] == venv[key] for key in keys) else 1)
PY
  then
    log "OK   : Existing build virtual environment matches host Python ($(format_python_identity "$host_json"))."
    return 0
  fi

  log "WARN : Existing build virtual environment Python does not match host Python. Recreating it."
  log "WARN : Host Python: $(format_python_identity "$host_json")"
  log "WARN : Venv Python: $(format_python_identity "$venv_json")"
  return 1
}

venv_abi_compatible() {
  local expected_abi="$1"
  local output

  if output="$(EXPECTED_ABI="$expected_abi" VENV_DIR="$VENV_DIR" "$PYTHON_BIN" - <<'PY'
from pathlib import Path
import os
import re
import sys

expected = os.environ["EXPECTED_ABI"]
root = Path(os.environ["VENV_DIR"])
wrong = []
for path in root.rglob("*"):
    if path.suffix.lower() not in {".so", ".pyd"}:
        continue
    name = path.name
    tags = []
    match = re.search(r"\.cp(\d{2,3})", name)
    if match:
        tags.append("cp" + match.group(1))
    match = re.search(r"\.cpython-(\d{2,3})", name)
    if match:
        tags.append("cp" + match.group(1))
    if tags and expected not in tags:
        wrong.append(str(path))
        if len(wrong) >= 8:
            break
if wrong:
    print("\n".join(wrong))
    raise SystemExit(1)
PY
  )"; then
    return 0
  fi

  log "WARN : Existing build virtual environment contains extension modules for a different Python ABI. Expected $expected_abi."
  while IFS= read -r line; do
    [ -n "$line" ] && log "WARN : Incompatible extension module: $line"
  done <<<"$output"
  return 1
}

ensure_build_venv() {
  local host_json expected_abi needs_rebuild=0

  if ! host_json="$(python_identity_json "$PYTHON_BIN" 2>&1)"; then
    fail "Unable to inspect host Python. Output: $host_json"
  fi
  expected_abi="$(json_field "$host_json" abi_tag)"
  log "OK   : Host Python: $(format_python_identity "$host_json")"

  if [ ! -x "$VENV_PYTHON" ]; then
    needs_rebuild=1
  elif ! venv_matches_host_python "$host_json"; then
    needs_rebuild=1
  elif ! venv_abi_compatible "$expected_abi"; then
    needs_rebuild=1
  fi

  if [ "$needs_rebuild" -eq 1 ]; then
    if [ -e "$VENV_DIR" ]; then
      log "RUN  : Remove broken/incompatible virtual environment at $VENV_DIR"
      safe_remove_path "$VENV_DIR"
      log "OK   : Remove broken/incompatible virtual environment"
    fi
    log "RUN  : Create build virtual environment at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    log "OK   : Create build virtual environment"
  else
    log "OK   : Reusing build virtual environment at $VENV_DIR"
  fi
}

llama_cmake_args() {
  local base_args="${CMAKE_ARGS:-}"
  local package_args="-DLLAMA_OPENSSL=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_SERVER=OFF -DGGML_CCACHE=OFF"

  if [ -n "$base_args" ]; then
    printf '%s %s\n' "$base_args" "$package_args"
  else
    printf '%s\n' "$package_args"
  fi
}

install_llama_runtime() {
  local llama_requirement="$1"
  local build_args
  build_args="$(llama_cmake_args)"

  log "DEBUG: llama-cpp-python CMAKE_ARGS: ${build_args}"
  CMAKE_ARGS="$build_args" \
    "$VENV_PYTHON" -m pip install \
      --timeout 60 \
      --retries 2 \
      --verbose \
      --no-compile \
      --no-binary llama-cpp-python \
      "$llama_requirement"
}

print_llama_install_debug() {
  log "DEBUG: Installed llama-cpp-python metadata"
  "$VENV_PYTHON" -m pip show llama-cpp-python || true
  "$VENV_PYTHON" - <<'PY' || true
import importlib.util

spec = importlib.util.find_spec("llama_cpp")
print(f"llama_cpp_importable={spec is not None}")
if spec is not None:
    print(f"llama_cpp_origin={spec.origin}")
PY
  find "$VENV_DIR" -path "*llama_cpp*" -type f -name "*.so" -print -exec file {} \; -exec ldd {} \; 2>/dev/null || true
}

verify_prerequisites() {
  [ "$(uname -s)" = "Linux" ] || fail "WorkLogger_build_linux.sh only supports Linux."
  [ -n "$PYTHON_BIN" ] || fail "python3 was not found. Install Python 3.10+ or set PYTHON_BIN."
  [ -x "$PYTHON_BIN" ] || fail "Python executable is not runnable: $PYTHON_BIN"
  [ -f "$SPEC" ] || fail "Spec file not found: $SPEC"
  [ -f "$I18N_COMPILE_SCRIPT" ] || fail "i18n compile script not found: $I18N_COMPILE_SCRIPT"
}

cleanup_source_cache_artifacts() {
  log "RUN  : Cleanup Python cache and test artifacts before packaging"
  find "$SCRIPT_DIR" \
    \( -path "$SCRIPT_DIR/.git" -o \
       -path "$SCRIPT_DIR/.venv" -o \
       -path "$SCRIPT_DIR/.venv_build" -o \
       -path "$VENV_DIR" \) -prune -o \
    -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
  find "$SCRIPT_DIR" \
    \( -path "$SCRIPT_DIR/.git" -o \
       -path "$SCRIPT_DIR/.venv" -o \
       -path "$SCRIPT_DIR/.venv_build" -o \
       -path "$VENV_DIR" \) -prune -o \
    -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true
  safe_remove_path "$SCRIPT_DIR/tests/_artifacts"
  find "$SCRIPT_DIR/tests" -maxdepth 1 -type f \
    \( -name "_tmp_export.csv" -o -name "_tmp_*.csv" -o -name "_tmp_*.db" \) \
    -delete 2>/dev/null || true
  log "OK   : Cleanup Python cache and test artifacts before packaging"
}

install_dependencies() {
  local requirements_file="$SCRIPT_DIR/requirements.txt"
  local filtered_requirements_file="$SCRIPT_DIR/.tmp_requirements_linux_${TIMESTAMP}.txt"
  local llama_requirement="llama-cpp-python>=0.3.19"

  ensure_build_venv

  retry 3 5 "Upgrade pip/setuptools/wheel" \
    "$VENV_PYTHON" -m pip install --timeout 60 --retries 2 --upgrade pip setuptools wheel

  retry 3 5 "Install packaging dependencies" \
    "$VENV_PYTHON" -m pip install --no-cache-dir --timeout 60 --retries 2 pyinstaller certifi

  if [ -f "$requirements_file" ]; then
    awk '
      /^[[:space:]]*llama-cpp-python([[:space:]]|[<>=!~]|$)/ {
        print > "/dev/stderr"
        next
      }
      { print }
    ' "$requirements_file" 2>"$SCRIPT_DIR/.tmp_llama_requirement_${TIMESTAMP}.txt" >"$filtered_requirements_file"

    if [ -s "$SCRIPT_DIR/.tmp_llama_requirement_${TIMESTAMP}.txt" ]; then
      llama_requirement="$(head -n 1 "$SCRIPT_DIR/.tmp_llama_requirement_${TIMESTAMP}.txt" | xargs)"
    fi
    safe_remove_path "$SCRIPT_DIR/.tmp_llama_requirement_${TIMESTAMP}.txt"

    retry 3 5 "Install application dependencies (excluding local-model runtime)" \
      "$VENV_PYTHON" -m pip install --no-cache-dir --timeout 60 --retries 2 -r "$filtered_requirements_file"
    safe_remove_path "$filtered_requirements_file"

    retry 1 5 "Install llama-cpp-python from source for Linux glibc" \
      install_llama_runtime "$llama_requirement"
    print_llama_install_debug
  else
    log "WARN : requirements.txt not found. Skipping application dependency installation."
  fi

  "$VENV_PYTHON" - <<'PY'
import importlib
import sys

required = [
    "PySide6",
    "holidays",
    "keyring",
    "cryptography",
    "cryptography.hazmat.backends.openssl.backend",
    "httpx",
    "httpcore",
    "anyio",
    "portalocker",
    "_cffi_backend",
    "numpy",
    "llama_cpp",
]
failures = []
for module_name in required:
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        failures.append(f"{module_name}: {type(exc).__name__}: {exc}")
if failures:
    print("dependency_import_check=failed")
    print("\n".join(failures))
    raise SystemExit(1)
print("dependency_import_check=ok")
PY
}

verify_internal_imports() {
  log "RUN  : Verify required internal imports"
  "$VENV_PYTHON" - "$SCRIPT_DIR" <<'PY'
import importlib
import sys
from pathlib import Path

project = Path(sys.argv[1])
sys.path.insert(0, str(project / "worklogger"))
required = [
    "services.app_services",
    "services.report_service",
    "services.export_service",
    "services.calendar_service",
]
failures = []
for module_name in required:
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        failures.append(f"{module_name}: {type(exc).__name__}: {exc}")
if failures:
    print("internal_import_check=failed")
    print("\n".join(failures))
    raise SystemExit(1)
print("internal_import_check=ok")
PY
  log "OK   : Verify required internal imports"
}

inspect_warning_file() {
  if [ -f "$WARN_FILE" ]; then
    if grep -Eq "services\.report_service|No module named 'services\.report_service'" "$WARN_FILE"; then
      fail "PyInstaller warning log contains a required internal service import failure: $WARN_FILE"
    fi
    log "OK   : PyInstaller warning file checked: $WARN_FILE"
  else
    log "OK   : PyInstaller warning log has no actionable warnings."
  fi
}

log "============================================================"
log "WorkLogger Linux onefile build started"
log "Project root : $SCRIPT_DIR"
log "Spec file    : $SPEC"
log "Target file  : $TARGET_BIN"
log "Log file     : $LOG_FILE"
log "============================================================"

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export PYTHONUTF8=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INPUT=1
export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-$(nproc 2>/dev/null || printf '2')}"

verify_prerequisites
cleanup_source_cache_artifacts
install_dependencies
verify_internal_imports

log "RUN  : Compile gettext catalogs (.po -> .mo)"
"$VENV_PYTHON" "$I18N_COMPILE_SCRIPT"
log "OK   : Compile gettext catalogs"

log "RUN  : Cleanup previous Linux build artifacts"
mkdir -p "$DIST_DIR"
safe_remove_path "$BUILD_DIR"
safe_remove_path "$TARGET_BIN"
log "OK   : Cleanup previous Linux build artifacts"

log "RUN  : PyInstaller build"
"$VENV_PYTHON" -m PyInstaller "$SPEC" --clean --noconfirm --distpath "$DIST_DIR" --workpath "$BUILD_DIR"
log "OK   : PyInstaller build"
inspect_warning_file

[ -f "$TARGET_BIN" ] || fail "Expected artifact missing: $TARGET_BIN"
[ -s "$TARGET_BIN" ] || fail "Artifact size is zero bytes: $TARGET_BIN"
chmod +x "$TARGET_BIN"

log "RUN  : Smoke-test packaged executable imports"
"$TARGET_BIN" --smoke-import
log "OK   : Smoke-test packaged executable imports"

if command -v file >/dev/null 2>&1; then
  file "$TARGET_BIN"
fi
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$TARGET_BIN"
fi

safe_remove_path "$BUILD_DIR"

log "SUCCESS: Linux onefile build completed."
log "SUCCESS: Artifact verified at $TARGET_BIN."
log "SUCCESS: Detailed log saved to $LOG_FILE."
