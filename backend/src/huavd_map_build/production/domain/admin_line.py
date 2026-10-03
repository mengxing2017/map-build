from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AdminLineDecision:
    feature: dict[str, Any] | None
    audit: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AdminLineRequest:
    target: str
    build_date: str
    workdir: str
    session: str
    overview: bool = False
    input_path: str | None = None
    filtered_pbf: str | None = None


class AdminLineExecutionError(RuntimeError):
    pass


class MissingAdminLineToolError(AdminLineExecutionError):
    pass


def classify_admin_line(
    feature: dict[str, Any],
    relation_levels: dict[str, tuple[int, ...]],
    hierarchy: dict[str, dict[str, Any]],
) -> AdminLineDecision:
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        properties = {}
        feature["properties"] = properties
    geometry = feature.get("geometry")
    geometry_type = geometry.get("type", "unknown") if isinstance(geometry, dict) else "unknown"
    way_id = _jq_string(properties.get("@id"))
    linked_levels = relation_levels.get(way_id, ())
    way_level = _numeric_level(properties.get("admin_level"))
    render_level = min(linked_levels) if linked_levels else way_level
    if geometry_type not in {"LineString", "MultiLineString"}:
        return _discard("geometry", geometry_type)
    if render_level is None:
        reason = "missing_level" if properties.get("admin_level") is None else "invalid_level"
        return _discard(reason, geometry_type)
    if not linked_levels and properties.get("boundary", "") != "administrative":
        return _discard("unlinked_boundary", geometry_type)
    tier = hierarchy["level_tier"].get(str(render_level))
    if tier is None:
        return AdminLineDecision(
            None,
            {"status": "discarded", "reason": "unmapped_level",
             "geometry": geometry_type, "level": render_level},
        )
    source = "relation" if linked_levels else "way"
    properties["admin_level"] = render_level
    properties["admin_tier"] = tier
    properties["level_source"] = source
    properties.pop("@id", None)
    feature["tippecanoe"] = dict(hierarchy["tier_zoom"][tier])
    return AdminLineDecision(
        feature,
        {"status": "kept", "geometry": geometry_type, "level": render_level,
         "tier": tier, "level_source": source},
    )


def _numeric_level(value: Any) -> int | None:
    if isinstance(value, str):
        return int(value) if value.isdigit() else None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0 and int(value) == value:
        return int(value)
    return None


def _jq_string(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _discard(reason: str, geometry: str) -> AdminLineDecision:
    return AdminLineDecision(
        None, {"status": "discarded", "reason": reason, "geometry": geometry}
    )
