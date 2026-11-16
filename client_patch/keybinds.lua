-- [gf-offline] Keybinds mod: changes the keys the client registers with CommonInputManager.
-- BattleUIController.AddKeyboardEvent registers the fight keys, AVGController the story's Space and Enter. Keys are swapped as
-- they are registered and removed, in AddKeyListenerWithEventType (AddKeyListener calls it), RemoveKeyListenerWithEventType and
-- RemoveKeyListener (which doesn't). The hints on the fight screen are set from their current text.
-- Other screens read keys straight from Input (Esc for back, the results screen), which can't be swapped this way.

do
	local ok, err = pcall(function()
		local FIGHT = {
			skill1 = {"Alpha1", "1"}, skill2 = {"Alpha2", "2"}, skill3 = {"Alpha3", "3"}, skill4 = {"Alpha4", "4"}, skill5 = {"Alpha5", "5"},
			pause = {"Space", "SPACE"}, pause2 = {"Escape", "ESC"}, auto = {"BackQuote", "`"},
			vehicle = {"F", "F"}, withdraw = {"E", "E"}, restart = {"R", "R"},
		}
		local STORY = {story_next = {"Space"}, story_next2 = {"Return"}}

		local function read_map(defaults)
			local map, count = {}, 0
			for action, default in pairs(defaults) do
				local key = GF_OPTIONS["key." .. action]
				if key ~= nil and key ~= default[1] then
					map[default[1]] = key
					count = count + 1
				end
			end
			return map, count
		end

		local fight, fight_count = read_map(FIGHT)
		local story, story_count = read_map(STORY)
		if fight_count + story_count == 0 then
			return
		end

		local labels = {}
		for action, default in pairs(FIGHT) do
			local label = GF_OPTIONS["label." .. action]
			if label ~= nil then
				labels[default[2]] = label
			end
		end

		local util = require 'xlua.util'
		local Input = CS.CommonInputManager
		local in_fight = false

		local function swap(key)
			local name = string.match(tostring(key), "^%w+")
			local to
			if in_fight then
				to = fight[name]
			elseif name == "Space" or name == "Return" then
				to = story[name]
			end
			return to ~= nil and CS.UnityEngine.KeyCode[to] or key
		end

		util.hotfix_ex(Input, 'AddKeyListenerWithEventType', function(self, key, kind, action)
			self:AddKeyListenerWithEventType(swap(key), kind, action)
		end)
		util.hotfix_ex(Input, 'RemoveKeyListenerWithEventType', function(self, key, kind, action)
			self:RemoveKeyListenerWithEventType(swap(key), kind, action)
		end)
		util.hotfix_ex(Input, 'RemoveKeyListener', function(self, key, action)
			self:RemoveKeyListener(swap(key), action)
		end)

		-- A hint keeps its new text in `done`, so swapped keys aren't changed back when it is seen again
		local done = setmetatable({}, {__mode = "k"})

		local function relabel(root)
			local parts = root:GetComponentsInChildren(typeof(CS.UnityEngine.Transform), true)
			for i = 0, parts.Length - 1 do
				local part = parts[i]
				if part.name == "PCShortcut" then
					local text = part:GetComponentInChildren(typeof(CS.UnityEngine.UI.Text), true)
					if text ~= nil and not done[text] then
						local label = labels[string.upper(text.text)]
						if label ~= nil then
							text.text = label
						end
						done[text] = true
					end
				end
			end
		end

		local function relabel_after(class, method)
			if next(labels) == nil then
				return
			end
			local hooked, e = pcall(util.hotfix_ex, class, method, function(self, ...)
				local result = self[method](self, ...)
				local good, why = pcall(relabel, self.gameObject)
				if not good then
					GF_MOD_ERROR("key hints", why)
				end
				return result
			end)
			if not hooked then
				GF_MOD_ERROR("key hints", e)
			end
		end

		local Battle = CS.BattleUIController
		xlua.private_accessible(Battle)
		xlua.private_accessible(CS.BattleUIManualSkillController)
		xlua.private_accessible(CS.BattleUIFloatingStatusController)

		util.hotfix_ex(Battle, 'AddKeyboardEvent', function(self)
			in_fight = true
			local good, e = pcall(self.AddKeyboardEvent, self)
			in_fight = false
			if not good then
				error(e)
			end
			if next(labels) ~= nil then
				local labelled, why = pcall(relabel, self.gameObject)
				if not labelled then
					GF_MOD_ERROR("key hints", why)
				end
			end
		end)
		util.hotfix_ex(Battle, 'RemoveKeyboardEvent', function(self)
			in_fight = true
			local good, e = pcall(self.RemoveKeyboardEvent, self)
			in_fight = false
			if not good then
				error(e)
			end
		end)

		relabel_after(CS.BattleManualSkillController, 'ShowPCShortCut')
		relabel_after(CS.BattleSangvisMeleeController, 'ShowPCShortCut')
		relabel_after(CS.BattleUIManualSkillController, 'OnLoadSkillFinish')
		relabel_after(CS.BattleUIFloatingStatusController, 'Switch')

		print("[gf-offline] keybinds on")
	end)
	if not ok then
		GF_MOD_ERROR("keybinds", err)
	end
end
