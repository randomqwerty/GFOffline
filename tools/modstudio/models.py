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
import json
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
MAP_AI = {1: "Standby: holds position", 2: "Random: wanders", 3: "Attack: heads for your Command Post",
          4: "Random (another kind)", -1: "Night: moves unseen", "expand": "Expand: pushes into Griffin nodes",
          "alert": "Alert: chases echelons that come close"}
MAP_AI_WORDS = {"expand", "alert"}     # kept in map_rules "default_ai" (the client's enemy_ai_type has no code for them)
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


def _tile_of(row):
    buffs = []
    for part in str(row.get("effect_grid_effect") or "").split(";"):
        p = _ints(part)
        if len(p) >= 2:
            buffs.append({"stat": p[0], "value": p[1]})
    return {"center": int(row.get("effect_grid_center") or 13), "cells": _ints(row.get("effect_grid_pos")),
            "targets": [t for t in _ints(row.get("effect_guntype")) if t], "buffs": buffs}


def doll_design(w, row, text, grant=None):
    """Design view of a gun row."""
    return {
        "id": row["id"], "name": w.text_of(text, row.get("name")) or row.get("en_name", ""),
        "intro": w.text_of(text, row.get("en_introduce")), "credits": w.text_of(text, row.get("extra")),
        "type": row["type"], "rarity": row.get("rank_display") or row["rank"], "model": row["code"],
        "stats": doll_stats(w, row),
        "tile": _tile_of(row),
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
    same = int(base_row.get("id") or 0) == int(design["id"])     # editing this doll itself (a game original or one of ours)
    if int(base_row.get("type") or 0) != t:
        # class changed: take the class's typical values for everything class-specific
        row.update(common)
    if not (same and int(base_row.get("type") or 0) == t and _same_stats(design["stats"], doll_stats(w, base_row))):
        row.update(solve_doll(w, t, design["stats"], int(row.get("eat_ratio") or common["eat_ratio"])))
    rarity = int(design["rarity"])
    if not (same and rarity == int(base_row.get("rank_display") or base_row.get("rank") or 0)):
        row.update({"rank": min(rarity, 6), "rank_display": rarity})
    row.update({"id": int(design["id"]), "type": t, "code": design.get("model") or row["code"]})
    if not same or not row.get("en_name"):
        row["en_name"] = design.get("name") or row.get("en_name", "")
    if int(design["stats"].get("rof_cap") or 0):
        row["atk_speed_max"] = int(design["stats"]["rof_cap"])
    tile = design.get("tile") or {}
    was = _tile_of(base_row)
    if int(tile.get("center") or 13) != was["center"]:
        row["effect_grid_center"] = int(tile.get("center") or 13)
    if set(tile.get("cells") or []) != set(was["cells"]):
        row["effect_grid_pos"] = ",".join(str(c) for c in sorted(set(tile.get("cells") or [])))
    if set(tile.get("targets") or []) != set(was["targets"]):
        row["effect_guntype"] = ",".join(str(x) for x in sorted(set(tile.get("targets") or []))) or "0"
    buffs = [(int(b["stat"]), int(b["value"])) for b in tile.get("buffs") or [] if int(b.get("stat") or 0) and int(b.get("value") or 0)]
    if buffs != [(b["stat"], b["value"]) for b in was["buffs"] if b["stat"] and b["value"]]:
        row["effect_grid_effect"] = ";".join(f"{s},{v}" for s, v in buffs)
    for i, slot in enumerate(design.get("equipment") or [], 1):
        if i <= 3:
            types = ",".join(str(x) for x in slot.get("types") or [])
            row[f"type_equip{i}"] = f"{int(slot.get('category') or 0)};{types}" if slot.get("category") else ""
    sk = design.get("skills") or {}
    row["normal_attack"] = int(sk.get("normal_attack") or common["normal_attack"])
    row["skill1"] = int(sk.get("skill1") or 0)
    row["skill2"] = int(sk.get("skill2") or 0)
    for f, key in (("passive_skill", "passive"), ("dynamic_passive_skill", "dynamic")):
        if [int(x) for x in sk.get(key) or []] != _ints(base_row.get(f)) or not same:
            row[f] = ",".join(str(x) for x in sk.get(key) or [])
    if not same:
        row["mindupdate_consume"] = ""      # no Neural Upgrade
    return row


def _same_stats(a, b):
    """Design stats equal to a row's (the editor sends numbers as given)."""
    return all(str(a.get(k)) == str(v) for k, v in b.items() if k in a)


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
    if (sid == int(base_row.get("id") or 0) and cls == int(base_row.get("type") or 0) and base_resolution
            and linkable == (int(base_row.get("formation") or 1) > 1)
            and _same_stats(design["stats"], sangvis_stats(w, base_row, sorted(base_resolution, key=lambda r: r["lv"])[-1]))):
        return _sangvis_fields(row, design, cls, linkable, keep=True), []     # an original, stats unchanged
    sol = solve_sangvis(w, cls, linkable, design["stats"], int(row.get("eat_ratio") or 100))
    flats = {k: sol.pop(k) for k in list(sol) if k.startswith("res_")}
    row.update(sol)
    row = _sangvis_fields(row, design, cls, linkable)
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


def _sangvis_fields(row, design, cls, linkable, keep=False):
    """The design's non-stat fields on a sangvis row; keep: an original whose stats stay as they are."""
    sid = int(design["id"])
    row.update({"id": sid, "type": cls, "rank": int(design["rarity"]), "forces": int(design.get("faction") or 0),
                "code": design.get("model") or row["code"]})
    if not keep:
        row.update({"en_name": design.get("name") or row.get("en_name", ""), "formation": 5 if linkable else 1,
                    "resolution": sid})
        chips = "1,2,3" if cls == 1 else ""     # only bosses carry chips
        row["type_chip1"] = row["type_chip2"] = chips
    sk = design.get("skills") or {}
    for f in ("normal_attack", "skill1", "skill2", "skill3", "skill_advance"):
        row[f] = int(sk.get(f) or 0)
    row["skill2_type"] = int(sk.get("skill2_kind") or 1) if row["skill2"] else row.get("skill2_type", 0)
    row["passive_skill2"] = ",".join(str(x) for x in sk.get("passive") or [])
    row["dynamic_passive_skill"] = ",".join(str(x) for x in sk.get("dynamic") or [])
    return row


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


def enemy_row(design, base_row, w=None):
    """w given: an original whose stats were not changed keeps its own level and stats."""
    row = dict(base_row)
    row.update({"id": int(design["id"]), "type": int(design["type"]), "code": design.get("model") or row["code"]})
    same = (w is not None and int(design["id"]) == int(base_row.get("id") or 0)
            and _same_stats(design["stats"], enemy_design(w, base_row, {})["stats"]))
    if not same:
        row.update({"level": 100, "number": 1})
        for key, f, _ in ENEMY_STATS:
            row[f] = int(design["stats"].get(key) or 0)
    sk = design.get("skills") or {}
    row["normal_attack"] = int(sk.get("normal_attack") or row.get("normal_attack") or 0)
    if [int(x) for x in sk.get("passive") or []] != _ints(row.get("passive_skill")):
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
                         "shield_pct": m.get("def_percent") or 0, "wave": m.get("batch") or 0,
                         "advance": bool(int(m.get("is_advance", 1) or 0))} for m in members]}


def team_rows(design, base_row):
    row = dict(base_row)
    ai, stay = TEAM_AI.get(design.get("ai") or "map_default", (0, 0))
    members = design.get("members") or []
    was = team_design(base_row, [{"enemy_character_type_id": m["enemy"], "coordinator_x": 0, "coordinator_y": 0,
                                  "level": 0, "number": 0} for m in members])
    lead = members[int(design.get("leader") or 0)]["enemy"] if members else row.get("enemy_leader", 0)
    if int(design.get("leader") or 0) != was["leader"]:
        row["enemy_leader"] = int(lead)     # (the game's leader need not be a member; kept unless changed)
    row.update({"id": int(design["id"]), "effect_ext": int(design.get("fixed_ce") or 0)})
    if design.get("ai") != was["ai"] or str(design.get("ai_param") or "") != str(was["ai_param"]):
        row.update({"ai": ai, "if_stay": stay,
                    "ai_content": str(design.get("ai_param") or "") if design.get("ai") in TEAM_AI_PARAM else ""})
    keep = [t for t in _ints(row.get("enemy_type_display")) if t not in TEAM_TAGS]    # custom tips stay
    row["enemy_type_display"] = ",".join(str(t) for t in sorted(set(keep + [int(t) for t in design.get("tags") or []])))
    belong = [int(x or 0) for x in (design.get("correction_belong") or [0, 0, 0, 0])]
    if belong != was["correction_belong"]:
        row["correction_belong"] = ",".join(str(x) for x in belong) if any(belong) else ""
    turns = sorted(design.get("correction_turn") or [], key=lambda t: int(t["turn"]))
    if [(int(t["turn"]), int(t["levels"])) for t in turns] != [(t["turn"], t["levels"]) for t in was["correction_turn"]]:
        row["correction_turn"] = ",".join(f"{int(t['turn'])}:{int(t['levels'])}" for t in turns)
    mem = [{"id": m.get("id"), "enemy_team_id": int(design["id"]), "enemy_character_type_id": int(m["enemy"]),
            "coordinator_x": int(m["x"]), "coordinator_y": int(m["y"]), "level": int(m["level"]), "number": int(m["links"]),
            "def_percent": int(m.get("shield_pct") or 0), "batch": int(m.get("wave") or 0),
            "is_advance": 0 if m.get("advance") is False else 1}       # EnemyInTeamInfo.isAdvance: 0 stands still until a target is in range
           for m in members]
    return row, mem


# ---------------------------------------------------------------------------- maps

def limit_parts(v):
    p = _ints(v)
    return (p + [0, 0])[:2]


# mission.event_score "<mode>|<30 comma fields>" (gfserver/missions.py score_rule): design key -> field
SCORE_NUMBERS = {"echelon_out": 2, "withdraw": 3, "repair": 4, "building": 5, "crate": 7, "hoc_withdraw": 8,
                 "hoc_out": 9, "hostage_bar": 11, "repair_point": 16, "supply": 17,
                 "ma_withdraw": 20, "ma_defeat": 21, "ma_out": 22, "ma_repair": 23}
SCORE_LISTS = {"specials": 15, "skills": 18, "buffs": 19}       # "<id>:<points>;..."
# a recent ranking map's (11002) values; fields 1, 6 and 10 are unread
SCORE_TEMPLATE = "1|10,10000,8000,5000,1000,0,5000,10000,8000,10000,1000,2000,1:10000;2:0;3:2000;5:0;6:0;7:5000,,10,0,1000,5000,,,8000,20000,10000,5000"


def _score_fields(text):
    mode, sep, rest = str(text or "").partition("|")
    if not sep or not mode.strip().isdigit():
        return None
    return rest.split(",") + [""] * max(0, 30 - len(rest.split(",")))


def _pct_of(div):
    """A kill field (points = strength / div) as a percent of the enemy's strength."""
    div = int(div or 0)
    return 0 if div <= 0 or div >= 99999 else round(100 / div, 2)


def score_design(text):
    """event_score as plain settings, or None for a map without a score."""
    f = _score_fields(text)
    if f is None:
        return None
    num = lambda x: int(x) if str(x).strip().lstrip("-").isdigit() else 0
    pairs = lambda x: [[int(p) for p in e.split(":")] for e in str(x).split(";")
                       if e and all(p.strip().lstrip("-").isdigit() for p in e.split(":"))]
    out = {k: num(f[i]) for k, i in SCORE_NUMBERS.items()}
    out["kill_pct"] = _pct_of(num(f[0]))
    out["npc_kill_pct"] = _pct_of(num(f[14]))
    out["spots"] = {str(e[0]): e[1] for e in pairs(f[12]) if len(e) == 2}
    out["allies"] = [{"team": e[0], "side": e[1], "points": e[2]} for e in pairs(f[13]) if len(e) == 3]
    for k, i in SCORE_LISTS.items():
        out[k] = [{"id": e[0], "points": e[1]} for e in pairs(f[i]) if len(e) == 2]
    return out


def score_text(score, base_text=""):
    """event_score from score_design settings; fields they don't cover stay as in base_text."""
    f = _score_fields(base_text) or _score_fields(SCORE_TEMPLATE)
    old = list(f)
    div = lambda pct: str(round(100 / float(pct))) if float(pct or 0) > 0 else "0"
    f[0], f[14] = div(score.get("kill_pct")), div(score.get("npc_kill_pct"))
    for k, i in SCORE_NUMBERS.items():
        f[i] = str(abs(int(score.get(k) or 0)))
    f[12] = ";".join(f"{int(t)}:{int(p)}" for t, p in (score.get("spots") or {}).items())
    f[13] = ";".join(f"{int(a['team'])}:{int(a.get('side') or 1)}:{int(a.get('points') or 0)}"
                     for a in score.get("allies") or [] if int(a.get("team") or 0))
    for k, i in SCORE_LISTS.items():
        f[i] = ";".join(f"{int(e['id'])}:{int(e.get('points') or 0)}" for e in score.get(k) or [] if int(e.get("id") or 0))
    for i in (12, 13, *SCORE_LISTS.values()):
        if not f[i] and ":" not in old[i]:
            f[i] = old[i]           # an empty list stays as written ("" or "0")
    while len(f) > 24 and not f[-1]:
        f.pop()
    return "1|" + ",".join(f)


def _switches(v):
    """mission.integration_switch "key-value;..." as a dict."""
    out = {}
    for part in str(v or "").split(";"):
        k, sep, val = part.partition("-")
        if sep and k.strip():
            out[k.strip()] = val.strip()
    return out


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
        # the client allows repairs only with integration_switch key 1 set to 1 (else "Repair Disabled")
        "repair": _switches(row.get("integration_switch")).get("1") == "1",
        "environment": _ints(row.get("fight_environment_group")),
        "hostages": (_ints(row.get("expect_hostage_num")) or [0])[0],
        "score": score_design(row.get("event_score")),
    }


def _ai_code(v, base_row):
    """enemy_ai_type for a design's default AI; a word kept in map_rules leaves the row's own."""
    return int(base_row.get("enemy_ai_type") or 1) if str(v) in MAP_AI_WORDS else int(v or 1)


def map_row(design, base_row):
    """The mission row; its campaign, list place and unlock come from the mod's Campaign entry (gfserver/mods.py).
    Only settings that differ from base_row's are written, so the game's own values stay as they are."""
    row = dict(base_row, id=int(design["id"]))
    was = map_design(base_row, [], [], {}, False)
    lim, wlim = design.get("limits") or {}, was["limits"]
    rank, wrank = design.get("rank") or {}, was["rank"]
    norm = lambda v: json.dumps(v, sort_keys=True, default=str)

    def changed(new, old):
        return str(new) != str(old) if not isinstance(new, (dict, list)) else norm(new) != norm(old)
    plain = {   # design key: (row field, value)
        "sub": ("sub", int(design.get("sub") or 1)), "difficulty": ("difficulty", int(design.get("difficulty") or 0)),
        "level": ("recommend_gun_level", int(design.get("level") or 0)),
        "base_ai": ("enemy_ai_type", _ai_code(design.get("base_ai"), base_row)), "goals": ("type", str(design.get("goals") or "2")),
        "win_turn": ("win_turn", int(design.get("win_turn") or 0)), "turn_limit": ("turn_limit", int(design.get("turn_limit") or 0)),
        "boss_team": ("boss_team_id", str(int(design.get("boss_team") or 0))),
        "background": ("map_res_name", design.get("background") or base_row.get("map_res_name") or ""),
        "frame": ("map_information", design.get("frame") or base_row.get("map_information") or ""),
    }
    for key, (f, v) in plain.items():
        if changed(design.get(key, was[key]), was[key]):
            row[f] = v
    if bool(design.get("night")) != was["night"]:
        row["special_type"] = 1 if design.get("night") else 0
    if bool(design.get("endless")) != was["endless"]:
        row["endless_mode"] = 1 if design.get("endless") else 0
    if bool(design.get("restart", True)) != was["restart"]:
        row["restart_hide"] = 0 if design.get("restart", True) else 1
    for key, f in (("turns", "expect_turn"), ("kills", "expect_enemy_die_num"), ("losses", "expect_gun_die_num")):
        if int(rank.get(key) or 0) != int(wrank[key] or 0):
            row[f] = int(rank.get(key) or 0)
    for key, f, default in (("coalition", "limit_sangvis", -1), ("hoc", "limit_squad", -1), ("vehicles", "limit_vehicle", -1),
                            ("support", "support_available", 0)):
        if int(lim.get(key, default)) != int(wlim[key]):
            row[f] = int(lim.get(key, default))
    if int(lim.get("echelons") or 0) != limit_parts(base_row.get("limit_team"))[0]:
        row["limit_team"] = str(int(lim.get("echelons") or 0))
    if changed(design.get("difficulty"), was["difficulty"]) or changed(design.get("level"), was["level"]):
        row["difficulty_recommend"] = f"{int(design.get('difficulty') or 0)},{int(design.get('level') or 0)};0,0;0,0;0,0;0,0"
    wins = sorted(int(s["id"]) for s in design.get("spots") or [] if s.get("win"))
    here = {int(s["id"]) for s in design.get("spots") or []}
    if wins != sorted(x for x in _ints(base_row.get("win_spot_id")) if x in here):
        row["win_spot_id"] = ",".join(str(x) for x in wins) if wins else "0"
    if bool(design.get("repair", True)) != was["repair"]:
        sw = _switches(row.get("integration_switch"))
        sw["1"] = "1" if design.get("repair", True) else "0"
        sw.setdefault("4", "40:80:160")
        row["integration_switch"] = ";".join(f"{k}-{v}" for k, v in sw.items())
    if int(design.get("hostages") or 0) != int(was["hostages"] or 0):
        h = int(design.get("hostages") or 0)
        row["expect_hostage_num"] = str(h) if isinstance(base_row.get("expect_hostage_num"), str) else h
    env = [int(x) for x in design.get("environment") or [] if int(x)]
    if env != was["environment"]:
        row["fight_environment_group"] = ";".join(str(x) for x in env)
    score = design.get("score")
    if not score:
        row["event_score"] = "" if was["score"] else base_row.get("event_score", "")
    elif score != was["score"]:
        row["event_score"] = score_text(score, base_row.get("event_score"))
    return row


# ---------------------------------------------------------------------------- allied forces and buildings

# an allied force's orders (stc team_ai force 3/4, as gfserver/missions.py moves them) -> ai code
ALLY_AI = {"hold": 0, "patrol": 101, "alert": 102, "expand": 103, "eliminate": 1, "capture": 2}
ALLY_AI_LABELS = {"hold": "Holds its node", "patrol": "Patrol: walks a route", "alert": "Alert: chases units that come close",
                  "expand": "Expand: takes nodes for its side", "eliminate": "Eliminate: hunts the nearest hostile unit",
                  "capture": "Capture: heads for the other side's Command Post"}
ALLY_POSITIONS = (12, 7, 17, 13, 8, 18, 14, 9, 19)      # formation slots, in the order new members take them


def _side_part(text, side):
    parts = str(text or "0").split(";")
    return (parts[side] if side < len(parts) else parts[0]).strip() or "0"


def ally_design(row, members, text_of_name):
    side = int(row.get("initial_type") or 0)
    code, content = _side_part(row.get("ai"), side), _side_part(row.get("ai_content"), side)
    word = next((k for k, v in ALLY_AI.items() if str(v) == code.split(":")[0]), "hold")
    return {"id": row["id"], "name": text_of_name, "side": side, "ai": word,
            "route": _ints(content) if word == "patrol" else [],
            "range": (_ints(content) or [2])[0] if word == "alert" else 2,
            "duration": int(row.get("duration") or 0), "fights_as": int(row.get("enemy_team_id") or 0),
            "members": [{"gun": int(m["gun_id"]), "level": int(m.get("gun_level") or 100), "position": int(m.get("position") or 0)}
                        for m in members]}


def ally_row(design, base_row):
    """The ally_team row; settings equal to base_row's stay as they are (the game's own ai for each side)."""
    row = dict(base_row, id=int(design["id"]))
    was = ally_design(base_row, [], "")
    side = int(design.get("side") or 0)
    if side != was["side"]:
        row["initial_type"] = side
    word = design.get("ai") or "hold"
    content = {"patrol": ",".join(str(int(x)) for x in design.get("route") or []) or "0",
               "alert": str(max(1, int(design.get("range") or 2)))}.get(word, "0")
    if (word, design.get("route") or [], int(design.get("range") or 2)) != (was["ai"], was["route"], was["range"]) or side != was["side"]:
        row["ai"] = ";".join([str(ALLY_AI.get(word, 0))] * 3)        # the same orders whichever side it ends up on
        row["ai_content"] = ";".join([content] * 3)
    for key, f in (("duration", "duration"), ("fights_as", "enemy_team_id")):
        if int(design.get(key) or 0) != int(was[key] or 0):
            row[f] = int(design.get(key) or 0)
    return row


def ally_members(w, design):
    """gun_in_ally rows (without ids) for the design's members, stats from the doll's own at that level."""
    out, used = [], set()
    for i, m in enumerate(design.get("members") or []):
        gun = w.world_index("gun").get(str(m.get("gun")))
        if gun is None:
            continue
        lv = max(1, min(120, int(m.get("level") or 100)))
        pos = int(m.get("position") or 0)
        if pos not in ALLY_POSITIONS or pos in used:
            pos = next(p for p in ALLY_POSITIONS if p not in used)
        used.add(pos)
        st, enh = doll_stats(w, gun, lv, 5), doll_enhancement(w, gun, lv)
        out.append({"gun_id": int(gun["id"]), "gun_level": lv, "location": i + 1, "position": pos, "life": st["hp"],
                    "pow": enh["pow"], "hit": enh["hit"], "dodge": enh["dodge"], "rate": enh["rate"], "skill1": 10,
                    "skill2": 10 if int(gun.get("skill2") or 0) else 0, "number": 5, "eat_lv": lv})
    return out


BUILDING_SIDES = {1: "Griffin", 2: "Enemy", 3: "Neutral", 0: "Other"}


def building_design(row, texts):
    slots = str(row.get("mission_skill") or "").split(";")
    destroy = [x.strip() for x in str(row.get("is_destroy") or "").split(",")]
    return {"id": row["id"], "name": texts.get("name", ""), "desc": texts.get("des", ""), "look": row.get("code") or "",
            "durability": int(row.get("defender") or 0), "side": int(row.get("belong") or 0),
            "falls_to": int(row.get("hold_belong") or 0),
            "by_attack": "1" in destroy, "by_entering": "2" in destroy,
            "turn_skills": {str(b): [x for x in _ints(slots[b]) if x] if b < len(slots) else [] for b in BUILDING_SIDES},
            "start_skills": [x for x in _ints(row.get("inherent_mission_skill")) if x],
            "death_skills": [x for x in _ints(row.get("missionskill_on_death")) if x]}


def building_row(design, base_row):
    row = dict(base_row, id=int(design["id"]))
    was = building_design(base_row, {})
    if design.get("look") and design["look"] != was["look"]:
        row["code"] = design["look"]
    if int(design.get("durability") or 0) != was["durability"]:
        row["defender"] = row["defender_upper"] = max(1, int(design.get("durability") or 1))
    for key, f in (("side", "belong"), ("falls_to", "hold_belong")):
        if int(design.get(key) or 0) != was[key]:
            row[f] = int(design.get(key) or 0)
    if (bool(design.get("by_attack")), bool(design.get("by_entering"))) != (was["by_attack"], was["by_entering"]):
        row["is_destroy"] = ",".join(x for x, on in (("1", design.get("by_attack")), ("2", design.get("by_entering"))) if on) or "0"
    turn = design.get("turn_skills") or {}
    if {k: list(map(int, v)) for k, v in turn.items()} != was["turn_skills"]:
        row["mission_skill"] = ";".join(",".join(str(int(x)) for x in turn.get(str(b)) or []) or "0" for b in range(4))
    for key, f in (("start_skills", "inherent_mission_skill"), ("death_skills", "missionskill_on_death")):
        if list(map(int, design.get(key) or [])) != was[key]:
            row[f] = ",".join(str(int(x)) for x in design.get(key) or [])
    return row
