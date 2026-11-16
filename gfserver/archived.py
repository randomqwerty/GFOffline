"""Replies saved from the live server, in player/archive/<uid>/ (tools/live_archive.py writes them).

  <Module>/<action>.json          a reply about the account itself
  <Module>/<action>/<id>.json     a reply about another player (Friend/visit, Friend/usercard, Vehicle/visit)

Each file is the bare reply. A missing file means nothing was archived, and callers fall back to what they did before.
"""
import json
import re

from . import config

_FUNCTION = re.compile(r"^\w+/\w+$")


def path(uid, function, key=None):
    if not _FUNCTION.match(function) or not str(uid).isdigit() or (key is not None and not str(key).isdigit()):
        return None
    base = config.PLAYER_DIR / "archive" / str(uid) / function
    return base / f"{key}.json" if key is not None else base.with_suffix(".json")


def read(uid, function, key=None):
    target = path(uid, function, key)
    if target is None:
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def write(uid, function, reply, key=None):
    target = path(uid, function, key)
    if target is None:
        raise ValueError(f"not an archive path: {function} {key}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(reply, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return target
