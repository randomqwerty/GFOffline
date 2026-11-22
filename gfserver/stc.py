"""Read the game's static data tables directly from its .stc files.

  stc.table("gun") -> list of row dicts

Files: <game>/GirlsFrontLine_Data/StreamingAssets/Res/Pc/stc/<table id>.stc (written by the
client when it unpacks the data package). Names/fields: data/stc_schema.json
(derived from the client's CmdDef enum and Stc* classes).

Layout (client >= 3020; cf. TableHelper / ByteBuffer, and gfl-data-miner's format_stc):
  uint16 table id | 4 bytes | int32 rows | byte cols | cols x type byte
  | int32 first-section id | int32 data offset   (section index; data read sequentially)
  rows x (cols values)
Types (TableHelper.eDataType): 1 sbyte, 5 int32, 8 int64, 9 float32,
  11 string = byte encoding flag (1 ASCII, else UTF-8) + uint16 length + bytes.
"""
import json
import struct
from functools import lru_cache

from . import config

_TYPE_CODES = {"sbyte": 1, "int": 5, "long": 8, "float": 9, "string": 11}


class StcFormatError(Exception):
    pass


@lru_cache(maxsize=1)
def schema():
    raw = json.loads(config.STC_SCHEMA.read_text("utf-8"))
    return {v["name"]: (int(tid), v["fields"]) for tid, v in raw.items()}


def parse(data, fields, table_id=None, exact_floats=False):
    """Decode one .stc file's bytes into row dicts using the schema's [name, type] list.

    exact_floats keeps float32 values unrounded, so write() reproduces the file byte for byte.
    """
    pos = 0

    def take(fmt):
        nonlocal pos
        v = struct.unpack_from(fmt, data, pos)
        pos += struct.calcsize(fmt)
        return v[0]

    code = take("<H")
    if table_id is not None and code != table_id:
        raise StcFormatError(f"file is table {code}, expected {table_id}")
    pos += 4
    rows = take("<i")
    if rows == 0:
        return []
    cols = take("<B")
    types = [take("<B") for _ in range(cols)]
    expected = [_TYPE_CODES.get(t) for _, t in fields]
    if types != expected:
        raise StcFormatError(f"table {code}: column types {types} do not match schema {expected}")
    pos += 4
    pos = take("<i")

    readers = {
        1: lambda: take("<b"),
        5: lambda: take("<i"),
        8: lambda: take("<q"),
        9: (lambda: take("<f")) if exact_floats else (lambda: float("%.7g" % take("<f"))),  # ~7 digits
    }

    def read_string():
        nonlocal pos
        flag = take("<B")
        n = take("<H")
        raw = data[pos:pos + n]
        pos += n
        return raw.decode("ascii" if flag == 1 else "utf-8", "replace")

    readers[11] = read_string
    names = [name for name, _ in fields]
    out = []
    for _ in range(rows):
        out.append({name: readers[t]() for name, t in zip(names, types)})
    return out


INDEX_STEP = 10   # the section index has one (first-column value, row offset) entry per 10 rows


def write(table_id, fields, rows):
    """Encode row dicts as a .stc file (inverse of parse).

    Header: uint16 id | uint32 bytes that follow | int32 rows | byte cols | types
    | (int32 first-column value, int32 row offset) for rows 0, 10, 20, ... | rows.
    Offsets are from the start of the file. A string is ASCII-flagged (1) when it is pure ASCII.
    """
    codes = [_TYPE_CODES[t] for _, t in fields]
    names = [n for n, _ in fields]
    packers = {1: struct.Struct("<b").pack, 5: struct.Struct("<i").pack,
               8: struct.Struct("<q").pack, 9: struct.Struct("<f").pack}

    def enc(code, v):
        if code != 11:
            if code == 9:
                return packers[9](float(v or 0))
            return packers[code](int(v or 0))
        s = "" if v is None else str(v)
        try:
            raw, flag = s.encode("ascii"), 1
        except UnicodeEncodeError:
            raw, flag = s.encode("utf-8"), 0
        return struct.pack("<BH", flag, len(raw)) + raw

    body = []
    for r in rows:
        body.append(b"".join(enc(c, r.get(n)) for n, c in zip(names, codes)))
    n_index = (len(rows) + INDEX_STEP - 1) // INDEX_STEP
    head_len = 2 + 4 + 4 + (1 + len(codes) + 8 * n_index if rows else 0)
    index, offset = [], head_len
    for i, chunk in enumerate(body):
        if i % INDEX_STEP == 0:
            index.append(struct.pack("<ii", _index_key(rows[i][names[0]], i), offset))
        offset += len(chunk)
    rest = struct.pack("<i", len(rows))
    if rows:
        rest += bytes([len(codes)] + codes) + b"".join(index) + b"".join(body)
    return struct.pack("<HI", table_id, len(rest)) + rest


def _index_key(v, row):
    """Index key: the first-column id, or the 1-based row number when it is not an integer."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return row + 1
    return (v + 2**31) % 2**32 - 2**31


def _ensure_base():
    """Extract the original data package into config.BASE_STC_DIR when it is the source."""
    if config.STC_DIR != config.BASE_STC_DIR or (config.BASE_STC_DIR / "catchdata.dat").exists():
        return
    import zipfile
    found = config.base_package()
    if found is None:
        return
    config.BASE_STC_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(found[0]) as z:
        z.extractall(config.BASE_STC_DIR)


@lru_cache(maxsize=None)
def table(name):
    _ensure_base()
    table_id, fields = schema()[name]
    path = config.STC_DIR / f"{table_id}.stc"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; press Set up in the launcher first")
    return parse(path.read_bytes(), fields, table_id)


# catchdata.dat (next to the .stc files): the remaining static tables (operation_info,
# attendance_info, ...). XOR with a fixed key, then gzip; one {"<name>": [...]} JSON per line.
CATCHDATA_KEY = b"c88d016d261eb80ce4d6e41a510d4048"


@lru_cache(maxsize=1)
def _catchdata():
    import gzip
    _ensure_base()
    path = config.STC_DIR / "catchdata.dat"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; press Set up in the launcher first")
    raw = path.read_bytes()
    plain = gzip.decompress(bytes(b ^ CATCHDATA_KEY[i % len(CATCHDATA_KEY)] for i, b in enumerate(raw)))
    out = {}
    for line in plain.decode("utf-8").splitlines():
        if line.strip():
            out.update(json.loads(line))
    return out


def catch(name):
    """A catchdata table by name, e.g. catch("operation_info") -> list of row dicts. game_config_info comes with the
    launcher's game rule changes (client_settings GAME_CONFIG)."""
    rows = _catchdata()[name]
    if name == "game_config_info":
        rows = _with_rules(rows)
    return rows


_RULES_CACHE = {"key": None, "rows": None, "file": None, "rules": {}}


def _rules():
    """The saved game rule changes, read again when the settings file changes."""
    from . import client_settings, config
    f = config.SETTINGS_FILE
    try:
        stamp = (str(f), f.stat().st_mtime_ns) if f.is_file() else (str(f), None)
    except OSError:
        stamp = (str(f), None)
    if _RULES_CACHE["file"] != stamp:
        try:
            rules = client_settings.load(f).get("game_config") or {} if stamp[1] is not None else {}
        except (client_settings.SettingsError, OSError):
            rules = {}
        _RULES_CACHE.update(file=stamp, rules=rules)
    return _RULES_CACHE["rules"]


def _with_rules(rows):
    rules = _rules()
    if not rules:
        return rows
    key = (id(rows), tuple(sorted(rules.items())))
    if _RULES_CACHE["key"] != key:
        _RULES_CACHE.update(key=key, rows=[dict(r, parameter_value=str(rules[r["parameter_name"]]))
                                           if r["parameter_name"] in rules else r for r in rows])
    return _RULES_CACHE["rows"]
