"""Original tiny OSM protobuf fixture: disconnected one-way and two-way roads.

No downloaded OSM data and no RouteWeft source/test dependency.
"""
import struct
from pathlib import Path
import sys


def varint(value):
    output = bytearray()
    while value > 127:
        output.append((value & 127) | 128)
        value >>= 7
    return bytes(output) + bytes([value])


def number(field, value):
    return varint(field << 3) + varint(value)


def blob(field, value):
    return varint(field << 3 | 2) + varint(len(value)) + value


def block(kind, payload):
    body = blob(1, payload)
    header = blob(1, kind.encode()) + number(3, len(body))
    return struct.pack('>I', len(header)) + header + body


def generate(path: Path, maxspeed='36', forward=None, backward=None, invalid_restriction=False):
    # Coordinates separated enough to keep radius=20 m queries on their own component.
    coordinates = [(0, 0), (10000, 0), (1000000, 0), (1010000, 0)]
    strings = ['', 'highway', 'residential', 'maxspeed', maxspeed, 'oneway', 'yes']
    directional = []
    for field, value in [('maxspeed:forward', forward), ('maxspeed:backward', backward)]:
        if value is not None:
            directional.append((len(strings), len(strings) + 1))
            strings.extend([field, value])
    relation_strings = len(strings)
    if invalid_restriction:
        strings.extend(['type', 'restriction', 'no_left_turn', 'from', 'to'])
    table = b''.join(blob(1, value.encode()) for value in strings)
    group = b''
    for identity, (lon, lat) in enumerate(coordinates, 1):
        node = number(1, identity * 2) + number(8, lat * 2) + number(9, lon * 2)
        group += blob(1, node)
    for identity, first in [(10, 1), (20, 3)]:
        keys, values = (b'\x01\x03\x05', b'\x02\x04\x06') if first == 1 else (b'\x01\x03', b'\x02\x04')
        keys += b''.join(varint(key) for key, _ in directional)
        values += b''.join(varint(value) for _, value in directional)
        way = (number(1, identity) + blob(2, keys) + blob(3, values)
               + blob(8, varint(first * 2) + varint(2)))
        group += blob(3, way)
    if invalid_restriction:
        # Both from/to refer to existing way 10; the missing via is invalid.
        # Way 20 survives as a separate routable component after conservative exclusion.
        offset = relation_strings
        relation = (number(1, 99)
                    + blob(2, varint(offset) + varint(offset + 1))
                    + blob(3, varint(offset + 1) + varint(offset + 2))
                    + blob(8, varint(offset + 3) + varint(offset + 4))
                    + blob(9, varint(20) + varint(0))
                    + blob(10, varint(1) + varint(1)))
        group += blob(4, relation)
    path.write_bytes(block('OSMHeader', blob(4, b'OsmSchema-V0.6'))
                     + block('OSMData', blob(1, table) + blob(2, group)))


if __name__ == '__main__':
    generate(Path(sys.argv[1]))
