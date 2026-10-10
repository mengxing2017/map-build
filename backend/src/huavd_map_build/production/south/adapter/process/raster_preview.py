"""Produce a small offline visual inspection page; this is not visual acceptance."""
from __future__ import annotations

import html
from pathlib import Path
import subprocess

from huavd_map_build.production.domain.raster import RasterTilePlan


def write_preview(workspace: Path, plan: RasterTilePlan) -> dict[str, str]:
    destination = workspace / "acceptance"
    destination.mkdir(parents=True, exist_ok=True)
    figures = []
    # Show a neighboring 2x2 group near the center at each of the top three zooms.
    for tile_range in plan.ranges[-3:]:
        x = (tile_range.x_min + tile_range.x_max) // 2
        y = (tile_range.y_min + tile_range.y_max) // 2
        cells = []
        for dy in range(2):
            for dx in range(2):
                tx, ty = min(x + dx, tile_range.x_max), min(y + dy, tile_range.y_max)
                z = tile_range.zoom
                source = workspace / "webp" / str(z) / str(tx) / f"{ty}.webp"
                image = destination / f"{z}-{tx}-{ty}.png"
                subprocess.run(["dwebp", str(source), "-o", str(image)],
                               check=True, timeout=30, capture_output=True)
                cells.append(f'<img src="{image.name}" alt="{z}/{tx}/{ty}" title="{z}/{tx}/{ty}">')
        figures.append(f'<section><h2>XYZ z{tile_range.zoom}</h2><div class="grid">' + "".join(cells) + '</div></section>')
    page = destination / "index.html"
    page.write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>图片瓦片查看</title>'
        '<style>.grid{display:grid;grid-template-columns:repeat(2,max-content);gap:0}'
        'img{display:block}body{font-family:sans-serif}</style><h1>图片瓦片查看</h1>'
        '<p>样本来自范围中心，可能是合法空白。请另查已知城区与边界。'
        '此页不表示接缝、视觉或客户端安装验收通过。</p><p>'
        + html.escape(str(workspace.resolve())) + '</p>' + "".join(figures) + '</html>\n',
        encoding="utf-8",
    )
    return {"preview": str(page.resolve()), "visual_acceptance": "not-run", "client_installation": "not-run"}
