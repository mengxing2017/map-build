#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/pmtiles.sh
source "${SCRIPT_DIR}/lib/pmtiles.sh"
# shellcheck source=lib/viewport.sh
source "${SCRIPT_DIR}/lib/viewport.sh"

WORKDIR="${WORKDIR:-/tmp/huavd-map-build}"

shopt -s nullglob
styles=("${WORKDIR}/outputs"/*.style.json)
if [[ "${#styles[@]}" -lt 1 ]]; then
  log_info "no style.json found, skipping viewport-lint"
  exit 0
fi

printf '%-32s %-24s %-24s %-10s\n' "REGION" "VIEWPORT_CENTER" "BOUNDS_CENTER" "ZOOM"
printf '%-32s %-24s %-24s %-10s\n' "------" "--------------" "-------------" "----"

failed=0
for style in "${styles[@]}"; do
  region_slug="$(basename "${style}" | sed -E 's/-[0-9]{8}\.style\.json$//')"
  yyyymmdd="$(basename "${style}" | sed -E 's/.*-([0-9]{8})\.style\.json$/\1/')"
  base_pmtiles="${WORKDIR}/outputs/${region_slug}-${yyyymmdd}.base.pmtiles"
  if [[ ! -f "${base_pmtiles}" ]]; then
    log_warn "no base.pmtiles for ${region_slug}"
    continue
  fi

  vp_center="$(jq -r '.metadata["huavd:viewport"].center // empty' "${style}" 2>/dev/null || true)"
  vp_zoom="$(jq -r '.metadata["huavd:viewport"].default_zoom // empty' "${style}" 2>/dev/null || true)"

  bounds_json="$(pmtiles_bounds "${base_pmtiles}")"
  min_lng="$(jq -r '.[0]' <<< "${bounds_json}")"
  min_lat="$(jq -r '.[1]' <<< "${bounds_json}")"
  max_lng="$(jq -r '.[2]' <<< "${bounds_json}")"
  max_lat="$(jq -r '.[3]' <<< "${bounds_json}")"
  bounds_center="$(jq -nc --argjson a "${min_lng}" --argjson b "${max_lng}" --argjson c "${min_lat}" --argjson d "${max_lat}" '[($a+$b)/2, ($c+$d)/2]')"

  if [[ -n "${vp_center}" && "${vp_center}" != "null" ]]; then
    vp_lng="$(jq -r '.[0]' <<< "${vp_center}")"
    vp_lat="$(jq -r '.[1]' <<< "${vp_center}")"
    if ! awk -v lng="${vp_lng}" -v lat="${vp_lat}" \
        -v a="${min_lng}" -v b="${max_lng}" -v c="${min_lat}" -v d="${max_lat}" \
        'BEGIN {
          eps = 0.0001
          if ((lng + eps) < a || (lng - eps) > b || (lat + eps) < c || (lat - eps) > d) {
            exit 1
          }
        }'; then
      log_error "viewport out of bounds: ${region_slug} [${vp_lng},${vp_lat}] not in [${min_lng},${min_lat},${max_lng},${max_lat}]"
      failed=1
    fi
  else
    vp_center="MISSING"
  fi

  printf '%-32s %-24s %-24s %-10s\n' "${region_slug}" "${vp_center}" "${bounds_center}" "${vp_zoom:-?}"
done

if [[ "${failed}" == "0" ]]; then
  log_info "viewport-lint OK"
else
  die "${HUAVD_EXIT_ERROR}" "viewport alignment failed"
fi
