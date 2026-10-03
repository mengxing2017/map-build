from pathlib import Path

from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.model import BuildPlan
from huavd_map_build.shared.kernel import BuildDate, RegionId, SessionId
from huavd_map_build.shared.kernel.identity import expand_roles


class BuildPlanner:
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    def plan(
        self,
        *,
        region: RegionId,
        build_date: BuildDate,
        role: str,
        workdir: Path,
        input_path: Path | None = None,
    ) -> BuildPlan:
        roles = expand_roles(role)
        session = SessionId.for_build(region, build_date)
        source = input_path or workdir / "mirror" / self._catalog.pbf_basename(region)
        outputs = tuple(
            str(
                workdir
                / "outputs"
                / f"{region.slug}-{build_date.value}.{resolved_role.value}.pmtiles"
            )
            for resolved_role in roles
        )
        return BuildPlan(region, build_date, session, roles, str(source), outputs)
