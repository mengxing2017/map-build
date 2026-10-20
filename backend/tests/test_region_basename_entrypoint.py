import os
import subprocess
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class RegionBasenameEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))
        cls.entrypoint = cls.root / "scripts/region-pbf-basename.sh"

    def test_region_environment_variable_remains_supported(self) -> None:
        environment = os.environ.copy()
        environment["REGION"] = "china/guangxi"
        result = subprocess.run(
            [str(self.entrypoint)],
            cwd="/tmp",
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("guangxi-latest.osm.pbf", result.stdout.strip())

    def test_region_without_basename_keeps_input_error_exit_code(self) -> None:
        result = subprocess.run(
            [str(self.entrypoint), "china/taiwan/taipei"],
            cwd="/tmp",
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("region lacks geofabrik.basename", result.stderr)
