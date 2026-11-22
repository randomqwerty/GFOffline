"""Logistics, auto-battles and campaign missions.

Reply formats (from the client's handlers):
  Operation/finishOperation     [{"item_id": "<id-num,...>" | "", "big_success": bool}, ...]  one per
                                completed run   OperationAction$$RequestFinishOperationHandle
  Automission/finishAutomission {"success_number", "add_user_exp", "add_gun_exp": [{"gun_with_user_id",
                                "gun_exp", "gun_life"}], optional "free_exp", "add_gun", "add_equip",
                                "add_prize", "add_fairy_exp"}
                                                AutoMissionAction$$RequestFinishAutoMissionHandler
  Mission/startMission          {"spot_act_info": [spot...]} (+ "night_spots" [{spot_id, belong}]
                                for night missions, where enemies out of sight are left out,
                                optional building_info/squad_info/vehicle_info/enemy_instance_info/
                                ally_instance_info/daily_info)
                                                DeploymentController$$RequestStartMissionHandle
                                spot: SpotAction$$UpdateInfo (team_id, sangvis_team_id,
                                vehicle_with_user_id, enemy_team_id, if_random, belong, supply_count,
                                fix_count, hostage_*, enemy_instance_id, ally/squad_instance_ids, seed)
  Mission/abortMission          {"mission_lose_result": {...}} (must be filled, see abort_mission)
                                                DeploymentController$$RequestAbortMissionHandle
  Mission/teamMove              {"ap"} required (sets MissionAction.ap); optional change_belong
                                {"<spot_id>": belong}, mission_win_result, type5_score (int)
                                                DeploymentController$$RequestMoveTeamHandle
  Mission/battleFinish          {"seed", "battle_rank", "gun_exp": [{"gun_with_user_id", "exp"}]},
                                optional user_exp, favor_change {"<gun_with_user_id>": n},
                                change_belong, mission_win_result/mission_lose_result, gun_life
                                    BattleController$$RequestBattleFinishHandle (seed),
                                    BattleResultController$$Init (the rest)
  Mission/endTurn               optional change_belong1 {"<spot_id>": belong} (our captures),
                                mission_win_result   DeploymentController$$RequestEndAllFriendTurnHandle
  Mission/startEnemyTurn        optional enemy_move: [{"enemy_instance_id": long,
                                "squad_instance_id": long, "from_spot_id", "to_spot_id",
                                "hp_percent": float, "hostage_hp", "hostage_id"}] (all required
                                per entry; DeploymentController$$AnalysicsEnemyAllyMove), plus
                                ally_move/grow_enemy/ally_battle/change_belong2 (unused here)
                                                DeploymentController$$RequestStartEnemyTurnHandle
                                Night maps: night_enemy moves instead of enemy_move (see the
                                night section at the end)
  Mission/enemyTurnMove         same keys; only requested on night maps or multi-step moves
                                (DeploymentController$$CheckNext), so day maps get every
                                enemy move from startEnemyTurn
  Mission/endEnemyTurn          {"type5_score": int} required, optional change_belong
  Mission/startTurn             {"type5_score": int} required, optional "ap"
  startMission body also has squad_spots [{spot_id, squad_with_user_id, battleskill_switch}] and
  sangvis_spots [{spot_id, sangvis_team_id}] (DeploymentController$$RequestStartMission)
  Mission/withdrawTeam, supplyTeam: every key optional (type5_score, mission_lose_result, ...)
  Mission/reinforceTeam         {"ap"} required    DeploymentTeamInfoController$$RequestReinforceHandle
  Mission/sangvisMove           a Coalition echelon moves (position only)
  Mission/fairySkillPerform     strategy fairy skills (special spots, buffs, traps; Illumination
                                lights night maps)
  night_enemy                   on night maps, in startMission/teamMove/sangvisMove/endEnemyTurn/
                                startTurn/reinforceTeam/fairySkillPerform/startEnemyTurn replies
  mission_win_result            (in any reply above; GameData$$AnalysisMissionResult)
                                {"rank": str, "medal4": bool, "mission_info": {"turn": str,
                                "gundie_num": int, "mysquad_die_num": int, "sangvisdie_num": int,
                                "enemydie_num": str}}, optional user_exp (str), item,
                                reward_gun/reward_equip/reward_prize, win_type_ids
  mission_lose_result           {"turn": str, "gundie_num", "mysquad_die_num", "sangvisdie_num",
                                "enemydie_num": str} directly inside; {} just closes the map
Value types matter for strings only: LitJson's get_Int/get_Double here also accept strings,
but a value read as a string (op_Explicit string) must be a JSON string.

Request bodies: teamMove {person_type, person_id, from_spot_id, to_spot_id, move_type}
(RequestTeamMove$$.ctor); battleFinish {spot_id, if_enemy_die, boss_hp, mvp, guns: [{id,
life}], ...} (BattleController$$CreateBattleResultJS); withdrawTeam {spot_id}; reinforceTeam
{spot_id, team_id}; the turn calls send no body.

Turn flow (DeploymentController$$CheckNext): endTurn -> startEnemyTurn -> [battleFinish for
each enemy attack] -> endEnemyTurn -> startTurn.

The mission in progress is kept in the save under "_mission" (not part of the Index/index
reply; handlers.index_index strips "_" keys): the spots as sent to the client, where each
echelon stands (team_pos), patrol directions, pending battles, turn, AP and counters.

Rules:
- A spot changes hands only at the end of a side's turn: the spots its units stand on, then
  every empty non-HQ spot whose neighbours all belong to that side (surround capture).
- Each enemy takes one step per turn according to its AI (see enemy_behaviour); stepping
  onto an echelon is an attack that the client fights.
- Victory follows mission.type (see win_groups): 1/2 every win spot is ours or has an echelon
  on it (win_spot_id, else "occupy" win conditions (mission_win_type_config type 1101), else
  every enemy HQ), so stepping onto the enemy HQ wins at once; 3 no enemy left, or the win spots
  as for 1/2 (most story maps use 3 and are won at the enemy HQ); 4 the boss team
  (boss_team_id) destroyed; 6 a supply line (Command Post to supply point, spot type 6, through
  spots we hold) stands for expect_defend_line_turn turns; 7 expect_hostage_num hostages
  (spot.hostage_info "<gun>,<hp>") carried to a deploy point (Mission/saveHostage); 11 survive
  win_turn turns. Lost when no echelon is left on the map,
  every HQ we started with is taken, or turn_limit is passed.
- Medals: bronze for a clear; gold for rank S, which needs the client's S-rank conditions
  (echelons lost or withdrawn <= expect_gun_die_num, within expect_turn rounds, every hostage or
  expect_enemy_die_num kills); silver (medal4) for medal_type_silver's conditions, or rank S on a
  map without them. APPROXIMATION: below S, one rank lower per missed condition.
- Mods can add enemy spawn tables per map (mods map_rules, see the spawn section): enemies
  appear at mission start or at the start of enemy turns (startEnemyTurn grow_enemy,
  DeploymentController$$AnalysicsGrowEnemy).
- Night maps hide enemies out of the player's sight (see the night section at the end).
- Battle damage is saved: battleFinish/sangvisBattleFinish write each unit's life (workshop.set_life),
  so damaged units stay damaged until repaired. Coalition echelons (sangvisMove) count as echelons
  for enemy attacks and captures, and fight through Mission/sangvisBattleFinish.
- Buildings and allied/third-party forces are placed from the map data (see the sections at the
  end): buildings can be attacked down and captured, hostile allies can be fought.
- Mission skills (fairies, Coalition, vehicles) place special spots and buffs; traps hurt enemies
  that step on them; vehicles can bombard (see the skill effects and vehicle sections).
SIMPLIFIED: battles resolve with the client's own result (if_enemy_die), random nodes roll
guessed odds (RANDOM_EVENTS), and forces fight each other by strength (_ally_fight); the client fights an enemy that
attacks a force the player moves. Skill trigger conditions (trigger_id) are evaluated for the
skills the server casts (buildings, subsidiaries); the client checks its own casts. The maps' own reinforcements were the live server's: enemies spawn from mod spawn
tables, recorded live runs (data/live_spawns.json), else on enemy-held heliports and spawn-point
special spots (_fallback_spawn_rules).
"""
import json
import math
import os
import random
import re
import time
from functools import lru_cache

from . import config, friends, quests, recordings, squads, stc, workshop
from . import factory
from .factory import _add


# --- logistics -------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _operations():
    return {int(r["id"]): r for r in stc.catch("operation_info")}


# Each run rolls a great success (big_success) at (the echelon's average doll level * 0.45 + 15)%,
# and during a great-success rate-up (GREAT_SUCCESS_RATEUP, off: no live events here) another
# (average * 0.15 + 15)%. The client pays the resources itself as floor(base * (100 +
# the outfit's logistics_reward_up) / 100), then floor(x * 1.5) on a great success
# (OperationAction$$RequestFinishOperationHandle, Data$$GetLogisticsResourceAfterFactor); the save
# gets the same. The drop is one even pick from operation_info.item_pool, 0 being nothing; a great
# success always drops, an even pick among its items. item_id is "<item>-<number>".
GREAT_SUCCESS_RES, GREAT_SUCCESS_RATEUP = 1.5, False


def great_success_chance(state, team):
    """The chance (0..1) of a great success for a logistics echelon."""
    levels = [int(g.get("gun_level") or 1) for g in _team_guns(state, team)]
    avg = sum(levels) / len(levels) if levels else 0
    pct = avg * 0.45 + 15 + ((avg * 0.15 + 15) if GREAT_SUCCESS_RATEUP else 0)
    return min(1.0, pct / 100)


def _operation_run(state, info, rng, team=None):
    great = rng.random() < great_success_chance(state, team)
    up = outfit_bonus(state, "logistics_reward_up")
    for res in ("mp", "ammo", "mre", "part"):
        got = math.floor(int(info[res]) * (100 + up) / 100)
        _add(state["user_info"], res, math.floor(got * GREAT_SUCCESS_RES) if great else got)
    pool = _ids(info.get("item_pool"))
    pool = [i for i in pool if i] if great else pool
    item = rng.choice(pool) if pool else 0
    if item:
        row = squads._item(state, item)
        row["number"] = str(int(row["number"]) + 1)
    return {"item_id": f"{item}-1" if item else "", "big_success": great}


def finish_operation(state, body, now=None, rng=random):
    """Collect a logistics op: one result per run it has done, up to exec_num (the runs it was sent
    out for). The op always ends here: the client drops it from its own list after every finish
    (OperationAction$$RequestFinishOperationHandle) and sends it out again itself with
    Operation/startOperation (OperationChecker$$RequestNextOperationRestart, the settlement's
    "again" buttons). An op that isn't running, such as one finished twice, gets an empty list,
    which pays nothing, as abortOperation does."""
    now = now or int(time.time())
    op_id = int((body or {}).get("operation_id") or 0)
    acts = state.get("operation_act_info") or []
    act = next((a for a in acts if int(a["operation_id"]) == op_id), None)
    info = _operations().get(op_id)
    if act is None or info is None:
        return []
    dur = int(info["duration"])
    runs = max(1, min(max(1, int(act.get("exec_num") or 1)), (now - int(act["start_time"])) // dur))
    state["operation_act_info"] = [a for a in acts if a is not act]
    return [_operation_run(state, info, rng, act.get("team_id")) for _ in range(runs)]


# --- auto-battles ----------------------------------------------------------------------

@lru_cache(maxsize=1)
def _level_exp():
    """Cumulative exp needed to reach each level (gun_exp_info gives exp per level)."""
    total, out = 0, {1: 0}
    for r in sorted(stc.catch("gun_exp_info"), key=lambda r: int(r["lv"])):
        total += int(r["exp"])
        out[int(r["lv"]) + 1] = total
    return out


def add_gun_exp(gun, exp):
    """Add exp to a doll in the save, levelling it up to its cap (100, or 120 once modded).
    Returns the exp past the cap, which goes to the free exp pool (add_free_exp)."""
    cap = 120 if int(gun.get("if_modification") or 0) > 0 else 100
    total = int(gun["gun_exp"]) + exp
    table = _level_exp()
    level = int(gun["gun_level"])
    while level < cap and table.get(level + 1, math.inf) <= total:
        level += 1
    over = 0
    if level >= cap:
        over = max(0, min(exp, total - table.get(cap, total)))
        total = min(total, table.get(cap, total))
    before = int(gun["gun_level"])
    gun["gun_exp"], gun["gun_level"] = str(total), str(level)
    if level > before:
        _level_up_life(gun, before, level)
    return over


def _level_up_life(gun, old, new):
    """A level-up raises the doll's full life; its current life goes up by as much, so it isn't
    left needing a repair (player report: dolls levelled up in auto-battles came back damaged)."""
    gid = int(gun.get("gun_id") or 0)
    if gid not in workshop.guns():
        return
    links = int(gun.get("number") or 1)
    gain = (workshop.gun_life(gid, min(100, new), links) - workshop.gun_life(gid, min(100, old), links))
    if gain > 0 and "life" in gun:
        gun["life"] = str(int(gun.get("life") or 0) + gain)


FREE_EXP_ITEM, FREE_EXP_CAP = "507", "204"      # the pool, and the facility whose parameter_1 caps it


def add_free_exp(state, exp):
    """Exp capped dolls could not take fills the free exp pool (item 507, used by the Data Room's
    combat reports) up to establish 204's parameter_1. Returns what was added (the battle reply's
    free_exp, which the client adds itself: GameData$$AnalysisMissionResult)."""
    if exp <= 0:
        return 0
    row = squads._item(state, FREE_EXP_ITEM)
    top = int(squads._establish(state, FREE_EXP_CAP).get("parameter_1") or 0)
    add = max(0, min(exp, top - int(row["number"])))
    row["number"] = str(int(row["number"]) + add)
    return add


@lru_cache(maxsize=1)
def _auto_missions():
    return {int(r["mission_id"]): r for r in stc.table("auto_mission")}


def _auto_drops(state, row, runs, rng=random):
    """An auto-battle's drops: per run, get_gun_num dolls (one from gun_1_pool, the rest from
    gun_n_pool) and get_equip_num equipment (equip_1_pool / equip_n_pool), each an even pick
    where 0 is nothing. -> (add_gun [{gun_with_user_id, gun_id}], add_equip [equip records])."""
    equips = {int(r["id"]) for r in stc.table("equip")}
    guns, eqs = [], []
    for _ in range(runs):
        for kind, num, first, rest in (("gun", "get_gun_num", "gun_1_pool", "gun_n_pool"),
                                       ("equip", "get_equip_num", "equip_1_pool", "equip_n_pool")):
            for i in range(int(row.get(num) or 0)):
                text = row.get(first if i == 0 else rest)
                pool = _gun_pool(text) if kind == "gun" else tuple(e for e in _ids(text) if e == 0 or e in equips)
                pick = rng.choice(pool) if pool else 0
                if pick and kind == "gun":
                    guns.append(_give_gun(state, pick))
                elif pick:
                    eqs.append(dict(workshop.new_equip(state, pick, rng)))
    return guns, eqs


def finish_automission(state, body, rng=random):
    mid = int((body or {}).get("auto_mission_id") or 0)
    acts = state.get("auto_mission_act_info") or []
    act = next((a for a in acts if int(a["auto_mission_id"]) == mid), None)
    if act is None:
        return None
    state["auto_mission_act_info"] = [a for a in acts if a is not act]
    runs = int(act.get("number") or 1)
    teams = {t for t in str(act.get("team_ids") or "").split(",") if t}
    row = _auto_missions().get(mid, {})
    # Recorded (auto_mission 141, experience 408, 3 runs): per run a doll gets experience * 5 * its
    # dummy-link multiplier, * 1.2 as leader, with no level penalty (6120 at 5 links, 5100 at 4,
    # 6120 for a 4-link leader); the fairy the average of its echelon's dolls; the commander
    # experience * runs * the outfit's commander bonus (1346); free exp a fifth of all doll exp.
    # gun_exp / fairy_exp in the reply are the new totals.
    base = int(row.get("experience") or 0)
    gained, fairy_exp, over, total = [], [], 0, 0
    per_team = {}
    for g in state.get("gun_with_user_info", []):
        if str(g.get("team_id")) not in teams:
            continue
        exp = base * 5 * (1 + 0.5 * (max(1, int(g.get("number") or 1)) - 1))
        exp = int(exp * (LEADER_EXP if str(g.get("location")) == "1" else 1)) * runs
        total += exp
        per_team.setdefault(str(g["team_id"]), []).append(exp)
        over += add_gun_exp(g, exp)
        gained.append({"gun_with_user_id": str(g["id"]), "gun_exp": str(g["gun_exp"]), "gun_life": str(g["life"])})
    fairies = state.get("fairy_with_user_info") or []
    for f in (fairies.values() if isinstance(fairies, dict) else fairies):
        team_exp = per_team.get(str(f.get("team_id")))
        if team_exp:
            f["fairy_exp"] = str(int(f.get("fairy_exp") or 0) + sum(team_exp) // len(team_exp))
            f["fairy_lv"] = str(max(1, workshop._level_for(int(f["fairy_exp"]), stc.catch("fairy_exp_info"), "id", 100)))
            fairy_exp.append({"fairy_with_user_id": str(f["id"]), "fairy_exp": f["fairy_exp"]})
    user_exp = int(base * runs * (1 + outfit_bonus(state, "battle_commander_exp_up") / 100))
    _add(state["user_info"], "experience", user_exp)
    add_gun, add_equip = _auto_drops(state, row, runs, rng)
    # read by AutoMissionAction$$RequestFinishAutoMissionHandler: add_gun [{gun_with_user_id,
    # gun_id}], add_equip [equip records, as Equip(JsonData) reads them]
    return {"success_number": runs, "add_user_exp": str(user_exp), "add_gun_exp": gained, "add_fairy_exp": fairy_exp,
            "free_exp": add_free_exp(state, total // 5 + over), "add_gun": add_gun, "add_equip": add_equip}


# --- campaign missions -----------------------------------------------------------------

@lru_cache(maxsize=1)
def _spots_by_mission():
    out = {}
    for r in stc.table("spot"):
        out.setdefault(int(r["mission_id"]), []).append(r)
    return out


@lru_cache(maxsize=1)
def _missions():
    return {int(r["id"]): r for r in stc.table("mission")}


_COPY_CACHE = {"of": None, "maps": {}}


def _copy_maps():
    """mods.copies() with int keys: {map: (source map, {source node: node})}."""
    from . import mods
    got = mods.copies()
    if got is not _COPY_CACHE["of"]:
        _COPY_CACHE.update(of=got, maps={int(k): (int(v["from"]), {int(a): int(b) for a, b in v["spots"].items()})
                                         for k, v in got.items()})
    return _COPY_CACHE["maps"]


def _copied_spots(mid):
    """{source node: this map's node} for a mod's copy of a game map (mods.copy_maps), else {}."""
    got = _copy_maps().get(int(mid)) if mid is not None else None
    return got[1] if got else {}


def _source(mid):
    """The game map a mod map copies, or None."""
    got = _copy_maps().get(int(mid)) if mid is not None else None
    return got[0] if got else None


def _for_map(table, mid, default=None):
    """A per-map rule of this file for the map, or for the game map a mod map copies (a set of
    nodes on the copy's nodes)."""
    if int(mid) in table:
        return table[int(mid)]
    src = _source(mid)
    if src is None or src not in table:
        return default
    got = table[src]
    if isinstance(got, (set, frozenset)):
        return frozenset(_copied_spots(mid).get(x, x) for x in got)
    return got


def local_spots(mid, text):
    """Text naming a copied map's source nodes (team ai_content routes) with this map's nodes."""
    remap = _copied_spots(mid)
    if not remap or text is None:
        return text
    return re.sub(r"\d+", lambda x: str(remap.get(int(x.group(0)), x.group(0))), str(text))


def _local_rules(mid, rules):
    """A copied map's source spawn rules on its own nodes (rule keys spot / spots / after_destroyed)."""
    remap = _copied_spots(mid)
    out = []
    for r in rules or []:
        r = dict(r)
        for k in ("spot", "after_destroyed"):
            if isinstance(r.get(k), int):
                r[k] = remap.get(r[k], r[k])
        if isinstance(r.get("spots"), list):
            r["spots"] = [remap.get(x, x) if isinstance(x, int) else x for x in r["spots"]]
        out.append(r)
    return out


def _local_recording(mid, entry):
    """A copied map's source recordings on its own nodes (recordings.py layout)."""
    remap = _copied_spots(mid)
    node = lambda x: remap.get(int(x), x) if str(x).isdigit() else x
    out = dict(entry)
    for key in ("grow", "start", "allies"):
        if key in entry:
            out[key] = [[node(x[0]), *x[1:]] for x in entry[key]]
    if "marker_runs" in entry:
        out["marker_runs"] = [dict(run, markers=[[node(mk[0]), *mk[1:]] for mk in run.get("markers", [])])
                              for run in entry["marker_runs"]]
    return out


@lru_cache(maxsize=1)
def _clear_prizes():
    """mission id -> prize id of its first-clear reward (catchdata mission_event_prize_info, which the
    mission screen also shows)."""
    return {int(r["mission_id"]): int(r["prize_id"]) for r in stc.catch("mission_event_prize_info")
            if str(r.get("prize_id") or "0").isdigit() and int(r.get("prize_id") or 0)}


def _first_clear_reward(state, mid):
    """Grant a map's clear prize. The win reply lists dolls in reward_gun ({gun_with_user_id, gun_id})
    and the rest as reward_prize [{prize_id}], which the client turns into the prize row's package
    (GameData$$AnalysisMissionResultReward); a doll is left out of reward_prize so it shows once."""
    prize = quests.prizes().get(_clear_prizes().get(mid, 0))
    if not prize:
        return {}
    pkg = quests.grant(state, quests._reward(prize))
    out = {}
    if pkg.get("guns"):
        out["reward_gun"] = pkg["guns"]
    if any(k not in ("gun_id", "guns") for k in pkg):
        out["reward_prize"] = [{"prize_id": int(prize["id"])}]
    return out


def _spot(row, rng):
    return {
        "spot_id": str(row["id"]), "enemy_team_id": str(row["enemy_team_id"]), "boss_hp": str(_boss_hp(row["enemy_team_id"])),
        "enemy_hp_percent": "1", "enemy_instance_id": "0", "enemy_birth_turn": "999",
        "enemy_ai": 0, "enemy_ai_para": "0", "belong": str(row["belong"]),
        "if_random": "0" if str(row.get("random_get") or "0") in ("", "0") else "1",
        "seed": rng.randint(1, 9999), "team_id": "0", "sangvis_team_id": "0",
        "ally_instance_ids": [], "squad_instance_ids": [], "hostage_id": "0", "hostage_hp": "0",
        "hostage_max_hp": "0", "reinforce_count": "0", "fix_count": "0",
        "vehicle_with_user_id": 0, "supply_count": "0",
        **_hostage_fields(row),
    }


def _hostage_fields(row):
    """spot.hostage_info "<gun_id>,<hp>": a hostage to rescue (win type 7). Hostage HP is counted in
    points that mission hurts' hostage_value take away."""
    gid, _, hp = str(row.get("hostage_info") or "").partition(",")
    if not gid.strip().isdigit() or not int(gid):
        return {}
    hp = str(int(hp)) if hp.strip().isdigit() else "1"
    return {"hostage_id": str(int(gid)), "hostage_hp": hp, "hostage_max_hp": hp}


# Starting enemies the stc's spots leave out. Vortex of Secrets+ 11497 (recorded 2026-11-12: 34
# at startMission, the stc has 17; the server numbers them in spot order, which fixes each one's
# range): patrols (ai 102 "@spot,n", whose spot is their own start: 6630105/6630104/6630106/
# 6630107 sit on theirs in the stc, and 6630101 was seen on 600114) on their @spot; the rest from
# the DR+ notes' fixed-enemy sheet, each the only fit in its range: layer 1 6630128 "3 nodes above
# the elevator" (600211 > 600210 > 600120 > 600125), 6630130 x2 "1 node lower-left / upper-right
# of the top-right heliport" 600130, 6630129 "3 nodes right of the radar" (6630005's 600220 >
# 600141 > 600300 > 600132); layer 2 6630124 "2 nodes lower-left of the top-left heliport"
# (600182 > 600181 > 600224); layer 3 6630115 / 6630118 upper-right of / right of the upper
# supply node 600200, 6630116 / 6630117 the top-right square's upper-left / lower-right corners.
EXTRA_ENEMIES = {11497: {
    600114: 6630101, 600125: 6630128, 600128: 6630130, 600131: 6630130, 600132: 6630129,
    600136: 6630191, 600138: 6630102, 600140: 6630103, 600182: 6630101, 600188: 6630108,
    600195: 6630109, 600196: 6630110, 600201: 6630115, 600203: 6630116, 600206: 6630117,
    600207: 6630118, 600224: 6630124}}


def start_mission(state, body, rng=random):
    body = body or {}
    mid = int(body.get("mission_id") or 0)
    rows = _spots_by_mission().get(mid)
    if not rows:
        return _story_node(state, mid)
    spots = {int(r["id"]): _spot(r, rng) for r in rows}
    for sid, team in EXTRA_ENEMIES.get(mid, {}).items():
        if sid in spots and not int(spots[sid]["enemy_team_id"]):
            spots[sid].update(enemy_team_id=str(team), boss_hp=str(_boss_hp(team)))
    instance = 0
    for s in spots.values():
        if int(s["enemy_team_id"]):
            instance += 1
            s["enemy_instance_id"] = str(instance)
            s["enemy_birth_turn"] = "1"
            # read by MissionAction$$CheckEnemyDataTemp as int / string
            team = _enemy_teams().get(int(s["enemy_team_id"])) or {}
            s["enemy_ai"] = int(team.get("ai") or 0)
            s["enemy_ai_para"] = local_spots(mid, str(team.get("ai_content") or "0"))
    for dep in body.get("spots") or []:
        s = spots.get(int(dep["spot_id"]))
        if s is not None:
            s["team_id"] = str(dep["team_id"])
    for dep in body.get("sangvis_spots") or []:
        s = spots.get(int(dep.get("spot_id") or 0))
        if s is not None:
            s["sangvis_team_id"] = str(dep.get("team_id") or dep.get("sangvis_team_id") or 0)
    deployed = [str(d["team_id"]) for d in body.get("spots") or []]
    spot_list = list(spots.values())
    state.pop("_last_score", None)
    m = state["_mission"] = {
        "mission_id": mid, "turn": 1, "spots": spot_list, "teams": deployed,
        "team_pos": {str(d["team_id"]): str(d["spot_id"]) for d in body.get("spots") or []},
        "sangvis_pos": {s["sangvis_team_id"]: s["spot_id"] for s in spot_list if s["sangvis_team_id"] != "0"},
        "vehicle_pos": {},
        "enemy_die": 0, "gun_die": 0, "started": int(time.time()), "enemy_attacks": {},
        "patrol_dir": {}, "next_instance": instance + 1, "spawned": {}}
    if win_step_start(mid) is not None:
        m["win_steps"] = list(win_step_start(mid))
    for dep in body.get("vehicle_spots") or []:
        s = spots.get(int(dep.get("spot_id") or 0))
        if s is not None and dep.get("vehicle_with_user_id"):
            s["vehicle_with_user_id"] = int(dep["vehicle_with_user_id"])
            m["vehicle_pos"][str(s["vehicle_with_user_id"])] = s["spot_id"]
    for dep in body.get("squad_spots") or []:
        _place_squad(state, m, dep.get("spot_id"), dep.get("squad_with_user_id"), int(dep.get("battleskill_switch", 1) or 0))
    _place_buildings(m, rng)
    _place_allies(m, body.get("mission_ally_spots"))
    if is_night(mid):
        _third_parties_hold(m)
    _spawn(m, rng, at_start=True)
    m["hostages_total"] = sum(1 for sp in m["spots"] if str(sp.get("hostage_id") or "0") != "0")
    m["had_units"] = bool(m["team_pos"] or m.get("sangvis_pos") or m.get("vehicle_pos"))
    m["had_hq"] = any(s["belong"] == BELONG_OURS for s in _hq_spots(m))
    m["boss_seen"] = any(int(s["enemy_team_id"]) in _boss_teams(mid) for s in _enemy_spots(m))
    m["ap"] = _turn_ap(m)
    rec = _mission_record(state, mid)
    rec["counter"] = str(int(rec["counter"]) + 1)
    if str(body.get("forcewin_missionevent") or "0").strip() not in ("0", "", "False"):
        # the skip button on an event's lowest difficulty (RequestSkipMission): the map counts as
        # won at once, and the reply is read like a win (GameData$$AnalysisMissionResult)
        m["enemy_die"] = int(_missions()[mid].get("expect_enemy_die_num") or 0)
        return _win(state, m, {})
    reply = {"spot_act_info": _hidden_view(state, m), "ap": m["ap"]}
    rally = _pick_rally(m, rng)
    changes = ([rally] if rally else []) + json.loads(_drop_crates(m, rng) or "[]")
    if changes:
        reply["new_spot_change"] = json.dumps(changes, separators=(",", ":"))
    put_out = _sandtable_schedule(m, rng)
    if m.get("squads"):
        reply["squad_info"] = _squad_info(m)
    if m["vehicle_pos"]:
        # an object, not a string like squad_info: the client reads it with readAction false, and
        # DeploymentVehicleTeamController$$Init throws for a spot's vehicle that isn't listed here
        reply["vehicle_info"] = {vid: {"id": int(vid), "atk_building_next_turn": 0, "battleskill_switch": True}
                                 for vid in m["vehicle_pos"]}
    if m.get("buildings"):
        reply["building_info"] = m["buildings"]
        reply.update(_building_start_skills(state, m, rng))
    chips = _chip_skills(state, m)
    if chips:
        reply.update(_merge_replies(chips))
    if m.get("allies"):
        reply["ally_instance_info"] = {iid: _ally_json(m, a) for iid, a in m["allies"].items()}
    if is_night(mid):
        reply["night_spots"] = [{"spot_id": s["spot_id"], "belong": s["belong"]} for s in spot_list]
        _enemy_instances(m, reply, {x["enemy_instance_id"] for x in reply["spot_act_info"]})
    if put_out:
        _corridor_markers(m)
        corridors = _corridor_wave(m, rng)
        if corridors:
            reply = _merge_replies([reply, {"fairy_skill_return": {"mission_hurt": [], "allyteam_summoner": corridors}}])
        reply = _effect_keys(m, reply)
    if _recorded_markers(m, "startMission", rng):
        reply = _effect_keys(m, reply)
    _trigger(m, "start", 0)
    return _flush_triggers(m, reply)


# mission_trigger_engine [ids] (MissionAction$$LoadSkillData -> LoadMissionSkillTrigger ->
# DeploymentPerformanceController.TriggerPerformance(MissionSkillTrigger)): the map's scripted
# performances (a per-map DeploymentPerformanceData asset: camera moves, spines, UI, effects)
# whose module's skillId is in the list play. The ids are the live server's own: mission skills,
# win / lose conditions. Only these are recorded (strings in a list, 2026-11-05 / -06 / -08), so
# only these are sent; any other map gets none (an id no module waits for plays nothing).
TRIGGER_ENGINE = {
    (11341, "start", 0): [580901],
    (11374, "turn", 2): [9584201],        # its lose condition (round 6) at the start of turn 2
    (11355, "step", 1135501): [1135501],  # its win condition, the step finishing (6580113 placed)
    (11946, "start", 0): [770000],
    (11946, "turn", 2): [770002], (11946, "turn", 3): [770003], (11946, "turn", 4): [770004],
}


def _trigger(m, kind, value):
    ids = TRIGGER_ENGINE.get((int(m["mission_id"]), kind, int(value)))
    if ids:
        m.setdefault("trigger_now", []).extend(str(i) for i in ids)


def _flush_triggers(m, reply):
    if m.get("trigger_now"):
        reply["mission_trigger_engine"] = m.pop("trigger_now")
    if m.get("spot_trans_now"):
        reply["spot_trans"] = m.pop("spot_trans_now")
    if m.get("mission_trigger_now"):
        ret = reply.setdefault("fairy_skill_return", {})
        ret["mission_trigger"] = list(ret.get("mission_trigger") or []) + m.pop("mission_trigger_now")
    return reply


# Spots that turn into something else when an enemy team dies (server-only: not in the stc).
# Hurricane Rescue+ (10766) Defection, recorded 2026-11-11: the vehicleBattleFinish that killed the
# Phase 1 Patroller 45010086 answered spot_trans {"<spot>": {"type": "3", "belong": "2"}} for the
# Playpen's P19/P27/P29/P37 and P9/P13/P43/P47 and fairy_skill_return.mission_trigger ["1076601"]
# (also its mission_trigger_engine); the Phase 2 Patroller 45010087 the Tankpen's nine heliports
# with "1076602". From then on they are enemy heliports (_types_now).
KILL_SPOT_TRANS = {
    10766: {
        45010086: ("1076601", (93780, 93782, 93783, 93781, 93807, 93816, 93825, 93794)),
        45010087: ("1076602", (93867, 93861, 93853, 93933, 93934, 93935, 93936, 93937, 93938)),
    },
}


# Spots that turn into enemy heliports at the end of an enemy turn (server-only too), with a team put
# on each one that is empty then. Waterfall (11118), the ranking guide: "At the end of enemy Turn 3,
# A4, A5, A7, B3, and K3 will turn into enemy heliports. If empty they also spawn ID 6549265" (the
# stc's type-2 belong-3 nodes 66698 / 66714 / 66716 / 66757 / 66783); player report's footage has it
# before our turn 4 starts. Sent in endEnemyTurn: its handler reads spot_trans
# (MissionAction$$AnalysicsSpotTransInfo), which goes on to read summon_enemy (AnalysicsMissionGrowEnemy
# -> CheckEnemyGrow: spot_id, enemy_team_id, boss_hp, enemy_hp_percent, enemy_ai, enemy_ai_para,
# enemy_instance_id, as grow_enemy). Not recorded live.
TURN_SPOT_TRANS = {
    11118: {3: ((66698, 66714, 66716, 66757, 66783), 6549265)},
}


def _turn_spot_trans(m):
    """The ending enemy turn's TURN_SPOT_TRANS: converts its spots and returns summon_enemy entries."""
    plan = TURN_SPOT_TRANS.get(int(m["mission_id"]), {}).get(int(m["turn"]))
    key = f"turn{int(m['turn'])}"
    if plan is None or key in (m.get("spot_trans_done") or []):
        return []
    spots, team = plan
    taken, grow = _taken(m), []
    _trans_spots(m, key, spots)
    for sid in spots:
        spot = _spot_of(m, sid)
        if spot is not None and int(sid) not in taken and team in _enemy_teams():
            grow.append(_put_enemy(m, spot, team, int(m["turn"])))
    return grow


def _trans_spots(m, key, spots):
    """spots become enemy heliports (spot_trans in the next reply); key marks it done."""
    m.setdefault("spot_trans_done", []).append(key)
    types = m.setdefault("spot_types", {})
    out = m.setdefault("spot_trans_now", {})
    for sid in spots:
        spot = _spot_of(m, sid)
        if spot is None:
            continue
        spot["belong"] = BELONG_ENEMY
        types[str(sid)] = SPOT_HELIPORT
        out[str(sid)] = {"type": str(SPOT_HELIPORT), "belong": BELONG_ENEMY}


def _kill_spot_trans(m, team):
    plan = KILL_SPOT_TRANS.get(int(m["mission_id"]), {}).get(int(team or 0))
    if plan is None or str(team) in (m.get("spot_trans_done") or []):
        return
    trigger, spots = plan
    _trans_spots(m, str(team), spots)
    m.setdefault("mission_trigger_now", []).append(trigger)
    m.setdefault("trigger_now", []).append(trigger)


STORY = 9      # mission.special_type 9 (MapSpecialType.Story): a story node with no map


def _story_node(state, mid):
    """A story node (special_type 9: no spots, map OPS67_Y; Slow Shock's Black Iris, "SPR Evening;
    Red Tree", "F1 The Red Rider"...). Its node on the event screen sends startMission with empty
    spots and squad_spots (OPSRulerLine$$PlayAvg) and hands the reply straight to
    GameData$$AnalysisMissionResult before playing the story (OPSRulerLine$$
    RequestStartMissionHandle), so the start is the clear: the mission_win_result of a won map,
    which opens the next nodes. None for any other map without spots."""
    row = _missions().get(mid)
    if row is None or int(row.get("special_type") or 0) != STORY:
        return None
    state.pop("_last_score", None)
    m = state["_mission"] = {
        "mission_id": mid, "turn": 1, "spots": [], "teams": [], "team_pos": {}, "sangvis_pos": {},
        "vehicle_pos": {}, "enemy_die": 0, "gun_die": 0, "started": int(time.time()), "enemy_attacks": {},
        "patrol_dir": {}, "next_instance": 1, "spawned": {}, "had_units": False, "had_hq": False}
    rec = _mission_record(state, mid)
    rec["counter"] = str(int(rec["counter"]) + 1)
    # recorded (11448, 2026-11-07): win_type_ids [], rank "5" and medal4 1, a silver medal for
    # every story node whatever its medal_type_silver says
    reply = _win(state, m, {}, won=[])
    reply["mission_win_result"]["medal4"] = 1
    rec["medal4"] = "1"
    return reply


def resume_info(state):
    """The mission in progress for the login reply (Index/index), so the game opens it where it was
    left after a restart: the map as the top-level spot_act_info (GameData$$ReadUserInfo makes
    SpotActions of it) and mission_act_info, read by MissionAction$$.ctor(JsonData) (mission_id,
    turn, ap and the counters, all get_Int; type5_score optional) and then, inside it, the same
    optional enemy/ally/building/squad/vehicle parts as the startMission reply. A battle that was
    being fought when the game closed is kept: the echelon stays on the enemy's node and fights again.
    The game rejects a whole login it can't read ("your account's data has anomalies") and then
    sends nothing more, so a mission is sent back once: if no call follows that login
    (resume_seen), the next login drops the mission instead of locking the account out.
    Coalition echelons are placed from spot_act_info and the account's own teams; sangvis_teams_info
    only gives back their state on the map (see below)."""
    m = state.get("_mission")
    if not m or int(m["mission_id"]) not in _missions():
        return {}
    if m.get("resume_sent") and not m.get("resume_seen"):
        _settle_score(state, m)
        _end_heal(state, m)
        state.pop("_mission", None)
        return {}
    m["resume_sent"], m["resume_seen"] = True, False
    pending = m.get("pending_battle")
    if pending and pending.get("friend"):
        # a friend's attack not fought yet: it stays where it was and steps again this turn
        m.pop("pending_battle")
        m.get("friend_moved", {}).pop(pending["friend"], None)
    # an echelon's battle cut off by closing the game stays: the echelon is on the enemy's node, and the fight
    # starts again on re-entering the map (pending_battle settles its battleFinish then)
    act = {"mission_id": int(m["mission_id"]), "turn": int(m["turn"]), "ap": int(m.get("ap") or 0),
           "enemydie_num": int(m.get("enemy_die") or 0), "enemydie_num_killbyfriend": int(m.get("friend_kills") or 0),
           "enemydie_num_killbymyside": int(m.get("npc_kills") or 0), "save_hostage": int(m.get("hostages_saved") or 0),
           "defend_line_start_turn": int(m.get("line_since") or 0),
           # read without a presence check (MissionAction$$.ctor, GameData$$ReadUserInfo): a missing
           # one throws; the game is always saved on the player's turn
           "gundie_num": int(m.get("gun_die") or 0), "reinforce_friend_team_num": int(m.get("friend_count") or 0), "turn_belong": int(BELONG_OURS)}
    if score_rule(m["mission_id"]) is not None:
        act["type5_score"] = int(m.get("score") or 0)
    # On login these parts are read with readAction true (GameData$$ReadUserInfo -> ReadEnemyTeamData,
    # ReadAllyTeamData, ReadBuildingAction, ReadSquadTeam, ReadVehicleTeam): each is a JSON *string*
    # that the client parses itself; an object there throws and the login fails ("account's data has
    # anomalies"). Every enemy the map shows needs its enemy_instance_info entry, day or night (on a
    # night map, those in sight; the rest are blank in spot_act_info): the map builds each enemy from
    # it (DeploymentEnemyTeamController$$Init), and one missing entry stops the whole map from loading
    # (no enemies, no echelons).
    def text(value):
        return json.dumps(value, separators=(",", ":"))
    if m.get("squads"):
        act["squad_info"] = _squad_info(m)
    if m.get("vehicle_pos"):
        atk = m.get("vehicle_atk") or {}
        act["vehicle_info"] = text({vid: {"id": int(vid), "atk_building_next_turn": int(atk.get(str(vid)) or 0),
                                          "battleskill_switch": True} for vid in m["vehicle_pos"]})
    if m.get("buildings"):
        act["building_info"] = text(m["buildings"])
    if m.get("allies"):
        act["ally_instance_info"] = text({iid: _ally_json(m, a) for iid, a in m["allies"].items()})
    if m.get("friends"):
        act["friend_act_info"] = _friend_act_info(m)       # an object, unlike the parts above
    coalition = [t for t in m.get("sangvis_pos") or {} if str(t) != "0"]
    if coalition:
        # MissionAction$$ReadSangvisTeam: per team {sangvis_team_id: "<id>[:<zone>]" (a string),
        # ally_instance_id (0: our own), battleskill_switch, chip_special_skill {"<special type>":
        # {sangvis_with_user_id, next_turn}} (sets that unit's chip canUseTurn), boss_assist_skill
        # {...: {next_turn}}}, the last two read unguarded ([] when there are none).
        switch, chips = m.get("sangvis_switch") or {}, m.get("chip_turns") or {}
        act["sangvis_teams_info"] = text({str(t): {"sangvis_team_id": str(t), "ally_instance_id": 0,
                                                   "battleskill_switch": bool(switch.get(str(t), True)),
                                                   "chip_special_skill": chips.get(str(t)) or [], "boss_assist_skill": []}
                                          for t in coalition})
    # Read from mission_act_info with readObject true (GameData$$ReadUserInfo -> MissionAction
    # $$LoadSkillData / LoadRangeAttackData), so strings: the special spots and buffs on the map
    # (fairy_skill_on_*), every skill's cooldown (fairy_skill_perform: fairies, Coalition echelons,
    # vehicles, buildings) and the vehicles' range attack turns.
    if (m.get("effects") or {}).get("specials") or (m.get("effects") or {}).get("buffs"):
        on_spot, on_unit = _effect_sets(m)
        act["fairy_skill_on_spot"] = text(on_spot or [])
        for kind, key in _EFFECT_KEYS.items():
            act[key] = text(on_unit[kind] or [])        # empty as [] (see _effect_keys)
    if m.get("cooldowns"):
        act["fairy_skill_perform"] = text(list(m["cooldowns"].values()))
    # also read there, strings too (MissionAction$$CheckWinStep / LoadTriggerPara parse them when
    # readObject): a staged map's current steps and the map's mission items
    if m.get("win_steps") is not None:
        act["mission_win_step_control_ids"] = text(_steps_now(m))
    if _trigger_para(m):
        act["trigger_para"] = text(_trigger_para(m))
    if m.get("range_turns"):
        act["range_atk_turn"] = text(_range_turns(m))
    if m.get("range_rec"):
        act["range_atk_rec"] = text(_range_rec(m))      # (LoadRangeAttackData reads both)
    if m.get("last_battle_info"):
        act["last_battle_info"] = m["last_battle_info"]      # the dolls' battle skill cooldowns
    live = ([m["rally"]] if m.get("rally") else []) + [c for c in (m.get("crates") or {}).values()
                                                       if int(c["end_turn"]) >= int(m["turn"])]
    if live:
        # the dropped crates (see _crate_plan), used ones too: GameData$$ReadUserInfo reads
        # mission_act_info's optional "spots_change" with MissionAction$$ReadChangeSpot, the same
        # JSON string as startTurn's new_spot_change
        act["spots_change"] = json.dumps(live, separators=(",", ":"))
    spots = _hidden_view(state, m, with_known=True)
    enemies = {}
    _enemy_instances(m, enemies, {s["enemy_instance_id"] for s in spots if str(s["enemy_instance_id"]) != "0"})
    act["enemy_instance_info"] = text(enemies.get("enemy_instance_info") or {})
    if m.get("died_enemy"):
        # MissionAction$$LoadKillNum (inside the ctor, revet true: strings), as startTurn sends them
        act.update(_kill_counts(m, text))
    if m.get("moved_step"):
        # who has already stepped this turn (forces the player moves, friends' echelons): read by
        # MissionAction$$.ctor -> LoadMoveStepData, a string there (player report: state lost on resume)
        act["target_moved_step"] = text(m["moved_step"])
    out = {"spot_act_info": spots, "mission_act_info": act}
    if m.get("spot_types"):
        # nodes the map changed into heliports and the like, which the live replies sent only once as
        # spot_trans: the login reads the top-level spot_trans_info with MissionAction
        # $$LoadSpotTransData (readObject: a string). It reads "type" with get_Int, so a number, never a
        # string; the owner already comes with spot_act_info
        out["spot_trans_info"] = text({sid: {"type": int(t)} for sid, t in sorted(m["spot_types"].items())})
    # every unit's ammo and rations on the map (see supply_team), in the records the login builds
    # them from (Gun, SangvisTeam, Squad, Vehicle); only this reply's copy changes
    for key, kind, field in (("gun_with_user_info", "gun", "id"), ("sangvis_team_with_user_info", "sangvis", "team_id"),
                             ("squad_with_user_info", "squad", "id"), ("vehicle_with_user_info", "vehicle", "id")):
        patched = _with_res(m, state.get(key), kind, field)
        if patched is not None:
            out[key] = patched
    return out


def _with_res(m, records, kind, field):
    """A copy of a save list (or dict) with the map's supply for the units it has; None if none."""
    res = {k.split(":", 1)[1]: v for k, v in (m.get("res") or {}).items() if k.startswith(kind + ":")}
    if not res or not records:
        return None

    def one(rec):
        r = res.get(str(rec.get(field)))
        if r is None:
            return rec
        cast = str if isinstance(rec.get("ammo"), str) else int
        return dict(rec, ammo=cast(r["ammo"]), mre=cast(r["mre"]))
    if isinstance(records, dict):
        return {k: one(v) for k, v in records.items()}
    return [one(r) for r in records]


def _kill_counts(m, fmt=lambda v: v):
    """died_enemy {"<enemy_team_id>": kills} and the ally counters, as recorded in startTurn."""
    return {"died_enemy": fmt(dict(m.get("died_enemy") or {})), "died_enemy_b": fmt(_all_kills(m)), "died_ally": fmt([]),
            "died_ally_type": fmt({"1": 0, "2": 0, "0": 0})}


def abort_mission(state, body):
    # DeploymentController$$RequestAbortMissionHandle clears the client's mission in progress
    # (GameData.missionAction, which the mission-select screen checks) only when
    # AnalysisMissionResult accepts mission_lose_result, and an empty one is not accepted.
    m = state.pop("_mission", None)
    if m:
        _settle_score(state, m)       # a score map keeps what it earned when it's ended or restarted
        _end_heal(state, m)
    counts = _result_counts(m) if m else {"turn": "1", "gundie_num": 0, "mysquad_die_num": 0,
                                          "sangvisdie_num": 0, "enemydie_num": "0"}
    return {"mission_lose_result": dict(counts, user_exp=0, win_type_ids=[], **(_score_result(m) if m else {}))}


def _score_result(m):
    """A score map's end result keys (recorded on 11116 abortMission / endEnemyTurn: type5_score,
    rank as an int, an empty mission_type5_drop). APPROXIMATION: the rank is mission_rank's."""
    if score_rule(m["mission_id"]) is None:
        return {}
    return {"type5_score": int(m.get("score") or 0), "rank": mission_rank(m),
            "mission_type5_drop": {"item": [], "prize": []}}


# --- mission turn loop -----------------------------------------------------------------

BELONG_OURS = "1"
BELONG_ENEMY = "2"
BELONG_NEUTRAL = "3"
# spot belong 99 / 100 (the client's Belong.hide / ingore): nodes the map keeps out of sight until
# something reveals them (Scorpion Vortex's right side, Tide of Blood's difficulty heliports)
HIDDEN_BELONGS = ("99", "100")
BELONG_GONE = "100"   # out of play: a hidden node, or an area that closed (AREA_CLOSE)
SPOT_HQ = 1
SPOT_HELIPORT = 3
SPOT_HEAVY = 7          # heavy heliport
RANK_S = 5
RANK_A, RANK_B = 4, 3
RANK_LOST = 2      # battle_rank of a lost battle (recorded on 5-6, losing to the boss)
# A won battle's rank falls with the share of the echelon's full HP it has lost (the client only
# shows the server's battle_rank). Recorded: 2% lost -> S, 49% lost -> A (11353, four map dolls
# 2472 HP down to 1262); player report: "around 30% lost drops the rank". APPROXIMATION: S below
# RANK_A_LOST, A below RANK_B_LOST, else B.
RANK_A_LOST, RANK_B_LOST = 0.30, 0.60
FAVOR_PER_WIN = 3000      # 0.3 affection in the save's units (1000000 = 100)

# Enemy AI codes (enemy_team.ai; the client's AIBehavior enum and team_ai table).
# Enemy AI. enemy_team.ai codes for the enemy force are named in stc team_ai (force_id 2) and
# described in data/text/table/team_ai.json: 1 Standby, 99 Offline, 101 Patrol, 102 Alert,
# 103 Expand (201/202: Patrol/Alert "susceptible to special skills"). Code 0 means
# Garrison ("will hold position and not move", team_ai 999) when enemy_team.if_stay is 1,
# else the mission's default, mission.enemy_ai_type (team_ai force_id 1): -1 night battle
# ("unable to determine trajectory"), 1 Standby, 2 and 4 Random, 3 Attack (toward the
# Command Post). Same resolution as the client's EnemyTeamInfo$$get_teamAi.
# 106 Lock On ("move towards the designated NPC following the shortest viable route"): ai_content
# "<ally_team_id>:<range>" (543101 "541400:15" on 11146; 6580301 "6580118:15" on 11359).
STANDBY, RANDOM, ATTACK, PATROL, ALERT, EXPAND, LOCK_ON = "standby", "random", "attack", "patrol", "alert", "expand", "lock_on"
_TEAM_AI = {101: PATROL, 201: PATROL, 102: ALERT, 202: ALERT, 103: EXPAND, 106: LOCK_ON}
_MISSION_AI = {2: RANDOM, 3: ATTACK, 4: RANDOM, -1: RANDOM}
AI_GARRISON = 999
# Anything else (1 Standby, 99 Offline, and the rare 4/203) holds position.

_ENEMY_FIELDS = ("enemy_team_id", "enemy_instance_id", "boss_hp", "enemy_hp_percent",
                 "enemy_birth_turn", "enemy_ai", "enemy_ai_para")
_NO_ENEMY = {"enemy_team_id": "0", "enemy_instance_id": "0", "boss_hp": "0", "enemy_hp_percent": "1",
             "enemy_birth_turn": "999", "enemy_ai": 0, "enemy_ai_para": "0"}


@lru_cache(maxsize=1)
def _enemy_teams():
    return {int(r["id"]): r for r in stc.table("enemy_team")}


ENEMY_BOSS = 1      # enemy_character_type.type (EnemyType.boss)


@lru_cache(maxsize=1)
def _enemy_types():
    return {int(r["id"]): r for r in stc.table("enemy_character_type")}


@lru_cache(maxsize=1)
def _team_members():
    out = {}
    for r in stc.table("enemy_in_team"):
        out.setdefault(int(r["enemy_team_id"]), []).append(int(r["enemy_character_type_id"]))
    return out


@lru_cache(maxsize=None)
def _boss_hp(team_id):
    """A team's boss HP as the map starts it: the boss_hp of its first boss member, as
    EnemyTeam$$get_BossHpMax takes it (first enemy_in_team row whose type is EnemyType.boss;
    boss_hp equals its maxlife there), else of its first member with any boss_hp. 0: no boss.
    A spot's boss_hp of 0 makes the client start the boss dead."""
    if not int(team_id or 0):
        return 0            # no enemy (enemy_in_team has rows under team 0 too)
    types = _enemy_types()
    members = [types.get(c, {}) for c in _team_members().get(int(team_id), [])]
    bosses = [r for r in members if int(r.get("boss_hp") or 0)]
    first = next((r for r in bosses if int(r.get("type") or 0) == ENEMY_BOSS), bosses[0] if bosses else {})
    return int(first.get("boss_hp") or 0)


def enemy_ai(team_id):
    """(ai code, ai_content) of an enemy team; code 0 with if_stay set is Garrison (999)."""
    row = _enemy_teams().get(int(team_id or 0)) or {}
    ai = int(row.get("ai") or 0)
    if ai == 0 and int(row.get("if_stay") or 0) == 1:
        ai = AI_GARRISON
    return ai, str(row.get("ai_content") or "0")


# A map whose AI-0 teams don't follow its enemy_ai_type: Scorpion Vortex (enemy_ai_type 4, read as
# random here) has its AI-0 teams on L1, L19, L4 and L23 "on Standby. Enemies on Standby will never
# move" (the MS guide).
MAP_AI_DEFAULT = {10674: "standby"}


# a mod map's "default_ai" for its AI-0 teams, where enemy_ai_type has no code for it
MAP_AI_WORDS = {STANDBY, RANDOM, ATTACK, ALERT, EXPAND}
ALERT_RANGE_DEFAULT = "2"


def enemy_behaviour(mid, team_id):
    """(behaviour, ai_content) of an enemy team in a mission, resolving code 0 to the
    mission's default."""
    behaviour, para = _enemy_behaviour(mid, team_id)
    return behaviour, local_spots(mid, para)


def _enemy_behaviour(mid, team_id):
    ai, para = enemy_ai(team_id)
    if ai == 0 and _for_map(MAP_AI_DEFAULT, mid):
        return _for_map(MAP_AI_DEFAULT, mid), para
    if ai == 0:
        word = _map_setting(mid, "default_ai")
        if word in MAP_AI_WORDS:
            return word, para if word != ALERT or (_ids(para.split("|")[0]) or [0])[0] > 0 else ALERT_RANGE_DEFAULT
    if ai == 0:
        return _MISSION_AI.get(int(_missions().get(mid, {}).get("enemy_ai_type") or 0), STANDBY), para
    return _TEAM_AI.get(ai, STANDBY), para


def _ids(text):
    return [int(x) for x in str(text or "").replace(";", ",").split(",") if x.strip().isdigit()]


@lru_cache(maxsize=None)
def _links(mid):
    """Spot -> spots an enemy or echelon can move to, in stc spot.route order (some links are
    one-way). Route order also breaks ties between equally short paths."""
    return {int(r["id"]): _ids(r["route"]) for r in _spots_by_mission().get(mid, [])}


@lru_cache(maxsize=None)
def _neighbours(mid):
    """Spot -> every spot linked to it either way, for surround captures."""
    out = {}
    for r in _spots_by_mission().get(mid, []):
        for to in _ids(r["route"]) + _ids(r["map_route"]):
            out.setdefault(int(r["id"]), set()).add(to)
            out.setdefault(to, set()).add(int(r["id"]))
    return out


@lru_cache(maxsize=None)
def _spot_types(mid):
    return {int(r["id"]): int(r["type"]) for r in _spots_by_mission().get(mid, [])}


def _distances(mid, start, blocked=()):
    """Steps from start along routes, never passing through blocked spots."""
    dist, todo = {start: 0}, [start]
    links = _links(mid)
    while todo:
        cur = todo.pop(0)
        if cur != start and cur in blocked:
            continue
        for nxt in links.get(cur, ()):
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                todo.append(nxt)
    return dist


def _step_toward(mid, start, goals, blocked=()):
    """First spot on a shortest route from start to the nearest goal, or None."""
    goals = set(goals) - {start}
    if not goals:
        return None
    prev, todo, links = {start: None}, [start], _links(mid)
    while todo:
        cur = todo.pop(0)
        if cur != start and cur in blocked:
            continue        # a blocked goal is no goal: the next nearest is (player report: an expanding
                            # enemy whose nearest blue node another had just attacked stood still)
        if cur in goals:
            while prev[cur] != start:
                cur = prev[cur]
            return cur
        for nxt in links.get(cur, ()):
            if nxt not in prev:
                prev[nxt] = cur
                todo.append(nxt)
    return None


def _mission(state):
    m = state.get("_mission")
    if m is not None:
        _spent_buffs(m)         # a used-up buff is shown once more, then gone (see _BUFF_COUNTS)
        # missions saved by older versions lack these
        if "team_pos" not in m:
            m["team_pos"] = {str(s["team_id"]): s["spot_id"] for s in m["spots"] if str(s["team_id"]) != "0"}
        m.setdefault("ap", _turn_ap(m))
        m.setdefault("enemy_die", 0)
        m.setdefault("gun_die", 0)
        m.setdefault("had_hq", any(s["belong"] == BELONG_OURS for s in _hq_spots(m)))
        m.setdefault("enemy_attacks", {})
        m.setdefault("patrol_dir", {})
        m.setdefault("sangvis_pos", {s["sangvis_team_id"]: s["spot_id"] for s in m["spots"]
                                     if str(s.get("sangvis_team_id") or "0") != "0"})
        m.setdefault("vehicle_pos", {})
    return m


def _spot_of(m, spot_id):
    return next((s for s in m["spots"] if s["spot_id"] == str(spot_id)), None)


def _enemy_spots(m):
    return [s for s in m["spots"] if str(s["enemy_instance_id"]) != "0" and str(s["enemy_team_id"]) != "0"]


def _hq_spots(m):
    types = _spot_types(m["mission_id"])
    return [s for s in m["spots"] if types.get(int(s["spot_id"])) == SPOT_HQ]


def _echelon_spots(m):
    """Spots our echelons stand on, Coalition echelons and friends' support echelons included."""
    return ({int(s) for s in m["team_pos"].values()} | {int(s) for s in m.get("sangvis_pos", {}).values()}
            | {int(s) for s in m.get("vehicle_pos", {}).values()} | _friend_spots(m))


@lru_cache(maxsize=1)
def _win_types():
    return {int(r["id"]): r for r in stc.table("mission_win_type_config")}


def win_spots(mid):
    """Spots that must all be ours to win: win_spot_id, else the spots of "occupy" (1101)
    win conditions, else every enemy HQ on the map."""
    row = _missions().get(mid, {})
    on_map = _spot_types(mid)
    # a win_spot_id that is not on the map (59, 10045, 10386) could never be held: ignored
    spots = [s for s in _ids(row.get("win_spot_id")) if s in on_map]
    if not spots:
        for wid in _ids(row.get("win_type")):
            cond = _win_types().get(wid)
            if cond and int(cond["type"]) == 1101:
                spots += _ids(cond["arguments"])
    if not spots:
        spots = [int(r["id"]) for r in _spots_by_mission().get(mid, [])
                 if int(r["type"]) == SPOT_HQ and int(r["belong"]) == 2]
    return spots


# Spots that give AP while held (SpotType: 1 headQuarter, 3 DTA heliport, 7 HeavyDTA; -3 / -7 the
# timed ones).
AP_SPOT_TYPES = {1, 3, 7, -3, -7}


def _turn_ap(m):
    """AP for a turn (and at the map's start): one per unit of ours on the map (doll and Coalition
    echelons, HOCs, vehicles) and one per HQ or heliport held. Recorded on map 126: 3 at the start
    (a Coalition echelon, the HQ, a heavy heliport), 4 with two echelons, 7 with two echelons, a
    HOC, the HQ, the heavy heliport and two heliports. Allied forces give none."""
    types = _spot_types(m["mission_id"])
    held = sum(1 for s in m["spots"] if s["belong"] == BELONG_OURS and types.get(int(s["spot_id"])) in AP_SPOT_TYPES)
    units = (len(m.get("team_pos") or {}) + sum(1 for t in (m.get("sangvis_pos") or {}) if _own_sangvis(t))
             + len(m.get("squads") or {}) + len(m.get("vehicle_pos") or {}))
    return max(1, units + held)


def _mission_record(state, mid):
    """The mission's mission_with_user_info row, created when missing."""
    rows = state.setdefault("mission_with_user_info", [])
    row = next((r for r in rows if str(r["mission_id"]) == str(mid)), None)
    if row is None:
        next_id = max((int(r.get("id") or 0) for r in rows), default=0) + 1
        user_id = str((state.get("user_info") or {}).get("user_id") or "")
        row = {"id": str(next_id), "user_id": user_id, "mission_id": str(mid), "medal1": "0",
               "medal2": "0", "bestrank": "0", "medal4": "0", "counter": "0", "win_counter": "0",
               "shortest_in_coinmission": "0.00", "type5_score": "0", "is_open": "1",
               "is_drop_draw_event": "0", "is_close": "0", "cycle_win_count": "0",
               "mapped_win_counter": "0", "drop_item_count": "", "intensify_item": ""}
        rows.append(row)
    return row


def _open_next(state, row):
    """Unlock the next mission of the same chapter and difficulty, if there is one. (Not matched on
    the win type: a chapter's last map is often "destroy the boss team", type 4, after type-2 maps.)
    Returns the win reply's "open" for it, {"<mission_id>": "<open>,<clocked>,<has reward>"}, which
    is how the client hears of the unlock before its next Index/index (GameData$$LoadMissionKey)."""
    keys = ("campaign", "if_emergency", "duplicate_type")
    nxt = next((r for r in _missions().values()
                if all(r[k] == row.get(k) for k in keys) and int(r["sub"]) == int(row.get("sub") or 0) + 1), None)
    if nxt is None:
        return {}
    # a map behind mission keys opens when they are held (_open_by_keys), not as the chapter's
    # next (10106 -> 10107 needs key 101062, which 10106 drops)
    held = state.get("mission_key_with_user_info") or {}
    if not _requirement_met(nxt.get("open_mission_keys"), held):
        return {}
    _mission_record(state, nxt["id"])["is_open"] = "1"
    return {str(nxt["id"]): "1,0,0"}


# Mission keys and map items. A win drops mission.drop_mission_key: ";"-separated groups of three
# fields, the keys in the third ("0,0,10051", "0,0,1051000:1|1051002:1|1051003:1"; "key:n", n
# defaulting to 1; the first two fields are 0 on every map but 11085, and aren't understood). Every
# key listed drops, "|" ones included, on every win: in the save this account came with, 1,297 keys
# held exactly as many times as their maps were won, and on the 78 maps with "|" every key of the
# group was held. reset_drop_key_once (91 maps) drops a key only while it isn't held (35 more keys
# held once though won again). drop_mission_item is the same for inventory items (10194:
# "0,0,8001:3000"). The save keeps the totals, mission_key_with_user_info {key: "n"}, and the
# win or lose result reports what changed as totals, mission_keys {key: n} and mission_item
# {item: n} (GameData$$LoadMissionKey sets the totals it is given, from either result).
# A map opens once every key of its open_mission_keys is held ("k:n;k:n", all of them: every one
# of the 65 played maps that names several had them all; "a:1|b:1" in one entry: either) and
# open_mission_items ("8001:10") is left alone: it is the Intelligence Points of the live Isomer and
# Shattered Connexion runs, no longer charged or needed (entering Illusory Peace cost nothing in a
# 2026-11 playtest; 31 of the 71 played maps that list an item are open without it held).
# close_missions (23 maps; 10107 and 10108 close each other, a branch) is marked is_close.
def _key_pairs(text):
    out = []
    for part in str(text or "").replace("|", ",").split(","):
        key, _, n = part.partition(":")
        if key.strip().isdigit() and int(key):
            out.append((key.strip(), int(n) if n.strip().isdigit() else 1))
    return out


def _drops(text):
    """drop_mission_key / drop_mission_item: every (id, n) of the groups' third fields."""
    out = []
    for group in str(text or "").split(";"):
        fields = group.split(",", 2)
        if len(fields) == 3:
            out += _key_pairs(fields[2])
    return out


def _item_row(state, iid):
    rows = state.setdefault("item_with_user_info", [])
    row = next((r for r in rows if str(r["item_id"]) == str(iid)), None)
    if row is None:
        row = {"item_id": str(iid), "number": "0", "last_recover_time": "0"}
        rows.append(row)
    return row


def _drop_keys(state, mid):
    """A win's key and item drops; returns ({key: total}, {item: total}) for what changed."""
    row = _missions().get(int(mid), {})
    once = str(row.get("reset_drop_key_once") or "0").strip() not in ("", "0")
    held = state.setdefault("mission_key_with_user_info", {})
    if not isinstance(held, dict):
        held = state["mission_key_with_user_info"] = {}
    keys, items = {}, {}
    for key, n in _drops(row.get("drop_mission_key")):
        have = int(held.get(key) or 0)
        if once and have:
            continue
        held[key] = str(have + n)
        keys[key] = have + n
    for iid, n in _drops(row.get("drop_mission_item")):
        item = _item_row(state, iid)
        item["number"] = str(int(item["number"] or 0) + n)
        items[iid] = int(item["number"])
    return keys, items


def _requirement_met(text, have):
    """open_mission_keys: every ";" entry held, "|" in an entry: any."""
    entries = [e for e in str(text or "").split(";") if e.strip() not in ("", "0")]
    return all(any(int(have.get(k) or 0) >= n for k, n in _key_pairs(e)) for e in entries)


def _open_by_keys(state, keys, items=None):
    """Maps that the keys just changed open: {mission_id: "1,0,0"} for the win reply."""
    if not keys:
        return {}
    held = state.get("mission_key_with_user_info") or {}
    known = {str(r["mission_id"]): r for r in state.get("mission_with_user_info") or []}
    opened = {}
    for row in _missions().values():
        need_keys = row.get("open_mission_keys")
        names = {k for k, _ in _key_pairs(str(need_keys or "").replace(";", ","))}
        if not names & set(keys):
            continue
        rec = known.get(str(row["id"]))
        if rec is not None and rec.get("is_open") == "1":
            continue
        if _requirement_met(need_keys, held):
            _mission_record(state, row["id"])["is_open"] = "1"
            opened[str(row["id"])] = "1,0,0"
    return opened


# Mapped maps: mission.mapped_mission_id names a mission_mapped group ("10196,10254": the same
# map in two places). In the save this account came with, every member of a group with a win
# shows mapped_win_counter 1, a member never won included (527 of 530; one group of three, 2);
# the client reads it into Mission.mappedwincounter. Set on existing records only, so a map
# isn't opened by it.
@lru_cache(maxsize=1)
def _mapped_groups():
    return {int(r["id"]): _ids(r["mapped_missions"]) for r in stc.table("mission_mapped")}


# Older events (Glory Day, Gunslinger Girl, VA-11 HALL-A, ...) have no mission_mapped group: the harder map is
# only named so ("STALKER" / "STALKER EX", "Critical Angle II" / "... EX-I" / "... EX-II"; Glory Day's EX maps sit
# in their own campaigns, -21 and -22, beside -19 and -20). name_groups pairs them by name; the base game's
# pairs are in data/difficulty_groups.json (tools/build_difficulty_groups.py), a mod's are made from its text.
_TIER = re.compile(r"^(?P<base>.*?)[\s\-]*(?P<mark>EX|UX)(?:[\s\-]*(?P<num>I{1,3}))?$")
_PART = re.compile(r"[\s\-]*(?:I{1,3}|[①-⑨])$")


def _tier(mark, num):
    return {"EX": 1, "UX": 2}[mark] * 10 + len(num or "")


def name_groups(rows, names):
    """rows: mission rows; names: {mission id: display name}. -> {mission id: [ids, easiest first]} for each map
    named as a harder version of another and rated harder (mission.difficulty): the base map is the one of the
    same name (or the name plus a part number: "①", " I") in the same campaign, else in the nearest campaign up
    to 3 away."""
    norm = {int(r["id"]): " ".join(str(names.get(int(r["id"])) or "").replace("//n", " ").split()) for r in rows}
    camp = {int(r["id"]): int(r.get("campaign") or 0) for r in rows}
    rating = {int(r["id"]): int(r.get("difficulty") or 0) for r in rows}
    by_name = {}
    for mid, n in norm.items():
        if n:
            by_name.setdefault(n, []).append(mid)
            by_name.setdefault(_PART.sub("", n), []).append(mid)
    marked = {}
    for mid, n in norm.items():
        m = _TIER.match(n)
        if not m or not m.group("base"):
            continue
        base = m.group("base")
        exact = [b for b in by_name.get(base, []) if norm[b] == base]      # "Reflective Surface∞" for its "-EX"
        loose = [b for b in by_name.get(_PART.sub("", base), []) if not _TIER.match(norm[b])]
        cands = [b for b in dict.fromkeys(exact or loose) if b != mid and abs(camp[b] - camp[mid]) <= 3
                 and rating[b] < rating[mid]]      # "Annealing EX" (1000, below "Annealing I") is a story node
        if not cands:
            continue
        best = min(cands, key=lambda b: (abs(camp[b] - camp[mid]), norm[b] != base, b))
        marked.setdefault(best, []).append((_tier(m.group("mark"), m.group("num")), mid))
    out = {}
    for base, tiers in marked.items():
        group = [base] + [mid for _, mid in sorted(tiers)]
        for mid in group:
            out[mid] = group
    return out


@lru_cache(maxsize=1)
def _name_groups():
    from . import mods
    path = config.ROOT / "data" / "difficulty_groups.json"
    groups = {int(k): v for k, v in json.loads(path.read_text("utf-8")).items()} if path.is_file() else {}
    text = {}
    for mod in mods.discover():
        text.update(mod.get("text") or {})
    if text:
        rows = [r for r in _missions().values() if str(r.get("name") or "") in text]
        if rows:
            names = {int(r["id"]): text[str(r["name"])] for r in rows}
            groups.update(merge_mapped(name_groups(rows, names), _mapped_groups()))
    return groups


def merge_mapped(groups, mapped):
    """A name group sharing a map with a mission_mapped group extends that group with its harder maps: in the name
    group's order when it holds the whole mapped group, else after it."""
    member = {mid: g for g in mapped.values() for mid in g}
    out = {}
    for mid, g in groups.items():
        known = next((member[x] for x in g if x in member), None)
        if known and not set(known) <= set(g):
            g = list(known) + [x for x in g[1:] if x not in known]
        for x in g:
            if x not in member:
                out[x] = g
    return out


@lru_cache(maxsize=1)
def _mapped_by_member():
    """mission id -> its mission_mapped group. Found by membership: some events' rows (Gunslinger Girl, -38 and
    -41) have mapped_mission_id 0 though a group lists them. Name groups (merge_mapped) can add harder maps to
    one ("That which must be protected EX I" beside its "EX II")."""
    return {mid: g for g in _mapped_groups().values() for mid in g}


def _difficulty_group(row):
    mid = int(row.get("id") or 0)
    return _mapped_by_member().get(mid) or _name_groups().get(mid, [])


def _mapped_win(state, row):
    """A map's difficulties, easiest first: stc mission_mapped ("Terzetto", "- EX", "- UX"), else name_groups. A win
    counts for the group, and as a clear of each easier one not yet won, which opens what that one's win opens
    (returned as the win reply's "open")."""
    group = _difficulty_group(row)
    opened = {}
    mid = int(row.get("id") or 0)
    for lower in group[:group.index(mid)] if mid in group else []:
        rec = _mission_record(state, lower)
        if int(rec["win_counter"] or 0) == 0 and lower in _missions():
            rec["win_counter"] = "1"
            rec["counter"] = str(max(int(rec["counter"] or 0), 1))
            rec["medal1"] = "1"
            opened.update(_open_next(state, _missions()[lower]))
    mapped = _mapped_by_member().get(mid, [])
    for r in state.get("mission_with_user_info") or []:
        if int(r["mission_id"]) in mapped:
            r["mapped_win_counter"] = str(max(1, int(r.get("mapped_win_counter") or 0)))
    return opened


def _close_missions(state, row):
    for mid in _ids(row.get("close_missions")):
        if mid in _missions():
            _mission_record(state, mid)["is_close"] = "1"


def _result_counts(m):
    # turn and enemydie_num are read as strings (JsonData op_Explicit string), the other
    # counters with get_Int (GameData$$AnalysisMissionResult).
    return {"turn": str(m["turn"]), "gundie_num": m.get("gun_die", 0), "mysquad_die_num": m.get("squad_die", 0),
            "sangvisdie_num": 0, "enemydie_num": str(m.get("enemy_die", 0)),
            "enemydie_num_killbyfriend": str(m.get("friend_kills", 0))}


def win_groups(mid):
    """mission.type as alternatives of required goals: "2" -> [[2]]. Groups split on ";",
    goals within a group on ","; a goal marked "*" is optional (not needed to win)."""
    groups = []
    for g in str(_missions().get(mid, {}).get("type") or "2").split(";"):
        req = [int(x) for x in (p.strip() for p in g.split(",")) if x.lstrip("-").isdigit()]
        if req:
            groups.append(req)
    return groups or [[2]]


def _targets_held(m, reach=False):
    """Every win spot ours. Taken spots change hands at the end of our turn, so a capture wins at
    endTurn (recorded: map 2 twice, 90038's 1101 "80546" at endTurn, not on the move onto it); a
    reach goal (1) counts an echelon standing there."""
    targets = win_spots(m["mission_id"])
    standing = _echelon_spots(m) if reach else set()
    return bool(targets) and all(t in standing or (_spot_of(m, t) or {}).get("belong") == BELONG_OURS
                                 for t in targets)


def _boss_teams(mid):
    return set(_ids(_missions().get(mid, {}).get("boss_team_id"))) - {0}


def _goal_met(m, goal):
    row = _missions().get(m["mission_id"], {})
    if goal == 3:
        # destroy every enemy, or take the win spots: 3316 of 3961 missions use 3, ordinary
        # story maps among them, which are won by taking the enemy HQ
        return not _enemy_spots(m) or _targets_held(m)
    if goal == 4:       # destroy the boss team
        bosses = _boss_teams(m["mission_id"])
        return bool(m.get("boss_killed")) or (bool(bosses) and bool(m.get("boss_seen")) and
                                              not any(int(s["enemy_team_id"]) in bosses for s in _enemy_spots(m)))
    if goal == 11:      # survive win_turn turns (checked when a new turn starts)
        return int(m["turn"]) > int(row.get("win_turn") or 0) > 0
    if goal == SCORE_GOAL:  # a score map ends well once its turns are used up, or on the win spots
        limit = int(row.get("turn_limit") or 0)
        return bool(limit) and int(m["turn"]) > limit or _targets_held(m)
    if goal == GOAL_SUPPLY_LINE:
        return _supply_line_held(m, int(row.get("expect_defend_line_turn") or 0))
    if goal == GOAL_HOSTAGE:
        need = (_ids(row.get("expect_hostage_num")) or [1])[0]
        return int(m.get("hostages_saved") or 0) >= max(1, need)
    # 1 reach / 2 capture, and goals that are not simulated, use the win spots
    return _targets_held(m, reach=goal == 1)


GOAL_SUPPLY_LINE, GOAL_HOSTAGE = 6, 7      # MissionWinType createSupplyLine, saveHostage
SPOT_SUPPLY = 6                            # the supply point a supply line must reach


# mission.random_line_spot: the nodes one of which the map's supply point (its "supply flag") is,
# picked at random when the map starts (Tide of Blood 10521: N3 92564 or N22 92563, the DR guide).
# Recorded (11116, packet log 2026-11-07): startMission's new_spot_change turns the picked node, a
# normal one in the stc, into type 6 from turn 1 to turn 10. Maps whose candidates are all type 6
# in the stc already (10342, 10365, 10386, 10675, 10800, 11549, 11630, 11988) are left as they are.
RALLY_END_TURN = 10
SPOT_NORMAL = 2


def _pick_rally(m, rng=random):
    row = _missions().get(int(m["mission_id"])) or {}
    spots = [x for x in _ids(row.get("random_line_spot")) if _spot_of(m, x) is not None]
    types = _spot_types(m["mission_id"])
    if not spots or all(types.get(x) == SPOT_SUPPLY for x in spots):
        return None
    end = max(RALLY_END_TURN, int(row.get("turn_limit") or 0))
    first = (RALLY_MOVES.get(int(m["mission_id"])) or {}).get("first")
    m["rally"] = {"spot_id": first if first in spots else rng.choice(spots), "type": SPOT_SUPPLY, "start_turn": "1", "end_turn": end,
                  "can_use_count": 0, "use_count": 0}
    return m["rally"]


# Maps whose supply point moves (the guides): Imaginary Maze+ 10158 "will change once on turn 6 and
# once on turn 11, appearing at random on one of the four, never where it has been" (the DD+ sheet);
# Labyrinthine Defense+ 11435 starts on the node 3 right of the Command Post (600052; "very rarely"
# on 600038 at once, not modelled) and moves to 600038 (the 6363018 node) on turn 5 (the PL+ sheet).
# A move doesn't break the line's run if it is joined again that turn (scored at the turn's end).
RALLY_MOVES = {10158: {"turns": (6, 11)}, 11435: {"turns": (5,), "first": 600052}}


def _move_rally(m, rng=random):
    """startTurn: the supply point moves (RALLY_MOVES); the new_spot_change entries, or []."""
    plan = RALLY_MOVES.get(int(m["mission_id"]))
    old = m.get("rally")
    if not plan or not old or int(m["turn"]) not in plan["turns"]:
        return []
    row = _missions().get(int(m["mission_id"])) or {}
    used = set(m.setdefault("rally_used", [int(old["spot_id"])]))
    spots = [x for x in _ids(row.get("random_line_spot")) if x not in used] or \
            [x for x in _ids(row.get("random_line_spot")) if x != int(old["spot_id"])]
    if not spots:
        return []
    new = rng.choice(spots)
    m["rally_used"].append(new)
    back = dict(old, type=_spot_types(m["mission_id"]).get(int(old["spot_id"]), 2), start_turn=str(m["turn"]))
    m["rally"] = dict(old, spot_id=new, start_turn=str(m["turn"]))
    return [back, m["rally"]]


@lru_cache(maxsize=None)
def _repair_uses(mid):
    """Repair points (type 8) with a limited number of repairs: spot.durability "<x>,<repairs>"
    (99 unlimited; 11435's three are "0,5", the PL+ notes: "each repair station gives 5 repairs")."""
    out = {}
    for r in _spots_by_mission().get(mid, []):
        parts = str(r.get("durability") or "").split(",")
        if int(r["type"]) == SPOT_REPAIR and len(parts) == 2 and parts[1].strip().isdigit() and int(parts[1]) < 99:
            out[int(r["id"])] = int(parts[1])
    return out


def _types_now(m):
    """The map's spot types as they are now: the stc's, with the picked supply point (_pick_rally),
    the map's own crate nodes (type 5) that were used as normal ones (see score_rule field 7), and
    repair points whose repairs are all used as normal ones (the PL+ notes: "once a repair station's
    repairs are used up it becomes a normal node, worth only 1,000 at the end")."""
    types = dict(_spot_types(m["mission_id"]))
    uses = _repair_uses(int(m["mission_id"]))
    for sp in m["spots"]:
        if types.get(int(sp["spot_id"])) == SPOT_CRATE and int(sp.get("supply_count") or 0) > 0:
            types[int(sp["spot_id"])] = SPOT_NORMAL
        left = uses.get(int(sp["spot_id"]))
        if left is not None and int(sp.get("fix_count") or 0) >= left:
            types[int(sp["spot_id"])] = SPOT_NORMAL
    if m.get("rally"):
        types[int(m["rally"]["spot_id"])] = SPOT_SUPPLY
    for sid, t in (m.get("spot_types") or {}).items():
        types[int(sid)] = int(t)        # spots that changed type in the run (KILL_SPOT_TRANS)
    return types


def _supply_line(m):
    """Our supply line stands: a supply point (spot type 6) we hold is joined to a Command Post we
    hold through spots we hold or stand on (DeploymentController$$CheckSupplyLine)."""
    held = {int(s["spot_id"]) for s in m["spots"] if s["belong"] == BELONG_OURS} | _echelon_spots(m)
    types = _types_now(m)
    hqs = [s for s in held if types.get(s) == SPOT_HQ]
    goals = {s for s in held if types.get(s) == SPOT_SUPPLY}
    if not hqs or not goals:
        return False
    links, seen, todo = _links(m["mission_id"]), set(hqs), list(hqs)
    while todo:
        cur = todo.pop()
        if cur in goals:
            return True
        for nxt in links.get(cur, ()):
            if nxt in held and nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return False


# A score map's supply line pays at the end of each of our turns it stands, more the longer it has
# stood; a break starts it again (player report). Per map, the n-th turn's points; nothing past the list.
# Server-only: no stc table, game_config entry or mission field holds these (11116 and 11630 have
# the same event_score and mission rows bar the line's spot), so they come from player reports.
SUPPLY_LINE_GAINS = {
    11116: (5000, 15000, 30000, 50000, 70000, 90000),       # Reign of Chaos+ (player report)
    11630: (5000, 10000, 20000, 30000, 40000, 50000),       # City of Nightmares+ (player report)
    11549: (50000, 100000, 150000),                         # Operation Mistbuster+ (player report)
    10675: (50000, 100000, 150000),                         # Operation Mistbuster (player report)
    10521: (50000, 100000, 150000),                         # Tide of Blood (DR guide: 50k, 100k, 150k)
    10342: (5000, 6250, 7500, 8750, 10000),                 # Flowers of the End (player report)
    10365: (5000, 6250, 7500, 8750, 10000),                 # Flowers of the End EX (player report)
    11320: (15000, 18750, 22500, 26250, 30000, 37500),      # Flowers of the End+ (player report)
    10800: (5000, 10000, 20000, 30000, 40000, 50000, 60000, 70000, 80000),     # City of Nightmares (player report)
    # Imaginary Maze+ (player report, by turn: turn 3 the first): 5000 ... 25000
    10158: (5000, 6250, 7500, 8750, 10000, 12500, 15000, 17500, 20000, 20000, 25000),
    11988: (10000, 20000, 40000, 80000),                    # Steel Rain Salute (player report)
}
SUPPLY_LINE_DEFAULT = SUPPLY_LINE_GAINS[11116]              # GUESS for other score maps


def _supply_line_score(m):
    """A score map's supply line, at the end of each of our turns it stands (SUPPLY_LINE_GAINS)."""
    if score_rule(m["mission_id"]) is None:
        return
    if not _supply_line(m):
        m.pop("line_turns", None)
        return
    # the player's map config ("supply_line": [points per turn]) can give a map its own
    gains = _map_setting(m["mission_id"], "supply_line") or SUPPLY_LINE_GAINS.get(int(m["mission_id"]), SUPPLY_LINE_DEFAULT)
    m["line_turns"] = int(m.get("line_turns") or 0) + 1
    if m["line_turns"] <= len(gains):
        _add_score(m, gains[m["line_turns"] - 1])


def _supply_line_held(m, turns):
    """Win type 6: the supply line has stood for expect_defend_line_turn turns. The turn it was
    first joined is kept (defend_line_start_turn); a break starts the count again."""
    if not _supply_line(m):
        m.pop("line_since", None)
        return False
    since = m.setdefault("line_since", int(m["turn"]))
    return int(m["turn"]) - since >= turns


def _take_hostage(m, spot, team):
    """Our echelon takes a spot with a hostage: it carries the hostage from now on (the client
    moves it with the echelon, SpotAction$$MoveHostageDataToSpotAction)."""
    if str(spot.get("hostage_id") or "0") == "0":
        return
    m.setdefault("carrying", {})[str(team)] = {k: spot[k] for k in ("hostage_id", "hostage_hp", "hostage_max_hp")}
    spot.update(hostage_id="0", hostage_hp="0", hostage_max_hp="0")


HOSTAGE_FIELDS = ("hostage_id", "hostage_hp", "hostage_max_hp")


def _swap_hostage(m, src, dst, team, body):
    """An exchange move (move_type 2) onto a hostage standing alone: the hostage steps onto the
    echelon's spot and the echelon onto the hostage's, for no AP; the echelon doesn't carry it
    until it moves onto it again (recorded on map 126: 91184 -> 91186 swapped, then a normal move
    back to 91184 picked the hostage up)."""
    if (src is None or int(body.get("move_type") or 1) != 2 or str(dst.get("hostage_id") or "0") == "0"
            or str(src.get("hostage_id") or "0") != "0" or str(team) in (m.get("carrying") or {})):
        return False
    hostage = {k: dst[k] for k in HOSTAGE_FIELDS}
    dst.update(hostage_id="0", hostage_hp="0", hostage_max_hp="0")
    src.update(hostage)
    if src["team_id"] == team:
        src["team_id"] = "0"
    m["team_pos"][team] = dst["spot_id"]
    dst["team_id"] = team
    _count_move(m, "team", team, moved=False)
    return True


def _hostage_on(m, sid):
    """The hostage on a spot: one standing there alone, or one an echelon of ours there carries."""
    spot = _spot_of(m, sid) or {}
    if str(spot.get("hostage_id") or "0") != "0":
        return {k: spot[k] for k in HOSTAGE_FIELDS}
    team = str(spot.get("team_id") or "0")
    return (m.get("carrying") or {}).get(team) if team != "0" else None


RESCUE_CONDITION = 1404     # mission_win_type_config type: "Rescue N hostages" (arguments N)


def _hostages_needed(mid):
    """How many hostages the map must have rescued to be won, or 0 when rescuing isn't required:
    a required "Rescue N hostages" condition (mission.win_type), else a rescue-only map (mission.type
    7) with expect_hostage_num."""
    row = _missions().get(mid, {})
    for wid in _ids(row.get("win_type")):
        cond = _win_types().get(wid)
        if cond and int(cond["type"]) == RESCUE_CONDITION:
            return max(1, (_ids(cond.get("arguments")) or [1])[0])
    if win_groups(mid) == [[GOAL_HOSTAGE]]:
        return max(1, (_ids(row.get("expect_hostage_num")) or [1])[0])
    return 0


def _hostages_out_of_reach(m):
    """A dead hostage fails the map only once too few are left to meet its rescue condition
    (recorded on map 126, "Rescue 1 hostage" with one hostage: failed at the enemy turn's end). A
    map that doesn't need them, or has spares, goes on; other fail conditions are per map."""
    need = _hostages_needed(m["mission_id"])
    if not need or not m.get("hostages_lost"):
        return False
    total = sum(1 for r in _spots_by_mission().get(m["mission_id"], []) if _hostage_fields(r))
    return total - int(m["hostages_lost"]) < need


def save_hostage(state, body):
    """Mission/saveHostage {spot_id} (RequestSaveHostage): the echelon on spot_id brings its
    hostage out (the client allows it where the echelon could deploy). -> {"type5_score"} read
    unguarded, optional mission_win_result (DeploymentTeamInfoController$$RequestSaveHostageHandle)."""
    m = _mission(state)
    if m is None:
        return None
    team = next((t for t, sid in m["team_pos"].items() if str(sid) == str((body or {}).get("spot_id"))), None)
    carried = m.get("carrying", {}).pop(team, None) if team is not None else None
    if carried is None:
        return {"type5_score": 0}
    m["_saved_hostage_hp"] = int(carried.get("hostage_hp") or 0)
    m["hostages_saved"] = int(m.get("hostages_saved") or 0) + 1
    rule = score_rule(m["mission_id"])
    if rule is not None:
        # field 11 for a hostage brought out whole, a share of it for each HP bar it still has (the
        # user: 2000 a bar for a 5-bar hostage, field 11 10000)
        hp, full = m["_saved_hostage_hp"], int(carried.get("hostage_max_hp") or 0) or m["_saved_hostage_hp"]
        _add_score(m, rule["hostage_hp"] * hp // full if full else 0)
    return _check_win(state, m, {"type5_score": 0})


def _s_rank_misses(m):
    """How many of the S-rank (gold medal) conditions were missed. They are what the client's map
    card lists (DeploymentCampaignExplain$$InitShowGoldTarget): 2403 echelons lost or withdrawn
    <= expect_gun_die_num; 1401 within expect_turn rounds (0: no limit here); then 1404 every hostage
    on the map rescued when it has any, else 1301 at least expect_enemy_die_num kills when that is
    1-98 (99 is no target; recorded: map 126, expect 99, rank S with 5 kills). The live server took
    1404 as no hostage still alive and left alone: the ones enemies killed don't count and the ones
    our units hold do (10199: 3 of 5 killed by enemy-side forces, one saved, one under a Coalition
    echelon: S; 100: one saved, one left on 5343: A, recorded)."""
    row = _missions().get(m["mission_id"], {})
    missed = 0
    if int(m.get("echelons_out") or 0) > int(row.get("expect_gun_die_num") or 0):
        missed += 1
    if int(row.get("expect_turn") or 0) and int(m["turn"]) > int(row["expect_turn"]):
        missed += 1
    need_kills = int(row.get("expect_enemy_die_num") or 0)
    if int(m.get("hostages_total") or 0):
        held = sum(1 for sp in m["spots"] if str(sp.get("hostage_id") or "0") != "0"
                   and (str(sp.get("team_id") or "0") != "0" or str(sp.get("sangvis_team_id") or "0") != "0"))
        held += len(m.get("carrying") or {})
        alive = int(m["hostages_total"]) - int(m.get("hostages_lost") or 0) - held
        missed += int(m.get("hostages_saved") or 0) < alive
    elif 0 < need_kills < 99 and _all_kills(m) < need_kills:
        missed += 1
    return missed


def mission_rank(m):
    """S (gold medal) when every S-rank condition holds; APPROXIMATION: one step lower for each
    missed one (the live server's rule for A-C isn't in the client). Lowest C (2)."""
    return max(2, RANK_S - _s_rank_misses(m))


def silver_medal(m, rank):
    """The silver medal: mission.medal_type_silver's conditions ("|" alternatives of ","-joined
    mission_win_type_config ids; DeploymentUIController$$CheckAllWinType), sent as the win
    result's medal4 and saved as medal4 (the client's Mission.medal2). Without them a story map
    (campaign >= 0; events are negative) gives it with rank S and any other map not at all (the recorded save: every story
    map's medal4 came with rank S, 867 of 920 S-rank event clears had none; recorded run: 11353,
    rank 5, medal4 0). A condition that isn't simulated: rank S decides."""
    row = _missions().get(m["mission_id"], {})
    text = str(row.get("medal_type_silver") or "").strip()
    groups = [_ids(part) for part in text.split("|") if _ids(part)]
    if not groups:
        return rank == RANK_S and int(row.get("campaign") or 0) >= 0
    known = all(int((_win_types().get(c) or {}).get("type") or 0) in WIN_SUPPORTED for g in groups for c in g)
    if not known:
        return rank == RANK_S
    return any(all(_win_condition(m, c) for c in g) for g in groups)


SCORE_GOAL = 5     # mission.type 5: a score map (event_score; the client shows type5_score)


@lru_cache(maxsize=None)
def score_rule(mid):
    """mission.event_score "<mode>|<fields>" as scoring terms, or None for an ordinary map. The live
    server scores (the client only shows type5_score); its result's mica_client_log lists the terms
    as emt<field index>. Read from Reign of Chaos+ (11116, both live runs exact: 49478 and 46941)
    and the maps' own score tips (guide_deployment texts, 11002-11010, 11117, 11118, 11402), and the
    user's lists of the Isomer+ (11116) and City of Nightmares+ (11630) terms:
      0  each enemy we kill scores floor(its enemy_team.effect_ext / field 0) (10, 100; 99999 /
         999999: nothing); 0 = nothing                                              emt0
      3  minus this for each echelon withdrawn from a Command Post or heliport (11116: -1000;
         11603: -5000)
      4  minus this for each repair (11116, 11630: -200)
      14 the same for an enemy an NPC ally kills (11118: 20 against 10, "enemies defeated by allies
         yield only half the points"; 11630: 5, M4A1? scores double); 0 = nothing   emt14
      2  minus this for each echelon withdrawn anywhere else or beaten (11116: -1500; 11603: -8000)  emt2
      5  each building destroyed (11118: 80000 "blowing up an enemy facility"; 11116: an AA tower,
         artillery or a purification tower 10000)                                     emt5
      7  each supply crate a map drops (_crate_plan) used (10508, 10766: 10000; random nodes
         aren't crates, player report). A crate node of the map's own (spot type 5) scores nothing when
         used, and counts as a normal node at the end from then on (the Iso+, PL+ and SC+ guides:
         "Cap for 10k, eat for LMAO"; "used, it turns into a normal node: 500 / 1,000 at the end")
      8  minus this for each HOC withdrawn from a Command Post or heliport (11630: -4000)
      9  minus this for each HOC withdrawn anywhere else or killed (11630: -5000)
      11 a hostage we bring out with all its HP bars, that share of it with fewer (player report: 10000,
         2000 a bar for a 5-bar hostage; 11004's tip, 2000 a bar, is taken as wrong: its hostages
         have 5 bars and 2000 here)
      12 "<spot type>:<points>;...": every spot of ours of that type at the end (11117: 10000 /
         2000 / 5000 for a Command Post / heliport / heavy heliport)              emt12
      13 "<ally team>:<side>:<points>;...": each force of that team still there on that side at the
         end ("every surviving friendly echelon gives 10000")                       emt13
      15 "<special spot>:<points>;...": each of those special spots on the map at the end (11118's
         ranks "on the field")                                                       emt15
      17 each resupply (11118: 20000 "re-supply to gain 20,000"; 11009: 5000)        emt17
      16 each repair on a repair point, on top of field 4 (11630: a Supply/Repair Station's repair
         5000 - 200; 11002-11010: 1000 - 1000, "Repair Points allow you to make repairs that do not
         deduct points")
      18 "<id>:<points>;...": each cast of that map skill (11116: picking up a Goliath 94040905
         20000, the bridge blown with one 94040902 30000; 11630: a Radar converted 10000, the n-th
         Teleporter 5000 + 10000 n, an EMP used 7000, a Data Station's downloads 5000 ... 10000;
         11002: the control panel 10000; 11402: a buff -10000, a reload 5000; 11118: an allied
         squad's support 60000), or a force of that ally team still alive on our side at the end
         (player report: 11005's 6510087 and the like). The ids also name buildings and other rows;
         those don't count.                                                         emt18
      19 "<mission buff>:<points>;...": each of those map buffs on the map at the end (11118)  emt19
        20-23 Mobile Armor (vehicles): minus 20 for one withdrawn from a heavy heliport, 21 for one
         beaten, 22 for one withdrawn anywhere else, 23 for each repair (11946: 5000 / 10000 / 8000
         / 1000; 10766: 8000 / 20000 / 10000 / 5000). Some older maps (10105, 10158) have these four
         values at 22-25 instead and some (10766, 11116) again at 26-29; not read.
    The supply line's points aren't in these fields (11116 and 11630 have the same 20-29 but
      score it differently): see SUPPLY_LINE_GAINS.
    The score never goes below 0 (11630). Fields 1, 6, 10 and 24-29 are unknown."""
    text = str(_missions().get(mid, {}).get("event_score") or "")
    mode, sep, rest = text.partition("|")
    if not sep or not mode.strip().isdigit():
        return None
    f = rest.split(",") + [""] * 30
    num = lambda x: int(x) if x.strip().lstrip("-").isdigit() else 0
    pairs = lambda field: [[int(p) for p in e.split(":")] for e in field.split(";")
                           if e and all(p.strip().lstrip("-").isdigit() for p in e.split(":"))]
    table = lambda field: {e[0]: e[-1] for e in pairs(field) if len(e) >= 2}
    return {"kill_div": num(f[0]), "npc_kill_div": num(f[14]), "echelon_out": num(f[2]),
            "withdraw_deploy": num(f[3]), "repair": num(f[4]), "crate": num(f[7]),
            "ma_withdraw_deploy": num(f[20]), "ma_defeat": num(f[21]), "ma_out": num(f[22]), "ma_repair": num(f[23]),
            "repair_point": num(f[16]),
            "hoc_withdraw_deploy": num(f[8]), "hoc_out": num(f[9]),
            "building": num(f[5]), "hostage_hp": num(f[11]), "spots": table(f[12]),
            "survive": {e[0]: (e[1], e[2]) for e in pairs(f[13]) if len(e) == 3},
            "specials": table(f[15]), "supply": num(f[17]),
            "skills": table(f[18]), "buffs": table(f[19])}


@lru_cache(maxsize=None)
def _death_scored(mid):
    """Teams whose death scores through a building's on-death skill listed in event_score field 18,
    in place of the kill score (Silent Sandtable 11946: the URNC forces 770001-770006 in the
    Central Area, whose deaths cast the Commander's Workstation's 770101-770106, 3000 ... 10500 =
    100% of their CE, whoever kills them; player report: 100% there, not 10% more)."""
    rule = score_rule(mid)
    if rule is None:
        return frozenset()
    out = set()
    for r in _spots_by_mission().get(mid, []):
        for e in str(_buildings().get(int(r["building_id"] or 0), {}).get("missionskill_on_death") or "").split(";"):
            e = e.split(",")
            if len(e) > 2 and e[1].isdigit() and e[2].isdigit() and int(e[2]) in rule["skills"]:
                out.add(int(e[1]))
    return frozenset(out)


def _wear_score(m, spot, before, after):
    """An enemy worn down without dying (a long-range shot that didn't finish it): on a score map
    it earns its kill points' share of the HP it lost; the kill earns the rest (player report)."""
    rule = score_rule(m["mission_id"])
    team = int(spot["enemy_team_id"] or 0)
    if rule is None or team in _death_scored(m["mission_id"]) or after >= before:
        return
    full = _kill_score(rule, team, turn=m["turn"])
    done = m.setdefault("hp_scored", {})
    key = str(spot["enemy_instance_id"])
    had = done.get(key, 0)
    done[key] = min(1.0, had + (before - after))
    _add_score(m, int(full * done[key]) - int(full * had))


def _team_worth(team, turn=1):
    """What an enemy is worth to a score map's kill field: its effect_ext, else its strength worked
    out from its members as it is on that turn (enemy_team.correction_turn: the AW+ / DD+ guides'
    CE tables are these exactly, e.g. 2328 150110 on turn 1, 179540 on turn 2). The ranking maps'
    teams mostly have effect_ext 0 (Scorpion Vortex: "Killing an enemy gives you 10% of its CE", the
    MS guide). The guides' own CE figures can differ from the formula (it has changed over the
    years); the formula is taken as right (player report)."""
    team = int(team or 0)
    ext = int((_enemy_teams().get(team) or {}).get("effect_ext") or 0)
    return ext or (_enemy_team_strength(team, _turn_levels(team, turn)) if team in _enemy_teams() else 0)


def _turn_levels(team, turn):
    """enemy_team.correction_turn "<turn>:<levels added>,...": the levels its members have gained by
    that turn (past the list: the last entry's)."""
    best = 0
    for part in str((_enemy_teams().get(int(team)) or {}).get("correction_turn") or "").split(","):
        t, _, lv = part.partition(":")
        if t.strip().isdigit() and lv.strip().lstrip("-").isdigit() and int(t) <= int(turn or 1):
            best = int(lv)
    return best


def _kill_score(rule, team, by="us", turn=1):
    div = rule["kill_div"] if by == "us" else rule["npc_kill_div"]
    return _team_worth(team, turn) // div if div > 0 else 0


def _rule_points(m, key, value=1):
    """Add a score map's points for one event: key a score_rule entry, a number or (with value) a
    table looked up by id. Returns what was added."""
    rule = score_rule(m["mission_id"])
    if rule is None:
        return 0
    term = rule[key]
    points = term.get(int(value or 0), 0) if isinstance(term, dict) else term * value
    _add_score(m, points)
    return points


def _end_score(m):
    """What a score map adds when it ends: spots by type (12), surviving forces (13), special spots
    (15) and map buffs (19) still on the map."""
    rule = score_rule(m["mission_id"])
    if rule is None:
        return 0
    types = _types_now(m)
    points = sum(rule["spots"].get(types.get(int(sp["spot_id"])), 0) for sp in m["spots"] if sp["belong"] == BELONG_OURS)
    for al in (m.get("allies") or {}).values():
        side, pts = rule["survive"].get(int(al.get("ally_team_id") or 0), (None, 0))
        if pts and str(al.get("belong")) == str(side):
            points += pts
        if str(al.get("belong")) == str(ALLY_FRIENDLY):
            points += rule["skills"].get(int(al.get("ally_team_id") or 0), 0)
    fx = m.get("effects") or {}
    points += sum(rule["specials"].get(int(sp.get("config") or 0), 0) for sp in (fx.get("specials") or {}).values())
    points += sum(rule["buffs"].get(int(b.get("buff_id") or 0), 0) for b in (fx.get("buffs") or {}).values())
    return points


def _add_score(m, points):
    if points:
        m["score"] = max(0, int(m.get("score") or 0) + points)     # never below 0 (11630's rules)


def current_score(state):
    """The running map's score, or the score of the map that just ended (type5_score)."""
    m = state.get("_mission")
    return int((m or {}).get("score") or 0) if m else int(state.get("_last_score") or 0)


def _settle_score(state, m):
    if not m.get("score_settled"):
        m["score_settled"] = True
        _add_score(m, _end_score(m))
    state["_last_score"] = int(m.get("score") or 0)
    if score_rule(m["mission_id"]) is not None:
        rec = _mission_record(state, m["mission_id"])
        rec["type5_score"] = str(max(int(rec.get("type5_score") or 0), state["_last_score"]))


def _team_kills(m):
    """Kills by team id: enemy teams, and hostile allied forces by their ally_team id (recorded:
    1306 "6580109:1" won 11353 when its enemy-side force was beaten, 1306 "6580116:1" 11355)."""
    out = dict(m.get("died_enemy") or {})
    for team, n in (m.get("died_allies") or {}).items():
        out[team] = out.get(team, 0) + n
    return out


KILL_COUNTER = {"us": "enemy_die", "friend": "friend_kills", "npc": "npc_kills"}


def _all_kills(m):
    """Every enemy that died, whoever killed it: the client's allDieEnemyNum (LoadKillNum's
    died_enemy_b), which its kill goals count (DeploymentUIController$$CheckDefeatAllEnemyNumLeast)."""
    return sum(int(m.get(k) or 0) for k in KILL_COUNTER.values())


def _enemy_killed(m, spot, state=None, by="us"):
    """An enemy on this spot died: count it, note a boss, clear the spot. by: who killed it, us
    (enemydie_num, the result's X), a friend's echelon (enemydie_num_killbyfriend, its +Y) or an
    allied force (enemydie_num_killbymyside, never shown). Only our kills count for quests."""
    m[KILL_COUNTER[by]] = int(m.get(KILL_COUNTER[by]) or 0) + 1
    kills = m.setdefault("died_enemy", {})
    kills[str(spot["enemy_team_id"])] = kills.get(str(spot["enemy_team_id"]), 0) + 1
    _kill_spot_trans(m, spot["enemy_team_id"])
    rule = score_rule(m["mission_id"])
    if rule is not None:
        team = int(spot["enemy_team_id"] or 0)
        if team not in _death_scored(m["mission_id"]):
            full = _kill_score(rule, team, by, m["turn"])
            done = m.setdefault("hp_scored", {}).pop(str(spot["enemy_instance_id"]), 0)
            _add_score(m, full - int(full * done))     # the rest, after what wearing it down earned
    if state is not None and by == "us":
        quests.record(state, "enemy_die")
    if int(spot["enemy_team_id"] or 0) in _boss_teams(m["mission_id"]):
        m["boss_killed"] = True
        if state is not None:
            quests.record(state, "win_boss")
    ally_changes(m, ALLY_ON_ENEMY_DEAD, int(spot["enemy_team_id"] or 0))   # the next reply has them
    spot.update(_NO_ENEMY)


# mission.win_type: mission_win_type_config ids, "," joining conditions that must all hold and "|"
# separating alternatives (11374 "9584202,9584203": round 5 reached AND Sana killed; 10295 "1|3":
# every Command Post OR every enemy). 1,019 maps have one; the rest are won by mission.type goals
# (win_groups), and so is a map whose win_type names an id missing from the table or a condition
# type below that isn't simulated (1304, 1310, 2204, 2406 ...),
# since half a set of conditions could never be met or would be met too soon. Types (arguments):
WIN_SPOTS = 1101        # "spot,...": each of those spots ours
WIN_SPOT_TYPE = 1102    # "type": every spot of that SpotType ours (1 Command Posts, 3 heliports,
                        #  201 the radar "defense line" points)
WIN_SPOT_TYPE_N = 1103  # "type:n": at least n spots of that SpotType ours
WIN_KILLS = 1301        # "n": at least n enemies killed
WIN_TEAM_KILLS = (1303, 1306)   # "enemy_team:n,...": each of those enemy teams killed n times
WIN_CLEAR = 1305        # every enemy except the bosses gone ("Destroy all enemies (... not
                        #  including bosses)"); the argument (0, 999) isn't explained: ignored
WIN_GUIDE = 1309        # "ally_team,spot": that allied force on that spot ("Guide M4A1 to ...")
WIN_FORCES_GONE = 1310  # no force left that isn't friendly (the client's CheckDefeatAllyteam; 10351)
WIN_HOSTAGES = 1404     # "n": n hostages rescued
WIN_SUPPLY = 1405       # "n": a supply line held n turns
WIN_ALL_SPOTS = 1106    # "n": at least n spots ours, 9999 every one ("Occupy all nodes", Bound
                        #  Spirit II); belong-100 spots aren't in play
WIN_BUILDINGS_DOWN = 1205  # "building:x,...": each of those buildings destroyed (defender 0)
WIN_BUILDINGS_UP = 1206    # ... each still standing
WIN_BUILDINGS_IDLE = 1208  # ... each not active
WIN_BUILDINGS = 1207    # "building:x,...": each of those buildings active (132 Immemorial II:
                        #  "close all defense gates", 9130801-3); the client never reads x
WIN_BUILDING_TYPE = 1209  # "n:x:building type": at least n buildings of that type active
                        #  (Fractured Cognition I "1:1:14": the Detonator, type 14)
WIN_IN_ROUNDS = 1401    # "n": while it is round n or earlier ("within 4 rounds", Bound Spirit II)
# The client's own checks (DeploymentUIController$$CheckTypeComplete: 1207 CheckBuildLogicOr with
# type 1, 1209 CheckBuildInActiveNumLeast, which counts the active ones and marks the rest as
# targets): a building is active while its defender is above 0 and its working_special_spot
# ("a|b": either; none: always) is on its spot (BuildingAction$$get_CanUseActiveMissionSkill).
# The server decides at the end of our turn (recorded on 132: the third gate closed by
# buildingSkillPerform, the map won at the endTurn after it, win_type_ids ["9130800"]).
WIN_FEW_BATTLES = 2302  # "n": at most n battles fought (90038 "7": "0", won with no battle)
WIN_FEW_WITHDRAWALS = 2403  # "n": at most n echelons lost or withdrawn (dolls, Coalition, vehicles;
                        #  the S-rank card's "without losing or withdrawing any echelon")
WIN_SUPPORTED = ({WIN_SPOTS, WIN_SPOT_TYPE, WIN_SPOT_TYPE_N, WIN_KILLS, WIN_CLEAR, WIN_GUIDE,
                  WIN_HOSTAGES, WIN_SUPPLY, WIN_FEW_BATTLES, WIN_FEW_WITHDRAWALS, WIN_ALL_SPOTS,
                  WIN_BUILDINGS, WIN_BUILDING_TYPE, WIN_IN_ROUNDS, WIN_BUILDINGS_DOWN, WIN_BUILDINGS_UP,
                  WIN_BUILDINGS_IDLE, WIN_FORCES_GONE, 1402, 1406, 1407}
                 | set(WIN_TEAM_KILLS))
# 1402 "n" (round n reached: "Survive to Round 2" is 1402 2, "Survive 6 turns" 1402 7) and 1406 /
# 1407 special-spot counts read as in _lose_condition.


def win_type_groups(mid):
    """mission.win_type as alternatives of required condition ids, or None when the map has no
    win_type or names a condition that isn't simulated (WIN_SUPPORTED)."""
    text = str(_missions().get(mid, {}).get("win_type") or "")
    groups = [g for g in (_ids(part) for part in text.split("|")) if g]
    if not groups:
        return None
    for cid in {c for g in groups for c in g}:
        cond = _win_types().get(cid)
        if cond is None or int(cond["type"]) not in WIN_SUPPORTED:
            return None
        if int(cond["type"]) in (WIN_SPOT_TYPE, WIN_SPOT_TYPE_N) and not _typed_spots(mid, cond["arguments"]):
            return None     # 10817, 10836, 11436: "hold the radar points" with none on the map
        if int(cond["type"]) == 1402 and (_ids(cond["arguments"]) or [0])[0] <= 1:
            return None     # 10605, 10778, 10779: "round 1 reached" would win at once
    return groups


def _typed_spots(mid, args):
    """The spots a 1102 / 1103 condition counts: that SpotType, except the ones that start as
    belong 100 (an allied side's, never ours: "Capture all non-allied Command Posts")."""
    want = str(args or "").partition(":")[0].strip()
    if not want.lstrip("-").isdigit():
        return []
    return [int(r["id"]) for r in _spots_by_mission().get(mid, [])
            if int(r["type"]) == int(want) and int(r["belong"]) != 100]


def _held(m, spot_id):
    """Ours once it changed hands (end of our turn; see _targets_held)."""
    return (_spot_of(m, spot_id) or {}).get("belong") == BELONG_OURS


def _win_condition(m, cid):
    """One win condition holds now."""
    cond = _win_types().get(cid)
    if cond is None:
        return False
    kind, args = int(cond["type"]), str(cond.get("arguments") or "")
    mid = m["mission_id"]
    if kind == WIN_SPOTS:
        spots = _ids(args)
        return bool(spots) and all(_held(m, s) for s in spots)
    if kind in (WIN_SPOT_TYPE, WIN_SPOT_TYPE_N):
        n = args.partition(":")[2]
        spots = _typed_spots(mid, args)
        have = sum(1 for s in spots if _held(m, s))
        if kind == WIN_SPOT_TYPE:
            return bool(spots) and have == len(spots)
        return have >= int(n) if n.strip().isdigit() else False
    if kind == WIN_KILLS:
        return bool(_ids(args)) and _all_kills(m) >= _ids(args)[0]
    if kind in WIN_TEAM_KILLS:
        died = _team_kills(m)
        need = [(t, n) for t, n in _pairs(args) if t.isdigit()]
        return bool(need) and all(int(died.get(t, 0)) >= max(1, n) for t, n in need)
    if kind == WIN_CLEAR:
        bosses = _boss_teams(mid)
        return not any(int(s["enemy_team_id"]) not in bosses for s in _enemy_spots(m))
    if kind == WIN_FORCES_GONE:
        return not any(a["belong"] != ALLY_FRIENDLY for a in (m.get("allies") or {}).values())
    if kind == WIN_GUIDE:
        team, spot = (_ids(args) + [0, 0])[:2]
        return any(int(a["ally_team_id"]) == team and str(a["spot"]) == str(spot)
                   for a in (m.get("allies") or {}).values())
    if kind == WIN_HOSTAGES:
        return int(m.get("hostages_saved") or 0) >= max(1, (_ids(args) or [1])[0])
    if kind == WIN_SUPPLY:
        return _supply_line_held(m, (_ids(args) or [0])[0])
    if kind == WIN_ALL_SPOTS:
        mine = [sp for sp in m["spots"] if str(sp.get("belong")) != "100"]
        have = sum(1 for sp in mine if sp.get("belong") == BELONG_OURS)
        return bool(_ids(args)) and bool(mine) and have >= min(_ids(args)[0], len(mine))
    if kind == WIN_IN_ROUNDS:
        return bool(_ids(args)) and int(m["turn"]) <= _ids(args)[0]
    if kind in (WIN_BUILDINGS_DOWN, WIN_BUILDINGS_UP, WIN_BUILDINGS, WIN_BUILDINGS_IDLE):
        return _buildings_hold(m, kind, args)
    if kind == WIN_BUILDING_TYPE:
        n, _, btype = (args.split(":") + ["0", "0", "0"])[:3]
        have = sum(1 for _, b in m.get("worked") or []
                   if str(_buildings().get(int(b), {}).get("type")) == btype.strip())
        return n.strip().isdigit() and have >= max(1, int(n))
    if kind == WIN_FEW_BATTLES:
        return int(m.get("battles") or 0) <= ((_ids(args) or [0])[0])
    if kind == WIN_FEW_WITHDRAWALS:
        return int(m.get("echelons_out") or 0) <= ((_ids(args) or [0])[0])
    if kind == LOSE_AT_MOST:
        # as a goal, "at most n" holds even if it never appeared (1001-EX's "clear the Paradeus
        # lab", 1406 481811:0, was met live with no 481811 ever placed); as a fail condition it
        # needs to have existed (_lose_condition)
        (config, n), = _pairs(args)[:1] or [("0", 0)]
        return config.isdigit() and _special_count(m, config) <= n
    if kind in (LOSE_ROUND, LOSE_AT_LEAST):
        return _lose_condition(m, cid)
    return False


# Staged wins: mission.win_step (66 maps) names the first mission_win_step_control rows ("a|b":
# several at once). A step's win_step is mission_win_type_config ids ("," all of them, "|" any);
# once they hold, the step and its lock_id steps (itself, and the alternatives running beside it:
# 1063701 / 1063702, 1147301-1147303) end and its next_id steps begin ("a|b" both), or "win<n>"
# wins the map. A step's lose_step ("|" any) fails it. Map replies carry the steps running now as
# mission_win_step_control_ids [id, ...] (MissionAction$$LoadSkillData -> CheckWinStep, which
# compares the list with the last one; recorded as [] on maps without steps). The map's own
# win_type / mission.type goals don't decide a staged map, except one whose chain names a condition
# that isn't simulated (10664: 2302 "no battles engaged"), which keeps them.
def _steps_now(m):
    """The steps running now as the live server sends them: ids as text (["1083802"], recorded)."""
    return [str(x) for x in m["win_steps"]]


def _with_steps(m, reply):
    """A reply that ends no step still lists the running ones on a staged map (moves into a
    battle: Ship of Theseus II, 1001-EX, recorded)."""
    if m.get("win_steps") is not None:
        reply["mission_win_step_control_ids"] = _steps_now(m)
    return reply


def _step_rows():
    return _table_by_id("mission_win_step_control")


@lru_cache(maxsize=None)
def _table_by_id(name):
    return {str(r["id"]): r for r in stc.table(name)}


def _step_ids(text):
    return [x.strip() for x in re.split(r"[|,]", str(text or "")) if x.strip().isdigit() and int(x)]


@lru_cache(maxsize=None)
def win_step_start(mid):
    """The first steps of a staged map, or None (no win_step, or a chain that can't be simulated)."""
    start = _step_ids(_missions().get(mid, {}).get("win_step"))
    if not start:
        return None
    rows, todo, seen = _step_rows(), list(start), set()
    while todo:
        sid = todo.pop()
        if sid in seen:
            continue
        seen.add(sid)
        row = rows.get(sid)
        if row is None:
            return None
        for cid in _step_ids(row["win_step"]) + _step_ids(row["lose_step"]):
            cond = _win_types().get(int(cid))
            if cond is None or int(cond["type"]) not in WIN_SUPPORTED:
                return None
        todo += [x for x in _step_ids(row["next_id"])]
    return start


def _expr_holds(m, text, all_of=True):
    """Condition ids: "," all of them (all_of) and "|" alternatives."""
    groups = [_step_ids(g) for g in str(text or "").split("|")]
    groups = [g for g in groups if g]
    if not all_of:
        groups = [[c] for g in groups for c in g]
    return any(all(_win_condition(m, int(c)) for c in g) for g in groups)


def _advance_steps(m):
    """Finish every running step whose conditions hold (a finished step can start one that already
    holds). Returns (the winning step's conditions or None, the lose_step condition that holds or
    None)."""
    steps = m.get("win_steps")
    if steps is None:
        return None, None
    if m.get("steps_won"):
        return m["steps_won"], None     # (the loss check, which runs first, may have got there)
    rows = _step_rows()
    for _ in range(32):
        done = next((sid for sid in steps if _expr_holds(m, rows[sid]["win_step"])), None)
        if done is None:
            break
        row = rows[done]
        _trigger(m, "step", done)
        ended = set(_step_ids(row["lock_id"])) | {done}
        at = min(i for i, x in enumerate(steps) if x in ended)
        steps[:] = [x for x in steps if x not in ended]
        nxt = [x.strip() for x in str(row["next_id"] or "").split("|") if x.strip()]
        win = next((x for x in nxt if x.startswith("win")), None)
        if win:
            m["win_ending"] = win
            m["steps_won"] = [int(c) for c in _step_ids(row["win_step"])]
            return m["steps_won"], None
        # the next steps take the finished ones' place (10637, recorded: 1063701 / 1063702 / 1063706,
        # then 1063705 / 1063706 once 1063702 was done)
        steps[at:at] = [x for x in nxt if x.isdigit() and x not in steps]
    for sid in steps:
        lost = next((int(c) for c in _step_ids(rows[sid]["lose_step"]) if _win_condition(m, int(c))), None)
        if lost:
            return None, lost
    return None, None


def _won_by(m):
    """The goals met now: the satisfied win_type group (its ids), [] for a map won by its
    mission.type goals, None while it isn't won."""
    if m.get("win_steps") is not None:
        return _advance_steps(m)[0]
    groups = win_type_groups(m["mission_id"])
    if groups is not None and not any(SCORE_GOAL in g for g in win_groups(m["mission_id"])):
        # (a score map ends on its turn limit, _check_loss, whatever its win_type says)
        held = {cid: _win_condition(m, cid) for cid in {c for g in groups for c in g}}
        return next((g for g in groups if all(held[c] for c in g)), None)
    if any(all(_goal_met(m, g) for g in group) for group in win_groups(m["mission_id"])):
        return []
    return None


def _check_win(state, m, reply):
    """Once the mission's goals are met (_won_by): settle the mission into the save and add
    mission_win_result to the reply. Stepping onto the enemy HQ wins at once."""
    _ally_flush(m, reply)
    won = _won_by(m)
    _flush_triggers(m, reply)
    if won is None and m.get("win_steps") is not None:
        # as they stand now, in every reply that can end a step, battle results too (1001-EX:
        # battleFinish carried them, recorded); the winning reply keeps the ones before (10637)
        reply["mission_win_step_control_ids"] = _steps_now(m)
    if won is None:
        return reply
    return _win(state, m, reply, won)


# Auto-repair: a unit that leaves a map (withdrawn, or the map won, lost, ended, restarted or
# dropped) and isn't heavily damaged is whole again; a heavily damaged one stays as it is for the
# repair bay (player report). The client does this itself: Gun.get_life gives maxLife for a doll or
# Coalition unit (SangvisGun : Gun) whose status isn't "mission" unless Gun.get_isDamaged
# (life < game_config damaged_life_percentage (10) % of maxLife), and shows the "repaired
# automatically" banner (ShowFixGunTip, from DeploymentController$$RequestWithDrawHandle and the
# result screen's CheckDamageGun). No reply key: the save only has to agree with it.
def _auto_repair(state, kind, units):
    share = float(_game_config("damaged_life_percentage", "10") or 10) / 100
    for u in units:
        life, full = int(u.get("life") or 0), workshop.max_life(state, kind, u)
        if 0 < life < full and life >= share * full:
            workshop.set_life(state, kind, u, full)


def _repair_team(state, team):
    _auto_repair(state, "gun", _team_guns(state, team))


def _repair_sangvis(state, team):
    if _own_sangvis(team):
        _auto_repair(state, "sangvis", _team_units(state, "sangvis", team)[1])


# Vehicles and HOCs: Vehicle / Squad.get_isDamaged is life == 0, and the withdraw handler gives a
# withdrawn one its maxLife unless so (Vehicle.set_life; a HOC's life reads as maxLife once it's
# off the map). So one hurt on the map (gas, a closing gate) is whole again when it retreats or
# the map ends; one an enemy killed stays at 0 for the repair bay (player report).
def _repair_vehicle(state, vid):
    veh = workshop._find(state.get("vehicle_with_user_info"), vid)
    if veh is not None and int(veh.get("life") or 0) > 0:
        veh["life"] = str(workshop.max_life(state, "vehicle", veh))


def _repair_hoc(state, rec):
    if rec is not None and int(rec.get("life") or 0) > 0:
        rec["life"] = str(workshop.max_life(state, "squad", rec))


def _end_heal(state, m):
    if not m:
        return
    for team in set(m.get("team_pos") or {}) | set(m.get("left_teams") or []):
        _repair_team(state, team)
    for team in set(m.get("sangvis_pos") or {}):
        _repair_sangvis(state, team)
    for vid in set(m.get("vehicle_pos") or {}):      # (withdrawn ones were repaired then)
        _repair_vehicle(state, vid)
    for inst in list(m.get("squads") or {}):
        _repair_hoc(state, _hoc_record(state, m, inst))


def _win(state, m, reply, won=None):
    """Settle a won mission into the save and add mission_win_result to the reply. won: the
    win_type conditions met (default: the whole win_type, as for a skipped map)."""
    row = _missions().get(m["mission_id"], {})
    user_exp = commander_exp(state, m["mission_id"], clear=True)
    _add(state["user_info"], "experience", user_exp)
    rec = _mission_record(state, m["mission_id"])
    first = int(rec["win_counter"] or 0) == 0
    rec["win_counter"] = str(int(rec["win_counter"]) + 1)
    rec["counter"] = str(max(int(rec["counter"]), int(rec["win_counter"])))
    rank = mission_rank(m)
    quests.record(state, "mission")
    quests.record(state, "mission_win")
    from . import gray_zone
    gray_zone.on_mission_win(state, m["mission_id"])          # a Gray Zone cell's mission
    rec["bestrank"] = str(max(int(rec["bestrank"] or 0), rank))
    rec["medal1"] = "1"
    silver = silver_medal(m, rank)
    if silver:
        rec["medal4"] = "1"
    keys, items = _drop_keys(state, m["mission_id"])
    opened = _open_next(state, row)
    opened.update(_open_by_keys(state, keys, items))
    _close_missions(state, row)
    opened.update(_mapped_win(state, row))
    _settle_score(state, m)
    # rank and user_exp are read as strings too
    # recorded on 126 (win_type "9130200"): ["9130200"], the conditions that were met
    ids = _ids(row.get("win_type")) if won is None else won
    reply["mission_win_result"] = {"win_type_ids": [str(w) for w in ids],
                                   "rank": str(rank), "medal4": silver, "user_exp": str(user_exp),
                                   "mission_info": _result_counts(m)}
    if score_rule(m["mission_id"]) is not None:
        reply["mission_win_result"]["type5_score"] = int(m.get("score") or 0)
    if opened:
        reply["mission_win_result"]["open"] = opened
    if keys:
        reply["mission_win_result"]["mission_keys"] = keys
    if items:
        reply["mission_win_result"]["mission_item"] = items
    if first:
        reply["mission_win_result"].update(_first_clear_reward(state, m["mission_id"]))
    doll = _clear_drop(state, m["mission_id"])      # any rank (recorded: A-rank 0-2 clears dropped one)
    if doll:
        reply["mission_win_result"].setdefault("reward_gun", []).append(doll)
    _end_heal(state, m)
    state.pop("_mission", None)
    return reply


# mission.lose_type: mission_win_type_config ids, "," joining conditions that must all hold and
# "|" separating alternatives (map 11269: "7 rounds done, 1402 8" AND "battle score <= 20, 1406").
# The client only lists them; the server decides. Types used (arguments):
LOSE_KILLS = 1306       # "enemy_team:n,...": each of those enemy teams killed n times
LOSE_ROUND = 1402       # "N": round N is entered
LOSE_AT_MOST = 1406     # "special_spot:n": at most n of that special spot on the map (once it existed)
LOSE_AT_LEAST = 1407    # "special_spot:n": at least n of it ("Agent J retreats" places a marker)
LOSE_UNITS = 1409       # "unit codes:n": n or fewer units of those codes on the map (UNIT_GUN's
                        #  list: 1 echelons, 8 Coalition, 10 vehicles, 7 HOCs, 2 friends, 3/301-304
                        #  friendly allied forces)


def lose_groups(mid):
    text = str(_missions().get(mid, {}).get("lose_type") or "")
    return [g for g in (_ids(part) for part in text.split("|")) if g]


def _pairs(text):
    out = []
    for part in str(text or "").split(","):
        key, _, n = part.partition(":")
        out.append((key.strip(), int(n) if n.strip().lstrip("-").isdigit() else 0))
    return out


def _special_count(m, config):
    return sum(1 for sp in _effects(m)["specials"].values() if int(sp["config"]) == int(config))


def _units_of(m, codes):
    n = 0
    if UNIT_GUN in codes:
        n += len(m.get("team_pos") or {})
    if UNIT_SANGVIS in codes:
        n += sum(1 for t in (m.get("sangvis_pos") or {}) if _own_sangvis(t))
    if UNIT_VEHICLE in codes:
        n += len(m.get("vehicle_pos") or {})
    if UNIT_SQUAD in codes:
        n += sum(len(s.get("squad_instance_ids") or []) for s in m["spots"])
    if UNIT_FRIEND in codes:
        n += len(m.get("friends") or {})
    n += sum(1 for a in (m.get("allies") or {}).values() if _ally_codes(a) & codes)
    return n


def _lose_condition(m, cid):
    """One lose condition holds now. Unknown types never do."""
    cond = _win_types().get(cid)
    if cond is None:
        return False
    kind, args = int(cond["type"]), str(cond.get("arguments") or "")
    if kind == LOSE_KILLS:
        died = _team_kills(m)
        return all(int(died.get(team, 0)) >= max(1, n) for team, n in _pairs(args) if team.isdigit())
    if kind == LOSE_ROUND:
        return bool(_ids(args)) and int(m["turn"]) >= _ids(args)[0]
    if kind in (LOSE_AT_MOST, LOSE_AT_LEAST):
        (config, n), = _pairs(args)[:1] or [("0", 0)]
        if not config.isdigit():
            return False
        have = _special_count(m, config)
        if kind == LOSE_AT_LEAST:
            return have >= n
        return int(config) in (m.get("specials_seen") or []) and have <= n
    if kind == LOSE_UNITS:
        codes, _, n = args.rpartition(":")
        codes = set(_ids(codes))
        have = _units_of(m, codes)
        armed = m.setdefault("lose_armed", [])
        if have > int(n or 0) and cid not in armed:
            armed.append(cid)       # only once there were more of them than that
        return cid in armed and have <= int(n or 0)
    return False


def _lost_by_condition(m):
    # every condition is evaluated, so 1409's "there were more of them" mark is kept up to date
    groups = lose_groups(m["mission_id"])
    held = {cid: _lose_condition(m, cid) for cid in {c for g in groups for c in g}}
    return next((g for g in groups if all(held[c] for c in g)), [])   # the group that holds


def _check_loss(state, m, reply, turn_start=False):
    """The mission fails once no echelon is left on the map, the enemy holds every HQ
    we started with, the turn limit is passed, a required hostage can't be rescued any more, or
    one of its lose_type alternatives holds. A running step's lose_step is judged only at the start
    of our turn (1001-EX, recorded: 482010 came in startEnemyTurn, and the map was lost by 1081905
    "482010:1" at the next startTurn, not in the battles or endEnemyTurn between)."""
    _ally_flush(m, reply)
    no_hq = m.get("had_hq") and not any(s["belong"] == BELONG_OURS for s in _hq_spots(m))
    limit = int(_missions().get(m["mission_id"], {}).get("turn_limit") or 0)
    # a map played only with forces the player deployed (mission_ally_spots) isn't lost for having
    # none left: its lose_type decides (recorded on 11341: the force beaten at line 102, the map
    # failed at 105 by 580001, Anna's marker gone)
    units = (m["team_pos"] or m.get("sangvis_pos") or m.get("vehicle_pos") or _myside_units(m)
             or not m.get("had_units", True))
    by_condition = _lost_by_condition(m)
    if not by_condition and m.get("win_steps") is not None:
        lost = _advance_steps(m)[1]
        by_condition = [lost] if lost and turn_start else []
        if not m.get("steps_won"):
            # the steps after this action (11355), lost battles too; the step that wins the map
            # stays listed (No More Omens: the winning startTurn still sent ["1058102"], recorded)
            reply["mission_win_step_control_ids"] = _steps_now(m)
    if (units and not no_hq and not (limit and int(m["turn"]) > limit) and not _hostages_out_of_reach(m)
            and not by_condition):
        return reply
    if limit and int(m["turn"]) > limit and units and not no_hq and not by_condition and any(SCORE_GOAL in g for g in win_groups(m["mission_id"])):
        return _check_win(state, m, reply)       # a score map's last turn is its finish
    _settle_score(state, m)
    # recorded (11341, 11374): win_type_ids = the lose_type conditions that failed the map
    reply["mission_lose_result"] = dict(_result_counts(m), user_exp=0,
                                        win_type_ids=[str(c) for c in by_condition or []], **_score_result(m))
    quests.record(state, "mission_lose")
    _end_heal(state, m)
    state.pop("_mission", None)
    return reply


def _move_enemy(src, dst):
    for k in _ENEMY_FIELDS:
        dst[k] = src[k]
    src.update(_NO_ENEMY)


def _visible_nbrs(m, nbrs):
    """A spot's neighbours for a surround capture, without the map's NEVER_REVEAL nodes: an
    exception for those, not a rule for hidden nodes (player report: Vortex of Secrets' hidden X1 92518
    must not keep 92413 from being surrounded)."""
    never = NEVER_REVEAL.get(int(m["mission_id"]), ())
    return [n for n in nbrs if n not in never]


def _enemy_surround(m):
    """The start of the enemy turn, before anyone moves: every spot not the enemy's whose every
    neighbour is the enemy's falls to it, HQs and spots with units on them too (recorded in all 14
    change_belong2 replies of the 11-04 / 11-05 / 11-06 logs; 105 Torrent Breaker was lost by its
    surrounded HQ, an echelon standing on it)."""
    belong = {int(s["spot_id"]): s["belong"] for s in m["spots"]}
    changes = {}
    for sid, nbrs in _neighbours(m["mission_id"]).items():
        nbrs = _visible_nbrs(m, nbrs)
        if (belong.get(sid, BELONG_ENEMY) == BELONG_ENEMY or str(belong.get(sid)) in HIDDEN_BELONGS
                or not nbrs or any(belong.get(n) != BELONG_ENEMY for n in nbrs)):
            continue
        _spot_of(m, sid)["belong"] = BELONG_ENEMY
        changes[str(sid)] = int(BELONG_ENEMY)
    return changes


def _our_surround(m):
    """The start of our turn: every spot not ours whose every neighbour is ours falls to us, HQs
    and heliports too, the enemy-side rule (_enemy_surround) mirrored. Recorded in every log: endTurn
    takes only the spots our units stand on, and the surrounded ones come in startTurn's
    change_belong (10581: 72618 / 72619 / 72623 / 72626, then the enemy HQ 72637, which won the map;
    10199 10813, 10838 74552 / 74567, 129 91333). APPROXIMATION: a spot an enemy stands on stays
    (never recorded either way)."""
    belong = {int(s["spot_id"]): s["belong"] for s in m["spots"]}
    held = {int(s["spot_id"]) for s in _enemy_spots(m)} | {int(a["spot"]) for a in (m.get("allies") or {}).values()
                                                            if a["belong"] != ALLY_FRIENDLY}
    changes = {}
    for sid, nbrs in _neighbours(m["mission_id"]).items():
        nbrs = _visible_nbrs(m, nbrs)
        if (belong.get(sid, BELONG_OURS) == BELONG_OURS or sid in held or not nbrs
                or str(belong.get(sid)) in HIDDEN_BELONGS or any(belong.get(n) != BELONG_OURS for n in nbrs)):
            continue
        _spot_of(m, sid)["belong"] = BELONG_OURS
        changes[str(sid)] = int(BELONG_OURS)
        _capture_score(m, sid, BELONG_OURS)
    return changes


def _capture_turn_end(m, side, surround=True):
    """End-of-turn captures for one side: spots its units stand on, then spots (not HQs)
    with nobody on them whose every neighbour is already that side's."""
    changes = {}
    # ours: our echelons, HOCs and friendly allied forces (recorded on map 126: the spots the
    # allied force ended our turn on became ours, and a spot with our HOC on it stayed ours)
    friendly = {int(a["spot"]) for a in (m.get("allies") or {}).values() if a["belong"] == ALLY_FRIENDLY}
    squads = {int(q["spot"]) for q in (m.get("squads") or {}).values() if q.get("spot")}
    # theirs: enemies and enemy-side forces (10199: the spots its forces stood on, recorded)
    hostile = {int(a["spot"]) for a in (m.get("allies") or {}).values() if a["belong"] == ALLY_ENEMY_SIDE}
    standing = (_echelon_spots(m) | friendly | squads) if side == BELONG_OURS else {int(s["spot_id"]) for s in _enemy_spots(m)} | hostile
    for sid in standing:
        spot = _spot_of(m, sid)
        if spot is not None and spot["belong"] != side and not _hidden(spot):
            # a hidden node isn't taken by who stands on it: that would reveal it (Mistbuster's
            # walled-in heliport prespawns showed Area 2's heliports at the end of turn 1, player report)
            spot["belong"] = side
            changes[spot["spot_id"]] = int(side)
            _capture_score(m, sid, side)
    if not surround:
        return changes
    belong = {int(s["spot_id"]): s["belong"] for s in m["spots"]}
    occupied = _echelon_spots(m) | squads | _ally_spots(m) | {int(s["spot_id"]) for s in _enemy_spots(m)}
    types = _spot_types(m["mission_id"])
    for sid, nbrs in _neighbours(m["mission_id"]).items():
        if (sid in occupied or belong.get(sid, side) == side or types.get(sid) == SPOT_HQ
                or str(belong.get(sid)) in HIDDEN_BELONGS or not nbrs or any(belong.get(n) != side for n in nbrs)):
            continue
        _spot_of(m, sid)["belong"] = side
        changes[str(sid)] = int(side)
        _capture_score(m, sid, side)
    return changes


def _hidden(spot):
    return spot is not None and str(spot.get("belong")) in HIDDEN_BELONGS


# Maps whose hidden nodes are walled off until revealed: an enemy on one doesn't move and none step
# onto one (Scorpion Vortex: "H2, H3 and H6 prespawns are on Alert, but they cannot move out of
# those nodes until you reveal the Heliports"; the R patrols likewise, the MS guide; Mirror Stage+'s
# hidden areas, whose heliports get their prespawns at the start, data/spawn_tables.json).
HIDDEN_WALLED = {10674, 10521, 11549, 10675}
# Maps where stepping next to a hidden node reveals it (Scorpion Vortex 10674, the MS guide and the
# user): a hidden heliport alone, as the enemy's (it spawns from then on: "stepping on R4 unlocks
# the hidden Red Heliport H4"), any other hidden node with every hidden non-heliport node joined to
# it, as neutral ("step on either L4, L20 or L23. This unlocks all the R nodes"). ASSUMED: neutral
# (3) for the revealed nodes, as the visible side's are.
REVEAL_ADJACENT = {10674}
# Maps where each hidden node next to where a unit steps (or lands, through a hole) is revealed on
# its own, as neutral: Vortex of Secrets 10520, whose three layers start mostly hidden (belong 99)
# though the DR guide counts every node but X1 and X31 (92519, 92518: linked to nothing) and has the
# NPC on X27 "appear if you step on X26". The 8 hidden heavy heliports (92601-92608) link only to
# each other and come another way. Vortex of Secrets+ 11497 likewise (its three layers, the DR+
# notes: areas open as units reach them; layer 3's heliports spawn once revealed). ASSUMED: neutral
# (3), as the visible ones are, but heliports the enemy's (they spawn, or are there to be taken).
REVEAL_STEP = {10520, 11497}
# REVEAL_STEP maps whose hidden nodes open by area: stepping on a key node opens its area. Vortex of
# Secrets (player report, 2026-11-14, against the old map's footage): X35 92509, where the lift from Y41
# lands, opens layer 0's east side above it but the NPC's 92421, which stepping on 92420 shows (it
# is next to it); stepping onto the X33 rock's node 92417 opens the nodes around it. The northern
# areas of each layer (layer 0 between 92441 and the 92599 rock, layer 1's around 92484 above the
# gate, layer 2) open only when an echelon drops in through a hole: their landing nodes open them,
# and no step next to one of their nodes shows it. Not the hidden heavy heliports (the Fairy of the
# Lake's) nor X1 / X31 (92518 / 92519), which the guide doesn't count.
REVEAL_AREAS = {10520: (
    # (key nodes, the area, opened only by those keys)
    ({92509}, {92418, 92419, 92420, 92424, 92425, 92426, 92427, 92428, 92429, 92430, 92431}, False),
    ({92417}, {92412, 92413, 92414, 92415, 92416}, False),
    ({92441}, {92432, 92433, 92434, 92435, 92437, 92438, 92439, 92440, 92441}, True),        # from 92486
    ({92456}, {92455, 92456}, True),                                                          # from 92416
    ({92483, 92484}, {92474, 92475, 92476, 92477, 92479, 92480, 92481, 92482, 92483, 92484, 92485,
                      92486, 92523}, True),                                                    # from 92432 / 92508
    # layer 2 opens whole from any of its landing nodes (player report: its nodes around 92499 didn't
    # show after landing on 92488; the two parts meet at 92495 - 92499)
    ({92488, 92506, 92522}, {92487, 92488, 92489, 92490, 92491, 92492, 92493, 92494, 92495, 92496, 92497,
                             92498, 92499, 92500, 92502, 92503, 92504, 92505, 92506, 92507, 92508, 92522}, True),
    # layer 1's Fairy of the Lake (player report): stepping on the rubble node 92461 opens 92613, 92589
    # and her 92598 (belong 100 in the stc, not 99). 92609-92612 lie under 92613 (same place, other
    # curves) and stay hidden.
    ({92461}, {92613, 92589, 92598}, True),
)}


# Hidden nodes no step ever shows: Vortex of Secrets' X1 92518 past 92413 and X31 92519 (player report:
# "92518 is still visible when it should not"; the DR guide: "X1, X31 ... are hidden nodes"). A hidden
# node doesn't stop a surround capture next to it (_visible_nbrs; only these, player report).
NEVER_REVEAL = {10520: frozenset({92518, 92519})}


def _area_reveal(mid, sid):
    """REVEAL_AREAS: (the hidden nodes stepping on sid opens, the nodes only their keys open)."""
    opened, locked = set(), set()
    for keys, area, only_keys in REVEAL_AREAS.get(mid, ()):
        if sid in keys:
            opened |= area
        if only_keys:
            locked |= area
    return opened, locked - opened


# Areas that open on a schedule (Mirror Stage+ 11549 and Mistbuster 10675, one layout; the Mirror
# Stage+ sheet): A2, layer 2's part with the HQ; A3, layer 2's other part; A4, layer 3. They start
# out of play (belong 100, a few 99) but for what the stc already shows.
#   T2 start: A2's heavy heliports open as ours. Stepping next to an open heavy heliport reveals the
#     rest of A2 ("moving to the adjacent normal node will unlock the rest of A2"); A3's heavy
#     heliport (ours) and the nodes next to it open with it ("A3 unlocks at the same time").
#   Stepping next to A3's heavy heliport reveals the rest of A3.
#   T3 start: A4's top heavy heliports open; stepping next to one reveals A4 but its centre (the
#     stc's belong-99 node there); T6 start: the centre opens.
# Revealed heliports are the enemy's (the spawning ones and A3's "enemy Helipads that do not spawn"),
# heavy heliports ours, the rest neutral. NOT DONE: the areas closing (A1 at T4, A2/A3 at T5).
# Mistbuster (the MS guide, Hole 2) runs later: A2's heavy heliports B1/B6 at T4 (stepping on B2/B7
# reveals A2), A3's C1/C2 at T7 (on its own turn, not with A2; stepping past C1 reveals A3, the
# C and Y regions together here), A4's D1 D2 D4 D5 at T8 (stepping on D4/D5 reveals all of A4).
# Each: turn A2 opens, turn A3's entrance opens (0: with A2's reveal), turn A4 opens, turn A4's
# centre opens (0: with A4's reveal).
AREA_MAPS = {11549: (2, 0, 3, 6), 10675: (4, 7, 8, 0)}
# Areas closing at the start of a turn: every node but the area's heavy heliports goes out of play
# (belong 100). Units there stay deployed but can't move (they can retreat). Mistbuster (the MS
# guide: "On T4, Area 1 closes up", "On Turn 7, Area 2 closes up", "On T8, Area 3 closes"; player report:
# all of layer 1 but the two heliports at the top goes on T4); Mirror Stage+ (A1 at T4, A2 and A3 at
# T5). ASSUMED: sent as change_belong 100, the way hidden nodes start. The HQ (in A2) closes with
# its area, so these maps aren't lost by losing it.
# Maps whose A3 far side (the Y region) opens only when a unit steps on its gate node (Mistbuster's
# C13, 93673: the guide, "When you step on C13, the Y region is revealed", and player report).
SPLIT_A3 = {10675: 93673}
AREA_CLOSE = {10675: {4: ("a1",), 7: ("a2",), 8: ("a3",)}, 11549: {4: ("a1",), 5: ("a2", "a3")}}
# Nodes that open on a later turn of their own and stay out of their area's reveal: Mistbuster's
# D11-D13 (93690 / 93688 / 93689) on turn 10, with ID43 on D11 and Commander and Machlian on D12 /
# D13 (the MS guide: "On T10, the nodes D11, D12 and D13 will appear"; player report).
LATE_SPOTS = {10675: {10: (93688, 93689, 93690)}}


@lru_cache(maxsize=None)
def _areas(mid):
    """{"a2", "a3", "a4", "heavy2", "heavy3", "heavy4", "centre"}: spot id sets (see AREA_MAPS)."""
    rows = {int(r["id"]): r for r in _spots_by_mission().get(mid, [])}
    nbrs = _neighbours(mid)
    comps, seen = [], set()
    for i in sorted(rows):
        if i in seen:
            continue
        todo, comp = [i], set()
        while todo:
            k = todo.pop()
            if k in comp:
                continue
            comp.add(k)
            todo += [x for x in nbrs.get(k, ()) if x in rows]
        seen |= comp
        comps.append(comp)
    layer = lambda c: str(rows[next(iter(c))]["map_num"])
    kind = lambda c, t: {x for x in c if str(rows[x]["type"]) == t}
    a2 = next(c for c in comps if layer(c) == "1" and kind(c, "1"))
    a3 = max((c for c in comps if layer(c) == "1" and c is not a2), key=len)
    a4 = max((c for c in comps if layer(c) == "2"), key=len)
    heavy4 = kind(a4, "7")
    top = max(int(rows[x]["coordinator_y"]) for x in heavy4)
    a1 = set(rows) - a2 - a3 - a4
    # A3's far side past its gate node (SPLIT_A3): the A3 nodes reached from the gate without
    # going back through it toward the heavy heliport
    gate, far = SPLIT_A3.get(mid), set()
    if gate in a3:
        rest, todo = set(), list(kind(a3, "7"))
        while todo:
            k = todo.pop()
            if k in rest or k == gate or k not in a3:
                continue
            rest.add(k)
            todo += list(nbrs.get(k, ()))
        far = a3 - rest - {gate}
    return {"a1": frozenset(a1), "far3": frozenset(far), "gate3": gate, "a2": frozenset(a2), "a3": frozenset(a3), "a4": frozenset(a4),
            "heavy2": frozenset(kind(a2, "7")), "heavy3": frozenset(kind(a3, "7")),
            "heavy4": frozenset(x for x in heavy4 if top - int(rows[x]["coordinator_y"]) < 300),
            "centre": frozenset(x for x in a4 if str(rows[x]["belong"]) == "99")}


def _open_spots(m, spots, side=None, heavy=BELONG_OURS):
    """Hidden spots among these come into play: heavy heliports ours (or `heavy`), heliports and
    nodes an enemy stands on the enemy's (player report: Mistbuster's C2 and C11 prespawns on red
    nodes), the rest neutral (or all `side`). Returns {spot: belong}."""
    types, changes = _spot_types(int(m["mission_id"])), {}
    for x in sorted(spots):
        spot = _spot_of(m, x)
        if not _hidden(spot):
            continue
        t = types.get(x)
        b = side or (heavy if t == SPOT_HEAVY else BELONG_ENEMY if t == SPOT_HELIPORT or int(spot["enemy_team_id"] or 0)
                     else BELONG_NEUTRAL)
        spot["belong"] = b
        changes[str(x)] = int(b)
    return changes


def _area_turn(m):
    """AREA_MAPS at startTurn: what opens on this turn."""
    plan = AREA_MAPS.get(int(m["mission_id"]))
    if plan is None:
        return {}
    a, turn, nbrs, out = _areas(int(m["mission_id"])), int(m["turn"]), _neighbours(int(m["mission_id"])), {}
    if turn == plan[0]:
        out.update(_open_spots(m, a["heavy2"]))
    if turn == plan[1]:
        out.update(_open_spots(m, set(a["heavy3"]) | {n for h in a["heavy3"] for n in nbrs.get(h, ())}))
    if turn == plan[2]:
        out.update(_open_spots(m, a["heavy4"]))
    if turn == plan[3]:
        out.update(_open_spots(m, a["centre"], BELONG_NEUTRAL))
    out.update(_open_spots(m, LATE_SPOTS.get(int(m["mission_id"]), {}).get(turn, ())))
    types = _spot_types(int(m["mission_id"]))
    hqs = {x for x, t in types.items() if t == SPOT_HQ}
    kept = hqs | {n for h in hqs for n in nbrs.get(h, ()) if types.get(n) == SPOT_HELIPORT}
    # a node our unit stands on stays too: the client lists a layer to switch to only while it has
    # a node of ours not out of play (DeploymentUIController$$CheckLayer: belong 1 or a friend
    # team, skipping belong 100), rebuilt from scratch after a restart, so the echelon left in a
    # closed area dropped out of reach (player report: "cannot switch the display back to old layer")
    kept |= _echelon_spots(m)
    for name in AREA_CLOSE.get(int(m["mission_id"]), {}).get(turn, ()):
        for x in sorted(a[name]):
            spot = _spot_of(m, x)
            if spot is None or types.get(x) == SPOT_HEAVY or x in kept or str(spot["belong"]) == BELONG_GONE:
                continue
            spot["belong"] = BELONG_GONE
            out[str(x)] = int(BELONG_GONE)
        m.setdefault("closed_areas", []).append(name)
    return out


def _area_step(m, sid):
    """AREA_MAPS: a unit stepped onto sid; the areas that reveals."""
    mid = int(m["mission_id"])
    if mid not in AREA_MAPS or sid is None:
        return {}
    plan = AREA_MAPS[mid]
    a, nbrs, changes = _areas(mid), _neighbours(mid), {}
    near = set(nbrs.get(int(sid), ())) | {int(sid)}
    is_open = lambda x: not _hidden(_spot_of(m, x))
    closed = set(m.get("closed_areas") or ())
    far = a["far3"]
    if "a3" not in closed and far and int(sid) == a["gate3"]:
        changes.update(_open_spots(m, far))     # SPLIT_A3: C13 opens the Y region
    # a closed area doesn't open again
    if "a2" not in closed and any(x in a["heavy2"] and is_open(x) for x in near) and any(_hidden(_spot_of(m, x)) for x in a["a2"]):
        changes.update(_open_spots(m, a["a2"]))
        if not plan[1]:
            door = set(a["heavy3"]) | {n for h in a["heavy3"] for n in nbrs.get(h, ())}
            changes.update(_open_spots(m, door))
    if "a3" not in closed and any(x in a["heavy3"] and is_open(x) for x in near) and int(sid) not in a["heavy3"]:
        changes.update(_open_spots(m, a["a3"] - far))
    if "a4" not in closed and any(x in a["heavy4"] and is_open(x) for x in near) and int(sid) not in a["heavy4"]:
        late = {x for spots in LATE_SPOTS.get(mid, {}).values() for x in spots}
        # its other heavy heliports come in neutral (player report: Mistbuster's Z5 93720 isn't ours)
        changes.update(_open_spots(m, a["a4"] - (a["centre"] if plan[3] else frozenset()) - late, heavy=BELONG_NEUTRAL))
    return changes


def _queue_belong(m, changes):
    """Belong changes made where the reply isn't read for them (a building skill's): sent with the
    next reply that is (_flush_belong: teamMove, startTurn, endEnemyTurn)."""
    if changes:
        m.setdefault("belong_queue", {}).update({str(k): int(v) for k, v in changes.items()})


def _queue_reveal(m, changes):
    """Hidden spots opened: queued like _queue_belong, and also sent as spot_trans {"belong"}.
    change_belong only sets the spot's data; the client redraws a spot (a hidden one shown) from
    spot_trans: DeploymentController$$PlaySpotTransChange calls UpdateColor when the drawn belong
    differs from the data ("归属直接变化"). Recorded on 11497: a building skill revealing four night
    spots answered spot_trans {"600295": {"belong": "1"}, ...} and no change_belong."""
    if changes:
        _queue_belong(m, changes)
        m.setdefault("reveal_queue", {}).update({str(k): int(v) for k, v in changes.items()})


def _flush_belong(m, reply):
    queued = m.pop("belong_queue", None)
    shown = m.pop("reveal_queue", None)
    if queued and isinstance(reply, dict):
        have = reply.get("change_belong")
        reply["change_belong"] = dict(have if isinstance(have, dict) else {}, **queued)
    if shown and isinstance(reply, dict):
        trans = reply.get("spot_trans") if isinstance(reply.get("spot_trans"), dict) else {}
        for sid, b in shown.items():
            trans.setdefault(sid, {})["belong"] = str(b)
        reply["spot_trans"] = trans
        # A building on a node that was hidden at the start isn't drawn when the node is shown:
        # the client gave it to no spot controller then (the node had none drawn). spot_trans_buiding
        # (the client's spelling; MissionAction$$AnalysicsSpotTransInfo -> ReadBuildingAction ->
        # BuildingAction$$SetData -> CheckController -> DeploymentSpotController$$CheckBuild) hands
        # it to the now-drawn node, which draws it and offers its skills (player report, Vortex of
        # Secrets: 92425's Goliath couldn't be picked up and revealed rubble showed no rock).
        # ASSUMED: live never sent it in the recorded runs.
        # A JSON string, not an object: with the trans flag ReadBuildingAction takes the field's
        # string, strips "\\" and parses it (an object threw there and the client dropped the rest
        # of the move: a recorded desync stepping onto 92461 and 92509).
        built = {sid: dict(m["buildings"][sid]) for sid in shown if sid in (m.get("buildings") or {})}
        # An enemy that came while its node was hidden isn't drawn by the reveal either; the map's
        # spots (spot_act_info: AnalysicsSpotTransInfo -> CheckSpotAction / CheckEnemyDataTemp) are,
        # as live sends them in every teamMove (recorded on 11497, 2026-11-13: 32 of 32). Only when a
        # shown node holds an enemy (player report: Vortex of Secrets' Dinergate on 92415 was there once
        # the triangle opened on turn 2, in a live video; ours stayed undrawn and was fought unseen).
        # With them the enemies' enemy_instance_info, as startMission sends it (player report: layer 3's Pyxis
        # on 92500 was in spot_act_info alone and didn't show)
        found = {str((_spot_of(m, int(sid)) or {}).get("enemy_instance_id") or "0") for sid in shown} - {"0"}
        if found and "spot_act_info" not in reply:
            reply["spot_act_info"] = _with_friends(m, m["spots"])
            _enemy_instances(m, reply, {x["enemy_instance_id"] for x in _enemy_spots(m)})
        if built:
            have = reply.get("spot_trans_buiding")
            have = json.loads(have) if isinstance(have, str) and have else {}
            reply["spot_trans_buiding"] = json.dumps(dict(have, **built), separators=(",", ":"))
    return reply


def _uncover_near(m, sid):
    """REVEAL_ADJACENT: what stepping onto sid reveals, as {spot: belong} (applied)."""
    mid = int(m["mission_id"])
    if mid in REVEAL_STEP and sid is not None:
        changes = {}
        types = _spot_types(mid)
        opened, locked = _area_reveal(mid, int(sid))
        locked |= NEVER_REVEAL.get(mid, frozenset())
        for n in sorted(({int(sid)} | set(_neighbours(mid).get(int(sid), ())) | opened) - locked):
            spot = _spot_of(m, n)
            if spot is not None and (str(spot.get("belong")) == "99" or (n in opened and str(spot.get("belong")) == "100")):
                spot["belong"] = BELONG_ENEMY if types.get(n) == SPOT_HELIPORT else BELONG_NEUTRAL
                changes[str(n)] = int(spot["belong"])
        return changes
    if mid not in REVEAL_ADJACENT or sid is None:
        return {}
    types, nbrs, changes = _spot_types(mid), _neighbours(mid), {}
    heli = lambda x: types.get(x) in DEPLOY_TYPES
    for n in sorted(nbrs.get(int(sid), ())):
        if not _hidden(_spot_of(m, n)):
            continue
        region, todo, side = {n}, [n], BELONG_ENEMY if heli(n) else BELONG_NEUTRAL
        while todo and not heli(n):
            for x in nbrs.get(todo.pop(), ()):
                if x not in region and not heli(x) and _hidden(_spot_of(m, x)):
                    region.add(x)
                    todo.append(x)
        for x in region:
            _spot_of(m, x)["belong"] = side
            changes[str(x)] = int(side)
    return changes


def _capture_score(m, sid, side):
    """Spots score when a score map ends (_end_score), not when taken (recorded on 11116)."""


# teamMove's person_type (RequestTeamMove$$.ctor, by the moving controller): 1 doll echelon,
# 2 Coalition echelon, 3 allied force, 4 vehicle (recorded: a Coalition echelon moves with
# person_type 2). HOCs move with Mission/squadMove and "squad_id" instead.
PERSON_SANGVIS, PERSON_ALLY, PERSON_VEHICLE = 2, 3, 4


def _myside_move(state, m, body):
    """teamMove person_type 3: a force the player deployed (mission_ally_spots) moves, person_id its
    instance. Recorded (11353): it walks like an echelon, fights what it moves onto (battleFinish
    for its spot, its own dolls in "guns"), and sets off the ally rules for the spot it reaches."""
    iid = str(body.get("person_id") or 0)
    a = (m.get("allies") or {}).get(iid)
    dst = _spot_of(m, body.get("to_spot_id"))
    reply = {"ap": int(m.get("ap") or 0), "type5_score": 0}
    if a is None or dst is None:
        return reply
    if _swap_mixed(state, m, _spot_of(m, a["spot"]), dst, "ally", iid, body):
        return _reveal(state, m, _effect_keys(m, reply))
    # 1 AP a move, like an echelon, and none under a free-move buff (recorded on 11946, the
    # Commander: 5 -> 4 -> 3 ..., then three free moves with Accelerate 770027)
    m["ap"] = max(0, int(m.get("ap") or 0) - _move_cost(m, "ally", iid))
    _count_move(m, "ally", iid, at=dst["spot_id"])
    reply["ap"] = m["ap"]
    src = _spot_of(m, a["spot"])
    if src is not None:
        src["ally_instance_ids"] = [i for i in src.get("ally_instance_ids") or [] if str(i) != iid]
    dst["ally_instance_ids"] = list(dst.get("ally_instance_ids") or []) + [int(iid)]
    a["spot"] = dst["spot_id"]
    _ally_entered(state, m, iid, a)
    for cond in (ALLY_ON_SPOT, ALLY_ON_ENTER):
        _merge_ally(reply, ally_changes(m, cond, dst["spot_id"], reply))
    return _reveal(state, m, _check_win(state, m, _effect_keys(m, reply)))


def _myside_units(m):
    return [k for k, a in (m.get("allies") or {}).items() if a.get("myside")]


def team_move(state, body):
    """Mission/teamMove (every kind of unit), then what the step reveals (REVEAL_ADJACENT) and the
    belong changes waiting to be sent (_queue_belong): the reply's change_belong is read
    (MissionAction$$AnalysicsSpotChange from RequestMoveTeamHandle)."""
    reply = _team_move(state, body)
    m = state.get("_mission")
    if not isinstance(reply, dict) or m is None:
        return reply
    _queue_reveal(m, _uncover_near(m, (body or {}).get("to_spot_id")))
    _queue_reveal(m, _area_step(m, (body or {}).get("to_spot_id")))
    for hop in reply.get("spot_teleport_result") or []:
        _queue_reveal(m, _uncover_near(m, hop.get("to_spot_id")))      # where a hole lands (REVEAL_STEP)
    return _flush_belong(m, reply)


def _team_move(state, body):
    body = body or {}
    kind = int(body.get("person_type") or 0)
    if kind == PERSON_SANGVIS:
        return sangvis_move(state, body)
    if "squad_id" in body:
        return squad_move(state, body)
    if kind == PERSON_VEHICLE:
        return vehicle_move(state, body)
    m = _mission(state)
    if kind == PERSON_ALLY:
        return _myside_move(state, m, body) if m is not None else None
    dst = _spot_of(m, body.get("to_spot_id")) if m is not None else None
    if dst is None:
        return None
    src = _spot_of(m, body.get("from_spot_id"))
    team = str(body.get("person_id") or 0)
    if (_swap(m, src, dst, "team", team) or _swap_hostage(m, src, dst, team, body)
            or _swap_mixed(state, m, src, dst, "team", team, body)):
        return _reveal(state, m, _effect_keys(m, {"ap": int(m.get("ap") or 0), "type5_score": 0}))
    cost = _move_cost(m, "team", team)
    _count_move(m, "team", team, at=dst["spot_id"])
    m["ap"] = max(0, int(m.get("ap") or 0) - cost)
    reply = {"ap": m["ap"], "type5_score": 0}
    if src is not None and src["team_id"] == team:
        src["team_id"] = "0"
    m["team_pos"][team] = dst["spot_id"]
    dst["team_id"] = team
    if _hostile_here(m, dst):
        # the client fights here now and reports the outcome with Mission/battleFinish
        # (on a night map the enemy may only now come into sight: night_enemy shows it here)
        m["pending_battle"] = {"team": team, "spot": dst["spot_id"], "from": src["spot_id"] if src else ""}
        # rules on the spot fire on the move, before the fight (105: onto 9278, recorded)
        for cond in (ALLY_ON_SPOT, ALLY_ON_ENTER):
            _merge_ally(reply, ally_changes(m, cond, dst["spot_id"], reply))
        return _reveal(state, m, _with_steps(m, reply))
    reply = _hazard_reply(state, m, dst["spot_id"], ("team", team), reply)
    reply = _random_event(state, m, dst, team, reply)
    if m.get("pending_battle"):
        return _reveal(state, m, _with_steps(m, reply))         # an ambush: the client fights it now
    out = _portal_exit(m, dst, came_from=(src or {}).get("spot_id"))
    if out is not None:
        reply["spot_teleport_result"] = [{"from_spot_id": int(dst["spot_id"]), "to_spot_id": str(out["spot_id"]),
                                          "target_type": TELEPORT_ECHELON, "target_id": team}]
        dst["team_id"], out["team_id"] = "0", team
        m["team_pos"][team] = out["spot_id"]
        dst = out
    _occupy_building(state, m, dst["spot_id"], reply)
    _take_hostage(m, dst, team)
    for cond in (ALLY_ON_SPOT, ALLY_ON_ENTER):
        _merge_ally(reply, ally_changes(m, cond, dst["spot_id"], reply))
    # the spot changes hands at the end of the turn, not now
    return _reveal(state, m, _check_win(state, m, reply))


# Random nodes (spot.random_get 1, sent as if_random): the first echelon onto one gets an event,
# answered in the teamMove reply and shown by DeploymentController$$AddPlayRendomPerformance, which
# reads (RandomEvent enum) "mp" / "ammo" / "mre" / "part" / "coin1".."coin3" (data) / "core": a
# gain; "loseammo" / "losemre": a loss (there is no lose key for manpower, parts, cores or data);
# "gun_id" + "gun_with_user_id": a doll; "enemy_team_id": an ambush, the client puts that enemy
# team on the spot and fights it (then Mission/battleFinish); "item" (an item package) and
# "if_runaway" aren't used here. Values are strings. Recorded on map 40, spot 593 (seven runs):
# +40 ammo, mre or manpower, -80 ammo or rations.
# APPROXIMATION: the odds and the data / core amounts (RANDOM_EVENTS) are from player reports
# ("a small amount of resources, data, sometimes a core, very rarely a doll, sometimes an ambush,
# can deduct resources"), not recorded.
RANDOM_GAIN, RANDOM_LOSS = 40, 80
RANDOM_EVENTS = (("gain", 45), ("loss", 20), ("data", 15), ("core", 6), ("ambush", 10), ("gun", 4))


def _random_odds(mid):
    """RANDOM_EVENTS, with a map's own odds where map_settings or a mod gives them (random_nodes
    {"gain": 45, ...}: kinds left out keep their default, all 0 falls back to the default)."""
    own = _map_setting(mid, "random_nodes") or {}
    odds = [(k, max(0, int(own.get(k, w) or 0))) for k, w in RANDOM_EVENTS]
    return odds if any(w for _, w in odds) else list(RANDOM_EVENTS)


def _random_event(state, m, dst, team, reply, rng=random):
    if str(dst.get("if_random") or "0") == "0":
        return reply
    dst["if_random"] = "0"                                  # once a map
    m.setdefault("randoms_used", []).append(dst["spot_id"])
    odds = _random_odds(m["mission_id"])
    kind = rng.choices([k for k, _ in odds], weights=[w for _, w in odds])[0]
    user = state["user_info"]
    if kind == "ambush":
        pool = _map_enemy_pool(m["mission_id"])
        if pool:
            enemy = rng.choices(list(pool), weights=list(pool.values()))[0]
            inst = int(m.get("next_instance") or 0) or 1 + max([int(s["enemy_instance_id"]) for s in m["spots"]] + [0])
            m["next_instance"] = inst + 1
            row = _enemy_teams()[enemy]
            dst.update({"enemy_team_id": str(enemy), "enemy_instance_id": str(inst), "boss_hp": str(_boss_hp(enemy)),
                        "enemy_hp_percent": "1", "enemy_birth_turn": str(m["turn"]),
                        "enemy_ai": int(row.get("ai") or 0),
                        "enemy_ai_para": local_spots(m["mission_id"], str(row.get("ai_content") or "0"))})
            m["pending_battle"] = {"team": team, "spot": dst["spot_id"], "from": ""}
            reply["enemy_team_id"] = str(enemy)
            return reply
        kind = "gain"
    if kind == "gun":
        pool = _gun_pool((_auto_missions().get(int(m["mission_id"])) or {}).get("gun_1_pool"))
        pool = [g for g in pool if g] or [g for t in _map_enemy_pool(m["mission_id"]) for g in _drop_pool(t) if g]
        if pool:
            reply.update(_give_gun(state, rng.choice(pool)))
            return reply
        kind = "gain"
    if kind == "loss":
        res = rng.choice(("ammo", "mre"))
        lost = min(RANDOM_LOSS, int(user.get(res) or 0))
        _add(user, res, -lost)
        reply["lose" + res] = str(RANDOM_LOSS)
    elif kind == "data":
        coin = rng.choices(("coin1", "coin2", "coin3"), weights=(6, 3, 1))[0]
        _add(user, coin, 1)
        reply[coin] = "1"
    elif kind == "core":
        _add(user, "core", 1)
        reply["core"] = "1"
    else:
        res = rng.choice(("mp", "ammo", "mre", "part"))
        _add(user, res, RANDOM_GAIN)
        reply[res] = str(RANDOM_GAIN)
    return reply


def _swap(m, src, dst, kind, uid):
    """Our unit moves onto another of ours (teamMove move_type 2): they trade places, which costs no
    AP (recorded: a Coalition echelon onto a doll echelon). Returns whether it was a swap."""
    if src is None:
        return False
    here = [("team", dst["team_id"]), ("sangvis", dst["sangvis_team_id"])]
    other = next(((k, u) for k, u in here if str(u) != "0" and (k, str(u)) != (kind, str(uid))), None)
    if other is None:
        return False
    field = {"team": "team_id", "sangvis": "sangvis_team_id"}
    pos = {"team": m["team_pos"], "sangvis": m.setdefault("sangvis_pos", {})}
    okind, ouid = other
    if str(src[field[okind]]) not in ("0", str(uid)) and okind != kind:
        return False                                # its own spot is taken by one of its kind
    src[field[kind]] = "0"
    dst[field[okind]] = "0"
    src[field[okind]], pos[okind][str(ouid)] = str(ouid), src["spot_id"]
    dst[field[kind]], pos[kind][str(uid)] = str(uid), dst["spot_id"]
    _count_move(m, kind, uid, moved=False)
    _count_move(m, okind, ouid, moved=False)
    return True


MOVE_SWAP = 2      # teamMove move_type: onto a unit of ours, the two trade places


def _units_on(m, spot):
    """Our movable units on a spot: echelons, Coalition echelons, our deployed allied forces, HOCs."""
    out = [("team", str(spot["team_id"])), ("sangvis", str(spot.get("sangvis_team_id") or "0"))]
    out = [(k, u) for k, u in out if u != "0"]
    out += [("ally", str(i)) for i in spot.get("ally_instance_ids") or []
            if ((m.get("allies") or {}).get(str(i)) or {}).get("myside")]
    out += [("squad", str(i)) for i in spot.get("squad_instance_ids") or []]
    return out


def _put_unit(m, spot, kind, uid, here):
    """Take a unit off a spot (here False) or put it there (True), keeping its position record."""
    sid = spot["spot_id"]
    if kind in ("team", "sangvis"):
        field = "team_id" if kind == "team" else "sangvis_team_id"
        if here:
            spot[field] = str(uid)
            (m["team_pos"] if kind == "team" else m.setdefault("sangvis_pos", {}))[str(uid)] = sid
        elif str(spot.get(field)) == str(uid):
            spot[field] = "0"
    else:
        field = "ally_instance_ids" if kind == "ally" else "squad_instance_ids"
        ids = [i for i in spot.get(field) or [] if str(i) != str(uid)]
        spot[field] = ids + [int(uid)] if here else ids
        rec = (m.get("allies") if kind == "ally" else m.get("squads") or {}).get(str(uid))
        if here and rec is not None:
            rec["spot"] = sid


def _swap_mixed(state, m, src, dst, kind, uid, body):
    """teamMove move_type 2 between different kinds of our units (recorded on Vortex of Secrets+
    11497, 2026-11-12: the deployed Support Squad traded places with a HOC, then echelon 1, then
    another HOC, and echelon 1 with a HOC and with the Squad). No AP; each side counts a shift
    (person_shift_count), not a move (the Squad's free-move buff 6510003 stayed unused through
    three swaps). Both set off the special spots where they land, as a move onto them would
    (recorded: echelon 1, swapped onto 600104 by the Squad, got 600104's 6630006/6630023 buffs
    again, from 6630003). Returns whether it was one."""
    if src is None or int((body or {}).get("move_type") or 0) != MOVE_SWAP:
        return False
    other = next(((k, u) for k, u in _units_on(m, dst) if (k, u) != (kind, str(uid))), None)
    if other is None:
        return False
    _put_unit(m, src, kind, uid, False)
    _put_unit(m, dst, other[0], other[1], False)
    _put_unit(m, src, other[0], other[1], True)
    _put_unit(m, dst, kind, uid, True)
    _count_move(m, kind, uid, moved=False)
    _count_move(m, other[0], other[1], moved=False)
    for (k, u), spot in (((kind, str(uid)), dst), (other, src)):
        codes = _ally_codes(m["allies"][u]) if k == "ally" else None
        hurts = _entered(state, m, spot["spot_id"], k, u, codes)[0]
        if hurts:
            m["effects"].setdefault("pending_hurts", []).extend(hurts)
    return True


def battle_exp(mid):
    """A doll's exp for a won battle before its bonuses: mission.exp_parameter * 10."""
    return int(_missions().get(mid, {}).get("exp_parameter") or 0) * 10


# Battle exp, as recorded on map 126 (exp_parameter 58, expect_gun_level 120):
#   a doll   exp_parameter * 10 * links multiplier (1 link 1.0, each more +0.5: 5 links -> 1740 at
#            level 115) * 1.2 as leader * 1.3 as MVP * the level penalty * outfit battle_gun_exp_up
#   commander  exp_parameter a battle, twice that for the clear, * outfit battle_commander_exp_up
#            (recorded 63 and 127 with a +10% set)
# Outfit sets (commander_class.skill_id, function_skill_config): a set's skill level is the number
# of its pieces worn (commander_with_user_info.dressed) minus one, up to max_level; each level adds
# the skill's arguments %.
# Recorded on 0-2 (exp_parameter 49, expect 102) and 5-6 (40, expect 75): base * links, * 1.2 for
# the leader, * 1.3 for the MVP, * 2 for an oathed doll with a neural upgrade, then 20% less for
# every full 10 levels past expect_gun_level (5-6, lv 115, 5 links: 1200 * 0.2 = 239; 0-2, the
# oathed lv 118 leader and MVP: 1470 * 1.2 * 1.3 * 2 * 0.8 = 3668). Values are truncated.
# The 10-exp floor once the penalty reaches 100% is recorded (10199, base 300, expected level 40:
# both dolls not at their cap got 10, and the fairy 10).
# The echelon's fairy gets FAIRY_EXP_SHARE of what its dolls earned, counted before the oath bonus
# and before the level cap cut it (the Weather System at level 10; recorded on every won battle of
# the 11-04..07 logs: 05, 3668 / 2 + 1470 + 980 + 1225 + 490 = 5999 -> 1199; 06, dolls at their cap
# counted in full: 1530 * 4 + 2386 -> 1701).
LEADER_EXP, MVP_EXP, OATH_MOD_EXP, FAIRY_EXP_SHARE = 1.2, 1.3, 2, 0.2


def _expect_level(mid):
    row = _auto_missions().get(int(mid)) or {}
    return int(row.get("expect_gun_level") or _missions().get(mid, {}).get("recommend_gun_level") or 0)


def _level_penalty(level, expect):
    over = int(level) - int(expect or 0)
    if not expect or over <= 0:
        return 1.0
    return max(0.0, 1 - 0.2 * (over // 10))


@lru_cache(maxsize=1)
def _outfit_skills():
    skills = {int(r["id"]): r for r in stc.table("function_skill_config")}
    sets = {str(r["id"]): skills.get(int(r.get("skill_id") or 0)) for r in stc.table("commander_class")}
    pieces = {int(r["id"]): str(r["uniform_class"]) for r in stc.table("commander_uniform")}
    return sets, pieces


def outfit_bonus(state, name):
    """Percent from the worn outfit sets' skills named `name` (function_skill_config.function_skill)."""
    sets, pieces = _outfit_skills()
    dressed = str((state.get("commander_with_user_info") or {}).get("dressed") or "")
    worn = {}
    for part in dressed.split(","):
        uid = part.split(":")[0].strip()
        if uid.isdigit() and int(uid) in pieces:
            worn[pieces[int(uid)]] = worn.get(pieces[int(uid)], 0) + 1
    total = 0
    for cls, n in worn.items():
        skill = sets.get(cls)
        if skill and skill["function_skill"] == name:
            total += int(skill.get("arguments") or 0) * min(int(skill.get("max_level") or 1), n - 1)
    return max(0, total)


def _oath_mod(gun):
    return bool(int(gun.get("soul_bond") or 0) and int(gun.get("if_modification") or 0))


def _fairy_battle_exp(state, team, earned):
    """The echelon's fairy takes its share of its dolls' battle exp; returns what it got (0: none)."""
    gained = int(earned * FAIRY_EXP_SHARE)
    fairies = state.get("fairy_with_user_info") or []
    f = next((f for f in (fairies.values() if isinstance(fairies, dict) else fairies)
              if str(f.get("team_id")) == str(team)), None)
    if f is None or gained <= 0:
        return 0
    f["fairy_exp"] = str(int(f.get("fairy_exp") or 0) + gained)
    f["fairy_lv"] = str(max(1, workshop._level_for(int(f["fairy_exp"]), stc.catch("fairy_exp_info"), "id", 100)))
    return gained


def doll_battle_exp(state, mid, gun, mvp=None):
    exp = battle_exp(mid) * (1 + 0.5 * (max(1, int(gun.get("number") or 1)) - 1))
    if str(gun.get("location")) == "1":
        exp *= LEADER_EXP
    if mvp is not None and str(mvp) == str(gun.get("id")):
        exp *= MVP_EXP
    exp = int(exp)      # truncated here (0-2: int(1470 * 1.2 * 1.3) * 2 * 0.8 = 3668, not 3669)
    if _oath_mod(gun):
        exp *= OATH_MOD_EXP
    penalty = _level_penalty(gun.get("gun_level") or 1, _expect_level(mid))
    exp *= 1 + outfit_bonus(state, "battle_gun_exp_up") / 100
    return int(exp * penalty) if penalty > 0 else 10


@lru_cache(maxsize=1)
def _sangvis_levels():
    """Coalition level -> total exp to reach it (sangvis_exp: exp from each level to the next)."""
    total, out = 0, {}
    for r in sorted(stc.table("sangvis_exp"), key=lambda r: int(r["lv"])):
        out[int(r["lv"])] = total
        total += int(r["exp"] or 0)
    return out


def _sangvis_exp(state, mid, team, mvp, won):
    """sangvis_battle_exp [{sangvis_with_user_id, exp}] for the Coalition echelon's units: as a doll's
    (sangvis_unit_exp) but without the dummy-link multiplier (player report). Recorded: "0" for units at
    level 100, the base for one below the expected level (126 580, 105 510, 100 500), the base * the
    level penalty past it (10637: 320 * 0.6 = 192)."""
    rec = next((t for t in state.get("sangvis_team_with_user_info") or [] if str(t.get("team_id")) == str(team)), {})
    info = rec.get("info") or {}
    levels = _sangvis_levels()
    top = max(levels) if levels else 100
    out = []
    for slot in (info.values() if isinstance(info, dict) else info):
        unit = workshop._find(state.get("sangvis_with_user_info"), slot.get("sangvis_with_user_id") or 0)
        if unit is None:
            continue
        gained = 0
        if won:
            exp = int(sangvis_unit_exp(state, mid, unit, mvp, leader=str(slot_key(info, slot)) == "1")
                      * _exp_rate(state.get("_mission") or {}, "sangvis", team))
            have = int(unit.get("sangvis_exp") or 0)
            cap = levels.get(top, have)
            gained = max(0, min(exp, cap - have))
            unit["sangvis_exp"] = str(have + gained)
            unit["sangvis_level"] = str(max([lv for lv, need in levels.items() if have + gained >= need] or [1]))
        out.append({"sangvis_with_user_id": str(unit["id"]), "exp": str(gained)})
    return out


def slot_key(info, slot):
    return next((k for k, v in info.items() if v is slot), None) if isinstance(info, dict) else None


CREW_DOLL, CREW_SANGVIS, CREW_SQUAD = "1", "2", "3"     # vehicle crew "slot:type-id"
# INFERRED from the recorded regular vehicle battle on 128 (2026-11-09): the vehicle and both HOCs of
# its crew at their caps, free_exp 960 = the vehicle's 600 (the map's battle exp) + 2 x 180, so a HOC
# crew member takes 30 % of it. A Coalition unit at its cap adds nothing (as in Coalition battles).
HOC_CREW_SHARE = 0.3


def _crew_exp(state, m, vid, won, mvp=None):
    """crew_exp [{crew_type, xx_with_user_id, after_exp}] for a vehicle's crew (record "crew"
    "1001:1-<gun>,1002:3-<squad>,..."): its dolls and Coalition units gain exp as in a regular
    battle, never as leader, also for a long-range shot (player report; recorded 2026-11-09 on 128: SV98,
    level 115 of 5 links, +1800 for the battle = 600 x 3 x the level penalty, with the vehicle's
    exp_buff). HOCs gain HOC_CREW_SHARE of the map's battle exp * the level penalty, up to squad_exp's
    cap (15000000), the rest going to free exp like a doll's. Returns (entries, exp past the dolls' and
    HOCs' caps)."""
    veh = workshop._find(state.get("vehicle_with_user_info"), vid)
    rate, mid, out, over = _exp_rate(m, "vehicle", vid), m["mission_id"], [], 0
    levels = _sangvis_levels()
    for part in str((veh or {}).get("crew") or "").split(","):
        kind, _, uid = part.partition(":")[2].partition("-")
        if not uid.strip():
            continue
        if kind == CREW_DOLL:
            g = workshop._find(state.get("gun_with_user_info"), uid)
            if g is None:
                continue
            exp = int(doll_battle_exp(state, mid, dict(g, location="0"), mvp) * rate) if won else 0
            over += add_gun_exp(g, exp) if exp else 0
            out.append({"crew_type": kind, "xx_with_user_id": str(g["id"]), "after_exp": int(g["gun_exp"])})
        elif kind == CREW_SANGVIS:
            u = workshop._find(state.get("sangvis_with_user_info"), uid)
            if u is None:
                continue
            have = int(u.get("sangvis_exp") or 0)
            if won:
                cap = levels.get(max(levels), have) if levels else have
                have += max(0, min(int(sangvis_unit_exp(state, mid, u, mvp) * rate), cap - have))
                u["sangvis_exp"] = str(have)
                u["sangvis_level"] = str(max([lv for lv, need in levels.items() if have >= need] or [1]))
            out.append({"crew_type": kind, "xx_with_user_id": str(u["id"]), "after_exp": str(have)})
        elif kind == CREW_SQUAD:
            q = workshop._find(state.get("squad_with_user_info"), uid)
            if q is None:
                continue
            if won:
                gain = int(battle_exp(mid) * HOC_CREW_SHARE * rate
                           * _level_penalty(q.get("squad_level") or 1, _expect_level(mid)))
                cap = max(e for _, e in squads._exp_table())
                have = int(q.get("squad_exp") or 0)
                q["squad_exp"] = str(min(cap, have + gain))
                over += max(0, have + gain - cap)       # past the cap: free exp, as for dolls (player report)
                q["squad_level"] = str(squads._level(int(q["squad_exp"])))
            out.append({"crew_type": kind, "xx_with_user_id": str(q["id"]), "after_exp": str(q.get("squad_exp") or 0)})
    return out, over


def _game_pct(key, default=100):
    """A game_config percentage ("100" -> 1.0)."""
    try:
        return float(str(squads._config().get(key) or default).split(",")[0]) / 100
    except ValueError:
        return default / 100


def _vehicle_exp(state, m, vid, won):
    """The vehicle's own exp for a battle or long-range shot: the map's battle exp (player report; game_config
    vehicle_battle_exp_M1 100 %) * its exp_buff, up to vehicle_max_exp (or what it already has, if more:
    the 11-09 log's vehicle stood at 210100 over the listed 209500). What the cap leaves goes to free
    exp, as for dolls (player report; with HOC_CREW_SHARE this gives the recorded 960 on 128).
    Returns (vehicle_battle_exp, overflow)."""
    veh = workshop._find(state.get("vehicle_with_user_info"), vid)
    if veh is None:
        return {"vehicle_with_user_id": str(vid), "after_exp": 0}, 0
    have = int(veh.get("exp") or 0)
    gain = int(battle_exp(m["mission_id"]) * _game_pct("vehicle_battle_exp_M1") * _exp_rate(m, "vehicle", vid)) if won else 0
    cap = max(have, int(squads._config().get("vehicle_max_exp") or have + gain))
    veh["exp"] = str(min(cap, have + gain))
    return {"vehicle_with_user_id": str(veh["id"]), "after_exp": int(veh["exp"])}, have + gain - int(veh["exp"])


def sangvis_unit_exp(state, mid, unit, mvp=None, leader=False):
    """A Coalition unit's exp for a won battle: base * LEADER_EXP for the echelon's first slot
    (INFERRED: the leader, info "1") * MVP_EXP for the MVP, truncated, * the outfit bonus, * the
    level penalty; 10 once the penalty takes it all (as for dolls)."""
    exp = battle_exp(mid) * (LEADER_EXP if leader else 1)
    if mvp is not None and str(mvp) == str(unit.get("id")):
        exp *= MVP_EXP
    exp = int(exp) * (1 + outfit_bonus(state, "battle_gun_exp_up") / 100)
    penalty = _level_penalty(unit.get("sangvis_level") or 1, _expect_level(mid))
    return int(exp * penalty) if penalty > 0 else 10


def commander_exp(state, mid, clear=False):
    base = int(_missions().get(mid, {}).get("exp_parameter") or 0) * (2 if clear else 1)
    return int(base * (1 + outfit_bonus(state, "battle_commander_exp_up") / 100))


def _echelon_out(m, spot=None, lost=False, vehicle=False):
    """An echelon of ours left the map (win type 2403, the S-rank limit). Score maps: a withdrawal
    from a Command Post or heliport costs field 3, one from anywhere else or a lost battle field 2
    (recorded on 11116: -1500; player report's City of Nightmares+ and Mirror Stage+ rules: "off
    helipad or fight retreat"). A mod map can price a lost battle on its own ("defeat_points")."""
    m["echelons_out"] = int(m.get("echelons_out") or 0) + 1
    rule = score_rule(m["mission_id"])
    if rule is None:
        return
    on_deploy = not lost and spot is not None and _spot_types(m["mission_id"]).get(int(spot["spot_id"])) in DEPLOY_TYPES
    if vehicle:         # Mobile Armor: fields 20-22
        beaten = MA_DEFEAT.get(int(m["mission_id"]), rule["ma_defeat"])
        _add_score(m, -(beaten if lost else rule["ma_withdraw_deploy"] if on_deploy else rule["ma_out"]))
        return
    if lost:
        own = _map_setting(m["mission_id"], "defeat_points")     # a mod map's own cost of a lost echelon
        _add_score(m, -(int(own) if own is not None else rule["echelon_out"]))
        return
    _add_score(m, -(rule["withdraw_deploy"] if on_deploy else rule["echelon_out"]))


DEPLOY_TYPES = (1, 3, 7)        # Command Post, heliport, heavy heliport
# An MA beaten costs field 21, except where recorded live runs say otherwise (Hurricane Rescue+:
# 10000, its field 21 is 20000)
MA_DEFEAT = {10766: 10000}


def _remove_team(m, team):
    if str(team) in m.get("team_pos", {}):
        m.setdefault("left_teams", [])
        if str(team) not in m["left_teams"]:
            m["left_teams"].append(str(team))     # its dolls still count at the map's end
    spot = _spot_of(m, m["team_pos"].pop(str(team), ""))
    if spot is not None and spot["team_id"] == str(team):
        spot["team_id"] = "0"
    if m.get("carrying", {}).pop(str(team), None) is not None:
        m["hostages_lost"] = int(m.get("hostages_lost") or 0) + 1      # "- HOSTAGE KIA -"


def _exp_rate(m, kind, unit):
    """mission_buff_config.exp_buff of the buffs a unit has, multiplied (the client parses it into
    MissionBuffCfg.expBuff the same way: "1.1" a factor, "*0" times 0, 1 / blank no change). 1301-1310
    give 1.05-1.25, 13 gives none."""
    rate = 1.0
    for b in (_effects(m)["buffs"].values() if m.get("effects") else []):
        if b["kind"] != kind or b["unit"] != str(unit):
            continue
        text = str(_mission_buffs().get(b["buff_id"], {}).get("exp_buff") or "1").strip().lstrip("*")
        try:
            rate *= float(text)
        except ValueError:
            pass
    return rate


@lru_cache(maxsize=1)
def _battle_skills():
    return {int(r["id"]): r for r in stc.table("battle_skill_config")}


def _spend_fairy_battle_skill(state, team):
    """The battle report's use_fairy_skill (BattleController$$CreateBattleResultJS): the echelon's
    fairy used its battle skill, and the client took battle_skill_config.consumption (skill group
    fairy.skill_id, row group * 100 + skill_lv) off its Fairy Command (BattleResultController$$Init)."""
    from . import account
    fairies = state.get("fairy_with_user_info") or []
    fairies = fairies.values() if isinstance(fairies, dict) else fairies       # keyed by id in most saves
    fairy = next((f for f in fairies if str(f.get("team_id")) == str(team)), None)
    row = next((r for r in stc.table("fairy") if str(r["id"]) == str((fairy or {}).get("fairy_id"))), None)
    group = str((row or {}).get("skill_id") or "")
    if fairy is None or not group.isdigit():
        return
    skill = _battle_skills().get(int(group) * 100 + int(fairy.get("skill_lv") or 1))
    if skill is not None:
        account.spend_ssoc(state, skill.get("consumption"))


def battle_finish(state, body, rng=random):
    """A battle the client fought: our attack (after teamMove) or an enemy's attack on an
    echelon (from startEnemyTurn's enemy_move)."""
    m = _mission(state)
    body = body or {}
    if m is None:
        return None
    spot = _spot_of(m, body.get("spot_id"))
    m["battles"] = int(m.get("battles") or 0) + 1       # win type 2302
    pending = m.pop("pending_battle", None) or {}
    attack = m["enemy_attacks"].pop(str(body.get("spot_id")), None) if not pending else None
    team = str(pending.get("team") or (spot or {}).get("team_id") or 0)
    won = bool(body.get("if_enemy_die"))
    # a Coalition echelon's own attack, or an enemy attack on one (body lists "sangvises")
    kind = "sangvis" if pending.get("sangvis") or (body.get("sangvises") and not body.get("guns")) else "gun"
    if pending.get("vehicle"):
        kind = "vehicle"
    friend = pending.get("friend") or (_friend_on(m, body.get("spot_id")) if attack is not None else None)
    if friend:
        return _friend_battle_end(state, m, body, spot, pending, attack, friend, won, rng)
    if kind == "gun" and team == "0":
        # no echelon of ours there: an allied force's battle (its own dolls in "guns")
        return _ally_battle_end(state, m, body, spot, attack, won, rng)
    guns = [g for g in body.get({"gun": "guns", "sangvis": "sangvises"}.get(kind, "vehicles")) or [] if isinstance(g, dict)]
    rank = _battle_rank(state, body, kind, won) if kind != "vehicle" else (RANK_S if won else RANK_LOST)
    for g in guns if kind != "vehicle" else []:
        unit = workshop._find(state.get(f"{kind}_with_user_info"), g.get("id") or 0)
        if unit is not None and "life" in g:
            workshop.set_life(state, kind, unit, int(g["life"] or 0))
    if str(body.get("use_fairy_skill") or "").lower() not in ("", "0", "false") and kind == "gun":
        _spend_fairy_battle_skill(state, team)
    fighter = team if kind != "sangvis" else str(pending.get("team") or (spot or {}).get("sangvis_team_id") or 0)
    fighter_res = _battle_supply(state, m, body, kind, fighter) if fighter != "0" else None
    _count_battle(m, kind, fighter)
    if isinstance(body.get("last_battle_info"), str):
        # the dolls' skill cooldowns carried into the next battle (SkillUtils$$GetSkillCDInfo); a
        # resumed map gives it back (mission_act_info.last_battle_info, SkillUtils$$LoadSkillCDInfo)
        m["last_battle_info"] = body["last_battle_info"]
    dead = sum(1 for g in guns if int(g.get("life") or 0) <= 0)
    m["gun_die"] = m.get("gun_die", 0) + dead
    wiped = bool(guns) and dead == len(guns)
    gun_exp, favor, over, for_fairy = [], {}, 0, 0
    for g in state.get("gun_with_user_info", []) if kind == "gun" else []:
        if str(g.get("team_id")) != team:
            continue
        exp = int(doll_battle_exp(state, m["mission_id"], g, body.get("mvp")) * _exp_rate(m, "team", team)) if won else 0
        for_fairy += exp // OATH_MOD_EXP if _oath_mod(g) else exp
        past_cap = add_gun_exp(g, exp) if exp else 0
        over += past_cap
        # what the doll took (recorded: "0" for a doll at its level cap; the rest goes to free_exp)
        gun_exp.append({"gun_with_user_id": str(g["id"]), "exp": str(exp - past_cap)})
        cap = int(g.get("max_favor") or 1000000)
        before = int(g.get("favor") or 0)
        after = max(before, min(cap, before + (FAVOR_PER_WIN if won else 0)))
        g["favor"] = str(after)
        favor[str(g["id"])] = after - before
    user_exp = commander_exp(state, m["mission_id"]) if won else 0
    _add(state["user_info"], "experience", user_exp)
    if won:
        quests.record(state, "win_normal")
        if rank == RANK_S:
            quests.record(state, "s_win")
    if wiped:
        quests.record(state, "team_die")
    elif kind != "vehicle":
        unit_id = team if kind == "gun" else str(pending.get("team") or (spot or {}).get("sangvis_team_id") or 0)
        _after_battle(state, m, ("team" if kind == "gun" else "sangvis", unit_id), won)
    if not wiped and kind in ("gun", "sangvis", "vehicle"):
        fought = {"gun": "team", "sangvis": "sangvis", "vehicle": "vehicle"}[kind]
        uid = team if kind == "gun" else str(pending.get("team") or (spot or {}).get(
            "sangvis_team_id" if kind == "sangvis" else "vehicle_with_user_id") or 0)
        _battle_triggers(state, m, body.get("spot_id"), (fought, uid))
    reply = {"seed": rng.randint(1, 9999), "battle_rank": rank,
             "user_exp": str(user_exp), "gun_exp": gun_exp, "favor_change": favor,
             "fairy_exp": _fairy_battle_exp(state, team, for_fairy) if won and kind == "gun" else 0,
             "free_exp": add_free_exp(state, over), "gun_life": [], "squad_exp": [], "type5_score": 0,
             "building_defender_change": [], "mission_control": {}}
    if fighter_res is not None:
        # as recorded: sangvisBattleFinish's sangvis_team_resource, vehicleBattleFinish's vehicle_resource
        reply["sangvis_team_resource" if kind == "sangvis" else "vehicle_resource"] = fighter_res
    support = _support_resource(state, m, body)
    if support is not None:
        reply["squad_resource"] = support
    if kind == "sangvis" and _own_sangvis(fighter):
        reply["sangvis_battle_exp"] = _sangvis_exp(state, m["mission_id"], fighter, body.get("mvp"), won)
    if kind == "vehicle" and fighter != "0":
        # recorded on 128 (vehicleBattleFinish): vehicle_battle_exp and the crew's exp. The vehicle's
        # own exp isn't worked out (it stayed at 210100 with free_exp 960; left unchanged here)
        crew, crew_over = _crew_exp(state, m, fighter, won, body.get("mvp"))
        reply["vehicle_battle_exp"], veh_over = _vehicle_exp(state, m, fighter, won)
        reply["crew_exp"] = crew
        reply["free_exp"] += add_free_exp(state, crew_over + veh_over)
    if spot is None:
        return reply
    foe = _spot_of(m, attack["from"]) if attack is not None else spot
    if not won and foe is not None and "boss_hp" in body and _boss_hp(foe.get("enemy_team_id")):
        # a boss that survived keeps the HP the client reports (battleFinish boss_hp)
        foe["boss_hp"] = str(max(1, int(body.get("boss_hp") or 0)))
    if attack is not None:
        # an enemy attacked this echelon from attack["from"]
        enemy_spot = _spot_of(m, attack["from"])
        if won and enemy_spot is not None:
            _battle_drop(state, reply, enemy_spot["enemy_team_id"])
            _enemy_killed(m, enemy_spot, state)
        elif kind == "sangvis":
            if m["sangvis_pos"].pop(spot["sangvis_team_id"], None) is not None:
                _echelon_out(m, spot, lost=True)
            spot["sangvis_team_id"] = "0"
        elif wiped or kind == "gun":
            _remove_team(m, team)           # dolls still alive retreated: the client takes the echelon off the map
            _echelon_out(m, spot, lost=True)
        reply = _check_loss(state, m, reply)
        return reply if "mission_lose_result" in reply else _check_win(state, m, reply)
    if kind == "sangvis":
        return _sangvis_battle_end(state, m, reply, spot, pending, won, wiped)
    if kind == "vehicle":
        return _unit_battle_end(state, m, reply, spot, pending, won, wiped, "vehicle_pos", "vehicle_with_user_id")
    if won:
        _defeat_on_spot(state, m, spot, reply)
        m["team_pos"][team] = spot["spot_id"]
        reply["building_defender_change"] = []
        _occupy_building(state, m, spot["spot_id"], reply)
        _take_hostage(m, spot, team)
        return _check_win(state, m, reply)
    # wiped, or its dolls retreated: either way the client takes the echelon off the map
    _remove_team(m, team)
    _echelon_out(m, spot, lost=True)
    return _check_loss(state, m, reply)


def _battle_rank(state, body, kind, won):
    """battle_rank of a battle the client reports: lost RANK_LOST; won by HP lost (see RANK_A_LOST)."""
    if not won:
        return RANK_LOST
    units = [g for g in body.get("sangvises" if kind == "sangvis" else "guns") or [] if isinstance(g, dict)]
    full = now = 0
    allies = _gun_in_ally() if kind != "sangvis" else _sangvis_in_ally()
    for g in units:
        unit = workshop._find(state.get(f"{kind}_with_user_info"), g.get("id") or 0) if kind in ("gun", "sangvis") else None
        top = workshop.max_life(state, kind, unit) if unit is not None else int((allies.get(int(g.get("id") or 0)) or {}).get("life") or 0)
        if top <= 0:
            continue
        full += top
        now += max(0, min(top, int(g.get("life") or 0)))
    lost = 1 - now / full if full else 0
    return RANK_S if lost < RANK_A_LOST else RANK_A if lost < RANK_B_LOST else RANK_B


@lru_cache(maxsize=1)
def _gun_in_ally():
    return {int(r["id"]): r for r in stc.table("gun_in_ally")}


@lru_cache(maxsize=1)
def _sangvis_in_ally():
    return {int(r["id"]): r for r in stc.table("sangvis_in_ally")}


def _support_resource(state, m, body):
    """squad_resource for the first HOC that supported a battle (recorded in its reply)."""
    for entry in body.get("use_skill_squads") or []:
        inst = entry.get("squad_instance_id") if isinstance(entry, dict) else entry
        if str(inst or 0) in (m.get("squads") or {}):
            return dict(_res(state, m, "squad", _squad_uid(m, inst)))
    return None


def _ally_battle_end(state, m, body, spot, attack, won, rng):
    """An allied force fought (attacking on our turn after allyMySideMove, or attacked on the enemy
    turn): recorded replies carry only battle_rank and seed, plus squad_resource when a HOC of ours
    supported it (it pays its support cost). No exp or drops; the enemy it beat dies, and a beaten
    ally leaves the map."""
    _battle_supply(state, m, body, "ally", "0")
    reply = {"seed": rng.randint(1, 9999), "battle_rank": _battle_rank(state, body, "ally", won), "type5_score": 0}
    res = _support_resource(state, m, body)
    if res is not None:
        reply["squad_resource"] = res
    if spot is None:
        return reply
    fought = _note_ally_life(m, spot, body, won)
    if fought is not None and won:
        reply["ally_instance_info"] = {fought: _ally_json(m, m["allies"][fought])}
    enemy_spot = _spot_of(m, attack["from"]) if attack is not None else spot
    if won and enemy_spot is not None and int(enemy_spot.get("enemy_team_id") or 0):
        _enemy_killed(m, enemy_spot, state, by="npc")
    elif won and enemy_spot is not None:
        _defeat_on_spot(state, m, enemy_spot, reply)       # a hostile force there (11368)
    elif not won:
        for iid in list(spot.get("ally_instance_ids") or []):
            a = (m.get("allies") or {}).get(str(iid))
            if a is not None:
                _ally_left(reply, a["ally_team_id"])        # recorded (11341: ["580901"])
            _remove_ally(m, str(iid))
        if (attack or {}).get("force") and enemy_spot is not spot and int(enemy_spot.get("enemy_team_id") or 0)                 and not int(spot.get("enemy_team_id") or 0):
            # the enemy that beat a force the player moves stands on its spot (1001-EX, recorded:
            # endEnemyTurn showed 483904 on 74547 and took it)
            _move_enemy(enemy_spot, spot)
    reply = _check_loss(state, m, _effect_keys(m, reply))
    return reply if "mission_lose_result" in reply else _check_win(state, m, reply)


def _note_ally_life(m, spot, body, won):
    """Keep the HP a force's dolls ended its battle with: battleFinish's guns [{"id": <gun_in_ally
    id>, "life": HP}]. The live server sent it back in ally_instance_info's ally_guns "life"
    (recorded 2026-11-07 on 11116: 748 565, 749 520 after a won fight; 0 for every doll after a lost
    one) and the force kept it into its next battle; without it the client puts the force back to
    full (player report, Scorpion Vortex). Returns the force's instance id, or None."""
    lives = {str(g.get("id")): max(0, int(g.get("life") or 0)) for g in body.get("guns") or []
             if isinstance(g, dict) and "life" in g}
    if not lives:
        return None
    for iid in spot.get("ally_instance_ids") or []:
        a = (m.get("allies") or {}).get(str(iid))
        if a is None or int(a["ally_team_id"]) in COMMANDER_ARMOR:
            continue
        mine = {str(g) for g in (a.get("guns") or _ids(_ally_teams().get(int(a["ally_team_id"]), {}).get("guns")))}
        if mine & set(lives):
            a["gun_life"] = {g: (lives[g] if won else 0) for g in sorted(mine & set(lives), key=int)}
            return str(iid)
    return None


def _sangvis_battle_end(state, m, reply, spot, pending, won, wiped):
    """A Coalition echelon's attack (after sangvisMove) is over."""
    return _unit_battle_end(state, m, reply, spot, pending, won, wiped, "sangvis_pos", "sangvis_team_id")


def _unit_battle_end(state, m, reply, spot, pending, won, wiped, pos_key, field):
    """A Coalition echelon's or vehicle's attack is over: it holds the spot, or leaves the map
    (a Coalition echelon that retreated, like a doll echelon) or falls back (a vehicle still running)."""
    team = str(pending.get("team"))
    if won:
        _defeat_on_spot(state, m, spot, reply)
        return _check_win(state, m, reply)
    back = _spot_of(m, pending.get("from"))
    empty = 0 if field == "vehicle_with_user_id" else "0"
    if str(spot[field]) == team:
        spot[field] = empty
    if wiped or back is None or field != "vehicle_with_user_id":
        if m[pos_key].pop(team, None) is not None:
            _echelon_out(m, spot, lost=True, vehicle=pos_key == "vehicle_pos")
        return _check_loss(state, m, reply)
    back[field] = int(team)
    m[pos_key][team] = back["spot_id"]
    return _with_steps(m, reply)


def sangvis_battle_finish(state, body, rng=random):
    """Mission/sangvisBattleFinish: same reply as battleFinish
    (BattleController$$RequestSangvisBattleFinishHandle); body lists "sangvises" [{id, life}]."""
    return battle_finish(state, body, rng)


def _buildings_hold(m, kind, args):
    """1205-1208 "building:x,...|...": every listed building (each copy of it on the map) destroyed /
    standing / active / not active, for any "|" alternative (DeploymentUIController$$CheckBuildLogicOr
    -> CheckBuild). Active is as of the end of our turn (m["worked"])."""
    worked = {(int(sp), int(b)) for sp, b in m.get("worked") or []}
    def ok(bid):
        copies = [(int(sp), b) for sp, b in (m.get("buildings") or {}).items() if int(b["building_id"]) == bid]
        if not copies:
            return False
        for sp, b in copies:
            down = int(b.get("defender") or 0) <= 0
            active = (sp, bid) in worked
            if not {WIN_BUILDINGS_DOWN: down, WIN_BUILDINGS_UP: not down,
                    WIN_BUILDINGS: active, WIN_BUILDINGS_IDLE: not active}[kind]:
                return False
        return True
    for alt in args.split("|"):
        need = [int(p.partition(":")[0]) for p in alt.split(",") if p.partition(":")[0].strip().isdigit()]
        if need and all(ok(b) for b in need):
            return True
    return False


def _working_buildings(m):
    """(spot, building_id) of each active building: defender above 0 and its working_special_spot
    on its spot (or none set)."""
    on = {}
    for sp in _effects(m)["specials"].values():
        on.setdefault(int(sp["spot"]), set()).add(int(sp["config"]))
    out = set()
    for spot, b in (m.get("buildings") or {}).items():
        want = set(_ids(str(_buildings().get(int(b["building_id"]), {}).get("working_special_spot") or "").replace("|", ","))) - {0}
        if int(b.get("defender") or 0) > 0 and (not want or want & on.get(int(spot), set())):
            out.add((int(spot), int(b["building_id"])))
    return out


def end_turn(state, body, rng=random):
    """Our turn ends: echelons take the spots they stand on (surrounded spots fall at startTurn)."""
    m = _mission(state)
    if m is None:
        return None
    if (m.get("pending_battle") or {}).get("friend"):
        m.pop("pending_battle")         # a friend's attack the client never fought: it stays put
    reply = {"change_belong1": _capture_turn_end(m, BELONG_OURS, surround=False)}
    corridors = _corridor_wave(m, rng)
    if corridors:
        reply["fairy_skill_return"] = {"mission_hurt": [], "allyteam_summoner": corridors}
    _supply_line_score(m)
    ally_stand_rules(m, ALLY_FRIENDLY, reply)
    quests.record(state, "map_capture", len(reply["change_belong1"]))
    m["worked"] = sorted(_working_buildings(m))      # active buildings, for 1207 / 1209
    if m.pop("resync", False):
        # The live server put the whole map in every reply; the client reads spot_act_info only
        # if present (endTurn: DeploymentController$$RequestEndAllFriendTurnHandle ->
        # MissionAction$$CheckEnemyDataTemp), so it goes out only after a change no reply reported.
        reply["spot_act_info"] = _hidden_view(state, m)
    return _check_win(state, m, _effect_keys(m, reply))


def _myside_spots(m):
    """Spots of the allied forces the player moves (ai 20100, teamMove person_type 3)."""
    return {int(m["allies"][k]["spot"]) for k in _myside_units(m)}


def _enemy_targets(m):
    """What enemies go for: our echelons and the forces the player moves (1001-EX, recorded: they
    went for Helian's and the Griffin squads' spots in the server rooms, and fought them there)."""
    return _echelon_spots(m) | _myside_spots(m) | _squad_spots(m)


def _squad_spots(m):
    return {int(q["spot"]) for q in (m.get("squads") or {}).values() if q.get("spot")}


def _hoc_record(state, m, inst):
    q = (m.get("squads") or {}).get(str(inst))
    return _squad_row(state, q["squad"]) if q is not None else None


def _hocs_lost(state, m, spot):
    """HOCs can't fight: an enemy stepping onto theirs, or they onto an enemy, kills them and takes
    them off the map (player report), each a defeat (score field 9, mysquad_die_num); a dead HOC is at
    0 HP and has to be repaired (player report). The client is sent the map again (spot_act_info) with
    the next reply that carries it."""
    lost = list(spot.get("squad_instance_ids") or [])
    rule = score_rule(m["mission_id"])
    for inst in lost:
        rec = _hoc_record(state, m, inst)
        if rec is not None:
            workshop.set_life(state, "squad", rec, 0)
        _unplace_squad(m, inst)
        m["squad_die"] = int(m.get("squad_die") or 0) + 1
        if rule is not None:
            _add_score(m, -rule["hoc_out"])
    if lost:
        m["resync"] = True
    return lost


def _enemy_step(m, inst, here, behaviour, para, blocked, rng):
    """The spot an enemy steps to this turn (an echelon's spot means an attack), or None."""
    mid, ours = m["mission_id"], _enemy_targets(m)
    links = [n for n in _links(mid).get(here, []) if n not in blocked]
    if behaviour == RANDOM:
        # any unobstructed neighbour, every turn
        return rng.choice(links) if links else None
    if behaviour == ATTACK:
        hqs = {int(s["spot_id"]) for s in _hq_spots(m) if s["belong"] == BELONG_OURS}
        return _step_toward(mid, here, hqs or ours, blocked)
    if behaviour == ALERT:
        # the closest echelon in detection range; a tie between echelons is broken at random
        reach = (_ids(para.split("|")[0]) or [1])[0]
        dist = _distances(mid, here, blocked)
        seen = sorted(s for s in ours if dist.get(s, reach + 1) <= reach)
        if not seen:
            return None
        nearest = [s for s in seen if dist[s] == min(dist[x] for x in seen)]
        return _step_toward(mid, here, {rng.choice(nearest)}, blocked)
    if behaviour == EXPAND:
        if _spot_of(m, here)["belong"] != BELONG_ENEMY:
            return None         # hold until this spot turns ours at the end of the turn
        griffin = {int(s["spot_id"]) for s in m["spots"] if s["belong"] == BELONG_OURS}
        nxt = _step_toward(mid, here, griffin, blocked)
        if nxt is None:
            # no way to a node of ours: the nearest neutral one (player report: Mistbuster's heliport
            # prespawns and Narciss stood still, hemmed in by the enemies ahead of them)
            neutral = {int(s["spot_id"]) for s in m["spots"] if s["belong"] == BELONG_NEUTRAL}
            nxt = _step_toward(mid, here, neutral, blocked)
        return nxt
    if behaviour == PATROL:
        # attack an echelon next to it (at most one spot off its course), else walk the
        # ai_content route back and forth, rejoining it first if it strayed
        near = [n for n in links if n in ours]
        if near:
            return near[0]
        route = _ids(para.split("|")[0])
        if here not in route:
            return _step_toward(mid, here, set(route), blocked)
        if len(route) < 2:
            return None
        i, step = route.index(here), m["patrol_dir"].get(inst, 1)
        if not 0 <= i + step < len(route):
            step = -step        # turn round at either end
        m["patrol_dir"][inst] = step
        return _step_toward(mid, here, {route[i + step]}, blocked)
    if behaviour == LOCK_ON:
        goals = _lock_on_goals(m, here, para)
        return _step_toward(mid, here, goals, blocked - (goals & ours)) if goals else None
    return None


def _lock_on_goals(m, here, para):
    """Lock On's ai_content "<ally_team_id>:<range>": the spots of that force within range."""
    team, _, reach = str(para or "").partition(":")
    if not team.strip().isdigit():
        return set()
    dist = _distances(m["mission_id"], int(here))
    reach = int(reach) if reach.strip().isdigit() else len(dist)
    return {int(a["spot"]) for a in (m.get("allies") or {}).values()
            if int(a["ally_team_id"]) == int(team) and dist.get(int(a["spot"]), reach + 1) <= reach}


# Extra steps (ExtraMove buffs, mission_buff_config ext_move: 20401 on Slow Shock's forces, SC+'s
# 6540238 from 9550101). After the enemy turn's moves the client compares each enemy's step count
# in target_moved_step (MissionAction$$LoadMoveStepData: the value is the count; read back by
# DeploymentController$$CheckTeamHasMoveStep) with 1 + the ext_move of its buffs
# (DeploymentTeamController$$CurrentMoveStepMax) and, while one has steps left, asks
# Mission/enemyTurnMove (DeploymentController$$CheckMissionTeamBuffStepMove from CheckNext). Each
# of those calls is one more step for the enemies that have one left. An enemy that attacked, was
# trapped, only just arrived or has nowhere to go is marked done (its count set to its max), so the
# client stops asking.
STEP_DONE = 99


def _ext_moves(m, inst, kind="enemy"):
    """Extra steps a unit's buffs give it this turn (the sum of their ext_move)."""
    rows = _mission_buffs()
    return sum(int((rows.get(b["buff_id"]) or {}).get("ext_move") or 0)
               for b in (m.get("effects") or {}).get("buffs", {}).values()
               if b["kind"] == kind and b["unit"] == str(inst))


# Move order: which enemy moves first in the enemy turn (player report: "it differs between maps and
# sometimes even map state"; the live server's rule isn't known). A map's "move_order" (a mod's
# map_rules, else the player's map config, else data/spawn_tables.json):
#   {"first": [{"team": id} | {"ai": "patrol"|"alert"|...} | {"spot": id}, ...],
#    "then": "oldest" | "newest" | "nearest" | "farthest"}
# Enemies matching an earlier "first" entry move before later ones and before the rest; within each
# group "then" decides: oldest (lowest enemy_instance_id, the default), newest, nearest to / farthest
# from our units and Command Posts (steps over the map's links).
MOVE_THEN = ("oldest", "newest", "nearest", "farthest")


def move_order(mid):
    got = _map_setting(mid, "move_order")
    if got is None:
        got = (_spawn_table(int(mid)) or {}).get("move_order")
    return got if isinstance(got, dict) else {}


def _move_order_key(m):
    order = move_order(m["mission_id"])
    first = [r for r in order.get("first") or [] if isinstance(r, dict)]
    then = order.get("then") if order.get("then") in MOVE_THEN else "oldest"
    dist = {}
    if then in ("nearest", "farthest"):
        ours = _enemy_targets(m) | {int(s["spot_id"]) for s in _hq_spots(m) if s["belong"] == BELONG_OURS}
        for o in ours:
            for sid, d in _distances(m["mission_id"], o).items():
                dist[sid] = min(dist.get(sid, d), d)

    def group(s):
        behaviour = enemy_behaviour(m["mission_id"], s["enemy_team_id"])[0]
        for i, r in enumerate(first):
            if ("team" in r and str(r["team"]) == str(s["enemy_team_id"]) or "spot" in r and str(r["spot"]) == str(s["spot_id"])
                    or "ai" in r and r["ai"] == behaviour):
                return i
        return len(first)

    def key(s):
        inst, here = int(s["enemy_instance_id"]), int(s["spot_id"])
        far = dist.get(here, 10 ** 6)
        tie = {"oldest": inst, "newest": -inst, "nearest": far, "farthest": -far}[then]
        return group(s), tie, inst
    return key


def _step_enemies(state, m, rng, skip=(), only=None):
    """One step for each enemy as its AI says, in the map's move order (only: just these
    instances, for a second step). Returns the enemy_move entries, already applied; an enemy
    stepping onto an echelon or a force attacks and stays put until battleFinish."""
    moves, attacked = [], set()
    steps = m.setdefault("enemy_steps", {})
    pending = [(sp, sp["enemy_instance_id"]) for sp in sorted(_enemy_spots(m), key=_move_order_key(m))]
    tried = set()       # had their turn at the trap checks (a retry must not pop "held" again)
    while pending:
        waiting, before = [], len(moves)
        for spot, inst in pending:
            if _enemy_steps_one(state, m, rng, spot, inst, skip, only, steps, moves, attacked, tried) is False:
                waiting.append((spot, inst))
        # an enemy whose way was blocked by one that moved later in the pass plans again (the
        # user: on Mistbuster expanding enemies stood still on red nodes because a faster one
        # took their path first); every AI, until a pass moves nobody
        pending = waiting if len(moves) > before else []
    return moves


def _enemy_steps_one(state, m, rng, spot, inst, skip, only, steps, moves, attacked, tried):
    """One enemy's step for _step_enemies. False: it found no way this time (it may try again)."""
    if spot["enemy_instance_id"] != inst or inst == "0" or inst in skip:
        return None         # moved away earlier this turn, or only just arrived
    if only is not None and inst not in only:
        return None
    here = int(spot["spot_id"])
    behaviour, para = enemy_behaviour(m["mission_id"], spot["enemy_team_id"])
    walled = {int(s["spot_id"]) for s in m["spots"] if _hidden(s)} if int(m["mission_id"]) in HIDDEN_WALLED else set()
    if here in walled:
        return None         # kept in until its node is revealed (HIDDEN_WALLED)
    blocked = (({int(s["spot_id"]) for s in _enemy_spots(m)} - {here}) | attacked
               | (_ally_spots(m) - _myside_spots(m)) | _no_entry_spots(m) | walled)
    if inst not in tried:
        tried.add(inst)
        if only is not None and m.get("held", {}).get(inst):
            return None         # caught in a trap on its first step: it waits out the next turn
        if m.get("held", {}).pop(inst, None):
            return None         # caught in a trap last turn
    nxt = _enemy_step(m, inst, here, behaviour, para, blocked, rng)
    if nxt is None or nxt in blocked:
        return False
    move = {"enemy_instance_id": int(inst), "squad_instance_id": 0, "from_spot_id": here,
            "to_spot_id": nxt, "hp_percent": float(spot["enemy_hp_percent"] or 1),
            "hostage_hp": 0, "hostage_id": 0}
    moves.append(move)
    if nxt in _myside_spots(m) and nxt not in _echelon_spots(m):
        # onto a force the player moves: the client fights it (battleFinish with the force's
        # dolls); the step counts on the spot's special spots at once (1001-EX: 482000's
        # move_count went to 1 and its 482010 came in startEnemyTurn, before the battle)
        attacked.add(nxt)
        m["enemy_attacks"][str(nxt)] = {"enemy_instance_id": inst, "from": spot["spot_id"], "force": True}
        _entered(state, m, nxt, "enemy", str(inst))
    elif nxt in _echelon_spots(m):
        # the hostage our echelon there carries, as recorded (it survives if the battle is won)
        carried = _hostage_on(m, nxt)
        if carried:
            move["hostage_id"], move["hostage_hp"] = int(carried["hostage_id"]), int(carried["hostage_hp"])
        attacked.add(nxt)
        m["enemy_attacks"][str(nxt)] = {"enemy_instance_id": inst, "from": spot["spot_id"]}
    else:
        _hocs_lost(state, m, _spot_of(m, nxt))
        hp, held = _spring_traps(state, m, nxt, inst, spot["enemy_team_id"], move["hp_percent"])
        move["hp_percent"] = hp
        spot["enemy_hp_percent"] = str(hp)
        if held:
            m.setdefault("held", {})[inst] = True
        target = _spot_of(m, nxt)
        if str(target.get("hostage_id") or "0") != "0":
            # a hostage left alone dies when an enemy reaches it (recorded on map 126: the
            # enemy_move there carries hostage 0, and endEnemyTurn fails the map)
            target.update(hostage_id="0", hostage_hp="0", hostage_max_hp="0")
            m["hostages_lost"] = int(m.get("hostages_lost") or 0) + 1
        _move_enemy(spot, target)       # enemies never knock buildings down by moving onto them (player report)
    steps[str(inst)] = steps.get(str(inst), 0) + 1
    if nxt in attacked:
        steps[str(inst)] = STEP_DONE        # fights where it stands: no further step this turn
    return True


def start_enemy_turn(state, body, rng=random):
    """Each enemy takes one step as its AI says, in the map's move order (move_order; the order
    the live server used is unknown; the client only re-sorts moves for animation, by map
    position, in DeploymentController$$QueueDataSort). Stepping onto an echelon is an attack:
    the client fights it and reports it with battleFinish; the enemy stays where it was
    until then."""
    m = _mission(state)
    if m is None:
        return None
    surrounded = _enemy_surround(m)
    # reinforcements first, so the moves go round them (the AI here only approximates the live one;
    # recorded on 11374: 9584211 appeared on 95551 / 95553 in enemy turn 1 and first moved in turn 2)
    grow = _spawn(m, rng)
    # new enemies move in the turn they appear (player report: true on every map); the client reads
    # grow_enemy before enemy_move (RequestStartEnemyTurnHandle), so they can move in the same reply
    m["enemy_steps"] = {}
    moves = _step_enemies(state, m, rng, set())
    for mv in moves:
        _count_move(m, "enemy", mv["enemy_instance_id"])
        _note_moved(m, MOVED_ENEMY, mv["enemy_instance_id"])
    if is_night(m["mission_id"]):
        # the client takes night moves from night_enemy, and only the ones in sight
        night, grow = _night_moves(state, m, moves, grow)
        reply = {"type5_score": 0, "enemy_move": [], "night_enemy": night}
        _enemy_instances(m, reply, {e["enemy_instance_id"] for e in night + grow})
    else:
        reply = {"type5_score": 0, "enemy_move": moves}
    if grow:
        reply["grow_enemy"] = grow
    ally_moves = _move_allies(m, ALLY_ENEMY_SIDE, rng, state)
    m["ally_steps"] = {str(mv["ally_instance_id"]): 1 for mv in ally_moves}
    if ally_moves:
        reply["ally_move"] = ally_moves
    _ally_battle_reply(m, reply)
    old = set(m.get("allies") or {})
    casts = _building_turn_skills(state, m, BELONG_ENEMY_INT)
    for iid in set(m.get("allies") or {}) - old:
        m["ally_steps"][iid] = STEP_DONE        # summoned this turn: no step yet
    _spent_buffs(m)
    _recorded_markers(m, "startEnemyTurn", rng)
    if casts:
        reply = _merge_replies(casts + [reply])
    if surrounded:
        reply["change_belong2"] = surrounded
        if m.get("had_hq") and not any(sp["belong"] == BELONG_OURS for sp in _hq_spots(m)):
            # a surrounded HQ loses at once (105); other losses wait for the turn's end (126)
            return _check_loss(state, m, _effect_keys(m, reply))
    return _effect_keys(m, reply)


# --- enemy spawn tables (mods) ----------------------------------------------------------
#
# mods map_rules[<mission id>]["spawns"]: list of rules
#   {"spot": id, "teams": [{"team": id, "weight": n}, ...], "start": false,
#    "from_turn": 1, "to_turn": 0, "every": 1, "chance": 100, "max": 0, "enemy_owned": true,
#    "while_alive": 0}
# "while_alive": an enemy team id; the rule only rolls while that team is somewhere on the map.
# "min_kills" / "max_kills": only while our kill count (NPC kills don't count) is within them.
# "if_special" / "unless_special": a special spot config id the spawn node must / must not hold
# (Steel Rain Salute: a heliport lit by detonated fireworks carries 800005 and spawns stronger teams).
# "after_killed": an enemy team id (or a list, any of them); only once one of that team has died
# (Hurricane Rescue+'s Defection: the Playpen heliports spawn after the B14 Patroller is killed).
# "after_destroyed": a node id; only once the building on it has been destroyed (defender 0)
# (Hurricane Rescue: an enemy spawns at the Command Tower the turn after it is destroyed).
# "our_turn": true rolls at the start of our turn instead of the enemy's (turns are then our turns).
# "blind": with "one_of", the node is drawn among all of them and the spawn is used up when that
# node is clogged or not the enemy's (Hornet's Nest+ bosses).
# "min_casts": {"<mission skill id>": n}; only once our buildings have cast that skill n times
# (FP 3g4: RPK-16 on A9 at the start of turn 4 with 9 emails, control panel skill 6510089).
# "not_ours": with enemy_owned false, still not on a node we hold.
# "start": placed once when the mission starts (before deployment). Otherwise rolled at the start
# of each enemy turn from from_turn to to_turn (0 = no end), every N turns, chance in %, at most
# "max" times (0 = unlimited). The spot must be empty (no enemy or echelon, and not part of this
# turn's moves) and, with enemy_owned, held by the enemy.

LIVE_SPAWNS = config.ROOT / "data" / "live_spawns.json"     # written by tools/import_spawns.py


def _live_spawn_rules(mid):
    """Spawn rules from recorded live runs. The live tables' spawn columns (the client's
    SpotInfo.grow_enemy_team_pool, grow_enemy_team_turn, grow_enemy_pool_defeat) aren't in the
    shipped stc, so what a map spawns is known only from what was seen on it: each team seen on a
    spot on a turn, at the rate of the runs that reached that turn."""
    seen = _live_spawn_seen(mid)
    grouped = {}
    for spot, turn, team, n in seen.get("grow", []):
        grouped.setdefault((spot, turn), {})[team] = n
    rules = []
    for (spot, turn), teams in sorted(grouped.items()):
        # runs that reached this enemy turn (logs imported before enemy_turns: runs that reached the turn)
        reached = (seen.get("enemy_turns") or seen.get("turns") or {}).get(str(turn))
        runs = max(int(reached or 0), sum(teams.values()))
        rules.append({"spot": spot, "from_turn": turn, "to_turn": turn, "chance": 100 * sum(teams.values()) / runs,
                      "teams": [{"team": t, "weight": n} for t, n in sorted(teams.items())]})
    grouped = {}
    for spot, team, n in seen.get("start", []):
        grouped.setdefault(spot, {})[team] = n
    for spot, teams in sorted(grouped.items()):
        runs = max(int(seen.get("turns", {}).get("1") or 0), sum(teams.values()))
        rules.append({"spot": spot, "start": True, "chance": 100 * sum(teams.values()) / runs,
                      "teams": [{"team": t, "weight": n} for t, n in sorted(teams.items())]})
    return rules


# Maps without a recording: the live spawn tables aren't in the client's files (only spot_buff
# grow_enemy_pool "1", the 出兵点 flag of the special spots 482101 / 800005 / 900001 that skills
# place), so every enemy-held heliport, and every spawn-point special spot, may grow an enemy at
# the start of each enemy turn, every turn it is empty (FALLBACK_SPAWN_CHANCE 100, the rule reported by players;
# no live rate is recorded). The
# team: one recorded spawning there, else one of the map's starting enemy teams (not a boss), in
# proportion. A map with recorded spawns uses them up to the last enemy turn a recorded run
# reached, and these after; a mod's own spawn list (even an empty one) replaces both.
FALLBACK_SPAWN_CHANCE = 100


def _live_spawn_seen(mid):
    """The map's recorded runs: the shipped ones and the player's own (gfserver/recordings.py); a
    mod's copy of a map adds its source's, on its own nodes."""
    seen = recordings.mission(LIVE_SPAWNS, mid)
    if _source(mid) is not None:
        seen = recordings.add(seen, _local_recording(mid, recordings.mission(LIVE_SPAWNS, _source(mid))))
    return seen


@lru_cache(maxsize=None)
def _map_enemy_pool(mid):
    bosses = _boss_teams(mid)
    pool = {}
    for r in _spots_by_mission().get(mid, []):
        team = int(r.get("enemy_team_id") or 0)
        if team and team in _enemy_teams() and team not in bosses:
            pool[team] = pool.get(team, 0) + 1
    return pool


def _spawn_pool(mid, spot):
    seen = {}
    for s_, _turn, team, n in _live_spawn_seen(mid).get("grow", []):
        if int(s_) == int(spot):
            seen[int(team)] = seen.get(int(team), 0) + n
    # none seen there: every non-boss team that starts on the map, equally likely (player report; as
    # GFLMaps lists a map's suspected spawns)
    pool = seen or {t: 1 for t in _map_enemy_pool(mid)}
    return [{"team": t, "weight": n} for t, n in sorted(pool.items())]


def _fallback_spawn_rules(mid):
    seen = _live_spawn_seen(mid)
    reached = [int(t) for t in (seen.get("enemy_turns") or seen.get("turns") or {})]
    first = max(reached) + 1 if reached else 1
    types = _spot_types(mid)
    rules = []
    for sid in sorted(s for s, t in types.items() if t == SPOT_HELIPORT):
        teams = _spawn_pool(mid, sid)
        if teams:
            rules.append({"spot": sid, "from_turn": first, "chance": FALLBACK_SPAWN_CHANCE, "teams": teams})
    return rules


def _spawn_point_rules(m):
    """Spawn-point special spots on the map now (placed by skills): on any side's node, but on a heliport
    only while the enemy holds it (and, like every spawn, not while it is closed)."""
    rules = []
    types = _spot_types(int(m["mission_id"]))
    for sp in (m.get("effects") or {}).get("specials", {}).values():
        if int(_spot_buff(sp).get("grow_enemy_pool") or 0):
            teams = _spawn_pool(m["mission_id"], sp["spot"])
            if teams:
                heli = abs(types.get(int(sp["spot"]), 0)) in (SPOT_HELIPORT, SPOT_HEAVY)
                rules.append({"spot": int(sp["spot"]), "chance": FALLBACK_SPAWN_CHANCE, "teams": teams,
                              "enemy_owned": heli, "_dynamic": True})
    return rules


_MAP_CONFIG = {"mtime": None, "maps": {}}


def map_config():
    """config.MAP_CONFIG {"maps": {"<mission id>": {"spawns": [rules], "random_nodes": {kind: weight}}}}:
    the player's own per-map settings, a global file rather than a mod (Mod Studio's Map spawns page
    writes it). Read again whenever the file changes, so edits apply without a restart. Tests
    (GF_NO_MODS) ignore the player's own unless they name one with GF_MAP_CONFIG."""
    if os.environ.get("GF_NO_MODS") and "GF_MAP_CONFIG" not in os.environ:
        return {}
    try:
        mtime = config.MAP_CONFIG.stat().st_mtime
    except OSError:
        return {}
    if mtime != _MAP_CONFIG["mtime"]:
        try:
            maps = json.loads(config.MAP_CONFIG.read_text("utf-8")).get("maps") or {}
        except (OSError, ValueError, AttributeError):
            maps = {}
        _MAP_CONFIG.update(mtime=mtime, maps=maps if isinstance(maps, dict) else {})
    return _MAP_CONFIG["maps"]


def _map_setting(mid, key):
    """A map's setting: a mod's map_rules for it first, else the player's map config, else None."""
    from . import mods
    rules = mods.map_rules(mid) or {}
    if key in rules:
        return rules[key]
    return (map_config().get(str(mid)) or {}).get(key)


SPAWN_TABLES = config.ROOT / "data" / "spawn_tables.json"


def _spawn_table(mid):
    """The map's entry in data/spawn_tables.json (a dict), or None; a mod's copy of a map has
    its source's, on its own nodes."""
    got = _shipped_spawn_table(mid)
    if got is None and _source(mid) is not None:
        got = _shipped_spawn_table(_source(mid))
        if got is not None:
            got = dict(got, spawns=_local_rules(mid, got.get("spawns")))
            if isinstance(got.get("move_order"), dict):
                got["move_order"] = dict(got["move_order"], first=_local_rules(mid, got["move_order"].get("first")))
    return got


@lru_cache(maxsize=None)
def _shipped_spawn_table(mid):
    try:
        got = json.loads(SPAWN_TABLES.read_text("utf-8")).get("missions", {}).get(str(mid))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def _table_spawn_rules(mid):
    """data/spawn_tables.json {"missions": {"<id>": {"spawns": [rules]}}}: the shipped spawn table
    for a map (from a ranking guide, a recording or the stc: its "_source"), or None for a map without one.
    With "adds_to_default": true its rules come first and the map keeps its recorded / fallback spawns."""
    got = _spawn_table(mid)
    if got is None:
        return None
    if got.get("adds_to_default"):
        # a table of extra rules only (bosses), ahead of the recorded runs and the heliport fallback
        return list(got.get("spawns") or []) + _live_spawn_rules(mid) + _fallback_spawn_rules(mid)
    return list(got.get("spawns") or [])


def _spawn_rules(mid, m=None):
    """A mod's spawn list for the map, else the player's map config one (either, even empty,
    replaces the rest), else the map's shipped spawn table (data/spawn_tables.json), else recorded live runs
    and the heliport fallback."""
    own = _map_setting(mid, "spawns")
    if own is not None:
        return list(own or [])
    table = _table_spawn_rules(int(mid))
    out = table if table is not None else _live_spawn_rules(mid) + _fallback_spawn_rules(mid)
    # "spawn_points": false in the table: the stc's spawn-point specials spawn nothing either
    # (Hurricane Rescue's 900001 on 8178-8180; the player: 'Just the initial prespawns')
    points = m is not None and (_spawn_table(int(mid)) or {}).get("spawn_points", True) is not False
    return out + (_spawn_point_rules(m) if points else [])


# Heliports open and close in turns by stc spot active_cycle "open,closed" (DeploymentSpotController
# $$CaculateTurnShow: turn % (open + closed), 0 counting as the last, above open is closed); "99,1", most
# of them, is open for 99 turns. Nothing spawns on a closed one.


@lru_cache(maxsize=1)
def _active_cycles():
    out = {}
    for r in stc.table("spot"):
        parts = str(r.get("active_cycle") or "").split(",")
        if abs(int(r.get("type") or 0)) in (3, 7) and len(parts) == 2 and all(x.strip().isdigit() for x in parts):
            opened, closed = int(parts[0]), int(parts[1])
            if opened + closed > 0:
                out[int(r["id"])] = (opened, closed)
    return out


def heliport_closed(sid, turn):
    cycle = _active_cycles().get(int(sid))
    if cycle is None or turn < 1:
        return False
    opened, closed = cycle
    at = turn % (opened + closed) or opened + closed
    return at > opened


def rule_spots(rule):
    """A spawn rule's nodes: "spots" [ids] (one rule for several heliports, each node on its own:
    its own chance, turn and "max" count), else its one "spot"."""
    return [int(x) for x in rule.get("spots") or [rule.get("spot")] if str(x or "").strip().lstrip("-").isdigit()]


def _spawn(m, rng, at_start=False, avoid=(), our_turn=False):
    """Roll the spawn rules: at mission start ("start" rules), at the start of an enemy turn, or with
    our_turn at the start of our turn ("our_turn" rules, sent as summon_enemy)."""
    grow = []
    turn = int(m["turn"])
    # allied forces hold their spot too (Hurricane Rescue+'s converted heliports stay empty while one is on them)
    occupied = _taken(m) | set(avoid)
    flat = []
    for i, rule in enumerate(_spawn_rules(m["mission_id"], m)):
        nodes = rule_spots(rule)
        if rule.get("one_of") and len(nodes) > 1:
            # one spawn on one of its nodes, picked at random among those that can take it
            flat.append((str(i), dict(rule, spot=None, _nodes=nodes)))
            continue
        # the count key stays "i" for a one-node rule, as saved maps have it
        flat += [(str(i) if len(nodes) == 1 else f"{i}:{sid}", dict(rule, spot=sid)) for sid in nodes]
    kills = int(m.get("enemy_die") or 0)
    for i, rule in flat:
        if rule.get("ally") or bool(rule.get("start")) != at_start:
            continue                # "ally" rules: _spawn_allies
        if not at_start and bool(rule.get("our_turn")) != our_turn:
            continue                # "our_turn": at the start of our turn (FP 3g4's RPK-16)
        casts = m.get("casts") or {}
        if any(int(casts.get(str(k), 0)) < int(n) for k, n in (rule.get("min_casts") or {}).items()):
            continue                # "min_casts": {mission skill: n}, cast at least n times (3g4's emails)
        if int(rule.get("min_kills") or 0) > kills:
            continue                # "kills": not before our kill count reaches it (NPC kills don't count)
        if rule.get("max_kills") is not None and kills > int(rule["max_kills"]):
            continue                # "max_kills": not once our kill count is past it (Hole 3's first Ouroboros)
        after = rule.get("after_killed")
        if after and not any(str(t) in (m.get("died_enemy") or {}) for t in (after if isinstance(after, list) else [after])):
            continue                # "after_killed": only once that team has died (Hurricane Rescue+'s Defection)
        down = rule.get("after_destroyed")
        if down and int(((m.get("buildings") or {}).get(str(down)) or {"defender": 1}).get("defender") or 0) > 0:
            continue                # "after_destroyed": only once the building on that node is down (Hurricane Rescue's Command Tower)
        if rule.get("while_alive") and not any(int(x["enemy_team_id"] or 0) == int(rule["while_alive"]) for x in _enemy_spots(m)):
            continue                # "while_alive": only while that enemy team is on the map (Hole 1's Ghost)
        if rule.get("_nodes"):
            ok = [x for x in rule["_nodes"] if x not in occupied and _spot_of(m, x) is not None
                  and (at_start or not rule.get("enemy_owned", True) or _spot_of(m, x)["belong"] == BELONG_ENEMY)
                  and (at_start or not heliport_closed(x, turn))]
            if rule.get("blind"):
                # "blind": the node is picked among all of them, and a clogged or captured one uses the
                # spawn up (Hornet's Nest+ bosses: "If the Heliport is clogged/captured, the boss does
                # not spawn and gets skipped")
                if int(rule.get("max") or 0) and m.setdefault("spawned", {}).get(i, 0) >= int(rule["max"]):
                    continue
                pick = rng.choice(rule["_nodes"])
                if pick not in ok:
                    m.setdefault("spawned", {})[i] = m["spawned"].get(i, 0) + 1
                    continue
                ok = [pick]
            if not ok:
                continue            # none free: tried again next turn
            rule = dict(rule, spot=rng.choice(ok))
        spot = _spot_of(m, rule.get("spot"))
        if spot is None or int(spot["spot_id"]) in occupied:
            continue
        marks = {sp["config"] for sp in (m.get("effects") or {}).get("specials", {}).values() if int(sp["spot"]) == int(spot["spot_id"])}
        if rule.get("if_special") and int(rule["if_special"]) not in marks or rule.get("unless_special") and int(rule["unless_special"]) in marks:
            continue                # "if_special" / "unless_special": only with / without that special spot there
        if not at_start:
            if heliport_closed(spot["spot_id"], turn):
                continue
            first, last = int(rule.get("from_turn") or 1), int(rule.get("to_turn") or 0)
            every = max(1, int(rule.get("every") or 1))
            if turn < first or (last and turn > last) or (turn - first) % every:
                continue
            if rule.get("enemy_owned", True) and spot["belong"] != BELONG_ENEMY:
                continue
            if rule.get("not_ours") and str(spot["belong"]) == BELONG_OURS:
                continue
        done = m.setdefault("spawned", {}).get(i, 0)
        if int(rule.get("max") or 0) and done >= int(rule["max"]):
            continue
        queue = [int(t) for t in rule.get("queue") or [] if int(t) in _enemy_teams()]
        if rule.get("queue") is not None and done >= len(queue):
            continue                # "queue": these teams one after another, each once
        if rng.random() * 100 >= float(rule.get("chance", 100)):
            continue
        teams = [t for t in rule.get("teams") or [] if int(t.get("team") or 0) in _enemy_teams()]
        if queue:
            team = queue[done]
        elif not teams:
            continue
        else:
            team = rng.choices([int(t["team"]) for t in teams], weights=[float(t.get("weight", 1)) for t in teams])[0]
        m["spawned"][i] = done + 1
        occupied.add(int(spot["spot_id"]))
        grow.append(_put_enemy(m, spot, _swapped_team(m, team, at_start), turn))
    return grow


def _spawn_allies(m, rng=random):
    """Spawn rules with "ally": true put a force (stc ally_team) on the heliport instead of an
    enemy: a third party's (SC+ 11320's military, ally teams 9550122-9550163 on their belong-0
    heliports, the SC+ notes). "side" sets whose side it is (else its row's). The rule's node must
    be held by "owner" (a belong, default 0: the third party) and free. Turns are enemy turns as
    for enemies; the force comes in at the start of our next turn in summon_ally (the reply Silent Sandtable's door waves were recorded in), as
    {"<instance>": <ally_instance_info entry, with spot_id>}. Returns that, or None."""
    turn = int(m["turn"]) - 1           # the enemy turn that just ended
    if turn < 1:
        return None
    taken, out = _taken(m), {}
    for i, rule in enumerate(_spawn_rules(m["mission_id"], m)):
        if not rule.get("ally") or rule.get("start"):
            continue
        first, last = int(rule.get("from_turn") or 1), int(rule.get("to_turn") or 0)
        every = max(1, int(rule.get("every") or 1))
        if turn < first or (last and turn > last) or (turn - first) % every:
            continue
        teams = [t for t in rule.get("teams") or [] if int(t.get("team") or 0) in _ally_teams()]
        for sid in rule_spots(rule):
            spot = _spot_of(m, sid)
            if not teams or spot is None or sid in taken or str(spot["belong"]) != str(rule.get("owner", ALLY_THIRD)):
                continue
            key = f"a{i}:{sid}"
            done = m.setdefault("spawned", {}).get(key, 0)
            if int(rule.get("max") or 0) and done >= int(rule["max"]):
                continue
            if rng.random() * 100 >= float(rule.get("chance", 100)):
                continue
            team = rng.choices([int(t["team"]) for t in teams], weights=[float(t.get("weight", 1)) for t in teams])[0]
            iid = _new_ally(m, team, spot, belong=rule.get("side"))
            if iid is None:
                continue
            m["spawned"][key] = done + 1
            taken.add(sid)
            out[iid] = dict(_ally_json(m, m["allies"][iid]), spot_id=str(sid))
    return out or None


def _put_enemy(m, spot, team, turn):
    """A new enemy of team on spot; returns its grow_enemy entry."""
    inst = int(m.get("next_instance") or 0) or 1 + max([int(s["enemy_instance_id"]) for s in m["spots"]] + [0])
    m["next_instance"] = inst + 1
    row = _enemy_teams()[team]
    ai, para = int(row.get("ai") or 0), local_spots(m["mission_id"], str(row.get("ai_content") or "0"))
    spot.update({"enemy_team_id": str(team), "enemy_instance_id": str(inst), "boss_hp": str(_boss_hp(team)),
                 "enemy_hp_percent": "1", "enemy_birth_turn": str(turn), "enemy_ai": ai, "enemy_ai_para": para})
    if team in _boss_teams(m["mission_id"]):
        m["boss_seen"] = True
    # read by DeploymentController$$AnalysicsGrowEnemy (get_Int / get_Float / get_String / get_Long)
    return {"spot_id": int(spot["spot_id"]), "enemy_team_id": team, "boss_hp": _boss_hp(team),
            "enemy_hp_percent": 1.0, "enemy_ai": ai, "enemy_ai_para": para, "enemy_instance_id": inst}


def enemy_turn_move(state, body, rng=random):
    """One more step for the enemies with an extra move left (see STEP_DONE); asked for while
    target_moved_step shows one short of its max. Night maps send it as night_enemy, as the first."""
    m = _mission(state)
    if m is None:
        return None
    steps = m.setdefault("enemy_steps", {})
    extra = {s["enemy_instance_id"]: _ext_moves(m, s["enemy_instance_id"]) for s in _enemy_spots(m) if s["enemy_instance_id"] != "0"}
    due = {i for i, n in extra.items() if n and steps.get(i, 0) < 1 + n}
    # enemy-side forces with an extra move (Slow Shock's Trojans) take theirs here too, as ally_move
    asteps = m.setdefault("ally_steps", {})
    aextra = {iid: _ext_moves(m, iid, "ally") for iid, a in (m.get("allies") or {}).items()
              if a["belong"] == ALLY_ENEMY_SIDE and not a.get("myside")}
    adue = {i for i, n in aextra.items() if n and asteps.get(i, 0) < 1 + n}
    if not due and not adue:
        return {"type5_score": 0, "enemy_move": []}
    before = {i: steps.get(i, 0) for i in due}
    moves = _step_enemies(state, m, rng, only=due)
    for inst in due:
        if steps.get(inst, 0) == before[inst]:
            steps[inst] = STEP_DONE         # nowhere to go: no further step this turn
    for mv in moves:
        _count_move(m, "enemy", mv["enemy_instance_id"])
    for inst in due:
        # the step count the client compares with its max (done ones at their max, so it stops asking)
        _note_moved(m, MOVED_ENEMY, inst, min(steps[inst], 1 + _ext_moves(m, inst)))
    if is_night(m["mission_id"]):
        night, _ = _night_moves(state, m, moves, [])
        reply = {"type5_score": 0, "enemy_move": [], "night_enemy": night}
        _enemy_instances(m, reply, {e["enemy_instance_id"] for e in night})
    else:
        reply = {"type5_score": 0, "enemy_move": moves}
    if adue:
        ally_moves = _move_allies(m, ALLY_ENEMY_SIDE, rng, state, only=adue)
        stepped = {str(mv["ally_instance_id"]) for mv in ally_moves}
        for iid in adue:
            asteps[iid] = asteps.get(iid, 0) + 1 if iid in stepped else STEP_DONE
            if iid in (m.get("allies") or {}):
                _note_moved(m, MOVED_ALLY, iid, min(asteps[iid], 1 + aextra[iid]))
        if ally_moves:
            reply["ally_move"] = ally_moves
        _ally_battle_reply(m, reply)
    _spent_buffs(m)
    return _effect_keys(m, reply)


def end_enemy_turn(state, body):
    """The enemy turn ends: enemies take the spots they stand on and surrounded spots."""
    m = _mission(state)
    if m is None:
        return None
    m["enemy_attacks"] = {}
    reply = {"type5_score": 0, "change_belong": _capture_turn_end(m, BELONG_ENEMY, surround=False)}
    summoned = _turn_spot_trans(m)      # TURN_SPOT_TRANS
    if summoned:
        reply["summon_enemy"] = summoned
    if m.get("spot_trans_now"):
        reply["spot_trans"] = m.pop("spot_trans_now")
    ally_stand_rules(m, ALLY_ENEMY_SIDE, reply)
    if m.get("win_steps") is not None:
        reply["mission_win_step_control_ids"] = _steps_now(m)     # recorded (11355)
    _flush_belong(m, reply)
    return _reveal(state, m, _check_loss(state, m, reply))


def start_turn(state, body, rng=random):
    m = _mission(state)
    if m is None:
        return None
    m["turn"] = int(m["turn"]) + 1
    m["ap"] = _turn_ap(m)
    reply = {"type5_score": 0, "ap": m["ap"]}
    _trigger(m, "turn", m["turn"])
    surrounded = _our_surround(m)
    if surrounded:
        reply["change_belong"] = surrounded
        quests.record(state, "map_capture", len(surrounded))
    _merge_ally(reply, ally_changes(m, ALLY_ON_TURN, m["turn"], reply))
    _turn_supply(state, m)
    changes = _move_rally(m, rng) + json.loads(_drop_crates(m, rng) or "[]")
    if changes:
        reply["new_spot_change"] = json.dumps(changes, separators=(",", ":"))
    summoned = dict(_summon_doors(m) or {}, **(_spawn_allies(m, rng) or {}))
    if summoned:
        reply["summon_ally"] = summoned
    reply.update(_turn_recovery(state, m))
    reply.update(_kill_counts(m))
    _sandtable_turn(m)
    hurts = _expire_effects(state, m)
    hurts += _turn_triggers(state, m)
    if hurts:
        reply["fairy_skill_return"] = {"mission_hurt": hurts}
    casts = (_building_turn_skills(state, m, BELONG_OURS_INT) + _chip_skills(state, m, every_turn=True)
             + _late_building_casts(state, m))
    # "our_turn" spawn rules, after this turn's building casts (3g4's RPK-16 counts this turn's emails);
    # the startTurn handler reads summon_enemy (MissionAction$$AnalysicsSpotTransInfo ->
    # AnalysicsMissionGrowEnemy), entries as grow_enemy. Not recorded live.
    summoned = _spawn(m, rng, our_turn=True)
    if summoned:
        reply["summon_enemy"] = summoned
    if casts:
        reply = _merge_replies(casts + [reply])
    _recorded_markers(m, "startTurn", rng)
    reply = _check_loss(state, m, _effect_keys(m, reply), turn_start=True)
    _queue_belong(m, _area_turn(m))             # AREA_MAPS: what opens this turn
    _flush_belong(m, reply)
    return _reveal(state, m, reply if "mission_lose_result" in reply else _check_win(state, m, reply))


def withdraw_team(state, body):
    m = _mission(state)
    if m is None:
        return None
    spot = _spot_of(m, (body or {}).get("spot_id"))
    if spot is not None and spot["team_id"] != "0":
        carried = m.get("carrying", {}).pop(spot["team_id"], None)
        if carried:
            spot.update(carried)            # a withdrawing echelon leaves its hostage behind
        _repair_team(state, spot["team_id"])
        _remove_team(m, spot["team_id"])
        _echelon_out(m, spot)
    return _check_loss(state, m, {"type5_score": 0})    # nothing new comes into sight


# Supply on the map. The client keeps it itself and the server only follows (the live server sent
# the results back: sangvis_team_resource, vehicle_resource, ...); each unit starts from its save
# record (deploying doesn't fill it: the recorded maps supply right after starting) and pays:
#   dolls (Gun.ammo / Gun.mre, full 5 / 10)  1 ammo + 1 ration per battle of its echelon
#                                            (BattleController$$CreateBattleResultJS)
#   Coalition echelon, HOC, vehicle (full 10 / 10)  game_config costs "ammo,mre":
#       its own battle            sangvis_attack_cost / vehicle_attack_cost
#       support in a doll battle  sangvis_assist_attack_cost / squad_battle_attack_cost /
#                                 vehicle_battle_attack_cost (battle body use_skill_*)
#       a building attack         <kind>_mission_attack_cost
#       a chip special skill      sangvis_chip active_special_skill_cost "ap,mre,ammo"
#   every unit, at the start of each of our turns: 1 ration for dolls, <kind>_mission_standby_cost
#       for the others (DeploymentController$$DeductMreEvent, run by startTurn)
# never below 0. Resupplying fills it (Mission/supplyTeam target_type 1 dolls, 8 Coalition;
# supplySangvis / supplySquad). Only the map's copy changes (m["res"]); a resumed map sends it in
# the login's gun / sangvis_team / squad / vehicle records (resume_info). Buffs on the unit change it
# (mission_buff_config, the Coalition chips' 50002 AmmoReduce "2,1": each use costs 2 ammo and 1
# ration less; 50000 ExtraAmmo "2,2": it holds 2 more of each).
FULL = {"gun": (5, 10), "sangvis": (10, 10), "squad": (10, 10), "vehicle": (10, 10)}
_BUFF_KIND = {"gun": "team", "sangvis": "sangvis", "vehicle": "vehicle"}


@lru_cache(maxsize=None)
def _cost(name, default="0,0"):
    text = next((r["parameter_value"] for r in stc.catch("game_config_info") if r["parameter_name"] == name), default)
    ammo, _, mre = str(text).partition(",")
    return int(ammo or 0), int(mre or 0)


def _team_guns(state, team):
    guns = state.get("gun_with_user_info") or []
    guns = guns.values() if isinstance(guns, dict) else guns
    return [g for g in guns if str(g.get("team_id")) == str(team)]


def _res_record(state, kind, uid):
    """The save record a unit's supply starts from and goes back to on a resumed map."""
    if kind == "sangvis":
        return next((t for t in state.get("sangvis_team_with_user_info") or [] if str(t.get("team_id")) == str(uid)), None)
    return workshop._find(state.get({"gun": "gun_with_user_info", "squad": "squad_with_user_info",
                                     "vehicle": "vehicle_with_user_info"}[kind]), uid)


def _res(state, m, kind, uid):
    """A unit's {"ammo", "mre"} on the map (dolls by gun_with_user_id, Coalition by team, HOCs by
    squad_with_user_id, vehicles by vehicle_with_user_id)."""
    key = f"{kind}:{uid}"
    res = m.setdefault("res", {}).get(key)
    if res is None:
        rec = _res_record(state, kind, uid) or {}
        full = _full(m, kind, uid, rec)
        res = m["res"][key] = {"ammo": min(full[0], int(rec.get("ammo", full[0]) or 0)),
                               "mre": min(full[1], int(rec.get("mre", full[1]) or 0))}
    return res


def _supply_buffs(m, buff_kind, uid):
    """(ammo, mre) less per use and (ammo, mre) more held, from the unit's buffs."""
    less, more = [0, 0], [0, 0]
    for b in (m.get("effects") or {}).get("buffs", {}).values():
        if b["kind"] != buff_kind or b["unit"] != str(uid):
            continue
        row = _mission_buffs().get(b["buff_id"], {})
        for key, out in (("ammo_mre_reduce", less), ("extra_ammo_mre", more)):
            vals = (_ids(row.get(key)) + [0, 0])[:2]
            out[0] += vals[0]
            out[1] += vals[1]
    return less, more


def _buff_owner(kind, uid, rec):
    """The unit a buff sits on for this supply record: a doll's is its echelon."""
    if kind == "gun":
        return "team", str((rec or {}).get("team_id") or 0)
    return _BUFF_KIND.get(kind, kind), str(uid)


def _full(m, kind, uid, rec=None):
    more = _supply_buffs(m, *_buff_owner(kind, uid, rec))[1]
    return FULL[kind][0] + more[0], FULL[kind][1] + more[1]


def _spend(state, m, kind, uid, cost):
    """Take (ammo, mre) from a unit ("team": each doll of that echelon); returns its resources."""
    if kind == "team":
        for g in _team_guns(state, uid):
            _spend(state, m, "gun", g["id"], cost)
        return None
    less = _supply_buffs(m, *_buff_owner(kind, uid, _res_record(state, kind, uid)))[0]
    ammo, mre = max(0, cost[0] - less[0]) if cost[0] else 0, max(0, cost[1] - less[1]) if cost[1] else 0
    res = _res(state, m, kind, uid)
    res["ammo"], res["mre"] = max(0, res["ammo"] - ammo), max(0, res["mre"] - mre)
    return dict(res)


def _fill(state, m, kind, uid):
    if kind == "team":
        for g in _team_guns(state, uid):
            _fill(state, m, "gun", g["id"])
        return _full(m, "gun", None, {"team_id": uid})
    full = _full(m, kind, uid, _res_record(state, kind, uid))
    m.setdefault("res", {})[f"{kind}:{uid}"] = {"ammo": full[0], "mre": full[1]}
    return full


def _squad_uid(m, inst):
    return str((m.get("squads") or {}).get(str(inst), {}).get("squad") or 0)


def _own_sangvis(team):
    return str(team) not in ("0", "") and not str(team).startswith("-")


def _turn_supply(state, m):
    """The start of our turn: every unit on the map eats (DeploymentController$$DeductMreEvent)."""
    for team in list(m.get("team_pos") or {}):
        _spend(state, m, "team", team, (0, 1))
    for team in list(m.get("sangvis_pos") or {}):
        if _own_sangvis(team):
            _spend(state, m, "sangvis", team, _cost("sangvis_mission_standby_cost", "0,1"))
    for inst in list(m.get("squads") or {}):
        _spend(state, m, "squad", _squad_uid(m, inst), _cost("squad_mission_standby_cost", "0,1"))
    for vid in list(m.get("vehicle_pos") or {}):
        _spend(state, m, "vehicle", vid, _cost("vehicle_mission_standby_cost", "0,1"))


def _battle_supply(state, m, body, kind, unit):
    """A battle report: the unit that fought pays for it, and so does every support it lists.
    Returns the fighting unit's resources (None for dolls)."""
    out = None
    if kind == "gun":
        _spend(state, m, "team", unit, (1, 1))
    elif kind == "sangvis" and _own_sangvis(unit):
        out = _spend(state, m, "sangvis", unit, _cost("sangvis_attack_cost", "2,1"))
    elif kind == "vehicle":
        out = _spend(state, m, "vehicle", unit, _cost("vehicle_attack_cost", "2,1"))
    for entry in body.get("use_skill_squads") or []:
        inst = entry.get("squad_instance_id") if isinstance(entry, dict) else entry
        if str(inst or 0) in (m.get("squads") or {}):
            _spend(state, m, "squad", _squad_uid(m, inst), _cost("squad_battle_attack_cost", "2,1"))
    for key, cost, field, kind2 in (("use_skill_vehicle_spots", "vehicle_battle_attack_cost", "vehicle_with_user_id", "vehicle"),
                                    ("use_skill_sangvis_spots", "sangvis_assist_attack_cost", "sangvis_team_id", "sangvis")):
        for entry in body.get(key) or []:
            spot = _spot_of(m, entry.get("spotid") if isinstance(entry, dict) else entry)
            uid = str((spot or {}).get(field) or 0)
            if _own_sangvis(uid):
                _spend(state, m, kind2, uid, _cost(cost, "2,1"))
    return out


def supply_team(state, body):
    """Mission/supplyTeam {mission_id, target_type (1 dolls, 8 Coalition), target_id, spot_id,
    item_cost} (RequestSupply), also Mission/supplySangvis / supplySquad {spot_id}: the unit is full
    again. Reply as recorded: {"max_ammo", "max_mre", "supply_count" (the spot's supplies so far),
    "type5_score"}."""
    m = _mission(state)
    if m is None:
        return None
    body = body or {}
    spot = _spot_of(m, body.get("spot_id"))
    target, uid = int(body.get("target_type") or 0), str(body.get("target_id") or 0)
    sangvis = str((spot or {}).get("sangvis_team_id") or "0")
    squads = [str(i) for i in (spot or {}).get("squad_instance_ids") or []]
    if target == 8 or (not target and sangvis != "0"):
        full = _fill(state, m, "sangvis", uid if uid != "0" else sangvis)
        full = (str(full[0]), str(full[1]))         # strings for Coalition echelons, as recorded
    elif target == 1 or (not target and spot is not None and spot["team_id"] != "0"):
        full = _fill(state, m, "team", uid if uid != "0" else spot["team_id"])
    elif target == 7 or squads:
        # HOC (target_type 7): strings, as recorded
        inst = str(body.get("target_id") or 0) if target == 7 and str(body.get("target_id") or 0) in (m.get("squads") or {}) else (squads or ["0"])[0]
        full = _fill(state, m, "squad", _squad_uid(m, inst))
        full = (str(full[0]), str(full[1]))
    elif spot is not None and int(spot.get("vehicle_with_user_id") or 0):
        full = _fill(state, m, "vehicle", spot["vehicle_with_user_id"])
    else:
        full = FULL["gun"]
    count = 1
    if spot is not None:
        count = int(spot.get("supply_count") or 0) + 1
        spot["supply_count"] = str(count)
    if spot is None or _spot_types(m["mission_id"]).get(int(spot["spot_id"])) not in DEPLOY_TYPES:
        _rule_points(m, "supply", 1)      # field 17: resupplying away from a Command Post or heliport (player report)
    if spot is not None:
        _use_crate(m, spot)                 # a dropped crate (_crate_plan); the map's own score nothing used
    return {"max_ammo": full[0], "max_mre": full[1], "type5_score": 0, "supply_count": str(count)}


def reinforce_team(state, body):
    """Deploy another echelon on a held HQ/heliport mid-mission."""
    m = _mission(state)
    body = body or {}
    spot = _spot_of(m, body.get("spot_id")) if m is not None else None
    if spot is None:
        return None
    team = str(body.get("team_id") or 0)
    spot["team_id"] = team
    m["team_pos"][team] = spot["spot_id"]
    if team not in m["teams"]:
        m["teams"].append(team)
    m["ap"] = max(0, int(m.get("ap") or 0) - 1)     # deploying costs 1 AP
    return _reveal(state, m, {"ap": m["ap"], "type5_score": 0})


# --- night maps -------------------------------------------------------------------------
#
# On night maps (mission.special_type 1) the server hides every enemy the player cannot see;
# the client only draws the fog (DeploymentSpotController$$GetNightCurrentShowSpots). Vision,
# as the client computes it (DeploymentSpotController$$CurrentNightEffect / RadarEffect):
#   echelon with a handgun (gun type 1): its spot and the spots next to it (night_hand_gun_range 1)
#   echelon without one: only its own spot
#   Coalition echelon: always range 1
#   radar node held by Griffin: range 2 (night_radar_range); a spot with special_eft 1 is a
#   radar (SpotInfo$$Init makes its type SpotType.Radar, 4)
#   Illumination Fairy (strategy skill 15): range 2 around the lit spot while it lasts
# Range counts steps over links in either direction.
#
# Enemies reach the client as "night_enemy" entries ({enemy_team_id, from_spot_id, to_spot_id,
# boss_hp, enemy_hp_percent (float), enemy_instance_id (long), enemy_ai, enemy_ai_para (str),
# hp_percent (float), hostage_id, hostage_hp}; DeploymentController$$AnalysisNightEnemy).
# In startEnemyTurn (playEnemyMove) an entry is a move from -> to, and the client creates the
# enemy at from_spot_id if it has not seen it yet. Everywhere else only from == to entries are
# used: "an enemy is here". The client has no message that removes an enemy it has seen, so a
# seen enemy stays tracked (m["known"]: instance -> spot) and its moves are always reported.
# The client looks each one up by instance id (DeploymentEnemyTeamController$$Init), and a miss
# throws out of the whole reply handler, so every reply with new enemies also has
# enemy_instance_info: an object, not a string (MissionAction$$ReadEnemyTeamData with readAction
# false, in AnalysisNightEnemy and every Deployment handler), read before night_enemy.

NIGHT = 1
GUN_HG = 1
HG_RANGE, COALITION_RANGE, RADAR_RANGE, LIGHT_RANGE = 1, 1, 2, 2
ILLUMINATION = 15             # mission_skill_config.skill_group_id of the Illumination Fairy
SOURCE_FAIRY = 99921          # SourceType.fairy


def is_night(mid):
    return int(_missions().get(int(mid), {}).get("special_type") or 0) == NIGHT


@lru_cache(maxsize=1)
def _gun_types():
    return {int(r["id"]): int(r["type"]) for r in stc.table("gun")}


@lru_cache(maxsize=None)
def _radar_spots(mid):
    return {int(r["id"]) for r in _spots_by_mission().get(mid, []) if str(r.get("special_eft") or "0") == "1"}


@lru_cache(maxsize=1)
def _mission_skills():
    return {int(r["id"]): r for r in stc.table("mission_skill_config")}


@lru_cache(maxsize=1)
def _special_spots():
    return {int(r["id"]): r for r in stc.table("special_spot_config")}


def _team_range(state, team):
    types = _gun_types()
    has_hg = any(str(g.get("team_id")) == str(team) and types.get(int(g.get("gun_id") or 0)) == GUN_HG
                 for g in state.get("gun_with_user_info", []))
    return HG_RANGE if has_hg else 0


def _friend_range(f):
    """A friend's echelon sees as ours do: a Coalition one range 1, dolls 1 with a handgun, else
    only its own spot."""
    if f.get("kind") == "sangvis":
        return COALITION_RANGE
    types = _gun_types()
    guns = ((f.get("team") or {}).get("guns") or {}).values()
    return HG_RANGE if any(types.get(int(g.get("gun_id") or 0)) == GUN_HG for g in guns) else 0


def _lights(m):
    """Illumination still burning: [{"spot", "until"}] (lit while turn < until)."""
    m["lights"] = [l for l in m.get("lights", []) if int(m["turn"]) < int(l["until"])]
    return m["lights"]


def visible_spots(state, m):
    """Spots the player can see on a night map."""
    mid = m["mission_id"]
    sources = [(int(s), _team_range(state, t)) for t, s in m["team_pos"].items()]
    sources += [(int(s), COALITION_RANGE) for s in m.get("sangvis_pos", {}).values()]
    sources += [(int(f["spot"]), _friend_range(f)) for f in (m.get("friends") or {}).values()]
    radars = _radar_spots(mid)
    sources += [(int(s["spot_id"]), RADAR_RANGE) for s in m["spots"]
                if int(s["spot_id"]) in radars and s["belong"] == BELONG_OURS]
    sources += [(int(l["spot"]), LIGHT_RANGE) for l in _lights(m)]
    sources += _vision_sources(m) + _buff_vision(m)
    nbrs, seen = _neighbours(mid), set()
    for start, reach in sources:
        ring = {start}
        for _ in range(reach):
            ring |= {n for s in ring for n in nbrs.get(s, ())}
        seen |= ring
    return seen


def _night_entry(spot, frm, to):
    hp = float(spot["enemy_hp_percent"] or 1)
    return {"enemy_team_id": int(spot["enemy_team_id"]), "from_spot_id": int(frm), "to_spot_id": int(to),
            "boss_hp": int(spot["boss_hp"] or 0), "enemy_hp_percent": hp,
            "enemy_instance_id": int(spot["enemy_instance_id"]), "enemy_ai": int(spot["enemy_ai"] or 0),
            "enemy_ai_para": str(spot["enemy_ai_para"] or "0"), "hp_percent": hp,
            "hostage_id": int(spot.get("hostage_id") or 0), "hostage_hp": int(spot.get("hostage_hp") or 0)}


def _enemy_instances(m, reply, ids):
    """Add enemy_instance_info for these instance ids, if any are on the map."""
    ids = {str(i) for i in ids}
    info = {}
    for s in _enemy_spots(m):
        if s["enemy_instance_id"] in ids:
            e = _night_entry(s, s["spot_id"], s["spot_id"])
            info[s["enemy_instance_id"]] = {k: e[k] for k in ("enemy_team_id", "boss_hp", "enemy_hp_percent", "enemy_ai", "enemy_ai_para")}
    if info:
        reply["enemy_instance_info"] = info


def _hidden_view(state, m, with_known=False):
    """spot_act_info as the player sees it: on night maps, enemies out of sight left out (with_known:
    except those already seen, whose moves the client keeps getting, as a resumed map needs them)."""
    if not is_night(m["mission_id"]):
        return _with_friends(m, m["spots"])
    seen, known = visible_spots(state, m), m.setdefault("known", {})
    out = []
    for s in m["spots"]:
        if str(s["enemy_instance_id"]) != "0":
            if int(s["spot_id"]) in seen:
                known[s["enemy_instance_id"]] = int(s["spot_id"])
            elif with_known and s["enemy_instance_id"] in known:
                known[s["enemy_instance_id"]] = int(s["spot_id"])
            else:
                s = dict(s, **_NO_ENEMY)
        out.append(s)
    return _with_friends(m, out)


def _reveal(state, m, reply):
    """Add night_enemy entries for enemies that just came into sight (night maps only), and the
    map item totals (trigger_para) to any reply that lacks them."""
    if m is not None and isinstance(reply, dict) and "trigger_para" not in reply and m.get("items"):
        reply["trigger_para"] = _trigger_para(m)
    if m is None or state.get("_mission") is not m or not is_night(m["mission_id"]):
        return reply
    seen, known = visible_spots(state, m), m.setdefault("known", {})
    alive = {s["enemy_instance_id"] for s in _enemy_spots(m)}
    for inst in [i for i in known if i not in alive]:
        del known[inst]
    found = []
    for s in _enemy_spots(m):
        sid = int(s["spot_id"])
        if sid in seen and known.get(s["enemy_instance_id"]) != sid:
            found.append(_night_entry(s, sid, sid))
            known[s["enemy_instance_id"]] = sid
    if found:
        reply.setdefault("night_enemy", []).extend(found)
        _enemy_instances(m, reply, {e["enemy_instance_id"] for e in found})
    return reply


def _night_moves(state, m, moves, grow):
    """startEnemyTurn on a night map: the moves the player can follow (an enemy already seen,
    or one stepping into sight or onto an echelon) as night_enemy entries, and the spawns in
    sight. Called after the moves were applied."""
    seen, known = visible_spots(state, m), m.setdefault("known", {})
    ours = _echelon_spots(m)
    shown = []
    for mv in moves:
        inst, frm, to = str(mv["enemy_instance_id"]), mv["from_spot_id"], mv["to_spot_id"]
        attack = to in ours
        if inst not in known and to not in seen and not attack:
            continue
        shown.append(_night_entry(_spot_of(m, frm if attack else to), frm, to))
        known[inst] = frm if attack else to     # an attacker stays put until battleFinish
    grow = [g for g in grow if g["spot_id"] in seen]
    for g in grow:
        known[str(g["enemy_instance_id"])] = g["spot_id"]
    return shown, grow


def fairy_skill_perform(state, body):
    """Mission/fairySkillPerform {fairy_team_id, mission_skill_config_id, ally_instance_id,
    fairy_spot, spot_id: [ids]}: the skill's special spots and buffs (see the skill effects
    section), its cooldown, and night_enemy for what an Illumination light reveals."""
    m = _mission(state)
    body = body or {}
    cfg = _mission_skills().get(int(body.get("mission_skill_config_id") or 0)) if m is not None else None
    if cfg is None:
        return None
    team = int(body.get("fairy_team_id") or 0)
    targets = body.get("spot_id")
    targets = _ids(",".join(str(t) for t in targets) if isinstance(targets, list) else targets)
    from . import account
    account.spend_ssoc(state, cfg.get("consumption"))     # the client takes the same off its count
    if int(cfg.get("is_airborne") or 0) and targets:
        _airdrop(m, cfg, team, targets[0])
        if str(m["team_pos"].get(str(team))) == str(targets[0]):
            # landing counts as moving there for special spots' move triggers (recorded 2026-11-09 on
            # 90040: a drop on 80625 set off the hideout 9334950 on 80624, detect_range 2, which gave
            # way to its 9334951 in this reply); their hurts wait for the next reply that carries them
            hurts = _enter_hazards(state, m, targets[0], ("team", str(team)))
            if hurts:
                _effects(m).setdefault("pending_hurts", []).extend(hurts)
    reply = _cast_skill(state, m, cfg, SOURCE_FAIRY, team, targets, ("team", str(team)))
    return _reveal(state, m, reply)


def _airdrop(m, cfg, team, target):
    """Parachute Fairy (is_airborne skills): the echelon drops onto the target spot (a heliport in
    range, chosen by the client) and carries airborne_mission_buff_config_id. The client flies the
    echelon itself (the reply callback calls DeploymentTeamController$$Fly, which moves it, locks input
    with DeploymentController.playAniming and unlocks after FlyComplete -> CheckBattle), so only our
    copy of the map moves here. Nothing about the move goes in the reply: spot_teleport_result or
    spot_act_info there make the client move the same echelon a second time, the flight never
    completes and the map stays locked."""
    src, dst = _spot_of(m, m["team_pos"].get(str(team))), _spot_of(m, target)
    if src is None or dst is None or dst["team_id"] != "0" or int(dst["enemy_team_id"] or 0):
        return
    src["team_id"], dst["team_id"] = "0", str(team)
    m["team_pos"][str(team)] = dst["spot_id"]
    buff = int(cfg.get("airborne_mission_buff_config_id") or 0)
    if buff in _mission_buffs():
        _effects(m)["buffs"][_next_instance(m)] = {"kind": "team", "unit": str(team), "buff_id": buff,
                                                  "skill": int(cfg["id"]), "source_type": SOURCE_FAIRY,
                                                  "source_value": team, "start_turn": int(m["turn"])}


def sangvis_move(state, body):
    """Mission/sangvisMove, or teamMove with person_type 2: a Coalition echelon moves. Only its
    position is tracked (night vision); a fight on arrival is left to the client."""
    m = _mission(state)
    body = body or {}
    dst = _spot_of(m, body.get("to_spot_id")) if m is not None else None
    if dst is None:
        return None
    team = str(body.get("person_id") or 0)
    src = _spot_of(m, body.get("from_spot_id"))
    if _swap(m, src, dst, "sangvis", team):
        return _reveal(state, m, {"ap": int(m.get("ap") or 0), "type5_score": 0})
    cost = _move_cost(m, "sangvis", team)
    _count_move(m, "sangvis", team, at=dst["spot_id"])
    if src is not None and src["sangvis_team_id"] == team:
        src["sangvis_team_id"] = "0"
        if str(src.get("hostage_id") or "0") != "0" and str(src.get("team_id") or "0") == "0" \
                and str(dst.get("hostage_id") or "0") == "0" and not _hostile_here(m, dst):
            # a Coalition echelon takes a hostage along, shown on its spot (10199: the one on 10815
            # was on 10817 with it two moves later, recorded)
            dst.update({k: src[k] for k in HOSTAGE_FIELDS})
            src.update(hostage_id="0", hostage_hp="0", hostage_max_hp="0")
    dst["sangvis_team_id"] = team
    m.setdefault("sangvis_pos", {})[team] = dst["spot_id"]
    if not _hostile_here(m, dst):
        # recorded on map 126: a Coalition echelon's move onto an enemy (its attack) costs no AP;
        # any other move costs 1
        m["ap"] = max(0, int(m.get("ap") or 0) - cost)
    if _hostile_here(m, dst):
        # the client fights here and reports it with Mission/sangvisBattleFinish
        m["pending_battle"] = {"team": team, "spot": dst["spot_id"], "from": src["spot_id"] if src else "",
                               "sangvis": True}
        reply = {"ap": m["ap"], "type5_score": 0}
        for cond in (ALLY_ON_SPOT, ALLY_ON_ENTER):      # 105: onto 9278, before the fight (recorded)
            _merge_ally(reply, ally_changes(m, cond, dst["spot_id"], reply))
        return _reveal(state, m, _with_steps(m, reply))
    reply = _hazard_reply(state, m, dst["spot_id"], ("sangvis", team), {"ap": m["ap"], "type5_score": 0})
    for cond in (ALLY_ON_SPOT, ALLY_ON_ENTER):          # 10199: onto 10817 (recorded)
        _merge_ally(reply, ally_changes(m, cond, dst["spot_id"], reply))
    if "mission_lose_result" in reply:
        return _reveal(state, m, reply)
    # a goal it reaches counts at once, as for dolls (10637, recorded: the move onto the northeast
    # bar 73244 finished step 1063702 in that reply)
    return _reveal(state, m, _check_win(state, m, _effect_keys(m, reply)))


def withdraw_sangvis(state, body):
    """Mission/withdrawSangvisTeam {spot_id}."""
    m = _mission(state)
    spot = _spot_of(m, (body or {}).get("spot_id")) if m is not None else None
    if spot is None:
        return None
    if m["sangvis_pos"].pop(spot["sangvis_team_id"], None) is not None:
        _repair_sangvis(state, spot["sangvis_team_id"])
        _echelon_out(m, spot)
    spot["sangvis_team_id"] = "0"
    return _check_loss(state, m, {"type5_score": 0})


def reinforce_sangvis(state, body):
    """Mission/reinforceSangvisTeam {sangvis_team_id, spot_id} (RequestSangvisReinforce$$.ctor):
    deploy a Coalition echelon mid-mission; reply {"ap"} (read unguarded by
    DeploymentTeamInfoController$$RequestSangvisTeamReinforceHandle)."""
    m = _mission(state)
    body = body or {}
    spot = _spot_of(m, body.get("spot_id")) if m is not None else None
    team = str(body.get("sangvis_team_id") or body.get("team_id") or 0)
    if spot is None or team == "0":
        return {"ap": m["ap"]} if m is not None else None
    spot["sangvis_team_id"] = team
    m["sangvis_pos"][team] = spot["spot_id"]
    m["ap"] = max(0, int(m.get("ap") or 0) - 1)     # deploying costs 1 AP
    reply = {"ap": m["ap"]}
    chips = _chip_skills(state, m, teams=[team])
    if chips:
        reply = _effect_keys(m, _merge_replies(chips + [reply]))
    return _reveal(state, m, reply)


def _fill_spot(state, m, spot):
    """Fill whatever of ours stands on a spot (doll echelon first); its full (ammo, mre) or None."""
    if spot["team_id"] != "0":
        return _fill(state, m, "team", spot["team_id"])
    if _own_sangvis(spot["sangvis_team_id"]):
        full = _fill(state, m, "sangvis", spot["sangvis_team_id"])
        return str(full[0]), str(full[1])
    squads = [str(i) for i in spot.get("squad_instance_ids") or []]
    if squads:
        full = _fill(state, m, "squad", _squad_uid(m, squads[0]))
        return str(full[0]), str(full[1])
    if int(spot.get("vehicle_with_user_id") or 0):
        return _fill(state, m, "vehicle", spot["vehicle_with_user_id"])
    return None


def supply_in_mission(state, body):
    """Mission/supplySangvis / supplySquad: as supplyTeam."""
    return supply_team(state, body)


def quick_fix_in_mission(state, body):
    """Mission/quickFixGun / quickFixSangvis {spot_id, team_id | sangvis_team_id, ally_instance_id,
    gun_with_user_ids | sangvis_with_user_ids}: repair on the map; reply {"fix_count", "type5_score"}
    (RequestMissionFix)."""
    m = _mission(state)
    body = body or {}
    if m is None:
        return None
    for gid in body.get("gun_with_user_ids") or []:
        workshop._heal(state, "gun", gid)
    for sid in body.get("sangvis_with_user_ids") or []:
        workshop._heal(state, "sangvis", sid)
    spot = _spot_of(m, body.get("spot_id"))
    count = 1
    if spot is not None:
        spot["fix_count"] = str(int(spot.get("fix_count") or 0) + 1)
        count = int(spot["fix_count"])
    # Mission/quickFixVehicle (RequestMissionFixVehicle: vehicle_with_user_id) costs field 23
    _rule_points(m, "ma_repair" if body.get("vehicle_with_user_id") else "repair", -1)
    if spot is not None and _free_repair_spot(m, spot):
        _rule_points(m, "repair_point")
    return {"fix_count": count, "type5_score": 0}


SPOT_REPAIR = 8      # spot.type 8: a repair point
SPOT_CRATE = 5       # spot.type 5: a supply crate (Isomer+ node scores, player report: a crate 10000)

# Crates some score maps drop at the start of each of our turns, turn 1 too (player report): base +
# kills so far // 7 of them. They reach the client as new_spot_change, a JSON string of
# [{spot_id, type, start_turn, end_turn, can_use_count, use_count}] that startMission and startTurn
# read (DeploymentController$$RequestStartMissionHandle / RequestStartTurnHandle ->
# MissionAction$$ReadChangeSpot): the spot is that type for those turns.
# The user: a crate lasts only the turn it comes (the next turn's replace it), one resupply uses
# it up, and the kills are our own (enemy_die). The client won't resupply a full echelon.
# How many: mission.supply_parameter "<crates a turn>;<kills>-<more crates per that many kills>;
# <points a crate>" (10508 "2;7-1;10000" and 10766 "7;7-1;10000" are the rule reported by playerss for Hornet's
# Nest+ and Hurricane Rescue+; Scorpion Vortex 10674 "4;999-1;30000": "4 crates will spawn every
# turn ... Using a supply crate gives you 30k points", the MS guide). Points 0: event_score's
# field 7. Only maps without a supply line have it (mission types 3 and 5).


@lru_cache(maxsize=None)
def _crate_plan(mid):
    """(crates a turn, kills, more crates per those kills, points a crate) or None."""
    parts = str((_missions().get(int(mid)) or {}).get("supply_parameter") or "").split(";")
    num = lambda x: int(x) if str(x).strip().isdigit() else 0
    if not parts or not num(parts[0]):
        return None
    kills, _, more = (parts[1] if len(parts) > 1 else "").partition("-")
    return num(parts[0]), num(kills), num(more), num(parts[2] if len(parts) > 2 else 0)
# Where they come: the map's spots that start as normal ones (type 2), not random nodes, and
# Hornet's Nest+: without one of its buildings 390102-390109 (player report); Hurricane Rescue+: with
# building 45010006 (unnamed, no skills, on 42 normal spots; INFERRED to be the marker); other maps:
# without a building (Scorpion Vortex: "any L and R node except L19 and L22", its two buildings;
# ASSUMED for the rest). Never a hidden node (Scorpion Vortex: none on the right side before it is
# revealed). A spot a unit stands on gets none (GUESS).
CRATE_SPOT_RULE = {
    10508: lambda b: not 390102 <= b <= 390109,
    10766: lambda b: b == 45010006,
}
CRATE_SPOT_DEFAULT = lambda b: b == 0
# Maps whose crate nodes the guides name. Vortex of Secrets 10520: "among the 4 nodes X23, X24, X30
# and X35, 3 crates will spawn randomly" (the DR guide; Hole 1 is this map): X23/X24/X30 the
# inverted triangle 92415/92414/92413 behind the rubbles X32/X34 (92417, 92511), X35 92509, the
# first node past the lift X39 (92510). Checked against mis's labelled map (rank_guides/DR_1_map.png).
CRATE_NODES = {10520: frozenset({92413, 92414, 92415, 92509})}


@lru_cache(maxsize=None)
def _crate_spots(mid):
    if _for_map(CRATE_NODES, mid):
        return _for_map(CRATE_NODES, mid)
    ok = _for_map(CRATE_SPOT_RULE, mid, CRATE_SPOT_DEFAULT)
    return frozenset(int(r["id"]) for r in _spots_by_mission().get(mid, [])
                     if int(r["type"]) == 2 and str(r.get("random_get") or "0") in ("", "0")
                     and ok(int(r["building_id"] or 0)))


def _drop_crates(m, rng=random):
    """The crates this turn drops (see _crate_plan), as new_spot_change, or None."""
    plan = _crate_plan(m["mission_id"])
    if plan is None:
        return None
    base, per, more = plan[:3]
    turn = int(m["turn"])
    m["crates"] = {k: c for k, c in (m.get("crates") or {}).items() if int(c["end_turn"]) >= turn}
    taken = (_echelon_spots(m) | _ally_spots(m) | _squad_spots(m) | {int(x["spot_id"]) for x in _enemy_spots(m)}
             | {int(k) for k in m["crates"]})
    # never on a hidden node: they come at the start of the turn after it is revealed (player report, from
    # a live video of Vortex of Secrets: the triangle 92413-92415's crates came the turn after it opened)
    taken |= {int(s["spot_id"]) for s in m["spots"] if _hidden(s)}
    free = sorted(_crate_spots(m["mission_id"]) - taken)
    want = base + (int(m.get("enemy_die") or 0) // per * more if per else 0)
    new = []
    for spot in rng.sample(free, min(want, len(free))):
        crate = {"spot_id": spot, "type": SPOT_CRATE, "start_turn": turn, "end_turn": turn,
                 "can_use_count": 1, "use_count": 0}
        m["crates"][str(spot)] = crate
        new.append(crate)
    return json.dumps(new, separators=(",", ":")) if new else None


# Silent Sandtable (11946): supply packs and portals, server-only like its spawns. Recorded
# (packet log 2026-11-08): startMission lays out the whole schedule as marker special spots, cast
# with source_type / source_value -1 and the marker's own skill: for the k-th of turns 2-7, marker
# 770011+k (skill 770011+k, which also puts 770000 there; it lasts k+1 turns) on 2 of the Central
# Area's 12 pack nodes and 1 of the outer ring's 6, and portal marker 770111+k (skill 770131+k) on
# 1 of the 6 portal nodes; each node once. At the start of that turn each marker gives way to a
# supply pack 770010 (99 turns: until Collect Supplies 770017 / 770018 takes it) or a portal
# 770110 (1 turn), with the marker's skill. The Central Area is the 17 spots within 900 of the
# Commander's Workstation; its pack nodes are those but for the 4 hidden spawners (building 770008)
# and the Workstation. A Central pack scores field 18's 10000 (770017); the outer ones none, and
# their ambush (770018) is the client's.
SANDTABLE = 11946
SANDTABLE_OUTER = (88856, 88889, 88892, 88865, 88835, 88802)      # player report
SANDTABLE_PORTALS = (88828, 88819, 88845, 88863, 88872, 88890)    # player report
SANDTABLE_TURNS = 6                                                 # turns 2-7 (markers 770011-770016)
NO_SOURCE = -1


@lru_cache(maxsize=None)
def _sandtable_packs(mid):
    rows = _spots_by_mission().get(mid, [])
    return tuple(sorted(int(r["id"]) for r in rows
                        if abs(int(r["coordinator_x"])) <= 900 and abs(int(r["coordinator_y"])) <= 900
                        and str(r["belong"]) != "99" and int(r["building_id"] or 0) not in (770000, 770008)))


def _sandtable_schedule(m, rng=random):
    """startMission: lay out the markers (see SANDTABLE). True when this map has them."""
    if int(m["mission_id"]) != SANDTABLE:
        return False
    central, outer, portals = list(_sandtable_packs(SANDTABLE)), list(SANDTABLE_OUTER), list(SANDTABLE_PORTALS)
    for lst in (central, outer, portals):
        rng.shuffle(lst)
    for k in range(SANDTABLE_TURNS):
        for spot in central[2 * k:2 * k + 2] + outer[k:k + 1]:
            _add_special(m, spot, 770011 + k, 770011 + k, NO_SOURCE, NO_SOURCE)
            _add_special(m, spot, 770000, 770011 + k, NO_SOURCE, NO_SOURCE)
        if k < len(portals):
            _add_special(m, portals[k], 770111 + k, 770131 + k, NO_SOURCE, NO_SOURCE)
    return True


def _sandtable_turn(m):
    """startTurn, before the markers run out: this turn's markers become packs and portals."""
    if int(m["mission_id"]) != SANDTABLE:
        return
    k = int(m["turn"]) - 2
    if not 0 <= k < SANDTABLE_TURNS:
        return
    for sp in list(_effects(m)["specials"].values()):
        if sp["config"] == 770011 + k:
            _add_special(m, int(sp["spot"]), 770010, sp["skill"], NO_SOURCE, NO_SOURCE)
        elif sp["config"] == 770111 + k:
            _add_special(m, int(sp["spot"]), 770110, sp["skill"], NO_SOURCE, NO_SOURCE)


# The Central Area's URNC forces come in through its four doors (the belong-99 spots 1200 from
# the Workstation), one on each at the start of every turn (a player's table; recorded 2026-11-08,
# turns 1-4): turn 1's are on the map at startMission, the later ones go out in startTurn's
# summon_ally {"<instance>": <its ally_instance_info entry, with spot_id>} (read by
# MissionAction$$AnalysicsMissionGrowEnemy), and they walk in on the enemy turn. A door something
# stands on gets none (GUESS). The corridor forces and the boss: SANDTABLE_CORRIDORS below.
SANDTABLE_DOORS = {"updown": (88908, 88911), "leftright": (88909, 88910)}
SANDTABLE_WAVES = {      # turn: (up/down, left/right) URNC team
    1: (770001, 770001), 2: (770001, 770002), 3: (770003, 770002), 4: (770003, 770004),
    5: (770005, 770004), 6: (770005, 770006), 7: (770006, 770006),
}


def _door_wave(turn):
    """[(door spot, URNC team)] for this turn, doors in spot order."""
    teams = SANDTABLE_WAVES.get(int(turn))
    if teams is None:
        return []
    return sorted([(d, teams[0]) for d in SANDTABLE_DOORS["updown"]] + [(d, teams[1]) for d in SANDTABLE_DOORS["leftright"]])


# NPCs the server adds that the stc's spots leave out. Vortex of Secrets+ 11497 (recorded
# 2026-11-12: ally instances 1-5 = 6630005, 6630002, 6630004, 6630001, 6630003, numbered in spot
# order): the Goddess of the Spring 6630003 stands on the fountain's dead end 600299 (seen there once
# a unit reached 600290, her betray_number). The Battered Doll 6630002 (betray_number 600121) is
# ASSUMED on 600122, the dead end past 600121, as the base map's Doll (betray 92420 = X26) is on
# X27 = 92421, the dead end past it (the DR guide: "a hidden NPC on X27, which will appear if you
# step on X26"); 600122 also fits the instance order (between 600105 and 600170). The Scapegoat
# 6630001 (instance 4: somewhere between 600170 and 600299) never showed and isn't placed.
# Operation Mistbuster 10675, Area 4 (the MS guide and its labelled map: D8 93692, D12 93688, D13
# 93689, D15 93704, D16 93707, D18 93700, D19 93701, D21 93703, Z8 93711): the prisoners 44440005-08
# on D16 D18 D19 D21 (hostages once a unit steps on D4 / D5, their transform_number), the prisoner
# 44440009 on D15 (a Smasher once a unit steps on D19 / D21, its betray_number), the Prison Guards
# 44440010 / 11 on D8 and Z8, Commander 44440012 on D12 and Machlian 44440013 on D13 (on our side
# from turn 10, their betray_number). Which prisoner team stands on which of the four: ASSUMED.
# Vortex of Secrets 10520 (player report): the Battered Doll 9411217 (betray_number 92420) on X27 = 92421,
# and the Fairy of the Lake 9411218 (betray_number 92589; leaves after an axe choice 9411239 /
# 9411240 / 9411244) on 92598, the dead end past 92589, as 11497's Goddess of the Spring.
EXTRA_ALLIES = {11497: [(600122, 6630002), (600299, 6630003)],
                10520: [(92421, 9411217), (92598, 9411218)],
                10675: [(93707, 44440005), (93700, 44440006), (93701, 44440007), (93703, 44440008),
                        (93704, 44440009), (93692, 44440010), (93711, 44440011),
                        (93688, 44440012), (93689, 44440013)]}


def _start_allies(mid):
    """Forces the server adds to a map's starting ones (Silent Sandtable's turn-1 door wave, EXTRA_ALLIES)."""
    return (_door_wave(1) if int(mid) == SANDTABLE else []) + EXTRA_ALLIES.get(int(mid), [])


def _summon_doors(m):
    """startTurn: this turn's door wave, as summon_ally, or None."""
    if int(m["mission_id"]) != SANDTABLE:
        return None
    taken = _taken(m)
    out = {}
    turn, boss, at = SANDTABLE_BOSS
    waves = _door_wave(m["turn"]) + ([(at, boss)] if int(m["turn"]) == turn else [])
    for door, team in sorted(waves):
        if door in taken:
            continue
        iid = _new_ally(m, team, _spot_of(m, door))
        if iid is not None:
            out[iid] = dict(_ally_json(m, m["allies"][iid]), spot_id=str(door))
    return out or None


# The outer ring's corridors (belong-99 spots in six groups) send URNC forces out too.
# startMission marks each group's spots with its special spot 770002-770007 (skills 770002-770007,
# source 99910 / the spot; 4 turns) and puts one force on each, an even pick from its group's list
# (recorded 2026-11-08); then at the end of every one of our turns (player report) each corridor spot
# nothing stands on gets another (recorded: a spot still held got none). The list is the summoning
# skill's allyteam_summoner: while the marker is there (turns 1-4) 770067-770072's (trigger
# "marker > 0": 770021-770035), after it 770073-770078's ("marker == 0": 770036-770050, turns 5-7,
# player report). Sent as fairy_skill_return.allyteam_summoner [{ally_instance_id, spot_id,
# ally_instance_info}] (endTurn: DeploymentController$$RequestEndAllFriendTurnHandle reads it with
# MissionAction$$LoadSkillData). At the start of turn 4 the boss force 770061 (200000 HP) comes in
# on 88895 with the door wave, once (recorded; player report).
SANDTABLE_CORRIDORS = {      # marker: (its spots, summoning skill with the marker, without it)
    770002: ((88896, 88897, 88898), 770067, 770073), 770003: ((88899, 88900, 88901), 770068, 770074),
    770004: ((88902, 88903, 88904), 770069, 770075), 770005: ((88905, 88906, 88907), 770070, 770076),
    770006: ((88912, 88913), 770071, 770077), 770007: ((88914, 88915), 770072, 770078),
}
CORRIDOR_MARKED = 4      # the markers' turns (special_spot_config duration_time)
MARKER_SOURCE = 99910
SANDTABLE_BOSS = (4, 770061, 88895)      # turn, ally team, spot


def _taken(m):
    return _echelon_spots(m) | _ally_spots(m) | _squad_spots(m) | {int(x["spot_id"]) for x in _enemy_spots(m)}


def _corridor_markers(m):
    for marker, (spots, _, _) in SANDTABLE_CORRIDORS.items():
        for spot in spots:
            _add_special(m, spot, marker, marker, MARKER_SOURCE, spot)


def _corridor_wave(m, rng=random):
    """This turn's corridor forces, as allyteam_summoner entries, or []."""
    if int(m["mission_id"]) != SANDTABLE:
        return []
    out = []
    for marker, (spots, marked, after) in sorted(SANDTABLE_CORRIDORS.items()):
        skill = marked if int(m["turn"]) <= CORRIDOR_MARKED else after
        teams = _ids(_mission_skills().get(skill, {}).get("allyteam_summoner"))
        for spot in spots:
            if not teams or spot in _taken(m):
                continue
            iid = _new_ally(m, rng.choice(teams), _spot_of(m, spot))
            if iid is not None:
                out.append({"ally_instance_id": int(iid), "spot_id": spot,
                            "ally_instance_info": _ally_json(m, m["allies"][iid])})
    return out


# The Commander (ally teams 770007-770010, its armor level 0-3 as it is upgraded: each upgrade
# turns it into the next team, at full HP) has the HP of its doll, gun_in_ally 770000 (429). A
# no-battle meet with a URNC force costs ceil(429 * (CE / 10000 - armor / 10)) of it (player report;
# fits all 11 recorded meets), the force's enemy team's CE; a 770053 (Vigor, a supply pack) on
# its spot gives back half its HP, rounded down (recorded: +214). Sent as noBattleMeet's
# nobattle_ally_life_change "myside" {"<gun_in_ally id>": HP left}; at 0 it dies and leaves the
# map (died_this_section). At the start of our turns it recovers like a doll (_turn_recovery).
COMMANDER_ARMOR = {770007: 0, 770008: 1, 770009: 2, 770010: 3}
COMMANDER_HEAL = 770053


def _commander_gun(a):
    gid = (_ids(_ally_teams().get(int(a["ally_team_id"]), {}).get("guns")) or [0])[0]
    return gid, int(_gun_in_ally().get(gid, {}).get("life") or 0)


def _commander_on(m, spot_id):
    for iid in (_spot_of(m, spot_id) or {}).get("ally_instance_ids") or []:
        a = (m.get("allies") or {}).get(str(iid))
        if a is not None and int(a["ally_team_id"]) in COMMANDER_ARMOR:
            return str(iid), a
    return None, None


def _commander_hit(m, a, enemy_team):
    gid, full = _commander_gun(a)
    ce = int((_enemy_teams().get(int(enemy_team or 0)) or {}).get("effect_ext") or 0)
    lost = max(0, math.ceil(full * (ce / 10000 - COMMANDER_ARMOR[int(a["ally_team_id"])] / 10)))
    a["life"] = max(0, int(a.get("life", full)) - lost)
    return gid, a["life"]


def _commander_heal(m, spot_id):
    iid, a = _commander_on(m, spot_id)
    if a is not None:
        gid, full = _commander_gun(a)
        a["life"] = min(full, int(a.get("life", full)) + full // 2)


def _commander_dies(m, iid, a, reply):
    """At 0 HP the Commander dies and leaves the map (player report)."""
    if int(a.get("life", 1)) > 0:
        return
    _remove_ally(m, iid)
    _ally_left(reply, a["ally_team_id"])


# Recovery: at the start of our turn, on a map whose integration_switch has 1-1 (nearly all),
# every unit of ours that is hurt but alive gets back its Recovery stat in HP, up to full (the
# user): dolls in echelons on the map (factory.gun_rec), Coalition units of our Coalition echelons
# (_sangvis_base "rec", times resolution_number) and the Commander (its gun_in_ally doll's
# gun_rec: 111 a turn). Sent as gun_life_after_rec {"<gun_with_user_id>": HP},
# sangvis_life_after_rec {"<sangvis_with_user_id>": HP} and ally_life_after_rec {"<instance>":
# {"<gun_in_ally id>": HP}} (MissionAction$$AnalysicsRecoveryData; the Commander's recorded once).
RECOVER_SWITCH = "1-1"


@lru_cache(maxsize=None)
def _recovers(mid):
    return RECOVER_SWITCH in str(_missions().get(int(mid), {}).get("integration_switch") or "").split(";")


def _turn_recovery(state, m):
    out = {}
    if not _recovers(m["mission_id"]):
        return out
    for team in list(m.get("team_pos") or {}):
        for g in _team_guns(state, team):
            if int(g.get("gun_id") or 0) not in factory.guns():
                continue
            life, full = int(g.get("life") or 0), workshop.max_life(state, "gun", g)
            if 0 < life < full:
                rec = factory.gun_rec(int(g["gun_id"]), int(g.get("gun_level") or 1), int(g.get("number") or 1))
                if rec > 0:
                    workshop.set_life(state, "gun", g, life + rec)
                    out.setdefault("gun_life_after_rec", {})[str(g["id"])] = int(g["life"])
    for team in list(m.get("sangvis_pos") or {}):
        if not _own_sangvis(team):
            continue
        for u in _team_units(state, "sangvis", team)[1]:
            life, full = int(u.get("life") or 0), workshop.max_life(state, "sangvis", u)
            rec = _sangvis_base(u, "rec")
            if 0 < life < full and rec > 0:
                workshop.set_life(state, "sangvis", u, life + rec)
                out.setdefault("sangvis_life_after_rec", {})[str(u["id"])] = int(u["life"])
    for iid, a in (m.get("allies") or {}).items():
        # a force hurt in battle (_note_ally_life): each living doll its Recovery (recorded 11116:
        # ally_life_after_rec {"3": {"749": 550}}, the hurt doll alone, back to full)
        for gid, life in (a.get("gun_life") or {}).items():
            row = _gun_in_ally().get(int(gid), {})
            gun, full = int(row.get("gun_id") or 0), int(row.get("life") or 0)
            rec = factory.gun_rec(gun, int(row.get("gun_level") or 1), int(row.get("number") or 1)) if gun in factory.guns() else 0
            if 0 < int(life) < full and rec > 0:
                a["gun_life"][gid] = min(full, int(life) + rec)
                out.setdefault("ally_life_after_rec", {}).setdefault(iid, {})[gid] = a["gun_life"][gid]
        if int(a["ally_team_id"]) not in COMMANDER_ARMOR:
            continue
        gid, full = _commander_gun(a)
        life = int(a.get("life", full))
        row = _gun_in_ally().get(gid, {})
        gun = int(row.get("gun_id") or 0)
        rec = factory.gun_rec(gun, int(row.get("gun_level") or 1), int(row.get("number") or 1)) if gun in factory.guns() else 0
        if 0 < life < full and rec > 0:
            a["life"] = min(full, life + rec)
            out.setdefault("ally_life_after_rec", {})[iid] = {str(gid): a["life"]}
    return out


# Portals: a spot's stc auto_teleport "<to,...>|<special spot>|<kind>:<to,...>" sends a unit that
# reaches it on to one of <to> while that special spot is there (11946: 770110). Recorded
# (2026-11-08): an echelon's teamMove onto 88845 with a portal on it answered spot_teleport_result
# [{"from_spot_id": 88845, "to_spot_id": "88890", "target_type": 1, "target_id": "<team>"}] and its
# next move started from 88890. Of two ways, one at random; an occupied one is skipped (player report).
# Only echelons are sent through here (the only kind recorded).
# With no special spot ("92460||0,1,2:0", Vortex of Secrets' holes and lifts and some 30 other maps)
# the way is always open. INFERRED from the stc's shapes: the part before ":" is the sides it sends
# (1 ours; "2" alone, the enemy's ways, isn't used here), the list after it the spots a unit must
# come from (0: any; No More Omens' 73498 "73497||1:73491,73505"), for always-open ways only; the far end's "0:<from>" is only
# the way back's note. A spot holding special spot PORTAL_LOCK (1000001, Vortex of Secrets' lift
# Y41 until the substation powers it: 9411209 takes it off) sends nobody, and a lift (building type
# 22) only once ("this elevator can only be used once", the DR guide).
TELEPORT_ECHELON = 1
PORTAL_LOCK = 1000001
BUILDING_LIFT = 22


@lru_cache(maxsize=None)
def _portals(mid):
    out = {}
    for r in _spots_by_mission().get(mid, []):
        parts = str(r.get("auto_teleport") or "").split("|")
        if len(parts) < 2 or not (parts[1].strip().isdigit() or parts[1].strip() == ""):
            continue
        to = [int(x) for x in parts[0].split(",") if x.strip().isdigit() and int(x)]
        sides, _, froms = (parts[2] if len(parts) > 2 else "1").partition(":")
        if to:
            out[int(r["id"])] = (tuple(to), int(parts[1]) if parts[1].strip() else 0,
                                 frozenset(_ids(sides)) if sides.strip() else frozenset({1}),
                                 frozenset(x for x in _ids(froms) if x))
    return out


def _portal_exit(m, spot, rng=random, came_from=None):
    """Where a unit reaching this spot is sent (an open portal), or None."""
    rule = _portals(m["mission_id"]).get(int(spot["spot_id"]))
    if rule is None:
        return None
    to, needs, sides, froms = rule
    here = [sp["config"] for sp in (m.get("effects") or {}).get("specials", {}).values() if int(sp["spot"]) == int(spot["spot_id"])]
    if needs and needs not in here or PORTAL_LOCK in here or 1 not in sides:
        return None
    if froms and not needs and (came_from is None or int(came_from) not in froms):
        return None                 # the from-list only on always-open ways: 11946's "88890|770110|1:88890" sent
                                    # an echelon coming from 88835 (recorded), so a special spot's portal ignores it
    building = (m.get("buildings") or {}).get(str(spot["spot_id"])) or {}
    lift = int(_buildings().get(int(building.get("building_id") or spot.get("building_id") or 0), {}).get("type") or 0) == BUILDING_LIFT
    if lift and str(spot["spot_id"]) in m.get("lifts_used", []):
        return None
    taken = (_echelon_spots(m) | _ally_spots(m) | _squad_spots(m) | {int(x["spot_id"]) for x in _enemy_spots(m)})
    free = [t for t in to if t not in taken]
    if not free:
        return None
    if lift:
        m.setdefault("lifts_used", []).append(str(spot["spot_id"]))
    return _spot_of(m, rng.choice(free))


def _use_crate(m, spot):
    """A resupply on a dropped crate: used up, scoring field 7 (True), else False."""
    crate = (m.get("crates") or {}).get(str(spot["spot_id"]))
    if crate is None or int(crate["end_turn"]) < int(m["turn"]) or crate["use_count"] >= crate["can_use_count"]:
        return False
    crate["use_count"] += 1
    points = (_crate_plan(m["mission_id"]) or (0, 0, 0, 0))[3]
    if points and score_rule(m["mission_id"]) is not None:
        _add_score(m, points)           # supply_parameter's own points
    else:
        _rule_points(m, "crate")
    return True


def _free_repair_spot(m, spot):
    """A repair point (spot type 8): a repair there also scores field 16 (see score_rule)."""
    return _spot_types(m["mission_id"]).get(int(spot["spot_id"])) == SPOT_REPAIR


# --- HOC (squads) on the map ------------------------------------------------------------
#
# A HOC deployed on the map is a "squad team" with an instance id (m["squads"]: instance ->
# {"squad": squad_with_user_id, "spot", "switch"}); spots list theirs in squad_instance_ids.
# startMission sends them as squad_info, a JSON *string* {"<instance>": {"squad_instance_id",
# "squad_id", "battleskill_switch", "attack_next_turn", "belong", "life"}}
# (MissionAction$$ReadSquadTeam, SquadTeam$$.ctor). HOC do not fight on the map here: their
# support fire happens inside the client's battles.

def _squad_row(state, squad_id):
    squads = state.get("squad_with_user_info") or {}
    if isinstance(squads, dict):
        return squads.get(str(squad_id))
    return next((q for q in squads if str(q["id"]) == str(squad_id)), None)


def _place_squad(state, m, spot_id, squad_id, switch=1):
    spot = _spot_of(m, spot_id)
    if spot is None or not squad_id:
        return None
    inst = int(m.get("next_squad_instance") or 1)
    m["next_squad_instance"] = inst + 1
    m.setdefault("squads", {})[str(inst)] = {"squad": str(squad_id), "spot": spot["spot_id"], "switch": switch}
    spot["squad_instance_ids"] = list(spot.get("squad_instance_ids") or []) + [inst]
    return inst


def _squad_info(m):
    out = {}
    for inst, q in m.get("squads", {}).items():
        out[inst] = {"squad_instance_id": int(inst), "squad_id": int(q["squad"]), "battleskill_switch": q["switch"],
                     "attack_next_turn": int(q.get("attack_next_turn") or 0), "belong": 1}
    return json.dumps(out, separators=(",", ":"))


def _unplace_squad(m, inst):
    q = m.get("squads", {}).pop(str(inst), None)
    if q is not None:
        spot = _spot_of(m, q["spot"])
        if spot is not None:
            spot["squad_instance_ids"] = [i for i in spot.get("squad_instance_ids") or [] if str(i) != str(inst)]
    return q


def squad_move(state, body):
    """Mission/squadMove: the teamMove body with "squad_id" (the HOC's instance) for person_id;
    the same reply ({"ap"}, DeploymentController$$RequestMoveTeamHandle)."""
    m = _mission(state)
    body = body or {}
    dst = _spot_of(m, body.get("to_spot_id")) if m is not None else None
    inst = str(body.get("squad_id") or body.get("person_id") or 0)
    q = m.get("squads", {}).get(inst) if dst is not None else None
    if q is None:
        return None
    _unplace_squad(m, inst)
    m["squads"][inst] = dict(q, spot=dst["spot_id"])
    dst["squad_instance_ids"] = list(dst.get("squad_instance_ids") or []) + [int(inst)]
    m["ap"] = max(0, int(m.get("ap") or 0) - 1)
    if int(dst.get("enemy_team_id") or 0) and dst["team_id"] == "0":
        _hocs_lost(state, m, dst)          # onto an enemy with no echelon there: the HOC dies
    return _reveal(state, m, _occupy_building(state, m, dst["spot_id"], {"ap": m["ap"], "type5_score": 0}))


def reinforce_squad(state, body):
    """Mission/reinforceSquad {spot_id, squad_with_user_id} (RequestSquadReinforce$$.ctor); reply
    {"squad_instance_id", "ap"} (DeploymentTeamInfoController$$RequestSquadReinforceHandle)."""
    m = _mission(state)
    body = body or {}
    if m is None:
        return None
    inst = _place_squad(state, m, body.get("spot_id"), body.get("squad_with_user_id"))
    if inst is None:
        return None
    m["ap"] = max(0, int(m.get("ap") or 0) - 1)
    return {"squad_instance_id": inst, "ap": m["ap"]}


def withdraw_squad(state, body):
    """Mission/withdrawSquad {spot_id}: every key of the reply is optional."""
    m = _mission(state)
    spot = _spot_of(m, (body or {}).get("spot_id")) if m is not None else None
    if spot is None:
        return None
    rule = score_rule(m["mission_id"])
    on_deploy = _spot_types(m["mission_id"]).get(int(spot["spot_id"])) in DEPLOY_TYPES
    for inst in list(spot.get("squad_instance_ids") or []):
        _repair_hoc(state, _hoc_record(state, m, inst))
        _unplace_squad(m, inst)
        if rule is not None:        # 11630: -4000 from a Command Post or heliport, else -5000
            _add_score(m, -(rule["hoc_withdraw_deploy"] if on_deploy else rule["hoc_out"]))
    return {"type5_score": 0}


def sangvis_skill_switch(state, body):
    """Mission/sangvisBattleSkillSwitch {"info": {"<Coalition team id>": 1 or 0}} (RequestSangvisSkillSwitch:
    SangvisTeam.AssistUICanUse); no reply keys read. Kept for a resumed map's sangvis_teams_info."""
    m = _mission(state)
    info = (body or {}).get("info")
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except ValueError:
            info = None
    if m is not None and isinstance(info, dict):
        for team, on in info.items():
            m.setdefault("sangvis_switch", {})[str(team)] = str(on).lower() not in ("0", "false", "")
    return {}


def squad_skill_switch(state, body):
    """Mission/squadBattleSkillSwitch {squad_instance_id, switch}; no reply keys read."""
    m = _mission(state)
    body = body or {}
    q = (m or {}).get("squads", {}).get(str(body.get("squad_instance_id") or 0))
    if q is not None:
        q["switch"] = int(body.get("switch") or 0)
    return {}


# --- other mission calls ------------------------------------------------------------------

def account_mission(state, body):
    """Mission/accountMission: settle the mission in progress; answered like abortMission
    (DeploymentController$$RequestAbortMissionHandle)."""
    return abort_mission(state, body)


def mission_group_reset(state, body):
    """Mission/missionGroupReset {mission_group_id}: restart a mission group (every reply key is
    guarded); the mission in progress is settled and dropped."""
    m = state.pop("_mission", None)
    if m:
        _settle_score(state, m)
        _end_heal(state, m)
    return {"mission_group_today_reset_num": 0}


def skip_missions(state, body):
    """Mission/skip {mission_skip_ids: "id,id"}: story skip; each mission counts as cleared and
    opens the next. Reply {"spend_gem"} (RequestMissionSkip); free offline."""
    for mid in _ids((body or {}).get("mission_skip_ids")):
        row = _missions().get(mid)
        if row is None:
            continue
        rec = _mission_record(state, mid)
        rec["win_counter"] = str(max(1, int(rec["win_counter"] or 0)))
        rec["counter"] = str(max(int(rec["counter"] or 0), int(rec["win_counter"])))
        rec["medal1"] = "1"
        # a skipped map drops its keys as a win would; the client reads them at the next login
        dropped = _drop_keys(state, mid)
        _open_next(state, row)
        _open_by_keys(state, *dropped)
        _close_missions(state, row)
        _mapped_win(state, row)
    return {"spend_gem": 0}


def weak_reset(state, body):
    """Mission/weakReset: reply {"user_all_mission_key": [...]} (guarded; none offline)."""
    return {"user_all_mission_key": []}


# --- vehicles (Armor units) on the map ---------------------------------------------------
#
# A vehicle moves with Mission/teamMove, person_type 4 (RequestTeamMove only switches the URL
# for HOC); spots carry it in vehicle_with_user_id. Mission/reinforceVehicle {vehicle_with_user_id,
# spot_id} (RequestVehicleReinforce$$.ctor) -> {"ap"} (read unguarded by
# DeploymentTeamInfoController$$RequestVehicleReinforceHandle); Mission/withdrawVehicle {spot_id};
# a fight on arrival ends with Mission/vehicleBattleFinish, answered like battleFinish.
# Long-range attacks (bombardment): Mission/vehicleRangeAtk {from_spot_id, to_spot_id}
# (RequestVehicleRangeAtk$$.ctor) -> the attack to play, MissionAction$$LoadRangeAttackData:
#   range_atk_rec   {"<turn>": [{from_spot_id, to_spot_id, from_target_type (10 vehicle),
#                   from_target_id, to_target_type (4 enemy), to_target_id ("id,..." string),
#                   if_finish}]}
#   range_atk_turn  {"10": {"<vehicle>": ["<turn>", ...]}, "304": [], "305": [], "4": [], "5": [],
#                   "6": []}   the turns each unit has fired (one shot per turn)
# The client fights it as a remote battle and reports it with Mission/vehicleRangeAtkFinish
# (BattleController$$CreateRemoteBattleResultJS: against_info {spot_id, target_type, target_id,
# enemy_hp_percent, boss_hp}, myforce_info, battle_damage), answered like battleFinish
# (RequestRemoteBattleFinishHandle: seed, died_this_section, range keys, vehicle_battle_exp).
# The target keeps the HP it was left with; at 0 it dies. A shot costs the vehicle attack cost.
TARGET_VEHICLE, TARGET_ENEMY = 10, 4

def vehicle_move(state, body):
    m = _mission(state)
    body = body or {}
    dst = _spot_of(m, body.get("to_spot_id")) if m is not None else None
    if dst is None:
        return None
    vid = str(body.get("person_id") or 0)
    src = _spot_of(m, body.get("from_spot_id"))
    cost = _move_cost(m, "vehicle", vid)
    _count_move(m, "vehicle", vid, at=dst["spot_id"])
    if src is not None and str(src["vehicle_with_user_id"]) == vid:
        src["vehicle_with_user_id"] = 0
    dst["vehicle_with_user_id"] = int(vid)
    m.setdefault("vehicle_pos", {})[vid] = dst["spot_id"]
    m["ap"] = max(0, int(m.get("ap") or 0) - cost)
    if _hostile_here(m, dst):
        m["pending_battle"] = {"team": vid, "spot": dst["spot_id"], "from": src["spot_id"] if src else "",
                               "vehicle": True}
        return _reveal(state, m, _with_steps(m, {"ap": m["ap"], "type5_score": 0}))
    return _reveal(state, m, _hazard_reply(state, m, dst["spot_id"], ("vehicle", vid), {"ap": m["ap"], "type5_score": 0}))


def reinforce_vehicle(state, body):
    m = _mission(state)
    body = body or {}
    spot = _spot_of(m, body.get("spot_id")) if m is not None else None
    vid = str(body.get("vehicle_with_user_id") or 0)
    if spot is None or vid == "0":
        return {"ap": m["ap"]} if m is not None else None
    spot["vehicle_with_user_id"] = int(vid)
    m.setdefault("vehicle_pos", {})[vid] = spot["spot_id"]
    m["ap"] = max(0, int(m.get("ap") or 0) - 1)
    return _reveal(state, m, {"ap": m["ap"]})


def withdraw_vehicle(state, body):
    m = _mission(state)
    spot = _spot_of(m, (body or {}).get("spot_id")) if m is not None else None
    if spot is None:
        return None
    if m.setdefault("vehicle_pos", {}).pop(str(spot["vehicle_with_user_id"]), None) is not None:
        _repair_vehicle(state, spot["vehicle_with_user_id"])
        # recorded (124): its fired turns go, so once deployed again it may fire again this turn
        (m.get("range_turns") or {}).pop(str(spot["vehicle_with_user_id"]), None)
        _echelon_out(m, spot, vehicle=True)
    spot["vehicle_with_user_id"] = 0
    return _check_loss(state, m, {"type5_score": 0})


def _range_rec(m):
    """range_atk_rec: every shot of the map so far, by turn, if_finish 1 once it was fought
    (recorded 2026-11-09 on 124: the whole history in every reply that carries it)."""
    return m.get("range_rec") or {}


def _range_turns(m):
    fired = m.setdefault("range_turns", {})
    return {"10": {k: [str(t) for t in v] for k, v in fired.items()} if fired else {},
            "304": [], "305": [], "4": [], "5": [], "6": []}


def vehicle_range_attack(state, body):
    m = _mission(state)
    body = body or {}
    if m is None:
        return None
    src, dst = _spot_of(m, body.get("from_spot_id")), _spot_of(m, body.get("to_spot_id"))
    vid = str((src or {}).get("vehicle_with_user_id") or 0)
    if dst is None or vid == "0" or not int(dst["enemy_team_id"] or 0):
        return None
    turn = int(m["turn"])
    m.setdefault("range_turns", {}).setdefault(vid, []).append(turn)
    _pay_attack(state, m, "vehicle", vid)
    m["range_pending"] = {"vehicle": vid, "from": src["spot_id"], "to": dst["spot_id"]}
    # recorded: ints, to_target_id the enemy instance
    rec = {"from_spot_id": int(src["spot_id"]), "to_spot_id": int(dst["spot_id"]), "from_target_type": TARGET_VEHICLE,
           "from_target_id": int(vid), "to_target_type": TARGET_ENEMY,
           "to_target_id": int(dst["enemy_instance_id"]), "if_finish": 0}
    m.setdefault("range_rec", {}).setdefault(str(turn), []).append(rec)
    # target_moved_step counts a vehicle's shots this turn under 10 (recorded: 1, then 2)
    moved = m.setdefault("moved_step", {}).setdefault(str(turn), {}).setdefault(str(TARGET_VEHICLE), {})
    moved[vid] = int(moved.get(vid) or 0) + 1
    return {"died_this_section": {"enemy": [], "ally": []}, "fight_environment_group": "",
            "range_atk_rec": _range_rec(m), "range_atk_turn": _range_turns(m),
            "type5_score": "0", "target_moved_step": m["moved_step"], "ally1_add": []}


def vehicle_range_finish(state, body, rng=random):
    m = _mission(state)
    body = body or {}
    if m is None:
        return None
    pending = m.pop("range_pending", None) or {}
    against = body.get("against_info") or {}
    if isinstance(against, list):
        against = against[0] if against else {}
    spot = _spot_of(m, against.get("spot_id") or pending.get("to"))
    vid = pending.get("vehicle") or "0"
    for rec in (m.get("range_rec") or {}).get(str(m["turn"]), []):
        if not rec["if_finish"] and rec["from_target_id"] == int(vid or 0):
            rec["if_finish"] = 1
    # recorded (124, 128): the commander's battle exp whether or not the shot kills (66 both
    # times); the vehicle and its crew gain as in a won battle (player report)
    user_exp = commander_exp(state, m["mission_id"])
    _add(state["user_info"], "experience", user_exp)
    crew, over = _crew_exp(state, m, vid, True)
    veh_exp, veh_over = _vehicle_exp(state, m, vid, True)      # as a regular battle (player report)
    over += veh_over
    reply = {"seed": rng.randint(1, 9999), "battle_rank": RANK_S, "user_exp": str(user_exp),
             "died_this_section": {"enemy": [], "ally": []}, "fight_environment_group": "",
             "range_atk_rec": _range_rec(m), "range_atk_turn": _range_turns(m), "type5_score": "0",
             "target_moved_step": m.get("moved_step") or {}, "ally1_add": [], "crew_exp": crew,
             "vehicle_battle_exp": veh_exp,
             "vehicle_resource": dict(_res(state, m, "vehicle", vid)), "building_defender_change": [],
             "mission_control": {}}
    if spot is None or not int(spot["enemy_team_id"] or 0):
        return reply
    before = _number(spot["enemy_hp_percent"] or 1)
    hp = _number(against.get("enemy_hp_percent", spot["enemy_hp_percent"]))
    if body.get("if_enemy_die") or hp <= 0:
        # recorded: the team in died_this_section, a doll it may drop, free_exp 0, change_belong
        # [] (the vehicle stays where it fired from; the spot keeps its side)
        team = str(spot["enemy_team_id"])
        _battle_drop(state, reply, team, rng)
        _enemy_killed(m, spot, state)
        reply["died_this_section"]["enemy"].append(team)
        reply.update(free_exp=add_free_exp(state, over), change_belong=[])
        return _check_win(state, m, reply)
    _wear_score(m, spot, before, hp)
    spot["enemy_hp_percent"] = str(round(hp, 4))
    if "boss_hp" in against:
        spot["boss_hp"] = str(int(against["boss_hp"] or 0))
    return reply


# --- buildings --------------------------------------------------------------------------
#
# Spots with a building_id carry a building (stc building: defender, defender_upper, belong,
# hold_belong). startMission sends them as building_info, an object (not a string: the handler
# passes the JsonData itself to MissionAction$$ReadBuildingAction) {"<spot>": {"building_id",
# "spot", "belong", "defender"}} (BuildingAction$$.ctor / SetData, all read unguarded).
# HOC, vehicles and Coalition echelons next to a building can attack it:
#   Mission/squadAttackBuilding   {squad_instance_id, squad_spot, building_spot_id}
#                                 -> {"attack_next_turn", "building_defender", "type5_score"}, optional
#                                 "exp", "life"        RequestSquadAttckBuild$$SuccessJsonHandleData
#   Mission/sangvisAttackBuilding {sangvis_with_user_id, sangvis_in_ally_id, sangvis_spot, building_spot_id}
#                                 -> {"sangvis_resource": {"ammo", "mre"}, "building_defender",
#                                 "next_turn", "type5_score"}, optional "sangvis_new" {"exp", "life"}
#   Mission/vehicleAttackBuilding {vehicle_with_user_id, vehicle_spot, building_spot_id}
#                                 -> {"vehicle_resource": {"ammo", "mre"}, "after_exp", "next_turn",
#                                 "building_defender", "type5_score"}
# The attack costs game_config <kind>_mission_attack_cost "ammo,mre" (see the supply section:
# each unit's ammo and rations on the map are tracked in m["res"]).
# Damage: a HOC's or vehicle's pierce (times its destroy_coef %), a Coalition unit's firepower (an
# assist-squad unit's times that squad's coef; recorded on 126). Nothing else hurts buildings (the
# user): only HOCs, Coalition assist-squad units and tanks. At 0 the building passes to
# hold_belong (Griffin when unset).
# Building skills (buildingSkillPerform, myforceSkillPerform, arbitrarySkillPerform,
# buildingSkillPerformOnDeath) cast their active_mission_skills like other mission skills (see the
# skill effects section). Every reply key they read is guarded except "ap" (sangvis/vehicle
# skills) and "after_exp" (vehicle).

@lru_cache(maxsize=1)
def _buildings():
    return {int(r["id"]): r for r in stc.table("building")}


# Buildings the live server dealt out at random at mission start, one to each of these spots, sent
# in startMission's building_info (player report). City of Nightmares+: the four hidden spots get the
# Nyto markers 670115-670118; 670115 summons Nyto 670190 at turn 4's enemy phase, and each of the
# others the next one after the one before it is killed (their own skills, missionskill_on_death).
RANDOM_BUILDINGS = {
    11630: ((86399, 86400, 86401, 86402), (670115, 670116, 670117, 670118)),
}
# Buildings the stc leaves off the map but the map has: Scorpion Vortex's Goliath ("Boomer"
# 44430001, player report) on H5, the hidden heliport 93739 (the one next to R6 93740, R6 from the R8
# patrol's route in enemy_team 44430006 and the MS guide's "R8->R6->R4->R3->R5->R7->R8"). Picked
# up with its own skill 1030101 (a carry buff), planted on the Control Panel from L22's 44430004
# (skill 44430001: the bomb, special spot 44430001).
# Vortex of Secrets (Hole 1): "On X21, there is a Bean that you can use to destroy a Rubble" (the DR
# guide); no layer-1 spot has one, so the map's own Bean (Boomer 9411202, as on layer 2's Y24 92517)
# goes on X21 = 92425 (mis's labelled map of the hole, linked from the guide: X21 the dead end
# past X20 92424, reached from X25 92419). Hole 1's X labels all come from that map.
# Vortex of Secrets+ 11497: the server places 81 buildings the stc's spots leave out (recorded
# 2026-11-12, every one in startMission's building_info; one run, so ASSUMED fixed): the unnamed
# 9411207 on most hidden nodes, rabbit holes 9411206, a Goliath 6630004 (600126), the move-counter
# nodes 6630003 (its specials 6630006/6630023), the Derelict Control Panel 9411212 (600175, opens
# the Defense Gate), 6630005 (its 1010101 on 600219-222), 9411215, and the Goddess of the Spring's
# fountain 6630006 (600299: the Golden/Silver Axe choices 6630017-6630021).
EXTRA_BUILDINGS = {
    # Slow Shock 11403: the commander building 6580019 on the hidden network node 60177 (recorded
    # 2026-11-12 in building_info; the stc gives it only to enemy team 6589999's use_building). Its
    # skills 6589041-6589045 summon a force on every portal node marked by the stage special
    # (6580065-69 on turns 0-1, then 6580070-74 …), and 6580075 gives every enemy-side force
    # ExtraMove 20401 (a second step each enemy turn).
    11403: {60177: 6580019},
    10674: {93739: 44430001},
    # Mistbuster's Area 3 Iaso's Boxes, C5 and Y7 (the MS guide: "There's an Iaso's Box on C5",
    # "another Iaso's Box on Y7"); the stc has only Area 1's two (LATE_BUILDINGS)
    10675: {93686: 6440052, 93687: 6440052},
    # the Fairy of the Lake's: the axe choices 9411210 (9411239-9411244) on her 92598 and 9411215 on
    # 92589, as 11497's fountain 6630006 on 600299 and 9411215 on 600290. ASSUMED from 11497.
    # Its hidden holes and panels too (player report: "Mysterious rabbit holes are not showing"): the stc
    # gives the Hole 9411206 only to the two seen at the start (92410, 92423). Live Vortex+ 11497
    # (recorded 2026-11-12) has 9411206 on its four hidden portals 600117 / 600133 / 600156 / 600183
    # and 9411207 on the panels 600186 / 600187, which sit where this map's 92416 (X22), 92432 (X18),
    # 92455 (layer 2's cutoff), 92482 (Y13) and 92485 / 92486 do (11497's coordinates are these
    # doubled). Z8 92508 (11497's 600209 holds the plus map's 6630003): 9411207, ASSUMED.
    10520: {92425: 9411202, 92598: 9411210, 92589: 9411215,
            92416: 9411206, 92432: 9411206, 92455: 9411206, 92482: 9411206,
            92485: 9411207, 92486: 9411207, 92508: 9411207,
            # Y7's Derelict Control Panel (its 9411245 opens the Defense Gate 9411211 on Y15 92600, two
            # nodes away; the DR guide: "On Y7, there is also a Control Panel that opens the Defense
            # Gate on Y15"), on 92474 (player report), as 11497 has it on 600175
            92474: 9411212},
    11497: {s: b for b, spots in (
    (9411207, (
        600113, 600119, 600120, 600121, 600122, 600125, 600127, 600128, 600129, 600131,
        600132, 600134, 600135, 600138, 600139, 600140, 600141, 600142, 600157, 600176,
        600177, 600178, 600179, 600180, 600181, 600184, 600185, 600186, 600187, 600188,
        600189, 600190, 600192, 600194, 600195, 600196, 600197, 600200, 600201, 600203,
        600204, 600205, 600206, 600207, 600208, 600223, 600224, 600310)),
    (9411206, (
        600117, 600133, 600156, 600183)),
    (6630004, (
        600126,)),
    (6630003, (
        600130, 600136, 600182, 600191, 600193, 600198, 600199, 600209, 600291, 600293,
        600294, 600295, 600297, 600298, 600302, 600303, 600304, 600305, 600306, 600309,
        600316)),
    (9411212, (
        600175,)),
    (6630005, (
        600219, 600220, 600221, 600222)),
    (9411215, (
        600290,)),
    (6630006, (
        600299,)),
    ) for s in spots},
}
# Special spots that blow up the building on their spot when they appear: Scorpion Vortex's bomb
# goes off as 44430002 at the start of the turn after it is planted ("the explosion only happens on
# the start of your next turn", the MS guide), taking the Control Panel 44430002 down (score
# field "building", 50000).
BLAST_SPECIALS = {44430002}


def _place_buildings(m, rng=random):
    out = {}
    dealt = {}
    if int(m["mission_id"]) in RANDOM_BUILDINGS:
        spots, kinds = RANDOM_BUILDINGS[int(m["mission_id"])]
        kinds = list(kinds)
        rng.shuffle(kinds)
        dealt = dict(zip(spots, kinds))
    dealt.update(EXTRA_BUILDINGS.get(int(m["mission_id"]), {}))
    for r in _spots_by_mission().get(m["mission_id"], []):
        b = _buildings().get(dealt.get(int(r["id"])) or int(r["building_id"] or 0))
        if b is not None:
            out[str(r["id"])] = {"building_id": int(b["id"]), "spot": int(r["id"]),
                                 "belong": int(b["belong"]), "defender": int(b["defender"])}
    if out:
        m["buildings"] = out


def _hit_building(state, m, spot_id, damage=None):
    """One attack on the building at spot_id; returns its defender afterwards (None: no building).
    damage: the attacker's (a HOC's pierce times its destroy_coef %, a Coalition assist squad's or
    a tank's); None or 0 for anything else, which can't hurt buildings (player report)."""
    b = (m.get("buildings") or {}).get(str(spot_id))
    if b is None:
        return None
    if not damage or damage <= 0:
        return b["defender"]
    b["defender"] = max(0, int(b["defender"]) - damage)
    if b["defender"] == 0 and str(spot_id) not in m.get("buildings_down", []):
        _building_down(m, spot_id)
    return b["defender"]


DESTROY_BY_ATTACK, DESTROY_BY_ENTERING = "1", "2"      # building.is_destroy
# Client-only stc fields, nothing to do here: building.condition and working_spot_activation
# (BuildingInfo.buildStates, the look per side), mission.ext_move and carry_mission_skill (the
# client limits moves and offers skills; the server doesn't check either).


def _occupy_building(state, m, spot_id, reply):
    """Our unit moves onto a building whose is_destroy lists 2 ("destroyed by moving onto it"; 1 is
    by attacking it) and that belongs to the enemy or nobody (belong 2 / 0): it goes down to 0, sent
    as building_defender_change. Ours (belong 1) don't: Mirror Stage+'s Iaso's Boxes (6440052,
    is_destroy 2) need a unit on them to use a skill as well (player report). Enemies never do this (player report: they can't knock the Goliaths
    down). Recorded on 11116 (94040901, is_destroy "1,2"): a HOC onto 95257, an echelon onto 95259
    and winning the battle there. The artillery and gates (no is_destroy) stayed. reply None: kept
    for the next reply. (That log also showed the artillery on 95300, 94040905, going to 0 at the
    first startEnemyTurn, cause unknown; player report says enemies can't destroy it.)"""
    b = (m.get("buildings") or {}).get(str(spot_id))
    if b is None or int(b["defender"]) <= 0:
        return reply
    row = _buildings().get(b["building_id"], {})
    if DESTROY_BY_ENTERING not in [x.strip() for x in str(row.get("is_destroy") or "").split(",")]:
        return reply
    if int(b.get("belong") or 0) not in (0, 2):
        return reply
    _hit_building(state, m, spot_id, int(b["defender"]))
    entry = {"building_spot_id": int(spot_id), "defender": 0}
    if reply is None:
        m.setdefault("building_changes", []).append(entry)
        return None
    reply.setdefault("building_defender_change", []).append(entry)
    return reply


def _building_down(m, spot_id):
    """A building attacked down to 0 keeps its side but stops working: the special spots and buffs
    it placed go and it casts no more (recorded on 126: HOC fire took turrets 91180 and 91192 to 0;
    they stayed belong 2, their 1200100/1200200 spots and the 910630 shields they gave enemies were
    gone from the next reply, and they cast nothing at the next startEnemyTurn)."""
    m.setdefault("buildings_down", []).append(str(spot_id))    # kept apart: building_info goes to the client
    rule = score_rule(m["mission_id"])
    if rule is not None:
        _add_score(m, rule["building"])         # recorded on 11116: +10000 each, the rock a HOC shot down too
    fx = m.get("effects")
    if fx:
        mine = lambda e: e["source_type"] == SOURCE_BUILDING and int(e["source_value"]) == int(spot_id)
        # is_still_alive 1 (133 configs; the client never reads it): read as outliving its source.
        # INFERRED: the turrets' spots that went (1200100 / 1200200) all have it 0
        lives = lambda sp: int(_special_spots().get(sp["config"], {}).get("is_still_alive") or 0) == 1
        fx["specials"] = {i: sp for i, sp in fx["specials"].items() if not mine(sp) or lives(sp)}
        fx["buffs"] = {i: x for i, x in fx["buffs"].items() if not mine(x)}


def _pay_attack(state, m, kind, uid):
    """A building attack (or a vehicle's range attack): game_config <kind>_mission_attack_cost."""
    return _spend(state, m, kind, uid, _cost(f"{kind}_mission_attack_cost", "2,1"))


def squad_attack_building(state, body):
    m = _mission(state)
    body = body or {}
    if m is None:
        return None
    q = m.get("squads", {}).get(str(body.get("squad_instance_id") or 0))
    rec = workshop._find(state.get("squad_with_user_info"), q["squad"]) if q is not None else None
    damage = None
    if rec:
        # its pierce times the squad's destroy_coef % (recorded: 214 pierce, 999 -> 785 -> ... -> 0)
        coef = int(squads.squad_rows().get(int(rec.get("squad_id") or 0), {}).get("destroy_coef") or 100)
        damage = max(1, squads.panel_attribute(state, rec) * coef // 100)
    defender = _hit_building(state, m, body.get("building_spot_id"), damage)
    reply = {"attack_next_turn": int(m["turn"]), "building_defender": defender or 0, "type5_score": 0}
    if q is not None:
        # recorded: attack_next_turn is the current turn, so a HOC may attack again while it has
        # ammo and rations; it pays squad_mission_attack_cost (2,2) each time
        q["attack_next_turn"] = int(m["turn"])              # resent in squad_info
        reply["squad_resource"] = _pay_attack(state, m, "squad", q["squad"])
    if rec:
        reply["squad_new"] = {"exp": str(rec.get("squad_exp") or 0), "life": str(rec.get("life") or 0)}
    return reply


def _destroy_coef(row):
    """% of pierce a unit deals to buildings: destroy_coef, else (Coalition squad rows, type 102,
    which have destroy_coef 0) assist_damage_destroy_coef."""
    return int(row.get("destroy_coef") or 0) or int(row.get("assist_damage_destroy_coef") or 0)


@lru_cache(maxsize=None)
def _game_config(name, default=""):
    return str(next((r["parameter_value"] for r in stc.catch("game_config_info")
                     if r["parameter_name"] == name), default))


def _favor_ratio(favor):
    """Gun$$get_favorRatio: the affection buff for a favor value (x10000), from game_config
    favor_attribute_0_9 / 10_89 / 90_139 / 140 / 190."""
    f = int(favor or 0)
    name = ("favor_attribute_190" if f >= 1900000 else "favor_attribute_140" if f >= 1400000 else
            "favor_attribute_90_139" if f >= 900000 else "favor_attribute_10_89" if f >= 100000 else
            "favor_attribute_0_9")
    return float(_game_config(name, "0") or 0)


def sangvis_pow(unit):
    """A Coalition unit's firepower (Gun.pow = basePow + favorPow):
    base = ceil(shape_val x ratio_pow x advance_pow x (level + sangvis_base_lv - 1) x basic_pow
    / 1e6 / formation) + resolution_pow, favor = ceil(base x favor ratio). shape_val from
    game_config sangvis_shape_val by sangvis_shape_n; advance_pow by sangvis_advance; basic_pow
    by the row's sangvis_type; resolution_pow from sangvis_resolution (group = row resolution,
    lv = sangvis_resolution_level). Recorded: Nyto_tareus lv 100, advance 5, shape 0,
    resolution 4, favor 150 -> 447 + 45 = 492."""
    base = _sangvis_base(unit, "pow")
    return base + math.ceil(round(base * _favor_ratio(unit.get("favor")), 6))


def _sangvis_base(unit, stat):
    """ceil(shape_val x ratio_<stat> x advance_<stat> x (level + sangvis_base_lv - 1) x basic_<stat>
    / 1e6 / formation) + resolution_<stat> (sangvis_pow's formula). Recovery ("rec") is from a player report:
    ceil(((shape_val x ratio_rec x advance_rec x (level + 40 - 1) x basic_rec + 1) / 1e6
    + resolution_rec) / max links) a link (max links: the unit's formation), times its links."""
    row = next((r for r in stc.table("sangvis") if int(r["id"]) == int(unit.get("sangvis_id") or 0)), None)
    if row is None:
        return 0
    cls = next((r for r in stc.table("sangvis_type") if r["id"] == row["type"]), {})
    adv = next((r for r in stc.table("sangvis_advance") if int(r["lv"]) == int(unit.get("sangvis_advance") or 1)), {})
    res = next((r for r in stc.table("sangvis_resolution") if r["group_id"] == row["resolution"]
                and int(r["lv"]) == int(unit.get("sangvis_resolution_level") or 0)), {})
    shapes = dict(x.split(":") for x in _game_config("sangvis_shape_val", "0:100").split(",") if ":" in x)
    shape = float(shapes.get(str(unit.get("sangvis_shape_n") or 0), 100))
    lv = int(unit.get("sangvis_level") or 1) + int(_game_config("sangvis_base_lv", "40") or 40) - 1
    links = max(1, int(row["formation"] or 1))
    grown = shape * float(row[f"ratio_{stat}"] or 0) * float(adv.get(f"advance_{stat}") or 100) * lv * float(cls.get(f"basic_{stat}") or 0)
    if stat == "rec":
        per = ((grown + 1) / 1e6 + int(res.get("resolution_rec") or 0)) / links
        return math.ceil(round(per, 6)) * max(1, int(res.get("resolution_number") or 1))
    return math.ceil(round(grown / 1e6 / links, 6)) + int(res.get(f"resolution_{stat}") or 0)


def _sangvis_building_damage(state, team):
    """A Coalition echelon's building damage. A unit whose skill2 is an assist squad (skill2_type
    3, SangvisGun$$TryGetAssistSquadInfo) attacks as that squad with assist_damage = the unit's
    firepower and assist_def_break 0, so it deals sangvis_pow x the squad's destroy coef %.
    Recorded on 126: Nyto_tareus (squad 1018, coef 50), 492 firepower -> 246. None: no such unit."""
    rec = next((t for t in state.get("sangvis_team_with_user_info") or [] if str(t.get("team_id")) == str(team)), {})
    info = rec.get("info") or {}
    rows = squads.squad_rows()
    sangvis = {int(r["id"]): r for r in stc.table("sangvis")}
    total, found = 0, False
    for slot in (info.values() if isinstance(info, dict) else info):
        unit = workshop._find(state.get("sangvis_with_user_info"), (slot or {}).get("sangvis_with_user_id") or 0)
        srow = sangvis.get(int((unit or {}).get("sangvis_id") or 0)) or {}
        row = rows.get(int(srow.get("skill2") or 0)) if int(srow.get("skill2_type") or 0) == 3 else None
        if row is None or not _destroy_coef(row):
            continue            # only assist squads with a building coef hurt buildings (3 of the 7 have 0)
        found = True
        total += sangvis_pow(unit) * _destroy_coef(row) // 100
    return max(1, total) if found else 0         # no such unit: it can't hurt buildings


def _ally_sangvis_damage(body):
    """A map-provided Coalition unit (sangvis_in_ally) attacking: as an own unit, only through an
    assist squad with a building coef; 0 (no harm) otherwise."""
    unit = _sangvis_in_ally().get(int(body.get("sangvis_in_ally_id") or 0))
    srow = next((r for r in stc.table("sangvis") if unit and int(r["id"]) == int(unit.get("sangvis_id") or 0)), {})
    row = squads.squad_rows().get(int(srow.get("skill2") or 0)) if int(srow.get("skill2_type") or 0) == 3 else None
    return sangvis_pow(unit) * _destroy_coef(row) // 100 if row and _destroy_coef(row) else 0


def vehicle_def_break(state, veh):
    """A vehicle's pierce: stc vehicle def_break + the record's def_break + the def_break of each
    equipped component (the record's component and common_component "slot:component_with_user_id"
    lists, looked up in vehicle_component_with_user_info)."""
    veh = veh or {}
    row = next((r for r in stc.table("vehicle") if int(r["id"]) == int(veh.get("vehicle_id") or 0)), {})
    total = int(row.get("def_break") or 0) + int(veh.get("def_break") or 0)
    for field in ("component", "common_component"):
        for part in str(veh.get(field) or "").split(","):
            cid = part.partition(":")[2]
            comp = workshop._find(state.get("vehicle_component_with_user_info"), cid) if cid else None
            total += int((comp or {}).get("def_break") or 0)
    return total


VEHICLE_TANK = 1      # vehicle.type


def _vehicle_building_damage(state, veh):
    """A vehicle's building damage: its full pierce (vehicle_def_break), or its destroy_coef % of
    it when the stc row has one (all current vehicles have 0). Recorded on 126: TankM1 with
    215 own + 3 x 76 component pierce took 443."""
    if veh is None:
        return None
    row = next((r for r in stc.table("vehicle") if int(r["id"]) == int(veh.get("vehicle_id") or 0)), {})
    if int(row.get("type") or 0) != VEHICLE_TANK:
        return 0            # only tanks hurt buildings (player report): not the Warjack or Tachikoma (type 2)
    coef = _destroy_coef(row) or 100
    return max(1, vehicle_def_break(state, veh) * coef // 100)


def sangvis_attack_building(state, body):
    m = _mission(state)
    body = body or {}
    if m is None:
        return None
    # a Coalition echelon's supply is the echelon's (SangvisTeam.ammo / mre)
    team = str((_spot_of(m, body.get("sangvis_spot")) or {}).get("sangvis_team_id") or 0)
    damage = _sangvis_building_damage(state, team) if _own_sangvis(team) else _ally_sangvis_damage(body)
    defender = _hit_building(state, m, body.get("building_spot_id"), damage)
    res = _pay_attack(state, m, "sangvis", team) if _own_sangvis(team) else {"ammo": 0, "mre": 0}
    reply = {"sangvis_resource": res, "building_defender": defender or 0,
             "next_turn": int(m["turn"]), "type5_score": 0}       # recorded: the current turn
    unit = workshop._find(state.get("sangvis_with_user_info"), body.get("sangvis_with_user_id") or 0)
    if unit is not None:
        reply["sangvis_new"] = {"exp": str(unit.get("sangvis_exp") or 0), "life": int(unit.get("life") or 0)}
    return reply


def vehicle_attack_building(state, body):
    m = _mission(state)
    body = body or {}
    if m is None:
        return None
    vid = body.get("vehicle_with_user_id") or 0
    veh = workshop._find(state.get("vehicle_with_user_info"), vid)
    defender = _hit_building(state, m, body.get("building_spot_id"), _vehicle_building_damage(state, veh))
    m.setdefault("vehicle_atk", {})[str(vid)] = int(m["turn"])         # resent in vehicle_info
    return {"vehicle_resource": _pay_attack(state, m, "vehicle", vid), "after_exp": int((veh or {}).get("exp") or 0),
            "next_turn": int(m["turn"]), "building_defender": defender or 0, "type5_score": 0}     # recorded: the current turn


SOURCE_BUILDING = 99910


def _defuse(state, m, spot, skill, reply):
    """A unit standing on a building of ours whose is_destroy lists 2 uses that building's own
    active skill there: the building is done with, down to 0 (player report: Mirror Stage+'s Iaso's
    Boxes, 6440052, need a unit on them and the defuse skill 6440110; each scores field 5, 50000).
    INFERRED: that this takes the building down in the live game too."""
    b = (m.get("buildings") or {}).get(str(spot))
    if b is None or int(b["defender"]) <= 0 or int(b.get("belong") or 0) != BELONG_OURS_INT:
        return
    row = _buildings().get(b["building_id"], {})
    if (DESTROY_BY_ENTERING not in [x.strip() for x in str(row.get("is_destroy") or "").split(",")]
            or skill not in _ids(row.get("active_mission_skill"))):
        return
    _hit_building(state, m, spot, int(b["defender"]))
    reply.setdefault("building_defender_change", []).append({"building_spot_id": int(spot), "defender": 0})


# Tide of Blood (10521): the console on N19 (building 9411301 on 92530) picks the difficulty, Easy /
# Normal / Hard (skills 9411301 / 9411302 / 9411303), and "12 Heliports will appear. This is where
# enemies will spawn ... The difficulty (and points awarded) from the spawns will depend on what
# difficulty you selected" (the DR guide). The skills only put down special spot 1020100 (which
# stops the console's trigger), so the heliports are the server's: three hidden sets of 12 on the
# same 12 places, one per difficulty, revealed as the enemy's. ASSUMED: the sets go Easy, Normal,
# Hard in id order. Their spawns are in data/spawn_tables.json, by set. Once a map.
DIFFICULTY_HELIPORTS = {
    9411301: (92545, 92546, 92549, 92552, 92554, 92556, 92557, 92558, 92559, 92560, 92561, 92562),
    9411302: tuple(range(92565, 92577)),
    9411303: tuple(range(92577, 92589)),
}


# Map skills that swap what spawns from then on (enemies already on the map stay): skill ->
# (team every spawn becomes, {team: its own replacement}). Labyrinthine Defense+ (11435): the HQ's
# Easy Mode 9363069 ("enemy helipads will no longer generate powerful reinforcements"; the PL
# ranking notes: every heliport spawn becomes 6363061, the 29859 CE Cyclops AR, and the boss
# 6363098 the weaker 6363099). Its "Stay in hell" 9363070 only takes the choice away.
SPAWN_SWAPS = {
    9363069: (6363061, {6363098: 6363099}),
}


def _pick_spawn_swap(m, skill):
    if skill in SPAWN_SWAPS and not m.get("spawn_swap"):
        m["spawn_swap"] = skill


def _swapped_team(m, team, at_start=False):
    swap = SPAWN_SWAPS.get(m.get("spawn_swap")) if not at_start else None
    if swap is None:
        return team
    every, own = swap
    out = own.get(team, every)
    return out if out in _enemy_teams() else team


def _pick_difficulty(m, skill):
    spots = DIFFICULTY_HELIPORTS.get(skill)
    if not spots or m.get("difficulty") or _spot_of(m, spots[0]) is None:
        return
    m["difficulty"] = skill
    changes = {}
    for sid in spots:
        sp = _spot_of(m, sid)
        if _hidden(sp):
            sp["belong"] = BELONG_ENEMY
            changes[str(sid)] = int(BELONG_ENEMY)
    _queue_reveal(m, changes)


# Choices that hand hidden nodes over: on Vortex of Secrets the Fairy of the Lake's honest answer,
# "Neither" (9411241, her axe-choice building 9411210 on 92598), gives the echelons her 16 hidden
# heavy heliports, layer 0's 92601-92608 and layer 1's 92590-92597, as ours: more AP each turn
# after (player report, 2026-11-14). The stc's skill only marks the choice (special spots 1020101 /
# 1000010); which heliports and that they come in ours: player report. Once only.
SKILL_HELIPORTS = {9411241: (tuple(range(92601, 92609)) + tuple(range(92590, 92598)), BELONG_OURS)}


def _skill_heliports(m, skill):
    spots, side = SKILL_HELIPORTS.get(skill, ((), None))
    if not spots or _spot_of(m, spots[0]) is None or skill in (m.get("skill_reveals") or []):
        return
    m.setdefault("skill_reveals", []).append(skill)
    changes = {}
    for sid in spots:
        sp = _spot_of(m, sid)
        if _hidden(sp):
            sp["belong"] = side
            changes[str(sid)] = int(side)
    _queue_reveal(m, changes)


def building_skill(state, body):
    """Skills cast by buildings, buffs and map events, each with "active_mission_skills"
    {"<mission_skill_config_id>": [target spot, ...]} (RequestBuildControl / RequestBuffSkillControl /
    RequestPerformSkillControl ..ctor):
      buildingSkillPerform     trigger_type, trigger_person_info {team_id, sangvis_team_id,
                               vehicle_with_user_id, ...}, trigger_person_spot, building_spot_id
      myforceSkillPerform      source_type, person_spot, mission_buff_instance_id
      arbitrarySkillPerform    trigger_type, trigger_person_spot, source_type, source_value,
                               source_spot_id, appoint_target_spots
      buildingSkillPerformOnDeath  (RequestBuildSkillOnDeath)
    Each skill acts as for fairies (_cast_skill); the unit on the trigger spot is the caster.
    Replies are read through the same loaders (building_info is guarded)."""
    m = _mission(state)
    if m is None:
        return None
    body = body if isinstance(body, dict) else {}
    on_death = body.get("building_missionskills_on_death_k")
    if isinstance(on_death, dict):
        return _building_skill_on_death(state, m, on_death)
    skills = body.get("active_mission_skills") or {}
    if not isinstance(skills, dict):
        return {}
    spot = body.get("trigger_person_spot") or body.get("person_spot") or body.get("source_spot_id") or body.get("building_spot_id")
    caster = _unit_on(m, spot) if spot else None
    if "building_spot_id" in body:
        source_type, source_value = SOURCE_BUILDING, int(body.get("building_spot_id") or 0)
    else:
        source_type, source_value = int(body.get("source_type") or SOURCE_BUILDING), int(body.get("source_value") or spot or 0)
    replies = []
    for sid, targets in skills.items():
        cfg = _mission_skills().get(int(sid)) if str(sid).isdigit() else None
        if cfg is None:
            continue
        targets = _ids(",".join(str(t) for t in targets) if isinstance(targets, list) else targets)
        if not targets and spot:
            # none picked by the player: the skill's own target_id around the caster (recorded on
            # 11355: myforceSkillPerform 6580125 with [] put special spot 6580113 on 68302, its
            # target 1, the caster's spot, which finished win step 1135501)
            # target 1 is the building's spot when cast from next to it (recorded on 1001-EX:
            # the allied force on 74539 armed the bomb building on 74574, 483902 landed there)
            targets = _skill_targets(state, m, cfg, int(body.get("building_spot_id") or spot))
        replies.append(_cast_skill(state, m, cfg, source_type, source_value, targets, caster))
        if source_type == SOURCE_BUILDING and caster is not None and str(source_value) == str(spot):
            _defuse(state, m, source_value, int(cfg["id"]), replies[-1])
        if int(cfg.get("is_airborne") or 0) and targets and caster is not None and caster[0] == "team":
            # a console that sends the echelon on (No More Omens' 420201, is_airborne 2: hacking the
            # theater security flies it to a landing spot, special spot 420202, on the other layer,
            # and its 420205 takes the console's 420211 off): the client flies it, as for the
            # Parachute Fairy, so only our copy moves, once the skill has acted where it was cast
            _airdrop(m, cfg, int(caster[1]), targets[0])
        _pick_difficulty(m, int(cfg["id"]))
        _skill_heliports(m, int(cfg["id"]))
        _pick_spawn_swap(m, int(cfg["id"]))
        changed = ally_changes(m, ALLY_ON_SKILL, cfg["id"], replies[-1])
        if changed:
            ret = replies[-1].setdefault("fairy_skill_return", {"mission_hurt": [], "allyteam_summoner": []})
            ret["allyteam_b_t"] = dict(changed, building_defender_change=[])
    # what a choice opened (_pick_difficulty, _skill_heliports) shows in this reply, not the next move's
    return _flush_belong(m, _check_loss(state, m, _reveal(state, m, _merge_replies(replies)))) if replies else {}


def _building_start_skills(state, m, rng=random):
    """Buildings' own skills at startMission, cast by the server (recorded on 11341: the reply
    already holds their special spots and cooldowns). Building by building in spot order: its
    inherent_mission_skill ids, then mission_skill's slot for its belong ("0;580051,580908;0;0":
    belong 1 casts 580051 and 580908). Each fires when its trigger_id finds a node and acts on its
    target_id's nodes around the building (_skill_targets); follow-ups pick their own targets."""
    replies = []
    # a building on a node out of play (Slow Shock's commander on the network node 60177) casts
    # last: its summons need the portal markers the map's own buildings put down (recorded order)
    off = lambda sp: _spot_of(m, int(sp)) is None or str(_spot_of(m, int(sp)).get("belong")) == "99"
    late = LATE_BUILDINGS.get(int(m["mission_id"]), {})
    for spot in sorted((m.get("buildings") or {}), key=lambda sp: (off(sp), int(sp))):
        if int(spot) not in late:
            replies += _building_own_casts(state, m, spot)
    recorded = bool(_marker_runs(m["mission_id"]))      # recorded markers replace these guesses
    markers = [] if recorded else list(START_MARKERS.get(int(m["mission_id"]), ()))
    plan = None if recorded else TIMED_MARKERS.get(int(m["mission_id"]))
    if plan is not None:
        skills, per_turn, where = plan
        spots = [int(sp["spot_id"]) for sp in m["spots"] if where(sp, _spot_types(int(m["mission_id"])))]
        picks = rng.sample(spots, min(len(spots), len(skills) * per_turn))
        markers += [(spot, skills[i // per_turn]) for i, spot in enumerate(picks)]
    for spot, sid in markers:
        cfg = _mission_skills().get(sid)
        if cfg is not None and _spot_of(m, spot) is not None:
            replies.append(_cast_skill(state, m, cfg, SOURCE_BUILDING, spot, [spot], None))
    return _merge_replies(replies) if replies else {}


def _building_own_casts(state, m, spot):
    """A building's own skills as it comes into play: its inherent_mission_skill ids, then
    mission_skill's slot for its belong."""
    b = m["buildings"][str(spot)]
    row = _buildings().get(b["building_id"], {})
    slots = str(row.get("mission_skill") or "").split(";")
    belong = int(b.get("belong") or 0)
    out = []
    for sid in _ids(row.get("inherent_mission_skill")) + (_ids(slots[belong]) if belong < len(slots) else []):
        cfg = _mission_skills().get(sid)
        if cfg is None or _does_nothing(cfg) or not _triggered(state, m, cfg, int(spot)):
            continue
        if sid in DIRECTION_MARKERS:
            out.append(_direction_markers(m, cfg, int(spot)))
            continue
        targets = RECORDED_TARGETS.get((int(m["mission_id"]), sid, int(spot)))
        targets = list(targets) if targets is not None else _skill_targets(state, m, cfg, int(spot))
        out.append(_cast_skill(state, m, cfg, SOURCE_BUILDING, int(spot), targets, _unit_on(m, int(spot))))
    return out


# Skills that mark the nodes next to their building, hidden ones included (_skill_targets keeps only
# nodes in play, and these start hidden). Vortex of Secrets' rubbles (Rock_S 9411201 / 9411209 /
# 9411214): their own 9411201 (range 1) lists the side markers 1000100 ... 1000400, and each node's
# forbid_specialspot refuses all but its own (92412 refuses 1000200 / 1000300 / 1000400). Throwing
# a Bean at the rubble (9411202 / 9411205 / 9411210 / 9411213, or 9411216 ... 9411225 on X32) needs
# a unit holding the Bean (buff 1000000) on a node next to it with one of them (player report: "Picked
# up goliaths but can't throw them at rubble": the markers went on the rubble itself before).
DIRECTION_MARKERS = {9411201}


def _direction_markers(m, cfg, spot):
    """DIRECTION_MARKERS: each of cfg's markers on each of spot's neighbours that takes it."""
    for n in sorted(_neighbours(int(m["mission_id"])).get(spot, ())):
        for mark in _counted(cfg.get("special_spot_add")):
            _add_special(m, n, mark, int(cfg["id"]), SOURCE_BUILDING, spot)
    return {"fairy_skill_perform": []}


# Buildings that stand from the start but come into play on a later turn: their own skills wait for
# it. Mistbuster's Area 3 Iaso's Boxes (C5 93686, Y7 93687; the MS guide) start their countdown
# (6440108: 6440082, 6440081, then the blast) when Area 3 opens on turn 7, not at the map's start.
LATE_BUILDINGS = {10675: {93686: 7, 93687: 7}}


def _late_building_casts(state, m):
    """startTurn: the LATE_BUILDINGS whose turn this is cast their own skills."""
    out = []
    for spot, turn in sorted(LATE_BUILDINGS.get(int(m["mission_id"]), {}).items()):
        if turn == int(m["turn"]) and str(spot) in (m.get("buildings") or {}):
            out += _building_own_casts(state, m, spot)
    return out


# Start-of-map building casts whose targets the live server picked by a rule we can't see:
# (mission, skill, building spot) -> the spots. Vortex of Secrets+ 11497, recorded 2026-11-12:
# 6630005's 9411228 (range 4, no target_id) put 1010101 on its own spot four times and once more on
# 600116 (from 600219), on no in-play spot in range (600148 / 600152 are within 4 of 600221).
# One run: ASSUMED the same every run.
RECORDED_TARGETS = {
    (11497, 9411228, 600219): (600219, 600116), (11497, 9411228, 600220): (600220,),
    (11497, 9411228, 600221): (600221,), (11497, 9411228, 600222): (600222,),
}
# Markers a map needs that no spot's building places (the live server's, never recorded).
# APPROXIMATION, Ship of Theseus II (10637, EX 10653): the third bar's 440603 (-> 440613, step
# 1063703 "check the place to the northwest") and the "unknown victory condition"'s 440604
# (-> 440614, step 1063706, which wins at once) come only from building 440603's skill, which no
# spot has. Both go on the one radar without a building, the northwest one inside the fog the
# NPC's scan lifts (73256 / 73293), from the start: entering it wins by the unknown condition at
# any time, and after the other two bars it is also the third bar (otherwise the unknown
# condition could only ever be met together with the third).
START_MARKERS = {10637: ((73256, 440603),), 10653: ((73293, 440603),)}
# Markers laid at the start that turn into something later, server-only like Silent Sandtable's:
# (marker skills, how many of each, which spots). CK 11603's Data Patches: "From turn 2 and on, 3
# Data Patches will spawn in one of the 24 initial blue nodes each turn ... These will not despawn"
# (the CK sheet; 18 in all, its score table): marker 660081+k (skill 660081+k) becomes 660080+k each
# turn and the Data Patch 660080 after k+1 turns; Patch (660080) scores 20000 by event_score field 18.
# ASSUMED: random distinct nodes among the 24 (ours, normal).
TIMED_MARKERS = {
    11603: ((660081, 660082, 660083, 660084, 660085, 660086), 3,
            lambda sp, types: str(sp.get("belong")) == BELONG_OURS and types.get(int(sp["spot_id"])) == 2),
}


# Hidden markers from recorded runs (recordings.py marker_runs): special spots the live server laid
# itself at the start and at turn changes, which no table names. One run is picked when the map
# starts and its markers are laid at the same turn and phase; past the last turn that run reached,
# another run that got further. Copies this server already laid on the spot that turn (its
# buildings' casts) count toward the recorded number, so the two don't add up.
def _marker_runs(mid):
    return [] if int(mid) == SANDTABLE else _live_spawn_seen(mid).get("marker_runs") or []   # _corridor_markers


def _recorded_markers(m, phase, rng=random):
    """Lay this turn and phase's recorded markers; True when any were laid."""
    runs, turn = _marker_runs(m["mission_id"]), int(m["turn"])
    live = [i for i, r in enumerate(runs) if int((r.get("reached") or {}).get(phase) or 0) >= turn]
    if not live:
        return False
    if m.get("marker_run") not in live:
        m["marker_run"] = rng.choice(live)
    upto = recordings.PHASES[:recordings.PHASES.index(phase) + 1]
    want, skill_of = {}, {}
    for spot, special, skill, t, ph, n in runs[m["marker_run"]].get("markers") or []:
        if t == turn and ph in upto:
            want[(spot, special)] = want.get((spot, special), 0) + n
            skill_of[(spot, special)] = skill
    have = {}
    for sp in _effects(m)["specials"].values():
        if int(sp.get("start_turn") or 0) == turn:
            have[(int(sp["spot"]), int(sp["config"]))] = have.get((int(sp["spot"]), int(sp["config"])), 0) + 1
    spots = {int(r["id"]) for r in _spots_by_mission().get(int(m["mission_id"]), [])}
    laid = False
    for (spot, special), n in sorted(want.items()):
        for _ in range(n - have.get((spot, special), 0) if spot in spots else 0):
            if _add_special(m, spot, special, skill_of[(spot, special)], MARKER_SOURCE, spot) is None:
                break
            laid = True
    return laid


BELONG_OURS_INT, BELONG_ENEMY_INT = 1, 2


def _ready(m, source_type, source_value, sid):
    """Not cast yet this turn and off cooldown: a cast on turn t with cd_time c shows
    next_skill_cd_turn t + c and comes again on a later turn (recorded on 126 / 11374: the
    startMission casts, next_skill_cd_turn 1, came again on turn 2, not in enemy turn 1)."""
    cd = (m.get("cooldowns") or {}).get(f"{source_type}:{source_value}:{sid}")
    return cd is None or int(m["turn"]) > int(cd["next_skill_cd_turn"])


@lru_cache(maxsize=None)
def _commander_skills(building_id):
    """The use_building_skill of the enemy team that uses this building (enemy_team use_building)."""
    for row in stc.table("enemy_team"):
        if str(row.get("use_building") or "") == str(building_id):
            return tuple(_ids(row.get("use_building_skill")))
    return ()


def _building_turn_skills(state, m, belong):
    """Each turn a working building casts its mission_skill slot for its side again (not the
    inherent ones, which are cast once at startMission): ours at startTurn, the enemy's at
    startEnemyTurn after the moves. Recorded: 11374's 9584007 cast 580112 (and its follow-ups) at
    every startTurn, 9584211 its 95842020 once its trigger held (turn 4); on 126 the enemy
    turrets cast 9130116 and 9130203 its 900002 at each startEnemyTurn from turn 2."""
    replies = []
    for spot in sorted((m.get("buildings") or {}), key=int):
        b = m["buildings"][spot]
        if int(b.get("belong") or 0) != belong or spot in m.get("buildings_down", []):
            continue
        slots = str(_buildings().get(b["building_id"], {}).get("mission_skill") or "").split(";")
        ids = _ids(slots[belong]) if belong < len(slots) else []
        off = _spot_of(m, int(spot)) is None or str(_spot_of(m, int(spot)).get("belong")) == "99"
        if off and belong == BELONG_ENEMY_INT:
            # a commander's building on a node out of play casts its team's use_building_skill every
            # enemy turn (Slow Shock: 6580019 on 60177 for team 6589999, which no node places; its
            # summons by stage marker give the sheet's waves: pair 1 at the start and turn 1, pair t
            # on turn t)
            ids += _commander_skills(b["building_id"])
        for sid in ids:
            cfg = _mission_skills().get(sid)
            if (cfg is None or _does_nothing(cfg) or not _ready(m, SOURCE_BUILDING, int(spot), sid)
                    or not _triggered(state, m, cfg, int(spot))):
                continue
            targets = _skill_targets(state, m, cfg, int(spot))
            replies.append(_cast_skill(state, m, cfg, SOURCE_BUILDING, int(spot), targets, _unit_on(m, int(spot))))
            casts = m.setdefault("casts", {})       # counted for the "min_casts" spawn key
            casts[str(sid)] = int(casts.get(str(sid), 0)) + 1
    return replies


def _team_chip_skills(state, team):
    """The map skills of the chips a Coalition echelon's units carry (sangvis_chip
    passive_mission_skill "group:level,...": 1003 ExtraAp "30003:1,2" is 3000301; recorded on 126)."""
    rec = next((t for t in state.get("sangvis_team_with_user_info") or [] if str(t.get("team_id")) == str(team)), {})
    info = rec.get("info") or {}
    units = {str((slot or {}).get("sangvis_with_user_id") or 0) for slot in (info.values() if isinstance(info, dict) else info)}
    units.discard("0")
    chips = {int(r["id"]): r for r in stc.table("sangvis_chip")}
    out = []
    for c in state.get("sangvis_chip_with_user_info") or []:
        if str(c.get("sangvis_with_user_id") or 0) not in units or str(c.get("chip_slot") or 0) == "0":
            continue
        for part in str(chips.get(int(c.get("chip_id") or 0), {}).get("passive_mission_skill") or "").split(";"):
            group, _, levels = part.partition(":")
            if not group.strip().isdigit():
                continue
            sid = int(group) * 100 + int((_ids(levels) or [1])[0])
            if sid in _mission_skills() and sid not in out:
                out.append(sid)
    return out


def _chip_skills(state, m, teams=None, every_turn=False):
    """Coalition chips' map skills on their echelon: when it is deployed (startMission,
    reinforceSangvisTeam) and, for those with cd_time_type 1, again at every startTurn
    (recorded on 126: 3000301 at startMission or reinforcement and each startTurn; 3000501 once)."""
    replies = []
    for team in (teams if teams is not None else sorted(m.get("sangvis_pos") or {})):
        if not _own_sangvis(team):
            continue
        for sid in _team_chip_skills(state, team):
            cfg = _mission_skills()[sid]
            if every_turn and (int(cfg.get("cd_time_type") or 0) != 1 or not _ready(m, SOURCE_SANGVIS, int(team), sid)):
                continue
            replies.append(_cast_skill(state, m, cfg, SOURCE_SANGVIS, int(team), [], ("sangvis", str(team))))
    return replies


_SKILL_ACTS = ("trigger_id", "target_id", "special_spot_add", "special_spot_minus", "mission_buff_add",
               "mission_buff_minus", "subsidiary_mission_skill", "allyteam_summoner", "resources_change")


def _does_nothing(cfg):
    """A placeholder skill (2000005: every field blank or 0); not cast at startMission (recorded
    on 11374: belong-3 buildings' 2000005/2000006 are missing from fairy_skill_perform)."""
    return not any(str(cfg.get(k) or "").strip() not in ("", "0") for k in _SKILL_ACTS)


def _building_skill_on_death(state, m, on_death):
    """buildingSkillPerformOnDeath {"building_missionskills_on_death_k": {"<building spot>": [i, ...]}}:
    entry i of that building's stc missionskill_on_death ("kind,team,mission skill,0;...", e.g.
    "2,580901,580060,0": allied team 580901 died) is cast from the building onto its own spot.
    Recorded on 11341: ally 580901 died in battle, entry 0 (580060) swapped special spot 580098
    for 580097 there, and the reply carried mission_lose_result (lose_type 580001: 1406 580098:0)."""
    replies = []
    for spot, picks in on_death.items():
        b = (m.get("buildings") or {}).get(str(spot))
        if b is None:
            continue
        entries = [e.split(",") for e in str(_buildings().get(b["building_id"], {}).get("missionskill_on_death") or "").split(";") if e]
        for i in (picks if isinstance(picks, list) else [picks]):
            entry = entries[int(i)] if str(i).lstrip("-").isdigit() and 0 <= int(i) < len(entries) else []
            cfg = _mission_skills().get(int(entry[2])) if len(entry) > 2 and entry[2].isdigit() else None
            if cfg is not None:
                replies.append(_cast_skill(state, m, cfg, SOURCE_BUILDING, int(spot), [int(spot)], _unit_on(m, spot)))
    return _check_loss(state, m, _reveal(state, m, _merge_replies(replies))) if replies else {}


def unit_skill_perform(state, body):
    """Mission/sangvisSkillPerform {sangvis_spot, mission_skill_config_id, spot_ids} and
    vehicleSkillPerform {vehicle_spot, ...}: the skill's effects as for fairies, plus {"ap"}
    (+ "after_exp" for vehicles), read unguarded."""
    m = _mission(state)
    if m is None:
        return None
    body = body or {}
    cfg = _mission_skills().get(int(body.get("mission_skill_config_id") or 0), {})
    m["ap"] = max(0, int(m.get("ap") or 0) - int(cfg.get("ap_cost") or 0))
    targets = body.get("spot_ids")
    targets = _ids(",".join(str(t) for t in targets) if isinstance(targets, list) else targets)
    if "vehicle_spot" in body:
        spot = _spot_of(m, body.get("vehicle_spot"))
        vid = int((spot or {}).get("vehicle_with_user_id") or 0)
        reply = _cast_skill(state, m, cfg, SOURCE_VEHICLE, vid, targets, ("vehicle", str(vid))) if cfg else {}
        veh = workshop._find(state.get("vehicle_with_user_info"), vid)
        reply["after_exp"] = int((veh or {}).get("exp") or 0)
    else:
        spot = _spot_of(m, body.get("sangvis_spot"))
        sid = int((spot or {}).get("sangvis_team_id") or 0)
        reply = _cast_skill(state, m, cfg, SOURCE_SANGVIS, sid, targets, ("sangvis", str(sid))) if cfg else {}
    reply["ap"] = m["ap"]
    return _reveal(state, m, reply)


def special_skill(state, body):
    """Coalition chip special skills. Mission/sangvisActiveSpecialSkill {special_skill_no,
    sangvis_team_spot_id, args, enemy_team_spot_id, target_spot_id} -> {"next_turn", "ap", "mre",
    "ammo", "result"} (unguarded), "type5_score"; Mission/myforceActiveSpecialSkill (buff_instance_id,
    sangvis_chip_id, myforce_*) -> {"ap", "result"}, optional next_turn/target_resource/type5_score.
    The effects are not simulated. The chip's active_special_skill_cost "ap,mre,ammo" is paid and it
    can be used again after active_special_skill_cd turns (recorded: 104, cd 2, used on turn 1 ->
    next_turn 3)."""
    m = _mission(state)
    if m is None:
        return None
    body = body or {}
    spot = _spot_of(m, body.get("sangvis_team_spot_id") or body.get("myforce_spot_id"))
    team = str((spot or {}).get("sangvis_team_id") or 0)
    special = int(body.get("special_skill_no") or 0)
    holder = _chip_holder(state, team, special) if special else None
    chip = _chip_row(state, holder, special) if holder is not None else {}
    ap, mre, ammo = ([int(x) for x in str(chip.get("active_special_skill_cost") or "0,0,0").split(",")] + [0, 0, 0])[:3]
    m["ap"] = max(0, int(m.get("ap") or 0) - ap)
    res = _spend(state, m, "sangvis", team, (ammo, mre)) if _own_sangvis(team) else {"ammo": 0, "mre": 0}
    # recorded: 104 (cd 2) used on turn 1 -> 3; Pilfer 102 (cd 0) on turn 2 -> 2
    next_turn = int(m["turn"]) + int(chip.get("active_special_skill_cd") or 0)
    if holder is not None:
        # the reply's next_turn is the chip's canUseTurn (RequestSangvisChipSpecialSkill); kept for a
        # resumed map (sangvis_teams_info.chip_special_skill)
        m.setdefault("chip_turns", {}).setdefault(team, {})[str(special)] = {
            "sangvis_with_user_id": int(holder), "next_turn": next_turn}
    reply = {"next_turn": next_turn, "ap": int(m.get("ap") or 0), "ammo": str(res["ammo"]),
             "mre": str(res["mre"]), "type5_score": 0, "result": True}
    args = body.get("args") if isinstance(body.get("args"), dict) else {}
    target = _spot_of(m, args.get("target_spot_id"))
    prey = _spot_of(m, args.get("enemy_team_spot_id"))
    if special == 102 and prey is not None and int(prey.get("enemy_team_id") or 0):
        # Pilfer: a doll from the enemy team's drop pool; the enemy stays (recorded)
        _battle_drop(state, reply, prey["enemy_team_id"], always=True)
    if special == 104 and target is not None:
        # 104 resupplies the echelon on args.target_spot_id (recorded: the reply's max_ammo 5 /
        # max_mre 10 for a doll echelon there, as supplyTeam answers)
        full = _fill_spot(state, m, target)
        if full is not None:
            reply["max_ammo"], reply["max_mre"] = full
    return reply


@lru_cache(maxsize=1)
def _chip_specials():
    """stc sangvis_chip id -> its active special skill type (SangvisChipCfg$$get_CurrentSpecialType:
    chips of type 2 or 5 with active_special_skill 101, 102, 203 or 104)."""
    return {str(r["id"]): int(r["active_special_skill"]) for r in stc.table("sangvis_chip")
            if int(r.get("type") or 0) in (2, 5) and str(r.get("active_special_skill") or "") in ("101", "102", "203", "104")}


def _chip_row(state, uid, special):
    unit = workshop._find(state.get("sangvis_with_user_info"), uid) or {}
    for i in (1, 2):
        cid = str(unit.get(f"chip{i}") or 0)
        if _chip_specials().get(cid) == special:
            return next((r for r in stc.table("sangvis_chip") if str(r["id"]) == cid), {})
    return {}


def _chip_holder(state, team, special):
    """The sangvis_with_user_id in our Coalition echelon `team` whose chip has that special skill."""
    row = next((t for t in state.get("sangvis_team_with_user_info") or [] if str(t.get("team_id")) == str(team)), None)
    for slot in ((row or {}).get("info") or {}).values():
        unit = workshop._find(state.get("sangvis_with_user_info"), (slot or {}).get("sangvis_with_user_id") or 0)
        if unit is not None and special in (_chip_specials().get(str(unit.get(f"chip{i}") or 0)) for i in (1, 2)):
            return unit["id"]
    return None


# --- mission skill effects --------------------------------------------------------------
#
# A mission skill (stc mission_skill_config, cast by a fairy, Coalition echelon or vehicle) places
# special spots (special_spot_add "id:n,...", stc special_spot_config) on the target spots and adds
# mission buffs (mission_buff_add, stc mission_buff_config) to echelons. The client keeps both from
# these reply keys (objects in game; JSON strings in the login's mission_act_info, read with
# readObject true), and drops any entry a new copy leaves out, so every copy is the full set (MissionAction$$LoadFairySkillOnSpot / LoadFairySkillOnTeam, ...OnSangvis,
# ...OnVehice; SpecialSpotAction / BuffAction):
#   fairy_skill_on_spot     {"<spot>": {"<instance>": {source_type, source_value,
#                           special_spot_config_id, building_id, squad_teaminstance_id, start_turn,
#                           battle_count, move_count, mission_skill_config_id}}}
#   fairy_skill_on_team     {"<team>": {"<instance>": {source_type, source_value, buff_id,
#   / _on_sangvis / _on_vehicle   start_turn, battle_count, battle_finish_count, person_move_count,
#                           person_shift_count, mission_skill_config_id}}}  (keyed by team id,
#                           Coalition team id, vehicle_with_user_id)
#   fairy_skill_perform     [{source_type, source_value, mission_skill_config_id, next_skill_cd_turn}]
# Buffs go to the caster's own echelon when the skill has no range (start_range 0), else to our
# units on the target spots. What a buff does in battle (battle_skill_config_id) is the client's.
# Every turn reply runs these loaders (startTurn, startEnemyTurn, teamMove, ...), so effects that
# run out are dropped at the start of our next turn, and triggered traps at once.
# Traps: a special spot with a mission_hurt_config, meant for enemies (effect_target_type 4,5,6) and
# set off by entering (conditions_type 3), hits an enemy that steps on it (startEnemyTurn): it loses
# the hurt's value in percent of its current HP (value "*0" = the skill's data_pool), never dying of
# it, and bosses are spared (Mines Frontline, Enhanced Beartrap: "ineffective against bosses"). A
# trap whose buff has cannot_move holds the enemy for its next turn. The new HP goes out as the
# move's hp_percent.
# Durations (duration_type/duration_time pairs): special spots 1 turns, 2 battles, 3 triggers
# (moves onto it); buffs see _BUFF_COUNTS.
# A special spot's skill_config_id_on_birth / _on_death "buff,hurt,special spot" act on the units on
# its spot when it appears / runs out (Reinforcement: buff 8 + one dummy link of HP; Nurse: heal;
# Fortress: buff). Hurts (stc mission_hurt_config) change HP and go out as fairy_skill_return
# {"mission_hurt": [entry]} with absolute results (HurtAction$$LoadHurtData: guns_life
# [{gun_with_user_id, life}], sangvises_life, enemy_hp_percent, ...; every id key present, 0 if
# unused). Negative values heal; the value is a percent of current (life_type 1) or full (2) HP, or
# of one dummy link (is_number 1); target_type 1 hits only the doll with the lowest HP share.
# Our units keep at least 1 HP, enemies at least 1%, and bosses are spared.
# Airborne skills (Parachute) move the echelon; the client flies it itself (see _airdrop).
# Traps reach effect_range nodes around their spot. Entering hazards aimed at our units
# (effect_target_type 1 / 8 / 10) hurt the echelon that moves in (teamMove, sangvisMove, vehicle
# moves reply with fairy_skill_return.mission_hurt).
# Summons: allyteam_summoner places those stc ally_team forces on the target spots, sent as
# fairy_skill_return {"allyteam_summoner": [{ally_instance_id, spot_id, ally_instance_info}]}.
# Buildings, buffs and map events cast through building_skill (active_mission_skills).
# A skill's subsidiary_mission_skill is cast with it (same targets, SUB_DEPTH deep; only the main
# cooldown is shown). Buffs that act after battles (conditions_type 4) and share their id with a
# mission_hurt_config apply it to their unit when it ends a battle (Heart-Healing Hymn: heals for the
# first 5 battles); the battle reply can't carry it, so it goes out with the next reply that runs
# the skill loaders. Hurts change vehicle HP too (vehicle_life).
# A follow-up skill with a trigger_id only fires when its node search finds something (_triggered).

SOURCE_GUN, SOURCE_SANGVIS, SOURCE_VEHICLE = 99901, 99903, 99905
# Unit codes (special spots' detect/effect_target_type, skills' spot_echelon, lose type 1409): the
# client's SpotAction$$get_teamEchelon gives what stands on a node: 1 our doll echelon, 8 our
# Coalition echelon, 10 our vehicle echelon, 2 a team with a negative id (friend echelons), 4 an
# enemy, 7 a HOC (squad), an allied force by its side and kind (friendly: 3, 301 one we can
# supply/control, 302 / 303 Coalition units (303 suppliable), 304 with vehicles; 5 enemy side;
# 6 neutral), 201 a hostage, 0 nothing. (The data agrees: 510703 [1, 7, 8, 10] is all ours,
# 6510115 [3, 10, 301-305] allied forces.)
UNIT_GUN, UNIT_SANGVIS, UNIT_VEHICLE = 1, 8, 10
UNIT_FRIEND, UNIT_SQUAD = 2, 7
OURS = {UNIT_GUN, UNIT_SANGVIS, UNIT_VEHICLE, UNIT_SQUAD, UNIT_FRIEND}
BIRTH, DEATH = "birth", "death"
SUB_DEPTH = 6                 # subsidiary_mission_skill chains followed this deep (11374: 580112 >
                              # 580116 > 580100 > 580103 > 580107 is 4)
COND_AFTER_BATTLE = 4         # mission_buff_config.conditions_type: acts when a battle ends
HYMN_GROUP, HYMN_BATTLES, HYMN_HURT = 24, 5, 2401
PERSON_ECHELON = 0
HURT_LOWEST = 1
ENEMY_TARGETS = {4, 5, 6}
DUR_TURNS, DUR_BATTLES, DUR_TRIGGERS = 1, 2, 3   # duration_type: turns, battles, moves onto it
DUR_MOVES = DUR_TRIGGERS
COND_TURN, COND_BATTLE, COND_MOVE = 1, 2, 3        # conditions_type (SpecialSpotCfg$$InitData)
COND_ENTER = COND_MOVE
# 4, always beside 3 ("3,4": 20 configs, mines among them), read as a battle finished there, as in
# mission_buff_config's duration types (2 fought, 4 finished). INFERRED: nothing recorded sets one off.
COND_BATTLE_END_AS = {"4": str(COND_BATTLE)}
_EFFECT_KEYS = {"team": "fairy_skill_on_team", "sangvis": "fairy_skill_on_sangvis",
                "vehicle": "fairy_skill_on_vehicle", "ally": "fairy_skill_on_ally", "enemy": "fairy_skill_on_enemy",
                # keyed by squad instance / friend_team_id (MissionAction$$LoadFairySkillOnSquad,
                # LoadFairySkillOnFriend, LoadFairySkillOnFriendSangvis: the same BuffAction entries)
                "squad": "fairy_skill_on_squad", "friend_team": "fairy_skill_on_friend_team",
                "friend_sangvis": "fairy_skill_on_friend_sangvis"}


@lru_cache(maxsize=1)
def _mission_buffs():
    return {int(r["id"]): r for r in stc.table("mission_buff_config")}


@lru_cache(maxsize=1)
def _hurts():
    return {int(r["id"]): r for r in stc.table("mission_hurt_config")}


def _counted(text):
    """'id:n,id:n' -> [id, ...], each id n times."""
    out = []
    for part in str(text or "").split(","):
        sid, _, n = part.partition(":")
        if sid.strip().isdigit():
            out += [int(sid)] * max(1, int(n) if n.strip().isdigit() else 1)
    return out


def _durations(row):
    types, times = str(row.get("duration_type") or "").split(","), str(row.get("duration_time") or "").split(",")
    return {int(t): int(v) for t, v in zip(types, times) if t.strip().isdigit() and v.strip().isdigit()}


def _number(text):
    try:
        return float(str(text).strip())
    except ValueError:
        return 0.0


def _effects(m):
    return m.setdefault("effects", {"specials": {}, "buffs": {}, "sent": False})


def _next_instance(m):
    inst = int(m.get("next_special") or 1)
    m["next_special"] = inst + 1
    return str(inst)


def _unit_on(m, spot_id):
    """Our unit standing on a spot, as a buff target: ("team" | "sangvis" | "vehicle", id)."""
    spot = _spot_of(m, spot_id)
    if spot is None:
        return None
    if spot["team_id"] != "0":
        return ("team", spot["team_id"])
    if spot["sangvis_team_id"] != "0":
        return ("sangvis", spot["sangvis_team_id"])
    if int(spot["vehicle_with_user_id"] or 0):
        return ("vehicle", str(spot["vehicle_with_user_id"]))
    ally = _friendly_ally_on(m, spot_id)
    return ("ally", ally) if ally else None


def _echelon_codes(cfg):
    """A skill's spot_echelon unit codes (empty: -1, any)."""
    return {c for c in _ids(cfg.get("spot_echelon")) if c >= 0}


def _occupants(m, spot_id):
    out = list(_units_at(m, spot_id, ()))
    ally, foe = _friendly_ally_on(m, spot_id), _enemy_on(m, spot_id)
    # hostile / third-party forces too (Slow Shock's 6580075, spot_echelon 5, buffed the enemy-side forces)
    others = [("ally", str(iid)) for iid, a in (m.get("allies") or {}).items()
              if int(a["spot"]) == int(spot_id) and str(iid) != str(ally) and a["belong"] != ALLY_FRIENDLY]
    return out + ([("ally", ally)] if ally else []) + others + ([foe] if foe else [])


def _fits_skill(m, unit, codes):
    """A skill's spot_echelon: an enemy answers to 4 only (recorded on Slow Shock: 6580075, code 5,
    buffed the 23 enemy-side forces and none of the enemies); special spots keep ENEMY_TARGETS."""
    if unit[0] == "enemy":
        return 4 in codes
    return _fits_echelon(m, unit, codes)


def _fits_echelon(m, unit, codes):
    if unit[0] == "ally":
        return bool(_ally_codes((m.get("allies") or {}).get(str(unit[1]), {"belong": -1})) & codes)
    return bool(_UNIT_CODES.get(unit[0], set()) & codes)


def _skill_recipients(m, cfg, source_type, spot_id):
    """Who a skill's buffs reach on a target spot: units of its spot_echelon codes (recorded on
    11374: 580123 "0,1,7,8,301,..." only ours; 95842012 "4" enemies). -1: everyone for a building's
    skill (9584001 / 9584201 on enemies), our units and allied forces for the rest."""
    codes = _echelon_codes(cfg)
    here = _occupants(m, spot_id)
    if codes:
        return [u for u in here if _fits_skill(m, u, codes)]
    return [u for u in here if source_type == SOURCE_BUILDING or u[0] != "enemy"][:1 if source_type != SOURCE_BUILDING else None]


def _enemy_on(m, spot_id):
    spot = _spot_of(m, spot_id)
    return ("enemy", spot["enemy_instance_id"]) if spot is not None and int(spot.get("enemy_team_id") or 0) else None


def _friendly_ally_on(m, spot_id):
    """A friendly allied force on a spot (its instance id), which holds map buffs like our units
    (recorded on 11341: fairy_skill_on_ally {instance: {n: {"ally": instance, buff_id, ...}}})."""
    return next((str(iid) for iid, a in (m.get("allies") or {}).items()
                 if int(a["spot"]) == int(spot_id) and a["belong"] == ALLY_FRIENDLY), None)


def _skill_distances(mid, start):
    """Steps from start over links taken either way: a skill's start_range (recorded on 11341:
    range 1 from 3500309 reached 3500303 and 3500310, which only link into it)."""
    dist, todo, links = {start: 0}, [start], _neighbours(mid)
    while todo:
        cur = todo.pop(0)
        for nxt in links.get(cur, ()):
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                todo.append(nxt)
    return dist


SKILL_NIGHT_ONLY = 2


def _cast_skill(state, m, cfg, source_type, source_value, targets, caster, depth=0):
    """Place a skill's special spots and buffs; returns a reply with its cooldown, the effect
    keys and what the spots' birth hurts did. caster: the unit using it, as _unit_on gives."""
    if int(cfg.get("is_night") or 0) == SKILL_NIGHT_ONLY and not is_night(m["mission_id"]):
        # mission_skill.is_night 2: night maps only, like C96's flare (player report); 1 / 0 any map
        return {"fairy_skill_perform": []}
    fx, turn, hurts = _effects(m), int(m["turn"]), []
    _rule_points(m, "skills", int(cfg["id"]))        # a score map's points for this skill (field 18)
    cooldown = {"source_type": source_type, "source_value": source_value, "mission_skill_config_id": int(cfg["id"]),
                "next_skill_cd_turn": turn + int(cfg.get("cd_time") or 0)}
    reply = {"fairy_skill_perform": [cooldown]}
    if depth == 0 or source_type == SOURCE_BUILDING:
        # a building's follow-ups are listed too (recorded on 11341's startMission);
        # kept for a resumed map (resume_info: fairy_skill_perform), so a restart doesn't reset it
        m.setdefault("cooldowns", {})[f"{source_type}:{source_value}:{cfg['id']}"] = dict(cooldown)
    # "id:n" takes n copies off each target spot (recorded on 11341: 580099:7 then 580099:2 left 5);
    # with no targets, copies anywhere on the map
    minus = _counted(cfg.get("special_spot_minus"))
    for spot in ([int(t) for t in targets] or [None]):
        for ss_id in minus:
            hits = [i for i, sp in fx["specials"].items() if sp["config"] == ss_id and spot in (None, int(sp["spot"]))]
            if hits:
                del fx["specials"][hits[0]]
    for ss_id in _counted(cfg.get("special_spot_add")):
        row = _special_spots().get(ss_id)
        if row is None:
            continue
        for sid in targets:
            sp = _add_special(m, int(sid), ss_id, int(cfg["id"]), source_type, source_value)
            if sp is None:
                continue
            hurts += _special_effects(state, m, sp, BIRTH)
            _drop_instant(m, sp)
            if int(cfg.get("skill_group_id") or 0) == ILLUMINATION:
                lasts = max(1, (_ids(row.get("duration_time")) or [1])[0])
                m.setdefault("lights", []).append({"spot": sid, "until": turn + lasts})
    removed = set(_counted(cfg.get("mission_buff_minus")))
    fx["buffs"] = {i: b for i, b in fx["buffs"].items() if b["buff_id"] not in removed}
    effects = []                            # fairy_skill_return.fairy_effect: the buffs given, shown on the unit
    units = [caster] if caster else []      # a building with nobody on it buffs only its targets
    if int(cfg.get("start_range") or 0) and targets or not caster:
        units = [u for t in targets for u in _skill_recipients(m, cfg, source_type, t)] or units
    for buff_id in _counted(cfg.get("mission_buff_add")):
        if buff_id not in _mission_buffs():
            continue
        for kind, uid in units:
            if any(b["kind"] == kind and b["unit"] == str(uid) and b["buff_id"] == buff_id and b["skill"] == int(cfg["id"])
                   for b in fx["buffs"].values()):
                continue        # one copy per skill (11374: 9583805 once, from 95842012 and its 9584204)
            if not _buff_room(m, kind, uid, buff_id):
                continue
            fx["buffs"][_next_instance(m)] = {"kind": kind, "unit": str(uid), "buff_id": buff_id,
                                             "skill": int(cfg["id"]), "source_type": source_type,
                                             "source_value": source_value, "start_turn": turn}
            aim = _unit_spot(m, kind, uid)
            if source_type == SOURCE_BUILDING and source_value and aim is not None:
                effects.append({"origin_key": 0, "origin_spot": int(source_value), "origin_type": EFFECT_FROM_BUILDING,
                                "origin_stc_id": str(cfg["id"]), "aim_spot": int(aim), "aim_type": EFFECT_ON_UNIT,
                                "aim_stc_id": int(buff_id)})
    summoned = []
    # "a;b": one of them on each node, drawn per node (recorded on Slow Shock 11403: 6589046
    # "6589221;6589222" put one force on each marked portal node, 6589240 / 6589239 alternating)
    choices = _ids(cfg.get("allyteam_summoner"))
    for sid in (targets or [_caster_spot(m, caster)]) if choices else []:
        for team_id in [random.choice(choices)]:
            iid = _new_ally(m, team_id, _spot_of(m, sid)) if sid is not None else None
            if iid is not None:
                summoned.append({"ally_instance_id": int(iid), "spot_id": int(sid),
                                 "ally_instance_info": _ally_json(m, m["allies"][iid])})
    dropped = _map_items(m, cfg)
    if hurts or summoned or dropped or effects:
        reply["fairy_skill_return"] = {"mission_hurt": hurts, "allyteam_summoner": summoned}
        if dropped:
            reply["fairy_skill_return"]["drop_item"] = dropped
        if effects:
            reply["fairy_skill_return"]["fairy_effect"] = _effect_entries(m, effects)
    # a building's follow-ups search from the building, also when it's worked from elsewhere (recorded
    # 2026-11-12 on 10508: the team on the console 91501 worked the hidden building on 91529, whose
    # 390135 -> 390136 (spot_type 3, belong 2, range 5) marked G3 / G5, 5 nodes from 91529)
    origin = ((source_value if source_type == SOURCE_BUILDING and source_value else None)
              or _caster_spot(m, caster) or (targets or [None])[0])
    subs = [_mission_skills()[i] for i in _ids(cfg.get("subsidiary_mission_skill")) if i in _mission_skills()]
    subs = [sub for sub in subs if _triggered(state, m, sub, origin)]
    if source_type == SOURCE_BUILDING and str(cfg.get("target_id") or "").strip() and not targets:
        subs = []           # recorded on 11341: 3500307's 580908 found no target, 580913 didn't follow
    if subs and depth < SUB_DEPTH:
        # a building's follow-ups pick their own targets (11341: 580903 -> 580904 on its neighbours)
        # (11374: 95842020's 95842021, start_range 100 and spot_echelon 4,5,6, put 9584208 on the 11
        # spots with enemies, not on 95842020's own target)
        own = lambda sub: (_skill_targets(state, m, sub, origin) if source_type == SOURCE_BUILDING
                           and (str(sub.get("target_id") or "").strip() or int(sub.get("start_range") or 0))
                           else targets)
        # a follow-up whose target_id finds nothing isn't cast (11603: 660000's 660041-660070 score
        # only for the echelons with their promotion buff; 11630: 480172 summons Grig only at 4)
        aimed = [(sub, own(sub)) for sub in subs]
        aimed = [(sub, t) for sub, t in aimed if t or not str(sub.get("target_id") or "").strip()]
        parts = [_cast_skill(state, m, sub, source_type, source_value, t, caster, depth + 1) for sub, t in aimed]
        for part in parts:
            part.pop("fairy_skill_perform", None)       # the main skill's cooldown is the one shown
        reply = _merge_replies([reply] + parts)
    return _effect_keys(m, reply, force=True)


# trigger_index: node searches around a spot, within the skill's start_range (MissionData
# $$CheckTargetCondition, SpotAction$$GetRangeSpotInfo). trigger_id joins ids with && or & (nodes
# both find) and || or | (either), with brackets; each id's own condition is "X*>n", "X*==n" or
# "X*<n" joined by && / ||. Types: 1 the spot itself, 2 the spot's special spots (or, with no
# special spot condition, its unit's map buffs), 3 nodes whose special spots match, 4 nodes whose
# units' map buffs match, 5 nodes holding enemy team X, 6 nodes holding allied force X, 7-11 a
# map-wide check (7 an inventory item; 8/9 mission items got/used on this map (_map_items), 10/11
# the map score, X ignored) that, when true, finds every node in range.
TRIG_SELF, TRIG_HERE, TRIG_SPECIAL, TRIG_BUFF, TRIG_ENEMY, TRIG_ALLY, TRIG_ITEM = 1, 2, 3, 4, 5, 6, 7
TRIG_ITEM_GOT, TRIG_ITEM_USED, TRIG_SCORE, TRIG_ENDLESS_SCORE = 8, 9, 10, 11


@lru_cache(maxsize=1)
def _trigger_rows():
    return {int(r["id"]): r for r in stc.table("trigger_index")}


def _condition(text, count):
    """ "X*>n && Y*==0 || ..." with count(X) the copies of X ("," also means && : "X*>2,X*<6" is a
    range); an empty condition holds."""
    text = str(text or "").strip()
    if not text:
        return True
    for alt in text.split("||"):
        ok = True
        for part in re.split(r"&&|,", alt):
            x, _, rest = part.strip().partition("*")
            op = next((o for o in ("==", ">", "<") if rest.startswith(o)), None)
            if op is None or not x.strip().lstrip("-").isdigit():
                continue
            have, want = count(int(x)), int(rest[len(op):] or 0)
            ok &= {"==": have == want, ">": have > want, "<": have < want}[op]
        if ok:
            return True
    return False


ANYWHERE = 99     # a start_range this large reaches every spot, layers not linked to the caster's
                  # included (No More Omens' console 420201, 100: the landing spot on the other layer)


def _trigger_nodes(state, m, tid, origin, reach):
    row = _trigger_rows().get(tid)
    if row is None:
        return set()
    fx, kind = _effects(m), int(row["type"])
    dist = _skill_distances(m["mission_id"], int(origin))
    near = {sid for sid, d in dist.items() if d <= reach}
    if reach >= ANYWHERE:
        near |= {int(s["spot_id"]) for s in m["spots"]}

    def specials(sid):
        return lambda x: sum(1 for sp in fx["specials"].values() if int(sp["spot"]) == sid and sp["config"] == x)

    def buffs(sid):
        here = {(k, str(u)) for k, u in _units_at(m, sid, ())}
        ally = _friendly_ally_on(m, sid)
        if ally:
            here.add(("ally", ally))
        return lambda x: sum(1 for b in fx["buffs"].values() if b["buff_id"] == x and (b["kind"], b["unit"]) in here)

    if kind == TRIG_SELF:
        return {int(origin)} if _condition(row["person_condition"], lambda x: 0) else set()
    if kind == TRIG_HERE:
        if str(row["special_spot_condition"]).strip():
            return {int(origin)} if _condition(row["special_spot_condition"], specials(int(origin))) else set()
        return {int(origin)} if _condition(row["mission_buff_condition"], buffs(int(origin))) else set()
    if kind == TRIG_SPECIAL:
        return {sid for sid in near if _condition(row["special_spot_condition"], specials(sid))}
    if kind == TRIG_BUFF:
        return {sid for sid in near if _condition(row["mission_buff_condition"], buffs(sid))}
    if kind == TRIG_ENEMY:
        team = lambda sid: lambda x: int(int((_spot_of(m, sid) or {}).get("enemy_team_id") or 0) == x)
        return {sid for sid in near if _condition(row["person_condition"], team(sid))}
    if kind == TRIG_ALLY:
        force = lambda sid: lambda x: sum(1 for a in (m.get("allies") or {}).values()
                                          if int(a["spot"]) == sid and int(a["ally_team_id"]) == x)
        return {sid for sid in near if _condition(row["person_condition"], force(sid))}
    if kind == TRIG_ITEM:
        from . import squads
        held = lambda x: int(squads._item(state, x)["number"]) if any(
            str(i["item_id"]) == str(x) for i in state.get("item_with_user_info") or []) else 0
        return near if _condition(row["person_condition"], held) else set()
    if kind in (TRIG_ITEM_GOT, TRIG_ITEM_USED):
        led = (m.get("items") or {}).get("got" if kind == TRIG_ITEM_GOT else "cost") or {}
        return near if _condition(row["person_condition"], lambda x: int(led.get(str(x), led.get(x, 0)) or 0)) else set()
    if kind in (TRIG_SCORE, TRIG_ENDLESS_SCORE):
        return near if _condition(row["person_condition"], lambda x: int(m.get("score") or 0)) else set()
    return near if _condition(row["person_condition"], lambda x: 0) else set()


def _expr_nodes(state, m, expr, origin, reach):
    """The nodes a trigger_index expression ("a&&b||(c|d)") finds around origin."""
    tokens = re.findall(r"\d+|&&?|\|\|?|\(|\)", str(expr or ""))
    pos = 0

    def atom():
        nonlocal pos
        tok = tokens[pos] if pos < len(tokens) else ""
        pos += 1
        if tok == "(":
            out = either()
            pos += 1                                    # ")"
            return out
        return _trigger_nodes(state, m, int(tok), origin, reach) if tok.isdigit() else set()

    def both():
        nonlocal pos
        out = atom()
        while pos < len(tokens) and tokens[pos] in ("&", "&&"):
            pos += 1
            out &= atom()
        return out

    def either():
        nonlocal pos
        out = both()
        while pos < len(tokens) and tokens[pos] in ("|", "||"):
            pos += 1
            out |= both()
        return out

    return either()


def _triggered(state, m, cfg, origin):
    """A skill's trigger_id finds at least one node around origin (no trigger_id: always)."""
    expr = str(cfg.get("trigger_id") or "").strip()
    if not expr or origin is None:
        return True
    return bool(_expr_nodes(state, m, expr, origin, int(cfg.get("start_range") or 0)))


def _skill_targets(state, m, cfg, origin):
    """The spots a server-cast skill acts on: its target_id's nodes around origin within
    start_range (target 1 is origin itself), in spot order. No target_id: origin, or with a
    start_range every spot in play within it (recorded on 11374: 95842011, range 2, from 3500547
    and 3500560 put 9584203 on them and the 13 spots around, not on the belong-100 spots
    3500563/3500564)."""
    expr = str(cfg.get("target_id") or "").strip()
    reach = int(cfg.get("start_range") or 0)
    if origin is None:
        return []
    if not expr:
        if not reach:
            return [int(origin)]
        found = {sid for sid, d in _skill_distances(m["mission_id"], int(origin)).items() if d <= reach}
        if reach >= WHOLE_MAP:
            # range 99 is the whole map, also from a node with no links (Slow Shock's commander on
            # the network node 60177: its 6580075 buffed all 23 enemy-side forces, recorded)
            found = {int(s["spot_id"]) for s in m["spots"]}
    else:
        found = _expr_nodes(state, m, expr, origin, reach)
    belong = {int(s["spot_id"]): str(s.get("belong")) for s in m["spots"]}
    codes = _echelon_codes(cfg)
    if codes:
        # spot_echelon picks spots by who stands there (0: nobody); recorded on 11374: 95842012
        # ("4", range 1 of 3500559/3500560) put 9584204 only where enemies stood
        # 0 (nobody) also means no hostile allied force: City of Nightmares' Bramedb (480173) is
        # summoned on D4 only if Grig (480142, a hostile force) is gone ('spawns on D4 (if empty)')
        taken = _taken(m) if 0 in codes else set()
        found = {sid for sid in found if any(_fits_skill(m, u, codes) for u in _occupants(m, sid))
                 or (0 in codes and not _occupants(m, sid) and sid not in taken)}
    kinds = _spot_kinds(cfg)
    if kinds:
        # spot_type: only spots of those types (recorded on 126: 900002, "3,7,-3,-7,1" range 2 from
        # 91189, went on the heliports 91188 / 91190, not on the plain spots 91185 / 91187 / 91189)
        types = _spot_types(m["mission_id"])
        found = {sid for sid in found if types.get(sid) in kinds}
    sides = {t for t in _signed_ids(cfg.get("spot_belong")) if t >= 0}
    if sides:
        found = {sid for sid in found if int(belong.get(sid) or 0) in sides}
    return sorted(sid for sid in found if belong.get(sid) in _IN_PLAY or (sid == int(origin) and not kinds and not sides))


WHOLE_MAP = 99                      # a start_range this big reaches every node
_IN_PLAY = {"0", "1", "2", "3"}      # spot belongs a skill can act on (100: out of play)


def _signed_ids(text):
    return [int(t) for t in re.findall(r"-?\d+", str(text or ""))]


def _spot_kinds(cfg):
    """mission_skill_config spot_type as a set of spot types ("-1": any). The negative entries
    are the timed heliports (SpotType -3 / -7, see AP_SPOT_TYPES)."""
    ids = _signed_ids(cfg.get("spot_type"))
    return set() if not ids or -1 in ids else set(ids)


# fairy_skill_return.fairy_effect {"<n>": {origin_key, origin_spot, origin_type, origin_stc_id, aim_spot,
# aim_type, aim_stc_id}} (MissionAction$$LoadFairySkillReturn -> MissionProcessEffectAction): what a
# skill did, played on the map; a BuffAction looks its effect up when it is made. Recorded: a building
# skill giving a buff answers origin_type 4 (a building) with the skill, aim_type 2 (a buff on the unit
# on aim_spot) with the buff: 11497's 6630005 on Ally 3 ({"139": {... "origin_stc_id": "6630005",
# "aim_spot": 600165, "aim_type": 2, "aim_stc_id": 6630020}}), map 129's start giving 1000000 Portable
# Explosives; aim_type 1 is a special spot. The count runs over the map. Without it the Goliath's
# Portable Explosives didn't show on the echelon (player report, 2026-11-13).
EFFECT_FROM_BUILDING, EFFECT_ON_SPOT, EFFECT_ON_UNIT = 4, 1, 2


def _effect_entries(m, effects):
    out = {}
    for e in effects:
        m["effect_count"] = int(m.get("effect_count") or 0) + 1
        out[str(m["effect_count"])] = e
    return out


def _unit_spot(m, kind, uid):
    """Where a unit stands: echelons, Coalition echelons, vehicles, allied forces, enemies."""
    if kind in ("team", "sangvis", "vehicle"):
        return _caster_spot(m, (kind, uid))
    if kind == "ally":
        return ((m.get("allies") or {}).get(str(uid)) or {}).get("spot")
    if kind == "enemy":
        return next((s["spot_id"] for s in _enemy_spots(m) if s["enemy_instance_id"] == str(uid)), None)
    return None


def _caster_spot(m, caster):
    if not caster:
        return None
    kind, uid = caster
    pos = {"team": "team_pos", "sangvis": "sangvis_pos", "vehicle": "vehicle_pos"}.get(kind)
    return (m.get(pos) or {}).get(str(uid)) if pos else None


def _merge_replies(replies):
    """Several casts in one call: hurts and summons add up; cooldowns and effect keys are the last copy."""
    out = {}
    for r in replies:
        for k, v in r.items():
            if k == "fairy_skill_perform":
                out[k] = v                                  # each copy is the whole list
            elif k == "died_this_section" and isinstance(v, dict):
                died = out.setdefault(k, {"enemy": [], "ally": []})
                for side in ("enemy", "ally"):
                    died[side] = list(died.get(side) or []) + list(v.get(side) or [])
            elif k == "fairy_skill_return":
                ret = out.setdefault(k, {"mission_hurt": [], "allyteam_summoner": []})
                for kk in ("mission_hurt", "allyteam_summoner"):
                    ret[kk] += v.get(kk, [])
                ret.setdefault("fairy_effect", {}).update(v.get("fairy_effect") or {})
                if not ret["fairy_effect"]:
                    del ret["fairy_effect"]
                for iid, n in (v.get("drop_item") or {}).items():
                    ret.setdefault("drop_item", {})[iid] = ret.get("drop_item", {}).get(iid, 0) + int(n)
                for kind, changed in (v.get("allyteam_b_t") or {}).items():
                    bt = ret.setdefault("allyteam_b_t", {"ally_instance_transform": {}, "ally_instance_betray": {},
                                                         "building_defender_change": []})
                    if isinstance(changed, dict):
                        bt[kind].update(changed)
            elif v == [] and out.get(k) == {} and (k == "fairy_skill_on_spot" or k in _EFFECT_KEYS.values()):
                pass        # an earlier cast's {} clears the client's copy (_effect_keys); a later [] would skip it
            else:
                out[k] = v
    return out


def _forbidden_specials(mid):
    """{spot: {special spot config ids the stc's spot.forbid_specialspot keeps off it}}."""
    out = {}
    for r in _spots_by_mission().get(int(mid)) or []:
        ids = _ids(r.get("forbid_specialspot"))
        if ids:
            out[int(r["id"])] = set(ids)
    return out


def _add_special(m, spot_id, config, skill, source_type, source_value):
    """Place one special spot; None when a stronger one of its conflict_type holds the spot.
    A different special spot of the same conflict_type on that spot gives way to it when its
    priority is not higher (recorded on 11341: 580097 replaced 580098, both type 580098, priority
    99). Priority -1 stacks (580099 x5 on 3500307, 580101 x13 on 11374's 95539); any other renews
    its own copy (11374: 95842020 cast 6580143 on 95550 each turn and one stayed)."""
    fx, row = _effects(m), _special_spots().get(config, {})
    if int(config) in _forbidden_specials(m["mission_id"]).get(int(spot_id), ()):
        return None         # spot.forbid_specialspot (10508's boss heliports refuse 900001; recorded 2026-11-12)
    ct = int(row.get("conflict_type") or 0)
    if ct not in (0, -1) and int(row.get("priority") or 0) != -1:
        for i, old in list(fx["specials"].items()):
            orow = _special_spots().get(old["config"], {})
            if int(old["spot"]) != int(spot_id) or int(orow.get("conflict_type") or 0) != ct:
                continue
            if int(row.get("priority") or 0) < int(orow.get("priority") or 0):
                return None
            del fx["specials"][i]
    sp = {"spot": spot_id, "config": config, "skill": skill, "source_type": source_type,
          "source_value": source_value, "start_turn": int(m["turn"]), "triggers": 0}
    _effects(m)["specials"][_next_instance(m)] = sp
    if config == COMMANDER_HEAL:
        _commander_heal(m, spot_id)
    seen = m.setdefault("specials_seen", [])
    if config not in seen:
        seen.append(config)         # a 1406 "at most N left" fail condition needs it to have existed
    return sp


def _units_at(m, spot_id, codes):
    """The units on a spot that target codes cover (see UNIT_GUN; none listed: all of ours). Allied
    forces are the callers' (_friendly_ally_on)."""
    spot = _spot_of(m, spot_id)
    if spot is None:
        return []
    codes = set(codes) or OURS
    out = []
    if UNIT_GUN in codes and spot["team_id"] != "0":
        out.append(("team", spot["team_id"]))
    if UNIT_SANGVIS in codes and spot["sangvis_team_id"] != "0":
        out.append(("sangvis", spot["sangvis_team_id"]))
    if UNIT_VEHICLE in codes and int(spot["vehicle_with_user_id"] or 0):
        out.append(("vehicle", str(spot["vehicle_with_user_id"])))
    if UNIT_SQUAD in codes:
        out += [("squad", str(i)) for i in spot.get("squad_instance_ids") or []]
    if UNIT_FRIEND in codes:
        out += [(_friend_kind(f), fid) for fid, f in (m.get("friends") or {}).items()
                if str(f["spot"]) == str(spot["spot_id"])]
    if codes & ENEMY_TARGETS and int(spot["enemy_team_id"] or 0):
        out.append(("enemy", spot["enemy_instance_id"]))
    return out


def _friend_kind(f):
    return "friend_sangvis" if f.get("kind") == "sangvis" else "friend_team"


def _special_effects(state, m, sp, when):
    """A special spot appears (BIRTH) or goes (DEATH): skill_config_id_on_birth / _on_death
    "buff,hurt,special spot" (SpecialSpotCfg birthBuffId/birthHurtId/birthSpecialSpotId) act on the
    units on its spot. Returns the mission_hurt entries."""
    row = _special_spots().get(sp["config"], {})
    field = "skill_config_id_on_birth" if when == BIRTH else "skill_config_id_on_death"
    parts = [int(x) if x.strip().isdigit() else 0 for x in str(row.get(field) or "").split(",")]
    buff_id, hurt_id, next_spot = (parts + [0, 0, 0])[:3]
    codes = [c for c in _ids(row.get("effect_target_type")) if c > 0]
    if when == DEATH and [c for c in _ids(row.get("death_effect_target_type")) if c > 0]:
        codes = [c for c in _ids(row.get("death_effect_target_type")) if c > 0]
    if not codes:
        codes = [c for c in _ids(_mission_skills().get(sp["skill"], {}).get("spot_echelon")) if c > 0]
    units = _units_at(m, sp["spot"], codes)
    out = []
    if buff_id in _mission_buffs():
        for kind, uid in units:
            _give_buff(m, kind, uid, buff_id, sp, replace=False)
    hurt = _hurts().get(hurt_id)
    if hurt is not None:
        for unit in units:
            if unit[0] == "enemy":
                _hurt_enemy(m, unit[1], hurt, sp["skill"])
                continue
            entry = _hurt_unit(state, m, hurt, sp["skill"], sp["spot"], unit)
            if entry is not None:
                out.append(entry)
        out += _hurt_spot(state, m, hurt, sp["spot"], codes)
    out += _spawn_child(state, m, sp, next_spot)
    if when == BIRTH:
        out += _birth_triggers(state, m, sp, row)
    return out


# --- special spot triggers (SpecialSpotCfg$$InitData) -------------------------------------
#
# conditions_type "BH;Spot" and conditions_time "delay-every;..." (each a ","-list): when the
# special spot's own buff/hurt (mission_buff_config_id / mission_hurt_config_id, the "BH" part)
# and its follow-up special spot (special_spot_config_id, the "Spot" part) act. 1 every turn
# (counted from the turn it appeared, at startTurn), 2 each battle there, 3 each move onto it;
# a trigger acts once its count reaches delay, then every `every` (0: only then). Who sets it off:
# detect_target_type within detect_range (-1: effect_target_type within effect_range); who it
# acts on: effect_target_type, on the unit that set it off, or for an area one (effect_range_type 2)
# or one set off by others, on its effect nodes (_effect_spots, _area_units). effect_conditions "1"
# only draws the effect over the whole detection area (SpecialSpotCfg$$get_detectRangeEffect, read
# by LastEffect / DeathEffect alone). Unit codes: 1 echelon, 301-305 Coalition, 10 vehicle, 4/5/6
# enemies, 201 allied forces. Duration types 1 turns, 2 battles, 3 moves (either one ends it).
# Recorded: 11374's 9584204 (move, enemies) buffs each enemy that steps on it with 9583805,
# replacing an older copy, and those standing on it when it appears (its move_count stays 0);
# 9584208 (1 turn or 1 move) went when an enemy stepped on it; on the 11-04 map 9363400 (Spot
# turn 0-1) sets a new 9363401 (1 turn) on its spot at every startTurn (the first comes from
# its birth skill).
# Spot buffs (spot_buff_config): no_entry keeps enemies off, vision_buff lights night maps;
# no_airborne is the client's (parachute button); grow_enemy_pool makes its spot a spawn point
# (_spawn_point_rules).
_UNIT_CODES = {"team": {UNIT_GUN}, "sangvis": {UNIT_SANGVIS}, "vehicle": {UNIT_VEHICLE},
               "enemy": ENEMY_TARGETS, "squad": {UNIT_SQUAD}, "friend_team": {UNIT_FRIEND},
               "friend_sangvis": {UNIT_FRIEND}}      # allied forces: _ally_codes
_BIRTH_DEPTH = [0]


@lru_cache(maxsize=None)
def _ss_triggers(config):
    """({kind: (delay, every)} for its buff/hurt, the same for its follow-up special spot)."""
    row = _special_spots().get(config, {})
    types = str(row.get("conditions_type") or "").split(";")
    times = str(row.get("conditions_time") or "").split(";")
    out = []
    for part in range(2):
        kinds = (types[part] if part < len(types) else "").split(",")
        spans = (times[part] if part < len(times) else "").split(",")
        got = {}
        for i, k in enumerate(kinds):
            k = COND_BATTLE_END_AS.get(k.strip(), k.strip())
            if k in ("1", "2", "3") and int(k) not in got:
                delay, _, every = (spans[i] if i < len(spans) else "0-0").partition("-")
                got[int(k)] = (int(delay) if delay.strip().isdigit() else 0,
                               int(every) if every.strip().isdigit() else 0)
        out.append(got)
    return out[0], out[1]


def _due(count, delay, every):
    if count < delay:
        return False
    return (count - delay) % every == 0 if every > 0 else count == delay


def _due_for(sp, row, count, delay, every):
    """_due, and the special spot still has uses left: conditions_count (0: no limit) caps how
    often its triggers act (GUESS from the data, the client never reads it: 21 rows, the only one
    with a trigger is 9334950, a follow-up spot every move with count 1, so once). A use is
    counted when it acts (_used)."""
    cap = int(str(row.get("conditions_count") or "0").split(";")[0] or 0)
    return (not cap or int(sp.get("uses") or 0) < cap) and _due(count, delay, every)


def _used(sp):
    sp["uses"] = int(sp.get("uses") or 0) + 1


def _detect_codes(row):
    text = str(row.get("detect_target_type") or "").strip()
    if text in ("", "-1"):
        text = str(row.get("effect_target_type") or "")
    return {c for c in _ids(text) if c > 0}


def _effect_codes(row):
    return {c for c in _ids(row.get("effect_target_type")) if c > 0}


def _detects(m, sp, row, spot_id):
    """A unit on spot_id is within reach of the special spot's detection."""
    reach = int(row.get("detect_range") or 0) or int(row.get("effect_range") or 0)
    if int(sp["spot"]) == int(spot_id):
        return True
    return reach > 0 and _skill_distances(m["mission_id"], int(sp["spot"])).get(int(spot_id), reach + 1) <= reach


RANGE_AREA = 2       # special_spot_config.effect_range_type


def _effect_spots(m, sp, row):
    """The nodes a special spot's buff/hurt reaches: its own, and those within its reach whose
    side is in effect_spotbelong_type (spot belong 0-3, and 99 / 100, the extra node kinds some
    maps have, only where it names them). The reach is effect_range, or for effect_range_type 2
    the detection area (detect_range): INFERRED from the data, the client never reads either
    field. Type 1 rows (2778) nearly all detect on their own node only; every type 2 row (59)
    detects around it and gives an effect_range of 0 or the same number (599901: battles within 10,
    our echelons within 10; 760004: enemies moving within 5, our echelons within 5)."""
    reach = int(row.get("effect_range") or 0)
    if int(row.get("effect_range_type") or 0) == RANGE_AREA:
        reach = max(reach, int(row.get("detect_range") or 0))
    home = int(sp["spot"])
    spots = [home]
    if reach > 0:
        sides = {str(x) for x in _ids(row.get("effect_spotbelong_type") or "0,1,2,3")} or {"0", "1", "2", "3"}
        belong = {int(x["spot_id"]): str(x.get("belong")) for x in m["spots"]}
        spots += [sid for sid, d in sorted(_skill_distances(m["mission_id"], home).items())
                  if 0 < d <= reach and belong.get(sid, "0") in sides]
    return spots


def _units_in_effect(m, sp, row):
    """Units on the special spot's effect nodes (_effect_spots) that its effect_target_type covers."""
    codes = _effect_codes(row)
    out = []
    for sid in _effect_spots(m, sp, row):
        out += _units_at(m, sid, codes)
        ally = _friendly_ally_on(m, sid)
        if ally and _ally_codes(m["allies"][ally]) & codes:
            out.append(("ally", ally))
    return out


def _buff_room(m, kind, uid, buff_id):
    """Make way for a new map buff on a unit by its conflict_type, as for special spots
    (_add_special): the unit's buffs of the same conflict_type give way when their priority is not
    higher; False when a stronger one holds (Vortex of Secrets+ 11497: killicon_0 ... _4, buffs
    6630001-6630005, one conflict_type, priority 0-4, each battle's next one takes the last's place).
    conflict_type 0: no conflict."""
    row = _mission_buffs().get(buff_id, {})
    ct = int(row.get("conflict_type") or 0)
    if not ct:
        return True
    fx, mine = _effects(m), int(row.get("priority") or 0)
    rivals = {i: b for i, b in fx["buffs"].items() if b["kind"] == kind and b["unit"] == str(uid)
              and int(_mission_buffs().get(b["buff_id"], {}).get("conflict_type") or 0) == ct}
    if any(int(_mission_buffs().get(b["buff_id"], {}).get("priority") or 0) > mine for b in rivals.values()):
        return False
    for i in rivals:
        del fx["buffs"][i]
    return True


def _give_buff(m, kind, uid, buff_id, sp, replace=True):
    """A special spot's buff on a unit; replace: a copy it already has from this buff id goes
    (recorded: an enemy stepping onto 9584204 again gets a fresh 9583805, its counts reset)."""
    if buff_id not in _mission_buffs():
        return
    fx = _effects(m)
    if replace:
        fx["buffs"] = {i: b for i, b in fx["buffs"].items()
                       if not (b["kind"] == kind and b["unit"] == str(uid) and b["buff_id"] == buff_id)}
    if not _buff_room(m, kind, uid, buff_id):
        return
    fx["buffs"][_next_instance(m)] = {"kind": kind, "unit": str(uid), "buff_id": buff_id, "skill": sp["skill"],
                                     "source_type": sp["source_type"], "source_value": sp["source_value"],
                                     "start_turn": int(m["turn"])}


def _hurt_enemy(m, inst, hurt, skill):
    """A hurt on an enemy standing somewhere: its hp_percent drops by the hurt's value (bosses are
    spared, never below 1%, as for traps)."""
    spot = next((s for s in _enemy_spots(m) if s["enemy_instance_id"] == str(inst)), None)
    if spot is None or int(spot["enemy_team_id"] or 0) in _boss_teams(m["mission_id"]):
        return
    cut = max(0.0, min(100.0, _hurt_value(hurt, skill))) / 100
    spot["enemy_hp_percent"] = str(max(0.01, round(float(spot["enemy_hp_percent"] or 1) * (1 - cut), 4)))


def _fire_bh(state, m, sp, row, units):
    """The special spot's own buff and hurt act on these units; returns our mission_hurt entries.
    Hurts on an enemy that is moving are the caller's (_spring_traps)."""
    buff_id = int(row.get("mission_buff_config_id") or 0)
    hurt = _hurts().get(int(row.get("mission_hurt_config_id") or 0))
    out = []
    for kind, uid in units:
        _give_buff(m, kind, uid, buff_id, sp)
        if hurt is None or kind == "ally":
            continue
        if kind == "enemy":
            _hurt_enemy(m, uid, hurt, sp["skill"])
            continue
        entry = _hurt_unit(state, m, hurt, sp["skill"], int(sp["spot"]), (kind, uid))
        if entry is not None:
            out.append(entry)
    if hurt is not None and units:
        out += _hurt_spot(state, m, hurt, int(sp["spot"]), _effect_codes(row))
    return out


def _spawn_child(state, m, sp, config):
    """Another special spot appears on sp's spot (with its own birth effects)."""
    if config not in _special_spots() or config == sp["config"] or _BIRTH_DEPTH[0] >= SUB_DEPTH:
        return []
    child = _add_special(m, int(sp["spot"]), config, sp["skill"], sp["source_type"], sp["source_value"])
    if child is None:
        return []
    if config in BLAST_SPECIALS:
        _blast(state, m, int(sp["spot"]))
    _BIRTH_DEPTH[0] += 1
    try:
        return _special_effects(state, m, child, BIRTH)
    finally:
        _BIRTH_DEPTH[0] -= 1
        _drop_instant(m, child)


def _drop_instant(m, sp):
    """A special spot that lasts 0 turns only acts as it appears (its birth effects) and is never
    on the map (recorded 2026-11-12 on 11497: Springfield's EMP 6360011 adds 6560030 and 6360012 on
    its target; 6560030, 0 turns, stunned the enemy there (buff 1000001) and was in no reply, while
    6360012, 1 turn, stayed; the Goddess's 1000010, 0 turns, hurt her and never showed)."""
    if _durations(_special_spots().get(sp["config"], {})) == {DUR_TURNS: 0}:
        fx = m.get("effects") or {}
        for i, other in list((fx.get("specials") or {}).items()):
            if other is sp:
                del fx["specials"][i]


def _blast(state, m, spot_id):
    """BLAST_SPECIALS: the building on spot_id goes down (sent with the next map reply)."""
    b = (m.get("buildings") or {}).get(str(spot_id))
    if b is None or int(b["defender"]) <= 0 or str(spot_id) in m.get("buildings_down", []):
        return
    _hit_building(state, m, spot_id, int(b["defender"]))
    m.setdefault("building_changes", []).append({"building_spot_id": int(spot_id), "defender": 0})


def _birth_triggers(state, m, sp, row):
    """What a special spot's triggers do the moment it appears: a move trigger acts on the units
    already standing on it (not counted as moves). Turn triggers wait for startTurn (recorded:
    9363400's first 9363401 comes from its birth skill "0,0,9363401", not a second copy)."""
    bh, _ = _ss_triggers(sp["config"])
    out = []
    if COND_MOVE in bh and _due_for(sp, row, 0, *bh[COND_MOVE]):
        det = _detect_codes(row)
        eff = _effect_codes(row) or det
        here = [u for u in _units_at(m, sp["spot"], det) if _fits_echelon(m, u, det & eff)]
        if here:
            _used(sp)
        out += _fire_bh(state, m, sp, row, here)
    return out


def _end_special(state, m, inst):
    sp = _effects(m)["specials"].pop(inst, None)
    return _special_effects(state, m, sp, DEATH) if sp is not None else []


def _entered(state, m, spot_id, kind, uid, codes=None):
    """A unit (kind as in _UNIT_CODES) moves onto spot_id: every special spot that detects it counts
    the move, its move triggers act (its buff/hurt on the unit, when effect_target_type covers it;
    its follow-up special spot), and a move-limited one ends. Returns (our mission_hurt entries,
    the special spots whose buff/hurt acted on the unit)."""
    fx = m.get("effects")
    if not fx:
        return [], []
    codes, out, acted = codes or _UNIT_CODES.get(kind, set()), [], []
    for inst, sp in list(fx["specials"].items()):
        if inst not in fx["specials"]:
            continue
        row = _special_spots().get(sp["config"], {})
        if not codes & _detect_codes(row) or not _detects(m, sp, row, spot_id):
            continue
        count = int(sp.get("triggers") or 0)
        sp["triggers"] = count + 1
        bh, nxt = _ss_triggers(sp["config"])
        # an allied force only counts the move (no buff/hurt model for it)
        if COND_MOVE in bh and kind != "ally" and _due_for(sp, row, count, *bh[COND_MOVE]):
            mover = bool(codes & (_effect_codes(row) or codes))
            others = _area_units(m, sp, row, (kind, uid), mover)
            if mover or others:
                _used(sp)
            if mover:
                acted.append(sp)
                if kind == "enemy":
                    _give_buff(m, kind, uid, int(row.get("mission_buff_config_id") or 0), sp)
                else:
                    out += _fire_bh(state, m, sp, row, [(kind, uid)])
            if others:
                hurts = _fire_bh(state, m, sp, row, others)
                if kind == "enemy":     # the enemy turn's reply can't carry them
                    fx.setdefault("pending_hurts", []).extend(hurts)
                else:
                    out += hurts
        if COND_MOVE in nxt and _due_for(sp, row, count, *nxt[COND_MOVE]):
            _used(sp)
            out += _spawn_child(state, m, sp, int(row.get("special_spot_config_id") or 0))
        limit = _durations(row).get(DUR_MOVES)
        if limit and sp["triggers"] >= limit:
            out += _end_special(state, m, inst)
    return out, acted


def _area_units(m, sp, row, unit, hit_unit):
    """Besides the unit that set a move/battle trigger off: everything on the effect nodes the
    special spot acts on, for an area one (effect_range_type 2), or for one the unit itself isn't
    a target of (760004: enemies moving near it buff our echelons there). Allied forces are left
    out (no buff/hurt model for them)."""
    if hit_unit and int(row.get("effect_range_type") or 0) != RANGE_AREA:
        return []
    if not _effect_codes(row):
        return []
    return [u for u in _units_in_effect(m, sp, row) if tuple(u) != tuple(unit) and u[0] != "ally"]


def _turn_triggers(state, m):
    """startTurn, after expiry: each special spot's turn triggers (counted in turns since it appeared)."""
    fx = m.get("effects")
    if not fx:
        return []
    turn, out = int(m["turn"]), []
    for inst, sp in list(fx["specials"].items()):
        if inst not in fx["specials"]:
            continue
        elapsed = turn - int(sp["start_turn"])
        if elapsed <= 0:
            continue
        row = _special_spots().get(sp["config"], {})
        bh, nxt = _ss_triggers(sp["config"])
        if COND_TURN in bh and _due_for(sp, row, elapsed, *bh[COND_TURN]):
            _used(sp)
            out += _fire_bh(state, m, sp, row, _units_in_effect(m, sp, row))
        if (COND_TURN in nxt and _due_for(sp, row, elapsed, *nxt[COND_TURN])
                and (not _effect_codes(row) or _units_in_effect(m, sp, row))):
            _used(sp)
            # one with effect targets only marks while one is in its range (1001-EX's lab 483701,
            # enemies within 2: its 481811, "lab not cleared" for 1406 481811:0, never appeared
            # live with the lab empty)
            out += _spawn_child(state, m, sp, int(row.get("special_spot_config_id") or 0))
    return out


def _battle_triggers(state, m, spot_id, unit):
    """One of our units fought on spot_id: special spots there that detect it count the battle,
    their battle triggers act, and battle-limited ones end. The battle reply can't carry hurts, so
    they wait for the next reply that runs the skill loaders."""
    fx = m.get("effects")
    if not fx or unit is None or spot_id is None:
        return
    codes, out = _UNIT_CODES.get(unit[0], set()), []
    for inst, sp in list(fx["specials"].items()):
        if inst not in fx["specials"]:
            continue
        row = _special_spots().get(sp["config"], {})
        if not codes & _detect_codes(row) or not _detects(m, sp, row, spot_id):
            continue
        count = int(sp.get("battles") or 0)
        sp["battles"] = count + 1
        bh, nxt = _ss_triggers(sp["config"])
        if COND_BATTLE in bh and _due_for(sp, row, count, *bh[COND_BATTLE]):
            fighter = bool(codes & (_effect_codes(row) or codes))
            others = _area_units(m, sp, row, tuple(unit), fighter)
            if fighter or others:
                _used(sp)
            out += _fire_bh(state, m, sp, row, ([unit] if fighter else []) + others)
        if COND_BATTLE in nxt and _due_for(sp, row, count, *nxt[COND_BATTLE]):
            _used(sp)
            out += _spawn_child(state, m, sp, int(row.get("special_spot_config_id") or 0))
        limit = _durations(row).get(DUR_BATTLES)
        if limit and sp["battles"] >= limit:
            out += _end_special(state, m, inst)
    if out:
        fx.setdefault("pending_hurts", []).extend(out)


@lru_cache(maxsize=1)
def _spot_buffs():
    return {int(r["id"]): r for r in stc.table("spot_buff_config")}


def _spot_buff(sp):
    return _spot_buffs().get(int(_special_spots().get(sp["config"], {}).get("spot_buff_config_id") or 0), {})


def _no_entry_spots(m):
    """Spots enemies can't move onto: a special spot whose spot_buff_config has no_entry 1, or 2
    while a building there still has defenders (SpecialSpotAction$$get_canEnter)."""
    out = set()
    for sp in (m.get("effects") or {}).get("specials", {}).values():
        rule = int(_spot_buff(sp).get("no_entry") or 0)
        b = (m.get("buildings") or {}).get(str(sp["spot"]))
        if rule == 1 or (rule == 2 and b is not None and int(b.get("defender") or 0) > 0):
            out.add(int(sp["spot"]))
    return out


def _vision_sources(m):
    """(spot, range) of special spots that light up a night map (spot_buff_config vision_buff;
    "*n" takes the n-th value of the placing skill's data_pool, SpecialSpotAction$$get_nightView)."""
    out = []
    for sp in (m.get("effects") or {}).get("specials", {}).values():
        raw = str(_spot_buff(sp).get("vision_buff") or "").strip()
        if raw.startswith("*"):
            pool = str(_mission_skills().get(sp["skill"], {}).get("data_pool") or "").split(",")
            i = int(raw[1:]) if raw[1:].isdigit() else -1
            raw = pool[i] if 0 <= i < len(pool) else "0"
        n = int(_number(raw))
        if n > 0:
            out.append((int(sp["spot"]), n))
    return out


def _buff_vision(m):
    """(spot, range) of units whose mission buff has vision_buff n (the Coalition chip NightView's
    50003, 1): the unit sees n around it on a night map."""
    where = {"team": m.get("team_pos") or {}, "sangvis": m.get("sangvis_pos") or {}, "vehicle": m.get("vehicle_pos") or {}}
    out = []
    for b in (m.get("effects") or {}).get("buffs", {}).values():
        n = int(_number(str(_mission_buffs().get(b["buff_id"], {}).get("vision_buff") or "0")))
        spot = where.get(b["kind"], {}).get(str(b["unit"]))
        if n > 0 and spot is not None:
            out.append((int(spot), n))
    return out


def _team_units(state, kind, uid):
    if kind == "team":
        return "gun", [g for g in state.get("gun_with_user_info", []) if str(g.get("team_id")) == str(uid)]
    if kind == "sangvis":
        from . import formation
        ids = {str(v.get("sangvis_with_user_id")) for v in formation._sangvis_team(state, uid)["info"].values()}
        return "sangvis", [u for u in state.get("sangvis_with_user_info", []) if str(u["id"]) in ids - {"0"}]
    return None, []


def _hurt_entry(hurt, spot_id):
    return {"spot_id": int(spot_id), "hostage_id": 0, "team_id": 0, "enemy_instance_id": 0,
            "ally_instance_id": 0, "building_spot_id": 0, "squad_instance_id": 0, "sangvis_team_id": 0,
            "vehicle_with_user_id": 0, "hurt_id": int(hurt["id"]), "guns_life": [], "sangvises_life": [],
            "hostage_hp": 0, "vehicle_life": 0, "squad_life": 0, "building_defender": 0,
            "ally_enemy_hp_percent": 0, "ally_guns_life": [], "ally_vehicle_life": 0, "enemy_hp_percent": 0}


UNIT_HOSTAGE = 201


def _hurt_spot(state, m, hurt, spot_id, codes=None):
    """The rest of a hurt on a spot (mission_hurt_config, absolute results as for units):
    hostage_value HP bars off the hostage there, waiting or carried by the echelon there (when the
    hurt's targets include hostages, 201, or name none); at 0 it is lost as when its carrier falls.
    defender_value off the building there's durability (99999 and the like: destroyed), like an
    attack (_hit_building). Returns its mission_hurt entries."""
    spot = _spot_of(m, spot_id)
    if spot is None:
        return []
    out = []
    bars = int(hurt.get("hostage_value") or 0)
    if bars > 0 and (not codes or UNIT_HOSTAGE in codes):
        team = spot["team_id"] if spot["team_id"] != "0" else None
        held = (m.get("carrying") or {}).get(str(team)) if team else None
        where = held if held is not None else spot if spot.get("hostage_id", "0") != "0" else None
        if where is not None:
            hp = max(0, int(where.get("hostage_hp") or 0) - bars)
            entry = _hurt_entry(hurt, spot_id)
            entry.update(hostage_id=int(where["hostage_id"]), hostage_hp=hp)
            out.append(entry)
            if hp:
                where["hostage_hp"] = str(hp)
            else:
                if held is not None:
                    m["carrying"].pop(str(team), None)
                else:
                    spot.update(hostage_id="0", hostage_hp="0", hostage_max_hp="0")
                m["hostages_lost"] = int(m.get("hostages_lost") or 0) + 1
    dmg = int(_number(hurt.get("defender_value") or 0))
    if dmg > 0 and str(spot_id) in (m.get("buildings") or {}):
        left = _hit_building(state, m, spot_id, dmg)
        entry = _hurt_entry(hurt, spot_id)
        entry.update(building_spot_id=int(spot_id), building_defender=int(left))
        out.append(entry)
    return out


def _hurt_unit(state, m, hurt, skill, spot_id, unit):
    """Apply a mission_hurt_config to one unit; returns its mission_hurt entry (absolute results,
    HurtAction$$LoadHurtData) or None. Negative values heal. value is a percent of the unit's
    current (life_type 1) or full (2) HP, or of one dummy link's HP (is_number 1); target_type 1
    picks only the doll with the lowest HP share."""
    kind, uid = unit
    if kind not in ("team", "sangvis", "vehicle", "enemy", "squad"):
        return None      # friend echelons take no map hurts (player report)
    v = _hurt_value(hurt, skill) / 100
    entry = _hurt_entry(hurt, spot_id)
    if kind == "enemy":
        spot = _spot_of(m, spot_id)
        if v <= 0 or spot is None or int(spot["enemy_team_id"] or 0) in _boss_teams(m["mission_id"]):
            return None
        hp = _number(spot["enemy_hp_percent"] or 1)
        hp = hp * (1 - v) if int(hurt["life_type"]) == 1 else hp - v
        spot["enemy_hp_percent"] = str(max(0.01, round(hp, 4)))
        entry.update(enemy_instance_id=int(uid), enemy_hp_percent=float(spot["enemy_hp_percent"]))
        return entry
    if kind == "squad":
        # a HOC hit by gas, a closing gate and the like (player report): keeps at least 1 HP like
        # our echelons (squad_instance_id / squad_life, HurtAction$$LoadHurtData)
        rec = _hoc_record(state, m, uid)
        if rec is None or int(rec.get("life") or 0) <= 0:
            return None
        full, life = workshop.max_life(state, "squad", rec), int(rec["life"])
        base = life if int(hurt["life_type"]) == 1 and not int(hurt["is_number"]) else full
        workshop.set_life(state, "squad", rec, max(1, round(life - base * v)))
        entry.update(squad_instance_id=int(uid), squad_life=int(rec["life"]))
        return entry
    if kind == "vehicle":
        veh = workshop._find(state.get("vehicle_with_user_info"), uid)
        if veh is None or int(veh.get("life") or 0) <= 0:
            return None
        key = f"vehicle:{veh['id']}"
        seen = state.setdefault("_max_life", {})
        full = seen[key] = max(int(seen.get(key) or 0), int(veh["life"]))
        life = int(veh["life"])
        base = life if int(hurt["life_type"]) == 1 and not int(hurt["is_number"]) else full
        veh["life"] = str(max(1, min(full, round(life - base * v))))
        entry.update(vehicle_with_user_id=int(uid), vehicle_life=int(veh["life"]))
        return entry
    life_kind, members = _team_units(state, kind, uid)
    members = [u for u in members if int(u.get("life") or 0) > 0]
    if not members:
        return None
    if int(hurt["target_type"]) == HURT_LOWEST:
        members = [min(members, key=lambda u: int(u["life"]) / max(1, workshop.max_life(state, life_kind, u)))]
    lives = []
    for u in members:
        full, life = workshop.max_life(state, life_kind, u), int(u["life"])
        if int(hurt["is_number"]):
            base = full / max(1, int(u.get("number") or 1))
        else:
            base = life if int(hurt["life_type"]) == 1 else full
        workshop.set_life(state, life_kind, u, max(1, round(life - base * v)))
        lives.append({f"{life_kind}_with_user_id": int(u["id"]), "life": int(u["life"])})
    if kind == "team":
        entry.update(team_id=int(uid), guns_life=lives)
    else:
        entry.update(sangvis_team_id=int(uid), sangvises_life=lives)
    return entry


def _effect_sets(m):
    """The special spots and buffs as the client keeps them: (fairy_skill_on_spot, {kind: on_unit})."""
    fx = _effects(m)
    on_spot = {}
    for inst, sp in fx["specials"].items():
        on_spot.setdefault(str(sp["spot"]), {})[inst] = {
            "source_type": sp["source_type"], "source_value": sp["source_value"],
            "special_spot_config_id": sp["config"], "building_id": 0, "squad_teaminstance_id": 0,
            "start_turn": sp["start_turn"], "battle_count": sp.get("battles", 0), "move_count": sp["triggers"],
            "mission_skill_config_id": sp["skill"]}
    on_unit = {kind: {} for kind in _EFFECT_KEYS}
    alive = {s["enemy_instance_id"] for s in _enemy_spots(m)}
    squads = {str(i) for s in m["spots"] for i in s.get("squad_instance_ids") or []}
    friends = set(m.get("friends") or {})
    for inst, b in fx["buffs"].items():
        if (b["kind"] == "enemy" and b["unit"] not in alive or b["kind"] == "squad" and b["unit"] not in squads
                or b["kind"].startswith("friend_") and b["unit"] not in friends):
            continue
        on_unit[b["kind"]].setdefault(b["unit"], {})[inst] = {
            "source_type": b["source_type"], "source_value": b["source_value"], "buff_id": b["buff_id"],
            "start_turn": b["start_turn"], "battle_count": b.get("battles", 0),
            "battle_finish_count": b.get("battles", 0), "person_move_count": b.get("moves", 0),
            "person_shift_count": b.get("shifts", 0), "mission_skill_config_id": b["skill"],
            "sangvis_chip_info": []}
        if b["kind"] in ("ally", "enemy", "team"):     # recorded on 11341 / 11374 / 129 (team_id)
            key = {"ally": "ally", "enemy": "enemy_instance_id", "team": "team_id"}[b["kind"]]
            on_unit[b["kind"]][b["unit"]][inst][key] = int(b["unit"])
    return on_spot, on_unit


# A buff counts what its unit does while it lasts (recorded: a Coalition echelon's buff after 3
# moves, a swap and a battle reads person_move_count 3, person_shift_count 4, battle_count 1,
# battle_finish_count 1; the doll echelon it swapped with, shift 1). A swap is a shift but not a move.
_UNIT_KIND = {"gun": "team", "team": "team", "sangvis": "sangvis", "vehicle": "vehicle", "squad": "squad",
              "enemy": "enemy", "ally": "ally"}

# mission_buff_config duration_type (the client's MissionSkillDurationType): 1 Turn, 2 Battle,
# 3 Walk, 4 BattleFinish, 5 PersonMove, 51 PersonShift. Turns run out at startTurn
# (_expire_effects); the counted ones end once the count reaches the limit (_spent_buffs).
# Recorded on 126: ExtraAp (50001, 1 turn or 1 move) reads person_move_count 1 in the reply to
# the Coalition echelon's move and is gone from the next one; an enemy's shield (910630, 2 turns
# or 1 move) is gone in the startEnemyTurn reply that moves it.
_BUFF_COUNTS = {2: "battles", 4: "battles", 5: "moves", 51: "shifts"}
BUFF_PERSON_MOVE = 5


def _spent_buffs(m):
    """Drop buffs whose battle / move limit is used up."""
    fx = m.get("effects")
    if not fx or not fx.get("buffs"):
        return

    def spent(b):
        limits = _durations(_mission_buffs().get(b["buff_id"], {}))
        return any(n > 0 and b.get(_BUFF_COUNTS[t], 0) >= n for t, n in limits.items() if t in _BUFF_COUNTS)
    fx["buffs"] = {i: b for i, b in fx["buffs"].items() if not spent(b)}


# Map items (Grenade 528, Flashbang 530, ...): a skill's drop_item "item:n,..." gives (or, negative,
# takes away, never below 0) and its consumption_item spends. Every map reply carries the totals as
# trigger_para {"drop_item": {item: got}, "cost_item": {item: spent} or []} (MissionAction getItems /
# useItems), and a cast's net change goes out as fairy_skill_return.drop_item. Recorded on 11374:
# 95838013 (+60) and 580116 (+5) give drop_item {"530": 65} at startMission, 580116 +5 at each
# startTurn (70, 75, ...), two 580111 (-5) at buildingSkillPerformOnDeath show drop_item -10 with
# the total unchanged. APPROXIMATION: the startMission net (recorded 0 there, -50 on 11341, where a
# -9999 / -99999 reset is cast too) depends on an order the live server kept to itself.
def _item_pairs(text):
    out = []
    for part in str(text or "").split(","):
        iid, _, n = part.partition(":")
        if iid.strip().isdigit() and n.strip().lstrip("-").isdigit():
            out.append((iid.strip(), int(n)))
    return out


def _map_items(m, cfg):
    """Apply a cast's drop_item / consumption_item; returns {item: net change} (empty: none)."""
    drops, costs = _item_pairs(cfg.get("drop_item")), _item_pairs(cfg.get("consumption_item"))
    if not drops and not costs:
        return {}
    led = m.setdefault("items", {"got": {}, "cost": {}, "have": {}})
    net = {}
    for iid, n in costs:
        led["cost"][iid] = led["cost"].get(iid, 0) + max(0, n)
        led["have"][iid] = max(0, led["have"].get(iid, 0) - max(0, n))
    for iid, n in drops:
        before = led["have"].get(iid, 0)
        led["have"][iid] = max(0, before + n)
        if n > 0:
            led["got"][iid] = led["got"].get(iid, 0) + n
        net[iid] = net.get(iid, 0) + led["have"][iid] - before
    return net


def _trigger_para(m):
    led = m.get("items")
    if not led:
        return None
    cost = {k: str(v) for k, v in led["cost"].items() if v}
    return {"drop_item": {k: str(v) for k, v in led["got"].items()}, "cost_item": cost or []}


def _move_cost(m, kind, uid):
    """AP for one move: 1, plus the unit's buffs' ext_ap_cost; 0 with a free move (_free_move)."""
    if _free_move(m, kind, uid):
        return 0
    extra = sum(int(_mission_buffs().get(b["buff_id"], {}).get("ext_ap_cost") or 0)
                for b in (m.get("effects") or {}).get("buffs", {}).values()
                if b["kind"] == _UNIT_KIND.get(kind) and b["unit"] == str(uid))
    return 1 + extra


def _free_move(m, kind, uid):
    """A buff with free_ap_move lets its unit move without AP while it lasts (MissionBuffCfg.freeMove;
    recorded on 126: a Coalition echelon with ExtraAp moved at no cost): as many moves as its
    PersonMove duration (recorded on 11946: Accelerate 770027, 3 moves, three free), else
    free_ap_move of them."""
    for b in (m.get("effects") or {}).get("buffs", {}).values():
        if b["kind"] == _UNIT_KIND.get(kind) and b["unit"] == str(uid):
            row = _mission_buffs().get(b["buff_id"], {})
            if not int(row.get("free_ap_move") or 0):
                continue
            n = _durations(row).get(BUFF_PERSON_MOVE) or int(row["free_ap_move"])
            if b.get("moves", 0) < n:
                return True
    return False


def _count_move(m, kind, uid, moved=True, at=None):
    """Count a move (or a shift) on the unit's buffs; at: the spot it moved to (the after-move
    special spots go there: recorded 2026-11-12 on 11497, the move counter's 6630012 appeared on the
    node echelon 1 stepped onto, 600109, not the one it left)."""
    for b in (m.get("effects") or {}).get("buffs", {}).values():
        if b["kind"] == _UNIT_KIND.get(kind) and b["unit"] == str(uid):
            b["shifts"] = b.get("shifts", 0) + 1
            if moved:
                b["moves"] = b.get("moves", 0) + 1
    if moved:
        _after_move_spots(m, _UNIT_KIND.get(kind), uid, at)


COND_AFTER_MOVE = 5           # mission_buff_config.conditions_type: acts after each move


def _after_move_spots(m, kind, uid, at=None):
    """A unit moved: its buffs that act after moves (conditions_type 5) with a special_spot_config_id
    place it where the unit is, and its birth buff acts (Vortex of Secrets+ 11497: 6630011 ->
    special spot 6630011 -> buff 6630012 ... 6630018 -> 6630019 "Vpm5", ext_ap_cost 1: "the first 8
    moves a turn cost AP as usual, after 8 moves they cost double", the DR+ notes; the building's
    6630004 takes 6630011-6630017 off and gives 6630011 again at startTurn). Only buffs (the chain's
    spots carry no hurt)."""
    spot = at if at is not None else _caster_spot(m, (kind, str(uid)))
    if spot is None or not m.get("effects"):
        return
    for b in [b for b in m["effects"]["buffs"].values() if (b["kind"], b["unit"]) == (kind, str(uid))]:
        row = _mission_buffs().get(b["buff_id"], {})
        ss = int(row.get("special_spot_config_id") or 0)
        if ss not in _special_spots() or int(str(row.get("conditions_type") or 0).split(",")[0] or 0) != COND_AFTER_MOVE:
            continue
        sp = _add_special(m, int(spot), ss, b["skill"], b["source_type"], b["source_value"])
        if sp is None:
            continue
        parts = [int(x) if x.strip().isdigit() else 0 for x in str(_special_spots()[ss].get("skill_config_id_on_birth") or "").split(",")]
        if parts and parts[0] in _mission_buffs():
            _give_buff(m, kind, uid, parts[0], sp, replace=False)


# target_moved_step {"<turn>": {"<code>": {"<id>": 1}}}: who moved on each turn, sent whole with the
# map replies (MissionAction$$LoadMoveStepData into hasMoveStepData, which mission buffs that care
# whether a unit moved read through CheckTeamHasMoveStep). Recorded codes: 2 friends (doll and
# Coalition, by friend_team_id), 3 allied forces (instance), 4 enemies (instance); our own echelons'
# moves aren't listed.
MOVED_FRIEND, MOVED_ALLY, MOVED_ENEMY = 2, 3, 4


def _note_moved(m, code, uid, count=1):
    m.setdefault("moved_step", {}).setdefault(str(m["turn"]), {}).setdefault(str(code), {})[str(uid)] = count


def _count_battle(m, kind, uid):
    for b in (m.get("effects") or {}).get("buffs", {}).values():
        if b["kind"] == _UNIT_KIND.get(kind) and b["unit"] == str(uid):
            b["battles"] = b.get("battles", 0) + 1


def _effect_keys(m, reply, force=False):
    """Add the full special spot and buff sets to a reply, when there are any (or once more,
    empty, to clear the client's copy after the last one went). Objects: every in-game caller of
    MissionAction$$LoadSkillData reads them with readObject false (a string there throws inside the
    loader's try/catch and the effects never show); an empty {} clears the client's copy, [] would not."""
    fx = m.get("effects")
    if m.get("moved_step"):
        reply["target_moved_step"] = m["moved_step"]
    if m.get("win_steps") is not None:
        reply["mission_win_step_control_ids"] = _steps_now(m)
    para = _trigger_para(m)
    if para:
        reply["trigger_para"] = para        # recorded: in every map reply once the map has items
    changes = m.pop("building_changes", None)
    if changes:
        reply["building_defender_change"] = list(reply.get("building_defender_change") or []) + changes
    if m.get("cooldowns"):
        # the whole list each time (recorded: every map reply after a cast repeats all of them)
        reply["fairy_skill_perform"] = list(m["cooldowns"].values())
    if not fx or not (force or fx["specials"] or fx["buffs"] or fx["sent"] or fx.get("pending_hurts")):
        return reply
    on_spot, on_unit = _effect_sets(m)
    pending = fx.pop("pending_hurts", None)
    if pending:
        ret = reply.setdefault("fairy_skill_return", {})
        ret["mission_hurt"] = list(ret.get("mission_hurt") or []) + pending
    keep = {k for k in ("fairy_skill_on_spot", *_EFFECT_KEYS.values()) if reply.get(k) == {}}   # a follow-up's clearing {}
    reply["fairy_skill_on_spot"] = on_spot or []
    for kind, key in _EFFECT_KEYS.items():
        # an empty one as [], never {} (recorded: live sends "fairy_skill_on_friend_team": []). The
        # client skips a section only when it is an empty array (Data$$IsJsonArrayNull: JsonType 2,
        # count 0); any other runs its loader, and LoadFairySkillOnFriend clears every buff in the
        # map's buff table that its own (empty) list lacks, so {} there wiped the echelon's buff the
        # same reply gave it (player report: the Goliath's Portable Explosives never showed)
        reply[key] = on_unit[kind] or []
    # ... but [] never clears anything, so once the last buff on a unit is gone, one {} (here the
    # team section's) has the client drop every buff it still holds (player report: Portable Explosives
    # stayed after the throw). Likewise the special spots.
    if not any(on_unit.values()) and fx.get("units_sent"):
        reply["fairy_skill_on_team"] = {}
    if not on_spot and fx.get("spots_sent"):
        reply["fairy_skill_on_spot"] = {}
    for k in keep:
        if reply.get(k) == []:
            reply[k] = {}
    fx["units_sent"], fx["spots_sent"] = any(on_unit.values()), bool(on_spot)
    fx["sent"] = bool(fx["specials"] or fx["buffs"])
    return reply


def _expire_effects(state, m):
    """At the start of our turn: drop special spots and buffs whose turns have run out (special
    spots set off their death effects). Returns the mission_hurt entries."""
    fx = m.get("effects")
    if not fx:
        return []
    turn = int(m["turn"])

    def alive(start, row):
        lasts = _durations(row).get(DUR_TURNS)
        return lasts is None or turn < int(start) + max(1, lasts)
    gone = [i for i, sp in fx["specials"].items() if not alive(sp["start_turn"], _special_spots().get(sp["config"], {}))]
    hurts = []
    for i in gone:
        hurts += _special_effects(state, m, fx["specials"].pop(i), DEATH)
    fx["buffs"] = {i: b for i, b in fx["buffs"].items()
                   if alive(b["start_turn"], _mission_buffs().get(b["buff_id"], {}))}
    return hurts


def _hurt_value(row, skill):
    raw = str(row.get("value") or "0")
    if raw.startswith("*"):
        pool = str(_mission_skills().get(skill, {}).get("data_pool") or "0").split(",")
        i = int(raw[1:] or 0)
        return _number(pool[i] if i < len(pool) else 0)
    return _number(raw)


def _enter_hazards(state, m, spot_id, unit):
    """One of our units (as _unit_on gives) moves onto spot_id (see _entered). Returns the
    mission_hurt entries."""
    if unit is None:
        return []
    return _entered(state, m, spot_id, unit[0], unit[1])[0]


def _hazard_reply(state, m, spot_id, unit, reply):
    hurts = _enter_hazards(state, m, spot_id, unit)
    if hurts:
        reply["fairy_skill_return"] = {"mission_hurt": hurts}
    return _effect_keys(m, reply)


def _after_battle_spots(state, m, unit):
    """A battle won: the unit's buffs that act after battles (conditions_type 4) and carry a
    special_spot_config_id place it on the unit's spot, and its birth acts (Vortex of Secrets+
    11497: killicon_n's special spot 663000n+1 gives killicon_n+1, and building 6630002's on-death
    6630009 then casts the 6630010-14 that finds it, 200 ... 1000 by event_score field 18; the
    turn's reset is the building's own 6630004 -> 6630027 at startTurn).
    APPROXIMATION: only won battles (the kill is what the spot is for); a lost one places nothing."""
    spot = _caster_spot(m, unit)
    if spot is None:
        return
    for b in [b for b in m["effects"]["buffs"].values() if (b["kind"], b["unit"]) == (unit[0], str(unit[1]))]:
        row = _mission_buffs().get(b["buff_id"], {})
        ss = int(row.get("special_spot_config_id") or 0)
        if ss not in _special_spots() or int(str(row.get("conditions_type") or 0).split(",")[0] or 0) != COND_AFTER_BATTLE:
            continue
        sp = _add_special(m, int(spot), ss, b["skill"], b["source_type"], b["source_value"])
        if sp is not None:
            m["effects"].setdefault("pending_hurts", []).extend(_special_effects(state, m, sp, BIRTH))


def _after_battle(state, m, unit, won=True):
    """One of our units finished a battle: its buffs that act after battles (conditions_type 4)
    and share their id with a mission_hurt_config apply it (Heart-Healing Hymn: heal, for the
    first HYMN_BATTLES battles of the turn). The battle reply doesn't run the skill loaders, so
    the result waits for the next reply that does (fairy_skill_return.mission_hurt)."""
    fx = m.get("effects")
    if not fx or unit is None:
        return
    if won:
        _after_battle_spots(state, m, unit)
    for b in list(fx["buffs"].values()):
        row, hurt = _mission_buffs().get(b["buff_id"], {}), _hurts().get(b["buff_id"])
        if (b["kind"], b["unit"]) != (unit[0], str(unit[1])) or hurt is None:
            continue
        if int(str(row.get("conditions_type") or 0).split(",")[0] or 0) != COND_AFTER_BATTLE:
            continue
        b["battles"] = int(b.get("battles") or 0) + 1
        skill = _mission_skills().get(b["skill"], {})
        if int(skill.get("skill_group_id") or 0) == HYMN_GROUP:
            if b["battles"] > HYMN_BATTLES:
                continue
            # APPROXIMATION: every level carries buff 2401; the 10/15/20/25/30% heals (hurt
            # 2401-2405) are taken two skill levels per step
            hurt = _hurts().get(HYMN_HURT + min(4, (int(skill.get("level") or 1) - 1) // 2), hurt)
        entry = _hurt_unit(state, m, hurt, b["skill"], int(_caster_spot(m, unit) or 0), unit)
        if entry is not None:
            fx.setdefault("pending_hurts", []).append(entry)


def _spring_traps(state, m, spot_id, inst, team_id, hp):
    """An enemy steps on spot_id (see _entered): the hurts of the special spots that act on it cut
    its hp_percent (bosses are spared), and a buff with cannot_move holds it. Returns
    (new hp_percent, held)."""
    boss = int(team_id or 0) in _boss_teams(m["mission_id"])
    held = False
    _, acted = _entered(state, m, spot_id, "enemy", str(inst))
    for sp in acted:
        row = _special_spots().get(sp["config"], {})
        hurt = _hurts().get(int(row.get("mission_hurt_config_id") or 0))
        if hurt is not None and not boss:
            cut = max(0.0, min(100.0, _hurt_value(hurt, sp["skill"]))) / 100
            hp = max(0.01, round(hp * (1 - cut), 4))
        buff = _mission_buffs().get(int(row.get("mission_buff_config_id") or 0), {})
        held |= str(buff.get("cannot_move") or "") == "1"
    return hp, held


# --- allied and third-party forces ------------------------------------------------------
#
# Spots with an ally_team_id carry an AI force (stc ally_team; initial_type is its side, the
# client's TeamBelong: 0 third party, 1 friendly, 2 enemy). Each gets an instance id; spots list it
# in ally_instance_ids and startMission sends ally_instance_info, an object {"<instance>":
# {"ally_team_id", "ally_instance_id", "battleskill_switch" (bool), "target_type", "ally_type",
# "duration_end_turn", "ai" ("<code>" or "<code>:<ammo>,<mre>"), "ai_para" (str), "ally_enemy"}}
# (AllyTeam$$.ctor / SetHp / CheckAI; ally_guns/team_resource are optional, the guns
# then come from the client's own ally_team row). target_type 302/303 switch the client to a
# Coalition-style force; 0 lets it decide from the row. The client catches bad entries ("Ally数据有误").
# duration_end_turn: the client removes the force once the turn equals it (0 = never).
#
# Their turns: Mission/allyMySideMove (friendly AI, RequestFriendAllyTeamTurn) -> {"ally_move": [...],
# "all_ally_team_moved", "type5_score"}; Mission/friendTeamMove (friends' support echelons) ->
# {"all_friend_team_moved", "type5_score"}; third parties: Mission/startOtherSideTurn ->
# othersideTurnMove -> endOtherSideTurn, parsed like startEnemyTurn (enemy_move/ally_move/
# change_belong all optional; endOtherSideTurn reads type5_score).
# Mission/reinforceAllyTeam {ally_team_id, spot_id, myside_data} deploys an allied force ->
# {"ally_instance_id", "ally_instance_info", "ap"} (DeploymentTeamInfoController$$RqquestAllyReinforceHandle).
# Mission/allyTeamAi {ally_instance_id, ai_type} / friendTeamAi {friend_team_id, ai_type} change a
# force's orders (plain "1").
# Moving onto a third-party or enemy-side force is a battle; winning it removes the force, reported
# as died_this_section {"enemy": [], "ally": ["<ally_team_id>"]} (MissionAction$$LoadDieEnemy).
# Movement: each force takes one step a turn by its AI (ally_team.ai, first of "<ai>;...;<ai>", and
# ai_content's first part; the codes are stc team_ai's, force 3/4): 101 Patrol (the ai_content route,
# back and forth), 102 Alert (toward the nearest hostile unit within 2 nodes), 103 Expand (toward
# the nearest node its side doesn't hold), 1 Eliminate (toward the nearest hostile unit), 2 Capture
# (toward the other side's Command Post); others hold. Friendly forces move in allyMySideMove,
# enemy-side forces in startEnemyTurn, third parties in startOtherSideTurn, each reported as ally_move
# [{squad_instance_id, ally_instance_id, from_spot_id, to_spot_id, hp_percent, hostage_hp,
# hostage_id}] (DeploymentController$$AnalysicsEnemyAllyMove). Hostile: friendly forces hunt enemies
# and enemy-side/third-party forces; enemy-side forces hunt our units and friendly forces; third
# parties hunt everyone.
# SIMPLIFIED: forces never step onto an occupied node (no force-on-force or force-on-echelon
# battles: the format of those results is unknown); betrayal/transform rules: ally_changes. Forces
# the player deployed (mission_ally_spots, target_type 301) move only by teamMove person_type 3.
# (No map has timed ally reinforcements: reinforce_ally_turn/spot are 0 everywhere, and
# reinforce_ally_team lists the forces the player can call in, Mission/reinforceAllyTeam.)

ALLY_FRIENDLY = 1
TARGET_FROM_ROW = 0
TARGET_MYSIDE = 301     # recorded on every force the player deployed and moves (mission_ally_spots)
ALLY_SIDE_CODES = {1: 3, 2: 5, 0: 6}


@lru_cache(maxsize=1)
def _ally_teams():
    return {int(r["id"]): r for r in stc.table("ally_team")}


def _first(text):
    return str(text or "0").split(";")[0] or "0"


def _new_ally(m, team_id, spot, belong=None):
    row = _ally_teams().get(int(team_id or 0))
    if row is None or spot is None:
        return None
    m["next_ally"] = int(m.get("next_ally") or 0) + 1
    iid = str(m["next_ally"])
    duration = int(row.get("duration") or 0)
    m.setdefault("allies", {})[iid] = {
        "ally_team_id": int(row["id"]), "spot": spot["spot_id"], "mission": m["mission_id"],
        "belong": int(row["initial_type"]) if belong is None else int(belong),
        "end_turn": int(m["turn"]) + duration if duration > 0 else 0}
    spot["ally_instance_ids"] = list(spot.get("ally_instance_ids") or []) + [int(iid)]
    return iid


def _place_allies(m, deployed=None):
    """The spot table's allied forces and those recorded runs saw at the start that the table
    doesn't have (data/live_spawns.json "allies": 11355's enemy-side force 6580116 at 68320), in
    spot order; the ones startMission's mission_ally_spots [{spot_id, ally_team_id,
    mission_myside_data}] names are the player's to move. Spot order gives the instance numbers
    the live server gave in every recorded run (11341, 11353, 11355, 11368, 11374)."""
    mine = {(int(d.get("spot_id") or 0), int(d.get("ally_team_id") or 0)) for d in deployed or [] if isinstance(d, dict)}
    placed = {(int(r["id"]), int(r["ally_team_id"])) for r in _spots_by_mission().get(m["mission_id"], [])
              if int(r["ally_team_id"] or 0)}
    # the table lists the deployed forces too (their spots' ally_team_id); the request says which
    sides = _map_setting(m["mission_id"], "ally_sides") or {}     # a mod's side for a node's force
    for spot, team in sorted(placed | set(_live_allies(m["mission_id"])) | set(_start_allies(m["mission_id"])) | mine):
        mine_here = (spot, team) in mine
        iid = _new_ally(m, team, _spot_of(m, spot), belong=ALLY_FRIENDLY if mine_here else sides.get(str(spot)))
        if iid is not None and mine_here:
            m["allies"][iid]["myside"] = True


def _live_allies(mid):
    """Recorded starting forces seen in at least half the runs of the map."""
    seen = _live_spawn_seen(mid)
    runs = max(1, int(seen.get("turns", {}).get("1") or 0))
    return [(int(spot), int(team)) for spot, team, n in seen.get("allies", []) if 2 * n >= runs]


def _ally_json(m, a):
    row = _ally_teams().get(a["ally_team_id"], {})
    iid = next(k for k, v in m["allies"].items() if v is a)
    out = {"ally_team_id": a["ally_team_id"], "ally_instance_id": int(iid), "battleskill_switch": True,
           "target_type": TARGET_MYSIDE if a.get("myside") else TARGET_FROM_ROW, "ally_type": a["belong"], "duration_end_turn": a["end_turn"],
           "ally_enemy": int(a.get("enemy", row.get("enemy_team_id")) or 0)}
    ai, content = _ally_ai(a, row)
    out.update(ai=ai, ai_para=_ai_para(a, ai, content))
    boss = _boss_hp(out["ally_enemy"])
    if boss:        # without it a force whose team has a boss (249 of them: 2298, Beak_M16) starts it at about 1 HP
        out["ally_boss_hp"] = int(a.get("boss_hp") or boss)
    if a.get("hp") is not None:
        out["ally_enemy_hp_percent"] = a["hp"]      # weakened in a fight with another force
    if a.get("guns"):           # re-equipped when it changed sides (ally_changes)
        out["ally_guns"], out["ally_equips"] = _ally_units(a["guns"])
    if a.get("gun_life"):       # hurt in a battle (_note_ally_life)
        if "ally_guns" not in out:
            out["ally_guns"], out["ally_equips"] = _ally_units(_ids(row.get("guns")))
        for gid, life in a["gun_life"].items():
            if gid in out["ally_guns"]:
                out["ally_guns"][gid]["life"] = int(life)
    if a.get("sangvis"):        # Coalition units it got the same way
        out["ally_sangvis"] = _ally_sangvis_units(a["sangvis"])
    return out


def _ally_sangvis_units(units):
    """ally_sangvis {"<sangvis_in_ally id>": {the row, location, position}} (AllyTeam$$CheckJsonTeamGun:
    sangvis_level, sangvis_resolution_level, location, position). location is the unit's place in
    the list from 1, as the client numbers a force's own "id-cell" list (AllyTeamCfg$$get_allySangvisGuns:
    SangvisGun(cfg, index + 1, cell))."""
    rows = {int(r["id"]): r for r in stc.table("sangvis_in_ally")}
    out = {}
    for n, (uid, pos) in enumerate(units, 1):
        row = rows.get(int(uid))
        if row is not None:
            out[str(uid)] = dict(row, location=n, position=int(pos))      # ints: read with get_Int
    return out


def _ally_spots(m):
    return {int(a["spot"]) for a in (m.get("allies") or {}).values()}


def _hostile_ally(m, spot):
    for iid in spot.get("ally_instance_ids") or []:
        a = (m.get("allies") or {}).get(str(iid))
        if a is not None and a["belong"] != ALLY_FRIENDLY:
            return str(iid)
    return None


def _hostile_here(m, spot):
    return bool(int(spot["enemy_team_id"] or 0)) or _hostile_ally(m, spot) is not None


def _remove_ally(m, iid):
    a = (m.get("allies") or {}).pop(str(iid), None)
    spot = _spot_of(m, a["spot"]) if a else None
    if spot is not None:
        spot["ally_instance_ids"] = [i for i in spot.get("ally_instance_ids") or [] if str(i) != str(iid)]


# A defeated enemy team may leave a doll behind: an even pick from its enemy_team.reward_gun_pool,
# where 0 is no doll (recorded on map 126: every doll dropped was in the team's pool), sent as
# battle_get_gun [{gun_with_user_id, gun_id}] and added to the save. The Pilfer chip (special skill
# 102) always takes a doll from the pool. An S-rank clear adds one from the map's
# auto_mission.gun_1_pool (reward_gun in mission_win_result).
@lru_cache(maxsize=None)
def _drop_pool(team_id):
    row = next((r for r in stc.table("enemy_team") if int(r["id"]) == int(team_id or 0)), {})
    return _gun_pool(row.get("reward_gun_pool"))


def _gun_pool(text):
    from . import factory
    known = factory.guns()
    return tuple(g for g in _ids(str(text or "")) if g == 0 or g in known)


def _give_gun(state, gun_id):
    from . import factory
    rec = factory.new_gun_record(state, gun_id, (state.get("user_info") or {}).get("user_id", ""))
    return {"gun_with_user_id": str(rec["id"]), "gun_id": str(rec["gun_id"])}


def _battle_drop(state, reply, team_id, rng=random, always=False):
    pool = [g for g in _drop_pool(int(team_id or 0)) if g or not always]
    gun = rng.choice(pool) if pool else 0
    if not gun:
        return None
    got = _give_gun(state, gun)
    reply.setdefault("battle_get_gun", []).append(got)
    return got


def _clear_drop(state, mid, rng=random):
    """A clear's doll (any rank: recorded on 0-2 at A): an even pick from auto_mission.gun_1_pool (0 is none)."""
    pool = _gun_pool((_auto_missions().get(int(mid)) or {}).get("gun_1_pool"))
    gun = rng.choice(pool) if pool else 0
    return _give_gun(state, gun) if gun else None


def _defeat_on_spot(state, m, spot, reply):
    """A won attack: the enemy on the spot dies, else the hostile force there."""
    if int(spot["enemy_team_id"] or 0):
        _battle_drop(state, reply, spot["enemy_team_id"])
        _enemy_killed(m, spot, state)
        return
    iid = _hostile_ally(m, spot)
    if iid is not None:
        force = m["allies"][iid]
        team = force["ally_team_id"]
        rule = score_rule(m["mission_id"])
        if rule is not None and int(team) not in _death_scored(m["mission_id"]):
            # a hostile force counts as a kill (the live emt0 lists them as ally5 / ally6), by its enemy team
            _add_score(m, _kill_score(rule, force.get("enemy", _ally_teams().get(team, {}).get("enemy_team_id")),
                                      turn=m["turn"]))
        _remove_ally(m, iid)
        quests.record(state, "enemy_die")
        died = m.setdefault("died_allies", {})
        died[str(team)] = died.get(str(team), 0) + 1
        _ally_left(reply, team)
        reply.update(ally_changes(m, ALLY_ON_TEAM_DEAD, team, reply))


# Allied forces that change: ally_team.transform_* (the force leaves the map) and betray_* (it
# changes sides). *_condition is ";"-separated groups, *_number and *_result their values
# position by position ("," within a group); betray_result_guns ("," per position, "|" between
# gun_in_ally ids) and betray_result_ai ("#" per position) re-equip a force that changes sides.
# Recorded (packet log 2026-11-06):
#   6  a mission skill in *_number is cast (11353: myforceSkillPerform 6580116 / 6580114;
#      11355: 6580125), answered in fairy_skill_return.allyteam_b_t
#   2  one of our echelons moves onto the spot in *_number (90038: team 2857 at 80546)
#   9  a force of the ally team in *_number is destroyed (11368: beating instance 18 of team
#      583602 took its twin, instance 2)
# Recorded (packet log 2026-11-06, second part):
#   1  turn n begins (startTurn; 129 Closing In "4,6", 10199 Illusory Peace III "2", 100
#      Desperate Breakout transform "2": its three forces leave at turn 2)
#   3  "<spot>-<side>": a unit of that side stands on the spot when its side's turn ends; a force
#      whose own side it is checks itself (129: its force walking onto 91323 / 91325 / 91328 swaps
#      versions, onto 91329 it leaves, all in endEnemyTurn)
#   4  the enemy team in *_number is beaten (105 Torrent Breaker: the battle beating team 2223 on
#      9279 turned four forces, in that battleFinish reply)
#   201 one of our units moves onto the spot, like 2 (10199: the sangvis echelon onto 10817)
# with 2 and 9 answered as top-level ally_instance_transform / ally_instance_betray. Results:
# transform "0" / "2" the force leaves ("0:0" too); "1:<gun>-<hp>" it leaves a hostage there (11355:
# "9077-3", hostage_hp 3 of 3); betray "0" / "1" / "2" / "3" its new side (ally_type; old_ally_type
# the side before; a rule fires even when the side stays, 105). betray_result_enemy gives the force
# a new enemy team, whose ai it then follows (129: 9130502 "101" "91323,91324"); team 0 leaves it
# no ai and no enemy (10199 back to side 1: ai "0", ally_enemy 0); an enemy team without ai, or none
# given, leaves the force's own ai for its side. APPROXIMATION: conditions 5, 7 and 8 aren't in a
# recording and are left alone.
ALLY_ON_SKILL, ALLY_ON_SPOT, ALLY_ON_TEAM_DEAD = 6, 2, 9
ALLY_ON_TURN, ALLY_ON_STAND, ALLY_ON_ENEMY_DEAD, ALLY_ON_ENTER = 1, 3, 4, 201


def _ally_rule(cond_text, num_text, cond, value):
    """(group, position) of value in the cond group of a condition/number pair, or None."""
    conds, nums = str(cond_text or "").split(";"), str(num_text or "").split(";")
    for g, c in enumerate(conds):
        if c.strip().isdigit() and int(c) == cond and g < len(nums):
            for k, n in enumerate(nums[g].split(",")):
                if n.strip() == str(value) or n.strip().split("-")[0] == str(value):
                    return g, k
    return None


def _pick(text, g, k, sep=","):
    groups = str(text or "").split(";")
    parts = (groups[g] if g < len(groups) else groups[-1]).split(sep)
    return (parts[k] if k < len(parts) else parts[-1]).strip()


@lru_cache(maxsize=1)
def _ally_guns_table():
    return {int(r["id"]): r for r in stc.table("gun_in_ally")}


@lru_cache(maxsize=1)
def _ally_equips_table():
    return {str(r["id"]): r for r in stc.catch("equip_in_ally_info")}


def _ally_units(gun_ids):
    """ally_guns / ally_equips for gun_in_ally ids, as recorded: every value a string, edit_type 2."""
    guns, equips = {}, {}
    for gid in gun_ids:
        row = _ally_guns_table().get(int(gid))
        if row is None:
            continue
        guns[str(gid)] = dict({k: str(v) for k, v in row.items()}, edit_type=2)
        for slot in ("equip1", "equip2", "equip3"):
            eq = _ally_equips_table().get(str(row.get(slot) or 0))
            if eq is not None:
                equips[str(eq["id"])] = dict({k: str(v) for k, v in eq.items()}, edit_type=2)
    return guns, equips


def _ally_left(reply, team):
    """died_this_section.ally lists the ally_team ids (strings) of forces beaten, transformed or
    turned this action (recorded: 11353 line 4 ["6580122", "6580102"] for a betray and a transform)."""
    died = reply.setdefault("died_this_section", {"enemy": [], "ally": []})
    if not isinstance(died.get("ally"), list):
        died["ally"] = []
    if str(team) not in died["ally"]:      # once each (11368: a beaten force and its twin, one team)
        died["ally"].append(str(team))


def _merge_ally(reply, changed):
    """Add ally_changes output to a reply (several rules can fire in one action)."""
    for k, v in (changed or {}).items():
        if isinstance(reply.get(k), dict):
            reply[k].update(v)
        else:
            reply[k] = dict(v)
    return reply


def _ally_later(m, changed, teams):
    """Changes set off where no reply is at hand (an enemy team beaten); the next reply carries them."""
    if changed:
        pend = m.setdefault("ally_pending", {"changes": {}, "teams": []})
        _merge_ally(pend["changes"], changed)
        pend["teams"] += [t for t in teams if t not in pend["teams"]]


def _ally_flush(m, reply):
    pend = m.pop("ally_pending", None) if isinstance(reply, dict) else None
    if pend:
        _merge_ally(reply, pend["changes"])
        for t in pend["teams"]:
            _ally_left(reply, t)
    return reply


def _side_on(m, spot_id, side):
    """Whether a unit of this side stands on the spot (1 ours: echelons and friendly forces,
    2 the enemy's: enemies and enemy-side forces, 0 third parties)."""
    sp = _spot_of(m, spot_id)
    if sp is None:
        return False
    forces = {int(a["belong"]) for a in (m.get("allies") or {}).values() if int(a["spot"]) == int(spot_id)}
    if side == ALLY_FRIENDLY:
        return sp["team_id"] != "0" or str(sp.get("sangvis_team_id") or "0") != "0" or side in forces
    if side == ALLY_ENEMY_SIDE:
        return bool(int(sp["enemy_team_id"] or 0)) or side in forces
    return side in forces


def ally_stand_rules(m, side, reply):
    """Condition 3 at the end of a side's turn, for the tokens of that side."""
    for iid, a in list((m.get("allies") or {}).items()):
        row = _ally_teams().get(a["ally_team_id"], {})
        tokens = set()
        for ct, nt in (("transform_condition", "transform_number"), ("betray_condition", "betray_number")):
            conds = str(row.get(ct) or "").split(";")
            nums = str(_spot_nums(m, ALLY_ON_STAND, row.get(nt)) or "").split(";")
            for g, c in enumerate(conds):
                if c.strip() == str(ALLY_ON_STAND) and g < len(nums):
                    tokens.update(n.strip() for n in nums[g].split(",") if n.strip())
        for tok in sorted(tokens):
            spot, _, who = tok.partition("-")
            if not spot.isdigit() or not (who or str(side)).isdigit() or int(who or side) != side:
                continue
            if str(iid) not in (m.get("allies") or {}):
                break
            here = int(a["spot"]) == int(spot) if int(a["belong"]) == side else _side_on(m, spot, side)
            if here:
                _merge_ally(reply, ally_changes(m, ALLY_ON_STAND, tok, reply, only=iid))
    return reply


def _ally_ai(a, row):
    """(ai, ai_content) a force follows: what a betray gave it, else its ally_team ai for its side
    (ai / ai_content are ";" groups by side 0 / 1 / 2: 105's 2211 "101;1;102" patrols on side 0
    and stands alert on side 2, recorded)."""
    if a.get("ai") is not None and a.get("ai_content") is not None:
        return str(a["ai"]), str(a["ai_content"])
    ais, paras = str(row.get("ai") or "0").split(";"), str(row.get("ai_content") or "0").split(";")
    side = int(a["belong"])
    pick = lambda xs: (xs[side] if side < len(xs) else xs[0]).strip() or "0"
    return pick(ais), local_spots(a.get("mission"), pick(paras))


def _ai_para(a, ai, content):
    """The client's ai_para, as recorded: patrol "@<route>:1", alert "@<spot>,<range>", else ""."""
    if ai == str(TEAM_PATROL):
        return "@%s:1" % content
    if ai == str(TEAM_ALERT):
        return "@%s,%s" % (a["spot"], content)
    return "" if content in ("", "0") else content


def _spot_nums(m, cond, text):
    """A transform / betray number list with a copied map's source nodes as its own, for the
    conditions whose numbers are nodes."""
    return local_spots(m["mission_id"], text) if cond in (ALLY_ON_SPOT, ALLY_ON_ENTER, ALLY_ON_STAND) else text


def ally_changes(m, cond, value, reply=None, only=None):
    """Apply every transform / betray rule that cond with value sets off (for the force only, when
    given). Returns {"ally_instance_transform": {...}, "ally_instance_betray": {...}} with what
    changed, or {}; the forces that changed go in reply's died_this_section (or the next reply's)."""
    out = {"ally_instance_transform": {}, "ally_instance_betray": {}}
    left = []
    for iid, a in list((m.get("allies") or {}).items()):
        if only is not None and str(iid) != str(only):
            continue
        row = _ally_teams().get(a["ally_team_id"], {})
        spot = _spot_of(m, a["spot"])
        hit = _ally_rule(row.get("transform_condition"), _spot_nums(m, cond, row.get("transform_number")), cond, value)
        if hit is not None:
            result = _pick(row.get("transform_result"), *hit) or "0"
            kind, _, hostage = result.partition(":")
            if kind not in ("0", "1", "2"):
                continue
            if hostage.split("-")[0] in ("", "0"):
                hostage = ""            # 100: "0:0" -> transform_result "0", hostage_info ""
            entry = {"ally_instance_id": int(iid), "transform_result": int(kind) if hostage else kind,
                     "hostage_info": hostage, "spot_id": int(a["spot"]), "condition_type": cond,
                     "ally_return_resource": {"ammo": 0, "mre": 0}}
            _remove_ally(m, iid)
            gun, _, hp = hostage.partition("-")
            if spot is not None and gun.isdigit():
                spot.update(hostage_id=gun, hostage_hp=hp or "1", hostage_max_hp=hp or "1")
            out["ally_instance_transform"][iid] = entry
            left.append(a["ally_team_id"])
            continue
        hit = _ally_rule(row.get("betray_condition"), _spot_nums(m, cond, row.get("betray_number")), cond, value)
        if hit is None or list(hit) in (a.get("betrayed") or []):
            continue        # (each rule once; 11353's force changes sides twice, by two skills)
        side = _pick(row.get("betray_result"), *hit)
        if side not in ("0", "1", "2", "3"):
            continue
        old = a["belong"]
        a["belong"] = int(side)
        a.setdefault("betrayed", []).append(list(hit))
        guns = [x for x in _pick(row.get("betray_result_guns"), *hit).split("|") if x.strip().isdigit()]
        if guns:
            a["guns"] = guns
        # betray_result_sangvis "<sangvis_in_ally id>-<position>|..." (4 forces: 9584203 ...)
        units = [x.split("-") for x in _pick(row.get("betray_result_sangvis"), *hit).split("|")]
        units = [(u[0].strip(), u[1].strip()) for u in units if len(u) == 2 and u[0].strip().isdigit() and u[1].strip().isdigit()]
        if units:
            a["sangvis"] = units
        a["ai"] = a["ai_content"] = None
        enemy = _pick(row.get("betray_result_enemy"), *hit) if str(row.get("betray_result_enemy") or "").strip() else ""
        if enemy.isdigit():
            a["enemy"] = int(enemy)
            team = _enemy_teams().get(int(enemy)) if int(enemy) else None
            if not int(enemy):
                a["ai"], a["ai_content"] = "0", ""
            elif team is not None and int(team.get("ai") or 0):
                a["ai"], a["ai_content"] = str(team["ai"]), str(team.get("ai_content") or "")
        ai = _pick(row.get("betray_result_ai"), hit[0], hit[1], "#")
        if ai.lstrip("-").isdigit() and int(ai):
            a["ai"] = ai
            a["ai_content"] = _pick(row.get("betray_result_ai_content"), hit[0], hit[1], "#")
        m.setdefault("ally_patrol", {}).pop(str(iid), None)
        entry = _ally_json(m, a)
        entry.update(ally_type=side, old_ally_type=str(old), condition_type=cond, spot_id=int(a["spot"]),
                     spot_rec=dict(spot) if spot is not None else {}, ally_return_resource={"ammo": 0, "mre": 0},
                     if_withdraw=0, if_fix=0, if_supply=0, if_reinforceAgain=0)
        out["ally_instance_betray"][iid] = entry
        left.append(a["ally_team_id"])
    out = {k: v for k, v in out.items() if v}
    if reply is not None:
        for t in left:
            _ally_left(reply, t)
    else:
        _ally_later(m, out, left)
        return {}
    return out


def _expire_allies(m):
    for iid, a in list((m.get("allies") or {}).items()):
        if a["end_turn"] and int(m["turn"]) >= a["end_turn"]:
            _remove_ally(m, iid)


ALLY_THIRD, ALLY_ENEMY_SIDE = 0, 2
ALLY_ALERT_RANGE = 2
AI_ELIMINATE, AI_CAPTURE = 1, 2
TEAM_PATROL, TEAM_ALERT, TEAM_EXPAND = 101, 102, 103
TEAM_QUIET_PATROL, TEAM_LOCK_ON = 104, 106      # 104 patrols without engaging anyone; 106 as LOCK_ON


def _hostile_spots(m, side, me):
    """Spots holding units hostile to a force of this side (never its own)."""
    out = set()
    for sp in m["spots"]:
        sid = int(sp["spot_id"])
        enemy = bool(int(sp["enemy_team_id"] or 0))
        ours = sid in _echelon_spots(m)
        if side == ALLY_FRIENDLY and enemy or side == ALLY_ENEMY_SIDE and ours or side == ALLY_THIRD and (enemy or ours):
            out.add(sid)
    for iid, a in (m.get("allies") or {}).items():
        if iid != me and a["belong"] != side and not (a["belong"] == ALLY_FRIENDLY and side == ALLY_FRIENDLY):
            out.add(int(a["spot"]))
    return out


def _occupied(m, me):
    taken = {int(s["spot_id"]) for s in _enemy_spots(m)} | _echelon_spots(m)
    return taken | {int(a["spot"]) for iid, a in (m.get("allies") or {}).items() if iid != me}


def _ally_step(m, iid, a, rng, past_own=False):
    """The spot a force moves to this turn, or None. It never enters an occupied spot (past_own:
    as if its own side's forces weren't in the way, the step it would rather wait for)."""
    mid, here = m["mission_id"], int(a["spot"])
    row = _ally_teams().get(a["ally_team_id"], {})
    ai_text, para = _ally_ai(a, row)
    ai = int((_ids(ai_text) or [0])[0])
    if any(j != iid and int(b["spot"]) == here and b["belong"] != a["belong"] for j, b in m["allies"].items()):
        return None         # it met a force of another side here: both stay (105: 2211 after 2214 came, recorded)
    blocked = _occupied(m, iid)
    if past_own:
        blocked = blocked - _own_side_spots(m, iid, a)
    hostile = _hostile_spots(m, a["belong"], iid)
    # a force hostile to the enemy may step onto an enemy and fight it (11116: an expanding force
    # onto enemy 34 at 95276, ally_battle in startOtherSideTurn, recorded)
    prey = {int(sp["spot_id"]) for sp in _enemy_spots(m)} - _echelon_spots(m) if a["belong"] != ALLY_ENEMY_SIDE else set()
    goal = None
    if ai in (TEAM_PATROL, TEAM_QUIET_PATROL):
        route = _ids(para.replace("|", ","))
        if len(route) >= 2:
            if here not in route:
                goal = set(route)
            else:
                i, step = route.index(here), m.setdefault("ally_patrol", {}).get(iid, 1)
                if not 0 <= i + step < len(route):
                    step = -step
                m["ally_patrol"][iid] = step
                goal = {route[i + step]}
    elif ai in (TEAM_ALERT, AI_ELIMINATE):
        dist = _distances(mid, here)
        # alert: its ai_content is the range (105 "1" / "2", 129 "7")
        reach = (int(para) if para.isdigit() and int(para) else ALLY_ALERT_RANGE) if ai == TEAM_ALERT else len(dist)
        seen = [h for h in hostile if h in dist and dist[h] <= reach]
        if seen:
            near = min(dist[h] for h in seen)
            goal = {rng.choice(sorted(h for h in seen if dist[h] == near))}
    elif ai == TEAM_EXPAND:
        # a third party's side is belong 0 (the spots it takes, other_side_turn); Flowers of the
        # End+'s KCCO military expands this way ("KCCO spawns capping K11", the SC guide)
        mine = BELONG_OURS if a["belong"] == ALLY_FRIENDLY else "0" if a["belong"] == ALLY_THIRD else BELONG_ENEMY
        if (_spot_of(m, here) or {}).get("belong") != mine:
            return None     # it takes the spot it stands on first (10199: none moved in enemy turn 1, recorded)
        # every spot not its side's that nobody stands on (one another force just took isn't
        # a goal any more: 10199, recorded, 2 took 10829 and 4 beside it went on to 10833)
        goal = {int(sp["spot_id"]) for sp in m["spots"] if sp["belong"] != mine} - (blocked - prey) or None
    elif ai == TEAM_LOCK_ON:
        goal = _lock_on_goals(m, here, para) or None
    elif ai == AI_CAPTURE:
        theirs = BELONG_ENEMY if a["belong"] == ALLY_FRIENDLY else BELONG_OURS
        types = _spot_types(mid)
        goal = {int(sp["spot_id"]) for sp in m["spots"] if sp["belong"] == theirs and types.get(int(sp["spot_id"])) == SPOT_HQ} or None
    if not goal:
        return None
    # a force never steps onto a heliport or HQ that isn't its side's (129: its patrols to 91324,
    # a heliport we held, and 91326, a neutral one, stood still; the one to 91329 went, recorded)
    mine = (BELONG_OURS if a["belong"] == ALLY_FRIENDLY else BELONG_ENEMY if a["belong"] == ALLY_ENEMY_SIDE
            else "0" if a["belong"] == ALLY_THIRD else None)
    types = _spot_types(mid)
    blocked = blocked | {int(sp["spot_id"]) for sp in m["spots"] if types.get(int(sp["spot_id"])) in (SPOT_HQ, SPOT_HELIPORT)
                         and sp["belong"] != mine}
    nxt = _ally_toward(mid, here, goal, blocked - goal)
    meets = nxt is not None and nxt in goal and nxt in _ally_spots(m) and nxt not in _echelon_spots(m) \
        and nxt not in {int(sp["spot_id"]) for sp in _enemy_spots(m)}
    if meets and ai in (TEAM_ALERT, AI_ELIMINATE):
        return nxt          # onto a hostile force: they meet there (ally_battle, _move_allies)
    if nxt is not None and nxt in prey and nxt in goal and ai != TEAM_QUIET_PATROL             and not any(int(b["spot"]) == nxt for b in m["allies"].values()):
        return nxt          # onto an enemy: they fight (_ally_enemy_fight)
    return nxt if nxt is not None and nxt not in blocked else None


@lru_cache(maxsize=None)
def _spot_xy(mid):
    return {int(r["id"]): (float(r.get("coordinator_x") or 0), float(r.get("coordinator_y") or 0))
            for r in _spots_by_mission().get(mid, [])}


def _ally_toward(mid, here, goal, blocked):
    """A force's next spot toward the nearest goal; between equally short routes the step nearest
    the goal on the map (129: from 91320 toward 91327 by 91323, not 91329; from 91323 toward
    91328 by 91325, not 91320, recorded)."""
    dist = _distances(mid, here, blocked)
    reach = [g for g in goal if g in dist and g != here]
    if not reach:
        return None
    best = min(dist[g] for g in reach)
    targets = [g for g in reach if dist[g] == best]
    xy = _spot_xy(mid)
    options = []
    for nb in _links(mid).get(here, ()):
        if nb in blocked and nb not in targets:
            continue
        d = 0 if nb in targets else min((_distances(mid, nb, blocked).get(g, 10 ** 6) for g in targets), default=10 ** 6)
        if d == best - 1:
            near = min(math.dist(xy.get(nb, (0, 0)), xy.get(g, (0, 0))) for g in targets)
            options.append((near, nb))
    return min(options)[1] if options else None


def _ally_codes(a):
    """The unit codes a force answers to: the target_type the live server gave it, by its side,
    1 -> 3, 2 -> 5, 0 -> 6, and 301 for one the player deployed (recorded on every force in the
    11-05 / 11-06 logs; a betrayed force took its new side's; the client's get_teamEchelon agrees)."""
    if a.get("myside"):
        return {TARGET_MYSIDE}
    return {ALLY_SIDE_CODES.get(int(a.get("belong", -1)), 6)}


def _ally_entered(state, m, iid, a):
    """A force stepped onto its spot: special spots that detect it count the move (11355: the
    enemy-side force 6580116 stepping onto 68321 used up 6580144, which left 6580138 there)."""
    if state is not None:
        _entered(state, m, a["spot"], "ally", iid, _ally_codes(a))


def _ally_battle_reply(m, reply):
    battles = m.pop("ally_battles", None)
    if battles:
        reply["ally_battle"] = battles
    for team in m.pop("ally_fight_dead", None) or []:
        _ally_left(reply, team)
    beaten = m.pop("ally_fight_dead_enemy", None)
    if beaten:
        died = reply.setdefault("died_this_section", {"enemy": [], "ally": []})
        died.setdefault("enemy", []).extend(beaten)
    return reply


def _own_side_spots(m, iid, a):
    return {int(b["spot"]) for j, b in (m.get("allies") or {}).items() if j != iid and b["belong"] == a["belong"]}


def _move_allies(m, side, rng=random, state=None, only=None):
    """One step for every force of this side; returns the ally_move entries. A line of forces moves
    front first, each stepping into the spot the one ahead left (10199, recorded: 4 10828 -> 10833,
    then 3 10827 -> 10828, 2 10826 -> 10829, 1 10825 -> 10826): a force whose step is held by one of
    its side that hasn't moved yet waits for it, and only when none of the rest can move does it
    take the way round (or stay). A free first step on its own way is taken even with its side
    further along (10199, recorded: 4 10833 -> 10837 as soon as 9 had left it).
    APPROXIMATION: the live order within a line (4, 3, 2, 1 recorded) and between equally short
    steps (9 10836 -> 10838, not 10837) isn't known; forces go by instance id, ties by spot id."""
    moves = []
    todo = [(iid, a) for iid, a in sorted((m.get("allies") or {}).items(), key=lambda kv: int(kv[0]))
            if a["belong"] == side and not a.get("myside") and (only is None or iid in only)]
    while todo:
        moved = _move_allies_pass(m, todo, moves, rng, state, wait=True)             or _move_allies_pass(m, todo, moves, rng, state, wait=False)
        todo = [(iid, a) for iid, a in todo if iid not in moved and iid in (m.get("allies") or {})]
        if not moved:
            break
    return moves


def _move_allies_pass(m, todo, moves, rng, state, wait=False):
    moved = set()
    done = {str(x["ally_instance_id"]) for x in moves}
    for iid, a in todo:
        if iid in moved or iid not in (m.get("allies") or {}):
            continue
        nxt = None
        if wait:
            want = _ally_step(m, iid, a, rng, past_own=True)
            ahead = {int(b["spot"]) for j, b in m["allies"].items()
                     if j != iid and b["belong"] == a["belong"] and j not in done and j not in moved
                     and any(j == k for k, _ in todo)}
            if want is not None and want in ahead:
                continue        # the one ahead moves first
            if want is not None and want not in _occupied(m, iid):
                nxt = want      # its own way, even with its side further along it (they move too)
        if nxt is None:
            nxt = _ally_step(m, iid, a, rng)
        if nxt is None:
            continue
        moved.add(iid)
        src, dst = _spot_of(m, a["spot"]), _spot_of(m, nxt)
        if src is not None:
            src["ally_instance_ids"] = [i for i in src.get("ally_instance_ids") or [] if str(i) != iid]
        dst["ally_instance_ids"] = list(dst.get("ally_instance_ids") or []) + [int(iid)]
        moves.append({"squad_instance_id": 0, "ally_instance_id": int(iid), "from_spot_id": int(a["spot"]),
                      "to_spot_id": nxt, "hp_percent": 1.0, "hostage_hp": 0, "hostage_id": 0})
        _note_moved(m, MOVED_ALLY, iid)
        there = [(j, b) for j, b in (m.get("allies") or {}).items() if j != iid and int(b["spot"]) == int(nxt)]
        a["spot"] = dst["spot_id"]
        if a["belong"] == ALLY_ENEMY_SIDE and str(dst.get("hostage_id") or "0") != "0":
            # an enemy-side force reaching a hostage left alone kills it, like an enemy (10199: the
            # hostages on 10829 / 10833 / 10834 / 10841 were gone once its forces walked on; 100:
            # those on 5337 / 5341 / 5344, recorded)
            dst.update(hostage_id="0", hostage_hp="0", hostage_max_hp="0")
            moves[-1]["hostage_id"] = 0
            m["hostages_lost"] = int(m.get("hostages_lost") or 0) + 1
        if there:
            _ally_fight(m, iid, a, there, int(nxt))
            if iid not in (m.get("allies") or {}):
                continue
        if int(dst.get("enemy_team_id") or 0) and a["belong"] == ALLY_THIRD:
            # a third party fights it out here; a friendly force's fight is the client's
            # (battleFinish with the force's dolls, recorded on 11116 after allyMySideMove)
            _ally_enemy_fight(m, iid, a, dst, state)
            if iid not in (m.get("allies") or {}):
                continue
        _ally_entered(state, m, iid, a)
    return moved


def _ce_coefs():
    """The client's enemy CE constants, catchdata game_config_info: enemy_effect_attack
    "22,50,35,2,0.85" and enemy_effect_defence "0.25,35,600,100,1200,0.6" (gflmaps hard-codes them)."""
    cfg = quests._config()
    nums = lambda key, dflt: [float(x) for x in str(cfg.get(key) or dflt).split(",") if x.strip()]
    return nums("enemy_effect_attack", "22,50,35,2,0.85"), nums("enemy_effect_defence", "0.25,35,600,100,1200,0.6")


@lru_cache(maxsize=1)
def _standard_attributes():
    return {int(r["level"]): r for r in stc.table("enemy_standard_attribute")}


@lru_cache(maxsize=1)
def _character_types():
    return {int(r["id"]): r for r in stc.table("enemy_character_type")}


def _enemy_attribute(ct, attr, level):
    """An enemy's attribute at a level, scaled by enemy_standard_attribute (gflmaps enemyattribute)."""
    std = _standard_attributes()
    base = float(ct.get(attr) or 0)
    first = std.get(min(std)) if std else {}
    if not first or not float(first.get(attr) or 0):
        return round(base)
    here, norm = std.get(int(level)), std.get(int(ct.get("level") or 0))
    if here is None or norm is None or not float(norm.get(attr) or 0):
        return round(base)
    v = base * float(here[attr]) / float(norm[attr])
    return v if attr == "maxlife" else round(v)


@lru_cache(maxsize=None)
def _enemy_team_strength(team_id, extra_levels=0):
    """An enemy team's combat effectiveness, the client's formula as gflmaps (Recomp/tools/gflmaps
    efectcal) reproduces it, real value (not effect_ext, the one shown); extra_levels on every
    member (_turn_levels)."""
    (a1, a_rate, a_hit, a_add, a_brk), (d1, d_dodge, d_arm, d_add, d_def, d_ten) = _ce_coefs()
    total = 0
    for r in stc.table("enemy_in_team"):
        if int(r["enemy_team_id"]) != int(team_id or 0):
            continue
        ct = _character_types().get(int(r["enemy_character_type_id"]))
        if ct is None:
            continue
        lv, n = int(r.get("level") or 0) + int(extra_levels or 0), int(r.get("number") or 0)
        at = {k: _enemy_attribute(ct, k, lv) for k in
              ("pow", "def_break", "rate", "hit", "maxlife", "dodge", "armor", "def", "tenacity")}
        dp = float(r.get("def_percent") or 0)
        att = math.ceil(a1 * n * ((at["pow"] + at["def_break"] * a_brk) * at["rate"] / a_rate
                                  * at["hit"] / (at["hit"] + a_hit) + a_add))
        dfn = math.ceil(d1 * (round(n * at["maxlife"]) * (d_dodge + at["dodge"]) / d_dodge
                              * d_arm / (d_arm - at["armor"])
                              * (math.trunc(at["tenacity"] / 100) + 1.0 - d_ten / 100) + d_add)
                        * (at["def"] * 2 - at["def"] * dp / 100 + d_def * 2)
                        / (at["def"] - at["def"] * dp / 100 + d_def) / 2)
        total += math.ceil(float(ct.get("effect_ratio") or 0) * (att + dfn))
    return total


def _force_strength(m, a):
    """A force's strength: its (current) enemy team's combat effectiveness, else a stand-in from its
    dolls, level x number (APPROXIMATION); scaled by the HP it has left."""
    # its enemy team's correction_turn levels for this map turn, as the client's AllyTeamCfg TurnLevelCorrect
    team = a.get("enemy", _ally_teams().get(a["ally_team_id"], {}).get("enemy_team_id"))
    base = _enemy_team_strength(team, _turn_levels(team, m.get("turn") or 1)) if team else 0
    if not base:
        guns = a.get("guns") or _ids(str(_ally_teams().get(a["ally_team_id"], {}).get("guns") or ""))
        base = sum(int(r.get("gun_level") or 0) * int(r.get("number") or 0)
                   for r in (_ally_guns_table().get(int(g)) for g in guns) if r)
    return base * float(a.get("hp") or 1)


def _ally_boss_hp(a):
    """A boss force's boss HP left (AllyTeam$$SetHp puts ally_boss_hp straight into bossHp, so a
    0 would empty its bar): its enemy team's boss_hp times the share it has left; 0 for others."""
    full = _boss_hp(a.get("enemy", _ally_teams().get(a["ally_team_id"], {}).get("enemy_team_id")) or 0)
    return max(1, round(full * float(a.get("hp") or 1))) if full else 0


def _ally_fight(m, iid, a, there, spot_id):
    """Forces of two sides on one spot fight it out (ally_battle). Recorded (105, twice): two forces of
    one enemy team (2224) met and both were gone, win_ally_instance_id 0 and survive_force -1.
    APPROXIMATION: unequal forces (by combat effectiveness, _force_strength): the stronger
    survives, weakened by the loser's share (ally_enemy_hp_percent); no such fight is recorded."""
    before = [_ally_json(m, b) for _, b in there] + [_ally_json(m, a)]
    sides = [(j, b) for j, b in there] + [(iid, a)]
    power = {j: _force_strength(m, b) for j, b in sides}
    best = max(power.values())
    top = [j for j, v in power.items() if v == best]
    win = top[0] if len(top) == 1 else None
    rest = sum(v for j, v in power.items() if j != win)
    hp = round(max(0.01, 1 - rest / best), 4) if win is not None and best else 1
    for j, b in sides:
        if j == win:
            b["hp"] = hp * float(b.get("hp") or 1)
            continue
        _remove_ally(m, j)
        m.setdefault("ally_fight_dead", [])
        if b["ally_team_id"] not in m["ally_fight_dead"]:
            m["ally_fight_dead"].append(b["ally_team_id"])
    m.setdefault("ally_battles", []).append({
        "win_ally_instance_id": int(win or 0), "ally_boss_hp": _ally_boss_hp(dict(sides)[win]) if win is not None else 0,
        "ally_enemy_hp_percent": hp if win is not None else 1, "enemy_instance_id": 0, "enemy_team_id": 0,
        "boss_hp": 0, "enemy_hp_percent": 1, "spot_id": spot_id,
        # recorded: -1 when none survived (105), 0 when a force did (11116: 13 won, 0.453 left)
        "survive_force": 0 if win is not None else -1,
        "ally_before_battle": before, "enemy_before_battle": []})


SURVIVE_FORCE, SURVIVE_ENEMY, SURVIVE_NONE = 0, 2, -1


def _ally_enemy_fight(m, iid, a, spot, state=None):
    """A force steps onto an enemy: they fight (ally_battle with the enemy's fields). Recorded on
    11116 (startOtherSideTurn): force 7 onto enemy 34, win_ally_instance_id 0, the enemy left at
    enemy_hp_percent 0.34, survive_force 2, the force gone. APPROXIMATION: the outcome by strength,
    as for two forces (_force_strength against the enemy team's combat effectiveness x its HP)."""
    team = int(spot["enemy_team_id"])
    before = [_ally_json(m, a)]
    mine = _force_strength(m, a)
    foe = _enemy_team_strength(team, _turn_levels(team, m.get("turn") or 1)) * float(spot.get("enemy_hp_percent") or 1)
    entry = {"ally_boss_hp": 0, "enemy_instance_id": str(spot["enemy_instance_id"]), "enemy_team_id": str(team),
             "boss_hp": str(spot.get("boss_hp") or 0), "spot_id": int(spot["spot_id"]),
             "ally_before_battle": before, "enemy_before_battle": []}
    if mine > foe:
        a["hp"] = round(max(0.01, 1 - foe / mine), 4) * float(a.get("hp") or 1)
        entry.update(win_ally_instance_id=int(iid), ally_enemy_hp_percent=round(a["hp"], 4),
                     enemy_hp_percent=0, survive_force=SURVIVE_FORCE, ally_boss_hp=_ally_boss_hp(a))
        # the beaten team goes in died_this_section, as from our own battles (no recording of a force
        # winning; without it the client was left waiting on turn 3 of a Hornet's Nest+ copy)
        m.setdefault("ally_fight_dead_enemy", []).append(str(team))
        _enemy_killed(m, spot, state, by="npc")
    else:
        left = round(max(0.01, 1 - mine / foe), 4) if foe else 1
        spot["enemy_hp_percent"] = str(round(left * float(spot.get("enemy_hp_percent") or 1), 4))
        entry.update(win_ally_instance_id=0, ally_enemy_hp_percent=1, enemy_hp_percent=float(spot["enemy_hp_percent"]),
                     survive_force=SURVIVE_ENEMY)
        _remove_ally(m, iid)
        dead = m.setdefault("ally_fight_dead", [])
        if a["ally_team_id"] not in dead:
            dead.append(a["ally_team_id"])
    m.setdefault("ally_battles", []).append(entry)


def _once_per_turn(m, key):
    if m.get(key) == int(m["turn"]):
        return False
    m[key] = int(m["turn"])
    return True


def ally_my_side_move(state, body, rng=random):
    m = _mission(state)
    if m is None:
        return None
    moves = _move_allies(m, ALLY_FRIENDLY, rng, state) if _once_per_turn(m, "allies_moved") else []
    return _ally_battle_reply(m, {"ally_move": moves, "all_ally_team_moved": True, "type5_score": 0})


# --- friends' support echelons -----------------------------------------------------------
#
# Mission/reinforceFriendTeam {spot_id, friend_team_id: -<friend uid>, group_id, friend_gunids,
# friend_sangvisids} (RequestReinforce) -> dolls: {"guns": {"<id>": gun row}, "equips": {"<id>": equip
# row}, "friend_team_fairy": fairy row}; Coalition: {"sangvisteam", "sangvis_chips", "sangvises"} (see
# friends.py); both with "friend_team_end_time" and "ap" (DeploymentTeamInfoController
# $$RequestReinforceHandle; the doll reply recorded on map 100). The echelon is friends.borrow's;
# deploying is free (recorded: ap stayed 0), and a map takes at most mission.support_available.
# Mission/friendTeamAi {friend_team_id, ai_type} -> "1" (recorded null; unread): the client's AIBehavior,
# 0 Await, 1 KillEnemy, 2 CaptureHQ.
# Mission/friendTeamMove {} (RequestFriendTurn, no body) -> {"friend_team_id", "from_spot_id",
# "to_spot_id", "all_friend_team_moved", "type5_score"} (recorded, the ids as text)
# (DeploymentController$$RequestFriendTurnHandle): the server moves the friends, one per call; the
# client asks again until all_friend_team_moved (TriggerFriendTurnEvent), then runs the allied
# forces' turn and endTurn. The move keys go out only with a move (the handler checks friend_team_id).
# Moves are free. Recorded on map 100: KillEnemy stepped one spot towards the enemy, and endTurn
# took that spot (change_belong1), so friends hold spots as our echelons do; enemies treat them as
# ours too (_echelon_spots). Each friend steps one spot a turn, along a shortest route to the nearest
# enemy (KillEnemy) or to the nearest HQ not ours, else the nearest enemy (CaptureHQ). Stepping onto
# an enemy is an attack the client fights and reports (battleFinish, sangvisBattleFinish for a
# Coalition friend), as for our echelons; a lost battle takes the friend off the map. Friend kills
# are counted apart (enemydie_num_killbyfriend) and drop nothing.
# On the map a friend is its spot's team_id (dolls) or sangvis_team_id (Coalition): "-<uid>[:zone]"
# (SpotAction$$UpdateInfo), which _hidden_view adds to every spot list sent. A resumed map gets
# them back from mission_act_info.friend_act_info (_friend_act_info).

FRIEND_AWAIT, FRIEND_KILL, FRIEND_HQ = 0, 1, 2


def _friend_spots(m):
    return {int(f["spot"]) for f in (m.get("friends") or {}).values()}


def _friend_on(m, spot_id):
    return next((k for k, f in (m.get("friends") or {}).items() if str(f["spot"]) == str(spot_id)), None)


def _with_friends(m, spots):
    """A spot list with each friend's id on its spot (copies; the map's own spots stay as they are)."""
    at = {str(f["spot"]): (k, f) for k, f in (m.get("friends") or {}).items()}
    if not at:
        return spots
    out = []
    for s in spots:
        hit = at.get(str(s["spot_id"]))
        if hit is not None:
            s = dict(s, **{"sangvis_team_id" if hit[1].get("kind") == "sangvis" else "team_id": hit[0]})
        out.append(s)
    return out


def reinforce_friend(state, body):
    m = _mission(state)
    body = body or {}
    if m is None:
        return None
    spot, fid = _spot_of(m, body.get("spot_id")), str(body.get("friend_team_id") or "")
    uid = fid.lstrip("-")
    limit = int(_missions()[m["mission_id"]].get("support_available") or 0)
    if spot is None or not uid.isdigit() or fid in (m.get("friends") or {}) \
            or int(spot["spot_id"]) in _echelon_spots(m) or int(m.get("friend_count") or 0) >= limit:
        return None
    team = friends.borrow(state, uid, body.get("group_id"), body.get("friend_gunids"), body.get("friend_sangvisids"))
    if team is None:
        return None
    sangvis = "sangvises" in team
    m.setdefault("friends", {})[fid] = {
        "uid": uid, "group": str(body.get("group_id") or ""), "spot": spot["spot_id"], "ai": FRIEND_AWAIT,
        "kind": "sangvis" if sangvis else "gun", "life": {}, "team": {k: v for k, v in team.items() if k != "end_time"}}
    m["friend_count"] = int(m.get("friend_count") or 0) + 1
    reply = {"friend_team_end_time": team["end_time"], "ap": int(m.get("ap") or 0), "type5_score": 0}
    if sangvis:
        reply.update(sangvisteam=team["team"], sangvis_chips=team["chips"], sangvises=team["sangvises"])
    else:
        reply.update(guns=team["guns"], equips=team["equips"])
        if team["fairy"]:
            reply["friend_team_fairy"] = team["fairy"]
    return _reveal(state, m, reply)


def friend_ai(state, body):
    m = _mission(state)
    f = (m.get("friends") or {}).get(str((body or {}).get("friend_team_id"))) if m is not None else None
    if f is not None:
        f["ai"] = int((body or {}).get("ai_type") or 0)
    return "1"          # the live null would be error:1 here; the client doesn't read the reply


def _friend_step(m, f):
    if f["ai"] not in (FRIEND_KILL, FRIEND_HQ):
        return None
    here = int(f["spot"])
    # friends never pick up hostages (friendTeamMove's hostage_id is 0), so they keep off a spot
    # where one stands alone
    hostages = {int(s["spot_id"]) for s in m["spots"]
                if str(s.get("hostage_id") or "0") != "0" and not int(s["enemy_team_id"] or 0)}
    blocked = (_echelon_spots(m) - {here}) | _ally_spots(m) | _no_entry_spots(m) | hostages
    foes = {int(s["spot_id"]) for s in _enemy_spots(m)}
    goals = foes
    if f["ai"] == FRIEND_HQ:
        goals = {int(s["spot_id"]) for s in _hq_spots(m) if s["belong"] != BELONG_OURS} or foes
    nxt = _step_toward(m["mission_id"], here, goals, blocked)
    return None if nxt is None or nxt in blocked else nxt


def friend_team_move(state, body):
    m = _mission(state)
    if m is None:
        return None
    teams, turn = m.get("friends") or {}, int(m["turn"])
    moved = m.setdefault("friend_moved", {})
    # recorded (2026-11-07): all_friend_team_moved 1, the move keys only with a move
    reply = {"all_friend_team_moved": 1, "type5_score": 0}
    stuck = []
    for key in sorted(teams):
        if moved.get(key) == turn:
            continue
        f = teams[key]
        nxt = _friend_step(m, f)
        if nxt is None:
            # no way now: it plans again at the next call, once another has moved out of its
            # way; a call that moves nobody ends the friends' turn
            stuck.append(key)
            continue
        moved[key] = turn
        here = int(f["spot"])
        # as recorded, doll and Coalition friends alike: the ids as text and no hp / hostage keys
        reply.update(friend_team_id=str(key), from_spot_id=str(here), to_spot_id=str(nxt),
                     all_friend_team_moved=int(all(moved.get(k) == turn for k in teams)))
        _note_moved(m, MOVED_FRIEND, key)
        dst = _spot_of(m, nxt)
        if int(dst["enemy_team_id"] or 0) or _hostile_ally(m, dst) is not None:
            m["pending_battle"] = {"friend": key, "from": str(here), "spot": str(nxt)}
        else:
            f["spot"] = dst["spot_id"]
        break
    else:
        for key in stuck:
            moved[key] = turn
    return _reveal(state, m, _effect_keys(m, reply))


def _friend_battle_end(state, m, body, spot, pending, attack, key, won, rng):
    """A friend's echelon fought: its own attack after friendTeamMove, or an enemy's on it."""
    f = (m.get("friends") or {}).get(key)
    units = [g for g in (body.get("guns") or []) + (body.get("sangvises") or []) if isinstance(g, dict) and "life" in g]
    if f is not None:
        full = f.setdefault("full", {})
        for g in units:
            gid = str(g.get("id"))
            full.setdefault(gid, max(1, int(g["life"] or 0)))      # the first report stands for full HP
            f["life"][gid] = int(g["life"] or 0)
    _battle_supply(state, m, body, "ally", "0")
    reply = {"seed": rng.randint(1, 9999), "battle_rank": RANK_S if won else RANK_LOST, "type5_score": 0}
    res = _support_resource(state, m, body)
    if res is not None:
        reply["squad_resource"] = res
    foe = _spot_of(m, attack["from"]) if attack is not None else spot
    if won and foe is not None:
        if int(foe["enemy_team_id"] or 0):
            _enemy_killed(m, foe, state, by="friend")
        else:
            iid = _hostile_ally(m, foe)
            if iid is not None:
                team = m["allies"][iid]["ally_team_id"]
                _remove_ally(m, iid)
                _ally_left(reply, team)
                reply.update(ally_changes(m, ALLY_ON_TEAM_DEAD, team, reply))
        if attack is None and f is not None and spot is not None and str(spot.get("hostage_id") or "0") == "0":
            f["spot"] = spot["spot_id"]     # beside a freed hostage it stays where it was
    elif not won:
        (m.get("friends") or {}).pop(key, None)         # beaten or retreated: off the map
    reply = _check_loss(state, m, _effect_keys(m, reply))
    return _reveal(state, m, reply if "mission_lose_result" in reply else _check_win(state, m, reply))


def _friend_act_info(m):
    """mission_act_info.friend_act_info for a resumed map, an object (GameData$$ReadUserInfo ->
    MissionAction$$ReadMission_Friend_info, every part guarded): friend_team_ai [{friend_team_id, ai}],
    friend_teams ["<id>"] (doll friends; a Coalition friend comes with its own parts, and listing it
    twice would add it twice), friend_guns / friend_equips / friend_team_fairy [rows], guns_life
    {"<uid>_<gun id>": {user_id, id, life}}, friend_team_sangvisteams {"<id>": {"sangvis": {...}}},
    friend_team_sangvis_chips {"<id>": [chips]}, friend_team_sangvises {"<id>": {"<unit id>": row}},
    friend_sangvises_life {"<unit id>-<uid>:0": {life}}. Units with no battle yet keep full HP."""
    teams = m.get("friends") or {}
    act = {"friend_team_ai": [{"friend_team_id": k, "ai": int(f["ai"])} for k, f in sorted(teams.items())],
           "friend_teams": [], "friend_guns": [], "friend_equips": [], "friend_team_fairy": [], "guns_life": {},
           "friend_team_sangvisteams": {}, "friend_team_sangvis_chips": {}, "friend_team_sangvises": {},
           "friend_sangvises_life": {}}
    for k, f in sorted(teams.items()):
        team, life = f.get("team") or {}, f.get("life") or {}
        if f.get("kind") == "sangvis":
            act["friend_team_sangvisteams"][k] = team.get("team") or {"sangvis": {}}
            act["friend_team_sangvis_chips"][k] = team.get("chips") or []
            act["friend_team_sangvises"][k] = team.get("sangvises") or {}
            for uid_, hp in life.items():
                act["friend_sangvises_life"][f"{uid_}-{f['uid']}:0"] = {"life": hp}
            continue
        act["friend_teams"].append(k)
        act["friend_guns"] += list((team.get("guns") or {}).values())
        act["friend_equips"] += list((team.get("equips") or {}).values())
        if team.get("fairy"):
            act["friend_team_fairy"].append(team["fairy"])
        for gid, hp in life.items():
            act["guns_life"][f"{f['uid']}_{gid}"] = {"user_id": int(f["uid"]), "id": int(gid), "life": hp}
    return {k: v for k, v in act.items() if v}


def _third_parties_hold(m):
    """Third parties take the spots they stand on: {spot: 0} for those that changed.
    At night the client draws a third party only on a spot it holds (seen on the 10508 copy:
    the forces at 91519 / 91521 showed once endOtherSideTurn turned their spots to 0), so on
    night maps this runs at the start too. Hidden nodes (HIDDEN_BELONGS) stay as they are: they open by their
    own rules (Vortex of Secrets)."""
    taken = {}
    for a in (m.get("allies") or {}).values():
        sp = _spot_of(m, a["spot"])
        if (a["belong"] == ALLY_THIRD and sp is not None and sp["belong"] != "0"
                and str(sp["belong"]) not in HIDDEN_BELONGS):
            sp["belong"] = "0"
            taken[sp["spot_id"]] = 0
    return taken


def other_side_turn(state, body):
    """startOtherSideTurn / othersideTurnMove / endOtherSideTurn: third parties take their step once a
    turn (in the first of these calls)."""
    m = _mission(state)
    if m is None:
        return None
    _expire_allies(m)
    first = _once_per_turn(m, "third_moved")
    moves = _move_allies(m, ALLY_THIRD, state=state) if first else []
    reply = _ally_battle_reply(m, {"type5_score": 0, "enemy_move": [], "ally_move": moves})
    if first:
        # third parties take the spots they stand on (105: endOtherSideTurn change_belong
        # {"9270": 0, ...}, recorded)
        taken = _third_parties_hold(m)
        if taken:
            reply["change_belong"] = taken
    reply = ally_stand_rules(m, ALLY_THIRD, reply) if first else reply
    if first:
        _recorded_markers(m, "startOtherSideTurn")
    # recorded (11116): the special spots, cooldowns and step list come in these replies too
    return _reveal(state, m, _effect_keys(m, reply))


def reinforce_ally(state, body):
    m = _mission(state)
    body = body or {}
    if m is None:
        return None
    spot = _spot_of(m, body.get("spot_id"))
    iid = _new_ally(m, body.get("ally_team_id"), spot, belong=ALLY_FRIENDLY)
    # free, like its moves (recorded on map 100: reinforceAllyTeam at 4 AP answered ap "4")
    if iid is None:
        return {"ally_instance_id": 0, "ally_instance_info": {}, "ap": m["ap"]}
    return {"ally_instance_id": int(iid), "ally_instance_info": {iid: _ally_json(m, m["allies"][iid])}, "ap": m["ap"]}


def ally_ai(state, body):
    m = _mission(state)
    a = (m.get("allies") or {}).get(str((body or {}).get("ally_instance_id"))) if m is not None else None
    if a is not None:
        a["ai_type"] = int((body or {}).get("ai_type") or 0)
    return "1"


# RequestAllyCuipiBattle$$.ctor writes meet_type 1 when one of the spots has a rangeAttackTeam
# (SpotAction+0x50: a ranged attack), else 2; it's sent from DeploymentController CheckBattle,
# CheckAllCuipiAllyBattle, CheckSquadBattle (a HOC's meeting), CreateCuiBattleRequest and
# ShowAllyOtherAttackBattle. Only the Commander's meet_type 2 is recorded; the other cases (and
# the reply's team / friendteam / sangvis / otherside sides) have no record or data, so they get
# the bare reply (every key is optional) and the map goes on as the server already moved it.
MEET_KILL = 2


def no_battle_meet(state, body):
    """Mission/noBattleMeet {appoint_spots, meet_type}: a no-fight encounter with an allied force;
    every reply key is optional (MissionAction$$ReadAllyCuipiBattleChange reads
    nobattle_ally_life_change's per-spot team / friendteam / sangvis / enemy / myside / enemyside /
    otherside under Contains). Recorded (11946, 2026-11-08): meet_type 2 after the Commander walked
    onto a URNC force's spot: {"<spot>": {"enemyside": {"enemy_hp_percent": 0, "boss_hp": 0},
    "myside": {"770000": <the Commander's HP left>}}}, the force gone (died_this_section) and the
    client then sent buildingSkillPerformOnDeath. The hostile force dies here, and the Commander
    pays its HP for it (_commander_hit)."""
    m = _mission(state)
    if m is None:
        return None
    body = body or {}
    reply = {"type5_score": 0}
    if int(body.get("meet_type") or 0) != MEET_KILL:
        return reply
    spots = body.get("appoint_spots") or []
    for sid in (spots if isinstance(spots, list) else _ids(spots)):
        spot = _spot_of(m, sid)
        foe = _hostile_ally(m, spot) if spot is not None else None
        if foe is None:
            continue
        f = m["allies"][foe]
        enemy = f.get("enemy", _ally_teams().get(int(f["ally_team_id"]), {}).get("enemy_team_id"))
        change = {"enemyside": {"enemy_hp_percent": 0, "boss_hp": 0}}
        ciid, cmd = _commander_on(m, spot["spot_id"])
        if cmd is not None:
            gid, life = _commander_hit(m, cmd, enemy)
            change["myside"] = {str(gid): life}
        _defeat_on_spot(state, m, spot, reply)
        if cmd is not None:
            _commander_dies(m, ciid, cmd, reply)
        reply.setdefault("nobattle_ally_life_change", {})[str(spot["spot_id"])] = change
    return _reveal(state, m, _check_win(state, m, _effect_keys(m, reply)))


# --- combat simulations and other mission calls -----------------------------------------
#
# Mission/coinTeam {"team_change": {"<team>": {"<slot>": {"gun_with_user_id", "position"}}}}
# (UISimulatorFormation$$RequestSaveFormation): the echelon picked for a combat simulation; the
# client then refreshes its team list (reply not read).
# Mission/coinBattleFinish {mission_id, boss_hp, duration, battle_time, ...}
# (BattleController$$RequestSimulatorBattleFinish) -> {"seed"}. The client adds the rewards itself
# ("客户端累计战果") and takes the energy (bp, mission.costbp); the save gets the same here: training
# data coin<coin_type> += coin_reward, from this run's time; the fastest kill is kept as the mission's
# shortest_in_coinmission, which sweeps pay by (Mission/simulation).
# coin_reward is the client's own UISimulatorBattleResultController$$CalculateCoinAfterBattle: with
# getcoin_parameter "a,b,c,d" and t seconds, getcoin + floor(a - b*t) from 10s to 30s, getcoin + floor(c - d*t)
# under 10s, and getcoin * coin_get_failure_ratio (0 when not configured) past 30s or on a failed fight.
# Mission/intelligencePoint {mission_id} (UnclockMission): unlock a mission with intel points.

COIN_FAST, COIN_LIMIT = 10.0, 30.0


def coin_reward(row, seconds):
    base = int(str(row.get("getcoin") or 0).split(",")[0] or 0)
    p = [float(x) for x in str(row.get("getcoin_parameter") or "").split(",") if x.strip()]
    if seconds is None or seconds > COIN_LIMIT or len(p) < 4:
        return int(base * float(quests._config().get("coin_get_failure_ratio") or 0))
    a, b = (p[0], p[1]) if seconds >= COIN_FAST else (p[2], p[3])
    return base + math.floor(a - b * seconds)


def _spend_bp(ui, n):
    """Simulation energy: the free bp first, then the bought bp_pay."""
    free = min(int(ui.get("bp") or 0), n)
    _add(ui, "bp", -free)
    _add(ui, "bp_pay", -min(int(ui.get("bp_pay") or 0), n - free))


def _pairs_config(text):
    return {int(k): int(v) for k, _, v in (p.partition(":") for p in str(text or "").split(";")) if v}


def _sweep_amounts(row):
    """(item or gift, id, amount per run) of a fixed-reward simulation (game_config duplicate*)."""
    cfg, mid, sub = quests._config(), int(row["id"]), int(row.get("sub") or 1)
    if int(row["duplicate_type"]) == 2:
        return "item", "9", [int(x) for x in cfg.get("duplicate2_win_item9", "1-2-3").split("-")][sub - 1]
    if int(row["duplicate_type"]) == 5:
        return "item", "45", [int(x) for x in cfg.get("duplicate5_win_item45", "8-20-30").split("-")][sub - 1]
    gifts, items = _pairs_config(cfg.get("duplicate1_giftitem200001")), _pairs_config(cfg.get("duplicate1_item46"))
    if mid in gifts:
        return "gift", "200001", gifts[mid]
    return "item", "46", items.get(mid, 0)


EXP_SIM_COMMANDER = 24      # Commander EXP per exp_parameter point of an EXP Mode run (player report, 2026-11-07)


def exp_sim_commander_exp(state, row):
    """Commander EXP for one EXP Mode run. The user's live sweeps: I 264, II 1056, III 3169 (exp_parameter
    10/40/120, a 10% battle_commander_exp_up outfit). That is ceil(exp_parameter * 24 * 1.1), done in
    floating point the way the live server's PHP did: 2880 * 1.1 is 3168.0000000000005, which rounds up
    to 3169. INFERRED: the 24, and that the ceiling also applies at other bonuses."""
    return math.ceil(int(row.get("exp_parameter") or 0) * EXP_SIM_COMMANDER
                     * (1 + outfit_bonus(state, "battle_commander_exp_up") / 100))


def simulation_sweep(state, body):
    """Mission/simulation {"m_type", "m_id", "count"}: count runs at once (the client takes the energy too).
    RequsetSimulationRaid$$SuccessJsonHandleData reads optional coin1-3, item {id: n}, gift_item {id: n}.
    Training data (duplicate_type 3) pays coin_reward at the mission's fastest time on record, and is a
    user_info currency (coin<coin_type>), not an inventory item. The EXP simulations (EXP Mode,
    duplicate_type 1 with an exp_parameter) also pay Commander EXP, as user_exp
    (exp_sim_commander_exp); the other simulations pay none (player report;
    a recorded live Data Mode sweep answered coin2 alone)."""
    body = body or {}
    row = _missions().get(int(body.get("m_id") or 0))
    count = max(1, int(body.get("count") or 1))
    if row is None or int(row["duplicate_type"]) not in (1, 2, 3, 5):
        return {}
    ui = state["user_info"]
    _spend_bp(ui, int(row.get("costbp") or 0) * count)
    if int(row["duplicate_type"]) == 3:
        best = float(_mission_record(state, row["id"]).get("shortest_in_coinmission") or 0)
        amount = coin_reward(row, best if best > 0 else None) * count
        key = f"coin{int(row['coin_type'])}"
        _add(ui, key, amount)
        return {key: amount}
    kind, iid, each = _sweep_amounts(row)
    amount = each * count
    reply = {}
    if amount:
        quests.grant(state, {"gift" if kind == "gift" else "item_ids": f"{iid}-{amount}"})
        reply["gift_item" if kind == "gift" else "item"] = {iid: amount}
    if int(row["duplicate_type"]) == 1 and int(row.get("exp_parameter") or 0):
        exp = exp_sim_commander_exp(state, row) * count
        _add(ui, "experience", exp)
        reply["user_exp"] = exp
    return reply


def coin_team(state, body):
    from . import formation
    for team, slots in ((body or {}).get("team_change") or {}).items():
        if isinstance(slots, dict):
            formation.quick_team(state, {"team_id": team, "guns": slots})
    return "1"


def coin_battle_finish(state, body, rng=random):
    body = body or {}
    row = _missions().get(int(body.get("mission_id") or 0))
    if row is None:
        return None
    ui = state["user_info"]
    _spend_bp(ui, int(row.get("costbp") or 0))
    kind = int(row.get("coin_type") or 0)
    seconds = float(body.get("duration") or 0)
    killed = int(body.get("boss_hp") or 0) <= 0
    if kind:
        _add(ui, f"coin{kind}", coin_reward(row, seconds if killed else None))
    if killed and seconds > 0:
        rec = _mission_record(state, row["id"])
        best = float(rec.get("shortest_in_coinmission") or 0)
        rec["shortest_in_coinmission"] = f"{min(best, seconds) if best > 0 else seconds:.2f}"
    return {"seed": rng.randint(1, 9999)}


def unlock_mission(state, body):
    mid = int((body or {}).get("mission_id") or 0)
    if mid in _missions():
        _mission_record(state, mid)
    return "1"


# --- event list (Index/index mission_event_info) ------------------------------------------
#
# The client takes each event's status from mission_event_info in the Index/index reply, a copy of
# stc mission_event rows (all values strings) plus "draw_info" and "after_days", keyed by id.
# type 2 = permanent (in the campaign list for good, no start/end time); type 1 = time-limited,
# closed once end_time has passed. The save keeps the list the live server last sent, so changes to
# mission_event (mods/collab_events makes the collaborations permanent) are applied here, to the
# reply only: turning the mod off brings the saved list back.
EVENT_PERMANENT = 2


def event_info(saved):
    out = {k: dict(v) for k, v in (saved or {}).items()}
    for row in stc.table("mission_event"):
        key = str(row["id"])
        entry = {f: str(v) for f, v in row.items()}
        if key in out:
            out[key].update(entry)
        elif int(row["type"]) == EVENT_PERMANENT:
            out[key] = dict(entry, draw_info=[], after_days=999)
    return out
