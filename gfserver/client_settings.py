"""The player's battle tools and keys. They change the game client, not its data, so they aren't mods and need no build.

The launcher edits settings.json; at startup the server writes the result to gf_client_options.txt in the game copy, and
client_patch/00_client_options.lua reads that when the game starts.
"""
import json
from pathlib import Path

from . import config

CLIENT_OPTIONS_FILE = "gf_client_options.txt"
TOOL_SWITCHES = ("damage_log", "damage_csv", "skill_overlay", "battle_log", "simulator", "mobile_armor", "old_target_order")
SERVER_SWITCHES = ("confirm_battles",)     # read by the server as it runs (gfserver/battle_hold.py), not sent to the game
LAUNCHER_SWITCHES = {"map_ids": False, "map_buildings": True, "map_chibis": True}     # the Map tab's switches
# The simulator's settings, written only while it is on: (lowest, highest). 0 for the enemy team or the seed means unset.
SIM_NUMBERS = {"sim_enemy_team": (0, 2**31 - 1), "sim_runs": (1, 1000), "sim_seed": (0, 2**31 - 1),
               "sim_limit_drone_seconds": (1, 86400), "sim_limit_other_seconds": (1, 86400)}
SIM_SWITCHES = ("sim_no_random",)
# Time limit switch -> its seconds. The client gets one line, switch=seconds, while the switch is on.
SIM_LIMITS = {"sim_limit_drone": "sim_limit_drone_seconds", "sim_limit_other": "sim_limit_other_seconds"}
LIMIT_SECONDS = 60      # until the player picks another
DEFAULTS = {"damage_log": False, "damage_csv": False, "skill_overlay": False, "battle_log": False, "simulator": False, "mobile_armor": False, "old_target_order": False,
            "confirm_battles": False,
            "sim_enemy_team": 0, "sim_runs": 1, "sim_seed": 0, "sim_no_random": False,
            "sim_limit_drone": False, "sim_limit_drone_seconds": LIMIT_SECONDS,
            "sim_limit_other": False, "sim_limit_other_seconds": LIMIT_SECONDS,
            "custom_keys": False, "keys": {}, "account": "own", "new_account": 1, "target_practice": "",
            **LAUNCHER_SWITCHES}
ACCOUNTS = ("own", "sample", "new", "perfect")     # gfserver/new_account.py
# target_practice: enemy team ids, "1,2,3"; when set, target practice lists them in place of the saved list
# (account.target_practice_list), which stays in the save untouched.

RENAMED = {"fight_log": "battle_log"}     # in settings.json files from before the rename
RETIRED = {"sim_vehicle", "sim_vehicle_name"}     # the Mobile Armor is now chosen in the game

# (action, what it does, group, default key). Actions of one group can't share a key. The default fight keys are in
# BattleUIController$$AddKeyboardEvent and KeyCodeUtil, the story's in AVGController$$AddKeyboardEvent.
KEY_ACTIONS = (
    ("skill1", "Manual skill 1", "Fights", "Alpha1"),
    ("skill2", "Manual skill 2", "Fights", "Alpha2"),
    ("skill3", "Manual skill 3", "Fights", "Alpha3"),
    ("skill4", "Manual skill 4", "Fights", "Alpha4"),
    ("skill5", "Manual skill 5", "Fights", "Alpha5"),
    ("pause", "Pause", "Fights", "Space"),
    ("pause2", "Pause (second key)", "Fights", "Escape"),
    ("auto", "Auto skill on / off", "Fights", "BackQuote"),
    ("vehicle", "Vehicle forward (hold)", "Fights", "F"),
    ("withdraw", "Withdraw unit", "Fights", "E"),
    ("restart", "Restart fight", "Fights", "R"),
    ("story_next", "Next line", "Story scenes", "Space"),
    ("story_next2", "Next line (second key)", "Story scenes", "Return"),
)

# Unity KeyCode name -> what the screen shows
KEY_LABELS = {**{chr(c): chr(c) for c in range(ord("A"), ord("Z") + 1)},
              **{f"Alpha{n}": str(n) for n in range(10)}, **{f"Keypad{n}": f"Num {n}" for n in range(10)},
              **{f"F{n}": f"F{n}" for n in range(1, 13)},
              "Space": "SPACE", "Escape": "ESC", "Return": "ENTER", "KeypadEnter": "Num Enter", "Tab": "TAB", "Backspace": "BKSP",
              "BackQuote": "`", "Minus": "-", "Equals": "=", "LeftBracket": "[", "RightBracket": "]", "Backslash": "\\",
              "Semicolon": ";", "Quote": "'", "Comma": ",", "Period": ".", "Slash": "/",
              "UpArrow": "Up", "DownArrow": "Down", "LeftArrow": "Left", "RightArrow": "Right",
              "LeftShift": "L Shift", "RightShift": "R Shift", "LeftControl": "L Ctrl", "RightControl": "R Ctrl",
              "LeftAlt": "L Alt", "RightAlt": "R Alt", "Insert": "INS", "Delete": "DEL", "Home": "HOME", "End": "END",
              "PageUp": "PgUp", "PageDown": "PgDn"}


class SettingsError(ValueError):
    pass


def check_keys(keys):
    """Raises SettingsError on an unknown action or key, or two actions of a group on one key (defaults count)."""
    defaults = {a: (group, key) for a, _, group, key in KEY_ACTIONS}
    labels = {a: label for a, label, _, _ in KEY_ACTIONS}
    used = {}
    for action in keys:
        if action not in defaults:
            raise SettingsError(f"unknown action {action!r}")
    for action, (group, key) in defaults.items():
        key = keys.get(action) or key
        if key not in KEY_LABELS:
            raise SettingsError(f"unknown key {key!r} for {labels[action]}")
        if (group, key) in used:
            raise SettingsError(f"{KEY_LABELS[key]} is set for both {labels[used[group, key]]} and {labels[action]}")
        used[group, key] = action


def clean(settings):
    """The settings checked and complete, with keys left at their default dropped. Raises SettingsError."""
    out = {**DEFAULTS, "keys": {}}
    defaults = {a: key for a, _, _, key in KEY_ACTIONS}
    for k, v in settings.items():
        k = RENAMED.get(k, k)
        if k in RETIRED:
            continue
        if k == "keys":
            out[k] = {a: key for a, key in (v or {}).items() if key != defaults.get(a)}
        elif k in TOOL_SWITCHES or k in SERVER_SWITCHES or k in SIM_SWITCHES or k in SIM_LIMITS or k in LAUNCHER_SWITCHES or k == "custom_keys":
            out[k] = bool(v)
        elif k == "target_practice":
            ids = [x.strip() for x in str(v or "").replace(";", ",").replace(" ", ",").split(",") if x.strip()]
            bad = [x for x in ids if not x.isdigit()]
            if bad:
                raise SettingsError(f"target practice: {bad[0]!r} is not an enemy team id")
            out[k] = ",".join(dict.fromkeys(ids))
        elif k == "account":
            if v not in ACCOUNTS:
                raise SettingsError(f"account must be one of {', '.join(ACCOUNTS)}, not {v!r}")
            out[k] = v
        elif k == "new_account":
            try:
                out[k] = max(1, int(v or 1))
            except (TypeError, ValueError):
                raise SettingsError(f"new_account must be a whole number, not {v!r}")
        elif k in SIM_NUMBERS:
            lo, hi = SIM_NUMBERS[k]
            try:
                n = int(v or 0)
            except (TypeError, ValueError):
                raise SettingsError(f"{k} must be a whole number, not {v!r}")
            if n and not lo <= n <= hi:
                raise SettingsError(f"{k} must be from {lo} to {hi}")
            out[k] = n
        else:
            raise SettingsError(f"unknown setting {k!r}")
    out["sim_runs"] = out["sim_runs"] or 1
    for seconds in SIM_LIMITS.values():
        out[seconds] = out[seconds] or LIMIT_SECONDS
    check_keys(out["keys"])
    return out


def load(path=None):
    """What's saved, or the defaults when nothing is. Raises SettingsError on a damaged file."""
    f = Path(path or config.SETTINGS_FILE)
    if not f.is_file():
        return clean({})
    try:
        return clean(json.loads(f.read_text("utf-8")))
    except ValueError as e:     # also SettingsError
        raise SettingsError(f"{f.name}: {e}")


def save(settings, path=None):
    """Check and write the settings. Nothing is written when they're refused."""
    good = clean(settings)
    f = Path(path or config.SETTINGS_FILE)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(good, ensure_ascii=False, indent=1) + "\n", "utf-8")
    tmp.replace(f)
    return good


def options_text(settings):
    """The file the client reads."""
    lines = [f"{k}=1" for k in TOOL_SWITCHES if settings.get(k)]
    if settings.get("simulator"):
        lines += [f"{k}={settings[k]}" for k in SIM_NUMBERS if settings.get(k) and k not in SIM_LIMITS.values()]
        lines += [f"{k}=1" for k in SIM_SWITCHES if settings.get(k)]
        lines += [f"{k}={settings[seconds]}" for k, seconds in SIM_LIMITS.items() if settings.get(k)]
    if settings.get("custom_keys"):
        for action, key in sorted((settings.get("keys") or {}).items()):
            lines += [f"key.{action}={key}", f"label.{action}={KEY_LABELS[key]}"]
    return "".join(line + "\n" for line in lines)


def sync(game_dir=None, settings=None):
    """Write the options file into the game copy, for the next time the game starts. Returns its path when written.
    The Steam install is never written to, and nothing is written when the file is already right."""
    game = Path(game_dir or config.GAME_DIR)
    target = game / CLIENT_OPTIONS_FILE
    if not game.is_dir() or "steamapps" in str(game.resolve()).lower():
        return None
    text = options_text(clean(settings) if settings is not None else load())
    if (target.read_text("utf-8") if target.is_file() else "") == text:
        return None
    target.write_text(text, "utf-8")
    return target
