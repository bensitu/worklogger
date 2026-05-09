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
LLAMA_CPP_ARM64_WHEEL_INDEX_URL="${LLAMA_CPP_ARM64_WHEEL_INDEX_URL:-https://abetlen.github.io/llama-cpp-python/whl/metal}"
LLAMA_CPP_X86_64_WHEEL_INDEX_URL="${LLAMA_CPP_X86_64_WHEEL_INDEX_URL:-https://abetlen.github.io/llama-cpp-python/whl/cpu}"
LLAMA_CPP_REQUIREMENT="${LLAMA_CPP_REQUIREMENT:-}"
LLAMA_CPP_REQUIREMENT_ARM64="${LLAMA_CPP_REQUIREMENT_ARM64:-${LLAMA_CPP_REQUIREMENT:-llama-cpp-python>=0.3.19}}"
LLAMA_CPP_REQUIREMENT_X86_64="${LLAMA_CPP_REQUIREMENT_X86_64:-${LLAMA_CPP_REQUIREMENT:-llama-cpp-python==0.3.2}}"
LLAMA_CPP_FORCE_REINSTALL="${LLAMA_CPP_FORCE_REINSTALL:-1}"
LLAMA_CPP_ONLY_BINARY="${LLAMA_CPP_ONLY_BINARY:-1}"
LLAMA_CPP_NO_CACHE="${LLAMA_CPP_NO_CACHE:-1}"
LLAMA_CPP_ALLOW_SOURCE_BUILD="${LLAMA_CPP_ALLOW_SOURCE_BUILD:-0}"
LLAMA_CPP_ALLOW_VERSION_MISMATCH="${LLAMA_CPP_ALLOW_VERSION_MISMATCH:-1}"
LLAMA_CPP_ALLOW_ARCH_SPECIFIC_LLAMA_LIBS="${LLAMA_CPP_ALLOW_ARCH_SPECIFIC_LLAMA_LIBS:-1}"
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

is_enabled() {
  case "${1:-}" in
    1 | true | TRUE | yes | YES | on | ON) return 0 ;;
    *) return 1 ;;
  esac
}

llama_wheel_index_for_arch() {
  case "$1" in
    arm64) printf '%s\n' "$LLAMA_CPP_ARM64_WHEEL_INDEX_URL" ;;
    x86_64) printf '%s\n' "$LLAMA_CPP_X86_64_WHEEL_INDEX_URL" ;;
    *) fail "Unsupported architecture for llama wheel index: $1" ;;
  esac
}

llama_requirement_for_arch() {
  case "$1" in
    arm64) printf '%s\n' "$LLAMA_CPP_REQUIREMENT_ARM64" ;;
    x86_64) printf '%s\n' "$LLAMA_CPP_REQUIREMENT_X86_64" ;;
    *) fail "Unsupported architecture for llama requirement: $1" ;;
  esac
}

is_llama_native_relpath() {
  case "$1" in
    *llama_cpp/lib/*.dylib | *llama_cpp/lib/*.so) return 0 ;;
    *) return 1 ;;
  esac
}

allow_arch_specific_macho_relpath() {
  is_enabled "$LLAMA_CPP_ALLOW_ARCH_SPECIFIC_LLAMA_LIBS" && is_llama_native_relpath "$1"
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
  "$@" || log "DEBUG: Optional debug command unavailable: ${desc}"
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

python_identity_json_for_arch() {
  local target_arch="$1"
  local python_exe="$2"

  run_arch "$target_arch" "$python_exe" - <<'PY'
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

json_field_for_arch() {
  local target_arch="$1"
  local python_exe="$2"
  local json_value="$3"
  local field_name="$4"

  JSON_VALUE="$json_value" run_arch "$target_arch" "$python_exe" -c 'import json, os, sys; print(json.loads(os.environ["JSON_VALUE"])[sys.argv[1]])' "$field_name"
}

format_python_identity_for_arch() {
  local target_arch="$1"
  local python_exe="$2"
  local json_value="$3"

  JSON_VALUE="$json_value" run_arch "$target_arch" "$python_exe" - <<'PY'
import json
import os

data = json.loads(os.environ["JSON_VALUE"])
print(
    f"version={data['version']} platform={data['platform']} "
    f"bits={data['bits']} machine={data['machine']} exe={data['executable']}"
)
PY
}

venv_matches_host_python_for_arch() {
  local target_arch="$1"
  local source_python="$2"
  local venv_python="$3"
  local host_json="$4"
  local venv_json

  if ! venv_json="$(python_identity_json_for_arch "$target_arch" "$venv_python" 2>&1)"; then
    log "WARN : Existing venv cannot be inspected (${target_arch}). Recreating it. Output: $venv_json"
    return 1
  fi
  if HOST_JSON="$host_json" VENV_JSON="$venv_json" run_arch "$target_arch" "$source_python" - <<'PY'
import json
import os
import sys

host = json.loads(os.environ["HOST_JSON"])
venv = json.loads(os.environ["VENV_JSON"])
keys = ("major", "minor", "bits", "machine", "platform")
raise SystemExit(0 if all(host[key] == venv[key] for key in keys) else 1)
PY
  then
    log "OK   : Existing venv matches host Python (${target_arch}): $(format_python_identity_for_arch "$target_arch" "$source_python" "$host_json")"
    return 0
  fi

  log "WARN : Existing venv Python does not match host Python (${target_arch}). Recreating it."
  log "WARN : Host Python (${target_arch}): $(format_python_identity_for_arch "$target_arch" "$source_python" "$host_json")"
  log "WARN : Venv Python (${target_arch}): $(format_python_identity_for_arch "$target_arch" "$source_python" "$venv_json")"
  return 1
}

venv_abi_compatible_for_arch() {
  local target_arch="$1"
  local source_python="$2"
  local venv_dir="$3"
  local expected_abi="$4"
  local output

  if output="$(EXPECTED_ABI="$expected_abi" VENV_DIR="$venv_dir" run_arch "$target_arch" "$source_python" - <<'PY'
from pathlib import Path
import os
import re

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

  log "WARN : Existing venv contains extension modules for a different Python ABI (${target_arch}). Expected $expected_abi."
  while IFS= read -r line; do
    [ -n "$line" ] && log "WARN : Incompatible extension module (${target_arch}): $line"
  done <<<"$output"
  return 1
}

ensure_build_venv_for_arch() {
  local target_arch="$1"
  local source_python="$2"
  local venv_dir="$3"
  local venv_python="$4"
  local host_json expected_abi needs_rebuild=0

  if ! host_json="$(python_identity_json_for_arch "$target_arch" "$source_python" 2>&1)"; then
    fail "Unable to inspect host Python (${target_arch}). Output: $host_json"
  fi
  expected_abi="$(json_field_for_arch "$target_arch" "$source_python" "$host_json" abi_tag)"
  log "OK   : Host Python (${target_arch}): $(format_python_identity_for_arch "$target_arch" "$source_python" "$host_json")"

  if [ ! -x "$venv_python" ]; then
    needs_rebuild=1
  elif ! venv_matches_host_python_for_arch "$target_arch" "$source_python" "$venv_python" "$host_json"; then
    needs_rebuild=1
  elif ! venv_abi_compatible_for_arch "$target_arch" "$source_python" "$venv_dir" "$expected_abi"; then
    needs_rebuild=1
  fi

  if [ "$needs_rebuild" -eq 1 ]; then
    if [ -e "$venv_dir" ]; then
      log "RUN  : Remove broken/incompatible venv (${target_arch}) at $venv_dir"
      safe_remove_path "$venv_dir"
      log "OK   : Remove broken/incompatible venv (${target_arch})"
    fi
    log "RUN  : Create venv (${target_arch}) at $venv_dir"
    run_arch "$target_arch" "$source_python" -m venv "$venv_dir"
    log "OK   : Create venv (${target_arch})"
  else
    log "OK   : Reusing venv (${target_arch}) at $venv_dir"
  fi
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
  local probe_log

  safe_remove_path "$probe_dir"
  mkdir -p "$probe_dir"
  probe_log="$probe_dir/pip_download.log"
  log "DEBUG: Probe llama-cpp-python binary wheel (${target_arch}, ${label}): $llama_requirement"
  if run_arch "$target_arch" "$python_exe" -m pip download \
    --no-deps \
    --no-cache-dir \
    --only-binary llama-cpp-python \
    -d "$probe_dir" \
    "$@" \
    "$llama_requirement" >"$probe_log" 2>&1; then
    find "$probe_dir" -maxdepth 1 -type f -name "*.whl" -exec basename {} \;
  else
    log "DEBUG: No compatible llama-cpp-python binary wheel found (${target_arch}, ${label})."
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
from pathlib import Path

spec = importlib.util.find_spec("llama_cpp")
print(f"llama_cpp_importable={spec is not None}")
if spec is not None:
    print(f"llama_cpp_origin={spec.origin}")
    package_dir = Path(spec.origin).resolve().parent
    native_files = sorted(
        p for pattern in ("*.so", "*.dylib")
        for p in package_dir.rglob(pattern)
    )
    for path in native_files:
        print(f"llama_cpp_native={path}")
PY
  find "$venv_dir" -path "*llama_cpp*" -type f \( -name "*.so" -o -name "*.dylib" \) -print -exec file {} \; 2>/dev/null || true
}

probe_llama_runtime_for_arch() {
  local target_arch="$1"
  local python_exe="$2"

  log "RUN  : Probe llama-cpp-python runtime (${target_arch})"
  run_arch "$target_arch" "$python_exe" - <<'PY'
from pathlib import Path
import importlib
import importlib.util
import platform

import llama_cpp
from llama_cpp import Llama  # noqa: F401

binding = importlib.import_module("llama_cpp.llama_cpp")
spec = importlib.util.find_spec("llama_cpp")
if spec is None or spec.origin is None:
    raise RuntimeError("llama_cpp package origin could not be resolved")

package_dir = Path(spec.origin).resolve().parent
native_files = sorted(
    p for pattern in ("*.so", "*.dylib")
    for p in package_dir.rglob(pattern)
)
if not native_files:
    raise RuntimeError(f"No llama_cpp native libraries found under {package_dir}")

print(f"llama_runtime_probe=ok")
print(f"machine={platform.machine()}")
print(f"llama_cpp_module={llama_cpp.__file__}")
print(f"llama_cpp_binding={binding.__file__}")
print(f"llama_backend_init_available={hasattr(binding, 'llama_backend_init')}")
for path in native_files:
    print(f"llama_native={path}")
PY
  log "OK   : Probe llama-cpp-python runtime (${target_arch})"
}

llama_cmake_args_for_arch() {
  local target_arch="$1"
  local base_args="${CMAKE_ARGS:-}"
  local package_args="-DLLAMA_OPENSSL=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_SERVER=OFF -DGGML_CCACHE=OFF -DCMAKE_OSX_ARCHITECTURES=${target_arch}"

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
  local llama_cmake_args=""
  local llama_index_url
  local wheel_dir="$SCRIPT_DIR/.tmp_llama_install_${target_arch}_${TIMESTAMP}"
  local wheel_path
  local pip_args
  local download_args
  local requirement_env_name

  llama_index_url="$(llama_wheel_index_for_arch "$target_arch")"
  case "$target_arch" in
    arm64) requirement_env_name="LLAMA_CPP_REQUIREMENT_ARM64" ;;
    x86_64) requirement_env_name="LLAMA_CPP_REQUIREMENT_X86_64" ;;
    *) requirement_env_name="LLAMA_CPP_REQUIREMENT_<arch>" ;;
  esac

  if is_enabled "$LLAMA_CPP_ALLOW_SOURCE_BUILD" && ! is_enabled "$LLAMA_CPP_ONLY_BINARY"; then
    llama_cmake_args="$(llama_cmake_args_for_arch "$target_arch")"
    pip_args=(install --verbose --no-compile)
    if is_enabled "$LLAMA_CPP_NO_CACHE"; then
      pip_args+=(--no-cache-dir)
    fi
    pip_args+=(--extra-index-url "$llama_index_url")
    if is_enabled "$LLAMA_CPP_FORCE_REINSTALL"; then
      pip_args+=(--force-reinstall)
    fi
    pip_args+=("$llama_requirement")

    log "WARN : LLAMA_CPP_ALLOW_SOURCE_BUILD=1 and LLAMA_CPP_ONLY_BINARY=0; source builds are allowed for ${target_arch}."
    log "DEBUG: llama-cpp-python CMAKE_ARGS (${target_arch}): ${llama_cmake_args}"
    log "DEBUG: llama-cpp-python wheel index (${target_arch}): ${llama_index_url}"
    log "DEBUG: llama-cpp-python pip command (${target_arch}): ${python_exe} -m pip ${pip_args[*]}"
    CMAKE_ARGS="$llama_cmake_args" \
      ARCHFLAGS="-arch ${target_arch}" \
      run_arch "$target_arch" "$python_exe" -m pip "${pip_args[@]}"
    return 0
  fi

  is_enabled "$LLAMA_CPP_ONLY_BINARY" || fail "LLAMA_CPP_ONLY_BINARY must remain enabled unless LLAMA_CPP_ALLOW_SOURCE_BUILD=1."
  safe_remove_path "$wheel_dir"
  mkdir -p "$wheel_dir"

  download_args=(download --verbose --no-deps --only-binary llama-cpp-python --index-url "$llama_index_url" -d "$wheel_dir")
  if is_enabled "$LLAMA_CPP_NO_CACHE"; then
    download_args+=(--no-cache-dir)
  fi
  download_args+=("$llama_requirement")

  log "DEBUG: llama-cpp-python wheel index (${target_arch}): ${llama_index_url}"
  log "DEBUG: llama-cpp-python wheel download command (${target_arch}): ${python_exe} -m pip ${download_args[*]}"
  if ! run_arch "$target_arch" "$python_exe" -m pip "${download_args[@]}"; then
    safe_remove_path "$wheel_dir"
    fail "No llama-cpp-python binary wheel matching '${llama_requirement}' for ${target_arch} at ${llama_index_url}. Set ${requirement_env_name} or LLAMA_CPP_REQUIREMENT to a version available at that wheel index, or explicitly opt into source builds with LLAMA_CPP_ALLOW_SOURCE_BUILD=1 and LLAMA_CPP_ONLY_BINARY=0."
  fi

  wheel_path="$(find "$wheel_dir" -maxdepth 1 -type f -name "*.whl" | head -n 1)"
  [ -n "$wheel_path" ] || fail "No llama-cpp-python wheel was downloaded for ${target_arch} from ${llama_index_url}."
  log "DEBUG: llama-cpp-python selected wheel (${target_arch}): $(basename "$wheel_path")"

  pip_args=(install --verbose --no-compile)
  if is_enabled "$LLAMA_CPP_NO_CACHE"; then
    pip_args+=(--no-cache-dir)
  fi
  if is_enabled "$LLAMA_CPP_FORCE_REINSTALL"; then
    pip_args+=(--force-reinstall)
  fi
  pip_args+=("$wheel_path")

  log "DEBUG: llama-cpp-python pip command (${target_arch}): ${python_exe} -m pip ${pip_args[*]}"
  run_arch "$target_arch" "$python_exe" -m pip "${pip_args[@]}"
  safe_remove_path "$wheel_dir"
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
    if is_enabled "$LLAMA_CPP_ALLOW_VERSION_MISMATCH"; then
      log "WARN : Allowing mismatched llama-cpp-python versions for transitional release: x86_64=${x86_version}, arm64=${arm_version}."
      log "WARN : This build must pass per-architecture llama runtime smoke tests and should not be used as the long-term release strategy."
    else
      fail "Refusing to merge universal app with mismatched llama-cpp-python versions: x86_64=${x86_version}, arm64=${arm_version}."
    fi
  fi
}

verify_internal_imports() {
  local target_arch="$1"
  local python_exe="$2"

  log "RUN  : Verify required internal imports (${target_arch})"
  run_arch "$target_arch" "$python_exe" - "$SCRIPT_DIR" <<'PY'
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
  log "OK   : Verify required internal imports (${target_arch})"
}

warning_file_for_arch() {
  local target_arch="$1"
  case "$target_arch" in
    x86_64) printf '%s\n' "$LOG_DIR/warn-worklogger-x86_64.txt" ;;
    arm64) printf '%s\n' "$LOG_DIR/warn-worklogger-arm64.txt" ;;
    *) printf '%s\n' "$LOG_DIR/warn-worklogger.txt" ;;
  esac
}

inspect_warning_file() {
  local target_arch="$1"
  local warn_file
  warn_file="$(warning_file_for_arch "$target_arch")"
  if [ -f "$warn_file" ]; then
    if grep -Eq "services\.report_service|No module named 'services\.report_service'" "$warn_file"; then
      fail "PyInstaller warning log contains a required internal service import failure: $warn_file"
    fi
    log "OK   : PyInstaller warning file checked (${target_arch}): $warn_file"
  else
    log "OK   : PyInstaller warning log has no actionable warnings (${target_arch})."
  fi
}

smoke_test_app() {
  local main_exec="$1"
  local target_arch="$2"
  [ -f "$main_exec" ] || fail "Cannot smoke-test missing executable: $main_exec"
  log "RUN  : Smoke-test packaged executable imports (${target_arch})"
  run_arch "$target_arch" "$main_exec" --smoke-import
  log "OK   : Smoke-test packaged executable imports (${target_arch})"
}

smoke_test_local_model_runtime_app() {
  local main_exec="$1"
  local target_arch="$2"
  [ -f "$main_exec" ] || fail "Cannot smoke-test missing executable: $main_exec"
  log "RUN  : Smoke-test packaged llama runtime (${target_arch})"
  run_arch "$target_arch" "$main_exec" --smoke-local-model-runtime
  log "OK   : Smoke-test packaged llama runtime (${target_arch})"
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
  require_cmd codesign

  log "Checking Python interpreter architecture support: arm64=$PYTHON_BIN_ARM64 x86_64=$PYTHON_BIN_X86_64"
  run_arch x86_64 "$PYTHON_BIN_X86_64" -c 'import platform, sys; raise SystemExit(0 if sys.version_info >= (3, 10) and platform.machine()=="x86_64" else 1)' || fail "Python cannot run in x86_64 mode with Python 3.10+. Install Rosetta-compatible Python or set PYTHON_BIN_X86_64."
  run_arch arm64 "$PYTHON_BIN_ARM64" -c 'import platform, sys; raise SystemExit(0 if sys.version_info >= (3, 10) and platform.machine()=="arm64" else 1)' || fail "Python cannot run in arm64 mode with Python 3.10+. Install arm64 Python or set PYTHON_BIN_ARM64."
  if ! is_enabled "$LLAMA_CPP_ALLOW_SOURCE_BUILD" && ! is_enabled "$LLAMA_CPP_ONLY_BINARY"; then
    fail "Source builds are disabled by default; set LLAMA_CPP_ALLOW_SOURCE_BUILD=1 before disabling LLAMA_CPP_ONLY_BINARY."
  fi
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
  local llama_requirement
  local requirements_llama_requirement=""
  local llama_index_url
  local source_python
  source_python="$(python_bin_for_arch "$target_arch")"
  llama_index_url="$(llama_wheel_index_for_arch "$target_arch")"
  llama_requirement="$(llama_requirement_for_arch "$target_arch")"

  ensure_build_venv_for_arch "$target_arch" "$source_python" "$venv_dir" "$venv_python"

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
      requirements_llama_requirement="$(head -n 1 "$llama_requirement_file" | xargs)"
      if [ -z "$llama_requirement" ]; then
        llama_requirement="$requirements_llama_requirement"
      else
        log "DEBUG: requirements.txt declares ${requirements_llama_requirement}; using macOS architecture selection for ${target_arch}: ${llama_requirement}."
      fi
    fi
    safe_remove_path "$llama_requirement_file"

    log "DEBUG: Local-model runtime requirement (${target_arch}): $llama_requirement"
    log "DEBUG: Local-model runtime wheel index (${target_arch}): $llama_index_url"
    probe_llama_binary_wheel "$target_arch" "$venv_python" "selected_index" "$llama_requirement" --index-url "$llama_index_url"

    retry 3 5 "Install application requirements (${target_arch}, excluding local-model runtime)" \
      run_arch "$target_arch" "$venv_python" -m pip install --no-compile --no-cache-dir -r "$filtered_requirements_file"
    safe_remove_path "$filtered_requirements_file"

    # Install separately so CI logs show the selected architecture-specific wheel source.
    log "DEBUG: Installing llama-cpp-python separately (${target_arch}); release builds require binary wheels unless LLAMA_CPP_ALLOW_SOURCE_BUILD=1."
    retry 1 5 "Install local-model runtime (${target_arch})" \
      run_with_heartbeat "Install local-model runtime (${target_arch})" 120 \
      install_llama_runtime "$target_arch" "$venv_python" "$llama_requirement"
    print_llama_install_debug "$target_arch" "$venv_python" "$venv_dir"
    probe_llama_runtime_for_arch "$target_arch" "$venv_python"
  fi

  if ! run_arch "$target_arch" "$venv_python" - <<'PY'
import importlib

required = [
    "PySide6",
    "holidays",
    "httpx",
    "httpcore",
    "anyio",
    "portalocker",
    "keyring",
    "cryptography",
    "cryptography.hazmat.backends.openssl.backend",
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
  then
    fail "Dependency import verification failed for ${target_arch} build venv."
  fi
  verify_internal_imports "$target_arch" "$venv_python"
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
  inspect_warning_file "$target_arch"
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

audit_native_libraries_in_app() {
  local app_bundle="$1"
  local label="$2"

  [ -d "$app_bundle" ] || fail "Cannot audit missing app bundle: $app_bundle"
  log "DEBUG: Native libraries in app bundle (${label})"
  find "$app_bundle" -type f \( -name "*.so" -o -name "*.dylib" \) -print -exec file {} \; 2>/dev/null || true
}

verify_macho_files_contain_arch() {
  local app_bundle="$1"
  local expected_arch="$2"
  local label="$3"
  local path archs failures=0

  [ -d "$app_bundle" ] || fail "Cannot verify missing app bundle: $app_bundle"
  log "RUN  : Verify Mach-O files contain ${expected_arch} (${label})"
  while IFS= read -r -d '' path; do
    if ! file "$path" | grep -q "Mach-O"; then
      continue
    fi
    archs="$(lipo -archs "$path" 2>/dev/null || true)"
    if [[ "$archs" != *"$expected_arch"* ]]; then
      log "ERROR: Mach-O file is missing ${expected_arch}: ${path} (archs=${archs:-unknown})"
      failures=$((failures + 1))
    fi
  done < <(find "$app_bundle" -type f -print0)
  [ "$failures" -eq 0 ] || fail "Found ${failures} Mach-O file(s) missing ${expected_arch} in ${label}."
  log "OK   : Verify Mach-O files contain ${expected_arch} (${label})"
}

verify_universal_macho_files() {
  local app_bundle="$1"
  local label="$2"
  local path rel archs failures=0

  [ -d "$app_bundle" ] || fail "Cannot verify missing app bundle: $app_bundle"
  log "RUN  : Verify merged Mach-O files are universal (${label})"
  while IFS= read -r -d '' path; do
    if ! file "$path" | grep -q "Mach-O"; then
      continue
    fi
    rel="${path#"$app_bundle"/}"
    archs="$(lipo -archs "$path" 2>/dev/null || true)"
    if [[ "$archs" != *"x86_64"* ]] || [[ "$archs" != *"arm64"* ]]; then
      if allow_arch_specific_macho_relpath "$rel" && { [[ "$archs" == *"x86_64"* ]] || [[ "$archs" == *"arm64"* ]]; }; then
        log "WARN : Transitional llama native library is not universal: ${path} (archs=${archs:-unknown})"
        continue
      fi
      log "ERROR: Merged Mach-O file is not universal: ${path} (archs=${archs:-unknown})"
      failures=$((failures + 1))
    fi
  done < <(find "$app_bundle" -type f -print0)
  [ "$failures" -eq 0 ] || fail "Found ${failures} non-universal Mach-O file(s) in ${label}."
  log "OK   : Verify merged Mach-O files are universal (${label})"
}

extract_macho_arch_slice() {
  local input="$1"
  local target_arch="$2"
  local output="$3"
  local rel="$4"
  local archs

  archs="$(lipo -archs "$input" 2>/dev/null || true)"
  if [[ " $archs " != *" $target_arch "* ]]; then
    fail "Mach-O file is missing ${target_arch} slice: $rel (archs=${archs:-unknown})"
  fi

  if [ "$archs" = "$target_arch" ]; then
    ditto "$input" "$output"
    return 0
  fi

  if ! lipo "$input" -thin "$target_arch" -output "$output" 2>/dev/null; then
    fail "Unable to extract ${target_arch} slice before lipo merge: $rel"
  fi
}

merge_universal_bundle() {
  local x86_app="$1"
  local arm_app="$2"

  mkdir -p "$OUT_DIST"
  safe_remove_path "$OUT_APP"
  ditto "$arm_app" "$OUT_APP"

  log "RUN  : Merge Mach-O binaries from x86_64 and arm64 bundles"
  local merged=0
  local missing_counterparts=0
  local merge_tmp_dir="$SCRIPT_DIR/.tmp_lipo_merge_${TIMESTAMP}"
  local merge_index=0
  local f rel x86f arm_archs x86_archs arm_slice x86_slice out_slice original_mode
  safe_remove_path "$merge_tmp_dir"
  mkdir -p "$merge_tmp_dir"
  while IFS= read -r -d '' f; do
    if ! file "$f" | grep -q "Mach-O"; then
      continue
    fi
    rel="${f#"$OUT_APP"/}"
    x86f="$x86_app/$rel"
    if [ ! -f "$x86f" ]; then
      if allow_arch_specific_macho_relpath "$rel"; then
        log "WARN : Keeping arm64-only transitional llama native library: $rel"
      else
        log "ERROR: Missing x86_64 counterpart for arm64 Mach-O file: $rel"
        missing_counterparts=$((missing_counterparts + 1))
      fi
      continue
    fi
    arm_archs="$(lipo -archs "$f" 2>/dev/null || true)"
    x86_archs="$(lipo -archs "$x86f" 2>/dev/null || true)"
    if [[ "$arm_archs" != *"arm64"* ]]; then
      fail "arm64 bundle Mach-O file is missing arm64 slice: $rel (archs=${arm_archs:-unknown})"
    fi
    if [[ "$x86_archs" != *"x86_64"* ]]; then
      fail "x86_64 bundle Mach-O file is missing x86_64 slice: $rel (archs=${x86_archs:-unknown})"
    fi
    merge_index=$((merge_index + 1))
    arm_slice="$merge_tmp_dir/${merge_index}.arm64"
    x86_slice="$merge_tmp_dir/${merge_index}.x86_64"
    out_slice="$merge_tmp_dir/${merge_index}.universal"
    original_mode="$(stat -f "%Lp" "$f" 2>/dev/null || true)"
    rm -f "$arm_slice" "$x86_slice" "$out_slice" || true
    extract_macho_arch_slice "$f" "arm64" "$arm_slice" "$rel"
    extract_macho_arch_slice "$x86f" "x86_64" "$x86_slice" "$rel"
    if ! lipo -create "$arm_slice" "$x86_slice" -output "$out_slice" 2>/dev/null; then
      rm -f "$arm_slice" "$x86_slice" "$out_slice" || true
      fail "Unable to merge same-path Mach-O file with lipo: $rel"
    fi
    [ -n "$original_mode" ] && chmod "$original_mode" "$out_slice" || true
    mv "$out_slice" "$f"
    rm -f "$arm_slice" "$x86_slice" || true
    merged=$((merged + 1))
  done < <(find "$OUT_APP" -type f -print0)

  while IFS= read -r -d '' x86f; do
    if ! file "$x86f" | grep -q "Mach-O"; then
      continue
    fi
    rel="${x86f#"$x86_app"/}"
    if [ ! -f "$OUT_APP/$rel" ]; then
      if allow_arch_specific_macho_relpath "$rel"; then
        log "WARN : Copying x86_64-only transitional llama native library: $rel"
        mkdir -p "$(dirname "$OUT_APP/$rel")"
        ditto "$x86f" "$OUT_APP/$rel"
      else
        log "ERROR: x86_64 Mach-O file has no matching path in final app: $rel"
        missing_counterparts=$((missing_counterparts + 1))
      fi
    fi
  done < <(find "$x86_app" -type f -print0)

  [ "$missing_counterparts" -eq 0 ] || fail "Cannot safely create hybrid universal app; ${missing_counterparts} Mach-O file(s) do not exist at matching paths in both architecture bundles."
  safe_remove_path "$merge_tmp_dir"
  log "OK   : Mach-O merge summary: merged=${merged}"
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
log "llama arm64 wheel index : $LLAMA_CPP_ARM64_WHEEL_INDEX_URL"
log "llama x86_64 wheel index: $LLAMA_CPP_X86_64_WHEEL_INDEX_URL"
log "llama requirement arm64 : $LLAMA_CPP_REQUIREMENT_ARM64"
log "llama requirement x86_64: $LLAMA_CPP_REQUIREMENT_X86_64"
log "llama binary-only       : $LLAMA_CPP_ONLY_BINARY (allow_source=$LLAMA_CPP_ALLOW_SOURCE_BUILD)"
log "llama mismatch allowed  : $LLAMA_CPP_ALLOW_VERSION_MISMATCH (arch_specific_libs=$LLAMA_CPP_ALLOW_ARCH_SPECIFIC_LLAMA_LIBS)"
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
audit_native_libraries_in_app "$X86_APP" "x86_64"
verify_macho_files_contain_arch "$X86_APP" "x86_64" "x86_64 app"
smoke_test_app "$X86_MAIN" "x86_64"
smoke_test_local_model_runtime_app "$X86_MAIN" "x86_64"

log "Step 2/3: Build arm64 (native)"
build_for_arch "arm64" "$DIST_ARM" "$BUILD_ARM" "$VENV_ARM"
ARM_APP="$(resolve_built_bundle "$DIST_ARM" "arm64")"
ARM_MAIN="$ARM_APP/Contents/MacOS/${APP_NAME}"
audit_native_libraries_in_app "$ARM_APP" "arm64"
verify_macho_files_contain_arch "$ARM_APP" "arm64" "arm64 app"
smoke_test_app "$ARM_MAIN" "arm64"
smoke_test_local_model_runtime_app "$ARM_MAIN" "arm64"

verify_llama_version_match

log "Step 3/3: Merge into universal app"
merge_universal_bundle "$X86_APP" "$ARM_APP"
validate_final_artifact
audit_native_libraries_in_app "$OUT_APP" "merged universal"
verify_universal_macho_files "$OUT_APP" "merged universal app"
resign_merged_bundle
verify_codesign_integrity

MAIN_EXEC="$OUT_APP/Contents/MacOS/${APP_NAME}"
smoke_test_app "$MAIN_EXEC" "arm64"
smoke_test_app "$MAIN_EXEC" "x86_64"
smoke_test_local_model_runtime_app "$MAIN_EXEC" "arm64"
smoke_test_local_model_runtime_app "$MAIN_EXEC" "x86_64"
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
