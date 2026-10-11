from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from huavd_map_build.production.domain.raster import (
    RasterAssemblyResult,
    RasterBakeResult,
    RasterAssemblySettings,
    RasterBounds,
    RasterCacheIdentity,
    RasterSourceMetadata,
    RasterCachePreparation,
    RasterCacheScanResult,
    RasterDisplayEndpoint,
    RasterDisplaySettings,
    RasterExecutionError,
    RasterMvtPreflightResult,
    RasterRenderResult,
    RasterRenderSettings,
    RasterStageTiming,
    create_raster_tile_plan,
)
from huavd_map_build.production.north.local.raster_bake import (
    RasterBakeRequest,
    RasterBakeService,
)
from huavd_map_build.production.north.local.raster_runtime import (
    RasterRuntimeRequest,
    RasterRuntimeResult,
)
from huavd_map_build.production.south.adapter.workspace.raster_lifecycle import (
    FileSystemRasterCacheLifecycle,
)
from huavd_map_build.production.south.adapter.workspace.raster_evidence import (
    FileSystemRasterEvidenceStore,
)
from huavd_map_build.delivery.south.adapter.filesystem.atomic_writer import (
    AtomicFileWriter,
)
from huavd_map_build.delivery.south.adapter.filesystem.digest import FileDigestAdapter
from huavd_map_build.bootstrap import raster_bake_service


class RasterCacheLifecycleTest(unittest.TestCase):
    def test_identity_change_invalidates_declared_paths_and_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            webp, mbtiles = root / "webp", root / "raster.mbtiles"
            webp.mkdir()
            (webp / "tile").write_text("cached", encoding="utf-8")
            mbtiles.write_text("cached", encoding="utf-8")
            (root / "inputs.sha512").write_text("old\n", encoding="ascii")
            lifecycle = FileSystemRasterCacheLifecycle()
            with lifecycle.open(
                "new", str(root), (str(webp), str(mbtiles))
            ) as preparation:
                self.assertTrue(preparation.invalidated)
                self.assertTrue((root / ".bake.lock/owner").is_file())
                self.assertFalse(webp.exists())
                self.assertFalse(mbtiles.exists())
            self.assertFalse((root / ".bake.lock").exists())
            self.assertEqual("new\n", (root / "inputs.sha512").read_text())

    def test_same_identity_preserves_cache_and_concurrent_open_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cached = root / "webp/tile"
            cached.parent.mkdir()
            cached.write_text("cached", encoding="utf-8")
            (root / "inputs.sha512").write_text("same\n", encoding="ascii")
            lifecycle = FileSystemRasterCacheLifecycle()
            with lifecycle.open("same", str(root), (str(root / "webp"),)) as first:
                self.assertFalse(first.invalidated)
                with self.assertRaisesRegex(RasterExecutionError, "already in use"):
                    with lifecycle.open("same", str(root), (str(root / "webp"),)):
                        pass
            self.assertEqual("cached", cached.read_text())

    def test_rejects_invalidation_outside_workspace_and_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cached = root / "webp/tile"
            cached.parent.mkdir()
            cached.write_text("preserved", encoding="utf-8")
            outside = root.parent / "outside-raster-cache"
            with self.assertRaisesRegex(RasterExecutionError, "escapes workspace"):
                with FileSystemRasterCacheLifecycle().open(
                    "new", str(root), (str(root / "webp"), str(outside))
                ):
                    pass
            self.assertFalse((root / ".bake.lock").exists())
            self.assertEqual("preserved", cached.read_text())


class FakeLifecycle:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    @contextmanager
    def open(self, identity, workspace, invalidation_paths):
        self.events.append("lock")
        try:
            yield RasterCachePreparation(identity, True)
        finally:
            self.events.append("unlock")


class FakeCache:
    def __init__(self, events: list[str], scans: list[RasterCacheScanResult]) -> None:
        self.events, self.scans = events, scans

    def write_plan(self, plan, plan_path, tiles_path):
        self.events.append("plan")

    def scan(self, plan, webp_directory, missing_path, quarantine_directory, tile_size):
        self.events.append("scan")
        return self.scans.pop(0)


class FakeDisplay:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    @contextmanager
    def open(self, settings):
        self.events.append("display-open")
        try:
            yield RasterDisplayEndpoint(":73", settings.mode, 123, 1.0)
        finally:
            self.events.append("display-close")


class FakeRuntime:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    @contextmanager
    def open(self, request):
        self.events.append("runtime-open")
        try:
            yield RasterRuntimeResult(
                "runtime.json", "http://tiles/{z}/{x}/{y}.mvt",
                RasterMvtPreflightResult("http://tiles/0/0/0.mvt", 2, 1.0),
                "base.pmtiles", RasterSourceMetadata(0, 14, (0, 0, 1, 1)),
            )
        finally:
            self.events.append("runtime-close")


class FakeRenderer:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def render(self, queue_path, settings):
        self.events.append(f"render:{settings.style_path}")
        return RasterRenderResult(1, 1, 1, 0)


class FakeAssembly:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def assemble(self, request):
        self.events.append("assembly")
        return RasterAssemblyResult(1, 1, 20)


class SequenceClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self):
        self.value += 0.001
        return self.value


class RasterBakeServiceTest(unittest.TestCase):
    def request(self, root: Path) -> RasterBakeRequest:
        plan = create_raster_tile_plan(RasterBounds(0, 0, 1, 1), 0, 0, 0)
        identity = RasterCacheIdentity(
            "a" * 128, "b" * 128, "c" * 128, plan, 256, 1, True, 6,
            "none", "mbgl-renderer", "renderer 1",
        )
        render = RasterRenderSettings(
            "style.json", str(root / "png"), str(root / "webp")
        )
        runtime = RasterRuntimeRequest(
            "base.pmtiles", "style.json", "runtime.json",
            next(plan.coordinates()),
        )
        assembly = RasterAssemblySettings(
            "raster", plan.bounds, 0, 0, str(root / "webp")
        )
        return RasterBakeRequest(
            identity, plan, str(root), str(root / "plan.json"),
            str(root / "tiles.tsv"), str(root / "missing.tsv"),
            str(root / "quarantine"), (str(root / "png"), str(root / "webp")),
            render, RasterDisplaySettings(), runtime, assembly, str(root / "out.mbtiles"),
            str(root / "out.pmtiles"),
        )

    def test_runs_miss_render_and_assembly_in_order(self) -> None:
        events: list[str] = []
        scans = [
            RasterCacheScanResult(1, 0, 1, 0, 0),
            RasterCacheScanResult(1, 1, 0, 0, 0),
        ]
        service = RasterBakeService(
            FakeLifecycle(events), FakeCache(events, scans), FakeDisplay(events),
            FakeRuntime(events),
            FakeRenderer(events), FakeAssembly(events), clock=SequenceClock(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = service.bake(self.request(Path(temporary)))
        self.assertEqual(
            ["lock", "plan", "display-open", "runtime-open", "scan",
             "render:runtime.json", "scan", "runtime-close", "display-close",
             "assembly", "unlock"],
            events,
        )
        self.assertEqual(1, result.render.rendered_tiles)
        self.assertEqual(
            ("plan", "cache-scan-initial", "render", "cache-scan-final", "assembly"),
            tuple(item.stage for item in result.timings),
        )

    def test_hot_cache_skips_renderer(self) -> None:
        events: list[str] = []
        scans = [
            RasterCacheScanResult(1, 1, 0, 0, 0),
            RasterCacheScanResult(1, 1, 0, 0, 0),
        ]
        service = RasterBakeService(
            FakeLifecycle(events), FakeCache(events, scans), FakeDisplay(events),
            FakeRuntime(events),
            FakeRenderer(events), FakeAssembly(events), clock=SequenceClock(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = service.bake(self.request(Path(temporary)))
        self.assertIsNone(result.render)
        self.assertNotIn("render:runtime.json", events)

    def test_incomplete_final_scan_prevents_assembly_and_releases_resources(self) -> None:
        events: list[str] = []
        scans = [
            RasterCacheScanResult(1, 0, 1, 0, 0),
            RasterCacheScanResult(1, 0, 1, 0, 0),
        ]
        service = RasterBakeService(
            FakeLifecycle(events), FakeCache(events, scans), FakeDisplay(events),
            FakeRuntime(events),
            FakeRenderer(events), FakeAssembly(events), clock=SequenceClock(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RasterExecutionError, "remains incomplete"):
                service.bake(self.request(Path(temporary)))
        self.assertNotIn("assembly", events)
        self.assertEqual(["runtime-close", "display-close", "unlock"], events[-3:])


class RasterEvidenceTest(unittest.TestCase):
    def test_writes_auditable_parameters_metrics_and_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = RasterBakeServiceTest().request(root)
            result = RasterBakeResult(
                RasterCachePreparation(request.identity.digest, False),
                RasterCacheScanResult(1, 1, 0, 0, 0),
                RasterCacheScanResult(1, 1, 0, 0, 0),
                None,
                RasterAssemblyResult(1, 1, 20),
                RasterMvtPreflightResult("http://tiles/0/0/0.mvt", 2, 1.25),
                (RasterStageTiming("assembly", 2.5),),
            )
            mbtiles, pmtiles = root / "out.mbtiles", root / "out.pmtiles"
            mbtiles.write_bytes(b"m" * 10)
            pmtiles.write_bytes(b"p" * 12)
            parameters, metrics = root / "parameters.json", root / "metrics.json"
            store = FileSystemRasterEvidenceStore(
                AtomicFileWriter(), FileDigestAdapter()
            )
            store.write_parameters(
                str(parameters), request.identity, request.render_settings,
                request.display_settings,
            )
            store.write_metrics(
                str(metrics), result, str(mbtiles), str(pmtiles)
            )
            parameter_document = json.loads(parameters.read_text())
            metrics_document = json.loads(metrics.read_text())
            for artifact in (parameters, metrics):
                expected = hashlib.sha512(artifact.read_bytes()).hexdigest()
                self.assertEqual(
                    f"{expected}  {artifact.name}\n",
                    Path(f"{artifact}.sha512").read_text(),
                )
        self.assertEqual(request.identity.digest, parameter_document["cache_identity"])
        self.assertEqual(1, parameter_document["plan"]["tile_count"])
        self.assertEqual(256, parameter_document["effective"]["tile_size"])
        self.assertEqual(
            "managed-xvfb", parameter_document["execution"]["display"]["mode"]
        )
        self.assertEqual(1, metrics_document["cache"]["initial_hits"])
        self.assertEqual(0, metrics_document["render"]["worker_queue_tiles"])
        self.assertEqual("not-run", metrics_document["quality"]["visual_grid_validation"])
        self.assertEqual({"mbtiles_bytes": 10, "pmtiles_bytes": 12}, metrics_document["artifacts"])

    def test_bootstrap_builds_complete_raster_service(self) -> None:
        service = raster_bake_service()
        self.assertIsInstance(service, RasterBakeService)
        self.assertIsNotNone(service._evidence)


if __name__ == "__main__":
    unittest.main()
