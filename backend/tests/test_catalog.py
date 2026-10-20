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

    def test_routing_defaults_overrides_and_invalid_values(self):
        from huavd_map_build.catalog.south.adapter.yaml.repository import PyYamlRegionCatalogRepository
        from huavd_map_build.catalog.domain.model import RoutingSettings
        import yaml
        import tempfile
        document = yaml.safe_load((self.root / 'config/regions.yaml').read_text())
        item = next(r for r in document['regions'] if r['id'] == 'monaco')
        document['regions'] = [item]
        item['geofabrik']['parent_region'] = None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'regions.yaml'
            def load():
                path.write_text(yaml.safe_dump(document))
                return PyYamlRegionCatalogRepository(path).load().get(RegionId('monaco')).routing
            self.assertEqual(load(), RoutingSettings('use_default', 'block_ways'))
            item['routing'] = {'invalid_restrictions': 'reject'}
            self.assertEqual(load(), RoutingSettings('use_default', 'reject'))
            for bad in ({'invalid_restrictions': 'ignore'}, {'invalid_maxspeed': False},
                        {'invalid_maxspeeed': 'reject'}, None):
                with self.subTest(bad=bad):
                    item['routing'] = bad
                    with self.assertRaises((ValueError, RuntimeError)):
                        load()
