-- [gf-offline] An event map skipped on its lowest difficulty (Mission/startMission with forcewin_missionevent) opens
-- the next map in the game's data (the reply's mission_win_result.open, GameData.LoadMissionKey), but
-- SpecialMissionInfoController.RequestSkipMissionHandle redraws only the skipped map's label, so the next map stayed
-- locked on screen until the event screen was opened again. Redraw every map of the event screen after a skip.
-- The open map panel kept its Skip button too (it is set when the panel opens); it is hidden once the map is won.

local util = require 'xlua.util'

util.hotfix_ex(CS.SpecialMissionInfoController, 'RequestSkipMissionHandle', function(self, request)
	self:RequestSkipMissionHandle(request)
	pcall(function()
		local button = self.btnSkip
		if button ~= nil and not button:Equals(nil) then
			button.gameObject:SetActive(false)
		end
	end)
	local ok, err = pcall(function()
		local panel = CS.OPSPanelController.Instance
		if panel == nil or panel:Equals(nil) then
			return
		end
		local holders = panel.panelallMission
		if holders ~= nil then
			for i = 0, holders.Count - 1 do
				local holder = holders[i]
				if holder ~= nil and not holder:Equals(nil) then
					pcall(function() holder:RefreshUI() end)
				end
			end
		end
		pcall(function() panel:RefreshUI(false) end)
		pcall(function() panel:CheckAnim() end)
	end)
	if not ok then
		print("[gf-offline] event screen not redrawn after a skip: " .. tostring(err))
	end
end)
