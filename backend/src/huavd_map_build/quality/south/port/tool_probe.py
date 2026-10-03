from typing import Protocol

from huavd_map_build.quality.domain.doctor import ToolRequirement, ToolStatus


class ToolProbe(Protocol):
    def probe(self, requirement: ToolRequirement) -> ToolStatus: ...
