from typing import Protocol

from huavd_map_build.production.domain.profile_transform import LayerProfilePolicy


class ProfileTransformer(Protocol):
    def require_file(self, path: str) -> None: ...

    def is_nonempty(self, path: str) -> bool: ...

    def transform(self, path: str, policy: LayerProfilePolicy) -> None: ...
