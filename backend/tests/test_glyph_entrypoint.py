import subprocess
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class GlyphEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = repository_root(Path(__file__)) / "scripts/glyph.sh"

    def test_help_runs_outside_repository(self) -> None:
        result = subprocess.run(
            [str(self.script), "--help"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--locales", result.stdout)

    def test_unknown_argument_keeps_input_error_exit_code(self) -> None:
        result = subprocess.run(
            [str(self.script), "--unknown"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("unknown argument", result.stderr)
