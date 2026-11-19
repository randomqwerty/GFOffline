"""Unit upgrades and looks: oaths, Neural Upgrade, calibration, Coalition and fairy upgrades,
skins, favourites and special effects.

Reply formats (from the client's handlers); every reply is "1" unless shown:
  Gun/contract           {"soul_bond_time"} (guarded)  {"gun_with_user_id"}  GF.Battle.Gun$$RequestContract
  Sangvis/contract       {"soul_bond_time"}            {"sangvis_with_user_id"}  RequestSangvisContract
  Gun/mindupdate         {"prize_info": {} (a reward Package), "equip_load": {} (unguarded; the
                         exclusive gear of the last step), optional adjutant_skin_item}
                         {"gun_with_user_id"}            RequestGunMindupdate
  Equip/adjust           {"<stat>": calibration 0-10000, ...} for each stat the equipment has
                         (ResearchEquipmentCalibrationController$$GetBounsTypeAfterDict); kept in
                         the equipment's last_adjust until Equip/resumeAdjust applies it
  Equip/resumeAdjust     {"equip_with_user_id"}: take the last calibration roll
  Fairy/adjust           {"passive_skill"}  {"fairy_with_user_id"}  RequestFairyCalibration; kept in
                         last_adjust until Fairy/adjustConfirm
  Fairy/modUpdate        {"fairy_with_user_id"}
  Sangvis/advance        {"status": true} (get_Bool)  {"sangvis_with_user_id"}
  Sangvis/resolution     {"sangvis_with_user_id", "sangvis_list": [duplicates used]}
  Sangvis/skillUpgrade   {"sangvis_with_user_id", "upgrade_slot", "skill", "if_quick", "to_level"},
                         finished by Sangvis/finishUpgrade {"upgrade_slot", "if_quick"}
  Gun/setCollect, Fairy/setCollect, Sangvis/setCollect  {"<kind>_with_user_id", "is_collect"}
  Dorm/changeSkin        {"gun_with_user_id", "skin_id"}    Fairy/changeSkin {"fairy_with_user_id", "skin_id"}
  Sangvis/changeSkin     {"sangvis_with_user_id", "skin"}   Sangvis/setSign {"sangvis_with_user_id", "sign"}
  Gun/onSpecialEffect    {"gun_with_user_id", "special_effect_id"}   Gun/offSpecialEffect {"gun_with_user_id"}
  Sangvis/setSpecialEffect {"sangvis_with_user_id", "special_effect"}
Costs (rings, cores, calibration tickets, Neural fragments) are deducted by the client.
"""
import json
import random
import time
from functools import lru_cache

from . import stc
from .inventory import TRAINING_SECONDS_PER_LEVEL, _remove_keyed
from .workshop import STAT_KEYS, _find, _talents, equips

MAX_MOD = 3
MAX_ADVANCE = 5
MAX_RESOLUTION = 4


@lru_cache(maxsize=1)
def _config():
    return {r["parameter_name"]: r["parameter_value"] for r in stc.catch("game_config_info")}


def _favor_cap(modded):
    key = "favor_mindupdate_toplimit" if modded else "favor_soulbind_toplimit"
    return str(int(_config().get(key) or (2000000 if modded else 1500000)))


def _unit(state, kind, body):
    return _find(state.get(f"{kind}_with_user_info"), (body or {}).get(f"{kind}_with_user_id") or 0)


# --- oaths and Neural Upgrade

def gun_contract(state, body):
    g = _unit(state, "gun", body)
    if g is None:
        return None
    now = int(time.time())
    g["soul_bond"], g["soul_bond_time"] = "1", str(now)
    g["max_favor"] = g["favor_toplimit"] = _favor_cap(int(g.get("if_modification") or 0) > 0)
    return {"soul_bond_time": now}


def sangvis_contract(state, body):
    s = _unit(state, "sangvis", body)
    if s is None:
        return None
    now = int(time.time())
    s["soul_bond"], s["soul_bond_time"] = "1", str(now)
    s["max_favor"] = s["favor_toplimit"] = _favor_cap(False)
    return {"soul_bond_time": now}


def mindupdate(state, body):
    g = _unit(state, "gun", body)
    if g is None or int(g.get("if_modification") or 0) >= MAX_MOD:
        return None
    g["if_modification"] = str(int(g.get("if_modification") or 0) + 1)
    if str(g.get("skill2") or "0") == "0":
        g["skill2"] = "1"       # the first Neural Upgrade step unlocks the second skill
    if g.get("soul_bond") == "1":
        g["max_favor"] = g["favor_toplimit"] = _favor_cap(True)
    return {"prize_info": {}, "equip_load": {}}


# --- calibration

def equip_adjust(state, body, rng=random):
    e = _unit(state, "equip", body)
    if e is None:
        return None
    row = equips().get(int(e["equip_id"]), {})
    roll = {k: rng.randint(0, 10000) for k in STAT_KEYS if str(row.get(k) or "").strip()}
    e["last_adjust"] = json.dumps(roll, separators=(",", ":"))
    e["adjust_count"] = str(int(e.get("adjust_count") or 0) + 1)
    return roll


def equip_resume_adjust(state, body):
    e = _unit(state, "equip", body)
    if e is None:
        return None
    try:
        roll = json.loads(e.get("last_adjust") or "0")
    except ValueError:
        roll = None
    if isinstance(roll, dict):
        for k, v in roll.items():
            if k in STAT_KEYS:
                e[k] = str(int(v))
    return "1"


def fairy_adjust(state, body, rng=random):
    f = _unit(state, "fairy", body)
    if f is None:
        return None
    talent = rng.choice(_talents())
    f["last_adjust"] = str(talent)
    f["adjust_count"] = str(int(f.get("adjust_count") or 0) + 1)
    return {"passive_skill": talent}


def fairy_adjust_confirm(state, body):
    f = _unit(state, "fairy", body)
    if f is None or str(f.get("last_adjust") or "0") == "0":
        return None
    f["passive_skill"], f["last_adjust"] = f["last_adjust"], "0"
    seen = [x for x in str(f.get("passive_skill_collect") or "").split(",") if x]
    if f["passive_skill"] not in seen:
        f["passive_skill_collect"] = ",".join(seen + [f["passive_skill"]])
    return "1"


def fairy_mod(state, body):
    f = _unit(state, "fairy", body)
    if f is None or int(f.get("mod") or 0) >= MAX_MOD:
        return None
    f["mod"] = str(int(f.get("mod") or 0) + 1)
    return "1"


# --- Coalition upgrades

def sangvis_advance(state, body):
    s = _unit(state, "sangvis", body)
    if s is None:
        return None
    s["sangvis_advance"] = str(min(MAX_ADVANCE, int(s.get("sangvis_advance") or 1) + 1))
    return {"status": True}


def sangvis_resolution(state, body):
    body = body or {}
    s = _unit(state, "sangvis", body)
    used = [str(i) for i in body.get("sangvis_list") or [] if str(i) != str((s or {}).get("id"))]
    if s is None:
        return None
    level = str(min(MAX_RESOLUTION, int(s.get("sangvis_resolution") or 0) + max(1, len(used))))
    s["sangvis_resolution"] = s["sangvis_resolution_level"] = level
    state["sangvis_with_user_info"] = _remove_keyed(state.get("sangvis_with_user_info") or [], used)
    return "1"


def sangvis_skill_upgrade(state, body):
    body = body or {}
    s = _unit(state, "sangvis", body)
    if s is None:
        return None
    skill, to_level = int(body.get("skill") or 1), int(body.get("to_level") or 0)
    if int(body.get("if_quick") or 0):
        s[f"skill{skill}"] = str(to_level)
        return "1"
    slot = int(body.get("upgrade_slot") or 1)
    acts = [a for a in state.get("upgrade_act_info") or [] if int(a["upgrade_slot"]) != slot]
    cur = int(s.get(f"skill{skill}") or 1)
    acts.append({"upgrade_slot": slot, "gun_with_user_id": 0, "sangvis_with_user_id": str(s["id"]),
                 "fairy_with_user_id": 0, "skill": skill, "to_level": to_level,
                 "end_time": int(time.time()) + TRAINING_SECONDS_PER_LEVEL * max(1, to_level - cur)})
    state["upgrade_act_info"] = acts
    return "1"


# --- looks and favourites

def set_collect(state, body):
    body = body or {}
    for kind in ("gun", "fairy", "sangvis"):
        unit = _unit(state, kind, body)
        if unit is not None:
            unit["is_collect"] = str(int(body.get("is_collect") or 0))
            return "1"
    return None


def _set_field(kind, field, key):
    def change(state, body):
        unit = _unit(state, kind, body)
        if unit is None or key not in (body or {}):
            return None
        unit[field] = str(body[key])
        return "1"
    return change


gun_skin = _set_field("gun", "skin", "skin_id")
fairy_skin = _set_field("fairy", "skin", "skin_id")
sangvis_skin = _set_field("sangvis", "skin", "skin")
sangvis_sign = _set_field("sangvis", "sign", "sign")
gun_effect_on = _set_field("gun", "special_effect", "special_effect_id")
sangvis_effect = _set_field("sangvis", "special_effect", "special_effect")


def gun_effect_off(state, body):
    g = _unit(state, "gun", body)
    if g is None:
        return None
    g["special_effect"] = "0"
    return "1"


# --- chips and memoirs

def squad_chip_lock(state, body):
    """Chip/changeLock {"lock_chips": [ids], "unlock_chips": [ids]} on chip_with_user_info."""
    body = body or {}
    chips = state.get("chip_with_user_info") or {}
    rows = chips.values() if isinstance(chips, dict) else chips
    lock = {str(i) for i in body.get("lock_chips") or []}
    unlock = {str(i) for i in body.get("unlock_chips") or []}
    for row in rows:
        cid = str(row.get("id") or row.get("chip_id"))
        if cid in lock:
            row["is_locked"] = "1"
        elif cid in unlock:
            row["is_locked"] = "0"
    return "1"


def sangvis_equip_chip(state, body):
    """Sangvis/equipChip {"sangvis_with_user_id", "chip_id", "chip_slot", "if_outfit"}: the save keeps
    it in sangvis_chip_with_user_info (sangvis_with_user_id, chip_slot) and the unit's chip<slot>."""
    body = body or {}
    s = _unit(state, "sangvis", body)
    slot, chip = int(body.get("chip_slot") or 0), str(body.get("chip_id") or 0)
    if s is None or f"chip{slot}" not in s:
        return None
    chips = state.setdefault("sangvis_chip_with_user_info", [])
    for row in chips:
        if row.get("sangvis_with_user_id") == str(s["id"]) and str(row.get("chip_slot")) == str(slot):
            row["sangvis_with_user_id"], row["chip_slot"] = "0", "0"
    s[f"chip{slot}"] = "0"
    if int(body.get("if_outfit") or 0):
        row = next((r for r in chips if str(r["chip_id"]) == chip), None)
        if row is None:
            return None
        if row.get("sangvis_with_user_id") not in (None, "0"):
            other = _find(state.get("sangvis_with_user_info"), row["sangvis_with_user_id"])
            if other is not None and other.get(f"chip{row['chip_slot']}") == chip:
                other[f"chip{row['chip_slot']}"] = "0"
        row["sangvis_with_user_id"], row["chip_slot"] = str(s["id"]), str(slot)
        s[f"chip{slot}"] = chip
    return "1"


def memoir_list(state, body):
    """Gun/memoirList -> [{"gun_id", "stage_id"}] (the save's gun_memoir_list)."""
    return state.get("gun_memoir_list") or []


def unlock_memoir(state, body):
    """Gun/memoir {"gun_id", "stage_id"}: a Neural Upgrade story read. The first read pays its
    mindupdate_story_info prize (Memory Fragments, item 45: 50/50/100/100 for stages 1-4); the reply is
    that package (RequestUnlockMemoir reads it with Package.GetPackage), empty after."""
    from . import quests
    body = body or {}
    gid, stage = str(body.get("gun_id") or 0), str(body.get("stage_id") or 0)
    if gid == "0":
        return None
    rows = state.setdefault("gun_memoir_list", [])
    if any(str(r["gun_id"]) == gid and str(r["stage_id"]) == stage for r in rows):
        return {}
    rows.append({"gun_id": gid, "stage_id": stage})
    story = next((r for r in stc.catch("mindupdate_story_info") if str(r["gun_id"]) == gid and str(r["stage_id"]) == stage), None)
    prize = quests.prizes().get(int((story or {}).get("prize_id") or 0))
    return quests.grant(state, quests._reward(prize)) if prize else {}


# --- HOC (squads) outside missions
#
# Squad/upSkill {"squad_with_user_id", "skill_slot", "skill", "if_quick", "to_level"} -> {"squad_skill_slot"}
# (RequestSquadUpSkill); a timed one is kept in squad_skill_act_info as {"squad_with_user_id",
# "squad_skill_slot", "end_time", "skill"} (SquadSkillAction$$.ctor) until Squad/finishSkill or
# Squad/quickSkill {"skill_slot"} ("1"). HOC repair (Squad/fixSquads, fixFinish, quickFix) only
# answers "1": HOC damage is not saved.

def _squad(state, sid):
    squads = state.get("squad_with_user_info") or {}
    if isinstance(squads, dict):
        return squads.get(str(sid))
    return next((q for q in squads if str(q["id"]) == str(sid)), None)


def squad_up_skill(state, body):
    from .inventory import TRAINING_SECONDS_PER_LEVEL
    body = body or {}
    q = _squad(state, body.get("squad_with_user_id") or 0)
    if q is None:
        return None
    skill, slot = int(body.get("skill") or 1), int(body.get("skill_slot") or 1)
    key = f"skill{skill}"
    to_level = int(body.get("to_level") or int(q.get(key) or 1) + 1)
    if int(body.get("if_quick") or 0):
        q[key] = str(to_level)
        return {"squad_skill_slot": slot}
    acts = [a for a in state.get("squad_skill_act_info") or [] if int(a["squad_skill_slot"]) != slot]
    acts.append({"squad_with_user_id": str(q["id"]), "squad_skill_slot": slot, "skill": skill, "to_level": to_level,
                 "end_time": int(time.time()) + TRAINING_SECONDS_PER_LEVEL * max(1, to_level - int(q.get(key) or 1))})
    state["squad_skill_act_info"] = acts
    return {"squad_skill_slot": slot}


def squad_finish_skill(state, body):
    slot = int((body or {}).get("skill_slot") or 0)
    acts = state.get("squad_skill_act_info") or []
    for a in [a for a in acts if int(a["squad_skill_slot"]) == slot]:
        acts.remove(a)
        q = _squad(state, a["squad_with_user_id"])
        if q is not None:
            key = f"skill{int(a.get('skill') or 1)}"
            q[key] = str(int(a.get("to_level") or int(q.get(key) or 1) + 1))
    return "1"


def sangvis_collect_list(state, body):
    """Sangvis/collectList -> {"sangvis_collect_info": ...} (the save's sangvis_capture_collect_info)."""
    return {"sangvis_collect_info": state.get("sangvis_capture_collect_info") or []}


def edit_soul_bond_time(state, body):
    """Gun/edit_soul_bond_time {"gun_with_user_id", "soul_bond_time"} -> {"soul_bond_time"}."""
    g = _unit(state, "gun", body)
    if g is None or g.get("soul_bond") != "1":
        return None
    g["soul_bond_time"] = str(int((body or {}).get("soul_bond_time") or g.get("soul_bond_time") or 0))
    return {"soul_bond_time": int(g["soul_bond_time"])}


# --- Armor (vehicles) outside missions
# Vehicle/changeComponentLock {"lock", "unlock"} on vehicle_component_with_user_info; Vehicle/unlockTechTree
# {"node_id"} -> {} adds the node to the vehicle's unlocked_nodes (node ids are vehicle_id * 10000 + n).
# Vehicle repair (Vehicle/fix -> {}, fixFinish "1") changes nothing: vehicle damage is not saved.

def component_lock(state, body):
    from .formation import _set_locks
    return _set_locks(state.get("vehicle_component_with_user_info"), body)


def unlock_tech_node(state, body):
    node = int((body or {}).get("node_id") or 0)
    vehicles = state.get("vehicle_with_user_info") or {}
    rows = vehicles.values() if isinstance(vehicles, dict) else vehicles
    v = next((r for r in rows if int(r.get("vehicle_id") or 0) == node // 10000), None)
    if v is None:
        return None
    nodes = [x for x in str(v.get("unlocked_nodes") or "").split(",") if x]
    if str(node) not in nodes:
        v["unlocked_nodes"] = ",".join(nodes + [str(node)])
    return {}


#   Vehicle/unlock {"vehicle_id"} -> {"vehicle_info": record} (RequestVehicleUnlock); the record has
#     the save's vehicle_with_user_info fields, starting with full energy (stc vehicle.energy_max).
#   Vehicle/upgradeComponent {"component_wu_id", "item_list": {"<item>": n}, "component_list": [ids]}
#     -> the upgraded component record (VehicleComponent$$UpdateInfoAfterStrength reads it): the
#     listed components and items are used up.
# APPROXIMATION: component exp values and level steps are server-side: COMPONENT_FOOD_EXP per rank
# of a consumed component, ITEM_EXP per item, and a level every COMPONENT_LEVEL_EXP up to 10
# (every level-10 component in a real save has 33600 exp).
COMPONENT_FOOD_EXP, ITEM_EXP, COMPONENT_LEVEL_EXP, COMPONENT_MAX_LEVEL = 400, 1000, 3360, 10


def unlock_vehicle(state, body):
    vid = int((body or {}).get("vehicle_id") or 0)
    row = next((r for r in stc.table("vehicle") if r["id"] == vid), None)
    vehicles = state.setdefault("vehicle_with_user_info", {})
    have = vehicles.values() if isinstance(vehicles, dict) else vehicles
    if row is None or any(int(v["vehicle_id"]) == vid for v in have):
        return None
    new_id = str(max((int(v["id"]) for v in have), default=0) + 1)
    rec = {"id": new_id, "user_id": str(state["user_info"].get("user_id", "")), "vehicle_id": str(vid), "exp": "0",
           "life": str(int(row.get("hp") or 0)), "ammo": "0", "mre": "0", "energy": str(int(row.get("energy_max") or 0)),
           "energy_bak": "0", "unlocked_nodes": "", "component": "", "common_component": "", "crew": "", "skin": "0",
           "locked_slots": ""}
    for k in ("basic_effect", "hp", "armor", "dodge", "heavy_damage", "light_damage", "reload", "atk_speed", "precision",
              "hit", "crit", "crit_dmg", "H_armor_piercing", "L_armor_piercing", "def_break"):
        rec[k] = str(int(row.get(k) or 0)) if str(row.get(k) or "0").lstrip("-").isdigit() else "0"
    if isinstance(vehicles, dict):
        vehicles[str(vid)] = rec
    else:
        vehicles.append(rec)
    return {"vehicle_info": rec}


def upgrade_component(state, body):
    body = body or {}
    comps = state.get("vehicle_component_with_user_info") or {}
    target = _find(comps, body.get("component_wu_id") or 0)
    if target is None:
        return None
    ranks = {int(r["id"]): int(r.get("rank") or 1) for r in stc.table("vehicle_component")}
    food = [str(i) for i in body.get("component_list") or [] if str(i) != str(target["id"])]
    gained = sum(COMPONENT_FOOD_EXP * ranks.get(int(_find(comps, f)["component_id"]), 1) for f in food if _find(comps, f))
    state["vehicle_component_with_user_info"] = _remove_keyed(comps, food)
    for item_id, n in (body.get("item_list") or {}).items():
        row = next((i for i in state.get("item_with_user_info", []) if str(i["item_id"]) == str(item_id)), None)
        used = min(int(n or 0), int(row["number"])) if row else 0
        if row is not None:
            row["number"] = str(int(row["number"]) - used)
        gained += ITEM_EXP * used
    cap = COMPONENT_LEVEL_EXP * COMPONENT_MAX_LEVEL
    target["exp"] = str(min(cap, int(target.get("exp") or 0) + gained))
    target["level"] = str(min(COMPONENT_MAX_LEVEL, int(target["exp"]) // COMPONENT_LEVEL_EXP))
    return target


# --- fairy mod exp
#   Fairy/modExpUpdate {"fairy_with_user_id", "food": [fairy ids], "item_num"} -> {"mod_exp"} (the new
#   total; RequestFairyModExpUpdateController sets the fairy's modExp and takes item_num of the
#   game_config fairy_mindupdate_expitem item). Each fodder fairy gives its stc fairy.mod_exp, each
#   item the exp in fairy_mindupdate_expitem "<item>-<exp>".

def fairy_mod_exp(state, body):
    from . import squads
    body = body or {}
    f = _unit(state, "fairy", body)
    if f is None:
        return None
    rows = {int(r["id"]): r for r in stc.table("fairy")}
    item, _, per = next((r["parameter_value"] for r in stc.catch("game_config_info")
                         if r["parameter_name"] == "fairy_mindupdate_expitem"), "55-500").partition("-")
    food = [str(i) for i in body.get("food") or [] if str(i) != str(f["id"])]
    gained = int(per or 0) * squads._spend(state, item, int(body.get("item_num") or 0))
    for fid in food:
        eaten = _find(state.get("fairy_with_user_info"), fid)
        if eaten is not None:
            gained += int(rows.get(int(eaten["fairy_id"]), {}).get("mod_exp") or 0)
    state["fairy_with_user_info"] = _remove_keyed(state.get("fairy_with_user_info") or [], food)
    f["mod_exp"] = str(int(f.get("mod_exp") or 0) + gained)
    return {"mod_exp": int(f["mod_exp"])}


# --- Coalition chip research (stc sangvis_chip: dev_battery_num, dev_time seconds). A chip is a
# sangvis_chip_with_user_info row; it is still being researched while its dev_time (the end time)
# is in the future, and the client finishes it by itself when that passes.
#   Sangvis/developChip {"chip_id", "if_quick", "select_item": {item: n}} "1"
#       (RequestSangvisChipStartResearchFinish: the client takes the batteries and the selected items)
#   Sangvis/finishDevelop {"chip_id"} -> {"cost_gem"} (SangvisChipResearchAction quick finish:
#       ceil(seconds left / game_config sangvis_accelerate_chip_dev) gems)

def sangvis_develop_chip(state, body, now=None):
    from . import squads
    body, now = body or {}, int(now or time.time())
    row = next((r for r in stc.table("sangvis_chip") if str(r["id"]) == str(body.get("chip_id"))), None)
    chips = state.setdefault("sangvis_chip_with_user_info", [])
    if row is None or any(str(c["chip_id"]) == str(row["id"]) for c in chips):
        return None
    squads._spend(state, "506", int(row.get("dev_battery_num") or 0))
    for item, n in (body.get("select_item") or {}).items():
        squads._spend(state, item, int(n or 0))
    end = now if body.get("if_quick") else now + int(row.get("dev_time") or 0)
    chips.append({"user_id": str(state["user_info"].get("user_id", "")), "chip_id": str(row["id"]),
                  "dev_time": str(end), "sangvis_with_user_id": "0", "chip_slot": "0"})
    return "1"


def sangvis_finish_chip(state, body, now=None):
    now = int(now or time.time())
    chip = next((c for c in state.get("sangvis_chip_with_user_info") or []
                 if str(c["chip_id"]) == str((body or {}).get("chip_id"))), None)
    if chip is None:
        return None
    rate = next((int(r["parameter_value"]) for r in stc.catch("game_config_info")
                 if r["parameter_name"] == "sangvis_accelerate_chip_dev"), 333)
    gems = -(-max(0, int(chip["dev_time"]) - now) // max(1, rate))
    ui = state["user_info"]
    if int(ui.get("gem") or 0) < gems:
        return None
    ui["gem"] = str(int(ui["gem"]) - gems)
    chip["dev_time"] = str(min(int(chip["dev_time"]), now))
    return {"cost_gem": gems}


# --- Coalition transfer
#   Sangvis/trans {"sangvis_with_user_id_from", "sangvis_with_user_id_to", "if_trans_special"} "1"
#   (RequestSangvisTransfer swaps the two units): if_trans_special swaps only the special-unit mark;
#   otherwise level, exp, resolution, HP, advance, affection and the advance skill swap, and skill3
#   too when the unit is stc sangvis type 2. SIMPLIFIED: the transfer's core cost (counted by the
#   client, not sent) is not taken.
TRANS_FIELDS = ("sangvis_level", "sangvis_exp", "sangvis_resolution", "sangvis_resolution_level", "life",
                "sangvis_advance", "favor", "skill_advance")
SANGVIS_TYPE_SKILL3 = 2


def sangvis_transfer(state, body):
    body = body or {}
    a = _find(state.get("sangvis_with_user_info"), body.get("sangvis_with_user_id_from") or 0)
    b = _find(state.get("sangvis_with_user_info"), body.get("sangvis_with_user_id_to") or 0)
    if a is None or b is None or a is b:
        return None
    fields = ["sangvis_is_special"] if int(body.get("if_trans_special") or 0) else list(TRANS_FIELDS)
    if fields != ["sangvis_is_special"]:
        kind = {int(r["id"]): int(r.get("type") or 0) for r in stc.table("sangvis")}.get(int(a["sangvis_id"]))
        if kind == SANGVIS_TYPE_SKILL3:
            fields.append("skill3")
    for f in fields:
        a[f], b[f] = b.get(f, "0"), a.get(f, "0")
    return "1"


# Vehicle/taskInfo {} -> {"vehicle_unlock_task_info": {task_type: progress}} (RequestVehicleUnlockTask): a number
#   for every task of that type, or "<condition>-<progress>,..." for tasks with a condition.
#   APPROXIMATION: the save has no kill count, so i_kill_enemy_all counts as done; mission_medal_all
#   counts each map's medal1, medal2 and medal4.
def vehicle_task_info(state, body):
    from . import quests
    records = state.get("mission_with_user_info") or []
    guide = str((state.get("guide_info") or {}).get("guide") or "")
    guns_owned = quests._rows(state, "gun_with_user_info")
    squads_owned = quests._rows(state, "squad_with_user_info")
    info = {"commander_level": int(state["user_info"].get("lv") or 0),
            "mission_medal_all": sum(1 for r in records for k in ("medal1", "medal2", "medal4") if str(r.get(k)) == "1"),
            "mission_bestrank5": sum(1 for r in records if str(r.get("bestrank")) == "5")}
    conds = {}
    for row in stc.table("vehicle_unlock_task"):
        kind, cond = row["task_type"], str(row["condition"])
        if kind == "i_gun_level":
            n = sum(1 for g in guns_owned if int(g.get("gun_level") or 0) >= int(cond))
        elif kind == "i_squad_level":
            n = sum(1 for q in squads_owned if int(q.get("squad_level") or 0) >= int(cond))
        elif kind == "c_guide_complete":
            n = int(cond in guide)
        elif kind == "i_kill_enemy_all":
            n = int(row["count"])
        else:
            continue
        conds.setdefault(kind, []).append(f"{cond}-{n}")
    info.update({k: ",".join(v) for k, v in conds.items()})
    return {"vehicle_unlock_task_info": info}
