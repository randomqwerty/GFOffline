"""The Carnival event (catchdata carnival_info / carnival_label_info / carnival_task_info).

A carnival runs start_time..end_time; its labels (label_ids) open their carnival_tasks from each
label's start_time. Index/carnival {} -> {"carnival_info": {"<task type>": progress}}
(RequestCarnival stores it; CarnivalTaskInfo$$get_count reads it by type). Rewards are mail:
a task that reaches its count sends its prize (mail type 16, carnivalTask), and the carnival's points
(pt_item_id, paid by the task prizes) send each pt_gift "points:prize" milestone (type 17,
carnivalPrize). Progress is the lifetime quest counters (quests.record) since the carnival began;
cumulative_login counts the days logged in during it. Friend tasks (FRIEND_TASKS) count as done, since there
are no friends offline; some task names are another counter's (COUNTERS); kinds the server doesn't count
(collect_gun, consume_ammo, ...) never complete.

The live account's part of the event is taken once (_sync_live): progress from its archived Index/carnival is
added to what is done here, and the tasks and point milestones it already reached there (by that progress,
the points held in its archived Index/index, or a reward mail of it in the imported mailbox) are not sent again.
"""
import time
from functools import lru_cache

from . import archived, quests, squads, stc

MAIL_TASK, MAIL_PRIZE = 16, 17
LOGIN = "cumulative_login"
FRIEND_TASKS = ("friend_praise", "upvote")
COUNTERS = {"operation_duration": "operation"}
FMT = "%Y-%m-%d %H:%M:%S"


def _stamp(text):
    return int(time.mktime(time.strptime(str(text), FMT)))


@lru_cache(maxsize=1)
def _tasks():
    return {str(r["id"]): r for r in stc.catch("carnival_task_info")}


@lru_cache(maxsize=1)
def _labels():
    return {str(r["id"]): r for r in stc.catch("carnival_label_info")}


def current(now):
    return next((r for r in stc.catch("carnival_info") if _stamp(r["start_time"]) <= now <= _stamp(r["end_time"])), None)


def _event(state, row, now):
    ev = state.get("carnival_event_info")
    fresh = not ev or ev.get("id") != str(row["id"])
    if fresh:
        ev = state["carnival_event_info"] = {"id": str(row["id"]), "base": dict(quests._state(state)["counters"]),
                                             "login_days": [], "tasks": [], "prizes": []}
    if not ev.get("live_synced"):
        _sync_live(state, row, ev, now, fresh)
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if day not in ev["login_days"]:
        ev["login_days"].append(day)
    return ev


def _live_points(state, row, fresh):
    saved = archived.read(str(state["user_info"].get("user_id", "")), "Index/index") or {}
    items = saved.get("item_with_user_info") if isinstance(saved, dict) else None
    for r in items if isinstance(items, list) else []:
        if isinstance(r, dict) and str(r.get("item_id")) == str(row["pt_item_id"]):
            return int(r.get("number") or 0)
    # no archive: a save new to this event holds the live count it was made from
    return int(squads._item(state, str(row["pt_item_id"]))["number"]) if fresh else 0


def _sync_live(state, row, ev, now, fresh):
    ev["live_synced"] = True
    saved = archived.read(str(state["user_info"].get("user_id", "")), "Index/carnival")
    live = (saved or {}).get("carnival_info") if isinstance(saved, dict) else None
    live = {k: int(v) for k, v in live.items() if str(v).lstrip("-").isdigit()} if isinstance(live, dict) else {}
    ev["live"] = live
    mailed = {(int(m["type"]), str(m.get("sub_id"))) for m in quests._mails(state) if int(m["type"]) in (MAIL_TASK, MAIL_PRIZE)}
    for task in _open_tasks(row, now):
        if live.get(task["type"], 0) >= int(task["count"]) or (MAIL_TASK, str(task["id"])) in mailed:
            if task["id"] not in ev["tasks"]:
                ev["tasks"].append(task["id"])
    points = _live_points(state, row, fresh)
    for part in str(row["pt_gift"]).split(","):
        need = part.partition(":")[0].strip()
        if need.isdigit() and (int(need) <= points or (MAIL_PRIZE, need) in mailed) and need not in ev["prizes"]:
            ev["prizes"].append(need)


def _open_tasks(row, now):
    out = []
    for lid in str(row["label_ids"]).split(","):
        label = _labels().get(lid.strip())
        if label and _stamp(label["start_time"]) <= now:
            out += [_tasks()[t] for t in str(label["carnival_tasks"]).split(",") if t in _tasks()]
    return out


def _progress(state, ev, kind, need=0):
    live = (ev.get("live") or {}).get(kind, 0)
    if kind == LOGIN:
        # the live count includes the day it was archived, most likely the first day here
        return max(len(ev["login_days"]), live + len(ev["login_days"]) - 1)
    if kind in FRIEND_TASKS:
        return need
    counter = COUNTERS.get(kind, kind)
    return live + max(0, quests._state(state)["counters"].get(counter, 0) - ev["base"].get(counter, 0))


def check(state, now=None):
    """Mail the rewards of newly finished tasks and reached point milestones."""
    now = int(now or time.time())
    row = current(now)
    if row is None:
        return None, None
    ev = _event(state, row, now)
    for task in _open_tasks(row, now):
        if task["id"] not in ev["tasks"] and _progress(state, ev, task["type"], int(task["count"])) >= int(task["count"]):
            ev["tasks"].append(task["id"])
            quests._prize_mail(state, MAIL_TASK, int(task["id"]), task["title"], task["prize_id"])
    have = int(squads._item(state, str(row["pt_item_id"]))["number"])
    for part in str(row["pt_gift"]).split(","):
        need, _, prize = part.partition(":")
        if need.strip().isdigit() and int(need) <= have and need not in ev["prizes"]:
            ev["prizes"].append(need)
            quests._prize_mail(state, MAIL_PRIZE, int(need), row["name"], prize)
    return row, ev


def index(state, body, now=None):
    now = int(now or time.time())
    row, ev = check(state, now)
    if row is None:
        return {"carnival_info": {}}
    need = {}
    for t in _open_tasks(row, now):
        need[t["type"]] = max(need.get(t["type"], 0), int(t["count"]))
    return {"carnival_info": {k: _progress(state, ev, k, need[k]) for k in sorted(need)}}
