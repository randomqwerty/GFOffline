"""A player's own saved account (userinfo.json), used as-is.

Drop the recorded Index/index response (the "..._user_info.json" a packet logger saves:
{"user_info": {...}, "gun_with_user_info": [...], ...}) into player/. The offline login is
then bound to that file's uid and name, and the account's save starts from the file
unchanged. Without a file, new accounts start from the anonymized template instead.

If the file is replaced later (detected by its hash), the current save is backed up to
saves/<uid>.<time>.bak.json and the new file is imported.
"""
import hashlib
import json
import logging

from . import config

log = logging.getLogger("gfserver.player")


class PlayerFileError(Exception):
    pass


def find_file():
    files = sorted(config.PLAYER_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if config.PLAYER_DIR.exists() else []
    if len(files) > 1:
        log.warning("several files in %s; using the newest, %s", config.PLAYER_DIR, files[0].name)
    return files[0] if files else None


def read(path):
    """Returns (state, uid, name, sha256). Recordings can contain a few non-UTF-8 bytes in
    other players' names; those characters are replaced rather than rejecting the file."""
    raw = path.read_bytes()
    try:
        state = json.loads(raw.decode("utf-8-sig", "replace"))
    except ValueError as e:
        raise PlayerFileError(f"{path.name} is not valid JSON: {e}") from None
    ui = state.get("user_info") if isinstance(state, dict) else None
    if not isinstance(ui, dict) or "user_id" not in ui or "name" not in ui:
        raise PlayerFileError(f"{path.name} has no user_info.user_id/name; expected a saved Index/index response")
    return state, str(ui["user_id"]), str(ui["name"]), hashlib.sha256(raw).hexdigest()
