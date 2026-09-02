#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/derived-map.sh"

DERIVED_MAP="" FORMAT="${FORMAT:-both}"
for arg in "$@"; do
  if parse_common_arg "${arg}"; then continue; fi
  case "${arg}" in
    --derived-map=*) DERIVED_MAP="${arg#*=}" ;;
    --format=*) FORMAT="${arg#*=}" ;;
    -h|--help) printf 'usage: %s --derived-map=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--format=tar|zip|both] [--workdir=<path>]\n' "$0"; exit 0 ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done
[[ -n "${DERIVED_MAP}" ]] || die "${HUAVD_EXIT_INPUT}" "--derived-map is required"
derived_map_validate "${DERIVED_MAP}"
REGION="$(derived_map_target_region "${DERIVED_MAP}")"; normalize_session_vars
"${SCRIPT_DIR}/verify-derived-map.sh" --derived-map="${DERIVED_MAP}" --session="${SESSION}" --workdir="${WORKDIR}" --strict
"${SCRIPT_DIR}/pack.sh" --region="${REGION}" --session="${SESSION}" --role=base --format="${FORMAT}" --workdir="${WORKDIR}"
