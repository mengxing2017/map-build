from contextlib import nullcontext
import hashlib
import json
import tempfile
import tarfile
import unittest
import zipfile
from pathlib import Path

from huavd_map_build.delivery.north.local.bundle import BundleRequest, BundleService
from huavd_map_build.shared.kernel import BuildDate, RegionId, SessionId


class _Viewport:
    def read(self, _path):
        return {"center": [108.3, 23.7], "default_zoom": 6, "min_zoom": 0}


class _Routing:
    policy = 'reject'
    maxspeed_policy = 'reject'
    speed_audit = []
    blocked_way_ids = []
    restriction_diagnostics = []
    review = None
    graph_capacity = 'regional'
    dataset_format = 1

    def __init__(self, root, source='a' * 64):
        from huavd_map_build.production.north.local.routing_resources import ResourceGate
        self.workdir = root
        self.outputs = root / 'outputs'
        (root / 'staging/routing').mkdir(parents=True, exist_ok=True)
        self.resources = ResourceGate(Path(__file__).resolve().parents[2], root)
        self.dataset = root / 'dataset'
        self.dataset.mkdir()
        (self.dataset / 'graph.bin').write_bytes(b'graph')
        self.source = source
        self.smoked = False

    def locked(self):
        return nullcontext()

    def current(self):
        from huavd_map_build.production.north.local.routing import file_records
        manifest = {'dataset_id': 'fixture', 'format': self.dataset_format, 'profile': 'driving-v1',
                    'attribution': 'OpenStreetMap contributors'}
        return self.dataset, manifest, {'source_sha256': self.source, 'maxspeed_diagnostics': self.speed_audit,
                                      'blocked_way_ids': self.blocked_way_ids,
                                      'restriction_diagnostics': self.restriction_diagnostics,
                                      'files': file_records(self.dataset)}

    def verify_dataset(self, path, source):
        assert path != self.dataset and (path / 'graph.bin').read_bytes() == b'graph'
        return self.current()[1]

    def smoke(self, path, manifest):
        self.smoked = True


class BundleServiceTest(unittest.TestCase):
    def test_both_packages_consumer_contract_and_skips_optional_building(self):
        self._pack('both')

    def test_raster_vector_packages_routing_by_default(self):
        self._pack('base_raster')

    def test_v2_package_declares_consumer_capability(self):
        from unittest.mock import patch
        with patch.object(_Routing, 'dataset_format', 2):
            self._pack('both')

    def test_fallback_policy_and_diagnostics_survive_standard_package(self):
        from unittest.mock import patch
        audit = [{'way_id': 42, 'field': 'maxspeed', 'value': '辅路',
                  'action': 'use_default', 'effective_kmh': 30.0}]
        with patch.object(_Routing, 'maxspeed_policy', 'use_default'), patch.object(_Routing, 'speed_audit', audit):
            self._pack('both')

    def test_blocked_restrictions_survive_standard_package(self):
        from unittest.mock import patch
        audit = [{'relation_id': 99, 'code': 'MissingVia', 'action': 'blocked_ways'}]
        with (patch.object(_Routing, 'policy', 'block_ways'),
              patch.object(_Routing, 'blocked_way_ids', [42]),
              patch.object(_Routing, 'restriction_diagnostics', audit)):
            self._pack('both')

    def test_source_mismatch_refuses_archive(self):
        self._pack('both', mismatch=True)

    def test_missing_map_source_sha256_refuses_archive(self):
        self._pack('both', map_sha=None)

    def test_absent_map_source_block_refuses_archive(self):
        self._pack('both', map_source_missing=True)

    def test_invalid_map_source_sha256_refuses_archive(self):
        self._pack('both', map_sha='A' * 64)

    def test_joint_package_requires_building_fingerprint(self):
        self._pack('both', building=True, building_sha=None)

    def test_building_source_mismatch_refuses_joint_archive(self):
        self._pack('both', building=True, building_sha='c' * 64)

    def test_joint_package_accepts_matching_building_fingerprint(self):
        self._pack('both', building=True)

    def test_missing_routing_refuses_archive(self):
        self._pack('both', missing=True)

    def _pack(self, role, mismatch=False, missing=False, map_sha='a' * 64,
              map_source_missing=False, building=False, building_sha='a' * 64):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "outputs"
            outputs.mkdir()
            session = "china-guangxi-20260818"
            payload = b"pmtiles-fixture"
            digest = hashlib.sha512(payload).hexdigest()
            stem = f"{session}.base"
            (outputs / f"{stem}.pmtiles").write_bytes(payload)
            (outputs / f"{stem}.pmtiles.sha512").write_text(
                f"{digest}  {stem}.pmtiles\n", encoding="ascii"
            )
            manifest = {
                "source": {"sha256": map_sha},
                "region": "china/guangxi", "build_id": "2026-08-18T00:00:00Z",
                "output": {"sha512": digest, "tile_range": {
                    "min_zoom": 0, "max_zoom": 14, "bounds": [104, 20, 113, 27]
                }},
                "huavd_record": {
                    "id": "cn-45-base", "name": stem, "source_id": "osm-geofabrik",
                    "package_version": "20260818.base", "source_revision": "fixture",
                    "asset_role": "base-vector", "source_type": "osm-pbf",
                    "format": "pmtiles", "coord_system": "EPSG:3857",
                    "transport": "offline", "style_id": "osm-dev",
                    "available_locales": ["zh-Hans"], "style_locales": ["zh-Hans"],
                    "bundle_id": f"{session}-standard", "activation": "manual",
                },
            }
            (outputs / f"{stem}.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            if map_source_missing:
                manifest.pop("source")
                (outputs / f"{stem}.manifest.json").write_text(
                    json.dumps(manifest), encoding="utf-8"
                )
            (outputs / f"{stem}.attribution.json").write_text("{}\n", encoding="utf-8")
            if building:
                building_stem = f"{session}.building"
                building_manifest = json.loads(json.dumps(manifest))
                building_manifest["source"]["sha256"] = building_sha
                building_manifest["huavd_record"].update({
                    "id": "cn-45-building", "name": building_stem,
                    "package_version": "20260818.building",
                    "asset_role": "building-vector",
                })
                for suffix in ("pmtiles", "pmtiles.sha512", "attribution.json"):
                    (outputs / f"{building_stem}.{suffix}").write_bytes(
                        (outputs / f"{stem}.{suffix}").read_bytes()
                    )
                (outputs / f"{building_stem}.manifest.json").write_text(
                    json.dumps(building_manifest), encoding="utf-8"
                )
            for style in ("style.json", "style-raster.json"):
                path = outputs / f"{session}.{style}"
                path.write_text("{}\n", encoding="utf-8")
                path.with_name(f"{path.name}.sha512").write_text("fixture\n", encoding="ascii")
            glyph = outputs / f"{session}.glyphs" / "zh-Hans"
            glyph.mkdir(parents=True)
            (glyph / "0-255.pbf").write_bytes(b"glyph")
            sprite = outputs / f"{session}.sprite"
            sprite.mkdir()
            (sprite / "sprite.json").write_text("{}\n", encoding="utf-8")
            (sprite / "sprite.png").write_bytes(b"png")

            routing = _Routing(root, 'b' * 64 if mismatch else 'a' * 64)
            def factory(request):
                if missing:
                    raise ValueError('routing missing')
                return routing
            service = BundleService(_Viewport(), factory)
            if role == 'base_raster':
                raster_stem = f'{session}.raster_bake'
                raster_manifest = json.loads(json.dumps(manifest))
                raster_manifest['huavd_record']['asset_role'] = 'raster-baked'
                raster_manifest['huavd_record']['id'] = 'cn-45-raster'
                for suffix in ('pmtiles', 'pmtiles.sha512', 'attribution.json'):
                    (outputs / f'{raster_stem}.{suffix}').write_bytes((outputs / f'{stem}.{suffix}').read_bytes())
                (outputs / f'{raster_stem}.manifest.json').write_text(json.dumps(raster_manifest))
                service._verify_ready = lambda paths: None
            request = BundleRequest(
                RegionId("china/guangxi"), BuildDate("20260818"), SessionId(session),
                role, directory, "both",
            )
            refused = (mismatch or missing or map_sha != 'a' * 64
                       or map_source_missing
                       or (building and building_sha != 'a' * 64))
            if refused:
                with self.assertRaises(ValueError):
                    service.run(request)
                self.assertFalse((outputs / f'{session}.bundle.zip').exists())
                return
            result = service.run(request)
            self.assertTrue(routing.smoked)
            install = json.loads(
                (root / "cache" / "pack" / session / "install.json").read_text()
            )
            archive = outputs / f"{session}.bundle.zip"
            with zipfile.ZipFile(archive) as package:
                members = set(package.namelist())
                contract = json.loads(package.read('package.json'))
                self.assertTrue(contract['routing']['required'])
                self.assertEqual(routing.maxspeed_policy, contract['routing']['invalid_maxspeed'])
                self.assertEqual(routing.speed_audit, contract['routing']['maxspeed_diagnostics'])
                self.assertEqual(routing.blocked_way_ids, contract['routing']['blocked_way_ids'])
                self.assertEqual(routing.restriction_diagnostics, contract['routing']['restriction_diagnostics'])
                self.assertEqual(routing.policy == 'block_ways', bool(contract['routing']['coverage_notice']))
                self.assertEqual(['offline-maps', f'routeweft-dataset-v{routing.dataset_format}'],
                                 contract['required_capabilities'])
                self.assertEqual(routing.dataset_format, contract['routing']['format'])
                self.assertEqual('regional', contract['routing']['graph_capacity'])
                self.assertEqual('a' * 64, contract['source_sha256'])
                self.assertIn('routing/graph.bin', package.read('SHA256SUMS').decode())
            with tarfile.open(outputs / f'{session}.bundle.tar.gz') as package:
                self.assertIn('./routing/graph.bin', package.getnames())

        self.assertEqual(
            2 if role == "base_raster" else 1 + int(building), result["copied_roles"]
        )
        self.assertEqual("huavd-map-install/v1", install["schema_version"])
        self.assertIn("base-vector", [item["asset-role"] for item in install["offline_maps"]])
        self.assertEqual(
            ["standard"] + (["standard-buildings"] if building else []),
            install["bundles"][0]["supported-presentations"],
        )
        self.assertIn("install.json", members)
        self.assertIn("package.json", members)
        self.assertIn("routing/graph.bin", members)
        self.assertIn("routing/attribution.json", members)
        self.assertIn("SHA256SUMS", members)
        self.assertIn("SHA512SUMS", members)


if __name__ == "__main__":
    unittest.main()
