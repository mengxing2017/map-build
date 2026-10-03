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
ESTIMATE=0
BAKE_MAX_TILES="${BAKE_MAX_TILES:-}"

usage() {
  printf 'usage: %s --region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--base-pmtiles=<path>] [--bbox=w,s,e,n] [--min-zoom=Z] [--max-zoom=Z] [--max-tiles=N] [--estimate] [--force]\n' "$0"
}

tree_stats_json() {
  local directory="$1"
  python3 - "${directory}" <<'PY'
import json
import os
import sys

directory = sys.argv[1]
count = total_bytes = 0
if os.path.isdir(directory):
    for root, _dirs, files in os.walk(directory):
        for name in files:
            path = os.path.join(root, name)
            try:
                total_bytes += os.path.getsize(path)
                count += 1
            except FileNotFoundError:
                pass
print(json.dumps({"file_count": count, "bytes": total_bytes}, separators=(",", ":")))
PY
}

filesystem_stats_json() {
  local directory="$1"
  python3 - "${directory}" <<'PY'
import json
import os
import sys

stat = os.statvfs(sys.argv[1])
print(json.dumps({
    "available_bytes": stat.f_bavail * stat.f_frsize,
    "available_inodes": stat.f_favail,
}, separators=(",", ":")))
PY
}

write_tile_plan() {
  local bounds="$1" min_zoom="$2" max_zoom="$3" tile_list="$4" plan_file="$5" max_tiles="$6" write_tiles="$7"
  python3 - "${bounds}" "${min_zoom}" "${max_zoom}" "${tile_list}" "${plan_file}" "${max_tiles}" "${write_tiles}" "${bbox_padding_tiles}" <<'PY'
import json
import math
import sys

bounds = [float(part) for part in sys.argv[1].split(",")]
min_zoom, max_zoom = map(int, sys.argv[2:4])
tile_list, plan_file, max_tiles, write_tiles, padding = sys.argv[4:]
max_tiles = int(max_tiles) if max_tiles else None
write_tiles = write_tiles == "1"
padding = int(padding)
if len(bounds) != 4:
    raise SystemExit("raster bake bounds must contain west,south,east,north")
west, south, east, north = bounds
if not west < east or not south < north:
    raise SystemExit("raster bake bounds must satisfy west < east and south < north")

def lon_to_x(lon, z):
    return int(math.floor((lon + 180.0) / 360.0 * (1 << z)))

def lat_to_y(lat, z):
    lat = max(min(lat, 85.05112878), -85.05112878)
    rad = math.radians(lat)
    return int(math.floor((1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * (1 << z)))

ranges = []
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
    count = (xmax - xmin + 1) * (ymax - ymin + 1)
    ranges.append((z, xmin, xmax, ymin, ymax, count))

total = sum(item[-1] for item in ranges)
plan = {
    "schema_version": 1,
    "coverage_strategy": "bbox-rectangle-with-padding",
    "bounds": bounds,
    "min_zoom": min_zoom,
    "max_zoom": max_zoom,
    "bbox_padding_tiles": padding,
    "max_tiles": max_tiles,
    "tile_count": total,
    "tiles_by_zoom": [
        {"zoom": z, "tile_count": count, "x_range": [xmin, xmax], "y_range": [ymin, ymax]}
        for z, xmin, xmax, ymin, ymax, count in ranges
    ],
}
with open(plan_file, "w", encoding="utf-8") as f:
    json.dump(plan, f, sort_keys=True, separators=(",", ":"))
    f.write("\n")
if write_tiles:
    def tile_center(x, y, z):
        n = 1 << z
        lon = (x + 0.5) / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 0.5) / n)))
        return lon, math.degrees(lat_rad)
    def tile_bounds(x, y, z):
        n = 1 << z
        west = x / n * 360.0 - 180.0
        east = (x + 1) / n * 360.0 - 180.0
        north = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
        south = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n))))
        return west, south, east, north
    with open(tile_list, "w", encoding="utf-8") as f:
        for z, xmin, xmax, ymin, ymax, _count in ranges:
            for x in range(xmin, xmax + 1):
                for y in range(ymin, ymax + 1):
                    lon, lat = tile_center(x, y, z)
                    west, south, east, north = tile_bounds(x, y, z)
                    f.write(f"{z}\t{x}\t{y}\t{lon:.8f}\t{lat:.8f}\t{west:.12f},{south:.12f},{east:.12f},{north:.12f}\n")
PY
}

validate_mvt_service_tile() {
  local base_url="$1" z="$2" x="$3" y="$4"
  python3 - "${base_url}" "${z}" "${x}" "${y}" <<'PY'
import json
import sys
import time
from urllib.request import urlopen

url = sys.argv[1].format(z=sys.argv[2], x=sys.argv[3], y=sys.argv[4])
started = time.perf_counter()
with urlopen(url, timeout=5) as response:
    payload = response.read()
if not payload:
    raise SystemExit(f"empty MVT response: {url}")
print(json.dumps({
    "url": url,
    "bytes": len(payload),
    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
}, separators=(",", ":")))
PY
}

PMTILES_SERVE_PID=""
BAKE_LOCK_DIR=""

cleanup_render_bake() {
  if [[ -n "${PMTILES_SERVE_PID}" ]] && kill -0 "${PMTILES_SERVE_PID}" >/dev/null 2>&1; then
    kill "${PMTILES_SERVE_PID}" >/dev/null 2>&1 || true
    wait "${PMTILES_SERVE_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${BAKE_LOCK_DIR}" ]]; then
    rm -f "${BAKE_LOCK_DIR}/owner"
    rmdir "${BAKE_LOCK_DIR}" >/dev/null 2>&1 || true
  fi
}

prepare_publish_stage() {
  local source
  PUBLISH_DIR="$(outputs_dir)/.staging/${SESSION}.raster_bake.$$"
  ensure_dir "${PUBLISH_DIR}"
  for source in \
    "$(build_pmtiles_path base)" \
    "$(build_sha512_path base)" \
    "$(build_manifest_path base)" \
    "$(build_attribution_path base)" \
    "$(build_style_path)" \
    "$(build_style_path).sha512" \
    "$(build_raster_style_path)" \
    "$(build_raster_style_path).sha512" \
    "$(build_glyphs_dir)" \
    "$(build_sprite_dir)"; do
    [[ -e "${source}" ]] || continue
    ln -s "${source}" "${PUBLISH_DIR}/$(basename -- "${source}")"
  done
}

publish_raster_bake_stage() {
  local staged_output="$1" staged_manifest="$2" staged_attribution="$3" staged_sha="$4"
  local ready_tmp ready_target
  ready_tmp="${PUBLISH_DIR}/$(basename -- "$(build_ready_path raster_bake)")"
  ready_target="$(build_ready_path raster_bake)"
  jq -n \
    --arg file "$(basename -- "${staged_output}")" \
    --arg sha512 "$(sha512_value "${staged_output}")" \
    --arg manifest_sha512 "$(sha512_value "${staged_manifest}")" \
    --arg attribution_sha512 "$(sha512_value "${staged_attribution}")" \
    --arg generated_at "$(timestamp_utc)" \
    '{schema_version: 1, role: "raster_bake", file: $file, sha512: $sha512, manifest_sha512: $manifest_sha512, attribution_sha512: $attribution_sha512, published_at: $generated_at}' > "${ready_tmp}"

  mv -f "${staged_output}" "$(build_pmtiles_path raster_bake)"
  mv -f "${staged_sha}" "$(build_sha512_path raster_bake)"
  mv -f "${staged_manifest}" "$(build_manifest_path raster_bake)"
  mv -f "${staged_attribution}" "$(build_attribution_path raster_bake)"
  mv -f "${ready_tmp}" "${ready_target}"
  rm -rf "${PUBLISH_DIR}"
}

quarantine_webp_tile() {
  local file="$1" z="$2" x="$3" y="$4"
  [[ -e "${file}" ]] || return 0
  local destination="${BAKE_QUARANTINE_DIR}/webp/${z}/${x}/${y}.webp.$(date +%s%N).$$"
  ensure_dir "$(dirname -- "${destination}")"
  mv -f "${file}" "${destination}"
  if [[ -f "${file}.sha512" ]]; then
    mv -f "${file}.sha512" "${destination}.sha512"
  fi
  log_warn "quarantined invalid WebP cache tile z=${z} x=${x} y=${y}: ${destination}"
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
  local z="$1" x="$2" y="$3" lng="$4" lat="$5" bounds="$6"
  local png="${BAKE_PNG_DIR}/${z}/${x}/${y}.png"
  local png_tmp="${png}.tmp.$$"
  local webp="${BAKE_WEBP_DIR}/${z}/${x}/${y}.webp"
  local webp_tmp="${webp}.tmp.$$"
  local render_log="${png}.render.log"
  local render_started_ms render_elapsed_ms=0 encode_started_ms encode_elapsed_ms
  ensure_dir "$(dirname -- "${png}")"
  ensure_dir "$(dirname -- "${webp}")"

  if [[ "${BAKE_SKIP_EXISTING}" == "1" && -s "${webp}" ]]; then
    if validate_webp_tile "${webp}" "${BAKE_TILE_SIZE}"; then
      write_sha512_file "${webp}"
      return 0
    fi
    quarantine_webp_tile "${webp}" "${z}" "${x}" "${y}"
  fi

  if [[ "${BAKE_SKIP_EXISTING}" != "1" || ! -s "${png}" ]]; then
    render_started_ms="$(epoch_millis)"
    rm -f "${png_tmp}" "${render_log}"
    if [[ -n "${MBGL_RENDER_TILE_COMMAND:-}" ]]; then
      local command="${MBGL_RENDER_TILE_COMMAND}"
      command="${command//\{style\}/${BAKE_STYLE}}"
      command="${command//\{z\}/${z}}"
      command="${command//\{x\}/${x}}"
      command="${command//\{y\}/${y}}"
      command="${command//\{lng\}/${lng}}"
      command="${command//\{lat\}/${lat}}"
      command="${command//\{bounds\}/${bounds}}"
      command="${command//\{tile_size\}/${BAKE_TILE_SIZE}}"
      command="${command//\{png\}/${png_tmp}}"
      if ! timeout --foreground "${BAKE_TILE_TIMEOUT_SECONDS}s" bash -c "${command}" >"${render_log}" 2>&1; then
        tail -n 40 "${render_log}" >&2 || true
        die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "renderer failed for PNG tile: ${png} (z=${z} x=${x} y=${y}; log=${render_log})"
      fi
    elif [[ "${MBGL_RENDER_ENGINE}" == "maplibre-native" ]]; then
      if ! timeout --foreground "${BAKE_TILE_TIMEOUT_SECONDS}s" "${MBGL_RENDER_BIN}" \
        --style "${BAKE_STYLE}" \
        --bounds "${bounds}" \
        --width "${BAKE_TILE_SIZE}" \
        --height "${BAKE_TILE_SIZE}" \
        --output "${png_tmp}" >"${render_log}" 2>&1
      then
        tail -n 40 "${render_log}" >&2 || true
        die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "renderer failed for PNG tile: ${png} (z=${z} x=${x} y=${y}; log=${render_log})"
      fi
    else
      if ! timeout --foreground "${BAKE_TILE_TIMEOUT_SECONDS}s" "${MBGL_RENDER_BIN}" \
        "${BAKE_STYLE}" \
        "${png_tmp}" \
        "${BAKE_TILE_SIZE}" \
        "${BAKE_TILE_SIZE}" \
        -b "${bounds}" >"${render_log}" 2>&1
      then
        tail -n 40 "${render_log}" >&2 || true
        die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "renderer failed for PNG tile: ${png} (z=${z} x=${x} y=${y}; log=${render_log})"
      fi
    fi

    if grep -Eqi 'Error parsing style|data expressions not supported' "${render_log}"; then
      tail -n 40 "${render_log}" >&2 || true
      die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "renderer rejected the bake style for PNG tile: ${png} (z=${z} x=${x} y=${y}; log=${render_log}); use a renderer compatible with MapLibre style-spec data expressions"
    fi
    [[ -s "${png_tmp}" ]] \
      || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "renderer did not create PNG tile: ${png} (z=${z} x=${x} y=${y}, style=${BAKE_STYLE})"
    mv -f "${png_tmp}" "${png}"
    rm -f "${render_log}"
    render_elapsed_ms="$(( $(epoch_millis) - render_started_ms ))"
  fi

  [[ -s "${png}" ]] \
    || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "renderer did not create PNG tile: ${png} (z=${z} x=${x} y=${y}, style=${BAKE_STYLE})"

  local cwebp_args=()
  if [[ "${BAKE_WEBP_LOSSLESS}" == "1" ]]; then
    cwebp_args+=("-lossless")
  fi
  cwebp_args+=("-m" "${BAKE_WEBP_METHOD}" "-metadata" "${BAKE_WEBP_METADATA}")
  encode_started_ms="$(epoch_millis)"
  rm -f "${webp_tmp}"
  timeout --foreground "${BAKE_TILE_TIMEOUT_SECONDS}s" cwebp "${cwebp_args[@]}" "${png}" -o "${webp_tmp}" >/dev/null \
    || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "cwebp failed for PNG tile: ${png}"
  validate_webp_tile "${webp_tmp}" "${BAKE_TILE_SIZE}" \
    || die "${HUAVD_EXIT_VERIFY}" "cwebp produced an invalid WebP tile: ${webp_tmp}"
  mv -f "${webp_tmp}" "${webp}"
  write_sha512_file "${webp}"
  encode_elapsed_ms="$(( $(epoch_millis) - encode_started_ms ))"
  if [[ -n "${BAKE_PREFLIGHT_TIMING_FILE:-}" ]]; then
    printf '%s\t%s\t%s\t%s\t%s\n' "${z}" "${x}" "${y}" "${render_elapsed_ms}" "${encode_elapsed_ms}" >> "${BAKE_PREFLIGHT_TIMING_FILE}"
  fi
}

write_missing_tiles() {
  local input_list="$1" missing_list="$2"
  python3 - "${input_list}" "${BAKE_WEBP_DIR}" "${missing_list}" "${BAKE_TILE_SIZE}" "${BAKE_QUARANTINE_DIR}" <<'PY'
import hashlib
import json
import os
import shutil
import sys

tile_list, webp_dir, missing_list, expected_size, quarantine_dir = sys.argv[1:]
expected_size = int(expected_size)

def structurally_valid_webp(data):
    if len(data) < 16 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    offset = 12
    while offset + 8 <= len(data):
        kind = data[offset:offset + 4]
        length = int.from_bytes(data[offset + 4:offset + 8], "little")
        payload = data[offset + 8:offset + 8 + length]
        if len(payload) != length:
            return False
        width = height = None
        if kind == b"VP8 " and len(payload) >= 10 and payload[3:6] == b"\x9d\x01\x2a":
            width = int.from_bytes(payload[6:8], "little") & 0x3fff
            height = int.from_bytes(payload[8:10], "little") & 0x3fff
        elif kind == b"VP8L" and len(payload) >= 5 and payload[0] == 0x2f:
            bits = int.from_bytes(payload[1:5], "little")
            width = (bits & 0x3fff) + 1
            height = ((bits >> 14) & 0x3fff) + 1
        elif kind == b"VP8X" and len(payload) >= 10:
            width = int.from_bytes(payload[4:7], "little") + 1
            height = int.from_bytes(payload[7:10], "little") + 1
        if width is not None:
            return width == expected_size and height == expected_size
        offset += 8 + length + (length & 1)
    return False

missing = 0
invalid = 0
unverified = 0
with open(tile_list, "r", encoding="utf-8") as src, open(missing_list, "w", encoding="utf-8") as dst:
    for line in src:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 6:
            continue
        z, x, y = parts[:3]
        webp = os.path.join(webp_dir, z, x, f"{y}.webp")
        marker = f"{webp}.sha512"
        try:
            data = open(webp, "rb").read()
        except OSError:
            data = None
        try:
            recorded_sha512 = open(marker, "r", encoding="utf-8").read().split(maxsplit=1)[0]
        except (OSError, IndexError):
            recorded_sha512 = ""
        if data is None or not structurally_valid_webp(data):
            if os.path.exists(webp):
                target = os.path.join(quarantine_dir, "webp", z, x, f"{y}.webp.invalid")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(webp, target)
                if os.path.exists(marker):
                    shutil.move(marker, f"{target}.sha512")
                invalid += 1
            dst.write(line)
            missing += 1
        elif recorded_sha512 != hashlib.sha512(data).hexdigest():
            dst.write(line)
            missing += 1
            unverified += 1
if invalid:
    print(f"raster bake quarantined structurally invalid cache tiles={invalid}", file=sys.stderr)
if unverified:
    print(f"raster bake revalidating unverified cache tiles={unverified}", file=sys.stderr)
print(json.dumps({
    "missing_tiles": missing,
    "structurally_invalid_tiles": invalid,
    "unverified_tiles": unverified,
}, separators=(",", ":")))
PY
}

render_tile_list() {
  local input_list="$1"
  xargs -P "${parallel_jobs}" -n 6 "${BASH}" "$0" --render-one < "${input_list}"
}

verify_raster_grid_alignment() {
  local input_list="$1" validation_dir="$2" max_channel_difference="$3" max_differing_pixels="$4"
  local grid_list macro_png macro_webp child_ppm macro_ppm z x y bounds
  grid_list="${validation_dir}/grid-samples.tsv"
  python3 - "${input_list}" "${grid_list}" <<'PY'
import sys

tile_list, output = sys.argv[1:]
tiles = {}
by_zoom = {}
with open(tile_list, encoding="utf-8") as source:
    for line in source:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 6:
            continue
        z, x, y = map(int, parts[:3])
        tiles[(z, x, y)] = parts
        by_zoom.setdefault(z, []).append((x, y))

candidates = {}
for z, points in by_zoom.items():
    for x, y in points:
        keys = [(z, x, y), (z, x + 1, y), (z, x, y + 1), (z, x + 1, y + 1)]
        if all(key in tiles for key in keys):
            top_left = tiles[keys[0]]
            bottom_right = tiles[keys[3]]
            west, _south, _east, north = top_left[5].split(",")
            _west, south, east, _north = bottom_right[5].split(",")
            candidates[z] = (x, y, f"{west},{south},{east},{north}")
            break

zooms = sorted(candidates)
selected = []
for zoom in (zooms[0], zooms[len(zooms) // 2], zooms[-1]) if zooms else ():
    if zoom not in selected:
        selected.append(zoom)
with open(output, "w", encoding="utf-8") as target:
    for zoom in selected:
        x, y, bounds = candidates[zoom]
        target.write(f"{zoom}\t{x}\t{y}\t{bounds}\n")
PY

  if [[ ! -s "${grid_list}" ]]; then
    log_warn "raster bake grid validation skipped: plan has no complete 2x2 tile sample"
    return 0
  fi

  while IFS=$'\t' read -r z x y bounds; do
    [[ -n "${z}" ]] || continue
    macro_png="${validation_dir}/grid-${z}-${x}-${y}.png"
    macro_webp="${validation_dir}/grid-${z}-${x}-${y}.webp"
    macro_ppm="${validation_dir}/grid-${z}-${x}-${y}.ppm"
    rm -f "${macro_png}" "${macro_webp}" "${macro_ppm}"
    if [[ -n "${MBGL_RENDER_TILE_COMMAND:-}" ]]; then
      local command="${MBGL_RENDER_TILE_COMMAND}"
      command="${command//\{style\}/${BAKE_STYLE}}"
      command="${command//\{z\}/${z}}"
      command="${command//\{x\}/${x}}"
      command="${command//\{y\}/${y}}"
      command="${command//\{bounds\}/${bounds}}"
      command="${command//\{tile_size\}/$((BAKE_TILE_SIZE * 2))}"
      command="${command//\{png\}/${macro_png}}"
      timeout --foreground "${BAKE_TILE_TIMEOUT_SECONDS}s" bash -c "${command}" >/dev/null 2>&1 \
        || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "grid validation renderer failed z=${z} x=${x} y=${y}"
    elif [[ "${MBGL_RENDER_ENGINE}" == "maplibre-native" ]]; then
      timeout --foreground "${BAKE_TILE_TIMEOUT_SECONDS}s" "${MBGL_RENDER_BIN}" \
        --style "${BAKE_STYLE}" --bounds "${bounds}" \
        --width "$((BAKE_TILE_SIZE * 2))" --height "$((BAKE_TILE_SIZE * 2))" --output "${macro_png}" >/dev/null 2>&1 \
        || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "grid validation renderer failed z=${z} x=${x} y=${y}"
    else
      timeout --foreground "${BAKE_TILE_TIMEOUT_SECONDS}s" "${MBGL_RENDER_BIN}" \
        "${BAKE_STYLE}" "${macro_png}" "$((BAKE_TILE_SIZE * 2))" "$((BAKE_TILE_SIZE * 2))" -b "${bounds}" >/dev/null 2>&1 \
        || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "grid validation renderer failed z=${z} x=${x} y=${y}"
    fi
    [[ -s "${macro_png}" ]] || die "${HUAVD_EXIT_VERIFY}" "grid validation renderer created no image z=${z} x=${x} y=${y}"
    cwebp -lossless "${macro_png}" -o "${macro_webp}" >/dev/null \
      || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "grid validation encoder failed z=${z} x=${x} y=${y}"
    dwebp -ppm "${macro_webp}" -o "${macro_ppm}" >/dev/null 2>&1 \
      || die "${HUAVD_EXIT_VERIFY}" "grid validation image cannot be decoded z=${z} x=${x} y=${y}"
    for child in "${z}/${x}/${y}" "${z}/$((x + 1))/${y}" "${z}/${x}/$((y + 1))" "${z}/$((x + 1))/$((y + 1))"; do
      IFS=/ read -r child_z child_x child_y <<< "${child}"
      child_ppm="${validation_dir}/${child_z}-${child_x}-${child_y}.ppm"
      dwebp -ppm "${BAKE_WEBP_DIR}/${child}.webp" -o "${child_ppm}" >/dev/null 2>&1 \
        || die "${HUAVD_EXIT_VERIFY}" "grid validation tile cannot be decoded: ${child}"
    done
    python3 - "${macro_ppm}" "${validation_dir}/${z}-${x}-${y}.ppm" "${validation_dir}/${z}-$((x + 1))-${y}.ppm" "${validation_dir}/${z}-${x}-$((y + 1)).ppm" "${validation_dir}/${z}-$((x + 1))-$((y + 1)).ppm" "${BAKE_TILE_SIZE}" "${max_channel_difference}" "${max_differing_pixels}" "${z}" "${x}" "${y}" <<'PY'
import sys
import json

macro, top_left, top_right, bottom_left, bottom_right, size, channel_limit, pixel_limit, zoom, x, y = sys.argv[1:]
children = [top_left, top_right, bottom_left, bottom_right]
size, channel_limit, pixel_limit = map(int, (size, channel_limit, pixel_limit))
def ppm(path):
    with open(path, "rb") as source:
        tokens = []
        while len(tokens) < 4:
            token = source.readline()
            if not token:
                raise SystemExit(f"truncated PPM: {path}")
            if not token.startswith(b"#"):
                tokens.extend(token.split())
        if tokens[:1] != [b"P6"] or tokens[3] != b"255":
            raise SystemExit(f"unsupported PPM: {path}")
        width, height = map(int, tokens[1:3])
        data = source.read()
    if len(data) != width * height * 3:
        raise SystemExit(f"invalid PPM pixels: {path}")
    return width, height, data
mw, mh, macro_data = ppm(macro)
if (mw, mh) != (size * 2, size * 2):
    raise SystemExit(f"unexpected grid dimensions {mw}x{mh}")
different = max_delta = 0
for index, child in enumerate(children):
    width, height, pixels = ppm(child)
    if (width, height) != (size, size):
        raise SystemExit(f"unexpected tile dimensions {width}x{height}: {child}")
    ox, oy = (index % 2) * size, (index // 2) * size
    for row in range(size):
        start = row * size * 3
        expected = ((oy + row) * mw + ox) * 3
        for left, right in zip(pixels[start:start + size * 3], macro_data[expected:expected + size * 3]):
            delta = abs(left - right)
            max_delta = max(max_delta, delta)
            if delta > channel_limit:
                different += 1
if different > pixel_limit:
    raise SystemExit(f"grid alignment mismatch pixels={different} limit={pixel_limit} max_channel_delta={max_delta}")
print(json.dumps({"zoom": int(zoom), "x": int(x), "y": int(y), "different_pixels": different, "max_channel_delta": max_delta}, separators=(",", ":")))
PY
  done < "${grid_list}"
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
        if len(parts) != 6:
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
  dwebp "${file}" -o /dev/null >/dev/null 2>&1
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
    --max-tiles=*) BAKE_MAX_TILES="${arg#*=}" ;;
    --estimate) ESTIMATE=1 ;;
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
require_cmd jq pmtiles python3 sha512sum
if (( ! ESTIMATE )); then
  require_cmd cwebp dwebp timeout xargs
fi
require_region "${REGION}"
normalize_session_vars
log_execution_context

MBGL_RENDER_ENGINE="${MBGL_RENDER_ENGINE:-mbgl-renderer}"
case "${MBGL_RENDER_ENGINE}" in
  mbgl-renderer|maplibre-native) ;;
  *) die "${HUAVD_EXIT_INPUT}" "invalid MBGL_RENDER_ENGINE=${MBGL_RENDER_ENGINE}; expected mbgl-renderer or maplibre-native" ;;
esac
MBGL_RENDER_BIN="${MBGL_RENDER:-mbgl-render}"
if (( ! ESTIMATE )) && [[ -z "${MBGL_RENDER_TILE_COMMAND:-}" ]]; then
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
tile_timeout_seconds="${BAKE_TILE_TIMEOUT_SECONDS:-$(jq -r '.tile_timeout_seconds // 120' <<< "${bake_defaults}")}"
visual_grid_max_channel_difference="${BAKE_VISUAL_GRID_MAX_CHANNEL_DIFFERENCE:-$(jq -r '.visual_grid_max_channel_difference // 8' <<< "${bake_defaults}")}"
visual_grid_max_differing_pixels="${BAKE_VISUAL_GRID_MAX_DIFFERING_PIXELS:-$(jq -r '.visual_grid_max_differing_pixels // 1024' <<< "${bake_defaults}")}"
pmtiles_extract="${BAKE_PMTILES_EXTRACT:-$(jq -r '.pmtiles_extract // false' <<< "${bake_defaults}")}"
skip_existing="${BAKE_SKIP_EXISTING:-$(jq -r 'if has("skip_existing") and .skip_existing != null then .skip_existing else true end' <<< "${bake_defaults}")}"
png_retention="$(jq -r '.png_cache_retention // 0' <<< "${bake_defaults}")"
webp_lossless="${BAKE_WEBP_LOSSLESS:-$(jq -r 'if (.cwebp | has("lossless")) and .cwebp.lossless != null then .cwebp.lossless else true end' <<< "${bake_defaults}")}"
webp_method="$(jq -r '.cwebp.method // 6' <<< "${bake_defaults}")"
webp_metadata="$(jq -r '.cwebp.metadata // "none"' <<< "${bake_defaults}")"
encoding="$(jq -r '.encoding // "webp"' <<< "${bake_defaults}")"
max_tiles="${BAKE_MAX_TILES:-$(jq -r '.max_tiles // empty' <<< "${bake_defaults}")}"

[[ "${min_zoom}" =~ ^[0-9]+$ && "${max_zoom}" =~ ^[0-9]+$ && "${tile_size}" =~ ^[0-9]+$ ]] \
  || die "${HUAVD_EXIT_INPUT}" "bake zooms and tile_size must be integers"
[[ "${pixel_ratio}" == "1" ]] \
  || die "${HUAVD_EXIT_INPUT}" "raster bake pixel_ratio=${pixel_ratio} is unsupported; only 1 is supported"
[[ "${encoding}" == "webp" ]] \
  || die "${HUAVD_EXIT_INPUT}" "raster bake encoding=${encoding} is unsupported; only webp is supported"
[[ "${bbox_padding_tiles}" =~ ^[0-9]+$ && "${bake_retries}" =~ ^[0-9]+$ ]] \
  || die "${HUAVD_EXIT_INPUT}" "BAKE_BBOX_PADDING_TILES and BAKE_RETRIES must be non-negative integers"
[[ "${tile_timeout_seconds}" =~ ^[1-9][0-9]*$ ]] \
  || die "${HUAVD_EXIT_INPUT}" "BAKE_TILE_TIMEOUT_SECONDS must be a positive integer"
[[ "${visual_grid_max_channel_difference}" =~ ^[0-9]+$ && "${visual_grid_max_differing_pixels}" =~ ^[0-9]+$ ]] \
  || die "${HUAVD_EXIT_INPUT}" "visual grid validation limits must be non-negative integers"
[[ -z "${max_tiles}" || "${max_tiles}" =~ ^[1-9][0-9]*$ ]] \
  || die "${HUAVD_EXIT_INPUT}" "BAKE_MAX_TILES must be a positive integer when set"
(( min_zoom <= max_zoom )) || die "${HUAVD_EXIT_INPUT}" "bake min_zoom must be <= max_zoom"
(( parallel_jobs > 0 )) || die "${HUAVD_EXIT_INPUT}" "BAKE_JOBS must be > 0"

case "${skip_existing}" in true) skip_existing=1 ;; false) skip_existing=0 ;; 1|0) ;; *) die "${HUAVD_EXIT_INPUT}" "skip_existing must be true, false, 1, or 0" ;; esac
case "${webp_lossless}" in true) webp_lossless=1 ;; false) webp_lossless=0 ;; 1|0) ;; *) die "${HUAVD_EXIT_INPUT}" "cwebp.lossless must be true, false, 1, or 0" ;; esac
case "${pmtiles_extract}" in true) pmtiles_extract=1 ;; false) pmtiles_extract=0 ;; 1|0) ;; *) die "${HUAVD_EXIT_INPUT}" "pmtiles_extract must be true, false, 1, or 0" ;; esac

output="$(build_pmtiles_path raster_bake)"
if (( ! ESTIMATE )) && [[ -e "${output}" && "${FORCE}" != "1" ]]; then
  die "${HUAVD_EXIT_ERROR}" "output already exists: ${output}; pass --force"
fi

bake_dir="$(bake_cache_dir)"
bake_runtime_style="${bake_dir}/style-render-runtime.json"
tile_list="${bake_dir}/tiles.tsv"
preflight_list="${bake_dir}/preflight.tsv"
plan_json="${bake_dir}/plan.json"
metrics_json="${bake_dir}/metrics.json"
assembly_metrics_json="${bake_dir}/assembly-metrics.json"
png_dir="${bake_dir}/png"
webp_dir="${bake_dir}/webp"
mbtiles="${bake_dir}/raster_bake.mbtiles"
ensure_dir "${bake_dir}" "${png_dir}" "${webp_dir}" "$(outputs_dir)"
filesystem_before="$(filesystem_stats_json "${bake_dir}")"

bounds="${BAKE_BBOX:-$(pmtiles_bounds "${BASE_PMTILES}" | jq -r '@csv' | tr -d '"')}"
planning_started_ms="$(epoch_millis)"
write_tile_plan "${bounds}" "${min_zoom}" "${max_zoom}" "${tile_list}" "${plan_json}" "${max_tiles}" "$((ESTIMATE == 1 ? 0 : 1))"
planning_elapsed_ms="$(( $(epoch_millis) - planning_started_ms ))"
tile_count="$(jq -r '.tile_count' "${plan_json}")"
(( tile_count > 0 )) || die "${HUAVD_EXIT_INPUT}" "bake tile plan is empty for bounds=${bounds}"
if [[ -n "${max_tiles}" ]] && (( tile_count > max_tiles )); then
  die "${HUAVD_EXIT_INPUT}" "raster bake plan exceeds max_tiles: planned=${tile_count} max_tiles=${max_tiles}; reduce bounds/zoom or raise BAKE_MAX_TILES"
fi
log_info "raster bake plan tiles=${tile_count} zoom=${min_zoom}-${max_zoom} padding=${bbox_padding_tiles} bounds=${bounds} plan=${plan_json}"
if (( ESTIMATE )); then
  cat "${plan_json}"
  exit 0
fi

if [[ ! -f "$(bake_render_style_path)" || "${SCRIPT_DIR}/style.sh" -nt "$(bake_render_style_path)" || "${CONFIG_DIR}/styles.yaml" -nt "$(bake_render_style_path)" || "$(bake_json)" -nt "$(bake_render_style_path)" ]]; then
  "${SCRIPT_DIR}/style.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
fi
require_file "$(bake_render_style_path)"
[[ -d "$(build_glyphs_dir)" ]] \
  || die "${HUAVD_EXIT_INPUT}" "raster_bake requires generated glyphs: $(build_glyphs_dir); run build with --glyph=1"
[[ -d "$(build_sprite_dir)" ]] \
  || die "${HUAVD_EXIT_INPUT}" "raster_bake requires generated sprite: $(build_sprite_dir); run build with --glyph=1"
prepare_publish_stage
bake_source_id="$(jq -r '.source.id // "huavd-offline"' "$(styles_json)")"
jq -e --arg source_id "${bake_source_id}" '
  (.glyphs? == null)
  and (.sprite? == null)
  and (.sources | keys == [$source_id])
  and (.sources[$source_id].type == "vector")
  and all(.layers[]; .type != "symbol" and .type != "fill-extrusion")
' "$(bake_render_style_path)" >/dev/null \
  || die "${HUAVD_EXIT_VERIFY}" "bake render style must contain only the declared base vector source and non-label layers"

if [[ -n "${MBGL_RENDER_TILE_COMMAND:-}" ]]; then
  renderer_identity="custom-command:${MBGL_RENDER_TILE_COMMAND}"
else
  renderer_identity="${MBGL_RENDER_BIN}:$(cmd_version "${MBGL_RENDER_BIN}")"
fi
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
  --arg tile_size "${tile_size}" \
  --arg parallel_jobs "${parallel_jobs}" \
  --arg skip_existing "${skip_existing}" \
  --arg webp_lossless "${webp_lossless}" \
  --arg pmtiles_extract "${pmtiles_extract}" \
  --arg max_tiles "${max_tiles}" \
  --arg tile_timeout_seconds "${tile_timeout_seconds}" \
  --arg visual_grid_max_channel_difference "${visual_grid_max_channel_difference}" \
  --arg visual_grid_max_differing_pixels "${visual_grid_max_differing_pixels}" \
  --arg renderer_engine "${MBGL_RENDER_ENGINE}" \
  --arg renderer_identity "${renderer_identity}" \
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
      BAKE_WEBP_LOSSLESS: $ENV.BAKE_WEBP_LOSSLESS,
      BAKE_TILE_TIMEOUT_SECONDS: $ENV.BAKE_TILE_TIMEOUT_SECONDS
    },
    effective: {
      bounds: $bounds,
      min_zoom: ($min_zoom | tonumber),
      max_zoom: ($max_zoom | tonumber),
      tile_size: ($tile_size | tonumber),
      parallel_jobs: ($parallel_jobs | tonumber),
      skip_existing: ($skip_existing == "1"),
      webp_lossless: ($webp_lossless == "1"),
      pmtiles_extract: ($pmtiles_extract == "1"),
      max_tiles: (if $max_tiles == "" then null else ($max_tiles | tonumber) end),
      tile_timeout_seconds: ($tile_timeout_seconds | tonumber),
      visual_grid_validation: {
        max_channel_difference: ($visual_grid_max_channel_difference | tonumber),
        max_differing_pixels: ($visual_grid_max_differing_pixels | tonumber)
      },
      renderer: {engine: $renderer_engine, identity: $renderer_identity}
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
  printf '%s\n' "tile-bounds-v1" "${MBGL_RENDER_ENGINE}" "${renderer_identity}"
)"
bake_inputs_digest="$(printf '%s' "${bake_inputs}" | sha512sum | awk '{print $1}')"
quarantine_dir="${bake_dir}/quarantine/${bake_inputs_digest}"
BAKE_LOCK_DIR="${bake_dir}/locks/${bake_inputs_digest}"
if ! mkdir -p "${bake_dir}/locks" || ! mkdir "${BAKE_LOCK_DIR}"; then
  die "${HUAVD_EXIT_ERROR}" "raster bake cache is already in use for input fingerprint=${bake_inputs_digest}"
fi
printf '%s\n' "$$" > "${BAKE_LOCK_DIR}/owner"
trap cleanup_render_bake EXIT
if [[ ! -f "${bake_inputs_file}" || "$(<"${bake_inputs_file}")" != "${bake_inputs_digest}" ]]; then
  rm -rf "${png_dir}" "${webp_dir}"
  rm -f "${mbtiles}"
  ensure_dir "${png_dir}" "${webp_dir}"
  printf '%s\n' "${bake_inputs_digest}" > "${bake_inputs_file}"
  log_info "raster bake cache invalidated: base, style, or bake configuration changed"
fi

runtime_source_url="pmtiles://${BASE_PMTILES}"
runtime_tile_url=""
mvt_preflight_json='null'
if [[ -z "${MBGL_RENDER_TILE_COMMAND:-}" && "${MBGL_RENDER_ENGINE}" == "mbgl-renderer" ]]; then
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
  IFS=$'\t' read -r mvt_z mvt_x mvt_y _mvt_lng _mvt_lat < "${tile_list}"
  mvt_preflight_json="$(validate_mvt_service_tile "${runtime_tile_url}" "${mvt_z}" "${mvt_x}" "${mvt_y}")" \
    || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "pmtiles serve returned no MVT tile for preflight z=${mvt_z} x=${mvt_x} y=${mvt_y}"
  log_info "pmtiles serve OK: ${pmtiles_serve_dir} on 127.0.0.1:${pmtiles_serve_port}"
fi

jq --arg source_id "${bake_source_id}" --arg base_url "${runtime_source_url}" --arg tile_url "${runtime_tile_url}" '
  if (.sources | keys) != [$source_id] then
    error("bake style contains unsupported sources")
  elif .sources[$source_id].type != "vector" then
    error("bake style base source must be vector")
  elif $tile_url == "" then
    .sources[$source_id] |= (.url = $base_url)
  else
    .sources[$source_id] |= (del(.url) + {tiles: [$tile_url]})
  end
' "$(bake_render_style_path)" > "${bake_runtime_style}"

export BAKE_STYLE="${bake_runtime_style}"
export BAKE_PNG_DIR="${png_dir}"
export BAKE_WEBP_DIR="${webp_dir}"
export BAKE_TILE_SIZE="${tile_size}"
export BAKE_SKIP_EXISTING="${skip_existing}"
export BAKE_WEBP_LOSSLESS="${webp_lossless}"
export BAKE_WEBP_METHOD="${webp_method}"
export BAKE_WEBP_METADATA="${webp_metadata}"
export BAKE_QUARANTINE_DIR="${quarantine_dir}"
export BAKE_TILE_TIMEOUT_SECONDS="${tile_timeout_seconds}"
export MBGL_RENDER_ENGINE
export MBGL_RENDER_BIN
export MBGL_RENDER_TILE_COMMAND="${MBGL_RENDER_TILE_COMMAND:-}"

preflight_started_ms="$(epoch_millis)"
preflight_timings="${bake_dir}/preflight-timings.tsv"
: > "${preflight_timings}"
BAKE_PREFLIGHT_TIMING_FILE="${preflight_timings}"
write_preflight_tiles "${tile_list}" "${preflight_list}"
while IFS=$'\t' read -r preflight_z preflight_x preflight_y preflight_lng preflight_lat preflight_bounds; do
  log_info "raster bake renderer preflight z=${preflight_z} x=${preflight_x} y=${preflight_y}"
  rm -f \
    "${png_dir}/${preflight_z}/${preflight_x}/${preflight_y}.png" \
    "${webp_dir}/${preflight_z}/${preflight_x}/${preflight_y}.webp"
  render_one_tile "${preflight_z}" "${preflight_x}" "${preflight_y}" "${preflight_lng}" "${preflight_lat}" "${preflight_bounds}"
  validate_webp_tile "${webp_dir}/${preflight_z}/${preflight_x}/${preflight_y}.webp" "${tile_size}"
done < "${preflight_list}"
unset BAKE_PREFLIGHT_TIMING_FILE
preflight_elapsed_ms="$(( $(epoch_millis) - preflight_started_ms ))"
preflight_timing_json="$(python3 - "${preflight_timings}" <<'PY'
import json
import sys

rows = []
with open(sys.argv[1], encoding="utf-8") as source:
    for line in source:
        z, x, y, render_ms, encode_ms = line.rstrip("\n").split("\t")
        rows.append({"z": int(z), "x": int(x), "y": int(y), "render_ms": int(render_ms), "encode_ms": int(encode_ms)})
print(json.dumps(rows, separators=(",", ":")))
PY
)"

missing_list="${bake_dir}/missing.tsv"
cache_scan="$(write_missing_tiles "${tile_list}" "${missing_list}")"
missing_count="$(jq -r '.missing_tiles' <<< "${cache_scan}")"
cache_invalid_count="$(jq -r '.structurally_invalid_tiles' <<< "${cache_scan}")"
cache_unverified_count="$(jq -r '.unverified_tiles' <<< "${cache_scan}")"
cache_hit_count="$((tile_count - missing_count))"
worker_queue_count="${missing_count}"
render_attempt_count=0
retry_attempt_count=0
log_info "raster bake cache hits=${cache_hit_count} render_queue=${worker_queue_count} invalid=${cache_invalid_count} unverified=${cache_unverified_count} total=${tile_count}"
render_started_ms="$(epoch_millis)"
if (( missing_count > 0 )); then
  render_input="${missing_list}"
  for attempt in $(seq 0 "${bake_retries}"); do
    render_attempt_count=$((render_attempt_count + 1))
    if (( attempt > 0 )); then
      retry_attempt_count=$((retry_attempt_count + 1))
      log_warn "retry raster bake missing tiles attempt=${attempt}/${bake_retries}"
    fi
    render_failed=0
    render_tile_list "${render_input}" || render_failed=1
    cache_scan="$(write_missing_tiles "${tile_list}" "${missing_list}")"
    missing_count="$(jq -r '.missing_tiles' <<< "${cache_scan}")"
    cache_invalid_count="$((cache_invalid_count + $(jq -r '.structurally_invalid_tiles' <<< "${cache_scan}")))"
    cache_unverified_count="$((cache_unverified_count + $(jq -r '.unverified_tiles' <<< "${cache_scan}")))"
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
else
  log_info "raster bake rendering skipped: all planned tiles are cached"
fi
render_elapsed_ms="$(( $(epoch_millis) - render_started_ms ))"

visual_validation_dir="${bake_dir}/visual-validation"
ensure_dir "${visual_validation_dir}"
visual_validation_started_ms="$(epoch_millis)"
visual_grid_validation="$(verify_raster_grid_alignment "${tile_list}" "${visual_validation_dir}" "${visual_grid_max_channel_difference}" "${visual_grid_max_differing_pixels}")"
visual_validation_elapsed_ms="$(( $(epoch_millis) - visual_validation_started_ms ))"
visual_grid_validation_json="$(jq -sc '.' <<< "${visual_grid_validation}")"

assemble_started_ms="$(epoch_millis)"
python3 - "${webp_dir}" "${mbtiles}" "$(artifact_stem raster_bake)" "${bounds}" "${min_zoom}" "${max_zoom}" "${tile_list}" "${assembly_metrics_json}" <<'PY'
import json
import os
import sqlite3
import sys
import time

webp_dir, mbtiles, name, bounds, min_zoom, max_zoom, tile_list, metrics_path = sys.argv[1:]
started = time.perf_counter()
expected = set()
with open(tile_list, "r", encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 6:
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
    scan_insert_started = time.perf_counter()
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
    scan_insert_ms = round((time.perf_counter() - scan_insert_started) * 1000, 3)
    index_started = time.perf_counter()
    conn.execute("create unique index tile_index on tiles (zoom_level, tile_column, tile_row)")
    index_ms = round((time.perf_counter() - index_started) * 1000, 3)
    if inserted != len(expected):
        raise SystemExit(f"MBTiles tile count mismatch: inserted={inserted} expected={len(expected)}")
    commit_started = time.perf_counter()
    conn.commit()
    commit_ms = round((time.perf_counter() - commit_started) * 1000, 3)
    with open(metrics_path, "w", encoding="utf-8") as metrics:
        json.dump({
            "expected_tiles": len(expected),
            "inserted_tiles": inserted,
            "scan_and_insert_ms": scan_insert_ms,
            "index_ms": index_ms,
            "commit_ms": commit_ms,
            "total_ms": round((time.perf_counter() - started) * 1000, 3),
        }, metrics, separators=(",", ":"))
        metrics.write("\n")
finally:
    conn.close()
PY
assemble_elapsed_ms="$(( $(epoch_millis) - assemble_started_ms ))"

convert_started_ms="$(epoch_millis)"
staged_output="${PUBLISH_DIR}/$(basename -- "${output}")"
rm -f "${staged_output}" "${staged_output}.sha512"
pmtiles convert "${mbtiles}" "${staged_output}" \
  || die "${HUAVD_EXIT_ERROR}" "pmtiles convert failed: ${mbtiles}"
convert_elapsed_ms="$(( $(epoch_millis) - convert_started_ms ))"

pmtiles_tile_count="$(pmtiles_addressed_tiles_count "${staged_output}")"
[[ "${pmtiles_tile_count}" == "${tile_count}" ]] \
  || die "${HUAVD_EXIT_VERIFY}" "raster_bake PMTiles tile_count mismatch: header=${pmtiles_tile_count} expected=${tile_count}"

postprocess_started_ms="$(epoch_millis)"
HUAVD_OUTPUTS_DIR="${PUBLISH_DIR}" "${SCRIPT_DIR}/metadata.sh" --pmtiles="${staged_output}" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"
HUAVD_OUTPUTS_DIR="${PUBLISH_DIR}" "${SCRIPT_DIR}/manifest.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"
HUAVD_OUTPUTS_DIR="${PUBLISH_DIR}" "${SCRIPT_DIR}/attribution.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"
write_sha512_file "${staged_output}"
HUAVD_OUTPUTS_DIR="${PUBLISH_DIR}" "${SCRIPT_DIR}/verify.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=raster_bake --workdir="${WORKDIR}"
publish_raster_bake_stage \
  "${staged_output}" \
  "${PUBLISH_DIR}/$(basename -- "$(build_manifest_path raster_bake)")" \
  "${PUBLISH_DIR}/$(basename -- "$(build_attribution_path raster_bake)")" \
  "${staged_output}.sha512"
postprocess_elapsed_ms="$(( $(epoch_millis) - postprocess_started_ms ))"

webp_stats="$(tree_stats_json "${webp_dir}")"
png_stats="$(tree_stats_json "${png_dir}")"
filesystem_after="$(filesystem_stats_json "${bake_dir}")"
jq -n \
  --arg generated_at "$(timestamp_utc)" \
  --argjson planned_tiles "${tile_count}" \
  --argjson cache_hit_tiles "${cache_hit_count}" \
  --argjson cache_invalid_tiles "${cache_invalid_count}" \
  --argjson cache_unverified_tiles "${cache_unverified_count}" \
  --argjson preflight_tiles "$(wc -l < "${preflight_list}" | tr -d '[:space:]')" \
  --argjson worker_queue_tiles "${worker_queue_count}" \
  --argjson render_attempts "${render_attempt_count}" \
  --argjson retry_attempts "${retry_attempt_count}" \
  --argjson planning_ms "${planning_elapsed_ms}" \
  --argjson preflight_ms "${preflight_elapsed_ms}" \
  --argjson render_ms "${render_elapsed_ms}" \
  --argjson visual_validation_ms "${visual_validation_elapsed_ms}" \
  --argjson assemble_ms "${assemble_elapsed_ms}" \
  --argjson convert_ms "${convert_elapsed_ms}" \
  --argjson postprocess_ms "${postprocess_elapsed_ms}" \
  --argjson mvt_preflight "${mvt_preflight_json}" \
  --argjson preflight_timings "${preflight_timing_json}" \
  --argjson visual_grid_validation "${visual_grid_validation_json}" \
  --argjson mbtiles_assembly "$(<"${assembly_metrics_json}")" \
  --argjson webp_cache "${webp_stats}" \
  --argjson png_cache "${png_stats}" \
  --argjson filesystem_before "${filesystem_before}" \
  --argjson filesystem_after "${filesystem_after}" \
  --argjson mbtiles_bytes "$(stat -c %s "${mbtiles}")" \
  --argjson pmtiles_bytes "$(stat -c %s "${output}")" \
  '{
    schema_version: 1,
    generated_at: $generated_at,
    planned_tiles: $planned_tiles,
    cache_hit_tiles: $cache_hit_tiles,
    cache: {
      initial_hits: $cache_hit_tiles,
      structurally_invalid: $cache_invalid_tiles,
      unverified: $cache_unverified_tiles
    },
    preflight_tiles: $preflight_tiles,
    worker_queue_tiles: $worker_queue_tiles,
    recovery: {render_attempts: $render_attempts, retry_attempts: $retry_attempts},
    phases_ms: {
      planning: $planning_ms,
      renderer_preflight: $preflight_ms,
      render_and_encode: $render_ms,
      visual_grid_validation: $visual_validation_ms,
      mbtiles_assembly: $assemble_ms,
      pmtiles_convert: $convert_ms,
      postprocess_and_verify: $postprocess_ms
    },
    mvt_service_preflight: $mvt_preflight,
    renderer_preflight_tiles: $preflight_timings,
    visual_grid_validation: $visual_grid_validation,
    mbtiles_assembly: $mbtiles_assembly,
    intermediate_files: {webp_cache: $webp_cache, png_cache: $png_cache},
    filesystem: {before: $filesystem_before, after: $filesystem_after},
    artifacts: {mbtiles_bytes: $mbtiles_bytes, pmtiles_bytes: $pmtiles_bytes}
  }' > "${metrics_json}"
write_sha512_file "${metrics_json}"
log_info "raster bake metrics: ${metrics_json}"

if [[ "${png_retention}" == "0" ]]; then
  rm -rf "${png_dir}"
fi

printf 'raster bake OK: %s\n' "${output}"
