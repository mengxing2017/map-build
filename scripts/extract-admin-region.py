#!/usr/bin/env python3
"""Extract an audited local OSM administrative polygon using osmium."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundaries', required=True, type=Path)
    parser.add_argument('--relation-id', required=True, type=int)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output-directory', required=True, type=Path)
    args = parser.parse_args()
    matches = []
    with args.boundaries.open() as source:
        for line in source:
            document = json.loads(line)
            if document['id'] == args.relation_id:
                matches.append(document)
    if len(matches) != 1 or not matches[0].get('polys'):
        raise ValueError('expected exactly one nonempty administrative polygon')
    args.output_directory.mkdir(parents=True, exist_ok=True)
    polygon = args.output_directory / 'boundary.geojson'
    output = args.output_directory / 'source.osm.pbf'
    report = args.output_directory / 'extraction.json'
    if any(path.exists() for path in (polygon, output, report)):
        raise ValueError('extraction outputs already exist; select a new directory')
    geometry = {'type': 'MultiPolygon', 'coordinates': matches[0]['polys']}
    points = [point for poly in geometry['coordinates'] for ring in poly for point in ring]
    bounds = [min(p[0] for p in points), min(p[1] for p in points),
              max(p[0] for p in points), max(p[1] for p in points)]
    polygon.write_text(json.dumps({'type': 'FeatureCollection', 'features': [{
        'type': 'Feature', 'properties': {'osm_relation': args.relation_id},
        'geometry': geometry}]}, ensure_ascii=False) + '\n')
    command = ['osmium', 'extract', '--polygon', str(polygon),
               '--strategy=complete_ways', '--output', str(output), str(args.input)]
    subprocess.run(command, check=True)
    def digest(path):
        with path.open('rb') as source:
            return hashlib.file_digest(source, 'sha256').hexdigest()
    document = {'relation_id': args.relation_id, 'bounds': bounds,
                'input': str(args.input.resolve()), 'input_sha256': digest(args.input),
                'boundary_catalog': str(args.boundaries),
                'boundary_catalog_sha256': digest(args.boundaries),
                'boundary_sha256': digest(polygon), 'output': str(output),
                'output_sha256': digest(output), 'output_bytes': output.stat().st_size,
                'strategy': 'complete_ways', 'command': command}
    report.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(document, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
