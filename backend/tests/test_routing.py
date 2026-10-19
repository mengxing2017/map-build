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
    def call(self, command, arguments, timeout, expected_error=None):
        if self.fail:
            raise RouteWeftError('injected failure')
        if command == 'build':
            output = Path(arguments[arguments.index('--output') + 1])
            assert not output.exists()
            self.outputs.append(output)
            output.mkdir()
            (output / 'graph.json').write_text('{}')
            manifest = {'dataset_id': 'fixture', 'format': 1, 'profile': 'driving-v1',
                        'source_sha256': sha256(Path(arguments[1])), 'diagnostics': {},
                        'source_snapshot': None, 'attribution': 'OSM contributors'}
            write_json(output / 'manifest.json', manifest)
        else:
            manifest = json.loads((Path(arguments[1]) / 'manifest.json').read_text())
        if command in ('build', 'verify', 'inspect'):
            return {'schema': 1, 'status': 'ok', 'verified': True, 'manifest': manifest}
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
        with self.assertRaises(RouteWeftError):
            RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019')
        with self.assertRaises(RouteWeftError):
            RoutingService(self.tool, ROOT, self.work, 'monaco', '20261019', 'monaco-20261018', self.config)


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
