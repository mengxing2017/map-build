import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.production.domain.island_water import (
    candidate_from_feature,
    match_water,
)
from huavd_map_build.production.south.adapter.workspace.island_water import (
    FileSystemIslandWaterStore,
)


def feature(geometry_type, coordinates, properties=None):
    return {
        "type": "Feature",
        "geometry": {"type": geometry_type, "coordinates": coordinates},
        "properties": properties or {},
    }


def ring(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


class IslandWaterDomainTest(unittest.TestCase):
    def test_enclosed_island_matches_water(self) -> None:
        island = candidate_from_feature(3, feature("Polygon", [ring(2, 2, 3, 3)]))
        match = match_water(island, {"type": "Polygon", "coordinates": [ring(0, 0, 5, 5)]}, 7)
        self.assertEqual(3, match.index)
        self.assertEqual(7, match.water_index)
        self.assertEqual(1.0, match.inside_ratio)

    def test_water_hole_and_bbox_reject_candidates(self) -> None:
        island = candidate_from_feature(0, feature("Polygon", [ring(2, 2, 3, 3)]))
        water_with_hole = {
            "type": "Polygon",
            "coordinates": [ring(0, 0, 5, 5), ring(1, 1, 4, 4)],
        }
        self.assertIsNone(match_water(island, water_with_hole, 0))
        outside = {"type": "Polygon", "coordinates": [ring(10, 10, 20, 20)]}
        self.assertIsNone(match_water(island, outside, 1))


class IslandWaterStoreTest(unittest.TestCase):
    @staticmethod
    def _sequence(values):
        return "".join("\x1e" + json.dumps(value) + "\n" for value in values)

    def test_flags_layer_writes_report_and_preserves_water_bytes(self) -> None:
        island = feature(
            "Polygon", [ring(0.002, 0.002, 0.003, 0.003)], {"name": "Tiny"}
        )
        point = feature("Point", [1, 1], {"name": "Node"})
        water = feature("Polygon", [ring(0, 0, 0.01, 0.01)])
        with tempfile.TemporaryDirectory() as directory:
            islands = Path(directory) / "island.geojsonseq"
            waters = Path(directory) / "water.geojsonseq"
            islands.write_text(self._sequence([island, point]), encoding="utf-8")
            water_bytes = self._sequence([water]).encode()
            waters.write_bytes(water_bytes)
            report = Path(directory) / "island_water_report.json"
            result = FileSystemIslandWaterStore().flag(
                str(islands), str(waters), str(Path(directory) / "cache"),
                str(report), "china/guangxi",
            )
            output = islands.read_text(encoding="utf-8")
            document = json.loads(report.read_text(encoding="utf-8"))
            flags = (Path(directory) / "cache/in-water-flags.tsv").read_text()
        self.assertEqual(1, result.in_water_count)
        self.assertIn('"in_water":true', output)
        self.assertEqual(hashlib.sha512(water_bytes).hexdigest(), document["summary"]["water_geojsonseq_sha512"])
        self.assertEqual(2, document["inputs"]["island_feature_count"])
        self.assertIn("\t1.000000\t0", flags)
        self.assertTrue(document["checks"]["max_in_water_area_within_limit"])

    def test_empty_island_layer_produces_zero_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            islands = Path(directory) / "island.geojsonseq"
            waters = Path(directory) / "water.geojsonseq"
            islands.write_text("", encoding="utf-8")
            waters.write_text("", encoding="utf-8")
            report = Path(directory) / "report.json"
            result = FileSystemIslandWaterStore().flag(
                str(islands), str(waters), str(Path(directory) / "cache"),
                str(report), "china/guangxi",
            )
            document = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(0, result.in_water_count)
        self.assertEqual([], document["flagged"])
