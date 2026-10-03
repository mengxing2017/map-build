from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any


class ProcessPmtilesMetadataReader:
    def embedded_metadata(self, path: str) -> dict[str, Any]:
        executable = shutil.which("pmtiles")
        if executable is None:
            raise RuntimeError("required command not found: pmtiles")
        allowed = ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        try:
            result = subprocess.run(
                [executable, "show", path, "--metadata"], env=environment,
                text=True, capture_output=True, check=False,
            )
        except OSError as error:
            raise RuntimeError(f"failed to start pmtiles: {error}") from error
        if result.returncode != 0:
            raise RuntimeError(
                f"pmtiles metadata read failed with exit code {result.returncode}"
            )
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ValueError("pmtiles returned invalid metadata JSON") from error
        if not isinstance(document, dict):
            raise ValueError("pmtiles metadata must be a JSON object")
        return document
