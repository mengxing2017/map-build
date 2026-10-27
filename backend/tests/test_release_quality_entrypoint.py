import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huavd_map_build.cli import run
from huavd_map_build.delivery.domain.integrity import ArtifactIntegrityReport
from huavd_map_build.quality.domain.vector import VectorQualityReport
from huavd_map_build.quality.domain.base import BaseDeepQualityReport
from huavd_map_build.quality.domain.staging import BaseStagingQualityReport
from huavd_map_build.quality.domain.tile import TileSamplingReport


class _VectorGate:
    def verify(self, **_request):
        return VectorQualityReport(())


class _FileVerifier:
    def verify(self, paths):
        return ArtifactIntegrityReport(paths.core_files(), ())


class _DeepGate:
    def inspect(self, build):
        return BaseDeepQualityReport(BaseStagingQualityReport((), 0, ()), TileSamplingReport((), ()))


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
            ), patch("huavd_map_build.cli.base_deep_quality_gate", return_value=_DeepGate()) as deep:
                status = run([
                    "quality", "release", "--region=china/guangxi",
                    "--yyyymmdd=20260818", "--role=both",
                    f"--workdir={directory}",
                ])
        self.assertEqual(0, status)
        deep.assert_called_once()

    def test_release_rejects_content_failure_even_when_artifact_contracts_pass(self):
        from huavd_map_build.quality.domain.vector import QualityFinding
        from unittest.mock import Mock
        gate = Mock()
        gate.inspect.return_value = BaseDeepQualityReport(
            BaseStagingQualityReport((), 0, ()),
            TileSamplingReport((), (QualityFinding("tile-low-zoom-gap", "road hole"),)),
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "huavd_map_build.cli.vector_quality_gate", return_value=_VectorGate()
        ), patch("huavd_map_build.cli.artifact_file_verifier", return_value=_FileVerifier()), patch(
            "huavd_map_build.cli.base_deep_quality_gate", return_value=gate
        ):
            status = run(["quality", "release", "--region=china/guangxi", "--yyyymmdd=20260818",
                          "--role=base", f"--workdir={directory}"])
        self.assertEqual(3, status)
        gate.inspect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
