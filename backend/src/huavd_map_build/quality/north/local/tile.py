from __future__ import annotations

from collections.abc import Callable
from typing import Any

from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.quality.domain.coverage import (
    CoveragePolicy, RoadCoverageAccumulator, SourceCoverage, decoded_road_cells, gap_components,
)
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.delivery.south.port.metadata import PmtilesHeaderReader
from huavd_map_build.quality.domain.tile import (
    TileCoordinate,
    TileSamplePlan,
    TileSamplingReport,
    VectorTilePayload,
    lonlat_to_tile,
    representative_lonlat,
    verify_sampled_tiles,
)
from huavd_map_build.quality.domain.vector import QualityFinding
from huavd_map_build.quality.south.port.staging import StagedLayerReader
from huavd_map_build.quality.south.port.tile import VectorTileReader
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


class VectorTileSamplingGate:
    ZOOM = 10
    MAX_SAMPLES_PER_RULE = 8

    def __init__(
        self, staged: StagedLayerReader, tiles: VectorTileReader,
        headers: PmtilesHeaderReader | None = None,
        configuration: BuildConfigurationService | None = None,
    ) -> None:
        self._staged, self._tiles, self._headers = staged, tiles, headers
        self._configuration = configuration

    def verify(
        self, *, region: RegionId, build_date: BuildDate, workdir: str,
        source_coverage: SourceCoverage | None = None, session: SessionId | None = None,
    ) -> TileSamplingReport:
        paths = ArtifactPaths(
            ArtifactIdentity(region, build_date, Role.BASE),
            f"{workdir.rstrip('/')}/outputs",
        )
        session = session or paths.identity.session
        layers = f"{workdir.rstrip('/')}/staging/{session.value}/layers"
        payloads: dict[TileCoordinate, VectorTilePayload] = {}

        def read(coordinate: TileCoordinate) -> VectorTilePayload:
            if coordinate not in payloads:
                if self._configuration is None:
                    payloads[coordinate] = VectorTilePayload(self._tiles.decode(paths.pmtiles, coordinate), 0, 0)
                else:
                    payloads[coordinate] = self._tiles.read(paths.pmtiles, coordinate)
            return payloads[coordinate]
        plan = TileSamplePlan(
            self._samples(f"{layers}/island.geojsonseq", "place", {"island", "islet"}),
            self._samples(f"{layers}/waterway.geojsonseq", "waterway", {"river"}),
        )
        decoded = {}
        findings: list[QualityFinding] = []
        for coordinate in plan.coordinates:
            try:
                decoded[coordinate] = read(coordinate).decoded
            except (OSError, RuntimeError, ValueError) as error:
                findings.append(QualityFinding(
                    "tile-decode",
                    f"cannot decode {coordinate.zoom}/{coordinate.x}/{coordinate.y}: {error}",
                ))
        report = verify_sampled_tiles(plan, decoded)
        high_coordinates: list[TileCoordinate] = []
        header = self._headers.read(paths.pmtiles) if self._headers is not None else None
        if header is not None:
            if header.max_zoom >= 19:
                high = self._verify_high_zoom(layers, header.max_zoom, read)
                high_coordinates.extend(high.sampled_tiles)
                findings.extend(high.findings)
        audit = {"status": "not-configured", "reason": "coverage configuration unavailable; legacy checks only"}
        coverage_coordinates: tuple[TileCoordinate, ...] = ()
        if self._configuration is not None:
            settings = self._configuration.tippecanoe(region.value, "base")
            policy = CoveragePolicy.from_settings(self._configuration.low_zoom_quality())
            if source_coverage is None:
                accumulator = RoadCoverageAccumulator(session.value, settings, policy)
                path = f"{layers}/road.geojsonseq"
                if "road" in settings["source_layers"]:
                    if not self._staged.exists(path):
                        findings.append(QualityFinding("tile-low-zoom-source", f"required source layer missing: {path}"))
                    else:
                        try:
                            for _line, feature in self._staged.features(path):
                                accumulator.add(feature)
                        except (OSError, UnicodeError, ValueError) as error:
                            findings.append(QualityFinding("tile-low-zoom-source", str(error)))
                source_coverage = accumulator.finish()
            expected_zooms = tuple(z for z in policy.zooms if settings["min_zoom"] <= z <= settings["max_zoom"])
            if (source_coverage.session != session.value or source_coverage.policy != policy
                or source_coverage.zooms != expected_zooms):
                findings.append(QualityFinding("tile-low-zoom-source", "source coverage session/policy/zoom mismatch"))
                audit = {"status": "invalid-source", "policy": policy.as_dict()}
            else:
                coverage_coordinates, extra, audit = self._inspect_coverage(
                    source_coverage, settings, header, read,
                )
                findings.extend(extra)
        return TileSamplingReport(
            tuple(dict.fromkeys((*report.sampled_tiles, *high_coordinates, *coverage_coordinates))),
            (*findings, *report.findings), audit,
        )

    def _inspect_coverage(
        self, source: SourceCoverage, settings: dict[str, Any], header: Any,
        read: Callable[[TileCoordinate], VectorTilePayload],
    ) -> tuple[tuple[TileCoordinate, ...], list[QualityFinding], dict[str, Any]]:
        policy = source.policy
        minimum = getattr(header, "min_zoom", settings["min_zoom"])
        maximum = getattr(header, "max_zoom", settings["max_zoom"])
        samples = {s.coordinate: s for s in source.samples if minimum <= s.coordinate.zoom <= maximum}
        high = tuple(dict.fromkeys(lonlat_to_tile(lon, lat, maximum)
                     for lon, lat, low, high, span in source.audit_points
                     if low <= maximum <= high and span*(1 << maximum)*256 >= policy.minimum_line_pixels))[:8]
        coordinates = tuple(dict.fromkeys((*samples, *high)))
        findings, diagnostics, audits = [], [], []
        limited = settings.get("no_tile_size_limit") is not True
        for coordinate in coordinates:
            label = f"{coordinate.zoom}/{coordinate.x}/{coordinate.y}"
            try:
                payload = read(coordinate)
                if payload.compressed_bytes == 0 or not payload.decoded:
                    findings.append(QualityFinding("tile-low-zoom-missing" if coordinate in samples else "tile-audit-missing",
                                                   f"sampled tile is absent: {label}"))
                    continue
                if limited and payload.compressed_bytes > settings["maximum_tile_bytes"]:
                    findings.append(QualityFinding("tile-low-zoom-oversize", f"{label}: compressed bytes {payload.compressed_bytes} > {settings['maximum_tile_bytes']}"))
                counts = {name: len(layer.get("features", [])) for name, layer in payload.decoded.items()}
                item = {"z": coordinate.zoom, "x": coordinate.x, "y": coordinate.y,
                        "selection": "low-zoom" if coordinate in samples else "highest-zoom-first-distinct",
                        "compressed_bytes": payload.compressed_bytes, "uncompressed_bytes": payload.uncompressed_bytes,
                        "feature_count": sum(counts.values()), "layer_counts": counts}
                if coordinate in samples:
                    occupied = decoded_road_cells(payload.decoded)
                    sample = samples[coordinate]
                    gaps = gap_components(sample, occupied, policy)
                    item.update(source_counts=list(sample.counts), road_cells=sorted(occupied),
                                gap_components=[list(group) for group in gaps])
                    for group in gaps:
                        finding = QualityFinding("tile-low-zoom-gap", f"road at {label}: contiguous empty cells {list(group)}; source counts {[sample.counts[i] for i in group]}")
                        diagnostics.append(finding.as_dict())
                        if policy.gap_mode == "error":
                            findings.append(finding)
                audits.append(item)
            except (OSError, RuntimeError, ValueError) as error:
                findings.append(QualityFinding("tile-low-zoom-decode", f"{label}: {error}"))
        audit = {
            "status": "gaps" if diagnostics else "sampled" if samples else "no-low-zoom-samples",
            "reason": None if samples else "no eligible road geometry at selected archive zooms",
            "policy": policy.as_dict(), "session": source.session,
            "source_road_features": source.road_features,
            "eligible_features": {str(z): count for z, count in source.eligible_features},
            "available_source_tiles": source.available_tiles, "byte_budget_enforced": limited,
            "samples": audits, "diagnostics": diagnostics,
            "sample_max_features": max((a["feature_count"] for a in audits), default=0),
            "sample_max_compressed_bytes": max((a["compressed_bytes"] for a in audits), default=0),
        }
        return coordinates, findings, audit

    def _verify_high_zoom(
        self, layers: str, zoom: int, read: Callable[[TileCoordinate], VectorTilePayload],
    ) -> TileSamplingReport:
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
                    tile = read(coordinate).decoded
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
