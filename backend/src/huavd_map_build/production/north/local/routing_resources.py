"""One deployment policy and admission gate for all routing entry points."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
from pathlib import Path
import time

from huavd_map_build.production.domain.routing_resources import ResourcePolicy, ResourcePlan, require_resource_capability
from huavd_map_build.production.south.adapter.process import routing_host
from huavd_map_build.production.south.port.routeweft import RouteWeftError


@dataclass(frozen=True)
class AdmissionDecision:
    phase: str
    logical_bytes: int
    peak_allowance_bytes: int
    available_for_job_bytes: int
    host: dict
    policy_sha256: str


class ResourceGate:
    def __init__(self, root, workdir, config=None, ceiling=None):
        self.policy, self.source = ResourcePolicy.load(root, config, ceiling)
        self.workdir = Path(workdir)
        self.decisions = []
        self.started = None

    def reject(self, phase, resource, limit, observed, message):
        raise RouteWeftError(message, command=phase, exit_code=4, response={
            'schema': 1, 'status': 'error', 'error': {'kind': 'BudgetExceeded', 'message': message,
                'resource': {'resource': resource, 'limit': limit, 'observed': observed,
                             'stage': phase}}})

    def available(self, host):
        policy = self.policy
        if (not host.detection_complete or host.available_bytes is None) and policy.mode != 'explicit':
            raise RouteWeftError('resource detection incomplete; supply an explicit deployment ceiling '
                                 'with --memory-ceiling-bytes or an explicit resource policy')
        limits = [v for v in (host.available_bytes, *host.cgroup_remaining_bytes,
                              policy.per_job_ceiling_bytes) if v is not None]
        if not limits:
            raise RouteWeftError('no finite resource ceiling')
        usable = min(limits)
        return max(0, usable - max(policy.reserve_bytes, usable * policy.reserve_percent // 100))

    def admit(self, phase, estimated, *, extra=0):
        host = routing_host.observe()
        available = self.available(host)
        peak = (estimated * self.policy.estimate_peak_percent + 99) // 100 + self.policy.unknown_overhead_bytes + extra
        decision = AdmissionDecision(phase, estimated, peak, available, host.as_dict(), self.source['sha256'])
        self.decisions.append({**asdict(decision), 'admitted': peak <= available})
        if peak > available:
            self.reject(phase, 'host_peak_allowance_bytes', available, peak,
                        f'resource admission refused for {phase}: needs {peak} bytes including deployment '
                        f'allowances, available {available}; change execution environment or deployment policy')
        return decision

    @contextmanager
    def reserved(self):
        path = self.workdir / 'staging/routing/resources.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RouteWeftError('routing resource pool busy in this workdir; retry after the active task') from error
            yield

    def timeout(self, phase_timeout):
        if self.started is None:
            return phase_timeout
        remaining = self.policy.total_timeout_s - (time.monotonic() - self.started)
        if remaining <= 0:
            self.reject('task', 'elapsed_seconds', self.policy.total_timeout_s,
                        int(time.monotonic() - self.started), 'routing total task timeout exceeded')
        return min(phase_timeout, remaining)

    capability = staticmethod(require_resource_capability)

    def plan(self, tool, dataset, manifest, capacity):
        with self.reserved():
            self.admit('resource-plan', self.policy.plan_workspace_bytes)
            result = tool.call('resource-plan', ['--dataset', str(dataset), '--json', *capacity,
                '--max-plan-workspace-bytes', str(self.policy.plan_workspace_bytes)],
                self.timeout(self.policy.verify_timeout_s))
        plan = ResourcePlan.parse(result.get('resource_plan'), manifest, workspace=self.policy.plan_workspace_bytes)
        if (Path(dataset) / 'routing.mld').exists():
            raise RouteWeftError('optional routing.mld memory is not estimated; remove it through a reviewed '
                                 'dataset migration or use a tool with a compatible acceleration estimate')
        return plan

    def call(self, tool, command, arguments, estimate, timeout, expected=None):
        with self.reserved():
            self.admit(command, estimate)
            return tool.call(command, [*arguments, '--max-load-bytes', str(max(1, estimate))],
                             self.timeout(timeout), expected)

    def build_space(self, source_bytes, *, frozen=False, scratch_requested=None, graph_bytes=0):
        info = routing_host.filesystem_info(self.workdir)
        if info['filesystem'] is None:
            raise RouteWeftError('cannot determine routing scratch filesystem')
        freeze_bytes = 0 if frozen else source_bytes
        available = max(0, info['free_bytes'] - self.policy.disk_reserve_bytes - freeze_bytes - graph_bytes)
        requested = self.policy.max_scratch_bytes if scratch_requested is None else scratch_requested
        if requested is not None and requested > available:
            self.reject('build', 'scratch_free_bytes', available, requested, 'insufficient scratch filesystem space')
        scratch = requested if requested is not None else available
        if info['filesystem'] in ('tmpfs', 'ramfs'):
            # Scratch is genuinely resident on this mount. Reserve a bounded share
            # before building; cumulative build working memory is still unknown.
            memory = self.available(routing_host.observe())
            if requested is None:
                scratch = min(scratch, max(0, (memory - self.policy.unknown_overhead_bytes - freeze_bytes - graph_bytes) // 3))
            self.admit('build-tmpfs', self.policy.plan_workspace_bytes, extra=scratch + freeze_bytes + graph_bytes)
        else:
            self.admit('build-start', self.policy.plan_workspace_bytes)
        if scratch <= 0:
            self.reject('build', 'scratch_free_bytes', available, 1, 'no scratch capacity after deployment reserves')
        return {'scratch_bytes': scratch, 'graph_output_reserve_bytes': graph_bytes, 'filesystem': info,
                'build_peak': 'unknown', 'future_engine_load': 'unknown_until_dataset_built'}

    @contextmanager
    def storage(self, phase, size, destination):
        """Reserve the workdir pool while materializing a known amount of data."""
        with self.reserved():
            info = routing_host.filesystem_info(destination)
            if info['filesystem'] is None:
                raise RouteWeftError('cannot determine package destination filesystem')
            available = max(0, info['free_bytes'] - self.policy.disk_reserve_bytes)
            if size > available:
                self.reject(phase, 'filesystem_free_bytes', available, size,
                            f'insufficient filesystem space for {phase}')
            self.admit(phase, self.policy.plan_workspace_bytes,
                       extra=size if info['filesystem'] in ('tmpfs', 'ramfs') else 0)
            yield

    def receipt(self):
        return {'schema': 1, 'policy': self.source, 'admissions': list(self.decisions),
                'reservation_scope': 'serialized_per_workdir; cross-workdir isolation requires scheduler/cgroup',
                'physical_memory_guarantee': False}
