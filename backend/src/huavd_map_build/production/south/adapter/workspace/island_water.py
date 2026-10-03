from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterator

from huavd_map_build.production.domain.island_water import (
    IslandCandidate,
    IslandWaterResult,
    WaterMatch,
    candidate_from_feature,
    match_water_candidates,
)


class FileSystemIslandWaterStore:
    SAMPLE_POINTS = 120
    MIN_INSIDE_RATIO = 0.999
    MAX_IN_WATER_AREA_KM2 = 1.0

    def flag(
        self, islands: str, waters: str, cache_directory: str, report: str, region: str
    ) -> IslandWaterResult:
        island_path, water_path = Path(islands), Path(waters)
        for path in (island_path, water_path):
            if not path.is_file():
                raise ValueError(f"required file does not exist: {path}")
        cache = Path(cache_directory)
        cache.mkdir(parents=True, exist_ok=True)
        report_path = Path(report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        candidates: list[IslandCandidate] = []
        island_count = 0
        for index, feature in enumerate(self._records(island_path)):
            island_count += 1
            candidate = candidate_from_feature(index, feature, self.SAMPLE_POINTS)
            if candidate is not None:
                candidates.append(candidate)
        self._write_indexes(cache, candidates)

        matches: dict[int, WaterMatch] = {}
        water_count = 0
        for water_index, feature in enumerate(self._records(water_path)):
            water_count += 1
            geometry = feature.get("geometry")
            pending = tuple(
                candidate for candidate in candidates if candidate.index not in matches
            )
            for match in match_water_candidates(
                pending, geometry, water_index, self.MIN_INSIDE_RATIO
            ):
                matches[match.index] = match
        self._write_flags(cache / "in-water-flags.tsv", matches)

        temporary = Path(f"{islands}.island-water.tmp")
        flagged: list[dict] = []
        if candidates:
            try:
                with temporary.open("w", encoding="utf-8", newline="\n") as output:
                    for index, feature in enumerate(self._records(island_path)):
                        match = matches.get(index)
                        if match is not None:
                            properties = feature.get("properties")
                            if not isinstance(properties, dict):
                                properties = {}
                                feature["properties"] = properties
                            properties["in_water"] = True
                            flagged.append(self._flag_document(feature, match))
                        self._write_record(output, feature)
                os.replace(temporary, island_path)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise

        water_digest = self._sha512(water_path)
        max_area = max((item["area_km2"] for item in flagged), default=0)
        document = {
            "schema_version": 1,
            "region": region,
            "layer": "island",
            "thresholds": {
                "sample_points": self.SAMPLE_POINTS,
                "min_inside_ratio": self.MIN_INSIDE_RATIO,
                "max_in_water_area_km2": self.MAX_IN_WATER_AREA_KM2,
            },
            "inputs": {
                "island_feature_count": island_count,
                "island_polygon_count": len(candidates),
                "water_feature_count": water_count,
            },
            "summary": {
                "in_water_count": len(flagged),
                "max_in_water_area_km2": max_area,
                "water_geojsonseq_sha512": water_digest,
            },
            "flagged": flagged,
            "checks": {
                "max_in_water_area_within_limit": max_area <= self.MAX_IN_WATER_AREA_KM2
            },
        }
        report_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return IslandWaterResult(
            island_count, len(candidates), water_count, len(flagged), str(report_path)
        )

    @staticmethod
    def _records(path: Path) -> Iterator[dict]:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                payload = line.removeprefix("\x1e").strip()
                if not payload:
                    continue
                try:
                    value = json.loads(payload)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"invalid GeoJSONSeq at {path}:{line_number}: {error.msg}"
                    ) from error
                if not isinstance(value, dict):
                    raise ValueError(f"GeoJSONSeq feature must be an object: {path}:{line_number}")
                yield value

    @staticmethod
    def _write_record(stream, value: dict) -> None:
        stream.write("\x1e")
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")

    @staticmethod
    def _write_indexes(cache: Path, candidates: list[IslandCandidate]) -> None:
        with (cache / "islands.tsv").open("w", encoding="utf-8") as stream:
            for item in candidates:
                samples = " ".join(f"{x},{y}" for x, y in item.samples)
                stream.write(
                    "I\t{}\t{}\t{}\t{}\t{}\t{}\t{}\n".format(
                        item.index, *item.bbox, item.area, samples
                    )
                )
        bbox = [
            {"i": item.index, "bb": list(item.bbox), "area": item.area}
            for item in candidates
        ]
        (cache / "islands.bbox.json").write_text(
            json.dumps(bbox, separators=(",", ":")) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _write_flags(path: Path, matches: dict[int, WaterMatch]) -> None:
        with path.open("w", encoding="utf-8") as stream:
            for index in sorted(matches):
                item = matches[index]
                stream.write(
                    f"{item.index}\t{item.area:.10f}\t{item.inside_ratio:.6f}\t{item.water_index}\n"
                )

    @staticmethod
    def _flag_document(feature: dict, match: WaterMatch) -> dict:
        properties = feature.get("properties", {})
        area_degrees = float(f"{match.area:.10f}")
        area_km2 = math.floor(area_degrees * 111.0 * 110.6 * 1000 + 0.5) / 1000
        return {
            "index": match.index,
            "area_deg2": area_degrees,
            "inside_ratio": float(f"{match.inside_ratio:.6f}"),
            "water_index": match.water_index,
            "name": properties.get("name"),
            "name_zh_hans": properties.get("name:zh-Hans"),
            "area_km2": area_km2,
        }

    @staticmethod
    def _sha512(path: Path) -> str:
        digest = hashlib.sha512()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
