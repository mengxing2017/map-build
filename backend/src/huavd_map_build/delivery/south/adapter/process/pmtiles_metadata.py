from __future__ import annotations

import os
import shutil
import subprocess

from huavd_map_build.delivery.domain.metadata import (
    MetadataEditError,
    MissingPmtilesToolError,
)


class ProcessPmtilesMetadataEditor:
    def edit(self, pmtiles_path: str, metadata_path: str) -> None:
        executable = shutil.which("pmtiles")
        if executable is None:
            raise MissingPmtilesToolError("required command not found: pmtiles")
        allowed = ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        try:
            result = subprocess.run(
                [executable, "edit", pmtiles_path, f"--metadata={metadata_path}"],
                env=environment, check=False,
            )
        except OSError as error:
            raise MetadataEditError(f"failed to start pmtiles: {error}") from error
        if result.returncode != 0:
            raise MetadataEditError(
                f"pmtiles metadata edit failed with exit code {result.returncode}"
            )
