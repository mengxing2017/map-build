import json
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.production.domain.island_anchor import derive_island_anchor
from huavd_map_build.production.south.adapter.workspace.island_anchor import (
    FileSystemIslandAnchorStore,
)


def polygon_feature(coordinates, properties=None, geometry_type="Polygon"):
    return {
        "type": "Feature",
        "geometry": {"type": geometry_type, "coordinates": coordinates},
        "properties": properties or {},
    }


class IslandAnchorDomainTest(unittest.TestCase):
    def test_square_uses_centroid_and_removes_water_derivation(self) -> None:
        ring = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
        result = derive_island_anchor(
            polygon_feature([ring], {"name": "Island", "in_water": True})
        )
        anchor, tier = result
        self.assertEqual("centroid", tier)
        self.assertEqual([1.0, 1.0], anchor["geometry"]["coordinates"])
        self.assertNotIn("in_water", anchor["properties"])
        self.assertEqual(49106.4, anchor["properties"]["island_area_km2"])

    def test_centroid_inside_hole_falls_back_to_grid(self) -> None:
        outer = [[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]]
        hole = [[3, 3], [5, 3], [5, 5], [3, 5], [3, 3]]
        anchor, tier = derive_island_anchor(polygon_feature([outer, hole]))
        self.assertEqual("grid", tier)
        self.assertNotEqual([4.0, 4.0], anchor["geometry"]["coordinates"])

    def test_non_polygon_is_ignored(self) -> None:
        value = polygon_feature([1, 2], geometry_type="Point")
        self.assertIsNone(derive_island_anchor(value))


class IslandAnchorStoreTest(unittest.TestCase):
    def test_appends_anchor_and_writes_audit_files(self) -> None:
        ring = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
        records = [
            polygon_feature([ring], {"name": "Island"}),
            polygon_feature([1, 1], {"name": "Existing"}, "Point"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "island.geojsonseq"
            source.write_text(
                "".join("\x1e" + json.dumps(item) + "\n" for item in records),
                encoding="utf-8",
            )
            cache = Path(directory) / "cache"
            report = Path(directory) / "island_anchor_report.json"
            result = FileSystemIslandAnchorStore().derive(
                str(source), str(cache), str(report), "china/guangxi"
            )
            output = source.read_text(encoding="utf-8")
            document = json.loads(report.read_text(encoding="utf-8"))
            clean = (cache / "anchors.geojsonseq").read_text(encoding="utf-8")
            raw = (cache / "anchors.raw.geojsonseq").read_text(encoding="utf-8")
        self.assertEqual(1, result.anchor_count)
        self.assertEqual(1, result.point_feature_count_before)
        self.assertEqual(3, output.count("\x1e"))
        self.assertNotIn("_anchor_tier", clean)
        self.assertIn("_anchor_tier", raw)
        self.assertTrue(document["checks"]["anchor_count_equals_polygon_count"])

    def test_no_polygon_leaves_layer_unchanged(self) -> None:
        point = polygon_feature([1, 1], geometry_type="Point")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "island.geojsonseq"
            original = "\x1e" + json.dumps(point) + "\n"
            source.write_text(original, encoding="utf-8")
            result = FileSystemIslandAnchorStore().derive(
                str(source), str(Path(directory) / "cache"),
                str(Path(directory) / "report.json"), "china/guangxi",
            )
            self.assertEqual(original, source.read_text(encoding="utf-8"))
        self.assertEqual(0, result.polygon_count)
