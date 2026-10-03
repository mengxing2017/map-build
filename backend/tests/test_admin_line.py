import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huavd_map_build.bootstrap import (
    build_configuration_service,
    catalog_service,
    repository_root,
)
from huavd_map_build.production.domain.admin_line import AdminLineRequest, classify_admin_line
from huavd_map_build.production.north.local.admin_line import AdminLineService
from huavd_map_build.production.south.adapter.process.osmium_relations import (
    OsmiumRelationLevelReader,
)
from huavd_map_build.production.south.adapter.workspace.admin_line import (
    FileSystemAdminLineStore,
)


def line(properties, geometry="LineString"):
    return {
        "type": "Feature",
        "geometry": {"type": geometry, "coordinates": []},
        "properties": properties,
    }


class AdminLineHierarchyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.configuration = build_configuration_service(repository_root(Path(__file__)))
        cls.hierarchy = cls.configuration.admin_line_hierarchy("china/guangxi")

    def test_real_hierarchy_resolves_levels_and_zoom(self) -> None:
        self.assertEqual("country", self.hierarchy["level_tier"]["2"])
        self.assertEqual(
            {"minzoom": 3, "maxzoom": 15}, self.hierarchy["tier_zoom"]["province"]
        )

    def test_relation_level_precedes_way_level_and_removes_id(self) -> None:
        decision = classify_admin_line(
            line({"@id": 42, "admin_level": "5", "boundary": "administrative"}),
            {"42": (2, 4)},
            self.hierarchy,
        )
        self.assertEqual(2, decision.feature["properties"]["admin_level"])
        self.assertEqual("country", decision.feature["properties"]["admin_tier"])
        self.assertEqual("relation", decision.feature["properties"]["level_source"])
        self.assertNotIn("@id", decision.feature["properties"])
        self.assertEqual({"minzoom": 0, "maxzoom": 15}, decision.feature["tippecanoe"])

    def test_way_fallback_requires_administrative_boundary(self) -> None:
        kept = classify_admin_line(
            line({"admin_level": 4, "boundary": "administrative"}), {}, self.hierarchy
        )
        discarded = classify_admin_line(
            line({"admin_level": 4, "boundary": "maritime"}), {}, self.hierarchy
        )
        self.assertEqual("way", kept.audit["level_source"])
        self.assertEqual("unlinked_boundary", discarded.audit["reason"])

    def test_discard_reasons_distinguish_geometry_level_and_mapping(self) -> None:
        geometry = classify_admin_line(line({"admin_level": 2}, "Polygon"), {}, self.hierarchy)
        missing = classify_admin_line(line({}), {}, self.hierarchy)
        invalid = classify_admin_line(line({"admin_level": "two"}), {}, self.hierarchy)
        unmapped = classify_admin_line(
            line({"admin_level": 9, "boundary": "administrative"}), {}, self.hierarchy
        )
        self.assertEqual("geometry", geometry.audit["reason"])
        self.assertEqual("missing_level", missing.audit["reason"])
        self.assertEqual("invalid_level", invalid.audit["reason"])
        self.assertEqual("unmapped_level", unmapped.audit["reason"])


class FakeProcess:
    def __init__(self, xml: bytes, return_code: int = 0) -> None:
        self.stdout = io.BytesIO(xml)
        self.return_code = return_code
        self.killed = False

    def wait(self) -> int:
        return self.return_code

    def kill(self) -> None:
        self.killed = True


class OsmiumRelationLevelReaderTest(unittest.TestCase):
    def test_collects_sorted_unique_way_levels(self) -> None:
        xml = b"""<osm>
          <relation id="1"><member type="way" ref="20"/><tag k="admin_level" v="4"/></relation>
          <relation id="2"><member type="way" ref="20"/><member type="way" ref="10"/><tag k="admin_level" v="2"/></relation>
          <relation id="3"><member type="node" ref="20"/><tag k="admin_level" v="x"/></relation>
        </osm>"""
        with patch("shutil.which", return_value="/bin/osmium"), patch(
            "subprocess.Popen", return_value=FakeProcess(xml)
        ) as popen:
            result = OsmiumRelationLevelReader().read("filtered.osm.pbf")
        self.assertEqual({"20": (2, 4), "10": (2,)}, result)
        self.assertEqual(
            ["/bin/osmium", "cat", "filtered.osm.pbf", "-t", "r", "-f", "xml", "-o", "-"],
            popen.call_args.args[0],
        )


class AdminLineStoreTest(unittest.TestCase):
    def test_streams_features_and_writes_complete_audit(self) -> None:
        hierarchy = build_configuration_service(repository_root(Path(__file__))).admin_line_hierarchy(
            "china/guangxi"
        )
        features = [
            line({"@id": 20, "admin_level": "7", "boundary": "maritime"}),
            line({"@id": 30, "admin_level": 4, "boundary": "administrative"}, "MultiLineString"),
            line({"admin_level": 2}, "Polygon"),
            line({}),
            line({"admin_level": "bad"}),
            line({"admin_level": 4, "boundary": "maritime"}),
            line({"admin_level": 9, "boundary": "administrative"}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "admin_line.geojsonseq"
            source.write_text(
                "".join("\x1e" + json.dumps(value) + "\n" for value in features),
                encoding="utf-8",
            )
            derived = Path(directory) / "derived"
            report_path = FileSystemAdminLineStore().transform(
                str(source), "filtered.osm.pbf", str(derived), "china/guangxi",
                {"20": (4, 2, 4), "10": (2,)}, hierarchy,
            )
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            output = source.read_text(encoding="utf-8")
            pairs = (derived / "admin-line-relation-level.tsv").read_text(encoding="utf-8")
        self.assertEqual(2, output.count("\x1e"))
        self.assertNotIn('"@id"', output)
        self.assertEqual("10\t2\n20\t2\n20\t4\n", pairs)
        self.assertEqual(7, report["input_feature_count"])
        self.assertEqual({"2,4": 1}, report["relation_sidecar"]["multi_level_combinations"])
        self.assertEqual({"relation": 1, "way": 1}, report["retained"]["by_level_source"])
        self.assertEqual(1, report["retained"]["relation_rescued_count"])
        self.assertEqual(0, report["retained"]["id_leak_count"])
        self.assertEqual(
            {"geometry": 1, "invalid_level": 1, "missing_level": 1,
             "unlinked_boundary": 1, "unmapped_level": 1},
            report["discarded"]["by_reason"],
        )


class RecordingReader:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def read(self, path: str) -> dict[str, tuple[int, ...]]:
        self.paths.append(path)
        return {}


class AdminLineServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))

    def service(self, reader: RecordingReader) -> AdminLineService:
        return AdminLineService(
            catalog_service(self.root), build_configuration_service(self.root),
            FileSystemAdminLineStore(), reader,
        )

    def test_empty_region_layer_writes_report_without_osmium(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "staging/china-guangxi-20261003/layers/admin_line.geojsonseq"
            pbf = root / "cache/tags-filter/china-guangxi-admin_line.osm.pbf"
            source.parent.mkdir(parents=True)
            pbf.parent.mkdir(parents=True)
            source.touch()
            pbf.touch()
            reader = RecordingReader()
            report_path = self.service(reader).run(AdminLineRequest(
                "china/guangxi", "20261003", directory, "china-guangxi-20261003"
            ))
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        self.assertEqual([], reader.paths)
        self.assertEqual("china/guangxi", report["region"])

    def test_overview_uses_source_digest_for_default_filtered_pbf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "staging/overviews/south-china-overview-20261003"
            layer = stage / "layers/admin_line.geojsonseq"
            source_pbf = stage / "source.osm.pbf"
            stage.joinpath("layers").mkdir(parents=True)
            layer.write_text("\x1e" + json.dumps(line({"admin_level": 2, "boundary": "administrative"})) + "\n",
                             encoding="utf-8")
            source_pbf.write_bytes(b"snapshot")
            store = FileSystemAdminLineStore()
            digest = store.sha512(str(source_pbf))
            filtered = root / f"cache/overview-tags-filter/south-china-overview/{digest}/admin_line.osm.pbf"
            filtered.parent.mkdir(parents=True)
            filtered.touch()
            reader = RecordingReader()
            report = self.service(reader).run(AdminLineRequest(
                "south-china-overview", "20261003", directory,
                "south-china-overview-20261003", overview=True,
            ))
        self.assertEqual([str(filtered)], reader.paths)
        self.assertTrue(report.endswith("derived/overview/south-china-overview-20261003/admin-line-tier-report.json"))
