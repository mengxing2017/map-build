#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/derived-map.sh"

DERIVED_MAP="" FORMAT="${IMPORT_FORMAT:-zip}" passthrough=()
for arg in "$@"; do
  if parse_common_arg "${arg}"; then continue; fi
  case "${arg}" in
    --derived-map=*) DERIVED_MAP="${arg#*=}" ;;
    --format=*) FORMAT="${arg#*=}" ;;
    --output=*|--transfer-id=*) passthrough+=("${arg}") ;;
    -h|--help) printf 'usage: %s --derived-map=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--format=tar|zip] [--output=<archive-path>] [--transfer-id=<id>] [--workdir=<path>]\n' "$0"; exit 0 ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done
[[ -n "${DERIVED_MAP}" ]] || die "${HUAVD_EXIT_INPUT}" "--derived-map is required"
derived_map_validate "${DERIVED_MAP}"
REGION="$(derived_map_target_region "${DERIVED_MAP}")"; normalize_session_vars
"${SCRIPT_DIR}/verify-derived-map.sh" --derived-map="${DERIVED_MAP}" --session="${SESSION}" --workdir="${WORKDIR}" --strict
"${SCRIPT_DIR}/prepare-import.sh" --region="${REGION}" --session="${SESSION}" --role=base --format="${FORMAT}" --workdir="${WORKDIR}" "${passthrough[@]}"
