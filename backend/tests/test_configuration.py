from copy import deepcopy
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import build_configuration_service, repository_root
from huavd_map_build.catalog.domain.configuration import (
    BuildConfigurationError,
    apply_tier_profile,
    inspect_layer_export_contracts,
)
from huavd_map_build.catalog.south.adapter.yaml.loader import (
    PyYamlConfigurationRepository,
)


class BuildConfigurationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = repository_root(Path(__file__))
        cls.configuration = build_configuration_service(root)

    def test_tippecanoe_building_overrides_defaults(self) -> None:
        result = self.configuration.tippecanoe("china/guangxi", "building")
        self.assertEqual(12, result["min_zoom"])
        self.assertEqual(18, result["max_zoom"])
        self.assertEqual(["building"], result["source_layers"])
        self.assertEqual("building", result["output_role"])

    def test_tippecanoe_high_density_region_overrides_baseline(self) -> None:
        result = self.configuration.tippecanoe("china/shanghai", "base")
        self.assertEqual(14, result["max_zoom"])
        self.assertEqual(2097152, result["maximum_tile_bytes"])
        self.assertEqual(
            "levels * 3 + 1 meters when height is absent",
            result["building_height_derivation"],
        )

    def test_raster_bake_pattern_matches_child_region(self) -> None:
        result = self.configuration.raster_bake("japan/tokyo-tokyo")
        self.assertEqual(16, result["parallel_jobs"])
        self.assertEqual("webp", result["encoding"])

    def test_country_tier_profile_overrides_base_settings(self) -> None:
        result = self.configuration.tippecanoe("china", "base")
        self.assertEqual(10, result["max_zoom"])
        self.assertEqual(1572864, result["maximum_tile_bytes"])
        self.assertFalse(result["extend_zooms_if_still_dropping"])
        self.assertTrue(result["simplify_only_low_zooms"])
        self.assertNotIn("building", result["source_layers"])

    def test_invalid_tier_profile_rejects_unknown_layer(self) -> None:
        tier = {
            "regions": {"test": {"build_profile": "bad"}},
            "profiles": {
                "bad": {
                    "min_zoom": 0,
                    "max_zoom": 10,
                    "maximum_tile_bytes": 1,
                    "extend_zooms_if_still_dropping": False,
                    "source_layers": ["missing"],
                }
            },
        }
        with self.assertRaisesRegex(BuildConfigurationError, "unknown layer"):
            apply_tier_profile({}, tier, {"source_layers": {}}, "test", "base")

    def test_country_vector_layers_follow_profile_rules(self) -> None:
        layers = self.configuration.vector_layers("china", "base", 10)
        by_id = {layer["id"]: layer for layer in layers}
        self.assertEqual(11, len(layers))
        self.assertNotIn("building", by_id)
        self.assertEqual(0, by_id["place_label"]["minzoom"])
        self.assertEqual(10, by_id["place_label"]["maxzoom"])
        self.assertEqual(8, by_id["admin"]["maxzoom"])

    def test_building_vector_layer_uses_role_zoom_range(self) -> None:
        layers = self.configuration.vector_layers("china/guangxi", "building", 18)
        self.assertEqual(1, len(layers))
        self.assertEqual("building", layers[0]["id"])
        self.assertEqual(12, layers[0]["minzoom"])
        self.assertEqual(18, layers[0]["maxzoom"])

    def test_real_cross_configuration_is_valid(self) -> None:
        summary = self.configuration.validate()
        self.assertEqual(17, summary.layer_count)
        self.assertEqual(1, summary.tier_profile_count)
        self.assertEqual(
            {"layers": "1", "tippecanoe": "1", "tier-profiles": "1", "bake": "1"},
            dict(summary.schema_versions),
        )

    def test_real_layer_and_export_contracts_are_consistent(self) -> None:
        root = repository_root(Path(__file__))
        repository = PyYamlConfigurationRepository(root / "config")
        layers = repository.load("layers")
        exports = {
            name: repository.load_export(name)
            for name in layers["source_layers"]
        }
        self.assertEqual((), inspect_layer_export_contracts(layers, exports))

    def test_layer_export_contract_reports_independent_configuration_drift(self) -> None:
        root = repository_root(Path(__file__))
        repository = PyYamlConfigurationRepository(root / "config")
        layers = repository.load("layers")
        exports = {
            name: repository.load_export(name)
            for name in layers["source_layers"]
        }
        changed_layers = deepcopy(layers)
        changed_exports = deepcopy(exports)
        changed_layers["source_layers"]["road"]["final_fields"]["phantom"] = "String"
        changed_exports["road"]["include_tags"].remove("ref")
        changed_exports["water"]["area_tags"] = ["water"]
        findings = inspect_layer_export_contracts(changed_layers, changed_exports)
        codes = {(item.code, item.layer) for item in findings}
        self.assertIn(("config-final-field", "road"), codes)
        self.assertIn(("export-config-tags", "road"), codes)
        self.assertIn(("config-required-field", "road"), codes)
        self.assertIn(("export-config-area", "water"), codes)

    def test_tags_filter_layers_preserve_configuration_and_explicit_order(self) -> None:
        all_layers = self.configuration.tags_filter_layers("all")
        selected = self.configuration.tags_filter_layers("water,road,,building")
        self.assertEqual("road", all_layers[0][0])
        self.assertEqual(["water", "road", "building"], [item[0] for item in selected])
        self.assertTrue(all(item[1] for item in selected))

    def test_tags_filter_layers_reject_unknown_layer(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown layer: missing"):
            self.configuration.tags_filter_layers("road,missing")

    def test_export_layers_resolve_keep_untagged_flag(self) -> None:
        result = dict(self.configuration.export_layers("road,admin_line"))
        self.assertFalse(result["road"])
        self.assertTrue(result["admin_line"])

    def test_place_label_hierarchy_selects_region_display_policy(self) -> None:
        china = self.configuration.place_label_hierarchy("china/guangxi")
        japan = self.configuration.place_label_hierarchy("japan/kanto")
        self.assertEqual("country", china["boundary_tier"]["2"])
        self.assertEqual({"minzoom": 5, "maxzoom": 11}, china["tier_zoom"]["prefecture"])
        self.assertTrue(china["admin_display_name"]["enabled"])
        self.assertEqual(["name"], japan["admin_display_name"]["target_fields"])
        self.assertFalse(japan["admin_display_name"]["enabled"])
