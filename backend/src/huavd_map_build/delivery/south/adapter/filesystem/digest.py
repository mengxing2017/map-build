import hashlib
from collections.abc import Iterable
from pathlib import Path


class FileDigestAdapter:
    _ALGORITHMS = frozenset({"md5", "sha256", "sha512"})

    def __init__(self, chunk_size: int = 1024 * 1024) -> None:
        if chunk_size <= 0:
            raise ValueError("digest chunk size must be positive")
        self._chunk_size = chunk_size

    def sha512(self, path: str) -> str:
        return self.checksum(path, "sha512")

    def checksum(self, path: str, algorithm: str) -> str:
        if algorithm not in self._ALGORITHMS:
            raise ValueError(f"unsupported digest algorithm: {algorithm}")
        with Path(path).open("rb") as stream:
            digest = hashlib.new(algorithm)
            while chunk := stream.read(self._chunk_size):
                digest.update(chunk)
        return digest.hexdigest()

    def sha512_chunks(self, chunks: Iterable[bytes]) -> str:
        digest = hashlib.sha512()
        for chunk in chunks:
            digest.update(chunk)
        return digest.hexdigest()
