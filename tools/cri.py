"""CRI ADX2 sound files: @UTF tables (.acb), AFS2 archives (.awb, inside an .acb), ADX encoding.

The game's music is one .acb per track (Res/Pc/<name>.acb.bytes, resource config "bytesData"),
each with its sound inside (an AFS2 archive in the AwbFile column, HCA-coded). replace_sound()
puts a new sound in: the waveform becomes ADX (CRI's ADPCM, which ADX2 also plays; HCA needs a
psychoacoustic encoder), and the waveform and cue lengths are updated.
"""
import struct

# column storage (flags & 0xF0) and type (flags & 0x0F)
ZERO, CONST, ROW = 0x10, 0x30, 0x50
_FMT = {0: ">B", 1: ">b", 2: ">H", 3: ">h", 4: ">I", 5: ">i", 6: ">Q", 7: ">q", 8: ">f", 9: ">d"}
STRING, DATA = 0xA, 0xB


class CriError(ValueError):
    pass


class Table:
    """An @UTF table: name, columns [(name, flags)], rows [{name: value}]; constant columns keep their
    value in const. Data values are bytes, strings str."""

    def __init__(self, name, columns, rows, const):
        self.name, self.columns, self.rows, self.const = name, columns, rows, const

    def get(self, row, col):
        return self.rows[row].get(col, self.const.get(col))

    def set(self, row, col, value):
        flags = dict(self.columns)[col]
        if flags & 0xF0 == ROW:
            self.rows[row][col] = value
        elif all(i == row for i in range(len(self.rows))) or self.const.get(col) == value:
            self.const[col] = value
        else:                               # a constant that now differs per row
            self.columns = [(n, (f & 0x0F) | ROW if n == col else f) for n, f in self.columns]
            for r in self.rows:
                r[col] = self.const.get(col)
            self.const.pop(col, None)
            self.rows[row][col] = value


def read_utf(data):
    data = bytes(data)
    if data[:4] != b"@UTF":
        raise CriError("not an @UTF table")
    size = struct.unpack_from(">I", data, 4)[0]
    t = data[8:8 + size]
    _, rows_off, str_off, data_off, name_off, ncol, width, nrows = struct.unpack_from(">HHIIIHHI", t, 0)

    def string(off):
        s = t[str_off + off:t.index(b"\0", str_off + off)]
        return s.decode("utf-8", "replace")

    def value(typ, buf, pos):
        if typ == STRING:
            return string(struct.unpack_from(">I", buf, pos)[0]), pos + 4
        if typ == DATA:
            off, n = struct.unpack_from(">II", buf, pos)
            return t[data_off + off:data_off + off + n], pos + 8
        f = _FMT[typ]
        return struct.unpack_from(f, buf, pos)[0], pos + struct.calcsize(f)

    pos, columns, const = 24, [], {}
    for _ in range(ncol):
        flags = t[pos]
        name = string(struct.unpack_from(">I", t, pos + 1)[0])
        pos += 5
        if flags & 0xF0 == CONST:
            const[name], pos = value(flags & 0x0F, t, pos)
        elif flags & 0xF0 == ZERO:
            const[name] = b"" if flags & 0x0F == DATA else "" if flags & 0x0F == STRING else 0
        columns.append((name, flags))
    rows = []
    for r in range(nrows):
        p, row = rows_off + r * width, {}
        for name, flags in columns:
            if flags & 0xF0 == ROW:
                row[name], p = value(flags & 0x0F, t, p)
        rows.append(row)
    return Table(string(name_off), columns, rows, const)


def write_utf(table):
    strings, sidx = bytearray(b"<NULL>\0"), {"<NULL>": 0}
    blobs = bytearray()

    def s(text):
        if text not in sidx:
            sidx[text] = len(strings)
            strings.extend(text.encode("utf-8") + b"\0")
        return sidx[text]

    def blob(b):
        if not b:
            return 0, 0
        while len(blobs) % 32:
            blobs.append(0)
        off = len(blobs)
        blobs.extend(b)
        return off, len(b)

    def enc(typ, v):
        if typ == STRING:
            return struct.pack(">I", s(v))
        if typ == DATA:
            sub = v if isinstance(v, (bytes, bytearray)) else write_utf(v)
            return struct.pack(">II", *blob(sub))
        return struct.pack(_FMT[typ], v)

    name_off = s(table.name)
    cols = bytearray()
    for name, flags in table.columns:
        flags = flags if flags & 0xF0 != ZERO else flags   # zero columns stay zero
        cols += bytes([flags]) + struct.pack(">I", s(name))
        if flags & 0xF0 == CONST:
            cols += enc(flags & 0x0F, table.const[name])
    rows = bytearray()
    width = 0
    for r in table.rows:
        one = b"".join(enc(f & 0x0F, r[n]) for n, f in table.columns if f & 0xF0 == ROW)
        width = len(one)
        rows += one
    rows_off = 24 + len(cols)
    str_off = rows_off + len(rows)
    while (str_off + len(strings)) % 8:
        strings.append(0)
    data_off = str_off + len(strings)
    if blobs:
        pad = (-(data_off + 8)) % 32           # blobs 32-aligned in the file
        strings.extend(b"\0" * pad)
        data_off += pad
    head = struct.pack(">HHIIIHHI", 1, rows_off, str_off, data_off, name_off, len(table.columns), width, len(table.rows))
    body = head + bytes(cols) + bytes(rows) + bytes(strings) + bytes(blobs)
    while len(body) % 8:
        body += b"\0"
    return b"@UTF" + struct.pack(">I", len(body)) + body


# ---------------------------------------------------------------------------- AFS2

def read_afs2(data):
    """{"ids": [...], "files": [bytes], "align": n, "subkey": n, "version": header bytes}"""
    data = bytes(data)
    if data[:4] != b"AFS2":
        raise CriError("not an AFS2 archive")
    ver, osz, isz = data[4], data[5], struct.unpack_from("<H", data, 6)[0]
    count, align, subkey = struct.unpack_from("<IHH", data, 8)
    ids = [int.from_bytes(data[16 + i * isz:16 + (i + 1) * isz], "little") for i in range(count)]
    base = 16 + count * isz
    offs = [int.from_bytes(data[base + i * osz:base + (i + 1) * osz], "little") for i in range(count + 1)]
    files = []
    for i in range(count):
        start = offs[i] + (-offs[i]) % align
        files.append(data[start:offs[i + 1]])
    return {"ids": ids, "files": files, "align": align, "subkey": subkey, "version": ver, "osz": osz, "isz": isz}


def write_afs2(arc):
    ids, files, align, osz, isz = arc["ids"], arc["files"], arc["align"], arc.get("osz", 4), arc.get("isz", 2)
    head = b"AFS2" + bytes([arc.get("version", 1), osz]) + struct.pack("<H", isz)
    head += struct.pack("<IHH", len(ids), align, 0)
    head += b"".join(i.to_bytes(isz, "little") for i in ids)
    table_end = len(head) + (len(files) + 1) * osz
    offs, body, pos = [], bytearray(), table_end
    for f in files:
        offs.append(pos)
        pad = (-pos) % align
        body += b"\0" * pad + f
        pos += pad + len(f)
    offs.append(pos)
    return head + b"".join(o.to_bytes(osz, "little") for o in offs) + bytes(body)


# ---------------------------------------------------------------------------- ADX

def _coefs(rate, cutoff=500):
    import math
    a = math.sqrt(2) - math.cos(2 * math.pi * cutoff / rate)
    b = math.sqrt(2) - 1
    c = (a - math.sqrt((a + b) * (a - b))) / b
    return int(c * 8192), int(-(c * c) * 4096)


def encode_adx(pcm, rate, cutoff=500, loop=False):
    """ADX (type 3, 4-bit, 18-byte frames; loop: the whole track repeats) from int16 samples, a numpy array (samples, channels).
    ADPCM is sequential: the track is cut into segments encoded side by side, then encoded twice more
    with each segment starting where the decoder really is after the segment before it."""
    import numpy as np
    pcm = np.asarray(pcm, dtype=np.int64)
    if pcm.ndim == 1:
        pcm = pcm[:, None]
    n, ch = pcm.shape
    c1, c2 = _coefs(rate, cutoff)
    frames = max(1, (n + 31) // 32)
    segs = max(1, min(4096, frames // 8))
    per = -(-frames // segs) * 32                 # samples per segment, whole frames
    x = np.zeros((segs * per, ch), dtype=np.int64)
    x[:n] = pcm
    body = np.zeros((frames, ch, 18), dtype=np.uint8)
    for k in range(ch):
        sig = x[:, k]
        prev1 = np.concatenate(([0], sig[:-1]))
        prev2 = np.concatenate(([0, 0], sig[:-2]))
        resid = np.abs(sig - ((c1 * prev1 + c2 * prev2) >> 12)).reshape(-1, 32).max(axis=1)
        scale = np.clip(-(-resid // 7), 1, 0x1FFF).reshape(segs, per // 32)
        seg = sig.reshape(segs, per)
        s1 = np.concatenate(([0], seg[:-1, -1]))
        s2 = np.concatenate(([0], seg[:-1, -2]))
        q = np.zeros((segs, per), dtype=np.int64)
        for _ in range(3):
            a1, a2 = s1.copy(), s2.copy()
            for t in range(per):
                pred = (c1 * a1 + c2 * a2) >> 12
                sc = scale[:, t // 32]
                qq = np.clip(np.rint((seg[:, t] - pred) / sc), -8, 7).astype(np.int64)
                q[:, t] = qq
                a2, a1 = a1, np.clip(pred + qq * sc, -32768, 32767)
            s1 = np.concatenate(([0], a1[:-1]))
            s2 = np.concatenate(([0], a2[:-1]))
        nib = (q.reshape(-1, 32) & 0xF).astype(np.uint8)[:frames]
        sc = scale.reshape(-1)[:frames]
        body[:, k, 0] = sc >> 8
        body[:, k, 1] = sc & 0xFF
        body[:, k, 2:] = (nib[:, 0::2] << 4) | nib[:, 1::2]
    data_off = 0x40
    head = struct.pack(">HH", 0x8000, data_off - 4) + bytes([3, 18, 4, ch]) + struct.pack(">IIH", rate, n, cutoff)
    head += bytes([3, 0]) + struct.pack(">HHI", 0, int(loop), int(loop))
    head += struct.pack(">IIII", 0, data_off, n if loop else 0, data_off + frames * ch * 18 if loop else 0)
    head += bytes(data_off - 6 - len(head)) + b"(c)CRI"
    footer = struct.pack(">HH", 0x8001, 14) + bytes(14)
    return head + body.tobytes() + footer


def decode_adx(data):
    """int16 samples (samples, channels) and the rate of an ADX file made by encode_adx (for tests)."""
    import numpy as np
    data = bytes(data)
    off = struct.unpack_from(">H", data, 2)[0] + 4
    ch, rate, n, cutoff = data[7], *struct.unpack_from(">IIH", data, 8)
    c1, c2 = _coefs(rate, cutoff)
    frames = (n + 31) // 32
    out = np.zeros((frames * 32, ch), dtype=np.int16)
    hist = [[0, 0] for _ in range(ch)]
    for f in range(frames):
        for k in range(ch):
            p = off + (f * ch + k) * 18
            scale = struct.unpack_from(">H", data, p)[0]
            s1, s2 = hist[k]
            for i in range(32):
                byte = data[p + 2 + i // 2]
                q = (byte >> 4) if i % 2 == 0 else byte & 0xF
                q = q - 16 if q >= 8 else q
                y = max(-32768, min(32767, ((c1 * s1 + c2 * s2) >> 12) + q * scale))
                out[f * 32 + i, k] = y
                s2, s1 = s1, y
            hist[k] = [s1, s2]
    return out[:n], rate


# ---------------------------------------------------------------------------- ACB

def acb_info(raw):
    """{"cues": [names], "waveforms": n, "seconds": length of the first cue, "embedded": bool}"""
    acb = read_utf(raw)
    names = read_utf(acb.get(0, "CueNameTable"))
    cues = read_utf(acb.get(0, "CueTable"))
    waves = read_utf(acb.get(0, "WaveformTable"))
    length = cues.get(0, "Length") if cues.rows and "Length" in dict(cues.columns) else 0
    return {"cues": [names.get(i, "CueName") for i in range(len(names.rows))], "waveforms": len(waves.rows),
            "seconds": (length or 0) / 1000, "embedded": bool(acb.get(0, "AwbFile"))}


def adx_info(adx):
    """{"channels", "rate", "samples", "loop"} of an ADX file."""
    adx = bytes(adx)
    if adx[:2] != bytes([0x80, 0]) or adx[4] != 3:
        raise CriError("not an ADX sound")
    ch, (rate, n) = adx[7], struct.unpack_from(">II", adx, 8)
    loop = adx[0x12] == 3 and struct.unpack_from(">H", adx, 2)[0] + 4 >= 0x2C + 6 and struct.unpack_from(">I", adx, 0x18)[0]
    return {"channels": ch, "rate": rate, "samples": n, "loop": bool(loop)}


def set_loop(adx, on):
    """An ADX made by encode_adx with its loop (the whole sound) switched on or off."""
    adx = bytearray(adx)
    info = adx_info(adx)
    data_off = struct.unpack_from(">H", adx, 2)[0] + 4
    end = data_off + -(-info["samples"] // 32) * 18 * info["channels"]
    struct.pack_into(">HI", adx, 0x16, int(on), int(on))
    struct.pack_into(">IIII", adx, 0x1C, 0, data_off if on else 0, info["samples"] if on else 0, end if on else 0)
    return bytes(adx)


def replace_sound(raw, adx):
    """The .acb with every waveform's sound replaced by an ADX sound (encode_adx); it loops (the whole
    sound) where the old waveform looped. Only .acbs with their sound inside (AwbFile) can be changed."""
    info = adx_info(adx)
    n, ch, rate = info["samples"], info["channels"], info["rate"]
    acb = read_utf(raw)
    awb = acb.get(0, "AwbFile")
    if not awb:
        raise CriError("this sound file streams its sound from elsewhere and can't be changed")
    arc = read_afs2(awb)
    waves = read_utf(acb.get(0, "WaveformTable"))
    cols = dict(waves.columns)
    loop = any(waves.get(i, "LoopFlag") for i in range(len(waves.rows))) if "LoopFlag" in cols else False
    adx = set_loop(adx, loop)
    arc["files"] = [adx for _ in arc["files"]]
    acb.set(0, "AwbFile", write_afs2(arc))
    for i in range(len(waves.rows)):
        for col, v in (("EncodeType", 0), ("NumChannels", ch), ("SamplingRate", rate), ("NumSamples", n)):
            if col in cols:
                waves.set(i, col, v)
    acb.set(0, "WaveformTable", write_utf(waves))
    ext = acb.get(0, "WaveformExtensionDataTable") if "WaveformExtensionDataTable" in dict(acb.columns) else b""
    if ext:
        t = read_utf(ext)
        for i in range(len(t.rows)):
            t.set(i, "LoopStart", 0)
            t.set(i, "LoopEnd", n)
        acb.set(0, "WaveformExtensionDataTable", write_utf(t))
    cues = read_utf(acb.get(0, "CueTable"))
    if "Length" in dict(cues.columns):
        for i in range(len(cues.rows)):
            if cues.get(i, "Length") != 0xFFFFFFFF:            # 0xFFFFFFFF: loops forever
                cues.set(i, "Length", int(n * 1000 // rate))
        acb.set(0, "CueTable", write_utf(cues))
    return write_utf(acb)


def rename_acb(raw, name):
    """An .acb (one cue) under a new name: the file's Name, its cue's name and a GUID of its own."""
    import hashlib
    acb = read_utf(raw)
    names = read_utf(acb.get(0, "CueNameTable"))
    if len(names.rows) != 1:
        raise CriError("only a sound file with one cue can be copied")
    names.set(0, "CueName", name)
    acb.set(0, "CueNameTable", write_utf(names))
    acb.set(0, "Name", name)
    if "AcbGuid" in dict(acb.columns):
        acb.set(0, "AcbGuid", hashlib.md5(("gfmod" + name).encode()).digest())
    return write_utf(acb)


def read_wav(raw):
    """(int16 samples (samples, channels), rate) of a PCM .wav (8/16/24/32-bit or float)."""
    import io
    import numpy as np
    raw = bytes(raw)
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise CriError("not a WAV file")
    pos, fmt, data = 12, None, None
    while pos + 8 <= len(raw):
        cid, n = raw[pos:pos + 4], struct.unpack_from("<I", raw, pos + 4)[0]
        body = raw[pos + 8:pos + 8 + n]
        if cid == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", body, 0)
        elif cid == b"data":
            data = body
        pos += 8 + n + (n & 1)
    if not fmt or data is None:
        raise CriError("the WAV file has no sound in it")
    tag, ch, rate, _, _, bits = fmt
    if tag == 0xFFFE:
        tag = 3 if bits == 32 and False else 1
    if tag == 3:
        x = np.frombuffer(data[:len(data) // 4 * 4], dtype="<f4")
        x = np.clip(x * 32767, -32768, 32767).astype(np.int16)
    elif bits == 16:
        x = np.frombuffer(data[:len(data) // 2 * 2], dtype="<i2")
    elif bits == 8:
        x = ((np.frombuffer(data, dtype=np.uint8).astype(np.int16) - 128) << 8)
    elif bits == 24:
        b = np.frombuffer(data[:len(data) // 3 * 3], dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        x = ((b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) << 8 >> 16).astype(np.int16)
    elif bits == 32:
        x = (np.frombuffer(data[:len(data) // 4 * 4], dtype="<i4") >> 16).astype(np.int16)
    else:
        raise CriError(f"{bits}-bit WAV files aren't supported")
    x = x[:len(x) // ch * ch].reshape(-1, ch)
    return x, rate
