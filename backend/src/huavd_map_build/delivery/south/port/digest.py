from collections.abc import Iterable
from typing import Protocol


class DigestPort(Protocol):
    def checksum(self, path: str, algorithm: str) -> str: ...

    def sha512(self, path: str) -> str: ...

    def sha512_chunks(self, chunks: Iterable[bytes]) -> str: ...
