-- [gf-offline] SDK login bypass. Appended to PatchList by server/tools/build_lpatch.py.
-- PatchList runs from LoginController.Awake (HotFixController.LoadHotFix), before any SDK call.
--
-- Normal PC flow:  SunBornUserCenter.InitPCSDK -> PCLoin_Hot (Sunborn passport over HTTPS)
--                  -> SDKAdapter.PCSDKLogin_Login -> PCLoginQueueController (ticket queue)
--                  -> OnQueueEnd -> RequestGetUIDWithToken(pid, token, ticket)
-- Offline flow:    SDK reports initialised/logged-in with a fixed local identity and the
--                  queue is skipped, so the first network call is Index/getUidEnMicaQueue
--                  to the local server, which hands out uid + sign.

local OFFLINE_PID = "gf_offline_player"
local OFFLINE_TOKEN = "gf_offline_token"

xlua.private_accessible(CS.SunBornUserCenter)
xlua.private_accessible(CS.SDKAdapter)

xlua.hotfix(CS.SunBornUserCenter, {
	CheckPCSDKInit = function(self) return true end,
	InitPCSDK = function(self, onInitSuc, onInitFail)
		if onInitSuc ~= nil then onInitSuc() end
	end,
	CheckLoginSuccess = function(self) return true end,
	GetSDKPID = function(self) return OFFLINE_PID end,
	GetSDKToken = function(self) return OFFLINE_TOKEN end,
	PCLoin_Hot = function(self, onLoginSuc)
		if onLoginSuc ~= nil then onLoginSuc(OFFLINE_PID, OFFLINE_TOKEN) end
	end,
	-- analytics calls to Sunborn endpoints; nothing to report offline
	TrackUserLogin = function(self) end,
	TrackUserLoginPlatform = function(self) end,
	TrackThirdLogin = function(self) end,
})

xlua.hotfix(CS.SDKAdapter, 'PCSDKLogin_Login', function()
	CS.SDKAdapter.RequestGetUIDWithToken(OFFLINE_PID, OFFLINE_TOKEN, "")
end)

print("[gf-offline] login bypass active")
