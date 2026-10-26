from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from huavd_map_build.production.domain.raster import (
    MissingRasterToolError,
    RasterBatchExecutionError,
    RasterExecutionError,
    RasterNonRetryableError,
    RasterRenderSettings,
    RasterTileCoordinate,
)
from huavd_map_build.production.north.local.raster_render import RasterRenderService
from huavd_map_build.production.south.adapter.process.raster import (
    ProcessRasterTileRenderer,
    ProcessWebpEncoder,
)
from huavd_map_build.production.south.adapter.workspace.raster_queue import (
    FileSystemRasterWorkQueue,
)


def lossless_webp(size: int = 256) -> bytes:
    bits = ((size - 1) | ((size - 1) << 14)).to_bytes(4, "little")
    chunk = b"\x2f" + bits
    return (
        b"RIFF" + (len(chunk) + 12).to_bytes(4, "little") + b"WEBPVP8L"
        + len(chunk).to_bytes(4, "little") + chunk + b"\x00"
    )


class RasterProcessAdapterTest(unittest.TestCase):
    def settings(self, root: Path, **overrides) -> RasterRenderSettings:
        values = dict(
            style_path=str(root / "style.json"), png_directory=str(root / "png"),
            webp_directory=str(root / "webp"),
        )
        values.update(overrides)
        return RasterRenderSettings(**values)

    def test_mbgl_renderer_uses_argument_vector_and_exact_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, calls = Path(temporary), []
            output = root / "tile.png"

            def run(arguments, **kwargs):
                calls.append((arguments, kwargs))
                output.write_bytes(b"png")
                return subprocess.CompletedProcess(arguments, 0)

            with patch("shutil.which", return_value="/tools/mbgl-render"), patch(
                "subprocess.run", side_effect=run
            ):
                ProcessRasterTileRenderer().render(
                    RasterTileCoordinate(1, 1, 0),
                    self.settings(root, display=":73"), str(output)
                )
        self.assertEqual("/tools/mbgl-render", calls[0][0][0])
        self.assertEqual(["256", "256", "-b"], calls[0][0][3:6])
        self.assertNotIn("shell", calls[0][1])
        self.assertEqual(120, calls[0][1]["timeout"])
        self.assertEqual(":73", calls[0][1]["env"]["DISPLAY"])
        self.assertNotIn("HTTP_PROXY", calls[0][1]["env"])

    def test_maplibre_renderer_uses_named_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, calls = Path(temporary), []
            output = root / "tile.png"

            def run(arguments, **kwargs):
                calls.append(arguments)
                output.write_bytes(b"png")
                return subprocess.CompletedProcess(arguments, 0)

            settings = self.settings(
                root, renderer_engine="maplibre-native", renderer_command="renderer"
            )
            with patch("shutil.which", return_value="/tools/renderer"), patch(
                "subprocess.run", side_effect=run
            ):
                ProcessRasterTileRenderer().render(
                    RasterTileCoordinate(1, 1, 0), settings, str(output)
                )
        self.assertEqual("--style", calls[0][1])
        self.assertEqual("--output", calls[0][-2])

    def test_encoder_validates_and_publishes_webp_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, calls = Path(temporary), []
            source, target = root / "tile.png", root / "out" / "tile.webp"
            source.write_bytes(b"png")

            def run(arguments, **kwargs):
                calls.append((arguments, kwargs))
                if arguments[0] == "/tools/cwebp":
                    Path(arguments[-1]).write_bytes(lossless_webp())
                return subprocess.CompletedProcess(arguments, 0)

            with patch(
                "shutil.which", side_effect=lambda command: f"/tools/{command}"
            ), patch("subprocess.run", side_effect=run):
                ProcessWebpEncoder().encode(
                    str(source), str(target), self.settings(root)
                )
            self.assertEqual(lossless_webp(), target.read_bytes())
            self.assertTrue(Path(f"{target}.sha512").is_file())
            self.assertEqual(["-lossless", "-m", "6", "-metadata", "none"], calls[0][0][1:6])
            self.assertEqual("/tools/dwebp", calls[1][0][0])
            self.assertNotIn("shell", calls[0][1])

    def test_missing_tool_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "shutil.which", return_value=None
        ):
            with self.assertRaisesRegex(MissingRasterToolError, "mbgl-render"):
                ProcessRasterTileRenderer().render(
                    RasterTileCoordinate(0, 0, 0),
                    self.settings(Path(temporary)), str(Path(temporary) / "tile.png"),
                )


class TrackingRenderer:
    def __init__(self, fail_once: RasterTileCoordinate | None = None) -> None:
        self.fail_once = fail_once
        self.calls: dict[RasterTileCoordinate, int] = {}
        self.active = 0
        self.maximum_active = 0
        self.lock = threading.Lock()

    def render(self, coordinate, settings, output_path) -> None:
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.calls[coordinate] = self.calls.get(coordinate, 0) + 1
            call = self.calls[coordinate]
        try:
            time.sleep(0.01)
            if coordinate == self.fail_once and call == 1:
                raise RuntimeError("transient")
            Path(output_path).write_bytes(b"png")
        finally:
            with self.lock:
                self.active -= 1


class FakeEncoder:
    def encode(self, input_path, output_path, settings) -> None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(lossless_webp(settings.tile_size))


class RasterRenderServiceTest(unittest.TestCase):
    def test_preflight_failure_stops_before_worker_pool(self) -> None:
        coordinates = [RasterTileCoordinate(2, index, 0) for index in range(3)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "tiles.tsv"
            queue.write_text("".join(item.tsv() for item in coordinates), encoding="utf-8")
            renderer = TrackingRenderer(coordinates[0])
            settings = RasterRenderSettings(
                str(root / "style.json"), str(root / "png"), str(root / "webp"),
                retries=0,
            )
            with self.assertRaises(RasterBatchExecutionError):
                RasterRenderService(
                    FileSystemRasterWorkQueue(), renderer, FakeEncoder()
                ).render(str(queue), settings)
        self.assertEqual({coordinates[0]: 1}, renderer.calls)

    def test_streams_with_bounded_workers_and_retries_only_failure(self) -> None:
        coordinates = [RasterTileCoordinate(3, index, 0) for index in range(6)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "tiles.tsv"
            queue.write_text("".join(item.tsv() for item in coordinates), encoding="utf-8")
            renderer = TrackingRenderer(coordinates[2])
            settings = RasterRenderSettings(
                str(root / "style.json"), str(root / "png"), str(root / "webp"),
                parallel_jobs=2, retries=1,
            )
            result = RasterRenderService(
                FileSystemRasterWorkQueue(), renderer, FakeEncoder()
            ).render(str(queue), settings)
        self.assertEqual(6, result.planned_tiles)
        self.assertEqual({"render:retryable": 1}, result.failure_counts)
        self.assertEqual(7, result.attempts)
        self.assertEqual(1, result.retried_tiles)
        self.assertLessEqual(renderer.maximum_active, 2)
        self.assertEqual(2, renderer.calls[coordinates[2]])
        self.assertTrue(all(
            count == 1 for coordinate, count in renderer.calls.items()
            if coordinate != coordinates[2]
        ))

    def test_reports_failed_batch_after_retry_budget(self) -> None:
        coordinate = RasterTileCoordinate(0, 0, 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "tiles.tsv"
            queue.write_text(coordinate.tsv(), encoding="utf-8")
            renderer = TrackingRenderer(coordinate)
            settings = RasterRenderSettings(
                str(root / "style.json"), str(root / "png"), str(root / "webp"),
                retries=0,
            )
            with self.assertRaises(RasterBatchExecutionError) as raised:
                RasterRenderService(
                    FileSystemRasterWorkQueue(), renderer, FakeEncoder()
                ).render(str(queue), settings)
        self.assertEqual(1, raised.exception.failed_tiles)
        self.assertEqual(1, len(raised.exception.samples))

    def test_failed_worker_metrics_include_all_attempts_and_exit_codes(self):
        coordinates = [RasterTileCoordinate(2, i, 0) for i in range(3)]
        class Renderer:
            def render(self, coordinate, settings, output_path):
                if coordinate.x == 1:
                    error = RasterExecutionError("native failure")
                    error.exit_code = 6
                    raise error
                Path(output_path).write_bytes(b"png")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "tiles.tsv"
            queue.write_text("".join(item.tsv() for item in coordinates))
            settings = RasterRenderSettings("style.json", str(root / "png"), str(root / "webp"), retries=1)
            with self.assertRaises(RasterBatchExecutionError) as raised:
                RasterRenderService(FileSystemRasterWorkQueue(), Renderer(), FakeEncoder()).render(str(queue), settings)
            metrics = raised.exception.metrics
            self.assertEqual(3, metrics["worker_queue_tiles"])
            self.assertEqual(2, metrics["rendered_tiles"])
            self.assertEqual(1, metrics["failed_tiles"])
            self.assertEqual(4, metrics["attempts"])
            self.assertEqual(1, metrics["retried_tiles"])
            self.assertEqual({"render:retryable": 2}, metrics["failure_counts"])
            self.assertEqual({"6": 2}, metrics["exit_code_counts"])
            self.assertEqual([], list((root / "png").rglob("*.png")))

    def test_non_retryable_encoder_preflight_failure_is_counted_once(self):
        class Encoder:
            def encode(self, *args):
                raise RasterNonRetryableError("bad encoder configuration")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "tiles.tsv"
            queue.write_text("0\t0\t0\n")
            settings = RasterRenderSettings("style.json", str(root / "png"), str(root / "webp"), retries=2)
            with self.assertRaises(RasterBatchExecutionError) as raised:
                RasterRenderService(FileSystemRasterWorkQueue(), TrackingRenderer(), Encoder()).render(str(queue), settings)
            metrics = raised.exception.metrics
            self.assertEqual(1, metrics["attempts"])
            self.assertEqual(0, metrics["rendered_tiles"])
            self.assertEqual(0, metrics["retried_tiles"])
            self.assertEqual({"encode:non-retryable": 1}, metrics["failure_counts"])

    def test_queue_rejects_invalid_rows_with_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary) / "tiles.tsv"
            queue.write_text("zoom\tx\ty\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "row 1"):
                list(FileSystemRasterWorkQueue().coordinates(str(queue)))

    def test_serial_batches_bound_each_callback_and_keep_the_last_partial_batch(self) -> None:
        coordinates = [RasterTileCoordinate(3, index, 0) for index in range(5)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "tiles.tsv"
            queue.write_text("".join(item.tsv() for item in coordinates), encoding="utf-8")
            batches = []
            settings = RasterRenderSettings(
                str(root / "style.json"), str(root / "png"), str(root / "webp"),
                parallel_jobs=2, batch_tiles=2,
            )
            result = RasterRenderService(
                FileSystemRasterWorkQueue(), TrackingRenderer(), FakeEncoder()
            ).render(str(queue), settings, on_batch=batches.append)
        self.assertEqual([1, 2, 3], [item.index for item in batches])
        self.assertEqual([2, 2, 1], [item.planned_tiles for item in batches])
        self.assertEqual([2, 2, 1], [item.rendered_tiles for item in batches])
        self.assertEqual([0, 0, 0], [item.failed_tiles for item in batches])
        self.assertEqual(5, result.planned_tiles)
        self.assertEqual(5, result.rendered_tiles)

    def test_failed_batch_reports_progress_and_skips_remaining_batches(self) -> None:
        coordinates = [RasterTileCoordinate(3, index, 0) for index in range(5)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "tiles.tsv"
            queue.write_text("".join(item.tsv() for item in coordinates), encoding="utf-8")
            renderer = TrackingRenderer(coordinates[2])
            batches = []
            settings = RasterRenderSettings(
                str(root / "style.json"), str(root / "png"), str(root / "webp"),
                retries=0, batch_tiles=2,
            )
            with self.assertRaises(RasterBatchExecutionError) as raised:
                RasterRenderService(
                    FileSystemRasterWorkQueue(), renderer, FakeEncoder()
                ).render(str(queue), settings, on_batch=batches.append)
        self.assertEqual(2, len(batches))
        self.assertEqual(1, batches[-1].failed_tiles)
        self.assertEqual(1, len(batches[-1].failed_samples))
        self.assertEqual(1, raised.exception.failed_tiles)
        self.assertNotIn(coordinates[3], renderer.calls)
        self.assertNotIn(coordinates[4], renderer.calls)

    def test_batch_size_validation_rejects_zero_and_non_positive_values(self) -> None:
        for batch_tiles in (0, -1, True):
            with self.subTest(batch_tiles=batch_tiles), self.assertRaisesRegex(
                ValueError, "batch_tiles"
            ):
                RasterRenderSettings(
                    "style.json", "png", "webp", batch_tiles=batch_tiles
                )


if __name__ == "__main__":
    unittest.main()
