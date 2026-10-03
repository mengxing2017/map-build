from __future__ import annotations

import json
from pathlib import Path
from pathlib import PurePosixPath
import struct
from typing import Any

from huavd_map_build.delivery.domain.metadata import PmtilesHeader
from huavd_map_build.delivery.south.port.atomic_writer import AtomicWriter
from huavd_map_build.delivery.south.port.digest import DigestPort


class FileSystemPmtilesHeaderReader:
    def read(self, path: str) -> PmtilesHeader:
        with Path(path).open("rb") as stream:
            payload = stream.read(118)
        if len(payload) < 118 or payload[:7] != b"PMTiles" or payload[7] != 3:
            raise ValueError(f"invalid PMTiles v3 header: {path}")
        bounds = tuple(
            value / 10_000_000 for value in struct.unpack_from("<iiii", payload, 102)
        )
        return PmtilesHeader(
            payload[99], payload[98], payload[100], payload[101], bounds,
            payload[97], struct.unpack_from("<Q", payload, 8)[0],
            struct.unpack_from("<Q", payload, 16)[0],
            struct.unpack_from("<Q", payload, 72)[0],
        )


class FileSystemMetadataStore:
    def __init__(self, writer: AtomicWriter, digest: DigestPort) -> None:
        self._writer = writer
        self._digest = digest

    def is_file(self, path: str) -> bool:
        return Path(path).is_file()

    def write_document(self, path: str, document: dict[str, Any]) -> None:
        self._writer.write_text(
            path, json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        )

    def write_sidecar(self, path: str) -> str:
        sidecar = f"{path}.sha512"
        content = f"{self._digest.sha512(path)}  {PurePosixPath(path).name}\n"
        self._writer.write_text(sidecar, content)
        return sidecar
