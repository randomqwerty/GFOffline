"""Guild (Guild/*), for a mod that turns guilds on. The game never did: the client has the URLs and its chat protobufs
(ProtoMsg.C_GuildChat...), but no request class, reply handler or screen, so every body and reply here is our own choice,
for that mod's Lua to follow. Nothing has exercised them against a client.

There is one guild, kept in the save's "_guild". Nobody else is there to answer, so friends (friends.py) join as soon as
they are invited, and applications and invitations are never left pending.
  Guild/create {"name"} -> {"guild"}; refused while in a guild
  Guild/data {} -> {"guild": guild or null}
  Guild/find {"name"} -> {"list": [guild]}: the player's own, if the name is part of it
  Guild/invite {"f_userid"}, Guild/removeMember {"f_userid"}, Guild/vicePresident {"f_userid"} (toggles),
  Guild/makeOver {"f_userid"} (the player becomes a plain member) -> "1"
  Guild/rename {"name"}, Guild/updateAnnouncement {"announcement"}, Guild/updateFlag {"flag"},
  Guild/updateGuildMemberIntro {"intro"} (the player's own), Guild/updateUserLv {} (the player's level) -> "1"
  Guild/leaveGuild {}: the guild goes with its last president; Guild/dismissGuild {}: president only -> "1"
  Guild/applyForGuild, handleApply, handleInvite, impeach, recallApply, recallInvite -> "1": nothing is ever pending,
      and only the player can act
A guild's rows: {"id", "name", "announcement", "flag", "members": [{"f_userid", "name", "lv", "headpic_id", "role", "intro"}]}.
"""
from . import friends

KEY = "_guild"
MEMBER, VICE, PRESIDENT = 0, 1, 2
GUILD_ID = 1


def _me(state):
    info = state.get("user_info") or {}
    return str(info.get("user_id", ""))


def _guild(state):
    return state.get(KEY)


def _member_row(uid, row, role):
    return {"f_userid": str(uid), "name": row.get("name", ""), "lv": friends._int(row.get("lv")),
            "headpic_id": friends._int(row.get("headpic_id")), "role": role, "intro": ""}


def _member(guild, uid):
    return next((m for m in guild["members"] if m["f_userid"] == str(uid)), None)


def _in_charge(state):
    """The guild, when the player is its president or a vice president."""
    guild = _guild(state)
    if guild is None:
        return None
    me = _member(guild, _me(state))
    return guild if me and me["role"] >= VICE else None


def create(state, body):
    name = str((body or {}).get("name") or "")
    if _guild(state) is not None or not name:
        return None
    me = _member_row(_me(state), state.get("user_info") or {}, PRESIDENT)
    state[KEY] = {"id": GUILD_ID, "name": name, "announcement": "", "flag": 0, "members": [me]}
    return {"guild": state[KEY]}


def data(state, body):
    return {"guild": _guild(state)}


def find(state, body):
    guild, name = _guild(state), str((body or {}).get("name") or "")
    return {"list": [guild] if guild is not None and name in guild["name"] else []}


def invite(state, body):
    guild, fid = _in_charge(state), (body or {}).get("f_userid")
    _, row = friends._find(state, fid)
    if guild is None or row is None:
        return None
    if _member(guild, fid) is None:
        guild["members"].append(_member_row(fid, row, MEMBER))
    return "1"


def remove_member(state, body):
    guild, fid = _in_charge(state), (body or {}).get("f_userid")
    target = _member(guild, fid) if guild else None
    if target is None or target["role"] == PRESIDENT:
        return None
    guild["members"].remove(target)
    return "1"


def vice_president(state, body):
    guild, fid = _guild(state), (body or {}).get("f_userid")
    target = _member(guild, fid) if guild else None
    me = _member(guild, _me(state)) if guild else None
    if target is None or not me or me["role"] != PRESIDENT or target is me:
        return None
    target["role"] = MEMBER if target["role"] == VICE else VICE
    return "1"


def make_over(state, body):
    guild, fid = _guild(state), (body or {}).get("f_userid")
    target = _member(guild, fid) if guild else None
    me = _member(guild, _me(state)) if guild else None
    if target is None or not me or me["role"] != PRESIDENT or target is me:
        return None
    me["role"], target["role"] = MEMBER, PRESIDENT
    return "1"


def _setter(field):
    def fn(state, body):
        guild = _in_charge(state)
        if guild is None or field not in (body or {}):
            return None
        guild[field] = body[field]
        return "1"
    return fn


rename, update_announcement, update_flag = _setter("name"), _setter("announcement"), _setter("flag")


def update_intro(state, body):
    guild = _guild(state)
    me = _member(guild, _me(state)) if guild else None
    if me is None:
        return None
    me["intro"] = str((body or {}).get("intro") or "")
    return "1"


def update_level(state, body):
    guild = _guild(state)
    me = _member(guild, _me(state)) if guild else None
    if me is None:
        return None
    me["lv"] = friends._int((state.get("user_info") or {}).get("lv"))
    return "1"


def leave(state, body):
    guild = _guild(state)
    me = _member(guild, _me(state)) if guild else None
    if me is None:
        return None
    guild["members"].remove(me)
    if me["role"] == PRESIDENT or not guild["members"]:
        state[KEY] = None
    return "1"


def dismiss(state, body):
    guild = _guild(state)
    me = _member(guild, _me(state)) if guild else None
    if me is None or me["role"] != PRESIDENT:
        return None
    state[KEY] = None
    return "1"


HANDLERS = {"create": create, "data": data, "find": find, "invite": invite, "removeMember": remove_member,
            "vicePresident": vice_president, "makeOver": make_over, "rename": rename,
            "updateAnnouncement": update_announcement, "updateFlag": update_flag, "updateGuildMemberIntro": update_intro,
            "updateUserLv": update_level, "leaveGuild": leave, "dismissGuild": dismiss,
            **{name: (lambda s, b: "1") for name in ("applyForGuild", "handleApply", "handleInvite", "impeach",
                                                     "recallApply", "recallInvite")}}
