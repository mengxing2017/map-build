from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch, MagicMock
from huavd_map_build.delivery.domain.metadata import PmtilesHeader

from huavd_map_build import cli
from huavd_map_build.bootstrap import (
    build_configuration_service,
    repository_root,
)
from huavd_map_build.delivery.south.adapter.filesystem.digest import FileDigestAdapter
from huavd_map_build.production.domain.raster import (
    RasterBounds,
    create_raster_tile_plan,
)
from huavd_map_build.production.north.local.raster_request import (
    RasterBakeOverrides,
    RasterBakeRequestFactory,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId


class RasterBakeRequestFactoryTest(unittest.TestCase):
    def test_builds_candidate_paths_and_content_identity(self) -> None:
        root = repository_root(Path(__file__))
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            session = "china-guangxi-20261004"
            outputs = workdir / "outputs"
            cache = workdir / "cache/bake" / session
            outputs.mkdir(parents=True)
            cache.mkdir(parents=True)
            base = outputs / f"{session}.base.pmtiles"
            style = cache / "style-render.json"
            base.write_bytes(b"base")
            style.write_text('{"version":8}', encoding="utf-8")
            plan = create_raster_tile_plan(RasterBounds(0, 0, 1, 1), 0, 0, 0)
            factory = RasterBakeRequestFactory(
                build_configuration_service(root), FileDigestAdapter(),
                str(root / "config/bake.yaml"),
                MagicMock(read=MagicMock(return_value=PmtilesHeader(1, 2, 0, 18, (0,0,1,1)))),
            )
            request = factory.create(
                RegionId("china/guangxi"), BuildDate("20261004"), str(workdir),
                plan, RasterBakeOverrides(
                    renderer_identity="renderer 1", parallel_jobs=3, retries=1,
                    extract_pmtiles=True,
                ),
            )
        self.assertEqual(str(cache / "raster_bake.candidate.pmtiles"), request.pmtiles_path)
        self.assertNotIn("/outputs/", request.pmtiles_path)
        self.assertEqual(3, request.render_settings.parallel_jobs)
        self.assertEqual(1, request.render_settings.retries)
        self.assertEqual("renderer 1", request.identity.renderer_identity)
        self.assertEqual(str(cache / "base-bake-subset.pmtiles"), request.runtime_request.subset_path)
        self.assertEqual(str(cache / "parameters.json"), request.parameters_path)

    def test_native_automatically_uses_headless_and_conservative_parallelism(self) -> None:
        root = repository_root(Path(__file__))
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            session = "china-guangxi-20261004"
            outputs, cache = workdir / "outputs", workdir / "cache/bake" / session
            outputs.mkdir(parents=True)
            cache.mkdir(parents=True)
            (outputs / f"{session}.base.pmtiles").write_bytes(b"base")
            (cache / "style-render.json").write_text("{}")
            factory = RasterBakeRequestFactory(
                build_configuration_service(root), FileDigestAdapter(), str(root / "config/bake.yaml"),
                MagicMock(read=MagicMock(return_value=PmtilesHeader(1, 2, 0, 18, (0,0,1,1))))
            )
            plan = create_raster_tile_plan(RasterBounds(0,0,1,1), 0,0,0)
            request = factory.create(
                RegionId("china/guangxi"), BuildDate("20261004"), temporary, plan,
                RasterBakeOverrides(renderer_engine="maplibre-native-headless"),
            )
            self.assertEqual("headless", request.display_settings.mode)
            self.assertEqual(2, request.render_settings.parallel_jobs)
            self.assertTrue(request.runtime_request.validate_mvt)
            with self.assertRaisesRegex(ValueError, "headless display"):
                factory.create(
                    RegionId("china/guangxi"), BuildDate("20261004"), temporary, plan,
                    RasterBakeOverrides(renderer_engine="maplibre-native-headless", display_mode="managed-xvfb"),
                )

    def test_missing_base_or_style_is_rejected_before_bake(self) -> None:
        root = repository_root(Path(__file__))
        with tempfile.TemporaryDirectory() as temporary:
            plan = create_raster_tile_plan(RasterBounds(0, 0, 1, 1), 0, 0, 0)
            factory = RasterBakeRequestFactory(
                build_configuration_service(root), FileDigestAdapter(),
                str(root / "config/bake.yaml"),
                MagicMock(read=MagicMock(return_value=PmtilesHeader(1, 2, 0, 18, (0,0,1,1)))),
            )
            with self.assertRaisesRegex(ValueError, "required raster bake input"):
                factory.create(
                    RegionId("china/guangxi"), BuildDate("20261004"), temporary,
                    plan, RasterBakeOverrides(),
                )

    def test_explicit_zero_jobs_is_rejected_instead_of_using_default(self) -> None:
        root = repository_root(Path(__file__))
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            session = "china-guangxi-20261004"
            outputs, cache = workdir / "outputs", workdir / "cache/bake" / session
            outputs.mkdir(parents=True)
            cache.mkdir(parents=True)
            (outputs / f"{session}.base.pmtiles").write_bytes(b"base")
            (cache / "style-render.json").write_text("{}", encoding="utf-8")
            factory = RasterBakeRequestFactory(
                build_configuration_service(root), FileDigestAdapter(),
                str(root / "config/bake.yaml"),
                MagicMock(read=MagicMock(return_value=PmtilesHeader(1, 2, 0, 18, (0,0,1,1)))),
            )
            with self.assertRaisesRegex(ValueError, "parallel jobs"):
                factory.create(
                    RegionId("china/guangxi"), BuildDate("20261004"), str(workdir),
                    create_raster_tile_plan(RasterBounds(0, 0, 1, 1), 0, 0, 0),
                    RasterBakeOverrides(parallel_jobs=0),
                )

    def test_native_rejects_z25_before_reading_source_header(self):
        root=repository_root(Path(__file__))
        with tempfile.TemporaryDirectory() as directory:
            workdir=Path(directory)
            base=workdir/'outputs/china-guangxi-20261004.base.pmtiles'
            style=workdir/'cache/bake/china-guangxi-20261004/style-render.json'
            base.parent.mkdir(parents=True);style.parent.mkdir(parents=True)
            base.write_bytes(b'base');style.write_text('{}')
            headers=MagicMock()
            factory=RasterBakeRequestFactory(build_configuration_service(root),FileDigestAdapter(),
                str(root/'config/bake.yaml'),headers)
            tiny=RasterBounds(110.3,25.3,110.30000001,25.30000001)
            plan=create_raster_tile_plan(tiny,25,25,0)
            with self.assertRaisesRegex(ValueError,'0..24'):
                factory.create(RegionId('china/guangxi'),BuildDate('20261004'),directory,plan,
                    RasterBakeOverrides(renderer_engine='maplibre-native-headless'))
            headers.read.assert_not_called()


    def test_z19_native_requires_a_known_feature_instead_of_accepting_all_background(self):
        root=repository_root(Path(__file__))
        with tempfile.TemporaryDirectory() as directory:
            workdir=Path(directory)
            base=workdir/'outputs/china-guangxi-20261004.base.pmtiles'
            style=workdir/'cache/bake/china-guangxi-20261004/style-render.json'
            base.parent.mkdir(parents=True);style.parent.mkdir(parents=True)
            base.write_bytes(b'base');style.write_text('{}')
            headers=MagicMock(read=MagicMock(return_value=PmtilesHeader(1,2,0,19,(110,25,111,26))))
            factory=RasterBakeRequestFactory(build_configuration_service(root),FileDigestAdapter(),
                str(root/'config/bake.yaml'),headers)
            plan=create_raster_tile_plan(RasterBounds(110.3,25.3,110.30000001,25.30000001),19,19,0)
            with self.assertRaisesRegex(ValueError,'known feature'):
                factory.create(RegionId('china/guangxi'),BuildDate('20261004'),directory,plan,
                    RasterBakeOverrides(renderer_engine='maplibre-native-headless'))



class StubPlanningService:
    def __init__(self, plan) -> None:
        self.plan_value = plan
        self.requests = []

    def plan(self, request):
        self.requests.append(request)
        return self.plan_value


class StubRequestFactory:
    def __init__(self) -> None:
        self.calls = []
        self.request = SimpleNamespace(pmtiles_path="/tmp/cache/candidate.pmtiles")

    def create(self, *arguments):
        self.calls.append(arguments)
        return self.request


class StubBakeResult:
    def as_dict(self):
        return {"schema_version": 1, "assembled_tiles": 1}


class StubBakeService:
    def __init__(self) -> None:
        self.requests = []

    def bake(self, request):
        self.requests.append(request)
        return StubBakeResult()


class RasterBakeEntrypointTest(unittest.TestCase):
    def test_builds_unpublished_candidate_with_explicit_overrides(self) -> None:
        plan = create_raster_tile_plan(RasterBounds(0, 0, 1, 1), 0, 0, 0)
        planning = StubPlanningService(plan)
        factory, service = StubRequestFactory(), StubBakeService()
        arguments = [
            "build", "raster-bake", "--region", "china/guangxi",
            "--yyyymmdd", "20261004", "--workdir", "/tmp/maps",
            "--bbox", "0,0,1,1", "--min-zoom", "0", "--max-zoom", "0",
            "--jobs", "3", "--retries", "1", "--timeout-seconds", "9",
            "--extract-pmtiles", "--renderer-command", "renderer", "--no-publish",
            "--renderer-engine", "mbgl-renderer",
        ]
        output = io.StringIO()
        with patch.object(cli, "raster_planning_service", return_value=planning), patch.object(
            cli, "raster_bake_request_factory", return_value=factory
        ), patch.object(cli, "raster_bake_service", return_value=service), patch(
            "huavd_map_build.delivery.south.adapter.process.tool_versions."
            "ProcessToolVersionReader.versions",
            return_value={"renderer": "renderer 1"},
        ), patch(
            "huavd_map_build.production.south.adapter.process.raster_preview.write_preview",
            return_value={"visual_acceptance": "not-run"},
        ), redirect_stdout(output):
            status = cli.run(arguments)
        document = json.loads(output.getvalue())
        overrides = factory.calls[0][-1]
        self.assertEqual(0, status)
        self.assertFalse(document["published"])
        self.assertEqual("/tmp/cache/candidate.pmtiles", document["candidate_pmtiles"])
        self.assertEqual("renderer 1", overrides.renderer_identity)
        self.assertEqual(3, overrides.parallel_jobs)
        self.assertTrue(overrides.extract_pmtiles)
        self.assertEqual([factory.request], service.requests)

    def test_invalid_bbox_is_rejected_before_planning(self) -> None:
        with self.assertRaisesRegex(ValueError, "west,south,east,north"):
            cli.run([
                "build", "raster-bake", "--region", "china/guangxi",
                "--yyyymmdd", "20261004", "--bbox", "0,1,2",
            ])


if __name__ == "__main__":
    unittest.main()
