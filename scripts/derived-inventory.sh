#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/source-asset.sh"
source "${SCRIPT_DIR}/lib/derived-map.sh"

DERIVED_MAP=""
for arg in "$@"; do
  if parse_common_arg "${arg}"; then continue; fi
  case "${arg}" in
    --derived-map=*) DERIVED_MAP="${arg#*=}" ;;
    -h|--help) printf 'usage: %s --derived-map=<id> [--workdir=<path>]\n' "$0"; exit 0 ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done
[[ -n "${DERIVED_MAP}" ]] || die "${HUAVD_EXIT_INPUT}" "--derived-map is required"
derived_map_validate "${DERIVED_MAP}"
while IFS= read -r asset; do
  "${SCRIPT_DIR}/source-inventory.sh" --asset="${asset}" --workdir="${WORKDIR}"
done < <(derived_map_source_assets "${DERIVED_MAP}")
printf 'derived-inventory: PASS derived-map=%s\n' "${DERIVED_MAP}"
