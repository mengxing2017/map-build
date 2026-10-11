"""Opt-in real MVT -> Native PNG -> WebP -> PMTiles -> full readback regression."""
import gzip
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from huavd_map_build.bootstrap import raster_bake_request_factory, raster_bake_service
from huavd_map_build.production.domain.raster import RasterBounds, RasterContentSample, RasterTileCoordinate, create_raster_tile_plan
from huavd_map_build.production.north.local.raster_request import RasterBakeOverrides
from huavd_map_build.production.south.adapter.process.raster_archive import ProcessRasterArchive
from huavd_map_build.production.south.adapter.process.raster_native import native_renderer_identity
from huavd_map_build.shared.kernel import BuildDate, RegionId


@unittest.skipUnless(os.environ.get('HUAVD_NATIVE_RENDER_BIN'), 'set HUAVD_NATIVE_RENDER_BIN for real raster pipeline')
class RasterNativePipelineTest(unittest.TestCase):
    def test_actual_z19_pipeline_reads_every_tile_logs_requests_and_reuses_cache(self):
        import mapbox_vector_tile
        from dataclasses import replace
        binary = os.environ['HUAVD_NATIVE_RENDER_BIN']
        output = RasterTileCoordinate(19,262144,229140)
        bounds = output.bounds
        # Keep the planning bbox strictly inside one XYZ tile to avoid boundary rounding.
        epsilon=0.00000001
        bounds=RasterBounds(bounds.west+epsilon,bounds.south+epsilon,bounds.east-epsilon,bounds.north-epsilon)
        payload = gzip.compress(mapbox_vector_tile.encode({'name':'water','features':[{
            'geometry':{'type':'Polygon','coordinates':[[[-4096,-4096],[8192,-4096],[8192,8192],[-4096,8192],[-4096,-4096]]]},
            'properties':{}}]}))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            base=root/'outputs/china-guangxi-20261003.base.pmtiles'
            base.parent.mkdir(parents=True)
            mbtiles=root/'base.mbtiles'
            with sqlite3.connect(mbtiles) as database:
                database.executescript('create table metadata(name text,value text);create table tiles(zoom_level integer,tile_column integer,tile_row integer,tile_data blob);')
                database.executemany('insert into metadata values (?,?)',[
                    ('name','z19-pipeline'),('format','pbf'),('minzoom','18'),('maxzoom','19'),
                    ('bounds',','.join(map(str,bounds.as_list())))])
                for z,x,y in ((18,output.x//2,output.y//2),(19,output.x,output.y)):
                    database.execute('insert into tiles values (?,?,?,?)',(z,x,(1<<z)-1-y,payload))
            ProcessRasterArchive().convert(str(mbtiles),str(base))
            cache=root/'cache/bake/china-guangxi-20261003'
            cache.mkdir(parents=True)
            (cache/'style-render.json').write_text(json.dumps({'version':8,
                'sources':{'base':{'type':'vector','url':'pmtiles://stale','maxzoom':14}},
                'layers':[{'id':'background','type':'background','paint':{'background-color':'#123456'}},
                          {'id':'water','type':'fill','source':'base','source-layer':'water','paint':{'fill-color':'#00ff00'}}]}))
            longitude,latitude=output.center
            plan=create_raster_tile_plan(bounds,19,19,0,10)
            self.assertEqual(1,plan.tile_count)
            request=raster_bake_request_factory().create(RegionId('china/guangxi'),BuildDate('20261003'),directory,plan,
                RasterBakeOverrides(renderer_engine='maplibre-native-headless',renderer_command=binary,
                    renderer_identity=native_renderer_identity(binary),retries=0,
                    content_samples=(RasterContentSample('water',longitude,latitude),)))
            first=raster_bake_service().bake(request)
            self.assertEqual(1,first.assembly.verified_tiles)
            self.assertEqual(1,first.render.rendered_tiles)
            runtime=json.loads((cache/'style-render-runtime.json').read_text())
            self.assertEqual(19,runtime['sources']['base']['maxzoom'])
            self.assertEqual(18,runtime['sources']['base']['minzoom'])
            requests=[json.loads(row) for row in base.with_name('.'+base.name+'.requests.jsonl').read_text().splitlines()]
            self.assertTrue(any(item['status']==200 for item in requests))
            self.assertTrue(all(18<=item['z']<=19 for item in requests),requests)
            warm=raster_bake_service().bake(request)
            self.assertFalse(warm.cache.invalidated)
            self.assertIsNone(warm.render)
            self.assertEqual(1,warm.assembly.verified_tiles)
            changed=replace(request,identity=replace(request.identity,runtime_source_policy='test-next-policy'))
            rebuilt=raster_bake_service().bake(changed)
            self.assertTrue(rebuilt.cache.invalidated)
            self.assertEqual(1,rebuilt.render.rendered_tiles)
