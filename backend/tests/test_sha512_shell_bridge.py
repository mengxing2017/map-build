import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class Sha512ShellBridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))

    def test_common_sha512_value_handles_spaces_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "map artifact.pmtiles"
            link = Path(directory) / "map-link.pmtiles"
            content = b"huavd-map-build-sha512"
            artifact.write_bytes(content)
            link.symlink_to(artifact)
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source scripts/lib/common.sh; sha512_value "$1"',
                    "_",
                    str(link),
                ],
                cwd=self.root,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(hashlib.sha512(content).hexdigest(), result.stdout.strip())

    def test_common_sha512_stdin_preserves_binary_input(self) -> None:
        content = b"huavd\x00" + "地图".encode() + b"\nmap-build"
        result = subprocess.run(
            ["bash", "-c", "source scripts/lib/common.sh; sha512_stdin"],
            cwd=self.root,
            input=content,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr.decode())
        self.assertEqual(
            hashlib.sha512(content).hexdigest(), result.stdout.decode().strip()
        )
