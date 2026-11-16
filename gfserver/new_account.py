"""New accounts: the launcher's Account choice, and the start of a new account.

Account (settings.json "account"):
  own     your account file in player/ (gfserver/player.py); the sample account when there is none
  sample  the sample account (data/player_template.json), with most things unlocked
  new     a new account (data/new_account.json, made by tools/make_new_account.py): the game asks for a name
          (Index/getUidEnMicaQueue "is_username_exist": false, then Index/setUserName) and runs the tutorial
          from the start (guide_info all 0). "new_account" numbers it: Start over moves to the next number,
          a new uid with its own save; earlier ones are kept.
  perfect the sample account's progress with one maxed copy of every unit and everything opened (gfserver/perfect.py)

A new account's times near its creation (reg_time, recover times, the seven-day sign-in start, ...) are moved to
when it is made: every number within a day of the recorded reg_time (BASE_KEY) in the sections below.
"""
import time

from . import config

BASE_KEY = "_new_account_base"
SHIFTED = ("user_info", "user_record", "outhouse_establish_info", "commander_uniform_info", "item_with_user_info")
DAY = 86400


# Keyed by id ({"<id>": row}) once they hold anything; the live server sends them empty as [].
KEYED = ("equip_with_user_info", "skin_with_user_info", "fairy_with_user_info", "mission_key_with_user_info",
         "squad_with_user_info", "chip_with_user_info", "theater_with_user_info", "mission_guide_info",
         "vehicle_with_user_info", "vehicle_component_with_user_info")


def keyed(state):
    """Empty keyed sections as {}, so rows can be added by id."""
    for k in KEYED:
        if state.get(k) == []:
            state[k] = {}
    return state


def openid(mode, number, login_openid):
    """The account key a login maps to, or None for "own" (player file, else the login's own key)."""
    if mode == "sample":
        return f"sample:{login_openid}"
    if mode == "new":
        return f"new:{int(number or 1)}"
    if mode == "perfect":
        return "perfect"
    return None


def template(acct):
    return config.NEW_ACCOUNT_TEMPLATE if (acct or {}).get("template") == "new" else config.PLAYER_TEMPLATE


def fresh(state, now=None):
    """Move the template's creation-time numbers to now; a no-op for other templates."""
    base = state.pop(BASE_KEY, None)
    if not base:
        return state
    delta = int(now or time.time()) - int(base)

    def shift(o):
        if isinstance(o, dict):
            for k, v in o.items():
                o[k] = shift(v)
        elif isinstance(o, list):
            return [shift(x) for x in o]
        elif isinstance(o, (int, str)) and not isinstance(o, bool) and str(o).isdigit() and abs(int(o) - base) <= DAY:
            return type(o)(int(o) + delta)
        return o

    for key in SHIFTED:
        if key in state:
            state[key] = shift(state[key])
    return state
