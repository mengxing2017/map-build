from __future__ import annotations

from dataclasses import dataclass

from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


@dataclass(frozen=True, slots=True)
class BuildPlan:
    region: RegionId
    build_date: BuildDate
    session: SessionId
    roles: tuple[Role, ...]
    input_path: str
    output_paths: tuple[str, ...]

    @property
    def workdir(self) -> str:
        if not self.output_paths:
            raise ValueError("build plan has no output paths")
        marker = "/outputs/"
        output = self.output_paths[0]
        if marker not in output:
            raise ValueError(f"output path is outside the workspace contract: {output}")
        return output.rsplit(marker, 1)[0]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "region": self.region.value,
            "yyyymmdd": self.build_date.value,
            "session": self.session.value,
            "roles": [role.value for role in self.roles],
            "input": self.input_path,
            "outputs": list(self.output_paths),
        }
