from __future__ import annotations

from contextlib import contextmanager
from huavd_map_build.delivery.domain.metadata import PmtilesHeader
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from huavd_map_build.production.domain.raster import (
    RasterExecutionError,
    RasterSourceMetadata,
    RasterSourceProbe,
    RasterMvtPreflightResult,
    RasterTileCoordinate,
    RasterTileServerEndpoint,
    rewrite_bake_source,
)
from huavd_map_build.production.north.local.raster_runtime import (
    RasterRuntimeRequest,
    RasterRuntimeService,
)
from huavd_map_build.production.south.adapter.process.raster_archive import (
    ProcessRasterArchive,
)
from huavd_map_build.production.south.adapter.process.raster_server import (
    ProcessRasterTileServer,
    UrlLibRasterMvtClient,
)
from huavd_map_build.production.south.adapter.workspace.raster_style import (
    FileSystemRasterRuntimeStyleStore,
)


def local_sockets_available() -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM):
            return True
    except OSError:
        return False


class RasterRuntimeStyleTest(unittest.TestCase):
    def test_rewrites_single_vector_source_without_mutating_input(self) -> None:
        source = {
            "version": 8,
            "sources": {"base": {"type": "vector", "url": "pmtiles://old"}},
            "layers": [],
        }
        result = rewrite_bake_source(
            source, tile_url="http://127.0.0.1:123/base/{z}/{x}/{y}.mvt"
        )
        self.assertEqual("pmtiles://old", source["sources"]["base"]["url"])
        self.assertNotIn("url", result["sources"]["base"])
        self.assertEqual(
            ["http://127.0.0.1:123/base/{z}/{x}/{y}.mvt"],
            result["sources"]["base"]["tiles"],
        )

    def test_rejects_ambiguous_or_non_vector_sources(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            rewrite_bake_source({"sources": {}}, tile_url="url", archive_path="path")
        with self.assertRaisesRegex(ValueError, "source must be vector"):
            rewrite_bake_source(
                {"sources": {"base": {"type": "raster"}}}, tile_url="url"
            )

    def test_store_atomically_writes_runtime_style(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "style.json", root / "runtime" / "style.json"
            source.write_text(json.dumps({
                "version": 8,
                "sources": {"base": {"type": "vector", "url": "old"}},
                "layers": [],
            }), encoding="utf-8")
            FileSystemRasterRuntimeStyleStore().write(
                str(source), str(target), "http://tiles/{z}/{x}/{y}.mvt",
                RasterSourceMetadata(2, 18, (1, 2, 3, 4))
            )
            document = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(
            ["http://tiles/{z}/{x}/{y}.mvt"], document["sources"]["base"]["tiles"]
        )


class RasterServerProcessTest(unittest.TestCase):
    def test_server_uses_argument_vector_and_terminates_on_body_failure(self) -> None:
        process = MagicMock()
        process.poll.return_value = None
        process.wait.return_value = 0
        connection = MagicMock()
        connection.__enter__.return_value = connection
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "base.pmtiles"
            archive.write_bytes(b"PMTiles")
            with patch("huavd_map_build.production.south.adapter.process.raster_server.ThreadingHTTPServer",
                       return_value=MagicMock(server_address=("127.0.0.1",12346))), patch.object(
                ProcessRasterTileServer, "_available_port", return_value=12345
            ), patch("shutil.which", return_value="/tools/pmtiles"), patch(
                "subprocess.Popen", return_value=process
            ) as popen, patch(
                "socket.create_connection", return_value=connection
            ):
                with self.assertRaisesRegex(OSError, "body"):
                    with ProcessRasterTileServer().open(str(archive)) as endpoint:
                        self.assertIn("/base/{z}/{x}/{y}.mvt", endpoint.tile_url)
                        raise OSError("body")
        arguments = popen.call_args.args[0]
        self.assertEqual(["/tools/pmtiles", "serve", str(archive.parent)], arguments[:3])
        self.assertNotIn("shell", popen.call_args.kwargs)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)

    def test_early_process_exit_is_reported_and_log_is_closed(self) -> None:
        process = MagicMock()
        process.poll.return_value = 17
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "base.pmtiles"
            archive.write_bytes(b"PMTiles")
            with patch("huavd_map_build.production.south.adapter.process.raster_server.ThreadingHTTPServer",
                       return_value=MagicMock(server_address=("127.0.0.1",12346))), patch.object(
                ProcessRasterTileServer, "_available_port", return_value=12345
            ), patch("shutil.which", return_value="/tools/pmtiles"), patch(
                "subprocess.Popen", return_value=process
            ):
                with self.assertRaisesRegex(RasterExecutionError, "code 17"):
                    with ProcessRasterTileServer(0.1).open(str(archive)):
                        pass
            log = archive.with_name(f".{archive.name}.serve.log")
            with log.open("ab") as output:
                output.write(b"closed")


class FakeSubsetter:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def extract(self, input_path, output_path, bounds, min_zoom, max_zoom):
        self.events.append("extract")


class FakeServer:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    @contextmanager
    def open(self, archive_path):
        self.events.append(f"open:{archive_path}")
        try:
            yield RasterTileServerEndpoint("http://tiles/{z}/{x}/{y}.mvt", 123)
        finally:
            self.events.append("close")


class FakeClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def fetch(self, tile_url, coordinate):
        self.events.append("fetch")
        return RasterMvtPreflightResult("http://tiles/0/0/0.mvt", 10, 1.0)


class FakeStyles:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def write(self, source_path, output_path, tile_url, metadata):
        self.events.append("style")


class RasterRuntimeServiceTest(unittest.TestCase):
    def test_subset_preflight_style_and_cleanup_have_fixed_order(self) -> None:
        events: list[str] = []
        service = RasterRuntimeService(
            FakeSubsetter(events), FakeServer(events), FakeClient(events), FakeStyles(events),
            MagicMock(read=MagicMock(return_value=PmtilesHeader(1, 2, 0, 4, (1, 2, 3, 4))))
        )
        request = RasterRuntimeRequest(
            "base.pmtiles", "style.json", "runtime.json",
            RasterTileCoordinate(0, 0, 0), "subset.pmtiles", "1,2,3,4", 0, 4,
        )
        with service.open(request) as result:
            events.append("body")
            self.assertEqual("subset.pmtiles", result.served_archive)
        self.assertEqual(
            ["extract", "open:subset.pmtiles", "fetch", "style", "body", "close"],
            events,
        )


@unittest.skipUnless(
    shutil.which("pmtiles") and local_sockets_available(),
    "pmtiles or local sockets are unavailable",
)
class RasterServerIntegrationTest(unittest.TestCase):
    def test_real_server_serves_tile_and_closes_port(self) -> None:
        coordinate = RasterTileCoordinate(0, 0, 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mbtiles, pmtiles = root / "map.mbtiles", root / "map.pmtiles"
            payload = b"\x1a\x00"
            with sqlite3.connect(mbtiles) as connection:
                connection.execute("create table metadata (name text, value text)")
                connection.execute(
                    "create table tiles (zoom_level integer, tile_column integer, "
                    "tile_row integer, tile_data blob)"
                )
                connection.executemany(
                    "insert into metadata(name, value) values (?, ?)",
                    (("name", "map"), ("format", "pbf"), ("minzoom", "0"),
                     ("maxzoom", "0"), ("bounds", "-180,-85,180,85")),
                )
                connection.execute(
                    "insert into tiles values (?, ?, ?, ?)", (0, 0, 0, payload)
                )
            ProcessRasterArchive().convert(str(mbtiles), str(pmtiles))
            with ProcessRasterTileServer().open(str(pmtiles)) as endpoint:
                result = UrlLibRasterMvtClient().fetch(endpoint.tile_url, coordinate)
                port = endpoint.port
            with self.assertRaises(OSError):
                socket.create_connection(("127.0.0.1", port), timeout=0.2)
        self.assertGreater(result.payload_bytes, 0)


if __name__ == "__main__":
    unittest.main()


class RasterSourceContractTest(unittest.TestCase):
    def test_replaces_stale_source_metadata_without_mutating_style(self):
        document = {"sources": {"base": {"type": "vector", "url": "old", "maxzoom": 14}}}
        metadata = RasterSourceMetadata(2, 19, (110, 25, 111, 26))
        rewritten = rewrite_bake_source(document, tile_url="local", metadata=metadata)
        self.assertEqual(14, document["sources"]["base"]["maxzoom"])
        self.assertEqual(19, rewritten["sources"]["base"]["maxzoom"])
        self.assertEqual([110, 25, 111, 26], rewritten["sources"]["base"]["bounds"])

    def test_rejects_invalid_headers_and_clamps_parent_coordinate(self):
        for minimum, maximum in ((True, 19), (0, 25), (19, 18)):
            with self.assertRaises(ValueError):
                RasterSourceMetadata(minimum, maximum, (1, 2, 3, 4))
        with self.assertRaises(ValueError):
            RasterSourceMetadata(0, 19, (3, 2, 1, 4))
        source = RasterSourceMetadata(0, 18, (1, 2, 3, 4))
        self.assertEqual(RasterTileCoordinate(18, 123, 234), source.coordinate(RasterTileCoordinate(19, 247, 469)))

    def test_subset_clamps_zooms_and_reads_served_header(self):
        source = PmtilesHeader(1, 2, 0, 18, (1, 2, 3, 4))
        subset = PmtilesHeader(1, 2, 15, 18, (1.1, 2.1, 2.9, 3.9))
        headers = MagicMock()
        headers.read.side_effect = [source, subset]
        subsetter, client, styles = MagicMock(), MagicMock(), MagicMock()
        client.fetch.return_value = RasterMvtPreflightResult("url", 1, 0)
        service = RasterRuntimeService(subsetter, FakeServer([]), client, styles, headers)
        request = RasterRuntimeRequest("base", "style", "runtime", RasterTileCoordinate(19, 247, 469),
                                       "subset", "1,2,3,4", 15, 19)
        with service.open(request) as result:
            self.assertEqual(subset.bounds, result.source_metadata.bounds)
        subsetter.extract.assert_called_once_with("base", "subset", "1,2,3,4", 15, 18)
        self.assertEqual(RasterTileCoordinate(18, 123, 234), client.fetch.call_args.args[1])
        self.assertEqual(15, styles.write.call_args.args[3].min_zoom)

    def test_empty_subset_zoom_intersection_fails_before_server(self):
        headers = MagicMock(read=MagicMock(return_value=PmtilesHeader(1, 2, 0, 14, (1,2,3,4))))
        server, subsetter = MagicMock(), MagicMock()
        service = RasterRuntimeService(subsetter, server, MagicMock(), MagicMock(), headers)
        request = RasterRuntimeRequest("base", "style", "runtime", RasterTileCoordinate(19,0,0),
                                       "subset", "1,2,3,4", 19,19)
        with self.assertRaisesRegex(ValueError, "no zoom intersection"):
            with service.open(request):
                pass
        subsetter.extract.assert_not_called()
        server.open.assert_not_called()


class RasterKnownContentTest(unittest.TestCase):
    def test_known_content_missing_fails_even_when_http_response_is_valid(self):
        headers = MagicMock(read=MagicMock(return_value=PmtilesHeader(1,2,0,18,(0,0,1,1))))
        client = MagicMock()
        client.fetch.return_value = RasterMvtPreflightResult("url", 0, 1)
        request = RasterRuntimeRequest("base", "style", "runtime", RasterTileCoordinate(0,0,0),
            probes=(RasterSourceProbe(RasterTileCoordinate(19,1,1), "road"),))
        service = RasterRuntimeService(MagicMock(), FakeServer([]), client, MagicMock(), headers)
        with self.assertRaisesRegex(ValueError, "no road content"):
            with service.open(request):
                pass
        client.fetch.return_value = RasterMvtPreflightResult("url", 100, 1, ("road",))
        with service.open(request) as result:
            self.assertEqual([18,0,0], result.evidence[0]["source_xyz"])
            self.assertEqual([19,1,1], result.evidence[0]["output_xyz"])
            self.assertEqual("road", result.evidence[0]["expected_layer"])
