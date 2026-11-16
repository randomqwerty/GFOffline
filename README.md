# GFOffline

"Offline" version of Girls' Frontline (EN/PC) for preservation and modding purposes, with additional tools and the ability to add mods on top.

This is an unofficial fan project, not connected to Sunborn. It does not contain any game files, so you will need your own install of the game.

Disclaimer: created with assistance from Claude after doing the decompilation myself and sharing other datamined files, reference code, notes, etc. I plan to do more human edits and review over time, but this is naturally a huge undertaking.

## Getting started

1. Install the game from Steam, start it once, and let it finish downloading.
2. Download the release zip and unpack it anywhere with room. Keep the files together.
3. Start `GF Offline.exe`.
4. Verify that game folders are correct and press "Set up". This will copy game files that need to be patched (~280MB), hard-link the remaining files, and then download `resconfig.txt` from the live server, as that file is not stored in the client itself.
5. (Optional) Import your own account information (see below).
6. Enable any mods or tools, then press "Play".

## Launcher

| Tab | Description |
|---|---|
| Play | Starts the server and the game, sets up the game folders, opens Mod Studio. |
| Battle tools | Switches for additional tools related to in-game battles. Any logs are written to `battle_logs`. |
| Map | Map of the active mission. |
| Keys | Edits keybinds for fights and story scenes. |
| Tools | Miscellaneous tools. |

Settings apply the next time the game starts.

## Account Options

Pick the account under **Account** on the Play tab:

- "Your account": Your own account file in `player/` (see below) if it exists. Otherwise, uses the sample account.
- "Sample account": A sample endgame account.
- "New account": Starts a brand new account from the tutorial.
- "Perfect account": A (mostly) "perfect" account with all units and skins. Includes multiple of each equipment and Coalition mook, all maps unlocked, all items at their limit, and all achievements.

Each account's progress is kept separately in `saves/`. To play your own account, keep its data from the live game while the service is still up. All of it goes in `player/`.

### How to import your own account

You will need to download [GFAlarm](https://gfverse.info/gfl1/guides/how-to-use-gfalarm) for this.

Method 1:
1. Go to GFAlarm settings (gear icon) -> enable "Print Packet Log" (under "Extra").
2. Log into GFL while connected to GFAlarm.
3. Click "Fetch data from the live game" under "Tools" in the launcher and choose `GFAlarm/Log/<YYYY-MM-DD-packet.log`.
4. The launcher will use the session key (`sign` in `/Index/getUidEnMicaQueue`) to request information from the live server. Leave the game idle or closed until it finished. Note that logging back in from a closed session will cause the prior session to be invalidated, so you will have to repeat the process again. Automated calls may break the game's terms of service.

Method 2:
1. Go to GFAlarm settings (gear icon) -> enable "Save User Info" (under "File Save") and "Print Packet Log" (under "Extra").
2. Log into GFL while connected to GFAlarm.
3. Take the `<Name>_<UID>_user_info.json` that is created (under `GFAlarm/Info`) and place it into `GFOffline/player` .
4. Open the following  to record them if desired:
    - Dorms (your own and individual friends)
    - Mail
    - Achievement menu
    - Quest menu
    - Shop menu
    - Friend profile cards (must open each individually)
    - Friend support echelons
5. Click "Keep data from a packet log" under "Tools" in the launcher and choose `GFAlarm/Log/<YYYY-MM-DD-packet.log` to import this information.

Note that only the latest file in `player/` is used (the newest).

## Modding

Mods are folders in `mods/`, each with their on/off switches. By clicking "Open Mod Studio" (on the "Play" tab of the launcher), you can make and edit mods without editing the files themselves. After changing a mod, make sure to click "Build mods". See `mods/README.md` for more information.

A few mods are included with this release:

| Mod | Description |
|---|---|
| `collab_events` | Makes past collaboration events accessible once again, either through the Campaign menu or the scrolling banner on your main screen. The latter will show the original map selection interface. |
| `retired_rankings` | Makes past ranking maps accessible once again through the Campaign menu. This includes various maps that have been replaced with a "+" version as well as others that are no longer accessible at all (ex: PL Hole 2, DR Holes 2/3, MS Hole 1). |
| `ck_letters` | Re-enables the letter interface in Convolutional Kernel (for letters sent in Angular Gyrus) |
| `honkai_collab` | Adds the Honkai Gakuen 2 collaboration from the CN client's data, with a fan translation of its story by [TLAnon](https://drive.google.com/drive/folders/1uJ8XfZnY5IA2Yu1eguKY1SSFaugBZIf2?usp=sharing) and game files from [Amaryllis](https://dev.s-ul.net/BLUEALiCE/gfl-cutscene-interpreter) |

## Limitations

Missions involve numerous server-only items that are not present in the client or game data, such as spawns, movement priority, and hidden markers that trigger events on missions. As such, you should expect to see differences or even errors related to these while playing through different maps.

To help with this, you can record packet logs with playthroughs of maps from the live server (see GFAlarm instructions above) and then use "Keep maps from a packet log" (under "Tools" in the launcher). This will save any enemies and the markers to `map_recordings.json`. Alternatively, the mod studio (see below) has the ability to set spawn tables and movement priority for given maps.

Otherwise, Luffberry Chess is the other main limitation that I am aware of. The AI for bot players is not in the client, so they may be even more crippled than they are actually are in the live game.

## Folders

| Folder | Description |
|---|---|
| `gfserver/` | The server |
| `client_patch/` | Lua hotfixes added to the game copy, primarily for offline mode and battle tools. |
| `data/` | Table layouts, Luffberry Chess protocol, sample/new account files, shop/gacha files, spawn tables |
| `mods/` | Mods |
| `tools/` | Setup, patching, mod builds, archiving, Mod Studio |
| `packaging/` | Builds the release files |
