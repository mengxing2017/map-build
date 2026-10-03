from __future__ import annotations

from dataclasses import dataclass
import math
import json
import struct
import zlib
from typing import Any

from huavd_map_build.shared.kernel import RegionId, SessionId


@dataclass(frozen=True, slots=True)
class SpriteRequest:
    region: RegionId
    session: SessionId
    workdir: str
    force: bool = False


@dataclass(frozen=True, slots=True)
class SpriteDocuments:
    index: bytes
    image: bytes
    index_2x: bytes
    image_2x: bytes


@dataclass(frozen=True, slots=True)
class SpriteIcon:
    id: str
    shape: str
    color: tuple[int, int, int, int]
    x: int
    y: int
    size: int


@dataclass(frozen=True, slots=True)
class SpritePlan:
    scale: int
    width: int
    height: int
    icons: tuple[SpriteIcon, ...]

    def index(self) -> dict[str, dict[str, int]]:
        return {
            icon.id: {
                "width": icon.size, "height": icon.size,
                "x": icon.x, "y": icon.y, "pixelRatio": self.scale,
            }
            for icon in self.icons
        }


def plan_sprite(manifest: dict[str, Any], scale: int) -> SpritePlan:
    if scale not in (1, 2):
        raise ValueError(f"unsupported sprite scale: {scale}")
    sprite = manifest["sprite"]
    icons = manifest["icons"]
    icon_size = int(sprite.get("icon_size", 24)) * scale
    padding = int(sprite.get("padding", 4)) * scale
    columns = min(6, max(1, len(icons)))
    rows = math.ceil(len(icons) / columns)
    cell = icon_size + padding * 2
    planned = tuple(
        SpriteIcon(
            icon["id"], icon.get("shape", "circle"),
            hex_to_rgba(icon.get("color", "#4b5563")),
            (index % columns) * cell + padding,
            (index // columns) * cell + padding,
            icon_size,
        )
        for index, icon in enumerate(icons)
    )
    return SpritePlan(scale, columns * cell, rows * cell, planned)


def hex_to_rgba(value: str) -> tuple[int, int, int, int]:
    normalized = value.strip().removeprefix("#")
    if len(normalized) != 6:
        raise ValueError(f"invalid color: #{normalized}")
    try:
        return tuple(int(normalized[index:index + 2], 16) for index in (0, 2, 4)) + (255,)
    except ValueError as error:
        raise ValueError(f"invalid color: #{normalized}") from error


def render_sprite(plan: SpritePlan) -> tuple[bytes, bytes]:
    pixels = [(0, 0, 0, 0)] * (plan.width * plan.height)
    for icon in plan.icons:
        _draw_icon(pixels, plan.width, plan.height, icon)
    index = (json.dumps(
        plan.index(), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n").encode("utf-8")
    return index, _png(plan.width, plan.height, pixels)


def _blend(dst, src):
    source_alpha, destination_alpha = src[3] / 255, dst[3] / 255
    output_alpha = source_alpha + destination_alpha * (1 - source_alpha)
    if output_alpha == 0:
        return 0, 0, 0, 0
    return tuple(round(
        (src[index] * source_alpha + dst[index] * destination_alpha * (1 - source_alpha))
        / output_alpha
    ) for index in range(3)) + (round(output_alpha * 255),)


def _pixel(canvas, width, height, x, y, color):
    if 0 <= x < width and 0 <= y < height:
        offset = y * width + x
        canvas[offset] = _blend(canvas[offset], color)


def _rect(canvas, width, height, x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(height, y1 + 1)):
        for x in range(max(0, x0), min(width, x1 + 1)):
            _pixel(canvas, width, height, x, y, color)


def _circle(canvas, width, height, cx, cy, radius, color):
    squared = radius * radius
    for y in range(math.floor(cy - radius), math.ceil(cy + radius) + 1):
        for x in range(math.floor(cx - radius), math.ceil(cx + radius) + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= squared:
                _pixel(canvas, width, height, x, y, color)


def _line(canvas, width, height, x0, y0, x1, y1, color, thickness=2):
    delta_x, delta_y = abs(x1 - x0), -abs(y1 - y0)
    step_x, step_y = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    error, x, y = delta_x + delta_y, x0, y0
    while True:
        _circle(canvas, width, height, x, y, max(1, thickness / 2), color)
        if x == x1 and y == y1:
            break
        doubled = 2 * error
        if doubled >= delta_y:
            error += delta_y
            x += step_x
        if doubled <= delta_x:
            error += delta_x
            y += step_y


def _triangle(canvas, width, height, points, color):
    (x1, y1), (x2, y2), (x3, y3) = points
    denominator = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    for y in range(max(0, min(y1, y2, y3)), min(height - 1, max(y1, y2, y3)) + 1):
        for x in range(max(0, min(x1, x2, x3)), min(width - 1, max(x1, x2, x3)) + 1):
            a = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / denominator
            b = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / denominator
            if a >= 0 and b >= 0 and 1 - a - b >= 0:
                _pixel(canvas, width, height, x, y, color)


def _star(canvas, width, height, cx, cy, outer, inner, color):
    points = []
    for index in range(10):
        angle = -math.pi / 2 + index * math.pi / 5
        radius = outer if index % 2 == 0 else inner
        points.append((round(cx + math.cos(angle) * radius),
                       round(cy + math.sin(angle) * radius)))
    for index, point in enumerate(points):
        _triangle(canvas, width, height,
                  ((cx, cy), point, points[(index + 1) % len(points)]), color)


def _draw_icon(canvas, width, height, icon: SpriteIcon):
    x, y, size, shape, color = icon.x, icon.y, icon.size, icon.shape, icon.color
    cx, cy, stroke = x + size // 2, y + size // 2, max(2, size // 12)
    white, soft_white = (255, 255, 255, 255), (255, 255, 255, 235)
    if shape == "triangle":
        _triangle(canvas, width, height, ((cx, y + 4), (x + 4, y + size - 5),
                  (x + size - 4, y + size - 5)), color)
        _line(canvas, width, height, x + 8, y + size - 8, cx, y + size // 2,
              (255, 255, 255, 210), stroke)
    elif shape == "rail":
        _line(canvas, width, height, x + 7, y + 4, x + 7, y + size - 4, color, stroke)
        _line(canvas, width, height, x + size - 7, y + 4, x + size - 7,
              y + size - 4, color, stroke)
        for yy in range(y + 7, y + size - 4, 5):
            _line(canvas, width, height, x + 5, yy, x + size - 5, yy, color, 1)
    elif shape == "station":
        top, bottom = y + round(size * .14), y + round(size * .76)
        left, right = x + round(size * .22), x + round(size * .78)
        _rect(canvas, width, height, left, top, right, bottom, color)
        _rect(canvas, width, height, left + stroke, top + stroke, right - stroke,
              y + round(size * .46), soft_white)
        _rect(canvas, width, height, cx - stroke, y + round(size * .52), cx,
              bottom - stroke, soft_white)
        _line(canvas, width, height, x + round(size * .10), y + round(size * .86),
              x + round(size * .90), y + round(size * .86), color, stroke)
    elif shape == "metro":
        _circle(canvas, width, height, cx, cy, size // 2 - 3, color)
        _rect(canvas, width, height, x + 8, y + 8, x + size - 8, y + size - 6,
              (255, 255, 255, 230))
        _rect(canvas, width, height, x + 11, y + 12, x + 13, y + size - 6, color)
        _rect(canvas, width, height, x + size - 13, y + 12, x + size - 11,
              y + size - 6, color)
    elif shape == "tram":
        _rect(canvas, width, height, x + 5, y + 7, x + size - 5, y + size - 7, color)
        _rect(canvas, width, height, x + 8, y + 10, x + size - 8, y + 14,
              (255, 255, 255, 230))
        _line(canvas, width, height, cx, y + 7, cx, y + 3, color, 1)
    elif shape == "bus":
        _rect(canvas, width, height, x + 4, y + 6, x + size - 4, y + size - 6, color)
        _rect(canvas, width, height, x + 7, y + 9, x + size - 7, y + 14,
              (255, 255, 255, 230))
        _circle(canvas, width, height, x + 8, y + size - 5, 2, (30, 41, 59, 255))
        _circle(canvas, width, height, x + size - 8, y + size - 5, 2, (30, 41, 59, 255))
    elif shape == "museum":
        _triangle(canvas, width, height, ((cx, y + 4), (x + 5, y + 10),
                  (x + size - 5, y + 10)), color)
        _rect(canvas, width, height, x + 6, y + 11, x + size - 6, y + 13, color)
        for xx in (x + 8, x + 12, x + 16):
            _rect(canvas, width, height, xx, y + 14, xx + 1, y + size - 6, color)
        _rect(canvas, width, height, x + 5, y + size - 5, x + size - 5,
              y + size - 4, color)
    elif shape == "star":
        _star(canvas, width, height, cx, cy, size // 2 - 3, size // 5, color)
    elif shape == "tree":
        radius = size // 2 - 3
        trunk_half, canopy = max(1, round(radius * .11)), cy + round(radius * .22)
        _circle(canvas, width, height, cx, cy, radius, color)
        _rect(canvas, width, height, cx - trunk_half, canopy - 1, cx + trunk_half,
              cy + round(radius * .55), white)
        _triangle(canvas, width, height, ((cx, cy - round(radius * .33)),
                  (cx - round(radius * .58), canopy),
                  (cx + round(radius * .58), canopy)), white)
        _triangle(canvas, width, height, ((cx, cy - round(radius * .66)),
                  (cx - round(radius * .44), cy - round(radius * .10)),
                  (cx + round(radius * .44), cy - round(radius * .10))), white)
    elif shape == "viewpoint":
        _circle(canvas, width, height, cx, cy, size // 2 - 4, color)
        _circle(canvas, width, height, cx, cy, size // 4, (255, 255, 255, 230))
        _circle(canvas, width, height, cx, cy, max(2, size // 9), color)
    elif shape == "bed":
        _rect(canvas, width, height, x + 4, y + 11, x + size - 4, y + size - 8, color)
        _rect(canvas, width, height, x + 5, y + 8, x + 10, y + 12, color)
        _line(canvas, width, height, x + 4, y + size - 8, x + 4, y + size - 4, color, 2)
        _line(canvas, width, height, x + size - 4, y + size - 8, x + size - 4,
              y + size - 4, color, 2)
    elif shape == "cross":
        disc, arm, span = round(size * .42), max(1, round(size * .09)), round(size * .28)
        _circle(canvas, width, height, cx, cy, disc, color)
        _rect(canvas, width, height, cx - arm, cy - span, cx + arm, cy + span, white)
        _rect(canvas, width, height, cx - span, cy - arm, cx + span, cy + arm, white)
    elif shape == "school":
        _triangle(canvas, width, height, ((cx, y + 5), (x + 5, y + 11),
                  (x + size - 5, y + 11)), color)
        _rect(canvas, width, height, x + 6, y + 12, x + size - 6, y + size - 6, color)
        _rect(canvas, width, height, x + 10, y + 15, x + 14, y + size - 6,
              (255, 255, 255, 220))
    elif shape == "service-area":
        _rect(canvas, width, height, x + round(size * .16), y + round(size * .16),
              x + round(size * .84), y + round(size * .84), color)
        x0, y0 = x + round(size * .28), y + round(size * .24)
        x1, y1 = x + round(size * .55), y + round(size * .74)
        _rect(canvas, width, height, x0, y0, x1, y1, soft_white)
        _rect(canvas, width, height, x + round(size * .34), y + round(size * .31),
              x + round(size * .49), y + round(size * .43), color)
        _line(canvas, width, height, x1, y + round(size * .34), x + round(size * .71),
              y + round(size * .44), soft_white, stroke)
        _line(canvas, width, height, x + round(size * .71), y + round(size * .44),
              x + round(size * .71), y + round(size * .69), soft_white, stroke)
        _line(canvas, width, height, x + round(size * .65), y + round(size * .25),
              x + round(size * .78), y + round(size * .35), soft_white, max(1, stroke - 1))
    elif shape == "parking":
        _rect(canvas, width, height, x + round(size * .16), y + round(size * .16),
              x + round(size * .84), y + round(size * .84), color)
        stem0 = x + round(size * .34)
        stem1, top, middle, cap = stem0 + stroke, y + round(size * .27), y + round(size * .50), x + round(size * .65)
        _rect(canvas, width, height, stem0, top, stem1, y + round(size * .73), soft_white)
        _rect(canvas, width, height, stem0, top, cap, top + stroke, soft_white)
        _rect(canvas, width, height, cap - stroke, top, cap, middle, soft_white)
        _rect(canvas, width, height, stem0, middle, cap, middle + stroke, soft_white)
    elif shape == "circle":
        _circle(canvas, width, height, cx, cy, size // 2 - 3, color)
    else:
        raise ValueError(f"unknown icon shape: {shape}")


def _png(width, height, pixels) -> bytes:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixels[y * width + x])

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(
            ">I", zlib.crc32(body) & 0xFFFFFFFF
        )

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
