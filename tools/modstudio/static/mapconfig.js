/* Map spawns page: the player's own enemy spawn tables, enemy move order and random node odds per map. Not part of
   any mod: saved to the server's map_config.json, which the server reads while it runs. */
"use strict";

const RANDOM_LABELS = [
  ["gain", "Supplies found", "+40 manpower, ammo, rations or parts"],
  ["loss", "Supplies lost", "−80 ammo or rations"],
  ["data", "Data found", "basic, intermediate or advanced"],
  ["core", "Core found", "one core"],
  ["ambush", "Enemy ambush", "a team from the map appears and fights"],
  ["gun", "T-Doll found", "one joins your base"],
];

async function openMapConfig() {
  if (S.dirty && !(await confirmDialog("Discard unsaved changes?"))) return;
  S.ent = null; S.dirty = false;
  renderSide();
  const list = await api("map-config");
  const pick = h("button", { class: "primary", onclick: async () => {
    const id = await pickDialog("mission", "Which map?");
    if (id !== null) openMapSettings(id);
  } }, "Pick a map…");
  $("#editor").replaceChildren(h("h2", {}, "Map spawns"),
    h("p", { class: "muted" }, "Which enemies appear during a map, which moves first, and what random nodes give. These are your own settings for every map, " +
      "not part of a mod, and the server uses changes straight away (the next turn). Maps you haven't set use the server's guess: " +
      "enemies appear on enemy heliports. A mod that sets a map's spawns wins over these."),
    card("Maps with settings", list.length
      ? list.map(m => h("button", { class: "ent", onclick: () => openMapSettings(m.id) }, h("span", { class: "id" }, m.id),
          `${m.name || ""}${m.spawns !== null ? ` · ${m.spawns} spawn row${m.spawns === 1 ? "" : "s"}` : ""}${m.move_order ? " · move order" : ""}${m.random_nodes ? " · random nodes" : ""}`))
      : h("p", { class: "muted" }, "None yet."), pick));
}

async function openMapSettings(id) {
  const e = await api("map-config/" + id);
  // the spawn rule editor (map.js) redraws through renderEditor, so this page is the open "entity"
  const draw = () => renderEditor();
  e.render = () => {
    const spawnBox = { v: e.custom_spawns }, rndBox = { v: e.custom_random }, orderBox = { v: e.custom_order };
    const spawns = e.custom_spawns ? spawnsTab(e, true)
      : h("p", { class: "muted" }, "Using the server's guess: spawns seen on the live server where any were recorded, else an enemy may appear on each enemy-held heliport every enemy turn.");
    const hasRandom = e.spots.some(s => s.random);
    const odds = e.custom_random
      ? h("div", { class: "fields" }, ...RANDOM_LABELS.map(([k, label, help]) => field(label, numberInput(e.random_nodes, k, { min: 0 }), help)))
      : h("p", { class: "muted" }, "Default odds: " + RANDOM_LABELS.map(([k, label]) => `${label.toLowerCase()} ${e.random_default[k]}`).join(", ") + ".");
    return h("div", {},
      h("div", { class: "head" }, h("div", {}, h("h2", {}, e.name || `Map ${e.id}`), h("span", { class: "muted small" }, `map ${e.id} · your own settings, not a mod`)),
        h("div", { class: "row" }, h("button", { onclick: openMapConfig }, "Back"), h("button", { class: "primary", onclick: save }, "Save"))),
      card("Enemy spawns",
        checkbox(spawnBox, "v", "Set this map's spawns myself", { onChange: () => { e.custom_spawns = spawnBox.v; dirty(); draw(); } }),
        h("p", { class: "muted small" }, "A team appears at the start of an enemy turn on an empty node; each row picks the nodes and the teams that may appear there, by weight. " +
          "Several rows on one node, or one row with several teams, give random spawns. With this on and no rows, nothing spawns."),
        spawns),
      card("Enemy move order",
        checkbox(orderBox, "v", "Set this map's move order myself", { onChange: () => { e.custom_order = orderBox.v; dirty(); draw(); } }),
        e.custom_order ? moveOrderTab(e, true)
          : h("p", { class: "muted" }, e.default_order && (e.default_order.first || []).length
            ? "Using this map's shipped move order." : "Enemies move in the order they appeared.")),
      card("Random nodes",
        hasRandom ? null : h("p", { class: "muted small" }, "This map has no random nodes, so these never come up."),
        checkbox(rndBox, "v", "Set this map's random node odds myself", { onChange: () => { e.custom_random = rndBox.v; dirty(); draw(); } }),
        h("p", { class: "muted small" }, "The numbers are weights: an outcome with 20 is twice as likely as one with 10. 0 turns it off."),
        odds));
  };
  const save = async () => {
    try {
      const fresh = await api("map-config/" + e.id, e);
      Object.assign(e, fresh);
      S.dirty = false;
      toast("Saved. The server uses it from the next turn.");
      draw();
    } catch (err) { toast("Not saved: " + err.message, 8000); }
  };
  S.ent = e; S.dirty = false;
  draw();
}
