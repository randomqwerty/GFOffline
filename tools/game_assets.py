"""The game's pictures and music in mods: replace one, or add a new one made from a template.

  mod.json "game_assets": {"<category>/<key>": {"file": "art/assets/<category>/<key>.png",
                                               "new": true, "from": "<key of the template>",   (new: only for added ones)
                                               "source": "art/assets/<category>/<key>_source.png", "place": {...}}}
  source + place (map and home backgrounds): the uploaded picture and how it lies on the map or the home
  screen, rendered by placed().

Categories (CATEGORIES), each found by path from the archived resource config:
  profile_pic  Pics/CardAvatar/<code>.png        friend_cosmetic sub_type 1 (code with ".png")
  home_bg      Pics/CardHomeBg/<code>.png + <code>_icon.png (the list icon, made from the picture)
               friend_cosmetic sub_type 3. The home screen draws <code>_prefab.prefab (resource_cardhomebg_c,
               an Image on the <code>.png sprite); with animated backgrounds on it first tries the Live2D
               <code>_New_Live2D.prefab and falls back to the still one when that path is unknown
               (HomeController.ShowHomeBg / GetBGLive2D). Every such prefab stretches the picture over a
               2048 x 1536 frame (HOME_AREA) on black; the UI is laid out for 16:9 (Utility.rr = screen
               aspect / (16/9)), so a 16:9 screen shows about the middle 2048 x 1152 (HOME_SCREEN).
               Without a picked background it shows
               UGUIPrefabs/Home/BGDefault_prefab from the game's own Resources: not replaceable here.
  map_bg       Maps/<name>.png                   mission.map_res_name. The client stretches the texture over the
               layer's map size (map_information "<w>,<h>|...", DeploymentBackgroundController.CreateBackground)
               centred on the nodes' origin; past its edges SetFrame adds 8 mirrored copies (UIImageMirror).
               The camera shows only the layer's view (second and third pairs: size, centre); the rest is darkened.
  music        <name>.acb (resource config bytesData; the game copy's Res/Pc/<name>.acb.bytes)
               one cue and one waveform with the sound inside (cri.py)
The client builds these paths from the codes (ItemInfo.get_codePath: Pics/CardAvatar/, Pics/CardHomeBg/,
Pics/CardBG/; AudioResManager.LoadBytesBGM: DaBao/Audio/BGM/<name>.acb).

Replacing: the bundle holding the picture is rebuilt with the picture swapped (same bundle name and CAB,
like build_mods.py's art), written to build/<bundle file> and declared with its new size; a music file
gets the new sound (cri.replace_sound) and its bytesData sizes.
A replaced home background's Live2D version is left out of the resource config, so the game shows the
still picture (listing "still").
Adding: a copy of the template's bundle with only the template's picture (custom_art.clone_prefabs),
renamed to the new code, with its own bundle and CAB name, declared through custom_art.add_entries (a new
home background also gets a copy of the template's _prefab pointing at the copied picture); a
new music file is the template's with the new name and sound, added to bytesData. The rows that make
the game show a new one (friend_cosmetic + item + a grant, music_collection) are ordinary mod rows the
studio writes; a new map background is used by naming it in a map's background.
Pictures are stored at the template's size; music as ADX (cri.encode_adx), made when uploaded.
"""
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import custom_art
import cri

ROOT = Path(__file__).resolve().parent.parent
LIST_FILE = ROOT / "build" / "game_assets.json"
PREFIX = "gfmodasset"                   # file names of added bundles and sounds
DABAO = "Assets/Resources/DaBao/"
CATEGORIES = {
    "profile_pic": {"label": "Profile pictures", "kind": "picture", "folder": "Pics/CardAvatar/"},
    "home_bg": {"label": "Home screen backgrounds", "kind": "picture", "folder": "Pics/CardHomeBg/"},
    "map_bg": {"label": "Map backgrounds", "kind": "picture", "folder": "Maps/"},
    "music": {"label": "Music", "kind": "sound"},
}
CODE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,63}")


class AssetError(ValueError):
    pass


# ---------------------------------------------------------------------------- what the game has

_indexes = {}


def _index(tree):
    """{pathKey lower: (section, entry)} (kept per tree while its sections keep their length)."""
    stamp = (id(tree), len(tree["BaseAssetBundles"]), len(tree["AddAssetBundles"]))
    if _indexes.get("stamp") != stamp:
        _indexes.update(stamp=stamp, index={a["pathKey"].lower(): (sec, e) for sec in ("BaseAssetBundles", "AddAssetBundles")
                                            for e in tree[sec] for a in e["assetAllRes"]})
    return _indexes["index"]


def _pathkey(index, rel):
    hit = index.get((DABAO + rel).lower())
    if hit is None:
        return None
    return next(a["pathKey"] for a in hit[1]["assetAllRes"] if a["pathKey"].lower() == (DABAO + rel).lower())


def paths(cat, key):
    """The DaBao-relative paths of one picture: the main one first."""
    if cat == "profile_pic":
        return [f"Pics/CardAvatar/{key}.png"]
    if cat == "home_bg":
        return [f"Pics/CardHomeBg/{key}.png", f"Pics/CardHomeBg/{key}_icon.png"]
    if cat == "map_bg":
        return [f"Maps/{key}.png"]
    raise AssetError(f"{cat} has no pictures")


def home_prefab(key):
    return f"Pics/CardHomeBg/{key}_prefab.prefab"


def home_live2d(key):
    return f"Pics/CardHomeBg/{key}_New_Live2D.prefab"


def catalog(cat, tree, table):
    """The game's own assets of a category: [{"key", ...}] (table(name) gives stc rows).
    profile_pic / home_bg: "cosmetic" (friend_cosmetic id), "item"; map_bg: "missions" (ids using it);
    home_bg also "moving" (it has a Live2D version); music: "file" (the .acb name), "collection" (music_collection row or None)."""
    if cat == "music":
        coll = {r["code"]: r for r in table("music_collection")}
        out = []
        for b in tree.get("bytesData") or []:
            name = b["fileName"]
            if not name.lower().endswith(".acb"):
                continue
            key = name[:-4]
            if key.startswith("BGM") or key in coll:
                out.append({"key": key, "file": name, "collection": coll.get(key)})
        return sorted(out, key=lambda x: x["key"].lower())
    index = _index(tree)
    if cat == "map_bg":
        uses = {}
        for r in table("mission"):
            for name in str(r.get("map_res_name") or "").split(";"):
                if name:
                    uses.setdefault(name, []).append(int(r["id"]))
        return [{"key": k, "missions": v} for k, v in sorted(uses.items()) if _pathkey(index, f"Maps/{k}.png")]
    sub = {"profile_pic": 1, "home_bg": 3}[cat]
    out = []
    for r in table("friend_cosmetic"):
        if int(r["sub_type"]) != sub:
            continue
        key = re.sub(r"\.png$", "", str(r["code"]), flags=re.I)
        if not key or not _pathkey(index, paths(cat, key)[0]):
            continue
        x = {"key": key, "cosmetic": int(r["id"]), "item": int(r["item_id"])}
        if cat == "home_bg":
            if not _pathkey(index, home_prefab(key)):
                continue
            x["moving"] = bool(_pathkey(index, home_live2d(key)))
        out.append(x)
    return out


def _bundle_of(tree, rel):
    hit = _index(tree).get((DABAO + rel).lower())
    if hit is None:
        raise AssetError(f"the game has no picture {rel}")
    return hit


def _find_original(fname):
    return custom_art._find_original(fname)


def find_sound(entry, find=_find_original):
    """The original bytes of a bytesData file: kept by setup or a build, else unpacked from the archive's
    <resname>.dat, else the game copy's (Res/Pc/<fileName>.bytes)."""
    import sys
    sys.path.insert(0, str(ROOT))
    from gfserver import config
    local = entry["fileName"] + ".bytes"
    hits = config.original_bundles(local)
    if hits:
        return hits[0].read_bytes()
    dat = config.ARCHIVE_DIR / "cdn" / "pc" / (entry["resname"] + ".dat")
    if dat.is_file():
        with zipfile.ZipFile(dat) as z:
            return z.read(z.namelist()[0])
    game = config.pc_dir(config.GAME_DIR) / local
    if game.is_file():
        return game.read_bytes()
    raise AssetError(f"the music file {entry['fileName']} is not on this computer (press Set up in the launcher)")


def sound_entry(tree, key):
    e = next((b for b in tree.get("bytesData") or [] if b["fileName"].lower() == (key + ".acb").lower()), None)
    if e is None:
        raise AssetError(f"the game has no music called {key}")
    return e


# ---------------------------------------------------------------------------- pictures

_envs = {}


def _env(path):
    """A loaded bundle (the last few kept: the home backgrounds are one 40 MB bundle)."""
    import UnityPy
    key = str(path)
    if key not in _envs:
        if len(_envs) >= 3:
            _envs.pop(next(iter(_envs)))
        _envs[key] = UnityPy.load(key)
    return _envs[key]


def _textures(env, rel):
    """The Texture2D objects a container path points at."""
    want = (DABAO + rel).lower()
    ab = next(o for o in env.objects if o.type.name == "AssetBundle").read_typetree()
    ids = {info["asset"]["m_PathID"] for p, info in ab["m_Container"] if p == want}
    return [o for o in env.objects if o.path_id in ids and o.type.name == "Texture2D"]


def picture(cat, key, tree, find=_find_original, which=0):
    """The game's picture (PIL RGBA): which 0 the main one, 1 the home background's list icon."""
    rel = paths(cat, key)[which]
    _, e = _bundle_of(tree, rel)
    f = find(e["resname"] + ".ab")
    if f is None:
        raise AssetError(f"the bundle with {rel} is not on this computer (press Set up in the launcher)")
    tex = _textures(_env(f), rel)
    if not tex:
        raise AssetError(f"{rel} is not a picture")
    return tex[0].read().image.convert("RGBA")


def cover(img, size):
    """The picture scaled to fill size, centre cropped."""
    from PIL import Image
    w, h = size
    img = img.convert("RGBA")
    scale = max(w / img.width, h / img.height)
    r = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.LANCZOS)
    x, y = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((x, y, x + w, y + h))


def _set_texture(obj, img):
    t = obj.read()
    if img.size != (t.m_Width, t.m_Height):
        img = cover(img, (t.m_Width, t.m_Height))
    t.set_image(img, target_format=t.m_TextureFormat, mipmap_count=max(1, int(t.m_MipCount or 1)))
    if t.m_StreamData is not None:
        t.m_StreamData.path, t.m_StreamData.offset, t.m_StreamData.size = "", 0, 0
    t.save()


def _swap(data, images):
    """Bundle bytes with the pictures at the given DaBao-relative paths replaced: {rel: PIL image}."""
    import UnityPy
    env = UnityPy.load(data)
    for rel, img in images.items():
        texes = _textures(env, rel)
        if not texes:
            raise AssetError(f"{rel} is not a picture in its bundle")
        for o in texes:
            _set_texture(o, img)
    return env.file.save(packer="original")


PLACE_MODES = ("fill", "fit", "stretch")
HOME_AREA, HOME_SCREEN = (2048, 1536), (2048, 1152)
LIMIT = 1e6                                     # zoom and offsets: any finite size, bounded only against overflow


def _num(v, default, low=-LIMIT):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return min(LIMIT, max(low, v)) if v == v else default


def place(img, area, size, p):
    """The texture (PIL RGBA at size) for a picture laid on a map area (w, h in map units) the client stretches
    the texture over. p: {"mode": fill | fit | stretch, "zoom", "x", "y"}; x, y move the picture's centre by
    that fraction of the area's width and height (y down); what it doesn't cover is black."""
    from PIL import Image
    W, H = (max(1.0, abs(float(v))) for v in area)
    tw, th = size
    img = img.convert("RGBA")
    mode = p.get("mode") if p.get("mode") in PLACE_MODES else "fill"
    zoom = _num(p.get("zoom"), 1.0, 1 / LIMIT) or 1.0
    if mode == "stretch":
        w, h = W * zoom, H * zoom
    else:
        k = (max if mode == "fill" else min)(W / img.width, H / img.height) * zoom
        w, h = img.width * k, img.height * k
    cx, cy = W / 2 + _num(p.get("x"), 0.0) * W, H / 2 + _num(p.get("y"), 0.0) * H
    sx, sy = tw / W, th / H                         # map units -> texture pixels
    ow, oh = w * sx, h * sy                         # the picture's size in texture pixels
    left, top = (cx - w / 2) * sx, (cy - h / 2) * sy
    if left >= tw or top >= th or left + ow <= 0 or top + oh <= 0:
        return Image.new("RGBA", (tw, th), (0, 0, 0, 255))
    if ow < img.width or oh < img.height:           # shrink first: the affine step doesn't smooth
        img = img.resize((max(1, min(img.width, round(ow))), max(1, min(img.height, round(oh)))), Image.LANCZOS)
    kx, ky = ow / img.width, oh / img.height
    out = img.transform((tw, th), Image.AFFINE, (1 / kx, 0, -left / kx, 0, 1 / ky, -top / ky),
                        resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    back = Image.new("RGBA", (tw, th), (0, 0, 0, 255))
    back.alpha_composite(out)
    return back


def placed(cat, img, p, sizes):
    """[picture per path of the category] for an uploaded picture and its placement; sizes: the textures'.
    A home background's list icon is the frame's middle square."""
    area = p.get("area") if cat == "map_bg" else HOME_AREA
    out = [place(img, area, sizes[0], p)]
    if cat == "home_bg" and len(sizes) > 1:
        view = place(img, HOME_AREA, (1024, 768), p)
        out.append(cover(view, sizes[1]))
    return out


def _images(cat, img):
    """{path index: picture} for one upload: a home background's list icon is made from it."""
    out = {0: img}
    if cat == "home_bg":
        out[1] = img
    return out


# ---------------------------------------------------------------------------- mods

def collect(found):
    """{(category, key): {"file", "new", "from", "mod"}} of the enabled mods (a later mod's entry wins)."""
    out = {}
    for m in found:
        for ref, spec in (m.get("game_assets") or {}).items():
            cat, _, key = str(ref).partition("/")
            if cat not in CATEGORIES or not CODE.fullmatch(key):
                raise AssetError(f"{m['name']}: game asset {ref!r}: expected <category>/<name>")
            spec = spec or {}
            f = (Path(m["dir"]) / str(spec.get("file") or "")).resolve()
            if Path(m["dir"]).resolve() not in f.parents or not f.is_file():
                raise AssetError(f"{m['name']}: game asset {ref}: the file {spec.get('file')} is missing")
            new = bool(spec.get("new"))
            src = str(spec.get("from") or "")
            if new and not CODE.fullmatch(src):
                raise AssetError(f"{m['name']}: game asset {ref}: a new one needs the template it is made from")
            source, pl = spec.get("source"), spec.get("place")
            if source and isinstance(pl, dict) and cat in ("map_bg", "home_bg"):
                source = (Path(m["dir"]) / str(source)).resolve()
                if Path(m["dir"]).resolve() not in source.parents or not source.is_file():
                    raise AssetError(f"{m['name']}: game asset {ref}: the file {spec.get('source')} is missing")
                if cat == "map_bg" and not (isinstance(pl.get("area"), list) and len(pl["area"]) == 2):
                    raise AssetError(f"{m['name']}: game asset {ref}: its placement needs the map size (area)")
            else:
                source = pl = None
            out[(cat, key)] = {"file": f, "new": new, "from": src, "mod": m["name"], "source": source, "place": pl}
    return out


def bundle_name(cat, key):
    return f"resource_gfmod_{cat}_{key.lower()}"


def file_of(name):
    return PREFIX + re.sub(r"[^a-z0-9]", "", name.lower()) + ".ab"


def build(spec, out_dir, find=_find_original, tree=None, built=(), log=print, sound=find_sound):
    """Write every replaced and added asset into out_dir and the list file. built: bundle files already in
    out_dir from this build (build_mods.py art), changed further rather than taken from the original.
    Returns {"replaced": {file: bundle}, "new": {file: bundle}, "sounds": {local file name: new?}}."""
    from PIL import Image
    tree = tree or custom_art._config_tree()
    out_dir = Path(out_dir)
    known = _index(tree)
    music = {b["fileName"].lower() for b in tree.get("bytesData") or []}
    replace, listing, sounds, still = {}, [], [], []
    result = {"replaced": {}, "new": {}, "sounds": {}}
    for (cat, key), s in sorted(spec.items()):
        kind = CATEGORIES[cat]["kind"]
        if kind == "sound":
            entry = sound_entry(tree, s["from"] if s["new"] else key)
            if s["new"] and (key + ".acb").lower() in music:
                raise AssetError(f"{s['mod']}: the game already has music called {key}")
            raw = cri.replace_sound(sound(entry, find), Path(s["file"]).read_bytes())
            if s["new"]:
                raw = cri.rename_acb(raw, key)
            local = key + ".acb.bytes"
            (out_dir / local).write_bytes(raw)
            dat = sound_resname(key) + ".dat" if s["new"] else entry["resname"] + ".dat"
            _zip(out_dir / local, out_dir / dat)
            sounds.append({"fileName": key + ".acb", "file": local, "dat": dat, "from": entry["fileName"], "new": s["new"]})
            result["sounds"][local] = s["new"]
            log(f"  music: {key} ({'new, from ' + s['from'] if s['new'] else 'replaced'})")
            continue
        img = Image.open(s["file"]).convert("RGBA")
        imgs = _images(cat, img)
        if s.get("source"):
            tpl = s["from"] if s["new"] else key
            sizes = [picture(cat, tpl, tree, find, i).size for i in range(len(paths(cat, tpl)))]
            imgs = dict(enumerate(placed(cat, Image.open(s["source"]), s["place"], sizes)))
        if not s["new"]:
            for i, im in imgs.items():
                if i < len(paths(cat, key)) and (DABAO + paths(cat, key)[i]).lower() in known:
                    sec, e = known[(DABAO + paths(cat, key)[i]).lower()]
                    replace.setdefault(e["resname"] + ".ab", (e, {}))[1][paths(cat, key)[i]] = im
            if cat == "home_bg" and _pathkey(known, home_live2d(key)):
                still.append(_pathkey(known, home_live2d(key)))
            log(f"  picture: {CATEGORIES[cat]['label'].lower()} {key} replaced")
            continue
        if any((DABAO + p).lower() in known for p in paths(cat, key)):
            raise AssetError(f"{s['mod']}: the game already has a picture called {key}")
        src_paths = [p for p in paths(cat, s["from"]) if (DABAO + p).lower() in known]
        if not src_paths:
            raise AssetError(f"{s['mod']}: {key}: the template {s['from']} is not a picture the game has")
        sec, e = known[(DABAO + src_paths[0]).lower()]
        f = find(e["resname"] + ".ab")
        if f is None:
            raise AssetError(f"{s['mod']}: {key}: the template's bundle is not on this computer (press Set up in the launcher)")
        name = bundle_name(cat, key)
        full = [next(a["pathKey"] for a in e["assetAllRes"] if a["pathKey"].lower() == (DABAO + p).lower()) for p in src_paths]
        data = custom_art.clone_prefabs(Path(f).read_bytes(), s["from"], key, name, full, {}, {})
        data = _swap(data, {custom_art.rename(p, s["from"], key): imgs.get(i, img) for i, p in enumerate(src_paths)})
        fname = file_of(name)
        (out_dir / fname).write_bytes(data)
        listing.append({"code": key, "from": s["from"], "source": e["assetBundleName"], "bundle": name, "file": fname,
                        "section": sec, "built": True, "paths": full, "category": cat})
        result["new"][fname] = name
        if cat == "home_bg":
            _new_home_prefab(s, key, name, f, known, find, out_dir, listing, result)
        log(f"  picture: new {CATEGORIES[cat]['label'].lower()[:-1]} {key} (from {s['from']})")
    for fname, (e, images) in sorted(replace.items()):
        src = out_dir / fname if fname in set(built) and (out_dir / fname).is_file() else find(fname)
        if src is None:
            raise AssetError(f"{fname} (bundle {e['assetBundleName']}) not found: press Set up in the launcher")
        (out_dir / fname).write_bytes(_swap(Path(src).read_bytes(), images))
        result["replaced"][fname] = e["assetBundleName"]
    LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    if replace or listing or sounds:
        LIST_FILE.write_text(json.dumps({"replaced": sorted(result["replaced"]), "new": listing, "sounds": sounds,
                                         "still": still}, indent=1), "utf-8")
    else:
        LIST_FILE.unlink(missing_ok=True)
    return result


def _new_home_prefab(s, key, name, tex_file, known, find, out_dir, listing, result):
    """The copy of the template's home screen prefab, its Image on the copied picture (bundle <name>_prefab)."""
    rel = home_prefab(s["from"])
    hit = known.get((DABAO + rel).lower())
    f = find(hit[1]["resname"] + ".ab") if hit else None
    if f is None:
        raise AssetError(f"{s['mod']}: {key}: the home screen part of {s['from']} is not on this computer (press Set up in the launcher)")
    sec, e = hit
    tex_cab = next(k for k in _env(tex_file).file.files if "." not in k)
    pname = name + "_prefab"
    full = _pathkey(known, rel)
    data = custom_art.clone_prefabs(Path(f).read_bytes(), s["from"], key, pname, [full],
                                    {tex_cab.lower(): custom_art._cab(name)}, {known[(DABAO + paths("home_bg", s["from"])[0]).lower()][1]["assetBundleName"]: name})
    fname = file_of(pname)
    (out_dir / fname).write_bytes(data)
    listing.append({"code": key, "from": s["from"], "source": e["assetBundleName"], "bundle": pname, "file": fname,
                    "section": sec, "built": True, "paths": [full], "category": "home_bg"})
    result["new"][fname] = pname


def sound_resname(key):
    return PREFIX + re.sub(r"[^a-z0-9]", "", key.lower()) + "acb"


def _zip(path, dat):
    """The download form of a bytesData file, as the CDN's <resname>.dat: a zip of the one file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(path, path.name)
    Path(dat).write_bytes(buf.getvalue())


def listed():
    try:
        return json.loads(LIST_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def add_entries(tree, listing=None, out_dir=None):
    """Declare the added bundles (custom_art.add_entries) and the music files in a resource config typetree:
    a replaced one gets its new sizes, an added one a copy of its template's entry; the Live2D versions of
    replaced home backgrounds are left out. Returns the bundle entries added."""
    listing = listed() if listing is None else listing
    out_dir = Path(out_dir or LIST_FILE.parent)
    added = custom_art.add_entries(tree, listing.get("new") or [], out_dir)
    hide = {p.lower() for p in listing.get("still") or []}
    if hide:
        for sec in ("BaseAssetBundles", "AddAssetBundles"):
            for e in tree[sec]:
                e["assetAllRes"] = [a for a in e["assetAllRes"] if a["pathKey"].lower() not in hide]
        _indexes.clear()
    data = tree.setdefault("bytesData", [])
    by_name = {b["fileName"].lower(): b for b in data}
    for s in listing.get("sounds") or []:
        f = out_dir / s["file"]
        if not f.is_file():
            continue
        z = out_dir / s["dat"]
        if s["new"]:
            if s["fileName"].lower() in by_name:
                continue
            src = by_name.get(s["from"].lower())
            if src is None:
                continue
            e = json.loads(json.dumps(src))
            e["fileName"] = s["fileName"]
            e["resname"] = s["dat"][:-4]
            data.append(e)
            by_name[s["fileName"].lower()] = e
        e = by_name.get(s["fileName"].lower())
        if e is None:
            continue
        raw = f.read_bytes()
        sha = hashlib.sha1(raw).hexdigest().upper()
        e["fileHash"] = "-".join(sha[i:i + 2] for i in range(0, len(sha), 2))
        e["fileHashs"] = [e["fileHash"]]
        e["sizeOriginal"] = len(raw)
        e["sizeCompress"] = z.stat().st_size if z.is_file() else len(raw)
    return added
