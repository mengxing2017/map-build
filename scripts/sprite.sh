#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

FORCE=0

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --force) FORCE=1 ;;
    -h|--help)
      printf 'usage: %s --region=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--workdir=<path>] [--force]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd python3 sha512sum
require_region "${REGION}"
normalize_session_vars

manifest="${CONFIG_DIR}/icons/manifest.yaml"
require_file "${manifest}"
sprite_dir="$(build_sprite_dir)"

if ! python3 -c 'import yaml' >/dev/null 2>&1; then
  die "${HUAVD_EXIT_REMOTE_OR_TOOL}" \
    "PyYAML is required to parse icon manifest but the active python3 cannot import yaml. Run 'devbox run setup' (which installs PyYAML into the project venv) or 'python3 -m pip install --break-system-packages --user PyYAML' before retrying."
fi

if [[ -e "${sprite_dir}" && "${FORCE}" != "1" ]]; then
  die "${HUAVD_EXIT_ERROR}" "sprite output already exists: ${sprite_dir}; pass --force or clean first"
fi
if [[ -e "${sprite_dir}" ]]; then
  rm -rf "${sprite_dir}"
fi
ensure_dir "${sprite_dir}"

python3 - "${manifest}" "${sprite_dir}" <<'PY'
import json
import math
import struct
import sys
import zlib

try:
    import yaml
except Exception as exc:
    raise SystemExit(f"PyYAML is required to parse icon manifest: {exc}")


def hex_to_rgba(value):
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"invalid color: #{value}")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def blend(dst, src):
    sa = src[3] / 255
    da = dst[3] / 255
    out_a = sa + da * (1 - sa)
    if out_a == 0:
        return (0, 0, 0, 0)
    return tuple(
        round((src[i] * sa + dst[i] * da * (1 - sa)) / out_a)
        for i in range(3)
    ) + (round(out_a * 255),)


def set_pixel(canvas, width, height, x, y, color):
    if 0 <= x < width and 0 <= y < height:
        idx = y * width + x
        canvas[idx] = blend(canvas[idx], color)


def draw_rect(canvas, width, height, x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(height, y1 + 1)):
        for x in range(max(0, x0), min(width, x1 + 1)):
            set_pixel(canvas, width, height, x, y, color)


def draw_circle(canvas, width, height, cx, cy, r, color):
    rr = r * r
    for y in range(math.floor(cy - r), math.ceil(cy + r) + 1):
        for x in range(math.floor(cx - r), math.ceil(cx + r) + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= rr:
                set_pixel(canvas, width, height, x, y, color)


def draw_line(canvas, width, height, x0, y0, x1, y1, color, thickness=2):
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        draw_circle(canvas, width, height, x, y, max(1, thickness / 2), color)
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def draw_triangle(canvas, width, height, points, color):
    (x1, y1), (x2, y2), (x3, y3) = points
    min_x = max(0, min(x1, x2, x3))
    max_x = min(width - 1, max(x1, x2, x3))
    min_y = max(0, min(y1, y2, y3))
    max_y = min(height - 1, max(y1, y2, y3))
    denom = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            a = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / denom
            b = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / denom
            c = 1 - a - b
            if a >= 0 and b >= 0 and c >= 0:
                set_pixel(canvas, width, height, x, y, color)


def draw_star(canvas, width, height, cx, cy, outer, inner, color):
    pts = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        radius = outer if i % 2 == 0 else inner
        pts.append((round(cx + math.cos(angle) * radius), round(cy + math.sin(angle) * radius)))
    for i in range(len(pts)):
        draw_triangle(canvas, width, height, ((cx, cy), pts[i], pts[(i + 1) % len(pts)]), color)


def draw_icon(canvas, width, height, x, y, size, shape, color):
    cx = x + size // 2
    cy = y + size // 2
    stroke = max(2, size // 12)
    if shape == "triangle":
        draw_triangle(canvas, width, height, ((cx, y + 4), (x + 4, y + size - 5), (x + size - 4, y + size - 5)), color)
        draw_line(canvas, width, height, x + 8, y + size - 8, cx, y + size // 2, (255, 255, 255, 210), stroke)
    elif shape == "rail":
        draw_line(canvas, width, height, x + 7, y + 4, x + 7, y + size - 4, color, stroke)
        draw_line(canvas, width, height, x + size - 7, y + 4, x + size - 7, y + size - 4, color, stroke)
        for yy in range(y + 7, y + size - 4, 5):
            draw_line(canvas, width, height, x + 5, yy, x + size - 5, yy, color, 1)
    elif shape == "station":
        body_top = y + round(size * 0.14)
        body_bottom = y + round(size * 0.76)
        body_left = x + round(size * 0.22)
        body_right = x + round(size * 0.78)
        window_bottom = y + round(size * 0.46)
        lower_top = y + round(size * 0.52)
        rail_y = y + round(size * 0.86)
        white = (255, 255, 255, 235)
        draw_rect(canvas, width, height, body_left, body_top, body_right, body_bottom, color)
        draw_rect(canvas, width, height, body_left + stroke, body_top + stroke, body_right - stroke, window_bottom, white)
        draw_rect(canvas, width, height, cx - stroke, lower_top, cx, body_bottom - stroke, white)
        draw_line(canvas, width, height, x + round(size * 0.10), rail_y, x + round(size * 0.90), rail_y, color, stroke)
    elif shape == "metro":
        draw_circle(canvas, width, height, cx, cy, size // 2 - 3, color)
        draw_rect(canvas, width, height, x + 8, y + 8, x + size - 8, y + size - 6, (255, 255, 255, 230))
        draw_rect(canvas, width, height, x + 11, y + 12, x + 13, y + size - 6, color)
        draw_rect(canvas, width, height, x + size - 13, y + 12, x + size - 11, y + size - 6, color)
    elif shape == "tram":
        draw_rect(canvas, width, height, x + 5, y + 7, x + size - 5, y + size - 7, color)
        draw_rect(canvas, width, height, x + 8, y + 10, x + size - 8, y + 14, (255, 255, 255, 230))
        draw_line(canvas, width, height, cx, y + 7, cx, y + 3, color, 1)
    elif shape == "bus":
        draw_rect(canvas, width, height, x + 4, y + 6, x + size - 4, y + size - 6, color)
        draw_rect(canvas, width, height, x + 7, y + 9, x + size - 7, y + 14, (255, 255, 255, 230))
        draw_circle(canvas, width, height, x + 8, y + size - 5, 2, (30, 41, 59, 255))
        draw_circle(canvas, width, height, x + size - 8, y + size - 5, 2, (30, 41, 59, 255))
    elif shape == "museum":
        draw_triangle(canvas, width, height, ((cx, y + 4), (x + 5, y + 10), (x + size - 5, y + 10)), color)
        draw_rect(canvas, width, height, x + 6, y + 11, x + size - 6, y + 13, color)
        for xx in (x + 8, x + 12, x + 16):
            draw_rect(canvas, width, height, xx, y + 14, xx + 1, y + size - 6, color)
        draw_rect(canvas, width, height, x + 5, y + size - 5, x + size - 5, y + size - 4, color)
    elif shape == "star":
        draw_star(canvas, width, height, cx, cy, size // 2 - 3, size // 5, color)
    elif shape == "viewpoint":
        draw_circle(canvas, width, height, cx, cy, size // 2 - 4, color)
        draw_circle(canvas, width, height, cx, cy, size // 4, (255, 255, 255, 230))
        draw_circle(canvas, width, height, cx, cy, max(2, size // 9), color)
    elif shape == "bed":
        draw_rect(canvas, width, height, x + 4, y + 11, x + size - 4, y + size - 8, color)
        draw_rect(canvas, width, height, x + 5, y + 8, x + 10, y + 12, color)
        draw_line(canvas, width, height, x + 4, y + size - 8, x + 4, y + size - 4, color, 2)
        draw_line(canvas, width, height, x + size - 4, y + size - 8, x + size - 4, y + size - 4, color, 2)
    elif shape == "cross":
        disc = round(size * 0.42)
        arm = max(1, round(size * 0.09))
        span = round(size * 0.28)
        draw_circle(canvas, width, height, cx, cy, disc, color)
        draw_rect(canvas, width, height, cx - arm, cy - span, cx + arm, cy + span, (255, 255, 255, 255))
        draw_rect(canvas, width, height, cx - span, cy - arm, cx + span, cy + arm, (255, 255, 255, 255))
    elif shape == "school":
        draw_triangle(canvas, width, height, ((cx, y + 5), (x + 5, y + 11), (x + size - 5, y + 11)), color)
        draw_rect(canvas, width, height, x + 6, y + 12, x + size - 6, y + size - 6, color)
        draw_rect(canvas, width, height, x + 10, y + 15, x + 14, y + size - 6, (255, 255, 255, 220))
    elif shape == "service-area":
        draw_rect(canvas, width, height, x + round(size * 0.16), y + round(size * 0.16), x + round(size * 0.84), y + round(size * 0.84), color)
        white = (255, 255, 255, 235)
        body_x0 = x + round(size * 0.28)
        body_y0 = y + round(size * 0.24)
        body_x1 = x + round(size * 0.55)
        body_y1 = y + round(size * 0.74)
        draw_rect(canvas, width, height, body_x0, body_y0, body_x1, body_y1, white)
        draw_rect(canvas, width, height, x + round(size * 0.34), y + round(size * 0.31), x + round(size * 0.49), y + round(size * 0.43), color)
        draw_line(canvas, width, height, body_x1, y + round(size * 0.34), x + round(size * 0.71), y + round(size * 0.44), white, stroke)
        draw_line(canvas, width, height, x + round(size * 0.71), y + round(size * 0.44), x + round(size * 0.71), y + round(size * 0.69), white, stroke)
        draw_line(canvas, width, height, x + round(size * 0.65), y + round(size * 0.25), x + round(size * 0.78), y + round(size * 0.35), white, max(1, stroke - 1))
    elif shape == "parking":
        draw_rect(canvas, width, height, x + round(size * 0.16), y + round(size * 0.16), x + round(size * 0.84), y + round(size * 0.84), color)
        white = (255, 255, 255, 235)
        stem_x0 = x + round(size * 0.34)
        stem_x1 = stem_x0 + stroke
        top_y = y + round(size * 0.27)
        mid_y = y + round(size * 0.50)
        cap_x1 = x + round(size * 0.65)
        draw_rect(canvas, width, height, stem_x0, top_y, stem_x1, y + round(size * 0.73), white)
        draw_rect(canvas, width, height, stem_x0, top_y, cap_x1, top_y + stroke, white)
        draw_rect(canvas, width, height, cap_x1 - stroke, top_y, cap_x1, mid_y, white)
        draw_rect(canvas, width, height, stem_x0, mid_y, cap_x1, mid_y + stroke, white)
    else:
        draw_circle(canvas, width, height, cx, cy, size // 2 - 3, color)


def write_png(path, width, height, pixels):
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixels[y * width + x])

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def build_sprite(manifest, out_dir, scale):
    sprite_cfg = manifest.get("sprite", {})
    icon_size = int(sprite_cfg.get("icon_size", 24)) * scale
    padding = int(sprite_cfg.get("padding", 4)) * scale
    icons = manifest.get("icons", [])
    if not icons:
        raise ValueError("icon manifest must declare at least one icon")
    cell = icon_size + padding * 2
    cols = min(6, max(1, len(icons)))
    rows = math.ceil(len(icons) / cols)
    width = cols * cell
    height = rows * cell
    pixels = [(0, 0, 0, 0)] * (width * height)
    index = {}

    for n, icon in enumerate(icons):
        icon_id = icon["id"]
        col = n % cols
        row = n // cols
        x = col * cell + padding
        y = row * cell + padding
        draw_icon(pixels, width, height, x, y, icon_size, icon.get("shape", "circle"), hex_to_rgba(icon.get("color", "#4b5563")))
        index[icon_id] = {
            "width": icon_size,
            "height": icon_size,
            "x": x,
            "y": y,
            "pixelRatio": scale,
        }

    suffix = "@2x" if scale == 2 else ""
    with open(f"{out_dir}/sprite{suffix}.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    write_png(f"{out_dir}/sprite{suffix}.png", width, height, pixels)


with open(sys.argv[1], "r", encoding="utf-8") as f:
    manifest = yaml.safe_load(f)

for scale in (1, 2):
    build_sprite(manifest, sys.argv[2], scale)
PY

for file in "${sprite_dir}"/sprite*.json "${sprite_dir}"/sprite*.png; do
  write_sha512_file "${file}"
done

log_info "sprite OK: ${sprite_dir}"
