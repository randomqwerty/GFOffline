"""Mod Studio: a T-Doll's own pictures (tools/custom_art.py builds them into the game's bundles).

The doll keeps its model's poses: the templates are that model's pictures, and uploads are converted
to their size. Stored as mods/<mod>/art/<code>/<slot>.png, listed in mod.json "custom_art".
"""
import base64
import io
import sys

import studio as w

sys.path.insert(0, str(w.SERVER / "tools"))
import custom_art  # noqa: E402

MAX_UPLOAD = 40 * 2**20
SLOTS = [
    {"slot": "portrait", "label": "Portrait",
     "help": "The full picture on the doll's screens. Any picture works: a plain background is removed and the figure is placed where the model's stands."},
    {"slot": "damaged", "label": "Damaged portrait",
     "help": "Shown when the doll is badly hurt. Without one, the portrait is used."},
    {"slot": "card", "label": "List picture",
     "help": "The small picture in lists: normal on the left half, damaged on the right. Made from the portrait when you don't upload one."},
    {"slot": "chibi", "label": "Battle chibi sheet",
     "help": "The sheet the battle chibi is cut from. Download the template, paint over each part where it is, and upload it. "
             "The chibi keeps the model's shape and animations, so it can't be made from an ordinary picture."},
    {"slot": "dorm", "label": "Dorm chibi sheet",
     "help": "The same for the dorm chibi. Without one, the dorm shows the model's own chibi."},
]
_templates = {}


def _templates_of(src):
    if src not in _templates:
        _templates[src] = custom_art.templates(src)
    return _templates[src]


def _entry(mod, code):
    return ((mod["meta"].get("custom_art") or {}).get(code)) if code else None


def looks(src):
    """The model's looks the pictures can replace: [{"skin": 0, "name": "Default look"}, {"skin": id, "name"}...]."""
    def build():
        text = w.world_text()
        names = {int(r["id"]): w.plain_text(w.text_of(text, r["name"])) for r in w.world_table("skin")}
        return [{"skin": 0, "name": "Default look"}] + [
            {"skin": sid, "name": names.get(sid) or f"Skin {sid}"} for sid in custom_art.skins(custom_art._config_tree(), src)]
    try:
        return w.cached(("looks", src), build)
    except Exception:
        return [{"skin": 0, "name": "Default look"}]


def info(mod_name, doll_id, model, skin=None):
    """The doll's art card: {"code", "from", "custom", "in_use" (its model is the code), "skin", "looks",
    "slots": [{slot, label, help, size, uploaded}]}. skin: the look to show when none is stored yet."""
    mod = w.load_mod(mod_name) if mod_name else None
    code = model if mod and _entry(mod, model) else custom_art.new_code(doll_id)
    entry = _entry(mod, code) if mod else None
    src = entry["from"] if entry else model
    skin = int((entry or {}).get("skin") or (skin if entry is None else 0) or 0)
    try:
        tpl = _templates_of(custom_art.look_code(src, skin)) if src else {}
    except Exception:
        tpl = {}
    have = set((entry or {}).get("images") or {})
    return {"code": code, "from": src, "template": custom_art.look_code(src, skin) if src else "",
            "custom": entry is not None, "in_use": entry is not None and code == model,
            "skin": skin, "looks": looks(src) if src else [],
            "slots": [dict(s, size=list(tpl[s["slot"]].size), uploaded=s["slot"] in have) for s in SLOTS if s["slot"] in tpl]}


def template_png(src, slot):
    tpl = _templates_of(src)
    if slot not in tpl:
        raise KeyError(f"{src} has no {slot} picture")
    return custom_art.png_bytes(tpl[slot])


def _open(data_url):
    from PIL import Image
    raw = base64.b64decode(str(data_url).split(",", 1)[-1])
    if len(raw) > MAX_UPLOAD:
        raise ValueError("That picture is too large (over 40 MB).")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.width * img.height > 8192 * 8192:
            raise ValueError("That picture is too large (over 8192 x 8192).")
        img.load()
    except (OSError, SyntaxError):
        raise ValueError("That file can't be read as a picture (use PNG, JPG, WebP, GIF or BMP).")
    return img


def upload(mod_name, body):
    """Store one uploaded picture for a doll: {"id": doll id, "model": its current model, "slot", "data": data URL}."""
    try:
        return _upload(mod_name, body)
    except ValueError as e:              # in words for the modder
        raise w.mods.ModError(str(e))


def _upload(mod_name, body):
    slot = body.get("slot")
    if slot not in custom_art.SLOTS:
        raise ValueError(f"unknown picture {slot!r}")
    with w.LOCK:
        mod = w.load_mod(mod_name)
        model = str(body.get("model") or "")
        entry = _entry(mod, model)
        code = model if entry else custom_art.new_code(body["id"])
        entry = entry or _entry(mod, code) or {"from": model, "images": {}}
        if not entry["images"] and body.get("skin") is not None:
            entry["skin"] = int(body.get("skin") or 0)
        tpl = _templates_of(custom_art.look_code(entry["from"], entry.get("skin") or 0))
        if slot not in tpl:
            raise ValueError(f"the model {entry['from']} has no {slot} picture")
        img = custom_art.fit(slot, _open(body.get("data")), tpl[slot])
        folder = w.mod_dir(mod_name) / "art" / code
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{slot}.png").write_bytes(custom_art.png_bytes(img))
        entry["images"][slot] = f"art/{code}/{slot}.png"
        mod["meta"].setdefault("custom_art", {})[code] = entry
        w.save_mod(mod_name, mod)
    return info(mod_name, body["id"], code)


def set_look(mod_name, body):
    """Which look the pictures replace ({"id", "model", "skin"}): the default look or one of the model's skins."""
    with w.LOCK:
        mod = w.load_mod(mod_name)
        code = str(body.get("model") or "")
        entry = _entry(mod, code)
        skin = int(body.get("skin") or 0)
        if entry is not None:
            if skin:
                entry["skin"] = skin
            else:
                entry.pop("skin", None)
            w.save_mod(mod_name, mod)
    return info(mod_name, body["id"], code, skin)


def remove(mod_name, body):
    """Remove one picture ({"id", "model", "slot"}), or all of them (slot "all"): the doll goes back to its model's art."""
    with w.LOCK:
        mod = w.load_mod(mod_name)
        code = str(body.get("model") or "")
        entry = _entry(mod, code)
        if entry is None:
            return info(mod_name, body["id"], code)
        folder = w.mod_dir(mod_name) / "art" / code
        for slot in list(entry["images"]) if body.get("slot") == "all" else [body.get("slot")]:
            entry["images"].pop(slot, None)
            (folder / f"{slot}.png").unlink(missing_ok=True)
        if not entry["images"]:
            mod["meta"]["custom_art"].pop(code)
            if not mod["meta"]["custom_art"]:
                mod["meta"].pop("custom_art")
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        w.save_mod(mod_name, mod)
    return info(mod_name, body["id"], code if entry["images"] else entry["from"])


def image_png(mod_name, code, slot):
    """A stored picture; slot "chibi_preview": the battle chibi drawn with the stored sheet."""
    from PIL import Image
    entry = _entry(w.load_mod(mod_name), code)
    if entry is None:
        return None
    if slot == "chibi_preview":
        if "chibi" not in entry["images"]:
            return None
        sheet = Image.open(w.mod_dir(mod_name) / entry["images"]["chibi"]).convert("RGBA")
        img = custom_art.chibi_preview(custom_art.look_code(entry["from"], entry.get("skin") or 0), sheet)
        return custom_art.png_bytes(img) if img is not None else None
    rel = entry["images"].get(slot)
    f = w.mod_dir(mod_name) / rel if rel else None
    return f.read_bytes() if f and f.is_file() else None
