from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from huavd_map_build.production.domain.raster import (
    MissingRasterToolError,
    RasterDisplaySettings,
    RasterExecutionError,
)
from huavd_map_build.production.south.adapter.process.raster_display import (
    ProcessRasterDisplaySession,
)


class RasterDisplaySessionTest(unittest.TestCase):
    def test_external_mode_requires_and_returns_display(self) -> None:
        session = ProcessRasterDisplaySession()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RasterExecutionError, "requires DISPLAY"):
                with session.open(RasterDisplaySettings(mode="external-x11")):
                    pass
        with patch.dict(os.environ, {"DISPLAY": ":42"}, clear=True):
            with session.open(RasterDisplaySettings(mode="external-x11")) as endpoint:
                self.assertEqual(":42", endpoint.display)
                self.assertIsNone(endpoint.server_pid)

    def test_managed_mode_reports_missing_xvfb(self) -> None:
        with patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(MissingRasterToolError, "Xvfb"):
                with ProcessRasterDisplaySession().open(RasterDisplaySettings()):
                    pass

    def test_managed_mode_uses_displayfd_and_reaps_process(self) -> None:
        process = MagicMock()
        process.pid = 123
        process.poll.return_value = None
        process.wait.return_value = 0
        with tempfile.TemporaryDirectory() as temporary:
            settings = RasterDisplaySettings(log_path=str(Path(temporary) / "xvfb.log"))
            with patch(
                "shutil.which", side_effect=lambda command: f"/tools/{command}"
            ), patch("subprocess.Popen", return_value=process) as popen, patch.object(
                ProcessRasterDisplaySession, "_read_display", return_value=":73"
            ), patch.object(ProcessRasterDisplaySession, "_wait_until_ready"):
                with ProcessRasterDisplaySession().open(settings) as endpoint:
                    self.assertEqual(":73", endpoint.display)
                    self.assertEqual(123, endpoint.server_pid)
        arguments = popen.call_args.args[0]
        self.assertEqual("/tools/Xvfb", arguments[0])
        self.assertIn("-displayfd", arguments)
        self.assertIn("-nolisten", arguments)
        self.assertIn("+iglx", arguments)
        self.assertNotIn("-ac", arguments)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)

    def test_ready_failure_still_reaps_process(self) -> None:
        process = MagicMock()
        process.poll.return_value = None
        process.wait.return_value = 0
        with tempfile.TemporaryDirectory() as temporary, patch(
            "shutil.which", side_effect=lambda command: f"/tools/{command}"
        ), patch("subprocess.Popen", return_value=process), patch.object(
            ProcessRasterDisplaySession, "_read_display", return_value=":73"
        ), patch.object(
            ProcessRasterDisplaySession, "_wait_until_ready",
            side_effect=RasterExecutionError("not ready"),
        ):
            with self.assertRaisesRegex(RasterExecutionError, "not ready"):
                with ProcessRasterDisplaySession().open(RasterDisplaySettings(
                    log_path=str(Path(temporary) / "xvfb.log")
                )):
                    pass
        process.terminate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
