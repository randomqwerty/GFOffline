-- [gf-offline] The launcher's settings for battle_log.lua, battle_tools.lua and keybinds.lua, runs before them.
-- The server writes gf_client_options.txt into the game copy at startup (client_settings.sync), one key=value a line.
-- No file means they are all off.

GF_OPTIONS = {}

function GF_MOD_ERROR(where, err)
	print("[gf-offline] " .. where .. ": " .. tostring(err))
	pcall(function()
		local file = CS.System.IO.File
		local path = CS.UnityEngine.Application.dataPath .. "/../mod_errors.txt"
		local old = file.Exists(path) and file.ReadAllText(path) or ""
		file.WriteAllText(path, old .. os.date("%Y-%m-%d %H:%M:%S ") .. where .. ": " .. tostring(err) .. "\n")
	end)
end

-- BattleCharacterData.name is the unit's code and id run together (MP41Mod221024991)
function GF_STRIP_ID(name, id)
	if name == nil then
		return nil
	end
	local s, tail = tostring(name), tostring(id)
	if id ~= nil and #s > #tail and string.sub(s, -#tail) == tail then
		return string.sub(s, 1, -#tail - 1)
	end
	return s
end

-- What the player knows a unit as: Gun.Name, also for Coalition units; failing that, the code
function GF_UNIT_NAME(member)
	local gun = member.gun
	local good, name = pcall(function() return gun.Name end)
	if good and name ~= nil and name ~= "" then
		return name
	end
	return GF_STRIP_ID(member.name, gun ~= nil and gun.id or nil)
end

do
	local ok, err = pcall(function()
		local path = CS.UnityEngine.Application.dataPath .. "/../gf_client_options.txt"
		if CS.System.IO.File.Exists(path) then
			for line in string.gmatch(CS.System.IO.File.ReadAllText(path), "[^\r\n]+") do
				local k, v = string.match(line, "^([%w_%.]+)=(.*)$")
				if k ~= nil then
					GF_OPTIONS[k] = v
				end
			end
		end
	end)
	if not ok then
		GF_MOD_ERROR("options", err)
	end
end
