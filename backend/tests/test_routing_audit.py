"""Province-sized audit contracts, budget wiring and bounded process output."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

import yaml

from test_routing import FakeTool, ROOT, configuration
from huavd_map_build.production.north.local.routing import RoutingService
from huavd_map_build.production.south.adapter.process.routeweft import RouteWeftProcess, sha256
from huavd_map_build.production.south.adapter.process.routeweft_contract import build_report
from huavd_map_build.production.south.adapter.process.routeweft_probe import generate
from huavd_map_build.production.south.port.routeweft import RouteWeftError
from huavd_map_build.delivery.north.local.routing import RoutingDelivery, unpack


class AuditCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.pbf'
        generate(self.source)
        self.tool = FakeTool()
        self.tool.blocked = True

    def report(self, count=728):
        report = self.tool.report(['--input', str(self.source), '--invalid-restrictions', 'block_ways'])
        template = report['restriction_diagnostics'][0]
        report['restriction_diagnostics'] = [dict(copy.deepcopy(template), attempt=1, relation_id=i)
                                             for i in range(1, count + 1)]
        report['diagnostics']['invalid_restrictions_blocked'] = count
        report['restriction_audit'] = {
            'attempt': 2, 'attempts_completed': 2, 'scan_complete': True, 'truncated': False,
            'records_observed': count, 'records_retained': count, 'retained_memory_bytes': count * 1024,
            'limits': {'max_diagnostics': 4096, 'max_audit_bytes': 16 * 1024**2,
                       'max_blockways_attempts': 64}}
        self.recount(report)
        return report

    def recount(self, report):
        report['restriction_audit']['retained_bytes'] = sum(
            len(json.dumps(d, ensure_ascii=False, separators=(',', ':')).encode())
            for d in report['restriction_diagnostics'])

    def validate(self, report, **kwargs):
        return build_report({'report': report}, sha256(self.source), 'block_ways', **kwargs)

    def test_complete_province_report_and_cross_attempt_identity(self):
        report = self.report()
        self.validate(report)
        report['restriction_diagnostics'][-1].update(attempt=2, relation_id=1)
        self.recount(report)
        self.validate(report)
        review = {'blocked_way_ids': [42], 'diagnostics': [
            {k: d[k] for k in ('attempt', 'relation_id', 'code')}
            for d in report['restriction_diagnostics']]}
        self.validate(report, review=review)
        review['diagnostics'][-1]['attempt'] = 1
        with self.assertRaisesRegex(RouteWeftError, 'reviewed'):
            self.validate(report, review=review)

    def test_incomplete_forged_and_over_budget_summaries_are_rejected(self):
        cases = [('scan_complete', False), ('truncated', True), ('attempts_completed', 1),
                 ('records_observed', 729), ('records_retained', 727), ('attempt', True),
                 ('attempt', 65), ('retained_bytes', 0), ('retained_memory_bytes', 64 * 1024**2 + 1)]
        for key, value in cases:
            with self.subTest(key=key):
                report = self.report()
                report['restriction_audit'][key] = value
                with self.assertRaises(RouteWeftError):
                    self.validate(report)
        for key, value in [('max_diagnostics', 32769), ('max_diagnostics', 727),
                           ('max_audit_bytes', 16 * 1024**2 + 1), ('max_audit_bytes', 1),
                           ('max_blockways_attempts', 258)]:
            report = self.report()
            report['restriction_audit']['limits'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RouteWeftError):
                self.validate(report)
        report = self.report()
        del report['restriction_audit']
        with self.assertRaises(RouteWeftError):
            self.validate(report)

    def test_duplicate_unordered_and_invalid_attempts_are_rejected(self):
        for mutation in (dict(attempt=0), dict(attempt=3), dict(attempt=True), dict(relation_id=1)):
            report = self.report()
            report['restriction_diagnostics'][1].update(mutation)
            self.recount(report)
            with self.subTest(mutation=mutation), self.assertRaises(RouteWeftError):
                self.validate(report)

    def test_legacy_report_remains_bounded(self):
        report = self.report(256)
        del report['restriction_audit']
        self.validate(report)
        report = self.report(257)
        del report['restriction_audit']
        with self.assertRaises(RouteWeftError):
            self.validate(report)

    def test_new_success_report_requires_applied_plan_and_no_blocker(self):
        report = self.report()
        report.update(planned_blocked_way_ids=[42], applied_blocked_way_ids=[42], blockways_failure=None)
        self.validate(report)
        for mutation in ({'applied_blocked_way_ids': []}, {'planned_blocked_way_ids': [43]},
                         {'blockways_failure': {'reason': 'NoSafeFromToMember'}}):
            with self.subTest(mutation=mutation), self.assertRaises(RouteWeftError):
                self.validate({**report, **mutation})
        report['policy'] = 'quarantine_ways'
        with self.assertRaisesRegex(RouteWeftError, 'marker'):
            build_report({'report': report}, sha256(self.source), 'quarantine_ways')
        report['diagnostics']['quarantine_ways_policy_v1'] = 1
        build_report({'report': report}, sha256(self.source), 'quarantine_ways')

    def test_quarantine_requires_fixed_source_and_tool_capability(self):
        with self.assertRaisesRegex(RouteWeftError, 'source SHA'):
            self.service({'invalid_restrictions': 'quarantine_ways'})
        service = self.service({'invalid_restrictions': 'quarantine_ways',
                                'source_sha256': sha256(self.source)})
        with self.assertRaisesRegex(RouteWeftError, 'coverage'):
            service.build(self.source)
        self.assertFalse(service.ready.exists())

    def test_province_audit_survives_receipts_and_failed_rebuild_keeps_ready(self):
        report = self.report()
        self.tool.report = lambda args: copy.deepcopy(report)
        service = self.service({'invalid_restrictions': 'block_ways'})
        service.build(self.source)
        service.verify()
        ready = service.ready.read_bytes()
        dataset, _, _ = service.current()
        receipt = json.loads((dataset / 'routing-build.json').read_text())
        self.assertEqual(728, len(receipt['build_result']['report']['restriction_diagnostics']))
        report['restriction_audit']['truncated'] = True
        with self.assertRaisesRegex(RouteWeftError, 'incomplete'):
            service.build(self.source)
        self.assertEqual(ready, service.ready.read_bytes())

    def service(self, settings):
        config = configuration()
        config['regions']['monaco'].update(settings)
        path = self.root / 'config.yaml'
        path.write_text(yaml.safe_dump(config))
        return RoutingService(self.tool, ROOT, self.root / ('work-' + settings.get('builder', 'memory')),
                              'monaco', '20261019', config=path)

    def test_budget_flags_are_checked_against_capabilities_and_forwarded(self):
        settings = dict(invalid_restrictions='block_ways', max_restriction_diagnostics=8192,
                        max_restriction_audit_bytes=1048576, max_blockways_attempts=80)
        service = self.service(settings)
        with self.assertRaisesRegex(RouteWeftError, 'capacity'):
            service.build(self.source)
        self.assertFalse(service.ready.exists())
        self.assertFalse(any(command == 'build' for command, _ in self.tool.calls))
        original = self.tool.call
        def call(command, args, timeout, expected_error=None):
            result = original(command, args, timeout, expected_error)
            if command == 'version':
                result['capabilities']['restriction_audit'] = {
                    'max_records': 32768, 'max_bytes': 16777216, 'max_blockways_attempts': 257}
            return result
        self.tool.call = call
        service.build(self.source)
        self.service({**settings, 'builder': 'external'}).build(self.source)
        for command, args in self.tool.calls:
            if command in ('build', 'preflight'):
                for key, value in settings.items():
                    if key.startswith('max_'):
                        self.assertEqual(str(value), args[args.index('--' + key.replace('_', '-')) + 1])

    def test_invalid_budget_configuration_is_rejected(self):
        for key, value in [('max_restriction_diagnostics', 32769), ('max_restriction_diagnostics', True),
                           ('max_restriction_audit_bytes', 0), ('max_blockways_attempts', 258),
                           ('max_blockways_attempts', 2)]:
            with self.subTest(key=key, value=value), self.assertRaises(RouteWeftError):
                self.service({key: value})

    def test_default_process_accepts_large_audit_but_explicit_bound_still_applies(self):
        binary = self.root / 'cli'
        binary.write_text('#!/usr/bin/env python3\nimport json\n'
                          'print(json.dumps({"schema":1,"status":"ok","audit":"x"*(5*1024**2)}))\n')
        binary.chmod(0o755)
        process = RouteWeftProcess(binary, sha256(binary))
        self.assertEqual(5 * 1024**2, len(process.call('build', [], 10)['audit']))
        with self.assertRaisesRegex(RouteWeftError, 'output limit'):
            RouteWeftProcess(binary, sha256(binary), limit=1024).call('build', [], 10)


@unittest.skipUnless(os.environ.get('ROUTEWEFT_TEST_BIN') and os.environ.get('ROUTEWEFT_TEST_SHA256'),
                     'requires real RouteWeft CLI')
class RealQuarantineTests(unittest.TestCase):
    def test_empty_roles_fail_conservatively_or_quarantine_with_coverage_and_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.osm.pbf'
            generate(source, invalid_restriction=True, empty_roles=True)
            process = RouteWeftProcess(Path(os.environ['ROUTEWEFT_TEST_BIN']),
                                      os.environ['ROUTEWEFT_TEST_SHA256'])
            conservative = RoutingService(process, ROOT, root / 'conservative', 'monaco', '20261019')
            with self.assertRaises(RouteWeftError) as caught:
                conservative.build(source)
            report = caught.exception.response['error']['details']
            self.assertEqual('NoSafeFromToMember', report['blockways_failure']['reason'])
            self.assertFalse(conservative.ready.exists())
            config = configuration()
            config['regions']['monaco'].update(
                invalid_restrictions='quarantine_ways', source_sha256=sha256(source),
                builder='external', smoke_mode='graph-edge-v1', max_blockways_attempts=8)
            path = root / 'config.yaml'
            path.write_text(yaml.safe_dump(config))
            service = RoutingService(process, ROOT, root / 'quarantine', 'monaco', '20261019', config=path)
            service.build(source)
            dataset, manifest, ready = service.current()
            self.assertEqual([10], ready['planned_blocked_way_ids'])
            self.assertEqual([10], ready['applied_blocked_way_ids'])
            self.assertEqual(1, manifest['diagnostics']['quarantine_ways_policy_v1'])
            smoke = service.verify(smoke=True)
            self.assertEqual(0, smoke['coverage']['coverage']['excluded_way_edges'])
            call = process.call
            def residual(command, arguments, timeout, expected_error=None):
                result = call(command, arguments, timeout, expected_error)
                if command == 'coverage':
                    result['coverage']['excluded_way_edges'] = 1
                return result
            process.call = residual
            with self.assertRaisesRegex(RouteWeftError, 'excluded-edge'):
                service.verify(smoke=True)
            process.call = call
            for archive in RoutingDelivery(service).pack('both'):
                extracted = unpack(Path(archive), root / ('unpacked-' + Path(archive).suffix))
                package = json.loads((extracted / 'routing-package.json').read_text())
                self.assertEqual('quarantine_ways', package['invalid_restrictions'])
                self.assertTrue(package['coverage_notice'])
                self.assertEqual([10], package['applied_blocked_way_ids'])
            saved = json.loads(service.ready.read_text())
            saved['applied_blocked_way_ids'] = []
            service.ready.write_text(json.dumps(saved))
            with self.assertRaisesRegex(RouteWeftError, 'audit mismatch'):
                service.verify()
