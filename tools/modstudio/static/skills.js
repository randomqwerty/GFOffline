/* Visual skill editor for Mod Studio (level 10). A skill is shown as cards: basics, when it activates,
   numbers (pools), who it targets, effects (buffs, with watchers and granted skills), and the
   animation's objects with their hits and area effects. On save the server copies only what was
   changed (skills.py), so links between a kit's skills keep working. */
"use strict";

const SK = {
  types: { 1: "Active skill (the unit's main skill)", 2: "Triggered skill", 4: "Instant triggered skill (does not stop the unit)",
           3: "Normal attack", 7: "On death (last stand)", 8: "Cast by a watcher", 6: "Active, special manual cast",
           10: "Active, player picks a spot", 301: "Special (no extra handling)", 5: "Other (5)", 9: "Other (9)" },
  cdTypes: { 1: "Seconds", 0: "No cooldown", 2: "Battles / turns", 3: "Follows rate of fire (normal attacks)", 4: "Won battles" },
  daynight: { 0: "Day and night", 1: "Day and night", 4: "Day only", 3: "Night only", 2: "Night numbers at night" },
  trig: { 6: "Has at least N stacks of a buff", 7: "Has fewer than N stacks of a buff", 18: "A formula is true",
          2: "HP at or below %", 3: "HP at or above %", 11: "Random chance %", 10: "Just dodged", 13: "Just took damage",
          5: "Is being targeted", 4: "Is dead", 14: "Force Shield at or below %", 15: "Force Shield at or above %",
          16: "Barrier at or below", 17: "Barrier at or above", 21: "This skill has killed at least N",
          20: "Battle node belongs to (1 Griffin, 2 enemy, 3 neutral)", 19: "Battle background is one of",
          8: "Mission is one of (ids)", 9: "The user is on the enemy side", 1: "Always", 0: "Always" },
  trigWho: { 1: "the user", 2: "the user's target", 3: "any unit on the user's side", 4: "any enemy" },
  noParam: [0, 1, 4, 5, 9, 10, 13],
  targetType: { 1: "Enemies in range", 4: "The user", 2: "All allies", 3: "Allies except the user", 7: "Own vehicle and parts", 8: "Own vehicle parts" },
  sort: { 0: "—", 1: "HP", 2: "HP %", 3: "Max HP", 4: "Distance", 5: "Firepower", 6: "Evasion", 7: "Armor",
          9: "Left-right distance", 10: "Left-right distance (2)", 11: "Front-back distance", 12: "Damage dealt so far",
          13: "Force Shield", 14: "Max Force Shield", formula: "A formula…" },
  priority: { 0: "None", 1: "None", 2: "Echelon leader first", 3: "Bosses first", 4: "Everyone in the chosen target's row", 5: "Everyone in its column" },
  filter: { none: "No filter", 6: "Only units with a buff", 7: "Only units without a buff", 18: "Only units matching a formula" },
  lost: { 2: "Pick a new target", 1: "Stop", 0: "Keep the old target" },
  start: { 6: "Target's feet", 5: "Target's body", 4: "Target's gun", 3: "User's feet", 2: "User's body", 1: "User's gun",
           7: "The object that spawned it", 8: "Griffin side's centre", 15: "The target", 99: "Spot the player picks",
           9: "User's row (map centre line)", 10: "User's column (centre line)", 11: "Target's row (centre line)", 12: "Target's column (centre line)" },
  route: { 0: "Appears in place", 3: "Appears in place (3)", 1: "Flies straight", 2: "Flies in an arc (thrown)", 6: "Keeps flying forward (piercing)",
           7: "Instant ray", 5: "Straight, no turning", 4: "Follows its effect" },
  area: { 0: "Only the target", 1: "Circle", 2: "Rectangle", 3: "Formation tiles", 4: "Long box from the object" },
  affects: { 2: "Enemies", 1: "Allies", 0: "Only its own target" },
  crit: { 1: "Can crit", 0: "Never crits", 2: "Always crits" },
  hitType: { 1: "Normal accuracy roll", 0: "Normal accuracy roll (0)", 2: "Precise (hard to dodge)" },
  hurtWhen: { 0: "When the hit lands", 1: "On critical hits only", 2: "Unless armor blocked it", 3: "Only when it misses" },
  watchEvent: { 1: "A buff changes", 2: "The unit takes damage", 3: "The unit deals damage", 4: "A skill is cast",
                5: "The unit is heavily damaged", 6: "A unit retreats", 7: "A unit dies" },
  watchTarget: { 0: "its own targets", 1: "the watched unit", 2: "the other side of the event" },
  hurtResult: { 0: "ordinary", 1: "stopped by armor", 2: "armor pierced", 3: "armor pierced and critical" },
  buff: {
    101: ["Firepower up", "pow_number", "%"], 201: ["Firepower down", "pow_number", "%"], 801: ["Firepower +flat", "pow_number", "flat"],
    102: ["Evasion up", "dodge_number", "%"], 202: ["Evasion down", "dodge_number", "%"], 802: ["Evasion +flat", "dodge_number", "flat"],
    103: ["Accuracy up", "hit_number", "%"], 203: ["Accuracy down", "hit_number", "%"], 803: ["Accuracy +flat", "hit_number", "flat"],
    104: ["Rate of fire up", "rate_number", "%"], 204: ["Rate of fire down", "rate_number", "%"], 804: ["Rate of fire +flat", "rate_number", "flat"],
    105: ["Movement speed up", "move_number", "%"], 205: ["Movement speed down", "move_number", "%"], 215: ["Movement speed down (2)", "move_number", "%"], 805: ["Movement speed +flat", "move_number", "flat"],
    106: ["Critical rate up", "critical_number", "%"], 206: ["Critical rate down", "critical_number", "%"], 806: ["Critical rate +flat", "critical_number", "flat"],
    108: ["Armor up", "armor_reduce_number", "%"], 208: ["Armor down", "armor_reduce_number", "%"], 808: ["Armor +flat", "armor_reduce_number", "flat"],
    110: ["Damage taken (100 = normal)", "damage_reduce_number", "%"], 810: ["Damage taken +flat", "damage_reduce_number", "flat"],
    111: ["Armor penetration up", "arp_number", "%"], 811: ["Armor penetration +flat", "arp_number", "flat"],
    112: ["Critical damage up", "critical_damage_number", "%"], 812: ["Critical damage +flat", "critical_damage_number", "flat"],
    109: ["Barrier (absorbs damage)", "shield_number", "points"], 122: ["Force Shield", "def_number", "points"],
    124: ["Max Force Shield up", "maxdef_number", "%"], 224: ["Max Force Shield down", "maxdef_number", "%"],
    126: ["Shield break up", "defbreak_number", "%"], 226: ["Shield break down", "defbreak_number", "%"], 826: ["Shield break +flat", "defbreak_number", "flat"],
    830: ["Range +flat", "range_number", "flat"], 128: ["Skill cooldown (100 = normal)", "cdr_number", "%"], 129: ["Cut remaining cooldowns", "cdr_number", "%"],
    130: ["Charge counter", "pow_number", "raw"], 131: ["Charge counter (2)", "pow_number", "raw"],
    132: ["Extra attack effect", "parameter_value", "none"], 133: ["Extra attack effect (2)", "parameter_value", "none"], 134: ["Extra attack effect (3)", "parameter_value", "none"],
    136: ["Damage over time", "parameter_value", "raw"], 221: ["Stun", "parameter_value", "none"], 301: ["Taunted", "parameter_value", "none"],
    303: ["Untargetable", "parameter_value", "none"], 304: ["Disarm (blocks some skills)", "parameter_value", "none"],
    305: ["Silence (blocks some skills)", "parameter_value", "none"], 307: ["Cannot die", "parameter_value", "none"],
    120: ["Immune to skills", "parameter_value", "none"], 402: ["Damage taken is recalculated (formula)", "parameter_value", "none"],
    404: ["Night vision", "night_view_percent", "%"], 408: ["Delays matching damage", "parameter_value", "raw"], 409: ["Locks a stat", "parameter_value", "raw"],
    401: ["Marker shown with its stacks", "parameter_value", "none"], 400: ["Marker", "parameter_value", "none"],
    500: ["Marker", "parameter_value", "none"], 501: ["Marker", "parameter_value", "none"], 300: ["Marker", "parameter_value", "none"],
    455: ["Marker", "parameter_value", "none"], 456: ["Marker", "parameter_value", "none"], 457: ["Marker", "parameter_value", "none"],
  },
};

let tempId = -1000;
const newTemp = () => String(tempId--);
const frames = (v) => (v === "" || v === undefined || v === null) ? 0 : Number(v);
const secs = (f) => Math.round(frames(f) / 30 * 100) / 100;
const pairs = (row, a, b) => {
  const A = String(row[a] ?? "").split(",").map(x => x.trim()), B = String(row[b] ?? "").split(",").map(x => x.trim());
  return A.map((x, i) => ({ id: x.split(":")[0], extra: x.includes(":") ? x.split(":")[1] : (B[i] ?? "") })).filter(p => p.id !== "" && p.id !== "0");
};
const idList = (v) => String(v ?? "").split(",").map(x => x.trim()).filter(x => x && x !== "0" && x !== "-1");
const isFormulaRef = (tree, v) => /^1\d{9}$/.test(String(v ?? "").trim()) && (String(Number(v) - 1000000000) in (tree.formulas || {}));
const buffLabel = (type) => (SK.buff[type] || [`Effect type ${type}`])[0];

function blankOf(table) {
  const row = {};
  for (const [f, t] of S.meta.tables[table]) row[f] = t === "string" ? "" : 0;
  return row;
}

/** Seconds input over a frames field (30 frames = 1 s). */
function secondsInput(obj, key, opts = {}) {
  if (/^\*/.test(String(obj[key] ?? "")) && opts.tree) return valueInput(opts.tree, obj, key, { hint: "frames" });
  const el = h("input", { type: "number", step: "any", min: opts.min, style: "width:90px" });
  el.value = Number(obj[key]) === -1 ? -1 : (obj[key] === "" || obj[key] === undefined ? "" : secs(obj[key]));
  el.addEventListener("input", () => {
    const s = parseFloat(el.value);
    const f = isNaN(s) ? 0 : (s === -1 ? -1 : Math.round(s * 30));
    obj[key] = typeof obj[key] === "number" ? f : String(f);
    dirty();
  });
  return h("span", { class: "row" }, el, h("span", { class: "muted small" }, opts.hint || "s"));
}

// ------------------------------------------------------------------ numbers: pools and formulas

function poolList(tree, name) { return String(tree.pools[name] || "").split(",").map(x => x.trim()); }
function setPool(tree, name, i, v) {
  const list = poolList(tree, name);
  while (list.length <= i) list.push("0");
  list[i] = v;
  tree.pools[name] = list.join(",");
  dirty();
}

// start_type / destination_type: a word is a named point on the unit's model (doc/stc-guide/04)
const modelPoint = (v) => /^\d+$/.test(String(v)) ? `${v} (kept as it is)` : `Point on the model: ${v}`;

/** A value that may be a number, a pool reference (*XY: pool X, entry Y) or a formula (1e9 + id). */
function valueInput(tree, obj, key, opts = {}) {
  const v = String(obj[key] ?? "").trim();
  const pool = v.match(/^\*([12])(\d+)$/);
  if (pool) {
    const p = pool[1], i = Number(pool[2]) - 1;
    const box = h("span", { class: "row poolref", title: `Number ${i + 1} of the skill's list ${p} (other skills using the same effect keep their own numbers)` });
    for (const [name, label] of [[`data_pool_${p}`, ""], [`sp_data_pool_${p}`, "special"], [`night_data_pool_${p}`, "night"]]) {
      if (label && !String(tree.pools[name] || "").trim()) continue;
      const el = h("input", { type: "text", style: "width:80px" });
      el.value = poolList(tree, name)[i] ?? "";
      el.addEventListener("input", () => setPool(tree, name, i, el.value));
      if (label) box.append(h("span", { class: "muted small" }, label));
      box.append(el);
    }
    box.append(h("button", { class: "small", title: "Give this effect its own fixed number (it is then copied for this skill)", onclick: () => {
      obj[key] = poolList(tree, `data_pool_${p}`)[i] ?? "0"; dirty(); renderEditor(); } }, "Fixed"));
    return box;
  }
  if (isFormulaRef(tree, v)) return formulaInput(tree, String(Number(v) - 1000000000), () => { obj[key] = typeof obj[key] === "number" ? 0 : "0"; dirty(); renderEditor(); });
  const el = h("input", { type: "text", style: "width:110px" });
  el.value = obj[key] ?? "";
  el.addEventListener("input", () => { obj[key] = typeof obj[key] === "number" ? (parseFloat(el.value) || 0) : el.value; dirty(); opts.onChange && opts.onChange(); });
  const fx = opts.allowFormula === false ? null : h("button", { class: "small", title: "Use a formula instead", onclick: async () => {
    const fid = await newFormula(tree);
    obj[key] = typeof obj[key] === "number" ? 1000000000 + Number(fid) : String(1000000000 + Number(fid)); dirty(); renderEditor(); } }, "ƒ");
  return h("span", { class: "row" }, el, fx);
}

function formulaInput(tree, fid, onRemove) {
  const inp = h("input", { type: "text", class: "formula", placeholder: "e.g. sbuffidtier(7000001)>=3" });
  inp.value = tree.formulas[fid] ?? "";
  inp.addEventListener("input", () => { tree.formulas[fid] = inp.value; dirty(); });
  return h("span", { class: "row" }, h("span", { class: "pill", title: `formula ${fid}` }, "ƒ"), inp,
    onRemove ? h("button", { class: "small", title: "Use a plain number instead", onclick: onRemove }, "Number") : null);
}

async function newFormula(tree) {
  const used = new Set(Object.keys(tree.formulas));
  const free = await api("free/battle_formula?n=20");
  const fid = String(free.find(x => !used.has(String(x))));
  tree.formulas[fid] = "";
  return fid;
}

function numbersCard(tree) {
  const r = tree.row;
  const p = tree.pools;
  const hasSp = String(p.sp_data_pool_1 || "").trim() || String(p.sp_data_pool_2 || "").trim();
  const hasNight = String(p.night_data_pool_1 || "").trim() || String(p.night_data_pool_2 || "").trim();
  const table = h("table", { class: "grid" });
  const cols = [["data_pool", "Normal"]].concat(hasSp ? [["sp_data_pool", "Special"]] : [], hasNight ? [["night_data_pool", "Night"]] : []);
  for (const n of ["1", "2"]) {
    const len = Math.max(...cols.map(([c]) => poolList(tree, `${c}_${n}`).filter(x => x !== "").length), 0);
    if (!len) continue;
    table.append(h("tr", {}, h("th", {}, `List ${n}`), ...cols.map(([, label]) => h("th", {}, label))));
    for (let i = 0; i < len; i++) {
      table.append(h("tr", {}, h("td", { class: "muted small" }, `*${n}${i + 1}`), ...cols.map(([c]) => {
        const cur = poolList(tree, `${c}_${n}`)[i] ?? "";
        const fm = cur.match(/^\*(\d+)$/);
        if (fm && fm[1] in tree.formulas)      // "*N" in a list = formula N
          return h("td", {}, formulaInput(tree, fm[1], () => { setPool(tree, `${c}_${n}`, i, "0"); renderEditor(); }));
        const el = h("input", { type: "text", style: "width:90px" });
        el.value = cur;
        el.addEventListener("input", () => setPool(tree, `${c}_${n}`, i, el.value));
        return h("td", {}, el);
      })));
    }
  }
  const box = h("div");
  box.append(h("p", { class: "muted small" }, "Values written as *XY in the effects below read number Y of list X. Effects shared with other skills read each skill's own numbers, so changing them here changes only this skill."));
  box.append(table.childElementCount ? table : h("p", { class: "muted small" }, "This skill has no number lists (its values are fixed in the effects)."));
  if (hasSp) box.append(field("Use the special numbers when", conditionList(tree, r, "sppool_trigger_id")));
  box.append(h("div", { class: "row" },
    !hasSp ? h("button", { class: "small", onclick: () => { p.sp_data_pool_1 = p.data_pool_1 || ""; p.sp_data_pool_2 = p.data_pool_2 || ""; dirty(); renderEditor(); } }, "+ Different numbers under conditions") : null,
    !hasNight ? h("button", { class: "small", onclick: () => { p.night_data_pool_1 = p.data_pool_1 || ""; p.night_data_pool_2 = p.data_pool_2 || ""; r.daynight_only = 2; dirty(); renderEditor(); } }, "+ Different numbers at night") : null,
    h("button", { class: "small", onclick: () => { p.data_pool_2 = poolList(tree, "data_pool_2").filter(x => x !== "").concat(["0"]).join(","); dirty(); renderEditor(); } }, "+ Number")));
  return card("Numbers", box);
}

// ------------------------------------------------------------------ conditions

/** Buff id input that shows what the buff is and which skills hand it out. */
function buffRef(tree, obj, key, opts = {}) {
  const info = h("span", { class: "muted small ref" });
  const show = async () => {
    const id = String(obj[key] ?? "").trim();
    if (!id || id === "0") { info.textContent = ""; return; }
    if (opts.isType && opts.isType()) { info.textContent = `any ${buffLabel(Number(id))} effect`; return; }
    const own = (tree.buffs || {})[id];
    const res = (await api(`buffinfo?ids=${id}`))[id] || {};
    const type = own ? own.type : res.type;
    const givers = (res.givers || []).map(g => g.name || g.id);
    info.textContent = `${type !== undefined && type !== null ? buffLabel(type) : "unknown effect"}` +
      (givers.length ? ` · given by ${givers.slice(0, 3).join(", ")}${givers.length > 3 ? "…" : ""}` : "");
  };
  const el = h("input", { type: "text", style: "width:100px", list: "own-buffs" });
  el.value = obj[key] ?? "";
  el.addEventListener("change", () => { obj[key] = typeof obj[key] === "number" ? (parseInt(el.value, 10) || 0) : el.value; dirty(); show(); });
  show();
  return h("span", { class: "row" }, el, h("datalist", { id: "own-buffs" }, ...Object.entries(tree.buffs || {}).map(([id, b]) => h("option", { value: id }, buffLabel(b.type)))), info);
}

/** Conditions stored as a list of battle_trigger ids in holder[field]; all must be true. */
function conditionList(tree, holder, field) {
  const box = h("div");
  const ids = () => idList(holder[field]);
  const draw = () => {
    box.replaceChildren(...ids().map((id, i) => conditionRow(tree, id, i, () => {
      holder[field] = ids().filter((_, j) => j !== i).join(",") || (field === "trigger_id" ? "0" : ""); dirty(); draw(); })),
      h("button", { class: "small", onclick: () => {
        const id = newTemp();
        tree.triggers[id] = Object.assign(blankOf("battle_trigger"), { id: Number(id), type: 6, target: 1, parameter: "1", buff_id: 0 });
        holder[field] = [...ids(), id].join(","); dirty(); draw();
      } }, "+ Condition"));
  };
  draw();
  return box;
}

function conditionRow(tree, id, i, onRemove) {
  const t = tree.triggers[id];
  if (!t) return h("div", { class: "cond muted" }, `Condition ${id} (missing in the game data)`, h("button", { class: "small danger", onclick: onRemove }, "✕"));
  const type = Number(t.type);
  const isType = { v: Number(t.is_buff_type) === 1 };
  const row = h("div", { class: "cond" }, h("strong", {}, i ? "and" : "If"),
    selectInput(t, "target", SK.trigWho), selectInput(t, "type", SK.trig, { onChange: renderEditor }));
  if (type === 18) {
    const fid = String(t.parameter ?? "").trim();
    if (fid in tree.formulas) row.append(formulaInput(tree, fid));
    else row.append(h("button", { class: "small", onclick: async () => { const f = await newFormula(tree); t.parameter = f; dirty(); renderEditor(); } }, "Write the formula…"));
  } else if (type === 6 || type === 7) {
    row.append(h("span", { class: "muted small" }, type === 6 ? "at least" : "fewer than"), valueInput(tree, t, "parameter", { allowFormula: false }),
      h("span", { class: "muted small" }, "stacks of"), buffRef(tree, t, "buff_id", { isType: () => isType.v }),
      checkbox(isType, "v", "any effect of this type", { onChange: () => { t.is_buff_type = isType.v ? 1 : 0; renderEditor(); } }));
  } else if (!SK.noParam.includes(type)) {
    row.append(valueInput(tree, t, "parameter", { allowFormula: false }));
  }
  row.append(h("button", { class: "small danger", onclick: onRemove }, "✕"));
  return row;
}

// ------------------------------------------------------------------ the editor

window.skillEditor = function (tree) {
  tree.formulas ||= {};
  tree.pools ||= {};
  tree.watches ||= {};
  tree.watch_triggers ||= {};
  const wrap = h("div");
  const r = tree.row;
  const blocks = { silence: String(r.special_buff_trigger || "").split(",").includes("2"), disarm: String(r.special_buff_trigger || "").split(",").includes("1") };
  const writeBlocks = () => { r.special_buff_trigger = [blocks.disarm ? "1" : "", blocks.silence ? "2" : ""].filter(Boolean).join(","); };
  const manual = { v: Number(r.is_manual) === 1 }, cdr = { v: Number(r.is_cdr) === 1 }, form = { v: Number(r.is_form_action) === 1 }, keep = { v: Number(r.continue_after_death) === 1 };
  const charge = Number(r.cd_type) > 1000000000;
  wrap.append(card("Basics",
    h("div", { class: "fields" },
      field("Name", textInput(tree.texts, "name")),
      field("Kind", selectInput(r, "type", SK.types, { onChange: renderEditor }), "Triggered and instant skills fire whenever their conditions are true and their cooldown is ready."),
      field("Icon", textInput(r, "code"), "Icon name from an existing skill."),
      charge ? field("Cooldown", h("span", { class: "muted small" }, `charges (type ${Number(r.cd_type) - 1000000000})`))
             : field("Cooldown counts in", selectInput(r, "cd_type", SK.cdTypes)),
      field("Cooldown", secondsInput(r, "cd_time", { tree }), "99999 frames ≈ once per battle."),
      field("Cooldown at battle start", secondsInput(r, "start_cd_time", { tree })),
      field("Effect lasts", secondsInput(r, "skill_duration", { tree }), "Used by some actions and effects."),
      field("Day / night", selectInput(r, "daynight_only", SK.daynight)),
      field("Priority", numberInput(r, "skill_priority"), "A running skill can only be replaced by one with a higher priority.")),
    field("Description (shown in game)", textInput(tree.texts, "description", { area: true })),
    h("div", { class: "row" },
      checkbox(cdr, "v", "Shortened by cooldown reduction", { onChange: () => { r.is_cdr = cdr.v ? 1 : 0; } }),
      checkbox(manual, "v", "Manual cast by default", { onChange: () => { r.is_manual = manual.v ? 1 : 0; } }),
      checkbox(form, "v", "User is busy while it plays", { onChange: () => { r.is_form_action = form.v ? 1 : 0; } }),
      checkbox(keep, "v", "Keeps going if the user dies", { onChange: () => { r.continue_after_death = keep.v ? 1 : 0; } }),
      checkbox(blocks, "silence", "Blocked by Silence", { onChange: writeBlocks }),
      checkbox(blocks, "disarm", "Blocked by Disarm", { onChange: writeBlocks }))));

  wrap.append(card("When it activates", h("p", { class: "muted small" },
    "All conditions must be true (and the cooldown ready). Kits often chain skills: one skill gives a marker effect, another checks its stacks."),
    conditionList(tree, r, "trigger_id")));
  wrap.append(numbersCard(tree));
  wrap.append(targetsCard(tree));
  wrap.append(card("Effects on the targets", buffList(tree, r, "buff_id_target", new Set())));
  wrap.append(card("Effects on the user", buffList(tree, r, "buff_id_self", new Set())));
  wrap.append(objectsCard(tree));
  const fids = Object.keys(tree.formulas);
  if (fids.length) wrap.append(card("Formulas", h("p", { class: "muted small" },
    "@ = the user's stat, # = the target's, sbuffidtier(id) / tbuffidtier(id) = stacks of an effect on the user / target, ? : = if / else. See doc/stc-guide/04-combat.md (battle_formula)."),
    ...fids.map(fid => field(`Formula ${fid}`, formulaInput(tree, fid)))));
  return wrap;
};

function targetsCard(tree) {
  const r = tree.row;
  const t = tree.target ||= Object.assign(blankOf("battle_target_select_ai"), { id: Number(newTemp()), target_type: 4, target_number: 1, list_ranking: 1, is_ingore_range: 1, buff_trigger_type: 6 });
  const keys = String(t.select_order ?? "0").split(",").map(x => x.trim());
  const orders = String(t.is_ascend_order ?? "1").split(",").map(x => x.trim());
  const sortRows = h("div");
  const writeSort = (list) => { t.select_order = list.map(x => x.key).join(",") || "0"; t.is_ascend_order = list.map(x => x.order).join(",") || "1"; dirty(); };
  const list = keys.map((k, i) => ({ key: k || "0", order: orders[i] ?? "1" })).filter((x, i) => i === 0 || x.key !== "0");
  const drawSort = () => {
    sortRows.replaceChildren(...list.map((s, i) => {
      const isF = Number(s.key) > 1000000000;
      const pick = { v: isF ? "formula" : s.key };
      const fid = isF ? String(Number(s.key) - 1000000000) : null;
      return h("div", { class: "row cond" }, h("strong", {}, i ? "then by" : "Pick by"),
        selectInput(pick, "v", SK.sort, { text: true, onChange: async () => {
          if (pick.v === "formula") { const f = await newFormula(tree); s.key = String(1000000000 + Number(f)); } else s.key = pick.v;
          writeSort(list); drawSort(); } }),
        isF && fid in tree.formulas ? formulaInput(tree, fid) : null,
        selectInput(s, "order", { 1: "highest first", 0: "lowest first" }, { text: true, onChange: () => writeSort(list) }),
        i ? h("button", { class: "small danger", onclick: () => { list.splice(i, 1); writeSort(list); drawSort(); } }, "✕") : null);
    }), list.length < 2 ? h("button", { class: "small", onclick: () => { list.push({ key: "4", order: "0" }); writeSort(list); drawSort(); } }, "+ Tie-breaker") : null);
  };
  drawSort();
  const ign = { v: Number(t.is_ingore_range) === 1 }, all = { v: Number(t.is_search_all) === 1 }, shared = { v: Number(r.is_re_target) === 1 }, isType = { v: Number(t.is_buff_type) === 1 };
  const ftype = Number(t.buff_trigger_type);
  const filt = { v: (ftype === 6 || ftype === 7) && String(t.target_buff_id || "0") === "0" ? "none" : String(ftype || "none") };
  if (ftype === 0) filt.v = "none";
  const filterBox = h("div", { class: "row" });
  if (filt.v === "6" || filt.v === "7") filterBox.append(valueInput(tree, t, "target_parameter", { allowFormula: false }), h("span", { class: "muted small" }, "stacks of"),
    buffRef(tree, t, "target_buff_id", { isType: () => isType.v }), checkbox(isType, "v", "any effect of this type", { onChange: () => { t.is_buff_type = isType.v ? 1 : 0; renderEditor(); } }));
  if (filt.v === "18") {
    const fid = String(Number(t.target_parameter) - 1000000000);
    filterBox.append(fid in tree.formulas ? formulaInput(tree, fid) : h("button", { class: "small", onclick: async () => { const f = await newFormula(tree); t.target_parameter = String(1000000000 + Number(f)); dirty(); renderEditor(); } }, "Write the formula…"));
  }
  return card("Targets", h("div", { class: "fields" },
    field("Who", selectInput(t, "target_type", SK.targetType, { onChange: renderEditor })),
    field("How many (0 = all)", numberInput(t, "target_number", { min: 0 })),
    field("Take the Nth after sorting", numberInput(t, "list_ranking", { min: 1 })),
    field("Special", selectInput(t, "target_priority", SK.priority)),
    field("If the target is lost", selectInput(r, "target_lost", SK.lost))),
    sortRows,
    field("Filter", h("div", {}, selectInput(filt, "v", SK.filter, { text: true, onChange: () => {
      if (filt.v === "none") { t.buff_trigger_type = 6; t.target_buff_id = 0; t.target_parameter = typeof t.target_parameter === "number" ? 0 : ""; }
      else t.buff_trigger_type = Number(filt.v);
      dirty(); renderEditor(); } }), filterBox)),
    h("div", { class: "row" },
      Number(t.target_type) === 1 ? checkbox(ign, "v", "Ignore range", { onChange: () => { t.is_ingore_range = ign.v ? 1 : 0; } }) : null,
      checkbox(all, "v", "Search the whole battlefield", { onChange: () => { t.is_search_all = all.v ? 1 : 0; } }),
      checkbox(shared, "v", "Use the echelon's shared target", { onChange: () => { r.is_re_target = shared.v ? 1 : 0; } })));
}

// ------------------------------------------------------------------ effects

function writePairs(row, a, b, list) {
  row[a] = list.map(x => x.id).join(",");
  row[b] = list.map(x => x.extra).join(",");
  dirty();
}

/** Buffs listed in a "buffId:stacks" field (skills, hits). */
function buffList(tree, row, key, visited) {
  const box = h("div");
  const draw = () => {
    const list = String(row[key] || "").split(",").map(x => x.trim()).filter(Boolean).map(x => ({ id: x.split(":")[0], stacks: x.split(":")[1] ?? "1" })).filter(b => b.id !== "0");
    const write = () => { row[key] = list.map(x => `${x.id}:${x.stacks}`).join(","); dirty(); };
    box.replaceChildren(...list.map((b, i) => buffCard(tree, b.id, { stacks: b, onStacks: write, onRemove: () => { list.splice(i, 1); write(); draw(); } }, visited)),
      h("div", { class: "row" }, h("button", { class: "small", onclick: () => { const id = newBuff(tree, 500); list.push({ id, stacks: "1" }); write(); draw(); } }, "+ Effect"),
        h("button", { class: "small", onclick: async () => { const id = await pickExistingBuff(tree); if (id) { list.push({ id, stacks: "1" }); write(); draw(); } } }, "Use an existing effect…"),
        h("button", { class: "small", onclick: async () => { const id = await copyBuffFrom(tree); if (id) { list.push({ id, stacks: "1" }); write(); draw(); } } }, "Copy an effect from another skill…")));
  };
  draw();
  return box;
}

function newBuff(tree, type) {
  const id = newTemp();
  const info = SK.buff[type] || ["", "parameter_value"];
  tree.buffs[id] = Object.assign(blankOf("battle_buff"), { id: Number(id), type, conflict_type: 9000000 + Math.floor(Math.random() * 900000),
    max_tier: 1, duration: "150", boss_available: 1, [info[1]]: info[2] === "%" ? "120" : info[2] === "none" ? "" : "10" });
  dirty();
  return id;
}

/** Refer to a buff by id (for example a marker another skill of the kit checks); not copied unless edited. */
async function pickExistingBuff(tree) {
  const v = prompt("Effect id (for example a marker given by another skill of this unit):");
  if (!v || !/^\d+$/.test(v.trim())) return null;
  const row = await api(`row/battle_buff/${v.trim()}`);
  if (!row) { toast("No such effect"); return null; }
  tree.buffs[v.trim()] ||= row;
  return v.trim();
}

function newCreation(tree) {
  const id = newTemp();
  tree.creations[id] = Object.assign(blankOf("battle_creation"), { id: Number(id), start_type: "6", destination_type: "6", route_type: 0,
    exist_duration: "30", effect_type: 2, effect_area: 1, effect_param_1: "2.5", scale: "1", is_form_offset: 1, is_form_offset_start: 1 });
  dirty();
  return id;
}

function newHurt(tree) {
  const id = newTemp();
  tree.hurts[id] = Object.assign(blankOf("battle_hurt_config"), { id: Number(id), damage_ratio: "100", is_miss: 1, hit_type: 1,
    is_critical_hit: 1, is_armor: 1, float_wide: 15, is_form_hurt: 1, buff_rate: "100" });
  dirty();
  return id;
}

async function copyCreationFrom(tree) {
  const g = await pickDialog("skill", "Copy an object from which skill?");
  if (g === null) return null;
  const other = await api(`design/skill/${g}`);
  const top = idList(other.action && other.action.creation_order)[0] || Object.keys(other.creations)[0];
  if (!top) { toast("That skill has no objects"); return null; }
  mergeTree(tree, other);
  return top;
}

async function copyBuffFrom(tree) {
  const g = await pickDialog("skill", "Copy an effect from which skill?");
  if (g === null) return null;
  const other = await api(`design/skill/${g}`);
  const id = idList(other.row.buff_id_target || other.row.buff_id_self).map(x => x.split(":")[0])[0] || Object.keys(other.buffs)[0];
  if (!id) { toast("That skill gives no effects"); return null; }
  mergeTree(tree, other);
  return id;
}

function mergeTree(tree, other) {
  for (const part of ["creations", "hurts", "buffs", "triggers", "watches", "watch_triggers"]) for (const [k, v] of Object.entries(other[part] || {})) if (!(k in (tree[part] ||= {}))) tree[part][k] = v;
  Object.assign(tree.formulas, other.formulas || {});
  // pool references inside copied pieces read this skill's numbers: bring the other skill's lists along when this one has none
  for (const f of ["data_pool_1", "data_pool_2"]) if (!String(tree.pools[f] || "").trim()) tree.pools[f] = other.pools[f] || "";
  dirty();
}

/** Skills linked by an effect, watcher or hit: open, change or remove (they are separate skills). */
function skillLinks(obj, key, label, opts = {}) {
  const box = h("div", { class: "row" });
  const draw = async () => {
    const raw = idList(obj[key]);
    const groups = raw.map(x => opts.rowIds ? String(Math.floor(Number(x) / 100)) : x);
    const n = groups.length ? await lookupNames("skill", groups) : {};
    const descs = await Promise.all(groups.map(skillDesc));
    box.replaceChildren(h("span", { class: "muted small" }, label), ...groups.map((g, i) => h("span", { class: "pill", title: descs[i] }, `${n[g] || "skill"} · ${g} `,
      h("button", { class: "small", onclick: () => openEntity("skill", g) }, "Open"),
      h("button", { class: "small danger", onclick: () => { raw.splice(i, 1); obj[key] = raw.join(","); dirty(); draw(); } }, "✕"))),
      opts.single && raw.length ? null : h("button", { class: "small", onclick: async () => {
        const g = await pickDialog("skill", label); if (g === null) return;
        raw.push(opts.rowIds ? String(Number(g) * 100 + 10) : String(g)); obj[key] = raw.join(","); dirty(); draw(); } }, "+"));
  };
  draw();
  return box;
}

function buffCard(tree, id, ctx, visited) {
  const b = tree.buffs[id];
  const remove = ctx.onRemove ? h("button", { class: "small danger", onclick: ctx.onRemove }, "✕") : null;
  if (!b) return h("div", { class: "node missing" }, `Effect ${id} (not in the game data)`, remove);
  if (visited.has("b" + id)) return h("div", { class: "node muted" }, `${buffLabel(b.type)} · effect ${id} (shown above)`, remove);
  visited = new Set(visited); visited.add("b" + id);
  const info = SK.buff[b.type] || [`Effect type ${b.type}`, "parameter_value", "raw"];
  const typeChoices = {};
  for (const [k, v] of Object.entries(SK.buff)) typeChoices[k] = v[0];
  const valHint = info[2] === "%" ? "100 = no change, 130 = +30%, 70 = −30%" : info[2] === "flat" ? "added per stack" : info[2] === "points" ? "points" : "";
  const bosses = { v: Number(b.boss_available) === 1 }, locked = { v: String(b.buff_sp_attributes || "") === "1" };
  const children = h("div", { class: "children" });
  const drawKids = () => {
    const list = idList(b.trigger_creation_id);
    children.replaceChildren(...list.map((cid, i) => creationCard(tree, cid, { label: "While active", onRemove: () => { list.splice(i, 1); b.trigger_creation_id = list.join(","); dirty(); drawKids(); } }, visited, 1)));
  };
  drawKids();
  const watchId = idList(b.watch_id)[0];
  return h("div", { class: "node buff" },
    h("div", { class: "node-head" }, h("strong", {}, info[0]), h("span", { class: "muted small" }, ` effect ${id}`), remove),
    h("div", { class: "fields" },
      field("Effect", selectInput(b, "type", typeChoices, { onChange: renderEditor })),
      info[2] !== "none" ? field("Value", valueInput(tree, b, info[1]), valHint) : null,
      Number(b.type) === 402 ? field("Damage taken becomes", valueInput(tree, b, "fix_damage"), "Formula; $1 = the damage") : null,
      field("Duration", secondsInput(b, "duration", { hint: "s (-1 = until removed)", tree })),
      ctx.stacks ? field("Stacks given", h("input", { type: "text", value: ctx.stacks.stacks, style: "width:80px", oninput: (ev) => { ctx.stacks.stacks = ev.target.value; ctx.onStacks(); } }), "0 = magazine size; negative removes stacks.") : null,
      field("Max stacks", numberInput(b, "max_tier", { min: 1 })),
      field("Stacking group", numberInput(b, "conflict_type"), "Effects of the same kind and group share one stack count."),
      field("Only for", textInput(b, "available_gun_type", { placeholder: "everyone" }), "Classes 1–6 (HG…SG), 101+ Coalition tags, 201–203 Coalition ranks."),
      checkbox(bosses, "v", "Works on bosses", { onChange: () => { b.boss_available = bosses.v ? 1 : 0; } }),
      checkbox(locked, "v", "Cannot be cleansed", { onChange: () => { b.buff_sp_attributes = locked.v ? "1" : ""; } })),
    h("div", { class: "sub" }, skillLinks(b, "forced_skill", "Gives these skills while active:")),
    [132, 133, 134].includes(Number(b.type)) ? h("div", { class: "sub" }, skillLinks(b, "orb_effect", "Adds this skill to the unit's attacks:", { rowIds: true, single: true })) : null,
    h("div", { class: "sub" }, h("div", { class: "subhead" }, "Watcher"),
      watchId ? watcherCard(tree, watchId, () => { b.watch_id = typeof b.watch_id === "number" ? 0 : "0"; dirty(); renderEditor(); }, visited)
              : h("button", { class: "small", onclick: () => { const wid = newTemp(); tree.watches[wid] = Object.assign(blankOf("battle_watch"), { id: Number(wid), watch_trigger_type: 1, watch_sp_trigger: "0", activation_skills: "", sp_skill_target: "" }); b.watch_id = typeof b.watch_id === "number" ? Number(wid) : wid; dirty(); renderEditor(); } }, "+ Watcher (cast skills when something happens)")),
    children);
}

function watcherCard(tree, wid, onRemove, visited) {
  const wch = tree.watches[wid];
  if (!wch) return h("div", { class: "node missing" }, `Watcher ${wid} (not in the game data)`, h("button", { class: "small danger", onclick: onRemove }, "✕"));
  const once = { v: Number(wch.max_times) === 1 }, delBuff = { v: Number(wch.if_delete_buff) === 1 };
  const trigId = idList(wch.activation_watch_trigger)[0];
  const skillsBox = h("div");
  const drawSkills = async () => {
    const list = idList(wch.activation_skills), targets = String(wch.sp_skill_target || "").split(",").map(x => x.trim());
    const n = list.length ? await lookupNames("skill", list) : {};
    const write = () => { wch.activation_skills = list.join(","); wch.sp_skill_target = list.map((_, i) => targets[i] || "0").join(","); dirty(); };
    skillsBox.replaceChildren(...list.map((g, i) => {
      const tg = { v: targets[i] || "0" };
      return h("div", { class: "row cond" }, h("span", { class: "pill", title: S.skillIndex && (S.skillIndex[String(g)] || {}).desc || "" }, `${n[g] || "skill"} · ${g}`),
        h("span", { class: "muted small" }, "aimed at"), selectInput(tg, "v", SK.watchTarget, { text: true, onChange: () => { targets[i] = tg.v; write(); } }),
        h("button", { class: "small", onclick: () => openEntity("skill", g) }, "Open"),
        h("button", { class: "small danger", onclick: () => { list.splice(i, 1); targets.splice(i, 1); write(); drawSkills(); } }, "✕"));
    }), h("button", { class: "small", onclick: async () => { const g = await pickDialog("skill", "Skill the watcher casts"); if (g !== null) { list.push(String(g)); targets.push("0"); write(); drawSkills(); } } }, "+ Skill to cast"));
  };
  drawSkills();
  return h("div", { class: "node watch" },
    h("div", { class: "node-head" }, h("strong", {}, "Watcher"), h("span", { class: "muted small" }, ` ${wid}`), h("button", { class: "small danger", onclick: onRemove }, "✕")),
    h("div", { class: "fields" },
      field("When", selectInput(wch, "watch_trigger_type", SK.watchEvent, { onChange: renderEditor })),
      checkbox(once, "v", "Only once", { onChange: () => { wch.max_times = once.v ? 1 : 0; } }),
      checkbox(delBuff, "v", "Remove the effect when the watcher ends", { onChange: () => { wch.if_delete_buff = delBuff.v ? 1 : 0; } }),
      Number(wch.record_chara1) ? field("Remembers (formula, read as a record in other formulas)", valueInput(tree, wch, "record_chara1")) : null),
    h("div", { class: "sub" }, h("div", { class: "subhead" }, "The event must match"),
      trigId ? watchTriggerCard(tree, trigId, Number(wch.watch_trigger_type))
             : h("button", { class: "small", onclick: () => { const id = newTemp(); tree.watch_triggers[id] = Object.assign(blankOf("battle_watch_trigger"), { id: Number(id), hurt_from: "0", available_gun_type: "0", hurt_type: "0" }); wch.activation_watch_trigger = Number(id); dirty(); renderEditor(); } }, "+ Event condition")),
    h("div", { class: "sub" }, h("div", { class: "subhead" }, "And these must be true"), conditionList(tree, wch, "watch_sp_trigger")),
    h("div", { class: "sub" }, h("div", { class: "subhead" }, "Then cast"), skillsBox));
}

function watchTriggerCard(tree, id, event) {
  const t = tree.watch_triggers[id];
  if (!t) return h("span", { class: "muted" }, `event condition ${id} (missing)`);
  const body = { v: Number(t.is_hurt_body) === 1 };
  const items = [];
  if (event === 1) items.push(field("Buff change counts when", Number(t.buff_judge) ? valueInput(tree, t, "buff_judge") :
    h("button", { class: "small", onclick: async () => { const f = await newFormula(tree); t.buff_judge = 1000000000 + Number(f); dirty(); renderEditor(); } }, "Write a formula…")));
  if (event === 2 || event === 3 || event === 5) {
    items.push(field("Damage counts when", Number(t.hurt_judge) > 1000000000 ? valueInput(tree, t, "hurt_judge") :
      h("button", { class: "small", onclick: async () => { const f = await newFormula(tree); t.hurt_judge = 1000000000 + Number(f); dirty(); renderEditor(); } }, "Write a formula…")));
    items.push(field("Hit results that count", textInput(t, "hurt_type"), "0 any; 1 stopped by armor, 2 armor pierced, 3 pierced and critical (comma list)."));
    items.push(field("Damage sources", textInput(t, "hurt_from"), "0 = any."));
    items.push(checkbox(body, "v", "Damage must reach HP", { onChange: () => { t.is_hurt_body = body.v ? 1 : 0; } }));
  }
  if (event === 4) {
    items.push(field("Skill kind (0 = any)", selectInput(t, "watched_skill_type", Object.assign({ 0: "Any" }, SK.types))));
    items.push(field("Skill (0 = any)", numberInput(t, "watched_skill_group_id")));
  }
  return h("div", { class: "fields" }, ...(items.length ? items : [h("span", { class: "muted small" }, "No extra condition for this event.")]));
}

// ------------------------------------------------------------------ objects

function objectsCard(tree) {
  const a = tree.action ||= Object.assign(blankOf("battle_action_config"), { id: Number(newTemp()), action_delay: "-1", action_playspeed: "100", effect_order: "1", effect_duration: "1" });
  const cutin = { v: String(a.effect_order || "").split(",").includes("1") };
  const objs = h("div");
  const drawObjs = () => {
    const list = pairs(a, "creation_order", "creation_delay");
    objs.replaceChildren(...list.map((o, i) => creationCard(tree, o.id, {
      delayLabel: "Starts after", delay: { v: secs(o.extra) },
      onDelay: (sec) => { list[i].extra = String(Math.round(sec * 30)); writePairs(a, "creation_order", "creation_delay", list); },
      onRemove: () => { list.splice(i, 1); writePairs(a, "creation_order", "creation_delay", list); drawObjs(); } }, new Set(), 0)),
      h("div", { class: "row" }, h("button", { class: "small", onclick: () => { const id = newCreation(tree); list.push({ id, extra: "0" }); writePairs(a, "creation_order", "creation_delay", list); drawObjs(); } }, "+ Object (strike, zone, projectile)"),
        h("button", { class: "small", onclick: async () => { const id = await copyCreationFrom(tree); if (id) { list.push({ id, extra: "0" }); writePairs(a, "creation_order", "creation_delay", list); drawObjs(); } } }, "Copy an object from another skill…")));
  };
  drawObjs();
  const extras = [];
  if (String(a.summon_order || "").trim() && a.summon_order !== "0") extras.push(`summons ${a.summon_order}`);
  if (String(a.move_order || "").trim() && a.move_order !== "0") extras.push(`movements ${a.move_order}`);
  return card("Animation and objects", h("div", { class: "fields" },
    field("Animation", textInput(a, "action_order"), "Chibi animation: attack, s (skill pose), 2 (throw)… empty = none."),
    checkbox(cutin, "v", "Show the skill cut-in", { onChange: () => { a.effect_order = cutin.v ? "1" : ""; a.effect_duration = cutin.v ? "1" : ""; a.effect_delay = cutin.v ? "0" : ""; } })),
    extras.length ? h("p", { class: "muted small" }, `The timeline also has ${extras.join(" and ")} (kept as they are).`) : null,
    h("p", { class: "muted small" }, "Objects are what the skill creates: bullets, thrown grenades, explosions and zones. They deal the hits and hand out area effects."), objs);
}

function creationCard(tree, id, ctx, visited, depth) {
  const c = tree.creations[id];
  const remove = ctx.onRemove ? h("button", { class: "small danger", onclick: ctx.onRemove }, "✕") : null;
  if (!c) return h("div", { class: "node missing" }, `Object ${id} (not in the game data)`, remove);
  if (visited.has("c" + id) || depth > 6) return h("div", { class: "node muted" }, `Object ${id} (shown above)`, remove);
  visited = new Set(visited); visited.add("c" + id);
  const homing = { v: Number(c.is_tracing) === 1 }, perLink = { v: Number(c.is_form_play) === 1 }, single = { v: Number(c.is_single_hurt) === 1 };
  const area = Number(c.effect_area);
  const kind = c.hurt_id ? "Strike" : c.buff_id ? "Zone" : c.code ? "Visual effect" : "Invisible object";
  const hits = h("div"), zone = h("div"), kids = h("div");
  const drawHits = () => {
    const list = pairs(c, "hurt_id", "hurt_cd");
    hits.replaceChildren(...list.map((x, i) => hurtCard(tree, x.id, { every: x, onEvery: () => writePairs(c, "hurt_id", "hurt_cd", list),
      onRemove: () => { list.splice(i, 1); writePairs(c, "hurt_id", "hurt_cd", list); drawHits(); } }, visited)),
      h("button", { class: "small", onclick: () => { list.push({ id: newHurt(tree), extra: "0" }); writePairs(c, "hurt_id", "hurt_cd", list); drawHits(); } }, "+ Hit"));
  };
  const drawZone = () => {
    const list = pairs(c, "buff_id", "buff_cd").map(x => ({ id: x.id, extra: x.extra, stacks: String(c.buff_id).split(",").find(p => p.split(":")[0] === x.id)?.split(":")[1] }));
    const write = () => { c.buff_id = list.map(x => x.stacks !== undefined ? `${x.id}:${x.stacks}` : x.id).join(","); c.buff_cd = list.map(x => x.extra || "0").join(","); dirty(); };
    zone.replaceChildren(...list.map((x, i) => h("div", {}, h("div", { class: "row small" }, h("span", { class: "muted" }, "Given every"),
      secondsInput(x, "extra", { hint: "s (0 = once)" })), buffCard(tree, x.id, { onRemove: () => { list.splice(i, 1); write(); drawZone(); } }, visited))),
      h("button", { class: "small", onclick: () => { list.push({ id: newBuff(tree, 204), extra: "30" }); write(); drawZone(); } }, "+ Area effect"));
  };
  const drawKids = () => {
    const list = pairs(c, "trigger_creation_id", "trigger_creation_delay");
    kids.replaceChildren(...list.map((x, i) => creationCard(tree, x.id, { delayLabel: "Then, after", delay: { v: Number(x.extra) === -1 ? -1 : secs(x.extra) },
      onDelay: (sec) => { list[i].extra = sec === -1 ? "-1" : String(Math.round(sec * 30)); writePairs(c, "trigger_creation_id", "trigger_creation_delay", list); },
      onRemove: () => { list.splice(i, 1); writePairs(c, "trigger_creation_id", "trigger_creation_delay", list); drawKids(); } }, visited, depth + 1)),
      h("button", { class: "small", onclick: () => { list.push({ id: newCreation(tree), extra: "-1" }); writePairs(c, "trigger_creation_id", "trigger_creation_delay", list); drawKids(); } }, "+ Follow-up object"));
  };
  drawHits(); drawZone(); drawKids();
  const delay = ctx.delay ? h("span", { class: "row small" }, h("span", { class: "muted" }, ctx.delayLabel),
    (() => { const el = h("input", { type: "number", step: "any", value: ctx.delay.v, style: "width:80px" }); el.addEventListener("input", () => ctx.onDelay(parseFloat(el.value) || 0)); return el; })(),
    h("span", { class: "muted" }, ctx.delayLabel === "Then, after" ? "s (-1 = when this one ends or hits)" : "s")) : null;
  return h("div", { class: `node creation depth${Math.min(depth, 3)}` },
    h("div", { class: "node-head" }, h("strong", {}, ctx.label ? `${ctx.label}: ${kind}` : kind), h("span", { class: "muted small" }, ` object ${id}`), delay, remove),
    h("div", { class: "fields" },
      field("Looks like", textInput(c, "code"), "Effect name from the game; empty = invisible."),
      field("Starts at", selectInput(c, "start_type", SK.start, { text: true, other: modelPoint })),
      field("Goes to", selectInput(c, "destination_type", SK.start, { text: true, other: modelPoint })),
      field("Movement", selectInput(c, "route_type", SK.route)),
      [1, 2, 5, 6].includes(Number(c.route_type)) ? field("Speed", numberInput(c, "speed")) : null,
      Number(c.route_type) === 2 ? field("Arc height", numberInput(c, "route_hight")) : null,
      field("Lasts", secondsInput(c, "exist_duration", { hint: "s", tree })),
      field("Area", selectInput(c, "effect_area", SK.area, { onChange: renderEditor })),
      area === 1 ? field("Radius", valueInput(tree, c, "effect_param_1"), "A formation tile is 2.4 × 4.2.") : null,
      area === 1 && String(c.effect_param_2 || "0") !== "0" ? field("Cone half-angle", valueInput(tree, c, "effect_param_2")) : null,
      area === 2 || area === 4 ? field("Width", valueInput(tree, c, "effect_param_1")) : null,
      area === 2 || area === 4 ? field("Height", valueInput(tree, c, "effect_param_2")) : null,
      area === 3 ? field("Tiles (1–25)", textInput(c, "effect_param_1")) : null,
      area ? field("Affects", selectInput(c, "effect_type", SK.affects)) : null,
      field("Hands out its area effects at most", numberInput(c, "active_times", { min: 0 }), "times (0 = no limit)"),
      checkbox(homing, "v", "Homing", { onChange: () => { c.is_tracing = homing.v ? 1 : 0; } }),
      checkbox(single, "v", "Hits each unit once (piercing)", { onChange: () => { c.is_single_hurt = single.v ? 1 : 0; } }),
      checkbox(perLink, "v", "One per dummy link", { onChange: () => { c.is_form_play = perLink.v ? 1 : 0; } })),
    String(c.summoner_order || "").trim() && c.summoner_order !== "0" ? h("p", { class: "muted small" }, `Summons ${c.summoner_order} (kept as is).`) : null,
    h("div", { class: "sub" }, h("div", { class: "subhead" }, "Hits"), hits),
    h("div", { class: "sub" }, h("div", { class: "subhead" }, "Area effects"), zone),
    h("div", { class: "sub" }, h("div", { class: "subhead" }, "Follow-up objects"), kids));
}

function hurtCard(tree, id, ctx, visited) {
  const x = tree.hurts[id];
  if (!x) return h("div", { class: "node missing" }, `Hit ${id} (not in the game data)`);
  const miss = { v: Number(x.is_miss) === 1 }, armor = { v: Number(x.is_armor) === 1 }, links = { v: Number(x.is_form_hurt) === 1 };
  return h("div", { class: "node hurt" },
    h("div", { class: "node-head" }, h("strong", {}, "Hit"), h("span", { class: "muted small" }, ` hit ${id}`),
      h("span", { class: "row small" }, h("span", { class: "muted" }, "repeats every"), secondsInput(ctx.every, "extra", { hint: "s (0 = once)" })),
      h("button", { class: "small danger", onclick: ctx.onRemove }, "✕")),
    h("div", { class: "fields" },
      field("Damage %", valueInput(tree, x, "damage_ratio"), "Of the user's damage; 100 = a normal shot."),
      String(x.fix_damage || "").trim() && x.fix_damage !== "0" ? field("Damage then becomes", valueInput(tree, x, "fix_damage"), "Formula; $1 = damage so far, $2 = critical") : null,
      field("Critical hits", selectInput(x, "is_critical_hit", SK.crit)),
      field("Accuracy roll", selectInput(x, "hit_type", SK.hitType)),
      field("Ignores Force Shield %", numberInput(x, "is_ricochet")),
      field("Goes through barriers %", numberInput(x, "is_shield")),
      field("Damage spread ± %", numberInput(x, "float_wide")),
      field("Knock-back chance %", numberInput(x, "beat_back_percent")),
      checkbox(miss, "v", "Can miss", { onChange: () => { x.is_miss = miss.v ? 1 : 0; } }),
      checkbox(armor, "v", "Armor applies", { onChange: () => { x.is_armor = armor.v ? 1 : 0; } }),
      checkbox(links, "v", "Hits every dummy link (area)", { onChange: () => { x.is_form_hurt = links.v ? 1 : 0; } })),
    Number(x.beat_back_percent) ? h("div", { class: "sub" }, skillLinks(x, "target_skill", "Skill the target is made to use (knock-back):", { single: true })) : null,
    h("div", { class: "sub" }, h("div", { class: "subhead" }, "Effects on whoever is hit"),
      h("div", { class: "fields" }, field("Chance %", textInput(x, "buff_rate")), field("When", selectInput(x, "hurt_buff_trigger_type", SK.hurtWhen))),
      buffList(tree, x, "buff_id_target", visited)),
    h("div", { class: "sub" }, h("div", { class: "subhead" }, "Effects on the attacker"), buffList(tree, x, "buff_id_self", visited)),
    String(x.range_buff_target || x.range_buff_self || "").trim() ? h("div", { class: "sub" }, h("div", { class: "subhead" }, "Once per attack (area)"),
      buffList(tree, x, "range_buff_target", visited), buffList(tree, x, "range_buff_self", visited)) : null);
}
