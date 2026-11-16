-- [gf-offline] Battle tools: target practice's damage log after every fight, each fight saved to a CSV, the simulator, and Mobile Armors in target practice.
-- Damage per unit is only kept when BattleController.NeedDamageStatistic is true, which the client limits to target
-- practice, so the getter is replaced (the collectors' target practice extras check isTargetTrainBattle themselves).
-- RequestBattleFinish opens the log for target practice only; this does the same for other fights.
-- TargetTrainSettlement.Init shows just the totals and the unit list for a record whose type isn't 1-4.
-- The client's own simulator scene (BattleMoni) ships without its controller and dolls, and nothing in a fight reads its random
-- damage or seed settings, so the simulator works on target practice fights: a chosen enemy team through
-- TargetTrainData.GetEnemyTeamID, the seed through BRandom.Init, the damage spread through BattleHurtCfg.floatWide (each row
-- passes through InitData once), and repeat runs through BattleController.RestartBattle, the same call the pause menu makes.
-- The restart happens at the start of BattleManager.RequestBattleFinish, in place of it: by the time BattleController hears of the end,
-- the manager has stopped its events and timers, and only the normal ending (DelayUninit) puts them right. A restart from there froze.
-- Time limits end a fight the way a remote fight's timer does: RequestBattleFinish(false) at the end of BattleManager.FrameMove. The fight clock counts
-- game frames, so game speed and pauses don't change it. A drone stage is target_type 1 in mission_targettrain.
-- A chosen Mobile Armor: right after BattleManager.InitFriendlyGun, a target practice fight gets what that method gives a vehicle spot: isVehicleBattle, friendlyVehicle
-- and an empty listFriendlyGun, so CreateFriendlyCharacterManager builds the armor instead of the echelon. The echelon's fairy stays out too: friendlyFairy and friendlyFairyData are cleared there,
-- and again by hooks on InitFriendlyFairy and just before CreateFairyData, which builds the fairy's data from it (a team with no fairy has it nil). HOCs need nothing: Data.TargetTrainSpotAction fills battleSquadTeam from
-- TargetTrainGameData.ListSquad. The results screen only counts units with a row, so the armor's damage goes straight into the totals and the idle dolls' rows are dropped.
-- Its own row is added just while TargetTrainSettlement.InitLogItem draws, so saved records never hold it. TargetTrainSettlementItem.Init has no armor branch and needs a real row to draw, so the row is
-- a HOC's (damage only, no hit or armor columns) with the first HOC's id, and gets the armor's icon and name afterwards.
-- The armor is chosen in target practice's HOC panel, from the game's own vehicle tab: DeploymentSquadType.Init closes it when TargetTrainSquadListContainer is open, and everything behind it works once it is
-- opened again. A label's button is off here (CommonVehicleListLableCtrl.Awake leaves it on only with CommonSquadListCtrl open): a tap flips its toggle, which calls SelectCurrentLabel, so that is what picks the armor.
-- The Confirm button keeps the pick and Close drops it. It is stored in PlayerPrefs, like the game's own HOC choice.
-- Any failure here goes to mod_errors.txt and leaves the fight's own ending alone.

do
	local ok, err = pcall(function()
		local log_on, csv_on, sim_on = GF_OPTIONS.damage_log == "1", GF_OPTIONS.damage_csv == "1", GF_OPTIONS.simulator == "1"
		local armor_on = GF_OPTIONS.mobile_armor == "1"
		if not (log_on or csv_on or sim_on or armor_on) then
			return
		end

		local util = require 'xlua.util'
		local BC = CS.GF.Battle.BattleController
		local Screen = CS.TargetTrainSettlement
		local PREFAB = "UGUIPrefabs/MissionSelection/CanvasTargettrainLog"
		local UNIT_COLUMNS = "unit_id,type,name,damage,shield_damage,damage_taken,shield_damage_taken,armor_broken,max_hp\n"
		local HEADER = "time,fight_seconds,enemy_team," .. UNIT_COLUMNS
		local SIM_HEADER = "time,run,seed,won,fight_seconds,enemy_team," .. UNIT_COLUMNS
		local HIDE = {"SingleInfoGroup", "MultipleInfoGroup", "SpecialInfoGroup", "FormationInfoGroup", "LogPlayerNameGroup", "BtnShowFormation"}
		local ARMOR_ROW_FIELDS = {"rawDamageTotal", "shieldDamageTotal", "takeDamageTotal", "shieldTakeDamageTotal", "defBreakTotal", "maxHealth"}

		xlua.private_accessible(BC)
		xlua.private_accessible(Screen)
		xlua.private_accessible(CS.GF.Battle.BattleFieldTeamHolderNew)

		local finished, screen = nil, nil

		local function safe(fn)
			local good, v = pcall(fn)
			return good and v or nil
		end

		local function team_list(battle)
			local holder = battle.friendlyTeamHolder
			return holder.listCharacterData or holder.mListCharacterData
		end

		-- Init(Gun) also accepts a SangvisGun, and xLua picks by what fits, so that overload is called by name
		local function init_sangvis(row, gun)
			local types = CS.System.Array.CreateInstance(typeof(CS.System.Type), 1)
			types:SetValue(typeof(CS.SangvisGun), 0)
			local args = CS.System.Array.CreateInstance(typeof(CS.System.Object), 1)
			args:SetValue(gun, 0)
			typeof(CS.TargetTrainStatisticData):GetMethod("Init", types):Invoke(row, args)
		end

		local function add_gun(record, names, member)
			local gun = member.gun
			local kind = gun:GetType().Name
			if kind == "SummonGun" then
				return
			end
			local row = CS.TargetTrainStatisticData()
			if kind == "SangvisGun" then
				init_sangvis(row, gun)
			else
				row:Init(gun)
			end
			names[tostring(gun.id)] = GF_UNIT_NAME(member)
			record.ListTeamStatisticData:Add(row)
		end

		local function collect(battle, stats)
			local record, names = CS.TargetTrainRecordData(), {}
			record.timeStamp = CS.GameData.GetCurrentTimeStamp()
			record.battleTime = CS.GF.Battle.BattleFrameManager.Instance:GetCurBattleTime()
			local list = team_list(battle)
			for i = 0, list.Count - 1 do
				local good, e = pcall(add_gun, record, names, list[i])
				if not good then
					GF_MOD_ERROR("damage log row", e)
				end
			end
			local fairy = battle.friendlyFairy
			if fairy ~= nil then
				local row = CS.TargetTrainStatisticData()
				row:Init(fairy)
				record.ListTeamStatisticData:Add(row)
				names[tostring(row.dynamicID)] = safe(function() return fairy.info.name end)
			end
			local data = CS.TargetTrainGameData.instance
			local saved = data.currentRecordData
			data.currentRecordData = record
			data:SetDamageLog(stats)
			data.currentRecordData = saved
			return record, names
		end

		local function cell(v)
			local s = tostring(v == nil and "" or v)
			if string.find(s, '[,"\r\n]') then
				s = '"' .. string.gsub(s, '"', '""') .. '"'
			end
			return s
		end

		-- One file a day; before = the cells each row starts with
		local function write_csv(prefix, header, before, stats, names)
			local file = CS.System.IO.File
			local dir = CS.UnityEngine.Application.dataPath .. "/../battle_logs"
			CS.System.IO.Directory.CreateDirectory(dir)
			local path = dir .. "/" .. prefix .. "_" .. os.date("%Y-%m-%d") .. ".csv"
			local out = {file.Exists(path) and file.ReadAllText(path) or header}
			for id, s in pairs(stats) do
				local kind = string.match(tostring(s.DamageInfoType), "^%w+")
				out[#out + 1] = before .. "," .. table.concat({cell(id), cell(kind), cell(names[tostring(id)]),
					cell(s.rawDamageTotal), cell(s.shieldDamageTotal), cell(s.takeDamageTotal), cell(s.shieldTakeDamageTotal),
					cell(s.defBreakTotal), cell(s.maxHealth)}, ",") .. "\n"
			end
			file.WriteAllText(path, table.concat(out))
		end

		local function fight_seconds()
			return string.format("%.2f", safe(function() return CS.GF.Battle.BattleFrameManager.Instance:GetCurBattleTime() end) or 0)
		end

		local function enemy_of(battle)
			return cell(safe(function() return battle.enemyTeamidUse end))
		end

		local function show(record)
			local go = CS.UnityEngine.Object.Instantiate(CS.ResManager.GetObjectByPath(PREFAB))
			local good, e = pcall(function()
				screen = go:GetComponent(typeof(Screen))
				screen.curdata = record
				screen:Init()
				screen.TextTitle.text = "Battle report"
				for _, name in ipairs(HIDE) do
					pcall(function() screen[name].gameObject:SetActive(false) end)
				end
			end)
			if not good then
				screen = nil
				CS.UnityEngine.Object.Destroy(go)
				error(e)
			end
		end

		-- ------------------------------------------------------------ simulator

		local sim_team = tonumber(GF_OPTIONS.sim_enemy_team or "") or 0
		local sim_runs = tonumber(GF_OPTIONS.sim_runs or "") or 1
		local sim_seed = tonumber(GF_OPTIONS.sim_seed or "") or 0
		local sim_flat = GF_OPTIONS.sim_no_random == "1"
		local limit_drone = tonumber(GF_OPTIONS.sim_limit_drone or "") or 0
		local limit_other = tonumber(GF_OPTIONS.sim_limit_other or "") or 0
		local ARMOR_KEY = "gf_offline_target_practice_armor"
		local HOC_TITLE = "Main/TeamGroup/SquardGroup/UI_SquardGroup/UI_Text_Squard"
		local armor_id, armor_pending, hoc_title, title_broken = nil, 0, nil, false
		local armor_now, armor_row, armor_drawn, armor_row_of = false, nil, nil, nil
		local run, in_practice = 0, false
		local drone_stage, limit_fight, limit_start, limit_left = false, nil, 0, 0
		local hurt_rows, flat_now = {}, false

		local function set_flat(on)
			if on ~= flat_now then
				flat_now = on
				for _, r in ipairs(hurt_rows) do
					r.row.floatWide = on and 0 or r.wide
				end
			end
		end

		local function practice_fight()
			return in_practice and CS.TargetTrainGameData.instance.isTargetTrainBattle
		end

		local function start_random()
			local practice = practice_fight()
			if practice and sim_seed > 0 then
				CS.GF.Battle.BRandom.Init(sim_seed)
			end
			set_flat(sim_flat and practice)
		end

		local function sim_row(battle)
			local names = {}
			local list = team_list(battle)
			for i = 0, list.Count - 1 do
				names[tostring(list[i].gun.id)] = GF_UNIT_NAME(list[i])
			end
			local seed = safe(function() return CS.GF.Battle.BRandom.Seed end)
			local before = table.concat({cell(os.date("%Y-%m-%d %H:%M:%S")), cell(run), cell(seed), battle.ifEnemyDie and "1" or "0",
				fight_seconds(), enemy_of(battle)}, ",")
			write_csv("simulator", SIM_HEADER, before, battle.battleDamageStatistics, names)
		end

		-- The last run, which ends like any fight
		local function sim_last(battle)
			run = run + 1
			local good, e = pcall(sim_row, battle)
			if not good then
				GF_MOD_ERROR("simulator table", e)
			end
			run, in_practice = 0, false
			set_flat(false)
		end

		-- true: the next run has started in place of this ending
		local function sim_restart(manager, battle, forceLose)
			local checked, e = pcall(function() manager:CheckBattleFinish(forceLose) end)     -- sets ifEnemyDie
			if not checked then
				GF_MOD_ERROR("simulator result", e)
			end
			run = run + 1
			local wrote, e2 = pcall(sim_row, battle)
			if not wrote then
				GF_MOD_ERROR("simulator table", e2)
			end
			local good, e3 = pcall(function() battle:RestartBattle() end)
			if good then
				pcall(function() CS.CommonController.LightMessageTips("Run " .. (run + 1) .. " of " .. sim_runs) end)
				return true
			end
			GF_MOD_ERROR("simulator restart", e3)
			run = run - 1
			return false
		end

		local function id_of(vehicle)
			return tonumber(tostring(vehicle.id)) or 0
		end

		local function saved_armor_id()
			if armor_id == nil then
				armor_id = tonumber(CS.UnityEngine.PlayerPrefs.GetString(ARMOR_KEY, "")) or 0
			end
			return armor_id
		end

		-- nil when none is chosen, or the choice belongs to another account
		local function chosen_armor()
			if saved_armor_id() > 0 then
				return CS.GameData.listVehicle:GetDataById(armor_id)
			end
			return nil
		end

		local function armor_name(armor)
			return armor.vehicleInfo.Name
		end

		local function use_armor()
			if not practice_fight() then
				return
			end
			local armor = chosen_armor()
			if armor == nil then
				return
			end
			local Dynamic = CS.GF.Battle.BattleDynamicData
			Dynamic.isVehicleBattle = true
			Dynamic.friendlyVehicle = armor
			Dynamic.listFriendlyGun = CS.GF.Battle.Team()
			Dynamic.friendlyFairy = nil
			Dynamic.friendlyFairyData = nil
			armor_now = true
		end

		local function open_armor_tab(menu)
			local tab = menu:GetComponentInChildren(typeof(CS.SquadListController), true).leftVehicleItem
			tab.open = true
			tab.openChild.gameObject:SetActive(true)
			tab.openClose.gameObject:SetActive(false)
			tab.toogle.interactable = true
			tab.transform:SetSiblingIndex(1)     -- a closed tab was moved to the end
		end

		local function in_armor_menu(list)
			return list ~= nil and string.match(tostring(list.listType), "^%w+") == "TargetTrain"
		end

		-- A switch between armors turns one off and the other on, in either order
		local function pick_armor(label, on)
			local id = id_of(label.vehicle)
			if on then
				armor_pending = id
			elseif armor_pending == id then
				armor_pending = 0
			end
		end

		-- The list being drawn: its toggles show the pick, and moving them isn't a tap
		local function mark_armor(label, vehicle)
			local on = id_of(vehicle) == armor_pending
			label.exToggle.group.allowSwitchOff = true
			label.exToggle.isOn = on
			label:SelectCurrentLabel(on)
		end

		local function confirm_armor()
			local changed = armor_pending ~= saved_armor_id()
			armor_id = armor_pending
			if changed then
				CS.UnityEngine.PlayerPrefs.SetString(ARMOR_KEY, tostring(armor_id))
				CS.UnityEngine.PlayerPrefs.Save()
				local armor = chosen_armor()
				CS.CommonController.LightMessageTips(armor ~= nil and "Mobile Armor: " .. armor_name(armor) or "No Mobile Armor: the echelon fights")
			end
		end

		-- The title over the HOC slots says which armor will fight
		local function show_armor_choice(setting)
			local text = setting.transform:Find(HOC_TITLE):GetComponent(typeof(CS.UnityEngine.UI.Text))
			hoc_title = hoc_title or text.text
			local armor = chosen_armor()
			text.horizontalOverflow = CS.UnityEngine.HorizontalWrapMode.Overflow
			text.text = armor ~= nil and hoc_title .. " + " .. armor_name(armor) or hoc_title
		end

		local function dress_armor_row(item, armor)
			item.TextName.text = armor_name(armor)
			local holder = item.IconTemplate
			for i = holder.childCount - 1, 0, -1 do
				local child = holder:GetChild(i)
				if child:GetComponent(typeof(CS.CommonIconController)) ~= nil then
					CS.UnityEngine.Object.Destroy(child.gameObject)
				end
			end
			local builder = CS.CommonIconController.CommonIconControllerBuilder()
			builder:SetVehicleInfo(armor.vehicleInfo, 0)
			builder:SetCloseTip(true, true)
			builder:Build(holder)
		end

		local function armor_record(battle)
			local record = CS.TargetTrainGameData.instance.currentRecordData
			local rows = record.ListTeamStatisticData
			for i = rows.Count - 1, 0, -1 do
				local kind = string.match(tostring(rows[i].type), "^%w+")
				if kind == "normal" or kind == "sangvis" then
					rows:RemoveAt(i)
				end
			end
			local armor_ids = {}
			local list = team_list(battle)
			for i = 0, list.Count - 1 do
				armor_ids[tostring(list[i].gun.id)] = true
			end
			local row = CS.TargetTrainStatisticData()
			row.type = CS.TargetTrainStatisticInfoType.squad
			row.infoid = CS.GameData.listSquadInfo:GetDataByIndex(0).id
			for id, stat in pairs(battle.battleDamageStatistics) do
				if armor_ids[tostring(id)] then
					record:AddDamageInfo(stat)
					record:AddDamageInfoPercent(stat)
					for _, field in ipairs(ARMOR_ROW_FIELDS) do
						row[field] = row[field] + stat[field]
					end
				end
			end
			armor_row, armor_row_of = row, CS.GF.Battle.BattleDynamicData.friendlyVehicle
		end

		-- Timed from the fight's first frame, each run having its own
		local function check_limit(manager)
			local battle = BC.Instance
			if battle == nil or not battle.isTargetTrain then
				return
			end
			local now = CS.GF.Battle.BattleFrameManager.Instance:GetCurBattleTime()
			if limit_fight == nil or limit_fight ~= battle then
				limit_fight, limit_start = battle, now
				limit_left = drone_stage and limit_drone or limit_other
			elseif limit_left > 0 and now - limit_start >= limit_left then
				limit_left = 0
				manager:RequestBattleFinish(false)
			end
		end

		if sim_on or armor_on then
			xlua.private_accessible(CS.MissionSelectionDroneTrainSettingController)
			util.hotfix_ex(CS.MissionSelectionDroneTrainSettingController, 'GoBattle', function(self, ...)
				run, in_practice = 0, true
				drone_stage = safe(function() return self.TargetTraindata.target_type == 1 end) or false
				return self:GoBattle(...)
			end)
		end

		if armor_on then
			xlua.private_accessible(CS.GF.Battle.BattleDynamicData)
			util.hotfix_ex(CS.GF.Battle.BattleManager, 'InitFriendlyGun', function(self)
				self:InitFriendlyGun()
				armor_now = false
				local good, err = pcall(use_armor)
				if not good then
					GF_MOD_ERROR("Mobile Armor", err)
				end
			end)
			local Dynamic = CS.GF.Battle.BattleDynamicData
			util.hotfix_ex(Dynamic, 'InitFriendlyFairy', function()
				Dynamic.InitFriendlyFairy()
				if armor_now then
					Dynamic.friendlyFairy = nil
				end
			end)
			-- CreateFairyData makes friendlyFairyData only when there is a fairy, so the last fight's would stay, and
			-- BattleController.CreateFairy would then look for a fairy that isn't there
			util.hotfix_ex(Dynamic, 'CreateFairyData', function()
				if armor_now then
					Dynamic.friendlyFairy = nil
				end
				Dynamic.CreateFairyData()
				if armor_now then
					Dynamic.friendlyFairyData = nil
				end
			end)

			local Menu, Label = CS.TargetTrainSquadListContainer, CS.CommonVehicleListLableCtrl
			xlua.private_accessible(Menu)
			xlua.private_accessible(Label)
			xlua.private_accessible(CS.SquadListController)
			xlua.private_accessible(CS.DeploymentSquadType)
			xlua.private_accessible(CS.CommonVehicleListCtrl)
			xlua.private_accessible(CS.TargetTrainSettlementItem)
			util.hotfix_ex(Menu, 'Open', function(callback)
				local good, err = pcall(function() armor_pending = saved_armor_id() end)
				if not good then
					GF_MOD_ERROR("Mobile Armor menu", err)
				end
				Menu.Open(callback)
			end)
			util.hotfix_ex(Menu, 'Start', function(self)
				self:Start()
				local good, err = pcall(open_armor_tab, self)
				if not good then
					GF_MOD_ERROR("Mobile Armor menu", err)
				end
			end)
			util.hotfix_ex(Menu, 'OnClickConfirm', function(self)
				local good, err = pcall(confirm_armor)
				if not good then
					GF_MOD_ERROR("Mobile Armor menu", err)
				end
				self:OnClickConfirm()
			end)
			local drawing_list = false
			util.hotfix_ex(Label, 'SelectCurrentLabel', function(self, on)
				self:SelectCurrentLabel(on)
				if not drawing_list and in_armor_menu(self.commonVehicleListCtrl) then
					local good, err = pcall(pick_armor, self, on)
					if not good then
						GF_MOD_ERROR("Mobile Armor menu", err)
					end
				end
			end)
			util.hotfix_ex(Label, 'InitData', function(self, data, list)
				drawing_list = true
				self:InitData(data, list)
				if in_armor_menu(list) then
					local good, err = pcall(mark_armor, self, data)
					if not good then
						GF_MOD_ERROR("Mobile Armor menu", err)
					end
				end
				drawing_list = false
			end)
			local function update_title(setting)
				if not title_broken then
					local good, err = pcall(show_armor_choice, setting)
					if not good then
						title_broken = true
						GF_MOD_ERROR("Mobile Armor title", err)
					end
				end
			end
			util.hotfix_ex(CS.MissionSelectionDroneTrainSettingController, 'RefreshShowSquad', function(self, pos)
				self:RefreshShowSquad(pos)
				update_title(self)
			end)
			-- With no HOCs picked, this may not redraw a slot
			util.hotfix_ex(CS.MissionSelectionDroneTrainSettingController, 'OnSquadSelected', function(self, squads)
				self:OnSquadSelected(squads)
				update_title(self)
			end)
			util.hotfix_ex(Screen, 'InitLogItem', function(self)
				local row = armor_row
				armor_row = nil
				if row == nil then
					return self:InitLogItem()
				end
				local rows = self.curdata.ListTeamStatisticData
				armor_drawn = row
				rows:Insert(0, row)
				local good, err = pcall(function() self:InitLogItem() end)
				rows:Remove(row)
				armor_drawn = nil
				if not good then
					GF_MOD_ERROR("Mobile Armor results", err)
				end
			end)
			util.hotfix_ex(CS.TargetTrainSettlementItem, 'Init', function(self, data)
				self:Init(data)
				if armor_drawn ~= nil and data == armor_drawn then
					local good, err = pcall(dress_armor_row, self, armor_row_of)
					if not good then
						GF_MOD_ERROR("Mobile Armor results", err)
					end
				end
			end)
		end

		if sim_on then
			if sim_team > 0 then
				xlua.hotfix(CS.TargetTrainData, 'GetEnemyTeamID', function(self)
					return sim_team
				end)
			end
			if sim_flat then
				util.hotfix_ex(CS.BattleHurtCfg, 'InitData', function(self)
					self:InitData()
					hurt_rows[#hurt_rows + 1] = {row = self, wide = self.floatWide}
					if flat_now then
						self.floatWide = 0
					end
				end)
			end
			local Manager = CS.GF.Battle.BattleManager
			xlua.private_accessible(Manager)
			local restarting = nil
			util.hotfix_ex(Manager, 'RequestBattleFinish', function(self, forceLose)
				local battle = BC.Instance
				limit_left = 0     -- ending anyway: the limit mustn't end it a second time
				if restarting ~= nil and restarting == battle then
					return     -- the old fight's last frame before the restart takes over
				end
				if battle.isTargetTrain and run + 1 < sim_runs and sim_restart(self, battle, forceLose) then
					restarting = battle
					return
				end
				self:RequestBattleFinish(forceLose)
			end)
			if limit_drone > 0 or limit_other > 0 then
				local limit_broken = false
				util.hotfix_ex(Manager, 'FrameMove', function(self, obj, e)
					self:FrameMove(obj, e)
					if not limit_broken then
						local good, err = pcall(check_limit, self)
						if not good then
							limit_broken = true
							GF_MOD_ERROR("simulator time limit", err)
						end
					end
				end)
			end
			if sim_flat or sim_seed > 0 then
				local Dynamic = CS.GF.Battle.BattleDynamicData
				xlua.private_accessible(Dynamic)
				util.hotfix_ex(Dynamic, 'InitBattleRandom', function()
					Dynamic.InitBattleRandom()
					local good, e = pcall(start_random)
					if not good then
						GF_MOD_ERROR("simulator random", e)
					end
				end)
			end
		end

		-- ------------------------------------------------------------ hooks

		xlua.hotfix(BC, 'get_NeedDamageStatistic', function(self)
			return true
		end)

		util.hotfix_ex(BC, 'RequestBattleFinish', function(self)
			local record
			if finished ~= self and self.isTargetTrain then
				finished = self
				if armor_now then
					armor_now = false
					local good, e = pcall(armor_record, self)
					if not good then
						GF_MOD_ERROR("Mobile Armor results", e)
					end
				end
				if sim_on then
					sim_last(self)
				end
				in_practice = false
			elseif finished ~= self and not self.IsPerformBattle then
				finished = self
				in_practice = false
				set_flat(false)
				if log_on or csv_on then
					local stats = self.battleDamageStatistics
					local names = {}
					local good, r, n = pcall(collect, self, stats)
					if good then
						record, names = r, n
					else
						GF_MOD_ERROR("damage log", r)
					end
					if csv_on then
						local before = table.concat({cell(os.date("%Y-%m-%d %H:%M:%S")), fight_seconds(), enemy_of(self)}, ",")
						local wrote, e = pcall(write_csv, "damage", HEADER, before, stats, names)
						if not wrote then
							GF_MOD_ERROR("damage csv", e)
						end
					end
				end
			end
			self:RequestBattleFinish()
			if record ~= nil and log_on then
				local good, e = pcall(show, record)
				if not good then
					GF_MOD_ERROR("damage log screen", e)
				end
			end
		end)

		-- The screen's own button goes to the mission list, which is only right after target practice
		util.hotfix_ex(Screen, 'OnClickBtnBack', function(self)
			if screen ~= nil and self == screen then
				local go = self.gameObject
				screen = nil
				CS.UnityEngine.Object.Destroy(go)
				return
			end
			self:OnClickBtnBack()
		end)

		print("[gf-offline] battle tools on")
	end)
	if not ok then
		GF_MOD_ERROR("battle tools", err)
	end
end
