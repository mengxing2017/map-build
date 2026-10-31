"""Audit configuration across Make, CLI, lifecycle and standard bundle delivery."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import yaml

from test_routing import FakeTool, ROOT, configuration
from huavd_map_build import cli
from huavd_map_build.delivery.north.local.bundle import BundleRequest, BundleService
from huavd_map_build.production.north.local.routing import RoutingService
from huavd_map_build.production.south.adapter.process.routeweft import RouteWeftProcess, sha256
from huavd_map_build.production.south.adapter.process.routeweft_probe import generate
from huavd_map_build.production.south.port.routeweft import RouteWeftError
from huavd_map_build.shared.kernel import BuildDate, RegionId, SessionId


class AuditEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='audit entrypoints ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.pbf'
        generate(self.source)
        self.config = self.root / 'audit config.yaml'
        self.config.write_text(yaml.safe_dump(configuration()))
        self.tool = FakeTool()

    def service(self):
        return RoutingService(self.tool, ROOT, self.root, 'monaco', '20261019', config=self.config)

    def test_production_plan_reaches_coverage_and_queries_without_region_budget(self):
        from test_routing import fake_plan
        service = RoutingService(self.tool, ROOT, self.root, 'china/guangdong', '20261030')
        self.assertNotIn('max_load_bytes', service.config)
        service.automatic_smoke = False
        service.config['smoke'] = [{'command': 'nearest', 'coordinates': '0,0', 'expect': 'ok'},
            {'command': 'route', 'coordinates': '0,0;0.001,0', 'expect': 'ok',
             'distance_m': [1, 1000], 'duration_s': [1, 100]}]
        (self.root / 'staging/routing').mkdir(parents=True)
        manifest = {'dataset_id': 'fixture', 'nodes': 2, 'edges': 2, 'restrictions': 0,
                    'profile': 'driving-v1', 'format': 2, 'graph_bytes': 100,
                    'graph_sha256': 'b'*64, 'source_sha256': 'c'*64}
        (self.root / 'manifest.json').write_text(json.dumps(manifest))
        service.smoke(self.root, manifest, excluded=[])
        commands = []
        for command, args in self.tool.calls:
            if command in ('coverage', 'nearest', 'route'):
                commands.append(command)
                self.assertEqual('1024', args[args.index('--max-load-bytes') + 1])
        self.assertEqual(['coverage', 'nearest', 'route'], commands)

    def test_check_does_not_build_or_publish_and_checks_sha(self):
        service = self.service()
        self.assertEqual(sha256(self.source), service.check(self.source)['source_sha256'])
        self.assertEqual(['version'], [cmd for cmd, _ in self.tool.calls])
        self.assertFalse(service.ready.exists())
        service.config['source_sha256'] = '0' * 64
        with self.assertRaisesRegex(RouteWeftError, 'snapshot'):
            service.check(self.source)
        self.assertEqual(2, len(self.tool.calls))

    def test_cli_check_and_relative_config_resolve_from_repository(self):
        relative = Path(os.path.relpath(self.config, ROOT))
        with patch('huavd_map_build.production.south.adapter.process.routeweft_tools.tool', return_value=self.tool):
            with redirect_stdout(io.StringIO()) as output:
                cli.run(['routing', 'check', '--region=monaco', '--yyyymmdd=20261019',
                         '--workdir=' + str(self.root), '--input=' + str(self.source),
                         '--config=' + str(relative)])
        self.assertEqual(sha256(self.source), json.loads(output.getvalue())['source_sha256'])
        self.assertEqual(['version'], [cmd for cmd, _ in self.tool.calls])

    def test_bundle_factory_receives_audit_config(self):
        request = BundleRequest(RegionId('monaco'), BuildDate('20261019'),
                                SessionId('monaco-20261019'), 'base', str(self.root),
                                routing_audit_config=self.config)
        with patch('huavd_map_build.production.south.adapter.process.routeweft_tools.tool', return_value=self.tool):
            service = BundleService._routing_service(request)
        self.assertEqual(self.service().config_sha256, service.config_sha256)

    def test_cli_pack_passes_audit_path_to_request(self):
        outputs = self.root / 'outputs'
        outputs.mkdir()
        session = 'monaco-20261019'
        for suffix in ('glyphs', 'sprite'):
            (outputs / f'{session}.{suffix}').mkdir()
        for suffix in ('style.json', 'style-raster.json'):
            (outputs / f'{session}.{suffix}').write_text('{}')
        bundle = Mock()
        bundle.run.return_value = {}
        with patch.object(cli, 'bundle_service', return_value=bundle), redirect_stdout(io.StringIO()):
            cli.run(['artifact', 'pack', '--region=monaco', '--yyyymmdd=20261019',
                     '--role=base', '--workdir=' + str(self.root),
                     '--routing-audit-config=' + str(self.config),
                     '--resource-config=' + str(ROOT / 'config/build-resources.yaml'),
                     '--memory-ceiling-bytes=21474836480'])
        request = bundle.run.call_args.args[0]
        self.assertEqual(self.config, request.routing_audit_config)
        self.assertEqual(ROOT / 'config/build-resources.yaml', request.resource_config)
        self.assertEqual(21474836480, request.memory_ceiling_bytes)

    def test_make_config_reaches_build_verify_and_pack(self):
        for target, expected in [('build', 'routing check'), ('verify', 'routing verify'),
                                 ('pack', 'artifact pack'), ('pack-tar', 'artifact pack')]:
            result = subprocess.run(['make', '-n', target, 'ROLE=base', 'REGION=monaco',
                                     'ROUTING_AUDIT_CONFIG=' + str(self.config),
                                     'ROUTING_RESOURCE_CONFIG=/tmp/resources.yaml',
                                     'ROUTING_MEMORY_CEILING_BYTES=21474836480'],
                                    cwd=ROOT, capture_output=True, text=True, check=True)
            self.assertIn('--resource-config="/tmp/resources.yaml"', result.stdout)
            self.assertIn('--memory-ceiling-bytes="21474836480"', result.stdout)
            self.assertIn(expected, result.stdout)
            self.assertIn(str(self.config), result.stdout)
            if target == 'build':
                self.assertLess(result.stdout.index('routing check'), result.stdout.index('build execute-vector'))

    def test_failure_summary_keeps_response_and_blocker(self):
        response = {'schema': 1, 'status': 'error', 'error': {'kind': 'InvalidDataset',
            'details': {'source_sha256': sha256(self.source), 'blockways_failure': {
                'relation_id': 5652903, 'reason': 'NoSafeFromToMember', 'attempt': 1,
                'recoverable': False}}}}
        original = self.tool.call
        def fail(command, arguments, timeout, expected_error=None):
            if command == 'build':
                raise RouteWeftError('rejected', response=response, command='build', exit_code=4)
            return original(command, arguments, timeout, expected_error)
        self.tool.call = fail
        service = self.service()
        with self.assertRaisesRegex(RouteWeftError, '核验源关系'):
            service.build(self.source)
        summary = json.loads(next((self.root / 'staging/routing').glob('*/failure-summary.json')).read_text())
        self.assertEqual(5652903, summary['relation_id'])
        self.assertFalse(summary['recoverable'])
        failure = json.loads(Path(summary['evidence']).read_text())
        self.assertEqual(response, failure['response'])
        self.assertFalse(service.ready.exists())


@unittest.skipUnless(os.environ.get('ROUTEWEFT_TEST_BIN'), 'real CLI binary required')
class RealAuditBundleTests(unittest.TestCase):
    def test_standard_bundle_uses_reviewed_config_and_reverifies_archives(self):
        import hashlib
        from test_bundle import _Viewport
        import tarfile
        import zipfile
        with tempfile.TemporaryDirectory(prefix='joint audit ') as tmp:
            root = Path(tmp)
            source = root / 'source.pbf'
            generate(source, invalid_restriction=True, empty_roles=True)
            doc = configuration()
            doc['regions']['monaco'].update(invalid_restrictions='quarantine_ways',
                source_sha256=sha256(source), smoke_mode='graph-edge-v1', smoke=[])
            config = root / 'audit.yaml'
            config.write_text(yaml.safe_dump(doc))
            process = RouteWeftProcess(Path(os.environ['ROUTEWEFT_TEST_BIN']), os.environ['ROUTEWEFT_TEST_SHA256'])
            service = RoutingService(process, ROOT, root, 'monaco', '20261019', config=config)
            service.build(source)
            session = 'monaco-20261019'
            outputs = root / 'outputs'
            stem = session + '.base'
            payload = b'map-fixture'
            digest = hashlib.sha512(payload).hexdigest()
            (outputs / (stem + '.pmtiles')).write_bytes(payload)
            (outputs / (stem + '.pmtiles.sha512')).write_text(digest + '  ' + stem + '.pmtiles\n')
            (outputs / (stem + '.attribution.json')).write_text('{}')
            manifest = {'source': {'sha256': sha256(source)}, 'region': 'monaco',
                'build_id': '2026-10-19T00:00:00Z', 'output': {'sha512': digest,
                'tile_range': {'min_zoom': 0, 'max_zoom': 14, 'bounds': [7, 43, 8, 44]}},
                'huavd_record': {'id': 'monaco-base', 'name': stem, 'source_id': 'osm',
                    'package_version': '20261019.base', 'source_revision': 'fixture',
                    'asset_role': 'base-vector', 'source_type': 'osm-pbf', 'format': 'pmtiles',
                    'coord_system': 'EPSG:3857', 'transport': 'offline', 'style_id': 'osm-dev',
                    'available_locales': ['zh-Hans'], 'style_locales': ['zh-Hans'],
                    'bundle_id': session + '-standard', 'activation': 'manual'}}
            (outputs / (stem + '.manifest.json')).write_text(json.dumps(manifest))
            style = outputs / f'{session}.style.json'
            style.write_text('{}')
            Path(str(style) + '.sha512').write_text(hashlib.sha512(style.read_bytes()).hexdigest())
            glyphs = outputs / f'{session}.glyphs'
            glyphs.mkdir()
            (glyphs / '0-255.pbf').write_bytes(b'glyph')
            sprites = outputs / f'{session}.sprite'
            sprites.mkdir()
            (sprites / 'sprite.json').write_text('{}')
            (sprites / 'sprite.png').write_bytes(b'png')
            request = BundleRequest(RegionId('monaco'), BuildDate('20261019'), SessionId(session),
                                    'base', tmp, routing_audit_config=config)
            # Production factory, real RouteWeft; only map viewport is a fixture.
            with patch('huavd_map_build.production.south.adapter.process.routeweft_tools.tool', return_value=process):
                bundle = BundleService(_Viewport())
                bundle.run(request)
                for suffix in ('tar.gz', 'zip'):
                    extracted = root / suffix
                    extracted.mkdir()
                    archive_path = outputs / f'{session}.bundle.{suffix}'
                    if suffix == 'zip':
                        with zipfile.ZipFile(archive_path) as archive:
                            archive.extractall(extracted)
                    else:
                        with tarfile.open(archive_path) as archive:
                            archive.extractall(extracted, filter='data')
                    for line in (extracted / 'SHA256SUMS').read_text().splitlines():
                        digest, name = line.split('  ', 1)
                        self.assertEqual(digest, sha256(extracted / name))
                    contract = json.loads((extracted / 'package.json').read_text())
                    self.assertEqual('quarantine_ways', contract['routing']['invalid_restrictions'])
                    self.assertTrue(contract['routing']['coverage_notice'])
                    verified = service.verify_dataset(extracted / 'routing', sha256(source))
                    smoke = service.smoke(extracted / 'routing', verified)
                    self.assertEqual(0, smoke['coverage']['coverage']['excluded_way_edges'])
                with self.assertRaisesRegex(RouteWeftError, 'policy mismatch'):
                    bundle.run(BundleRequest(RegionId('monaco'), BuildDate('20261019'),
                                             SessionId(session), 'base', tmp))
