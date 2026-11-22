"""Mod Studio designs: load, create, save and delete the simplified entries (see models.py, skills.py).

Each mod's maps are listed as one entry of the Campaign tab (mod.json "campaign", expanded by
gfserver/mods.py); a map's stage number is its place in that list.
"""
import json

import models
import combos
import skills
import studio as w
import content

GRANT_DOLL = {"level": 100, "number": 5, "skill1": 10, "skill2": 10, "enhance": 1}


# ---------------------------------------------------------------------------- the Campaign tab entry

def campaign(mod_name, create=False):
    """The mod's Campaign tab entry {"name", "description", "missions": [ids in list order]}. A mod made
    with a numbered chapter is moved to one, keeping its maps in stage order."""
    mod = w.load_mod(mod_name)
    c = mod["meta"].get("campaign")
    if c or not create:
        return c or None
    old = mod["meta"].pop("chapter", None) or {}
    mine = sorted((r for r in mod["tables"].get("mission", []) if old.get("number") and int(r.get("campaign") or 0) == int(old["number"])),
                  key=lambda r: int(r.get("sub") or 0))
    c = {"name": old.get("name") or mod["meta"].get("name", mod_name), "description": old.get("description") or mod["meta"].get("description", ""),
         "missions": [int(r["id"]) for r in mine]}
    mod["meta"]["campaign"] = c
    w.save_mod(mod_name, mod)
    return c


def set_campaign(mod_name, name=None, description=None):
    c = campaign(mod_name, create=True)
    mod = w.load_mod(mod_name)
    if name is not None:
        c["name"] = name
    if description is not None:
        c["description"] = description
    mod["meta"]["campaign"] = c
    w.save_mod(mod_name, mod)
    return c


def _place_map(mod, mid, position):
    """Put a map at its stage number (1-based) in the mod's Campaign entry."""
    order = [i for i in mod["meta"]["campaign"].get("missions", []) if int(i) != int(mid)]
    order.insert(max(0, min(len(order), int(position or 1) - 1)), int(mid))
    mod["meta"]["campaign"]["missions"] = order


# ---------------------------------------------------------------------------- helpers

def _stored(mod, table, key):
    return next((r for r in mod["tables"].get(table, []) if str(r.get(w.key_of(table))) == str(key)), None)


def _flags(mod, table, key):
    stored = _stored(mod, table, key) if mod else None
    return {"in_mod": stored is not None, "copy": (stored or {}).get("_copy"),
            "in_base": str(key) in {str(r[w.key_of(table)]) for r in w.base().table(table)}}


def _save_row(mod, mod_name, table, row, copy_from):
    st = w.stored_row(table, row, copy_from, mod_name)
    w.put_rows(mod, table, [] if w.unchanged_override(table, st, mod_name) else [st], remove_keys=[row[w.key_of(table)]])


def models_catalog(kind):
    """Model/art choices: one entry per code, named after a unit that uses it."""
    table = {"gun": "gun", "sangvis": "sangvis", "enemy": "enemy_character_type"}[kind]
    text = w.world_text()
    seen = {}
    for r in w.world_table(table):
        code = r.get("code")
        if code and code not in seen:
            seen[code] = {"id": code, "code": code, "name": w.text_of(text, r.get("name")) or r.get("en_name") or code}
    return sorted(seen.values(), key=lambda x: x["name"].lower())


# ---------------------------------------------------------------------------- load / new

def get(mod_name, kind, eid):
    if kind in content.KINDS:
        return content.get(mod_name, kind, eid)
    mod = w.load_mod(mod_name) if mod_name else None
    text = w.world_text()
    if kind == "unit":
        row = w.world_index("gun")[str(eid)]
        d = models.doll_design(w, row, text, w.get_grant(mod, "guns", eid) if mod else None)
        combo = ((mod or {"meta": {}})["meta"].get("combos") or {}).get(str(eid)) or {}
        made = set(combo.get("passives") or [])
        d["skills"]["passive"] = [g for g in d["skills"]["passive"] if g not in made]
        d["combos"] = combo.get("rules") or []
        return dict(d, kind=kind, **_flags(mod, "gun", eid))
    if kind == "sangvis":
        row = w.world_index("sangvis")[str(eid)]
        d = models.sangvis_design(w, row, text, w.get_grant(mod, "sangvis", eid) if mod else None)
        return dict(d, kind=kind, **_flags(mod, "sangvis", eid))
    if kind == "enemy":
        row = w.world_index("enemy_character_type")[str(eid)]
        return dict(models.enemy_design(w, row, text), kind=kind, **_flags(mod, "enemy_character_type", eid))
    if kind == "team":
        row = w.world_index("enemy_team")[str(eid)]
        members = [r for r in w.world_table("enemy_in_team") if r["enemy_team_id"] == int(eid)]
        return dict(models.team_design(row, members), kind=kind, **_flags(mod, "enemy_team", eid))
    if kind == "map":
        row = w.world_index("mission")[str(eid)]
        wins = set(models._ints(row.get("win_spot_id")))
        rules = ((mod or {"meta": {}})["meta"].get("map_rules") or {}).get(str(eid)) or {}
        sides = rules.get("ally_sides") or {}
        spots = [dict(s, win=s["id"] in wins, **({"ally_side": sides[str(s["id"])]} if str(s["id"]) in sides else {}))
                 for s in w.world_table("spot") if s["mission_id"] == int(eid)]
        texts = {f: w.text_of(text, row.get(f)) for f in ("name", "mission_describe")}
        open_ = mod is not None and w.get_grant(mod, "missions", eid) is not None
        spawns = rules["spawns"] if "spawns" in rules else _default_spawns(eid)
        d = dict(models.map_design(row, spots, spawns, texts, open_), icon=rules.get("icon") or "",
                 move_order=rules.get("move_order") or {})
        if rules.get("default_ai") in models.MAP_AI_WORDS:
            d["base_ai"] = rules["default_ai"]
        if d.get("score") is not None:
            d["score"]["defeat"] = int(rules.get("defeat_points", d["score"].get("echelon_out") or 0))
        flags = _flags(mod, "mission", eid)
        if not flags["in_base"] and not str(row.get("integration_switch") or "").strip():
            d["repair"] = True      # maps made before the repair switch was set: allow it unless turned off
        return dict(d, kind=kind, **flags)
    if kind == "ally":
        row = w.world_index("ally_team")[str(eid)]
        gia = w.world_index("gun_in_ally")
        members = [gia[x] for x in str(row.get("guns") or "").split(",") if x.strip() in gia]
        d = models.ally_design(row, members, w.text_of(text, row.get("name")))
        return dict(d, kind=kind, **_flags(mod, "ally_team", eid))
    if kind == "building":
        row = w.world_index("building")[str(eid)]
        d = models.building_design(row, {f: w.text_of(text, row.get(f)) for f in ("name", "des")})
        return dict(d, kind=kind, **_flags(mod, "building", eid))
    if kind == "skill":
        tree = skills.load(w, eid)
        mine = mod is not None and any(int(r.get("skill_group_id") or 0) == int(eid)
                                       for r in mod["tables"].get("battle_skill_config", []))
        base_ids = {r["skill_group_id"] for r in w.base().table("battle_skill_config")}
        return dict(tree, kind=kind, id=int(eid), in_mod=mine, in_base=int(eid) in base_ids, copy=None)
    raise KeyError(kind)


def new(kind, template=None, gun_type=1):
    """A new design: a copy of `template` (any unit, enemy, team, map or skill) or a blank one."""
    if kind in content.KINDS:
        return content.new(kind, template)
    t = template not in (None, "", "0")
    if kind == "unit":
        if t:
            d = get(None, "unit", template)
            d["copy"] = int(template)
        else:
            common, anchor = models.class_defaults(w, gun_type)
            d = get(None, "unit", anchor)
            d.update(copy=anchor, name="", intro="", credits="")
            d["skills"] = {"normal_attack": common["normal_attack"], "skill1": 0, "skill2": 0, "passive": [], "dynamic": []}
        d.update(id=w.free_ids("gun")[0], give=True)
    elif kind == "sangvis":
        d = get(None, "sangvis", template if t else 1001)
        d.update(copy=int(template) if t else 1001, id=w.free_ids("sangvis")[0], give=True)
        if not t:
            d.update(name="", intro="")
    elif kind == "enemy":
        d = get(None, "enemy", template if t else 90001)
        d.update(copy=int(template) if t else 90001, id=w.free_ids("enemy_character_type")[0])
        if not t:
            d["name"] = ""
    elif kind in ("ally", "building"):
        table = "ally_team" if kind == "ally" else "building"
        src = template if t else 1
        d = get(None, kind, src)
        d.update(copy=int(src), id=w.free_ids(table)[0])
        if not t:
            d["name"] = ""
    elif kind == "team":
        if t:
            d = get(None, "team", template)
            for m in d["members"]:
                m["id"] = None
            d["copy"] = int(template)
        else:
            d = dict(models.team_design({"id": 0}, []), copy=None)
        d.update(id=w.free_ids("enemy_team")[0])
    elif kind == "map":
        if t:
            d = get(None, "map", template)
            d["copy"] = int(template)
            fresh = w.free_ids("spot", len(d["spots"]))
            remap = {str(s["id"]): str(n) for s, n in zip(d["spots"], fresh)}
            for s in d["spots"]:
                s["id"] = int(remap[str(s["id"])])
                s["route"] = w._remap_list(s.get("route"), remap)
                s["map_route"] = w._remap_list(s.get("map_route"), remap)
            for r in d["spawns"]:
                for k in ("spot", "after_destroyed"):
                    if r.get(k) is not None:
                        r[k] = int(remap.get(str(r[k]), r[k]))
                if r.get("spots"):
                    r["spots"] = [int(remap.get(str(x), x)) for x in r["spots"]]
        else:
            row = w.blank_entity("map")["row"]
            d = dict(models.map_design(row, [], [], {}, True), copy=None)
        d.update(id=w.free_ids("mission")[0], open=True, restart=True)
    elif kind == "skill":
        tree = skills.load(w, template) if t else skills.blank(w)
        d = dict(tree, kind="skill", id=0, group=0, copy=int(template) if t else None)
    else:
        raise KeyError(kind)
    d.update(kind=kind, in_mod=False, in_base=False)
    return d


# ---------------------------------------------------------------------------- preview

def preview(kind, design):
    """What the game will show for a design (the solved stats may differ slightly from the request)."""
    if kind == "unit":
        base = _base_row("gun", design)
        row = models.doll_row(w, design, base)
        return {"stats": models.doll_stats(w, row), "ratios": {k: row[k] for k in ("ratio_life", "ratio_pow", "ratio_rate",
                                                                                    "ratio_hit", "ratio_dodge", "eat_ratio")}}
    if kind == "sangvis":
        base = _base_row("sangvis", design)
        row, res = models.sangvis_rows(w, design, base, _resolution_of(base))
        return {"stats": models.sangvis_stats(w, row, res[-1] if res else None)}     # an unchanged original keeps its own rows
    raise KeyError(kind)


def _base_row(table, design):
    """The row a design starts from: its current row, else its template, else a class default."""
    idx = w.world_index(table)
    for key in (design.get("id"), design.get("copy")):
        if key not in (None, "") and str(key) in idx:
            return dict(idx[str(key)])
    if table == "gun":
        return dict(idx[str(models.class_defaults(w, design.get("type") or 1)[1])])
    return dict(idx[{"sangvis": "1001", "enemy_character_type": "90001", "enemy_team": "1", "ally_team": "1", "building": "1"}[table]])


def _resolution_of(row):
    return [r for r in w.world_table("sangvis_resolution") if r["group_id"] == row.get("resolution")]


# ---------------------------------------------------------------------------- save

def _default_spawns(mid):
    """A game map's own spawns, as the server plays them without a mod (gfserver/missions.py: its shipped
    spawn table, else recorded runs and the heliport fallback); [] for a map the game doesn't have."""
    if str(mid) not in {str(r["id"]) for r in w.base().table("mission")}:
        return []
    from gfserver import missions
    got = missions._table_spawn_rules(int(mid))
    rules = got if got is not None else missions._live_spawn_rules(int(mid)) + missions._fallback_spawn_rules(int(mid))
    return json.loads(json.dumps(rules))


DEPLOY_TYPES = (1, 3, 7)        # Command Post, heliport, heavy heliport (gfserver/missions.py)


def _check_deploy(d):
    """A map needs somewhere to deploy: a Griffin Command Post or heliport, or an allied force on your side
    (you can give it orders)."""
    spots = d.get("spots") or []
    if not spots:
        return
    if any(int(s.get("belong") or 0) == 1 and int(s.get("type") or 0) in DEPLOY_TYPES for s in spots):
        return
    forces = w.world_index("ally_team")
    for s in spots:
        if int(s.get("ally_team_id") or 0):
            side = s.get("ally_side")
            side = int(side) if side not in (None, "") else int((forces.get(str(s["ally_team_id"])) or {}).get("initial_type") or 0)
            if side == 1:
                return
    from gfserver import mods
    raise mods.ModError("The map needs somewhere to deploy: a Command Post or heliport held by Griffin, "
                        "or an allied force on your side.")


def save(mod_name, kind, d):
    if kind in content.KINDS:
        return content.save(mod_name, kind, d)
    with w.LOCK:
        mod = w.load_mod(mod_name)
        if kind == "unit":
            _save_combos(mod, d)
            row = w.coerce_row("gun", models.doll_row(w, d, _base_row("gun", d)))
            w.own_texts("gun", row, {"name": d.get("name", ""), "en_introduce": d.get("intro", ""),
                                     "extra": d.get("credits", "")}, mod)
            _save_row(mod, mod_name, "gun", row, d.get("copy"))
            w.set_grant(mod, "guns", row["id"], dict(GRANT_DOLL, id=row["id"]) if d.get("give") else None)
        elif kind == "sangvis":
            base = _base_row("sangvis", d)
            row, res = models.sangvis_rows(w, d, base, _resolution_of(base))
            row = w.coerce_row("sangvis", row)
            w.own_texts("sangvis", row, {"name": d.get("name", ""), "en_introduce": d.get("intro", "")}, mod)
            _save_row(mod, mod_name, "sangvis", row, d.get("copy"))
            old = [r["id"] for r in mod["tables"].get("sangvis_resolution", []) if int(r.get("group_id") or 0) == row["id"]]
            if res:         # none: stats unchanged, its resolution rows stay as they are
                res = [w.coerce_row("sangvis_resolution", dict(w.blank_row("sangvis_resolution"), **r)) for r in res]
                w.put_rows(mod, "sangvis_resolution", [w.strip_row(r, "sangvis_resolution") for r in res], remove_keys=old)
            w.set_grant(mod, "sangvis", row["id"], {"id": row["id"], "max": 1} if d.get("give") else None)
        elif kind == "enemy":
            row = w.coerce_row("enemy_character_type", models.enemy_row(d, _base_row("enemy_character_type", d), w))
            w.own_texts("enemy_character_type", row, {"name": d.get("name", ""), "character": d.get("name", "")}, mod)
            _save_row(mod, mod_name, "enemy_character_type", row, d.get("copy"))
        elif kind == "ally":
            base = _base_row("ally_team", d)
            row = w.coerce_row("ally_team", models.ally_row(d, base))
            w.own_texts("ally_team", row, {"name": d.get("name", "")}, mod)
            gia = w.world_index("gun_in_ally")
            had = [gia[x] for x in str(base.get("guns") or "").split(",") if x.strip() in gia]
            was = models.ally_design(base, had, "")["members"]
            mine = w._owned_members(mod, row["id"])
            if [(m["gun"], m["level"], m["position"]) for m in was] != [(int(m.get("gun") or 0), int(m.get("level") or 100), int(m.get("position") or 0)) for m in d.get("members") or []]:
                members = models.ally_members(w, d)
                ids = [int(i) for i in mine] + w.free_ids("gun_in_ally", max(0, len(members) - len(mine)))
                rows = [w.coerce_row("gun_in_ally", dict(w.blank_row("gun_in_ally"), **m, id=i)) for m, i in zip(members, ids)]
                w.put_rows(mod, "gun_in_ally", [w.strip_row(r, "gun_in_ally") for r in rows], remove_keys=mine)
                row["guns"] = ",".join(str(r["id"]) for r in rows)
            _save_row(mod, mod_name, "ally_team", row, d.get("copy"))
        elif kind == "building":
            row = w.coerce_row("building", models.building_row(d, _base_row("building", d)))
            w.own_texts("building", row, {"name": d.get("name", ""), "des": d.get("desc", "")}, mod)
            _save_row(mod, mod_name, "building", row, d.get("copy"))
        elif kind == "team":
            levels = {int(r["level"]) for r in w.world_table("enemy_standard_attribute")}
            bad = sorted({int(m.get("level") or 0) for m in d.get("members") or []} - levels - {0})
            if bad:
                raise w.mods.ModError(f"The game has no stats for enemy level {', '.join(map(str, bad))} "
                                      f"(levels go 1–{max(l for l in levels if l < 1000)}, plus some special ones). Pick another level.")
            row, members = models.team_rows(d, _base_row("enemy_team", d))
            row = w.coerce_row("enemy_team", row)
            _save_row(mod, mod_name, "enemy_team", row, d.get("copy"))
            tid = row["id"]
            mine = {str(r["id"]) for r in mod["tables"].get("enemy_in_team", []) if int(r.get("enemy_team_id") or 0) == tid}
            theirs = {str(r["id"]) for r in w.world_table("enemy_in_team", exclude=mod_name) if r["enemy_team_id"] == tid}
            fresh = iter(w.free_ids("enemy_in_team", len(members)))
            out, kept = [], set()
            for m in members:
                mid = str(m.get("id") or "")
                if not (mid and (mid in mine or mid in theirs)) or mid in kept:
                    mid = str(next(fresh))
                kept.add(mid)
                st = w.stored_row("enemy_in_team", w.coerce_row("enemy_in_team", dict(m, id=int(mid))), None, mod_name)
                if not w.unchanged_override("enemy_in_team", st, mod_name):
                    out.append(st)
            deletes = [{"id": int(i), "_delete": True} for i in theirs if i not in kept]
            w.put_rows(mod, "enemy_in_team", out + deletes, remove_keys=mine)
        elif kind == "map":
            _check_deploy(d)
            original = str(d.get("id")) in {str(r["id"]) for r in w.base().table("mission")}
            if not original:        # a game map that is changed stays where it is in the game
                campaign(mod_name, create=True)
                mod = w.load_mod(mod_name)
            base = _base_row("mission", d) if str(d.get("id")) in w.world_index("mission") or d.get("copy") else w.blank_entity("map")["row"]
            row = w.coerce_row("mission", models.map_row(d, base))
            mid = row["id"]
            if not original:
                _place_map(mod, mid, d.get("sub"))
            w.own_texts("mission", row, {"name": d.get("name", ""), "mission_describe": d.get("subtitle", "")}, mod)
            _save_row(mod, mod_name, "mission", row, d.get("copy"))
            spots = [w.coerce_row("spot", dict({k: v for k, v in s.items() if k not in ("win", "ally_side")}, mission_id=mid))
                     for s in d.get("spots") or []]
            missing = [s for s in spots if not s["id"]]
            for s, n in zip(missing, w.free_ids("spot", len(missing))):
                s["id"] = n
            old = [r["id"] for r in mod["tables"].get("spot", []) if int(r.get("mission_id") or 0) == mid]
            others = w.world_index("spot", exclude=mod_name)
            stored = [st for st in (w.stored_row("spot", s, None, mod_name) for s in spots)
                      if not w.unchanged_override("spot", st, mod_name)]
            keep = {str(s["id"]) for s in spots}
            deletes = [{"id": int(k), "_delete": True} for k, r in others.items() if int(r["mission_id"]) == mid and k not in keep]
            w.put_rows(mod, "spot", stored + deletes, remove_keys=old)
            rules = {}
            if d.get("spawns") and (not original or d["spawns"] != _default_spawns(mid)):
                rules["spawns"] = d["spawns"]       # a game map left with its own spawns keeps following them
            if d.get("icon"):
                rules["icon"] = str(d["icon"])      # tools/build_mods.py gives the boss's icon path this image
            if str(d.get("base_ai")) in models.MAP_AI_WORDS:
                rules["default_ai"] = str(d["base_ai"])       # gfserver/missions.py enemy_behaviour
            sc = d.get("score")
            if sc and int(sc.get("defeat", sc.get("echelon_out")) or 0) != int(sc.get("echelon_out") or 0):
                rules["defeat_points"] = abs(int(sc["defeat"]))     # a lost echelon, apart from one withdrawn
            sides = {str(s["id"]): int(src["ally_side"]) for s, src in zip(spots, d.get("spots") or [])
                     if int(s.get("ally_team_id") or 0) and src.get("ally_side") not in (None, "")}
            if sides:
                rules["ally_sides"] = sides     # whose side a node's allied force is on (else its own)
            order = w.clean_move_order(d.get("move_order"), mid)
            if order:
                rules["move_order"] = order
            if rules:
                mod["meta"].setdefault("map_rules", {})[str(mid)] = rules
            else:
                (mod["meta"].get("map_rules") or {}).pop(str(mid), None)
            if not original:
                w.set_grant(mod, "missions", mid, {"id": mid} if d.get("open") else None)
        elif kind == "skill":
            group = int(d.get("group") or 0)
            old_ids = _skill_component_ids(mod, group) if group else {}
            owned = {t: {int(i) for i in ids} for t, ids in old_ids.items()}
            original = bool(group) and any(r["skill_group_id"] == group for r in w.base().table("battle_skill_config"))
            rows, group = skills.compile_tree(w, d, owned, group, original=original)
            texts = d.get("texts") or {}
            key_row = dict(rows["battle_skill_config"][-1])
            w.own_texts("battle_skill_config", key_row, texts, mod)
            # a game skill's lower levels keep their own text (it describes their own numbers)
            for r in rows["battle_skill_config"][-1:] if original else rows["battle_skill_config"]:
                for f in ("name", "description", "lvup_description"):
                    r[f] = key_row.get(f, r.get(f, ""))
            for table, lst in rows.items():
                coerced = [w.coerce_row(table, dict(w.blank_row(table), **r)) for r in lst]
                new_ids = {str(r[w.key_of(table)]) for r in coerced}
                stale = [i for i in old_ids.get(table, ()) if str(i) not in new_ids]
                w.put_rows(mod, table, [w.strip_row(r, table) for r in coerced],
                           remove_keys=stale + [r[w.key_of(table)] for r in coerced])
            d["group"] = group
        else:
            raise KeyError(kind)
        w.save_mod(mod_name, mod)
        res = w.check_mod(mod_name)
        res["id"] = d.get("group") if kind == "skill" else d.get("id")
        return res


def _save_combos(mod, d):
    """Rows for a doll's conditional skills (combos.py); their passives are added to d's skills."""
    store = mod["meta"].setdefault("combos", {})
    key = str(d["id"])
    old = store.get(key) or {}
    ids = old.get("ids") or {}
    for table in ("battle_buff", "battle_watch", "battle_watch_trigger", "battle_trigger"):
        w.put_rows(mod, table, [], remove_keys=ids.get(table) or [])
    w.put_rows(mod, "battle_skill_config", [], remove_keys=[g * 100 + lv for g in ids.get("groups") or [] for lv in range(1, 11)])
    rules = [r for r in d.get("combos") or [] if int(r.get("skill") or 0)]
    if not rules:
        store.pop(key, None)
        return
    rows, passives, made = combos.build(w, rules, ids)
    for table, lst in rows.items():
        coerced = [w.coerce_row(table, r) for r in lst]
        w.put_rows(mod, table, [w.strip_row(r, table) for r in coerced], remove_keys=[r[w.key_of(table)] for r in coerced])
    store[key] = {"rules": rules, "ids": made, "passives": passives}
    sk = d.setdefault("skills", {})
    sk["passive"] = [g for g in sk.get("passive") or [] if g not in passives] + passives


def _skill_component_ids(mod, group):
    """Ids of the component rows a mod's skill group uses (from its own rows)."""
    if not any(int(r.get("skill_group_id") or 0) == group for r in mod["tables"].get("battle_skill_config", [])):
        return {}
    tree = skills.load(w, group)
    out = {"battle_skill_config": [group * 100 + lv for lv in range(1, 11)]}
    mine = {t: {str(r.get("id")) for r in mod["tables"].get(t, [])} for t in skills.TABLES}
    for table, part in skills.PARTS.items():
        out[table] = [int(i) for i in tree.get(part) or {} if i in mine[table]]
    for table, node in (("battle_target_select_ai", tree["target"]), ("battle_action_config", tree["action"])):
        out[table] = [int(node["id"])] if node and str(node["id"]) in mine[table] else []
    my_formulas = {str(r.get("id")) for r in mod["tables"].get("battle_formula", [])}
    out["battle_formula"] = [int(i) for i in tree.get("formulas") or {} if i in my_formulas]
    return out


def delete(mod_name, kind, eid):
    if kind in content.KINDS:
        return content.delete(mod_name, kind, eid)
    with w.LOCK:
        if kind == "skill":
            mod = w.load_mod(mod_name)
            for table, ids in _skill_component_ids(mod, int(eid)).items():
                w.put_rows(mod, table, [], remove_keys=ids)
            for f in w.TEXT_FIELDS["battle_skill_config"]:
                mod["meta"]["text"].pop(w.text_key("battle_skill_config", f, int(eid) * 100 + 10), None)
            w.save_mod(mod_name, mod)
            return w.check_mod(mod_name)
        if kind == "unit":
            mod = w.load_mod(mod_name)
            _save_combos(mod, {"id": eid, "combos": []})
            w.save_mod(mod_name, mod)
            import art
            art.remove(mod_name, {"id": eid, "model": art.custom_art.new_code(eid), "slot": "all"})
        res = w.delete_entity(mod_name, kind, eid)
        if kind == "sangvis":
            mod = w.load_mod(mod_name)
            mod["tables"]["sangvis_resolution"] = [r for r in mod["tables"].get("sangvis_resolution", [])
                                                   if str(r.get("group_id")) != str(eid)]
            w.save_mod(mod_name, mod)
        return res
