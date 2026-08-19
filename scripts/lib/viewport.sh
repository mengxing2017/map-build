#!/usr/bin/env bash

set -euo pipefail

if [[ -z "${HUAVD_MAP_BUILD_COMMON_LOADED:-}" ]]; then
  # shellcheck source=common.sh
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"
fi
if [[ -z "${HUAVD_MAP_BUILD_PMTILES_LOADED:-}" ]]; then
  # shellcheck source=pmtiles.sh
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/pmtiles.sh"
fi
HUAVD_MAP_BUILD_VIEWPORT_LOADED=1

viewport_lnglat_to_tile() {
  local z="$1" lng="$2" lat="$3"
  Z="${z}" LNG="${lng}" LAT="${lat}" python3 -c "
import math, os
z = int(os.environ['Z']); lng = float(os.environ['LNG']); lat = float(os.environ['LAT'])
x = int((lng + 180.0) / 360.0 * (2**z))
lat_rad = math.radians(lat)
y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * (2**z))
print(f'{x} {y}')
"
}

viewport_tile_to_lnglat() {
  local z="$1" x="$2" y="$3"
  Z="${z}" X="${x}" Y="${y}" python3 -c "
import math, os
z = int(os.environ['Z']); x = int(os.environ['X']); y = int(os.environ['Y'])
n = 2**z
lng = x / n * 360.0 - 180.0
lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
lat = math.degrees(lat_rad)
print(f'{lng} {lat}')
"
}

python_with_mvt() {
  if [[ -f /lib/x86_64-linux-gnu/libstdc++.so.6 ]]; then
    LD_PRELOAD=/lib/x86_64-linux-gnu/libstdc++.so.6 python3 "$@"
  else
    python3 "$@"
  fi
}

viewport_has_mvt_decoder() {
  python_with_mvt -c "import mapbox_vector_tile" 2>/dev/null
}

viewport_extract_center() {
  local pmtiles="$1"
  local z=4
  local best_score=0 best_x=0 best_y=0

  if ! command -v pmtiles >/dev/null 2>&1; then
    log_warn "pmtiles command not found, falling back to bounds center"
    local bounds_json
    bounds_json="$(pmtiles_bounds "${pmtiles}")"
    awk -v a="$(jq -r '.[0]' <<< "${bounds_json}")" \
        -v b="$(jq -r '.[2]' <<< "${bounds_json}")" \
        -v c="$(jq -r '.[1]' <<< "${bounds_json}")" \
        -v d="$(jq -r '.[3]' <<< "${bounds_json}")" \
      'BEGIN { printf "%.6f %.6f 0\n", (a+b)/2, (c+d)/2 }'
    return 0
  fi

  local bounds_json
  bounds_json="$(pmtiles_bounds "${pmtiles}")"
  local min_lng min_lat max_lng max_lat
  min_lng="$(jq -r '.[0]' <<< "${bounds_json}")"
  min_lat="$(jq -r '.[1]' <<< "${bounds_json}")"
  max_lng="$(jq -r '.[2]' <<< "${bounds_json}")"
  max_lat="$(jq -r '.[3]' <<< "${bounds_json}")"

  local mid_lat
  mid_lat="$(awk -v a="${min_lat}" -v b="${max_lat}" 'BEGIN { printf "%.6f", (a+b)/2 }')"

  local x_min x_max y_min y_max
  read -r x_min y_min < <(viewport_lnglat_to_tile "${z}" "${min_lng}" "${mid_lat}")
  read -r x_max y_max < <(viewport_lnglat_to_tile "${z}" "${max_lng}" "${mid_lat}")

  local max_tile
  max_tile=$(( (1 << z) - 1 ))
  x_min=$(( x_min > 0 ? x_min - 1 : 0 ))
  y_min=$(( y_min > 0 ? y_min - 1 : 0 ))
  x_max=$(( x_max < max_tile ? x_max + 1 : max_tile ))
  y_max=$(( y_max < max_tile ? y_max + 1 : max_tile ))

  local can_decode=0
  if viewport_has_mvt_decoder; then
    can_decode=1
  fi

  if (( can_decode == 0 )); then
    log_warn "mapbox_vector_tile not installed, falling back to bounds center"
    awk -v a="${min_lng}" -v b="${max_lng}" -v c="${min_lat}" -v d="${max_lat}" \
      'BEGIN { printf "%.6f %.6f 0\n", (a+b)/2, (c+d)/2 }'
    return 0
  fi

  local x y score
  for ((x = x_min; x <= x_max; x++)); do
    for ((y = y_min; y <= y_max; y++)); do
      score="$(pmtiles tile "${pmtiles}" "${z}" "${x}" "${y}" 2>/dev/null \
        | python_with_mvt -c "
import sys
try:
    import mapbox_vector_tile
    data = sys.stdin.buffer.read()
    if not data:
        print(0); sys.exit(0)
    tile = mapbox_vector_tile.decode(data)
    place_layer = tile.get('place_label', {})
    features = place_layer.get('features', [])
    weights = {
        'country_capital': 1000,
        'state_capital': 100,
        'region_capital': 50,
        'city': 10,
        'town': 1,
    }
    score = sum(weights.get(f['properties'].get('place', ''), 1) for f in features)
    print(score)
except Exception:
    print(0)
")" || score=0
      if (( score > best_score )); then
        best_score="${score}"
        best_x="${x}"
        best_y="${y}"
      fi
    done
  done

  if (( best_score == 0 )); then
    log_info "no place_label found in z=${z} tiles, using bounds center"
    awk -v a="${min_lng}" -v b="${max_lng}" -v c="${min_lat}" -v d="${max_lat}" \
      'BEGIN { printf "%.6f %.6f 0\n", (a+b)/2, (c+d)/2 }'
  else
    local center_lng center_lat
    read -r center_lng center_lat < <(viewport_tile_to_lnglat "${z}" "${best_x}" "${best_y}")
    printf '%.6f %.6f %d\n' "${center_lng}" "${center_lat}" "${best_score}"
  fi
}

viewport_calc_default_zoom() {
  local pmtiles="$1"
  local bounds_json
  bounds_json="$(pmtiles_bounds "${pmtiles}")"

  MIN_LNG="$(jq -r '.[0]' <<< "${bounds_json}")" \
  MIN_LAT="$(jq -r '.[1]' <<< "${bounds_json}")" \
  MAX_LNG="$(jq -r '.[2]' <<< "${bounds_json}")" \
  MAX_LAT="$(jq -r '.[3]' <<< "${bounds_json}")" \
  python3 -c "
import math, os
min_lng = float(os.environ['MIN_LNG'])
min_lat = float(os.environ['MIN_LAT'])
max_lng = float(os.environ['MAX_LNG'])
max_lat = float(os.environ['MAX_LAT'])
R = 6371.0
def hav(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(a))

diag_km = hav(min_lat, min_lng, max_lat, max_lng)

def km_to_zoom(d):
    if d > 800: return 4
    elif d > 400: return 5
    elif d > 150: return 6
    elif d > 80: return 7
    elif d > 30: return 8
    elif d > 10: return 9
    elif d > 4: return 10
    else: return 11

print(km_to_zoom(diag_km))
"
}
