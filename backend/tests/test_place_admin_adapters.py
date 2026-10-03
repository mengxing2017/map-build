import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huavd_map_build.production.domain.place_admin import AdministrativeRelation
from huavd_map_build.production.south.adapter.process.osmium_place_admin import (
    OsmiumPlaceAdminTool,
)
from huavd_map_build.production.south.adapter.workspace.place_admin import (
    FileSystemPlaceAdminIndexStore,
)


class FakeProcess:
    def __init__(self, xml: bytes, return_code: int = 0) -> None:
        self.stdout = io.BytesIO(xml)
        self.return_code = return_code

    def wait(self) -> int:
        return self.return_code

    def kill(self) -> None:
        pass


class OsmiumPlaceAdminToolTest(unittest.TestCase):
    def test_reads_relations_role_members_and_node_wikidata(self) -> None:
        xml = """<osm>
          <node id="8"><tag k="place" v="city"/><tag k="wikidata" v="Q8"/></node>
          <relation id="20"><member type="node" ref="8" role="admin_centre"/>
            <member type="node" ref="9" role="outer"/><tag k="boundary" v="administrative"/>
            <tag k="admin_level" v="4"/><tag k="name:zh" v="广西"/><tag k="wikidata" v="Q20"/>
          </relation><relation id="21"><tag k="boundary" v="protected_area"/></relation>
        </osm>""".encode()
        with patch("shutil.which", return_value="/bin/osmium"), patch(
            "subprocess.Popen", return_value=FakeProcess(xml)
        ):
            relations, nodes = OsmiumPlaceAdminTool().read_relations_and_nodes("source.pbf")
        self.assertEqual({8: "Q8"}, nodes)
        self.assertEqual(1, len(relations))
        self.assertEqual((8, "admin_centre"), relations[0].nodes[0])
        self.assertEqual("广西", relations[0].display_name())

    def test_filter_and_export_use_argument_vectors(self) -> None:
        completed = type("Result", (), {"returncode": 0, "stderr": ""})()
        with patch("shutil.which", return_value="/bin/osmium"), patch(
            "subprocess.run", return_value=completed
        ) as run:
            tool = OsmiumPlaceAdminTool()
            tool.filter_source("input.pbf", "relations.pbf")
            tool.export_boundaries("relations.pbf", "boundaries.jsonseq", "config.json")
        self.assertEqual("tags-filter", run.call_args_list[0].args[0][1])
        self.assertIn("r/boundary=administrative", run.call_args_list[0].args[0])
        self.assertEqual("export", run.call_args_list[1].args[0][1])
        self.assertNotIn("shell", run.call_args_list[0].kwargs)

    @unittest.skipUnless(shutil.which("osmium"), "osmium is not installed")
    def test_real_osmium_smoke_fixture(self) -> None:
        fixture = Path(__file__).parent / "fixtures/place-admin-source.osm"
        with tempfile.TemporaryDirectory() as directory:
            store = FileSystemPlaceAdminIndexStore()
            pbf, _relations_path, _nodes_path, config = store.prepare(directory)
            boundaries_path = str(Path(directory) / "admin-boundaries.geojsonseq")
            tool = OsmiumPlaceAdminTool()
            tool.filter_source(str(fixture), pbf)
            relations, nodes = tool.read_relations_and_nodes(pbf)
            tool.export_boundaries(pbf, boundaries_path, config)
            boundaries = store.read_boundaries(boundaries_path)
        self.assertEqual({1: "Q1"}, nodes)
        self.assertEqual("Fixture Province", relations[0].display_name())
        self.assertIn(20, boundaries)


class FileSystemPlaceAdminIndexStoreTest(unittest.TestCase):
    def test_writes_compatible_indexes_and_reads_multipolygons(self) -> None:
        relation = AdministrativeRelation(
            20, 4, (None, "广西", None, None), "Q20", ((8, "label"),)
        )
        boundary = {
            "type": "Feature", "properties": {"@id": 20},
            "geometry": {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [0, 0]]]]},
        }
        point = {"type": "Feature", "properties": {"@id": 8},
                 "geometry": {"type": "Point", "coordinates": [0, 0]}}
        with tempfile.TemporaryDirectory() as directory:
            store = FileSystemPlaceAdminIndexStore()
            pbf, relations, nodes, config = store.prepare(directory)
            store.write_relation_indexes(relations, nodes, (relation,), {8: "Q8"})
            geojson = Path(directory) / "boundaries.geojsonseq"
            geojson.write_text("\x1e" + json.dumps(boundary) + "\n\x1e" + json.dumps(point) + "\n",
                               encoding="utf-8")
            indexed = store.read_boundaries(str(geojson))
            output = Path(directory) / "admin-boundaries.ndjson"
            store.write_boundary_index(str(output), indexed)
            relation_doc = json.loads(Path(relations).read_text(encoding="utf-8"))
            node_doc = json.loads(Path(nodes).read_text(encoding="utf-8"))
            config_doc = json.loads(Path(config).read_text(encoding="utf-8"))
        self.assertTrue(pbf.endswith("admin-relations.osm.pbf"))
        self.assertEqual([{"ref": 8, "role": "label"}], relation_doc["nodes"])
        self.assertEqual({"node_id": 8, "wikidata": "Q8"}, node_doc)
        self.assertEqual(["admin_level"], config_doc["include_tags"])
        self.assertEqual([[[[0, 0], [1, 0], [0, 0]]]], indexed[20])
