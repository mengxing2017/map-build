from copy import deepcopy
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
    PlaceAdminExecutionError,
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
        self.assertEqual(8, len(result.features))
        self.assertIn("Alpha Prefecture", output_names)
        self.assertEqual(3, summary["role_member_relations_with_place_candidates"])
        self.assertEqual(0, summary["fallback_canonical_feature_count"])
        self.assertEqual(0, summary["fallback_dropped_count"])
        self.assertEqual(1, summary["exact_duplicate_dropped_count"])
        self.assertEqual(0, summary["same_name_tier_dropped_count"])
        self.assertEqual(0, summary["redundant_role_member_dropped_count"])
        self.assertEqual(1, summary["admin_display_name_override_count"])
        decisions = {item["node_id"]: item for item in result.report["entity_decisions"]}
        self.assertEqual(3, result.report["schema_version"])
        self.assertEqual("node:2", decisions[2]["entity_key"])
        self.assertEqual("no-direct-identity-match", decisions[2]["unresolved_reason"])
        self.assertEqual("retained", decisions[2]["reason"])
        self.assertEqual("retained", decisions[5]["reason"])
        self.assertEqual([6], result.report["dropped_node_ids"])
        self.assertEqual([], result.report["identity_relations_without_kept_point"])
        self.assertTrue(all("@id" not in value["properties"] for value in result.features))

    def test_direct_identity_selection_preserves_parent_seats_and_ambiguous_names(self) -> None:
        def point(node_id, name, place, **properties):
            return {
                "type": "Feature",
                "properties": {"@id": node_id, "name": name, "place": place, **properties},
                "geometry": {"type": "Point", "coordinates": [node_id, 0]},
            }

        features = [
            point(1, "Parent", "state"),
            point(2, "Capital", "city"),
            point(3, "Seat Village", "village"),
            point(4, "Same Entity", "town"),
            point(5, "Same Entity", "town"),
            point(6, "Ambiguous", "town"),
        ]
        relations = (
            AdministrativeRelation(100, 4, (None, None, "Parent", None), None,
                                   ((1, "label"), (2, "admin_centre"))),
            AdministrativeRelation(200, 5, (None, None, "Capital", None), None,
                                   ((2, "label"),)),
            AdministrativeRelation(300, 8, (None, None, "Seat Town", None), None,
                                   ((3, "admin_centre"),)),
            AdministrativeRelation(400, 8, (None, None, "Same Entity", None), "Q400",
                                   ((4, "label"), (5, "admin_centre"))),
            AdministrativeRelation(500, 8, (None, None, "Ambiguous", None), None,
                                   ((6, "label"),)),
            AdministrativeRelation(600, 6, (None, None, "Ambiguous", None), None,
                                   ((6, "admin_centre"),)),
        )

        result = enrich_place_labels(
            features, relations, {4: "Q400", 5: "Q400"}, {}, self.hierarchy
        )
        decisions = {item["node_id"]: item for item in result.report["entity_decisions"]}
        output = {feature["properties"]["name"]: feature for feature in result.features}

        self.assertEqual(3, result.report["schema_version"])
        self.assertEqual(5, len(result.features))
        self.assertEqual(100, output["Parent"]["properties"]["admin_id"])
        self.assertEqual(200, output["Capital"]["properties"]["admin_id"])
        self.assertNotIn("admin_id", output["Seat Village"]["properties"])
        self.assertEqual(200, decisions[2]["identity_relation_id"])
        self.assertEqual([100, 200], decisions[2]["direct_relation_ids"])
        self.assertIsNone(decisions[2]["association_relation_id"])
        self.assertEqual("relation:200", decisions[2]["entity_key"])
        self.assertEqual("node:3", decisions[3]["entity_key"])
        self.assertEqual("no-direct-identity-match", decisions[3]["unresolved_reason"])
        self.assertEqual("entity-canonical-lost", decisions[4]["reason"])
        self.assertEqual(5, decisions[4]["kept_node_id"])
        self.assertEqual("node:6", decisions[6]["entity_key"])
        self.assertEqual("ambiguous-name-match", decisions[6]["unresolved_reason"])
        self.assertEqual([], result.report["identity_relations_without_kept_point"])

    def test_canonical_selection_prefers_fallback_point_with_matching_wikidata(self) -> None:
        def point(node_id, coordinates, **properties):
            return {
                "type": "Feature",
                "properties": {
                    "@id": node_id, "name": "Babu District", "place": "city",
                    **properties,
                },
                "geometry": {"type": "Point", "coordinates": coordinates},
            }

        boundary = [[[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]]
        relation = AdministrativeRelation(
            100, 6, (None, None, "Babu District", None), "Q100",
            ((2, "admin_centre"),),
        )
        result = enrich_place_labels(
            [point(1, [2, 2]), point(2, [8, 8])],
            (relation,), {1: "Q100"}, {100: boundary}, self.hierarchy,
        )
        decisions = {item["node_id"]: item for item in result.report["entity_decisions"]}

        self.assertEqual(1, len(result.features))
        self.assertEqual([2, 2], result.features[0]["geometry"]["coordinates"])
        self.assertEqual("name-boundary-unique", decisions[1]["entity_evidence"])
        self.assertEqual("kept", decisions[1]["outcome"])
        self.assertEqual("entity-canonical-lost", decisions[2]["reason"])
        self.assertEqual(1, decisions[2]["kept_node_id"])
        self.assertEqual([], result.report["identity_relations_without_kept_point"])

    def test_entity_key_keeps_unrelated_same_name_and_selects_unique_boundary_fallback(self) -> None:
        def point(node_id, coordinates, **properties):
            return {
                "type": "Feature", "properties": {
                    "@id": node_id, "name": "Naga", "place": "city", **properties,
                }, "geometry": {"type": "Point", "coordinates": coordinates},
            }

        boundary = [[[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]]
        relation = AdministrativeRelation(20, 6, (None, None, "Naga", None), "Q20", ())
        result = enrich_place_labels(
            [point(1, [1, 1]), point(2, [20, 20], wikidata="Q2")],
            (relation,), {2: "Q2"}, {20: boundary}, self.hierarchy,
        )
        output = {feature["properties"]["name"] for feature in result.features}
        decisions = {item["node_id"]: item for item in result.report["entity_decisions"]}
        self.assertEqual({"Naga"}, output)
        self.assertEqual(2, len(result.features))
        self.assertEqual("relation:20", decisions[1]["entity_key"])
        self.assertEqual(20, decisions[1]["admin_id"])
        self.assertEqual("wd:Q2", decisions[2]["entity_key"])
        self.assertEqual([], result.report["dropped_node_ids"])

    def test_conventional_region_filter_reports_only_when_no_evidence_exists(self) -> None:
        feature = {
            "type": "Feature",
            "properties": {"@id": 1, "name": "Yuebei", "place": "region"},
            "geometry": {"type": "Point", "coordinates": [20, 20]},
        }
        relation = AdministrativeRelation(20, 5, (None, None, "Guangdong", None), None, ())
        report_hierarchy = deepcopy(self.hierarchy)
        report_hierarchy["conventional_region_filter"]["action"] = "report_only"
        result = enrich_place_labels(
            [feature], (relation,), {}, {99: [[[[0, 0], [1, 0], [0, 0]]]]}, report_hierarchy
        )
        candidate = result.report["conventional_region_candidates"]
        self.assertEqual(1, len(result.features))
        self.assertEqual("reported", candidate[0]["outcome"])
        self.assertEqual("no-admin-evidence", candidate[0]["reason"])
        self.assertEqual(1, result.report["summary"]["conventional_region_candidate_count"])

    def test_conventional_region_filter_keeps_a1_a2_and_a3_evidence(self) -> None:
        def point(node_id, name, coordinates, **properties):
            return {
                "type": "Feature",
                "properties": {"@id": node_id, "name": name, "place": "region", **properties},
                "geometry": {"type": "Point", "coordinates": coordinates},
            }

        boundary = [[[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]]
        relations = (
            AdministrativeRelation(20, 5, (None, None, "Qid Province", None), "Q20", ()),
            AdministrativeRelation(21, 5, (None, None, "Tianjin City", None), None, ()),
        )
        result = enrich_place_labels(
            [
                point(1, "Different", [20, 20]),
                point(2, "Tianjin", [2, 2]),
                point(3, "Population Province", [20, 20], population=1),
            ],
            relations,
            {1: "Q20"},
            {20: boundary, 21: boundary},
            self.hierarchy,
        )
        self.assertEqual(3, len(result.features))
        self.assertEqual([], result.report["conventional_region_candidates"])

    def test_conventional_region_filter_keeps_candidate_when_matching_boundary_missing(self) -> None:
        feature = {
            "type": "Feature",
            "properties": {"@id": 1, "name": "Alpha", "place": "region"},
            "geometry": {"type": "Point", "coordinates": [2, 2]},
        }
        relations = (
            AdministrativeRelation(20, 5, (None, None, "Alpha City", None), None, ()),
            AdministrativeRelation(21, 5, (None, None, "Other", None), None, ()),
        )
        result = enrich_place_labels(
            [feature], relations, {}, {21: [[[[0, 0], [1, 0], [0, 0]]]]}, self.hierarchy
        )
        candidate = result.report["conventional_region_candidates"][0]
        self.assertEqual("boundary-coverage-incomplete", candidate["reason"])
        self.assertEqual("kept", candidate["outcome"])
        self.assertEqual(1, len(result.features))

    def test_conventional_region_filter_drops_historical_local_name_with_shared_english_name(self) -> None:
        feature = {
            "type": "Feature",
            "properties": {
                "@id": 1,
                "name": "Tongren Prefecture",
                "name:zh": "铜仁地区",
                "name:en": "Tongren",
                "place": "region",
            },
            "geometry": {"type": "Point", "coordinates": [2, 2]},
        }
        boundary = [[[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]]
        relation = AdministrativeRelation(
            20, 5, ("铜仁市", "铜仁市", "铜仁市", "Tongren"), None, ()
        )
        result = enrich_place_labels([feature], (relation,), {}, {20: boundary}, self.hierarchy)
        self.assertEqual((), result.features)
        self.assertEqual(
            "dropped", result.report["conventional_region_candidates"][0]["outcome"]
        )

    def test_conventional_region_filter_skips_empty_boundary_index_and_keep_names(self) -> None:
        feature = {
            "type": "Feature",
            "properties": {"@id": 1, "name": "Yuebei", "place": "region"},
            "geometry": {"type": "Point", "coordinates": [20, 20]},
        }
        skipped = enrich_place_labels([feature], (), {}, {}, self.hierarchy)
        self.assertEqual("boundary-index-empty", skipped.report["conventional_region_skipped_reason"])
        self.assertEqual([], skipped.report["conventional_region_candidates"])

        kept_hierarchy = deepcopy(self.hierarchy)
        kept_hierarchy["conventional_region_filter"]["keep_names"] = ["Yuebei"]
        kept = enrich_place_labels(
            [feature], (), {}, {99: [[[[0, 0], [1, 0], [0, 0]]]]}, kept_hierarchy
        )
        self.assertEqual([], kept.report["conventional_region_candidates"])

    def test_conventional_region_filter_drop_demote_and_limit(self) -> None:
        feature = {
            "type": "Feature",
            "properties": {"@id": 1, "name": "Yuebei", "place": "region"},
            "geometry": {"type": "Point", "coordinates": [20, 20]},
        }
        boundaries = {99: [[[[0, 0], [1, 0], [0, 0]]]]}
        drop_hierarchy = deepcopy(self.hierarchy)
        drop_hierarchy["conventional_region_filter"]["action"] = "drop"
        dropped = enrich_place_labels([feature], (), {}, boundaries, drop_hierarchy)
        self.assertEqual((), dropped.features)
        self.assertEqual(1, dropped.report["summary"]["conventional_region_dropped_count"])

        demote_hierarchy = deepcopy(self.hierarchy)
        demote_hierarchy["conventional_region_filter"]["action"] = "demote"
        demoted = enrich_place_labels([feature], (), {}, boundaries, demote_hierarchy)
        self.assertEqual("locality", demoted.features[0]["properties"]["label_tier"])
        self.assertEqual({"minzoom": 11}, demoted.features[0]["tippecanoe"])
        self.assertEqual(1, demoted.report["summary"]["conventional_region_demoted_count"])

        limited_hierarchy = deepcopy(self.hierarchy)
        limited_hierarchy["conventional_region_filter"]["max_candidates"] = 1
        with self.assertRaises(PlaceAdminExecutionError):
            enrich_place_labels([feature, {**feature, "properties": {
                **feature["properties"], "@id": 2, "name": "Yuebei East",
            }}], (), {}, boundaries, limited_hierarchy)
