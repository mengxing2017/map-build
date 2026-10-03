from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from huavd_map_build.shared.kernel import RegionId, SessionId


@dataclass(frozen=True, slots=True)
class NormalizeRequest:
    region: RegionId
    session: SessionId
    workdir: str
    layers: str = "all"


@dataclass(frozen=True, slots=True)
class NormalizationPolicy:
    layer: str
    name_order: tuple[str, ...]
    allowed_fields: tuple[str, ...]
    post_filter: dict[str, Any]
    field_types: dict[str, str] = field(default_factory=dict)


_LOCAL_SCRIPT = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_LATIN = re.compile(r"[A-Za-z]")
_SEPARATORS = r"\s()（）\[\]【】,，、/|·:：;；\-"
_TRIM_START = re.compile(f"^[{_SEPARATORS}]+")
_TRIM_END = re.compile(f"[{_SEPARATORS}]+$")
_TRAILING_LATIN = re.compile(
    f"[{_SEPARATORS}]*[A-Za-z][A-Za-z0-9 .&/()\\-]+$"
)
_AREA_AMENITIES = {
    "hospital", "clinic", "doctors", "school", "university", "college",
    "kindergarten",
}


def normalize_feature(
    feature: dict[str, Any], policy: NormalizationPolicy
) -> dict[str, Any] | None:
    properties = feature.get("properties")
    if not properties:
        return feature
    if not isinstance(properties, dict):
        return feature
    excluded = policy.post_filter.get("exclude", {})
    if isinstance(excluded, dict) and any(
        properties.get(field) is not None
        and isinstance(values, list)
        and properties.get(field) in values
        for field, values in excluded.items()
    ):
        return None

    _normalize_geometry(feature, policy.layer, properties)
    geometry = feature.get("geometry")
    geometry_type = geometry.get("type", "") if isinstance(geometry, dict) else ""
    allowed_geometry = policy.post_filter.get("geometry", [])
    if isinstance(allowed_geometry, list) and allowed_geometry and geometry_type not in allowed_geometry:
        return None

    original = dict(properties)
    candidate = next(
        (original.get(key) for key in policy.name_order if original.get(key) not in (None, "")),
        original.get("name"),
    )
    properties["name"] = _clean_bilingual_name(original, candidate)
    if policy.layer == "building":
        properties["type"] = _coalesce_null(properties.get("type"), properties.get("building"))
        properties["levels"] = _coalesce_null(
            properties.get("levels"), properties.get("building:levels")
        )
        properties["roof_height"] = _coalesce_null(
            properties.get("roof_height"), properties.get("roof:height")
        )
    elif policy.layer == "waterway":
        properties["width"] = _number(properties.get("width"))
    elif policy.layer == "peak":
        properties["ele"] = _number(properties.get("ele"))
    elif policy.layer == "place_label":
        properties["population"] = _number(properties.get("population"))
    for key, expected in policy.field_types.items():
        if key not in properties:
            continue
        if expected == "Number":
            properties[key] = _number(properties[key])
        elif expected == "Boolean":
            properties[key] = _boolean(properties[key])
    allowed = set(policy.allowed_fields)
    feature["properties"] = {
        key: value for key, value in properties.items() if key in allowed and value is not None
    }
    return feature


def _trim_separators(value: str) -> str:
    return _TRIM_END.sub("", _TRIM_START.sub("", value))


def _clean_bilingual_name(properties: dict[str, Any], candidate: Any) -> Any:
    if not (
        isinstance(candidate, str)
        and (properties.get("name") or "") == candidate
        and _LOCAL_SCRIPT.search(candidate)
        and _LATIN.search(candidate)
    ):
        return candidate
    localized = properties.get("name:zh-Hans")
    if localized is None:
        localized = properties.get("name:zh")
    if localized is not None:
        return localized
    english = properties.get("name:en")
    without_english = candidate
    if isinstance(english, str) and english and candidate.endswith(english):
        without_english = _trim_separators(candidate[: -len(english)])
    if without_english and without_english != candidate and _LOCAL_SCRIPT.search(without_english):
        return without_english
    without_latin = _trim_separators(_TRAILING_LATIN.sub("", candidate, count=1))
    if without_latin and without_latin != candidate and _LOCAL_SCRIPT.search(without_latin):
        return without_latin
    return candidate


def _number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value) if re.fullmatch(r"[+-]?\d+", value) else float(value)
    except ValueError:
        return None


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value in (1, -1):
            return True
        if value == 0:
            return False
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"yes", "true", "1", "-1"}:
        return True
    if normalized in {"no", "false", "0"}:
        return False
    return None


def _coalesce_null(value: Any, fallback: Any) -> Any:
    return fallback if value is None else value


def _normalize_geometry(
    feature: dict[str, Any], layer: str, properties: dict[str, Any]
) -> None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") == "Point":
        return
    should_center = (
        layer == "poi_label"
        and (properties.get("amenity") or "") in _AREA_AMENITIES
    ) or (layer == "poi_label" and (properties.get("tourism") or "") != "") or (
        layer == "highway_point"
        and (properties.get("highway") or "") in {"services", "rest_area"}
    )
    if not should_center:
        return
    points = list(_coordinate_pairs(geometry.get("coordinates")))
    if points:
        xs, ys = zip(*points)
        feature["geometry"] = {
            "type": "Point",
            "coordinates": [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2],
        }


def _coordinate_pairs(value: Any):
    if (
        isinstance(value, list) and len(value) == 2
        and isinstance(value[0], (int, float)) and not isinstance(value[0], bool)
        and isinstance(value[1], (int, float)) and not isinstance(value[1], bool)
    ):
        yield value[0], value[1]
    elif isinstance(value, list):
        for item in value:
            yield from _coordinate_pairs(item)
