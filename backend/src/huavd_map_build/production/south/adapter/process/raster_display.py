from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import select
import shutil
import subprocess
import time

from huavd_map_build.production.domain.raster import (
    MissingRasterToolError,
    RasterDisplayEndpoint,
    RasterDisplaySettings,
    RasterExecutionError,
)
from huavd_map_build.production.south.adapter.process.raster import _environment


class ProcessRasterDisplaySession:
    @contextmanager
    def open(self, settings: RasterDisplaySettings):
        if settings.mode == "headless":
            yield RasterDisplayEndpoint("", settings.mode, None, 0.0)
            return
        if settings.mode == "external-x11":
            display = os.environ.get("DISPLAY")
            if not display:
                raise RasterExecutionError("external-x11 requires DISPLAY")
            yield RasterDisplayEndpoint(display, settings.mode, None, 0.0)
            return

        xvfb = shutil.which("Xvfb")
        xdpyinfo = shutil.which("xdpyinfo")
        if xvfb is None:
            raise MissingRasterToolError("required command not found: Xvfb")
        if xdpyinfo is None:
            raise MissingRasterToolError("required command not found: xdpyinfo")

        log_path = Path(settings.log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("wb")
        read_fd, write_fd = os.pipe()
        process: subprocess.Popen[bytes] | None = None
        started = time.perf_counter()
        try:
            process = subprocess.Popen(
                [
                    xvfb, "-displayfd", str(write_fd), "-screen", "0", settings.screen,
                    "-nolisten", "tcp", "-noreset", "+extension", "GLX", "+iglx",
                    "+render",
                ],
                env=_environment(), stdout=log, stderr=subprocess.STDOUT,
                pass_fds=(write_fd,), start_new_session=True,
            )
            os.close(write_fd)
            write_fd = -1
            display = self._read_display(
                process, read_fd, settings.startup_timeout_seconds, log_path
            )
            self._wait_until_ready(
                process, xdpyinfo, display, settings.startup_timeout_seconds, log_path
            )
            yield RasterDisplayEndpoint(
                display, settings.mode, process.pid,
                round((time.perf_counter() - started) * 1000, 3),
            )
        finally:
            if write_fd >= 0:
                os.close(write_fd)
            os.close(read_fd)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            log.close()

    @staticmethod
    def _read_display(
        process: subprocess.Popen[bytes], read_fd: int, timeout: float, log_path: Path,
    ) -> str:
        deadline = time.monotonic() + timeout
        payload = b""
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                raise RasterExecutionError(
                    f"Xvfb exited before ready with code {return_code}; see {log_path}"
                )
            readable, _, _ = select.select([read_fd], [], [], 0.05)
            if readable:
                chunk = os.read(read_fd, 32)
                payload += chunk
                if b"\n" in payload:
                    value = payload.split(b"\n", 1)[0].decode("ascii", errors="strict")
                    if not value.isdigit():
                        raise RasterExecutionError(
                            f"Xvfb returned invalid display number: {value!r}"
                        )
                    return f":{value}"
        raise RasterExecutionError(f"Xvfb startup timed out; see {log_path}")

    @staticmethod
    def _wait_until_ready(
        process: subprocess.Popen[bytes], xdpyinfo: str, display: str,
        timeout: float, log_path: Path,
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                raise RasterExecutionError(
                    f"Xvfb exited before ready with code {return_code}; see {log_path}"
                )
            result = subprocess.run(
                [xdpyinfo, "-display", display],
                env=_environment({"DISPLAY": display}),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            if result.returncode == 0:
                return
            time.sleep(0.05)
        raise RasterExecutionError(f"Xvfb startup timed out; see {log_path}")
