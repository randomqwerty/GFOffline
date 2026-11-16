"""Launcher parts that follow a game in progress: the Map tab and the battle result prompt.

Both read the running server's /gfoffline/ calls (gfserver/live_view.py) from a worker thread, so a busy or absent
server never stalls the window.
"""
import json
import queue
import threading
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from tkinter import ttk

from . import config

BASE = f"http://127.0.0.1:{config.BIND_PORT}/gfoffline/"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
COLORS = {"ours": "#3b82f6", "enemy": "#dc2626", "neutral": "#9ca3af", "hidden": "#4b5563"}
MAP_BACK, LINK = "#1f2329", "#6b7280"
OURS, FORCE, ENEMY = "#1d4ed8", "#047857", "#b91c1c"       # tags over units
MAP_EVERY, BATTLE_EVERY = 1500, 500       # ms


def fetch(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    with OPENER.open(req, timeout=5) as r:
        return json.loads(r.read() or b"{}")


class Worker:
    """Runs fetches off the Tk thread; results come back through poll() on it."""

    def __init__(self):
        self.out = queue.Queue()
        self.busy = set()

    def get(self, key, path, body=None):
        if key in self.busy:
            return
        self.busy.add(key)

        def run():
            try:
                result = fetch(path, body)
            except ConnectionRefusedError:
                result = None
            except urllib.error.URLError as e:
                result = None if isinstance(e.reason, ConnectionRefusedError) else {"error": str(e.reason)}
            except Exception as e:      # a timeout, or an error answer (HTTPError is a URLError with no refused reason)
                result = {"error": str(e) or type(e).__name__}
            self.out.put((key, result))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        done = []
        while True:
            try:
                key, result = self.out.get_nowait()
            except queue.Empty:
                return done
            self.busy.discard(key)
            done.append((key, result))


class BattlePrompt:
    """A window over the game asking whether to send a finished battle's result (gfserver/battle_hold.py)."""

    def __init__(self, root, worker):
        self.root, self.worker, self.win, self.shown = root, worker, None, None

    def update(self, waiting):
        if waiting is not None and waiting.get("error"):
            return                      # a slow answer: keep what is shown
        if not waiting or not waiting.get("id"):
            self.close()
            return
        if self.shown == waiting["id"]:
            return
        self.close()
        self.shown = waiting["id"]
        s = waiting.get("summary") or {}
        lines = [f"{s.get('kind', 'Battle')} at node {s.get('node', '?')}"]
        if "won" in s:
            lines.append("Won" if s["won"] else "Not won: the enemy is still standing")
        if "units" in s:
            lines.append(f"{s['units']} units, {s.get('down', 0)} at 0 HP")
        self.win = tk.Toplevel(self.root)
        self.win.title("Battle result")
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        box = ttk.Frame(self.win, padding=16)
        box.pack()
        ttk.Label(box, text="\n".join(lines), font=("Segoe UI", 11)).pack(anchor="w")
        ttk.Label(box, text="Reject: the game loses its connection at once and logs in again. The result doesn't count, "
                            "and the fight starts again on the map.", wraplength=360, style="Muted.TLabel").pack(anchor="w", pady=(8, 10))
        row = ttk.Frame(box)
        row.pack(anchor="e")
        ttk.Button(row, text="Reject", command=lambda: self.decide(False)).pack(side="right")
        send = ttk.Button(row, text="Send", command=lambda: self.decide(True))
        send.pack(side="right", padx=6)
        send.focus_set()
        self.win.protocol("WM_DELETE_WINDOW", lambda: self.decide(False))
        self.win.lift()

    def decide(self, send):
        if self.shown:
            self.worker.get("decide", "battle", {"id": self.shown, "send": send})
        self.close()

    def close(self):
        if self.win is not None:
            self.win.destroy()
        self.win = None
        if self.shown is not None:
            self.shown = None


class MapTab:
    """The whole map in progress: nodes by side and links, with the chibis of echelons, Coalition echelons, HOCs,
    other forces and enemies standing on their nodes, and buildings; click a node or unit for what is on it. The mouse wheel zooms around the pointer and dragging moves the map."""

    ZOOM_STEP, ZOOM_MAX = 1.25, 12.0
    LAYERS = (("ids", "Node numbers", False), ("buildings", "Buildings", True), ("chibis", "Chibis", True))

    def __init__(self, box, worker, switch=None):
        """switch(name): the BooleanVar of a saved setting (map_ids, map_buildings, map_chibis), kept between runs."""
        self.worker, self.data, self.header = worker, None, ""
        self.zoom, self.pan, self.drag, self.mission = 1.0, [0.0, 0.0], None, None
        self.chibis = {}             # "kind:code:skin" -> PhotoImages (full, half, third size), or None
        top = ttk.Frame(box)
        top.pack(fill="x")
        self.title = tk.StringVar(value="No map in progress.")
        ttk.Label(top, textvariable=self.title, style="Head.TLabel").pack(side="left")
        ttk.Button(top, text="Fit", width=6, command=self.fit).pack(side="right")
        self.show = {}
        for key, label, on in reversed(self.LAYERS):
            self.show[key] = switch(f"map_{key}") if switch else tk.BooleanVar(value=on)
            ttk.Checkbutton(top, text=label, variable=self.show[key], command=self.draw).pack(side="right", padx=(8, 0))
        ttk.Label(box, text="Blue: yours. Red: enemy. Grey: neutral. Dark: hidden. Click a node or unit for its details. "
                            "Mouse wheel: zoom. Drag: move.", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        body = ttk.Frame(box)
        body.pack(fill="both", expand=True, pady=(8, 0))
        self.canvas = tk.Canvas(body, background=MAP_BACK, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        side = ttk.Frame(body, width=320)
        side.pack(side="right", fill="y", padx=(10, 0))
        side.pack_propagate(False)
        self.info = tk.Text(side, wrap="word", width=42, borderwidth=0, font=("Segoe UI", 9))
        self.info.pack(fill="both", expand=True)
        self.say("Click a node to see what is on it.")

    def say(self, text):
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", text)
        self.info.configure(state="disabled")

    def update(self, data):
        if data is None:
            self.title.set("The server isn't running.")
            self.data = None
        elif data.get("error"):
            self.title.set("The server didn't answer in time; trying again.")
            return
        elif not data.get("mission"):
            self.title.set("No map in progress.")
            self.data = None
        else:
            name = data.get("name") or f"Map {data['mission']}"
            self.title.set(f"{name} ({data['mission']}): turn {data['turn']}, {data['ap']} AP" + (", night" if data.get("night") else ""))
            if data["mission"] != self.mission:
                self.mission, self.zoom, self.pan = data["mission"], 1.0, [0.0, 0.0]
            self.data = data
        self.draw()

    # ------------------------------------------------------------ zoom and move

    def fit(self):
        self.zoom, self.pan = 1.0, [0.0, 0.0]
        self.draw()

    def wheel(self, e):
        step = self.ZOOM_STEP if e.delta > 0 else 1 / self.ZOOM_STEP
        zoom = min(self.ZOOM_MAX, max(1.0, self.zoom * step))
        # keep the point under the pointer where it is
        self.pan[0] = e.x - (e.x - self.pan[0]) * zoom / self.zoom
        self.pan[1] = e.y - (e.y - self.pan[1]) * zoom / self.zoom
        self.zoom = zoom
        if zoom == 1.0:
            self.pan = [0.0, 0.0]
        self.draw()

    def press(self, e):
        self.drag = (e.x, e.y, self.pan[0], self.pan[1], False)

    def move(self, e):
        if self.drag is None:
            return
        x, y, px, py, moved = self.drag
        if moved or abs(e.x - x) + abs(e.y - y) > 4:
            self.drag = (x, y, px, py, True)
            self.pan = [px + e.x - x, py + e.y - y]
            self.draw()

    def release(self, e):
        self.drag = None

    # ------------------------------------------------------------ drawing

    def picture(self, pic):
        """Full, half and third size PhotoImages of a {"kind", "code", "skin"} picture; None until it arrives or
        when there is none."""
        if not pic or not pic.get("code"):
            return None
        key = f"{pic['kind']}:{pic['code']}:{pic.get('skin') or 0}"
        if key not in self.chibis:
            self.chibis[key] = None
            self.worker.get("chibi:" + key, f"chibi?kind={pic['kind']}&code={urllib.parse.quote(str(pic['code']))}"
                                            f"&skin={pic.get('skin') or 0}")
        return self.chibis[key]

    def got_chibi(self, key, result):
        key = key.split(":", 1)[1]
        if result and result.get("png"):
            try:
                full = tk.PhotoImage(data=result["png"])
                self.chibis[key] = (full, full.subsample(2), full.subsample(3))
            except tk.TclError:
                self.chibis[key] = None
            self.draw()
        elif result is None or result.get("error"):
            self.chibis.pop(key, None)       # the server wasn't there: ask again later

    def draw(self):
        c = self.canvas
        c.delete("all")
        if not self.data or not self.data.get("nodes"):
            return
        show = {k: v.get() for k, v in self.show.items()}
        nodes = {n["id"]: n for n in self.data["nodes"]}
        xs, ys = [n["x"] for n in nodes.values()], [-n["y"] for n in nodes.values()]
        w, h = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        pad = 60
        base = min((w - 2 * pad) / max(1, max(xs) - min(xs)), (h - 2 * pad) / max(1, max(ys) - min(ys)))
        at = lambda n: ((pad + (n["x"] - min(xs)) * base) * self.zoom + self.pan[0],
                        (pad + (-n["y"] - min(ys)) * base) * self.zoom + self.pan[1])
        for a, b in {tuple(sorted((n["id"], o))) for n in nodes.values() for o in n["links"] if o in nodes}:
            (x0, y0), (x1, y1) = at(nodes[a]), at(nodes[b])
            c.create_line(x0, y0, x1, y1, fill=LINK, width=max(2, min(4, self.zoom / 2)))
        r = max(6, min(22, base * self.zoom * 40))
        font = max(7, min(11, int(r * 0.7)))
        size = 0 if r >= 11 else 1 if r >= 7.5 else 2            # which picture size fits the nodes
        drawn = sorted((n for n in nodes.values() if -150 < at(n)[0] < w + 150 and -60 < at(n)[1] < h + 200),
                       key=lambda n: at(n)[1])
        for n in drawn:
            x, y = at(n)
            tag = f"n{n['id']}"
            c.create_oval(x - r, y - r, x + r, y + r, fill=COLORS.get(n["side"], "#9ca3af"),
                          outline="#6b7280" if n["hidden"] else "#e5e7eb", dash=(2, 2) if n["hidden"] else None,
                          width=2, tags=tag)
            if show["buildings"] and n.get("building"):
                self.draw_building(n, x, y, r, font, tag, show["chibis"], size)
            if show["ids"]:
                c.create_text(x, y + r + 2, text=str(n["id"]), anchor="n", fill="#d1d5db", font=("Segoe UI", font - 1), tags=tag)
            c.tag_bind(tag, "<ButtonRelease-1>", lambda e, n=n: self.click(n))
        for n in drawn:                     # what stands on the nodes, the lower ones in front
            self.draw_units(n, *at(n), r, font, f"n{n['id']}", show["chibis"], size)

    def draw_units(self, n, x, y, r, font, tag, pictures, size):
        """Echelons, Coalition echelons, HOCs, other forces and enemies on a node: their chibis standing on it with
        a tag above each; a square (ours) or a number (enemy team) where there is no chibi."""
        c = self.canvas
        units = ([(e.get("picture"), e["short"], OURS) for e in n["echelons"]]
                 + [(f.get("picture"), "", FORCE) for f in n["forces"]]
                 + ([(n.get("enemy_picture"), str(n["enemy_team"]), ENEMY)] if n["enemy_team"] else []))
        if not units:
            return
        images = [(self.picture(p) or (None,) * 3)[size] if pictures else None for p, _, _ in units]
        stood = [img for img in images if img is not None]
        step = max((img.width() for img in stood), default=0) * 0.55
        k, foot = 0, y + r * 0.5
        squares = 0
        for img, (_, short, color) in zip(images, units):
            if img is not None:
                ux = x + (k - (len(stood) - 1) / 2) * step
                k += 1
                c.create_image(ux, foot, image=img, anchor="s", tags=tag)
                if short:
                    self.label(ux, foot - img.height(), short, color, font, tag)
            elif color == OURS:
                sq, sx = r * 0.55, x + squares * r * 0.5
                squares += 1
                c.create_rectangle(sx - sq, y - sq, sx + sq, y + sq, fill=color, outline="#ffffff", tags=tag)
                c.create_text(sx, y, text=short, fill="#ffffff", font=("Segoe UI", font - 1, "bold"), tags=tag)
            elif color == FORCE:
                c.create_text(x + r + 3, y - r / 2, text="F", anchor="w", fill="#6ee7b7", font=("Segoe UI", font, "bold"), tags=tag)
            else:
                self.label(x, y - r - 2, short, color, font, tag)

    def label(self, x, bottom, text, color, font, tag):
        c = self.canvas
        t = c.create_text(x, bottom - 2, text=text, anchor="s", fill="#ffffff", font=("Segoe UI", font - 1, "bold"), tags=tag)
        x0, y0, x1, y1 = c.bbox(t)
        box = c.create_rectangle(x0 - 3, y0, x1 + 3, y1, fill=color, outline="", tags=tag)
        c.tag_lower(box, t)

    def draw_building(self, n, x, y, r, font, tag, pictures, size):
        c = self.canvas
        img = (self.picture(n.get("building_picture")) or (None,) * 3)[size] if pictures else None
        if img is not None:
            c.create_image(x, y, image=img, tags=tag)
        else:
            s = r * 0.55
            bx, by = x - r * 0.95, y + r * 0.95
            fill = {"ours": "#93c5fd", "enemy": "#fca5a5"}.get(n.get("building_side"), "#e5e7eb")
            c.create_polygon(bx, by - s, bx + s, by, bx, by + s, bx - s, by, fill=fill, outline="#111827", tags=tag)
            if n.get("building_down"):
                c.create_line(bx - s, by - s, bx + s, by + s, fill="#111827", width=2, tags=tag)
        if self.zoom >= 2.5 and n.get("building_name"):
            c.create_text(x - r - 4, y + r, text=n["building_name"], anchor="e", fill="#d1d5db", font=("Segoe UI", font - 1), tags=tag)

    # ------------------------------------------------------------ what is on a node

    def click(self, n):
        if self.drag and self.drag[4]:
            return                  # the end of a drag, not a click
        self.pick(n)

    def pick(self, n):
        lines = [f"Node {n['id']}" + (" (hidden)" if n["hidden"] else ""), f"Side: {n['side']}"]
        if n.get("building"):
            name = n.get("building_name") or f"Building {n['building']}"
            lines.append(f"Building: {name} ({n['building']})" + (", destroyed" if n.get("building_down") else "")
                         + (f", {n['building_side']}" if n.get("building_side") else ""))
        for e in n["echelons"]:
            lines.append("")
            lines.append(e["label"])
            for m in e["members"]:
                lines.append(f"  {m['name']}: HP {m['hp']}/{m['max_hp']}")
                lines.append(f"    ammo {m['ammo']}/{m['max_ammo']}, rations {m['rations']}/{m['max_rations']}"
                             + (f"  ({', '.join(m['status'])})" if m["status"] else ""))
        for f in n["forces"]:
            lines.append(f"Force {f['force']} ({f['side']})" + (f", enemy team {f['enemy_team']}" if f["enemy_team"] else ""))
        team = n["enemy_team"] or next((f["enemy_team"] for f in n["forces"] if f["enemy_team"]), 0)
        self.header = "\n".join(lines)
        self.say(self.header)
        if team:
            self.worker.get("team", f"team?id={team}")

    def show_team(self, t):
        if not t or not t.get("found"):
            return
        lines = [self.header, "", f"Enemy team {t['team']}: CE {t['ce']}" + (f" (+{t['level_bonus']} levels this turn)" if t["level_bonus"] else "")]
        for m in t["members"]:
            lines.append(f"\n{'★ ' if m['leader'] else ''}{m['name']} ({m['id']}) x{m['number']}, level {m['level']}")
            lines.append(f"  HP {m['hp']}  Damage {m['damage']}  Rate {m['rate']}  Accuracy {m['accuracy']}")
            lines.append(f"  Evasion {m['evasion']}  Armor {m['armor']}  Range {m['range']}  Speed {m['speed']}"
                         + (f"  Boss HP {m['boss_hp']}" if m["boss_hp"] else ""))
        self.say("\n".join(lines))
