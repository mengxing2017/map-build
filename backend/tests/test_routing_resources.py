import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from huavd_map_build.production.domain.routing_resources import ResourcePolicy
from huavd_map_build.production.north.local.routing_resources import ResourceGate
from huavd_map_build.production.south.adapter.process.routing_host import HostResources, observe
from huavd_map_build.production.south.port.routeweft import RouteWeftError

ROOT = Path(__file__).resolve().parents[2]
GIB = 1024**3


class ResourceTests(unittest.TestCase):
    def test_policy_rejects_invalid_types_and_unknown_fields(self):
        for values in ({'reserve_percent': 100}, {'estimate_peak_percent': 99},
                       {'per_job_ceiling_bytes': True}, {'mode': 'explicit'}, {'plan_workspace_bytes': 0}):
            with self.subTest(values=values), self.assertRaises(RouteWeftError):
                ResourcePolicy(**values)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'p.yaml'
            p.write_text('schema: 1\nrouting:\n  typo: 1\n')
            with self.assertRaises(RouteWeftError):
                ResourcePolicy.load(ROOT, p)

    def test_same_data_different_host_and_large_estimate(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = ResourceGate(ROOT, Path(tmp))
            for available, allowed in ((32*GIB, True), (8*GIB, False)):
                with self.subTest(available=available), patch(
                        'huavd_map_build.production.north.local.routing_resources.routing_host.observe',
                        return_value=HostResources(available, (), True, (), 0)):
                    if allowed:
                        self.assertEqual(10*GIB, gate.admit('coverage', 10*GIB).logical_bytes)
                    else:
                        with self.assertRaises(RouteWeftError) as caught:
                            gate.admit('coverage', 10*GIB)
                        self.assertEqual('BudgetExceeded', caught.exception.response['error']['kind'])
            incomplete = HostResources(None, (6*GIB,), False, (), 0)
            with self.assertRaisesRegex(RouteWeftError, 'explicit'):
                gate.available(incomplete)
            explicit = ResourceGate(ROOT, Path(tmp), ceiling=20*GIB)
            self.assertLess(explicit.available(incomplete), 6*GIB)

    def test_shared_pool_serializes_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = ResourceGate(ROOT, Path(tmp))
            b = ResourceGate(ROOT, Path(tmp))
            with a.reserved():
                with self.assertRaisesRegex(RouteWeftError, 'pool busy'):
                    with b.reserved():
                        pass
            with b.reserved():
                pass

    def test_cgroup_v2_ancestor_limit_and_unlimited(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / 'proc'; (proc / 'self').mkdir(parents=True)
            (proc/'meminfo').write_text('MemAvailable: 10000000 kB\n')
            (proc/'self/cgroup').write_text('0::/parent/child\n')
            (proc/'self/mountinfo').write_text('1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup2 rw\n')
            base = root/'sys/fs/cgroup'; (base/'parent/child').mkdir(parents=True)
            for relative, limit, usage in (('', 'max', 100), ('parent', 500, 200), ('parent/child', 800, 100)):
                (base/relative/'memory.max').write_text(str(limit))
                (base/relative/'memory.current').write_text(str(usage))
            host = observe(proc, root)
            self.assertTrue(host.detection_complete)
            self.assertEqual((700, 300), host.cgroup_remaining_bytes)
            (base/'parent/memory.current').unlink()
            self.assertFalse(observe(proc, root).detection_complete)

    def test_cgroup_v1_and_hidden_ancestors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);proc=root/'proc';(proc/'self').mkdir(parents=True)
            (proc/'meminfo').write_text('MemAvailable: 10000 kB\n')
            (proc/'self/cgroup').write_text('2:cpu,memory:/tenant/job\n')
            (proc/'self/mountinfo').write_text('1 0 0:1 /tenant /cg rw - cgroup cgroup rw,memory\n')
            base=root/'cg';(base/'job').mkdir(parents=True)
            for path in (base,base/'job'):
                (path/'memory.limit_in_bytes').write_text('1000')
                (path/'memory.usage_in_bytes').write_text('600')
            host=observe(proc,root)
            self.assertEqual((400,400),host.cgroup_remaining_bytes)
            self.assertFalse(host.detection_complete)

    def test_tmpfs_budget_and_disk_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate=ResourceGate(ROOT,Path(tmp))
            with patch('huavd_map_build.production.north.local.routing_resources.routing_host.filesystem_info',
                       return_value={'filesystem':'tmpfs','free_bytes':30*GIB}), patch(
                       'huavd_map_build.production.north.local.routing_resources.routing_host.observe',
                       return_value=HostResources(16*GIB,(),True,(),0)):
                plan=gate.build_space(GIB)
                self.assertGreater(plan['scratch_bytes'],0)
                self.assertLess(plan['scratch_bytes'],8*GIB)
                gate.policy=ResourcePolicy(max_scratch_bytes=40*GIB)
                with self.assertRaisesRegex(RouteWeftError,'scratch'):
                    gate.build_space(GIB)

class ResourceLifecycleTests(unittest.TestCase):
    def setUp(self):
        from test_routing import FakeTool, configuration
        import yaml
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.config = self.work/'audit.yaml'
        self.config.write_text(yaml.safe_dump(configuration()))
        self.tool = FakeTool()
        from huavd_map_build.production.south.adapter.process.routeweft_probe import generate
        self.source = self.work/'source.pbf';generate(self.source)

    def service(self, **kwargs):
        from huavd_map_build.production.north.local.routing import RoutingService
        return RoutingService(self.tool, ROOT, self.work, 'monaco', '20261030', config=self.config, **kwargs)

    def test_budget_change_revalidates_without_rebuilding_or_mutating_graph(self):
        from huavd_map_build.production.north.local.routing import file_records
        first=self.service();old=first.build(self.source)
        dataset,_,_=first.current();files=file_records(dataset)
        count=len(self.tool.outputs)
        changed=self.service(memory_ceiling_bytes=20*GIB)
        self.assertEqual(first.config_sha256,changed.config_sha256)
        self.assertNotEqual(first.validation_policy_sha256,changed.validation_policy_sha256)
        with self.assertRaisesRegex(RouteWeftError,'routing verify'):
            changed.current()
        renewed=changed.verify()
        self.assertEqual(old['dataset_id'],renewed['dataset_id'])
        self.assertEqual(count,len(self.tool.outputs))
        self.assertEqual(files,file_records(dataset))
        self.assertNotEqual(old['validation_receipt'],renewed['validation_receipt'])
        changed.current()
        self.assertTrue((first.outputs/old['validation_receipt']['path']).is_file())

    def test_completed_build_survives_load_failure_and_recovers(self):
        from huavd_map_build.production.north.local.routing import file_records
        original=self.tool.call
        def fail(command,args,timeout,expected_error=None):
            if command=='nearest':
                raise RouteWeftError('engine resource failure',command='nearest',response={
                    'error':{'kind':'BudgetExceeded','resource':{'resource':'estimated_resident_bytes',
                        'limit':1,'observed':2,'stage':'engine_load','estimator_version':1}}})
            return original(command,args,timeout,expected_error)
        self.tool.call=fail
        service=self.service()
        with self.assertRaisesRegex(RouteWeftError,'engine resource failure'):
            service.build(self.source)
        self.assertFalse(service.ready.exists())
        dataset=next((self.work/'staging/routing').glob('monaco-20261030-*/dataset'))
        records=file_records(dataset)
        summary=json.loads((dataset.parent/'failure-summary.json').read_text())
        self.assertEqual(2,summary['resource']['observed'])
        self.assertIsNotNone(summary['source_sha256'])
        self.tool.call=original
        ready=service.revalidate(dataset)
        self.assertEqual(1,len(self.tool.outputs))
        self.assertEqual(records,ready['files'])
        service.current()
        # Changed semantic policy must not adopt the completed build.
        from huavd_map_build.production.north.local.routing import RoutingService
        incompatible=RoutingService(self.tool,ROOT,self.work,'monaco','20261030',config=self.config,
                                    invalid_maxspeed='use_default')
        with self.assertRaisesRegex(RouteWeftError,'identity'):
            incompatible.revalidate(dataset)

    def test_plan_identity_counts_and_version_are_checked_before_loading(self):
        from test_routing import fake_plan
        from huavd_map_build.production.domain.routing_resources import ResourcePlan
        manifest={'dataset_id':'test','graph_sha256':'a'*64,'source_sha256':'b'*64,'format':2,
                  'nodes':2,'edges':2,'restrictions':0,'graph_bytes':100}
        import copy
        for alter in (lambda p:p.update(estimator_version=2),
                      lambda p:p.update(dataset_id='other'),
                      lambda p:p['counts'].update(nodes=3),
                      lambda p:p['engine_load'].update(estimated_bytes=1),
                      lambda p:p.update(verification_scope='published_manifest')):
            plan=copy.deepcopy(fake_plan(manifest,independent=True));alter(plan)
            with self.subTest(plan=plan),self.assertRaises(RouteWeftError):
                ResourcePlan.parse(plan,manifest,workspace=67108864)

    def test_missing_planning_capability_never_loads_or_builds(self):
        original=self.tool.call
        def old(command,args,timeout,expected_error=None):
            result=original(command,args,timeout,expected_error)
            if command=='version':
                result['capabilities'].pop('resource_plan')
            return result
        self.tool.call=old
        with self.assertRaisesRegex(RouteWeftError,'resource-plan'):
            self.service().build(self.source)
        self.assertFalse(self.tool.outputs)

    def test_planning_admission_failure_preserves_completed_builder_receipt(self):
        service=self.service()
        original=service.resources.plan
        def refuse(*args,**kwargs):
            raise RouteWeftError('planning admission refused',command='resource-plan')
        service.resources.plan=refuse
        with self.assertRaisesRegex(RouteWeftError,'planning admission'):
            service.build(self.source)
        dataset=next((self.work/'staging/routing').glob('monaco-20261030-*/dataset'))
        self.assertEqual(2,json.loads((dataset/'routing-build.json').read_text())['schema'])
        service.resources.plan=original
        service.revalidate(dataset)
        self.assertEqual(1,len(self.tool.outputs))
        service.current()

    def test_archive_revalidation_failure_does_not_replace_previous_tar(self):
        from huavd_map_build.delivery.north.local.routing import RoutingDelivery
        service=self.service();service.build(self.source)
        previous=service.outputs/'monaco-20261030.routing.bundle.tar.gz'
        previous.write_bytes(b'previous verified archive')
        original=service.smoke
        def fail_zip(dataset,manifest,excluded=None):
            if dataset.name=='unpacked-zip':
                raise RouteWeftError('unpacked zip failed')
            return original(dataset,manifest,excluded)
        service.smoke=fail_zip
        with self.assertRaisesRegex(RouteWeftError,'unpacked zip failed'):
            RoutingDelivery(service).pack('both')
        self.assertEqual(b'previous verified archive',previous.read_bytes())
        self.assertFalse((service.outputs/'monaco-20261030.routing.bundle.zip').exists())
