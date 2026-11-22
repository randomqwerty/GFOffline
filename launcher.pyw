"""The launcher: play the game, open Mod Studio, run the tools, and set the battle tools and keys. Double-click it, or:

  python launcher.pyw

Everything it starts runs as its own process, with the output shown in the window. Settings are saved as they change, to
settings.json (gfserver/client_settings.py); the server hands them to the game when it starts.
"""
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from gfserver import client_settings as cs, config, install, mods, updater  # noqa: E402
from gfserver import launcher_panels as panels  # noqa: E402

STUDIO_PORT = 8770
LOG_LINES = 2000
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PLAY = {"id": "play", "name": "The game", "args": ["play.py"]}
SETUP = {"id": "setup", "name": "Setup", "args": ["tools/setup_game.py"]}
STUDIO = {"id": "studio", "name": "Mod Studio", "args": ["tools/modstudio/studio.py"], "port": STUDIO_PORT, "url": f"http://127.0.0.1:{STUDIO_PORT}/"}
# ask: run it with a file chosen by the player. stays: it runs until stopped.
TOOLS = (
    ("Mods", (
        {"id": "build", "name": "Build mods", "about": "Puts your mods' changes into the game. Do this after changing or turning mods on or off, then start the game.",
         "args": ["tools/build_mods.py"]},
        {"id": "check", "name": "Check mods", "about": "Looks for problems in your mods without changing anything.", "args": ["tools/build_mods.py", "--check"]},
        {"id": "add_mod", "name": "Add a mod", "about": "Adds a mod someone shared with you: the .zip file Mod Studio's Export button makes. Build mods afterwards.",
         "args": ["tools/add_mod.py"], "ask": "Choose the mod file", "types": [("Mod file", "*.zip")]},
    )),
    ("Your account", (
        {"id": "check_save", "name": "Check your save against mods", "about": "Shows what your next login puts aside from mods that are off or gone, "
         "and what comes back from mods that are on again. The game does this by itself; this only shows it.", "args": ["tools/check_save.py"]},
        {"id": "from_log", "name": "Keep data from a packet log", "about": "Saves what a packet log recorded of your account, for the offline server. Uses no internet.",
         "args": ["tools/live_archive.py", "--from-log"], "ask": "Choose the packet log"},
        {"id": "from_live", "name": "Fetch data from the live game", "about": "Asks the live server for your account's data, using the login in a recent packet log. The game can stay open.",
         "args": ["tools/live_archive.py", "--log"], "ask": "Choose the packet log with a login from this session"},
    )),
    ("Maps", (
        {"id": "import_maps", "name": "Keep maps from a packet log", "about": "Keeps the enemy spawns and hidden markers that your recorded map starts "
         "and turns showed, so the offline server plays those maps the same way. Uses no internet.",
         "args": ["tools/import_maps.py"], "ask": "Choose the packet log"},
    )),
    ("Maintenance", (
        {"id": "server", "name": "Server only", "about": "Runs the offline server without starting the game.", "args": ["run.py"], "stays": True},
        {"id": "archive", "name": "Archive the live service", "about": "Downloads the game's files from the live service. Takes a long time, and is safe to run again.", "args": ["tools/archive_live.py"]},
        {"id": "patch", "name": "Rebuild the game patch", "about": "Play does this by itself when the files in client_patch change.", "args": ["tools/build_patch.py"]},
    )),
)

KEYSYMS = {"space": "Space", "Escape": "Escape", "Return": "Return", "KP_Enter": "KeypadEnter", "Tab": "Tab", "BackSpace": "Backspace",
           "grave": "BackQuote", "minus": "Minus", "equal": "Equals", "bracketleft": "LeftBracket", "bracketright": "RightBracket",
           "backslash": "Backslash", "semicolon": "Semicolon", "apostrophe": "Quote", "comma": "Comma", "period": "Period", "slash": "Slash",
           "Up": "UpArrow", "Down": "DownArrow", "Left": "LeftArrow", "Right": "RightArrow", "Shift_L": "LeftShift", "Shift_R": "RightShift",
           "Control_L": "LeftControl", "Control_R": "RightControl", "Alt_L": "LeftAlt", "Alt_R": "RightAlt", "Insert": "Insert",
           "Delete": "Delete", "Home": "Home", "End": "End", "Prior": "PageUp", "Next": "PageDown"}


def key_name(keysym, keycode=0):
    """The game's name for a key press, or None if the game can't use it. keycode tells the number pad from the number row."""
    if 96 <= keycode <= 105:
        return f"Keypad{keycode - 96}"
    if len(keysym) == 1 and keysym.isascii() and keysym.isalpha():
        return keysym.upper()
    if len(keysym) == 1 and keysym.isdigit():
        return f"Alpha{keysym}"
    if re.fullmatch(r"F([1-9]|1[0-2])", keysym):
        return keysym
    return KEYSYMS.get(keysym)


def python_exe():
    """python.exe rather than pythonw.exe, so the output can be read. The built release has its own (packaging/frozen_main.py)."""
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return str(exe.with_name("gfpython.exe"))
    plain = exe.with_name("python.exe")
    return str(plain if plain.is_file() else exe)


def command(entry, chosen=None):
    args = [python_exe()]
    for a in entry["args"]:
        args.append(a if a.startswith("-") or not a.endswith(".py") else str(ROOT / a))
    return args + ([chosen] if chosen else [])


def port_busy(port):
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def team_label(team):
    return f"{team['name'] or 'Team'} · {team['id']} · {team['members']} enemies"


def load_teams():
    """Every enemy team, mods' too. Slow the first time: it reads the game data through Mod Studio's code."""
    sys.path.insert(0, str(ROOT / "tools" / "modstudio"))
    import studio
    sys.modules.setdefault("studio", studio)
    return studio.catalog("team")


class Runner:
    """The processes the launcher started. Their output and exits come out of `events`, read on the window's thread."""

    def __init__(self):
        self.procs = {}
        self.events = queue.Queue()

    def running(self, key):
        p = self.procs.get(key)
        return p is not None and p.poll() is None

    def start(self, key, args):
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        p = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        self.procs[key] = p
        threading.Thread(target=self._read, args=(key, p), daemon=True).start()
        return p

    def _read(self, key, p):
        for line in p.stdout:
            self.events.put(("line", key, line.rstrip("\n")))
        self.events.put(("exit", key, p.wait()))

    def stop(self, key):
        """Stops it and whatever it started: play.py's game, for one."""
        p = self.procs.get(key)
        if p is None or p.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        else:
            p.terminate()

    def stop_all(self):
        for key in list(self.procs):
            self.stop(key)


class Launcher(tk.Tk):
    def __init__(self, settings_file=None, runner=None):
        super().__init__()
        self.settings_file = settings_file
        self.runner = runner or Runner()
        self.names = {e["id"]: e["name"] for e in [PLAY, SETUP, STUDIO] + [t for _, group in TOOLS for t in group]}
        self.teams = None
        self.tool_buttons = {}
        self.title("GF1 Offline")
        self.geometry(f"780x{min(860, self.winfo_screenheight() - 80)}")
        self.minsize(520, 360)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        problem = None
        try:
            self.settings = cs.load(settings_file)
        except cs.SettingsError as e:
            self.settings, problem = cs.clean({}), f"Your settings file couldn't be read, so these are the defaults. Changing anything replaces it. ({e})"
        self.settings_ok = problem is None

        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Big.TButton", font=("Segoe UI", 14, "bold"), padding=(26, 12))
        style.configure("Head.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Muted.TLabel", foreground="#666666")
        style.configure("Warn.TLabel", foreground="#b3261e")

        # tabs above, the log below, with a divider to drag; the log keeps its height when the window gets smaller
        self.panes = ttk.PanedWindow(self, orient="vertical")
        self.panes.pack(fill="both", expand=True, padx=10, pady=(10, 10))
        upper = ttk.Frame(self.panes)
        tabs = ttk.Notebook(upper)
        tabs.pack(fill="both", expand=True, pady=(0, 4))
        self.scrollers = []
        self.bind_all("<MouseWheel>", self.wheel, add="+")
        self.build_play(self.tab(tabs, "Play"))
        self.build_battle(self.tab(tabs, "Battle tools"))
        self.build_keys(self.tab(tabs, "Keys"))
        self.build_tools(self.tab(tabs, "Tools"))
        self.live = panels.Worker()
        self.map_tab = panels.MapTab(self.tab(tabs, "Map", scroll=False), self.live, self.setting_var)     # it zooms and drags itself
        self.battle_prompt = panels.BattlePrompt(self, self.live)
        self.tabs, self.live_ticks = tabs, 0

        self.note = tk.StringVar(value=problem or "")
        ttk.Label(upper, textvariable=self.note, style="Warn.TLabel", wraplength=750).pack(fill="x", padx=2)
        out = ttk.Frame(self.panes)
        self.log = tk.Text(out, height=8, wrap="word", state="disabled", font=("Consolas", 9), relief="solid", borderwidth=1)
        bar = ttk.Scrollbar(out, command=self.log.yview)
        self.log.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.panes.add(upper, weight=1)
        self.panes.add(out, weight=0)

        self.refresh()
        self.check_mods()
        if self.settings.get("check_updates") and updater.frozen():
            self.check_updates()
        self.poll_job = self.after(100, self.poll)

    def destroy(self):
        self.after_cancel(self.poll_job)
        super().destroy()

    def tab(self, tabs, title, scroll=True):
        """The frame a tab's contents go in; with scroll, inside a canvas with scrollbars for when the window is too small."""
        if not scroll:
            frame = ttk.Frame(tabs, padding=14)
            tabs.add(frame, text=title)
            return frame
        outer = ttk.Frame(tabs)
        tabs.add(outer, text=title)
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0, background=ttk.Style(self).lookup("TFrame", "background") or None)
        down = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        across = ttk.Scrollbar(outer, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=down.set, xscrollcommand=across.set)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        canvas.grid(row=0, column=0, sticky="nsew")
        frame = ttk.Frame(canvas, padding=14)
        item = canvas.create_window(0, 0, window=frame, anchor="nw")

        wraps, seen = {}, [None]

        def rewrap(width):
            # labels that wrap do so within the window, up to the width they were made with
            todo = list(frame.winfo_children())
            while todo:
                wdg = todo.pop()
                todo += wdg.winfo_children()
                if isinstance(wdg, ttk.Label):
                    made = wraps.setdefault(wdg, int(str(wdg.cget("wraplength") or 0) or 0))
                    if made > 0:
                        room = width - (wdg.winfo_rootx() - frame.winfo_rootx()) - 24
                        wdg.configure(wraplength=max(200, min(made, room)))

        def fit(_=None):
            # the contents get the canvas's width (labels wrap in it) unless they need more; bars show only when needed
            if seen[0] != canvas.winfo_width() and canvas.winfo_width() > 1:
                seen[0] = canvas.winfo_width()
                rewrap(seen[0])
            w, h = max(canvas.winfo_width(), frame.winfo_reqwidth()), max(canvas.winfo_height(), frame.winfo_reqheight())
            canvas.itemconfigure(item, width=w)         # the height follows the contents, so this runs again when they change
            canvas.configure(scrollregion=(0, 0, w, h))
            if frame.winfo_reqheight() <= canvas.winfo_height():
                canvas.yview_moveto(0)
            for bar, need, place in ((down, frame.winfo_reqheight() > canvas.winfo_height(), dict(row=0, column=1, sticky="ns")),
                                     (across, frame.winfo_reqwidth() > canvas.winfo_width(), dict(row=1, column=0, sticky="ew"))):
                if need and not bar.winfo_ismapped():
                    bar.grid(**place)
                elif not need and bar.winfo_ismapped():
                    bar.grid_remove()
        frame.bind("<Configure>", fit)
        canvas.bind("<Configure>", fit)
        self.scrollers.append(canvas)
        return frame

    def wheel(self, event):
        """The mouse wheel scrolls the tab under the pointer; the log, lists, text boxes and the map handle it themselves."""
        self.scroll_at(self.winfo_containing(event.x_root, event.y_root), event.delta)

    def scroll_at(self, widget, delta):
        while widget is not None:
            if widget in self.scrollers:
                if widget.yview() != (0.0, 1.0):
                    widget.yview_scroll(-1 * (delta // 120 or (1 if delta > 0 else -1)), "units")
                return
            if isinstance(widget, (tk.Text, tk.Listbox, tk.Canvas, ttk.Combobox, ttk.Spinbox)):
                return
            widget = widget.master

    # ------------------------------------------------------------ Play

    def build_play(self, box):
        self.play_button = ttk.Button(box, text="Play", style="Big.TButton", command=self.play)
        self.play_button.pack(anchor="w")
        self.play_status = tk.StringVar()
        self.play_label = ttk.Label(box, textvariable=self.play_status, wraplength=720)
        self.play_label.pack(anchor="w", pady=(8, 0))
        self.close_game = ttk.Button(box, text="Close the game", command=self.stop_game)
        self.close_game.pack(anchor="w", pady=(6, 0))

        self.stale_row = ttk.Frame(box)
        ttk.Label(self.stale_row, text="Your mods changed since they were last built, so the game won't have those changes yet.", style="Warn.TLabel").pack(side="left")
        ttk.Button(self.stale_row, text="Build mods", command=lambda: self.run_tool(self.tool("build"))).pack(side="left", padx=8)

        self.play_end = ttk.Separator(box)
        self.play_end.pack(fill="x", pady=14)
        self.build_account(box)
        ttk.Separator(box).pack(fill="x", pady=14)
        self.build_folders(box)
        ttk.Separator(box).pack(fill="x", pady=14)
        ttk.Label(box, text="Mod Studio", style="Head.TLabel").pack(anchor="w")
        ttk.Label(box, text="Make and edit mods, and turn them on or off. It opens in your browser.", style="Muted.TLabel").pack(anchor="w", pady=(2, 6))
        row = ttk.Frame(box)
        row.pack(anchor="w")
        self.studio_button = ttk.Button(row, text="Open Mod Studio", command=self.open_studio)
        self.studio_button.pack(side="left")
        self.studio_stop = ttk.Button(row, text="Stop", command=lambda: self.runner.stop("studio"))
        self.studio_stop.pack(side="left", padx=6)
        ttk.Separator(box).pack(fill="x", pady=14)
        self.build_updates(box)

    # ------------------------------------------------------------ updates

    def build_updates(self, box):
        ttk.Label(box, text="Updates", style="Head.TLabel").pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(2, 0))
        ttk.Label(row, text=f"This is version {updater.VERSION}.").pack(side="left")
        self.update_button = ttk.Button(row, text="Check for updates", command=lambda: self.check_updates(asked=True))
        self.update_button.pack(side="left", padx=8)
        self.var_check_updates = self.setting_var("check_updates")
        ttk.Checkbutton(box, text="Look for a new version when the launcher starts", variable=self.var_check_updates).pack(anchor="w", pady=(4, 0))
        ttk.Label(box, text="New versions come from the GF Offline releases on GitHub. Updating keeps your saves, mods and settings.",
                  style="Muted.TLabel", wraplength=720).pack(anchor="w")
        self.updating = False

    def check_updates(self, asked=False):
        if self.updating:
            return
        self.updating = True
        self.update_button.configure(state="disabled")
        if asked:
            self.say("Looking for a new version…")

        def work():
            try:
                self.runner.events.put(("update", updater.check(), asked))
            except updater.UpdateError as e:
                self.runner.events.put(("update", e, asked))
        threading.Thread(target=work, daemon=True).start()

    def on_update(self, info, asked):
        self.updating = False
        self.update_button.configure(state="normal")
        if isinstance(info, Exception):
            if asked:
                self.say(f"Couldn't look for updates: {info}")
            return
        if info is None:
            if asked:
                self.say(f"Version {updater.VERSION} is the newest.")
            return
        notes = info["notes"][:600] + ("…" if len(info["notes"]) > 600 else "")
        about = f"GF Offline {info['version']} is out (this is {updater.VERSION}).\n\n" + (notes + "\n\n" if notes else "")
        if not updater.frozen() or not info["url"]:
            if messagebox.askyesno("New version", about + "Open its download page?", parent=self):
                webbrowser.open(info["page"])
            return
        size = f" ({info['size'] / 1e6:.0f} MB)" if info["size"] else ""
        busy = [self.names.get(k, k) for k in self.runner.procs if self.runner.running(k)]
        warn = ("When it's downloaded, this closes: " + ", ".join(busy) + ".\n\n") if busy else ""
        if not messagebox.askyesno("New version", about + f"Download and install it now{size}? The launcher restarts when it's done. "
                                   "Your saves, mods and settings stay.\n\n" + warn, parent=self):
            return
        self.updating = True
        self.update_button.configure(state="disabled")
        self.say(f"Downloading GF Offline {info['version']}…")
        shown = [0]

        def progress(done, total):
            step = int(done * 10 / total) if total else 0
            if step > shown[0]:
                shown[0] = step
                self.runner.events.put(("line", "update", f"  {step * 10}%"))

        def work():
            try:
                self.runner.events.put(("update_ready", updater.download(info, progress=progress), info["version"]))
            except (updater.UpdateError, OSError) as e:
                self.runner.events.put(("update_ready", e, info["version"]))
        threading.Thread(target=work, daemon=True).start()

    def on_update_ready(self, new, version):
        if isinstance(new, Exception):
            self.updating = False
            self.update_button.configure(state="normal")
            self.say(f"The update didn't download: {new}")
            return
        try:
            updater.install(new)
        except (updater.UpdateError, OSError) as e:
            self.updating = False
            self.update_button.configure(state="normal")
            self.say(f"The update couldn't start: {e}")
            return
        self.say(f"Installing GF Offline {version}; the launcher opens again when it's done.")
        self.runner.stop_all()
        self.destroy()

    ACCOUNTS = (("own", "Your account", "The account file in player/; the sample account when there is none."),
                ("sample", "Sample account", "Most things already unlocked."),
                ("new", "New account", "Pick a name, then play the tutorial from the start."),
                ("perfect", "Perfect account", "One of every unit, all maxed, all equipment, every map opened, nothing else: for reading the story."))

    def build_account(self, box):
        ttk.Label(box, text="Account", style="Head.TLabel").pack(anchor="w")
        ttk.Label(box, text="Each is kept separately in saves/. Used from the next Play.", style="Muted.TLabel").pack(anchor="w", pady=(2, 6))
        self.account_var = tk.StringVar(value=self.settings["account"])
        for value, name, about in self.ACCOUNTS:
            row = ttk.Frame(box)
            row.pack(anchor="w")
            ttk.Radiobutton(row, text=name, value=value, variable=self.account_var,
                            command=lambda: self.set_setting("account", self.account_var.get())).pack(side="left")
            ttk.Label(row, text=about, style="Muted.TLabel").pack(side="left", padx=6)
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(6, 0))
        ttk.Button(row, text="Start a new account over", command=self.restart_new_account).pack(side="left")
        self.new_account_note = tk.StringVar()
        ttk.Label(row, textvariable=self.new_account_note, style="Muted.TLabel").pack(side="left", padx=6)
        self.show_new_account()

    def show_new_account(self):
        n = self.settings["new_account"]
        self.new_account_note.set(f"New account {n}." + (" Earlier ones stay in saves/." if n > 1 else ""))

    def restart_new_account(self):
        if not messagebox.askyesno("Start over", "Make another new account? The current one is kept in saves/ but won't be played.", parent=self):
            return
        self.settings["account"] = "new"
        self.account_var.set("new")
        self.set_setting("new_account", self.settings["new_account"] + 1)
        self.show_new_account()

    def build_folders(self, box):
        saved = install.load()
        ttk.Label(box, text="Game folders", style="Head.TLabel").pack(anchor="w")
        ttk.Label(box, text="The game's files are only read. The offline copy needs about 280 MB on the same drive as the game (the rest is linked, not copied), or the game's full size on another drive.", style="Muted.TLabel", wraplength=720).pack(anchor="w", pady=(2, 6))
        steam = install.find_steam_game()
        self.source_var = tk.StringVar(value=saved.get("source") or (str(steam) if steam else ""))
        self.game_var = tk.StringVar(value=saved.get("game") or str(config.GAME_DIR))
        self.archive_var = tk.StringVar(value=saved.get("archive") or "")
        grid = ttk.Frame(box)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        rows = (("Game files (Steam, or another folder)", self.source_var), ("Offline copy goes in", self.game_var), ("Archive folder (optional)", self.archive_var))
        for i, (label, var) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(grid, textvariable=var).grid(row=i, column=1, sticky="ew", padx=6, pady=2)
            ttk.Button(grid, text="Browse", command=lambda v=var, t=label: self.browse(v, t)).grid(row=i, column=2, pady=2)
        self.setup_button = ttk.Button(box, text="Set up", command=self.run_setup)
        self.setup_button.pack(anchor="w", pady=(8, 0))
        ttk.Label(box, text="Run it once before playing, and again after changing a folder. It fetches a small file from the live service unless the archive folder has it.", style="Muted.TLabel", wraplength=720).pack(anchor="w", pady=(4, 0))

    def browse(self, var, title):
        chosen = filedialog.askdirectory(parent=self, title=title, initialdir=var.get() or None)
        if chosen:
            var.set(chosen.replace("/", "\\"))

    def run_setup(self):
        if self.runner.running("setup"):
            self.runner.stop("setup")
            return
        if self.runner.running("play"):
            messagebox.showinfo("The game is running", "Close the game first.", parent=self)
            return
        args = []
        for flag, var in (("--source", self.source_var), ("--game", self.game_var), ("--archive", self.archive_var)):
            if var.get().strip():
                args += [flag, var.get().strip()]
        self.say("Starting: Setup")
        self.runner.start("setup", command(SETUP) + args)
        self.refresh()

    def play(self):
        if self.runner.running("play"):
            return
        if self.runner.running("setup"):
            messagebox.showinfo("Setup is running", "Setup hasn't finished yet.", parent=self)
            return
        if not install.ready() and not (config.GAME_DIR / install.GAME_EXE).is_file():
            messagebox.showinfo("Set up first", "Press Set up first, under Game folders, to get the game ready for offline play.", parent=self)
            return
        if not self.settings_ok:
            if not messagebox.askokcancel("Settings not saved", self.note.get() + "\n\nStart the game with your last saved settings?", parent=self):
                return
        if port_busy(config.BIND_PORT):
            messagebox.showinfo("Server already running", "The offline server is already running. Stop \"Server only\" on the Tools tab, or close the other copy, then press Play.", parent=self)
            return
        self.say("Starting the game")
        self.runner.start("play", command(PLAY))
        self.refresh()

    def stop_game(self):
        if messagebox.askyesno("Close the game", "Close the game now? Anything not yet sent to the server is lost.", parent=self):
            self.runner.stop("play")

    def open_studio(self):
        if port_busy(STUDIO_PORT):
            webbrowser.open(STUDIO["url"])
            return
        self.say("Starting Mod Studio; the first start takes a few seconds")
        self.runner.start("studio", command(STUDIO))
        self.open_when_ready(STUDIO)
        self.refresh()

    def open_when_ready(self, entry):
        if not self.runner.running(entry["id"]):
            return
        if port_busy(entry["port"]):
            webbrowser.open(entry["url"])
        else:
            self.after(300, self.open_when_ready, entry)

    # ------------------------------------------------------------ Battle tools

    def setting_var(self, key):
        var = tk.BooleanVar(value=self.settings[key])
        var.trace_add("write", lambda *_: self.set_setting(key, var.get()))
        return var

    def number_var(self, key):
        var = tk.StringVar(value=str(self.settings[key]))
        var.trace_add("write", lambda *_: self.set_setting(key, var.get().strip()))
        return var

    def set_setting(self, key, value):
        self.settings[key] = value
        self.save_settings()
        if key == "simulator":
            self.show_simulator()
        elif key == "custom_keys":
            self.render_keys()

    def save_settings(self):
        """Saved as it changes. Something refused, such as one key on two actions while swapping them, stays on screen unsaved."""
        try:
            typed = {k: self.settings[k] for k in cs.SIM_NUMBERS}
            self.settings = {**cs.save(self.settings, self.settings_file), **typed}
            self.settings_ok = True
            self.note.set("")
        except cs.SettingsError as e:
            self.settings_ok = False
            self.note.set(f"Not saved yet: {self.plain_error(e)}")
        except OSError as e:
            self.settings_ok = False
            self.note.set(f"Couldn't save the settings: {e}")

    @staticmethod
    def plain_error(e):
        s = str(e)
        for key, name in (("sim_runs", "Times to run each fight"), ("sim_seed", "Fixed random seed"), ("sim_enemy_team", "Enemy team"),
                          ("sim_limit_drone_seconds", "Drone fight time limit"), ("sim_limit_other_seconds", "Other fight time limit"),
                          *((n, label) for n, label, _, _ in cs.GAME_CONFIG)):
            s = s.replace(key, name)
        return s

    def switch(self, box, key, label, about):
        var = self.setting_var(key)
        setattr(self, "var_" + key, var)
        ttk.Checkbutton(box, text=label, variable=var).pack(anchor="w", pady=(8, 0))
        ttk.Label(box, text=about, style="Muted.TLabel", wraplength=700).pack(anchor="w", padx=(22, 0))

    def build_battle(self, box):
        ttk.Label(box, text="Each one is on or off by itself. Changes apply the next time you start the game.", style="Muted.TLabel").pack(anchor="w")
        self.switch(box, "damage_log", "Show the damage log after every fight",
                    "The same screen as target practice: each unit's damage, shield damage, damage taken and armor broken.")
        self.switch(box, "damage_csv", "Save each fight's totals to a spreadsheet file",
                    "One file a day, battle_logs/damage_<date>.csv in the game folder. Opens in Excel.")
        self.switch(box, "skill_overlay", "Show skills on screen as they are cast",
                    "A running list at the top left of the fight: the time, who cast it (blue for yours, red for enemies) and the skill.")
        self.switch(box, "battle_log", "Save a full battle log of every fight",
                    "Everything that happens, with its time: hits, skills, attacks, buffs, triggers, targets, movement, deaths. One file a fight: "
                    "battle_logs/battle_<date>_<time>.csv. Big fights make big files.")
        self.switch(box, "mobile_armor", "Mobile Armors in target practice",
                    "Tap a HOC slot, open the vehicle tab, tap an armor and Confirm. It fights in place of the echelon and its fairy, with your HOCs. "
                    "Tap it again and Confirm to go back to the echelon. Keep one doll in the echelon so the fight can start: it stays out.")
        self.switch(box, "old_target_order", "Old enemy targeting order",
                    "When enemies could target several of your units equally, they pick by place in the echelon, the last (rightmost on the "
                    "skill bar) first and the first (leftmost) last, as the game once did. Off: the doll you got earliest is picked first.")
        self.switch(box, "confirm_battles", "Ask before a battle result counts",
                    "When a battle ends (Coalition and vehicle battles and ranged attacks too), this window asks whether to send the result. Reject it to "
                    "redo the battle: the game loses its connection and logs in again, and the fight starts again on the map. Works straight away, no restart needed.")
        ttk.Label(box, text="Target practice enemies").pack(anchor="w", pady=(8, 0))
        row = ttk.Frame(box, padding=(22, 0, 0, 0))
        row.pack(anchor="w", fill="x")
        self.var_target_practice = tk.StringVar(value=self.settings["target_practice"])
        self.var_target_practice.trace_add("write", lambda *_: self.set_setting("target_practice", self.var_target_practice.get()))
        ttk.Entry(row, textvariable=self.var_target_practice, width=60).pack(side="left")
        ttk.Label(box, text="Enemy team ids (as GFLMaps shows them), separated by commas. Target practice lists these in place of your "
                            "saved list, which is kept; leave it empty to get your list back. Applies at the next login.",
                  style="Muted.TLabel", wraplength=700).pack(anchor="w", padx=(22, 0))
        self.build_rules(box)
        self.switch(box, "simulator", "Simulator",
                    "Changes target practice fights so you can test a team: pick the enemy, repeat the fight, and get the results as a table.")

        self.sim_box = ttk.Frame(box, padding=(22, 6, 0, 0))
        grid = self.sim_box
        ttk.Label(grid, text="Enemy team").grid(row=0, column=0, sticky="w", pady=3)
        cell = ttk.Frame(grid)
        cell.grid(row=0, column=1, sticky="w", padx=8)
        self.team_text = tk.StringVar()
        ttk.Label(cell, textvariable=self.team_text).pack(side="left")
        ttk.Button(cell, text="Pick…", command=self.pick_team).pack(side="left", padx=(8, 0))
        ttk.Button(cell, text="Clear", command=lambda: self.set_team(None)).pack(side="left", padx=4)
        self.show_team(None)
        ttk.Label(grid, text="Times to run each fight").grid(row=1, column=0, sticky="w", pady=3)
        self.var_runs = self.number_var("sim_runs")
        ttk.Entry(grid, textvariable=self.var_runs, width=10).grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(grid, text="Fixed random seed").grid(row=2, column=0, sticky="w", pady=3)
        self.var_seed = self.number_var("sim_seed")
        ttk.Entry(grid, textvariable=self.var_seed, width=14).grid(row=2, column=1, sticky="w", padx=8)
        ttk.Label(grid, text="Above 0 starts every run from this seed, to compare two teams fairly. 0 leaves it random.",
                  style="Muted.TLabel", wraplength=640).grid(row=3, column=0, columnspan=2, sticky="w")
        self.var_sim_no_random = self.setting_var("sim_no_random")
        ttk.Checkbutton(grid, text="No random damage (simulator fights only)", variable=self.var_sim_no_random).grid(row=4, column=0, columnspan=2, sticky="w", pady=3)
        self.var_limit_drone, self.var_limit_drone_seconds = self.limit_row(grid, 5, "sim_limit_drone", "End drone fights after")
        self.var_limit_other, self.var_limit_other_seconds = self.limit_row(grid, 6, "sim_limit_other", "End other target practice fights after")
        ttk.Label(grid, text="Gives every run the same length, and ends fights that never would, such as an invincible drone. "
                             "The clock is the fight's own, so game speed and pausing don't change it. A fight stopped this way counts as not won.",
                  style="Muted.TLabel", wraplength=640).grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Label(grid, text="Start it from a target practice stage. Results go to battle_logs/simulator_<date>.csv in the game folder.",
                  style="Muted.TLabel", wraplength=640).grid(row=8, column=0, columnspan=2, sticky="w")
        self.show_simulator()

    def build_rules(self, box):
        ttk.Label(box, text="Game rules").pack(anchor="w", pady=(8, 0))
        ttk.Label(box, text="Change some of the game's own limits. Leave a box empty for the game's value, shown beside it. "
                            "Applies the next time you start the game.", style="Muted.TLabel", wraplength=700).pack(anchor="w", padx=(22, 0))
        grid = ttk.Frame(box, padding=(22, 4, 0, 0))
        grid.pack(anchor="w", fill="x")
        try:
            from gfserver import stc
            game = {r["parameter_name"]: r["parameter_value"] for r in stc._catchdata()["game_config_info"]}
        except Exception:     # no game data yet: the values just aren't shown
            game = {}
        saved = self.settings.get("game_config") or {}
        self.rule_vars = {}
        for row, (name, label, lo, hi) in enumerate(cs.GAME_CONFIG):
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(saved.get(name, "")))
            var.trace_add("write", lambda *_, n=name, v=var: self.set_rule(n, v.get().strip()))
            ttk.Entry(grid, textvariable=var, width=10).grid(row=row, column=1, sticky="w", padx=8)
            hint = f"game: {game[name]}" if name in game else ""
            ttk.Label(grid, text=f"{hint}  ({lo} to {hi})".strip(), style="Muted.TLabel").grid(row=row, column=2, sticky="w")
            self.rule_vars[name] = var

    def set_rule(self, name, value):
        rules = dict(self.settings.get("game_config") or {})
        rules[name] = value
        self.settings["game_config"] = rules
        self.save_settings()

    def limit_row(self, grid, row, key, label):
        on = self.setting_var(key)
        ttk.Checkbutton(grid, text=label, variable=on).grid(row=row, column=0, sticky="w", pady=3)
        cell = ttk.Frame(grid)
        cell.grid(row=row, column=1, sticky="w", padx=8)
        seconds = self.number_var(cs.SIM_LIMITS[key])
        ttk.Entry(cell, textvariable=seconds, width=10).pack(side="left")
        ttk.Label(cell, text="seconds").pack(side="left", padx=(6, 0))
        return on, seconds

    def show_simulator(self):
        if self.settings["simulator"]:
            self.sim_box.pack(anchor="w", fill="x")
        else:
            self.sim_box.pack_forget()

    def show_team(self, team):
        team_id = self.settings["sim_enemy_team"]
        try:
            team_id = int(team_id or 0)
        except ValueError:
            team_id = 0
        self.team_text.set(team_label(team) if team else f"Team {team_id}" if team_id else "Each stage's own enemies")

    def set_team(self, team):
        self.set_setting("sim_enemy_team", team["id"] if team else 0)
        self.show_team(team)

    def pick_team(self):
        win = tk.Toplevel(self)
        win.title("Pick the enemy team")
        win.geometry("520x480")
        win.transient(self)
        query = tk.StringVar()
        ttk.Label(win, text="Search by enemy name or team number").pack(anchor="w", padx=10, pady=(10, 2))
        entry = ttk.Entry(win, textvariable=query)
        entry.pack(fill="x", padx=10)
        entry.focus_set()
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=10, pady=8)
        box = tk.Listbox(frame, activestyle="none")
        bar = ttk.Scrollbar(frame, command=box.yview)
        box.configure(yscrollcommand=bar.set)
        box.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        status = tk.StringVar(value="Loading the game's enemy teams…")
        ttk.Label(win, textvariable=status, style="Muted.TLabel").pack(anchor="w", padx=10)
        shown = []

        def fill(*_):
            box.delete(0, "end")
            shown.clear()
            if self.teams is None:
                return
            q = query.get().strip().lower()
            found = [t for t in self.teams if not q or q in str(t["id"]) or q in (t["name"] or "").lower()]
            shown.extend(found[:500])
            box.insert("end", *[team_label(t) for t in shown])
            status.set(f"{len(found)} teams" + (", showing the first 500: search to narrow it" if len(found) > 500 else ""))

        def pick(*_):
            at = box.curselection()
            if at:
                self.set_team(shown[at[0]])
                win.destroy()

        def wait():
            if not win.winfo_exists():
                return
            if self.teams is None:
                win.after(200, wait)
            else:
                fill()

        def load():
            try:
                self.teams = load_teams()
            except Exception as e:
                self.teams = []
                self.runner.events.put(("line", "launcher", f"Couldn't read the enemy teams: {e}"))

        query.trace_add("write", fill)
        box.bind("<Double-Button-1>", pick)
        box.bind("<Return>", pick)
        row = ttk.Frame(win)
        row.pack(anchor="e", padx=10, pady=(4, 10))
        ttk.Button(row, text="Pick", command=pick).pack(side="left")
        ttk.Button(row, text="Cancel", command=win.destroy).pack(side="left", padx=(6, 0))
        if self.teams is None:
            threading.Thread(target=load, daemon=True).start()
        wait()

    # ------------------------------------------------------------ Keys

    def build_keys(self, box):
        self.var_custom_keys = self.setting_var("custom_keys")
        ttk.Checkbutton(box, text="Use my own keys", variable=self.var_custom_keys).pack(anchor="w")
        ttk.Label(box, text="For fights and story scenes. Changes apply the next time you start the game. Esc for going back, and the keys on the "
                            "results screen, are fixed by the game.", style="Muted.TLabel", wraplength=720).pack(anchor="w", pady=(2, 8))
        self.keys_box = ttk.Frame(box)
        self.keys_box.pack(fill="both", expand=True)
        self.render_keys()

    def key_of(self, action, default):
        return self.settings["keys"].get(action) or default

    def render_keys(self):
        for child in self.keys_box.winfo_children():
            child.destroy()
        if not self.settings["custom_keys"]:
            return
        row = 0
        for group in dict.fromkeys(a[2] for a in cs.KEY_ACTIONS):
            ttk.Label(self.keys_box, text=group, style="Head.TLabel").grid(row=row, column=0, sticky="w", pady=(6, 2))
            row += 1
            actions = [a for a in cs.KEY_ACTIONS if a[2] == group]
            for action, label, _, default in actions:
                key = self.key_of(action, default)
                clash = next((b[1] for b in actions if b[0] != action and self.key_of(b[0], b[3]) == key), None)
                ttk.Label(self.keys_box, text=label).grid(row=row, column=0, sticky="w", padx=(0, 16))
                ttk.Label(self.keys_box, text=cs.KEY_LABELS.get(key, key), width=10, anchor="center", relief="solid").grid(row=row, column=1, pady=1)
                ttk.Button(self.keys_box, text="Change", command=lambda a=action, n=label: self.capture_key(a, n)).grid(row=row, column=2, padx=(8, 2))
                if key != default:
                    ttk.Button(self.keys_box, text="Reset", command=lambda a=action: self.set_key(a, None)).grid(row=row, column=3)
                if clash:
                    ttk.Label(self.keys_box, text=f"Also used for: {clash}", style="Warn.TLabel").grid(row=row, column=4, sticky="w", padx=6)
                row += 1

    def set_key(self, action, key):
        keys = dict(self.settings["keys"])
        if key:
            keys[action] = key
        else:
            keys.pop(action, None)
        self.settings["keys"] = keys
        self.save_settings()
        self.render_keys()

    def capture_key(self, action, label):
        win = tk.Toplevel(self)
        win.title(label)
        win.geometry("320x120")
        win.transient(self)
        message = tk.StringVar(value="Press the new key…")
        ttk.Label(win, textvariable=message).pack(pady=(18, 10))
        # Cancel can't take the keyboard's focus: Escape, Space and Enter are keys people bind
        tk.Button(win, text="Cancel", takefocus=0, command=win.destroy).pack()

        def on_key(event):
            name = key_name(event.keysym, event.keycode)
            if name:
                win.destroy()
                self.set_key(action, name)
            else:
                message.set("The game can't use that key. Press another…")
            return "break"

        win.bind("<KeyPress>", on_key)
        win.bind("<Alt-KeyPress>", on_key)
        win.grab_set()
        win.focus_force()

    # ------------------------------------------------------------ Tools

    def tool(self, tool_id):
        return next(t for _, group in TOOLS for t in group if t["id"] == tool_id)

    def build_tools(self, box):
        for group, tools in TOOLS:
            ttk.Label(box, text=group, style="Head.TLabel").pack(anchor="w", pady=(8, 2))
            for t in tools:
                row = ttk.Frame(box)
                row.pack(fill="x", pady=2)
                button = ttk.Button(row, text=t["name"], width=30, command=lambda t=t: self.run_tool(t))
                button.pack(side="left", anchor="n")
                self.tool_buttons[t["id"]] = button
                ttk.Label(row, text=t["about"], style="Muted.TLabel", wraplength=470).pack(side="left", padx=10)

    def run_tool(self, t):
        if self.runner.running(t["id"]):
            self.runner.stop(t["id"])
            return
        chosen = None
        if t.get("ask"):
            chosen = filedialog.askopenfilename(parent=self, title=t["ask"], filetypes=t.get("types") or [("All files", "*")])
            if not chosen:
                return
        if t.get("port") and port_busy(t["port"]):
            webbrowser.open(t["url"])
            return
        self.say(f"Starting: {t['name']}")
        self.runner.start(t["id"], command(t, chosen))
        if t.get("port"):
            self.open_when_ready(t)
        self.refresh()

    # ------------------------------------------------------------ what's running

    def say(self, line):
        following = not self.log.winfo_viewable() or self.log.yview()[1] >= 0.999       # scrolled up to read: stay there
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        extra = int(self.log.index("end-1c").split(".")[0]) - LOG_LINES
        if extra > 0:
            self.log.delete("1.0", f"{extra + 1}.0")
        self.log.configure(state="disabled")
        if following:
            self.log.see("end")

    def poll(self):
        changed = False
        try:
            while True:
                event = self.runner.events.get_nowait()
                if event[0] == "line":
                    self.say(event[2])
                elif event[0] == "stale":
                    self.show_stale(event[1])
                elif event[0] == "update":
                    self.on_update(event[1], event[2])
                elif event[0] == "update_ready":
                    self.on_update_ready(event[1], event[2])
                else:
                    changed = True
                    self.on_exit(event[1], event[2])
        except queue.Empty:
            pass
        if changed:
            self.refresh()
        self.poll_live()
        self.poll_job = self.after(100, self.poll)

    def poll_live(self):
        """The Map tab and the battle prompt follow the running server (gfserver/launcher_panels.py)."""
        for key, result in self.live.poll():
            if key == "battle":
                self.battle_prompt.update(result)
            elif key == "map":
                self.map_tab.update(result)
            elif key == "team":
                self.map_tab.show_team(result)
            elif key.startswith("chibi:"):
                self.map_tab.got_chibi(key, result)
        self.live_ticks += 1
        serving = self.runner.running("play") or self.runner.running("server")
        if not serving:
            self.battle_prompt.close()
            return
        if self.settings.get("confirm_battles") and self.live_ticks % (panels.BATTLE_EVERY // 100) == 0:
            self.live.get("battle", "battle")
        if self.live_ticks % (panels.MAP_EVERY // 100) == 0 and self.tabs.tab(self.tabs.select(), "text") == "Map":
            self.live.get("map", "map")

    def on_exit(self, key, code):
        name = self.names.get(key, key)
        self.say(f"{name} finished." if code == 0 else f"{name} stopped (code {code}).")
        if key in ("build", "check", "setup"):
            self.check_mods()

    def refresh(self):
        playing = self.runner.running("play")
        self.play_button.configure(state="disabled" if playing else "normal", text="Playing…" if playing else "Play")
        self.play_status.set("The game is running. Keep this window open: it runs the offline server." if playing
                             else "Starts the offline server and the game. The server stops when the game closes.")
        if playing:
            self.close_game.pack(anchor="w", pady=(6, 0), after=self.play_label)
        else:
            self.close_game.pack_forget()
        self.setup_button.configure(text="Stop setup" if self.runner.running("setup") else "Set up")
        studio = self.runner.running("studio")
        self.studio_button.configure(text="Open in browser" if studio else "Open Mod Studio")
        self.studio_stop.configure(state="normal" if studio else "disabled")
        for tool_id, button in self.tool_buttons.items():
            name = self.tool(tool_id)["name"]
            button.configure(text=f"Stop: {name}" if self.runner.running(tool_id) else name)

    def check_mods(self):
        def work():
            self.runner.events.put(("stale", mods.stale()))
        threading.Thread(target=work, daemon=True).start()

    def show_stale(self, stale):
        if stale:
            self.stale_row.pack(anchor="w", pady=(10, 0), before=self.play_end)
        else:
            self.stale_row.pack_forget()

    def on_close(self):
        busy = [self.names.get(k, k) for k in self.runner.procs if self.runner.running(k)]
        if busy and not messagebox.askyesno("Close the launcher", "This also closes: " + ", ".join(busy) + ".\n\nClose anyway?", parent=self):
            return
        self.runner.stop_all()
        self.destroy()


def main():
    Launcher().mainloop()


if __name__ == "__main__":
    main()
