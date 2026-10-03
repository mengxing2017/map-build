from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from huavd_map_build.production.domain.admin_line import classify_admin_line


class FileSystemAdminLineStore:
    def require_file(self, path: str) -> None:
        if not Path(path).is_file():
            raise ValueError(f"required file does not exist: {path}")

    def is_nonempty(self, path: str) -> bool:
        return Path(path).stat().st_size > 0

    def sha512(self, path: str) -> str:
        digest = hashlib.sha512()
        with Path(path).open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def write_empty_report(self, path: str, target: str) -> None:
        self._write_json(Path(path), {
            "schema_version": 1, "region": target, "layer": "admin_line",
            "relation_sidecar": {"way_count": 0},
            "retained": {"count": 0, "id_leak_count": 0},
            "discarded": {"count": 0, "by_reason": {}},
        })

    def transform(
        self, input_path: str, filtered_pbf: str, derived_directory: str,
        target: str, relation_levels: dict[str, tuple[int, ...]],
        hierarchy: dict[str, dict[str, Any]],
    ) -> str:
        del target
        source, derived = Path(input_path), Path(derived_directory)
        derived.mkdir(parents=True, exist_ok=True)
        pairs_path = derived / "admin-line-relation-level.tsv"
        sidecar_path = derived / "admin-line-relation-level.json"
        report_path = derived / "admin-line-tier-report.json"
        temporary = Path(f"{input_path}.admin-line-tier.tmp")
        ordered = self._ordered_levels(relation_levels)
        self._write_sidecars(pairs_path, sidecar_path, ordered)
        geometry: Counter[str] = Counter()
        tiers: Counter[str] = Counter()
        sources: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        input_count = retained_count = id_leaks = 0
        try:
            with source.open("r", encoding="utf-8") as input_stream, temporary.open(
                "w", encoding="utf-8", newline="\n"
            ) as output_stream:
                for line_number, line in enumerate(input_stream, 1):
                    payload = line.removeprefix("\x1e").strip()
                    if not payload:
                        continue
                    try:
                        feature = json.loads(payload)
                    except json.JSONDecodeError as error:
                        raise ValueError(
                            f"invalid GeoJSONSeq at {input_path}:{line_number}: {error.msg}"
                        ) from error
                    if not isinstance(feature, dict):
                        raise ValueError(
                            f"GeoJSONSeq feature must be an object: {input_path}:{line_number}"
                        )
                    decision = classify_admin_line(feature, ordered, hierarchy)
                    audit = decision.audit
                    input_count += 1
                    geometry[str(audit["geometry"])] += 1
                    if decision.feature is None:
                        reasons[str(audit["reason"])] += 1
                        continue
                    retained_count += 1
                    tiers[str(audit["tier"])] += 1
                    sources[str(audit["level_source"])] += 1
                    properties = decision.feature.get("properties")
                    if isinstance(properties, dict) and properties.get("@id") is not None:
                        id_leaks += 1
                    self._write_feature(output_stream, decision.feature)
            combinations = Counter(
                ",".join(str(level) for level in levels)
                for levels in ordered.values() if len(levels) > 1
            )
            report = {
                "schema_version": 1, "input": input_path,
                "filtered_pbf": filtered_pbf, "input_feature_count": input_count,
                "relation_sidecar": {
                    "member_level_pair_count": sum(map(len, ordered.values())),
                    "way_count": len(ordered),
                    "multi_level_way_count": sum(len(v) > 1 for v in ordered.values()),
                    "multi_level_combinations": dict(sorted(combinations.items())),
                },
                "geometry": dict(sorted(geometry.items())),
                "retained": {
                    "count": retained_count, "by_tier": dict(sorted(tiers.items())),
                    "by_level_source": dict(sorted(sources.items())),
                    "relation_rescued_count": sources["relation"],
                    "id_leak_count": id_leaks,
                },
                "discarded": {"count": sum(reasons.values()),
                              "by_reason": dict(sorted(reasons.items()))},
            }
            self._write_json(report_path, report)
            os.replace(temporary, source)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return str(report_path)

    @staticmethod
    def _ordered_levels(values: dict[str, tuple[int, ...]]) -> dict[str, tuple[int, ...]]:
        def order(item: tuple[str, tuple[int, ...]]) -> tuple[int, int | str]:
            return (0, int(item[0])) if item[0].isdigit() else (1, item[0])
        return {key: tuple(sorted(set(levels)))
                for key, levels in sorted(values.items(), key=order)}

    @staticmethod
    def _write_sidecars(pairs: Path, sidecar: Path,
                        levels: dict[str, tuple[int, ...]]) -> None:
        with pairs.open("w", encoding="utf-8", newline="\n") as stream:
            for way_id, values in levels.items():
                for level in values:
                    stream.write(f"{way_id}\t{level}\n")
        FileSystemAdminLineStore._write_json(
            sidecar, {key: list(values) for key, values in levels.items()}
        )

    @staticmethod
    def _write_json(path: Path, document: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    @staticmethod
    def _write_feature(stream: Any, feature: dict[str, Any]) -> None:
        stream.write("\x1e")
        json.dump(feature, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")
