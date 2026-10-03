import unittest
from pathlib import Path

from huavd_map_build.bootstrap import catalog_service, repository_root
from huavd_map_build.shared.kernel import RegionId


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))
        cls.catalog = catalog_service(cls.root)

    def test_real_catalog_is_valid(self) -> None:
        summary = self.catalog.validate()
        self.assertGreater(summary.region_count, 4000)

    def test_manual_download_basename_matches_existing_contract(self) -> None:
        self.assertEqual(
            "guangxi-latest.osm.pbf",
            self.catalog.pbf_basename(RegionId("china/guangxi")),
        )

    def test_inherited_settings_and_templates_match_contract(self) -> None:
        settings = self.catalog.region_settings(
            RegionId("china/guangxi"), "building", "20260818"
        )
        self.assertEqual("osm-dev", settings["style_id"])
        self.assertEqual("base-vector", settings["asset_role"])
        self.assertFalse(settings["building_enabled"])
        self.assertIn("20260818", settings["package_version"])
