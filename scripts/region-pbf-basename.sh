#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

region="${1:-${REGION:-}}"
[[ -n "${region}" ]] || die "${HUAVD_EXIT_INPUT}" "region is required"
require_cmd jq
require_region "${region}"

basename="$(region_pbf_basename "${region}")"
[[ -n "${basename}" && "${basename}" != "null" ]] \
  || die "${HUAVD_EXIT_INPUT}" "region lacks geofabrik.basename: ${region}"

printf '%s\n' "${basename}"
