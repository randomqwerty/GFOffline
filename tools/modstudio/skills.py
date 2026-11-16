"""Skill trees for Mod Studio's visual skill editor (level 10 only).

A skill is a tree of rows across the battle tables (doc/stc-guide/04-combat.md):

  battle_skill_config (one row per level)
    -> battle_trigger (conditions; also the "special numbers" conditions, sppool_trigger_id)
    -> battle_target_select_ai (who)          -> battle_buff (filter), formulas (sort keys, filter)
    -> battle_buff (on the user / the targets)
    -> battle_action_config (timeline)         -> battle_creation
  battle_creation -> battle_hurt_config (hits), battle_buff (area effects), battle_creation (follow-ups)
  battle_buff     -> battle_creation (shown while active), battle_watch (watcher), formulas (fix_damage)
  battle_watch    -> battle_watch_trigger (event condition), battle_trigger (extra conditions), skills cast
  battle_hurt_config -> battle_buff (on hit), formulas
  battle_trigger  -> battle_buff (buff checks), formula (type 18)

Most newer kits are networks: skills hand out marker buffs that other skills of the same unit
check. compile_tree() is therefore copy-on-write: a node is copied under a free id only when it was
edited (or added), or when something it refers to was copied; everything else keeps its game id, so
the links between a kit's skills keep working. Number pools (`*XY` values) stay on the skill row and
are edited there. All ten level rows get the level-10 content. Skills referenced by buffs, watchers,
hits and summons are separate skills: they are linked, not copied.
"""
import re

TABLES = ("battle_trigger", "battle_target_select_ai", "battle_buff", "battle_action_config",
          "battle_creation", "battle_hurt_config", "battle_watch", "battle_watch_trigger")
FREE_FROM = {"battle_trigger": 71000001, "battle_target_select_ai": 7000001, "battle_buff": 7000001,
             "battle_action_config": 7000001, "battle_creation": 7000001, "battle_hurt_config": 7000001,
             "battle_watch": 7000001, "battle_watch_trigger": 7000001, "battle_formula": 7000001}
PARTS = {"battle_trigger": "triggers", "battle_buff": "buffs", "battle_creation": "creations",
         "battle_hurt_config": "hurts", "battle_watch": "watches", "battle_watch_trigger": "watch_triggers"}
SINGLE = {"battle_target_select_ai": "target", "battle_action_config": "action"}
GROUP_FROM = 9000001
FORMULA_BASE = 1000000000          # a field holding 1e9 + n uses battle_formula n
POOLS = ("data_pool_1", "data_pool_2", "night_data_pool_1", "night_data_pool_2", "sp_data_pool_1", "sp_data_pool_2")
_FORMULA_REF = re.compile(r"(?<![\d.])1(\d{9})(?![\d.])")
_BUFF_IN_FORMULA = re.compile(r"((?:s|t)buffid(?:tier|number|time))\((\d+)\)")

PRESETS = [
    {"id": 0, "name": "Blank skill", "about": "No effects yet; add them yourself."},
    {"id": 100107, "name": "Self buff", "about": "Raises the user's own stats for a while (Damage Focus T)."},
    {"id": 102101, "name": "Grenade", "about": "Throws a grenade that damages enemies in an area (Hand Grenade)."},
    {"id": 102601, "name": "Aimed shot", "about": "Aims, then hits one target hard (Aimed Shot)."},
    {"id": 102401, "name": "Debuff zone", "about": "A cloud that slows enemies inside it (Smoke Grenade)."},
    {"id": 103105, "name": "Shield", "about": "Blocks incoming damage for a while (Force Shield)."},
]

# fields of a node that refer to other nodes: (field, target table, kind); kind "list" = comma list
# of ids (optionally id:stacks), "one" = a single id. Conditional ones are added in _refs().
REFS = {
    "skill": [("trigger_id", "battle_trigger", "list"), ("sppool_trigger_id", "battle_trigger", "list"),
              ("buff_id_self", "battle_buff", "list"), ("buff_id_target", "battle_buff", "list"),
              ("target_select_ai", "battle_target_select_ai", "one"), ("action_id", "battle_action_config", "one")],
    "battle_action_config": [("creation_order", "battle_creation", "list")],
    "battle_creation": [("trigger_creation_id", "battle_creation", "list"), ("hurt_id", "battle_hurt_config", "list"),
                        ("buff_id", "battle_buff", "list")],
    "battle_buff": [("trigger_creation_id", "battle_creation", "list"), ("watch_id", "battle_watch", "one")],
    "battle_hurt_config": [("buff_id_target", "battle_buff", "list"), ("buff_id_self", "battle_buff", "list"),
                           ("range_buff_target", "battle_buff", "list"), ("range_buff_self", "battle_buff", "list")],
    "battle_watch": [("watch_sp_trigger", "battle_trigger", "list"), ("activation_watch_trigger", "battle_watch_trigger", "one"),
                     ("record_watch_trigger", "battle_watch_trigger", "one")],
    "battle_trigger": [], "battle_target_select_ai": [], "battle_watch_trigger": [],
}


def _ids(value):
    """Ids in a list field like "101:1,1000:1" or "11,21,138" (stack counts dropped)."""
    out = []
    for part in str(value if value is not None else "").replace(";", ",").split(","):
        head = part.split(":")[0].strip()
        if head.lstrip("-").isdigit() and head not in ("0", "-1"):
            out.append(int(head))
    return out


def _refs(table, row):
    """[(field, target table, kind)] of a node, including the conditional buff references."""
    out = list(REFS[table])
    if table == "battle_trigger" and int(row.get("type") or 0) in (6, 7) and not int(row.get("is_buff_type") or 0):
        out.append(("buff_id", "battle_buff", "one"))
    if table == "battle_target_select_ai" and int(row.get("buff_trigger_type") or 0) in (6, 7) and not int(row.get("is_buff_type") or 0):
        out.append(("target_buff_id", "battle_buff", "one"))
    return out


def _children(table, row):
    """(target table, id) pairs a node refers to."""
    out = []
    for field, target, kind in _refs(table, row):
        ids = _ids(row.get(field)) if kind == "list" else _ids(row.get(field))[:1]
        out += [(target, str(i)) for i in ids]
    return out


def _formula_refs(table, row):
    """Formula ids a node uses: 1e9 + n anywhere, and the plain id of a formula condition."""
    found = set()
    for v in row.values():
        for m in _FORMULA_REF.finditer(str(v)):
            found.add(int(m.group(1)))
    if table == "battle_trigger" and int(row.get("type") or 0) == 18 and str(row.get("parameter") or "").strip().isdigit():
        found.add(int(row["parameter"]))
    return found


def _level10(w, group):
    rows = [r for r in w.world_table("battle_skill_config") if r["skill_group_id"] == int(group)]
    if not rows:
        raise KeyError(f"skill {group} not found")
    return max(rows, key=lambda r: r["level"])


def _walk(tree, lookup):
    """Collect every node reachable from the skill row; lookup(table, id) -> row or None."""
    found = {"target": None, "action": None, **{p: {} for p in PARTS.values()}}
    todo = [("skill", tree["row"])]
    while todo:
        table, node = todo.pop()
        for target, key in _children(table, node):
            child = lookup(target, key)
            if child is None:
                continue
            if target in SINGLE:
                if found[SINGLE[target]] is None and str(child["id"]) == key:
                    found[SINGLE[target]] = child
                    todo.append((target, child))
            elif key not in found[PARTS[target]]:
                found[PARTS[target]][key] = child
                todo.append((target, child))
    return found


def load(w, group):
    """The tree of a skill group: {"group", "row", "target", "action", "triggers", "buffs", "creations",
    "hurts", "watches", "watch_triggers", "formulas", "texts", "pools"} (rows as in the game)."""
    row = dict(_level10(w, group))
    idx = {t: w.world_index(t) for t in TABLES}
    tree = {"group": int(group), "row": row}
    tree.update(_walk(tree, lambda t, k: dict(idx[t][k]) if k in idx[t] else None))
    text = w.world_text()
    tree["texts"] = {f: w.text_of(text, row.get(f)) for f in ("name", "description", "lvup_description")}
    tree["pools"] = {f: str(row.get(f) or "") for f in POOLS}
    return attach_formulas(w, tree)


def _nodes(tree):
    """(table, row) for every node of a tree, the skill row first."""
    out = [("skill", tree["row"])]
    for table, key in SINGLE.items():
        if tree.get(key):
            out.append((table, tree[key]))
    for table, part in PARTS.items():
        out += [(table, r) for r in (tree.get(part) or {}).values()]
    return out


def _pool_formulas(pools):
    """Formula ids named in number lists: an entry "*N" is formula N."""
    found = set()
    for v in (pools or {}).values():
        for part in str(v or "").split(","):
            part = part.strip()
            if part.startswith("*") and part[1:].isdigit():
                found.add(int(part[1:]))
    return found


def attach_formulas(w, tree):
    """tree["formulas"] = {id: expression} for every formula the tree's rows and number lists use."""
    idx = w.world_index("battle_formula")
    used = _pool_formulas(tree.get("pools"))
    for table, node in _nodes(tree):
        used |= _formula_refs(table, node)
    old = tree.get("formulas") or {}
    # only formulas that exist (a large id can look like 1e9 + n without being a formula)
    tree["formulas"] = {str(i): old.get(str(i), idx[str(i)]["formula"]) for i in sorted(used)
                        if str(i) in idx or str(i) in old}
    return tree


def blank(w):
    """A new active skill that targets its user and does nothing yet."""
    row = {f: ("" if t == "string" else 0) for f, t in w.stc.schema()["battle_skill_config"][1]}
    row.update(level=10, type=1, skill_priority=2, cd_type=1, cd_time=300, start_cd_time=30, trigger_type=1,
               trigger_target=1, target_select_ai=1, action_id=400, is_cdr=1, is_switch=1, train_coin_type=3,
               daynight_only=1, interrupt_type=2, target_lost=2, code="powBuffSelf", trigger_id="0")
    idx = {t: w.world_index(t) for t in SINGLE}
    return {"group": 0, "row": row, "target": dict(idx["battle_target_select_ai"]["1"]),
            "action": dict(idx["battle_action_config"]["400"]), **{p: {} for p in PARTS.values()},
            "texts": {"name": "", "description": "", "lvup_description": ""}, "formulas": {},
            "pools": {f: "" for f in POOLS}}


def prune(tree):
    """Drop nodes nothing in the tree refers to any more (removed in the editor)."""
    def lookup(table, key):
        if table in SINGLE:
            node = tree.get(SINGLE[table])
            return node if node and str(node["id"]) == key else None
        return (tree.get(PARTS[table]) or {}).get(key)
    out = dict(tree)
    out.update(_walk(tree, lookup))
    used = _pool_formulas(tree.get("pools"))
    for table, node in _nodes(out):
        used |= _formula_refs(table, node)
    out["formulas"] = {k: v for k, v in (tree.get("formulas") or {}).items() if int(k) in used}
    return out


# ---------------------------------------------------------------------------- compiling

def _remap_list(value, mapping):
    """Rewrite ids in "a:b,c" lists, keeping stack counts and anything that is not a mapped id."""
    def fix(part):
        head, sep, rest = part.partition(":")
        h = head.strip()
        return head.replace(h, str(mapping[h])) + sep + rest if h in mapping else part
    s = str(value if value is not None else "")
    if s == "":
        return value
    out = ",".join(fix(p) for p in s.split(","))
    return int(out) if isinstance(value, int) and out.lstrip("-").isdigit() else out


def _norm(v):
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _same(a, b):
    """Rows equal, comparing values as text (the editor may send numbers as strings and back)."""
    return all(_norm(a.get(k)) == _norm(b.get(k)) for k in set(a) | set(b) if k != "id")


def compile_tree(w, tree, owned, group=None):
    """Rows for a tree: {"battle_skill_config": [10 rows], <table>: [rows]} and the group id.

    owned: {table: ids already belonging to the mod} (they keep their ids and are always written).
    A node is copied when it is new (temporary negative id), edited, or refers to something copied.
    """
    tree = prune(tree)
    group = int(group or tree.get("group") or 0)
    if not group or group < GROUP_FROM:
        group = w.free_skill_group()
    owned = {t: {str(x) for x in ids} for t, ids in owned.items()}
    nodes = {(table, str(node["id"])): node for table, node in _nodes(tree)[1:]}
    formulas = {str(k): v for k, v in (tree.get("formulas") or {}).items()}
    fidx = w.world_index("battle_formula")

    # 1. edited or new nodes and formulas
    copied = set()
    for (table, key), node in nodes.items():
        orig = w.world_index(table).get(key)
        if key.startswith("-") or orig is None or not _same(node, orig):
            copied.add((table, key))
    # (a formula missing from the game data stays a dangling reference unless the editor gave it text)
    fcopied = {k for k, expr in formulas.items()
               if (k in fidx and fidx[k].get("formula") != expr) or (k not in fidx and expr)}

    # 2. propagate upwards: whatever refers to a copied node or formula is copied too, and a formula
    #    that names a copied buff (sbuffidtier(id) ...) is copied with the new id
    changed = True
    while changed:
        changed = False
        buffs_copied = {k for (t, k) in copied if t == "battle_buff"}
        for k, expr in formulas.items():
            if k not in fcopied and any(m.group(2) in buffs_copied for m in _BUFF_IN_FORMULA.finditer(expr or "")):
                fcopied.add(k)
                changed = True
        fset = {int(x) for x in fcopied}
        for (table, key), node in nodes.items():
            if (table, key) not in copied and (any(c in copied for c in _children(table, node))
                                               or _formula_refs(table, node) & fset):
                copied.add((table, key))
                changed = True

    # 3. ids: owned nodes keep theirs, copied ones get free ids
    def allocate(table, keys, own):
        mapping, taken = {}, set(w.used_ids(table))
        nid = FREE_FROM[table]
        for key in sorted(keys, key=lambda k: (k.startswith("-"), int(k.lstrip("-")))):
            if key in own:
                mapping[key] = key
                continue
            while str(nid) in taken:
                nid += 1
            taken.add(str(nid))
            mapping[key] = str(nid)
        return mapping
    maps = {t: allocate(t, [k for (tt, k) in copied if tt == t], owned.get(t, set())) for t in TABLES}
    fmap = allocate("battle_formula", fcopied, owned.get("battle_formula", set()))

    def rewrite(table, node):
        r = dict(node)
        for field, target, kind in _refs(table, r):
            r[field] = _remap_list(r.get(field), maps[target])
        if fmap:
            for f, v in list(r.items()):
                if isinstance(v, (str, int)) and _FORMULA_REF.search(str(v)):
                    out = _FORMULA_REF.sub(lambda m: str(FORMULA_BASE + int(fmap[str(int(m.group(1)))]))
                                           if str(int(m.group(1))) in fmap else m.group(0), str(v))
                    r[f] = int(out) if isinstance(v, int) and out.lstrip("-").isdigit() else out
            if table == "battle_trigger" and int(r.get("type") or 0) == 18 and str(r.get("parameter") or "") in fmap:
                r["parameter"] = fmap[str(r["parameter"])]
        return r

    out = {t: [] for t in TABLES}
    for (table, key), node in nodes.items():
        if (table, key) in copied or key in owned.get(table, set()):
            r = rewrite(table, node)
            r["id"] = int(maps[table].get(key, key))
            out[table].append(r)
    out["battle_formula"] = [
        {"id": int(fmap.get(k, k)), "formula": _BUFF_IN_FORMULA.sub(
            lambda m: f"{m.group(1)}({maps['battle_buff'].get(m.group(2), m.group(2))})", formulas.get(k, ""))}
        for k in sorted(fcopied | (owned.get("battle_formula", set()) & set(formulas)), key=int)]

    skill = rewrite("skill", dict(tree["row"]))
    skill["trigger_id"] = skill.get("trigger_id") or "0"

    def pool(v):
        parts = str(v or "").split(",")
        return ",".join("*" + fmap[p.strip()[1:]] if p.strip().startswith("*") and p.strip()[1:] in fmap else p for p in parts) if v else v
    for f in POOLS:
        skill[f] = pool((tree.get("pools") or {}).get(f, skill.get(f, "")))
    out["battle_skill_config"] = [dict(skill, id=group * 100 + lv, skill_group_id=group, level=lv) for lv in range(1, 11)]
    return out, group


# ---------------------------------------------------------------------------- who gives a buff

_GIVERS = {}


def buff_givers(w):
    """{buff id: [skill groups that hand it out]} over every skill in the world (cached per mod state)."""
    stamp = w._stamp()
    if _GIVERS.get("stamp") == stamp:
        return _GIVERS["data"]
    creations, hurts, actions = w.world_index("battle_creation"), w.world_index("battle_hurt_config"), w.world_index("battle_action_config")
    out = {}

    def add(buff, group):
        lst = out.setdefault(str(buff), [])
        if group not in lst:
            lst.append(group)

    best = {}
    for r in w.world_table("battle_skill_config"):
        if r["skill_group_id"] not in best or r["level"] > best[r["skill_group_id"]]["level"]:
            best[r["skill_group_id"]] = r
    for g, r in best.items():
        for b in _ids(r["buff_id_self"]) + _ids(r["buff_id_target"]):
            add(b, g)
        todo, seen = list(_ids((actions.get(str(r["action_id"])) or {}).get("creation_order"))), set()
        while todo:
            c = str(todo.pop())
            if c in seen or c not in creations:
                continue
            seen.add(c)
            node = creations[c]
            for b in _ids(node.get("buff_id")):
                add(b, g)
            for hid in _ids(node.get("hurt_id")):
                hrow = hurts.get(str(hid)) or {}
                for f in ("buff_id_target", "buff_id_self", "range_buff_target", "range_buff_self"):
                    for b in _ids(hrow.get(f)):
                        add(b, g)
            todo += _ids(node.get("trigger_creation_id"))
    _GIVERS.update(stamp=stamp, data=out)
    return out
