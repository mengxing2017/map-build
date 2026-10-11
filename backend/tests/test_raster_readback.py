import json
import io
from contextlib import redirect_stderr
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from huavd_map_build.production.domain.raster import RasterExecutionError, RasterTileCoordinate
from huavd_map_build.production.south.adapter.process.raster_readback import ProcessRasterArchiveVerifier
from test_raster_assembly import lossless_webp


class RasterReadbackTest(unittest.TestCase):
    def test_reads_every_xyz_compares_cache_and_decodes_duplicate_content_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue, archive = root / 'tiles.tsv', root / 'candidate.pmtiles'
            queue.write_text(''.join(RasterTileCoordinate(1,x,0).tsv() for x in (0,1)))
            archive.write_bytes(b'archive')
            for x in (0,1):
                tile = root / 'webp/1' / str(x) / '0.webp'
                tile.parent.mkdir(parents=True)
                tile.write_bytes(lossless_webp())
            with patch('shutil.which', side_effect=lambda name: '/tools/'+name), patch(
                'subprocess.run', return_value=subprocess.CompletedProcess([],0,stdout=lossless_webp())
            ) as run, patch('huavd_map_build.production.south.adapter.process.raster_readback._run') as decode:
                progress = io.StringIO()
                with redirect_stderr(progress), patch(
                    'huavd_map_build.production.south.adapter.process.raster_readback.time.monotonic',
                    side_effect=[0, 11, 22],
                ):
                    self.assertEqual(2, ProcessRasterArchiveVerifier().verify(str(archive),str(queue),str(root/'webp'),256))
                self.assertIn('raster readback started tiles=2', progress.getvalue())
                self.assertIn('1/2 (50.0%)', progress.getvalue())
                self.assertIn('2/2 (100.0%)', progress.getvalue())
                self.assertIn('eta=0s', progress.getvalue())
                self.assertEqual(2, run.call_count)
                self.assertEqual(1, decode.call_count)
                report = json.loads(archive.with_suffix('.readback.json').read_text())
                self.assertEqual(2, report['verified_tiles'])
                self.assertEqual('not-run', report['visual_acceptance'])
                (root/'webp/1/1/0.webp').write_bytes(b'wrong')
                with self.assertRaisesRegex(RasterExecutionError, 'differs from cache'):
                    ProcessRasterArchiveVerifier().verify(str(archive),str(queue),str(root/'webp'),256)
                self.assertFalse(archive.with_suffix('.readback.json').exists())

    def test_decode_failure_never_writes_passed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue, archive = root/'tiles.tsv', root/'candidate.pmtiles'
            queue.write_text(RasterTileCoordinate(0,0,0).tsv())
            archive.write_bytes(b'archive')
            tile=root/'webp/0/0/0.webp'
            tile.parent.mkdir(parents=True)
            tile.write_bytes(lossless_webp())
            with patch('shutil.which', return_value='/tools/tool'), patch('subprocess.run',
                return_value=subprocess.CompletedProcess([],0,stdout=lossless_webp())), patch(
                'huavd_map_build.production.south.adapter.process.raster_readback._run',
                side_effect=RasterExecutionError('corrupt WebP')):
                with self.assertRaisesRegex(RasterExecutionError,'corrupt'):
                    ProcessRasterArchiveVerifier().verify(str(archive),str(queue),str(root/'webp'),256)
                self.assertFalse(archive.with_suffix('.readback.json').exists())

    @unittest.skipUnless(all(shutil.which(tool) for tool in ('pmtiles','cwebp','dwebp')), 'raster tools unavailable')
    def test_real_candidate_readback_and_wrong_cache(self):
        from huavd_map_build.production.domain.raster import RasterAssemblySettings, RasterBounds
        from huavd_map_build.production.south.adapter.workspace.raster_mbtiles import SqliteRasterTileArchiveAssembler
        from huavd_map_build.production.south.adapter.process.raster_archive import ProcessRasterArchive
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            ppm=root/'tile.ppm'
            ppm.write_bytes(b'P6\n256 256\n255\n'+bytes((18,52,86))*256*256)
            tile=root/'webp/19/1/1.webp'
            tile.parent.mkdir(parents=True)
            subprocess.run(['cwebp','-lossless',str(ppm),'-o',str(tile)],check=True,capture_output=True)
            Path(str(tile)+'.sha512').write_text(hashlib.sha512(tile.read_bytes()).hexdigest()+'  1.webp\n')
            queue=root/'tiles.tsv'
            queue.write_text(RasterTileCoordinate(19,1,1).tsv())
            settings=RasterAssemblySettings('readback',RasterBounds(-180,-85,180,85),19,19,str(root/'webp'))
            mbtiles, archive=root/'raster.mbtiles',root/'raster.pmtiles'
            SqliteRasterTileArchiveAssembler().assemble(str(queue),str(mbtiles),settings)
            ProcessRasterArchive().convert(str(mbtiles),str(archive))
            self.assertEqual(1,ProcessRasterArchiveVerifier().verify(str(archive),str(queue),str(root/'webp'),256))
