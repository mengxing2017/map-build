from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from huavd_map_build.production.domain.place_admin import AdministrativeRelation


class FileSystemPlaceAdminIndexStore:
    def resolve_workspace_path(self, path: str, workdir: str) -> str:
        candidate = Path(path)
        if candidate.is_absolute():
            return str(candidate)
        if path.startswith(("mirror/", "cache/", "staging/", "outputs/")):
            return str(Path(workdir) / path)
        return str(candidate.resolve()) if candidate.exists() else str(Path(workdir) / path)

    def require_file(self, path: str) -> None:
        if not Path(path).is_file():
            raise ValueError(f"required file does not exist: {path}")

    def is_nonempty(self, path: str) -> bool:
        return Path(path).stat().st_size > 0

    def prepare(self, cache_directory: str) -> tuple[str, str, str, str]:
        cache = Path(cache_directory)
        cache.mkdir(parents=True, exist_ok=True)
        config = cache / "admin-boundaries-export.json"
        config.write_text(json.dumps({
            "attributes": {
                "type": False, "id": True, "version": False,
                "changeset": False, "timestamp": False, "uid": False, "user": False,
            },
            "include_tags": ["admin_level"],
        }, separators=(",", ":")) + "\n", encoding="utf-8")
        return (
            str(cache / "admin-relations.osm.pbf"),
            str(cache / "admin-relations.ndjson"),
            str(cache / "place-node-wikidata.ndjson"),
            str(config),
        )

    def write_relation_indexes(
        self, relations_path: str, nodes_path: str,
        relations: tuple[AdministrativeRelation, ...], node_wikidata: dict[int, str],
    ) -> None:
        with Path(relations_path).open("w", encoding="utf-8", newline="\n") as stream:
            for relation in relations:
                document = {
                    "id": relation.id, "level": relation.level,
                    "name_zh_hans": relation.names[0], "name_zh": relation.names[1],
                    "name": relation.names[2], "name_en": relation.names[3],
                    "wikidata": relation.wikidata,
                    "nodes": [{"ref": ref, "role": role} for ref, role in relation.nodes],
                }
                stream.write(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n")
        with Path(nodes_path).open("w", encoding="utf-8", newline="\n") as stream:
            for node_id, wikidata in sorted(node_wikidata.items()):
                stream.write(json.dumps(
                    {"node_id": node_id, "wikidata": wikidata},
                    ensure_ascii=False, separators=(",", ":"),
                ) + "\n")

    def read_boundaries(self, path: str) -> dict[int, list[Any]]:
        boundaries: dict[int, list[Any]] = {}
        with Path(path).open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                payload = line.removeprefix("\x1e").strip()
                if not payload:
                    continue
                try:
                    feature = json.loads(payload)
                    geometry = feature.get("geometry", {})
                    raw_id = feature.get("properties", {}).get("@id")
                    relation_id = int(raw_id)
                except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as error:
                    raise ValueError(f"invalid boundary GeoJSONSeq at {path}:{line_number}") from error
                if geometry.get("type") == "MultiPolygon":
                    boundaries[relation_id] = geometry.get("coordinates", [])
        return boundaries

    def write_boundary_index(self, path: str, boundaries: dict[int, list[Any]]) -> None:
        with Path(path).open("w", encoding="utf-8", newline="\n") as stream:
            for relation_id, polygons in sorted(boundaries.items()):
                stream.write(json.dumps(
                    {"id": relation_id, "polys": polygons},
                    ensure_ascii=False, separators=(",", ":"),
                ) + "\n")

    def read_features(self, path: str) -> list[dict[str, Any]]:
        features: list[dict[str, Any]] = []
        with Path(path).open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                payload = line.removeprefix("\x1e").strip()
                if not payload:
                    continue
                try:
                    feature = json.loads(payload)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"invalid GeoJSONSeq at {path}:{line_number}: {error.msg}"
                    ) from error
                if not isinstance(feature, dict):
                    raise ValueError(f"GeoJSONSeq feature must be an object: {path}:{line_number}")
                features.append(feature)
        return features

    def publish(
        self, source_path: str, report_path: str,
        features: tuple[dict[str, Any], ...], report: dict[str, Any],
    ) -> None:
        source = Path(source_path)
        temporary = Path(f"{source_path}.place-admin.tmp")
        report_target = Path(report_path)
        report_target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                for feature in features:
                    stream.write("\x1e")
                    stream.write(json.dumps(feature, ensure_ascii=False, separators=(",", ":")))
                    stream.write("\n")
            report_target.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(temporary, source)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def write_empty_report(self, report_path: str) -> None:
        report = {
            "schema_version": 1,
            "source": {"place_feature_count": 0, "administrative_relation_count": 0},
            "summary": {
                "role_member_relations_with_place_candidates": 0,
                "role_member_canonical_feature_count": 0,
                "fallback_canonical_feature_count": 0,
                "fallback_dropped_count": 0,
                "exact_duplicate_dropped_count": 0,
                "same_name_tier_dropped_count": 0,
                "redundant_role_member_dropped_count": 0,
                "admin_display_name_override_count": 0,
                "output_feature_count": 0,
            },
            "relations": [], "shared_member_choices": [], "fallback_dropped": [],
            "exact_duplicates": [], "same_name_tier_duplicates": [],
            "redundant_role_members": [],
        }
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
