from dataclasses import dataclass

from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


@dataclass(frozen=True, slots=True)
class TippecanoeRequest:
    region: RegionId
    build_date: BuildDate
    session: SessionId
    role: Role
    workdir: str


@dataclass(frozen=True, slots=True)
class TippecanoePlan:
    output_path: str
    layer_paths: tuple[tuple[str, str], ...]
    arguments: tuple[str, ...]


class TippecanoeExecutionError(RuntimeError):
    pass


class MissingTippecanoeToolError(TippecanoeExecutionError):
    pass


class MissingPmtilesToolError(TippecanoeExecutionError):
    pass
