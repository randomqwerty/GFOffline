"""The game's own text ({key: text}, e.g. "enemy_character_type-1xxxxxxx"), read from the original assettexttable
bundle and cached in build/modstudio/text.json (Mod Studio and the launcher's map share it)."""
import json
import sys

from . import config

CACHE = config.ROOT / "build" / "modstudio"


def load():
    sys.path.insert(0, str(config.ROOT / "tools"))
    import build_mods
    src = build_mods.pristine_text_bundle()
    cache = CACHE / "text.json"
    stamp = f"{src.name}:{src.stat().st_size}:{int(src.stat().st_mtime)}"
    if cache.is_file():
        data = json.loads(cache.read_text("utf-8"))
        if data.get("_stamp") == stamp:
            return data["text"]
    import UnityPy
    env = UnityPy.load(src.read_bytes())
    objs = {o.path_id: o for o in env.objects}
    text = {}
    for o in env.objects:
        if o.type.name != "AssetBundle":
            continue
        for path, ptr in o.read().m_Container:
            if not path.startswith(build_mods.TEXT_DIR):
                continue
            s = objs[ptr.asset.path_id].read().m_Script
            raw = s.encode("utf-8", "surrogateescape") if isinstance(s, str) else bytes(s)
            for line in raw.split(b"\r\n"):
                k, _, v = line.partition(b",")
                if k:
                    text[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"_stamp": stamp, "text": text}, ensure_ascii=False), "utf-8")
    return text
