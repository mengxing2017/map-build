#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/source-asset.sh"

ASSET=""
FORCE=0
for arg in "$@"; do
  if parse_common_arg "${arg}"; then continue; fi
  case "${arg}" in
    --asset=*) ASSET="${arg#*=}" ;;
    --force) FORCE=1 ;;
    -h|--help) printf 'usage: %s --asset=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--force]\n' "$0"; exit 0 ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done
[[ -n "${ASSET}" ]] || die "${HUAVD_EXIT_INPUT}" "--asset is required"
require_cmd jq osmium
source_asset_validate "${ASSET}"
"${SCRIPT_DIR}/source-inventory.sh" --asset="${ASSET}" --workdir="${WORKDIR}" >/dev/null

cache_dir="$(source_asset_cache_dir "${ASSET}")"
layers_out="${cache_dir}/layers"
manifest="${cache_dir}/adapter.manifest.json"
if [[ "${FORCE}" != 1 && -f "${manifest}" ]]; then
  printf '%s\n' "${layers_out}"
  exit 0
fi
rm -rf "${cache_dir}"
ensure_dir "${layers_out}"

mapfile -t layers < <(selected_layers all)
for layer in "${layers[@]}"; do : > "${layers_out}/${layer}.geojsonseq"; done
source_root="${cache_dir}/sources"
while IFS= read -r region; do
  input="$(source_asset_input_path "${ASSET}" "${region}")"
  source_workdir="${source_root}/$(slugify_region "${region}")"
  source_session="$(session_from_region_yyyymmdd "${region}" "${YYYYMMDD}")"
  WORKDIR="${source_workdir}" REGION="${region}" YYYYMMDD="${YYYYMMDD}" SESSION="${source_session}" \
    "${SCRIPT_DIR}/tags-filter.sh" --input="${input}" --region="${region}" --yyyymmdd="${YYYYMMDD}" --workdir="${source_workdir}" --layers=all
  WORKDIR="${source_workdir}" REGION="${region}" YYYYMMDD="${YYYYMMDD}" SESSION="${source_session}" \
    "${SCRIPT_DIR}/export.sh" --region="${region}" --yyyymmdd="${YYYYMMDD}" --workdir="${source_workdir}" --layers=all
  WORKDIR="${source_workdir}" REGION="${region}" YYYYMMDD="${YYYYMMDD}" SESSION="${source_session}" \
    "${SCRIPT_DIR}/normalize.sh" --region="${region}" --yyyymmdd="${YYYYMMDD}" --workdir="${source_workdir}" --layers=all
  for layer in "${layers[@]}"; do
    cat "${source_workdir}/staging/${source_session}/layers/${layer}.geojsonseq" >> "${layers_out}/${layer}.geojsonseq"
  done
done < <(source_asset_input_regions "${ASSET}")

layer_stats="$(for layer in "${layers[@]}"; do printf '%s\t%s\n' "${layer}" "$(tr '\036' '\n' < "${layers_out}/${layer}.geojsonseq" | sed '/^$/d' | wc -l | tr -d ' ')"; done | jq -Rn '[inputs | split("\t") | {key:.[0], value:(.[1] | tonumber)}] | from_entries')"
jq -n \
  --arg asset "${ASSET}" \
  --arg adapter "$(source_asset_adapter "${ASSET}")" \
  --arg fingerprint "$(source_asset_fingerprint "${ASSET}")" \
  --argjson layers "${layer_stats}" \
  '{schema:"huavd-map-build/adapter-v1",asset:$asset,adapter:$adapter,fingerprint:$fingerprint,layers:$layers}' > "${manifest}"
printf '%s\n' "${layers_out}"
