from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

from huavd_map_build.production.domain.admin_line import (
    AdminLineExecutionError,
    MissingAdminLineToolError,
)


class OsmiumRelationLevelReader:
    def read(self, pbf_path: str) -> dict[str, tuple[int, ...]]:
        executable = shutil.which("osmium")
        if executable is None:
            raise MissingAdminLineToolError("required command not found: osmium")
        allowed = ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        try:
            process = subprocess.Popen(
                [executable, "cat", pbf_path, "-t", "r", "-f", "xml", "-o", "-"],
                stdout=subprocess.PIPE,
                env=environment,
            )
        except OSError as error:
            raise AdminLineExecutionError(f"failed to start osmium: {error}") from error
        assert process.stdout is not None
        levels: dict[str, set[int]] = {}
        try:
            for _event, element in ET.iterparse(process.stdout, events=("end",)):
                if element.tag != "relation":
                    continue
                level = next(
                    (tag.get("v") for tag in element.findall("tag")
                     if tag.get("k") == "admin_level"),
                    None,
                )
                if level is not None and level.isdigit():
                    numeric = int(level)
                    for member in element.findall("member"):
                        if member.get("type") == "way" and (reference := member.get("ref")):
                            levels.setdefault(reference, set()).add(numeric)
                element.clear()
        except (ET.ParseError, OSError) as error:
            process.kill()
            process.wait()
            raise AdminLineExecutionError(f"cannot parse osmium relation XML: {error}") from error
        return_code = process.wait()
        if return_code != 0:
            raise AdminLineExecutionError(
                f"osmium relation export failed with exit code {return_code}"
            )
        return {key: tuple(sorted(value)) for key, value in levels.items()}
