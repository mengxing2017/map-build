import json
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.production.domain.normalize import (
    NormalizationPolicy,
    normalize_feature,
)
from huavd_map_build.production.south.adapter.workspace.normalize import (
    FileSystemGeoJsonSeqNormalizer,
)


def feature(properties, geometry=None):
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": geometry or {"type": "Point", "coordinates": [1, 2]},
    }


class NormalizeFeatureTest(unittest.TestCase):
    def test_coalesces_and_cleans_bilingual_name_then_drops_unknown_fields(self) -> None:
        policy = NormalizationPolicy(
            "road", ("name:zh-Hans", "name"), ("name", "name:en"), {}
        )
        result = normalize_feature(
            feature({"name": "桂林 Guilin", "name:en": "Guilin", "source": "x"}),
            policy,
        )
        self.assertEqual({"name": "桂林", "name:en": "Guilin"}, result["properties"])

    def test_post_filter_excludes_property_and_geometry_mismatches(self) -> None:
        policy = NormalizationPolicy(
            "water", ("name",), ("name", "place"),
            {"exclude": {"place": ["island"]}, "geometry": ["Polygon"]},
        )
        self.assertIsNone(normalize_feature(feature({"place": "island"}), policy))
        self.assertIsNone(normalize_feature(feature({"name": "lake"}), policy))

    def test_converts_numbers_and_centers_area_labels(self) -> None:
        number_policy = NormalizationPolicy(
            "waterway", ("name",), ("name", "width"), {}
        )
        converted = normalize_feature(feature({"width": "12.5"}), number_policy)
        self.assertEqual(12.5, converted["properties"]["width"])
        area_policy = NormalizationPolicy(
            "poi_label", ("name",), ("name", "amenity"), {}
        )
        polygon = {
            "type": "Polygon",
            "coordinates": [[[1, 2], [5, 8], [3, 4], [1, 2]]],
        }
        centered = normalize_feature(feature({"amenity": "hospital"}, polygon), area_policy)
        self.assertEqual(
            {"type": "Point", "coordinates": [3.0, 5.0]}, centered["geometry"]
        )

    def test_converts_configured_final_field_types(self) -> None:
        policy = NormalizationPolicy(
            "road", ("name",), ("layer", "bridge", "oneway", "name"), {},
            {"layer": "Number", "bridge": "Boolean", "oneway": "Boolean"},
        )
        result = normalize_feature(feature({
            "layer": "-2", "bridge": "yes", "oneway": "-1", "name": "road",
        }), policy)
        self.assertEqual(-2, result["properties"]["layer"])
        self.assertIs(result["properties"]["bridge"], True)
        self.assertIs(result["properties"]["oneway"], True)

    def test_drops_invalid_configured_number_and_boolean_values(self) -> None:
        policy = NormalizationPolicy(
            "road", ("name",), ("layer", "bridge"), {},
            {"layer": "Number", "bridge": "Boolean"},
        )
        result = normalize_feature(
            feature({"layer": "ground", "bridge": "sometimes"}), policy
        )
        self.assertEqual({}, result["properties"])

    def test_building_fallback_only_replaces_null_not_empty_string(self) -> None:
        policy = NormalizationPolicy(
            "building", ("name",), ("type", "levels", "roof_height"), {}
        )
        result = normalize_feature(
            feature({"type": "", "building": "yes", "building:levels": "4"}), policy
        )
        self.assertEqual("", result["properties"]["type"])
        self.assertEqual("4", result["properties"]["levels"])


class GeoJsonSeqNormalizerTest(unittest.TestCase):
    def test_streams_records_and_rotates_original_to_backup(self) -> None:
        policy = NormalizationPolicy("road", ("name",), ("name",), {})
        records = [feature({"name": "first", "drop": 1}), feature({"name": "second"})]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "road.geojsonseq"
            original = "".join(
                "\x1e" + json.dumps(item, separators=(",", ":")) + "\n"
                for item in records
            )
            path.write_text(original, encoding="utf-8")
            FileSystemGeoJsonSeqNormalizer().normalize(str(path), policy)
            self.assertEqual(original, Path(f"{path}.bak").read_text(encoding="utf-8"))
            output = path.read_text(encoding="utf-8")
            self.assertEqual(2, output.count("\x1e"))
            self.assertNotIn("drop", output)

    def test_invalid_record_preserves_source_and_removes_temporary_file(self) -> None:
        policy = NormalizationPolicy("road", ("name",), ("name",), {})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "road.geojsonseq"
            path.write_text("\x1e{invalid}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid GeoJSONSeq"):
                FileSystemGeoJsonSeqNormalizer().normalize(str(path), policy)
            self.assertEqual("\x1e{invalid}\n", path.read_text(encoding="utf-8"))
            self.assertFalse(Path(f"{path}.tmp").exists())
            self.assertFalse(Path(f"{path}.bak").exists())
