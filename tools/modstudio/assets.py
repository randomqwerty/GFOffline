"""Mod Studio: the game's pictures and music (tools/game_assets.py builds them into the game's files).

Replacing one stores the file under the game's name; adding one makes a new name from a template, plus the
rows that make the game offer it: a profile picture or home background is a friend_cosmetic + item row the
player is given (grant "items"); new music is a music_collection row (the base's music player); a new map
background is picked as a map's background. Files: mods/<mod>/art/assets/<category>/<name>.png (pictures,
at the template's size) or .adx (music, encoded here) with the uploaded sound file beside it for listening.
A map or home background also keeps the uploaded picture (<name>_source.png) and its placement (ga.placed).
"""
import base64
import io
import re
import sys

import studio as w

sys.path.insert(0, str(w.SERVER / "tools"))
import cri  # noqa: E402
import custom_art  # noqa: E402
import game_assets as ga  # noqa: E402

MAX_PICTURE = 40 * 2**20
MAX_SOUND = 10 * 60                     # seconds
MAX_PREVIEW = 20 * 2**20
THUMB = 256
COSMETIC_FROM, ITEM_FROM, MUSIC_FROM = 90001, 3900001, 9001
HELP = {
    "profile_pic": ("The small square picture on the player's profile and friend card.",
                    "A new profile picture is given to the player; pick it in the profile's appearance settings."),
    "home_bg": ("The picture behind the adjutant on the home screen, when this background is picked in the game's "
                "background settings. The game's own default background (shown when none is picked) can't be changed "
                "here. After choosing your picture you can move, zoom or fit it on the screen before saving; the small "
                "icon in the background list is made from it.",
                "A new background is given to the player; pick it in the home screen's background settings."),
    "map_bg": ("The picture under a map's nodes and roads. After choosing your picture you can see it under a map's "
               "nodes and move, zoom or fit it before saving.",
               "A new background for your own maps: open a map in this mod and set its background to the new name."),
    "music": ("A music track. Any sound file your browser can play works (MP3, OGG, WAV, M4A...). Tracks that loop in "
              "the game loop your whole file.",
              "New music shows in the base's music player, under the name you give it."),
}
_sizes, _catalogs = {}, {}


class Error(ValueError):
    pass


def _tree():
    return custom_art._config_tree()


def _catalog(cat):
    if cat not in ga.CATEGORIES:
        raise Error(f"unknown kind of asset {cat!r}")
    if cat not in _catalogs:
        _catalogs[cat] = ga.catalog(cat, _tree(), w.base().table)
    return _catalogs[cat]


def _entries(mod):
    return mod["meta"].get("game_assets") or {}


def categories():
    return [{"id": c, "label": v["label"], "kind": v["kind"], "help": HELP[c][0], "add_help": HELP[c][1]}
            for c, v in ga.CATEGORIES.items()]


def _pretty(key):
    """BGM_MissionSelect -> Mission Select, BGM_21Christmas_Battle -> 21 Christmas Battle"""
    k = re.sub(r"^BGM_?", "", key)
    k = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[0-9])(?=[A-Z][a-z])", " ", k).replace("_", " ").strip()
    return (k[:1].upper() + k[1:]) if k else key


def _names(cat, items):
    text = w.world_text()
    if cat in ("profile_pic", "home_bg"):
        rows = w.world_index("item")
        return {x["key"]: w.plain_text(w.text_of(text, (rows.get(str(x["item"])) or {}).get("item_name"))) or x["key"] for x in items}
    if cat == "map_bg":
        ms = w.world_index("mission")
        out = {}
        for x in items:
            labels = []
            for mid in x["missions"][:4]:
                r = ms.get(str(mid)) or {}
                labels.append(w.plain_text(w.text_of(text, r.get("name"))) or str(mid))
            more = len(x["missions"]) - len(labels)
            out[x["key"]] = ", ".join(dict.fromkeys(labels)) + (f" and {more} more" if more > 0 else "")
        return out
    return {x["key"]: (w.plain_text(w.text_of(text, (x["collection"] or {}).get("name"))) or _pretty(x["key"])) for x in items}


def listing(mod_name, cat):
    """{"items": the game's [{key, name, changed}], "own": this mod's new ones [{key, name, from}]}"""
    items = _catalog(cat)
    names = w.cached(("asset-names", cat), lambda: _names(cat, items))
    mine = _entries(w.load_mod(mod_name)) if mod_name else {}
    out = [{"key": x["key"], "name": names.get(x["key"]) or x["key"], "changed": f"{cat}/{x['key']}" in mine,
            "seconds": int(((x.get("collection") or {}).get("time")) or 0), "moving": bool(x.get("moving"))} for x in items]
    own = [{"key": ref.split("/", 1)[1], "name": e.get("name") or ref.split("/", 1)[1], "from": e.get("from"),
            "preview": bool(e.get("preview")), "place": e.get("place") if e.get("source") else None}
           for ref, e in mine.items() if ref.startswith(cat + "/") and e.get("new")]
    for x in out:
        if x["changed"]:
            e = mine[f"{cat}/{x['key']}"]
            x["preview"], x["place"] = bool(e.get("preview")), e.get("place") if e.get("source") else None
    return {"items": out, "own": own}


def owned(mod):
    """({(table, key)}, {text keys}) the mod's added pictures and music own: edited on their page, not listed elsewhere."""
    rows, keys = set(), set()
    for e in _entries(mod).values():
        if e.get("cosmetic"):
            rows.add(("friend_cosmetic", str(e["cosmetic"])))
        if e.get("item"):
            rows.add(("item", str(e["item"])))
            keys |= {f"item-{d}{int(e['item']):07d}" for d in "123"}
        if e.get("collection"):
            rows.add(("music_collection", str(e["collection"])))
            keys |= {f"music_collection-{d}{int(e['collection']):07d}" for d in "12"}
    return rows, keys


def summary(mod):
    """Sidebar entries: [{"id": "<category>/<key>", "name"}] of the mod's replaced and added assets."""
    out = []
    for ref, e in sorted(_entries(mod).items()):
        cat, key = ref.split("/", 1)
        label = ga.CATEGORIES.get(cat, {}).get("label", cat)
        name = e.get("name")
        if not name and cat in ga.CATEGORIES:
            try:
                name = w.cached(("asset-names", cat), lambda: _names(cat, _catalog(cat))).get(key)
            except Exception:
                name = None
        out.append({"id": ref, "show": "new" if e.get("new") else "changed", "name": f"{label}: {name or key}"})
    return out


# ---------------------------------------------------------------------------- pictures

def _game_picture(cat, key, which=0):
    return ga.picture(cat, key, _tree(), which=which)


def _size(cat, key):
    if (cat, key) not in _sizes:
        _sizes[(cat, key)] = _game_picture(cat, key).size
    return _sizes[(cat, key)]


def _png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _thumb(img):
    img = img.copy()
    img.thumbnail((THUMB, THUMB))
    return _png(img)


def thumb(mod_name, cat, key):
    """PNG: the mod's picture if it has one for that name, else the game's (cached on disk)."""
    from PIL import Image
    e = _entries(w.load_mod(mod_name)).get(f"{cat}/{key}") if mod_name else None
    if e:
        src = w.mod_dir(mod_name) / e["source"] if e.get("source") and e.get("place") else None
        if src and src.is_file():               # placed: at the shape the game shows it
            area = ga.HOME_AREA if cat == "home_bg" else e["place"]["area"]
            k = THUMB * 2 / max(area)
            return _thumb(ga.place(Image.open(src), area, (max(1, round(area[0] * k)), max(1, round(area[1] * k))), e["place"]))
        f = w.mod_dir(mod_name) / e["file"]
        return _thumb(Image.open(f)) if f.is_file() else None
    cache = w.CACHE / "asset_thumbs" / cat
    if not (cache / f"{key}.png").is_file():
        # every picture of the category in the same bundle at once: the bundle is loaded once
        tree = _tree()
        bundle = ga._bundle_of(tree, ga.paths(cat, key)[0])[1]["assetBundleName"]
        cache.mkdir(parents=True, exist_ok=True)
        for x in _catalog(cat):
            if x["key"] == key or (not (cache / f"{x['key']}.png").is_file()
                                   and ga._bundle_of(tree, ga.paths(cat, x["key"])[0])[1]["assetBundleName"] == bundle):
                try:
                    (cache / f"{x['key']}.png").write_bytes(_thumb(_game_picture(cat, x["key"])))
                except ga.AssetError:
                    pass
    f = cache / f"{key}.png"
    return f.read_bytes() if f.is_file() else None


def template_png(cat, key):
    return _png(_game_picture(cat, key))


def mod_file(mod_name, cat, key, which=""):
    """(bytes, content type) of the mod's stored picture (which "source": the uploaded one of a map background),
    or of the sound file uploaded for a track."""
    e = _entries(w.load_mod(mod_name)).get(f"{cat}/{key}")
    if not e:
        return None
    rel = (e.get("source") if which == "source" else e["file"]) if ga.CATEGORIES[cat]["kind"] == "picture" else e.get("preview")
    f = w.mod_dir(mod_name) / rel if rel else None
    if not f or not f.is_file():
        return None
    types = {".png": "image/png", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".wav": "audio/wav",
             ".flac": "audio/flac", ".opus": "audio/ogg", ".webm": "audio/webm"}
    return f.read_bytes(), types.get(f.suffix.lower(), "application/octet-stream")


def _open_picture(data_url):
    from PIL import Image
    raw = base64.b64decode(str(data_url).split(",", 1)[-1])
    if len(raw) > MAX_PICTURE:
        raise Error("That picture is too large (over 40 MB).")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.width * img.height > 8192 * 8192:
            raise Error("That picture is too large (over 8192 x 8192).")
        img.load()
    except (OSError, SyntaxError):
        raise Error("That file can't be read as a picture (use PNG, JPG, WebP, GIF or BMP).")
    return img


def _sound(body):
    """ADX bytes and length in seconds from the browser's decoded sound: {"pcm": base64 int16 interleaved, "rate", "channels"}."""
    import numpy as np
    rate, ch = int(body.get("rate") or 0), int(body.get("channels") or 0)
    if not 8000 <= rate <= 96000 or ch not in (1, 2):
        raise Error("That sound can't be used (it needs one or two channels).")
    pcm = np.frombuffer(base64.b64decode(str(body.get("pcm") or "")), dtype="<i2")
    if not len(pcm):
        raise Error("That sound file is empty.")
    if len(pcm) / ch / rate > MAX_SOUND:
        raise Error(f"That sound is too long (over {MAX_SOUND // 60} minutes).")
    pcm = pcm[:len(pcm) // ch * ch].reshape(-1, ch)
    return cri.encode_adx(pcm, rate, loop=True), len(pcm) / rate


def _rows_by(table, field):
    return w.cached(("rows-by", table, field), lambda: _group(w.world_table(table), field))


def _group(rows, field):
    out = {}
    for r in rows:
        out.setdefault(str(r.get(field)), []).append(r)
    return out


def maps_using(key, also=None, limit=24, mod_name=None):
    """The maps a map background lies under, to preview it on: [{"id", "name", "area": [w, h], "view": [w, h, x, y]
    or None, "spots": [{x, y, belong}], "routes": [[x1, y1, x2, y2]]}]. area: the picture's size; view: the part
    the game shows (map_information's second and third pairs; the rest is darkened). also: the template's name,
    for a new one no map uses yet. Maps the mod changes come first."""
    text = w.world_text()
    spots = _rows_by("spot", "mission_id")
    mine = set()
    if mod_name:
        tables = w.load_mod(mod_name)["tables"]
        mine = {str(r.get("id")) for r in tables.get("mission") or []} | {str(r.get("mission_id")) for r in tables.get("spot") or []}
    out = []
    for want in [key] + ([also] if also else []):
        for m in sorted(w.world_table("mission"), key=lambda m: str(m["id"]) not in mine):
            names = str(m.get("map_res_name") or "").split(";")
            infos = str(m.get("map_information") or "").split(";")
            for layer, name in enumerate(names):
                hit = re.match(r"^\s*(-?[\d.]+),(-?[\d.]+)\|", infos[layer]) if layer < len(infos) else None
                if name != want or not hit:
                    continue
                ss = [r for r in spots.get(str(m["id"]), []) if int(r.get("map_num") or 0) == layer]
                at = {str(r["id"]): (r["coordinator_x"], r["coordinator_y"]) for r in ss}
                routes = [[*at[str(r["id"])], *at[t]] for r in ss for t in str(r.get("route") or "").split(",") if t in at]
                label = w.plain_text(w.text_of(text, m.get("name"))) or str(m["id"])
                view = re.match(r"^\s*-?[\d.]+,-?[\d.]+\|(-?[\d.]+),(-?[\d.]+)\|(-?[\d.]+),(-?[\d.]+)", infos[layer])
                out.append({"id": m["id"], "name": label + (f" (layer {layer + 1})" if layer else ""),
                            "area": [abs(float(hit.group(1))), abs(float(hit.group(2)))],
                            "view": [abs(float(view.group(1))), abs(float(view.group(2))), float(view.group(3)),
                                     float(view.group(4))] if view else None,
                            "spots": [{"x": r["coordinator_x"], "y": r["coordinator_y"], "belong": r.get("belong")} for r in ss],
                            "routes": routes})
                if len(out) >= limit:
                    return out
        if out:
            return out
    return out


def _place(mod_name, cat, key, entry, place, img=None):
    """Store a map or home background's source picture (when given) and its placement, and render the file from them."""
    folder = w.mod_dir(mod_name) / "art" / "assets" / cat
    if img is not None:
        img = img.convert("RGBA")
        if max(img.size) > 4096:
            img.thumbnail((4096, 4096))
        (folder / f"{key}_source.png").write_bytes(_png(img))
        entry["source"] = f"art/assets/{cat}/{key}_source.png"
    src = w.mod_dir(mod_name) / entry["source"] if entry.get("source") else None
    if not src or not src.is_file():
        raise Error("Choose the picture again: the one uploaded before is gone.")
    tpl = entry.get("from") if entry.get("new") else key
    place = dict(place or {})
    area = place.get("area")
    if cat == "home_bg":
        area = list(ga.HOME_AREA)
    elif not (isinstance(area, list) and len(area) == 2 and all(isinstance(v, (int, float)) and 1 <= abs(v) <= 100000 for v in area)):
        maps = maps_using(key, tpl)
        area = maps[0]["area"] if maps else list(_size(cat, tpl))
    from PIL import Image
    p = {"mode": place.get("mode") if place.get("mode") in ga.PLACE_MODES else "fill",
         "zoom": ga._num(place.get("zoom"), 1.0, 1 / ga.LIMIT),
         "x": ga._num(place.get("x"), 0.0), "y": ga._num(place.get("y"), 0.0),
         "area": [float(area[0]), float(area[1])]}
    (folder / f"{key}.png").write_bytes(_png(ga.placed(cat, Image.open(src), p, [_size(cat, tpl)])[0]))
    entry["file"], entry["place"] = f"art/assets/{cat}/{key}.png", p


def _store(mod_name, cat, key, body, entry):
    """Write the uploaded file for one name; fills entry["file"] (and "preview" for music)."""
    folder = w.mod_dir(mod_name) / "art" / "assets" / cat
    folder.mkdir(parents=True, exist_ok=True)
    if cat in ("map_bg", "home_bg"):
        try:
            _place(mod_name, cat, key, entry, body.get("place"), _open_picture(body["data"]) if body.get("data") else None)
        except (TypeError, ValueError) as e:
            raise Error(str(e) if isinstance(e, Error) else "That placement can't be used.")
        return
    if ga.CATEGORIES[cat]["kind"] == "picture":
        tpl = entry.get("from") if entry.get("new") else key
        img = ga.cover(_open_picture(body.get("data")), _size(cat, tpl))
        (folder / f"{key}.png").write_bytes(_png(img))
        entry["file"] = f"art/assets/{cat}/{key}.png"
        return
    adx, seconds = _sound(body)
    (folder / f"{key}.adx").write_bytes(adx)
    entry["file"], entry["seconds"] = f"art/assets/{cat}/{key}.adx", round(seconds)
    for old in folder.glob(f"{key}.*"):
        if old.suffix.lower() not in (".adx",) and old.stem == key:
            old.unlink()
    entry.pop("preview", None)
    ext = re.sub(r"[^a-z0-9]", "", str(body.get("ext") or "").lower())
    if body.get("preview") and "." + ext in ga_preview_kinds():
        raw = base64.b64decode(str(body["preview"]).split(",", 1)[-1])
        if len(raw) <= MAX_PREVIEW:
            (folder / f"{key}.{ext}").write_bytes(raw)
            entry["preview"] = f"art/assets/{cat}/{key}.{ext}"


def ga_preview_kinds():
    from gfserver import mod_share
    return [k for k in mod_share.ART_KINDS if k not in (".png", ".adx")]


def upload(mod_name, body):
    """Replace one of the game's assets, or change the file of one this mod added: {"cat", "key", data or pcm...}."""
    try:
        return _upload(mod_name, body)
    except (Error, ga.AssetError, cri.CriError) as e:
        raise w.mods.ModError(str(e))


def _upload(mod_name, body):
    cat, key = body.get("cat"), str(body.get("key") or "")
    with w.LOCK:
        mod = w.load_mod(mod_name)
        assets = mod["meta"].setdefault("game_assets", {})
        entry = assets.get(f"{cat}/{key}")
        if entry is None:
            if key not in {x["key"] for x in _catalog(cat)}:
                raise Error(f"the game has no {ga.CATEGORIES[cat]['label'].lower()} called {key}")
            entry = {}
        _store(mod_name, cat, key, body, entry)
        assets[f"{cat}/{key}"] = entry
        w.save_mod(mod_name, mod)
    return listing(mod_name, cat)


def _taken(cat):
    """Names already used by the game or any mod."""
    keys = {x["key"].lower() for x in _catalog(cat)}
    for n in w.all_mod_names():
        keys |= {ref.split("/", 1)[1].lower() for ref in _entries(w.load_mod(n)) if ref.startswith(cat + "/")}
    return keys


def add(mod_name, body):
    """Add a new one: {"cat", "from": template key, "name": shown name, data or pcm...}. Returns the listing."""
    try:
        return _add(mod_name, body)
    except (Error, ga.AssetError, cri.CriError) as e:
        raise w.mods.ModError(str(e))


def _add(mod_name, body):
    cat, src = body.get("cat"), str(body.get("from") or "")
    templates = {x["key"]: x for x in _catalog(cat)}
    if src not in templates:
        raise Error("Pick which of the game's ones the new one is made from.")
    name = str(body.get("name") or "").strip()[:60] or f"New {ga.CATEGORIES[cat]['label'].lower()[:-1]}"
    with w.LOCK:
        mod = w.load_mod(mod_name)
        taken = _taken(cat)
        entry = {"new": True, "from": src, "name": name}
        text = mod["meta"].setdefault("text", {})
        if cat in ("profile_pic", "home_bg"):
            cid = w.free_ids("friend_cosmetic", start=COSMETIC_FROM)[0]
            iid = w.free_ids("item", start=ITEM_FROM)[0]
            key = ("profilePic_Own" if cat == "profile_pic" else "cg_Own") + str(cid)
            t = templates[src]
            w.put_rows(mod, "friend_cosmetic", [{
                "id": cid, "_copy": t["cosmetic"], "item_id": iid, "code": key + (".png" if cat == "profile_pic" else ""),
                "onsale": 0, "in_gasha": 0, "gem": 0, "mp": 0, "ammo": 0, "mre": 0, "part": 0, "item_ids": "",
                "decompose_gift": "", "event_id": 0, "skin": 0, "is_live2d": 0}])
            w.put_rows(mod, "item", [{"id": iid, "_copy": t["item"], "code": key, "item_name": f"item-1{iid:07d}",
                                      "introduction": f"item-2{iid:07d}", "detail_introduction": f"item-3{iid:07d}"}])
            text[f"item-1{iid:07d}"] = name
            text[f"item-2{iid:07d}"] = text[f"item-3{iid:07d}"] = f"From the mod {mod['meta'].get('name') or mod_name}."
            w.set_grant(mod, "items", iid, iid)
            entry.update(cosmetic=cid, item=iid)
        elif cat == "map_bg":
            n = 1
            while f"ownmap{n}_y" in taken:
                n += 1
            key = f"OwnMap{n}_Y"
        else:
            n = 1
            while f"bgm_own{n}" in taken:
                n += 1
            key = f"BGM_Own{n}"
            mid = w.free_ids("music_collection", start=MUSIC_FROM)[0]
            copy = (templates[src].get("collection") or {}).get("id") or w.base().table("music_collection")[0]["id"]
            orders = [int(r.get("order") or 0) for r in w.world_table("music_collection")]
            w.put_rows(mod, "music_collection", [{"id": mid, "_copy": copy, "type": 1, "code": key,
                                                  "name": f"music_collection-1{mid:07d}", "detail": f"music_collection-2{mid:07d}",
                                                  "unlock_mission": "", "order": max(orders or [0]) + 1}])
            text[f"music_collection-1{mid:07d}"] = name
            text[f"music_collection-2{mid:07d}"] = f"From the mod {mod['meta'].get('name') or mod_name}."
            entry["collection"] = mid
        _store(mod_name, cat, key, body, entry)
        if cat == "music":
            w.put_rows(mod, "music_collection", [dict(mod["tables"]["music_collection"][-1], time=entry.get("seconds") or 0)])
        mod["meta"].setdefault("game_assets", {})[f"{cat}/{key}"] = entry
        w.save_mod(mod_name, mod)
    return dict(listing(mod_name, cat), added=key)


def rename(mod_name, body):
    """The shown name of one this mod added: {"cat", "key", "name"}."""
    cat, key, name = body.get("cat"), str(body.get("key") or ""), str(body.get("name") or "").strip()[:60]
    with w.LOCK:
        mod = w.load_mod(mod_name)
        e = _entries(mod).get(f"{cat}/{key}")
        if not e or not e.get("new") or not name:
            return listing(mod_name, cat)
        e["name"] = name
        if e.get("item"):
            mod["meta"]["text"][f"item-1{int(e['item']):07d}"] = name
        if e.get("collection"):
            mod["meta"]["text"][f"music_collection-1{int(e['collection']):07d}"] = name
        w.save_mod(mod_name, mod)
    return listing(mod_name, cat)


def remove(mod_name, body):
    """Undo a replacement, or delete one this mod added (its rows too): {"cat", "key"}."""
    cat, key = body.get("cat"), str(body.get("key") or "")
    with w.LOCK:
        mod = w.load_mod(mod_name)
        assets = _entries(mod)
        e = assets.pop(f"{cat}/{key}", None)
        if e is None:
            return listing(mod_name, cat)
        folder = w.mod_dir(mod_name) / "art" / "assets" / cat
        for f in folder.glob(f"{key}*") if folder.is_dir() else ():
            if f.stem in (key, key + "_source"):
                f.unlink()
        if e.get("cosmetic"):
            w.put_rows(mod, "friend_cosmetic", [], remove_keys=[e["cosmetic"]])
        if e.get("item"):
            iid = int(e["item"])
            w.put_rows(mod, "item", [], remove_keys=[iid])
            w.set_grant(mod, "items", iid, None)
            for d in "123":
                mod["meta"]["text"].pop(f"item-{d}{iid:07d}", None)
        if e.get("collection"):
            mid = int(e["collection"])
            w.put_rows(mod, "music_collection", [], remove_keys=[mid])
            for d in "12":
                mod["meta"]["text"].pop(f"music_collection-{d}{mid:07d}", None)
        if not assets:
            mod["meta"].pop("game_assets", None)
        w.save_mod(mod_name, mod)
    return listing(mod_name, cat)


def own_map_backgrounds():
    """Map background names the mods added: [{"key", "name", "mod"}] (for the map editor)."""
    out = []
    for n in w.all_mod_names():
        for ref, e in _entries(w.load_mod(n)).items():
            if ref.startswith("map_bg/") and e.get("new"):
                out.append({"key": ref.split("/", 1)[1], "name": e.get("name") or "", "mod": n})
    return out
