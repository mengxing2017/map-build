from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zlib

from huavd_map_build.production.domain.raster import (
    RasterDisplaySettings, RasterExecutionError, RasterRenderSettings, RasterTileCoordinate,
)
from huavd_map_build.production.south.adapter.process.raster import ProcessRasterTileRenderer
from huavd_map_build.production.south.adapter.process.raster_display import ProcessRasterDisplaySession
from huavd_map_build.production.south.adapter.process.raster_native import (
    NativeProcessRegistry, native_environment, native_renderer_identity, run_native, validate_native_png,
)
from huavd_map_build.production.south.adapter.process.raster_server import UrlLibRasterMvtClient
from unittest.mock import MagicMock


def png(size: int) -> bytes:
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))
    return b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    ) + chunk(b"IDAT", zlib.compress((b"\0" + b"\x12\x34\x56\xff" * size) * size)) + chunk(b"IEND", b"")


class NativeBoundaryTest(unittest.TestCase):
    def test_mvt_preflight_accepts_204_but_rejects_untyped_empty_200(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {}
        response.read.return_value = b""
        response.status = 204
        with patch("huavd_map_build.production.south.adapter.process.raster_server.urlopen", return_value=response):
            result = UrlLibRasterMvtClient().fetch("http://localhost/{z}/{x}/{y}", RasterTileCoordinate(0,0,0), validate=True)
            self.assertEqual(0, result.payload_bytes)
            response.status = 200
            with self.assertRaisesRegex(RasterExecutionError, "empty MVT"):
                UrlLibRasterMvtClient().fetch("http://localhost/{z}/{x}/{y}", RasterTileCoordinate(0,0,0), validate=True)

    def test_headless_never_starts_xvfb_or_forwards_display(self):
        with patch("subprocess.Popen") as popen, patch.dict(os.environ, {
            "DISPLAY": ":99", "VK_DRIVER_FILES": "/driver.json", "HTTP_PROXY": "private",
        }, clear=True):
            with ProcessRasterDisplaySession().open(RasterDisplaySettings(mode="headless")) as endpoint:
                self.assertEqual("", endpoint.display)
                self.assertIsNone(endpoint.server_pid)
            environment = native_environment()
        popen.assert_not_called()
        self.assertNotIn("DISPLAY", environment)
        self.assertNotIn("HTTP_PROXY", environment)
        self.assertEqual("/driver.json", environment["VK_DRIVER_FILES"])

    def test_png_validation_rejects_truncation_crc_and_wrong_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "tile.png"
            target.write_bytes(png(256))
            validate_native_png(str(target), 256)
            for payload in (png(256)[:-8], png(512), png(256)[:-1] + b"x", b"png"):
                target.write_bytes(payload)
                with self.assertRaises(RasterExecutionError):
                    validate_native_png(str(target), 256)

    def test_adapter_passes_xyz_and_validates_output(self):
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "tile.png"
            def run(arguments, timeout, registry=None):
                calls.append((arguments, timeout))
                output.write_bytes(png(256))
            with patch("shutil.which", return_value="/tools/native"), patch(
                "huavd_map_build.production.south.adapter.process.raster_native.run_native", side_effect=run
            ):
                ProcessRasterTileRenderer().render(
                    RasterTileCoordinate(8, 204, 109),
                    RasterRenderSettings("style.json", "png", "webp", renderer_engine="maplibre-native-headless"),
                    str(output),
                )
        arguments, timeout = calls[0]
        self.assertEqual(["--z", "8", "--x", "204", "--y", "109"], arguments[3:9])
        self.assertNotIn("--bounds", arguments)
        self.assertEqual(120, timeout)

    def test_identity_rejects_protocol_and_tracks_actual_binary(self):
        metadata = {"protocol_version": 1, "engine": "maplibre-native-headless", "backend": "vulkan",
                    "wrapper_patch_sha256": "a" * 64, "source_sha256": "b" * 64}
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "native"
            binary.write_bytes(b"first")
            with patch("shutil.which", return_value=str(binary)), patch.dict(os.environ, {}, clear=True), patch(
                "subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(metadata), "")
            ):
                first = native_renderer_identity(str(binary))
                binary.write_bytes(b"second")
                second = native_renderer_identity(str(binary))
                self.assertNotEqual(first, second)
            metadata["protocol_version"] = 2
            with patch("shutil.which", return_value=str(binary)), patch(
                "subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(metadata), "")
            ), self.assertRaisesRegex(RasterExecutionError, "protocol"):
                native_renderer_identity(str(binary))

    def test_timeout_reaps_native_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "pid"
            script = "import os,time,pathlib; pathlib.Path(__import__('sys').argv[1]).write_text(str(os.getpid())); time.sleep(60)"
            with self.assertRaisesRegex(RasterExecutionError, "timed out"):
                run_native([sys.executable, "-c", script, str(marker)], 1)
            pid = int(marker.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_native_error_preserves_bounded_diagnostics(self):
        with self.assertRaises(RasterExecutionError) as caught:
            run_native([sys.executable, "-c", "import sys; print('x'*100000); print('native failure'); sys.exit(3)"], 5)
        self.assertIn("native failure", str(caught.exception))
        self.assertLess(len(str(caught.exception)), 66000)

    def test_input_failure_is_not_retried(self):
        from huavd_map_build.production.domain.raster import RasterNonRetryableError
        from huavd_map_build.production.north.local.raster_render import RasterRenderService
        renderer, encoder, queue = MagicMock(), MagicMock(), MagicMock()
        renderer.render.side_effect = RasterNonRetryableError("invalid style")
        with tempfile.TemporaryDirectory() as temporary:
            settings = RasterRenderSettings("style", temporary, temporary, retries=3)
            with self.assertRaisesRegex(RasterNonRetryableError, "invalid style"):
                RasterRenderService(queue, renderer, encoder)._render_one(RasterTileCoordinate(0,0,0), settings)
        renderer.render.assert_called_once()
        encoder.encode.assert_not_called()

    def test_batch_interrupt_cancels_before_waiting_for_executor(self):
        from huavd_map_build.production.north.local.raster_render import RasterRenderService
        renderer, encoder, queue = MagicMock(), MagicMock(), MagicMock()
        queue.coordinates.return_value = iter((RasterTileCoordinate(1,0,0), RasterTileCoordinate(1,1,0)))
        with tempfile.TemporaryDirectory() as temporary, patch(
            "huavd_map_build.production.north.local.raster_render.wait", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                RasterRenderService(queue, renderer, encoder).render(
                    "queue", RasterRenderSettings("style", temporary, temporary)
                )
        renderer.cancel.assert_called_once()

    def test_registry_cancellation_reaps_worker_and_cleans_exact_partial_png(self):
        registry = NativeProcessRegistry()
        errors = []
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "attempt.png"
            marker = Path(temporary) / "started"
            script = (
                "import os,time,pathlib,sys; p=pathlib.Path(sys.argv[2]); "
                "p.with_name('.'+p.name+'.native-'+str(os.getpid())+'.png').write_bytes(b'partial'); "
                "pathlib.Path(sys.argv[3]).touch(); time.sleep(60)"
            )
            def work():
                try:
                    run_native([sys.executable,"-c",script,"--output",str(output),str(marker)], 60, registry)
                except RasterExecutionError as error:
                    errors.append(error)
            worker = threading.Thread(target=work)
            worker.start()
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
            finally:
                registry.cancel()
                worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertTrue(errors)
            self.assertEqual([marker], list(Path(temporary).iterdir()))


if __name__ == "__main__":
    unittest.main()
