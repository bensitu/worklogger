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
  local llama_requirement="llama-cpp-python>=0.2.90"

  if [ ! -x "$VENV_PYTHON" ]; then
    log "RUN  : Create build virtual environment at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    log "OK   : Create build virtual environment"
  else
    log "OK   : Reusing build virtual environment at $VENV_DIR"
  fi

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

    retry 3 5 "Install llama-cpp-python prebuilt CPU wheel" \
      "$VENV_PYTHON" -m pip install \
        --no-cache-dir \
        --timeout 60 \
        --retries 2 \
        --prefer-binary \
        --only-binary llama-cpp-python \
        --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
        "$llama_requirement"
  else
    log "WARN : requirements.txt not found. Skipping application dependency installation."
  fi

  "$VENV_PYTHON" -c 'import importlib.util, sys; req=["PySide6","holidays","keyring","cryptography","httpx","httpcore","anyio","portalocker"]; miss=[m for m in req if importlib.util.find_spec(m) is None]; print("dependency_check=", "ok" if not miss else ",".join(miss)); sys.exit(1 if miss else 0)'
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

verify_prerequisites
cleanup_source_cache_artifacts
install_dependencies

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

[ -f "$TARGET_BIN" ] || fail "Expected artifact missing: $TARGET_BIN"
[ -s "$TARGET_BIN" ] || fail "Artifact size is zero bytes: $TARGET_BIN"
chmod +x "$TARGET_BIN"

if command -v file >/dev/null 2>&1; then
  file "$TARGET_BIN"
fi

safe_remove_path "$BUILD_DIR"

log "SUCCESS: Linux onefile build completed."
log "SUCCESS: Artifact verified at $TARGET_BIN."
log "SUCCESS: Detailed log saved to $LOG_FILE."
