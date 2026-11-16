"""Mod Studio designs: load, create, save and delete the simplified entries (see models.py, skills.py).

Each mod's maps are listed as one entry of the Campaign tab (mod.json "campaign", expanded by
gfserver/mods.py); a map's stage number is its place in that list.
"""
import models
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
        spots = [dict(s, win=s["id"] in wins) for s in w.world_table("spot") if s["mission_id"] == int(eid)]
        rules = ((mod or {"meta": {}})["meta"].get("map_rules") or {}).get(str(eid)) or {}
        texts = {f: w.text_of(text, row.get(f)) for f in ("name", "mission_describe")}
        open_ = mod is not None and w.get_grant(mod, "missions", eid) is not None
        d = dict(models.map_design(row, spots, rules.get("spawns", []), texts, open_), icon=rules.get("icon") or "",
                 move_order=rules.get("move_order") or {})
        return dict(d, kind=kind, **_flags(mod, "mission", eid))
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
                r["spot"] = int(remap.get(str(r["spot"]), r["spot"]))
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
        return {"stats": models.sangvis_stats(w, row, res[-1])}
    raise KeyError(kind)


def _base_row(table, design):
    """The row a design starts from: its current row, else its template, else a class default."""
    idx = w.world_index(table)
    for key in (design.get("id"), design.get("copy")):
        if key not in (None, "") and str(key) in idx:
            return dict(idx[str(key)])
    if table == "gun":
        return dict(idx[str(models.class_defaults(w, design.get("type") or 1)[1])])
    return dict(idx[{"sangvis": "1001", "enemy_character_type": "90001", "enemy_team": "1"}[table]])


def _resolution_of(row):
    return [r for r in w.world_table("sangvis_resolution") if r["group_id"] == row.get("resolution")]


# ---------------------------------------------------------------------------- save

def save(mod_name, kind, d):
    if kind in content.KINDS:
        return content.save(mod_name, kind, d)
    with w.LOCK:
        mod = w.load_mod(mod_name)
        if kind == "unit":
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
            res = [w.coerce_row("sangvis_resolution", dict(w.blank_row("sangvis_resolution"), **r)) for r in res]
            w.put_rows(mod, "sangvis_resolution", [w.strip_row(r, "sangvis_resolution") for r in res], remove_keys=old)
            w.set_grant(mod, "sangvis", row["id"], {"id": row["id"], "max": 1} if d.get("give") else None)
        elif kind == "enemy":
            row = w.coerce_row("enemy_character_type", models.enemy_row(d, _base_row("enemy_character_type", d)))
            w.own_texts("enemy_character_type", row, {"name": d.get("name", ""), "character": d.get("name", "")}, mod)
            _save_row(mod, mod_name, "enemy_character_type", row, d.get("copy"))
        elif kind == "team":
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
            campaign(mod_name, create=True)
            mod = w.load_mod(mod_name)
            base = _base_row("mission", d) if str(d.get("id")) in w.world_index("mission") or d.get("copy") else w.blank_entity("map")["row"]
            row = w.coerce_row("mission", models.map_row(d, base))
            mid = row["id"]
            _place_map(mod, mid, d.get("sub"))
            w.own_texts("mission", row, {"name": d.get("name", ""), "mission_describe": d.get("subtitle", "")}, mod)
            _save_row(mod, mod_name, "mission", row, d.get("copy"))
            spots = [w.coerce_row("spot", dict({k: v for k, v in s.items() if k != "win"}, mission_id=mid)) for s in d.get("spots") or []]
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
            if d.get("spawns"):
                rules["spawns"] = d["spawns"]
            if d.get("icon"):
                rules["icon"] = str(d["icon"])      # tools/build_mods.py gives the boss's icon path this image
            order = w.clean_move_order(d.get("move_order"), mid)
            if order:
                rules["move_order"] = order
            if rules:
                mod["meta"].setdefault("map_rules", {})[str(mid)] = rules
            else:
                (mod["meta"].get("map_rules") or {}).pop(str(mid), None)
            w.set_grant(mod, "missions", mid, {"id": mid} if d.get("open") else None)
        elif kind == "skill":
            group = int(d.get("group") or 0)
            old_ids = _skill_component_ids(mod, group) if group else {}
            owned = {t: {int(i) for i in ids} for t, ids in old_ids.items()}
            rows, group = skills.compile_tree(w, d, owned, group)
            texts = d.get("texts") or {}
            key_row = dict(rows["battle_skill_config"][-1])
            w.own_texts("battle_skill_config", key_row, texts, mod)
            for r in rows["battle_skill_config"]:
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
        res = w.delete_entity(mod_name, kind, eid)
        if kind == "sangvis":
            mod = w.load_mod(mod_name)
            mod["tables"]["sangvis_resolution"] = [r for r in mod["tables"].get("sangvis_resolution", [])
                                                   if str(r.get("group_id")) != str(eid)]
            w.save_mod(mod_name, mod)
        return res
