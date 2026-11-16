-- [gf-offline] Old enemy targeting order (option old_target_order): when an enemy's targeting finds your units tied, it picks
-- by place in the echelon (skill bar order, rightmost first) instead of by doll id.
-- SkillUtils.SortFallback is the last key of every targeting sort (SkillUtils.GetTargetFromList): units of another camp
-- first (camp 2, enemy, before the rest), then gun.id ascending, which is gun_with_user_id: the doll got earliest wins.
-- BattleCharacterData.index is the unit's place in its echelon (BattleDynamicData.CreateFriendlyCharacterManagerNormal
-- counts it up member by member), the order of the skill bar. Two of your units, neither summoned, now go by that index,
-- highest first; anything else keeps the game's order.

do
	local ok, err = pcall(function()
		if GF_OPTIONS.old_target_order ~= "1" then
			return
		end
		local Utils = CS.GF.Battle.SkillUtils
		local FRIENDLY, ENEMY = 1, 2
		xlua.private_accessible(Utils)
		xlua.private_accessible(CS.GF.Battle.BattleCharacterData)

		-- the camp as its number, whether it comes over as one or as an enum object
		local function camp(unit)
			local c = unit.camp
			if type(c) == "number" then
				return c
			end
			return c:GetHashCode()
		end

		local function game_order(left, right, lc, rc)
			if lc ~= rc then
				return lc == ENEMY and -1 or 1
			end
			local l, r = left.gun.id, right.gun.id
			return l < r and -1 or (l > r and 1 or 0)
		end

		xlua.hotfix(Utils, 'SortFallback', function(left, right)
			local good, result = pcall(function()
				local lc, rc = camp(left), camp(right)
				if lc == FRIENDLY and rc == FRIENDLY and not left.isSummon and not right.isSummon
						and left.index ~= right.index then
					return left.index > right.index and -1 or 1
				end
				return game_order(left, right, lc, rc)
			end)
			if good then
				return result
			end
			return 0
		end)
		print("[gf-offline] old enemy targeting order on")
	end)
	if not ok then
		GF_MOD_ERROR("old_target_order", err)
	end
end
