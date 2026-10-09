from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from huavd_map_build.production.domain.tippecanoe import (
    MissingPmtilesToolError,
    MissingTippecanoeToolError,
    TippecanoeExecutionError,
)


class ProcessTippecanoeRunner:
    def run(self, arguments: tuple[str, ...]) -> None:
        executable = shutil.which("tippecanoe")
        if executable is None:
            raise MissingTippecanoeToolError("required command not found: tippecanoe")
        output = self._output_path(arguments)
        if output is None:
            self._run([executable, *arguments], "tippecanoe")
            return

        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent, prefix=f".{target.name}.") as directory:
            mbtiles = Path(directory) / "tiles.mbtiles"
            pmtiles = Path(directory) / "tiles.pmtiles"
            resolved = tuple(
                f"--output={mbtiles}" if argument == f"--output={output}" else argument
                for argument in arguments
            )
            self._run([executable, *resolved], "tippecanoe")
            if not mbtiles.is_file() or mbtiles.stat().st_size == 0:
                raise TippecanoeExecutionError("tippecanoe created no MBTiles output")
            converter = shutil.which("pmtiles")
            if converter is None:
                raise MissingPmtilesToolError("required command not found: pmtiles")
            self._run([converter, "convert", str(mbtiles), str(pmtiles)], "pmtiles convert")
            if not pmtiles.is_file() or pmtiles.stat().st_size == 0:
                raise TippecanoeExecutionError("pmtiles convert created no PMTiles output")
            pmtiles.replace(target)

    @staticmethod
    def _output_path(arguments: tuple[str, ...]) -> str | None:
        outputs = [argument.removeprefix("--output=") for argument in arguments
                   if argument.startswith("--output=")]
        if len(outputs) > 1:
            raise TippecanoeExecutionError("tippecanoe accepts exactly one output path")
        return outputs[0] if outputs else None

    @staticmethod
    def _run(command: list[str], label: str) -> None:
        allowed = ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        try:
            result = subprocess.run(
                command,
                env=environment,
                check=False,
            )
        except OSError as error:
            raise TippecanoeExecutionError(f"failed to start {label}: {error}") from error
        if result.returncode != 0:
            raise TippecanoeExecutionError(f"{label} failed with exit code {result.returncode}")
