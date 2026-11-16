"""Account/save persistence: one JSON file per account under SAVE_DIR."""
import json
import secrets
import threading
import time

from . import config


class Store:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, root=config.SAVE_DIR):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "accounts.json"
        self.index = json.loads(self.index_path.read_text("utf-8")) if self.index_path.exists() else {
            "next_uid": 100001, "by_openid": {}, "by_uid": {}}

    @classmethod
    def get(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = Store()
            return cls._instance

    def _flush(self):
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.index, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.index_path)

    def account_for_openid(self, openid, template=None):
        """The account for a login key, made on first use. template "new": started from data/new_account.json;
        "perfect": the sample account cleared and filled by gfserver/perfect.py, made again when
        an older version of it made the save."""
        with self._lock:
            uid = self.index["by_openid"].get(openid)
            if uid is None:
                uid = str(self.index["next_uid"])
                self.index["next_uid"] += 1
                self.index["by_openid"][openid] = uid
                self.index["by_uid"][uid] = {"uid": uid, "openid": openid,
                                             "sign": secrets.token_hex(16), "name": ""}
                if template:
                    self.index["by_uid"][uid]["template"] = template
                self._flush()
            return dict(self.index["by_uid"][uid])

    def bind_player_file(self, openid, uid, name, sha, state):
        """Bind a login to a player's own saved account (gfserver/player.py).

        The account keeps the file's uid. Its save is created from the file the first time,
        and re-imported (after backing up the current save) whenever the file changes."""
        with self._lock:
            uid = str(uid)
            acct = self.index["by_uid"].get(uid)
            if acct is None:
                acct = {"uid": uid, "openid": openid, "sign": secrets.token_hex(16), "name": name}
                self.index["by_uid"][uid] = acct
            self.index["by_openid"][openid] = uid
            acct["openid"] = openid
            if acct.get("player_file_sha256") != sha:
                save = self._save_path(uid)
                if save.exists():
                    backup = save.with_name(f"{save.stem}.{time.strftime('%Y%m%d-%H%M%S')}.bak.json")
                    save.replace(backup)
                self._write_player(uid, state)
                acct["player_file_sha256"] = sha
                acct["name"] = name
            self._flush()
            return dict(acct)

    def set_name(self, uid, name):
        """Set the commander name; False if the uid is unknown or the name is taken."""
        with self._lock:
            accounts = self.index["by_uid"]
            if str(uid) not in accounts:
                return False
            if any(a["name"] == name and a["uid"] != str(uid) for a in accounts.values()):
                return False
            accounts[str(uid)]["name"] = name
            self._flush()
            return True

    def account(self, uid):
        acct = self.index["by_uid"].get(str(uid))
        return dict(acct) if acct else None

    # --- per-account game state (the Index/index document) ---

    def _save_path(self, uid):
        return self.root / f"{int(uid)}.json"

    def load_player(self, uid, template_path):
        """The account's Index/index state; created on first use from the template (a new account's own,
        when it is one: gfserver/new_account.py)."""
        from . import new_account, perfect
        with self._lock:
            p = self._save_path(uid)
            acct = self.index["by_uid"].get(str(uid))
            name = None
            if p.exists():
                state = json.loads(p.read_text("utf-8"))
                if (acct or {}).get("template") != "perfect" or state.get("_perfect") == perfect.VERSION:
                    return new_account.keyed(state)
                if state.get("_perfect") in perfect.UPGRADES:
                    state = perfect.upgrade(new_account.keyed(state), json.loads(template_path.read_text("utf-8")))
                    self._write_player(uid, state)
                    return state
                name = state.get("user_info", {}).get("name")
            if (acct or {}).get("template") == "new":
                template_path = new_account.template(acct)
            state = new_account.keyed(new_account.fresh(json.loads(template_path.read_text("utf-8"))))
            if (acct or {}).get("template") == "perfect":
                state = perfect.fill(state)
                if name:
                    state["user_info"]["name"] = name
            self._write_player(uid, state)
            return state

    def save_player(self, uid, state):
        with self._lock:
            self._write_player(uid, state)

    def _write_player(self, uid, state):
        p = self._save_path(uid)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), "utf-8")
        tmp.replace(p)

    def sign_for_uid(self, uid):
        acct = self.index["by_uid"].get(str(uid))
        return acct["sign"] if acct else ""
