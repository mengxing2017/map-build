import json
import os
from pathlib import Path
import tempfile

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
            source_coverage=staging.coverage,
            session=build.session,
        )
        return BaseDeepQualityReport(staging, tiles)

    def verify(self, build: BuildPlan) -> None:
        report = self.inspect(build)
        target = Path(build.workdir) / "staging" / build.session.value / "quality" / "base-deep.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".base-deep.", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            json.dump(report.as_dict(), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        try:
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        if not report.passed:
            raise BaseDeepQualityError(report)
