"use strict";

const PAGE_SIZE = 40;
const LS_UNIT = "mycoast-last-unit";

const state = {
  items: [],        // every image, in data order
  view: "todo",     // todo | done | all
  list: [],         // items matching the view, in order
  rendered: 0,      // how many of list are in the DOM
  dirty: new Set(), // record_ids with a typed depth that has NOT been saved
};

const $ = (id) => document.getElementById(id);
const grid = $("grid");

// ---- localStorage is only a convenience; never required ------------------
function lsGet(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function lsSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* ignore */ }
}

// ---- helpers --------------------------------------------------------------
function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k.includes("-")) node.setAttribute(k, v);
    else if (v !== undefined && v !== null) node[k] = v;
  }
  for (const c of [].concat(children)) {
    if (c !== null && c !== undefined) node.append(c);
  }
  return node;
}

const isDone = (item) => Boolean(item.annotation);
const matchesView = (item) =>
  state.view === "all" || (state.view === "done") === isDone(item);

function describe(a) {
  return a.status === "cant_tell" ? "can't tell" : `${a.depth_value} ${a.depth_unit}`;
}

// The saved depth as it appears in the input box ("" when nothing is saved).
function savedValue(item) {
  const a = item.annotation;
  return a && a.status === "depth" ? String(a.depth_value) : "";
}

// ---- data -----------------------------------------------------------------
async function load() {
  const res = await fetch("/api/items");
  if (!res.ok) throw new Error(`GET /api/items: ${res.status}`);
  const { items, instructions } = await res.json();
  items.forEach((it, i) => { it.order = i; });
  state.items = items;
  showInstructions(instructions);
  applyView();
}

async function post(item, status, value, unit) {
  const res = await fetch("/api/annotate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      record_id: item.record_id, status, depth_value: value, depth_unit: unit,
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `save failed (${res.status})`);
  item.annotation = body.annotation || null;
  state.dirty.delete(item.record_id);
  updateUnsavedNotice();
}

// Plain text from instructions.txt, shown above the cards. Line breaks are
// preserved by CSS; the text is set with textContent, never parsed as HTML.
function showInstructions(text) {
  $("instructions-text").textContent = text || "";
  $("instructions").hidden = !text;
}

// ---- view & rendering -------------------------------------------------------
function applyView() {
  state.list = state.items.filter(matchesView);
  state.rendered = 0;
  grid.replaceChildren();
  renderMore();
  updateCounts();
}

function renderMore() {
  const next = state.list.slice(state.rendered, state.rendered + PAGE_SIZE);
  grid.append(...next.map(buildCard));
  state.rendered += next.length;
}

function updateCounts() {
  const done = state.items.filter(isDone).length;
  const total = state.items.length;
  $("count-todo").textContent = total - done;
  $("count-done").textContent = done;
  $("count-all").textContent = total;
  $("progress").textContent =
    `${done} of ${total} images annotated (${total ? Math.round((100 * done) / total) : 0}%)`;
  const empty = $("empty");
  empty.hidden = state.list.length > 0;
  empty.textContent = state.view === "todo"
    ? "Everything is annotated. Export your results with the button above."
    : "Nothing here yet.";
}

function updateUnsavedNotice() {
  const n = state.dirty.size;
  const notice = $("unsaved");
  notice.hidden = n === 0;
  notice.textContent = n === 1
    ? "1 photo has a depth typed in but not saved"
    : `${n} photos have a depth typed in but not saved`;
}

function buildCard(item) {
  const valueInput = el("input", {
    type: "number", min: "0", step: "any", inputMode: "decimal",
    placeholder: "depth", "aria-label": "Water depth",
    value: savedValue(item),
  });
  const unitSelect = el("select", { "aria-label": "Unit" }, [
    el("option", { value: "inch", textContent: "inch" }),
    el("option", { value: "cm", textContent: "cm" }),
  ]);
  unitSelect.value = (item.annotation && item.annotation.depth_unit) || lsGet(LS_UNIT, "inch");
  const error = el("div", { class: "error", hidden: true });
  const existing = el("div", { class: "existing" });

  const card = el("article", { class: "card", dataset: { id: item.record_id } });

  const save = () => {
    const raw = valueInput.value.trim();
    const v = Number(raw);
    if (raw === "" || !Number.isFinite(v) || v < 0) {
      return showError(error, "Enter a depth of 0 or more.");
    }
    lsSet(LS_UNIT, unitSelect.value);
    submit(item, card, "depth", v, unitSelect.value, error);
  };
  // A typed depth does nothing until it is saved, so flag it as unsaved.
  const markDirty = () => {
    const changed = valueInput.value.trim() !== savedValue(item);
    state.dirty[changed ? "add" : "delete"](item.record_id);
    card.classList.toggle("dirty", changed);
    updateUnsavedNotice();
  };
  valueInput.addEventListener("input", markDirty);
  valueInput.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
  unitSelect.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });

  const buttons = [
    el("button", { class: "btn primary", textContent: "Save", onclick: save }),
    el("button", {
      class: "btn", textContent: "Can't tell", title: "Depth cannot be judged from this image",
      onclick: () => submit(item, card, "cant_tell", null, null, error),
    }),
  ];
  if (item.annotation) {
    buttons.push(el("button", {
      class: "btn", textContent: "Clear", title: "Remove this annotation",
      onclick: () => submit(item, card, "cleared", null, null, error),
    }));
  }

  const counter = item.image_count > 1 ? ` · image ${item.image_index} of ${item.image_count}` : "";
  card.append(
    el("button", { class: "thumb", title: "View full image", onclick: () => openLightbox(item) }, [
      el("img", { src: item.thumbnail_url, loading: "lazy", alt: `Flood report photo, ${item.place || ""}` }),
    ]),
    el("div", { class: "card-body" }, [
      el("div", { class: "meta" }, [
        el("span", { textContent: `${item.report_type || ""}${counter}` }),
        el("span", { textContent: item.local_time_text || "" }),
      ]),
      el("div", { class: "place", textContent: [item.place, item.county].filter(Boolean).join(", ") }),
      item.reporter_estimated_depth
        ? el("div", { class: "reporter", textContent: `Reporter's estimate: ${item.reporter_estimated_depth}` })
        : null,
      item.description ? el("p", { class: "desc", textContent: item.description }) : null,
      el("details", {}, [
        el("summary", { textContent: "Full report text" }),
        el("pre", { textContent: item.text || "" }),
      ]),
      el("a", { href: item.source_url, target: "_blank", rel: "noopener", textContent: "Open MyCoast report ↗" }),
      existing,
      el("div", { class: "form" }, [valueInput, unitSelect, ...buttons, error]),
    ]),
  );
  card.classList.toggle("is-done", isDone(item));
  existing.textContent = item.annotation ? `Saved: ${describe(item.annotation)}` : "";
  return card;
}

function showError(node, msg) {
  node.textContent = msg;
  node.hidden = false;
}

// ---- saving -----------------------------------------------------------------
async function submit(item, card, status, value, unit, errorNode) {
  errorNode.hidden = true;
  const prev = item.annotation;
  try {
    await post(item, status, value, unit);
  } catch (e) {
    return showError(errorNode, e.message);
  }
  afterChange(item, card);
  const what = status === "cleared"
    ? "Cleared"
    : `Saved ${describe({ status, depth_value: value, depth_unit: unit })}`;
  showToast(what, () => undo(item, prev));
}

async function undo(item, prev) {
  try {
    if (prev) await post(item, prev.status, prev.depth_value, prev.depth_unit);
    else await post(item, "cleared", null, null);
  } catch (e) {
    return showToast(`Undo failed: ${e.message}`);
  }
  afterChange(item, grid.querySelector(`[data-id="${item.record_id}"]`));
  showToast("Undone");
}

// Re-render or remove/insert one card after its annotation changed.
function afterChange(item, card) {
  const inList = state.list.includes(item);
  if (matchesView(item)) {
    const fresh = buildCard(item);
    if (inList && card) {
      card.replaceWith(fresh);
    } else if (!inList) {
      if (card) card.remove();  // may still be fading out after an earlier removal
      insertCard(item, fresh);
    }
  } else if (inList) {
    const idx = state.list.indexOf(item);
    state.list.splice(idx, 1);
    if (card) {
      state.rendered -= 1;
      const nextCard = card.nextElementSibling;
      card.classList.add("leaving");
      setTimeout(() => card.remove(), 250);
      if (nextCard) {
        const nextInput = nextCard.querySelector("input[type=number]");
        if (nextInput) nextInput.focus();
      }
      if (state.rendered < PAGE_SIZE) renderMore();
    }
  }
  updateCounts();
}

// Put an item back into the list at its original data-order position.
function insertCard(item, cardNode) {
  let idx = state.list.findIndex((it) => it.order > item.order);
  if (idx === -1) idx = state.list.length;
  state.list.splice(idx, 0, item);
  if (idx < state.rendered) {
    const before = grid.querySelector(`[data-id="${state.list[idx + 1].record_id}"]`);
    grid.insertBefore(cardNode, before);
    state.rendered += 1;
  } else if (idx === state.rendered) {
    grid.append(cardNode);
    state.rendered += 1;
  }
}

// ---- lightbox & toast -------------------------------------------------------
function openLightbox(item) {
  $("lightbox-img").src = item.image_url;
  $("lightbox-caption").replaceChildren(
    `${[item.place, item.county].filter(Boolean).join(", ")} · ${item.local_time_text || ""} · `,
    el("a", { href: item.source_url, target: "_blank", rel: "noopener", textContent: "Open report ↗" }),
    " · ",
    el("a", { href: item.image_url, target: "_blank", rel: "noopener", textContent: "Original file ↗" }),
  );
  $("lightbox").hidden = false;
}
function closeLightbox() {
  $("lightbox").hidden = true;
  $("lightbox-img").removeAttribute("src");
}
$("lightbox").addEventListener("click", (e) => {
  if (e.target.tagName !== "A") closeLightbox();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("lightbox").hidden) closeLightbox();
});

let toastTimer;
function showToast(msg, onUndo) {
  const t = $("toast");
  t.replaceChildren(el("span", { textContent: msg }));
  if (onUndo) {
    t.append(el("button", {
      textContent: "Undo",
      onclick: () => { t.hidden = true; onUndo(); },
    }));
  }
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, onUndo ? 6000 : 3000);
}

// ---- wiring -------------------------------------------------------------------
document.querySelectorAll(".segmented button").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.view = btn.dataset.view;
    document.querySelectorAll(".segmented button").forEach((b) => {
      b.classList.toggle("active", b === btn);
      b.setAttribute("aria-checked", String(b === btn));
    });
    applyView();
    window.scrollTo({ top: 0 });
  });
});

// The export contains SAVED annotations only, so say so before downloading.
$("export").addEventListener("click", (e) => {
  const n = state.dirty.size;
  if (n && !window.confirm(
    `${n} photo${n === 1 ? " has" : "s have"} a depth typed in that was never saved. `
    + "Those are NOT in the export. Download anyway?")) {
    e.preventDefault();
  }
});

// Typed-but-unsaved work is lost on reload; make the browser ask first.
window.addEventListener("beforeunload", (e) => {
  if (state.dirty.size) e.preventDefault();
});

new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting && state.rendered < state.list.length) renderMore();
}, { rootMargin: "800px" }).observe($("sentinel"));

load().catch((e) => {
  $("progress").textContent = `Failed to load: ${e.message}`;
});
