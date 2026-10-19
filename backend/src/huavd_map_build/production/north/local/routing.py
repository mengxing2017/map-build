"""Routing-only build lifecycle. Ready is the sole publication commit point."""
from contextlib import contextmanager
import fcntl
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
                 region: str, day: str, session: str | None = None, config: Path | None = None):
        region_id = RegionId(region)
        default = SessionId.for_build(region_id, BuildDate(day)).value
        self.session = SessionId(session or default).value
        if self.session != default:
            raise RouteWeftError('SESSION must match REGION and YYYYMMDD')
        document = yaml.safe_load((config or root / 'config/routing.yaml').read_text())
        if not isinstance(document, dict) or document.get('schema') != 1:
            raise RouteWeftError('unsupported routing config schema')
        self.config_sha256 = sha256(config or root / 'config/routing.yaml')
        self.config = document.get('regions', {}).get(region)
        if not self.config or self.config.get('enabled') is not True:
            raise RouteWeftError(f'routing region not enabled: {region}')
        if self.config.get('profile') != 'driving':
            raise RouteWeftError('unsupported routing profile')
        for key in ('build_timeout_s', 'verify_timeout_s', 'query_timeout_s'):
            value = self.config.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise RouteWeftError(f'invalid {key}')
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
        if not all(any(q.get('command') == cmd and q.get('expect') == 'ok' for q in queries)
                   for cmd in ('nearest', 'route')):
            raise RouteWeftError('smoke requires successful nearest and route')
        if not any(q.get('expect') == 'NoRoute' for q in queries):
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
        result = self.tool.call('verify', ['--dataset', str(dataset), '--json'],
                                self.config['verify_timeout_s'])
        manifest = result.get('manifest', {})
        if not isinstance(manifest, dict):
            raise RouteWeftError('invalid manifest envelope')
        if result.get('verified') is not True:
            raise RouteWeftError('verify did not confirm integrity')
        if type(manifest.get('format')) is not int or manifest['format'] != 1 or manifest.get('profile') != 'driving-v1':
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

    def smoke(self, dataset, manifest):
        results = []
        for query in self.config['smoke']:
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
            for key, value in self.config.get('query_budget', {}).items():
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
                            raise RouteWeftError(f'route outside reviewed {key} range')
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
        return {'schema': 1, 'dataset_id': manifest['dataset_id'], 'results': results}

    def current(self):
        ready = json.loads(self.ready.read_text())
        if ready.get('schema') != 1 or ready.get('region') != self.region:
            raise RouteWeftError('ready schema/region mismatch')
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
        return dataset, manifest, ready

    def build(self, input_path: Path):
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
                dataset = attempt / 'dataset'  # CLI requires an absent output directory.
                built = self.tool.call('build', ['--input', str(frozen), '--profile', 'driving',
                                                '--output', str(dataset)], self.config['build_timeout_s'])
                manifest = self.verify_dataset(dataset, before)
                if built.get('manifest') != manifest:
                    raise RouteWeftError('build/verify manifest mismatch')
                inspect = self.tool.call('inspect', ['--dataset', str(dataset), '--json'], self.config['verify_timeout_s'])
                if inspect.get('manifest') != manifest:
                    raise RouteWeftError('inspect manifest mismatch')
                smoke = self.smoke(dataset, manifest)
                if sha256(frozen) != before:
                    raise RouteWeftError('frozen input changed during build')
                build = {'schema': 1, 'tool': self.tool.identity, 'source_sha256': before,
                         'source_bytes': frozen.stat().st_size, 'source_snapshot': manifest.get('source_snapshot'),
                         'manifest': manifest, 'inspect': inspect, 'elapsed_s': time.monotonic() - started}
                build['input_provenance'] = input_provenance
                # Receipts live inside immutable version, so failed rebuilds cannot invalidate old ready.
                write_json(dataset / 'routing-build.json', build)
                write_json(dataset / 'routing-smoke.json', smoke)
                write_json(dataset / 'routing-process.json', getattr(self.tool, 'logs', []))
                destination = self.outputs / f'{self.session}.routing' / manifest['dataset_id']
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if file_records(destination).get('graph.json') != file_records(dataset).get('graph.json'):
                        raise RouteWeftError('immutable dataset collision')
                    # Reuse only an independently validated existing version.
                    if self.verify_dataset(destination, before) != manifest:
                        raise RouteWeftError('immutable manifest collision')
                    self.smoke(destination, manifest)
                else:
                    os.rename(dataset, destination)
                ready = {'schema': 1, 'dataset_id': manifest['dataset_id'], 'region': self.region,
                         'source_sha256': before, 'tool': self.tool.identity, 'config_sha256': self.config_sha256,
                         'files': file_records(destination)}
                write_json(self.ready, ready)
                return ready
            finally:
                write_json(attempt / 'process-log.json', getattr(self.tool, 'logs', []))

    def verify(self, smoke=False):
        with self.locked():
            dataset, manifest, ready = self.current()
            return self.smoke(dataset, manifest) if smoke else ready
