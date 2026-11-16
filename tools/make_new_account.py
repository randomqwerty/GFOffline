"""Make data/new_account.json, the start of a new account, from a fresh account's archived replies.

  python tools/make_new_account.py <player/archive/<uid> of a new account>

Uses that folder's Index/index.json (the account), Index/getMailList.json (its inbox) and Dorm/list.json (the
starting furniture, set out in both dorms). The uid becomes the
placeholder uid (config.TEMPLATE_UID), the name and open_id are cleared so the game asks for a name, and the
tutorial progress (guide_info) is reset so it starts from the beginning. Commander exp goes back to 0, and the
starting dolls' affection to what their profile (user_friend_info team_info) recorded at creation, so tutorials
played before the fetch leave nothing behind. Times near the account's creation are moved to the moment the offline account is made (gfserver/new_account.py). The
system mails (type 6) every new account found waiting are kept; mails the server sends itself (events, sign-in)
are not.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gfserver import config, new_account  # noqa: E402

UID_KEYS = ("user_id", "uid", "f_userid")
SYSTEM_MAIL = "6"
MAIL_FIELDS = ("title", "content", "start_time", "end_time", "mp", "ammo", "mre", "part", "core", "gem",
               "item_ids", "equip_ids", "fairy_ids", "gun_id", "gift", "furniture", "coins")


def _placeholder(doc, uid):
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in UID_KEYS and str(v) == uid:
                    o[k] = config.TEMPLATE_UID if isinstance(v, int) else str(config.TEMPLATE_UID)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(doc)


def make(folder):
    folder = Path(folder)
    state = json.loads((folder / "Index" / "index.json").read_text("utf-8-sig"))
    ui = state["user_info"]
    uid, open_id, name = str(ui["user_id"]), str(ui.get("open_id") or ""), str(ui.get("name") or "")
    _placeholder(state, uid)
    ui.pop("sign", None)
    ui.update(name="", open_id="", experience="0")
    if "user_friend_info" in state:
        state["user_friend_info"]["name"] = ""
    guide = json.loads(state["guide_info"]["guide"])
    guide["course"] = [0] * len(guide.get("course") or [])
    state["guide_info"]["guide"] = json.dumps(guide, separators=(",", ":"))
    at_start = {str(g.get("id")): g.get("favor") for g in (state.get("user_friend_info") or {}).get("team_info") or []}
    start_favor = min((int(v) for v in at_start.values() if str(v).isdigit()), default=None)
    for g in state["gun_with_user_info"]:          # the starting dolls all begin alike; the profile lists only the team
        if start_favor is not None:
            g["favor"] = str(at_start.get(str(g["id"])) or start_favor)
    try:
        pieces = json.loads((folder / "Dorm" / "list.json").read_text("utf-8-sig"))["furniture_with_user_info"]
    except (OSError, ValueError, KeyError):
        pieces = []
    state["_furniture"] = [dict(f, id=str(n)) for n, f in enumerate(pieces, 1)]
    mails = []
    try:
        inbox = json.loads((folder / "Index" / "getMailList.json").read_text("utf-8-sig"))
    except (OSError, ValueError):
        inbox = []
    for m in inbox:
        if str(m.get("type")) == SYSTEM_MAIL:
            mail = {k: m[k] for k in MAIL_FIELDS if m.get(k) not in (None, "", "0", 0)}
            mail.setdefault("content", "")
            mails.append(dict(mail, id=str(len(mails) + 1), sub_id="0", type=int(SYSTEM_MAIL), if_read=False,
                              if_received=False, start_time=int(mail["start_time"]), end_time=int(mail["end_time"])))
    state["_mail"], state["_mail_next"] = mails, len(mails) + 1
    state[new_account.BASE_KEY] = int(ui["reg_time"])
    text = json.dumps(state, ensure_ascii=False)
    for word in filter(None, (uid, open_id, name)):
        if word in text:
            raise SystemExit(f"the account's {'name' if word == name else 'ids'} still appear in the result; not written")
    return state


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    state = make(sys.argv[1])
    out = ROOT / "data" / "new_account.json"
    out.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), "utf-8", newline="\n")
    print(f"wrote {out.relative_to(ROOT)}: {len(state['gun_with_user_info'])} dolls, {len(state['_furniture'])} furniture, {len(state['_mail'])} mails")


if __name__ == "__main__":
    main()
