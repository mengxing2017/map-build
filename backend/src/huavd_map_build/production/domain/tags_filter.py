from dataclasses import dataclass

from huavd_map_build.shared.kernel import RegionId


@dataclass(frozen=True, slots=True)
class TagsFilterRequest:
    region: RegionId
    input_path: str
    workdir: str
    layers: str = "all"


@dataclass(frozen=True, slots=True)
class LayerFilterTask:
    layer: str
    filters: tuple[str, ...]
    output_path: str


@dataclass(frozen=True, slots=True)
class TagsFilterPlan:
    input_path: str
    cache_directory: str
    tasks: tuple[LayerFilterTask, ...]


class TagsFilterExecutionError(RuntimeError):
    pass


class MissingTagsFilterToolError(TagsFilterExecutionError):
    pass
