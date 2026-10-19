#!/usr/bin/env bash
# Download only the commit declared by the project source lock. Reuse exact caches.
set -euo pipefail

NATIVE_PROGRESS_SCRIPT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/native-progress.py"

native_run_stage() {
  local python="${NATIVE_PROGRESS_PYTHON:-python3}"
  if declare -F huavd_python >/dev/null && [[ -z "${NATIVE_PROGRESS_PYTHON:-}" ]]; then
    python="$(huavd_python)"
  fi
  "${python}" "${NATIVE_PROGRESS_SCRIPT}" "$@"
}

native_checkout_locked() {
  local repository="$1" revision="$2" destination="$3"
  if [[ ! -d "${destination}/.git" ]]; then
    if [[ -e "${destination}" ]]; then
      printf 'Native source cache is not a Git checkout: %s\n' "${destination}" >&2
      return 1
    fi
    mkdir -p "${destination}"
    git init -q "${destination}"
  fi
  if ! git -C "${destination}" cat-file -e "${revision}^{commit}" 2>/dev/null; then
    printf 'Fetching Native source %s at %s\n' "${repository}" "${revision}" >&2
    local status
    if native_run_stage "fetch:${destination}" timeout "${NATIVE_FETCH_TIMEOUT_SECONDS:-300}" \
        git -c http.lowSpeedLimit=1024 -c http.lowSpeedTime=60 \
        -C "${destination}" fetch --depth=1 "${repository}" "${revision}"; then
      :
    else
      status=$?
      printf 'Native source fetch failed (exit=%s): %s commit=%s cache=%s\n' \
        "${status}" "${repository}" "${revision}" "${destination}" >&2
      printf 'Check Git network/proxy access and rerun setup; cached sources are retained. Exit 124 means fetch timed out.\n' >&2
      return "${status}"
    fi
  fi
  if git -C "${destination}" rev-parse --verify HEAD >/dev/null 2>&1; then
    [[ "$(git -C "${destination}" rev-parse HEAD)" == "${revision}" ]] || {
      printf 'Native cache revision mismatch: %s\n' "${destination}" >&2; return 1;
    }
    [[ -z "$(git -C "${destination}" status --porcelain)" ]] || {
      printf 'Native cache has unrecorded changes: %s\n' "${destination}" >&2; return 1;
    }
  else
    native_run_stage "checkout:${destination}" git -C "${destination}" checkout --detach "${revision}"
  fi
}
