"""Opt-in real Vulkan tests: run through scripts/native-renderer-env.sh."""
from __future__ import annotations

import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

from huavd_map_build.production.domain.raster import RasterRenderSettings, RasterTileCoordinate
from huavd_map_build.production.south.adapter.process.raster import ProcessRasterTileRenderer, ProcessWebpEncoder
from huavd_map_build.production.south.adapter.process.raster_native import native_renderer_identity
from huavd_map_build.production.south.adapter.process.raster_server import UrlLibRasterMvtClient


@unittest.skipUnless(os.environ.get("HUAVD_NATIVE_RENDER_BIN"), "set HUAVD_NATIVE_RENDER_BIN to run Vulkan integration")
class NativeIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.binary = os.environ["HUAVD_NATIVE_RENDER_BIN"]
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def render(self, style, z=1, x=1, y=0, size=256):
        source = self.root / "style.json"
        source.write_text(json.dumps(style))
        output = self.root / "tile.png"
        settings = RasterRenderSettings(
            str(source), str(self.root), str(self.root), size,
            "maplibre-native-headless", self.binary,
        )
        ProcessRasterTileRenderer().render(RasterTileCoordinate(z, x, y), settings, str(output))
        webp = self.root / "tile.webp"
        ProcessWebpEncoder().encode(str(output), str(webp), settings)
        pam = self.root / "tile.pam"
        subprocess.run(["dwebp", str(webp), "-pam", "-o", str(pam)], check=True, capture_output=True)
        header, pixels = pam.read_bytes().split(b"ENDHDR\n", 1)
        self.assertIn(f"WIDTH {size}".encode(), header)
        depth = 4 if b"DEPTH 4" in header else 3
        self.assertEqual(size * size * depth, len(pixels))
        def pixel(x, y):
            offset = (y * size + x) * depth
            return tuple(pixels[offset:offset + 3])
        return pixel

    def test_version_and_real_self_test(self):
        identity = json.loads(native_renderer_identity(self.binary))
        self.assertEqual(1, identity["protocol_version"])
        self.assertIn("binary_sha512", identity)
        result = subprocess.run([self.binary, "--self-test"], check=True, capture_output=True, text=True)
        self.assertEqual("passed", json.loads(result.stdout)["self_test"])

    def test_invalid_input_is_rejected_without_an_output(self):
        source = self.root / "invalid.json"
        source.write_text(json.dumps({"version":8,"sources":{"base":{"type":"vector","tiles":[]}},"layers":[]}))
        output = self.root / "invalid.png"
        result = subprocess.run([
            self.binary,"--style",str(source),"--z","0","--x","0","--y","0",
            "--output",str(output),
        ], capture_output=True, text=True)
        self.assertEqual(2, result.returncode)
        self.assertIn("tiles must not be empty", result.stderr)
        self.assertFalse(output.exists())

    def test_gzipped_local_mvt_produces_visible_geometry_at_all_supported_sizes(self):
        import mapbox_vector_tile
        payload = gzip.compress(mapbox_vector_tile.encode({"name": "water", "features": [{
            "geometry": {"type": "Polygon", "coordinates": [[[512,512],[3584,512],[3584,3584],[512,3584],[512,512]]]},
            "properties": {},
        }]}))
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.mapbox-vector-tile")
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            style = {"version":8,"sources":{"base":{"type":"vector","tiles":[
                f"http://127.0.0.1:{server.server_port}/{{z}}/{{x}}/{{y}}.mvt"
            ]}},"layers":[
                {"id":"bg","type":"background","paint":{"background-color":"#123456"}},
                {"id":"water","type":"fill","source":"base","source-layer":"water","paint":{"fill-color":"#00ff00"}},
            ]}
            UrlLibRasterMvtClient().fetch(
                style["sources"]["base"]["tiles"][0], RasterTileCoordinate(0,0,0), validate=True
            )
            for z, size in ((0,256),(0,512),(1,256),(1,512)):
                with self.subTest(z=z, size=size):
                    pixel = self.render(style, z=z, x=0 if z == 0 else 1, size=size)
                    self.assertEqual((0,255,0), pixel(size//2, size//2))
                    self.assertEqual((18,52,86), pixel(size-2, 1))
            self.assertTrue(requests)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

    def test_adjacent_xyz_tiles_preserve_inline_geometry_seam(self):
        style = {"version":8,"sources":{"shape":{"type":"geojson","data":{
            "type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[
                [-1,24],[1,24],[1,26],[-1,26],[-1,24]
            ]]}
        }}},"layers":[
            {"id":"bg","type":"background","paint":{"background-color":"#123456"}},
            {"id":"shape","type":"fill","source":"shape","paint":{"fill-color":"#00ff00"}},
        ]}
        for size in (256,512):
            with self.subTest(size=size):
                left = self.render(style, z=8, x=127, y=109, size=size)
                right = self.render(style, z=8, x=128, y=109, size=size)
                self.assertEqual((0,255,0), left(size-1, size//2))
                self.assertEqual(left(size-1, size//2), right(0, size//2))

    def test_z19_local_mvt_respects_source_ceiling_and_keeps_visible_geometry(self):
        import mapbox_vector_tile
        payload = gzip.compress(mapbox_vector_tile.encode({"name":"water","features":[{
            "geometry":{"type":"Polygon","coordinates":[[[-4096,-4096],[8192,-4096],[8192,8192],[-4096,8192],[-4096,-4096]]]},
            "properties":{}}]}))
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(tuple(map(int,self.path.removesuffix('.mvt').strip('/').split('/'))))
                self.send_response(200)
                self.send_header('Content-Type','application/vnd.mapbox-vector-tile')
                self.send_header('Content-Encoding','gzip')
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self,*args):
                pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        try:
            for ceiling in (18,19):
                requests.clear()
                style={"version":8,"sources":{"base":{"type":"vector","minzoom":0,"maxzoom":ceiling,
                    "tiles":[f"http://127.0.0.1:{server.server_port}/{{z}}/{{x}}/{{y}}.mvt"]}},"layers":[
                    {"id":"bg","type":"background","paint":{"background-color":"#123456"}},
                    {"id":"water","type":"fill","source":"base","source-layer":"water","paint":{"fill-color":"#00ff00"}}]}
                with self.subTest(source_maxzoom=ceiling):
                    pixel=self.render(style,z=19,x=262144,y=229140)
                    self.assertEqual((0,255,0),pixel(128,128))
                    self.assertTrue(requests)
                    self.assertTrue(all(0<=z<=ceiling for z,x,y in requests),requests)
                    (self.root/f'xyz19-source{ceiling}-requests.json').write_text(json.dumps(requests))
        finally:
            server.shutdown();server.server_close();worker.join(timeout=5)

    def test_z19_adjacent_tiles_cross_canonical_boundary_without_gap(self):
        from huavd_map_build.production.domain.raster import RasterTileCoordinate
        left_bounds=RasterTileCoordinate(19,262143,229140).bounds
        right_bounds=RasterTileCoordinate(19,262144,229140).bounds
        south,north=left_bounds.south,left_bounds.north
        style={"version":8,"sources":{"shape":{"type":"geojson","data":{
            "type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[
                [left_bounds.west,south],[right_bounds.east,south],[right_bounds.east,north],
                [left_bounds.west,north],[left_bounds.west,south]]]}}}},"layers":[
            {"id":"bg","type":"background","paint":{"background-color":"#123456"}},
            {"id":"shape","type":"fill","source":"shape","paint":{"fill-color":"#00ff00"}}]}
        left=self.render(style,z=19,x=262143,y=229140)
        right=self.render(style,z=19,x=262144,y=229140)
        self.assertEqual((0,255,0),left(255,128))
        self.assertEqual(left(255,128),right(0,128))



if __name__ == "__main__":
    unittest.main()
