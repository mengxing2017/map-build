from pathlib import PurePosixPath

from huavd_map_build.delivery.south.port.artifact_store import ArtifactStore
from huavd_map_build.delivery.south.port.atomic_writer import AtomicWriter
from huavd_map_build.delivery.south.port.digest import DigestPort


class Sha512SidecarWriterService:
    def __init__(
        self, store: ArtifactStore, digest: DigestPort, writer: AtomicWriter
    ) -> None:
        self._store = store
        self._digest = digest
        self._writer = writer

    def write(self, artifact: str) -> str:
        if not self._store.is_file(artifact):
            raise ValueError(f"required file does not exist: {artifact}")
        sidecar = f"{artifact}.sha512"
        content = f"{self._digest.sha512(artifact)}  {PurePosixPath(artifact).name}\n"
        self._writer.write_text(sidecar, content)
        return sidecar
