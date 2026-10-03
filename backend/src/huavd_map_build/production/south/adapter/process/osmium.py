from __future__ import annotations

import os
import shutil
import subprocess

from huavd_map_build.production.domain.tags_filter import (
    MissingTagsFilterToolError,
    TagsFilterExecutionError,
)


class OsmiumTagsFilterRunner:
    def filter(
        self, input_path: str, output_path: str, filters: tuple[str, ...]
    ) -> None:
        executable = shutil.which("osmium")
        if executable is None:
            raise MissingTagsFilterToolError("required command not found: osmium")
        arguments = [
            executable, "tags-filter", "-O", "-o", output_path, input_path, *filters
        ]
        allowed = ("HOME", "LANG", "LC_ALL", "PATH")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        try:
            result = subprocess.run(
                arguments, env=environment, text=True, capture_output=True, check=False
            )
        except OSError as error:
            raise TagsFilterExecutionError(
                f"failed to start osmium for {output_path}: {error}"
            ) from error
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()
            message = detail[-1] if detail else f"exit {result.returncode}"
            raise TagsFilterExecutionError(
                f"osmium tags-filter failed for {output_path}: {message}"
            )
