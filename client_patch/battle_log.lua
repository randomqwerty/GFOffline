-- [gf-offline] Skill overlay and battle log, together because util.hotfix_ex keeps only one hook per method (OnCastSkill is both's).
-- Skill overlay: a running list of the skills being cast, at the top left of the fight. The client's own BattleSkillLog is an empty
-- shell (no screen, UpdateInfo does nothing, nothing creates its entries), so this draws its own text. It has no raycaster, so it
-- can't take clicks, and it goes with the Battle scene.
-- Battle log: what happens in a fight, with the fight's clock, to battle_logs/battle_<date>_<time>_<n>.csv, one file a fight. Rows are
-- held and appended every FLUSH_ROWS, at the fight's end and when it is left, so a crash loses only the last few.
-- hotfix_ex takes its hook off while the original runs, so a call of a method inside the same method (a hit inside a hit) isn't recorded.
-- Movement is logged as status changes with the position (SetCharacterStatus): positions change every frame, which is too often to hook.
-- System.IO.File has no AppendAllText in this client (stripped), so files are appended with Lua's io, or File.AppendText for a path io can't open.
-- A failure goes to mod_errors.txt once per kind of row and leaves the fight alone.

do
	local ok, err = pcall(function()
		local overlay_on, log_on = GF_OPTIONS.skill_overlay == "1", GF_OPTIONS.battle_log == "1"
		if not (overlay_on or log_on) then
			return
		end

		local util = require 'xlua.util'
		local U = CS.UnityEngine
		local B = CS.GF.Battle
		local BC = B.BattleController
		local Character = B.BattleCharacterData
		local MAX_LINES = 14
		local FRIEND, ENEMY = "#7fd4ff", "#ff8a7a"
		local FLUSH_ROWS = 300
		local COLUMNS = {"action", "source", "source_side", "target", "target_side", "name", "id", "amount", "shield", "hurt_id", "crit", "miss", "area", "detail", "x", "y"}
		local HEADER = "\239\187\191fight_seconds,time," .. table.concat(COLUMNS, ",") .. "\n"

		local function fight_time()
			return B.BattleFrameManager.Instance:GetCurBattleTime()
		end

		local reported = {}
		local function guarded(where, fn, ...)
			local good, e = pcall(fn, ...)
			if not good and not reported[where] then
				reported[where] = true
				GF_MOD_ERROR(where, e)
			end
		end

		-- ------------------------------------------------------------ overlay

		local owner, label, lines = nil, nil, {}

		local function make()
			local existing = U.Object.FindObjectOfType(typeof(U.UI.Text))
			local go = U.GameObject("GFSkillOverlay")
			local canvas = go:AddComponent(typeof(U.Canvas))
			canvas.renderMode = U.RenderMode.ScreenSpaceOverlay
			canvas.sortingOrder = 30000
			local holder = U.GameObject("Text")
			holder.transform:SetParent(go.transform, false)
			local text = holder:AddComponent(typeof(U.UI.Text))
			text.font = existing ~= nil and existing.font or U.Resources.GetBuiltinResource(typeof(U.Font), "Arial.ttf")
			text.fontSize = 22
			text.supportRichText = true
			text.raycastTarget = false
			text.alignment = U.TextAnchor.UpperLeft
			pcall(function() holder:AddComponent(typeof(U.UI.Outline)) end)
			local rect = holder:GetComponent(typeof(U.RectTransform))
			rect.anchorMin = U.Vector2(0, 1)
			rect.anchorMax = U.Vector2(0, 1)
			rect.pivot = U.Vector2(0, 1)
			rect.anchoredPosition = U.Vector2(16, -16)
			rect.sizeDelta = U.Vector2(640, 420)
			return text
		end

		local function add_line(member, skill)
			if skill == nil or skill.isNormalAttackSkill then
				return
			end
			local battle = BC.Instance
			if owner ~= battle or label == nil then
				owner, lines, label = battle, {}, make()
			end
			lines[#lines + 1] = string.format('%5.1fs  <color=%s>%s</color>  %s', fight_time(), member.isEnemy and ENEMY or FRIEND,
				tostring(GF_UNIT_NAME(member)), tostring(skill.info.name))
			if #lines > MAX_LINES then
				table.remove(lines, 1)
			end
			label.text = table.concat(lines, "\n")
		end

		-- ------------------------------------------------------------ log

		local log_owner, path, rows, count = nil, nil, {}, 0
		local seen, last_status = {}, {}

		local function cell(v)
			local s = v == nil and "" or tostring(v)
			if string.find(s, '[,"\r\n]') then
				s = '"' .. string.gsub(s, '"', '""') .. '"'
			end
			return s
		end

		local function safe(fn)
			local good, v = pcall(fn)
			if good then
				return v
			end
			return nil
		end

		-- FP is the fight's fixed-point number
		local function number(fp)
			local v = safe(function() return fp:AsFloat() end)
			return v and string.format("%.2f", v) or nil
		end

		local function enum_name(v)
			return v ~= nil and string.match(tostring(v), "^[%w_]+") or nil
		end

		local function flag(v)
			return v and "1" or "0"
		end

		local function append(file, text)
			local f = io and io.open(file, "ab")
			if f then
				f:write(text)
				f:close()
			else
				local w = CS.System.IO.File.AppendText(file)
				w:Write(text)
				w:Close()
			end
		end

		local function flush()
			if #rows > 0 and path ~= nil then
				local text = table.concat(rows)
				rows = {}
				append(path, text)
			end
		end

		local function start_file()
			local dir = U.Application.dataPath .. "/../battle_logs"
			CS.System.IO.Directory.CreateDirectory(dir)
			count = count + 1
			path = dir .. "/battle_" .. os.date("%Y-%m-%d_%H-%M-%S") .. "_" .. count .. ".csv"
			rows, seen, last_status = {HEADER}, {}, {}
		end

		-- Before anything looks at seen or last_status, which a new file clears
		local function ensure_file()
			local battle = BC.Instance
			if log_owner ~= battle or path == nil then
				flush()
				log_owner = battle
				start_file()
			end
		end

		local function write_row(values)
			ensure_file()
			local out = {string.format("%.2f", fight_time()), os.date("%H:%M:%S")}
			for _, column in ipairs(COLUMNS) do
				out[#out + 1] = cell(values[column])
			end
			rows[#rows + 1] = table.concat(out, ",") .. "\n"
			if #rows >= FLUSH_ROWS then
				flush()
			end
		end

		local function side(member)
			return member.isEnemy and "enemy" or "friend"
		end

		local function place(values, member)
			local pos = safe(function() return member:GetCharacterPos() end)
			if pos ~= nil then
				values.x, values.y = string.format("%.2f", pos.x), string.format("%.2f", pos.y)
			end
		end

		-- The first time a fight mentions a unit it gets a row of its own, with its id and where it is
		local function introduce(member)
			ensure_file()
			local id = safe(function() return tostring(member.gun.id) end) or tostring(member)
			if not seen[id] then
				seen[id] = true
				local values = {action = "unit", source = GF_UNIT_NAME(member), source_side = side(member), id = id,
					detail = safe(function() return member.gun:GetType().Name end)}
				place(values, member)
				write_row(values)
			end
		end

		-- source and target are units; source_name is for a source known only by name
		local function row(values)
			local source, target = values.source, values.target
			if source ~= nil then
				introduce(source)
				values.source, values.source_side = GF_UNIT_NAME(source), side(source)
			else
				values.source = values.source_name
			end
			if target ~= nil then
				introduce(target)
				values.target, values.target_side = GF_UNIT_NAME(target), side(target)
			end
			write_row(values)
		end

		-- SkillImpl -> the unit it belongs to
		local function unit_of(impl)
			return impl ~= nil and safe(function() return impl:GetCharacterData() end) or nil
		end

		-- ------------------------------------------------------------ hooks

		-- fn runs before the original. A method this client doesn't have is reported and the rest still work.
		local function before(class, method, where, fn)
			local good, e = pcall(util.hotfix_ex, class, method, function(self, ...)
				guarded(where, fn, self, ...)
				return self[method](self, ...)
			end)
			if not good then
				GF_MOD_ERROR(where, e)
			end
		end

		util.hotfix_ex(Character, 'OnCastSkill', function(self, inst, skill)
			self:OnCastSkill(inst, skill)
			if overlay_on then
				guarded("skill overlay", add_line, self, skill)
			end
			if log_on and skill ~= nil then
				guarded("battle log: skill", function()
					row({action = skill.isNormalAttackSkill and "attack" or "skill", source = self, name = skill.info.name, id = skill.info.id,
						target = safe(function() return self:GetCommonTarget() end)})
				end)
			end
		end)

		if log_on then
			xlua.private_accessible(BC)
			xlua.private_accessible(Character)
			xlua.private_accessible(B.BattleManager)
			xlua.private_accessible(B.BattleDamageInfo)

			before(Character, 'Hurted', "battle log: hit", function(self, info, damage, isAOE, isCrit, isMiss, defPercent, adType)
				local hurt = safe(function() return info.hurtCfg end)
				local source = unit_of(safe(function() return info.skillImpl end))
				row({action = "hit", source = source, source_name = GF_STRIP_ID(info.name, info.id), target = self,
					name = hurt ~= nil and hurt.description or nil, hurt_id = hurt ~= nil and hurt.id or nil,
					amount = number(damage), shield = number(info.shieldValue), crit = flag(isCrit), miss = flag(isMiss), area = flag(isAOE),
					detail = "armor=" .. tostring(enum_name(adType)) .. " def=" .. tostring(number(defPercent))})
			end)

			-- Every change to a unit's life: heals as well as damage. amount is what the client was given; detail is the life before it.
			before(Character, 'UpdateLife', "battle log: life", function(self, info, value)
				row({action = "life", target = self, source = unit_of(safe(function() return info.skillImpl end)), amount = number(value),
					detail = "before=" .. tostring(number(self.gunLife))})
			end)

			before(Character, 'CastSkillUsingCfg', "battle log: sub-skill", function(self, cfg, forceTarget)
				row({action = "sub-skill", source = self, name = cfg.name, id = cfg.id, target = unit_of(forceTarget)})
			end)

			before(Character, 'ForceCastSkill', "battle log: forced skill", function(self, skillid, ignoreTrigger, fromSurveil, source)
				row({action = "forced skill", source = self, id = skillid, detail = fromSurveil and "from a trigger" or nil, target = unit_of(source)})
			end)

			before(B.BattleSurveillanceEffect, 'DoSurveillanceEffect', "battle log: trigger", function(self, info)
				row({action = "trigger", source = self.sourceData, target = self.targetData, name = self.data.description, id = self.data.id,
					detail = enum_name(info.type) .. " times=" .. tostring(self.TriggerTimes)})
			end)

			before(Character, 'AddBuff', "battle log: buff on", function(self, condition)
				local buff = condition.buffCfg
				row({action = "buff on", source = unit_of(condition.Source), target = self, name = buff.name, id = buff.id,
					detail = "duration=" .. tostring(condition.duration)})
			end)

			before(Character, 'OnBuffExpired', "battle log: buff ended", function(self, condition)
				local buff = condition.buffCfg
				row({action = "buff ended", target = self, name = buff.name, id = buff.id})
			end)

			before(Character, 'RemoveBuffNum', "battle log: buff removed", function(self, source, configid, num)
				row({action = "buff removed", source = unit_of(source), target = self, id = configid, amount = num})
			end)

			before(Character, 'SetCommonTarget', "battle log: target", function(self, target)
				if target ~= self.mCommonTarget then
					row({action = target ~= nil and "target" or "target cleared", source = self, target = target})
				end
			end)

			before(Character, 'SetTauntTarget', "battle log: taunt", function(self, target)
				row({action = "taunted", source = self, target = target})
			end)

			-- advancing, fighting, switching, standby, withdraw, coldDown, hitback, seeking, dashing, returning
			before(Character, 'SetCharacterStatus', "battle log: status", function(self, status)
				ensure_file()
				local name, id = enum_name(status), tostring(self.gun.id)
				if last_status[id] ~= name then
					last_status[id] = name
					local values = {action = "status", source = self, detail = name}
					place(values, self)
					row(values)
				end
			end)

			before(B.CharacterSkillImpl, 'Teleport', "battle log: teleport", function(self, target)
				row({action = "teleport", source = unit_of(self), detail = "to " .. tostring(number(target.x)) .. " " .. tostring(number(target.y))})
			end)

			before(Character, 'OnSelfDie', "battle log: death", function(self)
				row({action = "death", target = self})
			end)

			before(Character, 'OnKillUnit', "battle log: kill", function(self)
				row({action = "kill", source = self})
			end)

			before(Character, 'ChangeCurChargeTier', "battle log: charge", function(self, amount)
				row({action = "charge", source = self, amount = amount})
			end)

			before(Character, 'ReduceCDByBuff', "battle log: cooldown", function(self, percent)
				row({action = "cooldown cut", source = self, amount = number(percent)})
			end)

			before(Character, 'DynamicAddSkill', "battle log: skill added", function(self, skillid)
				row({action = "skill added", source = self, id = skillid})
			end)

			before(Character, 'DynamicRemoveSkill', "battle log: skill removed", function(self, skillid)
				row({action = "skill removed", source = self, id = skillid})
			end)

			before(B.BattleManager, 'UpdateNextEnemyWave', "battle log: wave", function(self)
				row({action = "enemy wave"})
			end)

			before(BC, 'OnBattleFinish', "battle log: end", function(self)
				row({action = "fight end", detail = self.ifEnemyDie and "won" or "lost"})
				flush()
			end)

			-- A restarted fight is a new fight: a new controller comes with the scene, and this starts the new file even if it doesn't
			before(BC, 'RestartBattle', "battle log: restart", function(self)
				row({action = "fight restarted"})
				flush()
				path = nil
			end)

			before(BC, 'OnDestroy', "battle log: leaving", function(self)
				flush()
			end)
		end

		print("[gf-offline] skill overlay or battle log on")
	end)
	if not ok then
		GF_MOD_ERROR("skill overlay or battle log", err)
	end
end
