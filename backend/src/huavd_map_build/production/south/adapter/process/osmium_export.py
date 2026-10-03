from __future__ import annotations

import os
import shutil
import subprocess

from huavd_map_build.production.domain.export import (
    ExportExecutionError,
    MissingExportToolError,
)


class OsmiumExportRunner:
    def export(
        self,
        input_path: str,
        output_path: str,
        config_path: str,
        keep_untagged: bool,
    ) -> None:
        executable = shutil.which("osmium")
        if executable is None:
            raise MissingExportToolError("required command not found: osmium")
        arguments = [executable, "export"]
        if keep_untagged:
            arguments.append("--keep-untagged")
        arguments.extend(
            ["-c", config_path, "-f", "geojsonseq", "-O", "-o", output_path, input_path]
        )
        allowed = ("HOME", "LANG", "LC_ALL", "PATH")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        try:
            result = subprocess.run(
                arguments, env=environment, text=True, capture_output=True, check=False
            )
        except OSError as error:
            raise ExportExecutionError(
                f"failed to start osmium export for {output_path}: {error}"
            ) from error
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()
            message = detail[-1] if detail else f"exit {result.returncode}"
            raise ExportExecutionError(
                f"osmium export failed for {output_path}: {message}"
            )
