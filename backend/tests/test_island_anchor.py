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


CRESCENT_RING = [
    [9.6710122, 47.3934517], [9.6718326, 47.393037], [9.6724204, 47.3926024],
    [9.6730196, 47.3919551], [9.6735272, 47.3912648], [9.6737779, 47.3908217],
    [9.6740396, 47.3901463], [9.6740943, 47.3894181], [9.6740963, 47.3890698],
    [9.674135, 47.3890455], [9.6741732, 47.3890671], [9.6741835, 47.389422],
    [9.6741123, 47.3901477], [9.6738566, 47.3908369], [9.6736235, 47.3913084],
    [9.6731097, 47.3919996], [9.6724873, 47.3926527], [9.6718697, 47.3930744],
    [9.6710426, 47.3934911], [9.6710122, 47.3934517],
]


def inside(ring, point):
    crossings = 0
    for index, first in enumerate(ring):
        second = ring[(index + 1) % len(ring)]
        if (first[1] > point[1]) != (second[1] > point[1]):
            if point[0] < (
                (second[0] - first[0]) * (point[1] - first[1])
                / (second[1] - first[1]) + first[0]
            ):
                crossings += 1
    return crossings % 2 == 1


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

    def test_thin_crescent_is_anchored_inside(self) -> None:
        anchor, tier = derive_island_anchor(polygon_feature([CRESCENT_RING]))
        point = anchor["geometry"]["coordinates"]
        self.assertEqual("grid", tier)
        self.assertNotEqual(CRESCENT_RING[0], point)
        self.assertTrue(inside(CRESCENT_RING, point))

    def test_zero_area_ring_keeps_vertex_fallback(self) -> None:
        ring = [[0, 0], [1, 0], [2, 0], [0, 0]]
        anchor, tier = derive_island_anchor(polygon_feature([ring]))
        self.assertEqual("vertex", tier)
        self.assertEqual([0, 0], anchor["geometry"]["coordinates"])


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

    def test_thin_crescent_reports_no_vertex_tier(self) -> None:
        ring = CRESCENT_RING
        records = [polygon_feature([ring], {"place": "island"})]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "island.geojsonseq"
            source.write_text(
                "".join("\x1e" + json.dumps(item) + "\n" for item in records),
                encoding="utf-8",
            )
            report = Path(directory) / "island_anchor_report.json"
            result = FileSystemIslandAnchorStore().derive(
                str(source), str(Path(directory) / "cache"), str(report),
                "switzerland",
            )
            document = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(
            {"centroid": 0, "grid": 1, "vertex": 0}, result.tier_counts
        )
        self.assertEqual(0, document["summary"]["tier"]["vertex"])

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
