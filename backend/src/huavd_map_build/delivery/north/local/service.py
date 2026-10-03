from collections.abc import Iterable

from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.delivery.domain.attribution import AttributionDocument
from huavd_map_build.delivery.south.port.digest import DigestPort
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role


class ArtifactQuery:
    def __init__(self, digest: DigestPort) -> None:
        self._digest = digest

    def paths(
        self,
        *,
        region: RegionId,
        build_date: BuildDate,
        role: Role,
        workdir: str,
    ) -> ArtifactPaths:
        identity = ArtifactIdentity(region, build_date, role)
        return ArtifactPaths(identity, f"{workdir.rstrip('/')}/outputs")

    def sha512(self, path: str) -> str:
        return self._digest.sha512(path)

    def checksum(self, path: str, algorithm: str) -> str:
        return self._digest.checksum(path, algorithm)

    def sha512_chunks(self, chunks: Iterable[bytes]) -> str:
        return self._digest.sha512_chunks(chunks)

    def attribution(self, *, pbf_url: str) -> AttributionDocument:
        return AttributionDocument.geofabrik_osm(pbf_url)
