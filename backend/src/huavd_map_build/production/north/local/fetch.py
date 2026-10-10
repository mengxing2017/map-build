import re

from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.delivery.south.port.digest import DigestPort
from huavd_map_build.production.domain.fetch import FetchRequest, FetchToolError
from huavd_map_build.production.south.port.fetch import Downloader, FetchStore


class RegionFetchService:
    def __init__(
        self,
        catalog: CatalogService,
        downloader: Downloader,
        store: FetchStore,
        digest: DigestPort,
    ) -> None:
        self._catalog = catalog
        self._downloader = downloader
        self._store = store
        self._digest = digest

    def fetch(self, request: FetchRequest) -> str:
        if self._catalog.region(request.region).priority == "local-extract":
            raise ValueError(
                "region requires a local administrative polygon extract; "
                "use scripts/extract-admin-region.py and build --input"
            )
        pbf_url = self._catalog.pbf_url(request.region)
        md5_url = self._catalog.md5_url(request.region)
        basename = self._catalog.pbf_basename(request.region)
        mirror = f"{request.workdir.rstrip('/')}/mirror"
        pbf = f"{mirror}/{basename}"
        sidecar = f"{pbf}.md5"
        self._store.ensure_directory(mirror)
        self._downloader.download(pbf_url, mirror, request.limit_rate)
        self._downloader.download(md5_url, mirror, None)
        if not self._store.is_file(pbf) or not self._store.is_file(sidecar):
            raise FetchToolError(f"download did not produce PBF and MD5 files: {basename}")
        tokens = self._store.read_text(sidecar).split()
        expected = tokens[0].lower() if tokens else ""
        actual = self._digest.checksum(pbf, "md5")
        if not re.fullmatch(r"[0-9a-f]{32}", expected) or expected != actual:
            raise FetchToolError(f"md5 check failed for {basename}")
        return pbf
