import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class AttributionEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))
        cls.entrypoint = cls.root / "scripts/attribution.sh"

    def test_compatibility_entrypoint_writes_expected_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
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
