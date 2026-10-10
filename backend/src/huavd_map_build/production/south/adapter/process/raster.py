from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from huavd_map_build.production.domain.raster import (
    MissingRasterToolError,
    RasterExecutionError,
    RasterRenderSettings,
    RasterTileCoordinate,
    webp_dimensions,
)


def _environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    allowed = ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    if extra is not None:
        environment.update(extra)
    return environment


def _executable(command: str) -> str:
    executable = shutil.which(command)
    if executable is None:
        raise MissingRasterToolError(f"required command not found: {command}")
    return executable


def _run(
    arguments: list[str], timeout_seconds: int | None, label: str,
    environment: dict[str, str] | None = None,
) -> None:
    try:
        result = subprocess.run(
            arguments, env=_environment(environment), check=False, timeout=timeout_seconds,
            stdout=sys.stderr,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RasterExecutionError(f"failed to execute {label}: {error}") from error
    if result.returncode != 0:
        raise RasterExecutionError(
            f"{label} failed with exit code {result.returncode}"
        )


class ProcessRasterTileRenderer:
    def __init__(self) -> None:
        from huavd_map_build.production.south.adapter.process.raster_native import NativeProcessRegistry

        self._native_processes = NativeProcessRegistry()

    def cancel(self) -> None:
        self._native_processes.cancel()

    def render(
        self, coordinate: RasterTileCoordinate, settings: RasterRenderSettings,
        output_path: str,
    ) -> None:
        executable = _executable(settings.renderer_command)
        bounds = ",".join(f"{value:.12f}" for value in coordinate.bounds.as_list())
        size = str(settings.tile_size)
        if settings.renderer_engine == "mbgl-renderer":
            arguments = [
                executable, settings.style_path, output_path, size, size, "-b", bounds,
            ]
        elif settings.renderer_engine == "maplibre-native-headless":
            from huavd_map_build.production.south.adapter.process.raster_native import (
                run_native, validate_native_png,
            )

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            run_native([
                executable, "--style", settings.style_path,
                "--z", str(coordinate.zoom), "--x", str(coordinate.x),
                "--y", str(coordinate.y), "--width", size, "--height", size,
                "--output", output_path,
            ], settings.timeout_seconds, registry=self._native_processes)
            validate_native_png(output_path, settings.tile_size)
            return
        else:
            arguments = [
                executable, "--style", settings.style_path, "--bounds", bounds,
                "--width", size, "--height", size, "--output", output_path,
            ]
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        environment = {"DISPLAY": settings.display} if settings.display else None
        _run(
            arguments, settings.timeout_seconds, settings.renderer_command, environment
        )
        if not Path(output_path).is_file():
            raise RasterExecutionError(
                f"renderer did not create output for {coordinate.zoom}/{coordinate.x}/{coordinate.y}"
            )


class ProcessWebpEncoder:
    def encode(
        self, input_path: str, output_path: str, settings: RasterRenderSettings,
    ) -> None:
        cwebp, dwebp = _executable("cwebp"), _executable("dwebp")
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.name}.", suffix=".webp", delete=False,
        ) as temporary_file:
            temporary = Path(temporary_file.name)
        try:
            arguments = [cwebp]
            if settings.webp_lossless:
                arguments.append("-lossless")
            arguments.extend([
                "-m", str(settings.webp_method), "-metadata", settings.webp_metadata,
                input_path, "-o", str(temporary),
            ])
            _run(arguments, settings.timeout_seconds, "cwebp")
            _run(
                [dwebp, str(temporary), "-o", os.devnull],
                settings.timeout_seconds, "dwebp",
            )
            payload = temporary.read_bytes()
            if webp_dimensions(payload) != (settings.tile_size, settings.tile_size):
                raise RasterExecutionError("encoded WebP has unexpected dimensions")
            temporary.replace(target)
            self._write_digest(target, payload)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _write_digest(target: Path, payload: bytes) -> None:
        marker = Path(f"{target}.sha512")
        content = f"{hashlib.sha512(payload).hexdigest()}  {target.name}\n"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=marker.parent,
            prefix=f".{marker.name}.", delete=False,
        ) as output:
            temporary = Path(output.name)
            try:
                output.write(content)
                output.flush()
                temporary.replace(marker)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
