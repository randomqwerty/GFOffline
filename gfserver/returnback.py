"""The Returning Commander event (Returnback).

Index/index's "return_back_event" (1 = returning player, UserReturnEventData$$GetLoginReturnData)
opens it; the server starts one when the player logs in after RETURN_DAYS or more away, for
stc return_player page 1's continuous_time days. Pages: 1 login rewards "day,activity,prize";
2 the tasks (return_task "day:task,task,...", opening on that event day) and the activity
milestones "points,prize"; 3 the fund milestones (the fund is a real-money purchase, so it is never
available offline). Task progress is the lifetime quest counters (quests.record) since the event
began; task types the server doesn't count never complete.
Reply formats (from the client's handlers):
  Returnback/userInfo {} -> {"user_id", "login_day", "active_value", "fund_available", "invite_user_id",
      "login_get_prize_list": [day], "fund_get_list": [], "task_get_prize_list": [task id],
      "active_get_prize_list": [index], "task_info": {"<day>": [{"task_id", "process"}]}, "start_time",
      "end_time"} (UserReturnEventData$$GetReturnData)
  Returnback/getReturnInfo {} -> {"first_login", "battle_num", "kill_num", "gun_num", "soul_bond_gun",
      "sangvis_num", "soul_bond_num"} (the welcome-back summary, RequestReturnPVInfo)
  Returnback/getLoginPrize {"day"} -> {"returnloingprize": <package>, "add_active", "total_active"}
  Returnback/getTaskPrize {"day", "task_id"} -> {"returnquestprize": <package>, "add_active", "total_active"}
  Returnback/getTaskActivePrize {"index": 1-based milestone} -> {"returnquestactiveprize": <package>}
APPROXIMATION: the absence that makes a returning player is server-side; RETURN_DAYS is a guess.
"""
import time
from functools import lru_cache

from . import quests, stc

RETURN_DAYS = 14
LOGIN, TASKS, FUND = 1, 2, 3


@lru_cache(maxsize=1)
def _pages():
    return {int(r["page_id"]): r for r in stc.table("return_player")}


@lru_cache(maxsize=1)
def _tasks():
    return {int(r["id"]): r for r in stc.table("return_player_task")}


def _triples(text):
    return [[int(x) for x in p.split(",")] for p in str(text or "").split(";") if p.strip()]


def _days():
    return max(1, int(_pages()[LOGIN]["continuous_time"] or 7))


def _event(state, now):
    ev = state.get("return_event_info")
    if ev and int(ev["start_time"]) <= now <= int(ev["end_time"]):
        return ev
    return None


def on_login(state, now=None):
    """Called by Index/index: start the event after a long absence; sets return_back_event."""
    now = int(now or time.time())
    ui = state["user_info"]
    last = int(state.get("_last_seen") or ui.get("last_login_time") or now)
    if _event(state, now) is None and now - last >= RETURN_DAYS * 86400:
        state["return_event_info"] = {
            "start_time": now, "end_time": now + _days() * 86400, "active_value": 0, "login": [],
            "tasks": [], "active": [], "base": dict(quests._state(state)["counters"])}
    state["_last_seen"] = now
    ui["last_login_time"] = str(now) if isinstance(ui.get("last_login_time"), str) else now
    state["return_back_event"] = 1 if _event(state, now) else 0


def _login_day(ev, now):
    return min(_days(), (now - int(ev["start_time"])) // 86400 + 1)


def _schedule():
    """{day: [task ids]} from page 2's return_task."""
    out = {}
    for part in str(_pages()[TASKS].get("return_task") or "").split(";"):
        day, _, ids = part.partition(":")
        if day.strip().isdigit():
            out[int(day)] = [int(i) for i in ids.split(",") if i.strip().isdigit()]
    return out


def _progress(state, ev, task):
    have = quests._state(state)["counters"].get(task["type"], 0) - ev["base"].get(task["type"], 0)
    return max(0, min(int(task["count"]), have))


def user_info(state, body, now=None):
    now = int(now or time.time())
    ev = _event(state, now)
    if ev is None:
        return {"user_id": state["user_info"].get("user_id", "")}
    return {"user_id": state["user_info"].get("user_id", ""), "login_day": _login_day(ev, now),
            "active_value": int(ev["active_value"]), "fund_available": False, "invite_user_id": 0,
            "login_get_prize_list": list(ev["login"]), "fund_get_list": [], "task_get_prize_list": list(ev["tasks"]),
            "active_get_prize_list": list(ev["active"]),
            "task_info": {str(d): [{"task_id": t, "process": _progress(state, ev, _tasks()[t])} for t in ids if t in _tasks()]
                          for d, ids in sorted(_schedule().items())},
            "start_time": int(ev["start_time"]), "end_time": int(ev["end_time"])}


def return_info(state, body):
    ui, counters = state["user_info"], quests._state(state)["counters"]
    guns = list(state.get("gun_with_user_info") or [])
    sangvis = state.get("sangvis_with_user_info") or []
    sangvis = list(sangvis.values()) if isinstance(sangvis, dict) else sangvis
    bonded = [g for g in guns if int(g.get("soul_bond") or 0)]
    return {"first_login": int(ui.get("reg_time") or 0), "battle_num": counters.get("mission_win", 0) + counters.get("win_normal", 0),
            "kill_num": counters.get("enemy_die", 0), "gun_num": len(guns),
            "soul_bond_gun": int(bonded[0]["gun_id"]) if bonded else 0, "sangvis_num": len(sangvis),
            "soul_bond_num": len(bonded)}


def _pay(state, prize_id):
    return quests.grant(state, quests._reward(quests.prizes().get(int(prize_id or 0), {})))


def login_prize(state, body, now=None):
    now = int(now or time.time())
    ev, day = _event(state, now), int((body or {}).get("day") or 0)
    row = next((r for r in _triples(_pages()[LOGIN]["prize_id"]) if r[0] == day), None)
    if ev is None or row is None or day > _login_day(ev, now) or day in ev["login"]:
        return None
    ev["login"].append(day)
    ev["active_value"] = int(ev["active_value"]) + row[1]
    return {"returnloingprize": _pay(state, row[2]), "add_active": row[1], "total_active": ev["active_value"]}


def task_prize(state, body, now=None):
    now = int(now or time.time())
    body = body or {}
    ev, day, tid = _event(state, now), int(body.get("day") or 0), int(body.get("task_id") or 0)
    task = _tasks().get(tid)
    if ev is None or task is None or tid in ev["tasks"] or tid not in _schedule().get(day, []) \
            or day > _login_day(ev, now) or _progress(state, ev, task) < int(task["count"]):
        return None
    ev["tasks"].append(tid)
    ev["active_value"] = int(ev["active_value"]) + int(task["activity_bonus"] or 0)
    return {"returnquestprize": _pay(state, task["prize_id"]), "add_active": int(task["activity_bonus"] or 0),
            "total_active": ev["active_value"]}


def active_prize(state, body, now=None):
    now = int(now or time.time())
    ev, index = _event(state, now), int((body or {}).get("index") or 0)
    steps = _triples(_pages()[TASKS]["prize_id"])
    if ev is None or not 1 <= index <= len(steps) or index in ev["active"] or int(ev["active_value"]) < steps[index - 1][0]:
        return None
    ev["active"].append(index)
    return {"returnquestactiveprize": _pay(state, steps[index - 1][1])}
