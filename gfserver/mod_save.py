"""The save and the mods that are on: what a mod gave the save (a doll, a Coalition unit, a fairy,
an item, a mission ...) refers to that mod's table rows, and once the mod is turned off or deleted
the client finds no row for it and goes wrong. So at every login, before the save goes to the client:

  * save entries whose doll, unit, fairy, equipment, item, skin or mission is in neither the tables
    in use nor the original game's are put aside in the save's "_mod_aside", with anything that
    pointed at them let go (equipment and chips back in the inventory, team and preset slots emptied);
  * entries put aside earlier whose row is back (the mod on again) return, outside any team, with
    their own level, skills and so on as they were.

Only rows no original table has are touched: the original game's data stays as it is whatever the
tables say. tools/check_save.py reports what the next login would do (after Build mods, and from
the launcher), without changing anything.
"""
import copy

from . import config, stc

# (save section, id field, table, what it is): a section is a list of records or a {record id: record} dict
SECTIONS = (
    ("gun_with_user_info", "gun_id", "gun", "T-Doll"),
    ("sangvis_with_user_info", "sangvis_id", "sangvis", "Coalition unit"),
    ("fairy_with_user_info", "fairy_id", "fairy", "fairy"),
    ("equip_with_user_info", "equip_id", "equip", "equipment"),
    ("item_with_user_info", "item_id", "item", "item"),
    ("gift_with_user_info", "item_id", "gift_item", "gift"),
    ("skin_with_user_info", "skin_id", "skin", "skin"),
    ("squad_with_user_info", "squad_id", "squad", "HOC"),
    ("mission_with_user_info", "mission_id", "mission", "mission"),
    ("gun_memoir_list", "gun_id", "gun", None),
    ("fairy_collect_info", "fairy_id", "fairy", None),
)
# records whose own "id" other entries point at; they get a new one if it was taken meanwhile
OWN_IDS = {"gun_with_user_info", "sangvis_with_user_info", "fairy_with_user_info", "equip_with_user_info",
           "squad_with_user_info"}
TEAMED = {"gun_with_user_info": ("team_id", "location", "position"), "fairy_with_user_info": ("team_id",)}
SKINNED = (("gun_with_user_info", "gun_id"), ("sangvis_with_user_info", "sangvis_id"))
ASIDE = "_mod_aside"


def _ids(table, folder):
    tid, fields = stc.schema()[table]
    path = folder / f"{tid}.stc"
    if not path.exists():
        return None
    return {int(r[fields[0][0]]) for r in stc.parse(path.read_bytes(), fields, tid)}


class Tables:
    """The ids each table has now (the tables the server uses) and in the original game."""

    def __init__(self, now_dir=None, base_dir=None):
        self.now_dir, self.base_dir = now_dir or config.STC_DIR, base_dir or config.BASE_STC_DIR
        self._now, self._base = {}, {}

    def now(self, table):
        if table not in self._now:
            if self.now_dir == config.STC_DIR:
                self._now[table] = {int(r[stc.schema()[table][1][0][0]]) for r in stc.table(table)}
            else:
                self._now[table] = _ids(table, self.now_dir) or set()
        return self._now[table]

    def base(self, table):
        if table not in self._base:
            stc._ensure_base()
            self._base[table] = _ids(table, self.base_dir)
        return self._base[table]

    def gone(self, table, unit):
        """No table in use has it and the original game never had it: a mod's row, now off."""
        unit = int(unit or 0)
        base = self.base(table)
        return unit != 0 and unit not in self.now(table) and base is not None and unit not in base


def _records(state, section):
    v = state.get(section)
    if isinstance(v, dict):
        return list(v.items())
    return [(None, r) for r in (v or []) if isinstance(r, dict)]


def _remove(state, section, key, rec):
    v = state[section]
    if isinstance(v, dict):
        v.pop(key, None)
    else:
        v.remove(rec)


def _add(state, section, rec, key, is_dict):
    if is_dict:
        state.setdefault(section, {})[key] = rec
    else:
        state.setdefault(section, []).append(rec)


def _let_go(state, section, rid):
    """Whatever pointed at record rid of section, now set aside, lets go of it."""
    if section == "gun_with_user_info":
        for e in (state.get("equip_with_user_info") or {}).values():
            if str(e.get("gun_with_user_id")) == rid:
                e["gun_with_user_id"] = "0"
        coin = state.get("team_in_coin_mission_info") or {}
        for k in [k for k, v in coin.items() if str(v.get("gun_with_user_id")) == rid]:
            coin.pop(k)
        for p in state.get("gun_preset_info") or []:
            slots = p.get("gun") or {}
            for k in [k for k, v in slots.items() if str(v).split("-")[0] == rid]:
                slots.pop(k)
        ex = state.get("_explore") or {}
        if isinstance(ex.get("guns"), list):
            ex["guns"] = [g for g in ex["guns"] if str(g) != rid]
    elif section == "sangvis_with_user_info":
        for c in state.get("sangvis_chip_with_user_info") or []:
            if str(c.get("sangvis_with_user_id")) == rid:
                c["sangvis_with_user_id"] = "0"
        for t in state.get("sangvis_team_with_user_info") or []:
            for slot in (t.get("info") or {}).values():
                if str(slot.get("sangvis_with_user_id")) == rid:
                    slot.update(sangvis_with_user_id="0", position="0")


def reconcile(state, tables=None):
    """Put aside what the mods in use no longer have; bring back what they have again.
    Returns {"aside": [(what, id)], "back": [(what, id)]}; changes state only when either is non-empty."""
    t = tables or Tables()
    aside = state.get(ASIDE) or {"records": [], "skins": [], "collected": [], "mission": None}
    kinds = {s: (field, table, what) for s, field, table, what in SECTIONS}
    out = {"aside": [], "back": []}

    # back first: a record set aside earlier whose row is there again
    keep = []
    for e in aside["records"]:
        field, table, what = kinds[e["section"]]
        rec = e["record"]
        if int(rec[field]) not in t.now(table):
            keep.append(e)
            continue
        key = e.get("key")
        if e["section"] in OWN_IDS:
            taken = {str(r.get("id")) for _, r in _records(state, e["section"])}
            if str(rec.get("id")) in taken:
                new = str(max((int(x) for x in taken if str(x).isdigit()), default=0) + 1)
                rec["id"] = new
                key = new if key is not None else None
        for f in TEAMED.get(e["section"], ()):
            rec[f] = "0"
        _add(state, e["section"], rec, key, e.get("key") is not None)
        if what:
            out["back"].append((what, int(rec[field])))
    aside["records"] = keep
    still = []
    for e in aside["skins"]:
        rec = next((r for _, r in _records(state, e["section"]) if str(r.get("id")) == e["id"]), None)
        if rec is not None and int(e["skin"]) in t.now("skin"):
            if str(rec.get("skin") or "0") == "0":
                rec["skin"] = e["skin"]
        elif rec is not None:
            still.append(e)         # (a record no longer in the save was retired: its skin goes too)
    aside["skins"] = still
    coll = state.get("sangvis_capture_collect_info")
    back = [x for x in aside["collected"] if int(x) in t.now("sangvis")]
    if back and isinstance(coll, list):
        coll += [x for x in back if x not in coll]
    aside["collected"] = [x for x in aside["collected"] if x not in back]
    m = aside.get("mission")
    if m and int(m.get("mission_id") or 0) in t.now("mission") and not state.get("_mission"):
        state["_mission"] = m
        aside["mission"] = None

    # then aside: what no table in use has (and the original game never had)
    for section, field, table, what in SECTIONS:
        for key, rec in _records(state, section):
            if not t.gone(table, rec.get(field)):
                continue
            _remove(state, section, key, rec)
            if section in OWN_IDS:
                _let_go(state, section, str(rec.get("id")))
            aside["records"].append({"section": section, "key": key, "record": copy.deepcopy(rec)})
            if what:
                out["aside"].append((what, int(rec[field])))
    for section, _ in SKINNED:
        for _, rec in _records(state, section):
            if t.gone("skin", rec.get("skin")):
                aside["skins"].append({"section": section, "id": str(rec.get("id")), "skin": str(rec["skin"])})
                rec["skin"] = "0"
                out["aside"].append(("skin", int(aside["skins"][-1]["skin"])))
    coll = state.get("sangvis_capture_collect_info")
    if isinstance(coll, list):
        gone = [x for x in coll if t.gone("sangvis", x)]
        if gone:
            state["sangvis_capture_collect_info"] = [x for x in coll if x not in gone]
            aside["collected"] += gone
    m = state.get("_mission")
    if isinstance(m, dict) and t.gone("mission", m.get("mission_id")):
        aside["mission"] = state.pop("_mission")
        out["aside"].append(("mission in progress", int(m["mission_id"])))

    if any(aside[k] for k in ("records", "skins", "collected")) or aside.get("mission"):
        state[ASIDE] = aside
    else:
        state.pop(ASIDE, None)
    return out


def describe(change):
    """Plain lines for the log and the launcher."""
    def group(pairs):
        by = {}
        for what, unit in pairs:
            by.setdefault(what, []).append(unit)
        return "; ".join(f"{len(v)} {w}{'' if len(v) == 1 else 's'} (#{', #'.join(map(str, sorted(set(v))))})"
                         for w, v in sorted(by.items()))
    lines = []
    if change["aside"]:
        lines.append("Put aside, from mods that are off or gone: " + group(change["aside"])
                     + ". They come back when the mod is on again.")
    if change["back"]:
        lines.append("Back from a mod that is on again: " + group(change["back"])
                     + " (outside any echelon).")
    return lines
