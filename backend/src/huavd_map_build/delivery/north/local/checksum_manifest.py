from pathlib import PurePosixPath

from huavd_map_build.delivery.domain.checksum_manifest import (
    ChecksumEntry,
    ChecksumManifest,
)
from huavd_map_build.delivery.south.port.atomic_writer import AtomicWriter
from huavd_map_build.delivery.south.port.digest import DigestPort
from huavd_map_build.delivery.south.port.manifest_store import ManifestFileStore


class ChecksumManifestWriter:
    def __init__(
        self,
        store: ManifestFileStore,
        digest: DigestPort,
        writer: AtomicWriter,
    ) -> None:
        self._store = store
        self._digest = digest
        self._writer = writer

    def write(
        self,
        *,
        root: str,
        output_name: str,
        algorithm: str,
        excluded_names: tuple[str, ...] = (),
        excluded_suffixes: tuple[str, ...] = (),
    ) -> ChecksumManifest:
        if "/" in output_name or not output_name:
            raise ValueError(f"invalid checksum manifest name: {output_name}")
        excluded = {*excluded_names, output_name}
        entries: list[ChecksumEntry] = []
        for relative_path in self._store.list_regular_files(root):
            name = PurePosixPath(relative_path).name
            if name in excluded or any(
                name.endswith(suffix) for suffix in excluded_suffixes
            ):
                continue
            filesystem_path = f"{root.rstrip('/')}/{relative_path.removeprefix('./')}"
            entries.append(
                ChecksumEntry(
                    self._digest.checksum(filesystem_path, algorithm), relative_path
                )
            )
        manifest = ChecksumManifest(algorithm, tuple(entries))
        self._writer.write_text(f"{root.rstrip('/')}/{output_name}", manifest.render())
        return manifest
