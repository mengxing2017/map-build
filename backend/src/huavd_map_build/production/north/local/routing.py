"""Routing-only build lifecycle. Ready is the sole publication commit point."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

import yaml

from huavd_map_build.production.south.adapter.process.routeweft import sha256
from huavd_map_build.production.south.port.routeweft import RouteWeftError, RouteWeftPort
from huavd_map_build.shared.kernel.identity import RegionId, BuildDate, SessionId
from huavd_map_build.production.south.adapter.process.routeweft_contract import capabilities, build_report, audit_identity


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, path)


def file_records(directory: Path) -> dict:
    if directory.is_symlink() or not directory.is_dir():
        raise RouteWeftError('dataset must be a regular directory')
    records = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise RouteWeftError('dataset contains links or special files')
        if path.is_file():
            records[path.relative_to(directory).as_posix()] = {
                'bytes': path.stat().st_size, 'sha256': sha256(path)}
    return records


class RoutingService:
    def __init__(self, tool: RouteWeftPort, root: Path, workdir: Path,
                 region: str, day: str, session: str | None = None, config: Path | None = None,
                 invalid_maxspeed: str | None = None):
        region_id = RegionId(region)
        default = SessionId.for_build(region_id, BuildDate(day)).value
        self.session = SessionId(session or default).value
        if self.session != default:
            raise RouteWeftError('SESSION must match REGION and YYYYMMDD')
        self.automatic_smoke = config is None
        if config is None:
            # Routing uses the existing map region catalog, never a second whitelist.
            from huavd_map_build.bootstrap import catalog_service
            settings = catalog_service(root).region(region_id).routing
            self.config = {
                'profile': 'driving', 'invalid_restrictions': settings.invalid_restrictions,
                'invalid_maxspeed': os.environ.get('ROUTING_INVALID_MAXSPEED', settings.invalid_maxspeed),
                'max_input_bytes': 512 * 1024**2, 'build_timeout_s': 3600,
                'preflight_timeout_s': 3600, 'verify_timeout_s': 300,
                'query_timeout_s': 300, 'query_budget': {'radius-m': 0.1, 'timeout-ms': 10000},
                'smoke': [], 'smoke_mode': 'graph-edge-v1',
                'builder': 'external', 'graph_capacity': 'regional',
                'max_scratch_bytes': 16 * 1024**3, 'max_load_bytes': 8 * 1024**3,
            }
            effective = {'region': region, 'defaults': self.config}
            self.config_sha256 = hashlib.sha256(
                json.dumps(effective, sort_keys=True).encode()).hexdigest()
        else:
            # Explicit audit configurations are shared by CLI and standard bundles.
            config = (config if config.is_absolute() else root / config).resolve()
            try:
                document = yaml.safe_load(config.read_text())
            except (OSError, yaml.YAMLError) as error:
                raise RouteWeftError(f'cannot read routing audit config: {config}: {error}') from error
            if not isinstance(document, dict) or document.get('schema') != 1:
                raise RouteWeftError('unsupported routing config schema')
            self.config_sha256 = sha256(config)
            regions = document.get('regions')
            if not isinstance(regions, dict):
                raise RouteWeftError('routing config regions must be a mapping')
            self.config = regions.get(region)
            if not isinstance(self.config, dict) or self.config.get('enabled') is not True:
                raise RouteWeftError(f'routing region not enabled: {region}')
        self.automatic_smoke = self.automatic_smoke or self.config.get('smoke_mode') == 'graph-edge-v1'
        self.maxspeed_policy = (invalid_maxspeed if invalid_maxspeed is not None else
            self.config.get('invalid_maxspeed', os.environ.get('ROUTING_INVALID_MAXSPEED', 'reject')))
        if self.maxspeed_policy not in ('reject', 'use_default'):
            raise RouteWeftError('invalid maxspeed policy; use reject or use_default')
        self.config_sha256 = hashlib.sha256(json.dumps({
            'base_config_sha256': self.config_sha256, 'invalid_maxspeed': self.maxspeed_policy,
        }, sort_keys=True).encode()).hexdigest()
        self.external = self.config.get('builder', 'memory') == 'external'
        if self.config.get('builder', 'memory') not in ('memory', 'external'):
            raise RouteWeftError('unsupported routing builder')
        self.graph_capacity = self.config.get('graph_capacity', 'regional' if self.external else 'city')
        if self.graph_capacity not in ('city', 'regional') or (not self.external and self.graph_capacity != 'city'):
            raise RouteWeftError('regional capacity requires external builder')
        self.dataset_format = 2 if self.external else 1
        self.graph_file = 'graph.bin' if self.external else 'graph.json'
        self.capacity_args = ['--graph-capacity', self.graph_capacity] if self.external else []
        for key in ('max_scratch_bytes', 'max_load_bytes'):
            if key in self.config and (type(self.config[key]) is not int or self.config[key] <= 0):
                raise RouteWeftError(f'invalid {key}')
        if self.config.get('profile') != 'driving':
            raise RouteWeftError('unsupported routing profile')
        self.policy = self.config.get('invalid_restrictions', 'reject')
        if self.policy not in ('reject', 'block_ways', 'quarantine_ways'):
            raise RouteWeftError('invalid restriction policy; use reject, block_ways or quarantine_ways')
        if self.policy == 'quarantine_ways' and config is not None and not self.config.get('source_sha256'):
            raise RouteWeftError('quarantine_ways requires an explicit source SHA-256')
        from huavd_map_build.production.south.adapter.process.routeweft_contract import AUDIT_LIMITS
        self.audit_args = []
        for key, (_, maximum) in AUDIT_LIMITS.items():
            if key in self.config:
                value = self.config[key]
                if type(value) is not int or not 0 < value <= maximum:
                    raise RouteWeftError(f'invalid {key}')
                if key == 'max_blockways_attempts' and self.policy not in ('block_ways', 'quarantine_ways'):
                    raise RouteWeftError('max_blockways_attempts requires block_ways or quarantine_ways')
                self.audit_args += ['--' + key.replace('_', '-'), str(value)]
        self.review = self.config.get('restriction_review')
        if self.review is not None:
            if (not isinstance(self.review, dict) or not isinstance(self.review.get('reason'), str)
                    or not self.review['reason'].strip()
                    or not isinstance(self.review.get('blocked_way_ids'), list)
                    or any(type(v) is not int for v in self.review['blocked_way_ids'])
                    or len(set(self.review['blocked_way_ids'])) != len(self.review['blocked_way_ids'])
                    or not isinstance(self.review.get('diagnostics'), list)
                    or any(not isinstance(d, dict) or type(d.get('relation_id')) is not int
                           or not isinstance(d.get('code'), str) for d in self.review['diagnostics'])):
                raise RouteWeftError('restriction_review must be explicit and complete')
            if any('attempt' in d for d in self.review['diagnostics']) and any(
                    type(d.get('attempt')) is not int or not 0 < d['attempt'] <= 257
                    for d in self.review['diagnostics']):
                raise RouteWeftError('restriction_review attempts must be explicit and complete')
            if not self.config.get('source_sha256'):
                raise RouteWeftError('restriction_review requires a reviewed source SHA-256')
        for key in ('build_timeout_s', 'verify_timeout_s', 'query_timeout_s'):
            value = self.config.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise RouteWeftError(f'invalid {key}')
        timeout = self.config.get('preflight_timeout_s', self.config['build_timeout_s'])
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise RouteWeftError('invalid preflight_timeout_s')
        queries = self.config.get('smoke', [])
        if not isinstance(queries, list) or any(not isinstance(q, dict) for q in queries):
            raise RouteWeftError('smoke must be a list of query objects')
        maximum = self.config.get('max_input_bytes', 512 * 1024**2)
        if type(maximum) is not int or not 0 < maximum <= 512 * 1024**2:
            raise RouteWeftError('invalid routing input size limit')
        accepted = self.config.get('source_sha256')
        if accepted is not None and (not isinstance(accepted, str) or not re.fullmatch('[0-9a-f]{64}', accepted)):
            raise RouteWeftError('invalid reviewed source SHA-256')
        thresholds = self.config.get('diagnostic_max', {})
        if not isinstance(thresholds, dict) or any(type(v) is not int or v < 0 for v in thresholds.values()):
            raise RouteWeftError('invalid diagnostic thresholds')
        if not self.automatic_smoke and not all(any(q.get('command') == cmd and q.get('expect') == 'ok' for q in queries)
                   for cmd in ('nearest', 'route')):
            raise RouteWeftError('smoke requires successful nearest and route')
        if not self.automatic_smoke and not any(q.get('expect') == 'NoRoute' for q in queries):
            raise RouteWeftError('smoke requires a reviewed NoRoute case')
        self.tool, self.region = tool, region
        self.workdir = workdir.resolve()
        self.outputs = self.workdir / 'outputs'
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.ready = self.outputs / f'{self.session}.routing.ready.json'

    @contextmanager
    def locked(self):
        path = self.workdir / 'staging/routing' / f'{self.session}.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RouteWeftError('routing session is busy') from error
            yield

    def verify_dataset(self, dataset, source_sha256=None):
        result = self.tool.call('verify', ['--dataset', str(dataset), '--json', *self.capacity_args],
                                self.config['verify_timeout_s'])
        manifest = result.get('manifest', {})
        if not isinstance(manifest, dict):
            raise RouteWeftError('invalid manifest envelope')
        if result.get('verified') is not True:
            raise RouteWeftError('verify did not confirm integrity')
        if type(manifest.get('format')) is not int or manifest['format'] != self.dataset_format or manifest.get('profile') != 'driving-v1':
            raise RouteWeftError('unsupported manifest identity')
        if not isinstance(manifest.get('dataset_id'), str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', manifest['dataset_id']):
            raise RouteWeftError('unsafe dataset id')
        if source_sha256 and manifest.get('source_sha256') != source_sha256:
            raise RouteWeftError('source SHA-256 mismatch')
        if not isinstance(manifest.get('diagnostics'), dict) or any(
                type(v) is not int or v < 0 for v in manifest['diagnostics'].values()):
            raise RouteWeftError('invalid diagnostics')
        for name, maximum in self.config.get('diagnostic_max', {}).items():
            if name not in manifest['diagnostics'] or manifest['diagnostics'][name] > maximum:
                raise RouteWeftError(f'diagnostic threshold: {name}')
        return manifest

    def smoke(self, dataset, manifest, excluded=None):
        coverage = None
        if self.policy == 'quarantine_ways':
            if excluded is None:
                receipt = json.loads((dataset / 'routing-build.json').read_text())
                excluded = receipt['build_result']['report']['applied_blocked_way_ids']
            with tempfile.NamedTemporaryFile(mode='w', dir=self.workdir / 'staging/routing') as listing:
                json.dump(sorted(excluded), listing)
                listing.flush()
                coverage = self.tool.call('coverage', [
                    '--dataset', str(dataset), '--excluded-ways', listing.name, '--json',
                    *self.capacity_args, '--max-load-bytes',
                    str(self.config.get('max_load_bytes', 8 * 1024**3))], self.config['query_timeout_s'])
            stats = coverage.get('coverage', {})
            if (coverage.get('dataset_id') != manifest['dataset_id']
                    or any(type(stats.get(k)) is not int or stats[k] != manifest[k]
                           for k in ('nodes', 'edges'))
                    or type(stats.get('excluded_way_edges')) is not int
                    or stats['excluded_way_edges'] != 0):
                raise RouteWeftError('quarantine coverage/excluded-edge check failed')
        results = []
        queries = self._automatic_queries(dataset) if self.automatic_smoke else self.config['smoke']
        for query in queries:
            command, expected = query['command'], query['expect']
            if command not in ('nearest', 'route') or expected not in ('ok', 'NoRoute', 'NoSegment'):
                raise RouteWeftError('invalid smoke command/expectation')
            coordinates = query['coordinates']
            points = [[float(x) for x in point.split(',')] for point in coordinates.split(';')]
            if (command == 'nearest' and len(points) != 1) or (command == 'route' and len(points) < 2):
                raise RouteWeftError('invalid smoke waypoint count')
            if any(len(p) != 2 or not all(math.isfinite(v) for v in p)
                   or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in points):
                raise RouteWeftError('invalid smoke coordinates')
            arguments = ['--dataset', str(dataset), '--json',
                         '--coordinate' if command == 'nearest' else '--coordinates', coordinates]
            if self.external:
                arguments += [*self.capacity_args, '--max-load-bytes', str(self.config.get('max_load_bytes', 8 * 1024**3))]
            budget = {**self.config.get('query_budget', {}), **query.get('query_budget', {})}
            for key, value in budget.items():
                if key not in ('radius-m', 'max-work', 'max-states', 'max-queue', 'timeout-ms'):
                    raise RouteWeftError('unknown query budget')
                arguments += ['--' + key, str(value)]
            result = self.tool.call(command, arguments, self.config['query_timeout_s'],
                                    None if expected == 'ok' else expected)
            if expected == 'ok':
                payload = result.get('route', {}) if command == 'route' else result
                if any(payload.get(key) != manifest[key] for key in ('dataset_id', 'profile', 'format')):
                    raise RouteWeftError('query identity mismatch')
                if command == 'nearest':
                    if not payload.get('matches'):
                        raise RouteWeftError('nearest returned no matches')
                    for match in payload['matches']:
                        point = match.get('point', {})
                        if (any(type(point.get(k)) not in (int, float) or not math.isfinite(point[k])
                                or abs(point[k]) > bound for k, bound in [('lon', 180), ('lat', 90)])
                                or type(match.get('distance_m')) not in (int, float)
                                or not math.isfinite(match['distance_m']) or match['distance_m'] < 0):
                            raise RouteWeftError('invalid nearest match')
                else:
                    geometry = payload.get('geometry', [])
                    if len(geometry) < 2 or any(not all(
                            isinstance(p.get(k), (int, float)) and math.isfinite(p[k])
                            and abs(p[k]) <= bound for k, bound in [('lon', 180), ('lat', 90)])
                            for p in geometry):
                        raise RouteWeftError('invalid route geometry')
                    for key in ('distance_m', 'duration_s'):
                        value = payload.get(key)
                        bounds = query.get(key)
                        if (type(value) not in (int, float) or not math.isfinite(value) or value < 0
                                or not bounds or not bounds[0] <= value <= bounds[1]):
                            raise RouteWeftError(f'route outside expected {key} range')
                    legs = payload.get('legs', [])
                    if len(legs) != len(points) - 1 or not legs:
                        raise RouteWeftError('route leg count mismatch')
                    for leg in legs:
                        if any(type(leg.get(k)) not in (int, float) or not math.isfinite(leg[k])
                               or leg[k] < 0 for k in ('distance_m', 'duration_s')):
                            raise RouteWeftError('invalid leg cost')
                        if not 0 <= leg['geometry_start'] <= leg['geometry_end'] < len(geometry):
                            raise RouteWeftError('invalid leg geometry indices')
                    if (legs[0]['geometry_start'] != 0 or legs[-1]['geometry_end'] != len(geometry) - 1
                            or any(a['geometry_end'] != b['geometry_start'] for a, b in zip(legs, legs[1:]))
                            or len(payload.get('snapped', [])) != len(points)):
                        raise RouteWeftError('route geometry/waypoint continuity mismatch')
                    for step in payload.get('steps', []):
                        if not 0 <= step['geometry_start'] <= step['geometry_end'] < len(geometry):
                            raise RouteWeftError('invalid step geometry indices')
                    for key in ('distance_m', 'duration_s'):
                        if not math.isclose(sum(l[key] for l in legs), payload[key], rel_tol=1e-6, abs_tol=1e-6):
                            raise RouteWeftError('route leg cost mismatch')
            results.append(result)
        return {'schema': 1, 'dataset_id': manifest['dataset_id'],
                'mode': 'graph-edge-v1' if self.automatic_smoke else 'reviewed',
                'queries': queries, 'results': results,
                **({'coverage': coverage} if coverage is not None else {})}

    @staticmethod
    def _automatic_queries(dataset):
        from huavd_map_build.production.south.adapter.process.routeweft_graph import sample_edges
        for start, end, distance in sample_edges(dataset):
            if distance < 10000 or start == end:
                continue
            def coordinate(fraction):
                return ','.join(str(start[key] + fraction * (end[key] - start[key]))
                                for key in ('lon', 'lat'))
            first, last = coordinate(0.25), coordinate(0.75)
            return [
                {'command': 'nearest', 'coordinates': first, 'expect': 'ok'},
                {'command': 'route', 'coordinates': first + ';' + last, 'expect': 'ok',
                 'distance_m': [0, 1e15], 'duration_s': [0, 1e15]},
            ]
        raise RouteWeftError('routing graph has no suitable edge for automatic query checks')

    def current(self):
        ready = json.loads(self.ready.read_text())
        if ready.get('schema') != 1 or ready.get('region') != self.region:
            raise RouteWeftError('ready schema/region mismatch')
        if ready.get('invalid_maxspeed') != self.maxspeed_policy:
            raise RouteWeftError('ready maxspeed policy mismatch; rebuild required')
        if ready.get('invalid_restrictions') != self.policy:
            raise RouteWeftError('ready restriction policy mismatch; rebuild required')
        dataset_id = ready.get('dataset_id', '')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', dataset_id):
            raise RouteWeftError('invalid ready dataset id')
        dataset = self.outputs / f'{self.session}.routing' / dataset_id
        if file_records(dataset) != ready['files'] or not ready['files']:
            raise RouteWeftError('ready dataset hashes mismatch')
        if ready.get('config_sha256') != self.config_sha256:
            raise RouteWeftError('ready config changed; rebuild and review required')
        if ready['tool'] != self.tool.identity:
            raise RouteWeftError('ready tool identity mismatch')
        manifest = self.verify_dataset(dataset, ready['source_sha256'])
        if manifest['dataset_id'] != dataset_id:
            raise RouteWeftError('ready dataset identity mismatch')
        receipt = json.loads((dataset / 'routing-build.json').read_text())
        if (receipt.get('invalid_maxspeed') != self.maxspeed_policy
                or ready.get('maxspeed_diagnostics') != receipt.get('build_result', {}).get('report', {}).get('maxspeed_diagnostics')):
            raise RouteWeftError('ready maxspeed audit mismatch')
        report = receipt.get('build_result', {}).get('report', {})
        if (ready.get('blocked_way_ids') != report.get('blocked_way_ids')
                or ready.get('restriction_diagnostics') != report.get('restriction_diagnostics')):
            raise RouteWeftError('ready restriction audit mismatch')
        for key in ('planned_blocked_way_ids', 'applied_blocked_way_ids', 'blockways_failure'):
            if ready.get(key) != report.get(key):
                raise RouteWeftError('ready exclusion application audit mismatch')
        if receipt.get('invalid_restrictions') != self.policy:
            raise RouteWeftError('ready restriction policy mismatch')
        build_report(receipt.get('build_result', {}), ready['source_sha256'], self.policy,
                     manifest=manifest, review=self.review, maxspeed_policy=self.maxspeed_policy)
        if self.external:
            if (receipt.get('preflight') != {'mode': 'external-build-validation'}
                    or receipt.get('graph_capacity') != self.graph_capacity
                    or receipt['build_result'].get('build', {}).get('builder') != 'external'):
                raise RouteWeftError('external build audit mismatch')
        elif audit_identity(receipt.get('preflight', {}).get('report', {})) != audit_identity(receipt['build_result']['report']):
            raise RouteWeftError('ready preflight/build report mismatch')
        return dataset, manifest, ready

    def check(self, input_path: Path | None = None, *, version=None):
        """Validate configuration, capability and optional input without building a graph."""
        source_sha = None
        if input_path is not None:
            source = input_path if input_path.is_absolute() else self.workdir / input_path
            if not source.is_file():
                raise RouteWeftError("routing input must be a PBF file")
            if not 0 < source.stat().st_size <= min(self.config.get("max_input_bytes", 512 * 1024**2), 512 * 1024**2):
                raise RouteWeftError("input exceeds routing capacity")
            source_sha = sha256(source)
            if self.config.get("source_sha256") not in (None, source_sha):
                raise RouteWeftError("input does not match reviewed regional snapshot")
        version = capabilities(self.tool) if version is None else version
        if self.policy == 'quarantine_ways' and 'coverage' not in version.get('commands', []):
            raise RouteWeftError('RouteWeft lacks quarantine coverage verification')
        if self.policy not in version.get('invalid_restriction_policies', []):
            raise RouteWeftError('RouteWeft lacks requested restriction policy')
        if self.audit_args:
            from huavd_map_build.production.south.adapter.process.routeweft_contract import AUDIT_LIMITS
            audit_caps = version.get('capabilities', {}).get('restriction_audit', {})
            if not isinstance(audit_caps, dict) or any(
                    type(audit_caps.get(cap)) is not int
                    or audit_caps[cap] < self.config[key]
                    for key, (cap, _) in AUDIT_LIMITS.items() if key in self.config):
                raise RouteWeftError('RouteWeft lacks requested restriction audit capacity')
        if self.external:
            caps = version.get("capabilities", {})
            if (2 not in version.get("dataset_formats", [])
                    or "external" not in caps.get("build_modes", [])
                    or 2 not in caps.get("external_build_formats", [])
                    or self.graph_capacity not in caps.get("graph_capacity_profiles", {})):
                raise RouteWeftError("RouteWeft lacks external/v2 capacity support; reinstall locked tool")
        return {"schema": 1, "config_sha256": self.config_sha256,
                "invalid_restrictions": self.policy, "source_sha256": source_sha,
                "tool": self.tool.identity}

    def preflight(self, input_path: Path):
        return self.build(input_path, preflight_only=True)

    def build(self, input_path: Path, *, preflight_only=False):
        with self.locked():
            source = input_path if input_path.is_absolute() else self.workdir / input_path
            if source.is_symlink() or not source.is_file():
                raise RouteWeftError('input must be a regular non-symlink PBF')
            if not 0 < source.stat().st_size <= min(self.config.get('max_input_bytes', 512*1024*1024), 512*1024*1024):
                raise RouteWeftError('input exceeds routing capacity')
            attempt = Path(tempfile.mkdtemp(prefix=self.session + '-', dir=self.workdir / 'staging/routing'))
            started = time.monotonic()
            try:
                before = sha256(source)
                accepted = self.config.get('source_sha256')
                if accepted is not None and before != accepted:
                    raise RouteWeftError('input does not match reviewed regional snapshot')
                frozen = attempt / 'source.osm.pbf'
                shutil.copyfile(source, frozen)
                frozen.chmod(0o444)
                if sha256(frozen) != before or sha256(source) != before:
                    raise RouteWeftError('input changed during freeze')
                from huavd_map_build.production.south.adapter.process.routeweft_input import provenance
                input_provenance = provenance(frozen)
                version = capabilities(self.tool)
                self.check(version=version)
                arguments = ['--input', str(frozen), '--profile', 'driving',
                             '--invalid-restrictions', self.policy,
                             '--invalid-maxspeed', self.maxspeed_policy, '--json', *self.audit_args]
                dataset = attempt / 'dataset'
                if self.external:
                    preflight = {'mode': 'external-build-validation'}
                    arguments += ['--builder', 'external', '--format', '2', *self.capacity_args,
                                  '--scratch-dir', str(attempt / 'scratch'), '--max-scratch-bytes',
                                  str(self.config.get('max_scratch_bytes', 16 * 1024**3))]
                else:
                    preflight = self.tool.call('preflight', arguments, self.config.get(
                        'preflight_timeout_s', self.config['build_timeout_s']))
                    report = build_report(preflight, before, self.policy, review=self.review, maxspeed_policy=self.maxspeed_policy)
                    write_json(attempt / 'preflight.json', preflight)
                    if sha256(frozen) != before:
                        raise RouteWeftError('frozen input changed during preflight')
                    if preflight_only:
                        return {'schema': 1, 'tool': self.tool.identity, 'capabilities': version,
                                'input_provenance': input_provenance, 'attempt': str(attempt), **preflight}
                built = self.tool.call('build', [*arguments, '--output', str(dataset)],
                                       self.config.get('preflight_timeout_s', self.config['build_timeout_s'])
                                       if preflight_only else self.config['build_timeout_s'])
                write_json(attempt / 'build-result.json', built)
                manifest = self.verify_dataset(dataset, before)
                if built.get('manifest') != manifest:
                    raise RouteWeftError('build/verify manifest mismatch')
                actual_report = build_report(built, before, self.policy, manifest=manifest, review=self.review, maxspeed_policy=self.maxspeed_policy)
                if self.external:
                    if built.get('build', {}).get('builder') != 'external':
                        raise RouteWeftError('external build identity missing')
                    report = actual_report
                elif audit_identity(actual_report) != audit_identity(report):
                    raise RouteWeftError('preflight/build report mismatch')
                if sha256(frozen) != before:
                    raise RouteWeftError('frozen input changed during build')
                if preflight_only:
                    result = {'schema': 1, 'status': 'ok', 'mode': 'external-build-validation',
                              'tool': self.tool.identity, 'capabilities': version,
                              'input_provenance': input_provenance, 'attempt': str(attempt),
                              'report': report, 'build_result': built}
                    write_json(attempt / 'preflight.json', result)
                    return result
                inspect = self.tool.call('inspect', ['--dataset', str(dataset), '--json', *self.capacity_args], self.config['verify_timeout_s'])
                if inspect.get('manifest') != manifest:
                    raise RouteWeftError('inspect manifest mismatch')
                smoke = self.smoke(dataset, manifest, report['applied_blocked_way_ids']
                                   if self.policy == 'quarantine_ways' else None)
                if sha256(frozen) != before:
                    raise RouteWeftError('frozen input changed during build')
                build = {'schema': 1, 'tool': self.tool.identity, 'source_sha256': before,
                         'source_bytes': frozen.stat().st_size, 'source_snapshot': manifest.get('source_snapshot'),
                         'manifest': manifest, 'inspect': inspect, 'elapsed_s': time.monotonic() - started}
                build['input_provenance'] = input_provenance
                build.update({'capabilities': version, 'invalid_restrictions': self.policy,
                              'restriction_review': self.review, 'graph_capacity': self.graph_capacity,
                              'invalid_maxspeed': self.maxspeed_policy,
                              'preflight': preflight, 'build_result': built})
                # Receipts live inside immutable version, so failed rebuilds cannot invalidate old ready.
                write_json(dataset / 'routing-build.json', build)
                write_json(dataset / 'routing-smoke.json', smoke)
                write_json(dataset / 'routing-process.json', getattr(self.tool, 'logs', []))
                destination = self.outputs / f'{self.session}.routing' / manifest['dataset_id']
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if file_records(destination).get(self.graph_file) != file_records(dataset).get(self.graph_file):
                        raise RouteWeftError('immutable dataset collision')
                    # Reuse only an independently validated existing version.
                    if self.verify_dataset(destination, before) != manifest:
                        raise RouteWeftError('immutable manifest collision')
                    self.smoke(destination, manifest)
                    existing = json.loads((destination / 'routing-build.json').read_text())
                    if (existing.get('invalid_restrictions') != self.policy
                            or audit_identity(existing.get('build_result', {}).get('report', {})) != audit_identity(report)):
                        raise RouteWeftError('immutable restriction audit collision')
                else:
                    os.rename(dataset, destination)
                ready = {'schema': 1, 'dataset_id': manifest['dataset_id'], 'region': self.region,
                         'source_sha256': before, 'tool': self.tool.identity, 'config_sha256': self.config_sha256,
                         'invalid_restrictions': self.policy,
                         'invalid_maxspeed': self.maxspeed_policy,
                         'maxspeed_diagnostics': report['maxspeed_diagnostics'],
                         'blocked_way_ids': report['blocked_way_ids'],
                         'restriction_diagnostics': report['restriction_diagnostics'],
                         'files': file_records(destination)}
                for key in ('planned_blocked_way_ids', 'applied_blocked_way_ids', 'blockways_failure'):
                    if key in report:
                        ready[key] = report[key]
                write_json(self.ready, ready)
                return ready
            except RouteWeftError as error:
                write_json(attempt / 'failure.json', {'error': str(error), 'response': error.response,
                                                      'command': error.command, 'exit_code': error.exit_code,
                                                      'invalid_maxspeed': self.maxspeed_policy})
                response = error.response if isinstance(error.response, dict) else {}
                failure = response.get('error', {})
                failure = failure if isinstance(failure, dict) else {}
                details = failure.get('details', {})
                details = details if isinstance(details, dict) else {}
                blocker = details.get('blockways_failure', {})
                blocker = blocker if isinstance(blocker, dict) else {}
                summary = {'stage': error.command or 'routing-build', 'kind': failure.get('kind'),
                           'relation_id': blocker.get('relation_id'), 'reason': blocker.get('reason'),
                           'attempt': blocker.get('attempt'), 'recoverable': blocker.get('recoverable'),
                           'policy': self.policy, 'source_sha256': details.get('source_sha256'),
                           'evidence': str(attempt / 'failure.json')}
                if blocker.get('reason') == 'NoSafeFromToMember':
                    summary['action'] = '核验源关系，或使用绑定输入 SHA 的显式 quarantine_ways 审核配置；增加预算无法补全角色'
                write_json(attempt / 'failure-summary.json', summary)
                raise RouteWeftError(f'{error}; routing failure summary: {json.dumps(summary, ensure_ascii=False)}',
                                     response=error.response, command=error.command,
                                     exit_code=error.exit_code) from error
            finally:
                write_json(attempt / 'process-log.json', getattr(self.tool, 'logs', []))

    def verify(self, smoke=False):
        with self.locked():
            dataset, manifest, ready = self.current()
            return self.smoke(dataset, manifest) if smoke else ready
