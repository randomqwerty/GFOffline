-- [gf-offline] The launcher's game rule changes (client_settings GAME_CONFIG): game_config_info values, sent as
-- config.<parameter_name>=<value> options. The client reads them with Data.GetInt(key, default) where it needs them
-- (TargetTrainCollectionSettingController.Init: collect_target_num, BattleManager.InitBattleData:
-- targettrain_battle_timelimit, ...), so that answers with the changed value. Nothing is hooked when none is set.

do
	local ok, err = pcall(function()
		local rules = {}
		local any = false
		for k, v in pairs(GF_OPTIONS) do
			local name = string.match(k, "^config%.(.+)$")
			local n = tonumber(v)
			if name ~= nil and n ~= nil then
				rules[name] = math.floor(n)
				any = true
			end
		end
		if not any then
			return
		end
		local util = require 'xlua.util'
		util.hotfix_ex(CS.Data, 'GetInt', function(key, default)
			local n = rules[key]
			if n ~= nil then
				return n
			end
			return CS.Data.GetInt(key, default)
		end)
	end)
	if not ok then
		GF_MOD_ERROR("game rules", err)
	end
end
