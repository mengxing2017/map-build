import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huavd_map_build.cli import run
from huavd_map_build.delivery.domain.integrity import ArtifactIntegrityReport
from huavd_map_build.quality.domain.vector import VectorQualityReport


class _VectorGate:
    def verify(self, **_request):
        return VectorQualityReport(())


class _FileVerifier:
    def verify(self, paths):
        return ArtifactIntegrityReport(paths.core_files(), ())


class ReleaseQualityEntrypointTest(unittest.TestCase):
    def test_release_executes_keyword_only_artifact_query(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory) / "outputs"
            outputs.mkdir()
            (outputs / "china-guangxi-20260818.base.pmtiles").write_bytes(b"fixture")
            with patch(
                "huavd_map_build.cli.vector_quality_gate",
                return_value=_VectorGate(),
            ), patch(
                "huavd_map_build.cli.artifact_file_verifier",
                return_value=_FileVerifier(),
            ):
                status = run([
                    "quality", "release", "--region=china/guangxi",
                    "--yyyymmdd=20260818", "--role=both",
                    f"--workdir={directory}",
                ])
        self.assertEqual(0, status)


if __name__ == "__main__":
    unittest.main()
