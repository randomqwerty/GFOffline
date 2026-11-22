"""Mods: extra or changed static data (T-Dolls, Coalition units, enemies, enemy teams, maps).

A mod is a folder under mods/ (see mods/README.md):

  mods/<name>/mod.json          {"name", "version", "enabled", "tables", "catchdata", "text", "grant",
                                 "map_rules", "campaign", "chapter", "art", "custom_art", "game_assets", "banners", "profile_edits"}  (art: {"<new image path>":
                                 "<existing image path>"}, paths under Assets/Resources/DaBao/, built by
                                 tools/build_mods.py; custom_art: a T-Doll model with the mod's own pictures, see tools/custom_art.py;
                                 game_assets: replaced or added pictures and music, see tools/game_assets.py)
  mods/<name>/tables/<t>.json   optional: rows for .stc table <t> (same as mod.json "tables"[t])
  mods/<name>/catchdata/<t>.json  optional: rows for catchdata table <t>
  mods/<name>/story/<file>.txt    optional: replaces the game's story file of that name (avgtxt/<file>.txt)
  mods/<name>/art/<code>/<slot>.png  optional: pictures of "custom_art"
  mods/<name>/art/assets/<category>/<name>.png|.adx  optional: files of "game_assets"

Rows are matched on the table's first column (its key: "id" for almost every table). A row whose
key exists replaces only the fields it lists; a new key adds a row, with unlisted fields taken from
the row named by "_copy" (else 0 / ""). {"<key>": ..., "_delete": true} removes a row.
Mods are applied in folder-name order, so a later mod can change an earlier mod's rows.

How it reaches the client: tools/build_mods.py merges the mods into the pristine data package
(archive/stc/*.zip), writes the result to build/mods/ and gives it a new data_version. The client
compares that with the version it last downloaded (PlayerPrefs "version",
LoginController.CheckAndRequestUpdate) and downloads stc_<data_version>....zip again, which
app.py serves from build/mods/. Text keys ("gun-1xxxxxxx" names, ...) live in the
assettexttable bundle, which build_mods.py patches like build_lpatch.py does the luapatch bundle.
The server reads the merged tables too (config.STC_DIR), so production, maps and battles see
modded rows.
"""
import gzip
import math
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from . import config, stc

MODS_DIR = config.ROOT / "mods"
BUILD_DIR = config.ROOT / "build" / "mods"
MANIFEST = BUILD_DIR / "manifest.json"
# Part of data_version: bump when the builder's output changes for the same mods, so clients
# re-download (2: sorted tables; 3: map copies point at their own nodes; 4: new enemy team members walk forward).
BUILD_REVISION = 4
STORY_CUE = re.compile(r"<(?!/?Speaker\b)[^<>]+>[^<>|;]*")


class ModError(Exception):
    pass


# ---------------------------------------------------------------------------- loading

# Custom art models were first named Mod<gun id>, but the client drops "Mod" from a code when it
# builds picture paths (CommonController$$LoadSmallPic: code.Replace("Mod", "").Replace("_mod", ""),
# its Neural Upgrade naming), so Mod57's card and chibi were looked up as "57" and not found. They
# are Own<gun id> now (tools/custom_art.py new_code); older mods are renamed as they load.
OLD_ART_CODE = re.compile(r"Mod(\d+)")


def renamed_art_code(code):
    m = OLD_ART_CODE.fullmatch(str(code or ""))
    return f"Own{m.group(1)}" if m else code


def rename_old_art_codes(custom_art, tables):
    """Rename Mod<id> custom art models (and the gun rows using them) to Own<id>, in place."""
    old = [c for c in list(custom_art or {}) if renamed_art_code(c) != c]
    for c in old:
        custom_art[renamed_art_code(c)] = custom_art.pop(c)
    if old:
        for r in (tables or {}).get("gun", []):
            if isinstance(r, dict) and r.get("code") in old:
                r["code"] = renamed_art_code(r["code"])
    return bool(old)


# Which mods are on is the player's choice, kept in mods/_enabled.json ({"<mod folder>": true/false}) and
# never shipped, so unpacking a new release over a setup keeps it. A mod's own "enabled" is only the
# default for a mod with no choice made yet (the release ships every mod off).
CHOICES = "_enabled.json"


def _choices(mods_dir):
    try:
        found = json.loads((Path(mods_dir) / CHOICES).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def is_enabled(folder, meta, mods_dir=None):
    folder = Path(folder)
    return bool(_choices(mods_dir or folder.parent).get(folder.name, meta.get("enabled", True)))


def set_enabled(name, on, mods_dir=None):
    mods_dir = Path(mods_dir or MODS_DIR)
    choices = _choices(mods_dir)
    choices[name] = bool(on)
    mods_dir.mkdir(parents=True, exist_ok=True)
    tmp = mods_dir / (CHOICES + ".tmp")
    tmp.write_text(json.dumps(choices, indent=1, sort_keys=True) + "\n", "utf-8")
    tmp.replace(mods_dir / CHOICES)


def discover(mods_dir=MODS_DIR, include_disabled=False):
    """Enabled mods in apply order: [{"name", "version", "dir", "tables", "catchdata", "text", "grant"}]."""
    out = []
    if not mods_dir.is_dir():
        return out
    for d in sorted(p for p in mods_dir.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        f = d / "mod.json"
        if not f.is_file():
            continue
        try:
            meta = json.loads(f.read_text("utf-8"))
        except ValueError as e:
            raise ModError(f"{f}: {e}")
        if not is_enabled(d, meta, mods_dir) and not include_disabled:
            continue
        if meta.get("client"):
            raise ModError(f"{f}: battle tools and keys are launcher settings now, not part of a mod: remove \"client\"")
        mod = {"name": meta.get("name") or d.name, "version": str(meta.get("version", "")), "dir": d,
               "tables": dict(meta.get("tables") or {}), "catchdata": dict(meta.get("catchdata") or {}),
               "text": dict(meta.get("text") or {}), "grant": dict(meta.get("grant") or {}),
               "map_rules": {str(k): v for k, v in (meta.get("map_rules") or {}).items()},
               "campaign": dict(meta.get("campaign") or {}),
               "chapter": dict(meta.get("chapter") or {}), "art": dict(meta.get("art") or {}),
               "custom_art": dict(meta.get("custom_art") or {}), "game_assets": dict(meta.get("game_assets") or {}),
               "banners": list(meta.get("banners") or []), "profile_edits": dict(meta.get("profile_edits") or {}),
               "story": {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in sorted((d / "story").glob("*.txt"))}}
        for sub, key in (("tables", "tables"), ("catchdata", "catchdata")):
            for tf in sorted((d / sub).glob("*.json")) if (d / sub).is_dir() else []:
                try:
                    rows = json.loads(tf.read_text("utf-8"))
                except ValueError as e:
                    raise ModError(f"{tf}: {e}")
                mod[key].setdefault(tf.stem, [])
                mod[key][tf.stem] = list(mod[key][tf.stem]) + list(rows)
        rename_old_art_codes(mod["custom_art"], mod["tables"])
        out.append(mod)
    for n, mod in enumerate(m for m in out if (m["campaign"].get("missions"))):
        _campaign_rows(mod, n)
    return out


# ---------------------------------------------------------------------------- Campaign tab entries
#
# "campaign": {"name", "description", "missions": [mission ids in list order], "look": <normal_activity id>}
# lists the maps as one entry of the Campaign tab, like an archived event. Each mod with one gets the
# next free ids (campaign -9001, -9002, ... in apply order), so mods never clash. The maps move to that
# campaign (sub = list position; if_emergency -1, as event maps are) and lose their unlock keys. The
# entry's background and colours are taken from the normal_activity row "look" (default 1, the first
# archived event); scene_name is cleared so it opens the plain stage list.
FIRST_CAMPAIGN, FIRST_ACTIVITY, FIRST_EVENT, FIRST_ORDER = 9001, 9001, 99001, 301


def campaign_id(n):
    return -(FIRST_CAMPAIGN + n)


def _campaign_rows(mod, n):
    c = mod["campaign"]
    cid, act, ev = campaign_id(n), FIRST_ACTIVITY + n, FIRST_EVENT + n
    missions = [int(i) for i in c["missions"]]
    rows = mod["tables"].setdefault("mission", [])
    by_id = {int(r["id"]): r for r in rows if str(r.get("id", "")).lstrip("-").isdigit()}
    for sub, mid in enumerate(missions, 1):
        patch = {"campaign": cid, "sub": sub, "if_emergency": -1, "open_mission_keys": ""}
        if mid in by_id:
            by_id[mid].update(patch)
        else:
            rows.append(dict(patch, id=mid))
    key = lambda table, i, part: f"{table}-{part}{i:07d}"
    mod["tables"]["normal_activity"] = list(mod["tables"].get("normal_activity") or []) + [{
        "id": act, "_copy": int(c.get("look") or 1), "campaign_id": cid, "order": FIRST_ORDER + n,
        "tag": key("normal_activity", act, 1), "name": key("normal_activity", act, 2),
        "chapter_name": key("normal_activity", act, 3), "desc": key("normal_activity", act, 4),
        "scene_name": "", "event_prize_level": 0, "rank_id": ""}]
    mod["tables"]["mission_event"] = list(mod["tables"].get("mission_event") or []) + [{
        "id": ev, "type": 2, "mission_campaign": str(cid), "event_name": key("mission_event", ev, 1),
        "init_mission_id": str(missions[0])}]
    name, desc = str(c.get("name") or mod["name"]), str(c.get("description") or "")
    mod["text"] = dict({key("normal_activity", act, 1): f"MOD|{n + 1:02d}", key("normal_activity", act, 2): name,
                        key("normal_activity", act, 3): name, key("normal_activity", act, 4): desc,
                        key("mission_event", ev, 1): name}, **mod["text"])


def digest(mods):
    """Content hash of the enabled mods (decides the data_version)."""
    h = hashlib.md5()
    for m in mods:
        h.update(json.dumps([m["name"], m["version"], m["tables"], m["catchdata"], m["text"], m["grant"],
                             m.get("map_rules", {}), m.get("campaign", {}), m.get("chapter", {}), m.get("art", {}), m.get("banners", []),
                             m.get("profile_edits", {}), m.get("game_assets", {})],
                            sort_keys=True, ensure_ascii=False).encode("utf-8"))
        if m.get("story"):
            h.update(json.dumps(m["story"], sort_keys=True).encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------- story files

def story_lines(raw):
    """A story file's lines, without blank ones. Each is "<who and stage cues>:<what is said>"."""
    text = raw.decode("utf-8-sig", "replace") if isinstance(raw, bytes) else raw
    return [l for l in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if l.strip()]


def story_problems(raw, original=None):
    """What would go wrong in the game with a story file: a line the game can't split, or stage cues (music, backgrounds,
    effects) that differ from the original's. Spoken names may be translated, so <Speaker> isn't compared."""
    lines, problems = story_lines(raw), []
    for i, line in enumerate(lines, 1):
        if ":" not in line:
            problems.append(f"line {i} has no ':' between its cues and its text")
    if original is not None:
        def cues(rows):
            return [c for l in rows for c in STORY_CUE.findall(l.split(":", 1)[0])]
        mine, theirs = cues(lines), cues(story_lines(original))
        if mine != theirs:
            problems.append("the music, background or effect cues differ from the original's")
    return problems


# ---------------------------------------------------------------------------- merging

def _coerce(table, field, ftype, value):
    if ftype == "string":
        return "" if value is None else str(value)
    if ftype == "float":
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            raise ModError(f"{table}.{field}: {value!r} is not a number")
    try:
        v = int(value or 0)
    except (TypeError, ValueError):
        raise ModError(f"{table}.{field}: {value!r} is not an integer")
    lo, hi = {"sbyte": (-128, 127), "int": (-2**31, 2**31 - 1), "long": (-2**63, 2**63 - 1)}[ftype]
    if not lo <= v <= hi:
        raise ModError(f"{table}.{field}: {v} does not fit in {ftype}")
    return v


# Fields a new row (no _copy) gets other than 0 or "": enemies walk forward like nearly every game row (136058 of
# 136197; 0 makes one stand still until a target is in range, EnemyInTeamInfo.isAdvance)
NEW_ROW_DEFAULTS = {"enemy_in_team": {"is_advance": 1}}


def apply_rows(table, base_rows, patches, fields=None, source=""):
    """Apply one mod's rows to a table. fields = schema [[name, type]] (None for catchdata).

    Returns (rows, changed_keys). Keys are compared as strings, so 5 and "5" are the same row.
    """
    if fields:
        key = fields[0][0]
    else:
        sample = base_rows[0] if base_rows else patches[0] if patches else {}
        key = "id" if "id" in sample else next(iter(sample), "id")
    names = [n for n, _ in fields] if fields else None
    types = dict(fields) if fields else {}
    # catchdata is JSON the client reads with fixed types ("1" vs 1): follow the base rows
    json_str = {f for f, v in base_rows[0].items() if isinstance(v, str)} if base_rows and not fields else set()
    rows = list(base_rows)
    index = {str(r.get(key)): i for i, r in enumerate(rows)}
    changed = []
    for p in patches:
        if not isinstance(p, dict) or key not in p:
            raise ModError(f"{source}{table}: every row needs its key field {key!r}: {p!r}"[:300])
        k = str(p[key])
        if p.get("_delete"):
            if k in index:
                rows[index[k]] = None
                del index[k]
                changed.append(k)
            continue
        extra = [f for f in p if not f.startswith("_") and names is not None and f not in types]
        if extra:
            raise ModError(f"{source}{table} row {k}: unknown field(s) {extra}")
        if k in index and "_copy" in p:
            # almost always an id collision: the mod meant a new row but the id is taken
            raise ModError(f"{source}{table} row {k}: id already exists, so _copy would overwrite it; "
                           f"pick a free id (or drop _copy to edit the existing row)")
        if k in index:
            row = dict(rows[index[k]])
        elif "_copy" in p:
            src = str(p["_copy"])
            if src not in index:
                raise ModError(f"{source}{table} row {k}: _copy source {src} not found")
            row = dict(rows[index[src]])
        elif names is not None:
            row = {n: ("" if t == "string" else 0) for n, t in fields}
            row.update({f: v for f, v in NEW_ROW_DEFAULTS.get(table, {}).items() if f in row})
        else:
            row = {}
        for f, v in p.items():
            if f.startswith("_"):
                continue
            if names is not None:
                row[f] = _coerce(table, f, types[f], v)
            else:
                row[f] = str(v) if f in json_str and not isinstance(v, str) else v
        if names is not None:
            row[key] = _coerce(table, key, types[key], p[key])
        if k in index:
            rows[index[k]] = row
        else:
            index[k] = len(rows)
            rows.append(row)
        changed.append(k)
    return [r for r in rows if r is not None], changed


# ---------------------------------------------------------------------------- checks

THINGS = {"gun": "T-Doll", "sangvis": "Coalition unit", "fairy": "fairy", "mission": "map", "spot": "map node",
          "enemy_character_type": "enemy", "enemy_team": "enemy team", "enemy_in_team": "enemy team member",
          "battle_skill_config": "skill", "battle_buff": "skill effect", "item": "item", "skin": "skin", "equip": "equipment"}


def overlaps(mods, tables, schema):
    """Two mods using the same ids. A row two mods both add stops the build, naming both mods: they were made apart and
    picked the same free id. A row of the game that two mods both change is a warning, since only the later one counts.
    A mod may still change a few fields of another mod's row on purpose (a balance mod over a unit mod)."""
    added, changes, problems = {}, {}, []
    for t in sorted({t for m in mods for t in m["tables"]}):
        key, fields = schema[t][1][0][0], schema[t][1]
        base = {str(r[key]) for r in tables[t]}
        thing = THINGS.get(t, f"{t} row")
        for m in mods:
            for p in m["tables"].get(t, []):
                if not isinstance(p, dict) or key not in p or p.get("_delete"):
                    continue
                k, set_fields = str(p[key]), [f for f in p if not f.startswith("_") and f != key]
                first = added.get(k)
                if first and first != m["name"] and ("_copy" in p or len(set_fields) > len(fields) // 2):
                    raise ModError(f"The mods {first} and {m['name']} both add a {thing} with id {k}, so they can't be on "
                                   f"together. Turn one of them off, or ask one author to give theirs other ids.")
                if k not in base:
                    added.setdefault(k, m["name"])
                    continue
                for f in set_fields:
                    prev = changes.get((k, f))
                    if prev and prev[0] != m["name"] and str(prev[1]) != str(p[f]):
                        problems.append(f"The mods {prev[0]} and {m['name']} both change {thing} {k} ({f}); "
                                        f"{m['name']}'s change is used.")
                    changes[(k, f)] = (m["name"], p[f])
        added.clear()
        changes.clear()
    return problems

def _ints(v, seps=",;|"):
    s = str(v or "")
    for sep in seps[1:]:
        s = s.replace(sep, seps[0])
    out = []
    for piece in s.split(seps[0]):
        piece = piece.strip()
        if piece.lstrip("-").isdigit():
            out.append(int(piece))
    return out


# (table, field, target, how): how = "one" (0 = none), "list" (comma/semicolon list),
# "skill" (skill group ids: battle_skill_config.skill_group_id). Each rule holds for (nearly)
# every row of the unmodded data.
REFERENCES = [
    ("gun", "normal_attack", "skill", "one"),
    ("gun", "skill1", "skill", "one"),
    ("gun", "skill2", "skill", "one"),
    ("sangvis", "normal_attack", "skill", "one"),
    ("sangvis", "skill1", "skill", "one"),
    ("enemy_character_type", "normal_attack", "skill", "one"),
    ("enemy_character_type", "passive_skill", "skill", "list"),
    ("enemy_character_type", "level", "enemy_standard_attribute", "one"),
    ("enemy_in_team", "level", "enemy_standard_attribute", "one"),     # a level with no scaling row hangs the battle
    ("enemy_team", "enemy_leader", "enemy_character_type", "one"),
    ("enemy_in_team", "enemy_team_id", "enemy_team", "one"),
    ("enemy_in_team", "enemy_character_type_id", "enemy_character_type", "one"),
    ("spot", "mission_id", "mission", "one"),
    ("spot", "enemy_team_id", "enemy_team", "one"),
    ("spot", "ally_team_id", "ally_team", "one"),
    ("spot", "building_id", "building", "one"),
    ("spot", "route", "spot", "list"),
    ("mission", "boss_team_id", "enemy_team", "list"),
]


def check(tables, changed):
    """Reference problems in the changed rows: list of messages (empty = fine).

    tables: {name: rows} with every table the rules mention; changed: {table: set of keys}.
    """
    keysets = {}

    def keys(t):
        if t not in keysets:
            if t == "skill":
                keysets[t] = {int(r["skill_group_id"]) for r in tables["battle_skill_config"]}
            else:
                k = stc.schema()[t][1][0][0]
                keysets[t] = {int(r[k]) for r in tables[t]}
        return keysets[t]

    problems = []
    for table, field, target, how in REFERENCES:
        if table not in changed:
            continue
        k = stc.schema()[table][1][0][0]
        for r in tables[table]:
            if str(r[k]) not in changed[table]:
                continue
            vals = _ints(r[field]) if how == "list" else [int(r[field] or 0)]
            missing = [v for v in vals if v and v not in keys(target)]
            if missing:
                problems.append(f"{table} {r[k]}: {field} -> {target} {missing} not found")
    # the few enemy types with no stats of their own (maxlife 0, e.g. 10000) are stand-ins: a team using one can't be
    # fought from Target Practice (MissionSelectionDroneTrainSettingController.GetEnemyPower: EnemyGun.Init overflows)
    if "enemy_in_team" in changed:
        blank = {int(r["id"]) for r in tables["enemy_character_type"] if not int(r.get("maxlife") or 0)}
        for r in tables["enemy_in_team"]:
            if str(r["id"]) in changed["enemy_in_team"] and int(r["enemy_character_type_id"] or 0) in blank:
                problems.append(f"enemy_in_team {r['id']}: enemy_character_type {r['enemy_character_type_id']} is a stand-in "
                                f"with no stats; team {r['enemy_team_id']} freezes the game in Target Practice")
    # a new or changed enemy team without members fights nobody
    if "enemy_team" in changed or "enemy_in_team" in changed:
        members = {int(r["enemy_team_id"]) for r in tables["enemy_in_team"]}
        for r in tables["enemy_team"]:
            if str(r["id"]) in changed.get("enemy_team", ()) and int(r["id"]) not in members:
                problems.append(f"enemy_team {r['id']}: has no enemy_in_team members")
    return problems


# ---------------------------------------------------------------------------- building

def base_package():
    """Path and data_version of the original data package."""
    found = config.base_package()
    if found is None:
        raise ModError("The original game data isn't set up yet: press Set up in the launcher")
    return found


def read_catchdata(raw):
    plain = gzip.decompress(bytes(b ^ stc.CATCHDATA_KEY[i % len(stc.CATCHDATA_KEY)] for i, b in enumerate(raw)))
    return [line for line in plain.decode("utf-8").splitlines() if line.strip()]


def write_catchdata(lines):
    plain = ("\n".join(lines) + "\n").encode("utf-8")
    packed = gzip.compress(plain, mtime=0)
    return bytes(b ^ stc.CATCHDATA_KEY[i % len(stc.CATCHDATA_KEY)] for i, b in enumerate(packed))


def build(mods=None, out_dir=BUILD_DIR, log=print, write=True, load_table=None):
    """Merge mods into the base package; write <out>/stc/*, the zip and manifest.json.

    Returns the manifest dict. Raises ModError on bad mod data (nothing is written then).
    write=False only checks (nothing is encoded or written); load_table(name) can supply the
    original rows (exact floats; they are not modified) instead of parsing the package.
    """
    mods = discover() if mods is None else mods
    pkg, base_version = base_package()
    schema = stc.schema()
    with zipfile.ZipFile(pkg) as z:
        files = {i.filename: z.read(i) for i in z.infolist() if not i.is_dir()}

    touched = sorted({t for m in mods for t in m["tables"]})
    unknown = [t for t in touched if t not in schema]
    if unknown:
        raise ModError(f"unknown table(s) {unknown}; names are in data/stc_schema.json")
    # tables the reference checks need, parsed only when some mod touches a table
    need = set(touched)
    if touched:
        need |= {r[0] for r in REFERENCES if r[0] in touched} | {
            "battle_skill_config" if r[2] == "skill" else r[2] for r in REFERENCES if r[0] in touched}
        if {"enemy_team", "enemy_in_team"} & set(touched):
            need |= {"enemy_team", "enemy_in_team"}
        if _copied_missions(mods):
            need |= set(COPY_TABLES)
    tables = {}
    for t in sorted(need):
        tid, fields = schema[t]
        tables[t] = (list(load_table(t)) if load_table else
                     stc.parse(files[f"{tid}.stc"], fields, tid, exact_floats=True))

    # The client finds rows through each table's section index (StBaseDatas.GetDataById), which
    # needs ascending keys; 238 of 240 integer-keyed tables are sorted. Appending enemy team
    # 80000001 after 94040975 made it unfindable ("找不到敌人组队信息"), so sorted tables stay sorted.
    was_sorted = {t: _is_sorted(tables[t], schema[t][1]) for t in need}

    problems = overlaps(mods, tables, schema)
    changed = {}
    for m in mods:
        for t, patches in m["tables"].items():
            tables[t], keys = apply_rows(t, tables[t], patches, schema[t][1], source=f"{m['name']}: ")
            changed.setdefault(t, set()).update(keys)
            log(f"  {m['name']}: {t} {len(keys)} row(s)")

    copies = copy_maps(_copied_missions(mods), tables, changed)

    lines = None
    cd_changed = {}
    if any(m["catchdata"] for m in mods):
        lines = read_catchdata(files["catchdata.dat"])
        parsed = [json.loads(l) for l in lines]
        names = {next(iter(d)): i for i, d in enumerate(parsed)}
        for m in mods:
            for t, patches in m["catchdata"].items():
                if t not in names:
                    parsed.append({t: []})
                    names[t] = len(parsed) - 1
                i = names[t]
                parsed[i][t], keys = apply_rows(t, parsed[i][t], patches, None, source=f"{m['name']}: ")
                cd_changed.setdefault(t, set()).update(keys)
                log(f"  {m['name']}: catchdata {t} {len(keys)} row(s)")
        for t in cd_changed:
            lines[names[t]] = json.dumps(parsed[names[t]], ensure_ascii=False, separators=(",", ":"))

    for t in changed:
        if was_sorted[t]:
            key = schema[t][1][0][0]
            tables[t].sort(key=lambda r: int(r[key]))

    problems += check(tables, changed) if changed else []
    rules = _merged_map_rules(mods)
    if rules:
        problems += check_map_rules(rules, tables, files, schema, load_table)

    banners = _merged_banners(mods)
    problems += check_banners(banners, tables, files, schema, load_table)

    d = digest(mods)
    data_version = (hashlib.md5(f"{base_version}:{d}:{BUILD_REVISION}".encode()).hexdigest()
                    if mods else base_version)
    if not write:
        return {"data_version": data_version, "base_data_version": base_version, "digest": d,
                "mods": [{"name": m["name"], "version": m["version"]} for m in mods],
                "tables": {t: sorted(k, key=_sort_key) for t, k in changed.items()},
                "grant": _merged_grants(mods), "map_rules": rules, "banners": banners, "copies": copies,
                "problems": problems}
    out_files = dict(files)
    for t in changed:
        tid, fields = schema[t]
        out_files[f"{tid}.stc"] = stc.write(tid, fields, tables[t])
    if lines is not None:
        out_files["catchdata.dat"] = write_catchdata(lines)

    stc_dir = out_dir / "stc"
    stc_dir.mkdir(parents=True, exist_ok=True)
    for old in stc_dir.iterdir():
        if old.name not in out_files:
            old.unlink()
    for name, data in out_files.items():
        p = stc_dir / name
        if not p.exists() or p.read_bytes() != data:
            p.write_bytes(data)
    zip_name = f"stc_{data_version}.zip"
    for old in out_dir.glob("stc_*.zip"):
        if old.name != zip_name:
            old.unlink()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(out_files, key=lambda n: (not n.endswith(".stc"), n)):
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), out_files[name],
                       compress_type=zipfile.ZIP_DEFLATED)
    (out_dir / zip_name).write_bytes(buf.getvalue())

    manifest = {
        "data_version": data_version, "base_data_version": base_version, "digest": d,
        "zip": zip_name, "mods": [{"name": m["name"], "version": m["version"]} for m in mods],
        "tables": {t: sorted(k, key=_sort_key) for t, k in changed.items()},
        "catchdata": {t: sorted(k, key=_sort_key) for t, k in cd_changed.items()},
        "grant": _merged_grants(mods),
        "map_rules": rules,
        "banners": banners,
        "copies": copies,
        "build_revision": BUILD_REVISION,
        "problems": problems,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    return manifest


# ---------------------------------------------------------------------------- map copies
#
# A mod map made with "_copy" from a game map (Mod Studio's map copy) has new node ids at the same
# places on the same map art. What names the source's nodes has to follow:
#   - its own rows: spot route / map_route / auto_teleport, mission win_spot_id / special_spot_id /
#     random_line_spot (translated here);
#   - win conditions, which the client checks itself (DeploymentUIController$$CheckTypeComplete):
#     mission_win_type_config 1101 "spot,..." and 1309 "ally_team,spot" rows naming source nodes
#     get a copy for the map, and its win_type / lose_type / medal_type_silver / win_step (with the
#     mission_win_step_control chain) name the copies;
#   - what the server keeps by map id or shares with the source (team ai_content routes, ally
#     betray / transform nodes, data/spawn_tables.json, recorded runs): read through manifest
#     "copies" {"<map>": {"from": <source map>, "spots": {"<source node>": node}}} (missions.py).
COPY_TABLES = ("mission", "spot", "mission_win_type_config", "mission_win_step_control")
COPY_SPOT_FIELDS = {"mission": ("win_spot_id", "special_spot_id", "random_line_spot"),
                    "spot": ("route", "map_route", "auto_teleport")}
WIN_SPOT_ARGS = {1101: None, 1309: 1}       # condition type: which "," argument is a node (None: all)


def _copied_missions(mods):
    """{new map id: source map id} of the mods' mission rows made with _copy."""
    out = {}
    for m in mods:
        for p in m["tables"].get("mission", []):
            if isinstance(p, dict) and "_copy" in p and not p.get("_delete"):
                out[int(p["id"])] = int(p["_copy"])
    return out


def _swap(text, remap, only=None):
    """Numbers in text that are source nodes as the copy's (only: the "," position to touch)."""
    if only is None:
        return re.sub(r"\d+", lambda x: str(remap.get(int(x.group(0)), x.group(0))), str(text))
    parts = str(text).split(",")
    if only < len(parts) and parts[only].strip().isdigit():
        parts[only] = str(remap.get(int(parts[only]), parts[only].strip()))
    return ",".join(parts)


def copy_maps(copied, tables, changed):
    """Point each copied map at its own nodes (see above). Returns manifest "copies"."""
    out = {}
    if not copied:
        return out
    spots_of = {}
    for r in tables["spot"]:
        spots_of.setdefault(int(r["mission_id"]), []).append(r)
    missions = {int(r["id"]): r for r in tables["mission"]}
    conds = {int(r["id"]): r for r in tables["mission_win_type_config"]}
    steps = {str(r["id"]): r for r in tables["mission_win_step_control"]}
    place = lambda r: (int(r["coordinator_x"] or 0), int(r["coordinator_y"] or 0))
    for new, src in sorted(copied.items()):
        mine = {place(r): r for r in spots_of.get(new, [])}
        remap = {int(r["id"]): int(mine[place(r)]["id"]) for r in spots_of.get(src, []) if place(r) in mine}
        if not remap or new not in missions:
            continue
        out[str(new)] = {"from": src, "spots": {str(k): v for k, v in sorted(remap.items())}}
        for r in spots_of.get(new, []):
            for f in COPY_SPOT_FIELDS["spot"]:
                if r.get(f):
                    r[f] = _swap(r[f], remap)
            changed.setdefault("spot", set()).add(str(r["id"]))
        row = missions[new]
        for f in COPY_SPOT_FIELDS["mission"]:
            if row.get(f):
                row[f] = _swap(row[f], remap)
        base = new * 1000 if new * 1000 + 999 < 2 ** 31 else max(conds) + 1
        made = {}

        def cond_copy(cid):
            c = conds.get(int(cid))
            if c is None or int(c["type"]) not in WIN_SPOT_ARGS:
                return cid
            args = _swap(c["arguments"], remap, WIN_SPOT_ARGS[int(c["type"])])
            if args == str(c["arguments"]):
                return cid
            if int(cid) not in made:
                nid = base + len(made)
                while nid in conds:
                    nid += 1
                conds[nid] = dict(c, id=nid, arguments=args)
                tables["mission_win_type_config"].append(conds[nid])
                changed.setdefault("mission_win_type_config", set()).add(str(nid))
                made[int(cid)] = nid
            return str(made[int(cid)])

        swap_conds = lambda text: re.sub(r"\d+", lambda x: cond_copy(x.group(0)), str(text or ""))
        for f in ("win_type", "lose_type", "medal_type_silver"):
            if row.get(f):
                row[f] = swap_conds(row[f])
        # the win_step chain: copied when a step in it names a copied condition
        chain, todo = [], re.findall(r"\d+", str(row.get("win_step") or ""))
        while todo:
            sid = todo.pop()
            if sid in chain or sid not in steps:
                continue
            chain.append(sid)
            todo += re.findall(r"\d+", steps[sid]["next_id"] or "")
        if any(swap_conds(steps[s]["win_step"]) != steps[s]["win_step"] or
               swap_conds(steps[s]["lose_step"]) != steps[s]["lose_step"] for s in chain):
            ids = {}
            for s in sorted(chain):
                nid = base + 500 + len(ids)
                while str(nid) in steps:
                    nid += 1
                ids[s] = str(nid)
            swap_steps = lambda text: re.sub(r"\d+", lambda x: ids.get(x.group(0), x.group(0)), str(text or ""))
            for s in sorted(chain):
                r = steps[s]
                nr = dict(r, id=int(ids[s]), win_step=swap_conds(r["win_step"]), lose_step=swap_conds(r["lose_step"]),
                          next_id=swap_steps(r["next_id"]), lock_id=swap_steps(r["lock_id"]))
                steps[ids[s]] = nr
                tables["mission_win_step_control"].append(nr)
                changed.setdefault("mission_win_step_control", set()).add(ids[s])
            row["win_step"] = swap_steps(row["win_step"])
        changed.setdefault("mission", set()).add(str(new))
    return out


_COPIES = {"key": None, "copies": {}}


def copies():
    """Built map copies: {"<map>": {"from": source map, "spots": {"<source node>": node}}}."""
    try:
        key = (config.MODS_DISABLED, MANIFEST.stat().st_mtime_ns)
    except OSError:
        return {}
    if key != _COPIES["key"]:
        _COPIES.update(key=key, copies=(manifest() or {}).get("copies") or {})
    return _COPIES["copies"]


def _is_sorted(rows, fields):
    """Integer first column in ascending order (string-keyed tables are left as they are)."""
    if fields[0][1] == "string":
        return False
    keys = [int(r[fields[0][0]]) for r in rows]
    return keys == sorted(keys)


def _sort_key(k):
    return (0, int(k)) if k.lstrip("-").isdigit() else (1, k)


# the keys gfserver/missions.py _spawn and _spawn_allies read
SPAWN_KEYS = {"spot", "spots", "teams", "start", "from_turn", "to_turn", "every", "chance", "max", "enemy_owned",
              "one_of", "blind", "queue", "while_alive", "min_kills", "max_kills", "if_special", "unless_special",
              "after_killed", "after_destroyed", "our_turn", "min_casts", "not_ours", "ally", "owner", "side"}


def _merged_map_rules(mods):
    """{mission id (str): {"spawns": [...]}}; a later mod's rules for a map replace the earlier ones."""
    out = {}
    for m in mods:
        for mid, rules in (m.get("map_rules") or {}).items():
            if not str(mid).lstrip("-").isdigit():
                raise ModError(f"{m['name']}: map_rules key {mid!r} must be a mission id")
            if "icon" in (rules or {}) and not isinstance(rules["icon"], str):
                raise ModError(f"{m['name']}: map {mid} icon must be an icon name, e.g. \"Nyto_black\"")
            for r in (rules or {}).get("spawns") or []:
                bad = set(r) - SPAWN_KEYS - {k for k in r if k.startswith("_")}
                if bad:
                    raise ModError(f"{m['name']}: map {mid} spawn rule has unknown key(s) {sorted(bad)}")
                if not ("spot" in r or r.get("spots")) or not (r.get("teams") or r.get("queue")):
                    raise ModError(f"{m['name']}: map {mid} spawn rule needs a spot and teams: {r}")
            out[str(int(mid))] = rules
    return out


def check_map_rules(rules, tables, files, schema, load_table=None):
    """Spawn rules must name spots of their own map and enemy teams that exist."""
    def load(t):
        if t not in tables:
            tid, fields = schema[t]
            tables[t] = list(load_table(t)) if load_table else stc.parse(files[f"{tid}.stc"], fields, tid)
        return tables[t]
    spot_map = {int(r["id"]): int(r["mission_id"]) for r in load("spot")}
    teams = {int(r["id"]) for r in load("enemy_team")}
    problems = []
    for mid, rule_set in rules.items():
        for r in rule_set.get("spawns") or []:
            for sid in [int(x) for x in r.get("spots") or [r["spot"]]]:
                if spot_map.get(sid) != int(mid):
                    problems.append(f"map {mid}: spawn spot {sid} is not a node of this map")
            known = {int(x["id"]) for x in load("ally_team")} if r.get("ally") else teams
            wanted = [t.get("team") for t in r.get("teams") or []] + list(r.get("queue") or [])
            missing = [t for t in wanted if int(t or 0) not in known]
            if missing:
                problems.append(f"map {mid}: spawn teams {missing} not found")
    return problems


# HomeEventBarController$$AutoFit lays out at most 16 banners; past that "show all" indexes an empty list
MAX_BANNERS = 16


def _merged_banners(mods):
    """Home screen banners [{"event", "pic"}]; a later mod's banner for the same event replaces the earlier one."""
    out = {}
    for m in mods:
        for b in m.get("banners") or []:
            bad = set(b) - {"event", "pic"} - {k for k in b if k.startswith("_")}
            if bad or not b.get("event") or not b.get("pic"):
                raise ModError(f"{m['name']}: a banner needs an event and a pic, and nothing else: {b}")
            out[int(b["event"])] = {"event": int(b["event"]), "pic": str(b["pic"])}
    if len(out) > MAX_BANNERS:
        raise ModError(f"{len(out)} home screen banners; the client can lay out {MAX_BANNERS}")
    return list(out.values())


def check_banners(banners, tables, files, schema, load_table=None):
    """A banner opens its event through OPSConfig.GoToSceneByEventID, so the event has to exist."""
    if not banners:
        return []
    if "mission_event" in tables:
        rows = tables["mission_event"]
    else:
        tid, fields = schema["mission_event"]
        rows = list(load_table("mission_event")) if load_table else stc.parse(files[f"{tid}.stc"], fields, tid)
    events = {int(r["id"]) for r in rows}
    return [f"banner: mission_event {b['event']} not found" for b in banners if b["event"] not in events]


def _merged_grants(mods):
    """{kind: [{"id": n, ...options}]}; a later mod's entry for the same id replaces the earlier one."""
    out = {}
    for m in mods:
        for kind, entries in m["grant"].items():
            for e in entries:
                e = dict(e) if isinstance(e, dict) else {"id": e}
                if "id" not in e:
                    raise ModError(f"{m['name']}: grant {kind} entry without an id: {e}")
                e["id"] = int(e["id"])
                allowed = OPTIONS.get(kind, {})
                bad = [k for k in e if k != "id" and k not in allowed]
                if bad:
                    raise ModError(f"{m['name']}: grant {kind} {e['id']}: unknown option(s) {bad}")
                lst = out.setdefault(kind, [])
                lst[:] = [x for x in lst if x["id"] != e["id"]] + [e]
    return out


# ---------------------------------------------------------------------------- runtime

def manifest():
    """The built mod manifest, or None when no mods are built (or they are switched off)."""
    if config.MODS_DISABLED or not MANIFEST.is_file():
        return None
    try:
        return json.loads(MANIFEST.read_text("utf-8"))
    except ValueError:
        return None


def stale():
    """True when mods/ differs from what was last built (tools/build_mods.py needs a re-run)."""
    try:
        mods = discover()
    except ModError:
        return True
    m = manifest()
    if m is None:
        return bool(mods)
    return (m.get("digest") != digest(mods) or [x["name"] for x in m["mods"]] != [x["name"] for x in mods]
            or (bool(mods) and m.get("build_revision", 2) != BUILD_REVISION))


def map_rules(mission_id):
    """A modded map's server-side rules (enemy spawn tables), or None."""
    m = manifest()
    return ((m or {}).get("map_rules") or {}).get(str(mission_id))


def banners(man=None):
    """The reply's "banner" list for ServerInfo.RequestBannerAndAnnounce (EventBannerInfo$$.ctor). Type 1 is
    EventCampaign: HomeEventBarItemController$$OnPointerClick opens the second number of "extra" as a
    mission_event id; the first is unused for this type. pic is a path in the client's bundles, which
    client_patch/offline_banners.lua loads, since the client would otherwise download activity/<pic> from the CDN."""
    m = manifest() if man is None else man
    return [{"id": b["event"], "pic": b["pic"], "type": 1, "order": i, "delay": 5, "start_time": "2000-01-01 00:00:00",
             "end_time": "2037-12-31 23:59:59", "extra": f"1-{b['event']}", "iftimelimit": False}
            for i, b in enumerate((m or {}).get("banners") or [])]


def package_file(requested):
    """The built package for a requested stc_<data_version>....zip name, else None."""
    m = manifest()
    if m and m["mods"] and requested.startswith("stc_" + m["data_version"]):
        p = BUILD_DIR / m["zip"]
        return p if p.is_file() else None
    return None


GUN_OPTIONS = {"level": (1, 100), "number": (1, 5), "skill1": (1, 10), "skill2": (1, 10), "enhance": (0, 1)}
SANGVIS_OPTIONS = {"max": (0, 1)}
FAIRY_OPTIONS = {"max": (0, 1)}
OPTIONS = {"guns": GUN_OPTIONS, "sangvis": SANGVIS_OPTIONS, "fairies": FAIRY_OPTIONS}


def apply_grants(state, uid, man=None):
    """Give the save what the mods grant, once each (missions are opened in mission_with_user_info).

    "grant": {"guns": [8001 or {"id": 8001, "level": 100, "number": 5, "skill1": 10, "skill2": 10}],
              "sangvis": [...], "fairies": [...], "missions": [...], "items": [item ids: one of each, e.g. a mod's
              own profile picture or home background]}
    Granted ids are remembered in the save's "_mod_grants". When a doll's options change in a later
    build, the granted doll is updated to match. Returns {kind: [ids added or updated]}.
    """
    m = manifest() if man is None else man
    if not m or not m.get("grant"):
        return {}
    from . import factory, missions, workshop
    done = state.setdefault("_mod_grants", {})
    applied = done.setdefault("_options", {})
    added = {}
    for kind, entries in m["grant"].items():
        for e in entries:
            e = e if isinstance(e, dict) else {"id": e}
            unit, opts = int(e["id"]), {k: v for k, v in e.items() if k != "id"}
            key = f"{kind}:{unit}"
            if unit in done.get(kind, []):
                if kind == "guns" and opts and applied.get(key) != opts:
                    rec = next((g for g in state.get("gun_with_user_info", []) if g["gun_id"] == str(unit)), None)
                    if rec is not None:
                        _set_gun(rec, unit, opts)
                        applied[key] = opts
                        added.setdefault(kind, []).append(unit)
                elif kind == "sangvis" and opts and applied.get(key) != opts:
                    rec = next((r for r in state.get("sangvis_with_user_info", []) if r["sangvis_id"] == str(unit)), None)
                    if rec is not None:
                        _max_sangvis(rec, unit)
                        applied[key] = opts
                        added.setdefault(kind, []).append(unit)
                elif kind == "fairies" and opts.get("max") and applied.get(key) != opts:
                    rec = max((f for f in (state.get("fairy_with_user_info") or {}).values() if f["fairy_id"] == str(unit)),
                              key=lambda f: int(f["id"]), default=None)     # the newest: the one granted
                    if rec is not None:
                        _max_fairy(rec)
                        applied[key] = opts
                        added.setdefault(kind, []).append(unit)
                continue
            if kind == "guns" and unit in factory.guns():
                rec = factory.new_gun_record(state, unit, uid)
                if opts:
                    _set_gun(rec, unit, opts)
                    applied[key] = opts
            elif kind == "sangvis" and unit in _sangvis():
                rec = new_sangvis_record(state, unit, uid)
                if opts.get("max"):
                    _max_sangvis(rec, unit)
                    applied[key] = opts
            elif kind == "fairies" and unit in workshop.fairies():
                rec = workshop.new_fairy(state, unit, workshop._talents()[0])
                if opts.get("max"):
                    _max_fairy(rec)
                    applied[key] = opts
            elif kind == "missions" and unit in missions._missions():
                missions._mission_record(state, unit)["is_open"] = "1"
            elif kind == "items":
                from . import squads
                rec = squads._item(state, unit)
                rec["number"] = str(max(1, int(rec["number"] or 0)))
            else:
                continue
            done.setdefault(kind, []).append(unit)
            added.setdefault(kind, []).append(unit)
    return added


def _set_gun(rec, gun_id, opts):
    """Apply grant options (level, dummy links, skill levels) to a doll record in the save."""
    from . import factory, missions
    v = {k: max(lo, min(hi, int(opts[k]))) for k, (lo, hi) in GUN_OPTIONS.items() if k in opts}
    level = v.get("level", int(rec["gun_level"]))
    number = v.get("number", int(rec["number"]))
    rec["gun_level"], rec["gun_exp"], rec["number"] = str(level), str(missions._level_exp()[level]), str(number)
    rec["life"] = str(factory.gun_life(gun_id, level, number))   # full HP
    for k in ("skill1", "skill2"):
        if k in v and (k == "skill1" or int(rec.get("if_modification") or 0) or int(factory.guns()[gun_id]["skill2"] or 0)):
            rec[k] = str(v[k])      # no second skill on a doll that has none
    if v.get("enhance"):
        for k, n in factory.gun_enhancement(gun_id, level).items():
            rec[k] = str(n)


def _max_fairy(rec):
    """Level 100, 5 stars, skill 10."""
    rec.update(fairy_lv="100", fairy_exp="9999000", quality_lv="5", quality_exp="3000", skill_lv="10")


def _sangvis():
    return {int(r["id"]): r for r in stc.table("sangvis")}


def sangvis_life(sangvis_id):
    """Whole-unit HP at level 100, 5 stars, size 5 and max resolution (doc/stc-guide/10):
    ceil((res_hp + 139 x ratio_hp x eat x 110 x adv_hp x class_hp / 1e8 / formation) x models)."""
    row = _sangvis()[sangvis_id]
    cls = next(r for r in stc.table("sangvis_type") if r["id"] == row["type"])
    adv = next(r for r in stc.table("sangvis_advance") if r["lv"] == 5)
    res = max((r for r in stc.table("sangvis_resolution") if r["group_id"] == row["resolution"]),
              key=lambda r: r["lv"], default={"resolution_hp": 0, "resolution_number": 1})
    per = (139 * float(row["ratio_hp"] or 0) * float(row["eat_ratio"] or 0) * 110 * float(adv["advance_hp"])
           * float(cls["basic_hp"]) / 1e8 / max(1, int(row["formation"] or 1)))
    return math.ceil(round((float(res["resolution_hp"] or 0) + per) * int(res["resolution_number"] or 1), 6))


def _max_sangvis(rec, sangvis_id):
    """Level 100, 5 stars, size 5, max resolution, every skill at its class's maximum, full HP."""
    row = _sangvis()[sangvis_id]
    cls = next(r for r in stc.table("sangvis_type") if r["id"] == row["type"])
    caps = [int(x) for x in str(cls["skills_max_lv"] or "10,10,5,5").split(",")] + [5, 5, 5, 5]
    exp = sum(int(r["exp"]) for r in stc.table("sangvis_exp") if int(r["lv"]) < 100)
    rec.update({"sangvis_level": "100", "sangvis_exp": str(exp), "sangvis_advance": "5", "sangvis_resolution": "4",
                "sangvis_resolution_level": "4", "sangvis_shape_n": "5", "life": str(sangvis_life(sangvis_id))})
    for i, f in enumerate(("skill1", "skill2", "skill3", "skill_advance")):
        has = int(row[f] or 0) != 0
        rec[f] = str(caps[i] if caps[i] and has else (1 if has else 0))


def new_sangvis_record(state, sangvis_id, uid):
    """A level-1 Coalition unit in the save's sangvis_with_user_info format (fields as recorded)."""
    ids = [int(r["id"]) for r in state.get("sangvis_with_user_info", [])]
    row = _sangvis()[sangvis_id]
    rec = {
        "id": str(max(ids, default=0) + 1), "user_id": str(uid), "sangvis_id": str(sangvis_id),
        "sangvis_exp": "0", "sangvis_level": "1", "sangvis_advance": "1", "sangvis_resolution": "1",
        "sangvis_resolution_level": "1", "sangvis_shape_n": "0", "sangvis_is_special": "0",
        "skill1": "1", "skill2": "1" if int(row["skill2"] or 0) else "0",
        "skill3": "1" if int(row["skill3"] or 0) else "0", "skill_advance": "1",
        "chip1": "0", "chip2": "0", "can_click": "0",
        "favor": "0", "favor_toplimit": "1000000", "max_favor": "1000000",
        # APPROXIMATION: level-1 HP formula unknown; ratio_hp is the closest per-unit number.
        "life": str(max(1, int(row["ratio_hp"] or 0))),
        "sign": "0", "soul_bond": "0", "soul_bond_time": "0", "skin": "0", "special_effect": "0",
        "is_locked": "0", "is_collect": "0",
    }
    state.setdefault("sangvis_with_user_info", []).append(rec)
    collected = state.setdefault("sangvis_capture_collect_info", [])
    if str(sangvis_id) not in collected:
        collected.append(str(sangvis_id))
    return rec
