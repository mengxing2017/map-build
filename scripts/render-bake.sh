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
  local render_log="${png}.render.log"
  ensure_dir "$(dirname -- "${png}")"
  ensure_dir "$(dirname -- "${webp}")"

  if [[ "${BAKE_SKIP_EXISTING}" == "1" && -s "${webp}" ]]; then
    return 0
  fi

  if [[ "${BAKE_SKIP_EXISTING}" != "1" || ! -s "${png}" ]]; then
    rm -f "${png}" "${render_log}"
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
      if ! bash -c "${command}" >"${render_log}" 2>&1; then
        tail -n 40 "${render_log}" >&2 || true
        die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "renderer failed for PNG tile: ${png} (z=${z} x=${x} y=${y}; log=${render_log})"
      fi
    elif [[ "${MBGL_RENDER_ENGINE}" == "maplibre-native" ]]; then
      if ! "${MBGL_RENDER_BIN}" \
        --style "${BAKE_STYLE}" \
        --zoom "${z}" \
        --center "${lng},${lat}" \
        --width "${BAKE_TILE_SIZE}" \
        --height "${BAKE_TILE_SIZE}" \
        --output "${png}" >"${render_log}" 2>&1
      then
        tail -n 40 "${render_log}" >&2 || true
        die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "renderer failed for PNG tile: ${png} (z=${z} x=${x} y=${y}; log=${render_log})"
      fi
    else
      if ! "${MBGL_RENDER_BIN}" \
        "${BAKE_STYLE}" \
        "${png}" \
        "${BAKE_TILE_SIZE}" \
        "${BAKE_TILE_SIZE}" \
        -c "${lng},${lat}" \
        -z "${z}" >"${render_log}" 2>&1
      then
        tail -n 40 "${render_log}" >&2 || true
        die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "renderer failed for PNG tile: ${png} (z=${z} x=${x} y=${y}; log=${render_log})"
      fi
    fi

    if grep -Eqi 'Error parsing style|data expressions not supported' "${render_log}"; then
      tail -n 40 "${render_log}" >&2 || true
      die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "renderer rejected the bake style for PNG tile: ${png} (z=${z} x=${x} y=${y}; log=${render_log}); use a renderer compatible with MapLibre style-spec data expressions"
    fi
    rm -f "${render_log}"
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

write_missing_tiles() {
  local input_list="$1" missing_list="$2"
  python3 - "${input_list}" "${BAKE_WEBP_DIR}" "${missing_list}" <<'PY'
import os
import sys

tile_list, webp_dir, missing_list = sys.argv[1:]
missing = 0
with open(tile_list, "r", encoding="utf-8") as src, open(missing_list, "w", encoding="utf-8") as dst:
    for line in src:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 5:
            continue
        z, x, y = parts[:3]
        webp = os.path.join(webp_dir, z, x, f"{y}.webp")
        if not os.path.exists(webp) or os.path.getsize(webp) == 0:
            dst.write(line)
            missing += 1
print(missing)
PY
}

render_tile_list() {
  local input_list="$1"
  xargs -P "${parallel_jobs}" -n 5 "${BASH}" "$0" --render-one < "${input_list}"
}

write_preflight_tiles() {
  local input_list="$1" output_list="$2"
  python3 - "${input_list}" "${output_list}" <<'PY'
import sys

input_list, output_list = sys.argv[1:]
by_zoom = {}
with open(input_list, "r", encoding="utf-8") as src:
    for line in src:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 5:
            continue
        by_zoom.setdefault(int(parts[0]), []).append(line)

zooms = sorted(by_zoom)
if not zooms:
    raise SystemExit("raster bake preflight has no candidate tiles")

selected_zooms = []
for zoom in (zooms[0], zooms[len(zooms) // 2], zooms[-1]):
    if zoom not in selected_zooms:
        selected_zooms.append(zoom)

with open(output_list, "w", encoding="utf-8") as dst:
    for zoom in selected_zooms:
        tiles = by_zoom[zoom]
        dst.write(tiles[len(tiles) // 2])
PY
}

validate_webp_tile() {
  local file="$1" expected_size="$2"
  python3 - "${file}" "${expected_size}" <<'PY'
import struct
import sys

path, expected_size = sys.argv[1], int(sys.argv[2])
data = open(path, "rb").read()
if len(data) < 16 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
    raise SystemExit(f"invalid WebP container: {path}")

offset = 12
width = height = None
while offset + 8 <= len(data):
    kind = data[offset:offset + 4]
    length = struct.unpack_from("<I", data, offset + 4)[0]
    payload = data[offset + 8:offset + 8 + length]
    if len(payload) != length:
        raise SystemExit(f"truncated WebP chunk: {path}")
    if kind == b"VP8 " and len(payload) >= 10 and payload[3:6] == b"\x9d\x01\x2a":
        width = struct.unpack_from("<H", payload, 6)[0] & 0x3fff
        height = struct.unpack_from("<H", payload, 8)[0] & 0x3fff
        break
    if kind == b"VP8L" and len(payload) >= 5 and payload[0] == 0x2f:
        bits = struct.unpack_from("<I", payload, 1)[0]
        width = (bits & 0x3fff) + 1
        height = ((bits >> 14) & 0x3fff) + 1
        break
    if kind == b"VP8X" and len(payload) >= 10:
        width = int.from_bytes(payload[4:7], "little") + 1
        height = int.from_bytes(payload[7:10], "little") + 1
        break
    offset += 8 + length + (length & 1)

if width is None or height is None:
    raise SystemExit(f"WebP dimensions are unreadable: {path}")
if width != expected_size or height != expected_size:
    raise SystemExit(f"unexpected WebP dimensions {width}x{height}, expected {expected_size}x{expected_size}: {path}")
PY
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
require_cmd jq pmtiles cwebp python3 sha512sum xargs
require_region "${REGION}"
normalize_session_vars
log_execution_context

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

managed_base_pmtiles="$(build_pmtiles_path base)"
[[ "${BASE_PMTILES}" == "${managed_base_pmtiles}" ]] \
  || die "${HUAVD_EXIT_INPUT}" "raster_bake only accepts the verified session base PMTiles: ${managed_base_pmtiles}"
require_file "$(build_manifest_path base)"
require_file "$(build_attribution_path base)"
require_file "$(build_sha512_path base)"
"${SCRIPT_DIR}/verify.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=base --workdir="${WORKDIR}"

base_tile_type="$(pmtiles_tile_type "${BASE_PMTILES}")"
[[ "${base_tile_type}" == "1" ]] \
  || die "${HUAVD_EXIT_VERIFY}" "base PMTiles must be MVT tile_type=1, got ${base_tile_type}"

if [[ ! -f "$(bake_render_style_path)" || "${SCRIPT_DIR}/style.sh" -nt "$(bake_render_style_path)" || "${CONFIG_DIR}/styles.yaml" -nt "$(bake_render_style_path)" || "$(bake_json)" -nt "$(bake_render_style_path)" ]]; then
  "${SCRIPT_DIR}/style.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
fi
require_file "$(bake_render_style_path)"
[[ -d "$(build_glyphs_dir)" ]] \
  || die "${HUAVD_EXIT_INPUT}" "raster_bake requires generated glyphs: $(build_glyphs_dir); run build with --glyph=1"
[[ -d "$(build_sprite_dir)" ]] \
  || die "${HUAVD_EXIT_INPUT}" "raster_bake requires generated sprite: $(build_sprite_dir); run build with --glyph=1"

bake_config="$(bake_json)"
bake_defaults="$(jq -c '.defaults.raster_bake' "${bake_config}")"
bake_overrides=()
while IFS=$'\t' read -r region_match override; do
  [[ -n "${region_match}" ]] || continue
  if [[ "${REGION}" == ${region_match} ]]; then
    bake_defaults="$(jq -cn --argjson defaults "${bake_defaults}" --argjson override "${override}" '$defaults + $override')"
    bake_overrides+=("${override}")
  fi
done < <(jq -r '.high_density[]? | [.region_match, (del(.region_match) | tojson)] | @tsv' "${bake_config}")
tile_size="$(jq -r '.tile_size // 256' <<< "${bake_defaults}")"
pixel_ratio="$(jq -r '.pixel_ratio // 1' <<< "${bake_defaults}")"
min_zoom="${BAKE_MIN_ZOOM:-$(jq -r '.min_zoom // 0' <<< "${bake_defaults}")}"
max_zoom="${BAKE_MAX_ZOOM:-$(jq -r '.max_zoom // 14' <<< "${bake_defaults}")}"
parallel_jobs="${BAKE_JOBS:-$(jq -r '.parallel_jobs // 8' <<< "${bake_defaults}")}"
bbox_padding_tiles="${BAKE_BBOX_PADDING_TILES:-$(jq -r '.bbox_padding_tiles // 0' <<< "${bake_defaults}")}"
bake_retries="${BAKE_RETRIES:-$(jq -r '.retries // 2' <<< "${bake_defaults}")}"
pmtiles_extract="${BAKE_PMTILES_EXTRACT:-$(jq -r '.pmtiles_extract // false' <<< "${bake_defaults}")}"
skip_existing="${BAKE_SKIP_EXISTING:-$(jq -r 'if has("skip_existing") and .skip_existing != null then .skip_existing else true end' <<< "${bake_defaults}")}"
png_retention="$(jq -r '.png_cache_retention // 0' <<< "${bake_defaults}")"
webp_lossless="${BAKE_WEBP_LOSSLESS:-$(jq -r 'if (.cwebp | has("lossless")) and .cwebp.lossless != null then .cwebp.lossless else true end' <<< "${bake_defaults}")}"
webp_method="$(jq -r '.cwebp.method // 6' <<< "${bake_defaults}")"
webp_metadata="$(jq -r '.cwebp.metadata // "none"' <<< "${bake_defaults}")"
encoding="$(jq -r '.encoding // "webp"' <<< "${bake_defaults}")"

[[ "${min_zoom}" =~ ^[0-9]+$ && "${max_zoom}" =~ ^[0-9]+$ && "${tile_size}" =~ ^[0-9]+$ ]] \
  || die "${HUAVD_EXIT_INPUT}" "bake zooms and tile_size must be integers"
[[ "${pixel_ratio}" == "1" ]] \
  || die "${HUAVD_EXIT_INPUT}" "raster bake pixel_ratio=${pixel_ratio} is unsupported; only 1 is supported"
[[ "${encoding}" == "webp" ]] \
  || die "${HUAVD_EXIT_INPUT}" "raster bake encoding=${encoding} is unsupported; only webp is supported"
[[ "${bbox_padding_tiles}" =~ ^[0-9]+$ && "${bake_retries}" =~ ^[0-9]+$ ]] \
  || die "${HUAVD_EXIT_INPUT}" "BAKE_BBOX_PADDING_TILES and BAKE_RETRIES must be non-negative integers"
(( min_zoom <= max_zoom )) || die "${HUAVD_EXIT_INPUT}" "bake min_zoom must be <= max_zoom"
(( parallel_jobs > 0 )) || die "${HUAVD_EXIT_INPUT}" "BAKE_JOBS must be > 0"

case "${skip_existing}" in true) skip_existing=1 ;; false) skip_existing=0 ;; 1|0) ;; *) die "${HUAVD_EXIT_INPUT}" "skip_existing must be true, false, 1, or 0" ;; esac
case "${webp_lossless}" in true) webp_lossless=1 ;; false) webp_lossless=0 ;; 1|0) ;; *) die "${HUAVD_EXIT_INPUT}" "cwebp.lossless must be true, false, 1, or 0" ;; esac
case "${pmtiles_extract}" in true) pmtiles_extract=1 ;; false) pmtiles_extract=0 ;; 1|0) ;; *) die "${HUAVD_EXIT_INPUT}" "pmtiles_extract must be true, false, 1, or 0" ;; esac

output="$(build_pmtiles_path raster_bake)"
if [[ -e "${output}" && "${FORCE}" != "1" ]]; then
  die "${HUAVD_EXIT_ERROR}" "output already exists: ${output}; pass --force"
fi

bake_dir="$(bake_cache_dir)"
bake_runtime_style="${bake_dir}/style-render-runtime.json"
tile_list="${bake_dir}/tiles.tsv"
preflight_list="${bake_dir}/preflight.tsv"
png_dir="${bake_dir}/png"
webp_dir="${bake_dir}/webp"
mbtiles="${bake_dir}/raster_bake.mbtiles"
ensure_dir "${bake_dir}" "${png_dir}" "${webp_dir}" "$(outputs_dir)"

bounds="${BAKE_BBOX:-$(pmtiles_bounds "${BASE_PMTILES}" | jq -r '@csv' | tr -d '"')}"
bake_overrides_json="$(jq -cn --args "${bake_overrides[@]}" '$ARGS.positional | map(fromjson)')"
jq -n \
  --arg commit "$(execution_revision)" \
  --arg worktree "$(execution_worktree_state)" \
  --arg workdir "${WORKDIR}" \
  --arg session "${SESSION}" \
  --arg base_pmtiles "${BASE_PMTILES}" \
  --arg bounds "${bounds}" \
  --argjson declared "$(jq -c '.defaults.raster_bake' "${bake_config}")" \
  --argjson high_density_overrides "${bake_overrides_json}" \
  --argjson resolved "${bake_defaults}" \
  --arg min_zoom "${min_zoom}" \
  --arg max_zoom "${max_zoom}" \
  --arg parallel_jobs "${parallel_jobs}" \
  --arg skip_existing "${skip_existing}" \
  --arg webp_lossless "${webp_lossless}" \
  --arg pmtiles_extract "${pmtiles_extract}" \
  '{
    schema: 1,
    execution: {commit: $commit, worktree: $worktree, workdir: $workdir, session: $session},
    base_pmtiles: $base_pmtiles,
    declared: $declared,
    high_density_overrides: $high_density_overrides,
    resolved_config: $resolved,
    environment_overrides: {
      BAKE_MIN_ZOOM: $ENV.BAKE_MIN_ZOOM,
      BAKE_MAX_ZOOM: $ENV.BAKE_MAX_ZOOM,
      BAKE_JOBS: $ENV.BAKE_JOBS,
      BAKE_SKIP_EXISTING: $ENV.BAKE_SKIP_EXISTING,
      BAKE_WEBP_LOSSLESS: $ENV.BAKE_WEBP_LOSSLESS
    },
    effective: {
      bounds: $bounds,
      min_zoom: ($min_zoom | tonumber),
      max_zoom: ($max_zoom | tonumber),
      parallel_jobs: ($parallel_jobs | tonumber),
      skip_existing: ($skip_existing == "1"),
      webp_lossless: ($webp_lossless == "1"),
      pmtiles_extract: ($pmtiles_extract == "1")
    }
  }' > "${bake_dir}/parameters.json"
write_sha512_file "${bake_dir}/parameters.json"
log_info "raster bake parameters: ${bake_dir}/parameters.json"

bake_inputs_file="${bake_dir}/inputs.sha512"
bake_inputs="$(
  sha512sum "${BASE_PMTILES}" "$(bake_render_style_path)" "${bake_config}"
  printf '%s\n' "${bounds:-}" "${min_zoom}" "${max_zoom}" "${tile_size}" "${pixel_ratio}" "${bbox_padding_tiles}" "${webp_lossless}" "${webp_method}" "${webp_metadata}"
  printf '%s\n' "${bake_defaults}"
  printf '%s\n' "${BAKE_BBOX:-}"
  printf '%s\n' "${MBGL_RENDER_ENGINE}" "${MBGL_RENDER_BIN}" "${MBGL_RENDER_TILE_COMMAND:-}"
)"
bake_inputs_digest="$(printf '%s' "${bake_inputs}" | sha512sum | awk '{print $1}')"
if [[ ! -f "${bake_inputs_file}" || "$(<"${bake_inputs_file}")" != "${bake_inputs_digest}" ]]; then
  rm -rf "${png_dir}" "${webp_dir}"
  rm -f "${mbtiles}" "${tile_list}"
  ensure_dir "${png_dir}" "${webp_dir}"
  printf '%s\n' "${bake_inputs_digest}" > "${bake_inputs_file}"
  log_info "raster bake cache invalidated: base, style, or bake configuration changed"
fi

runtime_source_url="pmtiles://${BASE_PMTILES}"
runtime_tile_url=""
if [[ -z "${MBGL_RENDER_TILE_COMMAND:-}" && "${MBGL_RENDER_ENGINE}" == "mbgl-renderer" ]]; then
  trap cleanup_render_bake EXIT
  serve_pmtiles="${BASE_PMTILES}"
  if (( pmtiles_extract )); then
    subset_pmtiles="${bake_dir}/base-bake-subset.pmtiles"
    rm -f "${subset_pmtiles}"
    pmtiles extract "${BASE_PMTILES}" "${subset_pmtiles}" --bbox="${bounds}" --minzoom="${min_zoom}" --maxzoom="${max_zoom}" \
      || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "pmtiles extract failed for raster bake subset"
    [[ "$(pmtiles_tile_type "${subset_pmtiles}")" == "1" ]] \
      || die "${HUAVD_EXIT_VERIFY}" "raster bake subset PMTiles must be MVT tile_type=1"
    serve_pmtiles="${subset_pmtiles}"
    log_info "raster bake PMTiles subset OK: ${subset_pmtiles}"
  fi
  pmtiles_serve_dir="$(dirname -- "${serve_pmtiles}")"
  pmtiles_archive="$(basename -- "${serve_pmtiles}")"
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

python3 - "${bounds}" "${min_zoom}" "${max_zoom}" "${tile_list}" "${bbox_padding_tiles}" <<'PY'
import math
import sys

bounds = [float(part) for part in sys.argv[1].split(",")]
min_zoom = int(sys.argv[2])
max_zoom = int(sys.argv[3])
out = sys.argv[4]
padding = int(sys.argv[5])
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
        xmin, xmax = min(xmin, xmax), max(xmin, xmax)
        ymin, ymax = min(ymin, ymax), max(ymin, ymax)
        xmin = max(0, xmin - padding)
        xmax = min(max_index, xmax + padding)
        ymin = max(0, ymin - padding)
        ymax = min(max_index, ymax + padding)
        for x in range(xmin, xmax + 1):
            for y in range(ymin, ymax + 1):
                lon, lat = tile_center(x, y, z)
                f.write(f"{z}\t{x}\t{y}\t{lon:.8f}\t{lat:.8f}\n")
PY

tile_count="$(wc -l < "${tile_list}" | tr -d '[:space:]')"
(( tile_count > 0 )) || die "${HUAVD_EXIT_INPUT}" "bake tile list is empty for bounds=${bounds}"
log_info "raster bake tiles=${tile_count} zoom=${min_zoom}-${max_zoom} padding=${bbox_padding_tiles} bounds=${bounds}"

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

write_preflight_tiles "${tile_list}" "${preflight_list}"
while IFS=$'\t' read -r preflight_z preflight_x preflight_y preflight_lng preflight_lat; do
  log_info "raster bake renderer preflight z=${preflight_z} x=${preflight_x} y=${preflight_y}"
  rm -f \
    "${png_dir}/${preflight_z}/${preflight_x}/${preflight_y}.png" \
    "${webp_dir}/${preflight_z}/${preflight_x}/${preflight_y}.webp"
  render_one_tile "${preflight_z}" "${preflight_x}" "${preflight_y}" "${preflight_lng}" "${preflight_lat}"
  validate_webp_tile "${webp_dir}/${preflight_z}/${preflight_x}/${preflight_y}.webp" "${tile_size}"
done < "${preflight_list}"

render_input="${tile_list}"
missing_list="${bake_dir}/missing.tsv"
for attempt in $(seq 0 "${bake_retries}"); do
  if (( attempt > 0 )); then
    log_warn "retry raster bake missing tiles attempt=${attempt}/${bake_retries}"
  fi
  render_failed=0
  render_tile_list "${render_input}" || render_failed=1
  missing_count="$(write_missing_tiles "${tile_list}" "${missing_list}" | tr -d '[:space:]')"
  if (( missing_count == 0 )); then
    log_info "raster bake webp tiles complete: ${tile_count}"
    break
  fi
  if (( render_failed )); then
    log_warn "raster bake renderer exited non-zero; missing tiles=${missing_count}"
  fi
  if (( attempt == bake_retries )); then
    head -n 20 "${missing_list}" >&2
    die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "raster bake has ${missing_count} missing WebP tiles after ${bake_retries} retries"
  fi
  render_input="${missing_list}"
done

python3 - "${webp_dir}" "${mbtiles}" "$(artifact_stem raster_bake)" "${bounds}" "${min_zoom}" "${max_zoom}" "${tile_list}" <<'PY'
import os
import sqlite3
import sys

webp_dir, mbtiles, name, bounds, min_zoom, max_zoom, tile_list = sys.argv[1:]
expected = set()
with open(tile_list, "r", encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 5:
            expected.add(tuple(int(part) for part in parts[:3]))

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
        "tile_count": str(len(expected)),
    }
    conn.executemany("insert into metadata(name, value) values (?, ?)", metadata.items())
    inserted = 0
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
            if (z, x, y) not in expected:
                continue
            if os.path.getsize(path) == 0:
                continue
            tile_row = (1 << z) - 1 - y
            with open(path, "rb") as f:
                data = f.read()
            conn.execute(
                "insert into tiles(zoom_level, tile_column, tile_row, tile_data) values (?, ?, ?, ?)",
                (z, x, tile_row, data),
            )
            inserted += 1
    conn.execute("create unique index tile_index on tiles (zoom_level, tile_column, tile_row)")
    if inserted != len(expected):
        raise SystemExit(f"MBTiles tile count mismatch: inserted={inserted} expected={len(expected)}")
    conn.commit()
finally:
    conn.close()
PY

rm -f "${output}" "${output}.sha512"
pmtiles convert "${mbtiles}" "${output}" \
  || die "${HUAVD_EXIT_ERROR}" "pmtiles convert failed: ${mbtiles}"

pmtiles_tile_count="$(pmtiles_addressed_tiles_count "${output}")"
[[ "${pmtiles_tile_count}" == "${tile_count}" ]] \
  || die "${HUAVD_EXIT_VERIFY}" "raster_bake PMTiles tile_count mismatch: header=${pmtiles_tile_count} expected=${tile_count}"

"${SCRIPT_DIR}/metadata.sh" --pmtiles="${output}" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"
"${SCRIPT_DIR}/manifest.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"
"${SCRIPT_DIR}/attribution.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"
write_sha512_file "${output}"
"${SCRIPT_DIR}/verify.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"

if [[ "${png_retention}" == "0" ]]; then
  rm -rf "${png_dir}"
fi

printf 'raster bake OK: %s\n' "${output}"
