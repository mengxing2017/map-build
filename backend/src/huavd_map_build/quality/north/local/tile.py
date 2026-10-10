from __future__ import annotations

from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.delivery.south.port.metadata import PmtilesHeaderReader
from huavd_map_build.quality.domain.tile import (
    TileCoordinate,
    TileSamplePlan,
    TileSamplingReport,
    lonlat_to_tile,
    representative_lonlat,
    verify_sampled_tiles,
)
from huavd_map_build.quality.domain.vector import QualityFinding
from huavd_map_build.quality.south.port.staging import StagedLayerReader
from huavd_map_build.quality.south.port.tile import VectorTileReader
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role


class VectorTileSamplingGate:
    ZOOM = 10
    MAX_SAMPLES_PER_RULE = 8

    def __init__(
        self, staged: StagedLayerReader, tiles: VectorTileReader,
        headers: PmtilesHeaderReader | None = None,
    ) -> None:
        self._staged, self._tiles, self._headers = staged, tiles, headers

    def verify(
        self, *, region: RegionId, build_date: BuildDate, workdir: str
    ) -> TileSamplingReport:
        paths = ArtifactPaths(
            ArtifactIdentity(region, build_date, Role.BASE),
            f"{workdir.rstrip('/')}/outputs",
        )
        layers = f"{workdir.rstrip('/')}/staging/{paths.identity.session.value}/layers"
        plan = TileSamplePlan(
            self._samples(f"{layers}/island.geojsonseq", "place", {"island", "islet"}),
            self._samples(f"{layers}/waterway.geojsonseq", "waterway", {"river"}),
        )
        decoded = {}
        findings: list[QualityFinding] = []
        for coordinate in plan.coordinates:
            try:
                decoded[coordinate] = self._tiles.decode(paths.pmtiles, coordinate)
            except (OSError, RuntimeError, ValueError) as error:
                findings.append(QualityFinding(
                    "tile-decode",
                    f"cannot decode {coordinate.zoom}/{coordinate.x}/{coordinate.y}: {error}",
                ))
        report = verify_sampled_tiles(plan, decoded)
        high_coordinates: list[TileCoordinate] = []
        if self._headers is not None:
            header = self._headers.read(paths.pmtiles)
            if header.max_zoom >= 19:
                high = self._verify_high_zoom(paths.pmtiles, layers, header.max_zoom)
                high_coordinates.extend(high.sampled_tiles)
                findings.extend(high.findings)
        return TileSamplingReport(
            tuple(dict.fromkeys((*report.sampled_tiles, *high_coordinates))),
            (*findings, *report.findings),
        )

    def _verify_high_zoom(self, archive: str, layers: str, zoom: int) -> TileSamplingReport:
        coordinates: list[TileCoordinate] = []
        findings: list[QualityFinding] = []
        for layer in ("road", "building", "water", "waterway"):
            path = f"{layers}/{layer}.geojsonseq"
            if not self._staged.exists(path):
                continue
            samples: set[TileCoordinate] = set()
            for _line, feature in self._staged.features(path):
                point = representative_lonlat(feature)
                if point is None:
                    continue
                coordinate = lonlat_to_tile(*point, zoom)
                if coordinate in samples:
                    continue
                samples.add(coordinate)
                coordinates.append(coordinate)
                try:
                    tile = self._tiles.decode(archive, coordinate)
                    if not tile.get(layer, {}).get("features"):
                        findings.append(QualityFinding(
                            "tile-high-zoom-empty",
                            f"{layer} is missing at {zoom}/{coordinate.x}/{coordinate.y}",
                        ))
                except (OSError, RuntimeError, ValueError) as error:
                    findings.append(QualityFinding("tile-high-zoom-decode", str(error)))
                if len(samples) >= self.MAX_SAMPLES_PER_RULE:
                    break
        if not coordinates:
            findings.append(QualityFinding(
                "tile-high-zoom-no-samples", "no staged road/building/water samples for highest zoom"
            ))
        return TileSamplingReport(tuple(dict.fromkeys(coordinates)), tuple(findings))

    def _samples(
        self, path: str, field: str, values: set[str]
    ) -> tuple[TileCoordinate, ...]:
        if not self._staged.exists(path):
            return ()
        result = []
        seen = set()
        for _line, feature in self._staged.features(path):
            properties = feature.get("properties", {})
            if not isinstance(properties, dict) or properties.get(field) not in values:
                continue
            point = representative_lonlat(feature)
            if point is None:
                continue
            coordinate = lonlat_to_tile(*point, self.ZOOM)
            if coordinate not in seen:
                seen.add(coordinate)
                result.append(coordinate)
            if len(result) >= self.MAX_SAMPLES_PER_RULE:
                break
        return tuple(result)
