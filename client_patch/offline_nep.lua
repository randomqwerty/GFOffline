-- [gf-offline] Skip the game's own calls into the NEP anti-cheat (NLPC.LaunchStub).
-- NEP_Init (LoginNoticeController.OnInitSuccess -> SDKAdapter._NEPInit) and NEP_SetRoleInfo
-- (LoginController.EnterGame -> SDKAdapter._NEPLogin, reports the logged-in role) are the only
-- two game-code calls into NLPC (call scan of GameAssembly.dll).
-- This does NOT silence NEP itself: NEP2.dll is loaded by GirlsFrontLine.exe (it also decrypts
-- the exe's entry code, so it cannot be stubbed) and opens HTTPS to ir-sdk.guardease.com on its
-- own thread, bypassing the proxy. That connection is accepted (see README, "Is it fully offline?").

xlua.private_accessible(CS.SDKAdapter)

xlua.hotfix(CS.SDKAdapter, {
	_NEPInit = function() end,
	_NEPLogin = function() end,
})

print("[gf-offline] NEP anti-cheat calls disabled")
