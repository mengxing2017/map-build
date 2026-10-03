from __future__ import annotations

import json
import os
from pathlib import Path

from huavd_map_build.production.domain.island_anchor import (
    IslandAnchorResult,
    derive_island_anchor,
)


class FileSystemIslandAnchorStore:
    GRID_DIVISIONS = 7

    def derive(
        self, islands: str, cache_directory: str, report: str, region: str
    ) -> IslandAnchorResult:
        source = Path(islands)
        if not source.is_file():
            raise ValueError(f"required file does not exist: {islands}")
        cache = Path(cache_directory)
        cache.mkdir(parents=True, exist_ok=True)
        report_path = Path(report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path = cache / "anchors.raw.geojsonseq"
        clean_path = cache / "anchors.geojsonseq"
        temporary = Path(f"{islands}.island-anchor.tmp")
        polygons = points = anchors = 0
        tiers = {"centroid": 0, "grid": 0, "vertex": 0}
        try:
            with source.open("r", encoding="utf-8") as input_stream, raw_path.open(
                "w", encoding="utf-8", newline="\n"
            ) as raw_stream, clean_path.open("w", encoding="utf-8", newline="\n") as clean_stream:
                for line_number, line in enumerate(input_stream, 1):
                    payload = line.removeprefix("\x1e").strip()
                    if not payload:
                        continue
                    try:
                        feature = json.loads(payload)
                    except json.JSONDecodeError as error:
                        raise ValueError(
                            f"invalid GeoJSONSeq at {islands}:{line_number}: {error.msg}"
                        ) from error
                    geometry = feature.get("geometry", {}) if isinstance(feature, dict) else {}
                    if geometry.get("type") == "Point":
                        points += 1
                    derived = derive_island_anchor(feature) if isinstance(feature, dict) else None
                    if derived is None:
                        continue
                    polygons += 1
                    anchor, tier = derived
                    anchors += 1
                    tiers[tier] += 1
                    self._write(raw_stream, anchor)
                    clean = json.loads(json.dumps(anchor))
                    clean["properties"].pop("_anchor_tier", None)
                    self._write(clean_stream, clean)
            if polygons:
                with source.open("rb") as original, clean_path.open("rb") as additions, temporary.open("wb") as output:
                    for stream in (original, additions):
                        while chunk := stream.read(1024 * 1024):
                            output.write(chunk)
                os.replace(temporary, source)
            document = {
                "schema_version": 1,
                "region": region,
                "layer": "island",
                "thresholds": {"grid_divisions": self.GRID_DIVISIONS},
                "summary": {
                    "polygon_count": polygons,
                    "anchor_count": anchors,
                    "point_feature_count_before": points,
                    "tier": tiers,
                },
                "checks": {"anchor_count_equals_polygon_count": anchors == polygons},
            }
            report_path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return IslandAnchorResult(polygons, anchors, points, tiers, str(report_path))

    @staticmethod
    def _write(stream, value: dict) -> None:
        stream.write("\x1e")
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")
