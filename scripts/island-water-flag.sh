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

require_cmd jq awk sha512sum
require_region "${REGION}"
normalize_session_vars

islands="$(layers_dir)/island.geojsonseq"
waters="$(layers_dir)/water.geojsonseq"
require_file "${islands}"
require_file "${waters}"

cache_dir="$(island_water_cache_dir)"
ensure_dir "${cache_dir}"
report="$(island_water_report_path)"
island_index="${cache_dir}/islands.tsv"
island_bbox_json="${cache_dir}/islands.bbox.json"
flag_tsv="${cache_dir}/in-water-flags.tsv"
tmp="${islands}.island-water.tmp"

SAMPLE_POINTS=120
MIN_INSIDE_RATIO=0.999
MAX_IN_WATER_AREA_KM2=1.0

island_feature_count="$(tr '\036' '\n' < "${islands}" | sed '/^$/d' | wc -l | tr -d ' ')"
water_feature_count="$(tr '\036' '\n' < "${waters}" | sed '/^$/d' | wc -l | tr -d ' ')"
water_sha512="$(sha512sum "${waters}" | awk '{print $1}')"

log_info "index island geometries -> ${island_index}"
jq --seq -n -r --argjson max "${SAMPLE_POINTS}" '
  def fabs: if . < 0 then -. else . end;
  def ring_area($r):
    ($r | length) as $n
    | if $n < 3 then 0
      else (([range(0; $n) | ($r[.][0] * $r[(. + 1) % $n][1]) - ($r[(. + 1) % $n][0] * $r[.][1])] | add) | fabs) / 2
      end;
  def polys:
    if .type == "Polygon" then [.coordinates]
    elif .type == "MultiPolygon" then .coordinates
    else [] end;
  def bbox_of($ps):
    ([$ps[][][][0]] | min) as $x0 | ([$ps[][][][1]] | min) as $y0
    | ([$ps[][][][0]] | max) as $x1 | ([$ps[][][][1]] | max) as $y1
    | [$x0, $y0, $x1, $y1];
  def sample($ring; $max):
    ($ring | length) as $n
    | (($n / $max) | ceil | if . < 1 then 1 else . end) as $step
    | [range(0; $n; $step) | $ring[.]] | .[0:$max];
  [inputs] | to_entries[]
  | .key as $i
  | (.value.geometry // {}) as $g
  | ($g | polys) as $ps
  | select(($ps | length) > 0)
  | ($ps | map(ring_area(.[0])) | add) as $area
  | (bbox_of($ps)) as $bb
  | ([ $ps[] | .[0][] ]) as $verts
  | (sample($verts; $max)) as $sp
  | "I\t\($i)\t\($bb[0])\t\($bb[1])\t\($bb[2])\t\($bb[3])\t\($area)\t\($sp | map("\(.[0]),\(.[1])") | join(" "))"
' "${islands}" | tr -d '\036' > "${island_index}" \
  || die "${HUAVD_EXIT_ERROR}" "island geometry index failed"

if [[ ! -s "${island_index}" ]]; then
  log_warn "island layer has no polygon feature; nothing to flag"
  : > "${flag_tsv}"
  jq -n \
    --arg region "${REGION}" \
    --argjson island_feature_count "${island_feature_count}" \
    --argjson water_feature_count "${water_feature_count}" \
    --arg water_sha512 "${water_sha512}" \
    --argjson sample "${SAMPLE_POINTS}" \
    --argjson ratio "${MIN_INSIDE_RATIO}" \
    --argjson max_area "${MAX_IN_WATER_AREA_KM2}" \
    '{schema_version:1,region:$region,layer:"island",
      thresholds:{sample_points:$sample,min_inside_ratio:$ratio,max_in_water_area_km2:$max_area},
      inputs:{island_feature_count:$island_feature_count,island_polygon_count:0,water_feature_count:$water_feature_count},
      summary:{in_water_count:0,max_in_water_area_km2:0,water_geojsonseq_sha512:$water_sha512},
      flagged:[],
      checks:{max_in_water_area_within_limit:true}}' > "${report}"
  log_info "island-water-flag: no polygon island; report=${report}"
  exit 0
fi

jq -R -s '
  split("\n") | map(select(length > 0) | split("\t"))
  | map({i:(.[1] | tonumber), bb:[(.[2] | tonumber), (.[3] | tonumber), (.[4] | tonumber), (.[5] | tonumber)], area:(.[6] | tonumber)})
' "${island_index}" > "${island_bbox_json}" \
  || die "${HUAVD_EXIT_ERROR}" "island bbox index failed"

log_info "flag islands enclosed by water polygons"
awk_program=$(cat <<'AWK'
BEGIN {
  FS = "\t"
  OFS = "\t"
  active = 0
  wid = ""
  nring = 0
  npart = 0
  nflag = 0
  ratio = (ratio == "" ? 0.999 : ratio + 0)
}

FNR == NR {
  if ($1 != "I") next
  i = $2 + 0
  IA[i] = $7 + 0
  n = split($8, pts, " ")
  NS[i] = n
  for (k = 1; k <= n; k++) {
    m = split(pts[k], xy, ",")
    SX[i, k] = xy[1] + 0
    SY[i, k] = xy[2] + 0
  }
  next
}

$1 == "W" {
  flush_water()
  wid = $2 + 0
  NCAND = ($3 == "" ? 0 : split($3, cl, ","))
  for (k = 1; k <= NCAND; k++) CAND[k] = cl[k] + 0
  nring = 0
  npart = 0
  active = 1
  next
}

$1 == "P" {
  if (!active) next
  p = $3 + 0
  r = $4 + 0
  if (p != curp || r != curr) {
    nring++
    curp = p
    curr = r
    RINGP[nring] = p
    RINGR[nring] = r
    RN[nring] = 0
    if (p + 1 > npart) npart = p + 1
  }
  n = ++RN[nring]
  RX[nring, n] = $5 + 0
  RY[nring, n] = $6 + 0
  next
}

END { flush_water() }

function pip_ring(px, py, ci,   k, n, j, xi, yi, xj, yj, inside) {
  n = RN[ci]
  if (n < 3) return 0
  inside = 0
  j = n
  for (k = 1; k <= n; k++) {
    xi = RX[ci, k]; yi = RY[ci, k]
    xj = RX[ci, j]; yj = RY[ci, j]
    if (((yi > py) != (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi)) inside = !inside
    j = k
  }
  return inside
}

function pip_water(px, py,   part, ci, hit, ok) {
  for (part = 0; part < npart; part++) {
    hit = 0
    for (ci = 1; ci <= nring; ci++) {
      if (RINGP[ci] != part) continue
      if (RINGR[ci] == 0 && pip_ring(px, py, ci)) { hit = 1; break }
    }
    if (!hit) continue
    ok = 1
    for (ci = 1; ci <= nring; ci++) {
      if (RINGP[ci] != part) continue
      if (RINGR[ci] > 0 && pip_ring(px, py, ci)) { ok = 0; break }
    }
    if (ok) return 1
  }
  return 0
}

function flush_water(   k, m, i, ns, pass, r) {
  if (!active) return
  active = 0
  for (k = 1; k <= NCAND; k++) {
    i = CAND[k]
    if (DONE[i]) continue
    ns = NS[i]
    if (ns <= 0) continue
    pass = 0
    for (m = 1; m <= ns; m++) {
      if (pip_water(SX[i, m], SY[i, m])) pass++
    }
    r = pass / ns
    if (r > BEST[i]) BEST[i] = r
    if (r >= ratio) {
      DONE[i] = 1
      nflag++
      printf "%d\t%.10f\t%.6f\t%d\n", i, IA[i], r, wid > flag_out
    }
  }
  delete CAND
  NCAND = 0
  delete RINGP
  delete RINGR
  delete RN
  delete RX
  delete RY
  nring = 0
  npart = 0
}
AWK
)

jq --seq -n -r --slurpfile islands "${island_bbox_json}" '
  def fabs: if . < 0 then -. else . end;
  def ring_area($r):
    ($r | length) as $n
    | if $n < 3 then 0
      else (([range(0; $n) | ($r[.][0] * $r[(. + 1) % $n][1]) - ($r[(. + 1) % $n][0] * $r[.][1])] | add) | fabs) / 2
      end;
  ($islands[0] // []) as $IS
  | foreach inputs as $f (0; . + 1; {i: (. - 1), f: $f})
  | (.f.geometry // {}) as $g
  | (if $g.type == "Polygon" then [$g.coordinates]
     elif $g.type == "MultiPolygon" then $g.coordinates
     else [] end) as $ps
  | select(($ps | length) > 0)
  | ([$ps[][][][0]] | min) as $x0
  | ([$ps[][][][1]] | min) as $y0
  | ([$ps[][][][0]] | max) as $x1
  | ([$ps[][][][1]] | max) as $y1
  | ($ps | map(ring_area(.[0])) | add) as $warea
  | ([ $IS[] | select(.area <= $warea
                      and .bb[0] >= $x0 and .bb[1] >= $y0
                      and .bb[2] <= $x1 and .bb[3] <= $y1) | .i ]) as $cand
  | select(($cand | length) > 0)
  | .i as $wi
  | "W\t\($wi)\t\($cand | join(","))",
    ([ range(0; ($ps | length)) as $p
       | range(0; ($ps[$p] | length)) as $r
       | $ps[$p][$r][] as $pt
       | "P\t\($wi)\t\($p)\t\($r)\t\($pt[0])\t\($pt[1])" ] | .[])
' "${waters}" | tr -d '\036' | awk -v flag_out="${flag_tsv}" -v ratio="${MIN_INSIDE_RATIO}" "${awk_program}" "${island_index}" - \
  || die "${HUAVD_EXIT_ERROR}" "island/water containment test failed"

FLAGGED_JSON="$(jq -R -s 'split("\n") | map(select(length > 0) | split("\t")[0] | tonumber)' "${flag_tsv}")"

log_info "write in_water flag into ${islands}"
jq --seq -n -c --argjson flagged "${FLAGGED_JSON}" '
  [inputs] | to_entries[]
  | (.key as $k
     | if ($flagged | index($k)) != null then (.value | .properties.in_water = true) else .value end)
' "${islands}" > "${tmp}" \
  || die "${HUAVD_EXIT_ERROR}" "island in_water write-back failed"
mv "${tmp}" "${islands}"

jq --seq -n -c \
  --rawfile flags "${flag_tsv}" \
  --arg region "${REGION}" \
  --argjson island_feature_count "${island_feature_count}" \
  --argjson water_feature_count "${water_feature_count}" \
  --arg water_sha512 "${water_sha512}" \
  --argjson sample "${SAMPLE_POINTS}" \
  --argjson ratio "${MIN_INSIDE_RATIO}" \
  --argjson max_area "${MAX_IN_WATER_AREA_KM2}" '
  def km2($deg2): (((($deg2 * 111.0 * 110.6) * 1000) | round) / 1000);
  ($flags
   | split("\n") | map(select(length > 0) | split("\t"))
   | map({index:(.[0] | tonumber), area_deg2:(.[1] | tonumber), inside_ratio:(.[2] | tonumber), water_index:(.[3] | tonumber)})) as $F
  | [inputs] as $all
  | ($all | map(select((.geometry.type // "") == "Polygon" or (.geometry.type // "") == "MultiPolygon")) | length) as $polyCount
  | ($F | map(. + {
      name: ($all[.index].properties.name // null),
      name_zh_hans: ($all[.index].properties["name:zh-Hans"] // null),
      area_km2: km2(.area_deg2)
    })) as $flagged
  | ($flagged | map(.area_km2) | max // 0) as $maxArea
  | {
      schema_version: 1,
      region: $region,
      layer: "island",
      thresholds: {sample_points: $sample, min_inside_ratio: $ratio, max_in_water_area_km2: $max_area},
      inputs: {
        island_feature_count: $island_feature_count,
        island_polygon_count: $polyCount,
        water_feature_count: $water_feature_count
      },
      summary: {
        in_water_count: ($flagged | length),
        max_in_water_area_km2: $maxArea,
        water_geojsonseq_sha512: $water_sha512
      },
      flagged: $flagged,
      checks: {max_in_water_area_within_limit: ($maxArea <= $max_area)}
    }
' "${islands}" | tail -c +2 > "${report}" \
  || die "${HUAVD_EXIT_ERROR}" "island-water report failed"

flagged_count="$(jq -r '.summary.in_water_count' "${report}")"
log_info "island-water-flag OK: in_water=${flagged_count} report=${report}"
