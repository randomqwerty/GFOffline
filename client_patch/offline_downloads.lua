-- [gf-offline] Send the static data package download to the local server.
-- CatchDataController downloads stc_<data_version><md5>.zip with System.Net, which ignores
-- the game's per-process proxy, from DOWNLOAD_URL_FORMAT (Sunborn's CDN). It runs from the
-- login scene (LoginController.CheckAndRequestUpdate), after PatchList has loaded, so the URL
-- builder can be wrapped here: keep the path, replace the host with the local server.
-- Asset bundle/video downloads use the resource config's resUrl, which the server rewrites.
-- {{LOCAL_BASE}} is filled in by tools/build_lpatch.py.

local util = require 'xlua.util'
local LOCAL_BASE = "{{LOCAL_BASE}}"

xlua.private_accessible(CS.CatchDataController)

util.hotfix_ex(CS.CatchDataController, 'GetDataFileFullUrl', function(self, dataVersion)
	local url = self:GetDataFileFullUrl(dataVersion)
	local path = string.match(url, "^%a+://[^/]+/(.*)$")
	if path ~= nil then
		url = LOCAL_BASE .. path
	end
	return url
end)

print("[gf-offline] data package downloads -> " .. LOCAL_BASE)
