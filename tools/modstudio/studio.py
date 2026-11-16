"""Mod Studio: a local web interface for making mods (units, enemies, teams, maps, skills).

  python tools/modstudio/studio.py [port]      then open http://127.0.0.1:8770/

Reads the original tables from the archived data package plus every mod in mods/, and writes
mod files (mods/<name>/mod.json, tables/<table>.json) in the format gfserver/mods.py builds.
Building runs tools/build_mods.py. Only listens on 127.0.0.1.

Entities and the rows they own:
  unit     gun row (+ text, grant)                    sangvis  sangvis row (+ text, grant)
  enemy    enemy_character_type row (+ text)          team     enemy_team row + enemy_in_team rows
  map      mission row + spot rows + map_rules (spawn tables) (+ text, grant)
  skill    battle_skill_config rows of one skill group (one per level) (+ text)
  row      any other table row (buffs, buildings, win conditions, ...)
"""
import json
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent.parent
sys.path.insert(0, str(SERVER))
from gfserver import mods, stc  # noqa: E402

STATIC = HERE / "static"
GUIDE = SERVER.parent / "doc" / "stc-guide"
CACHE = SERVER / "build" / "modstudio"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8770

# First id tried for new rows (the unmodded data leaves these free; see mods/README.md).
FREE_FROM = {
    "gun": 8001, "sangvis": 8001, "enemy_character_type": 7000001, "enemy_team": 80000001,
    "enemy_in_team": 80000001, "mission": 800001, "spot": 8000001, "battle_skill_config": 900000101,
    "battle_buff": 7000001, "mission_win_type_config": 80000001, "building": 95000001,
    "sangvis_resolution": 800100, "battle_formula": 7000001, "battle_watch": 7000001, "battle_watch_trigger": 7000001,
}
SKILL_GROUP_FROM = 9000001

# Text keys owned by an entity: field -> key prefix digit (gun-1xxxxxxx = name, ...).
TEXT_FIELDS = {
    "gun": {"name": "1", "extra": "4", "en_introduce": "5"},
    "sangvis": {"name": "1", "en_introduce": "3"},
    "enemy_character_type": {"name": "2", "character": "1"},
    "mission": {"name": "1", "mission_describe": "2"},
    "battle_skill_config": {"name": "1", "description": "2", "lvup_description": "3"},
}

LOCK = threading.RLock()


def text_key(table, field, row_id):
    digit = TEXT_FIELDS[table][field]
    return f"{table}-{digit}{int(row_id):07d}"


# ---------------------------------------------------------------------------- base data

class Base:
    """The original tables (archived data package) and text, parsed on first use."""

    def __init__(self):
        self.pkg, self.version = mods.base_package()
        self._zip = zipfile.ZipFile(self.pkg)
        self._tables = {}
        self._text = None
        self._cd = None

    def table(self, name):
        if name not in self._tables:
            tid, fields = stc.schema()[name]
            self._tables[name] = stc.parse(self._zip.read(f"{tid}.stc"), fields, tid, exact_floats=True)
        return self._tables[name]

    def catchdata(self):
        if self._cd is None:
            out = {}
            for line in mods.read_catchdata(self._zip.read("catchdata.dat")):
                out.update(json.loads(line))
            self._cd = out
        return self._cd

    def text(self):
        """{key: text} from the assettexttable bundle (gfserver/game_text.py)."""
        if self._text is None:
            from gfserver import game_text
            self._text = game_text.load()
        return self._text


BASE = None


def base():
    global BASE
    if BASE is None:
        BASE = Base()
    return BASE


# ---------------------------------------------------------------------------- mod files

def mod_dir(name):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name or ""):
        raise ValueError("mod names use letters, digits, - and _")
    return mods.MODS_DIR / name


_CACHE = {"stamp": None, "data": {}}


def _stamp():
    """Changes whenever any mod file changes (or a mod is added/removed)."""
    if not mods.MODS_DIR.is_dir():
        return ()
    return tuple(sorted((str(f), f.stat().st_mtime_ns, f.stat().st_size)
                        for f in mods.MODS_DIR.rglob("*.json")))


def cached(key, fn):
    st = _stamp()
    if _CACHE["stamp"] != st:
        _CACHE["stamp"], _CACHE["data"] = st, {}
    if key not in _CACHE["data"]:
        _CACHE["data"][key] = fn()
    return _CACHE["data"][key]


def load_mod(name):
    """A mod's own content (a fresh copy; safe to modify)."""
    return json.loads(json.dumps(cached(("mod", name), lambda: _load_mod(name))))


def _load_mod(name):
    """A mod's own content: {"meta": mod.json without tables, "tables": {t: rows}, "catchdata": {...}}."""
    d = mod_dir(name)
    meta = json.loads((d / "mod.json").read_text("utf-8")) if (d / "mod.json").is_file() else {}
    tables = {t: list(r) for t, r in (meta.pop("tables", None) or {}).items()}
    for f in sorted((d / "tables").glob("*.json")) if (d / "tables").is_dir() else []:
        tables[f.stem] = tables.get(f.stem, []) + json.loads(f.read_text("utf-8"))
    cd = {t: list(r) for t, r in (meta.pop("catchdata", None) or {}).items()}
    for f in sorted((d / "catchdata").glob("*.json")) if (d / "catchdata").is_dir() else []:
        cd[f.stem] = cd.get(f.stem, []) + json.loads(f.read_text("utf-8"))
    meta.setdefault("name", name)
    meta.setdefault("version", "1")
    meta["enabled"] = mods.is_enabled(d, meta)          # the player's choice (mods/_enabled.json) first
    for k in ("text", "grant", "map_rules"):
        meta.setdefault(k, {})
    return {"meta": meta, "tables": tables, "catchdata": cd}


def save_mod(name, mod):
    """Write mod.json (no inline rows) and one tables/<t>.json per table; empty tables are removed."""
    d = mod_dir(name)
    (d / "tables").mkdir(parents=True, exist_ok=True)
    meta = dict(mod["meta"])
    for k in ("text", "grant", "map_rules"):
        if not meta.get(k):
            meta.pop(k, None)
    (d / "mod.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", "utf-8")
    for t, rows in mod["tables"].items():
        f = d / "tables" / f"{t}.json"
        if rows:
            body = "[\n" + ",\n".join(" " + json.dumps(r, ensure_ascii=False) for r in rows) + "\n]\n"
            f.write_text(body, "utf-8")
        elif f.exists():
            f.unlink()
    if mod["catchdata"]:
        (d / "catchdata").mkdir(exist_ok=True)
        for t, rows in mod["catchdata"].items():
            (d / "catchdata" / f"{t}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", "utf-8")


def all_mod_names():
    if not mods.MODS_DIR.is_dir():
        return []
    return sorted(p.name for p in mods.MODS_DIR.iterdir()
                  if p.is_dir() and not p.name.startswith((".", "_")) and (p / "mod.json").is_file())


# ---------------------------------------------------------------------------- the merged world

def key_of(table):
    return stc.schema()[table][1][0][0]


def world_table(table, exclude=None):
    """Base rows with every mod applied (folder order), optionally leaving one mod out."""
    return cached(("world", table, exclude), lambda: _world_table(table, exclude))


def _world_table(table, exclude):
    rows = base().table(table)
    fields = stc.schema()[table][1]
    for name in all_mod_names():
        if name == exclude:
            continue
        patches = load_mod(name)["tables"].get(table)
        if patches:
            try:
                rows, _ = mods.apply_rows(table, rows, patches, fields)
            except mods.ModError:
                pass        # shown when that mod is opened or built
    return rows


def world_index(table, exclude=None):
    k = key_of(table)
    return cached(("index", table, exclude), lambda: {str(r[k]): r for r in world_table(table, exclude)})


def world_text(exclude=None):
    return cached(("text", exclude), lambda: _world_text(exclude))


def _world_text(exclude):
    text = dict(base().text())
    for name in all_mod_names():
        if name != exclude:
            text.update(load_mod(name)["meta"].get("text") or {})
    return text


def used_ids(table):
    """Keys used by the base data or by any mod (so new ids never collide)."""
    return cached(("used", table), lambda: _used_ids(table))


def _used_ids(table):
    k = key_of(table)
    ids = {str(r[k]) for r in base().table(table)}
    for name in all_mod_names():
        ids |= {str(r.get(k)) for r in load_mod(name)["tables"].get(table, [])}
    return ids


def free_ids(table, count=1, start=None, step=1):
    used = used_ids(table)
    i = int(start if start is not None else FREE_FROM.get(table, 1))
    out = []
    while len(out) < count:
        if str(i) not in used:
            out.append(i)
        i += step
    return out


def free_skill_group():
    groups = {int(r["skill_group_id"]) for r in world_table("battle_skill_config")}
    for name in all_mod_names():
        groups |= {int(r.get("skill_group_id") or 0) for r in load_mod(name)["tables"].get("battle_skill_config", [])}
    g = SKILL_GROUP_FROM
    while g in groups:
        g += 1
    return g


# ---------------------------------------------------------------------------- field docs

def parse_guide():
    """{table: {"groups": [[title, [fields]]], "docs": {field: text}}} from doc/stc-guide/*.md."""
    out = {}
    if not GUIDE.is_dir():
        return out
    for f in sorted(GUIDE.glob("[0-9]*.md")):
        table = group = None
        for line in f.read_text("utf-8").splitlines():
            m = re.match(r"^## `?([a-z0-9_]+)`?\s*$", line)
            if m:
                table, group = m.group(1), None
                out.setdefault(table, {"groups": [], "docs": {}})
                continue
            if line.startswith("## "):
                table = None
                continue
            if table is None:
                continue
            m = re.match(r"^### (.+)$", line)
            if m:
                group = re.sub(r"[`*]", "", m.group(1)).strip()
                continue
            fields = []
            text = ""
            if line.startswith("|") and not re.match(r"^\|\s*-", line):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 2:
                    fields = re.findall(r"`([a-z0-9_]+)`", cells[0])
                    text = " | ".join(cells[1:])
            elif group and "not used" in group.lower():
                fields = re.findall(r"`([a-z0-9_]+)`", line)
                text = "Not used by the game client."
            if not fields:
                continue
            text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text).replace("**", "")
            entry = out[table]
            title = group or "Fields"
            if not entry["groups"] or entry["groups"][-1][0] != title:
                entry["groups"].append([title, []])
            for fld in fields:
                if fld not in entry["docs"]:
                    entry["docs"][fld] = text
                    entry["groups"][-1][1].append(fld)
    return out


GUIDE_CACHE = None


def guide():
    global GUIDE_CACHE
    if GUIDE_CACHE is None:
        GUIDE_CACHE = parse_guide()
    return GUIDE_CACHE


# ---------------------------------------------------------------------------- catalogs

def decode_text(v):
    """Stored text (//n line breaks, //c commas) as plain text."""
    return str(v or "").replace("//n", "\n").replace("//c", ",")


def text_of(text, key):
    return decode_text(text.get(str(key or ""), "")) if key else ""


def catalog(kind):
    text = world_text()
    if kind == "gun":
        return [{"id": r["id"], "name": text_of(text, r["name"]) or r["en_name"], "code": r["code"],
                 "type": r["type"], "rank": r["rank"]} for r in world_table("gun")]
    if kind == "sangvis":
        return [{"id": r["id"], "name": text_of(text, r["name"]) or r["en_name"], "code": r["code"],
                 "type": r["type"]} for r in world_table("sangvis")]
    if kind == "enemy":
        return [{"id": r["id"], "name": text_of(text, r["name"]) or r["code"], "code": r["code"],
                 "type": r["type"], "level": r["level"]} for r in world_table("enemy_character_type")]
    if kind == "team":
        enemies = world_index("enemy_character_type")
        counts = {}
        for r in world_table("enemy_in_team"):
            counts[r["enemy_team_id"]] = counts.get(r["enemy_team_id"], 0) + 1
        out = []
        for r in world_table("enemy_team"):
            lead = enemies.get(str(r["enemy_leader"])) or {}
            out.append({"id": r["id"], "leader": r["enemy_leader"],
                        "name": text_of(text, lead.get("name")) or lead.get("code", ""),
                        "members": counts.get(r["id"], 0)})
        return out
    if kind == "mission":
        return [{"id": r["id"], "name": text_of(text, r["name"]), "campaign": r["campaign"], "sub": r["sub"],
                 "kind": r["if_emergency"]} for r in world_table("mission")]
    if kind == "skill":
        seen = {}
        for r in world_table("battle_skill_config"):
            g = r["skill_group_id"]
            if g not in seen:
                seen[g] = {"id": g, "name": text_of(text, r["name"]), "code": r["code"], "levels": 0}
            seen[g]["levels"] += 1
        return list(seen.values())
    if kind == "story":
        import content
        return [{"id": n, "name": n} for n in sorted(content.originals())]
    if kind == "event_image":
        import content
        return [{"id": n, "name": n} for n in content.event_images()]
    raise KeyError(kind)


# ---------------------------------------------------------------------------- entities

def strip_row(row, table, against=None):
    """The fields to store: the differences from `against` (a full row), else non-default fields."""
    fields = stc.schema()[table][1]
    k = fields[0][0]
    out = {k: row[k]}
    for f, t in fields[1:]:
        v = row.get(f, "" if t == "string" else 0)
        if against is not None:
            if str(v) != str(against.get(f, "" if t == "string" else 0)):
                out[f] = v
        elif v not in ("", 0, 0.0, None, "0"):
            out[f] = v
    return out


def stored_row(table, row, copy_from, mod_name):
    """How an edited full row is written: override of a row that exists without this mod,
    else _copy + differences from the template, else non-default fields."""
    k = key_of(table)
    others = world_index(table, exclude=mod_name)
    existing = others.get(str(row[k]))
    if existing is not None:
        return strip_row(row, table, existing)
    if copy_from not in (None, "") and str(copy_from) in others:
        out = strip_row(row, table, others[str(copy_from)])
        return dict({k: out.pop(k), "_copy": int(copy_from) if str(copy_from).lstrip("-").isdigit() else copy_from}, **out)
    return strip_row(row, table)


def unchanged_override(table, stored, mod_name):
    """True for a stored row that only names an existing row and changes nothing."""
    k = key_of(table)
    return set(stored) == {k} and str(stored[k]) in world_index(table, exclude=mod_name)


def put_rows(mod, table, rows, remove_keys=()):
    """Replace or add rows (stored form) in a mod's table; remove_keys drops rows first."""
    k = key_of(table)
    lst = [r for r in mod["tables"].get(table, []) if str(r.get(k)) not in {str(x) for x in remove_keys}]
    index = {str(r.get(k)): i for i, r in enumerate(lst)}
    for r in rows:
        if str(r[k]) in index:
            lst[index[str(r[k])]] = r
        else:
            index[str(r[k])] = len(lst)
            lst.append(r)
    mod["tables"][table] = lst


def own_texts(table, row, texts, mod):
    """Point the row's text fields at this mod's own keys and store the given texts. A text
    that equals what the row's current key already shows is left alone (no rename)."""
    k = key_of(table)
    current = world_text()
    for field in TEXT_FIELDS.get(table, {}):
        key = text_key(table, field, row[k])
        if field in texts and key not in mod["meta"]["text"] and texts[field] == text_of(current, row.get(field)):
            continue
        if field in texts:
            if texts[field] in (None, ""):
                mod["meta"]["text"].pop(key, None)
                row[field] = ""
            else:
                row[field] = key
                mod["meta"]["text"][key] = texts[field]


def set_grant(mod, kind, unit_id, entry):
    lst = [e for e in mod["meta"]["grant"].get(kind, []) if int(e["id"] if isinstance(e, dict) else e) != int(unit_id)]
    if entry is not None:
        lst.append(entry)
    if lst:
        mod["meta"]["grant"][kind] = lst
    else:
        mod["meta"]["grant"].pop(kind, None)


def get_grant(mod, kind, unit_id):
    for e in mod["meta"]["grant"].get(kind, []):
        if int(e["id"] if isinstance(e, dict) else e) == int(unit_id):
            return e if isinstance(e, dict) else {"id": int(e)}
    return None


def entity_texts(table, row, text):
    return {f: text_of(text, row.get(f)) for f in TEXT_FIELDS.get(table, {})}


def load_entity(mod_name, kind, eid):
    """Everything the editor needs for one entity, merged (base + mods). A copy: the cached
    tables are shared, so the result must never alias them."""
    return json.loads(json.dumps(_load_entity(mod_name, kind, eid)))


def _load_entity(mod_name, kind, eid):
    mod = load_mod(mod_name) if mod_name else None
    text = world_text()
    if kind in ("unit", "sangvis", "enemy", "row"):
        table = {"unit": "gun", "sangvis": "sangvis", "enemy": "enemy_character_type"}.get(kind)
        if kind == "row":
            table, eid = eid.split(":", 1)
        row = world_index(table).get(str(eid))
        if row is None:
            raise KeyError(f"{table} {eid} not found")
        stored = next((r for r in (mod or {}).get("tables", {}).get(table, []) if str(r.get(key_of(table))) == str(eid)), None)
        out = {"kind": kind, "table": table, "row": row, "texts": entity_texts(table, row, text),
               "copy": (stored or {}).get("_copy"), "in_mod": stored is not None,
               "in_base": str(eid) in {str(r[key_of(table)]) for r in base().table(table)}}
        if kind in ("unit", "sangvis") and mod:
            out["grant"] = get_grant(mod, "guns" if kind == "unit" else "sangvis", eid)
        if kind == "sangvis":
            out["resolution"] = [r for r in world_table("sangvis_resolution") if r["group_id"] == row["resolution"]]
        return out
    if kind == "team":
        row = world_index("enemy_team").get(str(eid))
        if row is None:
            raise KeyError(f"enemy_team {eid} not found")
        members = [r for r in world_table("enemy_in_team") if r["enemy_team_id"] == int(eid)]
        stored = next((r for r in (mod or {}).get("tables", {}).get("enemy_team", []) if str(r.get("id")) == str(eid)), None)
        return {"kind": kind, "table": "enemy_team", "row": row, "members": members,
                "copy": (stored or {}).get("_copy"), "in_mod": stored is not None,
                "in_base": str(eid) in {str(r["id"]) for r in base().table("enemy_team")}}
    if kind == "map":
        row = world_index("mission").get(str(eid))
        if row is None:
            raise KeyError(f"mission {eid} not found")
        spots = [r for r in world_table("spot") if r["mission_id"] == int(eid)]
        rules = (mod or {"meta": {}})["meta"].get("map_rules", {}).get(str(eid)) or {}
        stored = next((r for r in (mod or {}).get("tables", {}).get("mission", []) if str(r.get("id")) == str(eid)), None)
        out = {"kind": kind, "table": "mission", "row": row, "spots": spots, "spawns": rules.get("spawns", []),
               "move_order": rules.get("move_order") or {},
               "texts": entity_texts("mission", row, text), "copy": (stored or {}).get("_copy"),
               "in_mod": stored is not None,
               "in_base": str(eid) in {str(r["id"]) for r in base().table("mission")}}
        if mod:
            out["open"] = get_grant(mod, "missions", eid) is not None
        return out
    if kind == "skill":
        rows = sorted((r for r in world_table("battle_skill_config") if r["skill_group_id"] == int(eid)),
                      key=lambda r: r["level"])
        if not rows:
            raise KeyError(f"skill group {eid} not found")
        mine = [r for r in (mod or {}).get("tables", {}).get("battle_skill_config", [])
                if int(r.get("skill_group_id") or 0) == int(eid)]
        in_base = any(r["skill_group_id"] == int(eid) for r in base().table("battle_skill_config"))
        return {"kind": kind, "table": "battle_skill_config", "group": int(eid), "rows": rows,
                "texts": [entity_texts("battle_skill_config", r, text) for r in rows],
                "in_mod": bool(mine), "in_base": in_base}
    raise KeyError(kind)


def new_entity(kind, template=None):
    """A new entity: a copy of `template` with fresh ids, or an empty one."""
    if template not in (None, ""):
        e = load_entity(None, kind, template)
    else:
        e = blank_entity(kind)
    e["in_mod"] = e["in_base"] = False
    if kind in ("unit", "sangvis", "enemy"):
        nid = free_ids(e["table"])[0]
        e["copy"] = e["row"][key_of(e["table"])] if template not in (None, "") else None
        e["row"] = dict(e["row"], **{key_of(e["table"]): nid})
        e["in_base"] = False
        e.setdefault("grant", None)
    elif kind == "team":
        nid = free_ids("enemy_team")[0]
        e["copy"] = e["row"]["id"] if template not in (None, "") else None
        e["row"] = dict(e["row"], id=nid)
        e["members"] = [dict(m, enemy_team_id=nid, id=None) for m in e.get("members", [])]
    elif kind == "map":
        nid = free_ids("mission")[0]
        e["copy"] = e["row"]["id"] if template not in (None, "") else None
        new_spot_ids = free_ids("spot", len(e.get("spots", [])))
        remap = {str(s["id"]): str(n) for s, n in zip(e.get("spots", []), new_spot_ids)}
        e["row"] = dict(e["row"], id=nid, win_spot_id=_remap_list(e["row"].get("win_spot_id"), remap))
        e["spots"] = [dict(s, id=int(remap[str(s["id"])]), mission_id=nid,
                           route=_remap_list(s["route"], remap), map_route=_remap_list(s["map_route"], remap))
                      for s in e.get("spots", [])]
        e["spawns"] = [dict(r, spot=int(remap.get(str(r["spot"]), r["spot"])),
                            **({"spots": [int(remap.get(str(x), x)) for x in r["spots"]]} if r.get("spots") else {}))
                       for r in e.get("spawns", [])]
        e["open"] = True
    elif kind == "skill":
        g = free_skill_group()
        e["group"] = g
        e["rows"] = [dict(r, id=g * 100 + int(r["level"]), skill_group_id=g) for r in e["rows"]]
    elif kind == "row":
        table = e["table"]
        e["row"] = dict(e["row"], **{key_of(table): free_ids(table)[0]})
        e["copy"] = template.split(":", 1)[1] if template else None
    return e


def _remap_list(value, remap):
    s = str(value or "")
    return re.sub(r"\d+", lambda m: remap.get(m.group(0), m.group(0)), s) if s else s


def blank_row(table):
    return {f: ("" if t == "string" else 0) for f, t in stc.schema()[table][1]}


def blank_entity(kind):
    if kind == "unit":
        r = blank_row("gun")
        r.update(type=1, rank=3, rank_display=3, ratio_life=100, ratio_pow=100, ratio_rate=100, ratio_speed=100,
                 ratio_hit=100, ratio_dodge=100, ratio_range=100, eat_ratio=100, crit=20, armor_piercing=15,
                 baseammo=10, basemre=10, ammo_add_withnumber=5, mre_add_withnumber=5, normal_attack=300101,
                 effect_grid_center=13, effect_guntype="0", launch_time="1970-01-01 08:00:00", code="M1911")
        return {"kind": kind, "table": "gun", "row": r, "texts": {f: "" for f in TEXT_FIELDS["gun"]}}
    if kind == "sangvis":
        r = dict(world_index("sangvis")["1001"])     # a full Coalition row; too many required fields to start empty
        return {"kind": kind, "table": "sangvis", "row": r, "texts": {f: "" for f in TEXT_FIELDS["sangvis"]},
                "resolution": []}
    if kind == "enemy":
        r = blank_row("enemy_character_type")
        r.update(type=2, level=1, maxlife=100, pow=10, hit=10, dodge=5, rate=50, range=4, speed=10, number=1,
                 code="Drone", normal_attack=300301, effect_ratio=1.0, deployment_scale=1.0, angle=180)
        return {"kind": kind, "table": "enemy_character_type", "row": r,
                "texts": {f: "" for f in TEXT_FIELDS["enemy_character_type"]}}
    if kind == "team":
        r = blank_row("enemy_team")
        return {"kind": kind, "table": "enemy_team", "row": r, "members": []}
    if kind == "map":
        r = blank_row("mission")
        r.update(campaign=1, sub=8, type="2", difficulty=500, exp_parameter=10, enemy_ai_type=4,
                 map_res_name="Chapter1_Y;OPS86_Y", map_information="3000,2625|2472,1574|0,-758;6000,6000|6000,4000|0,5000",
                 is_snow="0", fog_length="0,500;0,500", fog_color="#000000FF;#000000FF", round_config="1:1,2:2,3:3",
                 support_available=2, limit_sangvis=4, limit_squad=-1, limit_vehicle=-1, limit_team="0",
                 difficulty_recommend="500,1;0,0;0,0;0,0;0,0", turn_duration=360000000)
        return {"kind": kind, "table": "mission", "row": r, "spots": [], "spawns": [],
                "texts": {f: "" for f in TEXT_FIELDS["mission"]}}
    if kind == "skill":
        rows = []
        for lv in range(1, 11):
            r = blank_row("battle_skill_config")
            r.update(level=lv, type=1, cd_type=1, cd_time=300, start_cd_time=30, trigger_type=1, trigger_target=1,
                     target_select_ai=1, train_coin_type=1)
            rows.append(r)
        return {"kind": kind, "table": "battle_skill_config", "group": 0, "rows": rows,
                "texts": [{f: "" for f in TEXT_FIELDS["battle_skill_config"]} for _ in rows]}
    raise KeyError(kind)


def coerce_row(table, row):
    out = {}
    for f, t in stc.schema()[table][1]:
        v = row.get(f, "" if t == "string" else 0)
        out[f] = mods._coerce(table, f, t, v)
    return out


def save_entity(mod_name, e):
    """Write an entity into a mod. Returns the problems found by a check build."""
    with LOCK:
        mod = load_mod(mod_name)
        kind = e["kind"]
        if kind in ("unit", "sangvis", "enemy", "row"):
            table = e["table"]
            row = coerce_row(table, e["row"])
            own_texts(table, row, e.get("texts") or {}, mod)
            st = stored_row(table, row, e.get("copy"), mod_name)
            put_rows(mod, table, [] if unchanged_override(table, st, mod_name) else [st],
                     remove_keys=[row[key_of(table)]])
            if kind in ("unit", "sangvis"):
                g = e.get("grant")
                set_grant(mod, "guns" if kind == "unit" else "sangvis", row["id"],
                          None if not g else dict({"id": row["id"]}, **{k: int(v) for k, v in g.items()
                                                                          if k != "id" and v not in ("", None)}))
            if kind == "sangvis" and e.get("resolution_rows"):
                rows = [coerce_row("sangvis_resolution", r) for r in e["resolution_rows"]]
                put_rows(mod, "sangvis_resolution", [st for st in (stored_row("sangvis_resolution", r, None, mod_name) for r in rows)
                                                     if not unchanged_override("sangvis_resolution", st, mod_name)])
        elif kind == "team":
            row = coerce_row("enemy_team", e["row"])
            tid = row["id"]
            put_rows(mod, "enemy_team", [stored_row("enemy_team", row, e.get("copy"), mod_name)])
            # members keep their ids when they are this mod's rows or rows of an existing team
            # (then only changes are stored); everything else gets a free id
            mine = {str(r["id"]) for r in mod["tables"].get("enemy_in_team", []) if int(r.get("enemy_team_id") or 0) == tid}
            theirs = {str(r["id"]) for r in world_table("enemy_in_team", exclude=mod_name) if r["enemy_team_id"] == tid}
            members = e.get("members") or []
            fresh = iter(free_ids("enemy_in_team", len(members)))
            rows, kept = [], set()
            for m in members:
                mid_ = str(m.get("id") or "")
                if not (mid_ and (mid_ in mine or mid_ in theirs)) or mid_ in kept:
                    mid_ = str(next(fresh))
                kept.add(mid_)
                st = stored_row("enemy_in_team", coerce_row("enemy_in_team", dict(m, id=int(mid_), enemy_team_id=tid)),
                                None, mod_name)
                if not unchanged_override("enemy_in_team", st, mod_name):
                    rows.append(st)
            deletes = [{"id": int(i), "_delete": True} for i in theirs if i not in kept]
            put_rows(mod, "enemy_in_team", rows + deletes, remove_keys=mine)
        elif kind == "map":
            row = coerce_row("mission", e["row"])
            mid = row["id"]
            own_texts("mission", row, e.get("texts") or {}, mod)
            put_rows(mod, "mission", [stored_row("mission", row, e.get("copy"), mod_name)])
            spots = [coerce_row("spot", dict(s, mission_id=mid)) for s in e.get("spots") or []]
            new_ids = [s["id"] for s in spots if not s["id"]]
            if new_ids:
                fresh = iter(free_ids("spot", len(new_ids)))
                for s in spots:
                    if not s["id"]:
                        s["id"] = next(fresh)
            old = [r["id"] for r in mod["tables"].get("spot", []) if int(r.get("mission_id") or 0) == mid]
            others = world_index("spot", exclude=mod_name)
            stored = [st for st in (stored_row("spot", s, None, mod_name) for s in spots)
                      if not unchanged_override("spot", st, mod_name)]
            keep = {str(s["id"]) for s in spots}
            deletes = [{"id": int(k), "_delete": True} for k, r in others.items()
                       if int(r["mission_id"]) == mid and k not in keep]
            put_rows(mod, "spot", stored + deletes, remove_keys=old)
            spawns = e.get("spawns") or []
            rules = {k: v for k, v in (mod["meta"]["map_rules"].get(str(mid)) or {}).items() if k not in ("spawns", "move_order")}
            if spawns:
                rules["spawns"] = spawns
            order = clean_move_order(e.get("move_order"), mid)
            if order:
                rules["move_order"] = order
            if rules:
                mod["meta"]["map_rules"][str(mid)] = rules
            else:
                mod["meta"]["map_rules"].pop(str(mid), None)
            set_grant(mod, "missions", mid, {"id": mid} if e.get("open") else None)
        elif kind == "skill":
            g = int(e["group"])
            rows = []
            for r, t in zip(e["rows"], e.get("texts") or [{}] * len(e["rows"])):
                r = coerce_row("battle_skill_config", dict(r, skill_group_id=g, id=g * 100 + int(r["level"])))
                own_texts("battle_skill_config", r, t or {}, mod)
                rows.append(stored_row("battle_skill_config", r, None, mod_name))
            old = [r["id"] for r in mod["tables"].get("battle_skill_config", []) if int(r.get("skill_group_id") or 0) == g]
            put_rows(mod, "battle_skill_config", rows, remove_keys=old)
        else:
            raise KeyError(kind)
        save_mod(mod_name, mod)
        return check_mod(mod_name)


def delete_entity(mod_name, kind, eid):
    with LOCK:
        mod = load_mod(mod_name)
        eid = str(eid)
        if kind in ("unit", "sangvis", "enemy"):
            table = {"unit": "gun", "sangvis": "sangvis", "enemy": "enemy_character_type"}[kind]
            put_rows(mod, table, [], remove_keys=[eid])
            for f in TEXT_FIELDS[table]:
                mod["meta"]["text"].pop(text_key(table, f, eid), None)
            if kind != "enemy":
                set_grant(mod, "guns" if kind == "unit" else "sangvis", eid, None)
        elif kind == "row":
            table, key = eid.split(":", 1)
            put_rows(mod, table, [], remove_keys=[key])
        elif kind == "team":
            put_rows(mod, "enemy_team", [], remove_keys=[eid])
            mod["tables"]["enemy_in_team"] = [r for r in mod["tables"].get("enemy_in_team", [])
                                              if str(r.get("enemy_team_id")) != eid]
        elif kind == "map":
            put_rows(mod, "mission", [], remove_keys=[eid])
            mod["tables"]["spot"] = [r for r in mod["tables"].get("spot", []) if str(r.get("mission_id")) != eid]
            mod["meta"]["map_rules"].pop(eid, None)
            set_grant(mod, "missions", eid, None)
            if mod["meta"].get("campaign"):
                mod["meta"]["campaign"]["missions"] = [i for i in mod["meta"]["campaign"].get("missions", []) if str(i) != eid]
            for f in TEXT_FIELDS["mission"]:
                mod["meta"]["text"].pop(text_key("mission", f, eid), None)
        elif kind == "skill":
            mod["tables"]["battle_skill_config"] = [r for r in mod["tables"].get("battle_skill_config", [])
                                                    if str(r.get("skill_group_id")) != eid]
        save_mod(mod_name, mod)
        return check_mod(mod_name)


TABLE_LABELS = {"fairy": "Fairy", "gift_item": "Gift", "item": "Item", "skin": "Costume", "story_util": "Story scene",
                "furniture": "Furniture", "equip": "Equipment", "squad": "HOC", "vehicle": "Vehicle",
                "commander_uniform": "Commander outfit", "chip": "Chip", "mission_skill_config": "Map skill",
                "special_spot_config": "Map marker", "mission_buff_config": "Map effect", "building": "Building",
                "ally_team": "Allied force", "enemy_in_team": "Enemy team member"}


def table_label(table):
    return TABLE_LABELS.get(table) or table.replace("_", " ").capitalize()


def world_tables():
    return set(stc.schema())


def mod_summary(name):
    mod = load_mod(name)
    t = mod["tables"]
    text = world_text()
    world = {}

    def label(table, key, field="name"):
        if table not in world:
            world[table] = world_index(table)
        r = world[table].get(str(key)) or {}
        return text_of(text, r.get(field)) or r.get("en_name") or r.get("code") or ""

    ents = {
        "unit": [{"id": r["id"], "name": label("gun", r["id"])} for r in t.get("gun", []) if not r.get("_delete")],
        "sangvis": [{"id": r["id"], "name": label("sangvis", r["id"])} for r in t.get("sangvis", []) if not r.get("_delete")],
        "enemy": [{"id": r["id"], "name": label("enemy_character_type", r["id"])}
                  for r in t.get("enemy_character_type", []) if not r.get("_delete")],
        "team": [{"id": r["id"], "name": ""} for r in t.get("enemy_team", []) if not r.get("_delete")],
        "map": [{"id": r["id"], "name": label("mission", r["id"])} for r in t.get("mission", []) if not r.get("_delete")],
        "skill": [{"id": g, "name": label("battle_skill_config", g * 100 + 10)}
                  for g in sorted({int(r.get("skill_group_id") or int(r["id"]) // 100) for r in t.get("battle_skill_config", [])})],
    }
    # tables owned by an entry: the skill's pieces, a Coalition unit's resolution rows
    owned = {"gun", "sangvis", "enemy_character_type", "enemy_team", "enemy_in_team", "mission", "spot",
             "battle_skill_config", "battle_trigger", "battle_target_select_ai", "battle_buff", "battle_action_config",
             "battle_creation", "battle_hurt_config", "battle_formula", "battle_watch", "battle_watch_trigger",
             "sangvis_resolution", "normal_activity", "mission_event"}
    ents["row"] = [{"id": f"{tb}:{r.get(key_of(tb))}", "show": r.get(key_of(tb)),
                    "name": " · ".join(filter(None, [table_label(tb), text_of(text, (world_index(tb).get(str(r.get(key_of(tb)))) or {}).get("name")) if tb in world_tables() else ""]))}
                   for tb, rows in t.items() if tb not in owned for r in rows]
    import content
    ents.update(content.summary(name, mod))
    meta = {k: v for k, v in mod["meta"].items() if k not in ("text", "grant", "map_rules")}
    return {"meta": meta, "entities": ents, "campaign": mod["meta"].get("campaign") or mod["meta"].get("chapter")}


def check_mod(name):
    """Validate every enabled mod plus this one (as if enabled) without writing build output."""
    active = {n for n in all_mod_names() if load_mod(n)["meta"].get("enabled", True)} | {name}
    found = [m for m in mods.discover(mods.MODS_DIR, include_disabled=True) if m["dir"].name in active]
    try:
        man = mods.build(found, log=lambda *_: None, write=False, load_table=lambda t: base().table(t))
        return {"ok": True, "problems": man["problems"]}
    except mods.ModError as e:
        return {"ok": False, "problems": [str(e)]}


def run_build():
    p = subprocess.run([sys.executable, str(SERVER / "tools" / "build_mods.py")], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", cwd=str(SERVER))
    return {"ok": p.returncode == 0, "output": (p.stdout + p.stderr)[-6000:]}


def buff_info(ids):
    """For condition editors: each buff's type and the skills that hand it out (with names)."""
    import skills
    givers = skills.buff_givers(sys.modules[__name__])
    buffs = world_index("battle_buff")
    groups = sorted({g for i in ids for g in givers.get(str(i), [])})
    names_ = names("skill", [str(g) for g in groups]) if groups else {}
    return {str(i): {"type": (buffs.get(str(i)) or {}).get("type"), "exists": str(i) in buffs,
                     "givers": [{"id": g, "name": names_.get(str(g), "")} for g in givers.get(str(i), [])][:8]}
            for i in ids}


_ICONS = []


def mission_icons():
    """Names of the client's mission-select icons (Pics/Icons/Mission/<name>.png), read once from the
    archived resource config."""
    if not _ICONS:
        try:
            import UnityPy
            from gfserver import config
            meta = json.loads((config.ARCHIVE_DIR / "resconfig.json").read_text("utf-8"))
            tree = next(o for o in UnityPy.load(str(config.ARCHIVE_DIR / meta["file"])).objects
                        if o.type.name == "MonoBehaviour").read_typetree()
            _ICONS.extend(sorted({a["resName"][:-4] for sec in ("BaseAssetBundles", "AddAssetBundles")
                                  for e in tree[sec] for a in e["assetAllRes"]
                                  if "/Pics/Icons/Mission/" in a["pathKey"] and a["resName"].endswith(".png")},
                                 key=str.lower))
        except (OSError, ValueError, StopIteration, ImportError):
            pass
    return _ICONS


def lookups():
    """Labels and choices for the simplified editors."""
    import designs
    import models
    import skills
    text = world_text()
    equip = [{"type": r["type"], "category": r["category"], "name": text_of(text, r["name"]) or r["code"],
              "fits": [int(x) for x in str(r["fit_gun_type"] or "0").split(",") if x.strip().isdigit()]}
             for r in world_table("equip_type") if r["type"]]
    team_ai = {k: {"label": v, "param": models.TEAM_AI_PARAM.get(k)} for k, v in models.TEAM_AI_LABELS.items()}
    return {"gun_types": models.GUN_TYPES, "tile_stats": models.TILE_STATS, "equip_categories": models.EQUIP_CATEGORIES,
            "equip_types": equip, "factions": models.FACTIONS, "sangvis_classes": models.SANGVIS_CLASSES,
            "enemy_types": models.ENEMY_TYPES, "enemy_stats": [[k, label] for k, _, label in models.ENEMY_STATS],
            "team_ai": team_ai, "team_tags": models.TEAM_TAGS, "map_kinds": models.MAP_KINDS, "map_ai": models.MAP_AI,
            "skill2_kinds": models.SANGVIS_SKILL2_KINDS, "skill_presets": skills.PRESETS,
            "mission_icons": mission_icons()}


def meta_info():
    sch = stc.schema()
    tables = {t: sch[t][1] for t in sch}
    return {
        "tables": tables, "guide": guide(), "text_fields": TEXT_FIELDS, "free_from": FREE_FROM,
        "base_version": base().version,
        "team_ai": [{"id": r["id"], "code": r.get("code"), "name": text_of(world_text(), r.get("name"))}
                    for r in world_table("team_ai")] if "team_ai" in sch else [],
    }


# ---------------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "modstudio"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body, ctype="application/json; charset=utf-8", download=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        parts = [urllib.parse.unquote(p) for p in u.path.split("/") if p]
        try:
            if not parts or parts[0] != "api":
                return self._static(u.path)
            route = parts[1:]
            with LOCK:
                if route == ["meta"]:
                    return self._send(200, meta_info())
                if route == ["mods"]:
                    return self._send(200, [dict(mod_summary(n)["meta"], dir=n) for n in all_mod_names()])
                if len(route) == 2 and route[0] == "mod":
                    return self._send(200, mod_summary(route[1]))
                if len(route) == 3 and route[0] == "mod" and route[2] == "export":
                    from gfserver import mod_share
                    try:
                        data, fname = mod_share.export_bytes(route[1]), mod_share.file_name(route[1])
                    except mod_share.ShareError as e:
                        return self._send(404, {"error": str(e)})
                    return self._send(200, data, "application/zip", download=fname)
                if len(route) == 2 and route[0] == "catalog":
                    return self._send(200, catalog(route[1]))
                if len(route) == 3 and route[0] == "entity":
                    return self._send(200, load_entity(q.get("mod"), route[1], route[2]))
                if len(route) == 2 and route[0] == "new":
                    return self._send(200, new_entity(route[1], q.get("from")))
                if len(route) == 2 and route[0] == "free":
                    return self._send(200, free_ids(route[1], int(q.get("n", 1))))
                if len(route) == 3 and route[0] == "row":
                    return self._send(200, world_index(route[1]).get(route[2]))
                if route == ["text"]:
                    text = world_text()
                    return self._send(200, {k: text.get(k, "") for k in (q.get("keys") or "").split(",") if k})
                if route == ["names"]:
                    return self._send(200, names(q.get("table"), (q.get("ids") or "").split(",")))
                import designs
                if route == ["map-config"]:
                    return self._send(200, map_config_list())
                if len(route) == 2 and route[0] == "map-config":
                    return self._send(200, map_config_get(route[1]))
                if route == ["lookups"]:
                    return self._send(200, lookups())
                if len(route) == 3 and route[0] == "design":
                    return self._send(200, designs.get(q.get("mod"), route[1], route[2]))
                if len(route) == 2 and route[0] == "newdesign":
                    return self._send(200, designs.new(route[1], q.get("from"), int(q.get("type") or 1)))
                if len(route) == 2 and route[0] == "models":
                    return self._send(200, designs.models_catalog(route[1]))
                import content
                if route == ["text-search"]:
                    return self._send(200, content.search_text(q.get("q")))
                if route == ["cn-data"]:
                    return self._send(200, {"available": content.cn_available()})
                if route == ["buffinfo"]:
                    return self._send(200, buff_info([i for i in (q.get("ids") or "").split(",") if i]))
            return self._send(404, {"error": "not found"})
        except (KeyError, ValueError, FileNotFoundError) as e:
            return self._send(400, {"error": str(e)})

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        parts = [urllib.parse.unquote(p) for p in u.path.split("/") if p]
        try:
            body = self._body()
            route = parts[1:] if parts[:1] == ["api"] else None
            if route == ["mod"]:
                name = body.get("name", "")
                d = mod_dir(name)
                if d.exists():
                    raise ValueError(f"mod {name} already exists")
                save_mod(name, {"meta": {"name": name, "version": "1", "enabled": True,
                                         "description": body.get("description", "")},
                                "tables": {}, "catchdata": {}})
                return self._send(200, mod_summary(name))
            if route and len(route) == 3 and route[0] == "mod" and route[2] == "settings":
                import designs
                with LOCK:
                    if "enabled" in body:
                        mods.set_enabled(route[1], body["enabled"], mod_dir(route[1]).parent)
                    mod = load_mod(route[1])
                    for k in ("enabled", "version", "description"):
                        if k in body:
                            mod["meta"][k] = body[k]
                    save_mod(route[1], mod)
                    if "campaign_name" in body or "campaign_description" in body:
                        designs.set_campaign(route[1], body.get("campaign_name"), body.get("campaign_description"))
                return self._send(200, mod_summary(route[1]))
            if route and len(route) == 3 and route[0] == "mod" and route[2] == "save-design":
                import designs
                return self._send(200, designs.save(route[1], body["kind"], body["design"]))
            if route and len(route) == 3 and route[0] == "mod" and route[2] == "delete-design":
                import designs
                return self._send(200, designs.delete(route[1], body["kind"], body["id"]))
            if route and len(route) == 2 and route[0] == "preview":
                import designs
                return self._send(200, designs.preview(route[1], body))
            if route and len(route) == 3 and route[0] == "mod" and route[2] == "save":
                return self._send(200, save_entity(route[1], body))
            if route and len(route) == 3 and route[0] == "mod" and route[2] == "delete":
                return self._send(200, delete_entity(route[1], body["kind"], body["id"]))
            if route and len(route) == 3 and route[0] == "mod" and route[2] == "check":
                return self._send(200, check_mod(route[1]))
            if route and len(route) == 3 and route[0] == "mod" and route[2] == "story-import":
                import content
                return self._send(200, content.import_story(route[1], body.get("files") or []))
            if route and len(route) == 3 and route[0] == "mod" and route[2] == "copy-cn":
                import content
                return self._send(200, content.copy_from_cn(route[1], body.get("table"), body.get("ids") or []))
            if route and len(route) == 2 and route[0] == "map-config":
                with LOCK:
                    return self._send(200, map_config_save(route[1], body))
            if route == ["build"]:
                return self._send(200, run_build())
            return self._send(404, {"error": "not found"})
        except mods.ModError as e:
            return self._send(400, {"error": str(e)})
        except (KeyError, ValueError, TypeError) as e:
            return self._send(400, {"error": f"{type(e).__name__}: {e}"})

    def _static(self, path):
        rel = path.strip("/") or "index.html"
        f = (STATIC / rel).resolve()
        if STATIC.resolve() not in f.parents or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}.get(f.suffix, "application/octet-stream")
        return self._send(200, f.read_bytes(), ctype + "; charset=utf-8")


# ------------------------------------------------------------------ map config (not a mod)
# The player's own per-map settings for the server (gfserver/config.MAP_CONFIG): enemy spawn tables,
# enemy move order and random node odds. A global file, not mod data: the server reads it while running.
RANDOM_KINDS = ("gain", "loss", "data", "core", "ambush", "gun")
MOVE_AI = ("standby", "random", "attack", "patrol", "alert", "expand", "lock_on")


def clean_move_order(order, mid):
    """A map's move_order (gfserver/missions.move_order) checked against the map; {} when it is the default."""
    from gfserver import missions
    order = order if isinstance(order, dict) else {}
    spots = {int(r["id"]) for r in world_table("spot") if r["mission_id"] == int(mid)}
    teams = {int(r["id"]) for r in world_table("enemy_team")}
    first = []
    for r in order.get("first") or []:
        if "team" in r:
            if int(r["team"] or 0) not in teams:
                raise ValueError(f"move order: enemy team {r['team']} not found")
            first.append({"team": int(r["team"])})
        elif "spot" in r:
            if int(r["spot"] or 0) not in spots:
                raise ValueError(f"move order: node {r['spot']} is not on this map")
            first.append({"spot": int(r["spot"])})
        elif r.get("ai") in MOVE_AI:
            first.append({"ai": r["ai"]})
    then = order.get("then") if order.get("then") in missions.MOVE_THEN else "oldest"
    if not first and then == "oldest":
        return {}
    return {"first": first, "then": then}


def _read_map_config():
    from gfserver import config
    try:
        data = json.loads(config.MAP_CONFIG.read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def map_config_list():
    """Maps that have settings of their own: [{id, name, spawns, random_nodes}]."""
    maps = _read_map_config().get("maps") or {}
    idx, text = world_index("mission"), world_text()
    return [{"id": int(mid), "name": text_of(text, (idx.get(str(mid)) or {}).get("name")),
             "spawns": len(v.get("spawns") or []) if "spawns" in v else None, "move_order": "move_order" in v,
             "random_nodes": bool(v.get("random_nodes"))}
            for mid, v in sorted(maps.items(), key=lambda kv: int(kv[0]))]


def map_config_get(mid):
    from gfserver import missions
    row = world_index("mission").get(str(mid))
    if row is None:
        raise KeyError(f"map {mid} not found")
    own = (_read_map_config().get("maps") or {}).get(str(mid)) or {}
    spots = [{"id": r["id"], "type": int(r["type"] or 0), "belong": int(r["belong"] or 0),
              "random": str(r.get("random_get") or "0") == "1"} for r in world_table("spot") if r["mission_id"] == int(mid)]
    return {"id": int(mid), "name": text_of(world_text(), row.get("name")), "spots": spots,
            "map_teams": sorted(missions._map_enemy_pool(int(mid))),
            "custom_spawns": "spawns" in own, "spawns": own.get("spawns") or [],
            "custom_order": "move_order" in own, "move_order": own.get("move_order") or {"first": [], "then": "oldest"},
            "default_order": missions.move_order(int(mid)) if "move_order" not in own else None,
            "random_nodes": {k: int((own.get("random_nodes") or {}).get(k, w)) for k, w in missions.RANDOM_EVENTS},
            "random_default": dict(missions.RANDOM_EVENTS), "custom_random": bool(own.get("random_nodes"))}


def map_config_save(mid, body):
    """Store one map's settings (custom_spawns false: the server's own guess; custom_random false:
    the default odds). Spawn spots must be on the map and teams must exist."""
    from gfserver import config, missions
    if str(mid) not in world_index("mission"):
        raise KeyError(f"map {mid} not found")
    entry = {}
    if body.get("custom_spawns"):
        spots = {int(r["id"]) for r in world_table("spot") if r["mission_id"] == int(mid)}
        teams = {int(r["id"]) for r in world_table("enemy_team")}
        rules = []
        for r in body.get("spawns") or []:
            nodes = [int(x) for x in r.get("spots") or [r.get("spot") or 0]]
            if not nodes or any(n not in spots for n in nodes):
                raise ValueError(f"spawn nodes {nodes} are not all on this map")
            bad = [t["team"] for t in r.get("teams") or [] if int(t.get("team") or 0) not in teams]
            if bad:
                raise ValueError(f"enemy teams {bad} not found")
            # enemies appear only on heliports the enemy holds (player report)
            rules.append(dict({k: v for k, v in r.items() if not k.startswith("_")}, enemy_owned=True))
        entry["spawns"] = rules
    if body.get("custom_order"):
        entry["move_order"] = clean_move_order(body.get("move_order"), mid) or {"first": [], "then": "oldest"}
    if body.get("custom_random"):
        given = body.get("random_nodes") or {}
        odds = {k: max(0, int(given.get(k) or 0)) for k in RANDOM_KINDS}
        if not any(odds.values()):
            raise ValueError("give at least one random node outcome a chance above 0")
        if odds != dict(missions.RANDOM_EVENTS):
            entry["random_nodes"] = odds
    data = _read_map_config()
    maps = data.setdefault("maps", {})
    if entry:
        maps[str(mid)] = entry
    else:
        maps.pop(str(mid), None)
    data.setdefault("_comment", "Per-map server settings, edited in Mod Studio (Map spawns). The server "
                    "reads changes while it runs.")
    tmp = config.MAP_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), "utf-8")
    tmp.replace(config.MAP_CONFIG)
    return map_config_get(mid)


def names(table, ids):
    """Display names for ids of a table (units, enemies, teams, missions, skills)."""
    text = world_text()
    if table == "skill":
        rows = {}
        for r in world_table("battle_skill_config"):
            rows.setdefault(str(r["skill_group_id"]), r)
        return {i: text_of(text, (rows.get(i) or {}).get("name")) for i in ids}
    if table == "enemy_team":
        teams, enemies = world_index("enemy_team"), world_index("enemy_character_type")
        out = {}
        for i in ids:
            lead = enemies.get(str((teams.get(i) or {}).get("enemy_leader"))) or {}
            out[i] = text_of(text, lead.get("name")) or lead.get("code", "")
        return out
    idx = world_index(table)
    return {i: text_of(text, (idx.get(i) or {}).get("name")) or (idx.get(i) or {}).get("code", "") for i in ids}


def main():
    sys.modules.setdefault("studio", sys.modules[__name__])     # designs.py imports this module by name
    t0 = time.time()
    base().text()
    print(f"base data {base().version}, text loaded in {time.time() - t0:.1f}s")
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Mod Studio on http://127.0.0.1:{PORT}/")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
