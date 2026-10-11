import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import catalog_service, repository_root
from huavd_map_build.delivery.domain.integrity import ArtifactIntegrityReport
from huavd_map_build.production.north.local.raster_finalize import (
    RasterFinalizationRequest,
    RasterFinalizationService,
)
from huavd_map_build.quality.domain.raster import RasterQualityReport
from huavd_map_build.quality.domain.vector import QualityFinding
from huavd_map_build.shared.kernel import BuildDate, RegionId, SessionId


class RecordingComponent:
    def __init__(self, calls, name, result=None):
        self.calls, self.name, self.result = calls, name, result

    def bind(self, *args):
        self.calls.append(self.name)

    def run(self, request):
        self.calls.append(self.name)
        return self.result

    def write(self, paths, document):
        self.calls.append(self.name)
        return paths.attribution

    def verify(self, *args, **kwargs):
        self.calls.append(self.name)
        if isinstance(self.result, list):
            return self.result.pop(0)
        return self.result

    def publish_integrity_metadata(self, paths, *, published_at):
        self.calls.append(self.name)


class RecordingCandidates:
    def __init__(self, calls, paths):
        self.calls, self.paths = calls, paths

    def stage(self, candidate, identity, outputs):
        self.calls.append("stage")
        return self.paths

    def promote(self, staged, final):
        self.calls.append("promote")

    def discard(self, staged):
        self.calls.append("discard")


class RasterFinalizationServiceTest(unittest.TestCase):
    def test_quality_failure_never_promotes_candidate(self) -> None:
        from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
        from huavd_map_build.shared.kernel import Role

        calls = []
        identity = ArtifactIdentity(
            RegionId("china/guangxi"), BuildDate("20261003"), Role.RASTER_BAKE
        )
        staged = ArtifactPaths(identity, "/tmp/maps/outputs/.staging/test")
        failed = RasterQualityReport((QualityFinding("bad", "bad"),))
        service = RasterFinalizationService(
            catalog_service(repository_root(Path(__file__))),
            RecordingComponent(calls, "metadata", "/tmp/metadata.json"),
            RecordingComponent(calls, "manifest", staged.manifest),
            RecordingComponent(calls, "attribution"),
            RecordingComponent(calls, "quality", failed),
            RecordingComponent(calls, "integrity", ArtifactIntegrityReport((), ())),
            RecordingCandidates(calls, staged), RecordingComponent(calls, "publish"),
        )
        result = service.run(RasterFinalizationRequest(
            identity.region, identity.build_date, SessionId("china-guangxi-20261003"),
            "/tmp/maps", "/tmp/candidate.pmtiles", 2, 256,
        ))
        self.assertFalse(result.published)
        self.assertEqual(
            ["stage", "metadata", "manifest", "attribution", "quality",
             "integrity", "discard"], calls,
        )
        self.assertNotIn("promote", calls)

    def test_success_promotes_before_ready_publication_and_rechecks_final(self) -> None:
        from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
        from huavd_map_build.shared.kernel import Role

        calls = []
        identity = ArtifactIdentity(
            RegionId("china/guangxi"), BuildDate("20261003"), Role.RASTER_BAKE
        )
        staged = ArtifactPaths(identity, "/tmp/maps/outputs/.staging/test")
        passed = ArtifactIntegrityReport((), ())
        service = RasterFinalizationService(
            catalog_service(repository_root(Path(__file__))),
            RecordingComponent(calls, "metadata", "/tmp/metadata.json"),
            RecordingComponent(calls, "manifest", staged.manifest),
            RecordingComponent(calls, "attribution"),
            RecordingComponent(calls, "quality", RasterQualityReport(())),
            RecordingComponent(calls, "integrity", [passed, passed]),
            RecordingCandidates(calls, staged), RecordingComponent(calls, "publish"),
            styles=RecordingComponent(calls, "style-bind"),
        )
        result = service.run(RasterFinalizationRequest(
            identity.region, identity.build_date, SessionId("china-guangxi-20261003"),
            "/tmp/maps", "/tmp/candidate.pmtiles", 2, 256,
        ))
        self.assertTrue(result.published)
        self.assertEqual(
            ["stage", "metadata", "manifest", "attribution", "quality",
             "integrity", "promote", "style-bind", "publish", "integrity", "discard"], calls,
        )
