"""A small protobuf (proto3) codec driven by data/chess_proto.json (generated from the client).

Messages are plain dicts keyed by field name. Repeated fields are lists; map fields (repeated
"<Outer>.<Inner>Entry" messages with key/value) are dicts. Missing fields encode as nothing and decode
to their default (0, False, "", b"", [], {} or None for a message).
  encode("S_VerifySession", {"result": 0}) -> bytes;  decode("C_VerifySession", data) -> dict
"""
import json
import struct
from functools import lru_cache
from pathlib import Path

INT_TYPES = {3, 4, 5, 13, 14}      # int64, uint64, int32, uint32, enum: plain varints
ZIGZAG = {17, 18}                   # sint32, sint64
FIXED32, FIXED64 = {7, 2}, {6, 1}   # fixed32 / float, fixed64 / double
BOOL, STRING, MESSAGE, BYTES = 8, 9, 11, 12


@lru_cache(maxsize=1)
def schema():
    return json.loads((Path(__file__).resolve().parent.parent / "data" / "chess_proto.json").read_text(encoding="utf-8"))


def enum(name):
    return schema()["enums"][name]


def _fields(msg):
    return schema()["messages"][msg]


def _is_map(type_name):
    return type_name in schema()["map_entries"]


def _varint(n):
    n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _read_varint(data, i):
    shift = n = 0
    while True:
        b = data[i]
        i += 1
        n |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return n, i


def _scalar(ftype, value):
    """(wire type, payload bytes) of one scalar value."""
    if ftype in INT_TYPES:
        return 0, _varint(int(value))
    if ftype in ZIGZAG:
        v = int(value)
        return 0, _varint((v << 1) ^ (v >> 63))
    if ftype == BOOL:
        return 0, _varint(1 if value else 0)
    if ftype in FIXED32:
        return 5, struct.pack("<f", value) if ftype == 2 else struct.pack("<I", int(value) & 0xFFFFFFFF)
    if ftype in FIXED64:
        return 1, struct.pack("<d", value) if ftype == 1 else struct.pack("<Q", int(value) & (1 << 64) - 1)
    if ftype == STRING:
        raw = str(value).encode("utf-8")
        return 2, _varint(len(raw)) + raw
    if ftype == BYTES:
        return 2, _varint(len(value)) + bytes(value)
    raise ValueError(f"field type {ftype}")


def encode(msg, value):
    out = bytearray()
    value = value or {}
    for num, name, ftype, repeated, tname in _fields(msg):
        if name not in value or value[name] is None:
            continue
        v = value[name]
        if ftype == MESSAGE and _is_map(tname):
            items = [{"key": k, "value": x} for k, x in v.items()] if isinstance(v, dict) else v
        else:
            items = v if repeated else [v]
        for item in items:
            if ftype == MESSAGE:
                body = encode(tname, item)
                out += _varint(num << 3 | 2) + _varint(len(body)) + body
            else:
                if not repeated and not item and ftype not in (MESSAGE,):
                    continue                                   # proto3 default: not written
                wire, payload = _scalar(ftype, item)
                out += _varint(num << 3 | wire) + payload
    return bytes(out)


def _signed(n, bits):
    return n - (1 << bits) if n >= 1 << (bits - 1) else n


def _convert(ftype, n):
    if ftype == 5 or ftype == 14:
        return _signed(n & 0xFFFFFFFF, 32)
    if ftype == 3:
        return _signed(n, 64)
    if ftype in ZIGZAG:
        return (n >> 1) ^ -(n & 1)
    if ftype == BOOL:
        return bool(n)
    return n


def default(msg):
    out = {}
    for num, name, ftype, repeated, tname in _fields(msg):
        if ftype == MESSAGE and _is_map(tname):
            out[name] = {}
        elif repeated:
            out[name] = []
        elif ftype == MESSAGE:
            out[name] = None
        elif ftype == BOOL:
            out[name] = False
        elif ftype == STRING:
            out[name] = ""
        elif ftype == BYTES:
            out[name] = b""
        elif ftype in (1, 2):
            out[name] = 0.0
        else:
            out[name] = 0
    return out


def decode(msg, data):
    by_num = {f[0]: f for f in _fields(msg)}
    out = default(msg)
    i, end = 0, len(data)
    while i < end:
        key, i = _read_varint(data, i)
        num, wire = key >> 3, key & 7
        if wire == 0:
            raw, i = _read_varint(data, i)
            vals = [raw]
        elif wire == 1:
            vals, i = [data[i:i + 8]], i + 8
        elif wire == 5:
            vals, i = [data[i:i + 4]], i + 4
        elif wire == 2:
            n, i = _read_varint(data, i)
            vals, i = [data[i:i + n]], i + n
        else:
            raise ValueError(f"wire type {wire}")
        f = by_num.get(num)
        if f is None:
            continue
        _, name, ftype, repeated, tname = f
        for v in vals:
            if ftype == MESSAGE:
                sub = decode(tname, v)
                if _is_map(tname):
                    out[name][sub["key"]] = sub["value"]
                elif repeated:
                    out[name].append(sub)
                else:
                    out[name] = sub
                continue
            if wire == 2 and ftype not in (STRING, BYTES):         # packed repeated scalars
                j, items = 0, []
                while j < len(v):
                    if ftype in FIXED32:
                        items.append(struct.unpack("<f" if ftype == 2 else "<I", v[j:j + 4])[0]); j += 4
                    elif ftype in FIXED64:
                        items.append(struct.unpack("<d" if ftype == 1 else "<Q", v[j:j + 8])[0]); j += 8
                    else:
                        n, j = _read_varint(v, j)
                        items.append(_convert(ftype, n))
                out[name].extend(items)
                continue
            if ftype == STRING:
                val = v.decode("utf-8", "replace")
            elif ftype == BYTES:
                val = bytes(v)
            elif wire == 5:
                val = struct.unpack("<f" if ftype == 2 else "<I", v)[0]
            elif wire == 1:
                val = struct.unpack("<d" if ftype == 1 else "<Q", v)[0]
            else:
                val = _convert(ftype, v)
            if repeated:
                out[name].append(val)
            else:
                out[name] = val
    return out
