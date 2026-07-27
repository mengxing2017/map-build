#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

REQUIRED=(
  bash
  jq
  wget
  md5sum
  sha512sum
  sha256sum
  tar
  zip
  osmium
  tippecanoe
  pmtiles
)

WARNINGS=0

check_cmd() {
  local cmd="$1"
  local version
  if command -v "${cmd}" >/dev/null 2>&1; then
    version="$(cmd_version "${cmd}")"
    if [[ -n "${version}" ]]; then
      printf 'OK   %-12s %s\n' "${cmd}" "${version}"
    else
      printf 'WARN %-12s found but not runnable\n' "${cmd}"
      WARNINGS=$((WARNINGS + 1))
    fi
  else
    printf 'WARN %-12s missing\n' "${cmd}"
    WARNINGS=$((WARNINGS + 1))
  fi
}

for cmd in "${REQUIRED[@]}"; do
  check_cmd "${cmd}"
done

if command -v yq >/dev/null 2>&1; then
  printf 'OK   %-12s %s\n' "yq" "$(cmd_version yq)"
elif command -v python3 >/dev/null 2>&1 && python3 -c 'import yaml' >/dev/null 2>&1; then
  printf 'OK   %-12s python3+PyYAML\n' "yaml"
elif command -v ruby >/dev/null 2>&1 && ruby -ryaml -e 'exit 0' >/dev/null 2>&1; then
  printf 'OK   %-12s ruby stdlib yaml\n' "yaml"
else
  printf 'WARN %-12s missing yq or python3+PyYAML\n' "yaml"
  WARNINGS=$((WARNINGS + 1))
fi

if ((WARNINGS == 0)); then
  printf 'doctor: OK\n'
else
  printf 'doctor: WARN (%d missing item(s))\n' "${WARNINGS}"
  printf 'install hints: run devbox run setup, or run ./scripts/setup-tools.sh inside devbox shell. See README.md environment setup for manual commands.\n'
fi
