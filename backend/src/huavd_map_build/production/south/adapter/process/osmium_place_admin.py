from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

from huavd_map_build.production.domain.place_admin import (
    AdministrativeRelation,
    MissingPlaceAdminToolError,
    PlaceAdminExecutionError,
)


class OsmiumPlaceAdminTool:
    def filter_source(self, input_path: str, output_path: str) -> None:
        self._run([
            self._executable(), "tags-filter", "-O", "-o", output_path,
            input_path, "r/boundary=administrative", "n/place",
        ], "administrative relation filter")

    def read_relations_and_nodes(
        self, source_path: str
    ) -> tuple[tuple[AdministrativeRelation, ...], dict[int, str]]:
        executable = self._executable()
        try:
            process = subprocess.Popen(
                [executable, "cat", "-f", "xml", source_path, "-o", "-"],
                stdout=subprocess.PIPE, env=self._environment(),
            )
        except OSError as error:
            raise PlaceAdminExecutionError(f"failed to start osmium cat: {error}") from error
        assert process.stdout is not None
        relations: list[AdministrativeRelation] = []
        nodes: dict[int, str] = {}
        try:
            for _event, element in ET.iterparse(process.stdout, events=("end",)):
                if element.tag == "node":
                    tags = self._tags(element)
                    if tags.get("wikidata") and element.get("id", "").isdigit():
                        nodes[int(element.get("id", "0"))] = tags["wikidata"]
                    element.clear()
                elif element.tag == "relation":
                    tags = self._tags(element)
                    relation_id = element.get("id", "")
                    if tags.get("boundary") == "administrative" and relation_id.isdigit():
                        raw_level = tags.get("admin_level")
                        level = int(raw_level) if raw_level and raw_level.isdigit() else None
                        members = tuple(
                            (int(reference), member.get("role", ""))
                            for member in element.findall("member")
                            if member.get("type") == "node"
                            and (reference := member.get("ref", "")).isdigit()
                            and member.get("role") in {"admin_centre", "label"}
                        )
                        relations.append(AdministrativeRelation(
                            int(relation_id), level,
                            (tags.get("name:zh-Hans"), tags.get("name:zh"),
                             tags.get("name"), tags.get("name:en")),
                            tags.get("wikidata"), members,
                        ))
                    element.clear()
        except (ET.ParseError, OSError, ValueError) as error:
            process.kill()
            process.wait()
            raise PlaceAdminExecutionError(
                f"cannot parse osmium place administration XML: {error}"
            ) from error
        finally:
            process.stdout.close()
        return_code = process.wait()
        if return_code != 0:
            raise PlaceAdminExecutionError(
                f"osmium place administration index failed with exit code {return_code}"
            )
        return tuple(relations), nodes

    def export_boundaries(
        self, source_path: str, output_path: str, config_path: str
    ) -> None:
        self._run([
            self._executable(), "export", "-c", config_path, source_path,
            "-f", "geojsonseq", "-o", output_path, "--overwrite",
        ], "administrative boundary export")

    def _run(self, arguments: list[str], operation: str) -> None:
        try:
            result = subprocess.run(
                arguments, env=self._environment(), text=True,
                capture_output=True, check=False,
            )
        except OSError as error:
            raise PlaceAdminExecutionError(f"failed to start {operation}: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()
            message = detail[-1] if detail else f"exit {result.returncode}"
            raise PlaceAdminExecutionError(f"{operation} failed: {message}")

    @staticmethod
    def _tags(element: ET.Element) -> dict[str, str]:
        return {
            tag.get("k", ""): tag.get("v", "")
            for tag in element.findall("tag") if tag.get("k")
        }

    @staticmethod
    def _executable() -> str:
        executable = shutil.which("osmium")
        if executable is None:
            raise MissingPlaceAdminToolError("required command not found: osmium")
        return executable

    @staticmethod
    def _environment() -> dict[str, str]:
        allowed = ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
        return {key: os.environ[key] for key in allowed if key in os.environ}
