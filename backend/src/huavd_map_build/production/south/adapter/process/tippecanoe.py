from __future__ import annotations

import os
import shutil
import subprocess

from huavd_map_build.production.domain.tippecanoe import (
    MissingTippecanoeToolError,
    TippecanoeExecutionError,
)


class ProcessTippecanoeRunner:
    def run(self, arguments: tuple[str, ...]) -> None:
        executable = shutil.which("tippecanoe")
        if executable is None:
            raise MissingTippecanoeToolError("required command not found: tippecanoe")
        allowed = ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        try:
            result = subprocess.run(
                [executable, *arguments],
                env=environment,
                check=False,
            )
        except OSError as error:
            raise TippecanoeExecutionError(f"failed to start tippecanoe: {error}") from error
        if result.returncode != 0:
            raise TippecanoeExecutionError(
                f"tippecanoe failed with exit code {result.returncode}"
            )
