from __future__ import annotations

import re
import json
from pathlib import PurePosixPath

from huavd_map_build.delivery.domain.artifact import ArtifactPaths
from huavd_map_build.delivery.domain.integrity import (
    ArtifactIntegrityReport,
    IntegrityFailure,
)
from huavd_map_build.delivery.domain.publication import ReadyMarker, ReadyMarkerError
from huavd_map_build.delivery.south.port.artifact_store import ArtifactStore
from huavd_map_build.delivery.south.port.digest import DigestPort


_SHA512 = re.compile(r"^[0-9a-f]{128}$")


class ArtifactFileVerifier:
    def __init__(self, store: ArtifactStore, digest: DigestPort) -> None:
        self._store = store
        self._digest = digest

    def verify(
        self,
        paths: ArtifactPaths,
        *,
        require_consumer_closure: bool = False,
        require_ready_marker: bool = False,
    ) -> ArtifactIntegrityReport:
        expected = (
            paths.consumer_closure() if require_consumer_closure else paths.core_files()
        )
        checked = tuple(dict.fromkeys(expected))
        failures: list[IntegrityFailure] = []
        for path in checked:
            if not self._store.exists(path):
                failures.append(IntegrityFailure("missing", path, "required path is missing"))

        self._verify_sidecar(paths.pmtiles, paths.sha512, failures)
        if require_consumer_closure and paths.identity.role.value == "raster_bake":
            base_pmtiles = paths.pmtiles.replace(".raster_bake.pmtiles", ".base.pmtiles")
            base_sidecar = f"{base_pmtiles}.sha512"
            self._verify_sidecar(base_pmtiles, base_sidecar, failures)
        if require_ready_marker:
            if paths.ready not in checked:
                checked = (*checked, paths.ready)
            if not self._store.exists(paths.ready):
                failures.append(
                    IntegrityFailure("missing", paths.ready, "ready marker is missing")
                )
            else:
                self._verify_ready_marker(paths, failures)
        return ArtifactIntegrityReport(checked, tuple(failures))

    def _verify_sidecar(
        self, artifact: str, sidecar: str, failures: list[IntegrityFailure]
    ) -> None:
        if not self._store.is_file(artifact) or not self._store.is_file(sidecar):
            return
        try:
            content = self._store.read_text(sidecar).strip()
        except (OSError, UnicodeError) as error:
            failures.append(IntegrityFailure("sidecar-read", sidecar, str(error)))
            return
        fields = content.split()
        expected_name = PurePosixPath(artifact).name
        if len(fields) != 2 or not _SHA512.fullmatch(fields[0]):
            failures.append(
                IntegrityFailure(
                    "sidecar-format",
                    sidecar,
                    "expected '<128 lowercase hex>  <filename>'",
                )
            )
            return
        if fields[1].lstrip("*") != expected_name:
            failures.append(
                IntegrityFailure(
                    "sidecar-filename",
                    sidecar,
                    f"expected filename {expected_name}",
                )
            )
            return
        try:
            actual = self._digest.sha512(artifact)
        except OSError as error:
            failures.append(IntegrityFailure("digest-read", artifact, str(error)))
            return
        if actual != fields[0]:
            failures.append(
                IntegrityFailure("digest-mismatch", artifact, "SHA-512 does not match sidecar")
            )

    def _verify_ready_marker(
        self, paths: ArtifactPaths, failures: list[IntegrityFailure]
    ) -> None:
        try:
            document = json.loads(self._store.read_text(paths.ready))
            marker = ReadyMarker.from_mapping(document)
        except (OSError, UnicodeError, json.JSONDecodeError, ReadyMarkerError) as error:
            failures.append(IntegrityFailure("ready-format", paths.ready, str(error)))
            return
        expected_file = PurePosixPath(paths.pmtiles).name
        if marker.role is not paths.identity.role:
            failures.append(
                IntegrityFailure(
                    "ready-role", paths.ready, f"expected role {paths.identity.role.value}"
                )
            )
        if marker.file != expected_file:
            failures.append(
                IntegrityFailure(
                    "ready-file", paths.ready, f"expected file {expected_file}"
                )
            )
        digest_targets = (
            ("ready-sha512", paths.pmtiles, marker.sha512),
            ("ready-manifest-sha512", paths.manifest, marker.manifest_sha512),
            ("ready-attribution-sha512", paths.attribution, marker.attribution_sha512),
        )
        for code, path, expected in digest_targets:
            if not self._store.is_file(path):
                continue
            try:
                actual = self._digest.sha512(path)
            except OSError as error:
                failures.append(IntegrityFailure("digest-read", path, str(error)))
                continue
            if actual != expected:
                failures.append(
                    IntegrityFailure(code, path, "SHA-512 does not match ready marker")
                )
