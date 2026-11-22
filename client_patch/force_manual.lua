-- [gf-offline] Forced manual skills kept apart from the live game.
-- The skill page's "forced manual" toggle is saved by SkillUtils.SaveForceManualGunIds / SaveForceManualSangvisGunIds /
-- SaveForceManualVehicleComponentIds as a comma list in PlayerPrefs FORCE_MANUAL_CLOSE_DATA(_SANGVIS, _VEHICLE), read once
-- by the hashForceManualGunId(Sangvis, Vehicle) getters. PlayerPrefs are per company and product name, so this copy and the
-- Steam game share them: toggles made offline (another account's dolls too) replaced the live ones.
-- Here the lists live under <key>_OFFLINE: the first read loads that list in place of the shared one, and each save is
-- copied there while the shared key is put back as it was. The first offline read starts from the live list.

do
	local ok, err = pcall(function()
		local util = require 'xlua.util'
		local Utils = CS.GF.Battle.SkillUtils
		local PP = CS.UnityEngine.PlayerPrefs
		xlua.private_accessible(Utils)
		local SUFFIX = "_OFFLINE"
		local unpack = table.unpack or unpack
		local function pack(...)
			return {n = select("#", ...), ...}
		end

		local function read(key)
			if PP.HasKey(key) then
				return PP.GetString(key)
			end
			return nil
		end
		local function put(key, value)
			if value == nil then
				PP.DeleteKey(key)
			else
				PP.SetString(key, value)
			end
		end

		-- run fn with the shared key holding the offline list, then copy what it left there and restore the shared key
		local function as_offline(key, fn)
			local shared = read(key)
			local mine = read(key .. SUFFIX)
			if mine == nil then
				mine = shared
			end
			put(key, mine)
			local results = pack(pcall(fn))
			put(key .. SUFFIX, read(key) or "")
			put(key, shared)
			pcall(function() PP.Save() end)
			if not results[1] then
				error(results[2])
			end
			return unpack(results, 2, results.n)
		end

		local LISTS = {
			{key = "FORCE_MANUAL_CLOSE_DATA", getter = "hashForceManualGunId", save = "SaveForceManualGunIds"},
			{key = "FORCE_MANUAL_CLOSE_DATA_SANGVIS", getter = "hashForceManualGunIdSangvis", save = "SaveForceManualSangvisGunIds"},
			{key = "FORCE_MANUAL_CLOSE_DATA_VEHICLE", getter = "hashForceManualGunIdVehicle", save = "SaveForceManualVehicleComponentIds"},
		}
		for _, list in ipairs(LISTS) do
			local loaded = false
			util.hotfix_ex(Utils, "get_" .. list.getter, function()
				if loaded then
					return Utils[list.getter]
				end
				loaded = true
				return as_offline(list.key, function() return Utils[list.getter] end)
			end)
			util.hotfix_ex(Utils, list.save, function(...)
				local args = pack(...)
				return as_offline(list.key, function() return Utils[list.save](unpack(args, 1, args.n)) end)
			end)
		end
	end)
	if not ok then
		GF_MOD_ERROR("forced manual skills", err)
	end
end
