from __future__ import annotations

import json
from pathlib import PurePosixPath

from huavd_map_build.delivery.domain.artifact import ArtifactContractError, ArtifactPaths
from huavd_map_build.delivery.domain.publication import ReadyMarker
from huavd_map_build.delivery.south.port.artifact_store import ArtifactStore
from huavd_map_build.delivery.south.port.atomic_writer import AtomicWriter
from huavd_map_build.delivery.south.port.digest import DigestPort


class ArtifactPublicationService:
    def __init__(
        self, store: ArtifactStore, digest: DigestPort, writer: AtomicWriter
    ) -> None:
        self._store = store
        self._digest = digest
        self._writer = writer

    def publish_integrity_metadata(
        self, paths: ArtifactPaths, *, published_at: str
    ) -> ReadyMarker:
        for path in (paths.pmtiles, paths.manifest, paths.attribution):
            if not self._store.is_file(path):
                raise ArtifactContractError(f"cannot publish missing artifact file: {path}")

        pmtiles_sha512 = self._digest.sha512(paths.pmtiles)
        sidecar = f"{pmtiles_sha512}  {PurePosixPath(paths.pmtiles).name}\n"
        self._writer.write_text(paths.sha512, sidecar)

        marker = ReadyMarker.from_mapping(
            {
                "schema_version": 1,
                "role": paths.identity.role.value,
                "file": PurePosixPath(paths.pmtiles).name,
                "sha512": pmtiles_sha512,
                "manifest_sha512": self._digest.sha512(paths.manifest),
                "attribution_sha512": self._digest.sha512(paths.attribution),
                "published_at": published_at,
            }
        )
        content = json.dumps(
            marker.as_dict(), ensure_ascii=True, indent=2, sort_keys=True
        ) + "\n"
        self._writer.write_text(paths.ready, content)
        return marker
