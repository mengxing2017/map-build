"""Read optional replication provenance from the bounded OSM PBF header only."""
from datetime import datetime, timezone
from pathlib import Path
import struct
import zlib

from huavd_map_build.production.south.port.routeweft import RouteWeftError


def fields(data):
    offset = 0

    def integer():
        nonlocal offset
        value = 0
        for shift in range(0, 70, 7):
            if offset >= len(data):
                raise ValueError('truncated protobuf')
            byte = data[offset]
            offset += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError('oversized varint')

    while offset < len(data):
        tag = integer()
        field, wire = tag >> 3, tag & 7
        if not field:
            raise ValueError('invalid protobuf field')
        if wire == 0:
            yield field, integer()
        elif wire in (1, 2, 5):
            length = integer() if wire == 2 else (8 if wire == 1 else 4)
            end = offset + length
            if end > len(data):
                raise ValueError('truncated protobuf field')
            value, offset = data[offset:end], end
            yield field, value
        else:
            raise ValueError('unsupported protobuf wire type')


def provenance(path: Path):
    try:
        with path.open('rb') as stream:
            size = struct.unpack('>I', stream.read(4))[0]
            if not 0 < size <= 65536:
                raise ValueError('invalid BlobHeader size')
            header = dict(fields(stream.read(size)))
            if header.get(1) != b'OSMHeader' or not 0 < header.get(3, 0) <= 32 * 1024**2:
                raise ValueError('invalid OSM header block')
            content = stream.read(header[3])
            if len(content) != header[3]:
                raise ValueError('truncated header blob')
        blob = dict(fields(content))
        if 1 in blob:
            raw = blob[1]
        elif 3 in blob:
            decoder = zlib.decompressobj()
            raw = decoder.decompress(blob[3], 32 * 1024**2 + 1)
            if len(raw) > 32 * 1024**2 or not decoder.eof:
                raise ValueError('oversized or truncated header compression')
        else:
            raise ValueError('unsupported PBF header compression')
        values = dict(fields(raw))
        timestamp = values.get(32)
        return {
            'replication_timestamp': None if timestamp is None else datetime.fromtimestamp(
                timestamp, timezone.utc).isoformat().replace('+00:00', 'Z'),
            'replication_sequence': values.get(33),
        }
    except (ValueError, TypeError, OverflowError, struct.error, zlib.error) as error:
        raise RouteWeftError(f'invalid PBF provenance header: {error}') from error
