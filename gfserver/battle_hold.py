"""Confirm battle results before they count (launcher switch "confirm_battles").

When a battle ends, the server keeps the result waiting and the launcher asks (GET/POST /gfoffline/battle,
gfserver/live_view.py):
  Send  the result is applied and answered as usual.
  Reject  answered "error:2" at once: the game's lost-connection box, whose OK logs in again
          (Request$$CheckWWWError -> ConnectionController.ReLogin). The result never counts: the map comes back
          as it was before it (missions.resume_info), the echelon on the enemy's node, and the fight starts again.
If the game stops waiting before a decision, the result is dropped unapplied, so a later Retry can't count it twice.
Covers Mission/battleFinish, sangvisBattleFinish (Coalition echelons), vehicleBattleFinish and vehicleRangeAtkFinish.
"""
import itertools
import json
import logging
import threading

from . import client_settings

log = logging.getLogger("gfserver.battle_hold")
FUNCTIONS = {"Mission/battleFinish": "Battle", "Mission/sangvisBattleFinish": "Coalition battle", "Mission/vehicleBattleFinish": "Vehicle battle",
             "Mission/vehicleRangeAtkFinish": "Vehicle ranged attack"}
POLL = 0.25
_ids = itertools.count(1)
_lock = threading.Lock()
_pending = [None]      # the one waiting: {"id", "function", "summary", "event", "send"}


class Held(Exception):
    """The game stopped waiting for a battle result: answer nothing."""


class Rejected(Held):
    """The player rejected a battle result: answer REJECTED."""


REJECTED = 2        # error:2, the game's lost-connection box (ReLogin)


def _units(body):
    for key in ("guns", "vehicles", "sangvises"):
        units = body.get(key)
        if isinstance(units, str):
            try:
                units = json.loads(units)
            except ValueError:
                units = []
        for u in units or []:
            if isinstance(u, dict):
                yield u


def summary(function, body):
    body = body if isinstance(body, dict) else {}
    out = {"kind": FUNCTIONS[function], "node": body.get("spot_id")}
    if "if_enemy_die" in body:
        out["won"] = bool(body.get("if_enemy_die"))
    units = list(_units(body))
    if units:
        out["units"] = len(units)
        out["down"] = sum(1 for u in units if int(u.get("life") or 0) <= 0)
    return out


def waiting():
    with _lock:
        return {k: v for k, v in (_pending[0] or {}).items() if k in ("id", "function", "summary")}


def decide(pid, send):
    with _lock:
        entry = _pending[0]
        if not entry or entry["id"] != int(pid or 0):
            return False
        entry["send"] = bool(send)
        entry["event"].set()
        return True


def check(function, body, alive=lambda: True):
    """Returns when the result may be applied; raises Rejected or Held otherwise. alive() is False once the game hung up."""
    if function not in FUNCTIONS:
        return
    try:
        on = client_settings.load()["confirm_battles"]
    except client_settings.SettingsError:
        on = False
    if not on:
        return
    entry = {"id": next(_ids), "function": function, "summary": summary(function, body), "event": threading.Event(), "send": False}
    with _lock:
        if _pending[0]:
            _pending[0]["replaced"] = True   # a newer copy (the game's Retry) replaces the one still waiting
            _pending[0]["event"].set()
        _pending[0] = entry
    try:
        while not entry["event"].wait(POLL):
            if not alive():
                log.info("%s: the game stopped waiting; result dropped", function)
                raise Held(function)
        if entry.get("replaced"):
            raise Held(function)
        if not entry["send"]:
            log.info("%s rejected by the player", function)
            raise Rejected(function)
    finally:
        with _lock:
            if _pending[0] is entry:
                _pending[0] = None
