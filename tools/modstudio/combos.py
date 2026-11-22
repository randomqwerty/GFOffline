"""Conditional skills for a doll ("after it lands 5 hits, use Skill X"), built the way the game's own
kits chain their skills (e.g. skill groups 120802-120807):

  starter   passive, cast once at battle start: gives the doll a hidden effect that carries a watcher
  watcher   on each matching event (a hit landed, damage taken, its skill used) casts the counter skill
  counter   adds one stack of a hidden counter effect
  payoff    a copy of the chosen skill, triggered by "has at least N stacks"; it removes the N stacks
            (or keeps them and fires once)

The rules are kept in the mod's meta "combos" {"<doll id>": {"rules": [...], "ids": {table: [ids]}}}
so a save replaces the rows it made last time.
"""

# event -> (battle_watch.watch_trigger_type, battle_watch_trigger fields or None)
EVENTS = {
    "hit": (3, {"hurt_type": "0,1,2"}),             # lands a hit (each bullet that does damage)
    "hurt": (2, None),                              # takes damage
    "skill": (4, {"watched_skill_type": 1}),        # uses its active skill
}
# extra condition on the payoff -> battle_trigger type (target 1 = the doll itself)
ONLY_IF = {"hp_below": 2, "hp_above": 3, "chance": 11}
TRIGGER_FROM = 71000001
ONCE_CD = 9999999       # frames: a cooldown that never runs out in a battle


def _stacks_list(value):
    return [p for p in str(value or "").split(",") if p.strip() and p.split(":")[0].strip() not in ("", "0")]


class _Ids:
    """Free ids per table, reusing this doll's previous ones first so they stay stable."""

    def __init__(self, w, old):
        self.w, self.old, self.taken = w, {t: list(v) for t, v in (old or {}).items()}, {}

    def take(self, table, start=None):
        pool = self.old.get(table) or []
        if pool:
            return int(pool.pop(0))
        used = set(self.w.used_ids(table)) | self.taken.setdefault(table, set())
        i = int(start or self.w.FREE_FROM.get(table, 1))
        while str(i) in used:
            i += 1
        self.taken[table].add(str(i))
        return i

    def group(self):
        pool = self.old.get("groups") or []
        if pool:
            return int(pool.pop(0))
        groups = {int(r["skill_group_id"]) for r in self.w.world_table("battle_skill_config")}
        groups |= {int(g) for g in self.taken.setdefault("groups", set())}
        for name in self.w.all_mod_names():
            groups |= {int(r.get("skill_group_id") or 0) for r in self.w.load_mod(name)["tables"].get("battle_skill_config", [])}
        g = self.w.SKILL_GROUP_FROM
        while g in groups:
            g += 1
        self.taken["groups"].add(g)
        return g


def _skill_rows(w, group, fields, levels=range(1, 11)):
    out = []
    for lv in levels:
        r = dict(w.blank_row("battle_skill_config"))
        r.update(fields)
        r.update(id=group * 100 + lv, skill_group_id=group, level=lv)
        out.append(r)
    return out


def _base_skill(**extra):
    out = {"skill_priority": 10, "cd_type": 1, "cd_time": 1, "start_cd_time": 1, "trigger_type": 1, "trigger_target": 1,
           "target_select_ai": 1, "is_form_action": 1, "daynight_only": 1, "is_switch": 1, "train_coin_type": 1, "is_cdr": 1}
    out.update(extra)
    return out


def _buff(w, bid, **fields):
    r = dict(w.blank_row("battle_buff"))
    r.update({"id": bid, "conflict_type": bid, "max_tier": 1, "type": 501, "duration_type": 1, "duration": "-1",
              "boss_available": 1})
    r.update(fields)
    return r


def build(w, rules, old_ids=None):
    """Rows for a doll's conditional skills: ({table: [rows]}, [passive skill groups], {table: [ids]})."""
    ids = _Ids(w, old_ids)
    rows = {t: [] for t in ("battle_skill_config", "battle_buff", "battle_watch", "battle_watch_trigger", "battle_trigger")}
    passives, made = [], {t: [] for t in rows}
    made["groups"] = []
    skills = {}
    for r in w.world_table("battle_skill_config"):
        skills.setdefault(int(r["skill_group_id"]), []).append(r)
    for rule in rules or []:
        target = int(rule.get("skill") or 0)
        event = EVENTS.get(rule.get("event") or "hit")
        count = max(1, int(rule.get("count") or 1))
        if not target or target not in skills or event is None:
            continue
        holder, counter, watch = ids.take("battle_buff"), ids.take("battle_buff"), ids.take("battle_watch")
        trig = ids.take("battle_trigger", TRIGGER_FROM)
        starter, adder, payoff = ids.group(), ids.group(), ids.group()
        made["battle_buff"] += [holder, counter]
        made["battle_watch"].append(watch)
        made["battle_trigger"].append(trig)
        made["groups"] += [starter, adder, payoff]

        rows["battle_buff"].append(_buff(w, holder, watch_id=watch))
        rows["battle_buff"].append(_buff(w, counter, max_tier=max(count, 1)))     # hidden, like the game's own counters
        wrow = dict(w.blank_row("battle_watch"))
        wrow.update(id=watch, watch_trigger_type=event[0], activation_skills=str(adder), sp_skill_target="1")
        if event[1]:
            wt = ids.take("battle_watch_trigger")
            made["battle_watch_trigger"].append(wt)
            trow = dict(w.blank_row("battle_watch_trigger"))
            trow.update(event[1], id=wt)
            rows["battle_watch_trigger"].append(trow)
            wrow["activation_watch_trigger"] = wt
        rows["battle_watch"].append(wrow)
        rows["battle_skill_config"] += _skill_rows(w, starter, _base_skill(type=4, cd_time=ONCE_CD, buff_id_self=f"{holder}:1"))
        rows["battle_skill_config"] += _skill_rows(w, adder, _base_skill(type=8, buff_id_self=f"{counter}:1"))

        trows = [{"id": trig, "type": 6, "target": 1, "parameter": str(count), "buff_id": counter, "is_buff_type": 0}]
        extra = ONLY_IF.get((rule.get("only_if") or {}).get("kind") or "")
        if extra:
            t2 = ids.take("battle_trigger", TRIGGER_FROM)
            made["battle_trigger"].append(t2)
            trows.append({"id": t2, "type": extra, "target": 1, "parameter": str(int(rule["only_if"].get("value") or 0)),
                          "buff_id": 0, "is_buff_type": 0})
        for t in trows:
            rows["battle_trigger"].append(dict(w.blank_row("battle_trigger"), **t))

        repeat = rule.get("repeat", True)
        for src in sorted(skills[target], key=lambda r: r["level"]):
            r = dict(src)
            own_self = _stacks_list(r.get("buff_id_self"))
            r.update(id=payoff * 100 + int(src["level"]), skill_group_id=payoff,
                     type=2 if int(src.get("action_id") or 0) else 4,
                     trigger_id=",".join(str(t["id"]) for t in trows), trigger_type=6, trigger_target=1,
                     trigger_parameter=str(count), trigger_buff_id=counter,
                     cd_type=1, cd_time=1 if repeat else ONCE_CD, start_cd_time=1, is_manual=0,
                     buff_id_self=",".join(([f"{counter}:-{count}"] if repeat else []) + own_self))
            rows["battle_skill_config"].append(r)
        passives += [starter, payoff]
    return rows, passives, made
