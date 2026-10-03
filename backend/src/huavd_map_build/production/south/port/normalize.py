from typing import Protocol

from huavd_map_build.production.domain.normalize import NormalizationPolicy


class GeoJsonSeqNormalizer(Protocol):
    def require_directory(self, path: str) -> None: ...

    def require_file(self, path: str) -> None: ...

    def normalize(self, path: str, policy: NormalizationPolicy) -> None: ...
