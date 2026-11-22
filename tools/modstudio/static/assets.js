/* Pictures and music page: replace the game's profile pictures, home backgrounds, map backgrounds and music
   with the modder's own files, or add new ones made from one of the game's. Talks to assets.py. */
"use strict";

const ASSET = { cats: null, cat: null, list: null, search: "", shown: 120 };
const enc = encodeURIComponent;

async function openAssets(ref) {
  if (!S.mod) return toast("Create or pick a mod first");
  if (S.dirty && !(await confirmDialog("Discard unsaved changes?"))) return;
  S.ent = null; S.dirty = false;
  ASSET.cats ||= await api("assets");
  const [cat, key] = String(ref || "").split("/");
  ASSET.cat = ASSET.cats.some(c => c.id === cat) ? cat : (ASSET.cat || ASSET.cats[0].id);
  ASSET.search = ""; ASSET.shown = 120;
  renderSide();
  await loadAssets();
  if (key) {
    const it = ASSET.list.items.find(x => x.key === key);
    if (it) assetDialog(it);
  }
}

async function loadAssets() {
  $("#editor").replaceChildren(h("p", { class: "muted" }, "Loading…"));
  try { ASSET.list = await api(`assets/${ASSET.cat}?mod=${enc(S.mod)}`); }
  catch (err) { $("#editor").replaceChildren(h("p", { class: "muted" }, err.message)); return; }
  renderAssets();
}

const catOf = () => ASSET.cats.find(c => c.id === ASSET.cat);
const one = (c) => c.label.replace(/s$/, "").toLowerCase();
const thumbUrl = (key, mine) => `/api/asset-thumb?cat=${ASSET.cat}&key=${enc(key)}${mine ? `&mod=${enc(S.mod)}` : ""}&t=${ASSET.stamp || 0}`;
const fileUrl = (key) => `/api/asset-file?mod=${enc(S.mod)}&cat=${ASSET.cat}&key=${enc(key)}&t=${ASSET.stamp || 0}`;

function renderAssets() {
  const c = catOf(), L = ASSET.list;
  const tabs = h("div", { class: "row" }, ASSET.cats.map(x => h("button", { class: x.id === ASSET.cat ? "primary" : "",
    onclick: () => { ASSET.cat = x.id; ASSET.search = ""; ASSET.shown = 120; loadAssets(); } }, x.label)));
  const own = card(`New ${c.label.toLowerCase()} in this mod`,
    h("p", { class: "muted small" }, c.add_help),
    L.own.length ? h("div", { class: "asset-own" }, L.own.map(ownRow)) : h("p", { class: "muted small" }, "None yet."),
    h("button", { class: "primary", onclick: () => addDialog(L.items[0]) }, `+ Add a new ${one(c)}…`));
  const search = h("input", { type: "search", placeholder: "Search by name…", value: ASSET.search });
  const grid = h("div", { class: c.kind === "picture" ? "asset-grid" : "asset-rows" });
  const more = h("div", {});
  const fill = () => {
    const q = ASSET.search.trim().toLowerCase();
    const hits = L.items.filter(x => !q || x.name.toLowerCase().includes(q) || x.key.toLowerCase().includes(q))
      .sort((a, b) => b.changed - a.changed);
    grid.replaceChildren(...hits.slice(0, ASSET.shown).map(x => c.kind === "picture" ? tile(x) : soundRow(x)));
    if (!hits.length) grid.append(h("div", { class: "muted" }, "Nothing found"));
    more.replaceChildren(hits.length > ASSET.shown ? h("button", { onclick: () => { ASSET.shown += 240; fill(); } }, `Show more (${hits.length - ASSET.shown} left)`) : "");
  };
  search.addEventListener("input", () => { ASSET.search = search.value; ASSET.shown = 120; fill(); });
  fill();
  const changed = L.items.filter(x => x.changed).length;
  $("#editor").replaceChildren(
    h("div", { class: "head" }, h("div", {}, h("h2", {}, "Pictures and music"),
      h("p", { class: "muted" }, "Replace the game's pictures and music with your own files, or add new ones. They reach the game when you build mods."))),
    tabs,
    card(c.label, h("p", { class: "muted small" }, c.help),
      changed ? h("p", {}, h("span", { class: "pill" }, `${changed} replaced by this mod`)) : null,
      search, grid, more),
    own);
}

function tile(x) {
  return h("button", { class: "asset-tile" + (x.changed ? " changed" : ""), title: x.key, onclick: () => assetDialog(x) },
    h("div", { class: "asset-img" }, h("img", { loading: "lazy", src: thumbUrl(x.key, x.changed), alt: "" })),
    h("span", { class: "asset-name" }, x.name), x.changed ? h("span", { class: "pill" }, "replaced") : null);
}

const length = (s) => s ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "";

function soundRow(x) {
  return h("button", { class: "ent", onclick: () => assetDialog(x) }, h("span", { class: "id" }, length(x.seconds)), x.name,
    x.changed ? h("span", { class: "pill", style: "margin-left:8px" }, "replaced") : null);
}

function ownRow(x) {
  const c = catOf();
  const name = h("input", { type: "text", value: x.name, title: "The name shown in the game" });
  name.addEventListener("change", async () => {
    try { ASSET.list = await api(`mod/${enc(S.mod)}/asset-rename`, { cat: ASSET.cat, key: x.key, name: name.value }); toast("Name saved"); }
    catch (err) { toast(err.message, 9000); }
  });
  const shown = c.kind === "picture" ? h("div", { class: "art-thumb" }, h("img", { src: thumbUrl(x.key, true), alt: "" }))
    : x.preview ? h("audio", { controls: true, preload: "none", src: fileUrl(x.key) }) : null;
  const usage = ASSET.cat === "map_bg" ? `Background name for your maps: ${x.key}` : "";
  return h("div", { class: "art-slot" }, shown,
    h("div", { class: "art-text" }, name, h("div", { class: "doc" }, usage || `Made from: ${(ASSET.list.items.find(i => i.key === x.from) || {}).name || x.from}`),
      h("div", { class: "row" },
        h("button", { class: "small", onclick: () => replaceFile(c, Object.assign({ new: true }, x)) }, "Change file…"),
        x.place ? h("button", { class: "small", onclick: () => adjustPlace(x) }, "Move or zoom…") : null,
        h("button", { class: "small danger", onclick: async () => {
          if (!(await confirmDialog(`Delete "${x.name}" from this mod?`))) return;
          ASSET.list = await api(`mod/${enc(S.mod)}/asset-remove`, { cat: ASSET.cat, key: x.key });
          afterChange();
        } }, "Delete"))));
}

function pickFile(c, then) {
  const input = h("input", { type: "file", accept: c.kind === "picture" ? "image/*" : "audio/*", class: "hidden" });
  input.addEventListener("change", () => input.files[0] && then(input.files[0]));
  document.body.append(input);
  input.click();
  setTimeout(() => input.remove(), 60000);
}

/** The body for an upload: a picture as a data URL, a sound decoded here (the server can't read MP3 and the like). */
async function fileBody(c, file) {
  if (c.kind === "picture") return { data: await readAsDataURL(file) };
  let buf;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    buf = await ctx.decodeAudioData(await file.arrayBuffer());
    ctx.close();
  } catch (err) { throw new Error("That file can't be played as sound by your browser. Try MP3, OGG or WAV."); }
  const ch = Math.min(2, buf.numberOfChannels), n = buf.length;
  const pcm = new Int16Array(n * ch);
  for (let k = 0; k < ch; k++) {
    const d = buf.getChannelData(k);
    for (let i = 0; i < n; i++) pcm[i * ch + k] = Math.max(-32768, Math.min(32767, Math.round(d[i] * 32767)));
  }
  const bytes = new Uint8Array(pcm.buffer);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  return { pcm: btoa(bin), rate: buf.sampleRate, channels: ch, ext, preview: file.size <= 20 * 2 ** 20 ? await readAsDataURL(file) : null };
}

async function sendFile(action, body, file) {
  const c = catOf();
  toast(c.kind === "picture" ? "Converting the picture…" : "Converting the sound (this takes a few seconds)…", 60000);
  try {
    ASSET.list = await api(`mod/${enc(S.mod)}/${action}`, Object.assign(body, await fileBody(c, file)));
    toast(action === "asset-add" ? "Added. It reaches the game when you build mods." : "Saved. It reaches the game when you build mods.", 6000);
    afterChange();
    return true;
  } catch (err) { toast(err.message, 9000); return false; }
}

async function afterChange() {
  ASSET.stamp = Date.now();
  S.summary = await api("mod/" + S.mod);
  renderSide();
  renderAssets();
}

function assetDialog(x) {
  const c = catOf();
  let close;
  const done = () => close();
  const pictures = c.kind === "picture" ? h("div", { class: "row asset-compare" },
    h("figure", {}, h("img", { src: thumbUrl(x.key, false), alt: "" }), h("figcaption", { class: "muted small" }, "The game's")),
    x.changed ? h("figure", {}, h("img", { src: thumbUrl(x.key, true), alt: "" }), h("figcaption", { class: "muted small" }, "Yours")) : null) : null;
  const listen = c.kind === "sound" && x.changed && x.preview ? field("Your file", h("audio", { controls: true, src: fileUrl(x.key) })) : null;
  const moving = x.moving ? h("p", { class: "muted small" },
    "This background moves in the game (with animated backgrounds on). With your picture it shows still.") : null;
  close = openDialog(h("h3", {}, x.name), h("p", { class: "muted small" }, c.help), moving, pictures, listen,
    c.kind === "sound" && !x.changed ? h("p", { class: "muted small" }, "The game's own music can't be played here.") : null,
    h("div", { class: "row" },
      h("button", { class: "primary", onclick: () => replaceFile(c, x, done) },
        c.kind === "picture" ? "Replace with my picture…" : "Replace with my sound file…"),
      x.changed && x.place ? h("button", { onclick: () => { done(); adjustPlace(x); } }, "Move or zoom my picture…") : null,
      c.kind === "picture" ? h("button", { title: "To paint over", onclick: () => { location.href = `/api/asset-template?cat=${ASSET.cat}&key=${enc(x.key)}`; } }, "Download the original") : null,
      x.changed ? h("button", { class: "danger", onclick: async () => {
        ASSET.list = await api(`mod/${enc(S.mod)}/asset-remove`, { cat: ASSET.cat, key: x.key });
        done(); afterChange();
      } }, "Undo my change") : null),
    h("div", { class: "row" },
      h("button", { onclick: () => { done(); addDialog(x); } }, `Make a new ${one(c)} like this…`),
      h("button", { onclick: done }, "Close")));
}

function addDialog(from) {
  const c = catOf();
  const name = h("input", { type: "text", placeholder: `Name shown in the game` });
  const pick = h("select", {}, ASSET.list.items.map(i => h("option", { value: i.key, selected: i.key === from.key ? "" : null }, i.name)));
  const chosen = h("span", { class: "muted small" }, "No file chosen");
  let file = null, close;
  const like = c.kind === "picture" ? "Its size and shape are taken from this one." : "It copies this track's settings (whether it loops).";
  close = openDialog(h("h3", {}, `New ${one(c)}`), h("p", { class: "muted small" }, c.add_help),
    field("Name", name), field("Made like", pick, like),
    field(c.kind === "picture" ? "Picture" : "Sound file", h("div", { class: "row" },
      h("button", { onclick: () => pickFile(c, f => { file = f; chosen.textContent = f.name; }) }, "Choose…"), chosen)),
    h("div", { class: "row" },
      h("button", { class: "primary", onclick: async () => {
        if (!file) return toast("Choose a file first");
        if (PLACED.includes(ASSET.cat)) {
          const data = await readAsDataURL(file);
          return placeDialog({ from: pick.value, src: data, save: place => send("asset-add", { cat: ASSET.cat, from: pick.value, name: name.value, data, place }, close) });
        }
        if (await sendFile("asset-add", { cat: ASSET.cat, from: pick.value, name: name.value }, file)) close();
      } }, "Add"),
      h("button", { onclick: () => close() }, "Cancel")));
  name.focus();
}

/** Replace or change the file of one: a map background is placed on a map before it is saved. */
function replaceFile(c, x, done) {
  pickFile(c, async f => {
    if (!PLACED.includes(ASSET.cat)) { if (await sendFile("asset-upload", { cat: ASSET.cat, key: x.key }, f)) done && done(); return; }
    const data = await readAsDataURL(f);
    if (done) done();
    placeDialog({ key: x.key, from: x.new ? x.from : null, src: data, place: x.place,
                  save: place => send("asset-upload", { cat: ASSET.cat, key: x.key, data, place }) });
  });
}

function adjustPlace(x) {
  placeDialog({ key: x.key, from: x.from || null, src: fileUrl(x.key) + "&which=source", place: x.place,
                save: place => send("asset-upload", { cat: ASSET.cat, key: x.key, place }) });
}

async function send(action, body, then) {
  toast("Saving the picture…", 60000);
  try {
    ASSET.list = await api(`mod/${enc(S.mod)}/${action}`, body);
    toast(action === "asset-add" ? "Added. It reaches the game when you build mods." : "Saved. It reaches the game when you build mods.", 6000);
    afterChange();
    if (then) then();
    return true;
  } catch (err) { toast(err.message, 9000); return false; }
}

const PLACED = ["map_bg", "home_bg"];
const HOME_AREA = [2048, 1536], HOME_SCREEN = [2048, 1152];
const SIDE_COLOR = { 1: "#3b82f6", 2: "#ef4444", 3: "#9ca3af" };

/** The picture on a map under its nodes and roads, or on the home screen, with fill / fit / stretch, zoom
    (no limit: slider, scroll wheel or a typed percentage) and drag to move.
    o: {key, from, src: picture URL, place: saved placement, save(place) -> promise of true when saved}. */
async function placeDialog(o) {
  const NSV = "http://www.w3.org/2000/svg";
  const el = (tag, a = {}) => { const n = document.createElementNS(NSV, tag); for (const k in a) n.setAttribute(k, a[k]); return n; };
  const home = ASSET.cat === "home_bg";
  const where = home ? "screen" : "map";
  const PLACE_MODES = [["fill", `Fill the ${where}`], ["fit", "Fit inside"], ["stretch", `Stretch to the ${where}`]];
  let maps = [];
  if (!home) try { maps = await api(`asset-maps?key=${enc(o.key || o.from)}&from=${enc(o.from || "")}&mod=${enc(S.mod)}`); } catch (err) { maps = []; }
  const img = new Image();
  await new Promise(ok => { img.onload = ok; img.onerror = ok; img.src = o.src; });
  if (!img.naturalWidth) return toast("That picture can't be shown. Choose it again.", 9000);
  const p = Object.assign({ mode: "fill", zoom: 1, x: 0, y: 0 }, o.place || {});
  const saved = o.place && o.place.area;
  let at = Math.max(0, saved ? maps.findIndex(m => m.area[0] === saved[0] && m.area[1] === saved[1]) : 0);
  const area = () => home ? HOME_AREA : maps[at] ? maps[at].area : (saved || [img.naturalWidth, img.naturalHeight]);
  const svg = el("svg", { class: "place-view" });
  const modes = h("div", { class: "row" });
  // the slider moves in steps of a share of the zoom (log scale) and goes past its ends by typing or scrolling
  const zoom = h("input", { type: "range", min: "-5", max: "5", step: "0.01" });
  const zoomText = h("input", { type: "number", min: "0", step: "any", class: "zoom-num", title: "Zoom in percent" });
  const setZoom = (z, from) => {
    if (!(z > 0) || !isFinite(z)) return;
    p.zoom = Math.min(1e6, Math.max(1e-6, z));
    if (from !== "slider") zoom.value = String(Math.log2(p.zoom));
    if (from !== "typed") zoomText.value = String(+(p.zoom * 100).toPrecision(4));
    draw();
  };
  const draw = () => {
    const [W, H] = area();
    const m = maps[at];
    // a map: framed on the part the game shows (m.view), the picture repeated mirrored past its edges as the game does
    const v = m && m.view ? { x: m.view[2] - m.view[0] / 2, y: -m.view[3] - m.view[1] / 2, w: m.view[0], h: m.view[1] } : null;
    const f = v || { x: -W / 2, y: -H / 2, w: W, h: H };
    const pad = Math.max(f.w, f.h) * (v ? 0.12 : 0.04);
    svg.setAttribute("viewBox", `${f.x - pad} ${f.y - pad} ${f.w + 2 * pad} ${f.h + 2 * pad}`);
    let w, hh;
    if (p.mode === "stretch") { w = W * p.zoom; hh = H * p.zoom; }
    else {
      const k = (p.mode === "fill" ? Math.max : Math.min)(W / img.naturalWidth, H / img.naturalHeight) * p.zoom;
      w = img.naturalWidth * k; hh = img.naturalHeight * k;
    }
    const cx = W / 2 + p.x * W, cy = H / 2 + p.y * H;
    const r = Math.max(W, H) / 110, line = Math.max(W, H) / 400;
    const [SW, SH] = HOME_SCREEN;
    const clip = el("clipPath", { id: "place-clip" });
    clip.append(el("rect", { x: -W / 2, y: -H / 2, width: W, height: H }));
    const pic = el("image", { href: o.src, x: -W / 2 + cx - w / 2, y: -H / 2 + cy - hh / 2, width: w, height: hh,
                              preserveAspectRatio: "none", "clip-path": "url(#place-clip)" });
    const tile = el("g", { id: "place-tile" });
    tile.append(el("rect", { x: -W / 2, y: -H / 2, width: W, height: H, fill: "#000" }), pic);
    const kids = [clip, tile];
    if (!home) for (const i of [-1, 0, 1]) for (const j of [-1, 0, 1]) {
      if (!i && !j) continue;
      kids.push(el("use", { href: "#place-tile", transform: `matrix(${i ? -1 : 1} 0 0 ${j ? -1 : 1} ${i * W} ${j * H})` }));
    }
    kids.push(el("rect", { x: -W / 2, y: -H / 2, width: W, height: H, fill: "none", stroke: "currentColor", "stroke-width": line,
                           "stroke-opacity": .5, "stroke-dasharray": `${line * 6} ${line * 4}` }));
    if (v) {
      const big = 1e7;
      kids.push(el("path", { d: `M${-big},${-big}H${big}V${big}H${-big}Z M${v.x},${v.y}v${v.h}h${v.w}v${-v.h}Z`, fill: "#000", "fill-opacity": .6, "fill-rule": "evenodd" }),
                el("rect", { x: v.x, y: v.y, width: v.w, height: v.h, fill: "none", stroke: "#fff", "stroke-width": line * 1.5 }));
    }
    if (home) kids.push(el("rect", { x: -SW / 2, y: -SH / 2, width: SW, height: SH, fill: "none", stroke: "#fff", "stroke-width": line * 2,
                                     "stroke-dasharray": `${line * 8} ${line * 6}` }));
    for (const [x1, y1, x2, y2] of m ? m.routes : [])
      kids.push(el("line", { x1, y1: -y1, x2, y2: -y2, stroke: "#fff", "stroke-opacity": .8, "stroke-width": line * 2 }));
    for (const s of m ? m.spots : [])
      kids.push(el("circle", { cx: s.x, cy: -s.y, r, fill: SIDE_COLOR[s.belong] || "#9ca3af", stroke: "#fff", "stroke-width": line }));
    svg.replaceChildren(...kids);
    modes.replaceChildren(...PLACE_MODES.map(([k, label]) => h("button", { class: p.mode === k ? "primary" : "",
      onclick: () => { p.mode = k; draw(); } }, label)),
      h("button", { onclick: () => { p.x = 0; p.y = 0; setZoom(1); } }, "Centre"));
  };
  zoom.addEventListener("input", () => setZoom(2 ** +zoom.value, "slider"));
  zoomText.addEventListener("change", () => setZoom(+zoomText.value / 100, "typed"));
  let drag = null;
  svg.addEventListener("pointerdown", ev => { drag = { x: ev.clientX, y: ev.clientY, px: p.x, py: p.y }; svg.setPointerCapture(ev.pointerId); });
  svg.addEventListener("pointermove", ev => {
    if (!drag) return;
    const [W, H] = area();
    const box = svg.viewBox.baseVal, scale = Math.max(box.width / svg.clientWidth, box.height / svg.clientHeight);
    p.x = drag.px + (ev.clientX - drag.x) * scale / W;
    p.y = drag.py + (ev.clientY - drag.y) * scale / H;
    draw();
  });
  svg.addEventListener("pointerup", () => { drag = null; });
  svg.addEventListener("wheel", ev => {
    ev.preventDefault();
    setZoom(p.zoom * (ev.deltaY < 0 ? 1.1 : 1 / 1.1));
  }, { passive: false });
  const which = maps.length > 1 ? field("Show it on", h("select", { onchange: ev => { at = +ev.target.value; draw(); } },
    maps.map((m, i) => h("option", { value: i, selected: i === at ? "" : null }, `${m.name} (${m.area[0]} × ${m.area[1]})`))),
    "Maps using this background. Their shapes can differ; the picture is saved for the one shown.") : null;
  let close;
  close = openDialog(h("h3", {}, `Place your picture on the ${home ? "home screen" : "map"}`),
    h("p", { class: "muted small" }, home
      ? "The whole frame is what the game draws behind the adjutant; the dashed box is about what a widescreen (16:9) screen shows, the rest is cut off. Drag the picture to move it; scroll, use the slider or type a zoom. Black shows where the picture doesn't reach."
      : maps.length
      ? "The dots are the map's nodes and the lines its roads. The bright box is the part of the map the game shows (players scroll within it). Past the dashed edge the game repeats your picture mirrored. Drag the picture to move it; scroll, use the slider or type a zoom. Black shows where the picture doesn't reach."
      : "No map uses this background yet, so there are no nodes to show. Drag the picture to move it; scroll or use the slider to zoom."),
    which, svg, modes, field("Zoom", h("div", { class: "row" }, zoom, zoomText, h("span", { class: "muted small" }, "%"))),
    h("div", { class: "row" },
      h("button", { class: "primary", onclick: async () => { if (await o.save(Object.assign({}, p, { area: area() }))) close(); } }, "Save"),
      h("button", { onclick: () => close() }, "Cancel")));
  setZoom(p.zoom || 1);
}

window.openAssets = openAssets;
