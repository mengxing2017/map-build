"""Sample already CLI-verified graphs without loading a regional graph into Python."""
import json
import struct

from huavd_map_build.production.south.port.routeweft import RouteWeftError


def sample_edges(dataset):
    binary = dataset / 'graph.bin'
    if not binary.exists():
        graph = json.loads((dataset / 'graph.json').read_text())
        for edge in graph.get('edges', []):
            yield graph['nodes'][edge['from']], graph['nodes'][edge['to']], edge.get('distance_mm', 0)
        return
    with binary.open('rb') as stream:
        def read(size):
            data = stream.read(size)
            if len(data) != size:
                raise RouteWeftError('truncated v2 graph sample')
            return data
        magic, flags, nodes, edges, restrictions, strings, references, dictionary = struct.unpack('<8s7Q', read(64))
        if (magic != b'RWFTG002' or flags or nodes > 8_000_000 or edges > 16_000_000
                or binary.stat().st_size != 64 + dictionary + 16 * nodes + 56 * edges + 4 * restrictions + 8 * references):
            raise RouteWeftError('invalid v2 graph sample header')
        node_start = 64 + dictionary
        edge_start = node_start + 16 * nodes
        for index in range(edges):
            stream.seek(edge_start + index * 56)
            source, target, _, distance, _, _, _, _ = struct.unpack('<QQqQQIIQ', read(56))
            if source >= nodes or target >= nodes:
                raise RouteWeftError('invalid v2 graph sample node')
            if source == target or distance < 10000:
                continue
            points = []
            for node in (source, target):
                stream.seek(node_start + node * 16)
                lon, lat = struct.unpack('<dd', read(16))
                points.append({'lon': lon, 'lat': lat})
            yield *points, distance
