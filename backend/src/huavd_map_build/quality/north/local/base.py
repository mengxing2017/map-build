from huavd_map_build.production.domain.model import BuildPlan
from huavd_map_build.quality.domain.base import (
    BaseDeepQualityError,
    BaseDeepQualityReport,
)
from huavd_map_build.quality.north.local.staging import BaseStagingQualityGate
from huavd_map_build.quality.north.local.tile import VectorTileSamplingGate


class BaseDeepQualityGate:
    def __init__(
        self, staging: BaseStagingQualityGate, tiles: VectorTileSamplingGate
    ) -> None:
        self._staging, self._tiles = staging, tiles

    def inspect(self, build: BuildPlan) -> BaseDeepQualityReport:
        staging = self._staging.inspect(build)
        tiles = self._tiles.verify(
            region=build.region,
            build_date=build.build_date,
            workdir=build.workdir,
        )
        return BaseDeepQualityReport(staging, tiles)

    def verify(self, build: BuildPlan) -> None:
        report = self.inspect(build)
        if not report.passed:
            raise BaseDeepQualityError(report)
