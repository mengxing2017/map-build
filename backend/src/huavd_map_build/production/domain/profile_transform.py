from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from huavd_map_build.shared.kernel import RegionId, SessionId


@dataclass(frozen=True, slots=True)
class ProfileTransformRequest:
    region: RegionId
    session: SessionId
    workdir: str
    layers: str


@dataclass(frozen=True, slots=True)
class FeatureRule:
    when: dict[str, list[Any]]
    min_zoom: int
    max_zoom: int


@dataclass(frozen=True, slots=True)
class LayerProfilePolicy:
    layer: str
    min_zoom: int
    max_zoom: int
    rules: tuple[FeatureRule, ...] | None


def transform_profile_feature(
    feature: dict[str, Any], policy: LayerProfilePolicy
) -> dict[str, Any] | None:
    properties = feature.get("properties")
    if feature.get("type") != "Feature" or not isinstance(properties, dict):
        return feature
    if policy.rules is None:
        tippecanoe = feature.get("tippecanoe")
        if tippecanoe is None:
            tippecanoe = {}
        if not isinstance(tippecanoe, dict):
            raise ValueError("feature tippecanoe member must be an object")
        minimum, maximum = policy.min_zoom, policy.max_zoom
        if policy.layer in {"place_label", "admin_line"}:
            minimum = max(minimum, tippecanoe.get("minzoom", minimum))
            maximum = min(maximum, tippecanoe.get("maxzoom", maximum))
            if minimum > maximum:
                return None
            # An omitted hierarchy maxzoom deliberately means the archive ceiling.
            feature["tippecanoe"] = {**tippecanoe, "minzoom": minimum}
            if "maxzoom" in tippecanoe:
                feature["tippecanoe"]["maxzoom"] = maximum
            return feature
        feature["tippecanoe"] = {
            **tippecanoe, "minzoom": minimum, "maxzoom": maximum
        }
        return feature
    selected = next(
        (rule for rule in policy.rules if _matches(properties, rule)), None
    )
    if selected is None:
        return None
    existing = feature.get("tippecanoe")
    if policy.layer in {"place_label", "admin_line"} and isinstance(existing, dict):
        minimum = max(existing.get("minzoom", selected.min_zoom), selected.min_zoom)
        maximum = min(existing.get("maxzoom", selected.max_zoom), selected.max_zoom)
        if minimum > maximum:
            return None
        feature["tippecanoe"] = {"minzoom": minimum, "maxzoom": maximum}
    else:
        if existing is None:
            existing = {}
        if not isinstance(existing, dict):
            raise ValueError("feature tippecanoe member must be an object")
        feature["tippecanoe"] = {
            **existing, "minzoom": selected.min_zoom, "maxzoom": selected.max_zoom
        }
    return feature


def _matches(properties: dict[str, Any], rule: FeatureRule) -> bool:
    return all(properties.get(field) in values for field, values in rule.when.items())
