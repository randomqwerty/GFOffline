"""Game API handlers, keyed by the client's functionName (e.g. "Index/version").

A handler receives a Request and returns a Response. Unknown functions fall through
to app.py, which logs the decrypted payload so the next handler can be written from it.
"""
import datetime
import json
import logging
import time
from dataclasses import dataclass, field

from . import (account, attendance, client_settings, base, battlepass, bingo, breakout, carnival, chess, config, crypto, events, factory, formation, friends, gashapon, guilds, gray_zone, inventory,
               missions, mod_save, mods, player, quests, recruit, returnback, sangvis_sim, squads, stc, theater, trial, upgrades, workshop)
from .store import Store

log = logging.getLogger("gfserver.handlers")
HANDLERS = {}


def handler(name):
    def wrap(fn):
        HANDLERS[name] = fn
        return fn
    return wrap


@dataclass
class Request:
    function: str
    form: dict
    body: object            # decrypted outdatacode, parsed as JSON when possible
    uid: str
    sign: str               # session key, "" before login


@dataclass
class Response:
    """kind: "plain" (sent as-is), "json" (encrypted+gzip with key), or "error" (error:N)."""
    kind: str
    payload: object
    key: str = ""
    headers: dict = field(default_factory=dict)

    def encode(self):
        if self.kind == "plain":
            return self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)
        if self.kind == "error":
            return f"error:{self.payload}"
        text = json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))
        return crypto.encode_gzip(text, self.key)


# The live EN server rolls the day over at 00:00 UTC-8 all year (its tomorrow_zero and
# month_zero land on 08:00 UTC even during daylight saving), despite timezone "PST8PDT".
SERVER_DAY_TZ = datetime.timezone(datetime.timedelta(hours=-8))


def _server_clock():
    now = int(time.time())
    local = datetime.datetime.fromtimestamp(now, SERVER_DAY_TZ)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    next_month = (month + datetime.timedelta(days=32)).replace(day=1)
    return {"now": now, "tomorrow_zero": int((day + datetime.timedelta(days=1)).timestamp()),
            "month_zero": int(month.timestamp()), "next_month_zero": int(next_month.timestamp()),
            "weekday": local.isoweekday()}


@handler("Index/version")
def index_version(req: Request) -> Response:
    # Parsed directly as JSON by RequestIndexVersion$$SuccessHandleData. Field set and value
    # types mirror the archived live response; only the clock fields are recomputed.
    clock = _server_clock()
    resp = dict(config.LIVE_VERSION) or {"timezone": config.TIMEZONE, "is_kick": "0"}
    resp.update({
        "now": str(clock["now"]),
        "tomorrow_zero": str(clock["tomorrow_zero"]),
        "month_zero": clock["month_zero"],
        "next_month_zero": clock["next_month_zero"],
        "weekday": clock["weekday"],
        "data_version": config.DATA_VERSION,
        "client_version": config.CLIENT_VERSION,
        "ab_version": config.AB_VERSION,
    })
    return Response("plain", resp)


def _login(openid: str) -> Response:
    # The launcher's Account choice (gfserver/new_account.py): your account file in player/ when there is one,
    # the sample account, or a new account.
    openid = openid or "offline"
    from . import client_settings, new_account
    try:
        chosen = client_settings.load()
    except client_settings.SettingsError:
        chosen = client_settings.clean({})
    key = new_account.openid(chosen["account"], chosen["new_account"], openid)
    path = player.find_file() if key is None else None
    if key is not None:
        account = Store.get().account_for_openid(key, chosen["account"] if chosen["account"] in ("new", "perfect") else None)
    elif path is not None:
        try:
            state, uid, name, sha = player.read(path)
            account = Store.get().bind_player_file(openid, uid, name, sha, state)
            log.info("login bound to player file %s (uid %s)", path.name, uid)
        except player.PlayerFileError as e:
            log.error("ignoring player file: %s", e)
            account = Store.get().account_for_openid(openid)
    else:
        account = Store.get().account_for_openid(openid)
    return Response("json", {
        "uid": account["uid"],
        "sign": account["sign"],
        "is_username_exist": bool(account.get("name")),
    }, key=config.PRELOGIN_KEY)


@handler("Index/setUserName")
def set_user_name(req: Request) -> Response:
    # LoginController$$RequestSetUserNameHandle: plain "1" = success, "error:9" = name rejected.
    name = (req.body or {}).get("name", "").strip() if isinstance(req.body, dict) else ""
    if not name or not Store.get().set_name(req.uid, name):
        return Response("error", 9)
    return Response("plain", "1")


def _fill_uid(doc, uid):
    """Replace the placeholder uid (templates, imported responses) with the account's uid."""
    uid = int(uid)

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("user_id", "uid", "f_userid") and str(v) == str(config.TEMPLATE_UID):
                    o[k] = uid if isinstance(v, int) else str(uid)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(doc)
    return doc


def _personalize(state, acct):
    """Put the account's identity into an Index/index document (template uses placeholders)."""
    _fill_uid(state, acct["uid"])
    name = acct.get("name") or "Commander"
    state["user_info"]["name"] = name
    state["user_info"]["sign"] = acct["sign"]
    state["user_info"]["open_id"] = acct.get("openid", "")
    if "user_friend_info" in state:
        state["user_friend_info"]["name"] = name
    return state


@handler("Index/index")
def index_index(req: Request) -> Response:
    # Full player state, requested by LoginController.PreRequestIndex with {"time", "furniture_data"}.
    store = Store.get()
    acct = store.account(req.uid)
    if acct is None:
        return Response("error", 3)
    with store.editing(req.uid):
        return _index_reply(req, store, acct)


def _index_reply(req, store, acct):
    state = _personalize(store.load_player(req.uid, config.PLAYER_TEMPLATE), acct)
    if not state.get("_mission"):
        # a map left open on the live server (an account file's mission_act_info / spot_act_info):
        # this server never ran it, so every call on it fails (a Gray Zone battleFinish: error:1).
        # Dropped; the map is started again. This server's own open map comes from resume_info.
        for k in ("mission_act_info", "spot_act_info"):
            state.pop(k, None)
    attendance._migrate(state.setdefault("user_record", {}))   # next sign-in time, before the client reads it
    returnback.on_login(state)
    carnival.check(state)
    sangvis_sim.daily_energy(state)
    for sp in (False, True):
        workshop.produce_counts(state, sp)       # the week's free targeted builds, refilled on Mondays
    workshop.settle_quick_fairies(state)
    state.pop("_energy_unsent", None)      # this reply is the client's whole copy
    for line in mod_save.describe(mod_save.reconcile(state)):    # mods turned off or on since
        log.info("your save: %s", line)
    granted = mods.apply_grants(state, req.uid)
    if granted:
        log.info("mod grants added to the save: %s", granted)
    store.save_player(req.uid, state)
    # "_" keys are the server's own bookkeeping (e.g. "_mission"), not client data.
    reply = {k: v for k, v in state.items() if not k.startswith("_")}
    # Without this key the client never makes GameData.autoPlanSettinData (GameData.ReadUserInfo), and the
    # formation screen crashes on return (FormationController.CheckAutoPlanState); null makes an empty one.
    reply.setdefault("automission_presets_info", None)
    reply["dorm_rest_friend_build_coin_count"] = friends.batteries_left(state)
    if "mission_event_info" in reply:
        reply["mission_event_info"] = missions.event_info(reply["mission_event_info"])
    try:
        targets = account.target_practice_list(state, client_settings.load()["target_practice"])
    except client_settings.SettingsError:
        targets = None
    if targets is not None:
        reply["targettrain_collect_user_info"] = targets      # the launcher's list; the saved one is kept
    resume = missions.resume_info(state)          # a mission left open when the game closed
    if resume:
        store.save_player(req.uid, state)
        reply.update(resume)
    return Response("json", reply, key=req.sign)


def _with_state(req, change):
    """Load the account's save, apply change(state) -> reply, write the save back."""
    store = Store.get()
    with store.editing(req.uid):
        return _change_state(req, store, change)


def _change_state(req, store, change):
    state = store.load_player(req.uid, config.PLAYER_TEMPLATE)
    if (state.get("_mission") or {}).get("resume_sent"):
        state["_mission"]["resume_seen"] = True       # the login that sent it back was read (missions.resume_info)
    reply = change(state)
    if (isinstance(reply, dict) and "type5_score" not in reply and str(req.function).startswith("Mission/")
            and state.get("_mission") and missions.score_rule(state["_mission"]["mission_id"]) is not None):
        # every map reply on a score map carries the score, so points show the moment they're
        # made (player report: Mistbuster's Iaso's Box, defused by buildingSkillPerform, showed its
        # 50000 only at the next move)
        reply["type5_score"] = 0
    if isinstance(reply, dict) and "type5_score" in reply:
        # a score map's running score (missions.score_rule); string where the reply had a string
        score = missions.current_score(state)
        reply["type5_score"] = str(score) if isinstance(reply["type5_score"], str) else score
    quests.on_call(state, req.function, req.body, reply)   # daily/weekly/career progress
    carnival.check(state)                                  # carnival rewards go out by mail
    store.save_player(req.uid, state)
    return reply


def _json_or_plain(req, reply):
    if reply is None:
        return Response("error", 1)
    return Response("plain", reply) if isinstance(reply, str) else Response("json", reply, key=req.sign)


@handler("Gun/developGun")
def gun_develop(req: Request) -> Response:
    return _json_or_plain(req, _with_state(req, lambda s: factory.develop(s, req.uid, req.body)))


@handler("Gun/quickDevelop")
def gun_quick_develop(req: Request) -> Response:
    return _json_or_plain(req, _with_state(req, lambda s: factory.quick_develop(s, req.body)))


@handler("Gun/finishDevelop")
def gun_finish_develop(req: Request) -> Response:
    return _json_or_plain(req, _with_state(req, lambda s: factory.finish_develop(s, req.uid, req.body)))


@handler("Gun/finishAllDevelop")
def gun_finish_all_develop(req: Request) -> Response:
    return _json_or_plain(req, _with_state(req, lambda s: factory.finish_all_develop(s, req.uid, req.body)))


@handler("Gun/retireGun")
def gun_retire(req: Request) -> Response:
    return _json_or_plain(req, _with_state(req, lambda s: factory.retire(s, req.body)))


@handler("Gun/developMultiGun")
def gun_develop_multi(req: Request) -> Response:
    return _json_or_plain(req, _with_state(req, lambda s: factory.batch_develop(s, req.uid, req.body)))


@handler("Gun/developCollectList")
def gun_develop_collect_list(req: Request) -> Response:
    # Production log (recent rare builds server-wide); nothing to show offline.
    return Response("json", {"log_list": []}, key=req.sign)


def _state_handler(name, fn):
    """Register a handler that applies fn(state, body) to the save; fn returns the reply
    ("1"/dict/list) or None for an invalid request (sent as error:1)."""
    def h(req: Request) -> Response:
        return _json_or_plain(req, _with_state(req, lambda s: fn(s, req.body)))
    HANDLERS[name] = h


_state_handler("Fairy/retireFairy", inventory.retire_fairy)
_state_handler("Gun/wishGunDevelop", lambda s, b: factory.wish_develop(s, s["user_info"].get("user_id", ""), b))
_state_handler("Vehicle/disassembleComponent", inventory.disassemble_component)
_state_handler("Gun/combineGun", inventory.combine_gun)
_state_handler("Gun/skillUpgrade", inventory.skill_upgrade)
_state_handler("Gun/finishUpgrade", inventory.finish_upgrade)
_state_handler("Gun/quickUpgrade", inventory.finish_upgrade)
_state_handler("Operation/finishOperation", missions.finish_operation)
_state_handler("Automission/finishAutomission", missions.finish_automission)
_state_handler("Mission/startMission", missions.start_mission)
_state_handler("Mission/abortMission", missions.abort_mission)
_state_handler("Mission/teamMove", missions.team_move)
_state_handler("Mission/battleFinish", missions.battle_finish)
_state_handler("Mission/endTurn", missions.end_turn)
_state_handler("Mission/startEnemyTurn", missions.start_enemy_turn)
_state_handler("Mission/enemyTurnMove", missions.enemy_turn_move)
_state_handler("Mission/endEnemyTurn", missions.end_enemy_turn)
_state_handler("Mission/startTurn", missions.start_turn)
_state_handler("Mission/withdrawTeam", missions.withdraw_team)
_state_handler("Mission/supplyTeam", missions.supply_team)
_state_handler("Mission/reinforceTeam", missions.reinforce_team)
_state_handler("Mission/sangvisMove", missions.sangvis_move)


# Handlers mapped from the client's request builders whose bodies have not been seen live yet:
# the first few bodies of each are kept in logs/new_endpoints.jsonl so the parsing can be
# checked after a playtest. A "1"-reply endpoint whose body could not be used still answers
# "1" (the client already applied the change) and is marked "unparsed" there.
_NEW_SEEN = {}


def _new_handler(name, fn, plain=False):
    def h(req: Request) -> Response:
        reply = _with_state(req, lambda s: fn(s, req.body))
        n = _NEW_SEEN[name] = _NEW_SEEN.get(name, 0) + 1
        if n <= 5 or reply is None:
            config.LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(config.LOG_DIR / "new_endpoints.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": int(time.time()), "function": name, "body": req.body,
                                    "unparsed": reply is None}, ensure_ascii=False) + "\n")
        if reply is None and plain:
            reply = "1"
        return _json_or_plain(req, reply)
    HANDLERS[name] = h


for _name, _fn in {
    "Gun/teamGun": formation.team_gun, "Gun/setPosition": formation.set_position,
    "Gun/teamGuns": formation.team_guns, "Gun/exchangeTeam": formation.exchange_team,
    "Gun/quickTeam": formation.quick_team, "Equip/gunEquip": formation.gun_equip,
    "Equip/unequip": formation.unequip, "Fairy/teamFairy": formation.team_fairy,
    "Sangvis/teamSangvis": formation.team_sangvis, "Sangvis/setPosition": formation.sangvis_set_position,
    "Gun/changeLock": formation.gun_lock, "Equip/changeLock": formation.equip_lock,
    "Fairy/changeLock": formation.fairy_lock, "Sangvis/changeLock": formation.sangvis_lock,
    "Gun/fixGuns": workshop.fix_guns, "Gun/fixFinish": workshop.fix_finish, "Gun/quickFix": workshop.fix_finish,
    "Sangvis/fix": workshop.fix_sangvis, "Sangvis/fixFinish": workshop.fix_finish,
    "Index/quickFix": workshop.quick_fix_all, "Equip/quickDevelop": workshop.equip_quick_develop,
    "Equip/retire": workshop.retire_equip, "Sangvis/retireSangvis": workshop.retire_sangvis,
    "Fairy/skillUpgrade": workshop.fairy_skill_upgrade,
    # account
    "Index/modName": account.mod_name, "Index/adjutant": account.adjutant,
    "Commander/changeGender": account.change_gender, "Commander/changeDressed": account.change_dressed,
    "Commander/changeEmoji": account.change_emoji, "Commander/savePreset": account.save_preset,
    "Commander/usePreset": account.use_preset, "Index/gameSetting": account.game_setting,
    "Mission/autoMissionPresets": account.auto_mission_presets, "Mission/pauseTurnTime": lambda s, b: "1",
    "Mission/guide": lambda s, b: "1", "Gun/like": account.gun_like,     # Gun/like counts for the "like" daily
    "Index/setMailLock": quests.set_mail_lock, "Squad/dataChange": squads.data_change,
    "Manual/like": account.manual_like, "Dorm/skinRead": account.skin_read, "Dorm/set_notice": account.dorm_set_notice,
    "Dorm/spare_exchange": account.spare_exchange,
    # the player's own settings for visitors (RequestSetFriendDorm, RequestSetFriendMedal check "1")
    "Friend/setDorm": lambda s, b: s.__setitem__("_friend_dorm", (b or {}).get("dorm_id")) or "1",
    "Friend/setMedalIsVisible": account.set_medal_visible, "Friend/setCard": account.set_card,
    "Friend/setIntro": account.set_intro, "Friend/setMedal": account.set_medal,
    # friend list changes and team sharing: nobody to apply to, nothing to keep (each checks "1")
    "Friend/add": friends.add, "Friend/apply": friends.apply, "Friend/applyCancel": lambda s, b: "1",
    "Friend/comment": lambda s, b: "1", "Friend/delete": friends.delete, "Friend/dormGoaway": lambda s, b: "1",
    "Friend/refuse": lambda s, b: "1", "Friend/refuseall": lambda s, b: "1", "Friend/messagedel": lambda s, b: "1",
    "Sangvis/duplicateAward": sangvis_sim.choose_award, "Gun/applyShareTeam": lambda s, b: "1", "Returnback/lookVideo": lambda s, b: "1", "Sangvis/applyShareTeam": lambda s, b: "1",
    "Dorm/shareRed": lambda s, b: "1",              # ReqeustDrawSharePrize: the client adds the share prize
    "Commander/unClockEffect": lambda s, b: "1",    # RequestUnLockCommanderEffect only logs success
    "Index/logCheatContent": lambda s, b: "1",      # the client's own anti-cheat log (ConnectionController$$SendLog)
    "Sangvis/developChip": upgrades.sangvis_develop_chip, "Sangvis/trans": upgrades.sangvis_transfer,
    "Dorm/squadGuideFinish": account.squad_guide_finish,
    # unit upgrades and looks
    "Equip/resumeAdjust": upgrades.equip_resume_adjust, "Fairy/adjustConfirm": upgrades.fairy_adjust_confirm,
    "Fairy/modUpdate": upgrades.fairy_mod, "Sangvis/resolution": upgrades.sangvis_resolution,
    "Sangvis/skillUpgrade": upgrades.sangvis_skill_upgrade, "Sangvis/finishUpgrade": inventory.finish_upgrade,
    "Gun/setCollect": upgrades.set_collect, "Fairy/setCollect": upgrades.set_collect,
    "Sangvis/setCollect": upgrades.set_collect, "Dorm/changeSkin": upgrades.gun_skin,
    "Fairy/changeSkin": upgrades.fairy_skin, "Sangvis/changeSkin": upgrades.sangvis_skin,
    "Sangvis/setSign": upgrades.sangvis_sign, "Gun/onSpecialEffect": upgrades.gun_effect_on,
    "Gun/offSpecialEffect": upgrades.gun_effect_off, "Sangvis/setSpecialEffect": upgrades.sangvis_effect,
    "Gun/preset": formation.save_gun_preset, "Gun/presetToTeam": formation.gun_preset_to_team,
    "Equip/preset": formation.save_equip_preset, "Sangvis/presetToTeam": formation.team_sangvis,
    "Chip/changeLock": upgrades.squad_chip_lock, "Sangvis/equipChip": upgrades.sangvis_equip_chip,
    "Squad/finishSkill": upgrades.squad_finish_skill, "Squad/quickSkill": upgrades.squad_finish_skill,
    "Dorm/kalinaFavor": lambda s, b: "1", "Index/noticeRead": lambda s, b: "1", "Manual/view": lambda s, b: "1",
    "Explore/setTeam": account.explore_set_team, "Explore/setItem": account.explore_set_item,
    "Explore/cancel": account.explore_cancel, "Index/tips": lambda s, b: "1",
    "Outhouse/establish_upgrade": account.establish_upgrade, "Dorm/change": account.dorm_change,
    "Targettrain/addCollect": account.target_add, "Targettrain/delCollect": account.target_del,
    "Targettrain/lockCollect": account.target_lock,
    "Automission/abortAutomission": base.abort_automission, "Fetter/receiveBounty": account.fetter_receive_bounty,
    "Vehicle/changeComponentLock": upgrades.component_lock, "Vehicle/fixFinish": lambda s, b: "1",
    "Vehicle/setDormVehicle": lambda s, b: "1", "Vehicle/setVisit": lambda s, b: "1",
    "Fairy/finishUpgrade": inventory.finish_upgrade, "Fairy/quickUpgrade": inventory.finish_upgrade,
    "Gun/developCollectDel": lambda s, b: "1", "Equip/developCollectDel": lambda s, b: "1",
    "Gun/developLogCollect": lambda s, b: "1", "Equip/developLogCollect": lambda s, b: "1",
    "Squad/fixSquads": lambda s, b: "1", "Squad/fixFinish": lambda s, b: "1", "Squad/quickFix": lambda s, b: "1",
}.items():
    _new_handler(_name, _fn, plain=True)

for _name, _fn in {
    "Index/fixUnbrokenTargets": workshop.fix_unbroken,
    "Equip/develop": workshop.equip_develop, "Equip/finishDevelop": workshop.equip_finish_develop,
    "Equip/finishAllDevelop": workshop.equip_finish_all, "Fairy/develop": workshop.fairy_develop,
    "Fairy/finishDevelop": workshop.fairy_finish_develop, "Fairy/finishAllDevelop": workshop.fairy_finish_all,
    "Equip/eatEquip": workshop.eat_equip, "Fairy/eatFairy": workshop.eat_fairy,
    "Dorm/giftToGun": workshop.gift_to_gun,
    "Mission/sangvisBattleFinish": missions.sangvis_battle_finish,
    "Mission/withdrawSangvisTeam": missions.withdraw_sangvis,
    "Mission/reinforceSangvisTeam": missions.reinforce_sangvis,
    "Mission/supplySangvis": missions.supply_in_mission, "Mission/supplySquad": missions.supply_in_mission,
    "Mission/quickFixGun": missions.quick_fix_in_mission, "Mission/quickFixSangvis": missions.quick_fix_in_mission,
    # RequestActivityEventPrize reads a list of {event_id, num, has_get_prize}; RequestDrawEvent
    # guards every key (draw_info, mission_group_today_reset_num, tomorrow_unix, ...)
    "Index/recoverResource": account.recover_resource, "Index/heartBeat": account.heart_beat,
    "Index/ifNewMail": quests.if_new_mail, "Index/getMailList": quests.mail_list,
    "Index/deleteMails": quests.delete_mails, "Index/getResourceInMail": quests.get_mail_resource,
    "Index/Quest": quests.quest_info, "Index/accomplishDailyQuest": quests.accomplish_daily,
    "Index/accomplishWeeklyQuest": quests.accomplish_weekly, "Index/accomplishAllQuests": quests.accomplish_all,
    "Index/refreshDailyQuest": quests.refresh_daily, "Index/refreshWeeklyQuest": quests.refresh_weekly,
    "Index/achievement": quests.achievement, "Index/QuickGetQuestsResourceInMails": quests.quick_get_quest_mails,
    "Index/quickGetResourceInMails": quests.quick_get_all_mails, "Equip/presetList": formation.equip_preset_list,
    "Gun/memoirList": upgrades.memoir_list, "Gun/memoir": upgrades.unlock_memoir,
    "Squad/upSkill": upgrades.squad_up_skill, "Sangvis/collectList": upgrades.sangvis_collect_list,
    "Index/recoverSsoc": account.recover_ssoc, "Dorm/spare_name_list": account.spare_names,
    "Dorm/spare_name_modify": account.spare_rename, "Index/listTodo": account.list_todo,
    "Dorm/giftToSangvis": workshop.gift_to_sangvis,
    "Explore/balance": account.explore_balance, "Explore/start": account.explore_start,
    "Explore/getEvent": account.explore_get_event, "Index/getExploreMail": account.explore_reward, "Dorm/get_build_coin": account.get_build_coin,
    "Outhouse/establish_upgrade_finish": account.establish_upgrade_finish, "Index/japanGem": account.gem_info,
    # nobody else offline: empty friend lists (RequestBlackList / RequestFriendMall / RequestFriendAllMessage)
    "Friend/blackList": friends.black_list, "Friend/mall": lambda s, b: {"list": []},
    "Friend/messageget": lambda s, b: {"list": []},
    # friends' support echelons, from the archived reply (RequestFriendTeams reads the first two keys unguarded)
    "Friend/teamGuns": friends.support_teams,
    # the server-wide production logs: nothing offline (FactoryDevelopLogController)
    "Gun/developLog": lambda s, b: {"log_list": []}, "Equip/developLog": lambda s, b: {"log_list": []},
    "Equip/developCollectList": lambda s, b: {"log_list": []},
    "Gun/setWishGun": factory.set_wish_gun,
    "Equip/produceDevelop": workshop.produce_develop, "Equip/spProduceDevelop": workshop.sp_produce_develop,
    "Equip/produceRecover": workshop.produce_recover, "Equip/spProduceRecover": workshop.sp_produce_recover,
    "Squad/train": squads.train, "Squad/trainFinish": squads.train_finish, "Squad/trainGiveUp": squads.train_give_up,
    "Squad/addUpStartProgress": squads.add_rank_progress, "Squad/startUpStart": squads.start_promotion,
    "Squad/finishUpStart": squads.finish_promotion, "Squad/speedUpStar": squads.finish_promotion,
    "Squad/cancelUpStart": squads.cancel_promotion, "Squad/upSquadStar": squads.up_star,
    "Squad/researchUp": squads.research, "Squad/addSquadProgress": squads.add_unlock_progress,
    "Squad/addSquad": squads.add_squad, "Chip/strengthen": squads.chip_strengthen,
    "Chip/strengthenMax": squads.chip_strengthen_max,
    "Dorm/list": account.dorm_list, "Dorm/decompose": account.dorm_decompose,
    "Daily/index": gray_zone.index, "Daily/startPlan": gray_zone.start_plan,
    "Daily/finishPlan": gray_zone.finish_plan, "Daily/resetMap": gray_zone.reset_map,
    "Daily/eventOption": gray_zone.event_option, "Daily/getExmissionLog": lambda s, b: [],
    "Giftbox/open": workshop.open_gift_box, "Giftbox/checkOverTime": lambda s, b: {},  # nothing expired; delete_item must be a dict when present (RequestOpenOutDatePresent)
    "Mission/quickFixVehicle": missions.quick_fix_in_mission, "Mission/withdrawAlly": lambda s, b: {"type5_score": 0},
    "Mall/buyUniform": account.mall_buy_many, "Mall/buyVehicleSkin": account.mall_buy_many,
    "Sangvis/preset": account.save_sangvis_preset,
    "Fetter/index": account.fetter_index, "Fetter/orgInfo": account.fetter_org_info, "Mall/staticTables": account.mall_tables,
    "Fetter/readStory": account.fetter_read_story,
    "Fetter/milestone": account.fetter_milestone, "Fetter/receiveOrgBounty": account.fetter_receive_org_bounty,
    "Fetter/receiveAllOrgBounty": account.fetter_receive_all_org_bounty,
    "Vehicle/unlock": upgrades.unlock_vehicle, "Vehicle/upgradeComponent": upgrades.upgrade_component,
    "Vehicle/unlockTechTree": upgrades.unlock_tech_node, "Vehicle/fix": lambda s, b: {},
    # quick finish reports rewards like finishAutomission (RequestQuickAutoMission)
    "Automission/quickAutomission": missions.finish_automission,
    "Gun/coreRecoverGun": workshop.core_recover_gun, "Equip/coreRecoverEquip": workshop.core_recover_equip,
    "Gun/edit_soul_bond_time": upgrades.edit_soul_bond_time, "Equip/developMulti": workshop.equip_develop_multi,
    "Dorm/receive_favor": workshop.dorm_favor("gun"), "Dorm/receiveSangvisFavor": workshop.dorm_favor("sangvis"),
    "Gun/changeDamage": lambda s, b: {},
    "Mall/gemToResource": account.mall_buy, "Mall/gemToItem": account.mall_buy,
    "Mall/gemToGiftbag": account.mall_buy, "Mall/gemToMax": account.gem_to_max,
    "Sangvis/gasha": recruit.gasha_index, "Sangvis/gashaDraw": recruit.draw, "Sangvis/gashaRecover": recruit.recover,
    "Sangvis/gashaRefresh": recruit.refresh, "Sangvis/gashaReset": recruit.refill,
    "Gun/contract": upgrades.gun_contract, "Sangvis/contract": upgrades.sangvis_contract,
    "Gun/mindupdate": upgrades.mindupdate, "Equip/adjust": upgrades.equip_adjust,
    "Fairy/adjust": upgrades.fairy_adjust, "Sangvis/advance": upgrades.sangvis_advance,
    "Mission/squadMove": missions.squad_move, "Mission/reinforceSquad": missions.reinforce_squad,
    "Mission/reinforceVehicle": missions.reinforce_vehicle, "Mission/withdrawVehicle": missions.withdraw_vehicle,
    "Mission/vehicleBattleFinish": missions.battle_finish,
    "Mission/vehicleRangeAtk": missions.vehicle_range_attack,
    "Mission/vehicleRangeAtkFinish": missions.vehicle_range_finish,
    "Mission/withdrawSquad": missions.withdraw_squad, "Mission/quickFixSquad": missions.quick_fix_in_mission,
    "Mission/squadBattleSkillSwitch": missions.squad_skill_switch,
    # Coalition / allied / vehicle auto-skill toggles: no reply keys read, nothing simulated here
    "Mission/sangvisBattleSkillSwitch": missions.sangvis_skill_switch, "Mission/gunAllyBattleSkillSwitch": lambda s, b: {},
    "Mission/vehicleBattleSkillSwitch": lambda s, b: {},
    "Mission/saveHostage": missions.save_hostage,
    "Mission/accountMission": missions.account_mission, "Mission/missionGroupReset": missions.mission_group_reset,
    "Mission/skip": missions.skip_missions, "Mission/weakReset": missions.weak_reset,
    "Index/getEventInfo": lambda s, b: [],
    # RequestDrawEvent {mission_group_id}: draw_info [{draw_event_id, draw_num, draw_endtime}], the
    # same entries as Mission/drawEvent's list (RequestDrawEvent$$SuccessJsonHandleData)
    "Mission/eventDraw": lambda s, b: {"draw_info": events.draw_list(s, b)},
    # buildings, allied / third-party forces, chip special skills (missions.py)
    "Mission/squadAttackBuilding": missions.squad_attack_building,
    "Mission/sangvisAttackBuilding": missions.sangvis_attack_building,
    "Mission/vehicleAttackBuilding": missions.vehicle_attack_building,
    "Mission/buildingSkillPerform": missions.building_skill, "Mission/myforceSkillPerform": missions.building_skill,
    "Mission/arbitrarySkillPerform": missions.building_skill,
    "Mission/buildingSkillPerformOnDeath": missions.building_skill,
    "Mission/sangvisSkillPerform": missions.unit_skill_perform, "Mission/vehicleSkillPerform": missions.unit_skill_perform,
    "Mission/sangvisActiveSpecialSkill": missions.special_skill,
    "Mission/myforceActiveSpecialSkill": missions.special_skill,
    "Mission/allyMySideMove": missions.ally_my_side_move, "Mission/friendTeamMove": missions.friend_team_move,
    "Mission/reinforceFriendTeam": missions.reinforce_friend,
    "Mission/startOtherSideTurn": missions.other_side_turn, "Mission/othersideTurnMove": missions.other_side_turn,
    "Mission/endOtherSideTurn": missions.other_side_turn,
    "Mission/reinforceAllyTeam": missions.reinforce_ally,
    "Mission/allyTeamAi": missions.ally_ai, "Mission/friendTeamAi": missions.friend_ai,
    "Mission/allyMysideSet": lambda s, b: "1",      # allied force formation before deploying; reply not read
    "Mission/noBattleMeet": missions.no_battle_meet,
    # combat simulations, mission unlocks, Gray Zone sweeps
    "Mission/coinTeam": missions.coin_team, "Mission/coinBattleFinish": missions.coin_battle_finish,
    "Mission/intelligencePoint": missions.unlock_mission,
    "Mission/no_skip_winter_activity": lambda s, b: "1",    # story credits watched
    # RequestDailyExMissionMop -> GameData$$AnalysisMissionResultReward (lists optional)
    "Mission/simu": lambda s, b: {"reward_gun": [], "reward_equip": [], "reward_prize": [], "reward_item": []},
    # Defense Drill (trial.py)
    "Mission/startTrial": trial.start, "Mission/startTrialExercise": trial.start_battle,
    "Mission/endTrialExercise": trial.end_battle, "Mission/abortTrial": trial.abort,
    "Index/home": account.home, "Mall/quickBuyResource": account.quick_buy_resource,
    "Vehicle/preset": formation.save_vehicle_preset, "Targettrain/endBattle": account.target_end_battle,
    "Dorm/share": account.dorm_share,
    # HOC boosts, chip unlocks, Data Room cells, armour energy, dyes, fairy mod exp
    "Squad/strengthen": squads.strengthen, "Chip/addChip": squads.add_chip,
    "Dorm/get_data_cell": squads.get_data_cell, "Index/recoverEnergy": account.recover_energy,
    "Vehicle/exchangeEnergy": account.exchange_energy, "Commander/getColor": account.use_dye,
    "Fairy/modExpUpdate": upgrades.fairy_mod_exp,
    "Dorm/skinToGun": workshop.skin_to_gun, "Dorm/kalinaFavorUpLevel": account.kalina_level_up,
    "Manual/ReadList": account.manual_read_list, "Manual/Read": account.manual_read,
    "Manual/counter": account.manual_counter, "Sangvis/finishDevelop": upgrades.sangvis_finish_chip,
    "Dorm/gasha": gashapon.index, "Dorm/gasha_draw": gashapon.draw, "Dorm/gasha_exchange": gashapon.exchange,
    "Dorm/black_exchange_list": gashapon.black_list, "Dorm/black_exchange": gashapon.black_exchange,
    "Dorm/composeBlackCard": gashapon.compose_black_card,
    "Dorm/Medal": account.medal_list, "Friend/usercard": friends.card, "Friend/cosmeticBuy": account.buy_cosmetic, "Explore/getAdaptiveTeam": account.explore_adaptive_team,
    "Returnback/userInfo": returnback.user_info, "Returnback/getReturnInfo": returnback.return_info,
    "Returnback/getLoginPrize": returnback.login_prize, "Returnback/getTaskPrize": returnback.task_prize,
    "Returnback/getTaskActivePrize": returnback.active_prize,
    # the return fund is a real-money purchase, and invites need another player: refused offline
    "Returnback/getFundActivePrize": lambda s, b: None, "Returnback/checkUid": lambda s, b: None,
    "Returnback/saveInvite": lambda s, b: None, "Returnback/inviteInfo": lambda s, b: {},
    "Index/carnival": carnival.index,
    "Sangvis/duplicateIndex": sangvis_sim.index, "Sangvis/duplicateBattlefinish": sangvis_sim.battle_finish,
    "Dorm/skinToNpc": workshop.skin_to_npc,
    "Index/guildGetGameSign": chess.game_sign,       # the chess socket server and a session key for it
    "Chess/index": chess.index, "Chess/getTeamList": chess.team_list, "Chess/setTeam": chess.set_team,
    "Chess/getUserInfo": chess.user_info, "Chess/gashaDraw": chess.gasha_draw, "Chess/exchangeReward": chess.gasha_exchange,
    "Chess/log": chess.log_list, "Chess/getLogInfo": chess.log_detail,
    "Gun/eatGun": inventory.eat_gun, "Gun/eatGunIndex": inventory.eat_gun_index,
    "Vehicle/taskInfo": upgrades.vehicle_task_info, "Vehicle/teamUp": formation.vehicle_team_up,
    "Mission/drawEvent": events.draw_list,
    # online-only: the client reads these keys, and there is nothing behind them offline
    "Index/rankGuns": lambda s, b: {"gun_info": []}, "Index/bingGetGameSign": lambda s, b: {"game_sign": ""},
    "Index/questionnaire": lambda s, b: {"token": ""},
    "Index/getEventPrize": lambda s, b: {"package": {}}, "Index/getEventAllPrize": lambda s, b: {},
    "Event/lotteryIndex": lambda s, b: {"lottery_with_user": []}, "Event/drawLottery": lambda s, b: {},
    "Event/setShippingAddress": lambda s, b: {},
    "Mall/getSkinGiftInfo": lambda s, b: {}, "Mall/setMallSkinGift": lambda s, b: {},
    "Mission/startBreakoutMission": breakout.start, "Mission/teamBreakout": breakout.team,
    "Mission/shoppingBreakout": breakout.shopping, "Mission/organizePackage": breakout.organize,
    "Mission/breakoutBattleWin": breakout.battle_win, "Mission/abortBreakout": breakout.abort,
    "Bingo/user_bingo_info": bingo.info, "Bingo/tasklists": bingo.tasks,
    "Bingo/random_num": bingo.random_num, "Bingo/choose_num": bingo.choose_num,
    "Theater/data": theater.data, "Theater/teams": theater.save_teams,
    "Theater/startTheaterExercise": theater.start_exercise, "Theater/startTheaterBattle": theater.start_battle,
    "Theater/endTheaterBattle": theater.end_battle, "Theater/bossBattle": theater.boss_battle,
    "Theater/abortExercise": theater.abort_exercise, "Theater/finishExercise": theater.finish_exercise,
    "Theater/withdrawExercise": theater.withdraw_exercise, "Theater/teamAgainstBossEffect": theater.team_effect,
    "Theater/balance": theater.balance, "Theater/vote": theater.vote,
    "Theater/makeConstruction": theater.make_construction, "Theater/constructionCurPt": theater.construction_pt,
    "Theater/prizeData": theater.prize_data, "Theater/occupiedPrize": theater.occupied_prize,
    "Index/rank": account.rank,       # a one-entry board: the commander (score maps: their best scores)
    "Dorm/getDrawEvent": events.draw_num, "Dorm/openRed": events.open_red,
    "Event/letterIndex": events.letter_index, "Event/saveLetter": events.save_letter,
    "Event/revokeLetter": events.revoke_letter,
    "Battlepass/index": battlepass.index, "Battlepass/getBonus": battlepass.get_bonus,
    "Battlepass/getAllBonus": battlepass.get_all_bonus,
    "Sangvis/getMallList": account.sangvis_mall_list, "Sangvis/exchangeMall": account.sangvis_mall_buy,
    "Targettrain/log": account.target_log, "Index/sevenAttendance": account.seven_attendance,
    "Explore/career": lambda s, b: "1",     # RequestExploreCareer only marks the career read locally
    # gift codes: none exist offline, so every code is refused ("error:1"; HomeEventController$$RequestGiftHandle)
    "Index/sendGift": lambda s, b: None,
    "Friend/visit": friends.visit, "Friend/praise": friends.praise, "Friend/messageadd": friends.message_add,
    # a friend's goods and garage: the stock and vehicles aren't in the client or the account file, so these
    # are refused (error) rather than answered "1", which the JSON handlers can't read
    "Friend/mallBuy": lambda s, b: None, "Friend/buyMallByType9": lambda s, b: None,
    "Vehicle/visit": friends.vehicle_visit, "Vehicle/maintain": friends.vehicle_maintain,
    # real-money purchases can't happen offline: an error stops the client before it opens a payment
    # (an empty reply would go on to MallGoodController's Sunborn payment order)
    "Mall/ifAble": lambda s, b: None,
    # nobody else offline: no visits to the garage (RequestVehicleRoomVisitInfo), no like ranking
    # (RequestGunLikeList; every list guarded)
    "Vehicle/visitInfo": lambda s, b: {"is_vehicle_visit": False, "last_vehicle_visit_time": 0, "vehicle_visit_info": []},
    "Gun/likeList": account.gun_like_list, "Index/setFunctionControl": account.function_control,
    "Explore/getMallList": account.explore_mall_list, "Explore/buy": account.explore_buy,
    "Dorm/coffeeshop_unlock_list": account.cafe_list, "Dorm/coffeeshop_unlock": account.cafe_unlock,
    "Outhouse/establish_build": account.establish_build, "Outhouse/establish_build_finish": account.establish_build_finish,
}.items():
    _new_handler(_name, _fn)
_state_handler("Mission/fairySkillPerform", missions.fairy_skill_perform)
for _name, _fn in guilds.HANDLERS.items():      # no client code sends these; logged for whichever mod turns guilds on
    _new_handler("Guild/" + _name, _fn)

# Real client calls with nothing to do offline: each handler only checks for "1" (age and payment checks, the
# zone transfer, the anti-cheat report). Index/update stays unhandled: it fetches the game data itself.
for _name in ("Index/antiIndulgenceChange", "Index/buyerAge", "Index/checkOrder", "Index/transferZone", "Index/cheat"):
    _state_handler(_name, lambda s, b: "1")
for _name, _fn in {
    "test/dailyMapRouteList": account.daily_route_list, "test/mapRouteSetCheck": account.daily_route_check,
    "Chip/retire": squads.chip_retire, "Chip/change": squads.chip_change,
    "Dorm/data_analysis": squads.analysis_begin, "Dorm/data_analysis_complete": squads.analysis_complete,
    "Dorm/data_analysis_finish": squads.analysis_finish, "Dorm/data_analysis_finish_all": squads.analysis_finish_all,
}.items():
    _state_handler(_name, _fn)

# The client never sends these: RequestUrls$$.cctor names them and no method reads the field. So no reply
# format or body here was seen in use. Each takes the body of, and does the job of, the endpoint the client
# really calls for that feature.
for _name, _fn in {
    "Index/changeAdjutant": account.adjutant, "Theater/team": theater.save_teams, "Event/sendLetter": events.send_letter,
    "Equip/developEquip": workshop.equip_develop, "Gun/tagLike": account.gun_tag_like,
    "Factory/unlockBuildSlot": lambda s, b: account.gem_to_max(s, {"type": 4, "num": (b or {}).get("num")}),
    "Index/getOneMail": quests.one_mail, "Index/getGunCollect": account.gun_collect,
    "Index/getTime": lambda s, b: _server_clock(), "Index/bannerEvent": lambda s, b: {},
    "Friend/search": friends.card, "Friend/visitRandom": friends.visit_random, "Friend/cosmetic": lambda s, b: {"list": []},
    "Index/recoverBp": lambda s, b: {"bp": int(s["user_info"].get("bp") or 0)},
    "Gun/supplyGun": lambda s, b: "1",     # dolls hold no supply outside a mission here (Mission/supplyTeam)
}.items():
    _state_handler(_name, _fn)
HANDLERS["Factory/complete"] = HANDLERS["Factory/receive"] = gun_finish_develop
HANDLERS["Index/login"] = index_index


def _set_guide(state, body):
    # Index/guide {"guide": "<json string>"}: tutorial progress, echoed back by Index/index.
    if isinstance(body, dict) and "guide" in body:
        state.setdefault("guide_info", {})["guide"] = body["guide"]
    return "1"


_state_handler("Index/guide", _set_guide)
_state_handler("Index/attendance", attendance.attendance)
_state_handler("Operation/startOperation", base.start_operation)
_state_handler("Operation/abortOperation", base.abort_operation)
_state_handler("Automission/startAutomission", base.start_automission)
_state_handler("Index/setDesktopPet", base.set_desktop_pet)


@handler("Targettrain/battleLog")
def targettrain_battle_log(req: Request) -> Response:
    # Sent when a target-training battle starts (MissionSelectionDroneTrainSettingController
    # $$TargetTrainTrack); a tracking call, nothing to save.
    return Response("plain", "1")


# Friends who can't act offline: nobody applies or writes, and the limited shop is switched off
# (friend_itemstore_switch). Each reply has the shape its client handler reads (RequestBeAppliedList,
# RequestFriendsLastMessage, RequestGetFriendLimitGood).
_EMPTY_FRIEND_REPLIES = {
    "Friend/applylist": {"list": [], "apply_from_list": []},
    "Friend/messagelist": {"list": []},
    "Friend/mallByType9": {"mall_list": []},
}
for _name, _reply in _EMPTY_FRIEND_REPLIES.items():
    HANDLERS[_name] = (lambda reply: lambda req: Response("json", reply, key=req.sign))(_reply)
_state_handler("Friend/list", friends.friend_list)
_state_handler("Friend/randomList", friends.random_list)
_state_handler("Friend/teamAndPraisePrize", friends.progress)


@handler("Friend/setTeam")
def friend_set_team(req: Request) -> Response:
    # The support echelon shown to other players (RequestSetFriendTeam checks for "1").
    def change(state):
        state["_support_team"] = req.body
        return "1"
    return Response("plain", _with_state(req, change))


@handler("Index/downloadSuccess")
def download_success(req: Request) -> Response:
    return Response("plain", "1")


@handler("Mission/simulation")
def mission_simulation(req: Request) -> Response:
    # A sweep. A Coalition simulation sends its challenge_type as m_id; anything else is a combat
    # simulation mission (missions.simulation_sweep).
    body = req.body if isinstance(req.body, dict) else {}
    if int(body.get("m_id") or 0) in sangvis_sim.CHALLENGES:
        return _json_or_plain(req, _with_state(req, lambda s: sangvis_sim.sweep(s, body)))
    return _json_or_plain(req, _with_state(req, lambda s: missions.simulation_sweep(s, body)))


def _stc(name):
    """Static game table, read from the game's own .stc files."""
    return stc.table(name)


@handler("Index/crashLog")
def crash_log(req: Request) -> Response:
    # The client reports its own exceptions here; most point at a call whose reply it could
    # not parse. Kept in logs/client_crash.log rather than the unhandled list. A report sent
    # without a uid (the game's last-chance handler, just before it closes) can't be read with
    # the account's key, so each account's key is tried; failing that the raw form is kept.
    body = req.body
    if not isinstance(body, dict) and "outdatacode" in req.form:
        for acct in Store.get().index["by_uid"].values():
            text = crypto.decode(req.form["outdatacode"], acct["sign"], check_expiry=False) if acct.get("sign") else None
            if text is not None:
                try:
                    body = json.loads(text)
                except ValueError:
                    body = {"context": text}
                break
    context = body.get("context", "") if isinstance(body, dict) else body if isinstance(body, str) else ""
    if not context:
        context = "(not readable) " + json.dumps({k: v for k, v in req.form.items() if k != "signcode"}, ensure_ascii=False)[:20000]
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.LOG_DIR / "client_crash.log", "a", encoding="utf-8") as f:
        f.write(f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} uid={req.uid}\n{context}\n")
    return Response("plain", "1")


@handler("Friend/dormInfo")
def friend_dorm_info(req: Request) -> Response:
    # Own dorm summary, requested right after Index/index: account.dorm_info, from the account's archived
    # live reply, else an imported recording, else a minimal one shaped like the KR tool's preset.
    recorded = canned_response(req)
    return Response("json", _with_state(req, lambda s: account.dorm_info(s, recorded.payload if recorded else None)), key=req.sign)


def canned_response(req: Request):
    """data/responses/<Module>/<action>.json, as in the KR tool: under 3 bytes ("1", "[]") is
    sent as-is, anything longer is JSON sent encrypted. None if there is no file."""
    parts = req.function.split("/")
    path = config.RESPONSES_DIR.joinpath(*parts[:-1], parts[-1] + ".json")
    if len(parts) < 2 or not path.is_file():
        return None
    text = path.read_text("utf-8").strip()
    if len(text) < 3:
        return Response("plain", text)
    return Response("json", _fill_uid(json.loads(text), req.uid), key=req.sign)


@handler("Index/getUidEnMicaQueue")
def get_uid_en(req: Request) -> Response:
    return _login(req.form.get("openid", ""))


@handler("Index/getUid")
def get_uid_local(req: Request) -> Response:
    return _login(req.form.get("openid", ""))
