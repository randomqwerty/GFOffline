"""One chess game on the socket: the stages, dice, moves and battles, with built-in bot seats.

The live server's rules are not in the client, so this is a simplified game built on the client's
tables (chess_spot rings, chess_gun_type stats, chess_game_config) and its stage machine
(chess.py lists GameStageEventType):
  C_ChessInit -> S_ChessInitInfo; 2 SelectCamp, one seat at a time with curId (C_ChessSetCamp ->
  S_ChessSetCamp); 3 SelectTeam
  (C_ChessSetTeam -> S_SetTeamInfo per player, gunList keys 1..chess_member_num); 15 RoundStart;
  18 InitalGoFlight (C_ChessFly -> S_ChessGunFly); then per player 5 TurnStart, 6 PreBattleMain
  (C_ChessMoveRoll -> 8 Move + S_ChessRollResult; the client decides move or fly by itself:
  C_ChessFlyOrMove is only a notice, then C_ChessFly or C_ChessMove -> S_ChessGunMove type 1 walk,
  S_ChessMoveEnd), 9 BattleSelect when an enemy is in range (C_ChessAttack -> 10 Battle + S_ChessGunBattle;
  C_ChessBattleRoll -> S_ChessBattleRollResult, S_ChessAttackHurt), 11 PostBattleMain (C_ChessEnd),
  12 End. S_ChessWin {rank: {uid: place}, autoTime: {uid: seconds}, gameTime} ends it, and chess.py settles the
  game. C_CHESS_EXIT_GAME is the surrender: the commander comes last; a single game just stops.
Deploying (FlightChessGameController$$HandleRollMoveDice, HandleTurnStart): a roll in launch_point (1 or 6) offers move
  or deploy, up to launch_limit pieces on the board; with no piece on the board the turn opens on 7 TurnStartGoFlight.
  A 6 also grants another roll, at most 2 a turn (chess_selectframe 106).
Coins and the store (chess_gacha_mode 2, the client's isAutoChessMode): every 15 RoundStart moves to 4
  RoundStartingCardSel (FlightChessGameController$$HandleRoundStart). S_ChessShopCount opens the store and
  S_ChessChooseChip carries the coins and the offer (keys from 1). A round pays chip_refresh_chance + chess_coin_with_gun
  per piece on the board, up to chip_refresh_chance_limit (FlightChessUIMainController$$RefreshCounNumNextter). Kills pay
  kill_reward_coin and laps achieve_reward_coin. A player starts with START_COINS, and the first store pays no income.
  Every other change of coins is an S_ChessOrder (below) on AttrTotalToken.
Air drop: the commander's turn opens on 21 RandomAirDrop: S_ChessChanceList {chanceList: chess_choice_stage ids} opens
  the choice (FlightChessGameNetworkController$$OnChessChanceList) and C_ChessChanceChoose {chanceId} answers it; 1 is a
  Troop Carrier item card, 2 is 5 coins (the default on timeout). C_ChessUseItemFly {itemIndex, gunId, spotId, direction}
  plays the card.
Abilities: C_ChessUseGunChip {gunId, targetList}, C_ChessUseCampChip {targetList} and C_ChessUseChip {index, targetList}
  -> S_ChessUseChip {StaticChipId, userId, gunId, orderList, changeList}. The client changes nothing by itself: an order
  {orderType 1 Attribute, effectType 5 skill + skillObject, targetType 2 gun, targetId, AttrType, changeAttr (a size),
  changeAttrSign (true for a gain), lastAttr (the new value)} is what moves a number, and Hp 0 takes the piece off the
  board. changeList.ActiveChipChangeList {OwnType, OwnId, Cd, CdCount} sets the chip of a gun or a camp: Cd is its full
  cooldown and CdCount what is left (FlightChessGameNetworkController$$AnalysisChangeList calls set_maxCD(Cd), SetCD(CdCount)).
  The first order is {orderType 8 UseSkillAnimation, effectType chip id, effectId the user, targetType the gun}, which
  plays the cut-in and the voice (AnalysisOrder reuses those three fields this way). A refused ability answers S_Error
  (SkillInCd, ActiveSkillLaunchUnsuccessful).
  A target list holds the ids chess_chip_target_select asks for: grids when its target_type is 5, otherwise pieces.
Hand and turn tools: C_ChessUseItemDice {itemIndex, dicePoint} plays Planned Operation and rolls that number at once;
  C_ChessSetLock {mode} keeps the store's offer for the next round (the client hears nothing back); C_ChessSetAuto {mode} ->
  S_ChessUserStatus {uid, isAi}, and the server then plays the commander's turns as it plays a bot's; C_ChessDropChip {index}
  and C_ChessReplaceChip {indexList} discard or swap cards from the hand. C_ChessChooseChip is the store's purchase under its
  older name. The C_CHESS_PREPARE_* commands only preview a choice to the other players (RequestSendPresendInfo) and have no
  reply in the protocol, so nothing is sent for them. S_ChessReconnect is snapshot() below.
Every stage has a timeout that plays the default, so the game cannot stall on a missed message.
The client has no bot logic (its robot flags only change the display; the live server played them), so
this server plays the bot seats: they pick a free camp and a team, deploy on a 1 or 6 and otherwise walk the piece that can
reach an enemy, then attack with it. Before rolling they use up to BOT_SKILLS of their skills, tech skill and cards, and each
store they may buy one card (their hand is not sent: the client shows it for the commander's seat). A seat with no piece on the
board deploys one at the start of its turn, as the commander's client does. They don't take air drops, or buy passive chips.
A deployment leads straight to the end of the turn: BattleSelectPhaseAnim reads SelectedMoveChess, which only a walk sets, and
crashes without it.
APPROXIMATION: walking only (no jumps or airports), no monsters; abilities are written out by hand in ABILITIES below and
change numbers without the client's buff icons; passive chips can be bought and sold but do nothing in play; item
cards with no effect here are not sold (UNSUPPORTED_CARDS); Armament Alteration's "devastation" and "enhancement"
cards are the Intense Fire and Enhanced Velocity cards; the store's offer is random among level 1 chips whose init_time has come; a battle hurts the
defender by the attacker's power when the attacker's die is not lower; a full lap scores achieve_point, a
kill kill_point; first to chess_goal_point wins, or the most points after MAX_ROUNDS. Hand-tuned timings
leave room for the client's animations.
"""
import logging
import random
import threading
import time
from functools import lru_cache

from . import config, stc
from .store import Store

log = logging.getLogger("gfserver.chess")

INIT, CAMP, TEAM, CARD, TURN_START, PRE_BATTLE, TURN_FLIGHT, MOVE, BATTLE_SELECT, BATTLE, POST_BATTLE, END = range(1, 13)
ROUND_START, INITIAL_FLIGHT = 15, 18
TYPE_PLAYER = 1
MOVE_WALK = 1
MAX_ROUNDS = 30
BOT_PAUSE = 1.5
INIT_PAUSE = 6.0
EXTRA_ROLL_DICE = 6
MAX_EXTRA_ROLLS = 2
AIR_DROP = 21
AIR_DROP_CARD, AIR_DROP_COINS = 1, 2           # chess_choice_stage ids
SHOP_CARDS = 5
START_COINS = 10
TROOP_CARRIER = 60301
ORDER_ATTRIBUTE, ORDER_USE_SKILL = 1, 8
ERROR_IN_CD, ERROR_LAUNCH = 212, 232           # ErrorMsg.SkillInCd, ActiveSkillLaunchUnsuccessful
BOT_SKILLS = 2
BOT_SKILL_PAUSE = 3.0
BOT_BATTLE_PAUSE = 3.0
BOT_CARD_CHANCE = 0.6
BOT_CARDS = {14601, 15401, 19101, 19201, 19301}
SKILL_RANGE = 6                                # chess_chip_target_select 3 and 4, range "6,2"
LOW_HP = 3
TARGET_USER, TARGET_GUN = 1, 2
EFFECT_SKILL, COINS_KILL, COINS_LAP, COINS_CHANCE = 5, 202, 204, 205
ATTR_POWER, ATTR_HP, ATTR_MAX_HP, ATTR_RANGE, ATTR_AP, ATTR_SHIELD, ATTR_COINS = 1, 3, 4, 8, 9, 10, 115
ATTR_FIELD = {ATTR_POWER: "power", ATTR_HP: "hp", ATTR_MAX_HP: "maxHp", ATTR_RANGE: "attackRange", ATTR_AP: "ap", ATTR_SHIELD: "shield"}
GRID_TARGET = "5"                              # chess_chip_target_select.target_type
UNSUPPORTED_CARDS = {14901}                    # Turbo (no jumps here)
PLANNED_OPERATION = 19001
SUPPLY_FREE_USES, SUPPLY_COST = 1, 5


@lru_cache(maxsize=1)
def _config():
    return {r["parameter_name"]: str(r["parameter_value"]) for r in stc.table("chess_game_config")}


def _cfg_int(name, default):
    text = _config().get(name, "")
    head = text.split(",")[0]
    return int(head) if head.lstrip("-").isdigit() else default


@lru_cache(maxsize=None)
def _spots(mission):
    rows = [r for r in stc.table("chess_spot") if int(r["chess_mission_id"]) == int(mission)]
    return rows or [r for r in stc.table("chess_spot") if int(r["chess_mission_id"]) == 1]


@lru_cache(maxsize=None)
def _next_spot(mission):
    """spot id -> the next spot along the ring (positive_direction)."""
    rows = _spots(mission)
    at = {(int(r["axial_coordinator_q"]), int(r["axial_coordinator_r"])): int(r["id"]) for r in rows}
    out = {}
    for r in rows:
        q, _, s = str(r["positive_direction"]).partition(",")
        if q.lstrip("-").isdigit() and s.lstrip("-").isdigit() and (int(q), int(s)) in at:
            out[int(r["id"])] = at[(int(q), int(s))]
    return out


def _coords(mission):
    return {int(r["id"]): (int(r["axial_coordinator_q"]), int(r["axial_coordinator_r"])) for r in _spots(mission)}


def distance(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[0] + a[1] - b[0] - b[1]))


def base_spot(mission, order):
    rows = [r for r in _spots(mission) if int(r["type"]) == 4 and int(r["player_order"]) == order]
    return int(rows[0]["id"]) if rows else int(_spots(mission)[0]["id"])


@lru_cache(maxsize=1)
def _gun_types():
    return {int(r["id"]): r for r in stc.table("chess_gun_type")}


@lru_cache(maxsize=1)
def _guns():
    return {int(r["id"]): r for r in stc.table("gun")}


@lru_cache(maxsize=1)
def _chip_for_type():
    out = {}
    for r in stc.table("chess_chip"):
        fit = str(r["fit_gun_type"])
        if int(r["level"]) == 1 and int(r["type"]) == 1 and fit.isdigit():
            out.setdefault(int(fit), int(r["id"]))
    return out


def member_count():
    return _cfg_int("chess_member_num", 8)


def default_members():
    """chess_game_config default_team "gun:skin,..." as team members. gun.type and chess_gun_type agree on 1 to 4."""
    out = []
    for i, part in enumerate(_config().get("default_team", "").split(",")):
        gun, _, skin = part.partition(":")
        if gun.isdigit():
            kind = min(int(_guns().get(int(gun), {}).get("type") or 4), 4)
            out.append({"member_id": i + 1, "gun_id": int(gun), "skin": int(skin or 0), "chess_chip_id": _chip_for_type().get(kind, 0),
                        "chess_gun_type": kind})
    return out


def launch_points():
    return {int(x) for x in _config().get("launch_point", "6").split(",") if x.isdigit()}


@lru_cache(maxsize=1)
def _store_chips():
    """Level 1 effect and item chips that have a price: what the store can offer."""
    return [r for r in stc.table("chess_chip") if int(r["level"]) == 1 and int(r["type"]) == 1 and int(r["number"]) > 0
            and _price(r) > 0 and int(r["id"]) not in UNSUPPORTED_CARDS]


def _price(chip):
    head = str(chip["price"]).split(",")[0]
    return int(head) if head.isdigit() else 0


@lru_cache(maxsize=1)
def _chips():
    return {int(r["id"]): r for r in stc.table("chess_chip")}


@lru_cache(maxsize=1)
def _target_select():
    return {int(r["id"]): r for r in stc.table("chess_chip_target_select")}


@lru_cache(maxsize=1)
def _chances():
    return {int(r["id"]): r for r in stc.table("chess_choice_stage")}


def _first_skill(chip):
    """The chip's skill for a skillObject (ChessSkill reads its row by StaticSkillId)."""
    for field in ("skill_target_first", "skill_target_second"):
        head = str(chip.get(field) or "").split(",")[0]
        if head.isdigit() and int(head):
            return int(head)
    return 0


def camp_chip(camp):
    row = next((r for r in stc.table("chess_camp_type") if int(r["id"]) == int(camp)), None)
    return int(row["camp_skill"]) * 100 + 1 if row else 0


class Game:
    def __init__(self, reply, uid, users, names, mission, rng=None, pause=1.0, on_finish=None, single=False):
        self.reply, self.me, self.mission = reply, int(uid), int(mission or 1)
        self.on_finish, self.single = on_finish, single
        self.rng = rng or random.Random()
        self.lock = threading.RLock()
        self.pause = pause                     # scales the waits (tests run with 0)
        self.seq = 0                           # a newer stage cancels older timers
        self.started = time.time()
        self.over = False
        self.round = 1
        self.turn = 0
        self.dice = 0
        self.battle = None
        self.players = []
        for i, u in enumerate(users):
            self.players.append({"uid": int(u), "name": names.get(int(u), ""), "order": i + 1, "bot": int(u) != self.me,
                                 "camp": 0, "guns": {}, "points": 0, "kills": 0, "achieves": 0, "rank": 0,
                                 "token": START_COINS, "equips": {}, "items": {}, "cds": {}, "supplies": 0, "extra_dice": 0})
        self.done_flight = set()
        self.stage_id = 0
        self.acted = False                     # this roll has been spent on a move or a deployment
        self.extra_rolls = 0
        self.offer = {}                        # the store: slot (from 1) -> chip id
        self.after_shop = None                 # set while the store is open
        self.move = 0                          # the steps of this roll: every die, where self.dice is the first
        self.boosts = []                       # abilities that wear off: [turns left, gun, attr, size, skill]
        self.chip_result, self.chip_kills = None, 0   # the ability being played
        self.locked, self.kept_offer = False, None     # the store's lock, and the offer it keeps
        self.auto, self.auto_since, self.auto_time = False, 0, 0
        self.stage_end = 0
        self.ticked = False                    # this turn's cooldowns have been counted

    # --- plumbing
    def player(self, uid=None):
        uid = self.me if uid is None else int(uid)
        return next(p for p in self.players if p["uid"] == uid)

    def later(self, seconds, fn):
        seq = self.seq

        def run():
            with self.lock:
                if seq == self.seq and not self.over:
                    fn()
        if self.pause:
            t = threading.Timer(seconds * self.pause, run)
            t.daemon = True
            t.start()
        return run                             # tests call it directly

    def stage(self, stage_id, seconds=0, uid=0):
        self.seq += 1
        self.stage_id = stage_id
        now = int(time.time())
        self.stage_end = now + int(seconds)
        self.reply("S_GAMESTAGE", {"stageId": stage_id, "startTime": now, "endTime": now + int(seconds), "curType": TYPE_PLAYER,
                                   "curId": int(uid), "roundNum": self.round})

    # --- setup
    def start(self):
        with self.lock:
            self.reply("S_CHESSINITINFO", {
                "userList": [{"uid": p["uid"], "name": p["name"], "order": p["order"], "diceNum": 7 - p["order"], "isRobot": p["bot"]}
                             for p in self.players],
                # the chip group: FlightChessCamp$$get_chipInfo looks up group * 100 + level
                "campSkillInfo": {int(r["id"]): int(r["camp_skill"]) for r in stc.table("chess_camp_type")},
                "missionId": self.mission})
            self.later(INIT_PAUSE, self.select_camp)

    def select_camp(self):
        """Camps are picked one seat at a time: the stage's curId is whose turn it is
        (FlightChessGameController$$HandleCampSelEvent), and a camp goes to one seat."""
        p = next((x for x in self.players if not x["camp"]), None)
        if p is None:
            return self.later(1.0, self.select_team)
        seconds = _cfg_int("chess_set_camp_time", 45)
        self.stage(CAMP, seconds, p["uid"])
        if p["bot"] or self.auto:
            self.later(BOT_PAUSE, lambda: self.set_camp(p["uid"], self.rng.choice(self.free_camps())))
        else:
            self.later(seconds, lambda: self.set_camp(p["uid"], self.free_camps()[0]))

    def free_camps(self):
        taken = {x["camp"] for x in self.players}
        return [int(r["id"]) for r in stc.table("chess_camp_type") if int(r["id"]) not in taken]

    def set_camp(self, uid, camp):
        p = self.player(uid)
        p["camp"] = int(camp)
        self.reply("S_CHESSSETCAMP", {"uid": p["uid"], "camp": p["camp"], "staticChipId": camp_chip(p["camp"]), "chipId": p["order"]})
        self.seq += 1                                  # this seat's timeout is over
        self.later(1.0, self.select_camp)

    def select_team(self):
        self.stage(TEAM, _cfg_int("chess_set_team_time", 15))
        self.later(BOT_PAUSE if self.auto else _cfg_int("chess_set_team_time", 15), lambda: self.set_team(self.me, 0))

    def _members(self, uid, team_id):
        if uid == self.me:
            try:
                state = Store.get().load_player(str(uid), config.PLAYER_TEMPLATE)
                saved = ((state.get("_chess") or {}).get("teams") or {}).get(str(team_id))
                if saved and len(saved) >= member_count():
                    return saved
            except (OSError, ValueError, KeyError):
                log.warning("chess: could not read the saved team")
        return default_members()

    def _gun_info(self, p, member, slot):
        gun = _guns().get(int(member["gun_id"]), {})
        kind = int(member.get("chess_gun_type") or 0) or min(int(gun.get("type") or 4), 4)
        t = _gun_types().get(kind) or _gun_types()[4]
        return {"gunId": p["order"] * 100 + slot, "gunImage": int(member["gun_id"]), "gunType": kind, "skin": int(member.get("skin") or 0),
                "skillChipId": int(t["gun_type_skill"]) * 100 + 1,
                "chipId": int(member.get("chess_chip_id") or 0) or _chip_for_type().get(kind, 0), "uid": p["uid"], "direction": 0,
                "hp": int(t["hp"]), "power": int(t["power"]), "maxHp": int(t["hp"]), "armor": int(t["armor"]),
                "attackTimes": int(t["attack_times"]), "attackRange": int(t["range"]), "ap": int(t["ap"]), "shield": 0,
                "jumpNum": _cfg_int("chess_jump_distance", 4)}

    def set_team(self, uid, team_id):
        p = self.player(uid)
        if p["guns"]:
            return
        count = member_count()
        members = (self._members(p["uid"], team_id) or default_members())
        info = {}
        for slot in range(1, count + 1):
            info[slot] = self._gun_info(p, members[(slot - 1) % len(members)], slot)
            p["guns"][info[slot]["gunId"]] = {"info": info[slot], "spot": 0, "steps": 0}
        self.reply("S_SETTEAMINFO", {"uid": p["uid"], "gunList": info})
        if uid != self.me:
            return
        for bot in self.players:
            if bot["bot"]:
                self.set_team(bot["uid"], 0)
        self.seq += 1
        self.later(1.0, self.first_round)

    def first_round(self):
        self.stage(ROUND_START, _cfg_int("chess_round_start_show_time", 1))
        self.later(2.0, lambda: self.open_shop(self.initial_flight, income=False))

    def initial_flight(self):
        seconds = _cfg_int("chess_set_initial_gun_time", 15)
        self.stage(INITIAL_FLIGHT, seconds, self.me)
        for p in self.players:
            if p["bot"]:
                self._fly(p, next(iter(p["guns"])), base_spot(self.mission, p["order"]), 0)
        self.later(BOT_PAUSE if self.auto else seconds, self._auto_initial_flight)

    def _auto_initial_flight(self):
        me = self.player()
        self._fly(me, next(iter(me["guns"])), base_spot(self.mission, me["order"]), 0)
        self.start_turn(0)

    def _fly(self, p, gun_id, spot, direction):
        gun = p["guns"].get(int(gun_id))
        if gun is None:
            return False
        gun["spot"], gun["steps"] = int(spot), 0
        gun["info"]["direction"] = int(direction)
        self.reply("S_CHESSGUNFLY", {"uid": p["uid"], "gunId": int(gun_id), "spotId": int(spot), "direction": int(direction)})
        return True

    # --- turns
    def on_board(self, p):
        return [g for g in p["guns"].values() if g["spot"]]

    def start_turn(self, index):
        if self.over:
            return
        if index >= len(self.players):
            self.round += 1
            if self.round > MAX_ROUNDS:
                return self.finish()
            self.stage(ROUND_START, _cfg_int("chess_round_start_show_time", 1))
            return self.later(2.0, lambda: self.open_shop(lambda: self.start_turn(0)))
        self.turn = index
        self.dice = self.move = 0
        self.acted = False
        self.extra_rolls = 0
        self.battle = None
        self.ticked = False
        p = self.players[index]
        p["supplies"] = 0
        self.stage(TURN_START, 1, p["uid"])
        self.later(1.0, (lambda: self.bot_turn(p)) if p["bot"] or self.auto else self.air_drop)

    def air_drop(self):
        self.tick_cooldowns(self.player())
        seconds = _cfg_int("chess_chance_choose_time", 15)
        self.stage(AIR_DROP, seconds, self.me)
        self.reply("S_CHESS_CHANCE_LIST", {"chanceList": [AIR_DROP_CARD, AIR_DROP_COINS]})
        self.later(seconds, lambda: self.choose_air_drop(AIR_DROP_COINS))

    def choose_air_drop(self, chance):
        me = self.player()
        row = _chances()[chance]
        limit = _cfg_int("chip_basic_limit2", 5)
        if chance == AIR_DROP_CARD and len(me["items"]) < limit:
            self.give_card(me, int(row["parameter"]))
        else:                                          # a full hand takes the coins
            self.pay_coins(me, int(_chances()[AIR_DROP_COINS]["parameter"]), COINS_CHANCE)
        self.player_main()

    def on_C_CHESS_CHANCE_CHOOSE(self, body):
        chance = int(body.get("chanceId") or 0)
        if self.stage_id == AIR_DROP and chance in (AIR_DROP_CARD, AIR_DROP_COINS):
            self.choose_air_drop(chance)

    def give_card(self, p, chip):
        limit = _cfg_int("chip_basic_limit2", 5)
        slot = next((i for i in range(1, limit + 1) if i not in p["items"]), None)
        if slot is not None:
            p["items"][slot] = chip
            self.send_items(p, added=chip)

    def player_main(self):
        me = self.player()
        if not self.on_board(me):                      # the client goes to this stage by itself too
            seconds = _cfg_int("chess_set_initial_gun_time", 15)
            self.stage(TURN_FLIGHT, seconds, self.me)
            return self.later(seconds, self._auto_turn_flight)
        seconds = _cfg_int("chess_player_action_time", 60)
        self.stage(PRE_BATTLE, seconds, self.me)
        self.later(seconds, self.end_turn)

    def _auto_turn_flight(self):
        me = self.player()
        self._fly(me, next(g for g, x in me["guns"].items() if not x["spot"]), base_spot(self.mission, me["order"]), 0)
        self.player_main()

    def can_deploy(self, p):
        """A roll in launch_point, with room on the board and a piece left to send."""
        return (self.dice in launch_points() and not self.acted and len(self.on_board(p)) < _cfg_int("launch_limit", 3)
                and any(not g["spot"] for g in p["guns"].values()))

    def grant_extra_roll(self):
        if self.dice != EXTRA_ROLL_DICE or self.extra_rolls >= MAX_EXTRA_ROLLS:
            return False
        self.extra_rolls += 1
        self.dice = self.move = 0
        self.acted = False
        return True

    # --- coins and the store
    def add_coins(self, p, coins):
        p["token"] = min(_cfg_int("chip_refresh_chance_limit", 100), p["token"] + coins)

    def pay_coins(self, p, coins, effect):
        """Coins outside the store, which the commander's client hears as an order."""
        before = p["token"]
        self.add_coins(p, coins)
        if p["uid"] == self.me and p["token"] != before:
            self.reply("S_CHESS_ORDER_LIST", {"orderList": [self._order(
                effect, TARGET_USER, p["uid"], ATTR_COINS, p["token"] - before, p["token"])]})

    @staticmethod
    def _order(effect, target_type, target_id, attr, change, last, skill=None):
        order = {"orderType": ORDER_ATTRIBUTE, "effectType": effect, "targetType": target_type, "targetId": target_id, "AttrType": attr,
                 "changeAttr": abs(change), "lastAttr": last, "changeAttrSign": change >= 0}
        if skill:
            order["skillObject"] = skill
        return order

    def round_income(self, p):
        return _cfg_int("chip_refresh_chance", 3) + _cfg_int("chess_coin_with_gun", 2) * len(self.on_board(p))

    def deal_offer(self):
        pool = [r for r in _store_chips() if int(r["init_time"]) <= self.round]
        count = min(SHOP_CARDS, len(pool))
        self.offer = {i + 1: int(r["id"]) for i, r in enumerate(self.rng.sample(pool, count))}

    def send_offer(self):
        self.reply("S_CHESSCHOOSECHIP", {"token": self.player()["token"], "chipList": self.offer})

    def open_shop(self, then, income=True):
        for p in self.players:
            if income:
                self.add_coins(p, self.round_income(p))
        self.after_shop = then
        seconds = _cfg_int("chess_choose_chip_time", 60)
        self.stage(CARD, seconds, self.me)
        self.reply("S_CHESS_SHOP_COUNT", {"count": 0, "self": False})
        for p in self.players:
            if p["bot"]:
                self.bot_buy(p)
        if self.locked and self.kept_offer:
            self.offer = dict(self.kept_offer)
        else:
            self.deal_offer()
        self.send_offer()
        self.later(BOT_PAUSE if self.auto else seconds, self.close_shop)

    def close_shop(self):
        then, self.after_shop = self.after_shop, None
        self.kept_offer = dict(self.offer) if self.locked else None
        self.offer = {}
        if then:
            then()

    def send_equips(self, p):
        self.reply("S_CHESSEQUIPLIST", {"uid": p["uid"], "equipList": {i: {"chipId": c, "exp": 0} for i, c in p["equips"].items()}})

    def send_items(self, p, added=0, removed=()):
        if p["bot"]:
            return
        self.reply("S_CHESSITEMLIST", {"uid": p["uid"], "addChip": added, "deleteChipList": list(removed), "itemList": dict(p["items"])})

    def on_C_CHESS_BUY_CHIP(self, body):
        me = self.player()
        index = int(body.get("chipIndex") or 0)
        chip = _chips().get(self.offer.get(index, 0))
        if not self.after_shop or chip is None or me["token"] < _price(chip):
            return log.warning("chess: refused to sell store slot %s", index)
        active = int(chip["is_active"])
        slots = me["items"] if active else me["equips"]
        limit = _cfg_int("chip_basic_limit2" if active else "chip_basic_limit", 5)
        if len(slots) >= limit:
            return log.warning("chess: no room for chip %s", chip["id"])
        me["token"] -= _price(chip)
        del self.offer[index]
        slot = int(body.get("equipIndex") or 0)
        if slot <= 0 or slot in slots:
            slot = next(i for i in range(1, limit + 2) if i not in slots)
        slots[slot] = int(chip["id"])
        if active:
            self.send_items(me, added=int(chip["id"]))
        else:
            self.send_equips(me)
        self.reply("S_CHESS_BUY_END", {"index": index, "token": me["token"]})

    def on_C_CHESS_SELL_CHIP(self, body):
        me = self.player()
        index = int(body.get("index") or 0)
        slots = next((s for s in (me["equips"], me["items"]) if index in s), None)
        if slots is None:
            return log.warning("chess: nothing to sell in slot %s", index)
        chip = slots.pop(index)
        self.add_coins(me, int(_chips()[chip]["sell_price"]))
        if slots is me["items"]:
            self.send_items(me, removed=[chip])
        else:
            self.send_equips(me)
        self.reply("S_CHESS_SELL_END", {"type": int(body.get("type") or 0), "index": index, "token": me["token"]})

    def on_C_CHESSFLUSHCARD(self, body):
        me = self.player()
        price = _cfg_int("chip_refresh_price", 2)
        if self.after_shop and me["token"] >= price:
            me["token"] -= price
            self.deal_offer()
            self.send_offer()

    def on_C_CHESSGIVEUPCARD(self, body):
        if self.after_shop:
            self.add_coins(self.player(), _cfg_int("chess_abandon_reward", 2))
            self.seq += 1
            self.close_shop()

    def on_C_CHESSSETLOCK(self, body):
        self.locked = bool(body.get("mode"))

    def on_C_CHESSCHOOSECHIP(self, body):
        self.on_C_CHESS_BUY_CHIP(body)

    def on_C_CHESSDROPCHIP(self, body):
        me = self.player()
        dropped = [me["items"].pop(int(i)) for i in body.get("index") or [] if int(i) in me["items"]]
        if dropped:
            self.send_items(me, removed=dropped)

    def on_C_CHESSREPLACECHIP(self, body):
        me = self.player()
        pool = [int(r["id"]) for r in _store_chips() if int(r["is_active"])]
        for slot in [int(i) for i in body.get("indexList") or [] if int(i) in me["items"]]:
            old, me["items"][slot] = me["items"][slot], self.rng.choice(pool)
            self.send_items(me, added=me["items"][slot], removed=[old])

    def on_C_CHESS_REPLACECHIP_GIVEUP(self, body):
        pass                                           # keeps the hand as it is

    def on_C_CHESS_SET_SHOP_END(self, body):
        if not self.after_shop or not body.get("isEnd"):
            return
        self.reply("S_CHESS_SHOP_COUNT", {"count": len(self.players), "self": True})   # the bots are always ready
        self.seq += 1
        self.later(1.0, self.close_shop)

    # --- abilities
    def chip_cooldown(self, p, own_type, own_id, chip):
        return p["cds"].setdefault((own_type, own_id, chip), int(_chips()[chip]["init_cd"]))

    def _cd_change(self, own_type, own_id, chip, cd):
        return {"Id": chip, "StaticChipId": chip, "OwnType": own_type, "OwnId": own_id, "Cd": int(_chips()[chip]["cd"]), "CdCount": cd}

    def tick_cooldowns(self, p):
        """Each of a seat's turns but the first takes one from each cooldown; they start at init_cd, as they do in the client."""
        if self.ticked:
            return
        self.ticked = True
        first = not p["cds"]
        for gun_id, gun in p["guns"].items():
            self.chip_cooldown(p, TARGET_GUN, gun_id, gun["info"]["skillChipId"])
        if camp_chip(p["camp"]):
            self.chip_cooldown(p, TARGET_USER, p["uid"], camp_chip(p["camp"]))
        if first:
            return
        changes = {}
        for key, cd in p["cds"].items():
            if cd > 0:
                p["cds"][key] = cd - 1
                changes[len(changes) + 1] = self._cd_change(*key, cd - 1)
        if changes:
            self.reply("S_CHESS_ORDER_LIST", {"orderList": [], "changeList": {"ActiveChipChangeList": changes}})

    def _skill(self, chip, source):
        return {"Id": chip, "StaticSkillId": _first_skill(_chips()[chip]), "staticChipId": chip, "sourceType": 1, "sourceId": source, "LaunchCount": 1}

    def change_attr(self, orders, gun, attr, change, skill):
        field = ATTR_FIELD[attr]
        gun["info"][field] = int(gun["info"].get(field) or 0) + change
        orders.append(self._order(EFFECT_SKILL, TARGET_GUN, gun["info"]["gunId"], attr, change, gun["info"][field], skill))

    def hurt(self, orders, by, gun, damage, skill):
        """Shield first, then HP. Hp 0 takes the piece off the board, and an enemy's kill pays."""
        absorbed = min(int(gun["info"].get("shield") or 0), damage)
        if absorbed:
            self.change_attr(orders, gun, ATTR_SHIELD, -absorbed, skill)
        rest = min(int(gun["info"]["hp"]), damage - absorbed)
        if rest:
            self.change_attr(orders, gun, ATTR_HP, -rest, skill)
        if int(gun["info"]["hp"]) > 0:
            return False
        self.remove_piece(gun)
        if int(gun["info"]["uid"]) != by["uid"]:
            self.chip_kills += 1
        return True

    def remove_piece(self, gun):
        gun["spot"], gun["steps"] = 0, 0
        gun["info"]["hp"] = gun["info"]["maxHp"]

    def heal(self, orders, gun, amount, skill):
        amount = min(amount, int(gun["info"]["maxHp"]) - int(gun["info"]["hp"]))
        if amount > 0:
            self.change_attr(orders, gun, ATTR_HP, amount, skill)

    def enhance(self, orders, gun, skill):
        """One of the Enhance buffs 109 to 112, whose text is DMG, Mobility, Max. HP or Range +1."""
        attr = self.rng.choice((ATTR_POWER, ATTR_AP, ATTR_MAX_HP, ATTR_RANGE))
        self.change_attr(orders, gun, attr, 1, skill)
        if attr == ATTR_MAX_HP:
            self.change_attr(orders, gun, ATTR_HP, 1, skill)

    def boost(self, orders, gun, attr, size, skill):
        """Lasts for this turn, or for the next one when the turn's move has already been made."""
        self.change_attr(orders, gun, attr, size, skill)
        self.boosts.append([1 if self.stage_id == PRE_BATTLE else 2, gun, attr, size, skill])

    def wear_off(self, p):
        orders, left = [], []
        for entry in self.boosts:
            entry[0] -= int(entry[1]["info"]["uid"]) == p["uid"]
            if entry[0] > 0:
                left.append(entry)
            else:
                self.change_attr(orders, entry[1], entry[2], -entry[3], entry[4])
        self.boosts = left
        if orders:
            self.reply("S_CHESS_ORDER_LIST", {"orderList": orders})

    def _all_guns(self):
        return {gun_id: gun for p in self.players for gun_id, gun in p["guns"].items()}

    def chosen_pieces(self, targets):
        """The pieces in a target list that are on the board."""
        guns = self._all_guns()
        ids = [i for key in ("firstTargetIdList", "secondTargetIdList") for i in targets.get(key) or []]
        return [guns[int(i)] for i in ids if int(i) in guns and guns[int(i)]["spot"]]

    def chosen_grid(self, chip, targets):
        for select, key in (("target_select_first", "firstTargetIdList"), ("target_select_second", "secondTargetIdList")):
            row = _target_select().get(int(_chips()[chip][select]))
            ids = targets.get(key) or []
            if row and GRID_TARGET in str(row["target_type"]).split(",") and ids:
                return int(ids[0])
        return 0

    def _ability_scout(self, me, gun, targets, chip, skill, orders):
        self.boost(orders, gun, ATTR_AP, 2, skill)

    def _ability_snipe(self, me, gun, targets, chip, skill, orders):
        enemy = [g for g in self.chosen_pieces(targets) if int(g["info"]["uid"]) != me["uid"]]
        if not enemy:
            return False
        self.hurt(orders, me, enemy[0], 4, skill)

    def _ability_assault(self, me, gun, targets, chip, skill, orders):
        self.enhance(orders, gun, skill)

    def _ability_grenade(self, me, gun, targets, chip, skill, orders):
        coords = _coords(self.mission)
        at = coords.get(self.chosen_grid(chip, targets))
        if at is None:
            return False
        for p in self.players:
            if p is not me:
                for g in list(self.on_board(p)):
                    if distance(at, coords[g["spot"]]) <= 1:
                        self.hurt(orders, me, g, 3, skill)

    def _ability_bombing(self, me, gun, targets, chip, skill, orders):
        pieces = self.chosen_pieces(targets)
        if not pieces:
            return False
        self.hurt(orders, me, pieces[0], 2, skill)

    def _ability_supplies(self, me, gun, targets, chip, skill, orders):
        pieces = [g for g in self.chosen_pieces(targets) if int(g["info"]["uid"]) == me["uid"]]
        if not pieces or (me["supplies"] >= SUPPLY_FREE_USES and me["token"] < SUPPLY_COST):
            return False
        if me["supplies"] >= SUPPLY_FREE_USES:
            me["token"] -= SUPPLY_COST
            orders.append(self._order(EFFECT_SKILL, TARGET_USER, me["uid"], ATTR_COINS, -SUPPLY_COST, me["token"], skill))
        me["supplies"] += 1
        self.enhance(orders, pieces[0], skill)

    def _ability_reinforce(self, me, gun, targets, chip, skill, orders):
        pieces = self.chosen_pieces(targets)
        if not pieces:
            return False
        self.heal(orders, pieces[0], 2, skill)
        self.change_attr(orders, pieces[0], ATTR_SHIELD, 1, skill)

    def _ability_retrieve(self, me, gun, targets, chip, skill, orders):
        pieces = [g for g in self.chosen_pieces(targets) if int(g["info"]["uid"]) == me["uid"]]
        if not pieces:
            return False
        piece = pieces[0]
        kind = int(piece["info"]["gunType"])
        orders.append(self._order(EFFECT_SKILL, TARGET_GUN, piece["info"]["gunId"], ATTR_HP, -int(piece["info"]["hp"]), 0, skill))
        self.remove_piece(piece)
        if kind == 1:
            me["extra_dice"] = 1
        elif kind == 2:
            for g in self.on_board(me):
                self.change_attr(orders, g, ATTR_SHIELD, 2, skill)
        else:
            self.give_card(me, 19101 if kind == 3 else 19201)

    def _card_heal(self, me, gun, targets, chip, skill, orders):
        hurt = [g for g in self.on_board(me) if int(g["info"]["hp"]) < int(g["info"]["maxHp"])]
        if not hurt:
            return False
        piece = self.rng.choice(hurt)
        self.heal(orders, piece, max(1, int(piece["info"]["maxHp"]) // 2), skill)

    def _card_die(self, me, gun, targets, chip, skill, orders):
        me["extra_dice"] = 1

    def _card_boost(self, attr, size):
        def play(me, gun, targets, chip, skill, orders):
            pieces = [g for g in self.chosen_pieces(targets) if int(g["info"]["uid"]) == me["uid"]]
            if not pieces:
                return False
            self.boost(orders, pieces[0], attr, size, skill)
        return play

    def abilities(self):
        """Chip id -> its effect, the numbers from chess_chip's description. An effect returns False to refuse."""
        return {20101: self._ability_scout, 20201: self._ability_snipe, 20301: self._ability_assault, 20401: self._ability_grenade,
                30201: self._ability_bombing, 30301: self._ability_supplies, 30401: self._ability_reinforce, 30501: self._ability_retrieve,
                14601: self._card_heal, 15401: self._card_die, 19101: self._card_boost(ATTR_POWER, 2),
                19201: self._card_boost(ATTR_AP, 2), 19301: self._card_boost(ATTR_RANGE, 1)}

    def refuse(self, p, error, text, *args):
        log.warning("chess: " + text, *args)
        if not p["bot"]:
            self.reply("S_ERROR", {"errorNum": error})
        return False

    def use_chip(self, p, chip, source, gun, targets):
        """Run an ability on its seat's turn; True when it went off. S_ChessUseChip names the piece if there is one."""
        effect = self.abilities().get(chip)
        row = _chips().get(chip)
        if effect is None or self.players[self.turn] is not p or str(self.stage_id) not in str(row["use_stage"]).split(","):
            return self.refuse(p, ERROR_LAUNCH, "refused chip %s in stage %s", chip, self.stage_id)
        gun_id = gun["info"]["gunId"] if gun else 0
        orders = [{"orderType": ORDER_USE_SKILL, "effectType": chip, "effectId": p["uid"], "targetType": gun_id}]
        self.chip_kills = 0
        if effect(p, gun, targets, chip, self._skill(chip, source), orders) is False:
            return self.refuse(p, ERROR_LAUNCH, "chip %s found no target in %s", chip, targets)
        self.chip_result = {"StaticChipId": chip, "userId": p["uid"], "gunId": gun_id, "orderList": orders}
        return True

    def finish_chip(self, p, change=None):
        if change:
            self.chip_result["changeList"] = {"ActiveChipChangeList": {1: change}}
        self.reply("S_CHESSUSECHIPRESULT", self.chip_result)
        for _ in range(self.chip_kills):
            self.kill_paid(p)

    def use_gun_chip(self, p, gun, targets):
        gun_id = gun["info"]["gunId"]
        chip = int(gun["info"]["skillChipId"])
        if self.chip_cooldown(p, TARGET_GUN, gun_id, chip) > 0:
            return self.refuse(p, ERROR_IN_CD, "chip %s is cooling down", chip)
        if not self.use_chip(p, chip, gun_id, gun, targets):
            return False
        cd = p["cds"][(TARGET_GUN, gun_id, chip)] = int(_chips()[chip]["cd"])
        self.finish_chip(p, self._cd_change(TARGET_GUN, gun_id, chip, cd))
        return True

    def use_camp_chip(self, p, targets):
        chip = camp_chip(p["camp"])
        if self.chip_cooldown(p, TARGET_USER, p["uid"], chip) > 0:
            return self.refuse(p, ERROR_IN_CD, "chip %s is cooling down", chip)
        pieces = self.chosen_pieces(targets)
        if not self.use_chip(p, chip, p["uid"], pieces[0] if pieces else None, targets):
            return False
        cd = p["cds"][(TARGET_USER, p["uid"], chip)] = int(_chips()[chip]["cd"])
        self.finish_chip(p, self._cd_change(TARGET_USER, p["uid"], chip, cd))
        return True

    def use_card(self, p, index, targets):
        chip = p["items"].get(index)
        if chip is None:
            return self.refuse(p, ERROR_LAUNCH, "no card in slot %s", index)
        pieces = self.chosen_pieces(targets)
        if not self.use_chip(p, chip, p["uid"], pieces[0] if pieces else None, targets):
            return False
        del p["items"][index]
        self.send_items(p, removed=[chip])
        self.finish_chip(p)
        return True

    def kill_paid(self, by):
        by["kills"] += 1
        self.pay_coins(by, _cfg_int("kill_reward_coin", 3), COINS_KILL)
        self.score(by, _cfg_int("kill_point", 1))

    def on_C_CHESSUSEGUNCHIP(self, body):
        me = self.player()
        gun_id = int(body.get("gunId") or 0)
        gun = me["guns"].get(gun_id)
        if gun is None or not gun["spot"]:
            return self.refuse(me, ERROR_LAUNCH, "refused an ability of piece %s", gun_id)
        self.use_gun_chip(me, gun, body.get("targetList") or {})

    def on_C_CHESSUSECAMPCHIP(self, body):
        self.use_camp_chip(self.player(), body.get("targetList") or {})

    def on_C_CHESSUSECHIP(self, body):
        """An item card: played once, from its slot in the hand."""
        self.use_card(self.player(), int(body.get("index") or 0), body.get("targetList") or {})

    def on_C_CHESS_USE_ITEM_FLY(self, body):
        """The Troop Carrier: deploys whatever the roll, and leaves the turn where it is."""
        me = self.player()
        index = int(body.get("itemIndex") or 0)
        slot = index if me["items"].get(index) == TROOP_CARRIER else next((i for i, c in me["items"].items() if c == TROOP_CARRIER), None)
        gun = me["guns"].get(int(body.get("gunId") or 0))
        if (slot is None or gun is None or gun["spot"] or self.players[self.turn] is not me
                or len(self.on_board(me)) >= _cfg_int("launch_limit", 3)):
            return log.warning("chess: refused the deployment card of slot %s", index)
        del me["items"][slot]
        self._fly(me, gun["info"]["gunId"], int(body.get("spotId") or 0) or base_spot(self.mission, me["order"]), body.get("direction") or 0)
        self.send_items(me, removed=[TROOP_CARRIER])

    def on_C_CHESS_USE_ITEM_DICE(self, body):
        """Planned Operation: choose the roll. Its use_stage is 6, before the turn's roll."""
        me = self.player()
        index, point = int(body.get("itemIndex") or 0), int(body.get("dicePoint") or 0)
        slot = index if me["items"].get(index) == PLANNED_OPERATION else next((i for i, c in me["items"].items() if c == PLANNED_OPERATION), None)
        if slot is None or not 1 <= point <= 6 or self.dice or self.players[self.turn] is not me or self.stage_id != PRE_BATTLE:
            return log.warning("chess: refused the chosen roll of slot %s", index)
        del me["items"][slot]
        self.send_items(me, removed=[PLANNED_OPERATION])
        me["chosen_die"] = point
        self.on_C_CHESSMOVEROLL({})

    def on_C_CHESSSETAUTO(self, body):
        mode = bool(body.get("mode"))
        if mode == self.auto:
            return
        self.auto = mode
        now = time.time()
        if mode:
            self.auto_since = now
        else:
            self.auto_time += now - self.auto_since
        self.reply("S_CHESS_USER_STATUS", {"uid": self.me, "isAi": mode})
        me = self.player()
        if not mode or self.over or not self.players or self.players[self.turn] is not me or self.stage_id not in (AIR_DROP, TURN_FLIGHT, PRE_BATTLE, MOVE, BATTLE_SELECT, BATTLE, POST_BATTLE):
            return
        self.seq += 1
        self.later(BOT_PAUSE, self.end_turn if self.dice else lambda: self.bot_turn(me))

    def snapshot(self):
        """S_ChessReconnect: where the game stands, for a client that lost its socket."""
        me = self.player()
        order = {p["uid"]: p for p in self.players}
        cur = self.players[self.turn]["uid"] if self.players else 0
        msg = {"userList": [{"userId": p["uid"], "playOrder": p["order"], "camp": p["camp"], "score": p["points"], "handChipList": dict(p["items"]),
                             "equipChipList": {i: {"chipId": c, "exp": 0} for i, c in p["equips"].items()},
                             "maxItemNum": _cfg_int("chip_basic_limit2", 5), "maxEquipChipNum": _cfg_int("chip_basic_limit", 5),
                             "maxOnlineGunNum": _cfg_int("launch_limit", 3), "killGun": p["kills"], "totalAchieveNum": p["achieves"],
                             "isRobot": p["bot"]} for p in order.values()],
               "gunList": [{"gunInfo": g["info"], "currentPoint": g["spot"]} for p in self.players for g in p["guns"].values()],
               "ActiveChipList": [{"Id": chip, "StaticChipId": chip, "OwnType": own_type, "OwnId": own_id, "Cd": int(_chips()[chip]["cd"]), "CdCount": cd}
                                  for (own_type, own_id, chip), cd in me["cds"].items()],
               "currentStage": self.stage_id, "stageEndTime": self.stage_end, "roundNum": self.round, "curId": cur, "curType": TYPE_PLAYER,
               "userStatus": [{"uid": p["uid"], "isAi": p["bot"] or (p is me and self.auto)} for p in self.players],
               "isLock": self.locked, "campSkillInfo": {int(r["id"]): int(r["camp_skill"]) for r in stc.table("chess_camp_type")},
               "gameStartTime": int(self.started), "stageIsComp": False, "missionId": self.mission}
        if self.after_shop:
            msg["userChooseChip"] = {"token": me["token"], "chipList": self.offer}
        return msg

    def _roll(self, uid):
        p = self.player(uid)
        dice = {i + 1: self.rng.randint(1, 6) for i in range(1 + p["extra_dice"])}
        p["extra_dice"] = 0
        if p.get("chosen_die"):
            dice[1] = p.pop("chosen_die")
        self.dice, self.move = dice[1], sum(dice.values())    # the client checks a deployment on the first die
        self.reply("S_CHESSROLLRESULT", {"uid": int(uid), "diceList": dice, "diceListResult": dice})
        return self.dice

    # --- the bots
    def bot_turn(self, p):
        self.tick_cooldowns(p)
        if not self.on_board(p):
            self._fly(p, next(g for g, x in p["guns"].items() if not x["spot"]), base_spot(self.mission, p["order"]), 0)
        self.stage(PRE_BATTLE, 5, p["uid"])
        self.later(BOT_PAUSE, lambda: self.bot_skills(p, BOT_SKILLS))

    def bot_skills(self, p, left):
        if left and self.bot_use_one(p):
            if not self.over:
                self.later(BOT_SKILL_PAUSE, lambda: self.bot_skills(p, left - 1))
            return
        self.bot_roll(p)

    def bot_use_one(self, p):
        """One skill, tech skill or card that has something to do; False when there is none."""
        tries = [(camp_chip(p["camp"]), None)] + [(int(g["info"]["skillChipId"]), g) for g in self.on_board(p)]
        self.rng.shuffle(tries)
        for chip, gun in tries:
            if gun is not None and self.chip_cooldown(p, TARGET_GUN, gun["info"]["gunId"], chip) == 0:
                targets = self.bot_targets(p, chip, gun)
                if targets is not None and self.use_gun_chip(p, gun, targets):
                    return True
            elif gun is None and chip and self.chip_cooldown(p, TARGET_USER, p["uid"], chip) == 0:
                targets = self.bot_targets(p, chip, None)
                if targets is not None and self.use_camp_chip(p, targets):
                    return True
        for index, chip in list(p["items"].items()):
            targets = self.bot_targets(p, chip, None)
            if targets is not None and self.use_card(p, index, targets):
                return True
        return False

    def bot_enemies(self, p, gun=None):
        """Enemy pieces; given a piece, those a skill can reach from it, the nearest first."""
        enemies = [g for x in self.players if x is not p for g in self.on_board(x)]
        if gun is None:
            return enemies
        coords = _coords(self.mission)
        here = coords.get(gun["spot"])
        if not here:
            return []
        reach = [(distance(here, coords[g["spot"]]), i) for i, g in enumerate(enemies) if g["spot"] in coords]
        return [enemies[i] for d, i in sorted(reach) if d <= SKILL_RANGE]

    def bot_targets(self, p, chip, gun):
        """The target list a client would send for this ability, or None when using it now would be a waste."""
        mine = self.on_board(p)
        hurt = sorted((g for g in mine if int(g["info"]["hp"]) < int(g["info"]["maxHp"])), key=lambda g: int(g["info"]["hp"]))

        def one(piece):
            return {"firstTargetIdList": [piece["info"]["gunId"]]}
        if chip in (20101, 20301):
            return one(gun)
        if chip in (20201, 20401):
            enemies = self.bot_enemies(p, gun)
            if not enemies:
                return None
            second = enemies[0]["info"]["gunId"] if chip == 20201 else enemies[0]["spot"]
            return {"firstTargetIdList": [gun["info"]["gunId"]], "secondTargetIdList": [second]}
        if chip == 30201:
            enemies = sorted(self.bot_enemies(p), key=lambda g: int(g["info"]["hp"]))
            return one(enemies[0]) if enemies else None
        if chip == 30301:
            return one(mine[0]) if mine and p["supplies"] < SUPPLY_FREE_USES else None
        if chip == 30401:
            return one(hurt[0]) if hurt else None
        if chip == 30501:
            return one(hurt[0]) if hurt and int(hurt[0]["info"]["hp"]) <= LOW_HP and len(mine) > 1 else None
        if chip == 14601:
            return {} if hurt else None
        if chip == 15401:
            return None if p["extra_dice"] else {}
        if chip in (19101, 19201, 19301):
            return one(mine[0]) if mine else None
        return None

    def bot_buy(self, p):
        limit = _cfg_int("chip_basic_limit2", 5)
        cards = [r for r in _store_chips() if int(r["id"]) in BOT_CARDS and int(r["init_time"]) <= self.round and _price(r) <= p["token"]]
        if cards and len(p["items"]) < limit and self.rng.random() < BOT_CARD_CHANCE:
            card = self.rng.choice(cards)
            p["token"] -= _price(card)
            p["items"][next(i for i in range(1, limit + 1) if i not in p["items"])] = int(card["id"])

    def bot_roll(self, p):
        self.stage(MOVE, 5, p["uid"])
        self.acted = False
        self._roll(p["uid"])
        guns = self.on_board(p)

        def act():
            moved = None
            if self.can_deploy(p) and (not guns or self.rng.random() < 0.5):
                gun = next(g for g, x in p["guns"].items() if not x["spot"])
                self._fly(p, gun, base_spot(self.mission, p["order"]), 0)
                self.reply("S_CHESS_MOVE_END", {})
            elif guns:
                moved = self.bot_pick(p, guns)
                self._walk(p, moved)
                self.reply("S_CHESS_MOVE_END", {})
            if not self.over:
                self.later(BOT_PAUSE, lambda: self.bot_after_move(p, moved))
        self.later(BOT_PAUSE, act)

    def bot_pick(self, p, guns):
        """The piece that would end its walk in range of an enemy, otherwise the one nearest a lap."""
        coords = _coords(self.mission)
        enemies = [coords[g["spot"]] for g in self.bot_enemies(p) if g["spot"] in coords]
        for gun in guns:
            end = coords.get(self._walk_end(gun)[0])
            if end and any(distance(end, at) <= int(gun["info"]["attackRange"]) for at in enemies):
                return gun
        return max(guns, key=lambda g: g["steps"])

    def bot_after_move(self, p, gun):
        def then():
            if self.grant_extra_roll():
                self.bot_roll(p)
            else:
                self.end_stage(p)
        targets = self.targets(gun) if gun else []
        if not targets:
            return then()
        self.battle = {"gun": gun, "by": p, "then": then}
        self.start_battle(min(targets, key=lambda g: int(g["info"]["hp"])), TARGET_GUN, p["uid"], 8)
        self.later(BOT_BATTLE_PAUSE, self.battle_roll)

    def end_stage(self, p):
        self.wear_off(p)
        self.stage(END, 1, p["uid"])
        self.later(0.5, lambda: self.start_turn(self.turn + 1))

    def end_turn(self):
        if self.over:
            return
        self.end_stage(self.players[self.turn])

    def _walk_end(self, gun):
        """(spot, steps) of this roll's walk: dice + the piece's ap steps, at least 1, along the ring."""
        ring = _next_spot(self.mission)
        steps = max(1, (self.move or self.dice) + int(gun["info"]["ap"]))
        cur = gun["spot"]
        for _ in range(steps):
            cur = ring.get(cur, cur)
        return cur, steps

    def _walk(self, p, gun):
        """Move a piece along the ring and score a finished lap."""
        ring = _next_spot(self.mission)
        old = gun["spot"]
        cur, steps = self._walk_end(gun)
        gun["spot"] = cur
        gun["steps"] += steps
        self.reply("S_CHESSGUNMOVE", {"uid": p["uid"], "type": MOVE_WALK, "gunId": gun["info"]["gunId"], "oldSpotId": old, "newSpotId": cur,
                                      "stepNum": steps, "isAtk": False})
        if gun["steps"] >= max(1, len(ring)):
            gun["steps"] -= len(ring)
            p["achieves"] += 1
            self.pay_coins(p, _cfg_int("achieve_reward_coin", 6), COINS_LAP)
            self.score(p, _cfg_int("achieve_point", 2))

    def score(self, p, points):
        p["points"] += points
        if p["points"] >= _cfg_int("chess_goal_point", 5):
            self.finish()

    def targets(self, gun):
        """Enemy pieces in range of this piece."""
        coords = _coords(self.mission)
        me = coords.get(gun["spot"])
        out = []
        for p in self.players:
            if p["uid"] == gun["info"]["uid"]:
                continue
            for g in self.on_board(p):
                if me and g["spot"] in coords and distance(me, coords[g["spot"]]) <= int(gun["info"]["attackRange"]):
                    out.append(g)
        return out

    def after_move(self, gun):
        if self.over:
            return
        if gun and self.targets(gun):
            self.battle = {"gun": gun}
            seconds = _cfg_int("chess_player_battle_time", 20)
            self.stage(BATTLE_SELECT, seconds, self.me)
            return self.later(seconds, self.post_battle)
        self.post_battle()

    def post_battle(self):
        if self.grant_extra_roll():
            return self.player_main()
        seconds = _cfg_int("chess_player_end_time", 30)
        self.stage(POST_BATTLE, seconds, self.me)
        self.later(seconds, self.end_turn)

    def finish(self, surrender=False):
        if self.over:
            return
        self.over = True
        self.game_time = int(time.time() - self.started)
        if self.auto:
            self.auto_time += time.time() - self.auto_since
        ranked = sorted(self.players, key=lambda p: (surrender and p["uid"] == self.me, -p["points"], -p["kills"], p["order"]))
        for i, p in enumerate(ranked):
            p["rank"] = i + 1
        self.reply("S_CHESSWIN", {"rank": {p["uid"]: p["rank"] for p in ranked}, "autoTime": {self.me: int(self.auto_time)}, "gameTime": self.game_time})
        if self.on_finish:
            self.on_finish(self)

    # --- client messages
    def on_C_CHESSSETCAMP(self, body):
        camp = int(body.get("camp") or 0)
        current = next((x for x in self.players if not x["camp"]), None)
        if current is not None and current["uid"] == self.me and camp in self.free_camps():
            self.set_camp(self.me, camp)

    def on_C_CHESSSETTEAM(self, body):
        self.set_team(self.me, int(body.get("teamId") or 0))

    def on_C_CHESSFLY(self, body):
        me = self.player()
        first = self.me not in self.done_flight
        free = self.stage_id == TURN_FLIGHT and self.players[self.turn] is me
        gun = me["guns"].get(int(body.get("gunId") or 0))
        if gun is None or gun["spot"] or not (first or free or (self.players[self.turn] is me and self.can_deploy(me))):
            return log.warning("chess: refused a deployment in stage %s on a roll of %s", self.stage_id, self.dice)
        spot = int(body.get("spotId") or 0) or base_spot(self.mission, me["order"])
        self._fly(me, body.get("gunId"), spot, body.get("direction") or 0)
        if first:
            self.done_flight.add(self.me)
            self.seq += 1
            return self.later(1.0, lambda: self.start_turn(0))
        if free:
            self.seq += 1
            return self.later(1.0, self.player_main)
        self.acted = True
        self.reply("S_CHESS_MOVE_END", {})
        self.seq += 1
        self.later(1.0, self.post_battle)

    def on_C_CHESSMOVEROLL(self, body):
        me = self.player()
        if self.dice or self.players[self.turn] is not me:
            return
        seconds = _cfg_int("chess_move_time", 30)
        self.stage(MOVE, seconds, self.me)
        self.acted = False
        self._roll(self.me)
        if not self.on_board(me) and not self.can_deploy(me):
            self.later(BOT_PAUSE, self.post_battle)    # nothing can move or take off
        else:
            self.later(seconds, self.post_battle)

    def on_C_CHESSFLYORMOVE(self, body):
        pass                                           # a notice: the client goes on to C_ChessFly / C_ChessMove

    def on_C_CHESSMOVE(self, body):
        me = self.player()
        gun = me["guns"].get(int(body.get("gunId") or 0))
        if gun is None or not gun["spot"] or not self.dice or self.acted:
            return
        self.acted = True
        self._walk(me, gun)
        if self.over:
            return
        self.reply("S_CHESS_MOVE_END", {})
        self.seq += 1
        self.later(2.0, lambda: self.after_move(gun))

    def on_C_CHESSATTACK(self, body):
        if not self.battle:
            return
        target = next((g for g in self.targets(self.battle["gun"]) if g["info"]["gunId"] == int(body.get("targetId") or 0)), None)
        if target is None:
            return
        seconds = _cfg_int("chess_player_battle_roll_time", 15)
        self.battle.update(by=self.player(), then=self.post_battle)
        self.start_battle(target, int(body.get("targetType") or 0), self.me, seconds)
        self.later(seconds, self.post_battle)

    def start_battle(self, target, kind, uid, seconds):
        self.battle.update(target=target, kind=kind)
        self.stage(BATTLE, seconds, uid)
        self.reply("S_CHESSGUNBATTLE", {"atkType": kind, "atkId": self.battle["gun"]["info"]["gunId"], "atkDiceNum": 1, "defType": kind,
                                        "defId": target["info"]["gunId"], "defDiceNum": 1})

    def on_C_CHESSBATTLEROLL(self, body):
        if self.players[self.turn]["uid"] == self.me:
            self.battle_roll()

    def battle_roll(self):
        b = self.battle
        if not b or "target" not in b:
            return
        atk, dfn = self.rng.randint(1, 6), self.rng.randint(1, 6)
        target, kind = b["target"], b["kind"]
        self.reply("S_CHESSBATTLEROLLRESULT", {
            "atkUid": b["by"]["uid"], "atkDiceList": {1: atk}, "atkDiceListResult": {1: atk}, "defUid": target["info"]["uid"], "defDiceList": {1: dfn},
            "defDiceListResult": {1: dfn}, "atkType": kind, "atkId": b["gun"]["info"]["gunId"], "defType": kind, "defId": target["info"]["gunId"]})
        hurt = int(b["gun"]["info"]["power"]) if atk >= dfn else 0
        absorbed = min(int(target["info"].get("shield") or 0), hurt)
        target["info"]["shield"] = int(target["info"].get("shield") or 0) - absorbed
        target["info"]["hp"] = max(0, int(target["info"]["hp"]) - (hurt - absorbed))
        self.reply("S_CHESSATTACKHURT", {"atkHurt": 0, "defHurt": hurt, "defShield": target["info"]["shield"], "defHp": target["info"]["hp"],
                                         "endTime": int(time.time()) + 2, "isAgain": False})
        self.battle = None
        if not target["info"]["hp"]:
            self.remove_piece(target)
            self.kill_paid(b["by"])
        if not self.over:
            self.seq += 1
            self.later(2.0, b["then"])

    def on_C_CHESSEND(self, body):
        if self.players[self.turn]["uid"] == self.me:
            self.end_turn()

    def on_C_CHESS_EXIT_GAME(self, body):
        if self.single:                 # FlightChessGameController$$RequestExitSingleGame leaves on S_ChessLobbyEndGame
            self.over = True
            return self.reply("S_CHESSLOBBY_ENDGAME")
        self.finish(surrender=True)
