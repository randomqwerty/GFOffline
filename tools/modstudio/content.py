"""Mod Studio: the parts of a content mod besides units and maps: story text, event listings and game text.

Story files live in mods/<name>/story/<file>.txt, the rest in mod.json and tables/, as gfserver/mods.py describes. Copying rows from the
Chinese client's data (cn-data/stc/<table>.json, when that folder exists) is here too: it is how honkai_collab's maps and dolls were made.
"""
import difflib
import json
import re
import sys

from gfserver import config, mods
import studio as w

KINDS = ("story", "event", "text", "config")
SPEAKER = re.compile(r"<Speaker>(.*?)</Speaker>")
STORY_NAME = re.compile(r"[^/\\:*?\"<>|]+\.txt")
OPS_IMAGES = "Pics/Icons/OPS/"
EVENT_IDS_FROM = 90100
CN_DIR = config.CN_DATA_DIR / "stc"
_ORIGINALS = {}
_IMAGES = []


# ---------------------------------------------------------------------------- story text

def originals():
    """{file name in lower case: bytes} of every story file in the game (read once)."""
    if not _ORIGINALS:
        sys.path.insert(0, str(w.SERVER / "tools"))
        import build_mods
        _ORIGINALS.update(build_mods.read_story())
    return _ORIGINALS


def story_dir(mod_name):
    return w.mod_dir(mod_name) / "story"


def _story_file(mod_name, name):
    """The mod's file for this story, in whatever case it was saved, else None."""
    d = story_dir(mod_name)
    return next((p for p in sorted(d.glob("*.txt")) if p.name.lower() == name.lower()), None) if d.is_dir() else None


def _check_name(name):
    if not STORY_NAME.fullmatch(name or "") or name.lower() not in originals():
        raise ValueError(f"the game has no story file called {name}")


def _split(line):
    head, _, text = line.partition(":")
    m = SPEAKER.search(head)
    return {"cue": head, "speaker": m.group(1) if m else "", "text": text}


def _pairs(mine, theirs):
    """For each of my lines, the original line it translates (None where the file added one), lined up by stage cues."""
    bare = lambda rows: [SPEAKER.sub("", r["cue"]).strip() for r in rows]
    out = [None] * len(mine)
    for a, b, n in difflib.SequenceMatcher(None, bare(mine), bare(theirs), autojunk=False).get_matching_blocks():
        for i in range(n):
            out[a + i] = theirs[b + i]
    return out


def _rows(raw, original):
    mine, theirs = [_split(l) for l in mods.story_lines(raw)], [_split(l) for l in mods.story_lines(original)]
    for row, other in zip(mine, _pairs(mine, theirs)):
        row["original"] = other["text"] if other else ""
        row["original_speaker"] = other["speaker"] if other else ""
    return mine


def _story_design(mod_name, name):
    original = originals()[name.lower()]
    f = _story_file(mod_name, name) if mod_name else None
    raw = f.read_bytes() if f else original
    return {"kind": "story", "id": f.name if f else name, "name": f.name if f else name, "in_mod": bool(f),
            "rows": _rows(raw, original), "problems": mods.story_problems(raw, original)}


def _story_text(rows):
    lines = []
    for r in rows:
        cue, speaker = str(r["cue"]), str(r.get("speaker") or "").replace("<", "").replace(">", "")
        if SPEAKER.search(cue):
            cue = SPEAKER.sub(lambda _: f"<Speaker>{speaker}</Speaker>", cue)
        lines.append(f"{cue}:{str(r.get('text') or '')}".replace("\r", " ").replace("\n", "+"))
    return "".join(line + "\r\n" for line in lines)


def write_story(mod_name, name, text):
    """Store a story file; returns its problems."""
    _check_name(name)
    d = story_dir(mod_name)
    d.mkdir(parents=True, exist_ok=True)
    f = _story_file(mod_name, name) or d / name
    raw = text.encode("utf-8")
    f.write_bytes(raw)
    return mods.story_problems(raw, originals()[name.lower()])


def import_story(mod_name, files):
    """Text files people already have: [{"name", "text"}]. Nothing is stored if a name doesn't match a story of the game."""
    for item in files:
        _check_name(item.get("name"))
    out = {}
    for item in files:
        problems = write_story(mod_name, item["name"], item.get("text") or "")
        if problems:
            out[item["name"]] = problems
    return {"count": len(files), "problems": out}


# ---------------------------------------------------------------------------- event listings

def event_images():
    """The images an event's banner can use (Pics/Icons/OPS/<name>.png), read once from the archived resource config."""
    if not _IMAGES:
        import UnityPy
        meta = json.loads((config.ARCHIVE_DIR / "resconfig.json").read_text("utf-8"))
        tree = next(o for o in UnityPy.load(str(config.ARCHIVE_DIR / meta["file"])).objects
                    if o.type.name == "MonoBehaviour").read_typetree()
        _IMAGES.extend(sorted({a["resName"][:-4] for sec in ("BaseAssetBundles", "AddAssetBundles") for e in tree[sec]
                               for a in e["assetAllRes"] if "/" + OPS_IMAGES in a["pathKey"] and a["resName"].endswith(".png")},
                              key=str.lower))
    return _IMAGES


def _map_id(entry):
    """A map grant is an id, or {"id": ...} when the studio's map editor wrote it."""
    return int(entry["id"] if isinstance(entry, dict) else entry)


def _event_text_key(row_id, digit):
    return f"normal_activity-{digit}{int(row_id):07d}"


def _event_of(mod, row):
    campaign = str(row.get("campaign_id"))
    return next((r for r in mod["tables"].get("mission_event", []) if str(r.get("mission_campaign")) == campaign), None)


def _event_design(mod_name, row_id):
    mod = w.load_mod(mod_name)
    row = next((r for r in mod["tables"].get("normal_activity", []) if str(r["id"]) == str(row_id)), None)
    if row is None:
        raise KeyError(f"no event {row_id} in this mod")
    meta, event = mod["meta"], _event_of(mod, row) or {}
    text = meta.get("text") or {}
    group, _, number = text.get(str(row.get("tag")), "").partition("|")
    first = int(event.get("init_mission_id") or 0)
    image = next((old for new, old in (meta.get("art") or {}).items() if new == f"Pics/Title/{row.get('bg_code')}.png"), "")
    stem = image.rsplit("/", 1)[-1].removesuffix(".png")
    title, short = text.get(str(row.get("chapter_name")), ""), text.get(str(row.get("name")), "")
    return {"kind": "event", "id": row["id"], "name": title, "in_mod": True,
            "group": group, "group_number": int(number) if number.isdigit() else 10, "order": row.get("order", 300),
            "list_name": "" if short == title else short, "description": w.decode_text(text.get(str(row.get("desc")), "")),
            "first_map": first, "image": stem, "colors": row.get("bg_config", DEFAULT_COLORS),
            "on_home": any(int(b.get("event") or 0) == int(event.get("id") or -1) for b in meta.get("banners") or []),
            "open_first_map": first in [_map_id(x) for x in (meta.get("grant") or {}).get("missions", [])],
            "event_id": event.get("id", 0)}


DEFAULT_COLORS = "#000000C7,#3D415166,#B43939FF,#FFFFFFFF"


def _new_event():
    return {"kind": "event", "id": w.free_ids("normal_activity", 1, 200)[0], "name": "", "in_mod": False, "group": "COLLAB", "group_number": 10,
            "order": 300, "list_name": "", "description": "", "first_map": 0, "image": "", "colors": DEFAULT_COLORS, "on_home": True,
            "open_first_map": True, "event_id": 0}


def _remove_event(mod, row_id):
    """Takes an event's rows, text, picture path, banner and map grant out of the mod; returns its row or None."""
    meta = mod["meta"]
    row = next((r for r in mod["tables"].get("normal_activity", []) if str(r["id"]) == str(row_id)), None)
    if row is None:
        return None
    event = _event_of(mod, row)
    w.put_rows(mod, "normal_activity", [], remove_keys=[row_id])
    if event:
        w.put_rows(mod, "mission_event", [], remove_keys=[event["id"]])
        meta["text"].pop(str(event.get("event_name")), None)
        meta["banners"] = [b for b in meta.get("banners") or [] if int(b.get("event") or 0) != int(event["id"])]
        missions = (meta.get("grant") or {}).get("missions")
        if missions:
            missions[:] = [x for x in missions if _map_id(x) != int(event.get("init_mission_id") or 0)]
    for field in ("tag", "name", "chapter_name", "desc"):
        meta["text"].pop(str(row.get(field)), None)
    (meta.get("art") or {}).pop(f"Pics/Title/{row.get('bg_code')}.png", None)
    return row


def _drop_empty(meta):
    for k in ("banners", "art"):
        if not meta.get(k):
            meta.pop(k, None)
    grant = meta.get("grant") or {}
    if "missions" in grant and not grant["missions"]:
        del grant["missions"]


def _save_event(mod, d):
    title = str(d.get("name") or "").strip()
    if not title:
        raise ValueError("give the event a name")
    first = int(d.get("first_map") or 0)
    mission = w.world_index("mission").get(str(first))
    if not mission:
        raise ValueError("pick the event's first map")
    campaign = int(mission["campaign"])
    if campaign >= 0:
        raise ValueError(f"map {first} is in chapter {campaign}. The event list is for maps in event campaigns (negative numbers); "
                         "maps made here are already listed in their mod's Campaign tab entry")
    image = str(d.get("image") or "")
    if image not in event_images():
        raise ValueError("pick the event's banner picture")
    row_id = int(d["id"])
    old = next((r for r in mod["tables"].get("normal_activity", []) if str(r["id"]) == str(row_id)), None)
    event = _event_of(mod, old) if old else None
    event_id = int(event["id"]) if event else w.free_ids("mission_event", 1, EVENT_IDS_FROM)[0]
    if old:
        _remove_event(mod, row_id)
    meta = mod["meta"]
    meta.setdefault("text", {})
    group = re.sub(r"[|,\r\n]", " ", str(d.get("group") or "EVENT")).strip() or "EVENT"
    keys = {"tag": _event_text_key(row_id, 1), "name": _event_text_key(row_id, 2), "chapter_name": _event_text_key(row_id, 3),
            "desc": _event_text_key(row_id, 4)}
    meta["text"].update({keys["tag"]: f"{group}|{int(d.get('group_number') or 10)}", keys["name"]: str(d.get("list_name") or title),
                         keys["chapter_name"]: title, keys["desc"]: str(d.get("description") or "")})
    bg = f"collab_{image}"
    w.put_rows(mod, "normal_activity", [{"id": row_id, "campaign_id": campaign, **keys, "order": int(d.get("order") or 300), "bg_code": bg,
                                         "bg_config": str(d.get("colors") or DEFAULT_COLORS), "scene_name": "", "event_prize_level": 0,
                                         "rank_id": ""}])
    name_key = f"mission_event-1{event_id:07d}"
    meta["text"][name_key] = title
    w.put_rows(mod, "mission_event", [{"id": event_id, "type": 2, "mission_campaign": str(campaign), "event_name": name_key,
                                       "init_mission_id": str(first)}])
    meta.setdefault("art", {})[f"Pics/Title/{bg}.png"] = f"{OPS_IMAGES}{image}.png"
    if d.get("on_home"):
        meta.setdefault("banners", []).append({"event": event_id, "pic": f"{OPS_IMAGES}{image}"})
    if d.get("open_first_map"):
        missions = meta.setdefault("grant", {}).setdefault("missions", [])
        if first not in [_map_id(x) for x in missions]:
            missions.append(first)
    _drop_empty(meta)
    return row_id


# ---------------------------------------------------------------------------- game text

def _text_design(mod_name):
    mod = w.load_mod(mod_name)
    base = w.base().text()
    event_keys = {str(r.get(f)) for r in mod["tables"].get("normal_activity", []) for f in ("tag", "name", "chapter_name", "desc")}
    event_keys |= {str(r.get("event_name")) for r in mod["tables"].get("mission_event", [])}
    import assets
    event_keys |= assets.owned(mod)[1]             # names of added pictures and music: edited on their page
    return {"kind": "text", "id": "all", "name": "Game text", "in_mod": True,
            "rows": [{"key": k, "original": w.decode_text(base.get(k, "")), "value": w.decode_text(v)}
                     for k, v in sorted((mod["meta"].get("text") or {}).items()) if k not in event_keys]}


def _save_text(mod, d):
    keep = {k: v for k, v in (mod["meta"].get("text") or {}).items() if k in
            {str(r.get(f)) for r in mod["tables"].get("normal_activity", []) for f in ("tag", "name", "chapter_name", "desc")} |
            {str(r.get("event_name")) for r in mod["tables"].get("mission_event", [])}}
    import assets
    keep.update({k: v for k, v in (mod["meta"].get("text") or {}).items() if k in assets.owned(mod)[1]})
    for row in d.get("rows") or []:
        key = str(row.get("key") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]+-\d+", key):
            raise ValueError(f"{key!r} is not a text key from the game")
        keep[key] = str(row.get("value") or "")
    mod["meta"]["text"] = keep


def search_text(q):
    """Up to 60 of the game's text entries that contain the words, to pick what to change."""
    q = str(q or "").strip().lower()
    if len(q) < 2:
        return []
    out = []
    for k, v in w.world_text().items():
        plain = w.decode_text(v)
        if q in k.lower() or q in plain.lower():
            out.append({"key": k, "text": plain})
            if len(out) >= 60:
                break
    return out


# ---------------------------------------------------------------------------- rows from the Chinese client

def cn_available():
    return CN_DIR.is_dir()


def cn_rows(table):
    if not re.fullmatch(r"\w+", table or "") or not (CN_DIR / f"{table}.json").is_file():
        raise ValueError(f"the Chinese data has no table called {table}")
    return json.loads((CN_DIR / f"{table}.json").read_text("utf-8"))


def copy_from_cn(mod_name, table, ids):
    """Copies whole rows by key into the mod, keeping only the columns this client has. Returns what was copied and what wasn't found."""
    wanted = {str(i).strip() for i in ids if str(i).strip()}
    key = w.key_of(table)
    columns = [f for f, _ in w.stc.schema()[table][1]]
    found = {str(r.get(key)): r for r in cn_rows(table) if str(r.get(key)) in wanted}
    rows = [{f: r[f] for f in columns if f in r} for r in found.values()]
    with w.LOCK:
        mod = w.load_mod(mod_name)
        w.put_rows(mod, table, rows)
        w.save_mod(mod_name, mod)
    res = w.check_mod(mod_name)
    res.update(copied=sorted(found), missing=sorted(wanted - set(found)))
    return res


# ---------------------------------------------------------------------------- what designs.py calls

# ---------------------------------------------------------------------------- game screen settings

def _config_design(mod_name):
    """The mod's "profile_edits" (lines of the client's own config files, gfserver/mods.py) as rows."""
    mod = w.load_mod(mod_name) if mod_name else {"meta": {}}
    edits = mod["meta"].get("profile_edits") or {}
    rows = [{"file": f, "from": str(e.get("from", "")), "to": str(e.get("to", ""))} for f, lst in sorted(edits.items()) for e in lst]
    return {"kind": "config", "id": "all", "name": "Game screen settings", "in_mod": bool(rows), "rows": rows}


def _save_config(mod, d):
    edits = {}
    for r in d.get("rows") or []:
        f, old = str(r.get("file") or "").strip().replace("\\", "/"), str(r.get("from") or "")
        if f and old.strip():
            edits.setdefault(f, []).append({"from": old, "to": str(r.get("to") or "")})
    if edits:
        mod["meta"]["profile_edits"] = edits
    else:
        mod["meta"].pop("profile_edits", None)


def get(mod_name, kind, eid):
    if kind == "config":
        return _config_design(mod_name)
    if kind == "story":
        _check_name(eid)
        return _story_design(mod_name, eid)
    if kind == "event":
        return _event_design(mod_name, eid)
    return _text_design(mod_name)


def new(kind, template=None):
    if kind == "config":
        return _config_design(None)
    if kind == "story":
        _check_name(template)
        return _story_design(None, template)
    return _new_event() if kind == "event" else {"kind": "text", "id": "all", "name": "Game text", "in_mod": False, "rows": []}


def save(mod_name, kind, d):
    with w.LOCK:
        problems = []
        if kind == "story":
            problems = write_story(mod_name, d["id"], _story_text(d.get("rows") or []))
            saved = d["id"]
        else:
            mod = w.load_mod(mod_name)
            saved = _save_event(mod, d) if kind == "event" else "all"
            if kind == "text":
                _save_text(mod, d)
            elif kind == "config":
                _save_config(mod, d)
            w.save_mod(mod_name, mod)
        res = w.check_mod(mod_name)
        res["id"] = saved
        res["problems"] = problems + res["problems"]
        return res


def delete(mod_name, kind, eid):
    with w.LOCK:
        if kind == "story":
            f = _story_file(mod_name, eid)
            if f:
                f.unlink()
        else:
            mod = w.load_mod(mod_name)
            if kind == "event":
                _remove_event(mod, eid)
                _drop_empty(mod["meta"])
            elif kind == "config":
                _save_config(mod, {"rows": []})
            else:
                _save_text(mod, {"rows": []})
            w.save_mod(mod_name, mod)
        return w.check_mod(mod_name)


def summary(mod_name, mod):
    """The sidebar's entries for these kinds."""
    d = story_dir(mod_name)
    text = mod["meta"].get("text") or {}
    events = [{"id": r["id"], "name": text.get(str(r.get("chapter_name")), "")} for r in mod["tables"].get("normal_activity", [])]
    shown = _text_design(mod_name)["rows"]
    return {"story": [{"id": p.name, "show": p.stem, "name": ""} for p in sorted(d.glob("*.txt"))] if d.is_dir() else [],
            "event": events, "text": [{"id": "all", "show": "All", "name": f"{len(shown)} text{'' if len(shown) == 1 else 's'} changed"}] if shown else [],
            "config": [{"id": "all", "show": "All", "name": f"{n} line{'' if n == 1 else 's'} changed"}] if (n := sum(len(v) for v in (mod["meta"].get("profile_edits") or {}).values())) else []}
