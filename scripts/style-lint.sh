#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

WORKDIR="${WORKDIR:-/tmp/huavd-map-build}"

if [[ ! -d "${WORKDIR}/outputs" ]]; then
  log_info "no outputs directory, skipping cross-region style lint"
  exit 0
fi

shopt -s nullglob
styles=("${WORKDIR}/outputs"/*.style.json)
if [[ "${#styles[@]}" -lt 2 ]]; then
  log_info "only ${#styles[@]} style.json, skipping cross-region lint"
  exit 0
fi

baseline="$(mktemp)"
trap 'rm -f "${baseline}"' EXIT

jq -S 'del(.sources, .metadata)' "${styles[0]}" > "${baseline}"

failed=0
for ((i=1; i<${#styles[@]}; i++)); do
  candidate="${styles[$i]}"
  if ! diff -q "${baseline}" <(jq -S 'del(.sources, .metadata)' "${candidate}") >/dev/null 2>&1; then
    log_error "style.json mismatch: ${styles[0]} vs ${candidate}"
    diff "${baseline}" <(jq -S 'del(.sources, .metadata)' "${candidate}") || true
    failed=1
  fi
done

if [[ "${failed}" == "0" ]]; then
  log_info "style-lint OK: ${#styles[@]} regions aligned"
else
  die "${HUAVD_EXIT_ERROR}" "cross-region style.json inconsistent"
fi
