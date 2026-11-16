"""Theater (Theater/*): seasonal area battles, constructions and incidents.

The client picks the running season itself from stc theater_event dates (Data$$GetCurrentTheaterEventInfo);
every season in this client has ended, so a season only runs when a mod moves its dates. The server
answers for whichever theater_event_id the client asks about.

A season (theater_event) has primary theaters and a core theater (stc theater); each theater has areas
(theater_area) that open in turn as the theater's points pass their start_score/end_score, and is
occupied once its points reach theater.gauge. An exercise is one run at an area: its waves are the
area's enemy_group entries (indexes, TheaterAreaInfo$$GetEnemyTeamId), then the area's boss if it has one.
Reply formats (from the client's handlers):
  Theater/data {"theater_event_id"} -> {"theater_incident_info": [{"incident_id"}],
      "theater_construction_info": [{"construction_group_id", "lv", "init_pt", "pt", "user_pt", "theater_id"}],
      "theater_info": [{"theater_id", "battle_pt" (long), "is_open" (bool)}],
      "theater_event_log": {"theater_event_id", "battle_pt", "construction_pt", "incident_pt", "ap",
          "last_withdraw_time", "theater_cycle_withdraw_num"},
      "theater_area_type2_log": [{"theater_area_id", "best_pt"}], "theater_teams_info": [{"theater_area_id",
          "theater_teams"}]} (RequestTheaterData)
  Theater/teams {"theater_area_id", "theater_teams"} "1": the area's saved echelons
  Theater/startTheaterExercise {"theater_area_id", "theater_teams"} -> {"enemy_team": "0,1,2,..."}
  Theater/startTheaterBattle {"theater_teams", "squads", "if_fairy"} "1"
  Theater/endTheaterBattle {"if_win", ...} -> {"status", "score", "fight_success_condition": {"<cond>": 1},
      "finish_para", "next_enemy_no"} (RequestTheaterBattleFinish)
  Theater/bossBattle {} -> {"finish_para"}; Theater/abortExercise {} -> {"finish_para"}
  Theater/finishExercise {} "1" (the client adds the material itself); Theater/withdrawExercise {} "1"
  Theater/teamAgainstBossEffect {...} -> {}
  Theater/balance {} -> {"incident_pt"}; Theater/vote {"incident_id", "selection_id", "num"} "1"
  Theater/makeConstruction {"group_id", "num"} "1"; Theater/constructionCurPt {} -> [{"construction_group_id",
      "lv", "init_pt", "pt"}]
  Theater/prizeData {} -> [{"type": "2", "occupied_ids": "<theater>,..."}, {"type": "102", ...}]
  Theater/occupiedPrize {"type": 2, "occupied_id"} -> the prize package (RequestTheaterSendReward)
finish_para is "<per-battle scores, comma list>;<boss score>;<battle pt>;<material>" (TheaterBattleResult$$
SetScore); a recorded run reads "15000,15000,15000,15000,15000,15000;83067;173067;17306". The login keeps
the run in theater_exercise_info and each theater's own points in theater_with_user_info.
APPROXIMATION: a won battle scores basic_score x 10 with every success condition met (the recorded
1500 -> 15000); the boss scores 90% of the waves' total; material is a tenth of the battle pt. Theater and
area gauges are server-wide totals, so offline each own point counts OFFLINE_SCALE times. Constructions
level up as their points pass the next level's construction_pt. AP is fixed at AP.
"""
import json
import random
import time
from functools import lru_cache

from . import quests, squads, stc

OFFLINE_SCALE = 1000
AP = 5
WIN_FACTOR = 10
BOSS_SHARE = 0.9
MATERIAL_SHARE = 10
RUNNING, FINISHED = 1, 3
PRIZE_OCCUPIED, PRIZE_CORE = "2", "102"


@lru_cache(maxsize=1)
def _theaters():
    return {int(r["id"]): r for r in stc.table("theater")}


@lru_cache(maxsize=1)
def _areas():
    return {int(r["id"]): r for r in stc.table("theater_area")}


@lru_cache(maxsize=1)
def _events():
    return {int(r["id"]): r for r in stc.table("theater_event")}


@lru_cache(maxsize=1)
def _constructions():
    out = {}
    for r in stc.table("theater_construction"):
        out.setdefault(int(r["group_id"]), []).append(r)
    for rows in out.values():
        rows.sort(key=lambda r: int(r["lv"]))
    return out


def _ids(text):
    return [int(x) for x in str(text or "").replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()]


def _event_theaters(event_id):
    e = _events().get(int(event_id), {})
    return _ids(e.get("primary_theater")) + _ids(e.get("core_theater"))


def _season(state, event_id):
    seasons = state.setdefault("_theater", {})
    s = seasons.setdefault(str(event_id), {"theater_pt": {}, "construction": {}, "incident_pt": 0,
                                           "construction_pt": 0, "battle_pt": 0, "withdraws": 0,
                                           "last_withdraw": 0, "best": {}, "teams": {}, "claimed": []})
    return s


def _current_event(state):
    return int(state.get("_theater_event") or 0)


def _theater_of_area(area_id):
    return int(_areas().get(int(area_id), {}).get("theater_id") or 0)


def _event_of_theater(theater_id):
    return int(_theaters().get(int(theater_id), {}).get("theater_event_id") or 0)


def _theater_pt(season, theater_id):
    return int(season["theater_pt"].get(str(theater_id)) or 0)


def _construction_rows(state, event_id):
    season, out = _season(state, event_id), []
    for tid in _event_theaters(event_id):
        for aid in _ids(_theaters()[tid]["area"]) if tid in _theaters() else []:
            for gid in _ids(_areas().get(aid, {}).get("construction")):
                c = season["construction"].get(str(gid), {"lv": 0, "pt": 0, "user_pt": 0})
                out.append({"construction_group_id": gid, "lv": int(c["lv"]), "init_pt": 0, "pt": int(c["pt"]),
                            "user_pt": int(c["user_pt"]), "theater_id": tid})
    return out


def data(state, body):
    event_id = int((body or {}).get("theater_event_id") or 0)
    if event_id not in _events():
        return None
    state["_theater_event"] = event_id
    season = _season(state, event_id)
    return {
        "theater_incident_info": [{"incident_id": int(r["id"])} for r in stc.table("theater_incident")
                                  if int(r["theater_event_id"]) == event_id and int(r["is_active"])],
        "theater_construction_info": _construction_rows(state, event_id),
        "theater_info": [{"theater_id": tid, "battle_pt": _theater_pt(season, tid), "is_open": True}
                         for tid in _event_theaters(event_id)],
        "theater_event_log": {"theater_event_id": event_id, "battle_pt": int(season["battle_pt"]),
                              "construction_pt": int(season["construction_pt"]),
                              "incident_pt": int(season["incident_pt"]), "ap": AP,
                              "last_withdraw_time": int(season["last_withdraw"]),
                              "theater_cycle_withdraw_num": int(season["withdraws"])},
        "theater_area_type2_log": [{"theater_area_id": int(a), "best_pt": int(p)} for a, p in season["best"].items()],
        "theater_teams_info": [{"theater_area_id": int(a), "theater_teams": t} for a, t in season["teams"].items()],
    }


def _teams_text(teams):
    return teams if isinstance(teams, str) else json.dumps(teams or {}, separators=(",", ":"))


def save_teams(state, body):
    body = body or {}
    area = int(body.get("theater_area_id") or 0)
    event_id = _event_of_theater(_theater_of_area(area))
    if not event_id:
        return None
    teams = body.get("theater_teams")
    if isinstance(teams, str):
        try:
            teams = json.loads(teams)
        except ValueError:
            teams = {}
    _season(state, event_id)["teams"][str(area)] = teams or {}
    return "1"


def _exercise(state):
    return state.get("theater_exercise_info") or {}


def start_exercise(state, body, rng=random):
    body = body or {}
    area_id = int(body.get("theater_area_id") or 0)
    area = _areas().get(area_id)
    if area is None:
        return None
    save_teams(state, body)
    waves = list(range(len([g for g in str(area["enemy_group"]).split(",") if g.strip()])))
    if int(area.get("is_enemy_random") or 0):
        rng.shuffle(waves)
    order = ",".join(str(i) for i in waves)
    state["theater_exercise_info"] = {
        "user_id": str(state["user_info"].get("user_id", "")), "theater_area_id": str(area_id),
        "status": str(RUNNING), "enemy_teams": order, "theater_teams": _teams_text(body.get("theater_teams")),
        "lifes": "{}", "theater_squads_use_count": "", "theater_fairy_use_count": "0", "battle_enemy_no": "0",
        "battle_fairy": "0", "battle_squads": "", "score": "0", "finish_para": "", "scores": [],
        "last_battle_finish_time": "0"}
    return {"enemy_team": order}


def start_battle(state, body):
    ex = _exercise(state)
    if not ex or int(ex.get("status") or 0) != RUNNING:
        return None
    body = body or {}
    ex["battle_fairy"] = "1" if body.get("if_fairy") in (True, 1, "1") else "0"
    squads_used = body.get("squads") or []
    ex["battle_squads"] = ",".join(str(s) for s in squads_used) if isinstance(squads_used, list) else str(squads_used)
    return "1"


def _waves(ex):
    return len(_ids(ex.get("enemy_teams")))


def _finish_para(ex):
    area = _areas().get(int(ex.get("theater_area_id") or 0), {})
    scores = [int(s) for s in ex.get("scores") or []]
    boss = int(ex.get("boss_score") or 0)
    pt = sum(scores) + boss
    para = f"{','.join(str(s) for s in scores)};{boss};{pt};{pt // MATERIAL_SHARE}"
    ex.update(score=str(pt), finish_para=para)
    if area and str(area.get("material_item") or "0") != "0":
        ex["_material"] = [str(area["material_item"]), pt // MATERIAL_SHARE]
    return para


def end_battle(state, body, now=None):
    now, body = int(now or time.time()), body or {}
    ex = _exercise(state)
    if not ex or int(ex.get("status") or 0) != RUNNING:
        return None
    area = _areas().get(int(ex["theater_area_id"]), {})
    conds = [c for c in _ids(area.get("success_type_condition"))]
    won = body.get("if_win") in (True, 1, "1")
    if won:
        ex.setdefault("scores", []).append(int(area.get("basic_score") or 0) * WIN_FACTOR)
        ex["battle_enemy_no"] = str(int(ex["battle_enemy_no"]) + 1)
    ex["last_battle_finish_time"] = str(now)
    done = not won or (int(ex["battle_enemy_no"]) >= _waves(ex) and not str(area.get("boss") or "").strip())
    if done:
        ex["status"] = str(FINISHED)
    para = _finish_para(ex)
    return {"status": int(ex["status"]), "score": int(ex["score"]),
            "fight_success_condition": {str(c): 1 if won else 0 for c in conds},
            "finish_para": para, "next_enemy_no": int(ex["battle_enemy_no"])}


def boss_battle(state, body):
    ex = _exercise(state)
    if not ex or int(ex.get("status") or 0) != RUNNING:
        return None
    ex["boss_score"] = int(sum(int(s) for s in ex.get("scores") or []) * BOSS_SHARE)
    ex["status"] = str(FINISHED)
    return {"finish_para": _finish_para(ex)}


def abort_exercise(state, body):
    ex = _exercise(state)
    if not ex or not int(ex.get("theater_area_id") or 0):
        return None
    ex["status"] = str(FINISHED)
    return {"finish_para": _finish_para(ex)}


def team_effect(state, body):
    return {}


def _add_theater_points(state, area_id, pt, now):
    tid = _theater_of_area(area_id)
    event_id = _event_of_theater(tid)
    season = _season(state, event_id)
    season["battle_pt"] = int(season["battle_pt"]) + pt
    season["theater_pt"][str(tid)] = _theater_pt(season, tid) + pt * OFFLINE_SCALE
    if int(_areas().get(int(area_id), {}).get("type") or 0) == 2:
        season["best"][str(area_id)] = max(int(season["best"].get(str(area_id)) or 0), pt)
    own = state.setdefault("theater_with_user_info", {})
    row = own.setdefault(str(tid), {"theater_id": str(tid), "user_id": str(state["user_info"].get("user_id", "")),
                                    "battle_pt": "0", "last_exercise_finish_time": "0"})
    row["battle_pt"] = str(int(row["battle_pt"] or 0) + pt)
    row["last_exercise_finish_time"] = str(now)


def finish_exercise(state, body, now=None):
    now = int(now or time.time())
    ex = _exercise(state)
    if not ex or not int(ex.get("theater_area_id") or 0):
        return None
    if int(ex.get("status") or 0) != FINISHED:
        ex["status"] = str(FINISHED)
        _finish_para(ex)
    _add_theater_points(state, int(ex["theater_area_id"]), int(ex.get("score") or 0), now)
    item, n = ex.get("_material") or (None, 0)
    if item and n:
        row = squads._item(state, item)
        row["number"] = str(int(row["number"]) + int(n))
    state["theater_exercise_info"] = {"user_id": ex.get("user_id", ""), "theater_area_id": "0", "status": "0",
                                      "enemy_teams": "", "score": "0", "finish_para": "", "battle_enemy_no": "0"}
    return "1"


def withdraw_exercise(state, body, now=None):
    now = int(now or time.time())
    ex = _exercise(state)
    if not ex or not int(ex.get("theater_area_id") or 0):
        return None
    season = _season(state, _event_of_theater(_theater_of_area(int(ex["theater_area_id"]))))
    season["withdraws"] = int(season["withdraws"]) + 1
    season["last_withdraw"] = now
    state["theater_exercise_info"] = {"user_id": ex.get("user_id", ""), "theater_area_id": "0", "status": "0",
                                      "enemy_teams": "", "score": "0", "finish_para": "", "battle_enemy_no": "0"}
    return "1"


def balance(state, body):
    return {"incident_pt": int(_season(state, _current_event(state))["incident_pt"])}


def vote(state, body):
    body = body or {}
    sel = next((r for r in stc.table("theater_selection") if int(r["id"]) == int(body.get("selection_id") or 0)), None)
    num = max(1, int(body.get("num") or 1))
    if sel is None:
        return None
    need = int(sel["scout_material_number"]) * num
    if int(squads._item(state, str(sel["scout_material"]))["number"]) < need:
        return None
    squads._spend(state, str(sel["scout_material"]), need)
    season = _season(state, _current_event(state))
    season["incident_pt"] = int(season["incident_pt"]) + int(sel["scout_pt"]) * num
    return "1"


def make_construction(state, body):
    body = body or {}
    gid, num = int(body.get("group_id") or 0), max(1, int(body.get("num") or 1))
    rows = _constructions().get(gid)
    if not rows:
        return None
    item = str(rows[0]["material_item"])
    if int(squads._item(state, item)["number"]) < num:
        return None
    squads._spend(state, item, num)
    season = _season(state, _current_event(state) or _event_of_theater(int(_areas().get(gid, {}).get("theater_id") or 0)))
    c = season["construction"].setdefault(str(gid), {"lv": 0, "pt": 0, "user_pt": 0})
    gain = num * max(1, int(rows[0].get("material_rate") or 1))
    c["user_pt"] = int(c["user_pt"]) + gain
    c["pt"] = int(c["pt"]) + gain * OFFLINE_SCALE
    c["lv"] = max([int(r["lv"]) for r in rows if int(c["pt"]) >= int(r["construction_pt"] or 0)] or [0])
    season["construction_pt"] = int(season["construction_pt"]) + gain
    return "1"


def construction_pt(state, body):
    return [{k: r[k] for k in ("construction_group_id", "lv", "init_pt", "pt")}
            for r in _construction_rows(state, _current_event(state))]


def _occupied(state, event_id):
    season = _season(state, event_id)
    return [tid for tid in _event_theaters(event_id)
            if _theater_pt(season, tid) >= int(_theaters()[tid]["gauge"] or 0) > 0]


def prize_data(state, body):
    event_id = _current_event(state)
    claimed = set(_season(state, event_id)["claimed"])
    core = set(_ids(_events().get(event_id, {}).get("core_theater")))
    ready = [t for t in _occupied(state, event_id) if t not in claimed]
    return [{"type": PRIZE_OCCUPIED, "occupied_ids": ",".join(str(t) for t in ready if t not in core)},
            {"type": PRIZE_CORE, "occupied_ids": ",".join(str(t) for t in ready if t in core)}]


def occupied_prize(state, body):
    tid = int((body or {}).get("occupied_id") or 0)
    event_id = _event_of_theater(tid)
    season = _season(state, event_id)
    if tid not in _occupied(state, event_id) or tid in season["claimed"]:
        return None
    season["claimed"].append(tid)
    return quests.grant(state, quests._reward(quests.prizes().get(int(_theaters()[tid]["occupied_prize"] or 0), {})))
