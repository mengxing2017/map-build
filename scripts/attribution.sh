#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    -h|--help)
      printf 'usage: %s --region=<id> --role=<base|building> [--workdir=<path>] [--yyyymmdd=YYYYMMDD]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq
require_region "${REGION}"
normalize_session_vars
[[ "${ROLE}" == "base" || "${ROLE}" == "building" ]] \
  || die "${HUAVD_EXIT_INPUT}" "attribution role must be base or building"

output="$(build_attribution_path "${ROLE}")"
ensure_dir "$(dirname -- "${output}")"

jq -n \
  --arg url "$(region_pbf_url "${REGION}")" \
  '{
    data_license: "ODbL-1.0",
    attribution: "© OpenStreetMap contributors",
    sources: [
      {vendor: "geofabrik", url: $url}
    ]
  }' > "${output}"

log_info "attribution OK: ${output}"
