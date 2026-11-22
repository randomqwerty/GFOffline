"""Frontline Protocol (the battle pass).

Seasons are stc event_battlepass rows (start_time..end_time; rotate_switch "1,<days>" repeats the
window every <days> days). The pass exp is the count of the season's pt_item_id (10606), which
the daily and weekly quest prizes pay; the level is exp / game_config battlepass_lvup_exp + 1
(PassOrderUserData$$GetCurrentPassLevel: level 1 at 0 exp), up to battlepass_lv_upperlimit, and every
further battlepass_lvup_exp after the top level is one extra bundle (gift_extra). The paid track (gift_paytounlock) needs
either unlock_itemid item.
Reply formats (from the client's handlers):
  Battlepass/index {} -> {"battlepass_with_user": [{"id", "battlepass_id", "free_bonus", "paid_bonus",
      "extra_bonus", "is_expired", "start_time"}], "battlepass_pt_item": {"<item>": count}}
      (PassOrderUserData$$SetData: claimed levels as comma lists, extra_bonus the extras claimed)
  Battlepass/getBonus {"battlepass_id", "type": 1 free / 2 paid / 3 extra, "param": level} ->
      {"bonus": {"<level>": <package>}} (RequestGetBonus)
  Battlepass/getAllBonus {"battlepass_id"} -> {"free_bonus": {...}, "paid_bonus": {...},
      "extra_bonus": {...}} (RequestGetAllBonus)
A new season's record starts with the pass exp at 0. An imported account first takes its records and pass exp from
the archived live Battlepass/index, so a season already started there goes on with its exp and claimed levels.
"""
import time
from functools import lru_cache

from . import archived, quests, squads, stc

FREE, PAID, EXTRA = 1, 2, 3
FMT = "%Y-%m-%d %H:%M:%S"


@lru_cache(maxsize=1)
def _seasons():
    return {int(r["id"]): r for r in stc.table("event_battlepass") if int(r["id"]) > 0}


def _stamp(text):
    return int(time.mktime(time.strptime(str(text), FMT)))


def _window(row, now):
    """The season's (start, end) around now, or None when it isn't running."""
    start, end = _stamp(row["start_time"]), _stamp(row["end_time"])
    mode, _, days = str(row.get("rotate_switch") or "").partition(",")
    if mode.strip() == "1" and days.strip().isdigit() and int(days) > 0 and now > end:
        step = int(days) * 86400
        k = (now - start) // step
        start, end = start + k * step, end + k * step
    return (start, end) if start <= now <= end else None


def current(now=None):
    """The running season row and its window; fixed-date seasons win over rotating ones."""
    now = int(now or time.time())
    running = [(bool(r.get("rotate_switch")), sid, r) for sid, r in _seasons().items() if _window(r, now)]
    if not running:
        return None, None
    _, sid, row = min(running)
    return row, _window(row, now)


def _cfg(name, default):
    return int(quests._config().get(name) or default)


def _levels(text):
    return {int(p.split(":")[0]): int(p.split(":")[1]) for p in str(text or "").split(",") if ":" in p}


def _import(state):
    """Once per save: the live records and pass exp (archived Battlepass/index). A record this server opened for the
    same season with nothing claimed gives way to the live one."""
    if state.get("_battlepass_imported"):
        return
    state["_battlepass_imported"] = True
    saved = archived.read(str(state["user_info"].get("user_id", "")), "Battlepass/index")
    if not isinstance(saved, dict):
        return
    recs = state.setdefault("battlepass_with_user", [])
    for live in saved.get("battlepass_with_user") or []:
        if not isinstance(live, dict) or "battlepass_id" not in live:
            continue
        mine = next((r for r in recs if str(r["battlepass_id"]) == str(live["battlepass_id"])), None)
        if mine is None:
            recs.append(dict(live))
        elif not mine.get("free_bonus") and not mine.get("paid_bonus") and str(mine.get("extra_bonus") or "0") == "0":
            mine.clear()
            mine.update(live)
    for item, n in (saved.get("battlepass_pt_item") or {}).items():
        if str(item).isdigit() and str(n).isdigit():
            have = squads._item(state, str(item))
            have["number"] = str(max(int(have.get("number") or 0), int(n)))


def _record(state, row, now):
    _import(state)
    recs = state.setdefault("battlepass_with_user", [])
    rec = next((r for r in recs if str(r["battlepass_id"]) == str(row["id"])), None)
    if rec is None:
        for old in recs:
            old["is_expired"] = "1"
        squads._item(state, str(row["pt_item_id"]))["number"] = "0"
        rec = {"id": str(len(recs) + 1), "user_id": str(state["user_info"].get("user_id", "")), "battlepass_id": str(row["id"]), "free_bonus": "", "paid_bonus": "",
               "extra_bonus": "0", "is_expired": "0", "start_time": str(now)}
        recs.append(rec)
    return rec


def _exp(state, row):
    return int(squads._item(state, str(row["pt_item_id"]))["number"])


def _paid(state, row):
    """Either unlock item opens the paid track: PassOrderUserData$$UnlockLevel is 1 for the first (basic), 2 for
    the second (advanced), 3 for both. The items come with the account file (item_with_user_info) and the
    archived Battlepass/index (battlepass_pt_item), so a pass bought live stays bought."""
    unlock = [i.strip() for i in str(row.get("unlock_itemid") or "").split(";") if i.strip().isdigit()]
    return any(int(squads._item(state, i)["number"]) > 0 for i in unlock)


def index(state, body, now=None):
    now = int(now or time.time())
    row, _ = current(now)
    if row is None:
        return {"battlepass_with_user": state.get("battlepass_with_user") or [], "battlepass_pt_item": {}}
    _record(state, row, now)
    return {"battlepass_with_user": state["battlepass_with_user"], "battlepass_pt_item": pt_items(state, now)}


def pt_items(state, now=None):
    """{item: count} of the running season's pass exp and unlock items, as the client keeps them in its bag
    (Battlepass/index, Mall/staticTables)."""
    row, _ = current(now)
    if row is None:
        return {}
    items = [str(row["pt_item_id"])] + [i.strip() for i in str(row.get("unlock_itemid") or "").split(";") if i.strip().isdigit()]
    return {i: int(squads._item(state, i)["number"]) for i in items}


def _claim(state, row, rec, kind, level):
    """Pay one level of a track (or one extra bundle); returns the package, or None."""
    step, top = _cfg("battlepass_lvup_exp", 30), _cfg("battlepass_lv_upperlimit", 45)
    level_now = _exp(state, row) // step + 1
    reached = min(top, level_now)
    if kind == EXTRA:
        if int(rec["extra_bonus"]) >= max(0, level_now - top):
            return None
        rec["extra_bonus"] = str(int(rec["extra_bonus"]) + 1)
        return quests.grant(state, quests._reward(quests.prizes().get(int(row["gift_extra"] or 0), {})))
    field, track = ("free_bonus", "gift_free") if kind == FREE else ("paid_bonus", "gift_paytounlock")
    prizes = _levels(row[track])
    claimed = {int(x) for x in str(rec[field]).split(",") if x.strip().isdigit()}
    if level not in prizes or level > reached or level in claimed or (kind == PAID and not _paid(state, row)):
        return None
    rec[field] = ",".join(str(x) for x in sorted(claimed | {level}))
    return quests.grant(state, quests._reward(quests.prizes().get(prizes[level], {})))


def get_bonus(state, body, now=None):
    body, now = body or {}, int(now or time.time())
    row, _ = current(now)
    # nothing to give (not reached, claimed, another season) still answers, with no bonus: no reply
    # drops the connection
    if row is None or str(body.get("battlepass_id")) != str(row["id"]):
        return {"bonus": {}}
    rec, kind, level = _record(state, row, now), int(body.get("type") or FREE), int(body.get("param") or 0)
    if kind == EXTRA:
        out = {}
        while (pkg := _claim(state, row, rec, EXTRA, 0)) is not None:
            out[str(int(rec["extra_bonus"]))] = pkg
        return {"bonus": out}
    pkg = _claim(state, row, rec, kind, level)
    return {"bonus": {} if pkg is None else {str(level): pkg}}


def get_all_bonus(state, body, now=None):
    body, now = body or {}, int(now or time.time())
    row, _ = current(now)
    if row is None or str(body.get("battlepass_id")) != str(row["id"]):
        return {"free_bonus": {}, "paid_bonus": {}, "extra_bonus": {}}
    rec = _record(state, row, now)
    out = {"free_bonus": {}, "paid_bonus": {}, "extra_bonus": {}}
    for kind, key, track in ((FREE, "free_bonus", "gift_free"), (PAID, "paid_bonus", "gift_paytounlock")):
        for level in sorted(_levels(row[track])):
            pkg = _claim(state, row, rec, kind, level)
            if pkg is not None:
                out[key][str(level)] = pkg
    while (pkg := _claim(state, row, rec, EXTRA, 0)) is not None:
        out["extra_bonus"][str(int(rec["extra_bonus"]))] = pkg
    return out
