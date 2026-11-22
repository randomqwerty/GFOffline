/* Map editor for Mod Studio: settings, layout (nodes, links, zoom), enemy spawns, enemy move order. */
"use strict";

const SPOT_TYPES = { 1: "Command Post (HQ)", 2: "Node", 3: "Heliport", 7: "Heavy heliport", 5: "Supply point",
                     6: "Rally point", 8: "Repair point" };
const BELONGS = { 1: "Griffin", 2: "Enemy", 3: "Neutral", 0: "Other" };
// whose side an allied force fights on (gfserver/missions.py: 1 friendly, 2 enemy, 0 third party)
const FORCE_SIDES = { 1: "With you (Griffin)", 2: "With the enemy", 0: "Third party (fights everyone)" };

/** "Fights" select for an allied force: its own side by default, or one picked here. */
function forceSide(obj, key, teamId) {
  const sel = h("select", { onchange: () => { obj[key] = sel.value === "" ? null : Number(sel.value); if (obj[key] === null) delete obj[key]; dirty(); } });
  const fill = async () => {
    const it = (await catalog("ally_team")).find(r => String(r.id) === String(teamId));
    const own = it && it.side in FORCE_SIDES ? FORCE_SIDES[it.side].toLowerCase() : "its own side";
    sel.replaceChildren(h("option", { value: "" }, `As made (${own})`),
      ...[1, 2, 0].map(v => h("option", { value: v }, FORCE_SIDES[v])));
    sel.value = obj[key] === undefined || obj[key] === null ? "" : String(obj[key]);
  };
  fill();
  return sel;
}
const MAP_TYPES = { 1: "Village", 2: "Road", 3: "Bridge", 4: "Forest", 5: "City", 6: "Snowland", 7: "Snow village",
  8: "Snow forest", 9: "Forest 2", 10: "Airport", 11: "Grasslands", 12: "Village 2", 13: "Abandoned village", 14: "Valley",
  15: "Wasteland", 16: "Polluted", 17: "Network", 18: "Iron", 19: "Park", 20: "Train", 21: "Blood network", 22: "Downtown",
  23: "VA-11 city", 24: "Flowers", 26: "Beach", 28: "Tree sea" };
const MAP_CODES = { 1: "village", 2: "road", 4: "forest", 5: "city", 6: "snowland", 8: "snowforest", 9: "forest2", 10: "airport",
  11: "grasslands", 12: "village2", 13: "abandonedvillage", 14: "valley", 15: "wasteland", 16: "pollute", 17: "network", 21: "bloodnet" };
const GOALS = [[2, "Capture the enemy Command Post (or the win nodes)"], [1, "Reach the win nodes"],
               [3, "Destroy every enemy, or take the Command Post"], [4, "Destroy the boss team"], [11, "Survive a number of turns"],
               [7, "Rescue hostages"], [5, "Score points until the turn limit (ranking map)"]];
const SCORE_SPOTS = { 1: "Command Post", 2: "Node", 3: "Heliport", 7: "Heavy heliport", 5: "Supply point", 6: "Rally point" };

const NS = "http://www.w3.org/2000/svg";
const sv = (tag, a = {}) => { const n = document.createElementNS(NS, tag); for (const k in a) n.setAttribute(k, a[k]); return n; };
const ids = (v) => String(v ?? "").split(",").map(s => s.trim()).filter(s => /^\d+$/.test(s));

window.mapEditor = function (e) {
  S.mapTab ||= "settings";
  if (!e._free) { e._free = []; api("free/spot?n=300").then(list => { e._free = list; }); }
  const tabs = h("div", { class: "tabs" }, [["settings", "Settings"], ["layout", "Layout"], ["spawns", "Enemy spawns"], ["order", "Enemy move order"]]
    .map(([k, label]) => h("button", { class: S.mapTab === k ? "on" : "", onclick: () => { S.mapTab = k; renderEditor(); } }, label)));
  return h("div", {}, tabs, { settings: settingsTab, layout: layoutTab, spawns: spawnsTab, order: moveOrderTab }[S.mapTab](e));
};

// ------------------------------------------------------------------ settings

function settingsTab(e) {
  const L = S.L, wrap = h("div");
  wrap.append(card("Basics", h("div", { class: "fields" },
    field("Name", textInput(e, "name")), field("Subtitle", textInput(e, "subtitle")),
    field("Stage number", numberInput(e, "sub", { min: 1 }), "Its place in this mod's Campaign tab entry."),
    field("Time of day", selectInput(e, "night", { false: "Day", true: "Night (fog of war)" }, { text: true, onChange: () => { e.night = e.night === true || e.night === "true"; } })),
    field("Recommended combat effectiveness", numberInput(e, "difficulty"), "Enemy CE numbers are coloured against this."),
    field("Recommended level", numberInput(e, "level")),
    field("Enemy AI (default)", selectInput(e, "base_ai", L.map_ai), "Used by enemy teams set to the map's default AI.")),
    checkbox(e, "open", "Unlock this map for the player"),
    checkbox(e, "restart", "Allow restarting the map")));

  // victory
  const groups = String(e.goals || "2").split(";").map(g => g.split(",").map(x => x.trim()).filter(Boolean));
  const simple = groups.length === 1 || groups.every(g => g.length === 1);
  let mode = groups.length > 1 ? "any" : "all";
  const picked = new Set(simple ? groups.flat().filter(x => !x.endsWith("*")).map(Number) : []);
  const write = () => { const list = GOALS.map(g => g[0]).filter(g => picked.has(g)); e.goals = list.length ? list.join(mode === "all" ? "," : ";") : "2"; dirty(); };
  const goalBoxes = GOALS.map(([g, label]) => {
    const cb = h("input", { type: "checkbox" });
    cb.checked = picked.has(g);
    cb.disabled = !simple;
    cb.addEventListener("change", () => { cb.checked ? picked.add(g) : picked.delete(g); write(); renderEditor(); });
    return h("div", {}, h("label", { class: "check" }, cb, " " + label));
  });
  const modeSel = h("select", {}, h("option", { value: "all" }, "all of these"), h("option", { value: "any" }, "any one of these"));
  modeSel.value = mode;
  modeSel.addEventListener("change", () => { mode = modeSel.value; write(); });
  const wins = e.spots.filter(s => s.win).map(s => s.id);
  wrap.append(card("Victory",
    h("div", { class: "row" }, h("span", {}, "Win when"), modeSel),
    ...goalBoxes,
    simple ? null : h("p", { class: "muted small" }, `This map uses a combined goal (${e.goals}); copy it from a simpler map to edit it here.`),
    h("div", { class: "fields" },
      picked.has(1) || picked.has(2) || picked.has(3) ? field("Win nodes", h("span", {}, wins.length ? wins.join(", ") : "none (every enemy Command Post)"), "Mark them on the Layout tab.") : null,
      picked.has(4) ? field("Boss team", teamSlot(e, "boss_team")) : null,
      picked.has(11) ? field("Turns to survive", numberInput(e, "win_turn", { min: 1 })) : null,
      picked.has(7) ? field("Hostages to rescue", numberInput(e, "hostages", { min: 1 }), "Put hostages on nodes (Layout tab, a node's Mechanics).") : null)));

  const icons = { "": "Automatic (the boss's own, else a question mark)" };
  (S.L.mission_icons || []).forEach(n => { icons[n] = n; });
  wrap.append(card("Mission list icon", h("div", { class: "fields" },
    picked.has(4) ? null : field("Boss team", teamSlot(e, "boss_team"), "The icon needs a boss team. Its leader decides the picture, so maps with the same leader share one icon."),
    field("Icon", selectInput(e, "icon", icons, { text: true }), "The picture on this map's button in the mission list. A leader that already has its own icon keeps it."))));

  wrap.append(card("Defeat", h("div", { class: "fields" },
    field("Turn limit", numberInput(e, "turn_limit", { min: 0 }), "0 = no limit. The map is also lost when no echelon is left or every Griffin Command Post falls."))));

  const lim = e.limits;
  wrap.append(card("Deployment limits", h("div", { class: "fields" },
    field("T-Doll echelons", numberInput(lim, "echelons", { min: 0 }), "0 = no limit."),
    field("Coalition echelons", numberInput(lim, "coalition", { min: -1 }), "-1 = no limit, 0 = none."),
    field("HOC teams", numberInput(lim, "hoc", { min: -1 }), "-1 = no limit, 0 = none."),
    field("Vehicle teams", numberInput(lim, "vehicles", { min: -1 }), "-1 = no limit, 0 = none."),
    field("Friend support echelons", numberInput(lim, "support", { min: 0 })))));

  wrap.append(battlefieldCard(e));
  wrap.append(scoreCard(e, picked));

  wrap.append(card("Ranking", h("div", { class: "fields" },
    field("Turns for S rank", numberInput(e.rank, "turns", { min: 0 }), "0 = no turn target."),
    field("Enemies to defeat", numberInput(e.rank, "kills", { min: 0 }), "0 = no kill target."),
    field("T-Doll losses allowed", numberInput(e.rank, "losses", { min: 0 }))),
    h("p", { class: "muted small" }, "Rank starts at S and drops one step (to C at worst) for each missed target.")));

  wrap.append(h("details", { class: "card" }, h("summary", {}, "Map picture (advanced)"), h("div", { class: "fields" },
    field("Background", mapBackgroundInput(e), "Map art name, e.g. Chapter1_Y (from the game's maps), or one added under Pictures and music (OwnMap1_Y)."),
    field("Visible area", textInput(e, "frame"), "size|visible size|offset, e.g. 3000,2625|2472,1574|0,-758 (copy it from the map you started from)."))));
  return wrap;
}

/** Repairs and environment skills (the effects listed under the map's name before a battle). */
function battlefieldCard(e) {
  e.environment ||= [];
  const list = h("div");
  const draw = async () => {
    const all = await catalog("env_skill");
    const by = Object.fromEntries(all.map(r => [String(r.id), r]));
    list.replaceChildren(...e.environment.map((id, i) => {
      const r = by[String(id)] || { name: `Environment skill ${id}`, desc: "" };
      return h("div", { class: "mech" }, h("div", { class: "row" }, h("strong", {}, r.name),
          h("button", { class: "small danger", onclick: () => { e.environment.splice(i, 1); dirty(); draw(); } }, "Remove")),
        r.desc ? h("div", { class: "doc" }, r.desc) : null);
    }), e.environment.length ? "" : h("div", { class: "muted small" }, "None"),
    h("button", { class: "small", onclick: async () => {
      const id = await pickDialog("env_skill", "Add an environment skill");
      if (id !== null && !e.environment.includes(Number(id))) { e.environment.push(Number(id)); dirty(); draw(); } } }, "+ Add environment skill"));
  };
  draw();
  if (e.repair === undefined) e.repair = true;
  return card("Battlefield",
    checkbox(e, "repair", "Allow repairing T-Dolls on this map"),
    h("p", { class: "muted small" }, "Off shows “Repair Disabled” and blocks repairs."),
    field("Environment skills", list, "Effects on every battle of this map, shown with the map's name. Most maps have none."));
}

/** A ranking (score) map: what gives and costs points. */
function scoreCard(e, goals) {
  const on = { v: !!e.score };
  const toggle = checkbox(on, "v", "Ranking map: players score points", { onChange: () => {
    e.score = on.v ? JSON.parse(JSON.stringify(S.L.score_template)) : null;
    e.endless = on.v;       // ranking maps are "endless": ammo and rations can run out
    if (on.v && !Number(e.turn_limit)) e.turn_limit = 8;
    renderEditor();
  } });
  if (!e.score) return card("Ranking map", toggle,
    h("p", { class: "muted small" }, "Turn on to score the map like the ranking events: points for kills, buildings, nodes held at the end and more. " +
      "Ammo and rations can then run out, as on ranking maps."));
  const sc = e.score;
  if (sc.defeat === undefined) sc.defeat = sc.echelon_out || 0;
  const pts = (key, label, help) => field(label, numberInput(sc, key, { min: 0 }), help);
  const pct = (key, label, help) => field(label, h("div", { class: "row" }, numberInput(sc, key, { min: 0, step: "any" }),
    h("span", { class: "muted small" }, "% of its combat effectiveness")), help);
  sc.spots ||= {};
  const spotRows = Object.entries(SCORE_SPOTS).map(([t, label]) => {
    const o = { v: sc.spots[t] || 0 };
    return field(label, numberInput(o, "v", { min: 0, onChange: () => { if (Number(o.v)) sc.spots[t] = Number(o.v); else delete sc.spots[t]; } }));
  });
  return card("Ranking map", toggle,
    h("p", { class: "muted small" }, goals.has(5) ? "The map ends at the turn limit (set under Defeat). Penalties are taken off; the score never goes below 0."
      : "Tip: pick “Score points until the turn limit” under Victory for a map that is played out to its turn limit. Penalties are taken off; the score never goes below 0."),
    h("h4", {}, "Points gained"),
    h("div", { class: "fields" },
      pct("kill_pct", "Enemy defeated", "0 = kills give nothing."),
      pct("npc_kill_pct", "Enemy defeated by an allied force"),
      pts("building", "Enemy building destroyed"),
      pts("crate", "Supply crate picked up"),
      pts("hostage_bar", "Hostage rescued (per HP bar left)"),
      pts("supply", "Echelon resupplied on a supply point", "Not on a Command Post or heliport."),
      pts("repair_point", "Repair on a repair point", "Added on top of the repair penalty.")),
    h("h4", {}, "Points lost"),
    h("div", { class: "fields" },
      pts("withdraw", "Echelon withdrawn from a Command Post or heliport"),
      pts("echelon_out", "Echelon withdrawn anywhere else"),
      pts("defeat", "Echelon defeated (lost a battle)"),
      pts("repair", "Each repair"),
      pts("hoc_withdraw", "HOC withdrawn from a Command Post or heliport"),
      pts("hoc_out", "HOC withdrawn elsewhere, or destroyed"),
      pts("ma_withdraw", "Vehicle withdrawn from a heavy heliport"),
      pts("ma_out", "Vehicle withdrawn elsewhere"),
      pts("ma_defeat", "Vehicle defeated"),
      pts("ma_repair", "Vehicle repaired")),
    h("h4", {}, "Points at the end, for each node held"),
    h("div", { class: "fields" }, ...spotRows),
    h("h4", {}, "Points for map mechanics"),
    pointsList(sc, "skills", "map_skill", "Each use of a map skill", "Map skills come from nodes, buildings and items on the map (a bridge blown up, a radar taken)."),
    pointsList(sc, "buffs", "map_effect", "Each map effect still on the map at the end"),
    pointsList(sc, "specials", "map_marker", "Each map marker still on the map at the end"),
    alliesList(sc));
}

/** id:points pairs, with names and descriptions from a catalog. */
function pointsList(obj, key, kind, label, help) {
  obj[key] ||= [];
  const box = h("div");
  const draw = async () => {
    const all = await catalog(kind);
    const by = Object.fromEntries(all.map(r => [String(r.id), r]));
    box.replaceChildren(...obj[key].map((it, i) => {
      const r = by[String(it.id)] || { name: String(it.id), desc: "" };
      return h("div", { class: "mech" }, h("div", { class: "row" }, h("strong", {}, r.name || r.code || String(it.id)),
          h("span", { class: "muted small" }, String(it.id)), numberInput(it, "points"), h("span", { class: "muted small" }, "points"),
          h("button", { class: "small danger", onclick: () => { obj[key].splice(i, 1); dirty(); draw(); } }, "✕")),
        r.desc ? h("div", { class: "doc" }, r.desc) : null);
    }), h("button", { class: "small", onclick: async () => {
      const id = await pickDialog(kind, label);
      if (id !== null) { obj[key].push({ id: Number(id), points: 10000 }); dirty(); draw(); } } }, "+ Add"));
  };
  draw();
  return field(label, box, help);
}

function alliesList(sc) {
  sc.allies ||= [];
  const box = h("div");
  const draw = async () => {
    const n = await lookupNames("ally_team", sc.allies.map(a => a.team));
    box.replaceChildren(...sc.allies.map((a, i) => h("div", { class: "row mech" }, h("strong", {}, n[a.team] || `Allied force ${a.team}`),
      h("span", { class: "muted small" }, "on the side of"), selectInput(a, "side", BELONGS),
      numberInput(a, "points"), h("span", { class: "muted small" }, "points"),
      h("button", { class: "small danger", onclick: () => { sc.allies.splice(i, 1); dirty(); draw(); } }, "✕"))),
    h("button", { class: "small", onclick: async () => {
      const id = await pickDialog("ally_team", "Allied force");
      if (id !== null) { sc.allies.push({ team: Number(id), side: 1, points: 10000 }); dirty(); draw(); } } }, "+ Add"));
  };
  draw();
  return field("Each allied force still alive at the end", box);
}

function teamSlot(obj, key) {
  const name = h("span", { class: "ref" });
  const show = async () => { const id = obj[key]; if (!id) { name.textContent = "none"; return; } const n = await lookupNames("team", [id]); name.textContent = `${n[id] || ""} · team ${id}`; };
  show();
  return h("div", { class: "row" }, name,
    h("button", { class: "small", onclick: async () => { const id = await pickDialog("team", "Pick an enemy team"); if (id !== null) { obj[key] = Number(id); dirty(); show(); } } }, "Pick…"),
    h("button", { class: "small", onclick: () => obj[key] && openEntity("team", obj[key]) }, "Open"),
    h("button", { class: "small", onclick: () => { obj[key] = 0; dirty(); show(); } }, "None"));
}

// ------------------------------------------------------------------ layout

function newSpotId(e) {
  const used = new Set(e.spots.map(s => String(s.id)));
  while (e._free.length) { const id = e._free.shift(); if (!used.has(String(id))) return id; }
  return Math.max(8000000, ...e.spots.map(s => s.id)) + 1;
}

function spotById(e, id) { return e.spots.find(s => String(s.id) === String(id)); }

function curves(spot) {
  // curve_control: one "x,y" per map_route entry (control point of a curved link; "0,0" = straight)
  const out = {}, cc = String(spot.curve_control || "").split("|");
  ids(spot.map_route || spot.route).forEach((n, i) => { out[n] = cc[i] || "0,0"; });
  return out;
}

function setLinks(spot, list) {
  const keep = curves(spot);
  const sorted = [...list].sort((a, b) => a - b);
  spot.route = list.join(",");
  spot.map_route = sorted.join(",");
  spot.curve_control = sorted.map(n => keep[n] || "0,0").join("|");
}

function toggleLink(e, a, b, twoWay) {
  const A = spotById(e, a), B = spotById(e, b);
  const ra = ids(A.route), rb = ids(B.route);
  if (ra.includes(String(b)) || rb.includes(String(a))) {
    setLinks(A, ra.filter(x => x !== String(b)));
    setLinks(B, rb.filter(x => x !== String(a)));
  } else {
    setLinks(A, [...ra, String(b)]);
    if (twoWay) setLinks(B, [...rb, String(a)]);
  }
  dirty();
}

function frameBox(e) {
  const m = String(e.frame || "").split(";")[0].match(/^(\d+),(\d+)\|(-?\d+),(-?\d+)\|(-?\d+),(-?\d+)$/);
  return m ? { x0: +m[5] - m[3] / 2, x1: +m[5] + m[3] / 2, y0: +m[6] - m[4] / 2, y1: +m[6] + m[4] / 2 } : null;
}

function fitBox(e) {
  let b = frameBox(e);
  for (const s of e.spots) {
    if (!b) b = { x0: s.coordinator_x, x1: s.coordinator_x, y0: s.coordinator_y, y1: s.coordinator_y };
    b = { x0: Math.min(b.x0, s.coordinator_x - 150), x1: Math.max(b.x1, s.coordinator_x + 150),
          y0: Math.min(b.y0, s.coordinator_y - 150), y1: Math.max(b.y1, s.coordinator_y + 150) };
  }
  return b || { x0: -1500, x1: 1500, y0: -1000, y1: 1000 };
}

// ---- undo: snapshots of the nodes and spawns, taken before each change on this tab
const mapState = (e) => JSON.stringify({ spots: e.spots, spawns: e.spawns });
function pushUndo(e) {
  e._undo ||= [];
  const now = mapState(e);
  if (e._undo[e._undo.length - 1] !== now) { e._undo.push(now); if (e._undo.length > 200) e._undo.shift(); e._redo = []; }
}
function stepHistory(e, back) {
  const from = back ? (e._undo ||= []) : (e._redo ||= []), to = back ? (e._redo ||= []) : e._undo;
  const now = mapState(e);
  while (from.length && from[from.length - 1] === now) from.pop();
  if (!from.length) return toast(back ? "Nothing to undo" : "Nothing to redo");
  to.push(now);
  const st = JSON.parse(from.pop());
  e.spots = st.spots; e.spawns = st.spawns;
  S.mapMulti = []; if (!spotById(e, S.mapSel)) S.mapSel = null;
  dirty(); renderEditor();
}

/** Copies of the picked nodes beside them, with the links between them (not their spawns). */
function duplicateNodes(e) {
  const pick = (S.mapMulti || []).length ? S.mapMulti : S.mapSel ? [String(S.mapSel)] : [];
  if (!pick.length) return toast("Click a node first (shift-click to pick several)");
  pushUndo(e);
  const made = new Map();
  for (const id of pick) made.set(String(id), newSpotId(e));
  const k = Math.max(120, e._view.w / 20);
  const copies = [];
  for (const [old, nid] of made) {
    const src = spotById(e, old);
    const copy = Object.assign(JSON.parse(JSON.stringify(src)), { id: nid, coordinator_x: src.coordinator_x + k, coordinator_y: src.coordinator_y - k,
      win: false, route: "", map_route: "", curve_control: "" });
    e.spots.push(copy);
    copies.push([copy, ids(src.route).filter(x => made.has(x)).map(x => String(made.get(x)))]);
  }
  for (const [copy, links] of copies) setLinks(copy, links);
  S.mapMulti = [...made.values()].map(String); S.mapSel = S.mapMulti[0];
  dirty(); renderEditor();
  toast(`${made.size} node${made.size === 1 ? "" : "s"} copied`);
}

function layoutTab(e) {
  S.mapTool ||= "move";
  S.mapMulti ||= [];
  if (S.mapPics === undefined) S.mapPics = true;
  if (!e._view) { const b = fitBox(e); e._view = { cx: (b.x0 + b.x1) / 2, cy: (b.y0 + b.y1) / 2, w: b.x1 - b.x0 + 240 }; }
  const panel = h("div");
  const svg = sv("svg");
  const zoom = (f) => { e._view.w = Math.max(300, Math.min(40000, e._view.w * f)); draw(); };
  const tools = h("div", { class: "map-tools" },
    [["move", "Move / select"], ["link2", "Link (two-way)"], ["link1", "Link (one-way)"], ["add", "Add node"], ["del", "Delete node"]]
      .map(([k, label]) => h("button", { class: "small" + (S.mapTool === k ? " on" : ""), onclick: () => { S.mapTool = k; S.linkFrom = null; renderEditor(); } }, label)),
    h("span", { class: "spacer" }),
    h("button", { class: "small", title: "Undo (Ctrl+Z)", onclick: () => stepHistory(e, true) }, "↶ Undo"),
    h("button", { class: "small", title: "Redo (Ctrl+Y)", onclick: () => stepHistory(e, false) }, "↷ Redo"),
    h("button", { class: "small", title: "Copy the picked nodes (Ctrl+D); shift-click to pick several", onclick: () => duplicateNodes(e) }, "Copy nodes"),
    h("label", { class: "check small" }, (() => { const cb = h("input", { type: "checkbox" }); cb.checked = S.mapPics; cb.addEventListener("change", () => { S.mapPics = cb.checked; draw(); }); return cb; })(), " Pictures"),
    h("button", { class: "small", title: "Zoom in", onclick: () => zoom(1 / 1.3) }, "+"),
    h("button", { class: "small", title: "Zoom out", onclick: () => zoom(1.3) }, "−"),
    h("button", { class: "small", title: "Fit the whole map", onclick: () => { e._view = null; renderEditor(); } }, "Fit"));
  const hint = h("div", { class: "muted small", style: "padding:0 8px 6px" }, {
    move: "Drag nodes to move them, drag empty space to pan, scroll to zoom. Click a node to edit it; shift-click to pick several (to copy or move them together).",
    link2: "Click two nodes to link or unlink them.", link1: "Click the node units leave from, then the one they can reach.",
    add: "Click an empty spot to add a node.", del: "Click a node to remove it." }[S.mapTool]);
  const legend = h("div", { class: "legend" }, h("span", { style: "color:var(--griffin)" }, "Griffin"), h("span", { style: "color:var(--enemy)" }, "Enemy"),
    h("span", { style: "color:var(--neutral)" }, "Neutral"), h("span", { style: "color:var(--third)" }, "win node (ring)"),
    h("span", { class: "muted" }, "■ HQ  ◆ heliport  ● node  · red dot = enemy team · blue dot = allied force · ⌂ = building · ✚ = hostage · ↻ = spawn point · dashed = one-way"));
  const draw = () => drawMap(e, svg);
  draw();
  let drag = null, pan = null, moved = false, dragFrom = null;
  const toXY = (ev) => { const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY; const p = pt.matrixTransform(svg.getScreenCTM().inverse()); return [Math.round(p.x), Math.round(-p.y)]; };
  svg.addEventListener("wheel", ev => { ev.preventDefault(); zoom(ev.deltaY > 0 ? 1.15 : 1 / 1.15); }, { passive: false });
  svg.addEventListener("pointerdown", ev => {
    const id = ev.target.closest("[data-spot]")?.dataset.spot;
    const tool = S.mapTool;
    if (tool === "add" && !id) {
      pushUndo(e);
      const [x, y] = toXY(ev);
      const nid = newSpotId(e);
      e.spots.push({ id: nid, mission_id: e.id, type: 2, belong: 3, coordinator_x: x, coordinator_y: y, route: "", map_route: "",
                     curve_control: "", map_type: 2, map_code: "road", random_get: "0", durability: "0", enemy_team_id: 0, win: false });
      S.mapSel = nid; dirty(); renderEditor();
      return;
    }
    if (!id) {
      if (tool === "move") { pan = { x: ev.clientX, y: ev.clientY, cx: e._view.cx, cy: e._view.cy }; svg.setPointerCapture(ev.pointerId); }
      S.mapSel = null; S.linkFrom = null; S.mapMulti = []; draw(); renderPanel();
      return;
    }
    if (tool === "del") {
      pushUndo(e);
      e.spots = e.spots.filter(s => String(s.id) !== id);
      for (const s of e.spots) setLinks(s, ids(s.route).filter(x => x !== id));
      for (const r of e.spawns) setRuleSpots(r, ruleSpots(r).filter(x => x !== id));
      e.spawns = e.spawns.filter(r => ruleSpots(r).length);
      S.mapSel = null; dirty(); renderEditor();
      return;
    }
    if (tool === "link1" || tool === "link2") {
      if (!S.linkFrom) { S.linkFrom = id; S.mapSel = id; }
      else if (S.linkFrom !== id) { pushUndo(e); toggleLink(e, S.linkFrom, id, tool === "link2"); S.linkFrom = null; S.mapSel = id; }
      draw(); renderPanel();
      return;
    }
    if (ev.shiftKey) {
      const set = new Set(S.mapMulti.length ? S.mapMulti : S.mapSel ? [String(S.mapSel)] : []);
      set.has(id) ? set.delete(id) : set.add(id);
      S.mapMulti = [...set]; S.mapSel = id;
      draw(); renderPanel();
      return;
    }
    if (!S.mapMulti.includes(id)) S.mapMulti = [];
    S.mapSel = id; drag = id; moved = false;
    const [sx, sy] = toXY(ev);
    dragFrom = { x: sx, y: sy, at: Object.fromEntries((S.mapMulti.length ? S.mapMulti : [id]).map(n => { const sp = spotById(e, n); return [n, [sp.coordinator_x, sp.coordinator_y]]; })) };
    svg.setPointerCapture(ev.pointerId);
    draw(); renderPanel();
  });
  svg.addEventListener("pointermove", ev => {
    if (pan) {
      const scale = e._view.w / svg.clientWidth;
      e._view.cx = pan.cx - (ev.clientX - pan.x) * scale;
      e._view.cy = pan.cy + (ev.clientY - pan.y) * scale;
      draw();
      return;
    }
    if (!drag) return;
    const [x, y] = toXY(ev);
    const dx = x - dragFrom.x, dy = y - dragFrom.y;
    if (!dx && !dy) return;
    if (!moved) pushUndo(e);
    for (const [n, [ox, oy]] of Object.entries(dragFrom.at)) { const sp = spotById(e, n); if (sp) { sp.coordinator_x = ox + dx; sp.coordinator_y = oy + dy; } }
    moved = true; dirty(); draw();
  });
  svg.addEventListener("pointerup", () => { if (drag && moved) renderPanel(); drag = null; pan = null; });
  const renderPanel = () => panel.replaceChildren(nodePanel(e, draw));
  // an edit in the node panel can be undone too
  panel.addEventListener("pointerdown", () => pushUndo(e), true);
  panel.addEventListener("keydown", () => pushUndo(e), true);
  window._layoutKeys ||= (window.addEventListener("keydown", ev => {
    const ent = S.ent;
    if (!ent || ent.kind !== "map" || S.mapTab !== "layout" || !(ev.ctrlKey || ev.metaKey)) return;
    if (ev.target.closest && ev.target.closest("input, textarea, select")) return;
    const k = ev.key.toLowerCase();
    if (k === "z" && !ev.shiftKey) { ev.preventDefault(); stepHistory(ent, true); }
    else if (k === "y" || (k === "z" && ev.shiftKey)) { ev.preventDefault(); stepHistory(ent, false); }
    else if (k === "d") { ev.preventDefault(); duplicateNodes(ent); }
  }), true);
  renderPanel();
  return h("div", {}, h("div", { class: "map-wrap" }, h("div", { class: "map-canvas" }, tools, hint, svg, legend), panel));
}

function drawMap(e, svg) {
  const v = e._view;
  const ratio = (svg.clientHeight || 620) / (svg.clientWidth || 900);
  const hgt = v.w * ratio;
  svg.setAttribute("viewBox", `${v.cx - v.w / 2} ${-(v.cy + hgt / 2)} ${v.w} ${hgt}`);
  svg.replaceChildren();
  const k = Math.max(0.5, v.w / 3200);
  const fb = frameBox(e);
  if (fb) svg.append(sv("rect", { x: fb.x0, y: -fb.y1, width: fb.x1 - fb.x0, height: fb.y1 - fb.y0, fill: "none",
                                  stroke: "currentColor", "stroke-opacity": .25, "stroke-dasharray": `${20 * k} ${14 * k}`, "stroke-width": 4 * k }));
  const done = new Set();
  for (const s of e.spots) {
    for (const t of ids(s.route)) {
      const o = spotById(e, t);
      if (!o) continue;
      const key = [s.id, o.id].sort().join("-");
      const twoWay = ids(o.route).includes(String(s.id));
      if (twoWay && done.has(key)) continue;
      done.add(key);
      const cv = (curves(s)[String(o.id)] || "0,0").split(",").map(Number);
      const curved = cv.length === 2 && (cv[0] || cv[1]);
      const line = sv("path", { d: curved ? `M${s.coordinator_x},${-s.coordinator_y} Q${cv[0]},${-cv[1]} ${o.coordinator_x},${-o.coordinator_y}`
                                          : `M${s.coordinator_x},${-s.coordinator_y} L${o.coordinator_x},${-o.coordinator_y}`,
                                fill: "none", stroke: "currentColor", "stroke-opacity": .45, "stroke-width": 9 * k });
      if (!twoWay) {
        line.setAttribute("stroke-dasharray", `${26 * k} ${16 * k}`);
        const ax = s.coordinator_x + (o.coordinator_x - s.coordinator_x) * .7, ay = s.coordinator_y + (o.coordinator_y - s.coordinator_y) * .7;
        const ang = Math.atan2(-(o.coordinator_y - s.coordinator_y), o.coordinator_x - s.coordinator_x);
        const p = (d, a) => `${ax + d * Math.cos(ang + a)},${-ay + d * Math.sin(ang + a)}`;
        svg.append(sv("polygon", { points: `${p(30 * k, 0)} ${p(30 * k, 2.5)} ${p(30 * k, -2.5)}`, fill: "currentColor", "fill-opacity": .6 }));
      }
      svg.prepend(line);
    }
  }
  const color = { 1: "var(--griffin)", 2: "var(--enemy)", 3: "var(--neutral)" };
  for (const s of e.spots) {
    const g = sv("g", { "data-spot": s.id, style: "cursor:pointer" });
    const x = s.coordinator_x, y = -s.coordinator_y, c = color[s.belong] || "var(--muted)";
    const sel = String(S.mapSel) === String(s.id) || String(S.linkFrom) === String(s.id) || (S.mapMulti || []).includes(String(s.id));
    if (s.win) g.append(sv("circle", { cx: x, cy: y, r: 74 * k, fill: "none", stroke: "var(--third)", "stroke-width": 12 * k }));
    let shape;
    if (s.type === 1) shape = sv("rect", { x: x - 52 * k, y: y - 52 * k, width: 104 * k, height: 104 * k, rx: 10 * k });
    else if (s.type === 3 || s.type === 7) shape = sv("polygon", { points: `${x},${y - 62 * k} ${x + 62 * k},${y} ${x},${y + 62 * k} ${x - 62 * k},${y}` });
    else shape = sv("circle", { cx: x, cy: y, r: 46 * k });
    shape.setAttribute("fill", c);
    shape.setAttribute("stroke", sel ? "var(--text)" : "var(--panel)");
    shape.setAttribute("stroke-width", (sel ? 14 : 8) * k);
    g.append(shape);
    const letter = { 1: "HQ", 3: "H", 7: "HH", 5: "S", 6: "R", 8: "+" }[s.type] || (String(s.random_get) === "1" ? "?" : "");
    if (letter) { const t = sv("text", { x, y: y + 16 * k, "text-anchor": "middle", "font-size": 44 * k, fill: "#fff", "pointer-events": "none", "font-weight": 700 }); t.textContent = letter; g.append(t); }
    if (Number(s.enemy_team_id)) g.append(sv("circle", { cx: x + 46 * k, cy: y - 46 * k, r: 24 * k, fill: "var(--enemy)", stroke: "var(--panel)", "stroke-width": 6 * k }));
    if (Number(s.ally_team_id)) g.append(sv("circle", { cx: x - 46 * k, cy: y - 46 * k, r: 24 * k, fill: "var(--griffin)", stroke: "var(--panel)", "stroke-width": 6 * k }));
    const mark = (txt, dx, col) => { const t = sv("text", { x: x + dx * k, y: y + 64 * k, "text-anchor": "middle", "font-size": 40 * k, fill: col, "pointer-events": "none", "font-weight": 700 }); t.textContent = txt; g.append(t); };
    if (Number(s.building_id)) mark("⌂", 56, "var(--third)");
    if (Number(String(s.hostage_info || "").split(",")[0])) mark("✚", -56, "var(--griffin)");
    if (S.mapPics) {
      const pic = (kind, id, px, py, size) => g.append(sv("image", { href: `/api/picture?kind=${kind}&id=${id}`, x: px - size / 2, y: py - size, width: size, height: size,
        "pointer-events": "none", preserveAspectRatio: "xMidYMax meet", onerror: "this.remove()" }));
      if (Number(s.building_id)) pic("building", s.building_id, x + 90 * k, y - 30 * k, 110 * k);
      if (Number(s.ally_team_id)) pic("ally", s.ally_team_id, x - 70 * k, y - 40 * k, 150 * k);
      if (Number(s.enemy_team_id)) pic("team", s.enemy_team_id, x + 20 * k, y - 40 * k, 160 * k);
    }
    if (e.spawns.some(r => ruleSpots(r).includes(String(s.id)))) { const t = sv("text", { x: x - 70 * k, y: y - 50 * k, "font-size": 40 * k, fill: "var(--enemy)", "pointer-events": "none" }); t.textContent = "↻"; g.append(t); }
    const label = sv("text", { x, y: y + 96 * k, "text-anchor": "middle", "font-size": 34 * k, fill: "currentColor", "fill-opacity": .7, "pointer-events": "none" });
    label.textContent = s.id;
    g.append(label);
    svg.append(g);
  }
}

function nodePanel(e, redraw) {
  const s = spotById(e, S.mapSel);
  if (!s) return card("Nodes", h("p", { class: "muted" }, `${e.spots.length} nodes. Click one to edit it.`),
    h("p", { class: "muted small" }, "Start with a Griffin Command Post or heliport, an enemy Command Post, and nodes linked between them."));
  const enemyName = h("span", { class: "ref" });
  const showEnemy = async () => { const id = Number(s.enemy_team_id); if (!id) { enemyName.textContent = "none"; return; } const n = await lookupNames("team", [id]); enemyName.textContent = `${n[id] || ""} · team ${id}`; };
  showEnemy();
  const rnd = { v: String(s.random_get) === "1" };
  const radar = { v: Number(s.special_eft) === 1 };
  return card(`Node ${s.id}`, h("div", { class: "fields one" },
    field("Kind", selectInput(s, "type", SPOT_TYPES, { onChange: redraw })),
    field("Held by", selectInput(s, "belong", BELONGS, { onChange: redraw })),
    field("Enemy team standing here", h("div", { class: "row" }, enemyName,
      h("button", { class: "small", onclick: async () => { const id = await pickDialog("team", "Enemy team on this node"); if (id !== null) { s.enemy_team_id = Number(id); dirty(); showEnemy(); redraw(); } } }, "Pick…"),
      h("button", { class: "small", onclick: () => s.enemy_team_id && openEntity("team", s.enemy_team_id) }, "Open"),
      h("button", { class: "small", onclick: () => { s.enemy_team_id = 0; dirty(); showEnemy(); redraw(); } }, "None"))),
    checkbox(s, "win", "Win node", { onChange: redraw }),
    checkbox(rnd, "v", "Random node (event)", { onChange: () => { s.random_get = rnd.v ? "1" : "0"; redraw(); } }),
    checkbox(radar, "v", "Radar node", { onChange: () => { s.special_eft = radar.v ? 1 : 0; } }),
    field("Battle background", selectInput(s, "map_type", MAP_TYPES, { onChange: () => { if (MAP_CODES[s.map_type]) s.map_code = MAP_CODES[s.map_type]; } }))),
    h("p", { class: "muted small" }, ids(s.route).length ? `Links to ${ids(s.route).join(", ")}` : "No links yet: use a Link tool."),
    nodeMechanics(e, s, redraw));
}

/** One picked row (building, allied force, doll) with its name and description. */
function refSlot(obj, key, kind, title, onChange) {
  const box = h("div");
  const draw = async () => {
    const id = Number(obj[key]) || 0;
    let name = "none", desc = "";
    if (id) {
      if (kind === "gun") { const n = await lookupNames("gun", [id]); name = `${n[id] || "T-Doll"} · ${id}`; }
      else { const it = (await catalog(kind)).find(r => String(r.id) === String(id)); name = it ? `${it.name || it.code} · ${id}` : String(id); desc = (it || {}).desc || ""; }
    }
    box.replaceChildren(h("div", { class: "row" }, h("span", { class: "ref" }, name),
      h("button", { class: "small", onclick: async () => { const x = await pickDialog(kind, title); if (x !== null) { obj[key] = Number(x); dirty(); draw(); onChange && onChange(); } } }, "Pick…"),
      id ? h("button", { class: "small", onclick: () => { obj[key] = 0; dirty(); draw(); onChange && onChange(); } }, "None") : null),
      desc ? h("div", { class: "doc" }, desc) : "");
  };
  draw();
  return box;
}

/** Mechanics a node can carry (buildings, allied forces, hostages, ...); the server plays them (gfserver/missions.py). */
function nodeMechanics(e, s, redraw) {
  const heli = isHeliport(s);
  const cycle = String(s.active_cycle || "").split(",").map(Number);
  const cyc = { on: heli && cycle.length === 2 && cycle[0] > 0 && cycle[0] < 99, open: cycle[0] > 0 && cycle[0] < 99 ? cycle[0] : 3, closed: cycle[1] || 1 };
  const writeCycle = () => { s.active_cycle = cyc.on ? `${Math.max(1, cyc.open)},${Math.max(1, cyc.closed)}` : (heli ? "99,1" : ""); dirty(); };
  const [hgun, hhp] = String(s.hostage_info || "").split(",");
  const host = { on: !!Number(hgun), gun: Number(hgun) || 0, hp: Number(hhp) || 5 };
  const writeHost = () => { s.hostage_info = host.on && host.gun ? `${host.gun},${Math.max(1, host.hp)}` : ""; dirty(); };
  const dur = String(s.durability || "").split(",");
  const rep = { on: Number(s.type) === 8 && dur.length === 2 && Number(dur[1]) < 99, n: Number(dur[1]) < 99 ? Number(dur[1]) : 5 };
  const writeRep = () => { s.durability = rep.on ? `0,${Math.max(1, rep.n)}` : "0"; dirty(); };
  const any = Number(s.building_id) || Number(s.ally_team_id) || host.on || cyc.on || rep.on;
  return h("details", { class: "card inner", open: !!any }, h("summary", {}, "Mechanics"),
    h("div", { class: "fields one" },
      field("Building", refSlot(s, "building_id", "building", "Building on this node", redraw),
        "Turrets, radars, bridges, control panels: buildings act on their own (skills each turn, on capture or when destroyed)."),
      field("Allied force", refSlot(s, "ally_team_id", "ally_team", "Allied force on this node", () => { if (!Number(s.ally_team_id)) delete s.ally_side; redraw(); renderEditor(); }),
        "A force of its own (other Griffin units, a third party) that starts here and moves by itself."),
      Number(s.ally_team_id) ? field("It fights", forceSide(s, "ally_side", s.ally_team_id),
        "With you: it hunts enemies. With the enemy: it hunts your echelons. Third party: it attacks everyone.") : null,
      checkbox(host, "on", "Hostage to rescue here", { onChange: async () => {
        if (host.on && !host.gun) {
          const id = await pickDialog("gun", "Which T-Doll is the hostage?");
          if (id === null) { host.on = false; renderEditor(); return; }
          host.gun = Number(id);
        }
        writeHost(); renderEditor();
      } }),
      host.on ? field("Hostage (who, HP bars)", h("div", {}, refSlot(host, "gun", "gun", "Which T-Doll is the hostage?", writeHost),
        h("div", { class: "row" }, numberInput(host, "hp", { min: 1, onChange: writeHost }), h("span", { class: "muted small" }, "HP bars"))),
        "Bring the hostage to a Command Post or heliport. Add “Rescue hostages” goals or ranking points for it.") : null,
      heli ? checkbox(cyc, "on", "Opens and closes in turns", { onChange: () => { writeCycle(); renderEditor(); } }) : null,
      heli && cyc.on ? field("Open / closed", h("div", { class: "row" }, numberInput(cyc, "open", { min: 1, onChange: writeCycle }), h("span", { class: "muted small" }, "turns open, then"),
        numberInput(cyc, "closed", { min: 1, onChange: writeCycle }), h("span", { class: "muted small" }, "closed")), "Nothing spawns here while it is closed.") : null,
      Number(s.type) === 8 ? checkbox(rep, "on", "Limited repairs", { onChange: () => { writeRep(); renderEditor(); } }) : null,
      Number(s.type) === 8 && rep.on ? field("Repairs", numberInput(rep, "n", { min: 1, onChange: writeRep }), "After these, it becomes a normal node.") : null));
}

// ------------------------------------------------------------------ spawns

// Spawns are a list of rules (gfserver/missions.py _spawn). Plain ones (teams by weight on some nodes over a
// run of turns) are shown as a table like the ranking guides': turns down, heliports across. Rules with
// conditions or limits are "special spawns", listed under it.
const PLAIN_KEYS = new Set(["spot", "spots", "teams", "from_turn", "to_turn", "every", "chance", "max", "enemy_owned", "start"]);
const isPlain = (r) => Object.keys(r).every(k => PLAIN_KEYS.has(k)) && !Number(r.max) && r.enemy_owned !== false
  && (r.start || Number(r.every || 1) === 1 || Number(r.to_turn) > 0);

/** The table's turn rows: 1..rows, then (with no turn limit) an open "and later" row. */
function spawnShape(e) {
  const limit = Number(e.turn_limit) || 0;
  let rows = limit;
  if (!limit) {
    rows = Math.max(3, e._spawnRows || 0);
    for (const r of e.spawns.filter(isPlain)) if (!r.start) rows = Math.max(rows, Number(r.to_turn) || 0, (Number(r.from_turn) || 1) - (Number(r.to_turn) ? 0 : 1));
    e._spawnRows = rows;
  }
  return { rows, open: !limit };
}

/** cells[spot][turn] = list of {chance, teams}; turn is a number, "start" or "later". */
function spawnCells(e, shape) {
  const cells = {};
  const put = (sid, t, r) => ((cells[sid] ||= {})[t] ||= []).push({ chance: Number(r.chance ?? 100), teams: (r.teams || []).map(x => ({ team: Number(x.team), weight: Number(x.weight ?? 1) })) });
  for (const r of e.spawns.filter(isPlain)) {
    for (const sid of ruleSpots(r)) {
      if (r.start) { put(sid, "start", r); continue; }
      const from = Number(r.from_turn) || 1, to = Number(r.to_turn) || 0, every = Number(r.every) || 1;
      const last = to ? Math.min(to, shape.rows) : shape.rows;
      for (let t = from; t <= last; t += every) put(sid, t, r);
      if (!to && shape.open) put(sid, "later", r);
    }
  }
  return cells;
}

/** Back to rules: equal cells on following turns become one rule, equal runs on several nodes share it. */
function compileCells(e, cells, shape) {
  const runs = [];
  const key = (v) => JSON.stringify(v || []);
  for (const [sid, byTurn] of Object.entries(cells)) {
    if ((byTurn.start || []).length) runs.push({ sid, start: true, v: byTurn.start });
    let t = 1;
    while (t <= shape.rows) {
      const v = byTurn[t];
      if (!v || !v.length) { t++; continue; }
      let u = t;
      while (u + 1 <= shape.rows && key(byTurn[u + 1]) === key(v)) u++;
      const open = u === shape.rows && (shape.open ? key(byTurn.later) === key(v) : true);
      runs.push({ sid, from: t, to: open ? 0 : u, v });
      t = u + 1;
    }
    if (shape.open && (byTurn.later || []).length && key(byTurn[shape.rows]) !== key(byTurn.later))
      runs.push({ sid, from: shape.rows + 1, to: 0, v: byTurn.later });
  }
  const groups = new Map();
  for (const r of runs) {
    const k = key([r.start, r.from, r.to, r.v]);
    if (!groups.has(k)) groups.set(k, { ...r, sids: [] });
    groups.get(k).sids.push(r.sid);
  }
  const out = [];
  for (const g of groups.values()) {
    for (const entry of g.v) {
      const rule = g.start ? { spot: 0, teams: entry.teams, start: true, chance: entry.chance }
        : { spot: 0, teams: entry.teams, from_turn: g.from, to_turn: g.to, every: 1, chance: entry.chance, max: 0, enemy_owned: true };
      setRuleSpots(rule, g.sids);
      out.push(rule);
    }
  }
  return out;
}

function writeCells(e, cells, shape) {
  e.spawns = [...e.spawns.filter(r => !isPlain(r)), ...compileCells(e, cells, shape)];
  dirty();
}

function spawnsTab(e, embedded = false) {
  // embedded: inside another card (mapconfig.js), without its own frame and intro
  e.spawns ||= [];
  const nodes = {};
  for (const s of e.spots) nodes[s.id] = `${s.id} · ${SPOT_TYPES[s.type] || "Node"} (${BELONGS[s.belong] || ""})`;
  const shape = spawnShape(e), cells = spawnCells(e, shape);
  const cols = e.spots.filter(s => isHeliport(s) || cells[s.id]).sort((x, y) => (Number(y.belong) === 2) - (Number(x.belong) === 2) || x.id - y.id);
  const turns = ["start", ...Array.from({ length: shape.rows }, (_, i) => i + 1), ...(shape.open ? ["later"] : [])];
  const rowName = (t) => t === "start" ? "Mission start" : t === "later" ? `Turn ${shape.rows + 1} and later` : `Turn ${t}`;
  const table = h("table", { class: "grid spawn-table" });
  const draw = async () => {
    const ids = [...new Set(Object.values(cells).flatMap(c => Object.values(c).flat().flatMap(x => x.teams.map(t => t.team))))];
    const names = ids.length ? await lookupNames("team", ids) : {};
    table.replaceChildren(
      h("thead", {}, h("tr", {}, h("th", {}, ""), ...cols.map(s => h("th", { title: nodes[s.id] }, `${SPOT_TYPES[s.type] || "Node"} ${s.id}`,
        h("div", { class: "muted small" }, BELONGS[s.belong] || ""),
        h("button", { class: "small", title: "Give other heliports the same spawns", onclick: () => copyDialog(e, nodes, s.id) }, "Copy to…"))))),
      h("tbody", {}, ...turns.map(t => h("tr", {}, h("th", {}, rowName(t)), ...cols.map(s => {
        const list = (cells[s.id] || {})[t] || [];
        return h("td", { class: "cell" + (list.length ? " filled" : ""), title: "Click to change", onclick: () => cellDialog(e, cells, shape, s.id, t, nodes, cols, turns, rowName) },
          ...list.map(x => spawnChances(x, names)));
      })))));
  };
  draw();
  const special = e.spawns.map((r, i) => [r, i]).filter(([r]) => !isPlain(r));
  return (embedded ? (...kids) => h("div", {}, ...kids) : (...kids) => card("Enemy spawns", ...kids))(
    embedded ? null : h("p", { class: "muted small" }, "Enemies that start on the map are set on the nodes (Layout tab). This table adds more: click a square to choose which teams can appear on that heliport on that turn, and how likely. ",
      "Enemies appear at the start of the enemy turn, on an empty heliport the enemy holds."),
    cols.length ? h("div", { class: "tablewrap" }, table) : h("p", { class: "muted" }, "This map has no heliports yet (Layout tab)."),
    shape.open ? h("div", { class: "row" },
      h("button", { class: "small", onclick: () => { e._spawnRows = shape.rows + 1; renderEditor(); } }, "+ Turn row"),
      shape.rows > 1 ? h("button", { class: "small", onclick: () => { e._spawnRows = shape.rows - 1; const c = spawnCells(e, shape); writeCells(e, c, { rows: shape.rows - 1, open: true }); renderEditor(); } }, "− Turn row") : null,
      h("span", { class: "muted small" }, "With a turn limit (Settings, Defeat) the table has one row per turn.")) : null,
    h("h4", {}, "Special spawns"),
    h("p", { class: "muted small" }, "Spawns with conditions or limits, like the ranking maps' bosses: only after a team is defeated, only once, one random heliport out of several, and so on. They are tried before the table. ",
      "Enemies can also appear straight on chosen nodes once a condition is met. ",
      "Allied force spawns add another faction: Griffin reinforcements, the enemy's allies or a third party that fights everyone."),
    special.length ? h("div", { class: "tablewrap" }, h("table", { class: "grid spawns" },
      h("tr", {}, ...["Nodes", "When", "Chance %", "At most", "Teams (weight)", "Only if", ""].map(x => h("th", {}, x))),
      ...special.map(([r, i]) => spawnRow(e, r, i, nodes)))) : h("p", { class: "muted small" }, "None."),
    h("div", { class: "row" },
      h("button", { class: "small", onclick: () => {
        const helis = e.spots.filter(s => isHeliport(s) && Number(s.belong) === 2).map(s => s.id);
        const rule = { spot: 0, teams: [], from_turn: 1, to_turn: 0, every: 1, chance: 100, max: 1, enemy_owned: true };
        setRuleSpots(rule, helis.slice(0, 1));
        e.spawns.unshift(rule); dirty(); renderEditor();
      } }, "+ Special spawn"),
      h("button", { class: "small", title: "Enemies that appear on chosen nodes (not heliports) once a condition is met, as on many ranking maps", onclick: () => {
        const rule = { spot: 0, teams: [], from_turn: 1, to_turn: 0, every: 1, chance: 100, max: 1, enemy_owned: false, not_ours: true };
        e.spawns.unshift(rule); dirty(); renderEditor();
      } }, "+ Enemies appear on the map"),
      h("button", { class: "small", title: "Another force (Griffin, the enemy's or a third party) that appears during the mission", onclick: () => {
        const helis = e.spots.filter(isHeliport).map(s => s.id);
        const rule = { spot: 0, teams: [], from_turn: 1, to_turn: 0, every: 1, chance: 100, max: 1 };
        setRuleSpots(rule, helis.slice(0, 1));
        e.spawns.unshift(rule);
        setAllyRule(e, rule, true);
      } }, "+ Allied force spawn")));
}

/** A cell's teams with the chance each has of appearing. */
function spawnChances(x, names) {
  const sum = x.teams.reduce((a, t) => a + Math.max(0, t.weight), 0) || 1;
  return h("div", { class: "chances" }, ...x.teams.map(t => {
    const pct = Math.round(x.chance * Math.max(0, t.weight) / sum * 10) / 10;
    return h("div", {}, h("span", {}, names[t.team] || `Team ${t.team}`), h("span", { class: "muted small" }, ` ${t.team} · ${pct}%`));
  }), x.teams.length ? null : h("div", { class: "muted small" }, "no team"));
}

function cellDialog(e, cells, shape, sid, turn, nodes, cols, turns, rowName) {
  const cur = JSON.parse(JSON.stringify(((cells[sid] || {})[turn] || [])[0] || { chance: 100, teams: [] }));
  const extra = ((cells[sid] || {})[turn] || []).slice(1);
  const teams = h("div");
  const drawTeams = async () => {
    const names = await lookupNames("team", cur.teams.map(t => t.team));
    const sum = cur.teams.reduce((a, t) => a + Math.max(0, Number(t.weight) || 0), 0) || 1;
    teams.replaceChildren(...cur.teams.map((t, j) => h("div", { class: "row" }, h("strong", {}, names[t.team] || `Team ${t.team}`),
      h("span", { class: "muted small" }, `team ${t.team}`), h("span", { class: "muted small" }, "weight"),
      numberInput(t, "weight", { min: 0, step: "any", onChange: drawPct }), h("span", { class: "muted small pct", "data-i": j }, `${Math.round(cur.chance * (Number(t.weight) || 0) / sum * 10) / 10}%`),
      h("button", { class: "small", onclick: () => openEntity("team", t.team) }, "Open"),
      h("button", { class: "small danger", onclick: () => { cur.teams.splice(j, 1); drawTeams(); } }, "✕"))),
      h("div", { class: "row" },
        h("button", { class: "small", onclick: async () => { const id = await pickDialog("team", "Which enemy team can appear?"); if (id !== null) { cur.teams.push({ team: Number(id), weight: 1 }); drawTeams(); } } }, "+ Team"),
        h("button", { class: "small", title: "Every team that starts on this map, equally likely", onclick: () => {
          const have = new Set(cur.teams.map(t => Number(t.team)));
          const pool = e.map_teams || [...new Set(e.spots.map(s => Number(s.enemy_team_id || 0)).filter(Boolean))];
          for (const t of pool) if (!have.has(Number(t))) cur.teams.push({ team: Number(t), weight: 1 });
          drawTeams();
        } }, "+ This map's teams")));
  };
  const drawPct = () => {         // only the shares, so the box being typed in keeps focus
    const sum = cur.teams.reduce((a, t) => a + Math.max(0, Number(t.weight) || 0), 0) || 1;
    teams.querySelectorAll(".pct").forEach(el => { const t = cur.teams[Number(el.dataset.i)]; if (t) el.textContent = `${Math.round(cur.chance * (Number(t.weight) || 0) / sum * 10) / 10}%`; });
  };
  drawTeams();
  // where else the same applies
  const numTurns = turns.filter(t => typeof t === "number");
  const fromSel = h("select", {}, ...turns.filter(t => t !== "start").map(t => h("option", { value: t }, rowName(t))));
  const toSel = h("select", {}, ...turns.filter(t => t !== "start").map(t => h("option", { value: t }, rowName(t))));
  fromSel.value = toSel.value = String(turn);
  const spotTicks = cols.map(s => { const cb = h("input", { type: "checkbox" }); cb.checked = String(s.id) === String(sid); cb.dataset.id = s.id; return [s, cb]; });
  const order = (t) => t === "later" ? 1e9 : Number(t);
  const targets = () => {
    const ts = turn === "start" ? ["start"] : turns.filter(t => t !== "start" && order(t) >= order(fromSel.value) && order(t) <= order(toSel.value));
    const ss = spotTicks.filter(([, cb]) => cb.checked).map(([s]) => String(s.id));
    return [ts, ss];
  };
  const apply = (value) => {
    const [ts, ss] = targets();
    for (const s of ss) for (const t of ts) {
      (cells[s] ||= {})[t] = value ? [JSON.parse(JSON.stringify(value)), ...(String(s) === String(sid) && t === turn ? extra : [])] : [];
    }
    writeCells(e, cells, shape);
    close(); renderEditor();
  };
  let close;
  close = openDialog(h("h3", {}, `${nodes[sid] || sid} · ${rowName(turn)}`),
    field("Chance that an enemy appears", h("div", { class: "row" }, numberInput(cur, "chance", { min: 0, max: 100, step: "any", onChange: drawPct }), h("span", { class: "muted small" }, "%")),
      "Rolled each time; the team is then picked by weight."),
    field("Teams", teams),
    turn === "start" ? null : field("Same on turns", h("div", { class: "row" }, fromSel, h("span", {}, "to"), toSel)),
    field("Same on", h("div", { class: "row wrap" }, ...spotTicks.map(([s, cb]) => h("label", { class: "check pill" }, cb, ` ${SPOT_TYPES[s.type] || "Node"} ${s.id}`)))),
    extra.length ? h("p", { class: "muted small" }, `This square also has ${extra.length} more spawn roll(s), kept as they are.`) : null,
    h("div", { class: "row" },
      h("button", { class: "primary", onclick: () => apply(cur.teams.length ? cur : null) }, "OK"),
      h("button", { class: "danger", onclick: () => apply(null) }, "Empty these squares"),
      h("button", { title: "Move this square to the special spawns, to add conditions or a limit", onclick: () => {
        const [ts, ss] = targets();
        const nums = ts.filter(t => typeof t === "number");
        const rule = turn === "start" ? { spot: 0, teams: cur.teams, start: true, chance: cur.chance, max: 1 }
          : { spot: 0, teams: cur.teams, from_turn: nums.length ? Math.min(...nums) : shape.rows + 1, to_turn: ts.includes("later") ? 0 : Math.max(...nums), every: 1, chance: cur.chance, max: 1, enemy_owned: true };
        setRuleSpots(rule, ss);
        for (const s of ss) for (const t of ts) (cells[s] ||= {})[t] = [];
        writeCells(e, cells, shape);
        e.spawns.unshift(rule); close(); renderEditor();
      } }, "Make it a special spawn…"),
      h("button", { onclick: () => close() }, "Cancel")));
}

async function allyNames(ids) {
  const list = await catalog("ally_team");
  return Object.fromEntries(ids.map(id => [id, ((list.find(x => String(x.id) === String(id)) || {}).name) || ""]));
}

/** Switch a special spawn between an enemy team and an allied force (gfserver/missions.py _spawn_allies). */
function setAllyRule(e, r, ally) {
  r.teams = [];
  for (const k of [...Object.keys(SPAWN_CONDITIONS), "queue", "enemy_owned", "start", "ally", "owner", "side"]) delete r[k];
  if (ally) {
    const first = e.spots.find(s => String(s.id) === String(r.spot || (r.spots || [])[0]));
    Object.assign(r, { ally: true, owner: first ? Number(first.belong) : 0 });
  } else r.enemy_owned = true;
  dirty(); renderEditor();
}

function spawnRow(e, r, i, nodes) {
  const ally = !!r.ally;
  const who = h("select", {}, h("option", { value: "enemy" }, "Enemy team"), h("option", { value: "ally" }, "Allied force"));
  who.value = ally ? "ally" : "enemy";
  who.addEventListener("change", () => setAllyRule(e, r, who.value === "ally"));
  const kind = h("select", {}, h("option", { value: "turns" }, "Enemy turns"), ...(ally ? [] : [h("option", { value: "start" }, "Mission start")]));
  kind.value = r.start ? "start" : "turns";
  kind.addEventListener("change", () => { if (kind.value === "start") r.start = true; else delete r.start; dirty(); renderEditor(); });
  const when = h("div", {}, kind, ...(r.start ? [] : [
    h("div", { class: "row small" }, "from", numberInput(r, "from_turn", { min: 1 }), "to", numberInput(r, "to_turn", { min: 0 })),
    h("div", { class: "row small" }, "every", numberInput(r, "every", { min: 1 }), "turn(s)"),
    h("div", { class: "muted small" }, "to 0 = to the end")]));
  const teams = h("div", { class: "teams" });
  const drawTeams = async () => {
    if (ally) {
      const names = await allyNames(r.teams.map(t => t.team));
      teams.replaceChildren(...r.teams.map((t, j) => h("span", { class: "pill", title: names[t.team] || "" }, `${t.team}${names[t.team] ? " " + names[t.team] : ""} ×`,
        numberInput(t, "weight", { min: 0, step: "any" }), h("button", { class: "small", title: "Take this force out", onclick: () => { r.teams.splice(j, 1); dirty(); renderEditor(); } }, "✕"))),
        h("button", { class: "small", onclick: async () => { const id = await pickDialog("ally_team", "Which allied force appears?"); if (id !== null) { r.teams.push({ team: Number(id), weight: 1 }); dirty(); renderEditor(); } } }, "+ Force"),
        ...(r.teams.length ? [] : [h("span", { class: "muted small" }, "No force yet: nothing appears.")]));
      return;
    }
    const names = await lookupNames("team", r.teams.map(t => t.team));
    teams.replaceChildren(...r.teams.map((t, j) => h("span", { class: "pill", title: names[t.team] || "" }, `${t.team}${names[t.team] ? " " + names[t.team] : ""} ×`,
      numberInput(t, "weight", { min: 0, step: "any" }), h("button", { class: "small", title: "Take this team out", onclick: () => { r.teams.splice(j, 1); dirty(); drawTeams(); } }, "✕"))),
      h("button", { class: "small", onclick: async () => { const id = await pickDialog("team", "Which enemy team appears?"); if (id !== null) { r.teams.push({ team: Number(id), weight: 1 }); dirty(); drawTeams(); } } }, "+ Team"),
      h("button", { class: "small", title: "Every team that starts on this map, bosses left out, equally likely", onclick: () => {
        const have = new Set(r.teams.map(t => Number(t.team)));
        const pool = e.map_teams || [...new Set(e.spots.map(s => Number(s.enemy_team_id || 0)).filter(Boolean))];
        for (const t of pool) if (!have.has(Number(t))) r.teams.push({ team: Number(t), weight: 1 });
        dirty(); drawTeams();
      } }, "+ This map's"), ...(r.teams.length ? [] : [h("span", { class: "muted small" }, "No team yet: nothing appears.")]));
  };
  drawTeams();
  return h("tr", {},
    h("td", {}, nodePicker(e, r, nodes)),
    h("td", {}, when),
    h("td", {}, r.start ? h("span", { class: "muted" }, "100") : numberInput(r, "chance", { min: 0, max: 100 })),
    h("td", {}, r.start ? h("span", { class: "muted" }, "1") : numberInput(r, "max", { min: 0 }), r.start ? null : h("div", { class: "muted small" }, "0 = no limit")),
    h("td", {}, who, teams),
    h("td", {}, ally ? allyConditions(r) : conditionEditor(e, r, nodes)),
    h("td", {}, h("button", { class: "small danger", title: "Remove this spawn", onclick: () => { e.spawns.splice(i, 1); dirty(); renderEditor(); } }, "✕")));
}

/** An allied force spawn's settings: which nodes it can use and whose side it fights on. */
function allyConditions(r) {
  const side = h("span");
  const drawSide = () => side.replaceChildren(forceSide(r, "side", (r.teams[0] || {}).team));
  drawSide();
  return h("div", {},
    h("div", { class: "row cond" }, "on nodes held by", selectInput(r, "owner", BELONGS)),
    h("div", { class: "row cond" }, "it fights", side),
    h("div", { class: "muted small" }, "It appears at the start of your next turn, on an empty node."));
}

// conditions a special spawn can have (gfserver/missions.py _spawn)
const SPAWN_CONDITIONS = {
  after_killed: "after an enemy team is defeated", while_alive: "while an enemy team is on the map",
  min_kills: "once enough enemies are defeated", max_kills: "until too many enemies are defeated",
  after_destroyed: "after the building on a node is destroyed", if_special: "only if the node has a map marker",
  unless_special: "unless the node has a map marker", our_turn: "at the start of the player's turn instead",
  queue: "teams in a fixed order, one each time",
};
// where a special spawn's enemies can appear (gfserver/missions.py _spawn: enemy_owned, not_ours)
const SPAWN_WHERE = { heli: "on enemy heliports", free: "on nodes you don't hold", any: "on any of its nodes" };
const whereOf = (r) => r.enemy_owned === false ? (r.not_ours ? "free" : "any") : "heli";

function conditionEditor(e, r, nodes) {
  const box = h("div");
  const team = async (key, label) => {
    const id = r[key];
    const n = id ? await lookupNames("team", [id]) : {};
    return h("span", {}, label, " ", h("button", { class: "small", onclick: async () => { const x = await pickDialog("team", label); if (x !== null) { r[key] = Number(x); dirty(); draw(); } } }, id ? `${n[id] || "team"} ${id}` : "pick…"));
  };
  const marker = async (key, label) => {
    const list = await catalog("map_marker");
    const it = list.find(x => String(x.id) === String(r[key]));
    return h("span", { title: (it || {}).desc || "" }, label, " ", h("button", { class: "small", onclick: async () => { const x = await pickDialog("map_marker", label); if (x !== null) { r[key] = Number(x); dirty(); draw(); } } }, it ? `${it.name} ${it.id}` : "pick…"));
  };
  const has = (k) => k in r;
  const remove = (k) => { delete r[k]; if (k === "queue") r.teams ||= []; dirty(); renderEditor(); };
  const draw = async () => {
    const parts = [];
    for (const k of Object.keys(SPAWN_CONDITIONS)) {
      if (!has(k)) continue;
      let body;
      if (k === "after_killed" || k === "while_alive") body = await team(k, k === "after_killed" ? "after defeating" : "while alive:");
      else if (k === "min_kills") body = h("span", {}, "after ", numberInput(r, k, { min: 0 }), " kills");
      else if (k === "max_kills") body = h("span", {}, "until ", numberInput(r, k, { min: 0 }), " kills");
      else if (k === "after_destroyed") body = h("span", {}, "after the building on ", selectInput(r, k, Object.fromEntries(e.spots.filter(s => Number(s.building_id)).map(s => [s.id, nodes[s.id]]))), " is destroyed");
      else if (k === "if_special" || k === "unless_special") body = await marker(k, k === "if_special" ? "only with marker" : "unless marker");
      else if (k === "queue") {
        const ids = r.queue || [];
        const n = ids.length ? await lookupNames("team", ids) : {};
        body = h("span", {}, "in order: ", ...ids.map((t, j) => h("span", { class: "pill" }, `${j + 1}. ${n[t] || t}`, h("button", { class: "small", onclick: () => { ids.splice(j, 1); dirty(); draw(); } }, "✕"))),
          h("button", { class: "small", onclick: async () => { const x = await pickDialog("team", "Next team"); if (x !== null) { (r.queue ||= []).push(Number(x)); dirty(); draw(); } } }, "+"));
      } else body = h("span", {}, SPAWN_CONDITIONS[k]);
      parts.push(h("div", { class: "row cond" }, body, h("button", { class: "small danger", title: "Remove this condition", onclick: () => remove(k) }, "✕")));
    }
    const add = h("select", {}, h("option", { value: "" }, "+ Condition…"), ...Object.entries(SPAWN_CONDITIONS).filter(([k]) => !has(k)).map(([k, v]) => h("option", { value: k }, v)));
    add.addEventListener("change", () => {
      const k = add.value;
      if (!k) return;
      if (k === "our_turn") r[k] = true;
      else if (k === "queue") r.queue = (r.teams || []).map(t => Number(t.team));
      else if (k === "min_kills" || k === "max_kills") r[k] = 10;
      else r[k] = 0;
      dirty(); renderEditor();
    });
    box.replaceChildren(...parts, add);
  };
  draw();
  return box;
}

// ------------------------------------------------------------------ enemy move order

const MOVE_AI = { patrol: "Patrol", alert: "Alert", expand: "Expand", attack: "Attack", random: "Random", lock_on: "Lock On", standby: "Standby" };
const MOVE_THEN = { oldest: "First to appear", newest: "Last to appear", nearest: "Nearest to your units", farthest: "Farthest from your units" };

function moveOrderTab(e, embedded = false) {
  e.move_order ||= { first: [], then: "oldest" };
  const o = e.move_order;
  o.first ||= []; o.then ||= "oldest";
  const nodes = {};
  for (const s of e.spots) nodes[s.id] = `${s.id} · ${SPOT_TYPES[s.type] || "Node"}`;
  const body = h("tbody", {});
  const draw = async () => {
    const names = await lookupNames("team", o.first.filter(r => "team" in r).map(r => r.team));
    const what = (r) => "team" in r ? `Enemy team ${r.team}${names[r.team] ? " · " + names[r.team] : ""}`
      : "spot" in r ? `The enemy standing on ${nodes[r.spot] || "node " + r.spot}` : `Enemies on ${MOVE_AI[r.ai] || r.ai}`;
    const move = (i, d) => { const j = i + d; if (j < 0 || j >= o.first.length) return; [o.first[i], o.first[j]] = [o.first[j], o.first[i]]; dirty(); draw(); };
    body.replaceChildren(...o.first.map((r, i) => h("tr", {}, h("td", {}, String(i + 1)), h("td", {}, what(r)),
      h("td", {}, h("button", { class: "small", title: "Move up", onclick: () => move(i, -1) }, "↑"), h("button", { class: "small", title: "Move down", onclick: () => move(i, 1) }, "↓"),
        h("button", { class: "small danger", title: "Remove", onclick: () => { o.first.splice(i, 1); dirty(); draw(); } }, "✕")))),
      h("tr", {}, h("td", {}, String(o.first.length + 1)), h("td", { class: "muted" }, "Every other enemy"), h("td", {})));
  };
  draw();
  const ai = h("select", {}, h("option", { value: "" }, "+ Enemies with an AI…"), ...Object.entries(MOVE_AI).map(([k, v]) => h("option", { value: k }, v)));
  ai.addEventListener("change", () => { if (ai.value) { o.first.push({ ai: ai.value }); ai.value = ""; dirty(); draw(); } });
  const spot = h("select", {}, h("option", { value: "" }, "+ The enemy on a node…"), ...Object.entries(nodes).map(([k, v]) => h("option", { value: k }, v)));
  spot.addEventListener("change", () => { if (spot.value) { o.first.push({ spot: Number(spot.value) }); spot.value = ""; dirty(); draw(); } });
  return (embedded ? (...kids) => h("div", {}, ...kids) : (...kids) => card("Enemy move order", ...kids))(
    h("p", { class: "muted small" }, "Which enemy moves first in the enemy turn. It decides who gets a contested node and who attacks first. " +
      "Rows higher up move earlier; an enemy that matches no row moves after them all."),
    h("table", { class: "grid" }, h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, "Moves first"), h("th", {}))), body),
    h("div", { class: "row" },
      h("button", { class: "small", onclick: async () => { const id = await pickDialog("team", "Which enemy team moves first?"); if (id !== null) { o.first.push({ team: Number(id) }); dirty(); draw(); } } }, "+ An enemy team"),
      ai, spot),
    field("Within each row, and for everyone else", selectInput(o, "then", MOVE_THEN, { text: true }),
      "First to appear is the order the server uses when nothing is set."));
}

// enemies appear during the battle only on heliports the enemy holds (player report); other spawns come
// from skills' spawn points, which the server handles itself
const isHeliport = (s) => [3, 7].includes(Number(s.type));

// Give other heliports the spawn table of one: they join every rule the source heliport is in
function copyHeliport(e, nodes, start, done) {
  const used = [...new Set(e.spawns.filter(r => !r.start).flatMap(ruleSpots))].filter(id => nodes[id]);
  if (start !== undefined && !used.includes(String(start))) used.unshift(String(start));
  const st = { from: start !== undefined ? String(start) : used[0] || "" };
  const box = h("div", {});
  const draw = () => {
    const from = h("select", {}, ...used.map(id => h("option", { value: id }, nodes[id])));
    from.value = st.from;
    from.addEventListener("change", () => { st.from = from.value; draw(); });
    const rules = e.spawns.filter(r => !r.start && ruleSpots(r).includes(String(st.from)));
    const others = e.spots.filter(s => isHeliport(s) && String(s.id) !== String(st.from));
    const ticks = others.map(s => { const cb = h("input", { type: "checkbox" }); cb.checked = rules.length > 0 && rules.every(r => ruleSpots(r).includes(String(s.id))); cb.dataset.id = s.id; return cb; });
    box.replaceChildren(
      h("div", { class: "row" }, h("span", {}, "Copy the spawns of"), from, h("span", { class: "muted small" }, `(${rules.length} rule${rules.length === 1 ? "" : "s"})`), h("span", {}, "to:")),
      h("div", { class: "row" }, ...others.map((s, j) => h("label", { class: "check pill" }, ticks[j], " " + nodes[s.id]))),
      h("div", { class: "row" },
        h("button", { class: "small", onclick: () => { ticks.forEach((t, j) => { t.checked = Number(others[j].belong) === 2; }); } }, "Tick the enemy's"),
        h("button", { class: "small primary", onclick: () => {
          const to = ticks.filter(t => t.checked).map(t => t.dataset.id);
          if (!to.length) return toast("Tick the heliports to copy to");
          for (const r of rules) setRuleSpots(r, [...ruleSpots(r), ...to]);
          dirty(); done && done(); renderEditor(); toast(`Copied to ${to.length} heliport${to.length === 1 ? "" : "s"}. Save to keep it.`);
        } }, "Copy")));
  };
  draw();
  return h("div", { class: "card inner" }, h("strong", {}, "Same spawns on several heliports"), box);
}

// a rule's nodes: "spots" when there are several, else "spot" (gfserver/missions.rule_spots)
const ruleSpots = (r) => (r.spots && r.spots.length ? r.spots : [r.spot]).filter(x => x !== undefined && x !== null && x !== "").map(String);
function setRuleSpots(r, list) {
  const uniq = [...new Set(list.map(String))];
  r.spot = uniq.length ? Number(uniq[0]) : 0;
  if (uniq.length > 1) r.spots = uniq.map(Number); else delete r.spots;
}

function nodePicker(e, r, nodes) {
  const box = h("div", {});
  const draw = () => {
    const list = ruleSpots(r).filter(x => nodes[x]);
    // a mission-start enemy may stand on any node; during the battle they appear on heliports
    const anyNode = r.start || r.ally || r.enemy_owned === false;
    const allowed = new Set(e.spots.filter(s => anyNode || isHeliport(s)).map(s => String(s.id)));
    const add = h("select", {}, h("option", { value: "" }, anyNode ? "+ Add a node…" : "+ Add a heliport…"),
      ...Object.entries(nodes).filter(([id]) => allowed.has(id) && !list.includes(id)).map(([id, label]) => h("option", { value: id }, label)));
    add.addEventListener("change", () => { if (add.value) { setRuleSpots(r, [...list, add.value]); dirty(); draw(); } });
    const pick = (test) => () => {
      setRuleSpots(r, [...list, ...e.spots.filter(test).map(s => String(s.id))]); dirty(); draw();
    };
    box.replaceChildren(...[
      h("div", { class: "row" }, ...list.map(id => h("span", { class: "pill" }, nodes[id],
        h("button", { class: "small", title: "Take this node out", onclick: () => { setRuleSpots(r, list.filter(x => x !== id)); dirty(); draw(); } }, "✕")))),
      list.length ? null : h("p", { class: "muted small" }, "No node yet: this rule spawns nothing."),
      !anyNode && list.some(id => !allowed.has(id)) ? h("p", { class: "muted small" }, "Nodes that aren't heliports only get these enemies if they appear on the map (below).") : null,
      r.start || r.ally ? null : h("div", { class: "row small" }, "Appears", whereSelect(r)),
      h("div", { class: "row" }, add,
        r.start ? null : h("button", { class: "small", onclick: pick(s => isHeliport(s) && Number(s.belong) === 2) }, "+ All enemy heliports"),
        list.length > 1 ? h("button", { class: "small", onclick: () => { setRuleSpots(r, []); dirty(); draw(); } }, "Clear") : null),
      list.length > 1 && !r.start ? oneOfChoice(r) : null].filter(Boolean));
  };
  draw();
  return box;
}

function whereSelect(r) {
  const sel = h("select", {}, ...Object.entries(SPAWN_WHERE).map(([k, v]) => h("option", { value: k }, v)));
  sel.value = whereOf(r);
  sel.addEventListener("change", () => {
    if (sel.value === "heli") { r.enemy_owned = true; delete r.not_ours; }
    else { r.enemy_owned = false; if (sel.value === "free") r.not_ours = true; else delete r.not_ours; }
    dirty(); renderEditor();
  });
  return sel;
}

/** Several nodes: each on its own, or one of them picked at random each time. */
function oneOfChoice(r) {
  const sel = h("select", {}, h("option", { value: "each" }, "each of these nodes on its own"),
    h("option", { value: "one" }, "one of these nodes, picked at random"));
  sel.value = r.one_of ? "one" : "each";
  sel.addEventListener("change", () => { if (sel.value === "one") r.one_of = true; else { delete r.one_of; delete r.blind; } dirty(); renderEditor(); });
  const blind = { v: !!r.blind };
  return h("div", {}, h("div", { class: "row small" }, "Spawns", sel),
    r.one_of ? checkbox(blind, "v", "If the picked node is taken or blocked, skip this spawn (else another free one is picked)",
      { onChange: () => { if (blind.v) r.blind = true; else delete r.blind; } }) : null,
    h("p", { class: "muted small" }, r.one_of ? "The chance, turns and limit count once for the whole group."
      : "The chance, turns and limit count for every node separately."));
}

/** Copy one heliport's spawns to others, from the table's column header. */
function copyDialog(e, nodes, sid) {
  let close;
  close = openDialog(h("h3", {}, `Copy the spawns of ${nodes[sid] || sid}`),
    copyHeliport(e, nodes, sid, () => close()),
    h("div", { class: "row" }, h("button", { onclick: () => close() }, "Close")));
}

/** The map art name, with the game's and the mods' own map backgrounds to pick from. */
function mapBackgroundInput(e) {
  const input = textInput(e, "background");
  const list = h("datalist", { id: "map-backgrounds" });
  input.setAttribute("list", "map-backgrounds");
  Promise.all([api("own-map-backgrounds"), api("assets/map_bg")]).then(([own, game]) => {
    list.replaceChildren(...own.map(x => h("option", { value: x.key }, `${x.name} (mod ${x.mod})`)),
                         ...game.items.map(x => h("option", { value: x.key }, x.name)));
  }).catch(() => {});
  return h("div", {}, input, list);
}
