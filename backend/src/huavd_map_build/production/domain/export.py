from dataclasses import dataclass

from huavd_map_build.shared.kernel import RegionId, SessionId


@dataclass(frozen=True, slots=True)
class ExportRequest:
    region: RegionId
    session: SessionId
    workdir: str
    layers: str = "all"


@dataclass(frozen=True, slots=True)
class LayerExportTask:
    layer: str
    input_path: str
    source_config: str
    staged_config: str
    output_path: str
    keep_untagged: bool


@dataclass(frozen=True, slots=True)
class ExportPlan:
    layers_directory: str
    tasks: tuple[LayerExportTask, ...]


class ExportExecutionError(RuntimeError):
    pass


class MissingExportToolError(ExportExecutionError):
    pass
