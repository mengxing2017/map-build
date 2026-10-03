#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/overview.sh
source "${SCRIPT_DIR}/lib/overview.sh"

INPUT=""
FILTERED_PBF=""
OVERVIEW=""

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --input=*) INPUT="${arg#*=}" ;;
    --filtered-pbf=*) FILTERED_PBF="${arg#*=}" ;;
    --overview=*) OVERVIEW="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> [--yyyymmdd=YYYYMMDD] [--input=<admin-line.geojsonseq>] [--filtered-pbf=<admin-line.osm.pbf>] [--workdir=<path>]\n' "$0"
      printf '       %s --overview=<id> [--yyyymmdd=YYYYMMDD] [--input=<admin-line.geojsonseq>] [--filtered-pbf=<admin-line.osm.pbf>] [--workdir=<path>]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq osmium awk sort uniq sha512sum tail
validate_yyyymmdd "${YYYYMMDD}"
admin_line_hierarchy_validate

if [[ -n "${OVERVIEW}" ]]; then
  overview_validate "${OVERVIEW}"
  stage="$(overview_staging_dir "${OVERVIEW}" "${YYYYMMDD}")"
  INPUT="${INPUT:-${stage}/layers/admin_line.geojsonseq}"
  FILTERED_PBF="${FILTERED_PBF:-$(overview_filter_cache_dir "${OVERVIEW}")/$(sha512_value "${stage}/source.osm.pbf")/admin_line.osm.pbf}"
  hierarchy="$(admin_line_hierarchy_resolve "" 1)"
  derived_dir="${WORKDIR}/derived/overview/${OVERVIEW}-${YYYYMMDD}"
else
  require_region "${REGION}"
  normalize_session_vars
  slug="$(region_slug_configured "${REGION}")"
  INPUT="${INPUT:-$(layers_dir)/admin_line.geojsonseq}"
  FILTERED_PBF="${FILTERED_PBF:-$(tags_filter_cache_dir)/${slug}-admin_line.osm.pbf}"
  hierarchy="$(admin_line_hierarchy_resolve "${REGION}")"
  derived_dir="${WORKDIR}/derived/${SESSION}"
fi

require_file "${INPUT}"
require_file "${FILTERED_PBF}"
ensure_dir "${derived_dir}"

sidecar_pairs="${derived_dir}/admin-line-relation-level.tsv"
sidecar_json="${derived_dir}/admin-line-relation-level.json"
report="${derived_dir}/admin-line-tier-report.json"
tmp_output="${INPUT}.admin-line-tier.tmp"
tmp_audit="$(mktemp)"
audit_json="$(mktemp)"
retained_json="$(mktemp)"
trap 'rm -f "${tmp_output}" "${tmp_audit}" "${audit_json}" "${retained_json}"' EXIT

if [[ ! -s "${INPUT}" ]]; then
  jq -n \
    --arg region "${REGION:-${OVERVIEW}}" \
    '{schema_version:1,region:$region,layer:"admin_line",
      relation_sidecar:{way_count:0},
      retained:{count:0,id_leak_count:0},
      discarded:{count:0,by_reason:{}}}' > "${report}"
  log_info "admin line tiers: empty layer; report=${report}"
  exit 0
fi

log_info "index administrative relation member levels -> ${sidecar_json}"
# osmium XML writes members before tags, so each relation's way references are
# buffered until its admin_level is known at the closing element.
osmium cat "${FILTERED_PBF}" -t r -f xml -o - \
  | awk '
      /<relation / { level=""; count=0; delete members }
      /<member type="way" ref="[0-9]+"/ {
        if (match($0, /ref="[0-9]+"/)) members[++count] = substr($0, RSTART + 5, RLENGTH - 6)
      }
      /<tag k="admin_level" v="[^"]*"/ {
        if (match($0, /v="[^"]*"/)) level = substr($0, RSTART + 3, RLENGTH - 4)
      }
      /<\/relation>/ {
        if (level ~ /^[0-9]+$/) for (i = 1; i <= count; i++) print members[i] "\t" (level + 0)
      }
    ' \
  | LC_ALL=C sort -t $'\t' -k1,1n -k2,2n \
  | uniq > "${sidecar_pairs}"

jq -Rn '
  [inputs | split("\t") | select(length == 2) | {key: .[0], value: (.[1] | tonumber)}]
  | group_by(.key)
  | map({key: .[0].key, value: ([.[].value] | unique | sort)})
  | from_entries
' "${sidecar_pairs}" > "${sidecar_json}"

log_info "assign administrative line tiers -> ${INPUT}"
jq --seq -c \
  --slurpfile sidecar_file "${sidecar_json}" \
  --argjson hierarchy "${hierarchy}" '
    def numeric_level($value):
      if ($value | type) == "string" then
        if ($value | test("^[0-9]+$")) then ($value | tonumber) else null end
      elif ($value | type) == "number" and ($value | floor) == $value and $value >= 0 then
        $value
      else
        null
      end;
    $sidecar_file[0] as $sidecar
    | .properties = (.properties // {})
    | select((.geometry.type // "") == "LineString" or (.geometry.type // "") == "MultiLineString")
    | ((.properties["@id"] // null) | tostring) as $way_id
    | ($sidecar[$way_id] // []) as $relation_levels
    | (numeric_level(.properties.admin_level // null)) as $way_level
    | (if ($relation_levels | length) > 0 then ($relation_levels | min) else $way_level end) as $render_level
    | select($render_level != null)
    | select(($relation_levels | length) > 0 or (.properties.boundary // "") == "administrative")
    | ($hierarchy.level_tier[($render_level | tostring)] // null) as $tier
    | select($tier != null)
    | .properties.admin_level = $render_level
    | .properties.admin_tier = $tier
    | .properties.level_source = (if ($relation_levels | length) > 0 then "relation" else "way" end)
    | .tippecanoe = $hierarchy.tier_zoom[$tier]
    | del(.properties["@id"])
  ' "${INPUT}" > "${tmp_output}" \
  || die "${HUAVD_EXIT_ERROR}" "admin line tier assignment failed"

# Keep the audit independent from the transformed output so rejected features
# remain observable without leaking @id into vector tiles.
jq --seq -c \
  --slurpfile sidecar_file "${sidecar_json}" \
  --argjson hierarchy "${hierarchy}" '
    def numeric_level($value):
      if ($value | type) == "string" then
        if ($value | test("^[0-9]+$")) then ($value | tonumber) else null end
      elif ($value | type) == "number" and ($value | floor) == $value and $value >= 0 then
        $value
      else
        null
      end;
    $sidecar_file[0] as $sidecar
    | .properties = (.properties // {})
    | (.geometry.type // "unknown") as $geometry
    | ((.properties["@id"] // null) | tostring) as $way_id
    | ($sidecar[$way_id] // []) as $relation_levels
    | (numeric_level(.properties.admin_level // null)) as $way_level
    | (if ($relation_levels | length) > 0 then ($relation_levels | min) else $way_level end) as $render_level
    | if $geometry != "LineString" and $geometry != "MultiLineString" then
        {status: "discarded", reason: "geometry", geometry: $geometry}
      elif $render_level == null then
        {status: "discarded", reason: (if .properties.admin_level == null then "missing_level" else "invalid_level" end), geometry: $geometry}
      elif (($relation_levels | length) == 0 and (.properties.boundary // "") != "administrative") then
        {status: "discarded", reason: "unlinked_boundary", geometry: $geometry}
      elif ($hierarchy.level_tier[($render_level | tostring)] // null) == null then
        {status: "discarded", reason: "unmapped_level", geometry: $geometry, level: $render_level}
      else
        {status: "kept", geometry: $geometry,
         level: $render_level,
         tier: $hierarchy.level_tier[($render_level | tostring)],
         level_source: (if ($relation_levels | length) > 0 then "relation" else "way" end)}
      end
  ' "${INPUT}" > "${tmp_audit}" \
  || die "${HUAVD_EXIT_ERROR}" "admin line tier audit failed"

# jq --seq prefixes its aggregated JSON value with RS. Strip that transport
# delimiter only for the temporary JSON arrays consumed by the report; the
# staged GeoJSONSeq keeps its RS delimiters.
jq --seq -sc . "${tmp_audit}" | tail -c +2 > "${audit_json}"
jq --seq -sc . "${tmp_output}" | tail -c +2 > "${retained_json}"
jq -n \
  --arg input "${INPUT}" \
  --arg filtered_pbf "${FILTERED_PBF}" \
  --slurpfile sidecar_file "${sidecar_json}" \
  --slurpfile audit_file "${audit_json}" \
  --slurpfile retained_file "${retained_json}" '
    def counts_by($items; $field):
      $items | group_by(.[$field])
      | map({key: (.[0][$field] | tostring), value: length}) | from_entries;
    def geometry_counts($items):
      $items | group_by(.geometry)
      | map({key: .[0].geometry, value: length}) | from_entries;
    ($sidecar_file[0]) as $sidecar
    | ($audit_file[0]) as $audit
    | ($retained_file[0]) as $retained
    | ($audit | map(select(.status == "kept"))) as $kept
    | ($audit | map(select(.status == "discarded"))) as $discarded
    | ($sidecar | to_entries) as $side_entries
    | {
        schema_version: 1,
        input: $input,
        filtered_pbf: $filtered_pbf,
        input_feature_count: ($audit | length),
        relation_sidecar: {
          member_level_pair_count: ($side_entries | map(.value | length) | add // 0),
          way_count: ($side_entries | length),
          multi_level_way_count: ($side_entries | map(select(.value | length > 1)) | length),
          multi_level_combinations: ($side_entries
            | map(select(.value | length > 1) | {levels: (.value | map(tostring) | join(","))})
            | counts_by(.; "levels"))
        },
        geometry: geometry_counts($audit),
        retained: {
          count: ($kept | length),
          by_tier: counts_by($kept; "tier"),
          by_level_source: counts_by($kept; "level_source"),
          relation_rescued_count: ($kept | map(select(.level_source == "relation")) | length),
          id_leak_count: ($retained | map(select((.properties["@id"] // null) != null)) | length)
        },
        discarded: {
          count: ($discarded | length),
          by_reason: counts_by($discarded; "reason")
        }
      }
  ' > "${report}"

mv "${tmp_output}" "${INPUT}"
log_info "admin line tiers OK: ${report}"
