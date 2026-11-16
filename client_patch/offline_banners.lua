-- [gf-offline] Home screen banners show art the client already has.
-- HomeEventBarItemController.Init downloads activity/<pic> from the CDN unless it is handed a sprite. The server
-- sends pic as a path in the client's bundles (mods.banners), so the sprite is loaded from there instead.

local util = require 'xlua.util'

util.hotfix_ex(CS.HomeEventBarItemController, 'Init', function(self, info, sprite)
	if sprite == nil and string.sub(info.pic, 1, 5) == "Pics/" then
		sprite = CS.CommonController.LoadPngCreateSprite(info.pic)
	end
	self:Init(info, sprite)
end)
