from __future__ import annotations

from pathlib import Path
import tempfile

from huavd_map_build.production.domain.raster import RasterExecutionError
from huavd_map_build.production.south.adapter.process.raster import _executable, _run


class ProcessRasterArchive:
    def extract(
        self, input_path: str, output_path: str, bounds: str,
        min_zoom: int, max_zoom: int,
    ) -> None:
        self._publish([
            "extract", input_path, "{output}", f"--bbox={bounds}",
            f"--minzoom={min_zoom}", f"--maxzoom={max_zoom}",
        ], output_path, "pmtiles extract")

    def convert(self, input_path: str, output_path: str) -> None:
        self._publish(["convert", input_path, "{output}"], output_path, "pmtiles convert")

    @staticmethod
    def _publish(arguments: list[str], output_path: str, label: str) -> None:
        executable = _executable("pmtiles")
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.name}.", suffix=".pmtiles", delete=False,
        ) as output:
            temporary = Path(output.name)
        temporary.unlink()
        try:
            resolved = [str(temporary) if value == "{output}" else value for value in arguments]
            _run([executable, *resolved], None, label)
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise RasterExecutionError(f"{label} created no output")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
