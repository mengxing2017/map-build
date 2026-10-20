"""Independent audit archives; intentionally no install.json or map asset roles."""
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import zipfile

from huavd_map_build.production.north.local.routing import file_records, write_json
from huavd_map_build.production.south.adapter.process.routeweft import sha256
from huavd_map_build.production.south.port.routeweft import RouteWeftError


def unpack(archive: Path, destination: Path, max_bytes=3 * 1024**3, max_entries=100):
    """Extract only unique, bounded, flat regular files into an empty directory."""
    destination.mkdir(exist_ok=False)
    seen, total = set(), 0
    def consume(name, size, stream):
        nonlocal total
        if (not name or '/' in name or '\\' in name or name in ('.', '..')
                or name in seen or len(seen) >= max_entries or size < 0):
            raise RouteWeftError('unsafe or duplicate archive entry')
        seen.add(name)
        total += size
        if total > max_bytes:
            raise RouteWeftError('archive expansion budget exceeded')
        with (destination / name).open('xb') as output:
            remaining = size
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    raise RouteWeftError('truncated archive entry')
                output.write(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise RouteWeftError('archive entry size mismatch')
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                mode = (entry.external_attr >> 16) & 0o170000
                if entry.is_dir() or mode not in (0, 0o100000):
                    raise RouteWeftError('archive links/special files forbidden')
                with source.open(entry) as stream:
                    consume(entry.filename, entry.file_size, stream)
    else:
        with tarfile.open(archive, 'r:gz') as source:
            for entry in source:
                if not entry.isfile():
                    raise RouteWeftError('archive links/special files forbidden')
                with source.extractfile(entry) as stream:
                    consume(entry.name, entry.size, stream)
    return destination


class RoutingDelivery:
    def __init__(self, routing):
        self.routing = routing

    def pack(self, format):
        if format not in ('tar', 'zip', 'both'):
            raise RouteWeftError('invalid routing archive format')
        service = self.routing
        with service.locked():
            dataset, manifest, ready = service.current()
            service.smoke(dataset, manifest)
            with tempfile.TemporaryDirectory(prefix='routing-pack-', dir=service.workdir / 'staging/routing') as temporary:
                stage = Path(temporary) / 'package'
                shutil.copytree(dataset, stage)
                write_json(stage / 'attribution.json', {
                    'attribution': manifest['attribution'], 'source': 'OpenStreetMap contributors',
                    'license': 'ODbL-1.0', 'license_url': 'https://opendatacommons.org/licenses/odbl/1.0/',
                    'notice': 'Audit dataset only. Review ODbL obligations before redistribution. '
                              'RouteWeft executable is not included; project code licensing remains separate.'})
                write_json(stage / 'routing-package.json', {
                    'schema': 1, 'asset_type': 'routing-dataset', 'installable': False,
                    'region': service.region, 'session': service.session,
                    'dataset_id': manifest['dataset_id'], 'format': manifest['format'],
                    'profile': manifest['profile'], 'source_sha256': ready['source_sha256'],
                    'graph_capacity': service.graph_capacity,
                    'invalid_restrictions': service.policy,
                    'invalid_maxspeed': service.maxspeed_policy,
                    'maxspeed_diagnostics': ready['maxspeed_diagnostics'],
                    'restriction_review': service.review,
                    'coverage_notice': ('Invalid restriction ways were conservatively excluded; '
                                        'road coverage and reachability may be reduced.'
                                        if service.policy == 'block_ways' else None),
                    'tool': ready['tool'], 'files': file_records(stage)})
                outputs = []
                for kind in (['tar', 'zip'] if format == 'both' else [format]):
                    suffix = 'tar.gz' if kind == 'tar' else 'zip'
                    archive = Path(temporary) / ('bundle.' + suffix)
                    if kind == 'tar':
                        with tarfile.open(archive, 'w:gz') as stream:
                            for path in sorted(stage.iterdir()):
                                stream.add(path, arcname=path.name, recursive=False)
                    else:
                        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as stream:
                            for path in sorted(stage.iterdir()):
                                stream.write(path, arcname=path.name)
                    extracted = unpack(archive, Path(temporary) / ('unpacked-' + kind))
                    package = json.loads((extracted / 'routing-package.json').read_text())
                    actual = file_records(extracted)
                    del actual['routing-package.json']
                    if actual != package['files'] or 'attribution.json' not in actual:
                        raise RouteWeftError('routing package inventory mismatch')
                    unpacked_manifest = service.verify_dataset(extracted, ready['source_sha256'])
                    if unpacked_manifest != manifest:
                        raise RouteWeftError('unpacked manifest changed')
                    smoke = service.smoke(extracted, unpacked_manifest)
                    output = service.outputs / f'{service.session}.routing.bundle.{suffix}'
                    os.replace(archive, output)
                    receipt = {'schema': 1, 'sha256': sha256(output), 'bytes': output.stat().st_size,
                               'dataset_id': manifest['dataset_id'], 'unpacked_smoke': smoke}
                    write_json(Path(str(output) + '.verified.json'), receipt)
                    outputs.append(str(output))
                return outputs
