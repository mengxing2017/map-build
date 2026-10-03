import subprocess
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class SpriteEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = repository_root(Path(__file__)) / "scripts/sprite.sh"

    def test_help_and_unknown_argument_preserve_shell_contract(self) -> None:
        help_result = subprocess.run(
            [str(self.script), "--help"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(0, help_result.returncode, help_result.stderr)
        self.assertIn("--force", help_result.stdout)
        invalid = subprocess.run(
            [str(self.script), "--unknown"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(2, invalid.returncode)
        self.assertIn("unknown argument", invalid.stderr)

    def test_generates_from_outside_repository_and_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = [
                str(self.script), "--region=china/guangxi",
                "--yyyymmdd=20261003", f"--workdir={directory}",
            ]
            first = subprocess.run(
                command, cwd="/tmp", text=True, capture_output=True,
                timeout=30, check=False,
            )
            self.assertEqual(0, first.returncode, first.stderr)
            output = Path(directory) / "outputs/china-guangxi-20261003.sprite"
            self.assertEqual(8, len(tuple(output.iterdir())))
            second = subprocess.run(
                command, cwd="/tmp", text=True, capture_output=True,
                timeout=30, check=False,
            )
            self.assertEqual(2, second.returncode)
            self.assertIn("pass --force", second.stderr)
            forced = subprocess.run(
                [*command, "--force"], cwd="/tmp", text=True,
                capture_output=True, timeout=30, check=False,
            )
            self.assertEqual(0, forced.returncode, forced.stderr)
