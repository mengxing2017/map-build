import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class AttributionEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))
        cls.entrypoint = cls.root / "scripts/attribution.sh"

    @staticmethod
    def manifest(directory, source, region="china-guangxi"):
        path = Path(directory) / f"outputs/{region}-20260818.base.manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"source": source}), encoding="utf-8")

    def test_compatibility_entrypoint_writes_expected_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.manifest(directory, {"vendor": "geofabrik", "url": "https://download.geofabrik.de/asia/china/guangxi-latest.osm.pbf"})
            result = subprocess.run(
                [
                    str(self.entrypoint),
                    "--region=china/guangxi",
                    "--yyyymmdd=20260818",
                    "--role=base",
                    f"--workdir={directory}",
                ],
                cwd="/tmp",
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            output = Path(directory) / (
                "outputs/china-guangxi-20260818.base.attribution.json"
            )
            document = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertEqual("ODbL-1.0", document["data_license"])
        self.assertEqual("geofabrik", document["sources"][0]["vendor"])

    def test_session_overrides_build_date_like_existing_common_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.manifest(directory, {"vendor": "local", "url": None})
            result = subprocess.run(
                [
                    str(self.entrypoint),
                    "--region=china/guangxi",
                    "--yyyymmdd=20260101",
                    "--session=china-guangxi-20260818",
                    "--role=base",
                    f"--workdir={directory}",
                ],
                cwd=self.root,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            output = Path(directory) / (
                "outputs/china-guangxi-20260818.base.attribution.json"
            )
            exists = output.is_file()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(exists)

    def test_local_attribution_uses_manifest_despite_catalog_url(self) -> None:
        for region in ("china/guangxi", "china/taiwan/taipei"):
            with self.subTest(region=region), tempfile.TemporaryDirectory() as directory:
                self.manifest(directory, {"vendor": "local", "url": None}, region.replace("/", "-"))
                args = [sys.executable, "-m", "huavd_map_build", "artifact"]
                context = [f"--region={region}", "--yyyymmdd=20260818", f"--workdir={directory}"]
                result = subprocess.run(args + ["attribution"] + context, cwd=self.root,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(0, result.returncode, result.stderr)
                document = json.loads(result.stdout)
                self.assertEqual([{"vendor": "local", "url": None}], document["sources"])
                written = subprocess.run(args + ["write-attribution", "--role=base"] + context,
                                         cwd=self.root, capture_output=True, text=True, timeout=30)
                self.assertEqual(0, written.returncode, written.stderr)
                output = Path(json.loads(written.stdout)["path"])
                self.assertEqual(document, json.loads(output.read_text()))

    def test_missing_context_manifest_and_invalid_source_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = [sys.executable, "-m", "huavd_map_build", "artifact", "attribution",
                    "--region=china/guangxi", f"--workdir={directory}"]
            result = subprocess.run(args, cwd=self.root, capture_output=True, text=True)
            self.assertEqual(2, result.returncode)
            self.assertIn("--yyyymmdd", result.stderr)
            result = subprocess.run(args + ["--yyyymmdd=20260818"], cwd=self.root,
                                    capture_output=True, text=True)
            self.assertEqual(2, result.returncode)
            self.assertIn("generate or rebuild", result.stderr)
            for source in ({}, {"vendor": "local", "url": "https://example.test/pbf"},
                           {"vendor": "geofabrik", "url": None},
                           {"vendor": "geofabrik", "url": "https:///missing-host"},
                           {"vendor": "unknown", "url": None}):
                with self.subTest(source=source):
                    self.manifest(directory, source)
                    result = subprocess.run(args + ["--yyyymmdd=20260818"], cwd=self.root,
                                            capture_output=True, text=True)
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertEqual("", result.stdout)
