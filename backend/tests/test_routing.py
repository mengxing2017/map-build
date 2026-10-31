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
import struct

import yaml

from huavd_map_build.production.south.adapter.process.routeweft import RouteWeftProcess, sha256
from huavd_map_build.production.south.port.routeweft import RouteWeftError
from huavd_map_build.production.north.local.routing import RoutingService, write_json
from huavd_map_build.delivery.north.local.routing import RoutingDelivery, unpack

ROOT = Path(__file__).resolve().parents[2]


def configuration():
    return {'schema': 1, 'regions': {'monaco': {
        'enabled': True, 'profile': 'driving',
        'smoke': [
            {'command': 'nearest', 'coordinates': '0,0', 'expect': 'ok'},
            {'command': 'route', 'coordinates': '0,0;0.001,0', 'expect': 'ok',
             'distance_m': [50, 200], 'duration_s': [1, 100]},
            {'command': 'route', 'coordinates': '0,0;0.1,0', 'expect': 'NoRoute'}]}}}


def fake_plan(manifest, independent=False):
    estimate = {'estimated_bytes': 1024, 'nodes_bytes': 512, 'edges_bytes': 512,
                'restriction_bytes': 0, 'strings_bytes': 0, 'dictionary_bytes': 0}
    return {'schema': 1, 'estimator_version': 1,
            'estimate_kind': 'conservative_logical_allocations_not_rss',
            **{k: manifest[k] for k in ('dataset_id', 'graph_sha256', 'source_sha256', 'format')},
            'counts': {k: manifest[k] for k in ('nodes', 'edges', 'restrictions', 'graph_bytes')},
            'dataset_load': estimate, 'engine_load': estimate,
            'effective_load_options': {'max_bytes': 2147483648, 'max_nodes': 8000000,
                'max_edges': 16000000, 'max_restriction_edges': 1000000, 'max_resident_bytes': 2147483648},
            'included': ['graph'], 'excluded_unknown': ['query_workspace'],
            'verification_scope': ('full_streaming_v2' if manifest['format'] == 2 else
                                   'identity_size_hash_v1_not_semantic') if independent else 'published_manifest',
            'validation_workspace_budget_bytes': 67108864 if independent else None}


class FakeTool:
    identity = {'binary_sha256': 'a' * 64, 'commit': None}
    def __init__(self):
        self.fail = False
        self.outputs = []
        self.calls = []
        self.blocked = False
        self.speed_audit = []
    def report(self, arguments):
        speed_policy = arguments[arguments.index('--invalid-maxspeed') + 1] if '--invalid-maxspeed' in arguments else 'reject'
        counts = {'maxspeed_policy_use_default': 1} if speed_policy == 'use_default' else {}
        counts.update(invalid_restrictions_blocked=int(self.blocked),
                      invalid_restriction_ways_blocked=int(self.blocked))
        if self.speed_audit:
            counts['maxspeed_fallback_values'] = len(self.speed_audit)
        report = {'valid': True, 'failure_code': None,
                'maxspeed_policy': speed_policy, 'maxspeed_diagnostics': self.speed_audit,
                'policy': arguments[arguments.index('--invalid-restrictions') + 1],
                'source_sha256': sha256(Path(arguments[1])), 'source_snapshot': None,
                'nodes': 2, 'edges': 2, 'restrictions': 0, 'diagnostics': counts,
                'blocked_way_ids': [42] if self.blocked else [],
                'restriction_diagnostics': [{'relation_id': 99, 'code': 'MissingVia',
                    'action': 'blocked_ways', 'members_truncated': False,
                    'members': [{'kind': 'way', 'id': 42, 'role': 'from'}], 'tags': {}}] if self.blocked else []}
        if report['policy'] == 'quarantine_ways':
            counts['quarantine_ways_policy_v1'] = 1
            report.update(planned_blocked_way_ids=report['blocked_way_ids'],
                          applied_blocked_way_ids=report['blocked_way_ids'], blockways_failure=None)
            for item in report['restriction_diagnostics']:
                item['attempt'] = 1
            serialized = [json.dumps(item, ensure_ascii=False, separators=(',', ':')).encode()
                          for item in report['restriction_diagnostics']]
            report['restriction_audit'] = {
                'attempt': 1, 'attempts_completed': 1, 'scan_complete': True, 'truncated': False,
                'records_observed': len(serialized), 'records_retained': len(serialized),
                'retained_bytes': sum(map(len, serialized)), 'retained_memory_bytes': len(serialized)*1024,
                'limits': {'max_diagnostics': 4096, 'max_audit_bytes': 16777216,
                           'max_blockways_attempts': 64}}
        return report
    def call(self, command, arguments, timeout, expected_error=None):
        self.calls.append((command, list(arguments)))
        if self.fail:
            raise RouteWeftError('injected failure')
        if command == 'version':
            return {'schema': 1, 'status': 'ok', 'version': '0.1.0', 'cli_schema': 1,
                    'commands': ['build','preflight','inspect','verify','nearest','route','version','coverage','resource-plan'],
                    'dataset_formats': [1, 2], 'profiles': ['driving-v1'],
                    'capabilities': {'resource_plan': {'schema': 1, 'estimator_version': 1,
                                        'command': 'resource-plan', 'build_output': True, 'query_indexes_constructed': False},
                                     'limits': {'input_bytes': 536870912},
                                     'external_decode_limits': {'input_bytes': 536870912},
                                     'build_modes': ['memory', 'external'], 'external_build_formats': [2],
                                     'graph_capacity_profiles': {'city': {'bytes': 268435456}, 'regional': {'bytes': 2147483648}}},
                    'invalid_restriction_policies': ['reject','block_ways','quarantine_ways'],
                    'invalid_maxspeed_policies': ['reject', 'use_default']}
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
                        'source_sha256': sha256(Path(arguments[1])), 'diagnostics': self.report(arguments)['diagnostics'],
                        'nodes': 2, 'edges': 2, 'restrictions': 0,
                        'source_snapshot': None, 'attribution': 'OSM contributors'}
            if '--builder' in arguments:
                manifest['format'] = 2
                (output / 'graph.json').unlink()
                (output / 'graph.bin').write_bytes(
                    struct.pack('<8s7Q', b'RWFTG002', 0, 2, 1, 0, 0, 0, 0)
                    + struct.pack('<4d', 0, 0, 0.001, 0)
                    + struct.pack('<QQqQQIIQ', 0, 1, 42, 100000, 10000, 0, 0, 0))
            graph = output / ('graph.bin' if manifest['format'] == 2 else 'graph.json')
            manifest.update(graph_sha256=sha256(graph), graph_bytes=graph.stat().st_size)
            write_json(output / 'manifest.json', manifest)
        else:
            manifest = json.loads((Path(arguments[1]) / 'manifest.json').read_text())
        if command == 'resource-plan':
            return {'schema': 1, 'status': 'ok', 'resource_plan': fake_plan(manifest, independent=True)}
        if command in ('build', 'verify', 'inspect'):
            return {'schema': 1, 'status': 'ok', 'verified': True, 'manifest': manifest,
                    **({'resource_plan': fake_plan(manifest), 'report': self.report(arguments), 'build': {'builder': 'external' if '--builder' in arguments else 'memory'}} if command == 'build' else {})}
        if expected_error:
            return {'schema': 1, 'status': 'error', 'error': {'kind': expected_error}}
        identity = {k: manifest[k] for k in ('dataset_id', 'profile', 'format')}
        if command == 'coverage':
            return {'schema': 1, 'status': 'ok', **identity,
                    'coverage': {'nodes': manifest['nodes'], 'edges': manifest['edges'],
                                 'excluded_way_edges': 0}}
        if command == 'nearest':
            return {'schema': 1, 'status': 'ok', **identity,
                    'matches': [{'point': {'lon': 0, 'lat': 0}, 'distance_m': 0}]}
        return {'schema': 1, 'status': 'ok', 'route': {
            **identity, 'distance_m': 100, 'duration_s': 10,
            'geometry': [{'lon': 0, 'lat': 0}, {'lon': 0.001, 'lat': 0}],
            'legs': [{'distance_m': 100, 'duration_s': 10, 'geometry_start': 0, 'geometry_end': 1}],
            'steps': [], 'snapped': [{'lon': 0, 'lat': 0}, {'lon': 0.001, 'lat': 0}]}}


class RegionCatalogRoutingTests(unittest.TestCase):
    def test_production_config_is_independent_of_snapshot_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = [RoutingService(FakeTool(), ROOT, Path(tmp), 'china/guangxi', day,
                                       invalid_maxspeed='reject')
                        for day in ('20260803', '20260804')]
            self.assertEqual(services[0].config_sha256, services[1].config_sha256)
            for service in services:
                self.assertEqual(service.policy, 'quarantine_ways')
                self.assertEqual(service.maxspeed_policy, 'reject')
                self.assertTrue(service.automatic_smoke)
                self.assertNotIn('source_sha256', service.config)
                self.assertIsNone(service.review)


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
        verified = self.service.verify()
        self.assertEqual(ready['dataset_id'], verified['dataset_id'])
        self.assertEqual(ready['files'], verified['files'])
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
        with patch.dict(os.environ, {'HUAVD_TOOLS_DIR': str(self.work / 'empty-project-tools')}, clear=True):
            with self.assertRaises(RouteWeftError) as caught:
                tool(ROOT, self.work)
        message = str(caught.exception)
        self.assertIn('receipt not found:', message)
        self.assertIn('make setup-routeweft in the project', message)

    def test_region_only_build_verify_and_package(self):
        service = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019')
        service.build(self.input)
        result = service.verify(smoke=True)
        self.assertEqual('graph-edge-v1', result['mode'])
        self.assertEqual(['nearest', 'route'], [q['command'] for q in result['queries']])
        self.assertEqual(2, len(RoutingDelivery(service).pack('both')))

    def test_external_preflight_build_audit_and_rebuild(self):
        service = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019')
        result = service.preflight(self.input)
        self.assertEqual('external-build-validation', result['mode'])
        self.assertFalse(service.ready.exists())
        service.build(self.input)
        service.build(self.input)
        dataset, manifest, ready = service.current()
        self.assertEqual(2, manifest['format'])
        self.assertNotIn('preflight', [cmd for cmd, _ in self.tool.calls])
        for cmd, args in self.tool.calls:
            if cmd in ('build', 'verify', 'inspect', 'nearest', 'route'):
                self.assertEqual('regional', args[args.index('--graph-capacity') + 1])
            if cmd in ('nearest', 'route'):
                self.assertIn('--max-load-bytes', args)
        receipt = json.loads((dataset / 'routing-build.json').read_text())
        self.assertEqual({'mode': 'external-build-validation'}, receipt['preflight'])
        receipt['preflight'] = {'report': receipt['build_result']['report']}
        write_json(dataset / 'routing-build.json', receipt)
        from huavd_map_build.production.north.local.routing import file_records
        ready['files'] = file_records(dataset)
        write_json(service.ready, ready)
        with self.assertRaisesRegex(RouteWeftError, 'external build audit'):
            service.verify()

    def test_external_failure_preserves_ready(self):
        service = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019')
        service.build(self.input)
        before = service.ready.read_bytes()
        original = self.tool.call
        def failed(command, args, timeout, expected_error=None):
            if command == 'build':
                raise RouteWeftError('external budget exceeded')
            return original(command, args, timeout, expected_error)
        self.tool.call = failed
        with self.assertRaisesRegex(RouteWeftError, 'external budget'):
            service.build(self.input)
        self.assertEqual(before, service.ready.read_bytes())

    def test_v2_sampler_rejects_truncation_and_invalid_node(self):
        from huavd_map_build.production.south.adapter.process.routeweft_graph import sample_edges
        service = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019')
        service.build(self.input)
        dataset, _, _ = service.current()
        path = dataset / 'graph.bin'
        payload = path.read_bytes()
        path.write_bytes(payload[:-1])
        with self.assertRaisesRegex(RouteWeftError, 'sample header'):
            list(sample_edges(dataset))
        corrupted = bytearray(payload)
        struct.pack_into('<Q', corrupted, 64 + 32, 2)
        path.write_bytes(corrupted)
        with self.assertRaisesRegex(RouteWeftError, 'sample node'):
            list(sample_edges(dataset))

    def test_external_capability_missing_stops_before_build(self):
        service = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019')
        original = self.tool.call
        def missing(command, args, timeout, expected_error=None):
            result = original(command, args, timeout, expected_error)
            if command == 'version':
                result['capabilities'].pop('build_modes')
            return result
        self.tool.call = missing
        with self.assertRaisesRegex(RouteWeftError, 'external/v2'):
            service.build(self.input)
        self.assertFalse(self.tool.outputs)
        self.assertFalse(service.ready.exists())

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

    def test_block_ways_accepts_business_policy_and_enforces_optional_review(self):
        config = configuration()
        settings = config['regions']['monaco']
        settings['invalid_restrictions'] = 'block_ways'
        self.config.write_text(yaml.safe_dump(config))
        general = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019', config=self.config)
        self.tool.blocked = True
        general.build(self.input)
        general.verify()
        self.tool.blocked = False
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

    def test_speed_policy_configuration_and_ready_cannot_be_reused(self):
        with patch.dict(os.environ, {'ROUTING_INVALID_MAXSPEED': 'use_default'}):
            service = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019')
        self.assertEqual('use_default', service.maxspeed_policy)
        config = configuration()
        config['regions']['monaco']['invalid_maxspeed'] = 'reject'
        self.config.write_text(yaml.safe_dump(config))
        with patch.dict(os.environ, {'ROUTING_INVALID_MAXSPEED': 'use_default'}):
            configured = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019', config=self.config)
            overridden = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019',
                                        config=self.config, invalid_maxspeed='use_default')
        self.assertEqual('reject', configured.maxspeed_policy)
        self.assertEqual('use_default', overridden.maxspeed_policy)
        self.tool.speed_audit = [{'way_id': 42, 'field': 'maxspeed', 'value': '辅路',
                                 'action': 'use_default', 'effective_kmh': 30.0}]
        service.build(self.input)
        dataset, _, ready = service.current()
        self.assertEqual(self.tool.speed_audit, ready['maxspeed_diagnostics'])
        strict = RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019', invalid_maxspeed='reject')
        self.assertNotEqual(service.config_sha256, strict.config_sha256)
        with self.assertRaisesRegex(RouteWeftError, 'maxspeed policy'):
            strict.verify()
        for archive in RoutingDelivery(service).pack('both'):
            destination = unpack(Path(archive), self.work / Path(archive).suffix)
            package = json.loads((destination / 'routing-package.json').read_text())
            self.assertEqual('use_default', package['invalid_maxspeed'])
            self.assertEqual(self.tool.speed_audit, package['maxspeed_diagnostics'])
        ready.pop('maxspeed_diagnostics')
        write_json(service.ready, ready)
        with self.assertRaisesRegex(RouteWeftError, 'maxspeed audit'):
            service.verify()
        with self.assertRaisesRegex(RouteWeftError, 'maxspeed policy'):
            RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019', invalid_maxspeed='ignore')

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
    def test_embedded_identity_matches_locked_commit_and_rejects_untrusted_builds(self):
        from huavd_map_build.production.south.adapter.process.routeweft_contract import capabilities
        tool = FakeTool()
        tool.identity = {'commit': 'a' * 40}
        tool.require_build_identity = True
        response = copy.deepcopy(tool.call('version', [], 1))
        tool.call = lambda *args: response
        with self.assertRaisesRegex(RouteWeftError, 'missing embedded'):
            capabilities(tool)
        valid = {'git_commit': 'a' * 40, 'source_dirty': False, 'release_eligible': True,
                 'source_identity_kind': 'git', 'target': 'test-target',
                 'profile': 'release', 'rustc': 'rustc test'}
        response['build'] = valid.copy()
        self.assertEqual(valid, capabilities(tool)['build'])
        for key, value in [('git_commit', 'b' * 40), ('git_commit', 'unknown'),
                           ('source_dirty', True), ('source_dirty', None),
                           ('release_eligible', False), ('source_identity_kind', 'unknown'),
                           ('target', None)]:
            with self.subTest(key=key, value=value):
                response['build'] = {**valid, key: value}
                with self.assertRaises(RouteWeftError):
                    capabilities(tool)
        # Explicit digest overrides have no lock commit, but still require a clean identity.
        tool.identity = {'commit': None}
        response['build'] = valid.copy()
        capabilities(tool)
        response['build']['source_dirty'] = True
        with self.assertRaises(RouteWeftError):
            capabilities(tool)

    def test_incompatible_capabilities_are_rejected(self):
        from huavd_map_build.production.south.adapter.process.routeweft_contract import capabilities
        baseline = FakeTool().call('version', [], 1)
        mutations = [('cli_schema', 2), ('dataset_formats', [True]),
                     ('profiles', ['driving']), ('commands', ['build']),
                     ('invalid_restriction_policies', ['reject']),
                     ('invalid_maxspeed_policies', ['reject'])]
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
                    'blocked_way_ids': [], 'restriction_diagnostics': [],
                    'maxspeed_policy': 'reject', 'maxspeed_diagnostics': []}
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

    def test_general_restriction_audit_rejects_incomplete_or_unaccounted_data(self):
        from huavd_map_build.production.south.adapter.process.routeweft_contract import build_report
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'input'
            source.write_bytes(b'fixture')
            tool = FakeTool()
            tool.blocked = True
            report = tool.report(['--input', str(source), '--invalid-restrictions', 'block_ways'])
            build_report({'report': report}, sha256(source), 'block_ways')
            mutations = [
                lambda r: r['diagnostics'].update(invalid_restrictions_blocked=2),
                lambda r: r['diagnostics'].update(invalid_restriction_ways_blocked=0),
                lambda r: r['restriction_diagnostics'][0].update(members_truncated=True),
                lambda r: r['restriction_diagnostics'][0].update(members=[]),
                lambda r: r.update(blocked_way_ids=[100]),
                lambda r: r['restriction_diagnostics'].append(r['restriction_diagnostics'][0]),
            ]
            for mutate in mutations:
                invalid = copy.deepcopy(report)
                mutate(invalid)
                with self.assertRaises(RouteWeftError):
                    build_report({'report': invalid}, sha256(source), 'block_ways')

    def test_speed_audit_is_complete_and_matches_manifest_counts(self):
        from huavd_map_build.production.south.adapter.process.routeweft_contract import build_report
        entry = {'way_id': 42, 'field': 'maxspeed:forward', 'value': '辅路',
                 'action': 'use_default', 'effective_kmh': 20.0}
        report = {'valid': True, 'failure_code': None, 'policy': 'reject',
                  'source_sha256': 'a' * 64, 'source_snapshot': None,
                  'nodes': 2, 'edges': 2, 'restrictions': 0,
                  'diagnostics': {'maxspeed_policy_use_default': 1, 'maxspeed_fallback_values': 1},
                  'blocked_way_ids': [], 'restriction_diagnostics': [],
                  'maxspeed_policy': 'use_default', 'maxspeed_diagnostics': [entry]}
        build_report({'report': report}, 'a' * 64, 'reject', maxspeed_policy='use_default')
        mutations = [dict(maxspeed_policy='reject'), dict(maxspeed_diagnostics=None),
                     dict(maxspeed_diagnostics=[]), dict(diagnostics={'maxspeed_fallback_values': 1}),
                     dict(maxspeed_diagnostics=[entry, entry]),
                     dict(maxspeed_diagnostics=[{**entry, 'effective_kmh': float('nan')}]),
                     dict(maxspeed_diagnostics=[{**entry, 'value': 'a' * 65536}]),
                     dict(maxspeed_diagnostics=[{**entry, 'action': 'rejected'}])]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(RouteWeftError):
                    build_report({'report': {**report, **mutation}}, 'a' * 64, 'reject', maxspeed_policy='use_default')
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
    def test_real_maxspeed_reject_fallback_directional_and_pack(self):
        from huavd_map_build.production.south.adapter.process.routeweft_probe import generate
        process = RouteWeftProcess(Path(os.environ['ROUTEWEFT_TEST_BIN']), os.environ['ROUTEWEFT_TEST_SHA256'])
        with tempfile.TemporaryDirectory(prefix='real speed audit ') as temp:
            root = Path(temp)
            source = root / 'input.osm.pbf'
            generate(source, maxspeed='辅路')
            strict = RoutingService(process, ROOT, root / 'strict', 'monaco', '20261019',
                                    invalid_maxspeed='reject')
            with self.assertRaises(RouteWeftError) as caught:
                strict.build(source)
            self.assertEqual('InvalidMaxspeed', caught.exception.response['error']['details']['failure_code'])
            self.assertFalse(strict.ready.exists())
            failure = next(strict.workdir.glob('staging/routing/*/failure.json'))
            self.assertEqual('reject', json.loads(failure.read_text())['invalid_maxspeed'])
            fallback = RoutingService(process, ROOT, root / 'fallback', 'monaco', '20261019',
                                      invalid_maxspeed='use_default')
            fallback.build(source)
            dataset, manifest, ready = fallback.current()
            self.assertEqual(2, manifest['diagnostics']['maxspeed_fallback_values'])
            self.assertEqual({'辅路'}, {e['value'] for e in ready['maxspeed_diagnostics']})
            for archive in RoutingDelivery(fallback).pack('both'):
                out = unpack(Path(archive), root / Path(archive).suffix)
                package = json.loads((out / 'routing-package.json').read_text())
                self.assertEqual(ready['maxspeed_diagnostics'], package['maxspeed_diagnostics'])
            generate(source, maxspeed='20', forward='辅路', backward='10 mph')
            directional = RoutingService(process, ROOT, root / 'directional', 'monaco', '20261019',
                                         invalid_maxspeed='use_default')
            directional.build(source)
            dataset, manifest, ready = directional.current()
            self.assertTrue(ready['maxspeed_diagnostics'])
            for item in ready['maxspeed_diagnostics']:
                self.assertEqual('maxspeed:forward', item['field'])
                self.assertEqual(20, item['effective_kmh'])
            payload = (dataset / 'graph.bin').read_bytes()
            _, _, nodes, edges, _, _, _, dictionary = struct.unpack_from('<8s7Q', payload)
            speeds = []
            for index in range(edges):
                source_id, target, way, distance, duration, *_ = struct.unpack_from(
                    '<QQqQQIIQ', payload, 64 + dictionary + 16 * nodes + index * 56)
                if way == 20:
                    speeds.append(distance / duration * 3.6)
            self.assertEqual(2, len(speeds))
            self.assertAlmostEqual(16.09344, min(speeds), delta=0.02)
            self.assertAlmostEqual(20, max(speeds), delta=0.02)
            generate(source)
            payloads = []
            for policy in ('reject', 'use_default'):
                service = RoutingService(process, ROOT, root / ('valid-' + policy), 'monaco', '20261019',
                                         invalid_maxspeed=policy)
                service.build(source)
                dataset, _, ready = service.current()
                self.assertEqual([], ready['maxspeed_diagnostics'])
                payloads.append((dataset / 'graph.bin').read_bytes())
            self.assertEqual(*payloads)

    def test_business_defaults_handle_invalid_speed_and_turns_without_review(self):
        from huavd_map_build.production.south.adapter.process.routeweft_probe import generate
        process = RouteWeftProcess(Path(os.environ['ROUTEWEFT_TEST_BIN']), os.environ['ROUTEWEFT_TEST_SHA256'])
        with tempfile.TemporaryDirectory(prefix='real routing business ') as tmp:
            work = Path(tmp)
            source = work / 'input.osm.pbf'
            generate(source, maxspeed='辅路', invalid_restriction=True)
            strict_config = configuration()
            strict_config['regions']['monaco']['invalid_maxspeed'] = 'use_default'
            strict_path = work / 'strict.yaml'
            strict_path.write_text(yaml.safe_dump(strict_config))
            strict = RoutingService(process, ROOT, work / 'strict', 'monaco', '20261019',
                                    config=strict_path)
            with self.assertRaises(RouteWeftError) as failure:
                strict.build(source)
            self.assertEqual('InvalidRestriction', failure.exception.response['error']['details']['failure_code'])
            self.assertFalse(strict.ready.exists())
            service = RoutingService(process, ROOT, work, 'monaco', '20261019')
            service.build(source)
            dataset, manifest, ready = service.current()
            self.assertIsNone(service.review)
            self.assertEqual('use_default', service.maxspeed_policy)
            self.assertEqual('quarantine_ways', service.policy)
            self.assertEqual([10], ready['blocked_way_ids'])
            self.assertEqual('MissingVia', ready['restriction_diagnostics'][0]['code'])
            self.assertTrue(ready['maxspeed_diagnostics'])
            self.assertEqual(1, manifest['diagnostics']['invalid_restrictions_blocked'])
            service.verify(smoke=True)
            for archive in RoutingDelivery(service).pack('both'):
                out = unpack(Path(archive), work / ('unpack' + Path(archive).suffix))
                package = json.loads((out / 'routing-package.json').read_text())
                self.assertEqual([10], package['blocked_way_ids'])
                self.assertEqual(ready['restriction_diagnostics'], package['restriction_diagnostics'])
                self.assertTrue(package['coverage_notice'])

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
            self.assertEqual('external-build-validation', automatic.preflight(input)['mode'])
            self.assertFalse(automatic.ready.exists())
            automatic.build(input)
            automatic.build(input)
            self.assertEqual(2, automatic.current()[1]['format'])
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
