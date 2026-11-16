/* Map editor for Mod Studio: settings, layout (nodes, links, zoom), enemy spawns, enemy move order. */
"use strict";

const SPOT_TYPES = { 1: "Command Post (HQ)", 2: "Node", 3: "Heliport", 7: "Heavy heliport", 5: "Supply point",
                     6: "Rally point", 8: "Repair point" };
const BELONGS = { 1: "Griffin", 2: "Enemy", 3: "Neutral", 0: "Other" };
const MAP_TYPES = { 1: "Village", 2: "Road", 3: "Bridge", 4: "Forest", 5: "City", 6: "Snowland", 7: "Snow village",
  8: "Snow forest", 9: "Forest 2", 10: "Airport", 11: "Grasslands", 12: "Village 2", 13: "Abandoned village", 14: "Valley",
  15: "Wasteland", 16: "Polluted", 17: "Network", 18: "Iron", 19: "Park", 20: "Train", 21: "Blood network", 22: "Downtown",
  23: "VA-11 city", 24: "Flowers", 26: "Beach", 28: "Tree sea" };
const MAP_CODES = { 1: "village", 2: "road", 4: "forest", 5: "city", 6: "snowland", 8: "snowforest", 9: "forest2", 10: "airport",
  11: "grasslands", 12: "village2", 13: "abandonedvillage", 14: "valley", 15: "wasteland", 16: "pollute", 17: "network", 21: "bloodnet" };
const GOALS = [[2, "Capture the enemy Command Post (or the win nodes)"], [1, "Reach the win nodes"],
               [3, "Destroy every enemy, or take the Command Post"], [4, "Destroy the boss team"], [11, "Survive a number of turns"]];

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
    checkbox(e, "restart", "Allow restarting the map"),
    checkbox(e, "endless", "Endless (scored) map: ammo and rations can run out")));

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
      picked.has(11) ? field("Turns to survive", numberInput(e, "win_turn", { min: 1 })) : null)));

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

  wrap.append(card("Ranking", h("div", { class: "fields" },
    field("Turns for S rank", numberInput(e.rank, "turns", { min: 0 }), "0 = no turn target."),
    field("Enemies to defeat", numberInput(e.rank, "kills", { min: 0 }), "0 = no kill target."),
    field("T-Doll losses allowed", numberInput(e.rank, "losses", { min: 0 }))),
    h("p", { class: "muted small" }, "Rank starts at S and drops one step (to C at worst) for each missed target.")));

  wrap.append(h("details", { class: "card" }, h("summary", {}, "Map picture (advanced)"), h("div", { class: "fields" },
    field("Background", textInput(e, "background"), "Map art name, e.g. Chapter1_Y (from the game's maps)."),
    field("Visible area", textInput(e, "frame"), "size|visible size|offset, e.g. 3000,2625|2472,1574|0,-758 (copy it from the map you started from)."))));
  return wrap;
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

function layoutTab(e) {
  S.mapTool ||= "move";
  if (!e._view) { const b = fitBox(e); e._view = { cx: (b.x0 + b.x1) / 2, cy: (b.y0 + b.y1) / 2, w: b.x1 - b.x0 + 240 }; }
  const panel = h("div");
  const svg = sv("svg");
  const zoom = (f) => { e._view.w = Math.max(300, Math.min(40000, e._view.w * f)); draw(); };
  const tools = h("div", { class: "map-tools" },
    [["move", "Move / select"], ["link2", "Link (two-way)"], ["link1", "Link (one-way)"], ["add", "Add node"], ["del", "Delete node"]]
      .map(([k, label]) => h("button", { class: "small" + (S.mapTool === k ? " on" : ""), onclick: () => { S.mapTool = k; S.linkFrom = null; renderEditor(); } }, label)),
    h("span", { class: "spacer" }),
    h("button", { class: "small", title: "Zoom in", onclick: () => zoom(1 / 1.3) }, "+"),
    h("button", { class: "small", title: "Zoom out", onclick: () => zoom(1.3) }, "−"),
    h("button", { class: "small", title: "Fit the whole map", onclick: () => { e._view = null; renderEditor(); } }, "Fit"));
  const hint = h("div", { class: "muted small", style: "padding:0 8px 6px" }, {
    move: "Drag nodes to move them, drag empty space to pan, scroll to zoom. Click a node to edit it.",
    link2: "Click two nodes to link or unlink them.", link1: "Click the node units leave from, then the one they can reach.",
    add: "Click an empty spot to add a node.", del: "Click a node to remove it." }[S.mapTool]);
  const legend = h("div", { class: "legend" }, h("span", { style: "color:var(--griffin)" }, "Griffin"), h("span", { style: "color:var(--enemy)" }, "Enemy"),
    h("span", { style: "color:var(--neutral)" }, "Neutral"), h("span", { style: "color:var(--third)" }, "win node (ring)"),
    h("span", { class: "muted" }, "■ HQ  ◆ heliport  ● node  · red dot = enemy team · ↻ = spawn point · dashed = one-way"));
  const draw = () => drawMap(e, svg);
  draw();
  let drag = null, pan = null, moved = false;
  const toXY = (ev) => { const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY; const p = pt.matrixTransform(svg.getScreenCTM().inverse()); return [Math.round(p.x), Math.round(-p.y)]; };
  svg.addEventListener("wheel", ev => { ev.preventDefault(); zoom(ev.deltaY > 0 ? 1.15 : 1 / 1.15); }, { passive: false });
  svg.addEventListener("pointerdown", ev => {
    const id = ev.target.closest("[data-spot]")?.dataset.spot;
    const tool = S.mapTool;
    if (tool === "add" && !id) {
      const [x, y] = toXY(ev);
      const nid = newSpotId(e);
      e.spots.push({ id: nid, mission_id: e.id, type: 2, belong: 3, coordinator_x: x, coordinator_y: y, route: "", map_route: "",
                     curve_control: "", map_type: 2, map_code: "road", random_get: "0", durability: "0", enemy_team_id: 0, win: false });
      S.mapSel = nid; dirty(); renderEditor();
      return;
    }
    if (!id) {
      if (tool === "move") { pan = { x: ev.clientX, y: ev.clientY, cx: e._view.cx, cy: e._view.cy }; svg.setPointerCapture(ev.pointerId); }
      S.mapSel = null; S.linkFrom = null; draw(); renderPanel();
      return;
    }
    if (tool === "del") {
      e.spots = e.spots.filter(s => String(s.id) !== id);
      for (const s of e.spots) setLinks(s, ids(s.route).filter(x => x !== id));
      for (const r of e.spawns) setRuleSpots(r, ruleSpots(r).filter(x => x !== id));
      e.spawns = e.spawns.filter(r => ruleSpots(r).length);
      S.mapSel = null; dirty(); renderEditor();
      return;
    }
    if (tool === "link1" || tool === "link2") {
      if (!S.linkFrom) { S.linkFrom = id; S.mapSel = id; }
      else if (S.linkFrom !== id) { toggleLink(e, S.linkFrom, id, tool === "link2"); S.linkFrom = null; S.mapSel = id; }
      draw(); renderPanel();
      return;
    }
    S.mapSel = id; drag = id; moved = false;
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
    const s = spotById(e, drag);
    if (s.coordinator_x !== x || s.coordinator_y !== y) { s.coordinator_x = x; s.coordinator_y = y; moved = true; dirty(); draw(); }
  });
  svg.addEventListener("pointerup", () => { if (drag && moved) renderPanel(); drag = null; pan = null; });
  const renderPanel = () => panel.replaceChildren(nodePanel(e, draw));
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
    const sel = String(S.mapSel) === String(s.id) || String(S.linkFrom) === String(s.id);
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
    h("p", { class: "muted small" }, ids(s.route).length ? `Links to ${ids(s.route).join(", ")}` : "No links yet: use a Link tool."));
}

// ------------------------------------------------------------------ spawns

function spawnsTab(e, embedded = false) {
  // embedded: inside another card (mapconfig.js), without its own frame and intro
  const nodes = {};
  for (const s of e.spots) nodes[s.id] = `${s.id} · ${SPOT_TYPES[s.type] || "Node"} (${BELONGS[s.belong] || ""})`;
  const rows = e.spawns.map((r, i) => spawnRow(e, r, i, nodes));
  return (embedded ? (...kids) => h("div", {}, ...kids) : (...kids) => card("Enemy spawns", ...kids))(
    embedded ? null : h("p", { class: "muted small" }, "Enemies that start on the map are set on the nodes (Layout tab). Each row adds more: ",
      "a team from its list (picked by weight) appears on an empty node of the row, at the start of the enemy turn."),
    e.spawns.length
      ? h("div", { class: "tablewrap" }, h("table", { class: "grid spawns" },
          h("tr", {}, ...["Nodes", "When", "Chance %", "At most", "Teams (weight)", ""].map(x => h("th", {}, x))), ...rows))
      : h("p", { class: "muted" }, "No spawn rows: only the starting enemies."),
    h("div", { class: "row" },
      h("button", { onclick: () => {
        const helis = e.spots.filter(s => isHeliport(s) && Number(s.belong) === 2).map(s => s.id);
        const rule = { spot: 0, teams: [], from_turn: 1, to_turn: 0, every: 1, chance: 100, max: 0, enemy_owned: true };
        setRuleSpots(rule, helis);
        e.spawns.push(rule); dirty(); renderEditor();
      } }, "+ Add a row"),
      h("span", { class: "muted small" }, "Chance, turns and limit count for each node of a row on its own. Rows only spawn on heliports the enemy holds, except at mission start.")),
    e.spawns.some(r => !r.start) ? copyHeliport(e, nodes) : null);
}

function spawnRow(e, r, i, nodes) {
  const kind = h("select", {}, h("option", { value: "turns" }, "Enemy turns"), h("option", { value: "start" }, "Mission start"));
  kind.value = r.start ? "start" : "turns";
  kind.addEventListener("change", () => { if (kind.value === "start") r.start = true; else delete r.start; dirty(); renderEditor(); });
  const when = h("div", {}, kind, ...(r.start ? [] : [
    h("div", { class: "row small" }, "from", numberInput(r, "from_turn", { min: 1 }), "to", numberInput(r, "to_turn", { min: 0 })),
    h("div", { class: "row small" }, "every", numberInput(r, "every", { min: 1 }), "turn(s)"),
    h("div", { class: "muted small" }, "to 0 = to the end")]));
  const teams = h("div", { class: "teams" });
  const drawTeams = async () => {
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
    h("td", {}, teams),
    h("td", {}, h("button", { class: "small danger", title: "Remove this row", onclick: () => { e.spawns.splice(i, 1); dirty(); renderEditor(); } }, "✕")));
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
function copyHeliport(e, nodes) {
  const used = [...new Set(e.spawns.filter(r => !r.start).flatMap(ruleSpots))].filter(id => nodes[id]);
  const st = { from: used[0] || "" };
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
          dirty(); renderEditor(); toast(`Copied to ${to.length} heliport${to.length === 1 ? "" : "s"}. Save to keep it.`);
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
    const allowed = new Set(e.spots.filter(s => r.start || isHeliport(s)).map(s => String(s.id)));
    const add = h("select", {}, h("option", { value: "" }, r.start ? "+ Add a node…" : "+ Add a heliport…"),
      ...Object.entries(nodes).filter(([id]) => allowed.has(id) && !list.includes(id)).map(([id, label]) => h("option", { value: id }, label)));
    add.addEventListener("change", () => { if (add.value) { setRuleSpots(r, [...list, add.value]); dirty(); draw(); } });
    const pick = (test) => () => {
      setRuleSpots(r, [...list, ...e.spots.filter(test).map(s => String(s.id))]); dirty(); draw();
    };
    box.replaceChildren(...[
      h("div", { class: "row" }, ...list.map(id => h("span", { class: "pill" }, nodes[id],
        h("button", { class: "small", title: "Take this node out", onclick: () => { setRuleSpots(r, list.filter(x => x !== id)); dirty(); draw(); } }, "✕")))),
      list.length ? null : h("p", { class: "muted small" }, "No node yet: this rule spawns nothing."),
      !r.start && list.some(id => !allowed.has(id)) ? h("p", { class: "muted small" }, "Nodes that aren't heliports only get enemies from a rule placed at mission start.") : null,
      h("div", { class: "row" }, add,
        r.start ? null : h("button", { class: "small", onclick: pick(s => isHeliport(s) && Number(s.belong) === 2) }, "+ All enemy heliports"),
        list.length > 1 ? h("button", { class: "small", onclick: () => { setRuleSpots(r, []); dirty(); draw(); } }, "Clear") : null),
      list.length > 1 ? h("p", { class: "muted small" }, "Each node is on its own: the chance, turns and limit count for every node separately.") : null].filter(Boolean));
  };
  draw();
  return box;
}
