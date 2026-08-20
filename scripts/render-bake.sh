#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/pmtiles.sh
source "${SCRIPT_DIR}/lib/pmtiles.sh"

BASE_PMTILES=""
BAKE_BBOX="${BAKE_BBOX:-}"
BAKE_MIN_ZOOM="${BAKE_MIN_ZOOM:-}"
BAKE_MAX_ZOOM="${BAKE_MAX_ZOOM:-}"
FORCE=0
RENDER_ONE=0

usage() {
  printf 'usage: %s --region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--base-pmtiles=<path>] [--bbox=w,s,e,n] [--min-zoom=Z] [--max-zoom=Z] [--force]\n' "$0"
}

PMTILES_SERVE_PID=""

cleanup_render_bake() {
  if [[ -n "${PMTILES_SERVE_PID}" ]] && kill -0 "${PMTILES_SERVE_PID}" >/dev/null 2>&1; then
    kill "${PMTILES_SERVE_PID}" >/dev/null 2>&1 || true
    wait "${PMTILES_SERVE_PID}" >/dev/null 2>&1 || true
  fi
}

pick_local_port() {
  python3 - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("127.0.0.1", 0))
    print(s.getsockname()[1])
PY
}

wait_for_local_port() {
  local port="$1" pid="$2" log_file="$3"
  local attempt
  for attempt in $(seq 1 50); do
    if python3 - "${port}" <<'PY' >/dev/null 2>&1
import socket
import sys

port = int(sys.argv[1])
with socket.create_connection(("127.0.0.1", port), timeout=0.2):
    pass
PY
    then
      return 0
    fi
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
      tail -n 20 "${log_file}" >&2 2>/dev/null || true
      return 1
    fi
    sleep 0.1
  done
  tail -n 20 "${log_file}" >&2 2>/dev/null || true
  return 1
}

render_one_tile() {
  local z="$1" x="$2" y="$3" lng="$4" lat="$5"
  local png="${BAKE_PNG_DIR}/${z}/${x}/${y}.png"
  local webp="${BAKE_WEBP_DIR}/${z}/${x}/${y}.webp"
  ensure_dir "$(dirname -- "${png}")"
  ensure_dir "$(dirname -- "${webp}")"

  if [[ "${BAKE_SKIP_EXISTING}" == "1" && -s "${webp}" ]]; then
    return 0
  fi

  if [[ "${BAKE_SKIP_EXISTING}" != "1" || ! -s "${png}" ]]; then
    rm -f "${png}"
    if [[ -n "${MBGL_RENDER_TILE_COMMAND:-}" ]]; then
      local command="${MBGL_RENDER_TILE_COMMAND}"
      command="${command//\{style\}/${BAKE_STYLE}}"
      command="${command//\{z\}/${z}}"
      command="${command//\{x\}/${x}}"
      command="${command//\{y\}/${y}}"
      command="${command//\{lng\}/${lng}}"
      command="${command//\{lat\}/${lat}}"
      command="${command//\{tile_size\}/${BAKE_TILE_SIZE}}"
      command="${command//\{png\}/${png}}"
      bash -c "${command}"
    elif [[ "${MBGL_RENDER_ENGINE}" == "maplibre-native" ]]; then
      "${MBGL_RENDER_BIN}" \
        --style "${BAKE_STYLE}" \
        --zoom "${z}" \
        --center "${lng},${lat}" \
        --width "${BAKE_TILE_SIZE}" \
        --height "${BAKE_TILE_SIZE}" \
        --output "${png}"
    else
      "${MBGL_RENDER_BIN}" \
        "${BAKE_STYLE}" \
        "${png}" \
        "${BAKE_TILE_SIZE}" \
        "${BAKE_TILE_SIZE}" \
        -c "${lng},${lat}" \
        -z "${z}"
    fi
  fi

  [[ -s "${png}" ]] \
    || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "renderer did not create PNG tile: ${png} (z=${z} x=${x} y=${y}, style=${BAKE_STYLE})"

  local cwebp_args=()
  if [[ "${BAKE_WEBP_LOSSLESS}" == "1" ]]; then
    cwebp_args+=("-lossless")
  fi
  cwebp_args+=("-m" "${BAKE_WEBP_METHOD}" "-metadata" "${BAKE_WEBP_METADATA}")
  cwebp "${cwebp_args[@]}" "${png}" -o "${webp}" >/dev/null \
    || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "cwebp failed for PNG tile: ${png}"
}

for arg in "$@"; do
  if [[ "${arg}" == "--render-one" ]]; then
    RENDER_ONE=1
    continue
  fi
  if (( RENDER_ONE )); then
    continue
  fi
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --base-pmtiles=*) BASE_PMTILES="${arg#*=}" ;;
    --bbox=*) BAKE_BBOX="${arg#*=}" ;;
    --min-zoom=*) BAKE_MIN_ZOOM="${arg#*=}" ;;
    --max-zoom=*) BAKE_MAX_ZOOM="${arg#*=}" ;;
    --force) FORCE=1 ;;
    -h|--help)
      usage
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

if (( RENDER_ONE )); then
  shift
  render_one_tile "$@"
  exit 0
fi

ROLE="raster_bake"
require_cmd jq pmtiles cwebp python3 xargs
require_region "${REGION}"
normalize_session_vars

MBGL_RENDER_ENGINE="${MBGL_RENDER_ENGINE:-mbgl-renderer}"
case "${MBGL_RENDER_ENGINE}" in
  mbgl-renderer|maplibre-native) ;;
  *) die "${HUAVD_EXIT_INPUT}" "invalid MBGL_RENDER_ENGINE=${MBGL_RENDER_ENGINE}; expected mbgl-renderer or maplibre-native" ;;
esac
MBGL_RENDER_BIN="${MBGL_RENDER:-mbgl-render}"
if [[ -z "${MBGL_RENDER_TILE_COMMAND:-}" ]]; then
  require_cmd "${MBGL_RENDER_BIN}"
fi

BASE_PMTILES="${BASE_PMTILES:-$(build_pmtiles_path base)}"
BASE_PMTILES="$(resolve_workspace_path "${BASE_PMTILES}")"
require_file "${BASE_PMTILES}"

base_tile_type="$(pmtiles_tile_type "${BASE_PMTILES}")"
[[ "${base_tile_type}" == "1" ]] \
  || die "${HUAVD_EXIT_VERIFY}" "base PMTiles must be MVT tile_type=1, got ${base_tile_type}"

if [[ ! -f "$(bake_render_style_path)" || "${SCRIPT_DIR}/style.sh" -nt "$(bake_render_style_path)" || "${CONFIG_DIR}/styles.yaml" -nt "$(bake_render_style_path)" ]]; then
  "${SCRIPT_DIR}/style.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
fi
require_file "$(bake_render_style_path)"

bake_config="$(bake_json)"
bake_defaults="$(jq -c '.defaults.raster_bake' "${bake_config}")"
tile_size="$(jq -r '.tile_size // 256' <<< "${bake_defaults}")"
min_zoom="${BAKE_MIN_ZOOM:-$(jq -r '.min_zoom // 0' <<< "${bake_defaults}")}"
max_zoom="${BAKE_MAX_ZOOM:-$(jq -r '.max_zoom // 14' <<< "${bake_defaults}")}"
parallel_jobs="${BAKE_JOBS:-$(jq -r '.parallel_jobs // 8' <<< "${bake_defaults}")}"
skip_existing="$(jq -r '.skip_existing // true' <<< "${bake_defaults}")"
png_retention="$(jq -r '.png_cache_retention // 0' <<< "${bake_defaults}")"
webp_lossless="$(jq -r '.cwebp.lossless // true' <<< "${bake_defaults}")"
webp_method="$(jq -r '.cwebp.method // 6' <<< "${bake_defaults}")"
webp_metadata="$(jq -r '.cwebp.metadata // "none"' <<< "${bake_defaults}")"

[[ "${min_zoom}" =~ ^[0-9]+$ && "${max_zoom}" =~ ^[0-9]+$ && "${tile_size}" =~ ^[0-9]+$ ]] \
  || die "${HUAVD_EXIT_INPUT}" "bake zooms and tile_size must be integers"
(( min_zoom <= max_zoom )) || die "${HUAVD_EXIT_INPUT}" "bake min_zoom must be <= max_zoom"
(( parallel_jobs > 0 )) || die "${HUAVD_EXIT_INPUT}" "BAKE_JOBS must be > 0"

case "${skip_existing}" in true) skip_existing=1 ;; false) skip_existing=0 ;; 1|0) ;; *) skip_existing=1 ;; esac
case "${webp_lossless}" in true) webp_lossless=1 ;; false) webp_lossless=0 ;; 1|0) ;; *) webp_lossless=1 ;; esac

output="$(build_pmtiles_path raster_bake)"
if [[ -e "${output}" && "${FORCE}" != "1" ]]; then
  die "${HUAVD_EXIT_ERROR}" "output already exists: ${output}; pass --force"
fi

bake_dir="$(bake_cache_dir)"
bake_runtime_style="${bake_dir}/style-render-runtime.json"
tile_list="${bake_dir}/tiles.tsv"
png_dir="${bake_dir}/png"
webp_dir="${bake_dir}/webp"
mbtiles="${bake_dir}/raster_bake.mbtiles"
ensure_dir "${bake_dir}" "${png_dir}" "${webp_dir}" "$(outputs_dir)"

runtime_source_url="pmtiles://${BASE_PMTILES}"
runtime_tile_url=""
if [[ -z "${MBGL_RENDER_TILE_COMMAND:-}" && "${MBGL_RENDER_ENGINE}" == "mbgl-renderer" ]]; then
  trap cleanup_render_bake EXIT
  pmtiles_serve_dir="$(dirname -- "${BASE_PMTILES}")"
  pmtiles_archive="$(basename -- "${BASE_PMTILES}")"
  pmtiles_archive="${pmtiles_archive%.pmtiles}"
  pmtiles_serve_port="${BAKE_PMTILES_SERVE_PORT:-$(pick_local_port)}"
  pmtiles_serve_log="${bake_dir}/pmtiles-serve.log"
  pmtiles serve "${pmtiles_serve_dir}" --interface=127.0.0.1 --port="${pmtiles_serve_port}" > "${pmtiles_serve_log}" 2>&1 &
  PMTILES_SERVE_PID="$!"
  wait_for_local_port "${pmtiles_serve_port}" "${PMTILES_SERVE_PID}" "${pmtiles_serve_log}" \
    || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "pmtiles serve failed to start; see ${pmtiles_serve_log}"
  runtime_tile_url="http://127.0.0.1:${pmtiles_serve_port}/${pmtiles_archive}/{z}/{x}/{y}.mvt"
  log_info "pmtiles serve OK: ${pmtiles_serve_dir} on 127.0.0.1:${pmtiles_serve_port}"
fi

jq --arg base_url "${runtime_source_url}" --arg tile_url "${runtime_tile_url}" '
  .sources |= with_entries(
    if .value.type == "vector" then
      if $tile_url == "" then
        .value |= (.url = $base_url)
      else
        .value |= (del(.url) + {tiles: [$tile_url]})
      end
    else
      .
    end
  )
' "$(bake_render_style_path)" > "${bake_runtime_style}"

bounds="${BAKE_BBOX:-$(pmtiles_bounds "${BASE_PMTILES}" | jq -r '@csv' | tr -d '"')}"

python3 - "${bounds}" "${min_zoom}" "${max_zoom}" "${tile_list}" <<'PY'
import math
import sys

bounds = [float(part) for part in sys.argv[1].split(",")]
min_zoom = int(sys.argv[2])
max_zoom = int(sys.argv[3])
out = sys.argv[4]
west, south, east, north = bounds

def lon_to_x(lon, z):
    return int(math.floor((lon + 180.0) / 360.0 * (1 << z)))

def lat_to_y(lat, z):
    lat = max(min(lat, 85.05112878), -85.05112878)
    rad = math.radians(lat)
    return int(math.floor((1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * (1 << z)))

def tile_center(x, y, z):
    n = 1 << z
    lon = (x + 0.5) / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 0.5) / n)))
    lat = math.degrees(lat_rad)
    return lon, lat

with open(out, "w", encoding="utf-8") as f:
    for z in range(min_zoom, max_zoom + 1):
        max_index = (1 << z) - 1
        xmin = max(0, min(max_index, lon_to_x(west, z)))
        xmax = max(0, min(max_index, lon_to_x(east, z)))
        ymin = max(0, min(max_index, lat_to_y(north, z)))
        ymax = max(0, min(max_index, lat_to_y(south, z)))
        for x in range(min(xmin, xmax), max(xmin, xmax) + 1):
            for y in range(min(ymin, ymax), max(ymin, ymax) + 1):
                lon, lat = tile_center(x, y, z)
                f.write(f"{z}\t{x}\t{y}\t{lon:.8f}\t{lat:.8f}\n")
PY

tile_count="$(wc -l < "${tile_list}" | tr -d '[:space:]')"
(( tile_count > 0 )) || die "${HUAVD_EXIT_INPUT}" "bake tile list is empty for bounds=${bounds}"
log_info "raster bake tiles=${tile_count} zoom=${min_zoom}-${max_zoom} bounds=${bounds}"

export BAKE_STYLE="${bake_runtime_style}"
export BAKE_PNG_DIR="${png_dir}"
export BAKE_WEBP_DIR="${webp_dir}"
export BAKE_TILE_SIZE="${tile_size}"
export BAKE_SKIP_EXISTING="${skip_existing}"
export BAKE_WEBP_LOSSLESS="${webp_lossless}"
export BAKE_WEBP_METHOD="${webp_method}"
export BAKE_WEBP_METADATA="${webp_metadata}"
export MBGL_RENDER_ENGINE
export MBGL_RENDER_BIN
export MBGL_RENDER_TILE_COMMAND="${MBGL_RENDER_TILE_COMMAND:-}"

read -r preflight_z preflight_x preflight_y preflight_lng preflight_lat < "${tile_list}"
log_info "raster bake renderer preflight z=${preflight_z} x=${preflight_x} y=${preflight_y}"
render_one_tile "${preflight_z}" "${preflight_x}" "${preflight_y}" "${preflight_lng}" "${preflight_lat}"

xargs -P "${parallel_jobs}" -n 5 "${BASH}" "$0" --render-one < "${tile_list}"

python3 - "${webp_dir}" "${mbtiles}" "$(artifact_stem raster_bake)" "${bounds}" "${min_zoom}" "${max_zoom}" <<'PY'
import os
import sqlite3
import sys

webp_dir, mbtiles, name, bounds, min_zoom, max_zoom = sys.argv[1:]
if os.path.exists(mbtiles):
    os.remove(mbtiles)
conn = sqlite3.connect(mbtiles)
try:
    conn.execute("create table metadata (name text, value text)")
    conn.execute("create table tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)")
    metadata = {
        "name": name,
        "format": "webp",
        "bounds": bounds,
        "minzoom": min_zoom,
        "maxzoom": max_zoom,
        "type": "baselayer",
        "version": "1",
        "description": "HUAVD raster baked non-label base map",
        "attribution": "© OpenStreetMap contributors",
    }
    conn.executemany("insert into metadata(name, value) values (?, ?)", metadata.items())
    for root, _dirs, files in os.walk(webp_dir):
        for file_name in files:
            if not file_name.endswith(".webp"):
                continue
            path = os.path.join(root, file_name)
            rel = os.path.relpath(path, webp_dir)
            parts = rel.split(os.sep)
            if len(parts) != 3:
                continue
            z = int(parts[0])
            x = int(parts[1])
            y = int(parts[2][:-5])
            tile_row = (1 << z) - 1 - y
            with open(path, "rb") as f:
                data = f.read()
            conn.execute(
                "insert into tiles(zoom_level, tile_column, tile_row, tile_data) values (?, ?, ?, ?)",
                (z, x, tile_row, data),
            )
    conn.execute("create unique index tile_index on tiles (zoom_level, tile_column, tile_row)")
    conn.commit()
finally:
    conn.close()
PY

rm -f "${output}" "${output}.sha512"
pmtiles convert "${mbtiles}" "${output}" \
  || die "${HUAVD_EXIT_ERROR}" "pmtiles convert failed: ${mbtiles}"

"${SCRIPT_DIR}/metadata.sh" --pmtiles="${output}" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"
"${SCRIPT_DIR}/manifest.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"
"${SCRIPT_DIR}/attribution.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"
write_sha512_file "${output}"
"${SCRIPT_DIR}/verify.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"

if [[ "${png_retention}" == "0" ]]; then
  rm -rf "${png_dir}"
fi

printf 'raster bake OK: %s\n' "${output}"
