from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.quality.domain.doctor import (
    DoctorReport,
    ToolRequirement,
)
from huavd_map_build.quality.south.port.tool_probe import ToolProbe


CORE_TOOL_REQUIREMENTS = tuple(
    [
        ToolRequirement(name)
        for name in (
        "bash",
        "jq",
        "wget",
        "tar",
        "zip",
        "osmium",
        "tippecanoe",
        "pmtiles",
        "cwebp",
        "dwebp",
        "timeout",
        "xargs",
        "node",
        "pnpm",
        )
    ]
    + [
        ToolRequirement("fonttools", python_module="fontTools"),
        ToolRequirement("mvt-decode", python_module="mapbox_vector_tile"),
    ]
)


class DoctorQuery:
    def __init__(self, tool_probe: ToolProbe, catalog: CatalogService) -> None:
        self._tool_probe = tool_probe
        self._catalog = catalog

    def execute(self) -> DoctorReport:
        tools = tuple(self._tool_probe.probe(item) for item in CORE_TOOL_REQUIREMENTS)
        try:
            catalog = self._catalog.validate()
        except (RuntimeError, ValueError) as error:
            return DoctorReport(tools, None, None, str(error))
        return DoctorReport(
            tools,
            catalog.schema_version,
            catalog.region_count,
            None,
        )
