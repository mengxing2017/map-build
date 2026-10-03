from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from huavd_map_build.quality.domain.doctor import (
    ToolHealth,
    ToolRequirement,
    ToolStatus,
)


class ProcessToolProbe:
    def __init__(self, repository_root: Path) -> None:
        self._repository_root = repository_root

    def probe(self, requirement: ToolRequirement) -> ToolStatus:
        if getattr(requirement, "python_module", None) is not None:
            return self._probe_python_module(requirement)
        executable = self._resolve(requirement.name)
        if executable is None:
            return ToolStatus(requirement.name, ToolHealth.MISSING)
        for argument in ("--version", "version", "-version"):
            try:
                result = subprocess.run(
                    [str(executable), argument],
                    cwd=self._repository_root,
                    env=self._tool_environment(),
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            output = (result.stdout + "\n" + result.stderr).strip()
            if result.returncode == 0 and output:
                return ToolStatus(
                    requirement.name,
                    ToolHealth.OK,
                    output.splitlines()[0],
                    str(executable),
                )
        return ToolStatus(
            requirement.name,
            ToolHealth.NOT_RUNNABLE,
            executable=str(executable),
        )

    def _probe_python_module(self, requirement: ToolRequirement) -> ToolStatus:
        python = self._resolve("python") or self._resolve("python3")
        if python is None:
            return ToolStatus(requirement.name, ToolHealth.MISSING)
        module = requirement.python_module
        assert module is not None
        statement = (
            "import importlib; "
            f"module = importlib.import_module({module!r}); "
            "print(getattr(module, '__version__', 'found'))"
        )
        try:
            result = subprocess.run(
                [str(python), "-c", statement],
                cwd=self._repository_root,
                env=self._tool_environment(),
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ToolStatus(requirement.name, ToolHealth.NOT_RUNNABLE)
        version = result.stdout.strip()
        if result.returncode == 0 and version:
            return ToolStatus(
                requirement.name,
                ToolHealth.OK,
                version.splitlines()[0],
                str(python),
            )
        return ToolStatus(
            requirement.name,
            ToolHealth.NOT_RUNNABLE,
            executable=str(python),
        )

    def _resolve(self, name: str) -> Path | None:
        found = shutil.which(name)
        candidates = (
            self._repository_root / ".venv/bin" / name,
            self._repository_root / ".devbox/nix/profile/default/bin" / name,
            Path(found) if found else None,
        )
        for candidate in candidates:
            if candidate is not None and candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate.absolute()
        return None

    def _tool_environment(self) -> dict[str, str]:
        allowed = (
            "HOME",
            "LANG",
            "LC_ALL",
            "LD_LIBRARY_PATH",
            "PATH",
            "TMPDIR",
        )
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        path_entries = (
            self._repository_root / ".venv/bin",
            self._repository_root / ".devbox/nix/profile/default/bin",
        )
        existing_path = environment.get("PATH", "")
        environment["PATH"] = os.pathsep.join(
            [*(str(path) for path in path_entries if path.is_dir()), existing_path]
        )
        return environment
