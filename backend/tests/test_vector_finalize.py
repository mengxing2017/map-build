import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    catalog_service,
    repository_root,
    vector_finalization_service,
    vector_quality_gate,
)
from huavd_map_build.delivery.domain.integrity import (
    ArtifactIntegrityReport,
    IntegrityFailure,
)
from huavd_map_build.production.north.local.vector_finalize import (
    VectorFinalizationRequest,
    VectorFinalizationService,
)
from huavd_map_build.quality.domain.vector import QualityFinding, VectorQualityReport
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId
from backend.tests.test_manifest import write_header


class RecordingMetadata:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def run(self, request) -> str:
        self.calls.append("metadata")
        return "/tmp/maps/staging/session/metadata.base.json"


class RecordingManifest:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def run(self, request) -> str:
        self.calls.append("manifest")
        path = Path(request.workdir) / "outputs/map.manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"source": {"vendor": "local", "url": None}}))
        return str(path)


class RecordingAttribution:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def write(self, paths, document) -> str:
        self.calls.append("attribution")
        source = document.sources[0]
        if (source.vendor == "geofabrik") != (source.url is not None):
            raise AssertionError("inconsistent attribution source")
        return paths.attribution


class RecordingQuality:
    def __init__(self, calls: list[str], report: VectorQualityReport) -> None:
        self.calls, self.report = calls, report

    def verify(self, **kwargs) -> VectorQualityReport:
        self.calls.append("semantic")
        return self.report


class RecordingIntegrity:
    def __init__(self, calls: list[str], report: ArtifactIntegrityReport) -> None:
        self.calls, self.report = calls, report

    def verify(self, paths) -> ArtifactIntegrityReport:
        self.calls.append("integrity")
        return self.report


class VectorFinalizationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
    def service(
        self, semantic: VectorQualityReport, integrity: ArtifactIntegrityReport
    ) -> tuple[VectorFinalizationService, list[str]]:
        calls: list[str] = []
        service = VectorFinalizationService(
            catalog_service(repository_root(Path(__file__))),
            RecordingMetadata(calls), RecordingManifest(calls),
            RecordingAttribution(calls), RecordingQuality(calls, semantic),
            RecordingIntegrity(calls, integrity),
        )
        return service, calls

    def request(self) -> VectorFinalizationRequest:
        return VectorFinalizationRequest(
            RegionId("china/guangxi"), BuildDate("20261003"),
            SessionId("china-guangxi-20261003"), Role.BASE, self.directory.name,
        )

    def test_runs_delivery_and_gates_in_fixed_order(self) -> None:
        service, calls = self.service(
            VectorQualityReport(()), ArtifactIntegrityReport((), ())
        )
        result = service.run(self.request())
        self.assertTrue(result.passed)
        self.assertEqual(
            ["metadata", "manifest", "attribution", "semantic", "integrity"],
            calls,
        )
        self.assertEqual(
            f"{self.directory.name}/outputs/china-guangxi-20261003.base.pmtiles",
            result.paths.pmtiles,
        )

    def test_combines_semantic_and_integrity_failures(self) -> None:
        service, _calls = self.service(
            VectorQualityReport((QualityFinding("metadata", "bad"),)),
            ArtifactIntegrityReport(
                ("map.pmtiles",),
                (IntegrityFailure("digest", "map.pmtiles", "bad"),),
            ),
        )
        result = service.run(self.request())
        self.assertFalse(result.passed)
        document = result.as_dict()
        self.assertEqual("failed", document["status"])
        self.assertEqual("failed", document["semantic"]["status"])
        self.assertEqual("failed", document["integrity"]["status"])

    def test_rejects_non_vector_role_before_side_effects(self) -> None:
        service, calls = self.service(
            VectorQualityReport(()), ArtifactIntegrityReport((), ())
        )
        request = self.request()
        with self.assertRaisesRegex(ValueError, "base or building"):
            service.run(VectorFinalizationRequest(
                request.region, request.build_date, request.session,
                Role.RASTER_BAKE, request.workdir,
            ))
        self.assertEqual([], calls)

    def test_real_wiring_finalizes_small_pmtiles_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            tools = workspace / "tools"
            tools.mkdir()
            pmtiles_tool = tools / "pmtiles"
            pmtiles_tool.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "case \"${1:-}\" in\n"
                "  --version) printf 'pmtiles fixture 1.0\\n' ;;\n"
                "  edit) cp \"${3#--metadata=}\" \"$2.embedded.json\" ;;\n"
                "  show) cat \"$2.embedded.json\" ;;\n"
                "  *) exit 2 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            pmtiles_tool.chmod(0o755)
            output = workspace / "outputs/china-guangxi-20261003.base.pmtiles"
            output.parent.mkdir()
            write_header(output, max_zoom=14)
            manual = workspace / "manual/custom.osm.pbf"
            manual.parent.mkdir()
            manual.write_bytes(b"local input in a region with catalog URL")
            staged = workspace / "staging/china-guangxi-20261003/source.osm.pbf"
            staged.parent.mkdir(parents=True)
            staged.symlink_to(manual)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{tools}:{old_path}"
            try:
                result = vector_finalization_service().run(VectorFinalizationRequest(
                    RegionId("china/guangxi"), BuildDate("20261003"),
                    SessionId("china-guangxi-20261003"), Role.BASE, directory,
                ))
                rewrite = subprocess.run(
                    [str(repository_root(Path(__file__)) / "scripts/attribution.sh"),
                     "--region=china/guangxi", "--yyyymmdd=20261003", "--role=base",
                     f"--workdir={directory}"], capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(0, rewrite.returncode, rewrite.stderr)
                rechecked = vector_quality_gate().verify(
                    region=RegionId("china/guangxi"), build_date=BuildDate("20261003"),
                    role=Role.BASE, workdir=directory,
                )
                self.assertTrue(rechecked.passed, rechecked.as_dict())
            finally:
                os.environ["PATH"] = old_path
            self.assertTrue(result.passed, result.as_dict())
            self.assertTrue(Path(result.paths.manifest).is_file())
            self.assertTrue(Path(result.paths.attribution).is_file())
            self.assertTrue(Path(result.paths.sha512).is_file())
            self.assertEqual(
                [{"vendor": "local", "url": None}],
                json.loads(Path(result.paths.attribution).read_text())["sources"],
            )
