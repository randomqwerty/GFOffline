"""What live maps did that no table holds, from recorded runs (tools/import_maps.py, tools/import_spawns.py).

Two files, the same layout, added together: data/live_spawns.json ships with the server, and
config.MAP_RECORDINGS (map_recordings.json) is the player's own, read again whenever it changes.
  {"logs": [sha256 of each imported log], "missions": {"<mission id>": entry}}
An entry's spawns (import_spawns.py): turns, enemy_turns, grow, start, allies, other. Its markers:
  marker_runs   one per recorded run: {"reached": {phase: last turn}, "markers": [[spot, special spot,
                skill, turn, phase, copies]]}, each hidden marker (a special spot of source 99910, the
                server's own) the first time a PHASES reply showed it. Markers that first showed in
                the reply to something the player did (a battle, a building's skill) aren't kept:
                the server makes those itself.
"""
import json
import os
import re

from . import config

PHASES = ("startMission", "startTurn", "startEnemyTurn", "startOtherSideTurn")
MARKER_SOURCE = 99910
_FILES = {}


def _read(path):
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    got = _FILES.get(path)
    if got is None or got[0] != mtime:
        try:
            data = json.loads(path.read_text("utf-8")).get("missions") or {}
        except (OSError, ValueError, AttributeError):
            data = {}
        got = _FILES[path] = (mtime, data if isinstance(data, dict) else {})
    return got[1]


def _own():
    """The player's recordings; tests (GF_NO_MODS) only read one they name with GF_MAP_RECORDINGS."""
    if os.environ.get("GF_NO_MODS") and "GF_MAP_RECORDINGS" not in os.environ:
        return {}
    return _read(config.MAP_RECORDINGS)


def mission(shipped, mid):
    """The map's entry from both files, counts added."""
    out = {}
    for data in (_read(shipped), _own()):
        add(out, data.get(str(mid)) or {})
    return out


def add(into, entry):
    """Add a stored entry's counts and runs to another."""
    for key in ("turns", "enemy_turns"):
        for turn, n in (entry.get(key) or {}).items():
            into.setdefault(key, {})[turn] = into.get(key, {}).get(turn, 0) + int(n)
    for key, width in (("grow", 3), ("start", 2), ("allies", 2)):
        counts = {tuple(x[:width]): x[width] for x in into.get(key, [])}
        for x in entry.get(key) or []:
            counts[tuple(x[:width])] = counts.get(tuple(x[:width]), 0) + x[width]
        if counts or key in into:
            into[key] = [[*k, n] for k, n in sorted(counts.items())]
    if entry.get("other"):
        into["other"] = into.get("other", 0) + int(entry["other"])
    if entry.get("marker_runs"):
        into.setdefault("marker_runs", []).extend(entry["marker_runs"])
    return into


def _path(entry):
    return re.sub(r"^.*?(?=/[A-Z][A-Za-z]*/[A-Za-z]+$)", "", str(entry.get("URL") or "").split("?")[0])


def _on_spot(reply):
    fs = reply.get("fairy_skill_on_spot")
    if isinstance(fs, str):
        try:
            fs = json.loads(fs)
        except ValueError:
            return {}
    return fs if isinstance(fs, dict) else {}


def collect_markers(entries, mission_id):
    """{mission: [run]} from one log's entries (packet log order). mission_id(request) -> id or 0."""
    out, run = {}, None
    for e in entries:
        path, reply = _path(e), e.get("Response")
        if not path.startswith("/Mission/") or not isinstance(reply, dict):
            continue
        name = path.rsplit("/", 1)[-1]
        if name == "startMission":
            mid = mission_id(e.get("Request"))
            run = None
            if mid:
                run = {"turn": 1, "seen": set(), "copies": {}, "reached": {"startMission": 1}}
                out.setdefault(mid, []).append(run)
        if run is None:
            continue
        if name == "startTurn":
            run["turn"] += 1
        if name in PHASES:
            run["reached"][name] = run["turn"]
        for spot, insts in _on_spot(reply).items():
            for iid, v in (insts or {}).items() if isinstance(insts, dict) else ():
                if iid in run["seen"] or not isinstance(v, dict):
                    continue
                run["seen"].add(iid)
                if int(v.get("source_type") or 0) != MARKER_SOURCE or name not in PHASES:
                    continue
                key = (int(spot), int(v.get("special_spot_config_id") or 0),
                       int(v.get("mission_skill_config_id") or 0), run["turn"], name)
                if key[1]:
                    run["copies"][key] = run["copies"].get(key, 0) + 1
        if name == "abortMission" or reply.get("mission_win_result") or reply.get("mission_lose_result"):
            run = None
    return {mid: [{"reached": r["reached"], "markers": [[*k, n] for k, n in sorted(r["copies"].items())]}
                  for r in runs] for mid, runs in out.items()}
