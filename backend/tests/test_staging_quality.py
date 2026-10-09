import hashlib
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_configuration_service,
    build_planner,
    repository_root,
)
from huavd_map_build.quality.domain.staging import BaseDeepVerificationError
from huavd_map_build.quality.north.local.staging import BaseStagingQualityGate
from huavd_map_build.quality.south.adapter.filesystem.staging import (
    FileSystemStagedLayerReader,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId


class MemoryLayerReader:
    def __init__(self, missing=(), features=None, reports=None) -> None:
        self.missing = set(missing)
        self.documents = features or {}
        self.reports = reports if reports is not None else valid_reports()

    @staticmethod
    def layer(path: str) -> str:
        return Path(path).stem

    def exists(self, path: str) -> bool:
        return self.layer(path) not in self.missing and (
            not path.endswith(".json") or self.layer(path) in self.reports
        )

    def features(self, path: str):
        yield from enumerate(self.documents.get(self.layer(path), ()), 1)

    def json_document(self, path: str):
        return self.reports[self.layer(path)]

    def sha512(self, path: str) -> str:
        del path
        return "water-sha512"


def valid_reports():
    return {
        "admin-line-tier-report": {
            "schema_version": 1, "retained": {"count": 0, "id_leak_count": 0},
            "relation_sidecar": {"way_count": 0}, "discarded": {"by_reason": {}},
        },
        "place_label_dedup_report": {
            "schema_version": 1,
            "summary": {
                "output_feature_count": 0, "exact_duplicate_dropped_count": 0,
                "same_name_tier_dropped_count": 0,
                "redundant_role_member_dropped_count": 0,
                "admin_display_name_override_count": 0,
                "conventional_region_candidate_count": 0,
                "conventional_region_dropped_count": 0,
                "conventional_region_demoted_count": 0,
            },
            "relations": [], "shared_member_choices": [],
            "same_name_tier_duplicates": [], "redundant_role_members": [],
            "conventional_region_candidates": [],
            "conventional_region_skipped_reason": None,
        },
        "island_water_report": {
            "schema_version": 1, "layer": "island",
            "thresholds": {
                "sample_points": 120,
                "min_inside_ratio": 0.999,
                "max_in_water_area_km2": 1.0,
            },
            "inputs": {"island_polygon_count": 0},
            "summary": {
                "in_water_count": 0,
                "water_geojsonseq_sha512": "water-sha512",
            },
            "checks": {"max_in_water_area_within_limit": True},
        },
        "island_anchor_report": {
            "schema_version": 1, "layer": "island",
            "thresholds": {"grid_divisions": 7},
            "summary": {
                "polygon_count": 0,
                "anchor_count": 0,
                "tier": {"centroid": 0, "grid": 0, "vertex": 0},
            },
        },
    }


class BaseStagingQualityGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = repository_root(Path(__file__))
        cls.configuration = build_configuration_service(root)
        cls.build = build_planner(root).plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20261003"), role="base",
            workdir=Path("/tmp/maps"),
        )

    def test_empty_but_present_layers_pass(self) -> None:
        report = BaseStagingQualityGate(
            self.configuration, MemoryLayerReader()
        ).inspect(self.build)
        self.assertTrue(report.passed, report.as_dict())
        self.assertEqual(0, report.feature_count)
        self.assertIn("road", report.checked_layers)

    def test_reports_missing_layer_and_invalid_feature_contract(self) -> None:
        feature = {
            "type": "Feature", "properties": {"unexpected": "value"},
            "geometry": {"type": "Point", "coordinates": [1, 2]},
        }
        leaked_id = {
            "type": "Feature", "properties": {"@id": 42},
            "geometry": {"type": "Point", "coordinates": [1, 2]},
        }
        gate = BaseStagingQualityGate(
            self.configuration,
            MemoryLayerReader(
                missing=("railway",),
                features={"water": (feature,), "place_label": (leaked_id,)},
            ),
        )
        report = gate.inspect(self.build)
        codes = {finding.code for finding in report.findings}
        self.assertIn("layer-missing", codes)
        self.assertIn("feature-fields", codes)
        self.assertIn("feature-geometry", codes)
        self.assertTrue(any(
            finding.code == "feature-fields"
            and finding.layer == "place_label"
            and "@id" in finding.detail
            for finding in report.findings
        ))
        with self.assertRaises(BaseDeepVerificationError) as raised:
            gate.verify(self.build)
        self.assertEqual(report, raised.exception.report)

    def test_rejects_non_base_build(self) -> None:
        other = build_planner(repository_root(Path(__file__))).plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20261003"), role="raster_bake",
            workdir=Path("/tmp/maps"),
        )
        with self.assertRaisesRegex(ValueError, "base-only"):
            BaseStagingQualityGate(
                self.configuration, MemoryLayerReader()
            ).inspect(other)

    def test_reports_missing_and_inconsistent_derivation_evidence(self) -> None:
        reports = valid_reports()
        reports["island_water_report"]["summary"]["in_water_count"] = 1
        reader = MemoryLayerReader(
            missing=("admin-line-tier-report",), reports=reports
        )
        report = BaseStagingQualityGate(self.configuration, reader).inspect(self.build)
        self.assertTrue(any(
            item.code == "report-missing" and item.layer == "admin_line"
            for item in report.findings
        ))
        self.assertTrue(any(
            item.code == "report-invalid" and item.layer == "island_water"
            for item in report.findings
        ))

    def test_accepts_consistent_island_derivation_reports(self) -> None:
        anchor = {
            "type": "Feature",
            "properties": {"island_anchor": True, "island_area_km2": 0.5},
            "geometry": {"type": "Point", "coordinates": [1, 2]},
        }
        island = {
            "type": "Feature", "properties": {"in_water": True},
            "geometry": {"type": "Polygon", "coordinates": []},
        }
        reports = valid_reports()
        reports["island_water_report"]["inputs"]["island_polygon_count"] = 10
        reports["island_water_report"]["summary"]["in_water_count"] = 1
        reports["island_anchor_report"]["summary"].update(
            {"polygon_count": 1, "anchor_count": 1}
        )
        reader = MemoryLayerReader(features={"island": (island, anchor)}, reports=reports)
        report = BaseStagingQualityGate(self.configuration, reader).inspect(self.build)
        self.assertTrue(report.passed, report.as_dict())

    def test_small_island_sample_skips_percentage_anomaly_check(self) -> None:
        island = {
            "type": "Feature", "properties": {"in_water": True},
            "geometry": {"type": "Polygon", "coordinates": []},
        }
        other = {
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": []},
        }
        reports = valid_reports()
        reports["island_water_report"]["inputs"]["island_polygon_count"] = 2
        reports["island_water_report"]["summary"]["in_water_count"] = 1
        reports["island_anchor_report"]["summary"].update(
            {"polygon_count": 2, "anchor_count": 2}
        )
        reports["island_anchor_report"]["summary"]["tier"]["grid"] = 2
        anchors = tuple({
            "type": "Feature",
            "properties": {"island_anchor": True, "island_area_km2": 0.5},
            "geometry": {"type": "Point", "coordinates": [1, 2]},
        } for _ in range(2))
        reader = MemoryLayerReader(
            features={"island": (island, other, *anchors)}, reports=reports
        )
        report = BaseStagingQualityGate(self.configuration, reader).inspect(self.build)
        self.assertTrue(report.passed, report.as_dict())

    def test_accepts_place_label_semantic_contract(self) -> None:
        feature = {
            "type": "Feature",
            "properties": {
                "name": "Guilin", "name:zh": "桂林", "place": "city",
                "admin_id": 42, "label_tier": "county",
                "label_rank": 300_123_000_000,
            },
            "geometry": {"type": "Point", "coordinates": [110.29, 25.27]},
            "tippecanoe": {"minzoom": 6, "maxzoom": 13},
        }
        reports = valid_reports()
        reports["place_label_dedup_report"]["summary"]["output_feature_count"] = 1
        report = BaseStagingQualityGate(
            self.configuration,
            MemoryLayerReader(features={"place_label": (feature,)}, reports=reports),
        ).inspect(self.build)
        self.assertTrue(report.passed, report.as_dict())

    def test_validates_conventional_region_candidate_audit(self) -> None:
        reports = valid_reports()
        place_report = reports["place_label_dedup_report"]
        place_report["summary"].update({
            "conventional_region_candidate_count": 1,
            "conventional_region_dropped_count": 1,
        })
        place_report["conventional_region_candidates"] = [{
            "node_id": 1, "name": "Yuebei", "place": "region", "tier": "prefecture",
            "reason": "no-admin-evidence", "a1": False, "a2": False, "a3": False,
            "action": "drop", "outcome": "dropped",
        }]
        result = BaseStagingQualityGate(
            self.configuration,
            MemoryLayerReader(reports=reports),
        ).inspect(self.build)
        self.assertTrue(result.passed, result.as_dict())

    def test_reports_place_label_semantic_violations(self) -> None:
        common = {
            "name": "重复名称", "name:zh": "官方名称", "official_name": "官方名称",
            "place": "city", "label_tier": "county", "label_rank": 1,
        }
        first = {
            "type": "Feature",
            "properties": {**common, "admin_id": 42, "@id": 1},
            "geometry": {"type": "Point", "coordinates": [1, 2]},
            "tippecanoe": {"minzoom": 1},
        }
        second = {
            "type": "Feature", "properties": dict(common),
            "geometry": {"type": "Point", "coordinates": [1, 2]},
            "tippecanoe": {"minzoom": 6, "maxzoom": 13},
        }
        reports = valid_reports()
        reports["place_label_dedup_report"]["summary"]["output_feature_count"] = 2
        result = BaseStagingQualityGate(
            self.configuration,
            MemoryLayerReader(
                features={"place_label": (first, second)}, reports=reports
            ),
        ).inspect(self.build)
        codes = {finding.code for finding in result.findings}
        self.assertTrue({
            "feature-id-leak", "place-label-zoom", "place-duplicate",
            "place-name-tier", "place-display-name",
        }.issubset(codes), result.as_dict())

    def test_reports_configured_field_type_violation(self) -> None:
        road = {
            "type": "Feature", "properties": {"maxspeed": "fast"},
            "geometry": {"type": "LineString", "coordinates": [[1, 2], [2, 3]]},
        }
        result = BaseStagingQualityGate(
            self.configuration, MemoryLayerReader(features={"road": (road,)})
        ).inspect(self.build)
        self.assertTrue(any(
            finding.code == "feature-field-type"
            and finding.layer == "road"
            and "maxspeed" in finding.detail
            for finding in result.findings
        ))


class FileSystemStagedLayerReaderTest(unittest.TestCase):
    def test_streams_record_separated_geojson(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "road.geojsonseq"
            path.write_text(
                '\x1e{"type":"Feature","properties":{},"geometry":null}\n',
                encoding="utf-8",
            )
            rows = list(FileSystemStagedLayerReader().features(str(path)))
        self.assertEqual(1, rows[0][0])
        self.assertEqual("Feature", rows[0][1]["type"])

    def test_reports_path_and_line_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "road.geojsonseq"
            path.write_text("not-json\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "road.geojsonseq:1"):
                list(FileSystemStagedLayerReader().features(str(path)))

    def test_reads_json_document_and_streaming_sha512(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            content = '{"schema_version":1}\n'
            path.write_text(content, encoding="utf-8")
            reader = FileSystemStagedLayerReader()
            self.assertEqual(1, reader.json_document(str(path))["schema_version"])
            self.assertEqual(
                hashlib.sha512(content.encode()).hexdigest(), reader.sha512(str(path))
            )
