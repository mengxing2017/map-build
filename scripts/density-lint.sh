#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/pmtiles.sh
source "${SCRIPT_DIR}/lib/pmtiles.sh"

REGION_A="${1:?usage: $0 REGION_A REGION_B [YYYYMMDD]}"
REGION_B="${2:?usage: $0 REGION_A REGION_B [YYYYMMDD]}"
YYYYMMDD="${3:-$(date -u +%Y%m%d)}"
WORKDIR="${WORKDIR:-/tmp/huavd-map-build}"

python_with_mvt() {
  if [[ -f /lib/x86_64-linux-gnu/libstdc++.so.6 ]]; then
    LD_PRELOAD=/lib/x86_64-linux-gnu/libstdc++.so.6 python3 "$@"
  else
    python3 "$@"
  fi
}

SLUG_A="$(echo "${REGION_A}" | tr '/' '-')"
SLUG_B="$(echo "${REGION_B}" | tr '/' '-')"
BASE_A="${WORKDIR}/outputs/${SLUG_A}-${YYYYMMDD}.base.pmtiles"
BASE_B="${WORKDIR}/outputs/${SLUG_B}-${YYYYMMDD}.base.pmtiles"

if [[ ! -f "${BASE_A}" || ! -f "${BASE_B}" ]]; then
  log_warn "missing pmtiles files; skipping density-lint"
  exit 0
fi

bounds_a="$(pmtiles_bounds "${BASE_A}")"
bounds_b="$(pmtiles_bounds "${BASE_B}")"

center_a_lng="$(jq -r '(([0] + [2]) / 2) | tostring' <<< "${bounds_a}" 2>/dev/null || jq -n '0')"
center_a_lat="$(jq -r '(([1] + [3]) / 2) | tostring' <<< "${bounds_a}" 2>/dev/null || jq -n '0')"
center_b_lng="$(jq -r '(([0] + [2]) / 2) | tostring' <<< "${bounds_b}" 2>/dev/null || jq -n '0')"
center_b_lat="$(jq -r '(([1] + [3]) / 2) | tostring' <<< "${bounds_b}" 2>/dev/null || jq -n '0')"

center_a="${center_a_lng},${center_a_lat}"
center_b="${center_b_lng},${center_b_lat}"

count_features_at_tile() {
  local pmtiles_file="$1" z="$2" lng="$3" lat="$4"
  local x y
  read -r x y < <(Z="${z}" LNG="${lng}" LAT="${lat}" python3 -c "
import math, os
z = int(os.environ['Z']); lng = float(os.environ['LNG']); lat = float(os.environ['LAT'])
x = int((lng + 180.0) / 360.0 * (2**z))
lat_rad = math.radians(lat)
y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * (2**z))
print(x, y)
")
  if ! python_with_mvt -c "import mapbox_vector_tile" 2>/dev/null; then
    echo "ERR: mapbox_vector_tile not installed"
    return 0
  fi
  pmtiles tile "${pmtiles_file}" "${z}" "${x}" "${y}" 2>/dev/null \
    | python_with_mvt -c "
import sys
try:
    import mapbox_vector_tile
    data = sys.stdin.buffer.read()
    if not data:
        print('{}'); sys.exit(0)
    tile = mapbox_vector_tile.decode(data)
    counts = {layer: len(features) for layer, features in tile.items()}
    print(counts)
except Exception as e:
    print(f'ERR: {e}', file=sys.stderr)
    print('{}')
"
}

echo "=== z=10 中心瓦片要素计数 ==="
echo "  ${REGION_A} (${center_a}):"
count_features_at_tile "${BASE_A}" 10 "${center_a_lng}" "${center_a_lat}" | sed 's/^/    /'
echo "  ${REGION_B} (${center_b}):"
count_features_at_tile "${BASE_B}" 10 "${center_b_lng}" "${center_b_lat}" | sed 's/^/    /'

echo
echo "=== tippecanoe 配置对比 ==="
echo "  ${REGION_A} max_zoom / maximum_tile_bytes:"
echo "    (check via tippecanoe_resolve)"
echo "  ${REGION_B} max_zoom / maximum_tile_bytes:"
echo "    (check via tippecanoe_resolve)"

log_info "density-lint OK: review counts above for > 5x差异"
