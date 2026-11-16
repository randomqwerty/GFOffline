"""What the launcher shows while playing: the current map, and battle results waiting for a decision.

Served on the server's own port to local callers only (app.py), as JSON:
  GET  /gfoffline/map            the map in progress: every node with its place, links, side, enemy and echelons
  GET  /gfoffline/team?id=<id>   an enemy team: combat effectiveness and members with stats at their levels
  GET  /gfoffline/chibi?kind=<kind>&code=<code>&skin=<id>   a unit's picture, {"png": base64} or {} (gfserver/chibi.py):
                                 kind gun, sangvis, squad, enemy or building
  GET  /gfoffline/battle         the battle result waiting (gfserver/battle_hold.py), or {}
  POST /gfoffline/battle         {"id", "send": true|false}
The map is the one of the account that sent the last game call. Hidden nodes are included and marked; on night
maps enemies out of the player's sight are left out, as the game shows them.
"""
import base64
import threading
import time

from . import chibi, config, factory, missions, stc, workshop
from .store import Store

LAST = {"uid": ""}
SIDES = {"1": "ours", "2": "enemy", "3": "neutral"}


def seen(uid):
    if uid:
        LAST["uid"] = str(uid)


_TEXT = {}
_text_lock = threading.Lock()


def _load_text():
    try:
        from . import game_text
        _TEXT["data"] = game_text.load()
    except Exception:
        _TEXT["data"] = {}


def text(key):
    """A game text; "" while the text bundle is still being read (the first read parses it: seconds), or when it can't be."""
    if "data" not in _TEXT and _text_lock.acquire(blocking=False):
        threading.Thread(target=lambda: (_load_text(), _text_lock.release()), daemon=True).start()
    return (_TEXT.get("data") or {}).get(str(key), "")


def _ints(value):
    return [int(x) for x in str(value or "").replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()]


def _units(coll):
    return list(coll.values()) if isinstance(coll, dict) else list(coll or [])


def _member(name, life, full, res, res_full, extra=None):
    status = [w for w, bad in (("down", int(life) <= 0), ("no ammo", res["ammo"] <= 0), ("no rations", res["mre"] <= 0)) if bad]
    return dict({"name": name, "hp": int(life), "max_hp": int(full), "ammo": res["ammo"], "max_ammo": res_full[0],
                 "rations": res["mre"], "max_rations": res_full[1], "status": status}, **(extra or {}))


def _echelon(state, m, team):
    guns = factory.guns()
    members = []
    for g in sorted(missions._team_guns(state, team), key=lambda g: int(g.get("location") or 9)):
        row = guns.get(int(g["gun_id"]), {})
        members.append(_member(text(row.get("name")) or str(row.get("code") or g["gun_id"]), g.get("life") or 0,
                               workshop.max_life(state, "gun", g), missions._res(state, m, "gun", g["id"]),
                               missions._full(m, "gun", g["id"], g), {"code": row.get("code") or "", "skin": int(g.get("skin") or 0)}))
    lead = next((x for x in members if x["code"]), None)
    return {"kind": "echelon", "id": str(team), "label": f"Echelon {team}", "short": str(team), "members": members,
            "picture": {"kind": "gun", "code": lead["code"], "skin": lead["skin"]} if lead else None}


def _coalition(state, m, team):
    owned = {str(u["id"]): u for u in _units(state.get("sangvis_with_user_info"))}
    rows = {int(r["id"]): r for r in stc.table("sangvis")}
    rec = next((t for t in _units(state.get("sangvis_team_with_user_info")) if str(t.get("team_id")) == str(team)), {})
    res, full = missions._res(state, m, "sangvis", team), missions._full(m, "sangvis", team, rec)
    members = []
    for slot in sorted((rec.get("info") or {}).values(), key=lambda x: int(x.get("position") or 0)):
        u = owned.get(str(slot.get("sangvis_with_user_id")))
        if u is not None:
            row = rows.get(int(u["sangvis_id"]), {})
            members.append(_member(text(row.get("name")) or str(row.get("code") or u["sangvis_id"]), u.get("life") or 0,
                                   workshop.max_life(state, "sangvis", u), res, full))
    lead = next((owned.get(str(x.get("sangvis_with_user_id"))) for k, x in sorted((rec.get("info") or {}).items(), key=lambda kv: int(kv[0]))
                 if str(x.get("sangvis_with_user_id") or "0") != "0"), None)
    code = str(rows.get(int(lead["sangvis_id"]), {}).get("code") or "") if lead else ""
    return {"kind": "coalition", "id": str(team), "label": f"Coalition {team}", "short": f"C{team}", "members": members,
            "picture": {"kind": "sangvis", "code": code, "skin": 0} if code else None}


def _squad(state, m, inst):
    uid = missions._squad_uid(m, inst)
    q = next((u for u in _units(state.get("squad_with_user_info")) if str(u.get("id")) == str(uid)), {})
    row = {int(r["id"]): r for r in stc.table("squad")}.get(int(q.get("squad_id") or 0), {})
    full_hp = max(int(q.get("life") or 0), int((state.get("_max_life") or {}).get(f"squad:{uid}") or 0))
    member = _member(text(row.get("name")) or str(row.get("code") or "HOC"), q.get("life") or 0, full_hp,
                     missions._res(state, m, "squad", uid), missions._full(m, "squad", uid, q))
    code = str(row.get("code") or "")
    return {"kind": "squad", "id": str(inst), "label": member["name"], "short": "H", "members": [member],
            "picture": {"kind": "squad", "code": code, "skin": 0} if code else None}


def _enemy_picture(team):
    """The picture of an enemy team: its leader's chibi (else its first member's)."""
    t = missions._enemy_teams().get(int(team or 0))
    if t is None:
        return None
    types = missions._character_types()
    lead = types.get(int(t.get("enemy_leader") or 0))
    if lead is None:
        first = next((r for r in stc.table("enemy_in_team") if int(r["enemy_team_id"]) == int(team)), None)
        lead = types.get(int(first["enemy_character_type_id"])) if first else None
    code = str((lead or {}).get("code") or "")
    return {"kind": "enemy", "code": code, "skin": 0} if code else None


def _vehicle(state, m, vid):
    v = next((u for u in _units(state.get("vehicle_with_user_info")) if str(u.get("id")) == str(vid)), {})
    rows = {int(r["id"]): r for r in stc.table("vehicle")}
    row = rows.get(int(v.get("vehicle_id") or 0), {})
    full_hp = max(int(v.get("life") or 0), int((state.get("_max_life") or {}).get(f"vehicle:{vid}") or 0))
    member = _member(text(row.get("name")) or "Armor", v.get("life") or 0, full_hp, missions._res(state, m, "vehicle", vid),
                     missions._full(m, "vehicle", vid, v))
    return {"kind": "vehicle", "id": str(vid), "label": member["name"], "short": "V", "members": [member]}


def _sighted(state, m):
    """On a night map, the spots whose enemies the player sees (in sight, or followed since); None: all of them."""
    if not missions.is_night(m["mission_id"]):
        return None
    seen, known = missions.visible_spots(state, m), m.get("known") or {}
    return {int(s["spot_id"]) for s in m["spots"] if int(s["spot_id"]) in seen
            or str(s.get("enemy_instance_id") or "0") != "0" and known.get(s["enemy_instance_id"]) == int(s["spot_id"])}


def chibi_view(code, skin=0, kind="gun"):
    data = chibi.png(code, int(skin or 0), kind)
    return {"png": base64.b64encode(data).decode("ascii")} if data else {}


def map_view():
    uid = LAST["uid"]
    if not uid:
        return {"mission": None}
    state = Store.get().load_player(uid, config.PLAYER_TEMPLATE)
    m = state.get("_mission")
    if not m or not m.get("spots"):
        return {"mission": None}
    mid = int(m["mission_id"])
    row = missions._missions().get(mid, {})
    live = {int(s["spot_id"]): s for s in m["spots"]}
    teams = {}
    for team, sid in (m.get("team_pos") or {}).items():
        teams.setdefault(int(sid), []).append(_echelon(state, m, team))
    for team, sid in (m.get("sangvis_pos") or {}).items():
        if missions._own_sangvis(team):
            teams.setdefault(int(sid), []).append(_coalition(state, m, team))
    for vid, sid in (m.get("vehicle_pos") or {}).items():
        teams.setdefault(int(sid), []).append(_vehicle(state, m, vid))
    for inst, q in (m.get("squads") or {}).items():
        teams.setdefault(int(q["spot"]), []).append(_squad(state, m, inst))
    for sid in missions._friend_spots(m):
        teams.setdefault(int(sid), []).append({"kind": "friend", "id": "", "label": "Friend's echelon", "short": "F", "members": []})
    sighted = _sighted(state, m)
    buildings, down = m.get("buildings") or {}, {str(x) for x in m.get("buildings_down") or []}
    forces = {}
    for iid, a in (m.get("allies") or {}).items():
        enemy = a.get("enemy", missions._ally_teams().get(a["ally_team_id"], {}).get("enemy_team_id"))
        forces.setdefault(int(a["spot"]), []).append({"force": int(a["ally_team_id"]), "side": "allied" if int(a["belong"]) == 1 else "other",
                                                       "enemy_team": int(enemy or 0), "picture": _enemy_picture(enemy)})
    nodes = []
    for r in missions._spots_by_mission().get(mid, []):
        sid = int(r["id"])
        s = live.get(sid, {})
        team = int(s.get("enemy_team_id") or 0) if str(s.get("enemy_instance_id") or "0") != "0" else 0
        shown = forces.get(sid, [])
        if sighted is not None and sid not in sighted:
            team, shown = 0, [f for f in shown if f["side"] == "allied"]
        b =buildings.get(str(sid)) if isinstance(buildings.get(str(sid)), dict) else {}
        brow = missions._buildings().get(int(b.get("building_id") or 0), {})
        nodes.append({"id": sid, "x": int(r["coordinator_x"]), "y": int(r["coordinator_y"]), "links": _ints(r["route"]),
                      "type": int(r["type"]), "side": SIDES.get(str(s.get("belong")), "hidden" if missions._hidden(s) else "neutral"),
                      "hidden": missions._hidden(s), "enemy_team": team, "boss_hp": int(s.get("boss_hp") or 0),
                      "echelons": teams.get(sid, []), "forces": shown,
                      "enemy_picture": _enemy_picture(team) if team else None,
                      "building": int(b.get("building_id") or 0), "building_name": text(brow.get("name")) if b else "",
                      "building_picture": {"kind": "building", "code": str(brow.get("code") or ""), "skin": 0} if brow.get("code") else None,
                      "building_side": SIDES.get(str(b.get("belong")), "neutral") if b else "", "building_down": str(sid) in down})
    return {"mission": mid, "name": text(row.get("name")), "night": sighted is not None, "turn": int(m.get("turn") or 1), "ap": int(m.get("ap") or 0),
            "updated": int(time.time()), "nodes": nodes}


def team_view(team_id):
    team_id = int(team_id or 0)
    team = missions._enemy_teams().get(team_id)
    if team is None:
        return {"team": team_id, "found": False}
    uid = LAST["uid"]
    m = (Store.get().load_player(uid, config.PLAYER_TEMPLATE).get("_mission") or {}) if uid else {}
    extra = missions._turn_levels(team_id, m.get("turn") or 1)
    members = []
    for r in stc.table("enemy_in_team"):
        if int(r["enemy_team_id"]) != team_id:
            continue
        ct = missions._character_types().get(int(r["enemy_character_type_id"]))
        if ct is None:
            continue
        lv = int(r.get("level") or 0) + extra
        stat = lambda k: missions._enemy_attribute(ct, k, lv)
        members.append({"id": int(ct["id"]), "name": text(ct.get("name")) or str(ct.get("code") or ct["id"]),
                        "leader": int(team.get("enemy_leader") or 0) == int(ct["id"]), "level": lv, "number": int(r.get("number") or 1),
                        "hp": round(stat("maxlife")), "damage": stat("pow"), "rate": stat("rate"), "accuracy": stat("hit"),
                        "evasion": stat("dodge"), "armor": stat("armor"), "range": int(ct.get("range") or 0),
                        "speed": int(ct.get("speed") or 0), "boss_hp": int(ct.get("boss_hp") or 0)})
    return {"team": team_id, "found": True, "ce": missions._enemy_team_strength(team_id, extra), "level_bonus": extra,
            "ai": int(team.get("ai") or 0), "members": members}
