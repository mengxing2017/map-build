from typing import Protocol

from huavd_map_build.production.domain.island_anchor import IslandAnchorResult


class IslandAnchorStore(Protocol):
    def derive(
        self, islands: str, cache_directory: str, report: str, region: str
    ) -> IslandAnchorResult: ...
