# GF1 Offline

A local stand-in for the Girls' Frontline (EN, PC) servers, for preservation and modding. It lets a copy of your own game run with no account or live server, with battle tools and a mod editor on top.

This is an unofficial fan project, not connected to Sunborn. It contains no game files: you need your own install of the game.

## Getting started

1. Install the game from Steam, start it once, and let it finish downloading.
2. Download the release zip and unpack it anywhere with room. Keep the files together.
3. Start `GF Offline.exe`.
4. Under **Game folders**, check the folders and press **Set up**. It takes a while the first time.
5. Press **Play**.

Running from source instead needs Python 3.10 or newer: `pip install -r requirements.txt`, then `python launcher.pyw`.

### What setup does

- **Steam's files are never changed.** The game folder is only read, and setup refuses to write inside a Steam library. The game you play offline is a separate copy. Only the files that get patched or run (about 280 MB) are really copied. The rest is hard-linked to the game's own files, so it takes no extra space when the copy is on the same NTFS drive as the game. On another drive the whole game is copied. After a Steam update, press **Set up** again.
- **The game folder doesn't have to be Steam's.** Choose any folder holding the game. To use a non-Steam folder directly instead of copying it, choose the same folder for both, and it gets patched in place.
- **One small download.** The game doesn't keep its resource config (about 2 MB) on disk, so setup fetches it once from the live service. Nothing else is downloaded.
- **After the live service closes,** that file can only come from an archive. Make one with **Archive the live service** on the Tools tab while the service is up, and keep it. Setup can then use it through the **Archive folder** field, with no network.

## The launcher

| Tab | What's there |
|---|---|
| Play | Starts the server and the game, sets up the game folders, opens Mod Studio |
| Battle tools | A switch each: damage log, totals spreadsheet, skill overlay, full battle log, Mobile Armors in target practice, simulator, old enemy targeting order (ties go to the rightmost unit on the skill bar, as the game once did). **Ask before a battle result counts**, and your own **Target practice enemies** (enemy team ids, comma-separated) |
| Map | The map you're playing: every node, enemy, building and echelon, hidden nodes included (on night maps, only the enemies you can see). Zoom with the mouse wheel and drag to move. Chibis of your echelons, Coalition echelons, HOCs and enemies stand on their nodes, with building icons; switches turn node numbers, buildings and chibis on or off. Click a node or chibi for its echelons' HP, ammo, rations and dolls, or its enemy team's members and stats |
| Keys | Your own keys for fights and story scenes |
| Tools | Build or check mods, fetch or keep your account's data, server only, archive the live service, rebuild the game patch |

Settings apply the next time the game starts. Battle tools write their files to `battle_logs/` in the offline copy.

With **Ask before a battle result counts** on, the launcher asks after each battle (Coalition and vehicle battles too). **Send** counts it. **Reject** makes the game lose its connection at once and log in again: the result doesn't count, and the map comes back with the fight still to do.

## Your account

Pick the account under **Account** on the Play tab:

- **Your account:** your own account file in `player/` (see below). Without one, the sample account.
- **Sample account:** most things already unlocked.
- **New account:** the game asks for a name, then plays the tutorial from the start. **Start a new account over** makes another; earlier ones are kept.
- **Perfect account:** every doll, Coalition unit, fairy and costume (those added by mods too), 5 of each equipment (1 of each exclusive one), all maxed and locked, and every map opened. A full echelon of each 1-2★ Coalition unit (one of each Ringleader), every item at its limit (99,999 where it has none), 99,999 of every gift and every achievement. Nothing else of the sample's: no echelons, presets or adjutants, only M4A1 in echelon 1. For reading the story.

Each account's progress is kept separately in `saves/`. To play your own account, keep its data from the live game while the service is still up. All of it goes in `player/`.

### What to keep

| Data | Where it comes from | Without it |
|---|---|---|
| Your account (dolls, equipment, items, progress) | `Index/index`, the reply to login | The sample account |
| Dorm furniture, mail, quests, achievements, career, Coalition, friends' cards and dorms, shop | Separate replies, fetched by the archive tool | Empty dorms and no friends. The shop is a new account's |
| Friends' support echelons with their equipment | `Mission/reinforceFriendTeam`, only sent when you deploy one | Top equipment is assumed |

### How

You need a packet logging tool that saves the game's traffic to a file (GF Alarm, for example). A plain saved account file (`<Name>_<UID>_user_info.json` from a tool that exports one) is enough for the account alone: put it in `player/`.

For everything else:

1. Start the logging tool, then start the game from Steam and log in.
2. In the launcher, **Tools** tab, press **Fetch data from the live game** and choose that log. It reads the login from the log and asks the live server for the replies above. The game can stay open. Logging in again ends that session, so use a log from the current one. If the log holds several logins, the last one is used.
3. The data goes to `player/archive/<uid>/` and your account to `player/<uid>_user_info.json`. Running it again only fetches what is missing.

The session key (the `sign` in the login reply) is read from the log for the run and never saved. No password is asked for. The calls only read data, except that friends whose dorms are fetched see you as a recent visitor. Automated calls may break the game's terms of service.

**Keep data from a packet log** (same tab) uses no network: it keeps only what the log already recorded. Use it for logs from earlier sessions, or once the service is gone. Open the menus you want kept while logging: dorm, mail, quests, friends' profiles, and a mission with a friend's echelon deployed.

Only one account file in `player/` is used, the newest.

### Not kept anywhere

**Enemy spawns during a map**, and **the order enemies move in**, were decided by the live server and aren't in any reply. The server uses each map's starting enemies, what you recorded (below), and otherwise guesses from enemy heliports; enemies move in the order they appeared. Set your own for any map in Mod Studio's **Map spawns** page, along with what its random nodes give. These are your own settings, not a mod. They are kept in `map_config.json`, and the server uses changes straight away.

### Recording maps

Some maps also get **hidden markers** from the live server: nodes that set off events, show where things appear, or decide a win. They only show once the map is started. While the live service is up, you can record what your maps do:

1. Start the logging tool, then the game, and log in.
2. Start a map. Playing a few turns records what each turn brings too. Then withdraw. Each start counts once, so starting a map several times gives truer odds.
3. In the launcher, **Tools** tab, press **Keep maps from a packet log** and choose the log.

The enemies that appeared and the markers laid at the start and at each turn go to `map_recordings.json`, and the server uses them straight away. Only map, node, team and marker numbers are kept, nothing about your account. The same log twice counts once. A map's spawns set in Mod Studio win over recorded ones.

## Mods

Mods are folders in `mods/`, each with its own on/off switch, all off to begin with. Mod Studio (**Open Mod Studio** on the Play tab) makes and edits them without touching files. After changing them, use **Build mods**. See `mods/README.md`.

To share a mod, pick it in Mod Studio and press **Export to share**: that makes one `.zip` file. To add a mod someone sent you, use **Add a mod** on the Tools tab and choose that file, then **Build mods**. A mod that uses the same ids as one you have on is added turned off, with a note saying which mod it clashes with.

| Mod | What it does |
|---|---|
| `collab_events` | Lists the collaboration events in the Campaign tab |
| `retired_rankings` | Lists ranking maps that their "+" versions replaced, as one Campaign tab entry |
| `ck_letters` | Turns on the Convolutional Kernel letter entrance |
| `honkai_collab` | Adds the Houkai Gakuen 2 collaboration from the CN client's data, with a fan translation of its story by TLAnon (game files from Amaryllis) |

## How it works

The launcher starts the game with this server as an HTTP proxy for that process only, so no system setting or hosts file changes. Requests for the game's hosts are answered locally and anything else is refused. The copy gets small patches: login goes through a Lua hotfix, and the account SDK and resource config are switched from HTTPS to HTTP so the proxy can answer them.

**One connection isn't stopped.** The game's NEP anti-cheat connects to its vendor (`ir-sdk.guardease.com`) by itself. It can't be removed, because it also decrypts the game's entry code. No game data goes through it, and blocking it would need firewall changes, which this project doesn't make. If that backend goes away, whether the game keeps running is untested.

## Folders

| Folder | What's in it |
|---|---|
| `gfserver/` | The server |
| `client_patch/` | Lua hotfixes added to the game copy |
| `data/` | Table layouts, the chess protocol, the sample and new-account starts, the shop and gashapon, spawn tables |
| `mods/` | Mods |
| `tools/` | Setup, patching, mod builds, archiving, Mod Studio |
| `packaging/` | Builds the no-Python release (`python packaging/build_exe.py`) |
These are created as you use it and are never part of the release: `install.json`, `settings.json`, `map_config.json`, `map_recordings.json`, `saves/`, `player/`, `archive/`, `build/`, `logs/`, `game/`.
