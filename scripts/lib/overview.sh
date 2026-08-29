#!/usr/bin/env bash

set -euo pipefail

if [[ -z "${HUAVD_MAP_BUILD_CONFIG_LOADED:-}" ]]; then
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
fi

overview_json() {
  local id="$1"
  jq -e --arg id "${id}" '.overviews[] | select(.id == $id)' "$(overviews_json)"
}

require_overview() {
  local id="$1"
  [[ "${id}" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] \
    || die "${HUAVD_EXIT_INPUT}" "invalid overview id: ${id}"
  overview_json "${id}" >/dev/null \
    || die "${HUAVD_EXIT_INPUT}" "overview is not configured: ${id}"
}

overview_validate() {
  local id="$1" json layers layer region basename export_config
  require_overview "${id}"
  json="$(overviews_json)"
  jq -e --arg id "${id}" '
    .schema_version == 1
    and ([.overviews[].id] | length == (unique | length))
    and (.overviews[] | select(.id == $id) | (.source_regions | (type == "array" and length > 0 and (length == (unique | length))))
      and (.huavd.id | type == "string" and length > 0)
      and (.huavd.source_id | type == "string" and length > 0)
      and (.huavd.package_version_template | type == "string" and length > 0)
      and (.huavd.style_id | type == "string" and length > 0))
  ' "${json}" >/dev/null \
    || die "${HUAVD_EXIT_INPUT}" "invalid overview configuration: ${id}"
  layers="$(overview_params "${id}" | jq -r '.source_layers[]')"
  while IFS= read -r layer; do
    layer_exists "${layer}" || die "${HUAVD_EXIT_INPUT}" "overview ${id} references unknown layer: ${layer}"
    export_config="${CONFIG_DIR}/export-config/${layer}.json"
    require_file "${export_config}"
  done <<< "${layers}"
  while IFS= read -r region; do
    require_region "${region}"
    basename="$(region_pbf_basename "${region}")"
    [[ -n "${basename}" && "${basename}" != "null" ]] \
      || die "${HUAVD_EXIT_INPUT}" "overview ${id} source region has no PBF basename: ${region}"
  done < <(overview_source_regions "${id}")
  jq -e --arg id "${id}" '
    (.defaults + ((.overviews[] | select(.id == $id)).tippecanoe // {})) as $p
    | ($p.min_zoom | type == "number") and ($p.max_zoom | type == "number")
    and $p.min_zoom >= 0 and $p.min_zoom <= $p.max_zoom and $p.max_zoom <= 10
    and (((.overviews[] | select(.id == $id)).tippecanoe // {}) | keys
      - ["min_zoom", "max_zoom", "maximum_tile_bytes", "drop_densest_as_needed", "extend_zooms_if_still_dropping", "detect_shared_borders", "coalesce_densest_as_needed", "read_parallel", "source_layers"]
      | length == 0)
  ' "${json}" >/dev/null \
    || die "${HUAVD_EXIT_INPUT}" "overview ${id} must have 0 <= min_zoom <= max_zoom <= 10"
}

overview_source_regions() { overview_json "$1" | jq -r '.source_regions[]'; }

overview_params() {
  local id="$1"
  jq -c --arg id "${id}" '.defaults + ((.overviews[] | select(.id == $id)).tippecanoe // {})' "$(overviews_json)"
}

overview_layers_json() { overview_params "$1" | jq -c '.source_layers'; }
overview_layers() { overview_layers_json "$1" | jq -r '.[]'; }
overview_get() { overview_json "$2" | jq -r --arg key "$1" 'getpath($key | split(".")) // empty'; }
overview_session() { printf '%s-%s\n' "$1" "$2"; }
overview_staging_dir() { printf '%s/staging/overviews/%s\n' "${WORKDIR}" "$(overview_session "$1" "$2")"; }
overview_layers_dir() { printf '%s/layers\n' "$(overview_staging_dir "$1" "$2")"; }
overview_export_config_dir() { printf '%s/export-config\n' "$(overview_staging_dir "$1" "$2")"; }
overview_stem() { printf '%s-%s.overview\n' "$1" "$2"; }
overview_pmtiles_path() { printf '%s/%s.pmtiles\n' "$(outputs_dir)" "$(overview_stem "$1" "$2")"; }
overview_manifest_path() { printf '%s/%s.manifest.json\n' "$(outputs_dir)" "$(overview_stem "$1" "$2")"; }
overview_attribution_path() { printf '%s/%s.attribution.json\n' "$(outputs_dir)" "$(overview_stem "$1" "$2")"; }
overview_sha512_path() { printf '%s/%s.pmtiles.sha512\n' "$(outputs_dir)" "$(overview_stem "$1" "$2")"; }
overview_merge_cache_dir() { printf '%s/cache/merge/%s\n' "${WORKDIR}" "$1"; }
overview_filter_cache_dir() { printf '%s/cache/overview-tags-filter/%s\n' "${WORKDIR}" "$1"; }

overview_vector_layers_json() {
  local id="$1" max_zoom="$2" tmp layer
  tmp="$(mktemp)"
  while IFS= read -r layer; do
    jq -n --arg id "${layer}" --argjson minzoom "$(layer_min_zoom "${layer}")" \
      --argjson maxzoom "$(layer_effective_max_zoom "${layer}" base "${max_zoom}")" \
      --argjson fields "$(layer_final_fields_json "${layer}")" \
      '{id:$id,minzoom:$minzoom,maxzoom:$maxzoom,fields:$fields}' >> "${tmp}"
  done < <(overview_layers "${id}")
  jq -s '.' "${tmp}"
  rm -f "${tmp}"
}
