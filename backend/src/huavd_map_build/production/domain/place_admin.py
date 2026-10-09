from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import json
import re
from typing import Any
from urllib.parse import unquote

from huavd_map_build.shared.kernel import RegionId, SessionId


@dataclass(frozen=True, slots=True)
class AdministrativeRelation:
    id: int
    level: int | None
    names: tuple[str | None, str | None, str | None, str | None]
    wikidata: str | None
    nodes: tuple[tuple[int, str], ...]

    def display_name(self) -> str | None:
        for value in self.names:
            if value is not None and (cleaned := value.strip()):
                return cleaned
        return None


@dataclass(frozen=True, slots=True)
class PlaceAdminSourceIndex:
    relations: tuple[AdministrativeRelation, ...]
    node_wikidata: dict[int, str]
    boundaries: dict[int, list[Any]]


class PlaceAdminExecutionError(RuntimeError):
    pass


class MissingPlaceAdminToolError(PlaceAdminExecutionError):
    pass


@dataclass(frozen=True, slots=True)
class PlaceCandidate:
    relation: AdministrativeRelation
    tier: str | None
    role: str
    node_id: int
    feature: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PlaceAdminResult:
    features: tuple[dict[str, Any], ...]
    report: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PlaceAdminRequest:
    region: RegionId
    session: SessionId
    workdir: str
    input_path: str


def opl_decode(value: str) -> str:
    return unquote(value)


def name_key(properties: dict[str, Any]) -> str | None:
    for key in ("name:zh-Hans", "name:zh", "name", "name:en"):
        value = properties.get(key)
        if isinstance(value, str) and (cleaned := value.strip()):
            return cleaned
    return None


def numeric_feature_id(feature: dict[str, Any]) -> int | None:
    value = feature.get("properties", {}).get("@id")
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else None


def population(feature: dict[str, Any]) -> float:
    value = feature.get("properties", {}).get("population", 0)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def common_prefix_length(left: str, right: str) -> int:
    for index, pair in enumerate(zip(left, right)):
        if pair[0] != pair[1]:
            return index
    return min(len(left), len(right))


def display_name_allowed(current: Any, official: Any) -> bool:
    return (
        isinstance(current, str) and isinstance(official, str)
        and "/" not in official and len(official) >= len(current)
        and common_prefix_length(current, official) >= 2
    )


def point_in_multipolygon(point: list[float], polygons: list[Any]) -> bool:
    return any(_point_in_polygon(point, polygon) for polygon in polygons)


def _point_in_polygon(point: list[float], polygon: list[Any]) -> bool:
    return bool(polygon and _point_in_ring(point, polygon[0]) and not any(
        _point_in_ring(point, hole) for hole in polygon[1:]
    ))


def _point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    if len(ring) < 3:
        return False
    x, y = point
    inside = False
    previous = ring[-1]
    for current in ring:
        xi, yi = current
        xj, yj = previous
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        previous = current
    return inside


def label_tier(
    feature: dict[str, Any], assigned_tier: str | None, hierarchy: dict[str, Any]
) -> str:
    if assigned_tier:
        return assigned_tier
    place = feature.get("properties", {}).get("place", "default")
    fallback = hierarchy["place_fallback_tier"]
    return fallback.get(place, fallback["default"])


def apply_label_rendering(
    feature: dict[str, Any], tier: str, hierarchy: dict[str, Any]
) -> None:
    properties = feature.setdefault("properties", {})
    rank = hierarchy["rank"][tier]
    bounded_population = min(999_999_999, int(population(feature)))
    properties["label_tier"] = tier
    properties["label_rank"] = rank * 1_000_000_000 + bounded_population
    zoom = hierarchy["tier_zoom"].get(tier, hierarchy["tier_zoom"]["default"])
    feature["tippecanoe"] = {
        key: zoom[key] for key in ("minzoom", "maxzoom") if key in zoom
    }


def apply_admin_display_name(
    feature: dict[str, Any], tier: str, policy: dict[str, Any]
) -> bool:
    if not policy.get("enabled", False):
        return False
    properties = feature.setdefault("properties", {})
    official = properties.get("official_name")
    locality_match = isinstance(official, str) and any(
        keyword in official for keyword in policy.get("locality_keywords", [])
    )
    if (tier not in policy.get("tiers", []) and not locality_match) or not display_name_allowed(
        properties.get("name"), official
    ):
        return False
    for field in policy.get("target_fields", []):
        properties[field] = official
    return True


def _normalized_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def _feature_name_forms(properties: dict[str, Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        normalized for key in ("name", "name:zh", "name:zh-Hans", "name:en", "official_name")
        if (normalized := _normalized_name(properties.get(key))) is not None
    ))


def _relation_name_forms(relation: AdministrativeRelation) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        normalized for value in relation.names
        if (normalized := _normalized_name(value)) is not None
    ))


def _prefix_match(left: str, right: str, minimum: int) -> bool:
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    return len(shorter) >= minimum and longer.startswith(shorter)


def _conventional_region_filter(
    features: list[dict[str, Any]],
    dropped_ids: set[int | None],
    relations: tuple[AdministrativeRelation, ...],
    node_wikidata: dict[int, str],
    boundaries: dict[int, list[Any]],
    hierarchy: dict[str, Any],
) -> tuple[set[int], list[dict[str, Any]], str | None, int, int]:
    policy = hierarchy["conventional_region_filter"]
    if not policy["enabled"]:
        return set(), [], "disabled", 0, 0
    if not boundaries:
        return set(), [], "boundary-index-empty", 0, 0

    levels = set(policy["admin_evidence_levels"])
    evidence_relations = tuple(
        relation for relation in relations if relation.level in levels
    )
    relation_qids = {
        relation.wikidata for relation in evidence_relations if relation.wikidata
    }
    keep_names = {
        normalized for value in policy["keep_names"]
        if (normalized := _normalized_name(value)) is not None
    }
    filter_dropped: set[int] = set()
    candidates: list[dict[str, Any]] = []
    dropped_count = 0
    demoted_count = 0
    for feature in features:
        feature_id = numeric_feature_id(feature)
        properties = feature.get("properties", {})
        if (
            feature_id is None or feature_id in dropped_ids
            or properties.get("admin_id") is not None
            or properties.get("place") not in policy["places"]
            or properties.get("label_tier") not in policy["tiers"]
        ):
            continue
        names = _feature_name_forms(properties)
        if not names or keep_names.intersection(names):
            continue
        a1 = node_wikidata.get(feature_id) in relation_qids
        primary_name = name_key(properties)
        matches = tuple(
            relation for relation in evidence_relations
            if primary_name is not None and _prefix_match(
                primary_name, relation.display_name() or "", policy["min_prefix_len"]
            )
        )
        coverage_incomplete = bool(matches) and any(
            not boundaries.get(relation.id) for relation in matches
        )
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        a2 = not coverage_incomplete and any(
            point_in_multipolygon(coordinates, boundaries.get(relation.id, []))
            for relation in matches
        )
        a3 = policy["population_is_admin_evidence"] and population(feature) > 0
        if a1 or a2 or a3:
            continue

        outcome = "kept" if coverage_incomplete else {
            "report_only": "reported", "drop": "dropped", "demote": "demoted",
        }[policy["action"]]
        candidates.append({
            "node_id": feature_id,
            "name": properties.get("name") if isinstance(properties.get("name"), str)
                    else names[0],
            "place": properties.get("place"),
            "tier": properties.get("label_tier"),
            "reason": "boundary-coverage-incomplete" if coverage_incomplete
                      else "no-admin-evidence",
            "a1": a1,
            "a2": a2,
            "a3": a3,
            "action": policy["action"],
            "outcome": outcome,
        })
        if outcome == "dropped":
            filter_dropped.add(feature_id)
            dropped_count += 1
        elif outcome == "demoted":
            apply_label_rendering(feature, "locality", hierarchy)
            demoted_count += 1

    if len(candidates) > policy["max_candidates"]:
        raise PlaceAdminExecutionError(
            "conventional region candidate count exceeds configured maximum: "
            f"{len(candidates)} > {policy['max_candidates']}"
        )
    return filter_dropped, candidates, None, dropped_count, demoted_count


def enrich_place_labels(
    features: list[dict[str, Any]],
    relations: tuple[AdministrativeRelation, ...],
    node_wikidata: dict[int, str],
    boundaries: dict[int, list[Any]],
    hierarchy: dict[str, Any],
) -> PlaceAdminResult:
    feature_by_id = {
        feature_id: feature for feature in features
        if (feature_id := numeric_feature_id(feature)) is not None
    }
    relation_tiers = {
        relation.id: (
            hierarchy["boundary_tier"].get(str(relation.level))
            if relation.level is not None else None
        ) for relation in relations
    }
    candidates_by_relation: dict[int, list[PlaceCandidate]] = {}
    for relation in relations:
        for node_id, role in relation.nodes:
            feature = feature_by_id.get(node_id)
            if feature is not None:
                candidates_by_relation.setdefault(relation.id, []).append(PlaceCandidate(
                    relation, relation_tiers[relation.id], role, node_id, feature
                ))
    groups: list[tuple[int, PlaceCandidate, list[PlaceCandidate]]] = []
    for relation_id in sorted(candidates_by_relation):
        candidates = candidates_by_relation[relation_id]
        chosen = min(candidates, key=lambda value: _candidate_key(value, hierarchy))
        groups.append((relation_id, chosen, candidates))

    chosen_by_node: dict[int, list[PlaceCandidate]] = {}
    for _relation_id, chosen, _candidates in groups:
        chosen_by_node.setdefault(chosen.node_id, []).append(chosen)
    assignments = {
        node_id: min(values, key=lambda value: _primary_key(value, hierarchy))
        for node_id, values in chosen_by_node.items()
    }
    selected_node_ids = set(assignments)
    member_duplicates: list[dict[str, Any]] = []
    for _relation_id, chosen, candidates in groups:
        kept_name = name_key(chosen.feature.get("properties", {}))
        for candidate in candidates:
            candidate_name = name_key(candidate.feature.get("properties", {}))
            if (
                candidate.node_id != chosen.node_id
                and candidate.node_id not in selected_node_ids
                and candidate_name is not None and kept_name is not None
                and common_prefix_length(candidate_name, kept_name) >= 2
            ):
                member_duplicates.append({
                    "dropped_node_id": candidate.node_id,
                    "kept_node_id": chosen.node_id,
                    "reason": "redundant-role-member",
                })
    shared = []
    for node_id, values in sorted(chosen_by_node.items()):
        if len(values) > 1:
            ordered = sorted(values, key=lambda value: _primary_key(value, hierarchy))
            shared.append({
                "node_id": node_id,
                "selected_admin_id": ordered[0].relation.id,
                "discarded_admin_ids": sorted(value.relation.id for value in ordered[1:]),
            })

    relations_by_name: dict[str, list[AdministrativeRelation]] = {}
    for relation in relations:
        if (relation_name := relation.display_name()) is not None:
            relations_by_name.setdefault(relation_name, []).append(relation)
    kept_relation_ids = set(candidates_by_relation)
    fallback_dropped: list[dict[str, Any]] = []
    fallback_candidates: dict[int, list[tuple[dict[str, Any], AdministrativeRelation]]] = {}
    fallback_places = {"city", "county", "district", "town"}
    for feature in features:
        feature_id = numeric_feature_id(feature)
        if feature_id in assignments or feature.get("properties", {}).get("place") not in fallback_places:
            continue
        feature_name = name_key(feature.get("properties", {}))
        matches = relations_by_name.get(feature_name, []) if feature_name is not None else []
        if len(matches) != 1 or feature_id is None:
            continue
        relation = matches[0]
        if relation.id in kept_relation_ids:
            node_qid, relation_qid = node_wikidata.get(feature_id), relation.wikidata
            same_entity = (
                node_qid == relation_qid if node_qid is not None and relation_qid is not None
                else point_in_multipolygon(
                    feature.get("geometry", {}).get("coordinates", []),
                    boundaries.get(relation.id, []),
                )
            )
            if same_entity:
                fallback_dropped.append({
                    "node_id": feature_id, "admin_id": relation.id,
                    "reason": "relation-already-selected",
                })
        else:
            fallback_candidates.setdefault(relation.id, []).append((feature, relation))

    fallback_lost: list[dict[str, Any]] = []
    for relation_id in sorted(fallback_candidates):
        values = fallback_candidates[relation_id]
        winner, relation = min(values, key=lambda value: (
            -population(value[0]), _id_or_max(value[0])
        ))
        winner_id = numeric_feature_id(winner)
        assert winner_id is not None
        assignments[winner_id] = PlaceCandidate(
            relation, relation_tiers[relation.id], "name-fallback", winner_id, winner
        )
        for feature, _relation in values:
            feature_id = numeric_feature_id(feature)
            if feature_id != winner_id:
                fallback_lost.append({
                    "node_id": feature_id, "admin_id": relation.id,
                    "reason": "fallback-canonical-lost",
                })
    fallback_drop_ids = {
        item["node_id"] for item in (*fallback_dropped, *fallback_lost)
    }
    intermediate: list[dict[str, Any]] = []
    for original in features:
        feature_id = numeric_feature_id(original)
        if feature_id in fallback_drop_ids:
            continue
        feature = deepcopy(original)
        assignment = assignments.get(feature_id)
        tier = label_tier(feature, assignment.tier if assignment else None, hierarchy)
        if assignment is not None:
            properties = feature.setdefault("properties", {})
            properties["admin_id"] = assignment.relation.id
            if assignment.relation.level is not None:
                properties["boundary_admin_level"] = assignment.relation.level
        apply_label_rendering(feature, tier, hierarchy)
        intermediate.append(feature)

    exact_duplicates = _exact_duplicates(intermediate)
    name_duplicates = _same_name_tier_duplicates(intermediate, hierarchy)
    dropped_ids = {
        item["dropped_node_id"]
        for item in (*exact_duplicates, *name_duplicates, *member_duplicates)
    }
    (
        conventional_dropped_ids,
        conventional_candidates,
        conventional_skipped_reason,
        conventional_dropped_count,
        conventional_demoted_count,
    ) = _conventional_region_filter(
        intermediate, dropped_ids, relations, node_wikidata, boundaries, hierarchy
    )
    dropped_ids.update(conventional_dropped_ids)
    output: list[dict[str, Any]] = []
    policy = hierarchy["admin_display_name"]
    override_count = sum(
        apply_admin_display_name(
            deepcopy(feature), feature.get("properties", {}).get("label_tier"), policy
        )
        for feature in intermediate
    )
    for feature in intermediate:
        if numeric_feature_id(feature) in dropped_ids:
            continue
        properties = feature.setdefault("properties", {})
        properties.pop("@id", None)
        apply_admin_display_name(feature, properties["label_tier"], policy)
        output.append(feature)
    report = {
        "schema_version": 1,
        "source": {
            "place_feature_count": len(features),
            "administrative_relation_count": len(relations),
        },
        "summary": {
            "role_member_relations_with_place_candidates": len(groups),
            "role_member_canonical_feature_count": len(assignments) - len(fallback_candidates),
            "fallback_canonical_feature_count": len(fallback_candidates),
            "fallback_dropped_count": len(fallback_dropped) + len(fallback_lost),
            "exact_duplicate_dropped_count": len(exact_duplicates),
            "same_name_tier_dropped_count": len(name_duplicates),
            "redundant_role_member_dropped_count": len(member_duplicates),
            "admin_display_name_override_count": override_count,
            "conventional_region_candidate_count": len(conventional_candidates),
            "conventional_region_dropped_count": conventional_dropped_count,
            "conventional_region_demoted_count": conventional_demoted_count,
            "output_feature_count": len(output),
        },
        "relations": [{
            "admin_id": relation_id, "selected_node_id": chosen.node_id,
            "selected_role": chosen.role, "selected_tier": chosen.tier,
            "candidate_node_ids": sorted({value.node_id for value in candidates}),
        } for relation_id, chosen, candidates in groups],
        "shared_member_choices": shared,
        "fallback_dropped": fallback_dropped + fallback_lost,
        "exact_duplicates": exact_duplicates,
        "same_name_tier_duplicates": name_duplicates,
        "redundant_role_members": member_duplicates,
        "conventional_region_candidates": conventional_candidates,
        "conventional_region_skipped_reason": conventional_skipped_reason,
    }
    return PlaceAdminResult(tuple(output), report)


def _candidate_key(candidate: PlaceCandidate, hierarchy: dict[str, Any]) -> tuple[Any, ...]:
    relation_name = candidate.relation.display_name()
    feature = candidate.feature
    expected = hierarchy["tier_expected_place"].get(candidate.tier, [])
    return (
        -1 if relation_name is not None and relation_name == name_key(feature.get("properties", {})) else 0,
        -1 if candidate.role == "label" else 0,
        -1 if candidate.tier is not None and feature.get("properties", {}).get("place") in expected else 0,
        -population(feature), _id_or_max(feature),
    )


def _primary_key(candidate: PlaceCandidate, hierarchy: dict[str, Any]) -> tuple[int, int, int]:
    rank = hierarchy["rank"].get(candidate.tier, 0) if candidate.tier else 0
    role_priority = (
        1 if candidate.tier in {"country", "province", "prefecture"}
        and candidate.role == "admin_centre"
        else 1 if candidate.tier in {"county", "township", "locality"}
        and candidate.role == "label" else 0
    )
    return -rank, -role_priority, candidate.relation.id


def _id_or_max(feature: dict[str, Any]) -> int:
    value = numeric_feature_id(feature)
    return value if value is not None else 9_223_372_036_854_775_807


def _exact_duplicates(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for feature in features:
        properties = feature.get("properties", {})
        coordinates = json.dumps(
            feature.get("geometry", {}).get("coordinates"),
            ensure_ascii=False, separators=(",", ":"),
        )
        groups.setdefault((name_key(properties), properties.get("place"), coordinates), []).append(feature)
    duplicates = []
    for values in groups.values():
        winner = min(values, key=lambda feature: (
            -1 if feature.get("properties", {}).get("admin_id") is not None else 0,
            -population(feature), _id_or_max(feature),
        ))
        winner_id = numeric_feature_id(winner)
        for feature in values:
            feature_id = numeric_feature_id(feature)
            if feature_id != winner_id:
                duplicates.append({
                    "dropped_node_id": feature_id, "kept_node_id": winner_id,
                    "reason": "exact-duplicate",
                })
    return duplicates


def _same_name_tier_duplicates(
    features: list[dict[str, Any]], hierarchy: dict[str, Any]
) -> list[dict[str, Any]]:
    groups: dict[tuple[str | None, Any], list[dict[str, Any]]] = {}
    for feature in features:
        properties = feature.get("properties", {})
        groups.setdefault((name_key(properties), properties.get("label_tier")), []).append(feature)
    duplicates = []
    allowed = set(hierarchy.get("dedupe_name_tiers", []))
    for (_name, tier), values in groups.items():
        with_admin = [value for value in values if value.get("properties", {}).get("admin_id") is not None]
        if tier in allowed and len(with_admin) == 1:
            kept_id = numeric_feature_id(with_admin[0])
            duplicates.extend({
                "dropped_node_id": numeric_feature_id(value), "kept_node_id": kept_id,
                "reason": "same-name-tier-redundant",
            } for value in values if value.get("properties", {}).get("admin_id") is None)
    return duplicates
