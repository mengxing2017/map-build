#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/source-asset.sh"
source "${SCRIPT_DIR}/lib/derived-map.sh"

DERIVED_MAP=""
FORCE=0
for arg in "$@"; do
  if parse_common_arg "${arg}"; then continue; fi
  case "${arg}" in
    --derived-map=*) DERIVED_MAP="${arg#*=}" ;;
    --force) FORCE=1 ;;
    -h|--help) printf 'usage: %s --derived-map=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--force]\n' "$0"; exit 0 ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done
[[ -n "${DERIVED_MAP}" ]] || die "${HUAVD_EXIT_INPUT}" "--derived-map is required"
require_cmd jq sort awk
derived_map_validate "${DERIVED_MAP}"
REGION="$(derived_map_target_region "${DERIVED_MAP}")"
normalize_session_vars
report="$(derived_map_report_path)"
if [[ "${FORCE}" != 1 && -f "${report}" ]]; then
  printf '%s\n' "$(layers_dir)"
  exit 0
fi

mapfile -t assets < <(derived_map_source_assets "${DERIVED_MAP}")
declare -a adapter_layers=()
for asset in "${assets[@]}"; do
  "${SCRIPT_DIR}/adapter-run.sh" --asset="${asset}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" $( [[ "${FORCE}" == 1 ]] && printf '%s' --force ) >/dev/null
  adapter_layers+=("$(source_asset_cache_dir "${asset}")/layers")
done

target_layers="$(layers_dir)"
rm -rf "${target_layers}"
ensure_dir "${target_layers}"
layer_stats='{}'
while IFS= read -r layer; do
  files=()
  before=0
  for source_layers in "${adapter_layers[@]}"; do
    file="${source_layers}/${layer}.geojsonseq"
    require_file "${file}"
    files+=("${file}")
    count="$(tr '\036' '\n' < "${file}" | sed '/^$/d' | wc -l | tr -d ' ')"
    before=$((before + count))
  done
  jq --seq -cS . "${files[@]}" | tr '\036' '\n' | sed '/^$/d' | LC_ALL=C sort -u | awk '{printf "\036%s\n", $0}' > "${target_layers}/${layer}.geojsonseq"
  after="$(tr '\036' '\n' < "${target_layers}/${layer}.geojsonseq" | sed '/^$/d' | wc -l | tr -d ' ')"
  layer_stats="$(jq -cn --argjson current "${layer_stats}" --arg layer "${layer}" --argjson before "${before}" --argjson after "${after}" '$current + {($layer): {input_features:$before, output_features:$after, exact_duplicates_removed:($before-$after)}}')"
done < <(effective_role_layers "${REGION}" base)

asset_lineage="$(for asset in "${assets[@]}"; do source_asset_json "${asset}" | jq -c --arg fingerprint "$(source_asset_fingerprint "${asset}")" '. + {fingerprint:$fingerprint}'; done | jq -s .)"
ensure_dir "$(outputs_dir)"
jq -n \
  --arg schema "huavd-map-build/composition-v1" \
  --arg derived_map "${DERIVED_MAP}" \
  --arg target_region "${REGION}" \
  --arg policy "$(derived_map_policy "${DERIVED_MAP}")" \
  --arg generated_at "$(timestamp_utc)" \
  --argjson assets "${asset_lineage}" \
  --argjson layers "${layer_stats}" \
  '{schema:$schema,derived_map:$derived_map,target_region:$target_region,conflict_policy:$policy,generated_at:$generated_at,assets:$assets,layers:$layers}' > "${report}"
printf '%s\n' "${target_layers}"
