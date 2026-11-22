-- [gf-offline] The shop's paid ($) goods are bought with gems (server: gfserver/paid_shop.py).
-- A paid good is a MallGood made from the product list (MallGood(PayProduct): rmbId is the product id, gemValue the
-- product's "gem", which the server sets to the gem price). Its price label shows that price.
-- The buy button (OnClickCashBuy) asks to confirm the price, then sends the client's own Mall/ifAble, which the server
-- answers by taking the gems and giving the goods: {"gem_buy": 1, "gem": <gems left>, "mailed": 1 when they were
-- mailed, "items": {id: count} when given at once} or {"gem_buy": 0, "reason"}. Gem packs (thirdProductId
-- "offline_gem_pack_<id>", set by the server, or MallGood.type 4 payToGem; their gemValue is the gems they give, as
-- live) cost basic resources: a quarter of their gems' worth in each, at the Supply shop's rate of 4500 manpower, ammo or
-- rations, or 1500 parts, for 480 gems (paid_shop.resource_price); the reply's "resources" are what is left.
-- Its handler (RequestIfAbleToBuyHandle) would go on to a Steam payment; here it sets the gem count and the items'
-- counts in the bag (the battle pass screen unlocks from its unlock item there), and runs OnPayFinished, as a finished
-- payment does (it fetches the mail list and sets the monthly card end times).
-- The good's detail box (QuickPurchaseBox.GemBuyItemView) prints MallGood.displayPrice as the price, so Init sets it to
-- the gem price; InitCommonPriceTag is also given the gem price, without the cash text (a gem pack's resource price as
-- the cash text), for a box opened another way.
-- Without a confirm box (CustomConfirmBox needs a UnityAction from Lua), the first click says the price and a
-- second click within 10 seconds buys.
do
	local ok, err = pcall(function()
		local util = require 'xlua.util'
		local Good = CS.MallGoodController
		xlua.private_accessible(Good)

		local function is_paid(good)
			return good ~= nil and good.rmbId ~= nil and good.rmbId ~= ""
		end
		-- MallGood.type is a GoodType enum: a number, or a userdata that a second copy of the same value isn't == to,
		-- so it is compared as a number (Convert.ToInt32), or by its name (ToString)
		local GEM_PACK = 4    -- GoodType.payToGem
		local function good_type(v)
			if type(v) == "number" then
				return v
			end
			local ok, n = pcall(function() return CS.System.Convert.ToInt32(v) end)
			if ok and type(n) == "number" then
				return n
			end
			local text = tostring(v)
			if string.find(text, "payToGem", 1, true) then
				return GEM_PACK
			end
			return tonumber(string.match(text, "^%s*(%d+)%s*$"))
		end
		local RES = { {"mp", 4500, "manpower"}, {"ammo", 4500, "ammo"}, {"mre", 4500, "rations"}, {"part", 1500, "parts"} }
		-- a gem pack's price, {amount per RES}, or nil
		local function res_price(good)
			local pack = false
			pcall(function() pack = string.find(tostring(good.thirdProductId or ""), "offline_gem_pack_", 1, true) == 1 end)
			if not pack then
				pcall(function() pack = good_type(good.type) == GEM_PACK end)
			end
			local gems = good.gemValue
			if not pack or gems == nil or gems <= 0 then
				return nil
			end
			local out = {}
			for i, r in ipairs(RES) do
				out[i] = math.floor((gems * r[2] + 1919) / 1920)
			end
			return out
		end
		local function price_text(good)
			local res = res_price(good)
			if res ~= nil then
				return table.concat(res, "/")
			end
			return good.gemValue > 0 and (tostring(good.gemValue) .. " Gems") or "Free"
		end
		local function res_words(res)
			local parts = {}
			for i, r in ipairs(RES) do
				parts[i] = tostring(res[i]) .. " " .. r[3]
			end
			return table.concat(parts, ", ", 1, 3) .. " and " .. parts[4]
		end
		local function name_of(good)
			local ok, name = pcall(function() return good.giftName end)
			return (ok and name ~= nil and name ~= "") and name or "this"
		end

		util.hotfix_ex(Good, 'Init', function(self, good)
			self:Init(good)
			if is_paid(good) then
				pcall(function() self.textPrice.text = price_text(good) end)
				-- what the detail box (QuickPurchaseBox.GemBuyItemView) and the pass screen print as the price
				pcall(function() good.displayPrice = price_text(good) end)
			end
		end)

		local armed = {}
		util.hotfix_ex(Good, 'OnClickCashBuy', function(self)
			local good = self.good
			if not is_paid(good) then
				return self:OnClickCashBuy()
			end
			local res = res_price(good)
			local msg = res ~= nil and ("Buy " .. name_of(good) .. " for " .. res_words(res) .. "?")
				or good.gemValue > 0 and ("Buy " .. name_of(good) .. " for " .. tostring(good.gemValue) .. " Gems?")
				or ("Get " .. name_of(good) .. " for free?")
			local buy = function() self:RequestIfAbleToBuy() end
			if pcall(CS.CommonController.CustomConfirmBox, msg, "Buy", buy, "Cancel", nil, true, false) then
				return
			end
			local key = good.rmbId
			if armed[key] ~= nil and os.time() - armed[key] <= 10 then
				armed[key] = nil
				buy()
			else
				armed[key] = os.time()
				pcall(function() CS.CommonController.LightMessageTips(msg .. " Click again to buy.") end)
			end
		end)

		local Box = CS.QuickPurchaseBox
		xlua.private_accessible(Box)
		util.hotfix_ex(Box, 'InitCommonPriceTag', function(self, price, cash, coin, target)
			local good = nil
			pcall(function() good = self.itemGood end)
			if good == nil then
				pcall(function() good = self.item_good end)
			end
			if is_paid(good) then
				-- a gem pack's resource price goes in as the cash text
				if res_price(good) ~= nil then
					return self:InitCommonPriceTag(0, price_text(good), coin, target)
				end
				return self:InitCommonPriceTag(good.gemValue, nil, coin, target)
			end
			return self:InitCommonPriceTag(price, cash, coin, target)
		end)

		local set_item = nil
		pcall(function()
			local types = CS.System.Array.CreateInstance(typeof(CS.System.Type), 3)
			types:SetValue(typeof(CS.System.Int32), 0)
			types:SetValue(typeof(CS.System.Int32), 1)
			types:SetValue(typeof(CS.System.Int64), 2)
			set_item = xlua.tofunction(typeof(CS.GameData):GetMethod("SetItem", types))
		end)
		local function set_items(text)
			local list = string.match(text, '"items"%s*:%s*(%b{})')
			if list == nil then
				return false
			end
			for id, n in string.gmatch(list, '"(%d+)"%s*:%s*(%d+)') do
				local ok = set_item ~= nil and pcall(set_item, tonumber(id), tonumber(n), 0)
				if not ok then
					pcall(function() CS.GameData.SetItem(tonumber(id), tonumber(n), 0) end)
				end
			end
			pcall(function()
				local pass = CS.PassOrderController.Instance
				if pass ~= nil and pass.gameObject.activeInHierarchy then
					pass:RefreshUI()
				end
			end)
			return true
		end

		util.hotfix_ex(Good, 'RequestIfAbleToBuyHandle', function(self, www)
			local text = ""
			pcall(function() text = www.downloadHandler.text end)
			local bought = string.match(text, '"gem_buy"%s*:%s*(%d)')
			if bought == nil then
				return self:RequestIfAbleToBuyHandle(www)
			end
			pcall(function() CS.ConnectionController.CloseConsole() end)
			if bought == "1" then
				local gem = tonumber(string.match(text, '"gem"%s*:%s*(%d+)'))
				if gem ~= nil then
					pcall(function() CS.GameData.userInfo.gem = gem end)
				end
				local left = string.match(text, '"resources"%s*:%s*(%b{})')
				if left ~= nil then
					for res, n in string.gmatch(left, '"(%a+)"%s*:%s*(%d+)') do
						pcall(function() CS.GameData.userInfo[res] = tonumber(n) end)
					end
				end
				set_items(text)
				self:OnPayFinished()
				local mailed = string.match(text, '"mailed"%s*:%s*1') ~= nil
				pcall(function() CS.CommonController.LightMessageTips(mailed and "Bought. The goods are in your mail." or "Bought.") end)
			else
				local reason = string.match(text, '"reason"%s*:%s*"([^"]*)"') or "This can't be bought."
				pcall(function() CS.CommonController.MessageBox(reason) end)
			end
		end)
	end)
	if not ok then
		GF_MOD_ERROR("paid shop", err)
	end
end
