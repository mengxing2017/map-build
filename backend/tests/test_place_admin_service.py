import json
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_configuration_service,
    catalog_service,
    repository_root,
)
from huavd_map_build.production.domain.place_admin import PlaceAdminRequest
from huavd_map_build.production.north.local.place_admin import PlaceAdminService
from huavd_map_build.production.south.adapter.process.osmium_place_admin import (
    OsmiumPlaceAdminTool,
)
from huavd_map_build.production.south.adapter.workspace.place_admin import (
    FileSystemPlaceAdminIndexStore,
)
from huavd_map_build.shared.kernel import RegionId, SessionId


class FailingTool:
    def __getattr__(self, name):
        raise AssertionError(f"tool must not be called for empty input: {name}")


class PlaceAdminServiceTest(unittest.TestCase):
    def test_missing_symlink_target_reports_original_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.osm.pbf"
            original = Path(directory) / "moved-input.osm.pbf"
            source.symlink_to(original)
            with self.assertRaisesRegex(ValueError, "broken symbolic link.*moved-input.osm.pbf"):
                FileSystemPlaceAdminIndexStore().require_file(str(source))

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))

    def service(self, tool) -> PlaceAdminService:
        return PlaceAdminService(
            catalog_service(self.root), build_configuration_service(self.root),
            FileSystemPlaceAdminIndexStore(), tool,
        )

    @staticmethod
    def request(directory: str, source: str) -> PlaceAdminRequest:
        return PlaceAdminRequest(
            RegionId("china/guangxi"), SessionId("china-guangxi-20261003"),
            directory, source,
        )

    def test_empty_layer_writes_zero_report_without_tool_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "mirror/source.osm.pbf"
            labels = root / "staging/china-guangxi-20261003/layers/place_label.geojsonseq"
            source.parent.mkdir(parents=True)
            labels.parent.mkdir(parents=True)
            source.touch()
            labels.touch()
            report_path = self.service(FailingTool()).run(
                self.request(directory, "mirror/source.osm.pbf")
            )
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        self.assertEqual(0, report["summary"]["output_feature_count"])
        self.assertEqual([], report["relations"])

    @unittest.skipUnless(shutil.which("osmium"), "osmium is not installed")
    def test_real_fixture_runs_complete_pipeline(self) -> None:
        fixture = self.root / "backend/tests/fixtures/place-admin-source.osm"
        feature = {
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"@id": 1, "name": "Fixture Province", "place": "state",
                           "population": 100},
        }
        with tempfile.TemporaryDirectory() as directory:
            labels = Path(directory) / "staging/china-guangxi-20261003/layers/place_label.geojsonseq"
            labels.parent.mkdir(parents=True)
            labels.write_text("\x1e" + json.dumps(feature) + "\n", encoding="utf-8")
            report_path = self.service(OsmiumPlaceAdminTool()).run(
                self.request(directory, str(fixture))
            )
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            output = labels.read_text(encoding="utf-8")
            cache = Path(directory) / "cache/place-admin/china-guangxi-20261003"
            relation_index_exists = (cache / "admin-relations.ndjson").is_file()
            boundary_index_exists = (cache / "admin-boundaries.ndjson").is_file()
        self.assertEqual(1, report["summary"]["output_feature_count"])
        self.assertEqual(3, report["schema_version"])
        self.assertEqual([], report["identity_relations_without_kept_point"])
        self.assertEqual(
            hashlib.sha512(output.encode("utf-8")).hexdigest(),
            report["output_geojsonseq_sha512"],
        )
        self.assertEqual(20, report["relations"][0]["admin_id"])
        self.assertIn('"admin_id":20', output)
        self.assertNotIn('"@id"', output)
        self.assertTrue(relation_index_exists)
        self.assertTrue(boundary_index_exists)
