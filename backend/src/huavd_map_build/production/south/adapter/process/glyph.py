from __future__ import annotations

import os
import shutil
import subprocess

from huavd_map_build.production.domain.glyph import (
    GlyphExecutionError,
    MissingGlyphToolError,
)


class ProcessGlyphGenerator:
    def generate(self, command: str, font_path: str, output_directory: str) -> None:
        executable = shutil.which(command)
        if executable is None:
            raise MissingGlyphToolError(f"required command not found: {command}")
        allowed = ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        cargo_bin = os.path.join(environment.get("HOME", ""), ".cargo", "bin")
        cargo_generator = os.path.join(cargo_bin, "versatiles_glyphs")
        if command == "build-glyphs" and os.path.isfile(cargo_generator):
            environment["PATH"] = os.pathsep.join(
                value for value in (cargo_bin, environment.get("PATH", "")) if value
            )
        try:
            result = subprocess.run(
                [executable, font_path, output_directory],
                env=environment,
                check=False,
            )
        except OSError as error:
            raise GlyphExecutionError(
                f"failed to start glyph generator {command}: {error}"
            ) from error
        if result.returncode != 0:
            raise GlyphExecutionError(
                f"glyph generator failed with exit code {result.returncode}"
            )
