from typing import Protocol

from huavd_map_build.production.domain.model import BuildPlan


class BuildStageExecutor(Protocol):
    def execute(self, stage_id: str, build: BuildPlan) -> None: ...


class BuildSourceWorkspace(Protocol):
    def link(self, input_path: str, workdir: str, session: str) -> str: ...


class BaseDeepVerifier(Protocol):
    def verify(self, build: BuildPlan) -> None: ...
