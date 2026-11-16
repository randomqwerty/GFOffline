/* Mod Studio front end: shell, shared widgets, and the T-Doll / Coalition / enemy / team editors.
   map.js adds the map editor, skills.js the skill editor. Talks to studio.py (/api/...). */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false)
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
};

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch("/api/" + path, opt);
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

const S = { meta: null, L: null, mod: null, summary: null, ent: null, catalogs: {}, names: {}, dirty: false };

const KINDS = {
  unit: { label: "T-Dolls", catalog: "gun", one: "T-Doll" },
  sangvis: { label: "Coalition units", catalog: "sangvis", one: "Coalition unit" },
  enemy: { label: "Enemies", catalog: "enemy", one: "enemy" },
  team: { label: "Enemy teams", catalog: "team", one: "enemy team" },
  map: { label: "Maps", catalog: "mission", one: "map" },
  skill: { label: "Skills", catalog: "skill", one: "skill" },
  story: { label: "Story text", catalog: "story", one: "story file" },
  event: { label: "Event listings", one: "event" },
  text: { label: "Game text (names, descriptions)", one: "text" },
  row: { label: "Other game data (advanced)", one: "entry" },
};
const NAME_TABLE = { skill: "skill", enemy: "enemy_character_type", team: "enemy_team", gun: "gun", sangvis: "sangvis", mission: "mission" };
const dirty = () => { S.dirty = true; };
const num = (v) => (v === "" || v === null || v === undefined || isNaN(+v)) ? 0 : +v;

// ------------------------------------------------------------------ data helpers

async function catalog(kind) {
  if (!S.catalogs[kind]) S.catalogs[kind] = kind.startsWith("models_") ? await api("models/" + kind.slice(7)) : await api("catalog/" + kind);
  return S.catalogs[kind];
}

async function lookupNames(kind, ids) {
  const table = NAME_TABLE[kind] || kind;
  const cache = (S.names[table] ||= {});
  const need = [...new Set(ids.map(String))].filter(i => i && i !== "0" && !(i in cache));
  if (need.length) Object.assign(cache, await api(`names?table=${table}&ids=${need.join(",")}`));
  return cache;
}

// ------------------------------------------------------------------ widgets

/** A labelled control with an optional help line. */
function field(label, control, help) {
  return h("div", { class: "field" }, h("label", {}, label), control, help ? h("div", { class: "doc" }, help) : null);
}

function numberInput(obj, key, opts = {}) {
  const el = h("input", { type: "number", step: opts.step || "1", min: opts.min, max: opts.max });
  el.value = obj[key] ?? "";
  el.addEventListener("input", () => { obj[key] = el.value === "" ? 0 : (opts.step === "any" ? parseFloat(el.value) : parseInt(el.value, 10)); dirty(); opts.onChange && opts.onChange(); });
  return el;
}

function textInput(obj, key, opts = {}) {
  const el = opts.area ? h("textarea", { rows: opts.rows || 3, placeholder: opts.placeholder || "" }) : h("input", { type: "text", placeholder: opts.placeholder || "" });
  el.value = obj[key] ?? "";
  el.addEventListener("input", () => { obj[key] = el.value; dirty(); opts.onChange && opts.onChange(); });
  return el;
}

function selectInput(obj, key, choices, opts = {}) {
  const el = h("select", {}, Object.entries(choices).map(([v, label]) => h("option", { value: v }, label)));
  el.value = String(obj[key] ?? "");
  if (el.value !== String(obj[key] ?? "") && obj[key] !== undefined) { el.append(h("option", { value: obj[key] }, opts.other ? opts.other(obj[key]) : `${obj[key]} (kept as it is)`)); el.value = String(obj[key]); }
  el.addEventListener("change", () => { const v = el.value; obj[key] = /^-?\d+$/.test(v) && !opts.text ? parseInt(v, 10) : v; dirty(); opts.onChange && opts.onChange(); });
  return el;
}

function checkbox(obj, key, label, opts = {}) {
  const el = h("input", { type: "checkbox" });
  el.checked = !!obj[key];
  el.addEventListener("change", () => { obj[key] = el.checked; dirty(); opts.onChange && opts.onChange(); });
  return h("label", { class: "check" }, el, " " + label);
}

function card(title, ...kids) {
  return h("div", { class: "card" }, title ? h("h3", {}, title) : null, ...kids);
}

/** One skill slot: shows the skill's name, pick / open / clear. */
function skillSlot(obj, key, label, help) {
  const name = h("span", { class: "ref" });
  const show = async () => {
    const id = obj[key];
    if (!id) { name.textContent = "none"; return; }
    const n = await lookupNames("skill", [id]);
    name.textContent = `${n[id] || "(unnamed)"} · ${id}`;
  };
  show();
  return field(label, h("div", { class: "row" }, name,
    h("button", { class: "small", onclick: async () => { const id = await pickDialog("skill", `Pick ${label.toLowerCase()}`); if (id !== null) { obj[key] = Number(id); dirty(); show(); } } }, "Pick…"),
    h("button", { class: "small", title: "Open this skill in the skill editor", onclick: () => obj[key] && openEntity("skill", obj[key]) }, "Open"),
    h("button", { class: "small", onclick: () => { obj[key] = 0; dirty(); show(); } }, "Clear")), help);
}

/** A list of skills (passives). */
function skillList(obj, key, label, help) {
  const box = h("div", { class: "row" });
  const render = async () => {
    const ids = obj[key] || [];
    const n = await lookupNames("skill", ids);
    box.replaceChildren(...ids.map((id, i) => h("span", { class: "pill" }, `${n[id] || "(unnamed)"} · ${id} `,
      h("button", { class: "small", onclick: () => { obj[key].splice(i, 1); dirty(); render(); } }, "✕"))),
      h("button", { class: "small", onclick: async () => { const id = await pickDialog("skill", `Add to ${label.toLowerCase()}`); if (id !== null) { (obj[key] ||= []).push(Number(id)); dirty(); render(); } } }, "+ Add"));
  };
  render();
  return field(label, box, help);
}

/** Model / art: one code shared by every unit drawn with it. */
function modelSlot(obj, kind) {
  const name = h("span", { class: "ref" }, obj.model || "none");
  return field("Model / art", h("div", { class: "row" }, name,
    h("button", { class: "small", onclick: async () => { const code = await pickDialog("models_" + kind, "Pick a model (art, animations and voice come with it)"); if (code !== null) { obj.model = code; name.textContent = code; dirty(); } } }, "Pick…")),
    "Uses the art of an existing unit (new art needs new asset bundles, not supported yet).");
}

// ------------------------------------------------------------------ game options

async function openAllMods() {
  if (S.dirty && !(await confirmDialog("Discard unsaved changes?"))) return;
  S.ent = null; S.dirty = false;
  renderSide();
  const list = await api("mods");
  $("#editor").replaceChildren(h("h2", {}, "Turn mods on or off"),
    h("p", { class: "muted" }, "Each mod is separate, so people can use any mix of them. After changing these, press Build mods and restart the server: the game downloads the new data at the next login."),
    h("p", { class: "muted" }, "To add a mod someone shared with you, use Add a mod on the launcher's Tools tab. To share one of yours, pick it and press Export to share."),
    card("", list.map(m => {
      const on = h("input", { type: "checkbox" });
      on.checked = m.enabled !== false;
      on.addEventListener("change", async () => {
        await api(`mod/${m.dir}/settings`, { enabled: on.checked });
        toast(`${m.name} is ${on.checked ? "on" : "off"}. Press Build mods when you're done.`);
        loadMods(S.mod);
      });
      return h("div", { class: "field" }, h("label", { class: "check" }, on, " " + m.name), m.description || m._comment ? h("div", { class: "doc" }, m.description || m._comment) : null);
    })));
}

// ------------------------------------------------------------------ story text, event listings, game text

function storyEditor(e) {
  const rows = e.rows.map((r, i) => {
    const text = h("textarea", { rows: Math.max(1, Math.min(4, Math.ceil(Math.max(r.text.length, r.original.length) / 60))) });
    text.value = r.text;
    text.addEventListener("input", () => { r.text = text.value; dirty(); });
    const speaker = r.cue.includes("<Speaker>") ? textInput(r, "speaker", { placeholder: "who speaks" }) : h("span", { class: "muted small" }, "narration");
    return h("tr", {}, h("td", { class: "muted small" }, i + 1), h("td", {}, speaker,
      r.original_speaker && r.original_speaker !== r.speaker ? h("div", { class: "muted small" }, r.original_speaker) : null),
      h("td", { class: "story-original" }, r.original), h("td", {}, text));
  });
  const problems = e.problems && e.problems.length ? h("ul", { class: "problems" }, e.problems.map(p => h("li", {}, p))) : null;
  return card("", problems,
    h("p", { class: "muted small" }, "Change the text on the right; music, backgrounds and effects stay as they are. A + in the text starts a new line in the game's text box."),
    h("table", { class: "story" }, h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, "Speaker"), h("th", {}, "The game's text"), h("th", {}, "This mod's text"))), h("tbody", {}, rows)));
}

function eventEditor(e) {
  const banner = h("span", { class: "ref" }, e.image || "none");
  const mapName = h("span", { class: "ref" }, e.first_map || "none");
  const showMap = async () => {
    if (!e.first_map) return;
    const m = (await catalog("mission")).find(r => String(r.id) === String(e.first_map));
    mapName.textContent = m ? `${m.name} · ${m.id} · campaign ${m.campaign}` : e.first_map;
  };
  showMap();
  return card("",
    h("p", { class: "muted small" }, "Lists an event's maps in the campaign menu, and can put it on the home screen. For maps in event campaigns (negative numbers), such as ones the game carries but doesn't list. Maps made here already appear in their mod's own chapter."),
    h("div", { class: "fields" },
      field("Event name", textInput(e, "name"), "Shown in the campaign menu."),
      field("Short name in the list", textInput(e, "list_name", { placeholder: "same as the event name" })),
      field("Description", textInput(e, "description", { area: true })),
      field("First map", h("div", { class: "row" }, mapName, h("button", { class: "small", onclick: async () => { const id = await pickDialog("mission", "Pick the event's first map"); if (id !== null) { e.first_map = Number(id); dirty(); showMap(); } } }, "Pick…"))),
      field("Banner picture", h("div", { class: "row" }, banner, h("button", { class: "small", onclick: async () => { const id = await pickDialog("event_image", "Pick a picture"); if (id !== null) { e.image = id; banner.textContent = id; dirty(); } } }, "Pick…")),
        "New pictures can't be added yet, so this uses one the game has."),
      field("Group in the list", textInput(e, "group"), "Events with the same group are listed together, four to a page."),
      field("Group number", numberInput(e, "group_number", { min: 0 })),
      field("Place in the list", numberInput(e, "order", { min: 0 }), "Lower comes first."),
      field("", checkbox(e, "on_home", "Show on the home screen's banner bar")),
      field("", checkbox(e, "open_first_map", "Open the first map for the player"))));
}

function textEditor(e) {
  const list = h("tbody", {});
  const render = () => list.replaceChildren(...e.rows.map((r, i) => {
    const value = h("textarea", { rows: 2 });
    value.value = r.value;
    value.addEventListener("input", () => { r.value = value.value; dirty(); });
    return h("tr", {}, h("td", { class: "story-original" }, r.original || h("span", { class: "muted" }, "new text")), h("td", {}, value),
      h("td", {}, h("button", { class: "small", onclick: () => { e.rows.splice(i, 1); dirty(); render(); } }, "✕")));
  }));
  const search = h("input", { type: "search", placeholder: "Search the game's text, e.g. a doll's name…" });
  const found = h("div", { class: "pick-list" });
  search.addEventListener("input", async () => {
    const hits = search.value.trim().length < 2 ? [] : await api("text-search?q=" + encodeURIComponent(search.value.trim()));
    found.replaceChildren(...hits.map(t => h("button", { onclick: () => {
      if (!e.rows.some(r => r.key === t.key)) { e.rows.push({ key: t.key, original: t.text, value: t.text }); dirty(); render(); }
    } }, h("span", {}, t.text.slice(0, 120)))));
  });
  render();
  return h("div", {}, card("Change some of the game's text", search, found),
    card("", h("table", { class: "story" }, h("thead", {}, h("tr", {}, h("th", {}, "The game's text"), h("th", {}, "This mod's text"), h("th", {}, ""))), list)));
}

async function newStoryDialog() {
  const input = h("input", { type: "file", accept: ".txt", multiple: true });
  let close;
  input.addEventListener("change", async () => {
    try {
      const files = await Promise.all([...input.files].map(async f => ({ name: f.name, text: await f.text() })));
      const res = await api(`mod/${S.mod}/story-import`, { files });
      close();
      S.summary = await api("mod/" + S.mod);
      renderSide();
      const issues = Object.entries(res.problems);
      openDialog(h("h3", {}, `Added ${res.count} story file(s)`),
        issues.length ? h("ul", { class: "problems" }, issues.flatMap(([n, ps]) => ps.map(p => h("li", {}, `${n}: ${p}`)))) : h("p", {}, "They all match the game's stage cues."),
        h("div", { class: "row" }, h("button", { onclick: () => $("#dialog").classList.add("hidden") }, "Close")));
    } catch (err) { toast(err.message, 8000); }
  });
  close = openDialog(h("h3", {}, "Add story text"),
    h("p", { class: "muted" }, "Translate a story file here, or add text files you already have. Each file's name must match the game's, such as -14-1-1.txt."),
    h("div", { class: "row" }, h("button", { class: "primary", onclick: async () => {
      close();
      const name = await pickDialog("story", "Pick a story file");
      if (name !== null) showEditor(await api(`newdesign/story?from=${encodeURIComponent(name)}`));
    } }, "Pick a story file…")),
    field("Or add text files", input),
    h("div", { class: "row" }, h("button", { onclick: () => close() }, "Cancel")));
}

async function copyFromCnDialog() {
  const tables = Object.keys(S.meta.tables).sort();
  const sel = h("select", {}, tables.map(t => h("option", { value: t }, t)));
  sel.value = "mission";
  const ids = h("input", { type: "text", placeholder: "ids, separated by commas" });
  let close;
  close = openDialog(h("h3", {}, "Copy rows from the Chinese client (advanced)"),
    h("p", { class: "muted" }, "Some content is only in the Chinese client's tables, though this client still has its art and story. This copies whole rows into the mod; check them afterwards."),
    h("div", { class: "row" }, sel, ids),
    h("div", { class: "row" }, h("button", { class: "primary", onclick: async () => {
      try {
        const res = await api(`mod/${S.mod}/copy-cn`, { table: sel.value, ids: ids.value.split(",") });
        close();
        S.summary = await api("mod/" + S.mod);
        renderSide();
        toast(`Copied ${res.copied.length} row(s)` + (res.missing.length ? `; not found: ${res.missing.join(", ")}` : ""), 8000);
      } catch (err) { toast(err.message, 8000); }
    } }, "Copy"), h("button", { onclick: () => close() }, "Cancel")));
}

// ------------------------------------------------------------------ dialogs

function openDialog(...content) {
  const d = $("#dialog"), body = $("#dialog-body");
  body.replaceChildren(...content);
  d.classList.remove("hidden");
  return () => d.classList.add("hidden");
}

function pickDialog(kind, title) {
  return new Promise(async (resolve) => {
    const list = await catalog(kind);
    const search = h("input", { type: "search", placeholder: "Search by name, id or code…" });
    const box = h("div", { class: "pick-list" });
    let close;
    const done = (v) => { close(); resolve(v); };
    const render = () => {
      const q = search.value.trim().toLowerCase();
      const hits = list.filter(r => !q || String(r.id).toLowerCase().includes(q) || (r.name || "").toLowerCase().includes(q)
                                         || (r.code || "").toLowerCase().includes(q)).slice(0, 300);
      box.replaceChildren(...hits.map(r => h("button", { onclick: () => done(r.id) },
        h("span", { class: "id" }, r.id), h("span", {}, r.name || r.code || ""), h("span", { class: "sub" }, subLabel(kind, r)))));
      if (!hits.length) box.append(h("div", { class: "empty" }, "Nothing found"));
    };
    search.addEventListener("input", render);
    close = openDialog(h("h3", {}, title), search, box, h("div", { class: "row" }, h("button", { onclick: () => done(null) }, "Cancel")));
    render();
    search.focus();
  });
}

function subLabel(kind, r) {
  const T = { 1: "HG", 2: "SMG", 3: "RF", 4: "AR", 5: "MG", 6: "SG" };
  if (kind === "gun") return `${T[r.type] || r.type} ${r.rank}★ · ${r.code}`;
  if (kind === "sangvis" || kind === "enemy") return r.code;
  if (kind === "team") return `${r.members} enemies`;
  if (kind === "mission") return `${r.campaign}-${r.sub}` + (r.kind == 3 ? " night" : r.kind == 1 ? " emergency" : "");
  if (kind === "skill") return r.code;
  if (kind.startsWith("models_")) return r.code;
  return "";
}

function confirmDialog(msg) {
  return new Promise(resolve => {
    let close;
    const done = v => { close(); resolve(v); };
    close = openDialog(h("p", {}, msg), h("div", { class: "row" },
      h("button", { class: "primary", onclick: () => done(true) }, "OK"), h("button", { onclick: () => done(false) }, "Cancel")));
  });
}

async function newEntityDialog(kind) {
  if (!S.mod) return toast("Create or pick a mod first");
  if (kind === "row") return newRowDialog();
  if (kind === "story") return newStoryDialog();
  if (kind === "event") return showEditor(await api("newdesign/event"));
  if (kind === "text") return showEditor(await api(`design/text/all?mod=${S.mod}`));
  const k = KINDS[kind];
  let close;
  const go = async (from, extra = "") => {
    close();
    const d = await api(`newdesign/${kind}?` + (from !== null && from !== undefined ? `from=${from}` : "") + extra);
    showEditor(d);
  };
  const fromTemplate = h("button", { class: "primary", onclick: async () => { const id = await pickDialog(k.catalog, `Copy which ${k.one}?`); if (id !== null) go(id); } }, `Copy an existing ${k.one}…`);
  let scratch;
  if (kind === "unit") {
    scratch = h("div", { class: "row" }, h("span", { class: "muted" }, "New from scratch:"),
      ...Object.entries(S.L.gun_types).map(([t, label]) => h("button", { onclick: () => go(null, `&type=${t}`) }, label)));
  } else if (kind === "skill") {
    scratch = h("div", { class: "presets" }, ...S.L.skill_presets.map(p => h("button", { class: "preset", onclick: () => go(p.id || null) },
      h("strong", {}, p.name), h("span", { class: "muted small" }, p.about))));
  } else {
    scratch = h("button", { onclick: () => go(null) }, "Start from scratch");
  }
  close = openDialog(h("h3", {}, `New ${k.one}`),
    h("p", { class: "muted" }, kind === "skill" ? "Start from a common kind of skill, or copy any skill in the game and change it." :
      "Copy an existing one (then change what you like), or start from scratch."),
    h("div", { class: "row" }, fromTemplate), scratch, h("div", { class: "row" }, h("button", { onclick: () => close() }, "Cancel")));
}

function newRowDialog() {
  const tables = Object.keys(S.meta.tables).sort();
  const sel = h("select", {}, tables.map(t => h("option", { value: t }, t)));
  sel.value = "battle_buff";
  const key = h("input", { type: "text", placeholder: "copy this key (optional)" });
  let close;
  close = openDialog(h("h3", {}, "New row in any table (advanced)"),
    h("p", { class: "muted" }, "Raw table rows for things without their own editor. Fields are explained from the STC guide."),
    h("div", { class: "row" }, sel, key),
    S.cnData ? h("div", { class: "row" }, h("button", { onclick: () => { close(); copyFromCnDialog(); } }, "Copy from the Chinese client instead…")) : null,
    h("div", { class: "row" },
      h("button", { class: "primary", onclick: async () => {
        close();
        const tk = key.value.trim();
        const e = tk ? await api(`new/row?from=${encodeURIComponent(sel.value + ":" + tk)}`) : { kind: "row", table: sel.value, row: await blankRow(sel.value), copy: null };
        showEditor(e);
      } }, "Create"), h("button", { onclick: () => close() }, "Cancel")));
}

async function blankRow(table) {
  const row = {};
  for (const [f, t] of S.meta.tables[table]) row[f] = t === "string" ? "" : 0;
  row[S.meta.tables[table][0][0]] = (await api(`free/${table}`))[0];
  return row;
}

// ------------------------------------------------------------------ sidebar

async function loadMods(select) {
  const mods = await api("mods");
  const sel = $("#mod-select");
  sel.replaceChildren(h("option", { value: "" }, "— pick a mod —"), ...mods.map(m => h("option", { value: m.dir }, `${m.name}${m.enabled === false ? " (off)" : ""}`)));
  sel.value = select ?? S.mod ?? "";
  if (sel.value) await openMod(sel.value); else renderSide();
}

async function openMod(name) {
  S.mod = name || null;
  S.summary = name ? await api("mod/" + name) : null;
  renderSide();
}

function renderSide() {
  const box = $("#mod-settings"), list = $("#entity-list");
  if (!S.summary) { box.replaceChildren(h("span", { class: "muted" }, "No mod selected")); list.replaceChildren(); return; }
  const m = S.summary.meta, ch = S.summary.campaign || {};
  const save = (body) => api(`mod/${S.mod}/settings`, body).then(r => { S.summary = r; });
  const enabled = h("input", { type: "checkbox" });
  enabled.checked = m.enabled !== false;
  enabled.addEventListener("change", async () => { await save({ enabled: enabled.checked }); loadMods(S.mod); });
  const chName = h("input", { type: "text", placeholder: "Name in the Campaign tab" });
  chName.value = ch.name || m.name || "";
  chName.addEventListener("change", () => save({ campaign_name: chName.value }).then(renderSide));
  const chDesc = h("textarea", { rows: 2, placeholder: "Description (shown in the Campaign tab)" });
  chDesc.value = ch.description || "";
  chDesc.addEventListener("change", () => save({ campaign_description: chDesc.value }));
  const share = h("button", { class: "small", onclick: () => { window.location.href = `/api/mod/${encodeURIComponent(S.mod)}/export`; toast("Saved as a .zip in your downloads. Others add it with Add a mod in the launcher."); } }, "Export to share");
  box.replaceChildren(h("label", { class: "check" }, enabled, " Mod enabled"),
    field("Campaign tab entry", chName), chDesc,
    h("div", { class: "row" }, share, h("span", { class: "muted small" }, "One file to send to others")));
  list.replaceChildren();
  for (const [kind, k] of Object.entries(KINDS)) {
    const items = S.summary.entities[kind] || [];
    if (kind === "row" && !items.length && !S.advanced) continue;
    list.append(h("div", { class: "kind-head" }, k.label, h("button", { class: "small", onclick: () => newEntityDialog(kind) }, "+ New")));
    for (const it of items) {
      const active = S.ent && S.ent.kind === kind && String(entId(S.ent)) === String(it.id);
      list.append(h("button", { class: "ent" + (active ? " active" : ""), onclick: () => openEntity(kind, it.id) },
        h("span", { class: "id" }, it.show ?? it.id), it.name || ""));
    }
    if (!items.length) list.append(h("div", { class: "muted small", style: "padding:2px 8px" }, "none"));
  }
}

function entId(e) {
  if (!e) return null;
  if (e.kind === "skill") return e.group || e.id;
  if (e.kind === "row") return `${e.table}:${e.row[S.meta.tables[e.table][0][0]]}`;
  return e.id;
}

async function openEntity(kind, id) {
  if (S.dirty && !(await confirmDialog("Discard unsaved changes?"))) return;
  const e = kind === "row" ? await api(`entity/row/${encodeURIComponent(id)}?mod=${S.mod || ""}`)
                           : await api(`design/${kind}/${encodeURIComponent(id)}?mod=${S.mod || ""}`);
  showEditor(e);
}

// ------------------------------------------------------------------ editor frame

function showEditor(e) {
  S.ent = e;
  S.dirty = false;
  renderSide();
  renderEditor();
}

function renderEditor() {
  const e = S.ent, root = $("#editor");
  if (!e) { root.replaceChildren(h("div", { class: "empty" }, "Nothing open")); return; }
  if (e.render) { const y = window.scrollY; root.replaceChildren(e.render()); window.scrollTo(0, y); return; }   // a page of its own (mapconfig.js)
  const editors = { unit: dollEditor, sangvis: sangvisEditor, enemy: enemyEditor, team: teamEditor, map: window.mapEditor,
                    skill: window.skillEditor, row: rowEditor, story: storyEditor, event: eventEditor, text: textEditor };
  const y = window.scrollY;
  root.replaceChildren(editorHead(e), editors[e.kind](e));
  window.scrollTo(0, y);
}

function editorHead(e) {
  const k = KINDS[e.kind];
  const title = e.kind === "skill" ? (e.texts && e.texts.name) || "New skill" : e.kind === "row" ? entId(e)
    : (e.name || (e.in_mod || e.in_base ? `${k.one[0].toUpperCase()}${k.one.slice(1)} ${entId(e)}` : `New ${k.one}`));
  const tag = e.in_mod ? h("span", { class: "pill" }, "in this mod")
    : e.in_base ? h("span", { class: "pill warn" }, "game original: saving stores your changes in this mod")
    : h("span", { class: "pill warn" }, "not saved yet");
  return h("div", { class: "head" },
    h("div", {}, h("h2", {}, title), h("div", {}, h("span", { class: "muted small" }, `${k.one} ${entId(e) || ""} `), tag),
      h("div", { id: "problems" })),
    h("div", { class: "row" },
      e.in_mod ? h("button", { class: "danger", onclick: deleteCurrent }, "Delete") : null,
      h("button", { class: "primary", onclick: saveCurrent }, "Save to mod")));
}

async function saveCurrent() {
  if (!S.mod) return toast("Pick a mod first");
  const e = S.ent;
  try {
    let res, id;
    if (e.kind === "row") { res = await api(`mod/${S.mod}/save`, e); id = entId(e); }
    else { res = await api(`mod/${S.mod}/save-design`, { kind: e.kind, design: e }); id = res.id; }
    S.dirty = false; S.catalogs = {}; S.names = {};
    S.summary = await api("mod/" + S.mod);
    const fresh = e.kind === "row" ? await api(`entity/row/${encodeURIComponent(id)}?mod=${S.mod}`) : await api(`design/${e.kind}/${encodeURIComponent(id)}?mod=${S.mod}`);
    showEditor(fresh);
    showProblems(res);
    toast(res.ok ? (res.problems.length ? "Saved, with warnings" : "Saved") : "Saved, but the mod does not build");
  } catch (err) {
    toast("Not saved: " + err.message, 8000);
  }
}

function showProblems(res) {
  const box = $("#problems");
  if (box && res && res.problems && res.problems.length) box.replaceChildren(h("ul", { class: "problems" }, res.problems.map(p => h("li", {}, p))));
}

async function deleteCurrent() {
  const e = S.ent;
  if (!(await confirmDialog(`Remove this ${KINDS[e.kind].one} from mod ${S.mod}?`))) return;
  const res = e.kind === "row" ? await api(`mod/${S.mod}/delete`, { kind: "row", id: entId(e) })
                               : await api(`mod/${S.mod}/delete-design`, { kind: e.kind, id: entId(e) });
  S.ent = null; S.dirty = false; S.catalogs = {};
  S.summary = await api("mod/" + S.mod);
  renderSide();
  $("#editor").replaceChildren(h("div", { class: "empty" }, "Deleted."));
  if (res.problems && res.problems.length) toast(res.problems.join("\n"), 8000);
}

/** Stat grid with "in game" values from the server's solver. */
function statsCard(e, rows, kind, note) {
  const out = {};
  const grid = h("div", { class: "fields" });
  for (const [key, label, help, show] of rows) {
    if (show && !show()) continue;
    const got = h("span", { class: "ingame" });
    out[key] = got;
    grid.append(field(label, h("div", { class: "row" }, numberInput(e.stats, key, { onChange: () => preview() }), got), help));
  }
  let timer;
  const preview = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const p = await api("preview/" + kind, e);
        for (const [key, el] of Object.entries(out)) {
          const v = p.stats[key];
          if (v === undefined) continue;
          const same = num(v) === num(e.stats[key]);
          el.textContent = same ? "✓" : `in game: ${v}`;
          el.className = "ingame" + (same ? " ok" : " off");
          el.title = same ? "The game will show exactly this" : "The closest value the game's formula can produce";
        }
      } catch (err) { /* incomplete input */ }
    }, 250);
  };
  preview();
  return card("Final stats", note ? h("p", { class: "muted small" }, note) : null, grid);
}

// ------------------------------------------------------------------ T-Doll

function dollEditor(e) {
  const L = S.L, wrap = h("div");
  wrap.append(card("Basics", h("div", { class: "fields" },
    field("Name", textInput(e, "name")),
    field("Weapon class", selectInput(e, "type", L.gun_types, { onChange: renderEditor })),
    field("Rarity (stars)", selectInput(e, "rarity", { 2: "2★", 3: "3★", 4: "4★", 5: "5★", 6: "6★ (special)" })),
    modelSlot(e, "gun"),
    field("Credits (illustrator, voice)", textInput(e, "credits")),
    field("Weapon sheet", textInput(e, "intro", { area: true }))),
    checkbox(e, "give", "Give this T-Doll to the player (level 100, 5 dummy links, skills at level 10, fully enhanced)")));

  const isSG = Number(e.type) === 6, hasMag = [5, 6].includes(Number(e.type));
  wrap.append(statsCard(e, [
    ["hp", "HP (5 dummy links)"], ["firepower", "Firepower"], ["rate", "Rate of fire"], ["accuracy", "Accuracy"],
    ["evasion", "Evasion"], ["armor", "Armor", "Only shotguns have armor.", () => isSG], ["speed", "Movement speed"],
    ["crit", "Critical rate %"], ["armor_pen", "Armor penetration"], ["magazine", "Rounds per magazine", "Machine guns and shotguns.", () => hasMag],
    ["rof_cap", "Rate-of-fire cap", "Highest rate of fire buffs can reach (usually 120; MG 1000, SG 60)."],
  ], "unit", "Level 100, fully enhanced, before affection and equipment. The game rounds its formula, so a few values may land one or two points off; the closest value is shown."));

  wrap.append(tileCard(e));
  wrap.append(equipCard(e));
  wrap.append(card("Skills",
    h("div", { class: "fields" },
      skillSlot(e.skills, "skill1", "Skill", "The skill shown on the doll (level 10)."),
      skillSlot(e.skills, "skill2", "Second skill", "Optional; normally the Neural Upgrade skill."),
      skillSlot(e.skills, "normal_attack", "Normal attack", "Usually the class's standard attack."),
      skillList(e.skills, "passive", "Passive skills", "Always active."),
      skillList(e.skills, "dynamic", "Battle-start passives", "Added at the start of each battle; can scale with the skill level.")),
    h("p", { class: "muted small" }, "Make new skills under Skills on the left, then pick them here.")));
  return wrap;
}

function tileCard(e) {
  const t = e.tile ||= { center: 13, cells: [], targets: [], buffs: [] };
  let setCenter = false;
  const grid = h("div", { class: "tilegrid" });
  const draw = () => {
    grid.replaceChildren();
    for (let c = 1; c <= 25; c++) {
      const inEchelon = [7, 8, 9, 12, 13, 14, 17, 18, 19].includes(c);
      const cls = ["tile", inEchelon ? "ech" : "", t.cells.includes(c) ? "on" : "", t.center === c ? "me" : ""].join(" ");
      grid.append(h("button", { class: cls, title: `cell ${c}`, onclick: () => {
        if (setCenter) { t.center = c; setCenter = false; modeBtn.classList.remove("on"); }
        else if (t.cells.includes(c)) t.cells.splice(t.cells.indexOf(c), 1); else t.cells.push(c);
        dirty(); draw();
      } }, t.center === c ? "DOLL" : t.cells.includes(c) ? "★" : ""));
    }
  };
  const modeBtn = h("button", { class: "small", onclick: () => { setCenter = !setCenter; modeBtn.classList.toggle("on", setCenter); } }, "Move the doll…");
  draw();
  const buffs = h("div");
  const drawBuffs = () => {
    buffs.replaceChildren(...t.buffs.map((b, i) => h("div", { class: "row" },
      selectInput(b, "stat", S.L.tile_stats), numberInput(b, "value"), h("span", { class: "muted small" }, b.stat == 6 ? "% shorter cooldowns" : "%"),
      h("button", { class: "small danger", onclick: () => { t.buffs.splice(i, 1); dirty(); drawBuffs(); } }, "✕"))),
      h("button", { class: "small", onclick: () => { t.buffs.push({ stat: 1, value: 10 }); dirty(); drawBuffs(); } }, "+ Buff"));
  };
  drawBuffs();
  const targets = h("div", { class: "row" }, ...Object.entries(S.L.gun_types).map(([v, label]) => {
    const cb = h("input", { type: "checkbox" });
    cb.checked = t.targets.includes(Number(v));
    cb.addEventListener("change", () => { const n = Number(v); t.targets = t.targets.filter(x => x !== n); if (cb.checked) t.targets.push(n); dirty(); });
    return h("label", { class: "check" }, cb, " " + label.split(" (")[1].replace(")", ""));
  }));
  return card("Tiles",
    h("div", { class: "tilewrap" }, h("div", {}, grid, h("div", { class: "row small" }, modeBtn,
      h("span", { class: "muted" }, "Click cells to buff them. The inner 3×3 is the echelon."))),
      h("div", { class: "grow" }, field("Buffs given to dolls on the starred cells", buffs),
        field("Which classes get the buff (none ticked = all)", targets))));
}

function equipCard(e) {
  const slots = e.equipment ||= [{ category: 0, types: [] }, { category: 0, types: [] }, { category: 0, types: [] }];
  const wrap = h("div");
  slots.forEach((slot, i) => {
    const types = h("div", { class: "row" });
    const drawTypes = () => types.replaceChildren(...S.L.equip_types.filter(t => t.category === Number(slot.category)).map(t => {
      const cb = h("input", { type: "checkbox" });
      cb.checked = slot.types.includes(t.type);
      cb.addEventListener("change", () => { slot.types = slot.types.filter(x => x !== t.type); if (cb.checked) slot.types.push(t.type); dirty(); });
      const fits = t.fits.includes(0) || t.fits.includes(Number(e.type));
      return h("label", { class: "check" + (fits ? "" : " muted"), title: fits ? "" : "Not normally used by this class" }, cb, " " + t.name);
    }));
    drawTypes();
    wrap.append(h("div", { class: "slot" }, h("strong", {}, `Slot ${i + 1}`),
      selectInput(slot, "category", Object.assign({ 0: "(no slot)" }, S.L.equip_categories), { onChange: () => { slot.types = []; drawTypes(); } }), types));
  });
  return card("Equipment slots", wrap, h("p", { class: "muted small" }, "Greyed types are not normally used by this class."));
}

// ------------------------------------------------------------------ Coalition

function sangvisEditor(e) {
  const L = S.L, wrap = h("div");
  wrap.append(card("Basics", h("div", { class: "fields" },
    field("Name", textInput(e, "name")), modelSlot(e, "sangvis"),
    field("Faction", selectInput(e, "faction", L.factions)),
    field("Class", selectInput(e, "class", L.sangvis_classes, { onChange: renderEditor }), "Only bosses have chip slots."),
    field("Rarity (stars)", selectInput(e, "rarity", { 3: "3★", 4: "4★", 5: "5★" })),
    field("Formation", selectInput(e, "linkable", { false: "Single unit", true: "Linkable (up to 5 models)" }, { text: true, onChange: () => { e.linkable = e.linkable === true || e.linkable === "true"; renderEditor(); } })),
    field("Introduction", textInput(e, "intro", { area: true }))),
    checkbox(e, "give", "Give this unit to the player (level 100, 5 stars, max size and resolution, skills maxed)")));
  const per = e.linkable === true || e.linkable === "true" ? " (per model)" : "";
  wrap.append(statsCard(e, [
    ["hp", "HP (whole unit)"], ["damage", "Damage" + per], ["rate", "Rate of fire"], ["accuracy", "Accuracy"], ["evasion", "Evasion"],
    ["armor", "Armor"], ["crit", "Critical rate %"], ["crit_dmg", "Critical damage %"], ["armor_pen", "Armor penetration"],
    ["speed", "Movement speed"], ["range", "Attack range"],
  ], "sangvis", "Level 100, 5 stars, largest size, max resolution, before affection. These are exact."));
  const sk = e.skills;
  wrap.append(card("Skills", h("div", { class: "fields" },
    skillSlot(sk, "skill1", "Skill 1"), skillSlot(sk, "skill2", "Skill 2"),
    field("Skill 2 kind", selectInput(sk, "skill2_kind", L.skill2_kinds), "Map and support skills come from other tables; battle skills are made under Skills."),
    skillSlot(sk, "skill3", "Skill 3"), skillSlot(sk, "skill_advance", "Advanced skill", "Unlocked at 4 stars."),
    skillSlot(sk, "normal_attack", "Normal attack"),
    skillList(sk, "passive", "Passive skills"), skillList(sk, "dynamic", "Battle-start passives"))));
  return wrap;
}

// ------------------------------------------------------------------ enemy

function enemyEditor(e) {
  const L = S.L, wrap = h("div");
  wrap.append(card("Basics", h("div", { class: "fields" },
    field("Name", textInput(e, "name")), modelSlot(e, "enemy"), field("Type", selectInput(e, "type", L.enemy_types)))));
  const grid = h("div", { class: "fields" }, ...L.enemy_stats.map(([key, label]) => field(label, numberInput(e.stats, key))));
  wrap.append(card("Stats at level 100", h("p", { class: "muted small" },
    "Enemies placed at other levels in a team scale from these numbers like the game's own enemies."), grid));
  wrap.append(card("Skills", h("div", { class: "fields" },
    skillSlot(e.skills, "normal_attack", "Normal attack"), skillList(e.skills, "passive", "Passive skills"))));
  return wrap;
}

// ------------------------------------------------------------------ enemy team

function teamEditor(e) {
  const L = S.L, wrap = h("div");
  const ai = L.team_ai[e.ai] || {};
  const leaderChoices = {};
  e.members.forEach((m, i) => { leaderChoices[i] = `#${i + 1} (enemy ${m.enemy})`; });
  lookupNames("enemy", e.members.map(m => m.enemy)).then(n => {
    const sel = $("#leader-select");
    if (sel) [...sel.options].forEach((o, i) => { const m = e.members[i]; if (m) o.textContent = `#${i + 1} ${n[m.enemy] || m.enemy}`; });
  });
  const leader = selectInput(e, "leader", leaderChoices);
  leader.id = "leader-select";
  const aiChoices = {};
  for (const [k, v] of Object.entries(L.team_ai)) aiChoices[k] = v.label;
  wrap.append(card("Team", h("div", { class: "fields" },
    field("Leader (shown on the map)", leader),
    field("Movement AI", selectInput(e, "ai", aiChoices, { text: true, onChange: renderEditor })),
    ai.param ? field(ai.param, textInput(e, "ai_param", { placeholder: e.ai === "patrol" ? "e.g. 8000002,8000003,8000006" : "e.g. 2" })) : null,
    field("Fixed combat effectiveness", numberInput(e, "fixed_ce"), "Added to the team's shown CE (0 = none)."),
    field("Warning tags", h("div", { class: "row" }, ...Object.entries(L.team_tags).map(([v, label]) => {
      const cb = h("input", { type: "checkbox" });
      cb.checked = e.tags.includes(Number(v));
      cb.addEventListener("change", () => { e.tags = e.tags.filter(x => x !== Number(v)); if (cb.checked) e.tags.push(Number(v)); dirty(); });
      return h("label", { class: "check" }, cb, " " + label);
    }))))));
  const cb = e.correction_belong;
  const belong = h("div", { class: "fields" }, ...["on a Griffin node", "on an enemy node", "on a neutral node", "anywhere else"].map((label, i) => {
    const o = { v: cb[i] || 0 };
    return field(`Levels ${label}`, numberInput(o, "v", { onChange: () => { cb[i] = o.v; } }));
  }));
  const turns = h("div");
  const drawTurns = () => turns.replaceChildren(...e.correction_turn.map((t, i) => h("div", { class: "row" },
    h("span", {}, "From turn"), numberInput(t, "turn", { min: 1 }), h("span", {}, "add"), numberInput(t, "levels"), h("span", {}, "levels"),
    h("button", { class: "small danger", onclick: () => { e.correction_turn.splice(i, 1); dirty(); drawTurns(); } }, "✕"))),
    h("button", { class: "small", onclick: () => { e.correction_turn.push({ turn: 2, levels: 1 }); dirty(); drawTurns(); } }, "+ Turn step"));
  drawTurns();
  wrap.append(card("Level corrections", h("p", { class: "muted small" }, "Extra levels for every member, by where the team stands and by turn."),
    belong, field("By turn", turns)));
  wrap.append(card("Members", h("div", { class: "row" }, h("button", { class: "small", onclick: async () => {
      const id = await pickDialog("enemy", "Add which enemy?");
      if (id === null) return;
      e.members.push({ id: null, enemy: Number(id), x: 13, y: 4, level: 100, links: 5, shield_pct: 0, wave: 0 });
      dirty(); renderEditor();
    } }, "+ Add enemy")),
    battlefield(e), h("div", { class: "tablewrap" }, memberTable(e)),
    h("p", { class: "muted small" }, "Drag the dots to place enemies (Griffin echelons stand on the left). Links multiply HP; wave 2+ arrives later. When targets tie, the enemy listed first is chosen.")));
  return wrap;
}

function memberTable(e) {
  const tbl = h("table", { class: "grid" }, h("tr", {}, ["#", "Enemy", "Level", "Links", "Shield %", "Wave", "x", "y", ""].map(c => h("th", {}, c))));
  e.members.forEach((m, i) => {
    const nameSpan = h("span", { class: "muted small" });
    lookupNames("enemy", [m.enemy]).then(n => { nameSpan.textContent = n[m.enemy] || ""; });
    const enemyCell = h("div", { class: "row" }, h("button", { class: "small", onclick: async () => {
      const id = await pickDialog("enemy", "Change enemy"); if (id !== null) { m.enemy = Number(id); dirty(); renderEditor(); } } }, String(m.enemy)), nameSpan);
    const tr = h("tr", {}, h("td", {}, i + 1 + (e.leader === i ? " ★" : "")), h("td", {}, enemyCell));
    for (const k of ["level", "links", "shield_pct", "wave", "x", "y"]) tr.append(h("td", {}, numberInput(m, k, { onChange: () => k === "x" || k === "y" ? drawBattlefield(e) : null })));
    tr.append(h("td", {}, h("span", { class: "row small" },
      h("button", { title: "Duplicate this enemy", onclick: () => { e.members.splice(i + 1, 0, Object.assign({}, m, { id: null, y: m.y + 2 })); dirty(); renderEditor(); } }, "Duplicate"),
      h("button", { title: "Move up", onclick: () => { if (i) { [e.members[i - 1], e.members[i]] = [e.members[i], e.members[i - 1]]; if (e.leader === i) e.leader = i - 1; else if (e.leader === i - 1) e.leader = i; dirty(); renderEditor(); } } }, "↑"),
      h("button", { class: "danger", onclick: () => { e.members.splice(i, 1); if (e.leader >= e.members.length) e.leader = 0; dirty(); renderEditor(); } }, "✕"))));
    tbl.append(tr);
  });
  if (!e.members.length) tbl.append(h("tr", {}, h("td", { colspan: 9, class: "muted" }, "No enemies yet")));
  return tbl;
}

const BF = { x0: 0, x1: 22, y0: -2, y1: 11 };
function battlefield(e) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `${BF.x0} ${-BF.y1} ${BF.x1 - BF.x0} ${BF.y1 - BF.y0}`);
  svg.setAttribute("id", "bf");
  setTimeout(() => drawBattlefield(e), 0);
  let drag = null;
  const toXY = (ev) => { const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY; const p = pt.matrixTransform(svg.getScreenCTM().inverse()); return [Math.round(p.x), Math.round(-p.y)]; };
  svg.addEventListener("pointerdown", ev => { const i = ev.target.dataset && ev.target.dataset.i; if (i !== undefined) { drag = Number(i); svg.setPointerCapture(ev.pointerId); } });
  svg.addEventListener("pointermove", ev => { if (drag === null) return; const [x, y] = toXY(ev); const m = e.members[drag]; if (m.x !== x || m.y !== y) { m.x = x; m.y = y; dirty(); drawBattlefield(e); } });
  svg.addEventListener("pointerup", () => { if (drag !== null) { drag = null; renderEditor(); } });
  return h("div", { class: "bf" }, svg);
}

function drawBattlefield(e) {
  const svg = $("#bf");
  if (!svg) return;
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, a) => { const n = document.createElementNS(NS, tag); for (const k in a) n.setAttribute(k, a[k]); return n; };
  svg.replaceChildren();
  for (let x = BF.x0; x <= BF.x1; x++) svg.append(el("line", { x1: x, y1: -BF.y0, x2: x, y2: -BF.y1, stroke: "currentColor", "stroke-opacity": x % 5 ? .08 : .2, "stroke-width": .03 }));
  for (let y = BF.y0; y <= BF.y1; y++) svg.append(el("line", { x1: BF.x0, y1: -y, x2: BF.x1, y2: -y, stroke: "currentColor", "stroke-opacity": y % 5 ? .08 : .2, "stroke-width": .03 }));
  svg.append(el("rect", { x: -2.9, y: -8.6, width: 7.2, height: 9.1, fill: "var(--griffin)", "fill-opacity": .08, rx: .3 }));
  const lbl = el("text", { x: -2.7, y: -8.8, "font-size": .5, fill: "var(--muted)" }); lbl.textContent = "Griffin echelon"; svg.append(lbl);
  e.members.forEach((m, i) => {
    svg.append(el("circle", { cx: m.x, cy: -m.y, r: .42, fill: m.wave > 1 ? "var(--third)" : "var(--enemy)", stroke: e.leader === i ? "var(--text)" : "none", "stroke-width": .08, "data-i": i, style: "cursor:grab" }));
    const t = el("text", { x: m.x, y: -m.y + .17, "font-size": .45, "text-anchor": "middle", fill: "#fff", "pointer-events": "none" });
    t.textContent = i + 1;
    svg.append(t);
  });
}

// ------------------------------------------------------------------ raw rows (advanced)

const fieldsOf = (table) => S.meta.tables[table] || [];
const docOf = (table, f) => ((S.meta.guide[table] || {}).docs || {})[f] || "";

function rawInput(table, f, row) {
  const t = (fieldsOf(table).find(x => x[0] === f) || [])[1] || "string";
  const long = t === "string" && String(row[f] ?? "").length > 60;
  const el = long ? h("textarea", { rows: 3 }) : h("input", { type: t === "string" ? "text" : "number", step: t === "float" ? "any" : "1" });
  el.value = row[f] ?? "";
  el.addEventListener("input", () => { row[f] = t === "string" ? el.value : (t === "float" ? parseFloat(el.value || 0) : parseInt(el.value || 0, 10)); dirty(); });
  return el;
}

function rawGroups(table, row, exclude = []) {
  const all = fieldsOf(table).map(f => f[0]).filter(f => !exclude.includes(f));
  const seen = new Set(), wrap = h("div");
  const groups = [];
  for (const [title, flds] of ((S.meta.guide[table] || {}).groups || [])) {
    const fs = flds.filter(f => all.includes(f) && !seen.has(f));
    fs.forEach(f => seen.add(f));
    if (fs.length) groups.push([title, fs]);
  }
  const rest = all.filter(f => !seen.has(f));
  if (rest.length) groups.push(["Other fields", rest]);
  for (const [title, flds] of groups)
    wrap.append(card(title, h("div", { class: "fields" }, flds.map(f => field(f, rawInput(table, f, row), docOf(table, f))))));
  return wrap;
}

function rowEditor(e) {
  return h("div", {}, h("p", { class: "muted" }, `Raw row of ${e.table}. Field notes come from doc/stc-guide.`), rawGroups(e.table, e.row));
}

// ------------------------------------------------------------------ start

async function init() {
  [S.meta, S.L] = await Promise.all([api("meta"), api("lookups")]);
  $("#mod-select").addEventListener("change", async (ev) => {
    if (S.dirty && !(await confirmDialog("Discard unsaved changes?"))) { ev.target.value = S.mod || ""; return; }
    S.ent = null; S.dirty = false;
    $("#editor").replaceChildren(h("div", { class: "empty" }, "Open or create an entry on the left."));
    openMod(ev.target.value);
  });
  $("#mod-new").addEventListener("click", () => {
    const name = h("input", { type: "text", placeholder: "folder name: letters, digits, - and _" });
    const desc = h("input", { type: "text", placeholder: "description" });
    let close;
    close = openDialog(h("h3", {}, "New mod"), h("p", { class: "muted small" }, "Each mod's maps are listed together as one entry in the game's Campaign tab."), name, desc, h("div", { class: "row" },
      h("button", { class: "primary", onclick: async () => {
        try {
          await api("mod", { name: name.value.trim(), description: desc.value });
          close(); S.ent = null; S.dirty = false;
          $("#editor").replaceChildren(h("div", { class: "empty" }, "Open or create an entry on the left."));
          await loadMods(name.value.trim());
        } catch (err) { toast(err.message); }
      } }, "Create"), h("button", { onclick: () => close() }, "Cancel")));
    name.focus();
  });
  $("#btn-all-mods").addEventListener("click", openAllMods);
  $("#btn-map-config").addEventListener("click", () => openMapConfig());
  S.cnData = (await api("cn-data")).available;
  $("#btn-check").addEventListener("click", async () => {
    if (!S.mod) return toast("Pick a mod first");
    const res = await api(`mod/${S.mod}/check`, {});
    openDialog(h("h3", {}, res.ok ? (res.problems.length ? "Builds, with warnings" : "All good") : "Does not build"),
      res.problems.length ? h("ul", { class: "problems" }, res.problems.map(p => h("li", {}, p))) : h("p", {}, "No problems found."),
      h("div", { class: "row" }, h("button", { onclick: () => $("#dialog").classList.add("hidden") }, "Close")));
  });
  $("#btn-build").addEventListener("click", async () => {
    const close = openDialog(h("h3", {}, "Building…"), h("p", { class: "muted" }, "Merging the enabled mods into the game data."));
    const res = await api("build", {});
    close();
    openDialog(h("h3", {}, res.ok ? "Built" : "Build failed"), h("pre", { class: "out" }, res.output),
      h("p", { class: "muted small" }, "Restart the server (play.py); the game downloads the new data on the next login."),
      h("div", { class: "row" }, h("button", { onclick: () => $("#dialog").classList.add("hidden") }, "Close")));
  });
  const adv = $("#advanced-toggle");
  if (adv) adv.addEventListener("change", () => { S.advanced = adv.checked; renderSide(); });
  window.addEventListener("beforeunload", ev => { if (S.dirty) { ev.preventDefault(); ev.returnValue = ""; } });
  await loadMods();
}

init().catch(err => { $("#editor").replaceChildren(h("div", { class: "empty" }, "Could not load: " + err.message)); });
