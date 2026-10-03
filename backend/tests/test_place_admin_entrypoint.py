import subprocess
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class PlaceAdminEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entrypoint = repository_root(Path(__file__)) / "scripts/place-admin-enrich.sh"

    def test_help_runs_outside_repository(self) -> None:
        result = subprocess.run(
            [str(self.entrypoint), "--help"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--input=<source.osm.pbf>", result.stdout)

    def test_missing_input_and_unknown_argument_keep_input_exit_code(self) -> None:
        missing = subprocess.run(
            [str(self.entrypoint)], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        unknown = subprocess.run(
            [str(self.entrypoint), "--unknown"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(2, missing.returncode)
        self.assertEqual(2, unknown.returncode)
