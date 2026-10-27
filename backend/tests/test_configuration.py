from local_extract_fixture import local_extract_repository
from copy import deepcopy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import build_configuration_service, repository_root
from huavd_map_build.catalog.domain.configuration import (
    BuildConfigurationError,
    apply_tier_profile,
    inspect_layer_export_contracts,
    resolve_tippecanoe,
    resolve_vector_layers,
    validate_tile_feature_limit,
)
from huavd_map_build.catalog.south.adapter.yaml.loader import (
    PyYamlConfigurationRepository,
)
from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService


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
        self.assertEqual(200000, result["maximum_tile_features"])

    def test_feature_budget_survives_region_and_country_profiles(self) -> None:
        for region in ("china/sichuan", "china/guangxi", "china/shanghai", "china"):
            with self.subTest(region=region):
                self.assertEqual(1000000, self.configuration.tippecanoe(region, "base")["maximum_tile_features"])

    def test_invalid_feature_budget_is_rejected_after_every_override(self) -> None:
        root = repository_root(Path(__file__))
        original = PyYamlConfigurationRepository(root / "config")
        for value in (None, 0, -1, True, "1000000", 1.5, 10000001):
            with self.subTest(value=value):
                document = original.load("tippecanoe")
                document["high_density"].append({"region_match": "china", "maximum_tile_features": value})
                with self.assertRaisesRegex(BuildConfigurationError, "tippecanoe.yaml.*maximum_tile_features"):
                    resolve_tippecanoe(document, "china", "base")
                tier = original.load("tier-profiles")
                tier["profiles"]["country-low"]["tippecanoe"]["maximum_tile_features"] = value

                class Repository:
                    def load(self, name):
                        return tier if name == "tier-profiles" else original.load(name)

                with self.assertRaisesRegex(BuildConfigurationError, "maximum_tile_features"):
                    BuildConfigurationService(Repository()).tippecanoe("china", "base")
        with self.assertRaisesRegex(BuildConfigurationError, "maximum_tile_features"):
            validate_tile_feature_limit({})

    def test_locked_jq_rejects_invalid_raw_and_effective_feature_limits(self) -> None:
        root = repository_root(Path(__file__))
        locked = root / ".devbox/nix/profile/default/bin"
        for value in (None, 0, -1, True, "1000000", 1.5, 10000001):
            for effective in (False, True):
                with self.subTest(value=value, effective=effective), tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "settings.json"
                    if effective:
                        path.write_text(json.dumps({"tippecanoe": {"maximum_tile_features": value}}))
                        command = '''set -euo pipefail
source scripts/lib/config.sh
tippecanoe_resolve() { printf '%s\\n' '{"maximum_tile_features":1000000}'; }
effective_build_profile() { printf '%s\\n' country-low; }
tier_profile_json() { cat "$HUAVD_TEST_SETTINGS"; }
effective_tippecanoe_resolve china base
'''
                    else:
                        settings = PyYamlConfigurationRepository(root / "config").load("tippecanoe")
                        settings["defaults"]["high_density_baseline"]["maximum_tile_features"] = value
                        path.write_text(json.dumps(settings))
                        command = '''set -euo pipefail
source scripts/lib/config.sh
tippecanoe_json() { printf '%s\\n' "$HUAVD_TEST_SETTINGS"; }
tippecanoe_resolve china/sichuan base
'''
                    result = subprocess.run(["bash", "-c", command], cwd=root, capture_output=True, text=True,
                        env={**os.environ, "PATH": f"{locked}:{os.environ['PATH']}", "WORKDIR": directory,
                             "HUAVD_TEST_SETTINGS": str(path)}, timeout=30, check=False)
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn("maximum_tile_features", result.stderr)

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
        self.assertEqual("drop", china["conventional_region_filter"]["action"])
        self.assertEqual([2, 4, 5, 6], china["conventional_region_filter"]["admin_evidence_levels"])


class StandardZ19ConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(local_extract_repository(repository_root(Path(__file__))))
        self.configuration = build_configuration_service(self.root)
        self.repository = PyYamlConfigurationRepository(self.root / "config")

    def test_pilot_role_isolation_and_legacy_profiles(self):
        pilot = "china/guangxi/test-extract"
        base = self.configuration.tippecanoe(pilot, "base")
        self.assertEqual(19, base["max_zoom"])
        self.assertFalse(base["extend_zooms_if_still_dropping"])
        self.assertNotIn("roles", base)
        self.assertEqual(18, self.configuration.tippecanoe(pilot, "building")["max_zoom"])
        self.assertEqual(14, self.configuration.tippecanoe("china/guangxi", "base")["max_zoom"])
        self.assertEqual(10, self.configuration.tippecanoe("china", "base")["max_zoom"])
        self.assertEqual(14, self.configuration.tippecanoe("china/shanghai", "base")["max_zoom"])
        layers = {layer["id"]: layer for layer in self.configuration.vector_layers(pilot, "base")}
        for name in ("road", "building", "water", "waterway", "island", "place_label"):
            self.assertEqual(19, layers[name]["maxzoom"])
        self.assertEqual(8, layers["admin"]["maxzoom"])
        self.assertEqual(15, layers["admin_line"]["maxzoom"])
        self.assertEqual("standard-z19", self.configuration.profile_transform(pilot)["name"])

    def test_local_raster_override_keeps_other_regions_at_legacy_zoom(self):
        from huavd_map_build.production.domain.raster import RasterBounds, create_raster_tile_plan
        settings = self.configuration.raster_bake("china/guangxi/test-extract")
        self.assertEqual(19, settings["max_zoom"])
        self.assertEqual(2, settings["native_parallel_jobs"])
        self.assertEqual(40000, settings["max_tiles"])
        self.assertEqual(14, self.configuration.raster_bake("china/guangxi")["max_zoom"])
        bounds = RasterBounds(110.2877168,25.214619,110.3996555,25.309026)
        plan = create_raster_tile_plan(bounds, settings["min_zoom"], settings["max_zoom"],
                                       settings["bbox_padding_tiles"], settings["max_tiles"])
        self.assertEqual(35060, plan.tile_count)

    def test_override_validation_and_order(self):
        original = self.repository.load("tippecanoe")
        for roles in ([], ["dem"], "base", ["base", "base"], [True]):
            document = deepcopy(original)
            document["high_density"][0]["roles"] = roles
            with self.subTest(roles=roles), self.assertRaises(BuildConfigurationError):
                resolve_tippecanoe(document, "unmatched", "base")
        for zoom in (-1, 25, True, 19.5):
            document = deepcopy(original)
            document["high_density"][0]["max_zoom"] = zoom
            with self.subTest(zoom=zoom), self.assertRaises(BuildConfigurationError):
                resolve_tippecanoe(document, "china/guangxi/test-extract", "base")
        original["high_density"].append({"region_match": "china/guangxi/*", "roles": ["base"], "max_zoom": 18})
        self.assertEqual(18, resolve_tippecanoe(original, "china/guangxi/test-extract", "base")["max_zoom"])

    def test_zoom_profile_rejects_unknown_layer_or_range(self):
        tippecanoe = self.configuration.tippecanoe("china/guangxi/test-extract", "base")
        layers = self.repository.load("layers")
        for value in ({"missing": {"maxzoom": 19}}, {"road": {"maxzoom": True}}, {"road": {"maxzoom": 25}}, {"road": {"maxzoom": 1, "minzoom": 2}}):
            changed = deepcopy(layers)
            changed["zoom_profiles"]["standard-z19"] = value
            with self.subTest(value=value), self.assertRaises(BuildConfigurationError):
                resolve_vector_layers(tippecanoe, self.repository.load("tier-profiles"), changed, "china/guangxi/test-extract", "base", 19)


    def test_local_extract_requires_explicit_input_and_retains_parent_provenance(self):
        from huavd_map_build.bootstrap import build_planner, catalog_service
        from huavd_map_build.shared.kernel import RegionId, BuildDate
        region = RegionId("china/guangxi/test-extract")
        catalog = catalog_service(self.root)
        self.assertIn("guangxi-latest.osm.pbf", catalog.source_pbf_url(region))
        with self.assertRaisesRegex(ValueError, "lacks geofabrik.pbf_url"):
            catalog.pbf_url(region)
        with self.assertRaisesRegex(ValueError, "requires explicit INPUT"):
            build_planner(self.root).plan(region=region, build_date=BuildDate("20261003"), role="base", workdir=Path("/tmp/maps"))


    def test_shell_resolver_matches_python_with_locked_jq(self):
        import json
        import os
        import subprocess
        import tempfile
        cases = [("china/guangxi/test-extract", "base"), ("china/guangxi/test-extract", "building"), ("china/guangxi", "base"), ("china", "base"), ("china/shanghai", "base")]
        commands = ["source scripts/lib/config.sh"]
        commands.extend(f"effective_tippecanoe_resolve {region} {role}" for region, role in cases)
        commands.append("effective_vector_layers_json china/guangxi/test-extract base 19")
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(["bash", "-c", "\n".join(commands)], cwd=self.root,
                env={**os.environ, "WORKDIR": directory, "PATH": f"{self.root}/.devbox/nix/profile/default/bin:" + os.environ["PATH"]},
                text=True, capture_output=True, check=True, timeout=90)
        decoder = json.JSONDecoder()
        documents = []
        output = result.stdout.lstrip()
        while output:
            document, end = decoder.raw_decode(output)
            documents.append(document)
            output = output[end:].lstrip()
        for (region, role), actual in zip(cases, documents, strict=False):
            self.assertEqual(self.configuration.tippecanoe(region, role), actual)
        self.assertEqual(self.configuration.vector_layers(cases[0][0], "base", 19), documents[-1])
