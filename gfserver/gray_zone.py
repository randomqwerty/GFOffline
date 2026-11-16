"""Gray Zone exploration (Daily/*): the server generates each run from the client's daily tables.

A run is one stc daily_map_spot map (map_id). Each cell becomes a hex entry
  {"spot_id", "spot_num": 1 once finished, "spot_type", "mission": "1:<day mission>,2:<night mission>",
   "event", "event_options": "<option>,<option>"}  (DailyMapHexData)
by its spot_type (DailyMapHexType): 1 Battle / 2 Fairy / 3 HOC / 6 Vehicle cells draw a mission from
daily_mission_group (that type, the run's difficulty, the cell's difficulty_group, state_type 1 day
and 2 night; Vehicle cells use difficulty 4), 7 Ex cells a vehicle mission from daily_exmission_group,
4 Chat cells a daily_event offering one of its option pairs, 5 Obstacle cells nothing; the start cell
(sub_type 1) is finished from the start. Battles are ordinary missions (Mission/startMission); a win
on a cell's mission finishes it (missions._check_win calls on_mission_win), adds its group's daily_pt
to the running daily_pass item and moves the commander there.
Reply formats (from the client's handlers):
  Daily/index {} and Daily/resetMap {"difficulty"} -> {"daily_status_with_user_info", "daily_map_with_user_info",
      "daily_pt_item": {"<item>": pt}, "daily_mail_list": [], "daily_perfect_prize": 0}
      (DailyExploreData$$RefreshAllData). Status: map_id, spot_id, prev_spot_id, total_spot_num,
      total_boss_num, total_complete_num, total_ex_num, difficulty, next_free_time,
      fight_environment_skill ("option,skill,rounds,battles,delay;..."), plan, ex_ticket.
  Daily/startPlan {"plan"} -> {}; Daily/finishPlan {} -> {"mission_drop": ""} (the commander ends on the
      plan's last cell)
  Daily/eventOption {"spot_id", "option_id"} -> the status part of the above (RefreshMapStatus): the
      option's fight environment skill joins the status and the cell is finished
  Daily/getExmissionLog {"mission_id"} -> []
daily_pass milestones ("pt" thresholds -> "gift" prizes) are mailed (mail type 27) as points cross them.
APPROXIMATION: the cell-to-pool rules above, the random choices (map, missions, event options) and the
"1:"/"2:" mission prefixes are inferred; drops, perfect-clear prizes and the paid gift2 track are not given.
"""
import random
import time
from functools import lru_cache

from . import battlepass, quests, squads, stc

BATTLE, FAIRY, SQUAD, CHAT, OBSTACLE, VEHICLE, EX = 1, 2, 3, 4, 5, 6, 7
START, BOSS = 1, 2
POOL_TYPE = {BATTLE: 1, FAIRY: 2, SQUAD: 3, VEHICLE: 6}
VEHICLE_DIFFICULTY = 4
DAY, NIGHT = 1, 2
MAIL_DAILY_EXPLORE = 27


@lru_cache(maxsize=1)
def _maps():
    out = {}
    for r in stc.table("daily_map_spot"):
        out.setdefault(int(r["map_id"]), []).append(r)
    return out


@lru_cache(maxsize=1)
def _groups():
    return stc.table("daily_mission_group")


@lru_cache(maxsize=1)
def _events():
    return {int(r["id"]): r for r in stc.table("daily_event")}


@lru_cache(maxsize=1)
def _options():
    return {int(r["id"]): r for r in stc.table("daily_event_option")}


def _ids(text):
    return [int(x) for x in str(text or "").split(",") if x.strip().isdigit()]


def _pool(kind, difficulty, band, state_type):
    rows = [g for g in _groups() if int(g["type"]) == kind and int(g["difficulty"]) == difficulty
            and int(g["state_type"]) == state_type]
    if not rows:
        return None
    return min(rows, key=lambda g: abs(int(g["difficulty_group"]) - max(1, band)))


def _option_pairs(event):
    """An event's options, in their pairs (101/102, 203/204, ...)."""
    pairs = {}
    for o in _ids(event["options"]):
        pairs.setdefault(o // 100, []).append(o)
    return list(pairs.values())


def generate(state, difficulty=1, rng=random, map_id=None):
    """A fresh run on a random map (or map_id)."""
    map_id = map_id or rng.choice(sorted(_maps()))
    hexes, start = {}, None
    ex_pool = [r for r in stc.table("daily_exmission_group")]
    for sp in sorted(_maps()[map_id], key=lambda r: int(r["spot_id"])):
        kind, sid = int(sp["spot_type"]), int(sp["spot_id"])
        h = {"spot_id": sid, "spot_num": 0, "spot_type": kind, "mission": "", "event": 0, "event_options": ""}
        if int(sp["sub_type"]) == START:
            h["spot_num"], start = 1, sid
        elif kind in POOL_TYPE:
            level = VEHICLE_DIFFICULTY if kind == VEHICLE else difficulty
            picks = []
            for st in (DAY, NIGHT):
                g = _pool(POOL_TYPE[kind], level, int(sp["difficulty_group"]), st)
                picks.append(f"{st}:{rng.choice(_ids(g['mission_group']))}" if g else "")
            h["mission"] = ",".join(p for p in picks if p)
        elif kind == EX and ex_pool:
            h["mission"] = ",".join(f"{st}:{rng.choice([r for r in ex_pool if int(r['state_type']) == st] or ex_pool)['mission_id']}"
                                    for st in (DAY, NIGHT))
        elif kind == CHAT:
            event = rng.choice(list(_events().values()))
            h["event"], h["event_options"] = int(event["id"]), ",".join(str(o) for o in rng.choice(_option_pairs(event)))
        hexes[str(sid)] = h
    start = start or int(sorted(_maps()[map_id], key=lambda r: int(r["spot_id"]))[0]["spot_id"])
    content = [h for h in hexes.values() if h["mission"] or h["event"]]
    status = {"map_id": map_id, "spot_id": start, "prev_spot_id": 0,
              "total_spot_num": len(content),
              "total_boss_num": sum(1 for sp in _maps()[map_id] if int(sp["sub_type"]) == BOSS),
              "total_complete_num": 0, "total_ex_num": 0, "difficulty": int(difficulty), "next_free_time": 0,
              "fight_environment_skill": "", "plan": "",
              "ex_ticket": int(((state.get("_daily_run") or {}).get("status") or {}).get("ex_ticket") or 0)}
    state["_daily_run"] = {"status": status, "hexes": hexes, "groups": _mission_groups(hexes)}
    return state["_daily_run"]


def _mission_groups(hexes):
    """mission id -> daily_pt of its pool, for the run's missions."""
    out = {}
    for g in _groups():
        for mid in _ids(g["mission_group"]):
            out.setdefault(str(mid), int(g["daily_pt"] or 0))
    return {m.split(":")[1]: out.get(m.split(":")[1], 0)
            for h in hexes.values() for m in str(h["mission"]).split(",") if ":" in m}


def _run(state):
    """The current run; the first one keeps the save's map and difficulty (daily_status_with_user_info
    from the live server; its cells were never saved, so they are generated afresh)."""
    if not state.get("_daily_run"):
        old = state.get("daily_status_with_user_info") or {}
        mid = int(old.get("map_id") or 0)
        run = generate(state, int(old.get("difficulty") or 1), map_id=mid if mid in _maps() else None)
        run["status"]["ex_ticket"] = int(old.get("ex_ticket") or 0)
    return state["_daily_run"]


def _pass(now):
    """The running daily_pass row (fixed or rotating dates)."""
    for row in stc.table("daily_pass"):
        if battlepass._window(row, now):
            return row
    return None


def _points(state, now):
    row = _pass(now)
    return {} if row is None else {str(row["item"]): int(squads._item(state, str(row["item"]))["number"])}


def _status_reply(state, now):
    run = _run(state)
    return {"daily_status_with_user_info": run["status"], "daily_pt_item": _points(state, now),
            "daily_mail_list": [], "daily_perfect_prize": 0}


def index(state, body, now=None):
    now = int(now or time.time())
    reply = _status_reply(state, now)
    reply["daily_map_with_user_info"] = list(_run(state)["hexes"].values())
    return reply


def reset_map(state, body, now=None, rng=random):
    difficulty = int((body or {}).get("difficulty") or _run(state)["status"].get("difficulty") or 1)
    generate(state, difficulty, rng)
    return index(state, body, now)


def start_plan(state, body):
    plan = (body or {}).get("plan")
    _run(state)["status"]["plan"] = plan if isinstance(plan, str) else ""
    return {}


def finish_plan(state, body):
    status = _run(state)["status"]
    steps = _ids(str(status.get("plan") or "").replace("|", ",").replace(";", ","))
    if steps:
        status["prev_spot_id"], status["spot_id"] = status["spot_id"], steps[-1]
    status["plan"] = ""
    return {"mission_drop": ""}


def _finish(state, h, now):
    run = _run(state)
    if h["spot_num"]:
        return
    h["spot_num"] = 1
    status = run["status"]
    status["prev_spot_id"], status["spot_id"] = status["spot_id"], h["spot_id"]
    status["total_ex_num" if h["spot_type"] == EX else "total_complete_num"] += 1


def event_option(state, body, now=None):
    now, body = int(now or time.time()), body or {}
    h = _run(state)["hexes"].get(str(body.get("spot_id")))
    opt = _options().get(int(body.get("option_id") or 0))
    if h is None or opt is None or int(opt["id"]) not in _ids(h["event_options"]):
        return None
    status = _run(state)["status"]
    entry = ",".join(str(int(opt[k])) for k in ("id", "fight_environment_skill_id", "round_duration", "battle_duration", "delay"))
    status["fight_environment_skill"] = ";".join(x for x in (status.get("fight_environment_skill"), entry) if x)
    _finish(state, h, now)
    return _status_reply(state, now)


def on_mission_win(state, mission_id, now=None):
    """A won mission that belongs to the current run finishes its cell and pays its points."""
    now, run = int(now or time.time()), state.get("_daily_run")
    if not run:
        return
    mid = str(mission_id)
    h = next((h for h in run["hexes"].values() if not h["spot_num"]
              and mid in [m.split(":")[1] for m in str(h["mission"]).split(",") if ":" in m]), None)
    if h is None:
        return
    _finish(state, h, now)
    row = _pass(now)
    if row is None:
        return
    item = squads._item(state, str(row["item"]))
    before = int(item["number"])
    item["number"] = str(before + int(run["groups"].get(mid) or 0))
    for need, prize in zip(_ids(row["pt"]), _ids(row["gift"])):
        if before < need <= int(item["number"]):
            quests._prize_mail(state, MAIL_DAILY_EXPLORE, need, "daily_pass", prize)
