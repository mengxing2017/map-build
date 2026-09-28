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
      printf 'usage: %s --region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq sha512sum
require_region "${REGION}"
normalize_session_vars

islands="$(layers_dir)/island.geojsonseq"
require_file "${islands}"

cache_dir="$(island_anchor_cache_dir)"
ensure_dir "${cache_dir}"
report="$(island_anchor_report_path)"
anchors_raw="${cache_dir}/anchors.raw.geojsonseq"
anchors_out="${cache_dir}/anchors.geojsonseq"
tmp="${islands}.island-anchor.tmp"

GRID_DIVISIONS=7

poly_count="$(tr '\036' '\n' < "${islands}" | sed '/^$/d' | jq -r '
  select(.geometry.type == "Polygon" or .geometry.type == "MultiPolygon") | 1
' | wc -l | tr -d ' ')"
point_count_before="$(tr '\036' '\n' < "${islands}" | sed '/^$/d' | jq -r '
  select(.geometry.type == "Point") | 1
' | wc -l | tr -d ' ')"

if (( poly_count == 0 )); then
  log_warn "island layer has no polygon feature; nothing to anchor"
  : > "${anchors_out}"
  jq -n \
    --arg region "${REGION}" \
    --argjson grid "${GRID_DIVISIONS}" \
    --argjson point_before "${point_count_before}" \
    '{schema_version:1,region:$region,layer:"island",
      thresholds:{grid_divisions:$grid},
      summary:{polygon_count:0,anchor_count:0,point_feature_count_before:$point_before,
               tier:{centroid:0,grid:0,vertex:0}},
      checks:{anchor_count_equals_polygon_count:true}}' > "${report}"
  log_info "island-anchor: no polygon island; report=${report}"
  exit 0
fi

log_info "derive one interior anchor per island polygon (${poly_count} polygons)"
jq --seq -n -c --argjson grid "${GRID_DIVISIONS}" '
  def fabs: if . < 0 then -. else . end;
  def ring_area($r):
    ($r | length) as $n
    | if $n < 3 then 0
      else (([range(0; $n) | ($r[.][0] * $r[(. + 1) % $n][1]) - ($r[(. + 1) % $n][0] * $r[.][1])] | add) | fabs) / 2
      end;
  def ring_centroid($r):
    ($r | length) as $n
    | if $n < 3 then null
      else
        reduce range(0; $n) as $i ({a: 0, x: 0, y: 0};
           ($r[$i][0]) as $x1 | ($r[$i][1]) as $y1
           | ($r[(($i + 1) % $n)][0]) as $x2 | ($r[(($i + 1) % $n)][1]) as $y2
           | ($x1 * $y2 - $x2 * $y1) as $cr
           | .a += $cr | .x += (($x1 + $x2) * $cr) | .y += (($y1 + $y2) * $cr))
        | if .a == 0 then null else {x: (.x / (3 * .a)), y: (.y / (3 * .a))} end
      end;
  def pip_ring($pt; $ring):
    ($ring | length) as $n
    | if $n < 3 then false
      else (reduce range(0; $n) as $i (0;
          (($i - 1 + $n) % $n) as $j
          | ($ring[$i][0]) as $xi | ($ring[$i][1]) as $yi
          | ($ring[$j][0]) as $xj | ($ring[$j][1]) as $yj
          | if ((($yi > $pt[1]) != ($yj > $pt[1]))
                and ($pt[0] < ($xj - $xi) * ($pt[1] - $yi) / ($yj - $yi) + $xi))
            then . + 1 else . end)) % 2 == 1
      end;
  def pip_poly($pt; $poly):
    (pip_ring($pt; $poly[0])) and (([$poly[1:][] | pip_ring($pt; .)] | any) | not);
  def inside($pt; $polys): ([$polys[] | select(pip_poly($pt; .))] | length) > 0;
  def geom_polys($g):
    if $g.type == "Polygon" then [$g.coordinates]
    elif $g.type == "MultiPolygon" then $g.coordinates
    else [] end;
  def interior($polys):
    ([ $polys[] | {c: ring_centroid(.[0]), a: ring_area(.[0])} ] | sort_by(-.a)) as $cs
    | (first($cs[] | select(.c != null) | .c as $c | select(inside([$c.x, $c.y]; $polys)) | [$c.x, $c.y]) // null) as $hit
    | if $hit != null then {pt: $hit, tier: "centroid"}
      else
        ($polys | max_by(ring_area(.[0]))) as $big
        | ($big[0]) as $outer
        | ([$outer[][0]] | min) as $x0 | ([$outer[][1]] | min) as $y0
        | ([$outer[][0]] | max) as $x1 | ([$outer[][1]] | max) as $y1
        | (first(range(1; $grid + 1) as $i
                 | range(1; $grid + 1) as $j
                 | [($x0 + ($x1 - $x0) * $i / ($grid + 1)), ($y0 + ($y1 - $y0) * $j / ($grid + 1))]
                 | select(inside(.; $polys))) // null) as $g
        | if $g != null then {pt: $g, tier: "grid"} else {pt: $outer[0], tier: "vertex"} end
      end;
  [inputs] | to_entries[]
  | .key as $k
  | .value as $f
  | (($f.geometry // {}) | geom_polys(.)) as $ps
  | select(($ps | length) > 0)
  | (interior($ps)) as $ip
  | ($ps | map(ring_area(.[0])) | add) as $deg2
  | (((($deg2 * 111.0 * 110.6) * 1000) | round) / 1000) as $area_km2
  | {
      type: "Feature",
      geometry: {type: "Point", coordinates: $ip.pt},
      properties: ((($f.properties // {}) | del(.in_water)) + {
        island_anchor: true,
        island_area_km2: $area_km2,
        _anchor_tier: $ip.tier
      })
    }
' "${islands}" > "${anchors_raw}" \
  || die "${HUAVD_EXIT_ERROR}" "island anchor derivation failed"

jq --seq -n -c 'inputs | del(.properties._anchor_tier)' "${anchors_raw}" > "${anchors_out}" \
  || die "${HUAVD_EXIT_ERROR}" "island anchor cleanup failed"

cat "${islands}" "${anchors_out}" > "${tmp}"
mv "${tmp}" "${islands}"

jq --seq -n -c \
  --arg region "${REGION}" \
  --argjson grid "${GRID_DIVISIONS}" \
  --argjson poly_count "${poly_count}" \
  --argjson point_before "${point_count_before}" '
  [inputs] as $A
  | ($A | map(select(.properties._anchor_tier == "centroid")) | length) as $tc
  | ($A | map(select(.properties._anchor_tier == "grid")) | length) as $tg
  | ($A | map(select(.properties._anchor_tier == "vertex")) | length) as $tv
  | {
      schema_version: 1,
      region: $region,
      layer: "island",
      thresholds: {grid_divisions: $grid},
      summary: {
        polygon_count: $poly_count,
        anchor_count: ($A | length),
        point_feature_count_before: $point_before,
        tier: {centroid: $tc, grid: $tg, vertex: $tv}
      },
      checks: {anchor_count_equals_polygon_count: (($A | length) == $poly_count)}
    }
' "${anchors_raw}" | tail -c +2 > "${report}" \
  || die "${HUAVD_EXIT_ERROR}" "island anchor report failed"

anchor_count="$(jq -r '.summary.anchor_count' "${report}")"
log_info "island-anchor OK: anchors=${anchor_count} tier=$(jq -c '.summary.tier' "${report}") report=${report}"
