import hashlib
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import io
import copy

import yaml

from huavd_map_build.production.south.adapter.process.routeweft import RouteWeftProcess, sha256
from huavd_map_build.production.south.port.routeweft import RouteWeftError
from huavd_map_build.production.north.local.routing import RoutingService, write_json
from huavd_map_build.delivery.north.local.routing import RoutingDelivery, unpack

ROOT = Path(__file__).resolve().parents[2]


def configuration():
    return {'schema': 1, 'regions': {'monaco': {
        'enabled': True, 'profile': 'driving', 'build_timeout_s': 10,
        'verify_timeout_s': 10, 'query_timeout_s': 10,
        'smoke': [
            {'command': 'nearest', 'coordinates': '0,0', 'expect': 'ok'},
            {'command': 'route', 'coordinates': '0,0;0.001,0', 'expect': 'ok',
             'distance_m': [50, 200], 'duration_s': [1, 100]},
            {'command': 'route', 'coordinates': '0,0;0.1,0', 'expect': 'NoRoute'}]}}}


class FakeTool:
    identity = {'binary_sha256': 'a' * 64, 'commit': None}
    def __init__(self):
        self.fail = False
        self.outputs = []
        self.calls = []
        self.blocked = False
    def report(self, arguments):
        return {'valid': True, 'failure_code': None,
                'policy': arguments[arguments.index('--invalid-restrictions') + 1],
                'source_sha256': sha256(Path(arguments[1])), 'source_snapshot': None,
                'nodes': 2, 'edges': 2, 'restrictions': 0, 'diagnostics': {},
                'blocked_way_ids': [42] if self.blocked else [],
                'restriction_diagnostics': [{'relation_id': 99, 'code': 'MissingVia',
                    'action': 'blocked_ways', 'members_truncated': False,
                    'members': [], 'tags': {}}] if self.blocked else []}
    def call(self, command, arguments, timeout, expected_error=None):
        self.calls.append((command, list(arguments)))
        if self.fail:
            raise RouteWeftError('injected failure')
        if command == 'version':
            return {'schema': 1, 'status': 'ok', 'version': '0.1.0', 'cli_schema': 1,
                    'commands': ['build','preflight','inspect','verify','nearest','route','version'],
                    'dataset_formats': [1], 'profiles': ['driving-v1'],
                    'invalid_restriction_policies': ['reject','block_ways']}
        if command == 'preflight':
            return {'schema': 1, 'status': 'ok', 'report': self.report(arguments)}
        if command == 'build':
            output = Path(arguments[arguments.index('--output') + 1])
            assert not output.exists()
            self.outputs.append(output)
            output.mkdir()
            write_json(output / 'graph.json', {'nodes': [{'lon': 0, 'lat': 0}, {'lon': 0.001, 'lat': 0}],
                                               'edges': [{'from': 0, 'to': 1, 'distance_mm': 100000}]})
            manifest = {'dataset_id': 'fixture', 'format': 1, 'profile': 'driving-v1',
                        'source_sha256': sha256(Path(arguments[1])), 'diagnostics': {},
                        'nodes': 2, 'edges': 2, 'restrictions': 0,
                        'source_snapshot': None, 'attribution': 'OSM contributors'}
            write_json(output / 'manifest.json', manifest)
        else:
            manifest = json.loads((Path(arguments[1]) / 'manifest.json').read_text())
        if command in ('build', 'verify', 'inspect'):
            return {'schema': 1, 'status': 'ok', 'verified': True, 'manifest': manifest,
                    **({'report': self.report(arguments)} if command == 'build' else {})}
        if expected_error:
            return {'schema': 1, 'status': 'error', 'error': {'kind': expected_error}}
        identity = {k: manifest[k] for k in ('dataset_id', 'profile', 'format')}
        if command == 'nearest':
            return {'schema': 1, 'status': 'ok', **identity,
                    'matches': [{'point': {'lon': 0, 'lat': 0}, 'distance_m': 0}]}
        return {'schema': 1, 'status': 'ok', 'route': {
            **identity, 'distance_m': 100, 'duration_s': 10,
            'geometry': [{'lon': 0, 'lat': 0}, {'lon': 0.001, 'lat': 0}],
            'legs': [{'distance_m': 100, 'duration_s': 10, 'geometry_start': 0, 'geometry_end': 1}],
            'steps': [], 'snapped': [{'lon': 0, 'lat': 0}, {'lon': 0.001, 'lat': 0}]}}


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='routing tests ')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.config = self.work / 'routing.yaml'
        self.config.write_text(yaml.safe_dump(configuration()))
        self.tool = FakeTool()
        self.service = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019', config=self.config)
        self.input = self.work / 'city input.osm.pbf'
        from huavd_map_build.production.south.adapter.process.routeweft_probe import generate
        generate(self.input)

    def test_build_rebuild_pack_both_and_corruption(self):
        ready = self.service.build(self.input)
        self.assertIsNone(json.loads((self.work / 'outputs/monaco-20261019.routing/fixture/routing-build.json').read_text())['source_snapshot'])
        self.service.build(self.input)
        self.assertNotEqual(*self.tool.outputs)
        self.assertEqual(ready, self.service.verify())
        outputs = RoutingDelivery(self.service).pack('both')
        self.assertEqual(2, len(outputs))
        for output in outputs:
            receipt = json.loads(Path(output + '.verified.json').read_text())
            self.assertEqual(sha256(Path(output)), receipt['sha256'])
        dataset, _, _ = self.service.current()
        (dataset / 'graph.json').write_text('corrupt')
        with self.assertRaises(RouteWeftError):
            self.service.verify()

    def test_failed_rebuild_keeps_ready(self):
        self.service.build(self.input)
        before = self.service.ready.read_bytes()
        self.tool.fail = True
        with self.assertRaises(RouteWeftError):
            self.service.build(self.input)
        self.assertEqual(before, self.service.ready.read_bytes())
        self.tool.fail = False
        self.service.verify()

    def test_ready_identity_and_root_symlink_rejected(self):
        self.service.build(self.input)
        ready = json.loads(self.service.ready.read_text())
        ready['region'] = 'other'
        write_json(self.service.ready, ready)
        with self.assertRaisesRegex(RouteWeftError, 'schema/region'):
            self.service.verify()
        from huavd_map_build.production.north.local.routing import file_records
        link = self.work / 'dataset-link'
        link.symlink_to(self.work / 'outputs', target_is_directory=True)
        with self.assertRaises(RouteWeftError):
            file_records(link)

    def test_reviewed_source_hash_required_when_configured(self):
        self.service.config['source_sha256'] = '0' * 64
        with self.assertRaisesRegex(RouteWeftError, 'reviewed regional snapshot'):
            self.service.build(self.input)
        self.assertFalse(self.service.ready.exists())

    def test_concurrent_session_rejected(self):
        with self.service.locked():
            with self.assertRaisesRegex(RouteWeftError, 'busy'):
                self.service.build(self.input)

    def test_source_mutation_prevents_ready(self):
        original = self.tool.call
        def mutate(command, args, timeout, expected_error=None):
            value = original(command, args, timeout, expected_error)
            if command == 'build':
                frozen = Path(args[1])
                frozen.chmod(0o644)
                frozen.write_bytes(b'mutated')
            return value
        self.tool.call = mutate
        with self.assertRaisesRegex(RouteWeftError, 'frozen input'):
            self.service.build(self.input)
        self.assertFalse(self.service.ready.exists())

    def test_disabled_profile_session_rejected(self):
        default = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019')
        self.assertTrue(default.automatic_smoke)
        with self.assertRaises(RouteWeftError):
            RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019', 'monaco-20261018', self.config)

    def test_missing_tool_receipt_explains_installation_in_actual_workdir(self):
        from huavd_map_build.production.south.adapter.process.routeweft_tools import tool
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RouteWeftError) as caught:
                tool(ROOT, self.work)
        message = str(caught.exception)
        self.assertIn('receipt not found:', message)
        self.assertIn(f'make setup-routeweft WORKDIR="{self.work.resolve()}"', message)

    def test_region_only_build_verify_and_package(self):
        service = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019')
        service.build(self.input)
        result = service.verify(smoke=True)
        self.assertEqual('graph-edge-v1', result['mode'])
        self.assertEqual(['nearest', 'route'], [q['command'] for q in result['queries']])
        self.assertEqual(2, len(RoutingDelivery(service).pack('both')))

    def test_automatic_query_requires_a_usable_graph_edge(self):
        dataset = self.work / 'empty-dataset'
        dataset.mkdir()
        write_json(dataset / 'graph.json', {'nodes': [], 'edges': []})
        with self.assertRaisesRegex(RouteWeftError, 'no suitable edge'):
            RoutingService._automatic_queries(dataset)

    def test_region_only_rejects_unknown_map_region(self):
        with self.assertRaises((ValueError, KeyError)) as caught:
            RoutingService(self.tool, ROOT, self.work, 'not/a-configured-region', '20261019')
        self.assertIn('region', str(caught.exception).lower())

    def test_preflight_never_publishes_and_build_retains_audit(self):
        result = self.service.preflight(self.input)
        self.assertTrue(result['report']['valid'])
        self.assertFalse(self.service.ready.exists())
        self.assertFalse(self.tool.outputs)
        self.assertEqual(['version', 'preflight'], [cmd for cmd, _ in self.tool.calls])
        self.service.build(self.input)
        dataset, _, _ = self.service.current()
        receipt = json.loads((dataset / 'routing-build.json').read_text())
        self.assertEqual(receipt['preflight']['report'], receipt['build_result']['report'])
        self.assertEqual('reject', receipt['invalid_restrictions'])

    def test_preflight_failure_and_mismatched_build_report_stop_publication(self):
        original = self.tool.call
        def altered(command, args, timeout, expected_error=None):
            value = original(command, args, timeout, expected_error)
            if command == 'preflight':
                value['report']['valid'] = False
            return value
        self.tool.call = altered
        with self.assertRaises(RouteWeftError):
            self.service.build(self.input)
        self.assertFalse(self.tool.outputs)
        self.assertFalse(self.service.ready.exists())
        def mismatch(command, args, timeout, expected_error=None):
            value = original(command, args, timeout, expected_error)
            if command == 'build':
                value['report']['nodes'] += 1
            return value
        self.tool.call = mismatch
        with self.assertRaisesRegex(RouteWeftError, 'report/manifest'):
            self.service.build(self.input)
        self.assertFalse(self.service.ready.exists())

    def test_block_ways_requires_explicit_review_and_exact_audit(self):
        config = configuration()
        settings = config['regions']['monaco']
        settings['invalid_restrictions'] = 'block_ways'
        self.config.write_text(yaml.safe_dump(config))
        with self.assertRaisesRegex(RouteWeftError, 'restriction_review'):
            RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019', config=self.config)
        settings.update(source_sha256=sha256(self.input), restriction_review={
            'reason': 'Reviewed synthetic invalid restriction', 'blocked_way_ids': [42],
            'diagnostics': [{'relation_id': 99, 'code': 'MissingVia'}]})
        self.config.write_text(yaml.safe_dump(config))
        service = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019', config=self.config)
        with self.assertRaisesRegex(RouteWeftError, 'differs from reviewed'):
            service.build(self.input)
        self.tool.blocked = True
        service.build(self.input)
        service.verify()
        for command, args in self.tool.calls:
            if command in ('preflight', 'build'):
                self.assertEqual('block_ways', args[args.index('--invalid-restrictions') + 1])

    def test_query_budget_can_be_narrowed_for_reviewed_no_route(self):
        self.service.config['query_budget'] = {'radius-m': 50, 'timeout-ms': 1000}
        self.service.config['smoke'][-1]['query_budget'] = {'radius-m': 0.01}
        self.service.build(self.input)
        route_args = [args for command, args in self.tool.calls if command == 'route'][-1]
        self.assertEqual('0.01', route_args[route_args.index('--radius-m') + 1])


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cli spaces ')
        self.addCleanup(self.temp.cleanup)
        self.binary = Path(self.temp.name) / 'fake cli'

    def process(self, body, limit=4096):
        self.binary.write_text('#!/usr/bin/env python3\n' + body)
        self.binary.chmod(0o755)
        return RouteWeftProcess(self.binary, sha256(self.binary), limit=limit)

    def test_protocol_fault_matrix(self):
        cases = ["print('not-json')", "print('{}')",
                 "print('{\"schema\":2,\"schema\":1,\"status\":\"ok\"}')",
                 "print('{\"schema\":2,\"status\":\"ok\"}')",
                 "print('{\"schema\":1,\"status\":\"error\"}')",
                 "import sys; print('{\"schema\":1,\"status\":\"ok\"}'); sys.exit(4)",
                 "import os,signal; os.kill(os.getpid(),signal.SIGTERM)",
                 "print('x'*10000)", "import time; time.sleep(10)"]
        for body in cases:
            with self.subTest(body=body):
                process = self.process(body)
                with self.assertRaises(RouteWeftError):
                    process.call('verify', ['--dataset', '/path with spaces/$(touch nope)'], .2)
                self.assertTrue(process.logs)

    def test_exact_expected_error_and_success(self):
        process = self.process("import sys; print('{\"schema\":1,\"status\":\"error\",\"error\":{\"kind\":\"NoRoute\"}}'); sys.exit(3)")
        process.call('route', [], 2, 'NoRoute')
        with self.assertRaises(RouteWeftError):
            process.call('route', [], 2, 'NoSegment')
        process = self.process("import sys,json; print(json.dumps({'schema':1,'status':'ok','args':sys.argv[1:]}))")
        self.assertEqual(['build', '--input', 'a b;$(false)'], process.call('build', ['--input', 'a b;$(false)'], 2)['args'])

    def test_binary_identity(self):
        process = self.process("print('{}')")
        with self.assertRaises(RouteWeftError):
            RouteWeftProcess(self.binary, '0' * 64)
        self.binary.write_text('changed')
        with self.assertRaises(RouteWeftError):
            process.call('verify', [], 1)

    def test_structured_failure_details_are_preserved(self):
        value = {'schema': 1, 'status': 'error', 'error': {'kind': 'InvalidDataset',
                 'details': {'failure_code': 'InvalidRestriction', 'restriction_diagnostics': [
                     {'relation_id': 99, 'code': 'MissingVia'}]}}}
        process = self.process('import sys,json; print(json.dumps(' + repr(value) + ')); sys.exit(4)')
        with self.assertRaises(RouteWeftError) as caught:
            process.call('preflight', [], 2)
        self.assertEqual(value, caught.exception.response)
        self.assertEqual(4, caught.exception.exit_code)
        self.assertEqual('preflight', caught.exception.command)


class ContractTests(unittest.TestCase):
    def test_incompatible_capabilities_are_rejected(self):
        from huavd_map_build.production.south.adapter.process.routeweft_contract import capabilities
        baseline = FakeTool().call('version', [], 1)
        mutations = [('cli_schema', 2), ('dataset_formats', [True]),
                     ('profiles', ['driving']), ('commands', ['build']),
                     ('invalid_restriction_policies', ['reject'])]
        for key, value in mutations:
            with self.subTest(key=key):
                tool = FakeTool()
                response = copy.deepcopy(baseline)
                response[key] = value
                tool.call = lambda *args: response
                with self.assertRaises(RouteWeftError):
                    capabilities(tool)

    def test_invalid_reports_fail_closed(self):
        from huavd_map_build.production.south.adapter.process.routeweft_contract import build_report
        baseline = {'valid': True, 'failure_code': None, 'policy': 'reject',
                    'source_sha256': 'a' * 64, 'source_snapshot': None,
                    'nodes': 2, 'edges': 2, 'restrictions': 0, 'diagnostics': {},
                    'blocked_way_ids': [], 'restriction_diagnostics': []}
        for key, value in [('valid', False), ('source_sha256', 'b' * 64),
                           ('policy', 'block_ways'), ('diagnostics', {'count': -1}),
                           ('nodes', True), ('blocked_way_ids', [42]),
                           ('restriction_diagnostics', [{'relation_id': 99, 'code': 'MissingVia',
                             'action': 'blocked_ways', 'members_truncated': True}])]:
            with self.subTest(key=key):
                report = copy.deepcopy(baseline)
                report[key] = value
                with self.assertRaises(RouteWeftError):
                    build_report({'report': report}, 'a' * 64, 'reject')


class ArchiveTests(unittest.TestCase):
    def test_tar_links_traversal_duplicates_and_budget(self):
        for case in ('../escape', '/absolute', 'duplicate', 'link', 'budget'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                archive = Path(temp) / 'evil.tar.gz'
                with tarfile.open(archive, 'w:gz') as stream:
                    entry = tarfile.TarInfo(case)
                    entry.size = 2
                    if case == 'link':
                        entry.type = tarfile.SYMTYPE
                        entry.linkname = '/etc/passwd'
                    stream.addfile(entry, io.BytesIO(b'xx'))
                    if case == 'duplicate':
                        stream.addfile(entry, io.BytesIO(b'xx'))
                with self.assertRaises(RouteWeftError):
                    unpack(archive, Path(temp) / 'out', max_bytes=1 if case == 'budget' else 100)

    def test_zip_link(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'evil.zip'
            with zipfile.ZipFile(archive, 'w') as stream:
                entry = zipfile.ZipInfo('link')
                entry.external_attr = 0o120777 << 16
                stream.writestr(entry, '/etc/passwd')
            with self.assertRaises(RouteWeftError):
                unpack(archive, Path(temp) / 'out')


class ProvenanceTests(unittest.TestCase):
    def test_header_timestamp_unknown_and_corruption(self):
        from huavd_map_build.production.south.adapter.process.routeweft_input import provenance
        from huavd_map_build.production.south.adapter.process.routeweft_probe import block, blob, number, generate
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input.pbf'
            generate(path)
            self.assertIsNone(provenance(path)['replication_timestamp'])
            path.write_bytes(block('OSMHeader', blob(4, b'OsmSchema-V0.6') + number(32, 1785788496) + number(33, 743)))
            self.assertEqual({'replication_timestamp': '2026-08-03T20:21:36Z', 'replication_sequence': 743}, provenance(path))
            path.write_bytes(b'broken')
            with self.assertRaises(RouteWeftError):
                provenance(path)


@unittest.skipUnless(os.environ.get('ROUTEWEFT_TEST_BIN'), 'explicit real CLI binary required')
class RealCLITests(unittest.TestCase):
    def test_contract_probe(self):
        from huavd_map_build.production.south.adapter.process.routeweft_tools import doctor
        binary = Path(os.environ['ROUTEWEFT_TEST_BIN'])
        process = RouteWeftProcess(binary, os.environ['ROUTEWEFT_TEST_SHA256'])
        doctor(process)
        from huavd_map_build.production.south.adapter.process.routeweft_probe import generate
        with tempfile.TemporaryDirectory(prefix='real routing ') as temp:
            work = Path(temp)
            input = work / 'input.osm.pbf'
            generate(input)
            config = configuration()
            settings = config['regions']['monaco']
            settings['query_budget'] = {'radius-m': 20, 'timeout-ms': 1000}
            settings['smoke'][0]['coordinates'] = '0.0002,0'
            settings['smoke'][1]['coordinates'] = '0.0002,0;0.0008,0'
            settings['smoke'][2]['coordinates'] = '0.0002,0;0.1002,0'
            settings['smoke'].append({'command': 'route', 'coordinates': '0.0008,0;0.0002,0', 'expect': 'NoRoute'})
            path = work / 'routing.yaml'
            path.write_text(yaml.safe_dump(config))
            service = RoutingService(process, ROOT, work, 'monaco', '20261019', config=path)
            service.build(input)
            service.verify(smoke=True)
            RoutingDelivery(service).pack('both')
            # Production path: same REGION and PBF, no routing configuration.
            automatic = RoutingService(process, ROOT, work / 'automatic', 'monaco', '20261019')
            automatic.build(input)
            self.assertEqual('graph-edge-v1', automatic.verify(smoke=True)['mode'])
            RoutingDelivery(automatic).pack('both')


@unittest.skipUnless(os.environ.get('ROUTEWEFT_TEST_BIN') and os.environ.get('ROUTEWEFT_TEST_NANNING_PBF'),
                     'explicit real CLI and Nanning PBF required')
class RealNanningTests(unittest.TestCase):
    def test_strict_rejection_and_reviewed_audit_delivery(self):
        binary = Path(os.environ['ROUTEWEFT_TEST_BIN'])
        process = RouteWeftProcess(binary, os.environ['ROUTEWEFT_TEST_SHA256'])
        source = Path(os.environ['ROUTEWEFT_TEST_NANNING_PBF']).resolve()
        fixture = ROOT / 'backend/tests/fixtures/routing/nanning-audit.yaml'
        with tempfile.TemporaryDirectory(prefix='real Nanning audit ') as temporary:
            work = Path(temporary)
            strict = yaml.safe_load(fixture.read_text())
            strict['regions']['china/nanning']['invalid_restrictions'] = 'reject'
            strict_path = work / 'strict.yaml'
            strict_path.write_text(yaml.safe_dump(strict))
            service = RoutingService(process, ROOT, work, 'china/nanning', '20260803', config=strict_path)
            with self.assertRaises(RouteWeftError) as caught:
                service.preflight(source)
            detail = caught.exception.response['error']['details']
            self.assertEqual('InvalidRestriction', detail['failure_code'])
            self.assertEqual('MissingVia', detail['restriction_diagnostics'][0]['code'])
            self.assertFalse(service.ready.exists())
            service = RoutingService(process, ROOT, work, 'china/nanning', '20260803', config=fixture)
            service.preflight(source)
            self.assertFalse(service.ready.exists())
            service.build(source)
            service.verify(smoke=True)
            for archive in RoutingDelivery(service).pack('both'):
                extracted = unpack(Path(archive), work / ('unpacked-' + Path(archive).suffix.lstrip('.')))
                package = json.loads((extracted / 'routing-package.json').read_text())
                self.assertEqual('block_ways', package['invalid_restrictions'])
                receipt = json.loads((extracted / 'routing-build.json').read_text())
                report = receipt['build_result']['report']
                self.assertEqual(8, len(report['blocked_way_ids']))
                self.assertEqual(5, len(report['restriction_diagnostics']))
                self.assertEqual(receipt['preflight']['report'], report)
