"""Simplified "designs" for Mod Studio and their conversion to and from game rows.

A design holds only what a modder decides (name, class, final stats, skills, ...); everything
else comes from class defaults. Stats are entered as final values and solved back to the
tables' ratio fields with the client's own formulas (doc/stc-guide/01 and 10):

  T-Doll, level 100, max enhancement:  base = ceil(B x T x r/100) + ceil(99 x g x T x r x eat/10000)
  Coalition, level 100, 5 stars, max size and resolution:
      stat = ceil(L x r x eat x S x A x T / 1e8 [/ formation]) with L = 139, A = 120, S = 110
  Enemies: stats are written for level 100 (enemy_character_type.level = 100)

`w` is the studio module (world tables, text, free ids).
"""
import math
import re
from collections import Counter

# ---------------------------------------------------------------------------- labels

GUN_TYPES = {1: "Handgun (HG)", 2: "Submachine gun (SMG)", 3: "Rifle (RF)", 4: "Assault rifle (AR)",
             5: "Machine gun (MG)", 6: "Shotgun (SG)"}
TILE_STATS = {1: "Firepower", 2: "Rate of fire", 3: "Accuracy", 4: "Evasion", 5: "Critical rate",
              6: "Skill cooldown", 7: "Armor penetration", 8: "Armor"}
EQUIP_CATEGORIES = {1: "Accessory", 2: "Magazine / ammo", 3: "Doll gear"}
FACTIONS = {1: "Sangvis Ferri", 2: "KCCO", 3: "Paradeus / other", 0: "Other"}
SANGVIS_CLASSES = {1: "Boss", 2: "Elite", 3: "Normal"}
ENEMY_TYPES = {1: "Boss", 2: "Machine", 3: "Human", 4: "Armored machine", 5: "Armored human"}
TEAM_AI = {  # words -> (ai, if_stay); parameter meaning in TEAM_AI_PARAM
    "map_default": (0, 0), "standby": (1, 0), "garrison": (0, 1), "patrol": (101, 0),
    "alert": (102, 0), "expand": (103, 0), "offline": (99, 0),
}
TEAM_AI_LABELS = {
    "map_default": "Use the map's default AI", "standby": "Standby: holds position",
    "garrison": "Garrison: never moves", "patrol": "Patrol: walks a route, attacks next to it",
    "alert": "Alert: waits, then chases echelons in range", "expand": "Expand: pushes into Griffin nodes",
    "offline": "Offline: does nothing",
}
TEAM_AI_PARAM = {"patrol": "Route (node ids in order)", "alert": "Detection range (nodes)"}
TEAM_TAGS = {1: "Hard to defeat", 2: "Can change position", 3: "Full force"}
MAP_KINDS = {0: "Normal", 1: "Emergency", 3: "Night"}
MAP_AI = {1: "Standby", 2: "Random", 3: "Attack (toward the Command Post)", 4: "Random (another kind)", -1: "Night (moves hidden)"}
SANGVIS_SKILL2_KINDS = {1: "Battle skill", 2: "Map skill", 3: "Support skill"}

L_SANGVIS, A_SANGVIS, S_SANGVIS = 139, 120, 110      # level 100 + 39, advancement 5, size 5


def _ceil(x):
    # float noise (0.6 x 110 = 66.00000000000001) must not round up
    return math.ceil(round(x, 6))


def _ints(v):
    return [int(x) for x in re.findall(r"-?\d+", str(v or ""))]


# ---------------------------------------------------------------------------- T-Dolls

def gun_type_info(w):
    return {int(r["id"]): {k: float(v) for k, v in r.items() if k.startswith("basic_attribute_")}
            for r in w.base().catchdata()["gun_type_info"]}


def doll_stats(w, row, level=100, links=5):
    """Final stats at level 100 with max enhancement (before affection and equipment)."""
    T = gun_type_info(w)[int(row["type"])]
    r = lambda f: float(row.get(f) or 0)
    e = r("eat_ratio")
    lv = level - 1
    grow = lambda g, t, ratio: _ceil(lv * g * t * ratio * e / 10000)
    out = {
        "hp": _ceil((55 + lv * 0.555) * T["basic_attribute_life"] * r("ratio_life") / 100) * links,
        "firepower": _ceil(16 * T["basic_attribute_pow"] * r("ratio_pow") / 100) + grow(0.242, T["basic_attribute_pow"], r("ratio_pow")),
        "rate": _ceil(45 * T["basic_attribute_rate"] * r("ratio_rate") / 100) + grow(0.181, T["basic_attribute_rate"], r("ratio_rate")),
        "accuracy": _ceil(5 * T["basic_attribute_hit"] * r("ratio_hit") / 100) + grow(0.303, T["basic_attribute_hit"], r("ratio_hit")),
        "evasion": _ceil(5 * T["basic_attribute_dodge"] * r("ratio_dodge") / 100) + grow(0.303, T["basic_attribute_dodge"], r("ratio_dodge")),
        "armor": _ceil((2 + lv * 0.161) * T["basic_attribute_armor"] * r("ratio_armor") / 100),
        "speed": _ceil(10 * T["basic_attribute_speed"] * r("ratio_speed") / 100),
        "crit": int(row.get("crit") or 0), "armor_pen": int(row.get("armor_piercing") or 0),
        "magazine": int(row.get("special") or 0), "rof_cap": int(row.get("atk_speed_max") or 0),
    }
    out["rate"] = min(out["rate"], out["rof_cap"] or out["rate"])
    return out


def doll_enhancement(w, row, level=100):
    """Max enhancement points (the save's pow/rate/hit/dodge fields) at this level."""
    T = gun_type_info(w)[int(row["type"])]
    e = float(row.get("eat_ratio") or 0)
    lv = level - 1
    g = lambda grow, t, f: _ceil(lv * grow * T[t] * float(row.get(f) or 0) * e / 10000)
    return {"pow": g(0.242, "basic_attribute_pow", "ratio_pow"), "rate": g(0.181, "basic_attribute_rate", "ratio_rate"),
            "hit": g(0.303, "basic_attribute_hit", "ratio_hit"), "dodge": g(0.303, "basic_attribute_dodge", "ratio_dodge")}


def _best_ratio(fn, target, lo=1, hi=3000):
    """Integer ratio whose stat is closest to target (exact if possible; smallest ratio on ties)."""
    best = None
    for r in range(lo, hi + 1):
        d = abs(fn(r) - target)
        if best is None or d < best[0]:
            best = (d, r)
            if d == 0:
                break
    return best[1], best[0]


def solve_doll(w, gun_type, stats, eat_hint=110):
    """Ratios (and eat_ratio) that reproduce the requested final stats as closely as possible."""
    T = gun_type_info(w)[int(gun_type)]
    lv = 99
    out = {}
    hp_link = max(1, int(stats.get("hp") or 0)) / 5
    out["ratio_life"], _ = _best_ratio(lambda r: _ceil((55 + lv * 0.555) * T["basic_attribute_life"] * r / 100), hp_link)
    grown = [("ratio_pow", "firepower", 16, 0.242, "basic_attribute_pow"), ("ratio_rate", "rate", 45, 0.181, "basic_attribute_rate"),
             ("ratio_hit", "accuracy", 5, 0.303, "basic_attribute_hit"), ("ratio_dodge", "evasion", 5, 0.303, "basic_attribute_dodge")]
    best = None
    for e in sorted(range(60, 201), key=lambda x: abs(x - eat_hint)):
        sol, miss = {}, 0
        for field, key, b, g, t in grown:
            target = int(stats.get(key) or 0)
            fn = lambda r, b=b, g=g, t=t, e=e: _ceil(b * T[t] * r / 100) + _ceil(lv * g * T[t] * r * e / 10000)
            sol[field], d = _best_ratio(fn, target) if target > 0 else (0, 0)
            miss += d
        if best is None or miss < best[0]:
            best = (miss, e, sol)
            if miss == 0:
                break
    out["eat_ratio"] = best[1]
    out.update(best[2])
    if T["basic_attribute_armor"] > 0 and int(stats.get("armor") or 0) > 0:
        out["ratio_armor"], _ = _best_ratio(lambda r: _ceil((2 + lv * 0.161) * T["basic_attribute_armor"] * r / 100), int(stats["armor"]))
    else:
        out["ratio_armor"] = 0
    out["ratio_speed"], _ = _best_ratio(lambda r: _ceil(10 * T["basic_attribute_speed"] * r / 100), int(stats.get("speed") or 10))
    out["crit"] = int(stats.get("crit") or 0)
    out["armor_piercing"] = int(stats.get("armor_pen") or 0)
    out["special"] = int(stats.get("magazine") or 0) if int(gun_type) in (5, 6) else 0
    return out


def class_defaults(w, gun_type):
    """Most common values among the dolls of a class, and a typical doll of that class to copy from."""
    rows = [g for g in w.world_table("gun") if g["type"] == int(gun_type) and g["id"] < 1000]
    common = {}
    for f in ("normal_attack", "atk_speed_max", "special", "crit", "armor_piercing", "baseammo", "basemre",
              "ammo_add_withnumber", "mre_add_withnumber", "type_equip1", "type_equip2", "type_equip3",
              "effect_grid_center", "eat_ratio", "ratio_speed", "develop_duration", "retiremp", "retireammo",
              "retiremre", "retirepart", "ai"):
        common[f] = Counter(g[f] for g in rows).most_common(1)[0][0]
    anchor = next((g for g in rows if all(g[f] == common[f] for f in ("normal_attack", "type_equip1", "type_equip2",
                                                                      "type_equip3"))), rows[0])
    return common, anchor["id"]


def parse_equip(value):
    m = re.match(r"^\s*(\d+)\s*;\s*([\d,\s]*)$", str(value or ""))
    if not m:
        return {"category": 0, "types": []}
    return {"category": int(m.group(1)), "types": [int(x) for x in m.group(2).split(",") if x.strip()]}


def doll_design(w, row, text, grant=None):
    """Design view of a gun row."""
    tile_buffs = []
    for part in str(row.get("effect_grid_effect") or "").split(";"):
        p = _ints(part)
        if len(p) >= 2:
            tile_buffs.append({"stat": p[0], "value": p[1]})
    targets = [t for t in _ints(row.get("effect_guntype")) if t]
    return {
        "id": row["id"], "name": w.text_of(text, row.get("name")) or row.get("en_name", ""),
        "intro": w.text_of(text, row.get("en_introduce")), "credits": w.text_of(text, row.get("extra")),
        "type": row["type"], "rarity": row.get("rank_display") or row["rank"], "model": row["code"],
        "stats": doll_stats(w, row),
        "tile": {"center": row.get("effect_grid_center") or 13, "cells": _ints(row.get("effect_grid_pos")),
                 "targets": targets, "buffs": tile_buffs},
        "equipment": [parse_equip(row.get(f"type_equip{i}")) for i in (1, 2, 3)],
        "skills": {"normal_attack": row.get("normal_attack") or 0, "skill1": row.get("skill1") or 0,
                   "skill2": row.get("skill2") or 0, "passive": _ints(row.get("passive_skill")),
                   "dynamic": _ints(row.get("dynamic_passive_skill"))},
        "give": grant is not None,
    }


def doll_row(w, design, base_row):
    """A full gun row from a design; fields the design does not cover come from base_row."""
    row = dict(base_row)
    t = int(design["type"])
    common, _ = class_defaults(w, t)
    if int(base_row.get("type") or 0) != t:
        # class changed: take the class's typical values for everything class-specific
        row.update(common)
    row.update(solve_doll(w, t, design["stats"], int(row.get("eat_ratio") or common["eat_ratio"])))
    row.update({"id": int(design["id"]), "type": t, "rank": min(int(design["rarity"]), 6),
                "rank_display": int(design["rarity"]), "code": design.get("model") or row["code"],
                "en_name": design.get("name") or row.get("en_name", "")})
    if int(design["stats"].get("rof_cap") or 0):
        row["atk_speed_max"] = int(design["stats"]["rof_cap"])
    tile = design.get("tile") or {}
    row["effect_grid_center"] = int(tile.get("center") or 13)
    row["effect_grid_pos"] = ",".join(str(c) for c in sorted(set(tile.get("cells") or [])))
    row["effect_guntype"] = ",".join(str(x) for x in sorted(set(tile.get("targets") or []))) or "0"
    row["effect_grid_effect"] = ";".join(f"{int(b['stat'])},{int(b['value'])}" for b in tile.get("buffs") or []
                                         if int(b.get("stat") or 0) and int(b.get("value") or 0))
    for i, slot in enumerate(design.get("equipment") or [], 1):
        if i <= 3:
            types = ",".join(str(x) for x in slot.get("types") or [])
            row[f"type_equip{i}"] = f"{int(slot.get('category') or 0)};{types}" if slot.get("category") else ""
    sk = design.get("skills") or {}
    row["normal_attack"] = int(sk.get("normal_attack") or common["normal_attack"])
    row["skill1"] = int(sk.get("skill1") or 0)
    row["skill2"] = int(sk.get("skill2") or 0)
    row["passive_skill"] = ",".join(str(x) for x in sk.get("passive") or [])
    row["dynamic_passive_skill"] = ",".join(str(x) for x in sk.get("dynamic") or [])
    row["mindupdate_consume"] = ""          # no Neural Upgrade
    return row


# ---------------------------------------------------------------------------- Coalition

def sangvis_tables(w):
    return ({int(r["id"]): r for r in w.world_table("sangvis_type")},
            {int(r["lv"]): r for r in w.world_table("sangvis_advance")})


def sangvis_stats(w, row, resolution=None):
    """Final stats at level 100, 5 stars, size 5 and max resolution. resolution = the unit's
    level-4 resolution row (flat bonuses, model count); None looks it up in the world."""
    types, adv = sangvis_tables(w)
    T, A = types[int(row["type"])], adv[5]
    F = max(1, int(row.get("formation") or 1))
    if resolution is None:
        rows = [r for r in w.world_table("sangvis_resolution") if r["group_id"] == row.get("resolution")]
        resolution = max(rows, key=lambda r: r["lv"]) if rows else {}
    R = lambda f: float(resolution.get(f) or 0)
    models = int(resolution.get("resolution_number") or (5 if F > 1 else 1))
    e = float(row.get("eat_ratio") or 0)
    k = lambda f, tf, af, per_model=True: L_SANGVIS * float(row.get(f) or 0) * e * S_SANGVIS * float(A[af]) * float(T[tf]) / 1e8 / (F if per_model else 1)
    return {
        "hp": _ceil((R("resolution_hp") + k("ratio_hp", "basic_hp", "advance_hp")) * models),
        "damage": _ceil(k("ratio_pow", "basic_pow", "advance_pow") + R("resolution_pow")),
        "rate": _ceil(k("ratio_rate", "basic_rate", "advance_rate", False) + R("resolution_rate")),
        "accuracy": _ceil(k("ratio_hit", "basic_hit", "advance_hit", False) + R("resolution_hit")),
        "evasion": _ceil(k("ratio_dodge", "basic_dodge", "advance_dodge", False) + R("resolution_dodge")),
        "armor": _ceil(k("ratio_armor", "basic_armor", "advance_armor", False) + R("resolution_armor")),
        "crit": int(row.get("crit") or 0) + int(R("resolution_crit")), "crit_dmg": int(row.get("crit_dmg") or 0),
        "armor_pen": int(row.get("armor_piercing") or 0), "speed": int(row.get("ratio_speed") or 0),
        "range": int(row.get("search_range") or 0),
    }


def solve_sangvis(w, cls, linkable, stats, eat=100):
    """Ratios plus flat max-resolution bonuses ("res_*") that give the requested final stats.

    A ratio point moves a boss's HP by about 9, so the ratio gets close from below and the unit's
    own resolution rows (which nothing else shares) carry the small remainder exactly.
    """
    types, adv = sangvis_tables(w)
    T, A = types[int(cls)], adv[5]
    F = 5 if linkable else 1
    models = F
    base = lambda tf, af: L_SANGVIS * eat * S_SANGVIS * float(A[af]) * float(T[tf]) / 1e8
    out = {"eat_ratio": eat}

    def fit(target, unit, per_models, scale=1):
        """ratio r and flat f with ceil((f + unit x r) x scale) == target (scale = models for HP)."""
        if target <= 0:
            return 0, 0
        top = max(0, int((target / scale) // unit))
        best = None
        for r in range(top, max(-1, top - 80), -1):       # the ratio near the top, the flat makes up the rest
            rest = target / scale - unit * r
            for f in (math.floor(rest) - 1, math.floor(rest), math.ceil(rest)):
                if f < 0:
                    continue
                d = abs(_ceil((f + unit * r) * scale) - target)
                if best is None or d < best[0]:
                    best = (d, r, f)
            if best[0] == 0:
                break
        return best[1], best[2]

    hp_unit = base("basic_hp", "advance_hp") / F
    out["ratio_hp"], out["res_hp"] = fit(int(stats.get("hp") or 1), hp_unit, True, models)
    out["ratio_pow"], out["res_pow"] = fit(int(stats.get("damage") or 1), base("basic_pow", "advance_pow") / F, True)
    for f, rf, key, tf, af in (("ratio_rate", "res_rate", "rate", "basic_rate", "advance_rate"),
                               ("ratio_hit", "res_hit", "accuracy", "basic_hit", "advance_hit"),
                               ("ratio_dodge", "res_dodge", "evasion", "basic_dodge", "advance_dodge"),
                               ("ratio_armor", "res_armor", "armor", "basic_armor", "advance_armor")):
        out[f], out[rf] = fit(int(stats.get(key) or 0), base(tf, af), False)
    out.update({"crit": int(stats.get("crit") or 0), "crit_dmg": int(stats.get("crit_dmg") or 0),
                "armor_piercing": int(stats.get("armor_pen") or 0), "ratio_speed": int(stats.get("speed") or 0),
                "search_range": int(stats.get("range") or 0)})
    return out


def sangvis_design(w, row, text, grant=None):
    return {
        "id": row["id"], "name": w.text_of(text, row.get("name")) or row.get("en_name", ""),
        "intro": w.text_of(text, row.get("en_introduce")), "model": row["code"], "faction": row.get("forces") or 0,
        "class": row["type"], "rarity": row["rank"], "linkable": int(row.get("formation") or 1) > 1,
        "stats": sangvis_stats(w, row),
        "skills": {"normal_attack": row.get("normal_attack") or 0, "skill1": row.get("skill1") or 0,
                   "skill2": row.get("skill2") or 0, "skill2_kind": row.get("skill2_type") or 1,
                   "skill3": row.get("skill3") or 0, "skill_advance": row.get("skill_advance") or 0,
                   "passive": _ints(row.get("passive_skill2")), "dynamic": _ints(row.get("dynamic_passive_skill"))},
        "give": grant is not None,
    }


def sangvis_rows(w, design, base_row, base_resolution):
    """(sangvis row, its own resolution rows). The resolution rows carry the flat remainders."""
    row = dict(base_row)
    sid, cls, linkable = int(design["id"]), int(design["class"]), bool(design.get("linkable"))
    sol = solve_sangvis(w, cls, linkable, design["stats"], int(row.get("eat_ratio") or 100))
    flats = {k: sol.pop(k) for k in list(sol) if k.startswith("res_")}
    row.update(sol)
    row.update({"id": sid, "type": cls, "rank": int(design["rarity"]), "forces": int(design.get("faction") or 0),
                "code": design.get("model") or row["code"], "en_name": design.get("name") or row.get("en_name", ""),
                "formation": 5 if linkable else 1, "resolution": sid})
    chips = "1,2,3" if cls == 1 else ""     # only bosses carry chips
    row["type_chip1"] = row["type_chip2"] = chips
    sk = design.get("skills") or {}
    for f in ("normal_attack", "skill1", "skill2", "skill3", "skill_advance"):
        row[f] = int(sk.get(f) or 0)
    row["skill2_type"] = int(sk.get("skill2_kind") or 1) if row["skill2"] else 0
    row["passive_skill2"] = ",".join(str(x) for x in sk.get("passive") or [])
    row["dynamic_passive_skill"] = ",".join(str(x) for x in sk.get("dynamic") or [])
    tiles = {int(r["lv"]): r.get("effect_grid_effect", "") for r in base_resolution}
    res = []
    for lv in range(5):
        res.append({"id": sid * 100 + lv, "group_id": sid, "lv": lv, "unlock_num": 0 if lv == 0 else 1,
                    "resolution_number": lv + 1 if linkable else 1, "effect_grid_effect": tiles.get(lv, ""),
                    "resolution_effect": 0, "skill1": 0, "skill2": 0, "skill3": 0, "skill_advance": 0,
                    "resolution_hp": flats["res_hp"], "resolution_pow": flats["res_pow"],
                    "resolution_rate": flats["res_rate"], "resolution_hit": flats["res_hit"],
                    "resolution_dodge": flats["res_dodge"], "resolution_armor": flats["res_armor"]})
    return row, res


# ---------------------------------------------------------------------------- enemies

ENEMY_STATS = [("hp", "maxlife", "HP (per link)"), ("damage", "pow", "Damage"), ("rate", "rate", "Rate of fire"),
               ("accuracy", "hit", "Accuracy"), ("evasion", "dodge", "Evasion"), ("armor", "armor", "Armor"),
               ("armor_pen", "armor_piercing", "Armor penetration"), ("crit", "crit", "Critical rate %"),
               ("crit_dmg", "crit_dmg", "Critical damage %"), ("range", "range", "Range"), ("speed", "speed", "Movement speed"),
               ("shield", "def", "Force Shield"), ("shield_break", "def_break", "Shield break")]


def enemy_design(w, row, text):
    """Stats as at level 100 (scaled from the row's own level)."""
    std = {int(r["level"]): r for r in w.world_table("enemy_standard_attribute")}
    lv = int(row.get("level") or 100)
    scaled = {"maxlife": "maxlife", "pow": "pow", "hit": "hit", "dodge": "dodge", "armor": "armor",
              "armor_piercing": "armor_piercing", "def": "def", "def_break": "def_break"}
    stats = {}
    for key, f, _ in ENEMY_STATS:
        v = float(row.get(f) or 0)
        if f in scaled and lv != 100 and lv in std and 100 in std and float(std[lv][scaled[f]] or 0):
            v = v * float(std[100][scaled[f]]) / float(std[lv][scaled[f]])
        stats[key] = int(round(v))
    return {"id": row["id"], "name": w.text_of(text, row.get("name")) or row.get("code", ""), "model": row["code"],
            "type": row["type"], "stats": stats,
            "skills": {"normal_attack": row.get("normal_attack") or 0, "passive": _ints(row.get("passive_skill"))}}


def enemy_row(design, base_row):
    row = dict(base_row)
    row.update({"id": int(design["id"]), "type": int(design["type"]), "code": design.get("model") or row["code"],
                "level": 100, "number": 1})
    for key, f, _ in ENEMY_STATS:
        row[f] = int(design["stats"].get(key) or 0)
    sk = design.get("skills") or {}
    row["normal_attack"] = int(sk.get("normal_attack") or row.get("normal_attack") or 0)
    row["passive_skill"] = ",".join(str(x) for x in sk.get("passive") or [])
    return row


# ---------------------------------------------------------------------------- enemy teams

def team_design(row, members):
    ai = int(row.get("ai") or 0)
    stay = int(row.get("if_stay") or 0)
    word = next((k for k, (a, s) in TEAM_AI.items() if a == ai and s == stay), None)
    if word is None:
        word = next((k for k, (a, s) in TEAM_AI.items() if a == ai), "map_default")
    belong = (_ints(row.get("correction_belong")) + [0, 0, 0, 0])[:4]
    turns = []
    for part in str(row.get("correction_turn") or "").split(","):
        p = _ints(part)
        if len(p) == 2:
            turns.append({"turn": p[0], "levels": p[1]})
    leader = next((i for i, m in enumerate(members) if m["enemy_character_type_id"] == row.get("enemy_leader")), 0)
    return {"id": row["id"], "leader": leader, "ai": word, "ai_param": str(row.get("ai_content") or ""),
            "tags": [t for t in _ints(row.get("enemy_type_display")) if t in TEAM_TAGS],
            "fixed_ce": int(row.get("effect_ext") or 0), "correction_belong": belong, "correction_turn": turns,
            "members": [{"id": m.get("id"), "enemy": m["enemy_character_type_id"], "x": m["coordinator_x"],
                         "y": m["coordinator_y"], "level": m["level"], "links": m["number"],
                         "shield_pct": m.get("def_percent") or 0, "wave": m.get("batch") or 0} for m in members]}


def team_rows(design, base_row):
    row = dict(base_row)
    ai, stay = TEAM_AI.get(design.get("ai") or "map_default", (0, 0))
    members = design.get("members") or []
    lead = members[int(design.get("leader") or 0)]["enemy"] if members else row.get("enemy_leader", 0)
    row.update({"id": int(design["id"]), "enemy_leader": int(lead), "ai": ai, "if_stay": stay,
                "ai_content": str(design.get("ai_param") or "") if design.get("ai") in TEAM_AI_PARAM else "",
                "effect_ext": int(design.get("fixed_ce") or 0)})
    keep = [t for t in _ints(row.get("enemy_type_display")) if t not in TEAM_TAGS]    # custom tips stay
    row["enemy_type_display"] = ",".join(str(t) for t in sorted(set(keep + [int(t) for t in design.get("tags") or []])))
    belong = [int(x or 0) for x in (design.get("correction_belong") or [0, 0, 0, 0])]
    row["correction_belong"] = ",".join(str(x) for x in belong) if any(belong) else ""
    turns = sorted(design.get("correction_turn") or [], key=lambda t: int(t["turn"]))
    row["correction_turn"] = ",".join(f"{int(t['turn'])}:{int(t['levels'])}" for t in turns)
    mem = [{"id": m.get("id"), "enemy_team_id": int(design["id"]), "enemy_character_type_id": int(m["enemy"]),
            "coordinator_x": int(m["x"]), "coordinator_y": int(m["y"]), "level": int(m["level"]), "number": int(m["links"]),
            "def_percent": int(m.get("shield_pct") or 0), "batch": int(m.get("wave") or 0), "is_advance": 0}
           for m in members]
    return row, mem


# ---------------------------------------------------------------------------- maps

def limit_parts(v):
    p = _ints(v)
    return (p + [0, 0])[:2]


def map_design(row, spots, spawns, texts, open_):
    echelons, total = limit_parts(row.get("limit_team"))
    return {
        "id": row["id"], "name": texts.get("name", ""), "subtitle": texts.get("mission_describe", ""),
        "sub": row.get("sub") or 1,
        "mission_type": row.get("if_emergency") if row.get("if_emergency") in MAP_KINDS else 0,
        "night": int(row.get("special_type") or 0) == 1, "difficulty": row.get("difficulty") or 0,
        "level": row.get("recommend_gun_level") or 0, "base_ai": row.get("enemy_ai_type") or 1,
        "goals": str(row.get("type") or "2"), "win_turn": row.get("win_turn") or 0, "turn_limit": row.get("turn_limit") or 0,
        "boss_team": (_ints(row.get("boss_team_id")) or [0])[0],
        "rank": {"turns": row.get("expect_turn") or 0, "kills": row.get("expect_enemy_die_num") or 0,
                 "losses": row.get("expect_gun_die_num") or 0},
        "limits": {"echelons": echelons, "coalition": row.get("limit_sangvis") if row.get("limit_sangvis") is not None else -1,
                   "hoc": row.get("limit_squad") if row.get("limit_squad") is not None else -1,
                   "vehicles": row.get("limit_vehicle") if row.get("limit_vehicle") is not None else -1,
                   "support": row.get("support_available") or 0},
        "endless": int(row.get("endless_mode") or 0) > 0, "restart": int(row.get("restart_hide") or 0) == 0,
        "background": row.get("map_res_name") or "", "frame": row.get("map_information") or "",
        "spots": spots, "spawns": spawns, "open": open_,
    }


def map_row(design, base_row):
    """The mission row; its campaign, list place and unlock come from the mod's Campaign entry (gfserver/mods.py)."""
    row = dict(base_row)
    lim = design.get("limits") or {}
    rank = design.get("rank") or {}
    row.update({
        "id": int(design["id"]), "sub": int(design.get("sub") or 1), "special_type": 1 if design.get("night") else 0,
        "difficulty": int(design.get("difficulty") or 0), "recommend_gun_level": int(design.get("level") or 0),
        "enemy_ai_type": int(design.get("base_ai") or 1), "type": str(design.get("goals") or "2"),
        "win_turn": int(design.get("win_turn") or 0), "turn_limit": int(design.get("turn_limit") or 0),
        "boss_team_id": str(int(design.get("boss_team") or 0)),
        "expect_turn": int(rank.get("turns") or 0), "expect_enemy_die_num": int(rank.get("kills") or 0),
        "expect_gun_die_num": int(rank.get("losses") or 0),
        "limit_team": str(int(lim.get("echelons") or 0)), "limit_sangvis": int(lim.get("coalition", -1)),
        "limit_squad": int(lim.get("hoc", -1)), "limit_vehicle": int(lim.get("vehicles", -1)),
        "support_available": int(lim.get("support") or 0),
        "endless_mode": 1 if design.get("endless") else 0, "restart_hide": 0 if design.get("restart", True) else 1,
        "difficulty_recommend": f"{int(design.get('difficulty') or 0)},{int(design.get('level') or 0)};0,0;0,0;0,0;0,0",
    })
    if design.get("background"):
        row["map_res_name"] = design["background"]
    if design.get("frame"):
        row["map_information"] = design["frame"]
    wins = [s["id"] for s in design.get("spots") or [] if s.get("win")]
    row["win_spot_id"] = ",".join(str(x) for x in wins) if wins else "0"
    return row
