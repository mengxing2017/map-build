import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class Md5ShellBridgeTest(unittest.TestCase):
    def test_common_md5_value_matches_geofabrik_sidecar_digest(self) -> None:
        root = repository_root(Path(__file__))
        content = b"small-pbf-fixture"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source map.osm.pbf"
            path.write_bytes(content)
            result = subprocess.run(
                ["bash", "-c", 'source scripts/lib/common.sh; md5_value "$1"', "_", str(path)],
                cwd=root, text=True, capture_output=True, timeout=30, check=False,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(hashlib.md5(content).hexdigest(), result.stdout.strip())
