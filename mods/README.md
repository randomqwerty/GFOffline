# Mods

Add or change game content (T-Dolls, Coalition units, enemies, enemy teams, maps) without
touching the client's code. Every mod is a folder here; `tools/build_mods.py` merges them into
the game's data package, and the client downloads that package on its next login.

```
python tools/build_mods.py --check   # validate only
python tools/build_mods.py           # build (needs UnityPy if a mod has "text")
python play.py                       # restart the server, log in: the client downloads the new data
```

Set `GF_NO_MODS=1` (or disable every mod and rebuild) to go back to the original data. The
client notices the version change and downloads the original package again.

## Mod Studio (editor)

```
python tools/modstudio/studio.py        # then open http://127.0.0.1:8770/
```

A local editor that hides the table details. It writes the same files, so hand edits and the
editor can be mixed. Everything can start from scratch or as a copy of anything in the game
(or another mod).

| Entry | What you set | Assumed / automatic |
|---|---|---|
| **T-Doll** | name, weapon class, rarity, model, final stats, tiles (5×5 grid), equipment slots, skills | level 100, skill level 10, no Neural Upgrade, fully enhanced; stats are solved back to the table's ratios with the game's formula (HP lands within one rounding step) |
| **Coalition unit** | name, model, faction, class, rarity, single or linkable, final stats, skills | level 100, 5 stars, largest size, max resolution, skills maxed; only bosses get chip slots; stats are exact |
| **Enemy** | name, model, type, stats at level 100, skills | other levels scale like the game's enemies |
| **Enemy team** | members on a battlefield grid (duplicate a row to copy an enemy), leader, movement AI in words, warning tags, fixed combat effectiveness, level corrections | |
| **Map** | name, stage number, day or night, difficulty, recommended level, default enemy AI, victory goals, turn limit, deployment limits, ranking targets, endless mode, restarts; layout with zoom; enemy spawns; enemy move order | the map is listed in the mod's Campaign tab entry |
| **Skill** | a visual editor: basics, when it activates, targets, effects on targets / user, animation objects with their hits, area effects and follow-ups, formulas | level 10 only: all ten levels get the level-10 numbers |
| Other rows | any table (advanced, off by default) | |

**Campaign tab.** Each mod's maps are listed together as one entry of the Campaign tab, like an
archived event. The entry's name and description are set in the side panel; a map's stage number is
its place in the list. In `mod.json` this is `"campaign": {"name", "description", "missions": [ids in
order], "look"}`. The loader gives each mod with one its own campaign id (-9001, -9002, … in folder
order), `normal_activity` row (9001+) and permanent `mission_event` row (99001+), so mods never clash.
The maps move to that campaign and lose their unlock keys (use `grant.missions` to open them).
`look` is the `normal_activity` row whose background and colours the entry uses (default 1). A mod
made with the older numbered `"chapter"` still builds as a chapter; Mod Studio moves it to a Campaign
entry when it is next opened.

**Map icons.** A map's button in the mission list shows `Pics/Icons/Mission/<code>.png`, where
`<code>` is the enemy type of its boss team's leader (a map without a boss team shows none). Pick
the picture on the map's Settings tab ("Mission list icon"); it is stored as `map_rules.<map>.icon`.
Maps whose boss leader has no icon of its own get the picked one, or the game's question mark when
none is picked. A leader that already has an icon keeps it, and maps sharing a leader share one icon.

**Skills.** The editor covers what current kits use:
- **Conditions:** all condition types, combined (all must hold). Buff-stack checks name the marker
  effect and the skills that hand it out; there are buff-type checks and formula conditions.
- **Numbers:** the skill's number lists (`*XY` values), plus the special numbers used under
  conditions and the night numbers.
- **Targeting:** who, how many, the Nth, two sort keys (including formula sorts), buff and formula
  filters, the whole battlefield, the echelon's shared target, what happens when the target is lost.
- **Effects:** stats, statuses, markers, damage recalculation formulas, class limits, and skills
  granted while active.
- **Watchers:** an event, an event condition, extra conditions, and skills cast with their aim.
- **Objects:** objects, hits (with knock-back skills) and area effects.

Saving is **copy-on-write**: only what you changed (and the pieces above it that refer to it) gets
new ids. Everything else keeps its game id, so a kit's skills keep reacting to each other's marker
effects. Number-list values are stored on the skill itself, so effects shared with other skills
stay untouched. Linked skills (granted, cast by watchers, knock-backs) are separate skills: open
them to edit them. "Copy an object / effect from another skill" brings in pieces of any game skill.

Grants made by the studio: dolls `{"level": 100, "number": 5, "skill1": 10, "skill2": 10,
"enhance": 1}` and Coalition units `{"max": 1}` (see Grants).

## Battle tools and keys are not mods

They change how the client behaves, not the game's data, so they are the launcher's settings (`launcher.pyw`, Battle tools and Keys
tabs), stored in `settings.json`. See `server/README.md`. A `mod.json` with a `"client"` entry is refused with that reason.

## Story, event listings and game text

Each mod is its own folder and can be switched on or off by itself: the side panel's **Turn mods on or off** lists them all.
These entries sit beside the others in Mod Studio:

- **Story text**: the original line next to yours, one row per line. The original's stage cues stay in place, so only the speaker and
  the words are edited. Whole translated files can be imported at once; each is checked for lost cues.
- **Event listing**: makes a map group appear on the Events screen, with its title, description, picture and banner, and can open the
  first map. It only takes maps with a negative campaign number, the game's event maps.
- **Game text**: search any text in the game and replace it for this mod.
- **Copy from the Chinese client**: brings rows the EN client lacks into a mod. An advanced option, shown only when `cn-data/` exists.

Story files go in `mods/<name>/story/<file>.txt`, named as in the client's `avgtxt` folder, any case. Folders apply in name order, so a
later mod's copy of a file wins. They are built into the `*assettextavg.ab` bundle (`tools/build_mods.py`), which restores the original
when no mod has story files, and they count towards the data version, so players get them after a server restart and the re-download
at login. New art still isn't possible (see Art).

## Sharing

Mod Studio's **Export to share** saves the mod as one `.zip` (`<name>-v<version>.zip`, the folder inside). The
launcher's **Add a mod** (Tools tab, or `tools/add_mod.py <zip>`) checks a zip before writing anything: one `mod.json`,
nothing that would land outside the folder, only `.json`, `.txt` and `.md` files and the mod's own `.png` pictures under `art/`, at most 50 MB.
A mod with the same folder name is replaced, and the old one kept in `mods/_replaced/`. If the new mod can't be on with
the mods you have on (most often both add something with the same id), it is added turned off, and the note names
the other mod.

Ids: the build stops when two mods both add a row with the same id (a `_copy` row, or one that sets most of the
fields), naming both mods. Mods made apart often pick the same first free id, so a mod meant for sharing is safer with
ids away from the start of each free range. When two mods change the same field of one of the game's rows, the later
mod's value is used and the build warns.

## Layout

```
mods/<name>/mod.json
mods/<name>/tables/<table>.json      optional, one file per .stc table
mods/<name>/catchdata/<table>.json   optional, catchdata tables (operation_info, gun_obtain_info, ...)
```

`mod.json`:

```json
{
 "name": "my_mod",
 "art":       { "Pics/Title/my_banner.png": "Pics/Icons/OPS/missionselect_VA11.png" },
 "version": "1",
 "enabled": true,
 "campaign":  { "name": "My Maps", "description": "Shown in the Campaign tab", "missions": [800001] },
 "tables":    { "gun": [ ...rows... ] },
 "catchdata": { "gun_exp_info": [ ...rows... ] },
 "text":      { "gun-10008001": "My Doll" },
 "grant":     { "guns": [8001], "sangvis": [8001], "fairies": [1001], "missions": [800001] },
 "map_rules": { "800001": { "spawns": [ ...rules... ] } }
}
```

Rows can go in `mod.json` or in `tables/<table>.json`, or both. Folders are applied in name
order, so `20_balance` can change rows added by `10_new_dolls`. A folder whose name starts with `_`
or `.` is skipped.

## Rows

Each row is matched on its table's **first column** (`id` for nearly every table; the column
lists are in `data/stc_schema.json`, and every field is explained in `doc/stc-guide/`).

| Row | Effect |
|---|---|
| `{"id": 2, "ratio_pow": 120}` | id exists: change only the listed fields |
| `{"id": 8001, "_copy": 2, "name": "gun-10008001"}` | new id: clone row 2, then change the listed fields |
| `{"id": 8001, ...all fields...}` | new id without `_copy`: unlisted fields are 0 / "" |
| `{"id": 2, "_delete": true}` | remove the row |

The build stops with an error on unknown field names, values that don't fit the column type, a
`_copy` source that doesn't exist, and a `_copy` onto an id that **already exists** (that is
nearly always an id collision, so pick a free id).

It also warns about references that point nowhere, such as an enemy-team member whose enemy type
doesn't exist, a skill group missing from `battle_skill_config`, a map node linked to a missing
node, or an enemy team without members. It also notes one-way map links (a link listed on only one of the two nodes, which the original maps use too). Warnings are also printed when the server starts.

## Free id ranges

Ids that the unmodded data doesn't use. Keep to these to avoid overwriting real content.

| Table | Free range used by the test sample (`tests/fixtures/mods/example`) | Notes |
|---|---|---|
| `gun` | 8001–8999 | below 20000: id + 20000 is the Neural Upgrade form |
| `sangvis` | 8001–8999 | |
| `sangvis_resolution` | groups 8001+ (ids 800100+) | group 801 is used |
| `battle_skill_config` | skill groups 9000001+ (row ids 900000101+) | row id = group × 100 + level |
| `battle_buff` | 7000001+ | |
| `mission_win_type_config` | 80000001+ | |
| `building` | 95000001+ | |
| `enemy_character_type` | 7000001+ | 800001–993701 is partly used |
| `enemy_team` | 80000001+ | |
| `enemy_in_team` | 80000001+ | 70000001 is used |
| `mission` | 800001+ | |
| `spot` | 8000001+ | |

## Text

Names and descriptions are text keys (`gun.name` = `gun-10000002`). The client looks them up in
the `assettexttable` bundle, one `key,value` per line per table. A mod's `"text"` adds or
replaces keys there; the file is picked from the key's prefix (`gun-…` → `gun.txt`). A line break
in a value is written as `\n` (stored as `//n`). Existing keys can be replaced too, for example to
rename a doll.

## Grants

`"grant"` puts content into the player's save on the next login, once per save. The save
remembers what was granted in `_mod_grants`.

- `guns`: a T-Doll, level 1 by default. An entry can also be an object with options:
  `{"id": 8001, "level": 100, "number": 5, "skill1": 10, "skill2": 10, "enhance": 1}`. Here `level`
  is 1–100, `number` is the dummy links (1–5), `skill1`/`skill2` are skill levels (1–10), and
  `enhance` fills the maximum enhancement. HP is set to full by the verified formula. If the
  options change in a later build, the doll already granted is updated to match on the next login.
- `sangvis`: a level-1 Coalition unit, or with `{"id": 8001, "max": 1}` level 100, 5 stars, max
  size and resolution, every skill at its class maximum and full HP.
- `fairies`: a level-1 fairy with the first basic talent, or with `{"id": 1001, "max": 1}` level 100, 5 stars
  and skill 10
- `missions`: opens the map in `mission_with_user_info`
- `items`: one of each item (`item_with_user_info`), e.g. a mod's own profile picture or home background

Fields starting with `_` (such as `"_comment"`) are ignored, so rows can carry notes.

### Turning a mod off or deleting it

Whatever a mod's rows gave a save (granted, produced, dropped or bought) refers to those rows.
When the mod is off or gone, the next login puts those entries aside in the save's `_mod_aside`:
T-Dolls, Coalition units, fairies, equipment, items, gifts, skins, HOCs, missions and a map in
progress. Equipment and chips they held go back to the inventory, and their echelon and preset
slots are emptied. When the mod is on again, they come back as they were, outside any echelon.
Only ids the original game doesn't have are touched (gfserver/mod_save.py). Build mods ends with
what the next login will do, and the launcher's "Check your save against mods" shows it any time.

Dolls with `obtain_ids` containing `1` (standard) or `2` (heavy) also enter the server's production pools.

## Map rules (enemy spawns, move order)

`"map_rules"` holds server-side rules per map (mission id). Enemies that start on the map are
set on the nodes (`spot.enemy_team_id`). Spawn rules add more:

```json
{"spot": 8000004, "teams": [{"team": 1, "weight": 3}, {"team": 80000001, "weight": 1}],
 "from_turn": 2, "to_turn": 0, "every": 2, "chance": 100, "max": 3, "enemy_owned": true}
```

| Key | Meaning |
|---|---|
| `spot` | node the team appears on (a node of this map) |
| `teams` | enemy teams to pick from, by weight |
| `start` | `true`: placed once when the mission starts (randomized starts); the turn keys are ignored |
| `from_turn`, `to_turn`, `every` | rolled at the start of enemy turns `from_turn`…`to_turn` (0 = no end), every N turns |
| `chance` | % per roll (100) |
| `max` | at most this many spawns from this rule (0 = no limit) |
| `enemy_owned` | only while the enemy holds the node (default `true`) |

The node must be empty: no enemy, no echelon, and no enemy moving into or out of it that
turn. The client is told through `grow_enemy` in the enemy-turn reply.

`"move_order"` sets which enemy moves first in the enemy turn (Mod Studio: the map's **Enemy move
order** tab):

```json
"move_order": {"first": [{"team": 80000001}, {"ai": "patrol"}, {"spot": 8000004}], "then": "nearest"}
```

| Key | Meaning |
|---|---|
| `first` | moves before everyone else, top entry first: an enemy team, every enemy with an AI (`patrol`, `alert`, `expand`, `attack`, `random`, `lock_on`, `standby`), or the enemy standing on a node |
| `then` | order within each entry and for the rest: `oldest` (first to appear, the default), `newest`, `nearest` / `farthest` (from your units and Command Posts) |

## Win, defeat and rank on the offline server

- **Victory:** the map's win conditions (`mission.win_type`: `mission_win_type_config` ids, `,` = all
  of them, `|` = any group). The server checks the kinds the client lists (nodes held, kills,
  teams or forces destroyed, hostages, supply lines, buildings, rounds survived, ...). A map
  without win conditions follows `mission.type`: 1 / 2 the win nodes (`win_spot_id`, else every
  enemy HQ) are ours; 3 no enemy left, or the win nodes; 4 the boss team destroyed; 11 survive
  `win_turn` turns.
- **Defeat:** `mission.lose_type` if set; otherwise no echelon left, every Griffin HQ lost, or
  `turn_limit` passed.
- **Medals and rank:** gold (rank S) needs the client's S-rank targets: `expect_turn` (turns),
  `expect_enemy_die_num` (kills; 0 = no target) and `expect_gun_die_num` (echelons lost or
  withdrawn). Below S, one rank lower for each missed target (an approximation). Silver follows
  `medal_type_silver`.

## Kinds of content

| Content | Tables | Notes |
|---|---|---|
| T-Doll | `gun` (+ `text`) | `code` picks the art, chibi and voice. Reusing an existing code works today. |
| Coalition unit | `sangvis` (+ `sangvis_resolution`) | same: `code` picks the art. Resolution levels swap skills through `sangvis.resolution` → `sangvis_resolution.group_id` (ids are group × 100 + level). |
| Enemy type | `enemy_character_type` | `code` picks the model. Stats scale by `enemy_standard_attribute`, see doc/stc-guide/05. |
| Enemy team | `enemy_team` + `enemy_in_team` | members: type, position (`coordinator_x/y`), level, links (`number`) |
| Map | `mission` + `spot` (+ `building`, `mission_win_type_config`) | `map_res_name` picks the background. Nodes need `coordinator_x/y`, `route` (both directions) and `map_route`. |

The server's campaign code reads the merged tables, so deployment, enemy turns and battles on a
modded map work the same as on an original one.

## Not possible yet

- **New models** (new chibi animations, map backgrounds): a T-Doll can have its own pictures (see
  Custom T-Doll art), but its chibi keeps an existing doll's skeleton and animations.
- **Skill checks**: the build checks references between tables, but not whether a formula is valid
  or a skill makes sense in battle.
- **Map icons and banners** can only reuse the game's images (see Art).
- **Random-node rewards** are not simulated by the offline server. Buildings can be attacked down
  and captured, and allied/third-party forces are placed and can be fought, but they never move and
  building skills have no effect.
- **Night maps** hide enemies the player can't see. An echelon with a handgun sees the next node,
  one without sees only its own node, a Coalition echelon always sees the next node, a radar node
  held by Griffin sees 2 nodes around it, and an Illumination Fairy lights 2 nodes around its
  target for a turn.

## Custom T-Doll art

A T-Doll can have pictures of its own (Mod Studio: the doll's Own pictures card). They are copies of
an existing doll's art with the mod's pictures painted in, under a new model code:

```json
"custom_art": { "Mod8001": { "from": "KP31", "images": { "portrait": "art/Mod8001/portrait.png",
                                                        "chibi": "art/Mod8001/chibi.png" } } }
```

Pictures (`mods/<mod>/art/<code>/`): `portrait`, `damaged` (else the portrait), `card` (the list
picture; else made from the portrait), `chibi` and `dorm` (sprite sheets painted over the source
doll's sheet, same layout). Mod Studio converts any picture for the portraits (a plain background
is removed, the figure placed as the source doll's stands); a sheet must be the template painted over,
since the chibi keeps the source doll's skeleton. The doll's gun row uses the new code. The build (`tools/custom_art.py`)
copies the source doll's `character_<code>`, `_he`, `_nom` and `_spine` bundles with the new paths
and pictures, and declares them in the resource config.

## Pictures and music

Mod Studio's Pictures and music page replaces the game's profile pictures, home screen backgrounds,
map backgrounds and music, or adds new ones made like one of the game's:

```json
"game_assets": { "home_bg/cg_manwear": { "file": "art/assets/home_bg/cg_manwear.png" },
                 "profile_pic/profilePic_Own90001": { "file": "art/assets/profile_pic/profilePic_Own90001.png",
                                                      "new": true, "from": "profilePic_rank2_G43", "name": "My face" } }
```

Pictures are stored at the size of the one they replace or are made from; music as ADX
(`.adx`, converted when uploaded) with the uploaded file beside it. The build (`tools/game_assets.py`)
rebuilds a replaced picture's bundle with the picture swapped, copies the template's bundle for a new
one (only its picture, under the new name), and puts the sound into the game's music file
(`<name>.acb.bytes`, `tools/cri.py`); everything is declared in the resource config. A new profile picture
or background also needs a `friend_cosmetic` and an `item` row and an `items` grant, new music a
`music_collection` row (the base's music player); the studio writes them. A new map background is used
by setting a map's background to its name (`OwnMap1_Y`).

Home backgrounds: the game shows the one picked in its background settings; its built-in default (none
picked) can't be changed. A replaced background that has an animated (Live2D) version shows still: the
build leaves the animated one out of the resource config. A new one also gets a copy of the template's
home screen part (`<code>_prefab.prefab`). Every home background is drawn stretched over a 2048 x 1536
(4:3) frame; a 16:9 screen shows about the middle 2048 x 1152.

Map and home backgrounds keep the uploaded picture and how it lies on the map or the home frame (a home
background's `place` has no `area`; its list icon is the frame's middle square):

```json
"map_bg/Chapter1_Y": { "file": "art/assets/map_bg/Chapter1_Y.png", "source": "art/assets/map_bg/Chapter1_Y_source.png",
                       "place": { "mode": "fit", "zoom": 1, "x": 0.1, "y": -0.2, "area": [3000, 2625] } }
```

The game stretches the map texture over the map's size (the first pair of `map_information`, here
3000 x 2625), so the build draws the picture on that shape (`fill`, `fit` or `stretch`, then `zoom`;
`x`/`y` move its centre by that share of the width/height, down is positive) and squeezes it into the
texture. Zoom and offsets have no limit. Past the map's edges the game repeats the picture mirrored,
and it only shows the map's view (the second and third pairs, size and centre); the studio's preview
draws both.

## Art

An existing image can be given a second path, so the client finds
it where a table points: `"art": {"<new path>": "<existing image>"}`, paths below
`Assets/Resources/DaBao/` (the new one as the client asks for it, case included). The build adds
the path to the bundle that holds the image (an AssetBundle may list several paths for one asset),
writes that bundle to `build/`, declares the path in the resource config (`build/asset_aliases.json`
→ `tools/build_resconfig.py`) and copies the bundle into the game copy. The build also adds map icons
(and title art for an older numbered chapter) this way.

## Collaboration events (`collab_events/`)

The collaborations (DJMAX, VA-11 HALL-A, Gunslinger Girl, The Division, Dropkick on My Devil,
Zombie Land Saga, Ghost in the Shell, Arena Breakout, and BlazBlue × Guilty Gear's Operation Rabbit
Hunt, campaign -8) are left out of the permanent campaign in the
original data. This mod lists them there (`normal_activity` rows 101–112; the list groups rows by
their tag text, at most four chapters a group, so each collab has its own tag and order) and makes
their events permanent (`mission_event` type 2: the three newest had expired type 1 rows, the
others get rows 90001+). The server copies `mission_event` into the event list it sends at login
(`missions.event_info`). The list draws a banner from `Pics/Title/<bg_code>`; each collab's
mission-select image (`Pics/Icons/OPS/…`) is given a path there with `"art"`. Arena Breakout's own
Breakout mode is not handled, only its story maps. Disable the folder (rename it with a leading `_`) to hide them again.

The mod also puts each collab on the home screen's banner (see Home screen banners).

## Retired rankings (`retired_rankings/`)

Ranking maps that a later "+" version replaced (Operation Mistbuster by Operation Mistbuster+, and so on) can't be
reached from the event archives. This mod lists sixteen of them as one Campaign tab entry, "Retired Rankings":
Down the Rabbit Hole, Imaginary Maze, Hornet's Nest, Hurricane Rescue, Reign of Chaos (both), Flowers of the End and its
EX, Escape Acceleration EX-I, Labyrinthine Defense, Dual Randomness's three rankings (Vortex of Secrets, Tide of Blood,
Trap of Espionage), Mirror Stage's two (Scorpion Vortex, Operation Mistbuster) and City of Nightmares. It uses Dual
Randomness's background. The maps keep their ids, so the server's scoring and supply-line rules for them still apply.

## Home screen banners

`"banners": [{"event": 90005, "pic": "Pics/Icons/OPS/missionselect_VA11"}]` adds a banner to the scrolling bar at the bottom
right of the home screen. `event` is a `mission_event` id: a click opens that event's own screen, which `ActivityMapConfig.txt`
picks (a campaign it doesn't list opens the campaign menu instead). `pic` is an image the client has, without the extension;
`client_patch/offline_banners.lua` loads it, since the client would otherwise download it from the CDN. At most 16: past that
the bar's "show all" layout fails, so the build refuses more. Only the collabs use it, since the other events are all in the
campaign menu.

## Config edits

`"profile_edits": {"opspanel/campion-74.txt": [{"from": "<whole line>", "to": "<whole line>"}]}` changes lines of the
client's config files (`profilesconfig/`, lower-case paths). The build stops if the line isn't there exactly once.
`ck_letters/` uses it to uncomment Convolutional Kernel's letter entrance.

## Houkai Gakuen 2 collaboration (`honkai_collab/`)

The 2017 collaboration with Houkai Gakuen 2 (campaign -14, "Honkai Descends": maps 10043-10046) ran
only on the CN server. The EN client still carries its spots, enemies, skills, English names,
story files and art; only the table rows were left out. This mod copies them from the CN tables
(`cn-data/`): the maps (`mission`), their story links (`story_util` 198-201), the six dolls
(`gun` 1003-1008: Kiana, Mei, Bronya, Theresa, Himeko, Seele), their skins (`skin` and
`gift_item` 506-508), the three fairies (`fairy` 1001-1003: Sakura, Kaguya, Chloe; the EN client
has their skins, skills and art, and the mod's English text replaces old placeholder names), and the
maps' clear rewards (catchdata `mission_event_prize_info`, pointing at prizes 6043-6046, which the EN
client has: a souvenir icon, `item` 1193, for map 3 and Theresa for map 4). It lists the event like the other collabs (`normal_activity` 113, tag
`COLLAB|10`; `mission_event` 90010, permanent) with the `missionselect_HonkaiGakuen2` banner. It
also grants the six dolls (level 100, 5 links, skills 10, fully enhanced; maps 3 and 4 only allow Mei) and the three
fairies (level 100, 5 stars), and opens the first map.
Map 2 is a hostage rescue (win type 7) and map 4 a supply line (win type 6); the offline server
handles both. The client's story text is Chinese (`avgtxt/-14-*.txt`); `story/` holds the English fan translation
by TLAnon and Amaryllis from `fan-tl/` (10 files, unchanged, with their credit line in the first scene).

