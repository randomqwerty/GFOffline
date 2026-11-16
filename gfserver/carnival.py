"""The Carnival event (catchdata carnival_info / carnival_label_info / carnival_task_info).

A carnival runs start_time..end_time; its labels (label_ids) open their carnival_tasks from each
label's start_time. Index/carnival {} -> {"carnival_info": {"<task type>": progress}}
(RequestCarnival stores it; CarnivalTaskInfo$$get_count reads it by type). Rewards are mail:
a task that reaches its count sends its prize (mail type 16, carnivalTask), and the carnival's points
(pt_item_id, paid by the task prizes) send each pt_gift "points:prize" milestone (type 17,
carnivalPrize). Progress is the lifetime quest counters (quests.record) since the carnival began;
cumulative_login counts the days logged in during it. Task types the server doesn't count
(friend_praise, collect_gun, operation_duration, ...) never complete.
"""
import time
from functools import lru_cache

from . import quests, squads, stc

MAIL_TASK, MAIL_PRIZE = 16, 17
LOGIN = "cumulative_login"
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
    if not ev or ev.get("id") != str(row["id"]):
        ev = state["carnival_event_info"] = {"id": str(row["id"]), "base": dict(quests._state(state)["counters"]),
                                             "login_days": [], "tasks": [], "prizes": []}
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if day not in ev["login_days"]:
        ev["login_days"].append(day)
    return ev


def _open_tasks(row, now):
    out = []
    for lid in str(row["label_ids"]).split(","):
        label = _labels().get(lid.strip())
        if label and _stamp(label["start_time"]) <= now:
            out += [_tasks()[t] for t in str(label["carnival_tasks"]).split(",") if t in _tasks()]
    return out


def _progress(state, ev, kind):
    if kind == LOGIN:
        return len(ev["login_days"])
    return max(0, quests._state(state)["counters"].get(kind, 0) - ev["base"].get(kind, 0))


def check(state, now=None):
    """Mail the rewards of newly finished tasks and reached point milestones."""
    now = int(now or time.time())
    row = current(now)
    if row is None:
        return None, None
    ev = _event(state, row, now)
    for task in _open_tasks(row, now):
        if task["id"] not in ev["tasks"] and _progress(state, ev, task["type"]) >= int(task["count"]):
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
    kinds = {t["type"] for t in _open_tasks(row, now)}
    return {"carnival_info": {k: _progress(state, ev, k) for k in sorted(kinds)}}
