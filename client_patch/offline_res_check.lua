-- [gf-offline] "Resource Verification" and "Delete Cache" in the settings are switched off. Verification compares every
-- file with the live resource list and deletes or downloads again whatever differs, which includes the files this
-- project patches; Delete Cache removes the downloaded files. Either way the game would lose its patch and want to
-- download everything, which can't be done offline. The settings' Delete Cache (SettingController.OnClickClearPlayerPrefs,
-- then ClearAndReLogin) wipes the saved settings and the downloaded videos and comics and logs out.
-- The buttons (ResCenter.ShowCheckFileWindows, ShowDeleteWindows, LoginController.DeleteLocalResBox) and what their
-- confirms run (GoOnCheckRes, BeginDeleteRes, DeleteAllResData, LoginController.DeleteRes) now only say so, and
-- ForcceFullResCheck, which asks for a check at startup after one was cut short, answers no. The loading screen's
-- own buttons come before this file loads; tools/patch_gameassembly.py switches those off.
do
	local ok, err = pcall(function()
		local function say()
			pcall(function()
				CS.CommonController.LightMessageTips("Not available offline: this copy keeps its own game files.")
			end)
		end
		local Res = CS.ResCenter
		xlua.private_accessible(Res)
		for _, name in ipairs({'ShowCheckFileWindows', 'GoOnCheckRes', 'ShowDeleteWindows', 'BeginDeleteRes', 'DeleteAllResData'}) do
			xlua.hotfix(Res, name, function(self)
				say()
			end)
		end
		xlua.hotfix(Res, 'ForcceFullResCheck', function(self)
			return false
		end)
		local Setting = CS.SettingController
		xlua.private_accessible(Setting)
		for _, name in ipairs({'OnClickClearPlayerPrefs', 'ClearAndReLogin'}) do
			xlua.hotfix(Setting, name, function(self)
				say()
			end)
		end
		local Login = CS.LoginController
		xlua.private_accessible(Login)
		for _, name in ipairs({'DeleteLocalResBox', 'DeleteRes'}) do
			xlua.hotfix(Login, name, function(self)
				say()
			end)
		end
	end)
	if not ok then
		GF_MOD_ERROR("resource check", err)
	end
end
