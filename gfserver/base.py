"""Starting and cancelling base activities: logistics, auto-battles, and small settings.

Reply formats (from the client's handlers):
  Operation/startOperation      "1"   RequestStartOperation$$SuccessHandleData (builds the
                                      OperationAction locally)
  Operation/abortOperation      "1"   RequestAbortOperation$$SuccessHandleData
  Automission/startAutomission  is_quick=0: "1" (RequestStartAutoMission$$SuccessJsonHandleData
                                compares the reply text with "1"); is_quick=1: the
                                Automission/finishAutomission reply, applied at once
  Index/setDesktopPet           "1"
Finishing them is in missions.py (finish_operation, finish_automission).
"""
import random
import time

from . import missions


def start_operation(state, body, now=None):
    """{"team_id", "operation_id", "max_level", "exec_num"} -> operation_act_info entry
    (the save's format: id, operation_id, user_id, team_id, start_time, exec_num)."""
    body = body or {}
    op_id = int(body.get("operation_id") or 0)
    if op_id not in missions._operations():
        return None
    acts = [a for a in state.get("operation_act_info") or [] if int(a["operation_id"]) != op_id]
    next_id = max((int(a.get("id") or 0) for a in acts), default=0) + 1
    acts.append({"id": str(next_id), "operation_id": str(op_id), "user_id": str(state["user_info"]["user_id"]),
                 "team_id": str(body.get("team_id") or 0), "start_time": str(now or int(time.time())),
                 "exec_num": str(max(1, int(body.get("exec_num") or 1)))})
    state["operation_act_info"] = acts
    return "1"


def abort_operation(state, body, now=None):
    """Operation/abortOperation {"operation_id"} -> [{"item_id", "big_success"}], one per run already
    finished (RequestAbortOperation$$SuccessJsonHandleData adds their resources and shows the
    settlement; an empty list just cancels). The client reads JSON here: a plain "1" fails."""
    op_id = int((body or {}).get("operation_id") or 0)
    acts = state.get("operation_act_info") or []
    act = next((a for a in acts if int(a["operation_id"]) == op_id), None)
    if act is None:
        return []
    info = missions._operations().get(op_id) or {}
    runs = 0
    if int(info.get("duration") or 0):
        elapsed = max(0, int(now or time.time()) - int(act["start_time"]))
        runs = min(max(1, int(act.get("exec_num") or 1)), elapsed // int(info["duration"]))
    state["operation_act_info"] = [a for a in acts if a is not act]
    return [missions._operation_run(state, info, random, act.get("team_id")) for _ in range(runs)]


def start_automission(state, body, now=None):
    """{"team_ids": [..], "auto_mission_id", "number", "is_quick"}.
    The client deducts the cost itself (Data$$GetAutoCombatResource).
    APPROXIMATION: the save is charged the table's cost per run; the client's formula
    (team count, effects) is not reproduced."""
    body = body or {}
    mid = int(body.get("auto_mission_id") or 0)
    row = missions._auto_missions().get(mid)
    teams = [str(t) for t in body.get("team_ids") or []]
    if row is None or not teams:
        return None
    number = max(1, int(body.get("number") or 1))
    ui = state["user_info"]
    for res in ("mp", "ammo", "mre", "part"):
        missions._add(ui, res, -int(row[res]) * number)
    now = now or int(time.time())
    acts = [a for a in state.get("auto_mission_act_info") or [] if int(a["auto_mission_id"]) != mid]
    next_id = max((int(a.get("id") or 0) for a in acts), default=0) + 1
    acts.append({"id": str(next_id), "user_id": str(ui["user_id"]), "auto_mission_id": str(mid),
                 "team_ids": ",".join(teams), "end_time": str(now + int(row["duration"]) * number),
                 "number": str(number)})
    state["auto_mission_act_info"] = acts
    if int(body.get("is_quick") or 0):
        return missions.finish_automission(state, {"auto_mission_id": mid})
    return "1"


def set_desktop_pet(state, body):
    if isinstance(body, dict) and "desktop_pet" in body:
        state.setdefault("user_record", {})["desktop_pet"] = str(body["desktop_pet"])
    return "1"


def abort_automission(state, body):
    """Automission/abortAutomission {"auto_mission_id"}: the run is dropped (reply "1")."""
    mid = str((body or {}).get("auto_mission_id") or "")
    state["auto_mission_act_info"] = [a for a in state.get("auto_mission_act_info") or [] if str(a["auto_mission_id"]) != mid]
    return "1"
