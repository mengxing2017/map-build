from __future__ import annotations

import os
import shutil
import subprocess


class ProcessToolVersionReader:
    def versions(self, names: tuple[str, ...]) -> dict[str, str]:
        return {name: self._version(name) for name in names}

    @staticmethod
    def _version(name: str) -> str:
        executable = shutil.which(name)
        if executable is None:
            return "missing"
        allowed = ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        for argument in ("--version", "version", "-version"):
            try:
                result = subprocess.run(
                    [executable, argument], env=environment, text=True,
                    capture_output=True, timeout=10, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            output = (result.stdout + "\n" + result.stderr).strip()
            if result.returncode == 0 and output:
                return output.splitlines()[0]
        return "unknown"
