"""Changes to owned units and their upkeep: retiring, linking, skill training.

Reply formats (from the client's handlers; all of these only check for "1"):
  Fairy/retireFairy            RetireController$$RequestRetireFairyHandle
  Vehicle/disassembleComponent RequestRetireComponents$$SuccessHandleData
  Gun/combineGun               CombineController$$RequestCombineHandle
  Gun/skillUpgrade             ResearchSkillTrainingController$$RequestBeginTrainingHandle
  Gun/finishUpgrade            ResearchAction$$SkillNormalFinishHandle
  Gun/quickUpgrade             ResearchAction$$SkillQuicklyFinishHandle
The client applies its own side of each change (rewards, costs) locally; these functions
keep the save in step so the change survives a relogin.
"""
import math
import time
from functools import lru_cache

from . import stc
from .factory import _add, _type_info, gun_enhancement, guns


def _remove_keyed(collection, ids):
    """Drop entries by id from a save collection stored either as a list or as {id: entry}."""
    ids = {str(i) for i in ids}
    if isinstance(collection, dict):
        for i in ids:
            collection.pop(i, None)
        return collection
    return [x for x in collection if str(x.get("id")) not in ids]


def retire_fairy(state, body):
    """Fairy/retireFairy {"fairies": [fairy_with_user_id, ...]}."""
    ids = (body or {}).get("fairies") or []
    state["fairy_with_user_info"] = _remove_keyed(state.get("fairy_with_user_info") or {}, ids)
    return "1"


def disassemble_component(state, body):
    """Vehicle/disassembleComponent {"component_list": [id, ...]}.
    TODO: the materials refunded (Data$$GetComponentRetireMaterial) are only added client-side."""
    ids = (body or {}).get("component_list") or []
    state["vehicle_component_with_user_info"] = _remove_keyed(state.get("vehicle_component_with_user_info") or {}, ids)
    return "1"


@lru_cache(maxsize=1)
def _link_core_cost():
    """Cores per dummy link by doll rank, from game_config gun_recover_core ("2:1,3:3,...")."""
    row = next((r for r in stc.catch("game_config_info") if r["parameter_name"] == "gun_recover_core"), None)
    pairs = (row["parameter_value"] if row else "2:1,3:3,4:9,5:15").split(",")
    return {int(k): int(v) for k, v in (p.split(":") for p in pairs)}


def combine_gun(state, body):
    """Gun/combineGun {"gun_with_user_id", "combine": [ids of duplicate dolls consumed]}.
    An empty combine list is a dummy link paid with cores (one link)."""
    body = body or {}
    target = str(body.get("gun_with_user_id"))
    consumed = [str(i) for i in body.get("combine") or []]
    dolls = state.get("gun_with_user_info", [])
    g = next((d for d in dolls if str(d["id"]) == target), None)
    if g is None:
        return None
    links = len(consumed) or 1
    if not consumed:
        rank = int(guns().get(int(g["gun_id"]), {}).get("rank") or 5)
        _add(state["user_info"], "core", -_link_core_cost().get(rank, 15))
    else:
        state["gun_with_user_info"] = dolls = [d for d in dolls if str(d["id"]) not in consumed]
    g["number"] = str(min(5, int(g.get("number") or 1) + links))
    return "1"


# APPROXIMATION: the client computes training time itself (SkillTrainingEndTime); the
# server only needs an end_time. One hour per level keeps timed training plausible.
TRAINING_SECONDS_PER_LEVEL = 3600


def _skill_owner(state, act):
    gid = str(act.get("gun_with_user_id") or 0)
    return next((d for d in state.get("gun_with_user_info", []) if str(d["id"]) == gid), None)


def skill_upgrade(state, body):
    """Gun/skillUpgrade {"skill", "if_quick", "gun_with_user_id", "upgrade_slot", "to_level"}.
    Quick training levels the skill at once; otherwise an upgrade_act_info entry (read by
    GameData$$ReadUserInfo: upgrade_slot, gun/sangvis/fairy_with_user_id, end_time, skill)
    holds it until Gun/finishUpgrade."""
    body = body or {}
    gun = _skill_owner(state, body)
    if gun is None:
        return None
    skill, to_level = int(body.get("skill") or 1), int(body.get("to_level") or 0)
    if int(body.get("if_quick") or 0):
        gun[f"skill{skill}"] = str(to_level)
        return "1"
    cur = int(gun.get(f"skill{skill}") or 1)
    slot = int(body.get("upgrade_slot") or 1)
    acts = [a for a in state.get("upgrade_act_info") or [] if int(a["upgrade_slot"]) != slot]
    acts.append({"upgrade_slot": slot, "gun_with_user_id": str(gun["id"]), "sangvis_with_user_id": 0,
                 "fairy_with_user_id": 0, "skill": skill, "to_level": to_level,
                 "end_time": int(time.time()) + TRAINING_SECONDS_PER_LEVEL * max(1, to_level - cur)})
    state["upgrade_act_info"] = acts
    return "1"


def finish_upgrade(state, body):
    """Gun/finishUpgrade and Gun/quickUpgrade {"upgrade_slot"}: apply the training in that slot."""
    slot = int((body or {}).get("upgrade_slot") or 0)
    acts = state.get("upgrade_act_info") or []
    act = next((a for a in acts if int(a["upgrade_slot"]) == slot), None)
    if act is None:
        return "1"
    state["upgrade_act_info"] = [a for a in acts if a is not act]
    fid = str(act.get("fairy_with_user_id") or 0)
    if fid != "0":
        # fairy strategy skill training (Fairy/skillUpgrade)
        fairies = state.get("fairy_with_user_info") or {}
        f = fairies.get(fid) if isinstance(fairies, dict) else next((x for x in fairies if str(x["id"]) == fid), None)
        if f is not None:
            f["skill_lv"] = str(int(act.get("to_level") or int(f.get("skill_lv") or 1) + 1))
        return "1"
    sid = str(act.get("sangvis_with_user_id") or 0)
    if sid != "0":
        # Coalition skill training (Sangvis/skillUpgrade)
        s = next((x for x in state.get("sangvis_with_user_info") or [] if str(x["id"]) == sid), None)
        if s is not None:
            key = f"skill{int(act.get('skill') or 1)}"
            s[key] = str(int(act.get("to_level") or int(s.get(key) or 1) + 1))
        return "1"
    gun = _skill_owner(state, act)
    if gun is not None:
        key = f"skill{int(act.get('skill') or 1)}"
        gun[key] = str(int(act.get("to_level") or int(gun.get(key) or 1) + 1))
    return "1"


# Doll enhancement (FeedController).
#   Gun/eatGunIndex {"gun_with_user_id"} -> {"pow", "hit", "dodge", "rate"}: the doll's limits at its level
#   Gun/eatGun {"gun_with_user_id", "item9_num", "food": [gun_with_user_id]} -> the points gained
#       (FeedController$$RequestEatGunHandle adds them, removes the food and takes the capsules off itself)
#   A food doll is worth x / (x + M / 2) of each stat (GF.Battle.Gun$$get_feedPow: x its enhancement plus
#   base value, M from game_config gun_grow_M, "pow,rate,hit,dodge"), the sum times gun_grow_N, rounded down.
#   APPROXIMATION: a capsule (item 9) is one point of each stat; FeedValueCompute's share-out is not reproduced.
FEED_BASE = {"pow": 16, "rate": 45, "hit": 5, "dodge": 5}


def _feed_value(gun, stat, m):
    """What one food doll is worth (the save's stat field holds its enhancement points)."""
    row = guns().get(int(gun["gun_id"]), {})
    ratio = float(_type_info(row.get("type") or 1)[f"basic_attribute_{stat}"]) * float(row.get(f"ratio_{stat}") or 0)
    x = int(gun.get(stat) or 0) + math.ceil(FEED_BASE[stat] * ratio / 100)
    return x / (x + m / 2) if x + m else 0.0


def eat_gun_index(state, body):
    gun = next((g for g in state.get("gun_with_user_info") or []
                if str(g["id"]) == str((body or {}).get("gun_with_user_id"))), None)
    if gun is None:
        return None
    return gun_enhancement(int(gun["gun_id"]), int(gun.get("gun_level") or 1))


def eat_gun(state, body):
    from . import quests, squads
    body = body or {}
    guns_owned = state.get("gun_with_user_info") or []
    gun = next((g for g in guns_owned if str(g["id"]) == str(body.get("gun_with_user_id"))), None)
    food = {str(i) for i in body.get("food") or []} - {str((gun or {}).get("id"))}
    if gun is None:
        return None
    cfg = quests._config()
    grow_n = float(cfg.get("gun_grow_N") or 1.2)
    grow_m = dict(zip(("pow", "rate", "hit", "dodge"), (float(x) for x in cfg.get("gun_grow_M", "100,300,50,50").split(","))))
    eaten = [g for g in guns_owned if str(g["id"]) in food]
    capsules = squads._spend(state, "9", int(body.get("item9_num") or 0))
    limits = gun_enhancement(int(gun["gun_id"]), int(gun.get("gun_level") or 1))
    gained = {}
    for stat, m in grow_m.items():
        points = math.floor(grow_n * sum(_feed_value(g, stat, m) for g in eaten)) + capsules
        have = int(gun.get(stat) or 0)
        gained[stat] = max(0, min(points, limits[stat] - have))
        gun[stat] = str(have + gained[stat])
    state["gun_with_user_info"] = [g for g in guns_owned if str(g["id"]) not in food]
    return gained
