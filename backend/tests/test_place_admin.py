import unittest

from huavd_map_build.bootstrap import build_configuration_service, repository_root
from huavd_map_build.production.domain.place_admin import (
    AdministrativeRelation,
    apply_admin_display_name,
    apply_label_rendering,
    common_prefix_length,
    display_name_allowed,
    name_key,
    numeric_feature_id,
    opl_decode,
    point_in_multipolygon,
    population,
    enrich_place_labels,
)


class PlaceAdminDomainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hierarchy = build_configuration_service(
            repository_root()
        ).place_label_hierarchy("china/guangxi")

    def test_opl_and_relation_name_decode_utf8_percent_bytes(self) -> None:
        encoded = "%E6%B5%8B%E8%AF%95"
        relation = AdministrativeRelation(1, 4, (None, "测试", None, None), None, ())
        self.assertEqual("测试", opl_decode(encoded))
        self.assertEqual("测试", relation.display_name())

    def test_xml_relation_name_does_not_decode_literal_percent_sequence(self) -> None:
        relation = AdministrativeRelation(1, 4, (None, None, "Route %41", None), None, ())
        self.assertEqual("Route %41", relation.display_name())

    def test_feature_helpers_match_jq_coercion_and_name_priority(self) -> None:
        feature = {"properties": {"@id": "42", "population": "123.9",
                                  "name": " fallback ", "name:zh": " 中文 "}}
        self.assertEqual("中文", name_key(feature["properties"]))
        self.assertEqual(42, numeric_feature_id(feature))
        self.assertEqual(123.9, population(feature))
        self.assertEqual(0, population({"properties": {"population": -3}}))

    def test_prefix_and_display_name_gate_match_contract(self) -> None:
        self.assertEqual(2, common_prefix_length("广西省", "广西壮族自治区"))
        self.assertTrue(display_name_allowed("广西省", "广西壮族自治区"))
        self.assertFalse(display_name_allowed("广西", "Guangxi/广西"))
        self.assertFalse(display_name_allowed("自治州", "州"))

    def test_point_in_multipolygon_respects_holes(self) -> None:
        polygon = [[[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                    [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]]
        self.assertTrue(point_in_multipolygon([2, 2], polygon))
        self.assertFalse(point_in_multipolygon([5, 5], polygon))
        self.assertFalse(point_in_multipolygon([20, 20], polygon))

    def test_label_rendering_sets_rank_zoom_and_clamps_population(self) -> None:
        feature = {"properties": {"place": "city", "population": 2_000_000_000}}
        apply_label_rendering(feature, "prefecture", self.hierarchy)
        self.assertEqual("prefecture", feature["properties"]["label_tier"])
        self.assertEqual(400_999_999_999, feature["properties"]["label_rank"])
        self.assertEqual({"minzoom": 5, "maxzoom": 11}, feature["tippecanoe"])

    def test_admin_display_name_updates_all_configured_local_fields(self) -> None:
        feature = {"properties": {"name": "龙胜县", "official_name": "龙胜各族自治县"}}
        changed = apply_admin_display_name(
            feature, "county", self.hierarchy["admin_display_name"]
        )
        self.assertTrue(changed)
        for field in ("name:zh-Hans", "name:zh", "name"):
            self.assertEqual("龙胜各族自治县", feature["properties"][field])

    def test_complete_selection_fallback_dedup_and_audit(self) -> None:
        def point(node_id, name, place, population_value=0, coordinates=None, **extra):
            properties = {
                "@id": node_id, "name": name, "place": place,
                "population": population_value, **extra,
            }
            return {"type": "Feature", "properties": properties,
                    "geometry": {"type": "Point", "coordinates": coordinates or [node_id, 0]}}

        features = [
            point(1, "Alpha", "city", 100, official_name="Alpha Prefecture"),
            point(2, "Alpha City", "city", 200),
            point(3, "Beta", "city", 10),
            point(4, "Beta", "city", 20),
            point(5, "Alpha", "city", 50),
            point(6, "Delta", "village", 10, coordinates=[6, 6]),
            point(7, "Delta", "village", 20, coordinates=[6, 6]),
            point(8, "Gamma", "region", 30),
            point(9, "Gamma", "region", 20),
        ]
        relations = (
            AdministrativeRelation(100, 5, (None, None, "Alpha", None), "Q100",
                                   ((1, "admin_centre"), (2, "label"))),
            AdministrativeRelation(200, 6, (None, None, "Other", None), None,
                                   ((1, "label"),)),
            AdministrativeRelation(300, 6, (None, None, "Beta", None), None, ()),
            AdministrativeRelation(400, 5, (None, None, "Gamma", None), None,
                                   ((8, "admin_centre"),)),
        )
        result = enrich_place_labels(
            features, relations, {5: "Q100"}, {}, self.hierarchy
        )
        output_names = [value["properties"]["name"] for value in result.features]
        summary = result.report["summary"]
        self.assertEqual(4, len(result.features))
        self.assertIn("Alpha Prefecture", output_names)
        self.assertEqual(3, summary["role_member_relations_with_place_candidates"])
        self.assertEqual(1, summary["fallback_canonical_feature_count"])
        self.assertEqual(2, summary["fallback_dropped_count"])
        self.assertEqual(1, summary["exact_duplicate_dropped_count"])
        self.assertEqual(1, summary["same_name_tier_dropped_count"])
        self.assertEqual(1, summary["redundant_role_member_dropped_count"])
        self.assertEqual(1, summary["admin_display_name_override_count"])
        self.assertEqual(
            [{"node_id": 1, "selected_admin_id": 100, "discarded_admin_ids": [200]}],
            result.report["shared_member_choices"],
        )
        self.assertTrue(all("@id" not in value["properties"] for value in result.features))
