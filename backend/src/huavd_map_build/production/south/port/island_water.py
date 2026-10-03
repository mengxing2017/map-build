from typing import Protocol

from huavd_map_build.production.domain.island_water import IslandWaterResult


class IslandWaterStore(Protocol):
    def flag(
        self, islands: str, waters: str, cache_directory: str, report: str, region: str
    ) -> IslandWaterResult: ...
