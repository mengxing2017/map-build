import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from huavd_map_build.delivery.north.local.bundle import BundleRequest, BundleService
from huavd_map_build.shared.kernel import BuildDate, RegionId, SessionId


class _Viewport:
    def read(self, _path):
        return {"center": [108.3, 23.7], "default_zoom": 6, "min_zoom": 0}


class BundleServiceTest(unittest.TestCase):
    def test_both_packages_consumer_contract_and_skips_optional_building(self):
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
            (outputs / f"{stem}.attribution.json").write_text("{}\n", encoding="utf-8")
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

            result = BundleService(_Viewport()).run(BundleRequest(
                RegionId("china/guangxi"), BuildDate("20260818"), SessionId(session),
                "both", directory, "zip",
            ))
            install = json.loads(
                (root / "cache" / "pack" / session / "install.json").read_text()
            )
            archive = outputs / f"{session}.bundle.zip"
            with zipfile.ZipFile(archive) as package:
                members = set(package.namelist())

        self.assertEqual(1, result["copied_roles"])
        self.assertEqual("huavd-map-install/v1", install["schema_version"])
        self.assertEqual(["base-vector"], [item["asset-role"] for item in install["offline_maps"]])
        self.assertEqual(["standard"], install["bundles"][0]["supported-presentations"])
        self.assertIn("install.json", members)
        self.assertIn("SHA256SUMS", members)
        self.assertIn("SHA512SUMS", members)


if __name__ == "__main__":
    unittest.main()
