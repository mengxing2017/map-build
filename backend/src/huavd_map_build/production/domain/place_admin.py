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
    if tier not in policy.get("tiers", []) and not locality_match:
        return False
    if not any(
        display_name_allowed(properties.get(field), official)
        for field in ("name", *policy.get("target_fields", []))
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


def _direct_identity_selection(
    feature: dict[str, Any], candidates: list[PlaceCandidate], node_qid: str | None,
) -> tuple[PlaceCandidate | None, str | None, str | None, list[dict[str, Any]]]:
    feature_forms = set(_feature_name_forms(feature.get("properties", {})))
    evidence: list[tuple[PlaceCandidate, str | None]] = []
    for candidate in candidates:
        if node_qid is not None and node_qid == candidate.relation.wikidata:
            match = "wikidata"
        elif feature_forms.intersection(_relation_name_forms(candidate.relation)):
            match = "name-form"
        else:
            match = None
        evidence.append((candidate, match))

    audit = [{
        "relation_id": candidate.relation.id,
        "role": candidate.role,
        "evidence": match,
    } for candidate, match in evidence]
    wikidata_matches = {
        candidate.relation.id: candidate
        for candidate, match in evidence if match == "wikidata"
    }
    if len(wikidata_matches) == 1:
        return next(iter(wikidata_matches.values())), "wikidata", None, audit
    if len(wikidata_matches) > 1:
        return None, None, "ambiguous-wikidata-match", audit
    name_matches = {
        candidate.relation.id: candidate
        for candidate, match in evidence if match == "name-form"
    }
    if len(name_matches) == 1:
        return next(iter(name_matches.values())), "name-form", None, audit
    if len(name_matches) > 1:
        return None, None, "ambiguous-name-match", audit
    return None, None, "no-direct-identity-match", audit


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
    feature_by_id: dict[int, dict[str, Any]] = {}
    for feature in features:
        feature_id = numeric_feature_id(feature)
        if feature_id is None:
            raise PlaceAdminExecutionError("place_label feature has no numeric @id for audit")
        if feature_id in feature_by_id:
            raise PlaceAdminExecutionError(f"duplicate place_label @id: {feature_id}")
        feature_by_id[feature_id] = feature
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
    direct_by_node: dict[int, list[PlaceCandidate]] = {}
    for candidates in candidates_by_relation.values():
        for candidate in candidates:
            direct_by_node.setdefault(candidate.node_id, []).append(candidate)
    relations_by_name: dict[str, list[AdministrativeRelation]] = {}
    for relation in relations:
        for relation_name in _relation_name_forms(relation):
            relations_by_name.setdefault(relation_name, []).append(relation)
    relations_with_direct_candidates = set(candidates_by_relation)
    fallback_places = {"city", "county", "district", "town"}
    decisions: dict[int, dict[str, Any]] = {}
    for feature_id, feature in feature_by_id.items():
        properties = feature.get("properties", {})
        direct = direct_by_node.get(feature_id, [])
        if direct:
            node_qid = node_wikidata.get(feature_id)
            candidate, identity_evidence, unresolved_reason, identity_candidates = (
                _direct_identity_selection(feature, direct, node_qid)
            )
            node_direct_relation_ids = sorted({value.relation.id for value in direct})
            if candidate is None:
                decisions[feature_id] = {
                    "feature": feature,
                    "entity_key": f"wd:{node_qid}" if node_qid is not None else f"node:{feature_id}",
                    "entity_evidence": "node-wikidata" if node_qid is not None else "unresolved",
                    "relation": None,
                    "role": None,
                    "association_relation_id": (
                        node_direct_relation_ids[0] if len(node_direct_relation_ids) == 1 else None
                    ),
                    "direct_relation_ids": node_direct_relation_ids,
                    "identity_candidates": identity_candidates,
                    "identity_relation_id": None,
                    "unresolved_reason": unresolved_reason,
                }
                continue
            decisions[feature_id] = {
                "feature": feature, "entity_key": f"relation:{candidate.relation.id}",
                "entity_evidence": f"role-member-{identity_evidence}-match",
                "relation": candidate.relation,
                "role": candidate.role,
                "association_relation_id": (
                    node_direct_relation_ids[0] if len(node_direct_relation_ids) == 1 else None
                ),
                "direct_relation_ids": node_direct_relation_ids,
                "identity_candidates": identity_candidates,
                "identity_relation_id": candidate.relation.id,
                "unresolved_reason": None,
            }
            continue
        node_qid = node_wikidata.get(feature_id)
        forms = set(_feature_name_forms(properties))
        potential = {
            relation.id: relation for form in forms
            for relation in relations_by_name.get(form, [])
        }
        accepted: list[AdministrativeRelation] = []
        low_tier = False
        missing_boundary = False
        fallback_tier = label_tier(feature, None, hierarchy)
        fallback_rank = hierarchy["rank"][fallback_tier]
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        for relation in potential.values():
            relation_tier = relation_tiers[relation.id]
            if relation_tier is None or hierarchy["rank"][relation_tier] < fallback_rank:
                low_tier = True
            elif not boundaries.get(relation.id):
                missing_boundary = True
            elif point_in_multipolygon(coordinates, boundaries[relation.id]):
                accepted.append(relation)
        relation = accepted[0] if len(accepted) == 1 else None
        if relation is not None and properties.get("place") in fallback_places:
            same_wikidata = node_qid is not None and node_qid == relation.wikidata
            if relation.id not in relations_with_direct_candidates or same_wikidata:
                decisions[feature_id] = {
                    "feature": feature, "entity_key": f"relation:{relation.id}",
                    "entity_evidence": "name-boundary-unique", "relation": relation,
                    "role": "name-fallback", "association_relation_id": relation.id,
                    "direct_relation_ids": [], "identity_candidates": [],
                    "identity_relation_id": None,
                    "unresolved_reason": None,
                }
                continue
            decisions[feature_id] = {
                "feature": feature, "entity_key": f"node:{feature_id}",
                "entity_evidence": "fallback-ambiguous-existing-selection", "relation": None,
                "role": None, "association_relation_id": relation.id,
                "direct_relation_ids": [], "identity_candidates": [],
                "identity_relation_id": None,
                "unresolved_reason": "existing-relation-selection",
            }
            continue
        reason = "multiple-boundary-matches" if len(accepted) > 1 else (
            "low-tier" if low_tier else "missing-boundary" if missing_boundary else "zero-boundary-matches"
        )
        decisions[feature_id] = {
            "feature": feature,
            "entity_key": f"wd:{node_qid}" if node_qid is not None else f"node:{feature_id}",
            "entity_evidence": "node-wikidata" if node_qid is not None else "unresolved",
            "relation": None, "role": None, "association_relation_id": None,
            "direct_relation_ids": [], "identity_candidates": [],
            "identity_relation_id": None,
            "unresolved_reason": reason,
        }

    def canonical_key(item: dict[str, Any]) -> tuple[Any, ...]:
        evidence = item["entity_evidence"]
        role = item["role"]
        relation = item["relation"]
        node_qid = node_wikidata.get(numeric_feature_id(item["feature"]))
        identity_match = (
            node_qid is not None
            and relation is not None
            and node_qid == relation.wikidata
        )
        return (
            0 if identity_match else 1,
            0 if role == "admin_centre" else 1 if role == "label" else 2,
            0 if evidence == "name-boundary-unique" else 1,
            -population(item["feature"]), numeric_feature_id(item["feature"]),
        )

    by_entity: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for feature_id, decision in decisions.items():
        if not decision["entity_key"].startswith("node:"):
            by_entity.setdefault(decision["entity_key"], []).append((feature_id, decision))
    for entity_key, values in by_entity.items():
        winner_id, _winner = min(values, key=lambda value: canonical_key(value[1]))
        for feature_id, decision in values:
            if feature_id != winner_id:
                decision["outcome"] = "dropped"
                decision["reason"] = "entity-canonical-lost"
                decision["kept_node_id"] = winner_id

    intermediate: list[dict[str, Any]] = []
    for feature_id, decision in decisions.items():
        if decision.get("outcome") == "dropped":
            continue
        feature = deepcopy(decision["feature"])
        relation = decision["relation"]
        tier = label_tier(feature, relation_tiers[relation.id] if relation else None, hierarchy)
        if relation is not None:
            properties = feature.setdefault("properties", {})
            properties["admin_id"] = relation.id
            if relation.level is not None:
                properties["boundary_admin_level"] = relation.level
        apply_label_rendering(feature, tier, hierarchy)
        decision["label_tier"] = tier
        intermediate.append(feature)
    exact_duplicates = _exact_duplicates(intermediate)
    legacy_name_candidates = _same_name_tier_duplicates(intermediate, hierarchy)
    for item in exact_duplicates:
        decision = decisions[item["dropped_node_id"]]
        decision["outcome"] = "dropped"
        decision["reason"] = item["reason"]
        decision["kept_node_id"] = item["kept_node_id"]
    dropped_ids = {item["dropped_node_id"] for item in exact_duplicates}
    dropped_ids.update(
        feature_id for feature_id, decision in decisions.items()
        if decision.get("outcome") == "dropped"
    )
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
    for item in conventional_candidates:
        if item["outcome"] == "dropped":
            decision = decisions[item["node_id"]]
            decision["outcome"] = "dropped"
            decision["reason"] = "conventional-region-filter"
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
    for feature_id, decision in decisions.items():
        if decision.get("outcome") != "dropped":
            decision["outcome"] = "kept"
            decision["reason"] = "retained"
    identity_relations: dict[int, list[dict[str, Any]]] = {}
    for decision in decisions.values():
        relation_id = decision["identity_relation_id"]
        if relation_id is not None:
            identity_relations.setdefault(relation_id, []).append(decision)
    identity_relations_without_kept_point = []
    for relation_id, values in sorted(identity_relations.items()):
        entity_key = f"relation:{relation_id}"
        covered = any(
            decision["outcome"] == "kept" and decision["entity_key"] == entity_key
            for decision in decisions.values()
        )
        if not covered:
            identity_relations_without_kept_point.append({
                "relation_id": relation_id,
                "candidate_node_ids": sorted(
                    numeric_feature_id(value["feature"]) for value in values
                ),
                "final_outcomes": [{
                    "node_id": numeric_feature_id(value["feature"]),
                    "outcome": value["outcome"],
                    "reason": value["reason"],
                } for value in sorted(
                    values, key=lambda value: numeric_feature_id(value["feature"])
                )],
            })
    audit_decisions = []
    for feature_id, decision in sorted(decisions.items()):
        feature = decision["feature"]
        properties = feature.get("properties", {})
        audit_decisions.append({
            "node_id": feature_id, "entity_key": decision["entity_key"],
            "entity_evidence": decision["entity_evidence"], "outcome": decision["outcome"],
            "reason": decision["reason"], "kept_node_id": decision.get("kept_node_id"),
            "association_relation_id": decision["association_relation_id"],
            "admin_id": decision["relation"].id if decision["relation"] is not None else None,
            "direct_relation_ids": decision["direct_relation_ids"],
            "identity_candidates": decision["identity_candidates"],
            "identity_relation_id": decision["identity_relation_id"],
            "unresolved_reason": decision["unresolved_reason"], "place": properties.get("place"),
            "label_tier": decision.get("label_tier", label_tier(feature, None, hierarchy)),
        })
    dropped_node_ids = sorted(feature_id for feature_id, decision in decisions.items()
                              if decision["outcome"] == "dropped")
    report = {
        "schema_version": 3,
        "source": {
            "place_feature_count": len(features),
            "administrative_relation_count": len(relations),
        },
        "summary": {
            "source_feature_count": len(features),
            "role_member_relations_with_place_candidates": len(candidates_by_relation),
            "role_member_canonical_feature_count": sum(
                1 for decision in decisions.values()
                if decision["entity_evidence"].startswith("role-member") and decision["outcome"] == "kept"
            ),
            "fallback_canonical_feature_count": sum(
                1 for decision in decisions.values()
                if decision["entity_evidence"] == "name-boundary-unique" and decision["outcome"] == "kept"
            ),
            "fallback_dropped_count": 0,
            "exact_duplicate_dropped_count": len(exact_duplicates),
            "same_name_tier_dropped_count": 0,
            "same_name_tier_legacy_candidate_count": len(legacy_name_candidates),
            "redundant_role_member_dropped_count": 0,
            "admin_display_name_override_count": override_count,
            "conventional_region_candidate_count": len(conventional_candidates),
            "conventional_region_dropped_count": conventional_dropped_count,
            "conventional_region_demoted_count": conventional_demoted_count,
            "output_feature_count": len(output),
        },
        "dropped_node_ids": dropped_node_ids,
        "entity_decisions": audit_decisions,
        "identity_relations_without_kept_point": identity_relations_without_kept_point,
        "entity_groups": [{
            "entity_key": key, "candidate_count": len(values),
            "kept_node_id": next((
                feature_id for feature_id, _decision in values
                if decisions[feature_id]["outcome"] == "kept"
            ), None),
        } for key, values in sorted(by_entity.items())],
        "relations": [{
            "admin_id": relation_id,
            "candidate_node_ids": sorted({value.node_id for value in candidates}),
        } for relation_id, candidates in sorted(candidates_by_relation.items())],
        "shared_member_choices": [],
        "fallback_dropped": [],
        "exact_duplicates": exact_duplicates,
        "same_name_tier_duplicates": [],
        "same_name_tier_legacy_candidates": legacy_name_candidates,
        "redundant_role_members": [],
        "conventional_region_candidates": conventional_candidates,
        "conventional_region_skipped_reason": conventional_skipped_reason,
    }
    return PlaceAdminResult(tuple(output), report)


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
        groups.setdefault((
            name_key(properties), properties.get("place"), coordinates,
            properties.get("admin_id"), properties.get("boundary_admin_level"),
        ), []).append(feature)
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
