from __future__ import annotations

import json
from typing import Any

from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.production.domain.model import BuildPlan
from huavd_map_build.quality.domain.staging import (
    BaseDeepVerificationError,
    BaseStagingQualityReport,
    StagingFinding,
)
from huavd_map_build.quality.south.port.staging import StagedLayerReader
from huavd_map_build.shared.kernel import Role


class BaseStagingQualityGate:
    def __init__(
        self, configuration: BuildConfigurationService, reader: StagedLayerReader
    ) -> None:
        self._configuration, self._reader = configuration, reader

    def verify(self, build: BuildPlan) -> None:
        report = self.inspect(build)
        if not report.passed:
            raise BaseDeepVerificationError(report)

    def inspect(self, build: BuildPlan) -> BaseStagingQualityReport:
        if build.roles != (Role.BASE,):
            raise ValueError("base staging quality gate requires a base-only build")
        settings = self._configuration.tippecanoe(build.region.value, "base")
        layers = tuple(settings["source_layers"])
        policies = {
            name: (set(fields), geometry)
            for name, fields, geometry in self._configuration.final_layer_contracts(
                ",".join(layers)
            )
        }
        field_types = self._configuration.final_field_types(",".join(layers))
        place_policy = self._configuration.place_label_hierarchy(build.region.value)
        place_state = self._new_place_state()
        findings: list[StagingFinding] = []
        for item in self._configuration.layer_export_findings():
            findings.append(StagingFinding(item.code, item.layer, item.detail))
        feature_count = 0
        layer_stats: dict[str, dict[str, int]] = {}
        for layer in layers:
            path = (
                f"{build.workdir}/staging/{build.session.value}/layers/"
                f"{layer}.geojsonseq"
            )
            if not self._reader.exists(path):
                findings.append(StagingFinding(
                    "layer-missing", layer, f"required staged layer is missing: {path}"
                ))
                continue
            allowed_fields, allowed_geometry = policies[layer]
            stats = {
                "count": 0,
                "in_water": 0,
                "anchors": 0,
                "invalid_anchors": 0,
            }
            layer_stats[layer] = stats
            try:
                for line_number, feature in self._reader.features(path):
                    feature_count += 1
                    stats["count"] += 1
                    properties = feature.get("properties")
                    if isinstance(properties, dict):
                        if properties.get("in_water") is True:
                            stats["in_water"] += 1
                        if properties.get("island_anchor") is True:
                            stats["anchors"] += 1
                            geometry = feature.get("geometry")
                            if not (
                                isinstance(geometry, dict)
                                and geometry.get("type") == "Point"
                                and isinstance(geometry.get("coordinates"), list)
                                and len(geometry["coordinates"]) == 2
                                and self._number(properties.get("island_area_km2"))
                            ):
                                stats["invalid_anchors"] += 1
                    self._inspect_feature(
                        layer, line_number, feature, allowed_fields,
                        allowed_geometry, field_types[layer], findings,
                    )
                    if layer == "place_label":
                        self._inspect_place_label(
                            line_number, feature, place_policy, place_state, findings
                        )
                    if layer == "admin_line" and isinstance(properties, dict):
                        if "@id" in properties:
                            findings.append(StagingFinding(
                                "feature-id-leak", layer,
                                f"line {line_number} leaks @id after enrichment",
                            ))
            except (OSError, UnicodeError, ValueError) as error:
                findings.append(StagingFinding("layer-read", layer, str(error)))
        self._finish_place_label(place_state, place_policy, findings)
        self._inspect_derivation_reports(build, layer_stats, findings)
        return BaseStagingQualityReport(layers, feature_count, tuple(findings))

    def _inspect_derivation_reports(
        self, build: BuildPlan, stats: dict[str, dict[str, int]],
        findings: list[StagingFinding],
    ) -> None:
        root = build.workdir
        session = build.session.value
        reports = (
            (
                "admin_line",
                f"{root}/derived/{session}/admin-line-tier-report.json",
                self._valid_admin_line_report,
            ),
            (
                "place_label",
                f"{root}/staging/{session}/place_label_dedup_report.json",
                lambda value: self._valid_place_report(
                    value, stats.get("place_label", {}).get("count", 0),
                    self._configuration.place_label_hierarchy(build.region.value),
                ),
            ),
            (
                "island_water",
                f"{root}/staging/{session}/island_water_report.json",
                lambda value: self._valid_island_water_report(
                    value, stats.get("island", {}).get("in_water", 0)
                ),
            ),
            (
                "island_anchor",
                f"{root}/staging/{session}/island_anchor_report.json",
                lambda value: self._valid_island_anchor_report(
                    value, stats.get("island", {})
                ),
            ),
        )
        for name, path, validator in reports:
            if not self._reader.exists(path):
                findings.append(StagingFinding(
                    "report-missing", name, f"required derivation report is missing: {path}"
                ))
                continue
            try:
                document = self._reader.json_document(path)
                error = validator(document)
            except (OSError, UnicodeError, ValueError) as cause:
                error = str(cause)
            if error:
                findings.append(StagingFinding("report-invalid", name, error))

        water = f"{root}/staging/{session}/layers/water.geojsonseq"
        report = f"{root}/staging/{session}/island_water_report.json"
        if self._reader.exists(water) and self._reader.exists(report):
            try:
                expected = self._reader.json_document(report).get("summary", {}).get(
                    "water_geojsonseq_sha512"
                )
                if expected != self._reader.sha512(water):
                    findings.append(StagingFinding(
                        "report-mismatch", "island_water",
                        "water layer SHA-512 does not match island water report",
                    ))
            except (OSError, UnicodeError, ValueError, AttributeError) as cause:
                findings.append(
                    StagingFinding("report-invalid", "island_water", str(cause))
                )

    @classmethod
    def _valid_admin_line_report(cls, value: dict[str, Any]) -> str | None:
        try:
            valid = (
                value.get("schema_version") == 1
                and cls._nonnegative(value["retained"]["count"])
                and value["retained"]["id_leak_count"] == 0
                and cls._nonnegative(value["relation_sidecar"]["way_count"])
                and isinstance(value["discarded"]["by_reason"], dict)
            )
        except (KeyError, TypeError):
            valid = False
        return None if valid else "admin_line tier report contract is invalid"

    @classmethod
    def _valid_place_report(
        cls, value: dict[str, Any], count: int, policy: dict[str, Any]
    ) -> str | None:
        try:
            summary = value["summary"]
            conventional = policy["conventional_region_filter"]
            candidates = value["conventional_region_candidates"]
            valid = (
                value.get("schema_version") == 1
                and all(
                    isinstance(value[key], list)
                    for key in (
                        "relations",
                        "shared_member_choices",
                        "same_name_tier_duplicates",
                        "redundant_role_members",
                        "conventional_region_candidates",
                    )
                )
                and summary["output_feature_count"] == count
                and summary["conventional_region_candidate_count"] == len(candidates)
                and summary["conventional_region_candidate_count"] <= conventional["max_candidates"]
            )
            for key in (
                "exact_duplicate_dropped_count", "same_name_tier_dropped_count",
                "redundant_role_member_dropped_count",
                "admin_display_name_override_count",
                "conventional_region_candidate_count",
                "conventional_region_dropped_count",
                "conventional_region_demoted_count",
            ):
                valid = valid and cls._nonnegative(summary[key])
            dropped = sum(
                isinstance(item, dict) and item.get("outcome") == "dropped"
                for item in candidates
            )
            demoted = sum(
                isinstance(item, dict) and item.get("outcome") == "demoted"
                for item in candidates
            )
            valid = valid and (
                summary["conventional_region_dropped_count"] == dropped
                and summary["conventional_region_demoted_count"] == demoted
            )
            skipped_reason = value.get("conventional_region_skipped_reason")
            if not conventional["enabled"]:
                valid = valid and skipped_reason == "disabled" and not candidates
            elif skipped_reason is not None:
                valid = valid and isinstance(skipped_reason, str) and not candidates
            else:
                expected_outcome = {
                    "report_only": "reported", "drop": "dropped", "demote": "demoted",
                }[conventional["action"]]
                for item in candidates:
                    valid = valid and (
                        isinstance(item, dict)
                        and type(item.get("node_id")) is int
                        and isinstance(item.get("name"), str)
                        and isinstance(item.get("place"), str)
                        and isinstance(item.get("tier"), str)
                        and item.get("reason") in {
                            "no-admin-evidence", "boundary-coverage-incomplete",
                        }
                        and all(isinstance(item.get(key), bool) for key in ("a1", "a2", "a3"))
                        and item.get("action") == conventional["action"]
                        and (
                            item.get("outcome") == "kept"
                            if item.get("reason") == "boundary-coverage-incomplete"
                            else item.get("outcome") == expected_outcome
                        )
                    )
        except (KeyError, TypeError, AttributeError):
            valid = False
        return None if valid else "place_label enrichment report contract is invalid"

    @classmethod
    def _valid_island_water_report(cls, value: dict[str, Any], flagged: int) -> str | None:
        try:
            thresholds = value["thresholds"]
            inputs = value["inputs"]
            summary = value["summary"]
            polygons = inputs["island_polygon_count"]
            valid = (
                value.get("schema_version") == 1 and value.get("layer") == "island"
                and all(
                    cls._number(thresholds[key])
                    for key in (
                        "sample_points",
                        "min_inside_ratio",
                        "max_in_water_area_km2",
                    )
                )
                and cls._nonnegative(polygons)
                and summary["in_water_count"] == flagged
                and value.get("checks", {}).get("max_in_water_area_within_limit") is True
                and (polygons < 10 or flagged * 10 <= polygons)
            )
        except (KeyError, TypeError):
            valid = False
        return None if valid else "island water report contract or staged count is invalid"

    @classmethod
    def _valid_island_anchor_report(
        cls, value: dict[str, Any], stats: dict[str, int]
    ) -> str | None:
        try:
            summary, tier = value["summary"], value["summary"]["tier"]
            polygons = summary["polygon_count"]
            valid = (
                value.get("schema_version") == 1 and value.get("layer") == "island"
                and cls._number(value["thresholds"]["grid_divisions"])
                and cls._nonnegative(polygons)
                and summary["anchor_count"] == polygons == stats.get("anchors", 0)
                and all(
                    cls._nonnegative(tier[key])
                    for key in ("centroid", "grid", "vertex")
                )
                and tier["vertex"] == 0
                and stats.get("invalid_anchors", 0) == 0
            )
        except (KeyError, TypeError):
            valid = False
        return None if valid else "island anchor report contract or staged anchors are invalid"

    @staticmethod
    def _number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @classmethod
    def _nonnegative(cls, value: object) -> bool:
        return cls._number(value) and value >= 0

    @staticmethod
    def _inspect_feature(
        layer: str, line_number: int, feature: dict,
        allowed_fields: set[str], allowed_geometry: tuple[str, ...],
        field_types: dict[str, str],
        findings: list[StagingFinding],
    ) -> None:
        if feature.get("type") != "Feature":
            findings.append(StagingFinding(
                "feature-type", layer, f"line {line_number} is not a GeoJSON Feature"
            ))
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            findings.append(StagingFinding(
                "feature-properties", layer,
                f"line {line_number} properties must be an object",
            ))
        else:
            unexpected = sorted(set(properties) - allowed_fields)
            if unexpected:
                findings.append(StagingFinding(
                    "feature-fields", layer,
                    f"line {line_number} has unexpected fields: {','.join(unexpected)}",
                ))
            for field, value in properties.items():
                expected = field_types.get(field)
                if expected and not BaseStagingQualityGate._matches_type(value, expected):
                    findings.append(StagingFinding(
                        "feature-field-type", layer,
                        f"line {line_number} field {field} must be {expected}",
                    ))
        geometry = feature.get("geometry")
        geometry_type = geometry.get("type") if isinstance(geometry, dict) else None
        if allowed_geometry and geometry_type not in allowed_geometry:
            findings.append(StagingFinding(
                "feature-geometry", layer,
                f"line {line_number} has disallowed geometry: {geometry_type or '<missing>'}",
            ))

    @staticmethod
    def _matches_type(value: object, expected: str) -> bool:
        if expected == "String":
            return isinstance(value, str)
        if expected == "Boolean":
            return isinstance(value, bool)
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def _new_place_state() -> dict[str, Any]:
        return {
            "count": 0,
            "admin_ids": set(),
            "identities": set(),
            "name_tiers": {},
        }

    @classmethod
    def _inspect_place_label(
        cls, line_number: int, feature: dict[str, Any], policy: dict[str, Any],
        state: dict[str, Any], findings: list[StagingFinding],
    ) -> None:
        state["count"] += 1
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            return
        if "@id" in properties:
            findings.append(StagingFinding(
                "feature-id-leak", "place_label",
                f"line {line_number} leaks @id after enrichment",
            ))
        tier = properties.get("label_tier")
        rank = properties.get("label_rank")
        if not isinstance(tier, str) or not tier:
            findings.append(StagingFinding(
                "place-label-tier", "place_label",
                f"line {line_number} label_tier must be a non-empty string",
            ))
        if not cls._number(rank):
            findings.append(StagingFinding(
                "place-label-rank", "place_label",
                f"line {line_number} label_rank must be numeric",
            ))

        admin_id = properties.get("admin_id")
        if admin_id is not None:
            admin_key = json.dumps(
                admin_id, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if admin_key in state["admin_ids"]:
                findings.append(StagingFinding(
                    "place-admin-id", "place_label",
                    f"line {line_number} has duplicate admin_id: {admin_id}",
                ))
            state["admin_ids"].add(admin_key)

        geometry = feature.get("geometry", {})
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        identity = json.dumps(
            {
                "name": properties.get("name"),
                "place": properties.get("place"),
                "coordinates": coordinates,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if identity in state["identities"]:
            findings.append(StagingFinding(
                "place-duplicate", "place_label",
                f"line {line_number} duplicates name/place/coordinates",
            ))
        state["identities"].add(identity)

        if isinstance(tier, str):
            name_key = json.dumps(
                properties.get("name"), ensure_ascii=False, sort_keys=True
            )
            key = (name_key, tier)
            flags = state["name_tiers"].setdefault(key, set())
            flags.add(admin_id is not None)
            zoom = policy["tier_zoom"].get(tier, policy["tier_zoom"]["default"])
            actual_zoom = feature.get("tippecanoe")
            expected_zoom = {
                key: zoom[key] for key in ("minzoom", "maxzoom") if key in zoom
            }
            if actual_zoom != expected_zoom:
                findings.append(StagingFinding(
                    "place-label-zoom", "place_label",
                    f"line {line_number} tippecanoe zoom does not match tier {tier}",
                ))

        display = policy["admin_display_name"]
        official = properties.get("official_name")
        if display.get("enabled") and official is not None:
            values = [
                properties[field] for field in display.get("target_fields", [])
                if properties.get(field) is not None
            ]
            matches = sum(value == official for value in values)
            if matches not in {0, len(values)}:
                findings.append(StagingFinding(
                    "place-display-name", "place_label",
                    f"line {line_number} applies official_name to only some target fields",
                ))

    @staticmethod
    def _finish_place_label(
        state: dict[str, Any], policy: dict[str, Any],
        findings: list[StagingFinding],
    ) -> None:
        dedupe_tiers = set(policy.get("dedupe_name_tiers", ()))
        for (name, tier), flags in state["name_tiers"].items():
            if tier in dedupe_tiers and flags == {False, True}:
                findings.append(StagingFinding(
                    "place-name-tier", "place_label",
                    f"same name/tier mixes administrative and fallback labels: {name}/{tier}",
                ))
