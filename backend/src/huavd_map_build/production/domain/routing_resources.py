"""Deployment resource policy and versioned RouteWeft planning contract.

Logical estimates are not RSS limits. Environment admission is a conservative
policy check; the scheduler/cgroup remains responsible for physical isolation.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

import yaml

from huavd_map_build.production.south.port.routeweft import RouteWeftError


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def positive(value, name, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 2**63 - 1:
        raise RouteWeftError(f'invalid resource policy {name}')
    return value


@dataclass(frozen=True)
class ResourcePolicy:
    mode: str = 'auto'
    per_job_ceiling_bytes: int | None = None
    reserve_bytes: int = 1073741824
    reserve_percent: int = 10
    estimate_peak_percent: int = 125
    unknown_overhead_bytes: int = 536870912
    plan_workspace_bytes: int = 67108864
    max_input_bytes: int | None = None
    max_scratch_bytes: int | None = None
    disk_reserve_bytes: int = 1073741824
    build_timeout_s: int = 7200
    verify_timeout_s: int = 600
    query_timeout_s: int = 600
    total_timeout_s: int = 14400

    def __post_init__(self):
        if self.mode not in ('auto', 'explicit'):
            raise RouteWeftError('resource mode must be auto or explicit')
        for name, value in asdict(self).items():
            if name == 'mode':
                continue
            if value is None and name in ('per_job_ceiling_bytes', 'max_input_bytes', 'max_scratch_bytes'):
                continue
            positive(value, name, zero=name in ('reserve_bytes', 'reserve_percent', 'disk_reserve_bytes'))
        if self.reserve_percent >= 100 or self.estimate_peak_percent < 100:
            raise RouteWeftError('invalid resource reserve/peak percentage')
        if self.mode == 'explicit' and self.per_job_ceiling_bytes is None:
            raise RouteWeftError('explicit resource policy requires per_job_ceiling_bytes')

    @classmethod
    def load(cls, root: Path, path: Path | None = None, ceiling: int | None = None):
        selected = path or Path('config/build-resources.yaml')
        selected = (selected if selected.is_absolute() else root / selected).resolve()
        try:
            document = yaml.safe_load(selected.read_text())
            if (not isinstance(document, dict) or set(document) != {'schema', 'routing'}
                    or type(document['schema']) is not int or document['schema'] != 1
                    or not isinstance(document['routing'], dict)):
                raise ValueError('expected schema 1 and routing policy')
            values = dict(document['routing'])
            if ceiling is not None:
                values.update(mode='explicit', per_job_ceiling_bytes=ceiling)
            policy = cls(**values)
        except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
            raise RouteWeftError(f'cannot load resource policy {selected}: {error}') from error
        return policy, {'file': str(selected), 'cli_ceiling_bytes': ceiling,
                        'effective': asdict(policy), 'sha256': digest(asdict(policy))}


@dataclass(frozen=True)
class ResourcePlan:
    raw: dict

    @classmethod
    def parse(cls, raw, manifest, *, workspace=None):
        if (not isinstance(raw, dict) or type(raw.get('schema')) is not int or raw['schema'] != 1
                or type(raw.get('estimator_version')) is not int or raw['estimator_version'] != 1
                or raw.get('estimate_kind') != 'conservative_logical_allocations_not_rss'):
            raise RouteWeftError('incompatible RouteWeft resource plan; reinstall locked tool')
        for key in ('dataset_id', 'graph_sha256', 'source_sha256', 'format'):
            if raw.get(key) != manifest.get(key) or key not in manifest:
                raise RouteWeftError(f'resource plan identity mismatch: {key}')
        if type(raw['format']) is not int or raw['format'] not in (1, 2):
            raise RouteWeftError('invalid resource plan format')
        counts = raw.get('counts', {})
        if not isinstance(counts, dict):
            raise RouteWeftError('invalid resource plan counts')
        for key in ('nodes', 'edges', 'restrictions', 'graph_bytes'):
            if type(counts.get(key)) is not int or counts[key] < 0 or counts[key] != manifest.get(key):
                raise RouteWeftError(f'resource plan count mismatch: {key}')
        options = raw.get('effective_load_options')
        if not isinstance(options, dict):
            raise RouteWeftError('missing effective load options')
        for name in ('max_bytes', 'max_nodes', 'max_edges', 'max_restriction_edges', 'max_resident_bytes'):
            positive(options.get(name), name)
        for phase in ('dataset_load', 'engine_load'):
            part = raw.get(phase)
            if not isinstance(part, dict):
                raise RouteWeftError('missing resource estimate')
            components = ('nodes_bytes', 'edges_bytes', 'restriction_bytes', 'strings_bytes', 'dictionary_bytes')
            for key in ('estimated_bytes', *components):
                positive(part.get(key), key, zero=True)
            if sum(part[k] for k in components) != part['estimated_bytes']:
                raise RouteWeftError('resource estimate components do not sum')
        scope = ('full_streaming_v2' if raw['format'] == 2 else 'identity_size_hash_v1_not_semantic')
        if workspace is not None:
            if raw.get('verification_scope') != scope:
                raise RouteWeftError('resource plan was not independently verified')
            positive(raw.get('validation_workspace_budget_bytes'), 'validation workspace')
            if raw['validation_workspace_budget_bytes'] > workspace:
                raise RouteWeftError('resource plan workspace mismatch')
        elif raw.get('verification_scope') != 'published_manifest':
            raise RouteWeftError('invalid build resource plan scope')
        for field in ('included', 'excluded_unknown'):
            if not isinstance(raw.get(field), list) or not raw[field] or any(not isinstance(v, str) for v in raw[field]):
                raise RouteWeftError('resource plan must declare included and unknown costs')
        return cls(raw)

    def estimated(self, phase):
        return self.raw[phase]['estimated_bytes']


def require_resource_capability(version):
    cap = version.get('capabilities', {}).get('resource_plan', {})
    if ('resource-plan' not in version.get('commands', []) or type(cap.get('schema')) is not int
            or cap['schema'] != 1 or type(cap.get('estimator_version')) is not int
            or cap['estimator_version'] != 1 or cap.get('command') != 'resource-plan'
            or cap.get('build_output') is not True or cap.get('query_indexes_constructed') is not False):
        raise RouteWeftError('RouteWeft lacks compatible resource-plan schema/estimator; reinstall locked tool')
