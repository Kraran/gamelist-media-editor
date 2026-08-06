const FIELDS = [
{ key: "image",   label: "Image (screenshot)", icon: "🖼️" },
{ key: "video",   label: "Vidéo",              icon: "🎬" },
{ key: "marquee", label: "Marquee",            icon: "🏷️" },
{ key: "manual",  label: "Manuel (PDF)",       icon: "📖" },
{ key: "boxback", label: "Box Back",           icon: "📦" },
];
const SPECIAL_FLAGS = { wr: "🌍", world: "🌍", multi: "🌐", unk: "🏳️", xx: "🏳️" };
const LANG_TO_FLAGCDN = { en: "gb", jp: "jp", ja: "jp", ko: "kr", zh: "cn", cn: "cn", us: "us", br: "br", eu: "eu" };
let GENRES = {};
/**
 * UI logic — Gamelist Media Editor
 * games[]          : sorted by name; each item has .index = original XML position
 * currentIndex     : XML index (API routes)
 * currentListIndex : index inside games[] (list selection)
 * mediaFilter      : all | image | video | marquee | manual | boxback | any
 */
let games = [];
let currentIndex = null;
let currentListIndex = null;
let mediaFilter = "all";
let searchDebounceTimer = null;
const SEARCH_DEBOUNCE_MS = 180;
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024; // 50 Mo — aligné serveur
let _toastTimer = null;

function toast(msg, type = "success") {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = String(msg || "");
  el.className = "toast " + type + " show";
  if (_toastTimer) clearTimeout(_toastTimer);
  const ms = type === "error" ? 6500 : type === "warning" ? 4500 : 3200;
  _toastTimer = setTimeout(() => el.classList.remove("show"), ms);
}

function setStatus(txt) {
  const el = document.getElementById("status");
  if (el) el.textContent = txt;
}

/**
 * Fetch JSON from our API with consistent error handling.
 * Throws Error with a French, user-readable message.
 */
async function apiFetch(url, options = {}) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (e) {
    const offline = (typeof navigator !== "undefined" && navigator.onLine === false);
    throw new Error(
      offline
        ? "Pas de connexion réseau."
        : "Impossible de contacter le serveur local (est-il toujours lancé ?)."
    );
  }

  let data = null;
  const ct = (res.headers.get("content-type") || "").toLowerCase();
  if (ct.includes("application/json")) {
    try {
      data = await res.json();
    } catch (_) {
      data = null;
    }
  } else {
    try {
      const text = await res.text();
      if (text) data = { error: text.slice(0, 400) };
    } catch (_) {}
  }

  if (!res.ok) {
    const serverMsg = data && (data.error || data.message);
    let msg = serverMsg || ("Erreur serveur HTTP " + res.status);
    if (res.status === 404 && !serverMsg) msg = "Ressource introuvable (404).";
    if (res.status === 413) msg = "Fichier trop volumineux pour le serveur.";
    if (res.status >= 500 && !serverMsg) msg = "Erreur interne du serveur (" + res.status + ").";
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    err.code = data && data.code;
    throw err;
  }

  if (data && data.error && data.ok === false) {
    const err = new Error(data.error);
    err.data = data;
    err.code = data.code;
    throw err;
  }
  return data;
}

function handleError(e, context) {
  const msg = (e && e.message) ? e.message : String(e);
  const prefix = context ? context + " : " : "";
  console.error(prefix, e);
  const low = msg.toLowerCase();
  const isQuota = [
    "quota", "thread", "limite", "limit", "429", "trop de requ",
    "patiente", "boost", "503", "maintenance", "satur"
  ].some(k => low.includes(k));
  toast(prefix + msg, isQuota ? "warning" : "error");
  setStatus(isQuota ? "Limite API — réessaie plus tard" : "Erreur");
  return msg;
}
function mediaUrl(relPath) {
if (!relPath) return null;
return "/media/" + relPath.replace(/^\.\//, "");
}
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&" + "amp;")
    .replace(/</g, "&" + "lt;")
    .replace(/>/g, "&" + "gt;")
    .replace(/"/g, "&" + "quot;");
}
function initGenreSelects() {
const mainSel = document.getElementById("meta-genre-main");
mainSel.innerHTML = '<option value="">— Choisir —</option>';
Object.keys(GENRES).sort().forEach(main => {
const opt = document.createElement("option");
opt.value = main; opt.textContent = main;
mainSel.appendChild(opt);
});
}
function fillSubGenres(main, selectedSub = "") {
const subSel = document.getElementById("meta-genre-sub");
subSel.innerHTML = '<option value="">— Aucun —</option>';
const subs = GENRES[main] || [];
if (!subs.length) { subSel.disabled = true; return; }
subSel.disabled = false;
subs.forEach(sub => {
const opt = document.createElement("option");
opt.value = sub; opt.textContent = sub;
if (sub === selectedSub) opt.selected = true;
subSel.appendChild(opt);
});
}
function parseGenre(genreStr) {
if (!genreStr) return { main: "", sub: "" };
const parts = genreStr.split(/\s*\/\s*/);
const main = (parts[0] || "").trim().toUpperCase();
const sub = (parts[1] || "").trim().toUpperCase();
let foundMain = Object.keys(GENRES).find(k => k.toUpperCase() === main) || "";
let foundSub = "";
if (foundMain && sub) {
foundSub = (GENRES[foundMain] || []).find(s => s.toUpperCase() === sub) || "";
}
if (!foundMain && main) {
for (const [m, subs] of Object.entries(GENRES)) {
if (subs.some(s => s.toUpperCase() === main)) {
foundMain = m;
foundSub = subs.find(s => s.toUpperCase() === main) || "";
break;
}
}
}
return { main: foundMain, sub: foundSub };
}
function buildGenreValue() {
const main = document.getElementById("meta-genre-main").value;
const sub = document.getElementById("meta-genre-sub").value;
if (!main) return "";
return sub ? `${main} / ${sub}` : main;
}
function setGenreUI(genreStr) {
const { main, sub } = parseGenre(genreStr);
document.getElementById("meta-genre-main").value = main;
fillSubGenres(main, sub);
}
function hasMedia(g, key) {
  return !!(g[key] && String(g[key]).trim());
}

function matchesMediaFilter(g, filterKey) {
  const key = filterKey !== undefined ? filterKey : mediaFilter;
  if (key === "all") return true;
  if (key === "any") return FIELDS.some(f => !hasMedia(g, f.key));
  return !hasMedia(g, key);
}

function matchesSearch(g, query) {
  if (!query) return true;
  const q = query.toLowerCase();
  return g.name.toLowerCase().includes(q) || g.path.toLowerCase().includes(q);
}

/** Visible games under current search + media filter. Returns { game, listIndex }[] */
function getFilteredGames(searchQuery) {
  const q = (searchQuery !== undefined
    ? searchQuery
    : document.getElementById("search").value).toLowerCase().trim();
  const out = [];
  games.forEach((g, i) => {
    if (!matchesSearch(g, q)) return;
    if (!matchesMediaFilter(g)) return;
    out.push({ game: g, listIndex: i });
  });
  return out;
}

function updateGameCount(visibleCount) {
  const el = document.getElementById("game-count");
  if (mediaFilter === "all" && !document.getElementById("search").value.trim()) {
    el.textContent = games.length + " jeux";
  } else {
    el.textContent = visibleCount + " / " + games.length + " jeux";
  }
}

function updateFilterCounts(q) {
  const query = (q || "").toLowerCase().trim();
  const counts = { all: 0, image: 0, video: 0, marquee: 0, manual: 0, boxback: 0, any: 0 };
  games.forEach(g => {
    if (!matchesSearch(g, query)) return;
    counts.all++;
    FIELDS.forEach(f => {
      if (!hasMedia(g, f.key)) counts[f.key]++;
    });
    if (FIELDS.some(f => !hasMedia(g, f.key))) counts.any++;
  });
  document.querySelectorAll(".filter-chip").forEach(btn => {
    const key = btn.dataset.filter;
    const el = btn.querySelector(".filter-count");
    if (el && key in counts) el.textContent = counts[key];
  });
}

function updateSystemBadge(system) {
  const el = document.getElementById("system-name");
  if (!el) return;
  if (!system || !system.label) {
    el.textContent = "—";
    el.title = "Système inconnu";
    el.dataset.empty = "1";
    return;
  }
  el.textContent = system.label;
  el.dataset.empty = "0";
  const bits = [system.label];
  if (system.id != null) bits.push("ScreenScraper id " + system.id);
  if (system.folder && system.folder !== system.label.toLowerCase()) {
    bits.push("dossier " + system.folder);
  }
  el.title = bits.join(" · ");
}

async function loadGames() {
  setStatus("Chargement…");
  const keepIndex = currentIndex;
  try {
    const data = await apiFetch("/api/games");
    // Back-compat: array or { games, system }
    if (Array.isArray(data)) {
      games = data;
      updateSystemBadge(null);
    } else {
      games = data.games || [];
      updateSystemBadge(data.system || null);
    }
    if (keepIndex !== null) {
      const listIdx = games.findIndex(g => g.index === keepIndex);
      if (listIdx >= 0) {
        currentListIndex = listIdx;
        renderList();
        selectGame(listIdx);
      } else {
        currentIndex = null;
        currentListIndex = null;
        document.getElementById("editor").hidden = true;
        document.getElementById("empty-state").hidden = false;
        document.getElementById("btn-delete-game").disabled = true;
const _ssBtn2 = document.getElementById("btn-ss-scrape");
if (_ssBtn2) _ssBtn2.disabled = true;
const _adbBtn2 = document.getElementById("btn-adb-scrape");
if (_adbBtn2) _adbBtn2.disabled = true;
        renderList();
      }
    } else {
      renderList();
    }
    setStatus("Prêt — " + games.length + " jeux chargés");
  } catch (e) {
    handleError(e, "Chargement");
  }
}
function renderList(filter) {
  const list = document.getElementById("game-list");
  const q = (filter !== undefined ? filter : document.getElementById("search").value).toLowerCase().trim();
  const filtered = getFilteredGames(q);
  const frag = document.createDocumentFragment();

  filtered.forEach(({ game: g, listIndex: i }) => {
    const div = document.createElement("div");
    div.className = "game-item" + (currentListIndex === i ? " active" : "");
    div.dataset.listIndex = i;
    div.setAttribute("role", "option");
    div.setAttribute("aria-selected", currentListIndex === i ? "true" : "false");
    div.tabIndex = -1;
    const dots = FIELDS.map(f =>
      `<span class="dot ${hasMedia(g, f.key) ? "filled" : ""}" title="${f.label}"></span>`
    ).join("");
    div.innerHTML =
      `<div class="name">${escapeHtml(g.name)}</div>` +
      `<div class="path">${escapeHtml(g.path)}</div>` +
      `<div class="media-dots">${dots}</div>`;
    div.addEventListener("click", () => selectGame(i));
    frag.appendChild(div);
  });

  list.innerHTML = "";
  if (filtered.length === 0) {
    const empty = document.createElement("div");
    empty.className = "filter-empty";
    empty.textContent = games.length
      ? "Aucun jeu ne correspond à ce filtre."
      : "Aucun jeu dans le gamelist.";
    list.appendChild(empty);
  } else {
    list.appendChild(frag);
  }
  updateGameCount(filtered.length);
  updateFilterCounts(q);
}

function getVisibleListIndices() {
  return getFilteredGames().map(x => x.listIndex);
}

function scrollActiveIntoView() {
  const active = document.querySelector(".game-item.active");
  if (active) active.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function navigateGame(delta) {
  const visible = getVisibleListIndices();
  if (!visible.length) return;

  let pos = visible.indexOf(currentListIndex);
  if (pos < 0) {
    // Nothing selected (or selection filtered out) → start at first/last
    pos = delta > 0 ? -1 : visible.length;
  }
  const nextPos = Math.max(0, Math.min(visible.length - 1, pos + delta));
  selectGame(visible[nextPos]);
}

function isTypingTarget(el) {
  if (!el || el === document.body) return false;
  const tag = (el.tagName || "").toLowerCase();
  if (tag === "textarea" || tag === "select") return true;
  if (tag === "input") {
    const type = (el.type || "text").toLowerCase();
    return !["button", "checkbox", "radio", "submit", "reset", "file"].includes(type);
  }
  return el.isContentEditable;
}

function selectGame(listIndex) {
const g = games[listIndex];
if (!g) return;
currentIndex = g.index;
currentListIndex = listIndex;
document.getElementById("empty-state").hidden = true;
document.getElementById("editor").hidden = false;
document.getElementById("btn-delete-game").disabled = false;
const _ssBtn = document.getElementById("btn-ss-scrape");
if (_ssBtn) _ssBtn.disabled = false;
const _adbBtn = document.getElementById("btn-adb-scrape");
if (_adbBtn) _adbBtn.disabled = false;
document.getElementById("game-name-input").value = g.name;
document.getElementById("game-path").textContent = g.path;
document.getElementById("desc-textarea").value = g.desc || "";
document.getElementById("meta-rating").value = g.rating || "";
document.getElementById("meta-releasedate").value = g.releasedate || "";
document.getElementById("meta-developer").value = g.developer || "";
document.getElementById("meta-publisher").value = g.publisher || "";
document.getElementById("meta-family").value = g.family || "";
document.getElementById("meta-players").value = g.players || "";
document.getElementById("meta-lang").value = g.lang || "";
updateLangFlag(g.lang || "");
setGenreUI(g.genre || "");
document.querySelectorAll(".game-item").forEach(el => {
  const on = parseInt(el.dataset.listIndex, 10) === listIndex;
  el.classList.toggle("active", on);
  el.setAttribute("aria-selected", on ? "true" : "false");
});
renderZones(g);
scrollActiveIntoView();
}
function updateLangFlag(code) {
  const key = (code || "").toLowerCase().trim();
  const img = document.getElementById("lang-flag-img");
  const fallback = document.getElementById("lang-flag-fallback");
  const container = document.getElementById("lang-flag");
  container.title = key ? key.toUpperCase() : "";
  if (SPECIAL_FLAGS[key]) {
    img.hidden = true;
    img.removeAttribute("src");
    fallback.hidden = false;
    fallback.textContent = SPECIAL_FLAGS[key];
    return;
  }
  if (!key) {
    img.hidden = true;
    fallback.hidden = false;
    fallback.textContent = "🌐";
    return;
  }
  const flagCode = LANG_TO_FLAGCDN[key] || key;
  img.onload = () => { img.hidden = false; fallback.hidden = true; };
  img.onerror = () => {
    img.hidden = true;
    fallback.hidden = false;
    fallback.textContent = "🏳️";
  };
  img.src = `https://flagcdn.com/24x18/${flagCode}.png`;
  img.alt = key.toUpperCase();
}
function renderZones(g) {
const grid = document.getElementById("media-grid");
grid.innerHTML = "";
FIELDS.forEach(f => {
const has = hasMedia(g, f.key);
const zone = document.createElement("div");
zone.className = "drop-zone" + (has ? " has-media" : "");
zone.dataset.field = f.key;
let previewHtml = "";
if (has) {
const url = mediaUrl(g[f.key]);
if (f.key === "video") {
previewHtml = `<video class="preview-video" src="${url}" controls muted></video>`;
} else if (f.key === "manual") {
previewHtml = `<div class="placeholder"><div class="big">📄</div><div>Manuel PDF</div><a class="manual-link" href="${url}" target="_blank" rel="noopener">Ouvrir</a></div>`;
} else {
previewHtml = `<img src="${url}" alt="${f.label}" onerror="this.parentElement.innerHTML='<div class=\'placeholder\'><div class=\'big\'>⚠️</div>Aperçu indisponible</div>'" />`;
}
} else {
previewHtml = `<div class="placeholder"><div class="big">${f.icon}</div><div>Glisse un fichier ici<br>ou une image depuis le web</div></div>`;
}
zone.innerHTML = `
<div class="zone-header">
<div class="zone-title"><span class="icon">${f.icon}</span> ${f.label}</div>
<div class="zone-actions">${has ? `<button class="btn btn-danger" data-action="clear" title="Supprimer">✕</button>` : ""}</div>
</div>
<div class="preview-area">${previewHtml}</div>
${has ? `<div class="path-display">${escapeHtml(g[f.key])}</div>` : ""}
`;
zone.addEventListener("dragover", e => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.add("drag-over"); });
zone.addEventListener("dragleave", e => { e.preventDefault(); e.currentTarget.classList.remove("drag-over"); });
zone.addEventListener("drop", onDrop);
const clearBtn = zone.querySelector('[data-action="clear"]');
if (clearBtn) clearBtn.addEventListener("click", e => { e.stopPropagation(); clearField(f.key); });
grid.appendChild(zone);
});
}
async function onDrop(e) {
e.preventDefault(); e.stopPropagation();
const zone = e.currentTarget;
zone.classList.remove("drag-over");
if (currentIndex === null) return;
const field = zone.dataset.field;
const dt = e.dataTransfer;
if (dt.files && dt.files.length > 0) { await uploadMedia(field, { file: dt.files[0] }); return; }
let url = null;
if (dt.types.includes("text/uri-list")) url = dt.getData("text/uri-list").split("\n")[0].trim();
else if (dt.types.includes("text/plain")) {
const txt = dt.getData("text/plain").trim();
if (txt.startsWith("http://") || txt.startsWith("https://")) url = txt;
}
if (!url && dt.types.includes("text/html")) {
const m = dt.getData("text/html").match(/src=["'](https?:\/\/[^"']+)["']/i);
if (m) url = m[1];
}
if (url) await uploadMedia(field, { url });
else toast("Aucun fichier ou URL détecté", "error");
}
async function uploadMedia(field, { file, url }) {
  if (currentIndex === null) return;
  if (file && typeof file.size === "number" && file.size > MAX_UPLOAD_BYTES) {
    toast(`Fichier trop volumineux (max ${MAX_UPLOAD_BYTES / (1024 * 1024)} Mo)`, "error");
    return;
  }
  setStatus(file ? "Envoi du fichier…" : "Téléchargement depuis le web…");
  const form = new FormData();
  if (file) form.append("file", file);
  if (url) form.append("url", url);
  try {
    const data = await apiFetch(`/api/upload/${currentIndex}/${field}`, { method: "POST", body: form });
    const g = games.find(x => x.index === currentIndex);
    if (g) { g[field] = data.path; renderZones(g); }
    renderList(document.getElementById("search").value);
    toast(`✓ ${field} → ${data.filename}`);
    setStatus("Enregistré");
  } catch (e) {
    handleError(e);
  }
}

async function clearField(field) {
  // Detach media tag in XML only (file kept on disk)
  const choice = await askConfirm({
    title: `Retirer le champ « ${field} » ?`,
    bodyHtml:
      "<p>La balise sera retirée du <code>gamelist.xml</code>.</p>" +
      "<p>Le fichier média sur le disque <strong>n’est pas supprimé</strong>.</p>",
    showBackup: false,
  });
  if (!choice.confirmed) return;
  try {
    const data = await apiFetch(`/api/clear/${currentIndex}/${field}`, { method: "POST" });
    const g = games.find(x => x.index === currentIndex);
    if (g) { g[field] = ""; renderZones(g); }
    renderList(document.getElementById("search").value);
    toast("Champ retiré du XML");
  } catch (e) {
    handleError(e);
  }
}
async function saveName() {
  if (currentIndex === null) return true;
  const newName = document.getElementById("game-name-input").value.trim();
  if (!newName) { toast("Le nom ne peut pas être vide", "error"); return false; }
  setStatus("Enregistrement du nom…");
  try {
    const data = await apiFetch(`/api/name/${currentIndex}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName }),
    });
    const g = games.find(x => x.index === currentIndex);
    if (g) g.name = newName;
    games.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    currentListIndex = games.findIndex(x => x.index === currentIndex);
    renderList(document.getElementById("search").value);
    toast("✓ Nom enregistré");
    setStatus("Enregistré");
    return true;
  } catch (e) {
    handleError(e);
    return false;
  }
}

async function saveDesc() {
  if (currentIndex === null) return true;
  const newDesc = document.getElementById("desc-textarea").value;
  setStatus("Enregistrement de la description…");
  try {
    const data = await apiFetch(`/api/desc/${currentIndex}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ desc: newDesc }),
    });
    const g = games.find(x => x.index === currentIndex);
    if (g) g.desc = newDesc;
    toast("✓ Description enregistrée");
    setStatus("Enregistré");
    return true;
  } catch (e) {
    handleError(e);
    return false;
  }
}

async function saveMeta() {
  if (currentIndex === null) return true;
  const payload = {
    rating: document.getElementById("meta-rating").value,
    releasedate: document.getElementById("meta-releasedate").value,
    developer: document.getElementById("meta-developer").value,
    publisher: document.getElementById("meta-publisher").value,
    family: document.getElementById("meta-family").value,
    players: document.getElementById("meta-players").value,
    lang: document.getElementById("meta-lang").value,
    genre: buildGenreValue(),
  };
  setStatus("Enregistrement des métadonnées…");
  try {
    const data = await apiFetch(`/api/meta/${currentIndex}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const g = games.find(x => x.index === currentIndex);
    if (g && data.updated) Object.assign(g, data.updated);
    toast("✓ Métadonnées enregistrées");
    setStatus("Enregistré");
    return true;
  } catch (e) {
    handleError(e);
    return false;
  }
}

document.getElementById("btn-save-name").addEventListener("click", saveName);
document.getElementById("game-name-input").addEventListener("keydown", e => {
if (e.key === "Enter") { e.preventDefault(); saveName(); }
});
document.getElementById("btn-save-desc").addEventListener("click", saveDesc);
document.getElementById("desc-textarea").addEventListener("keydown", e => {
if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); saveDesc(); }
});
document.getElementById("btn-save-meta").addEventListener("click", saveMeta);
document.getElementById("meta-lang").addEventListener("input", e => updateLangFlag(e.target.value));
document.getElementById("search").addEventListener("input", e => {
  const value = e.target.value;
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => renderList(value), SEARCH_DEBOUNCE_MS);
});
document.getElementById("meta-genre-main").addEventListener("change", e => fillSubGenres(e.target.value));

document.getElementById("media-filters").addEventListener("click", e => {
  const btn = e.target.closest(".filter-chip");
  if (!btn) return;
  mediaFilter = btn.dataset.filter || "all";
  document.querySelectorAll(".filter-chip").forEach(c => {
    const on = c === btn;
    c.classList.toggle("active", on);
    c.setAttribute("aria-pressed", on ? "true" : "false");
  });
  renderList();
});

document.addEventListener("keydown", e => {
  // Ignore while confirmation modal is open
  const modal = document.getElementById("confirm-modal");
  if (modal && modal.classList.contains("open")) return;

  // Escape closes SS modal or tools panel
  const ssModal = document.getElementById("ss-modal");
  if (ssModal && ssModal.classList.contains("open")) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeSsModal();
    }
    return;
  }
  const tools = document.getElementById("tools-panel");
  if (tools && tools.classList.contains("open")) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeToolsPanel();
    }
    return;
  }

  const typing = isTypingTarget(e.target);
  const ctrl = e.ctrlKey || e.metaKey;

  // Ctrl+S : save according to focus (or everything if editor open)
  if (ctrl && e.key.toLowerCase() === "s") {
    e.preventDefault();
    if (currentIndex === null) return;
    (async () => {
      if (e.target && e.target.id === "desc-textarea") {
        await saveDesc();
      } else if (e.target && e.target.id === "game-name-input") {
        await saveName();
      } else if (e.target && (e.target.id || "").startsWith("meta-")) {
        await saveMeta();
      } else {
        // Stop at first failure
        if (!(await saveName())) return;
        if (!(await saveDesc())) return;
        await saveMeta();
      }
    })();
    return;
  }

  // Ctrl+F or / : focus search (when not typing in another field)
  if ((ctrl && e.key.toLowerCase() === "f") || (e.key === "/" && !typing)) {
    e.preventDefault();
    const search = document.getElementById("search");
    search.focus();
    search.select();
    return;
  }

  // Arrow navigation in the visible game list
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    const isSearch = e.target && e.target.id === "search";
    // Allow normal caret movement inside text fields, unless Alt is held.
    // From the search box, ↓ enters the list.
    if (typing && !e.altKey && !isSearch) return;
    if (isSearch && e.key === "ArrowUp") return;
    e.preventDefault();
    navigateGame(e.key === "ArrowDown" ? 1 : -1);
    return;
  }

  // Home / End → first / last visible game (not while typing)
  if ((e.key === "Home" || e.key === "End") && !typing) {
    const visible = getVisibleListIndices();
    if (!visible.length) return;
    e.preventDefault();
    selectGame(e.key === "Home" ? visible[0] : visible[visible.length - 1]);
    return;
  }

  // PageUp / PageDown → jump ~10 games
  if ((e.key === "PageDown" || e.key === "PageUp") && !typing) {
    e.preventDefault();
    navigateGame(e.key === "PageDown" ? 10 : -10);
    return;
  }
});
function askConfirm({ title, bodyHtml, showBackup = true }) {
  return new Promise(resolve => {
    const overlay = document.getElementById("confirm-modal");
    document.getElementById("confirm-title").textContent = title;
    document.getElementById("confirm-body").innerHTML = bodyHtml;
    const backupRow = document.getElementById("confirm-backup").closest("label")
      || document.getElementById("confirm-backup").parentElement;
    const backupCb = document.getElementById("confirm-backup");
    backupCb.checked = true;
    if (backupRow) backupRow.style.display = showBackup ? "" : "none";
    overlay.classList.add("open");

    const cleanup = (result) => {
      overlay.classList.remove("open");
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      overlay.removeEventListener("click", onOverlay);
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onOk = () => cleanup({
      confirmed: true,
      backup: document.getElementById("confirm-backup").checked,
    });
    const onCancel = () => cleanup({ confirmed: false, backup: false });
    const onOverlay = (e) => { if (e.target === overlay) onCancel(); };
    const onKey = (e) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onOk();
    };
    const okBtn = document.getElementById("confirm-ok");
    const cancelBtn = document.getElementById("confirm-cancel");
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    overlay.addEventListener("click", onOverlay);
    document.addEventListener("keydown", onKey);
    okBtn.focus();
  });
}

function openToolsPanel() {
  document.getElementById("tools-panel").classList.add("open");
  if (typeof loadSsConfig === "function") loadSsConfig();
}
function closeToolsPanel() {
  document.getElementById("tools-panel").classList.remove("open");
}

document.getElementById("btn-tools").addEventListener("click", openToolsPanel);

document.getElementById("btn-reload").addEventListener("click", async () => {
  await loadGames();
  toast("Liste rechargée");
});


document.getElementById("btn-quit").addEventListener("click", async () => {
  const choice = await askConfirm({
    title: "Quitter Gamelist Media Editor ?",
    bodyHtml:
      "<p>Le serveur s’arrête (fenêtre de commande).</p>" +
      "<p>Cet onglet du navigateur sera fermé si le navigateur le permet.</p>",
    showBackup: false,
  });
  if (!choice.confirmed) return;

  setStatus("Arrêt…");
  try {
    await fetch("/api/shutdown", { method: "POST" });
  } catch (e) {
    // Server may die before the response — expected
  }

  document.body.innerHTML =
    '<div class="shutdown-screen">' +
    '<div class="shutdown-emoji">👋</div>' +
    '<div class="shutdown-title">Serveur arrêté</div>' +
    '<div class="shutdown-msg">' +
    "Tu peux fermer cet onglet.<br>La fenêtre de commande devrait se fermer toute seule." +
    "</div></div>";

  // Often blocked by the browser if the tab was not opened by script
  setTimeout(() => {
    try { window.close(); } catch (e) {}
    try { window.open("", "_self"); window.close(); } catch (e) {}
  }, 300);
});

document.getElementById("tools-close").addEventListener("click", closeToolsPanel);
document.getElementById("tools-close-2").addEventListener("click", closeToolsPanel);
document.getElementById("tools-panel").addEventListener("click", e => {
  if (e.target.id === "tools-panel") closeToolsPanel();
});

document.getElementById("btn-manual-backup").addEventListener("click", async () => {
  setStatus("Sauvegarde du XML…");
  try {
    const data = await apiFetch("/api/backup", { method: "POST" });
    toast("✓ Sauvegarde créée : " + (data.filename || "gamelist.xml.bak"));
    setStatus("Sauvegarde .bak OK");
  } catch (e) {
    handleError(e);
  }
});

document.getElementById("btn-purge-regions").addEventListener("click", async () => {
  closeToolsPanel();
  const choice = await askConfirm({
    title: "Supprimer toutes les balises <region> ?",
    bodyHtml:
      "<p>Toutes les lignes <code>" + "&" + "lt;region&" + "gt;…&" + "lt;/region&" + "gt;</code> de <strong>tous</strong> les jeux seront retirées du fichier XML.</p>" +
      "<p>Cette action est irréversible sur le fichier courant.</p>",
  });
  if (!choice.confirmed) return;

  setStatus("Suppression des <region>…");
  try {
    const data = await apiFetch("/api/purge-regions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup: choice.backup }),
    });
    let msg = `✓ ${data.removed} balise(s) <region> supprimée(s)`;
    if (data.backup) msg += " — sauvegarde .bak créée";
    toast(msg);
    setStatus("Terminé");
  } catch (e) { handleError(e); }
});

document.getElementById("btn-delete-game").addEventListener("click", async () => {
  if (currentIndex === null) return;
  const g = games.find(x => x.index === currentIndex);
  const name = g ? g.name : "ce jeu";
  const choice = await askConfirm({
    title: `Supprimer « ${name} » ?`,
    bodyHtml:
      "<p>Suppression définitive de :</p>" +
      "<ul>" +
      "<li>la ROM</li>" +
      "<li>l’image, la vidéo, le marquee, le manuel, le boxback</li>" +
      "<li>toute l’entrée dans <code>gamelist.xml</code></li>" +
      "</ul>" +
      "<p><strong>Cette action est irréversible</strong> (sauf restauration manuelle du .bak).</p>",
  });
  if (!choice.confirmed) return;

  setStatus("Suppression du jeu…");
  try {
    const data = await apiFetch(`/api/delete-game/${currentIndex}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup: choice.backup }),
    });
    const nFiles = (data.deleted_files || []).length;
    let msg = `✓ « ${data.name} » supprimé (${nFiles} fichier(s) effacé(s))`;
    if (data.backup) msg += " — sauvegarde .bak créée";
    toast(msg);
    currentIndex = null;
    currentListIndex = null;
    document.getElementById("btn-delete-game").disabled = true;
    document.getElementById("editor").hidden = true;
    document.getElementById("empty-state").hidden = false;
    await loadGames();
  } catch (e) {
    handleError(e);
  }
});

async function boot() {
  try {
    GENRES = await apiFetch("/static/genres.json");
  } catch (e) {
    handleError(e, "Genres");
    GENRES = {};
  }
  initGenreSelects();
  loadGames();
}


/* ========== ScreenScraper ========== */
let ssBusy = false;

function setSsLoading(on, message) {
  ssBusy = !!on;
  const el = document.getElementById("ss-loading");
  const txt = document.getElementById("ss-loading-text");
  if (txt && message) txt.textContent = message;
  if (el) el.hidden = !on;
  document.body.classList.toggle("ss-busy", on);
  const scrapeBtn = document.getElementById("btn-ss-scrape");
  if (scrapeBtn) scrapeBtn.disabled = on || currentIndex === null;
  const adbBtn = document.getElementById("btn-adb-scrape");
  if (adbBtn) adbBtn.disabled = on || currentIndex === null;
  const applyBtn = document.getElementById("ss-modal-apply");
  if (applyBtn && !applyBtn.hidden) applyBtn.disabled = on;
  const testBtn = document.getElementById("btn-ss-test");
  if (testBtn) testBtn.disabled = on;
}

let ssLastProposed = null;
let scrapeSource = "screenscraper"; // or arcadeitalia

async function loadSsConfig() {
  try {
    const cfg = await apiFetch("/api/ss/config");
    document.getElementById("ss-ssid").value = cfg.ssid || "";
    document.getElementById("ss-region").value = cfg.prefer_region || "fr";
    document.getElementById("ss-sspassword").placeholder = cfg.sspassword_set
      ? "(enregistré — laisser vide pour ne pas changer)"
      : "Mot de passe membre (optionnel)";
    const st = document.getElementById("ss-status");
    if (cfg.user_boost) {
      st.textContent = "Boost membre actif";
      st.className = "ss-status ok";
    } else {
      st.textContent = "Quotas de base (boost optionnel ci-dessus)";
      st.className = "ss-status";
    }
  } catch (e) {
    document.getElementById("ss-status").textContent = "Erreur chargement config";
    document.getElementById("ss-status").className = "ss-status err";
  }
}

async function saveSsConfig() {
  const payload = {
    ssid: document.getElementById("ss-ssid").value.trim(),
    prefer_region: document.getElementById("ss-region").value,
  };
  const sspass = document.getElementById("ss-sspassword").value;
  if (sspass) payload.sspassword = sspass;
  try {
    await apiFetch("/api/ss/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    document.getElementById("ss-sspassword").value = "";
    await loadSsConfig();
    toast("✓ Paramètres ScreenScraper enregistrés");
  } catch (e) {
    handleError(e);
  }
}

async function testSsConfig() {
  if (ssBusy) return;
  const st = document.getElementById("ss-status");
  st.textContent = "Test en cours…";
  st.className = "ss-status";
  setSsLoading(true, "Test ScreenScraper…");
  try {
    // Persist form fields first (ssid / region / password if typed)
    await saveSsConfig();
    const data = await apiFetch("/api/ss/test", { method: "POST" });
    let msg = "✓ Connexion OK";
    if (data.mode === "user") {
      msg += " · niveau " + (data.level || "?");
      if (data.maxthreads) msg += " · threads " + data.maxthreads;
    } else {
      msg += " · " + (data.message || "dev OK");
    }
    st.textContent = msg;
    st.className = "ss-status ok";
    toast(msg);
  } catch (e) {
    st.textContent = "✗ " + e.message;
    st.className = "ss-status err";
    toast("ScreenScraper : " + e.message, "error");
  } finally {
    setSsLoading(false);
  }
}

function openSsModal() {
  document.getElementById("ss-modal").classList.add("open");
}
function closeSsModal() {
  document.getElementById("ss-modal").classList.remove("open");
  ssLastProposed = null;
  const cand = document.getElementById("ss-candidates");
  const fields = document.getElementById("ss-fields");
  if (cand) { cand.hidden = true; cand.innerHTML = ""; }
  if (fields) fields.hidden = false;
  const apply = document.getElementById("ss-modal-apply");
  if (apply) apply.hidden = false;
}

function buildSsFieldRows(proposed, current) {
  const box = document.getElementById("ss-fields");
  box.innerHTML = "";
  const metaFields = [
    { key: "name", label: "Nom" },
    { key: "desc", label: "Description" },
    { key: "rating", label: "Rating" },
    { key: "releasedate", label: "Date" },
    { key: "developer", label: "Developer" },
    { key: "publisher", label: "Publisher" },
    { key: "genre", label: "Genre" },
    { key: "players", label: "Players" },
    { key: "lang", label: "Lang" },
  ];
  const mediaFields = [
    { key: "image", label: "Image" },
    { key: "video", label: "Vidéo" },
    { key: "marquee", label: "Marquee" },
    { key: "manual", label: "Manuel" },
    { key: "boxback", label: "Boxback" },
  ];

  function addRow(key, label, newVal, oldVal, isMedia) {
    const hasNew = isMedia ? !!(proposed.medias && proposed.medias[key] && proposed.medias[key].url) : !!(newVal && String(newVal).trim());
    const row = document.createElement("div");
    row.className = "ss-field-row" + (hasNew ? "" : " disabled");
    const checked = hasNew && (!oldVal || isMedia);
    const preview = isMedia
      ? (hasNew
          ? `<span class="ss-new">URL ${escapeHtml(proposed.medias[key].type || "media")}</span>` +
            (oldVal ? `<br><span class="ss-old">${escapeHtml(oldVal)}</span>` : "")
          : "<em>non disponible</em>")
      : (hasNew
          ? `<span class="ss-new">${escapeHtml(String(newVal).slice(0, 220))}${String(newVal).length > 220 ? "…" : ""}</span>` +
            (oldVal ? `<br><span class="ss-old">${escapeHtml(String(oldVal).slice(0, 120))}</span>` : "")
          : "<em>vide côté ScreenScraper</em>");
    row.innerHTML =
      `<input type="checkbox" data-ss-field="${key}" ${checked ? "checked" : ""} ${hasNew ? "" : "disabled"} />` +
      `<label class="ss-field-name">${escapeHtml(label)}</label>` +
      `<div class="ss-field-values">${preview}</div>`;
    box.appendChild(row);
  }

  metaFields.forEach(f => addRow(f.key, f.label, proposed[f.key], current[f.key], false));
  mediaFields.forEach(f => addRow(f.key, f.label, null, current[f.key], true));
}

async function scrapeCurrentGame(gameid) {
  if (currentIndex === null) return;
  if (ssBusy) return;
  // Ignore DOM event objects accidentally passed as gameid
  if (gameid != null && typeof gameid !== "string" && typeof gameid !== "number") {
    gameid = null;
  }
  if (gameid != null) gameid = String(gameid).trim();
  if (gameid === "" || gameid === "undefined" || gameid === "null") gameid = null;

  const loadingMsg = gameid
    ? "Chargement du jeu ScreenScraper…"
    : "Recherche ScreenScraper…";
  setSsLoading(true, loadingMsg);
  setStatus("ScreenScraper : recherche…");
  try {
    const opts = { method: "POST", headers: { "Content-Type": "application/json" } };
    if (gameid) opts.body = JSON.stringify({ gameid });
    else opts.body = JSON.stringify({});
    let data;
    try {
      data = await apiFetch(`/api/ss/scrape/${currentIndex}`, opts);
    } catch (e) {
      // Enrich with technical fields if the server sent them
      const d = e.data || {};
      let msg = e.message;
      if (d.hash && d.hash.crc && !msg.includes("CRC")) msg += ` · CRC ${d.hash.crc}`;
      throw new Error(msg);
    }

    // Ambiguous: show candidate picker
    if (data.need_choice && data.candidates && data.candidates.length) {
      showSsCandidates(data);
      setStatus("ScreenScraper : choix requis");
      return;
    }

    if (!data.proposed) throw new Error("Pas de proposition");
    ssLastProposed = data.proposed;
    scrapeSource = data.source || "screenscraper";
    const titleEl = document.getElementById("ss-modal-title");
    if (titleEl) {
      titleEl.textContent = scrapeSource === "arcadeitalia"
        ? "🕹️ Arcade Database — appliquer les champs"
        : "📡 ScreenScraper — appliquer les champs";
    }
    const info = document.getElementById("ss-modal-info");
    const method = data.match_method || "?";
    if (scrapeSource === "arcadeitalia") {
      info.textContent =
        `Romset « ${data.proposed.adb_romset || data.proposed.ss_id || "?"} » · ` +
        `« ${data.proposed.name || "?"} » · dossier ${data.system_folder || "?"} · match: ${method}`;
    } else {
      info.textContent =
        `Jeu SS #${data.proposed.ss_id || "?"} · « ${data.proposed.name || "?"} » · ` +
        `système ${data.system_folder || "?"} (${data.system_id || "?"}) · ` +
        `match: ${method}` +
        (data.hash && data.hash.crc ? ` · CRC ${data.hash.crc}` + (data.hash.source ? ` [${data.hash.source}]` : "") : "");
    }
    document.getElementById("ss-fields").hidden = false;
    document.getElementById("ss-candidates").hidden = true;
    document.getElementById("ss-modal-apply").hidden = false;
    buildSsFieldRows(data.proposed, data.current || {});
    openSsModal();
    setStatus("ScreenScraper : résultat prêt");
  } catch (e) {
    handleError(e, "ScreenScraper");
  } finally {
    setSsLoading(false);
  }
}

function showSsCandidates(data) {
  const box = document.getElementById("ss-candidates");
  const fields = document.getElementById("ss-fields");
  fields.hidden = true;
  box.hidden = false;
  document.getElementById("ss-modal-apply").hidden = true;
  scrapeSource = data.source || "screenscraper";
  const titleEl = document.getElementById("ss-modal-title");
  if (titleEl) {
    titleEl.textContent = scrapeSource === "arcadeitalia"
      ? "🕹️ Arcade Database — choisir le jeu"
      : "📡 ScreenScraper — choisir le jeu";
  }
  const info = document.getElementById("ss-modal-info");
  info.textContent =
    (data.message || "Plusieurs résultats") +
    ` · recherche « ${data.search || data.local_name || data.romset || ""} » · ` +
    `dossier ${data.system_folder || "?"}` +
    (data.system_id != null ? ` (SS id ${data.system_id})` : "") +
    (data.hash && data.hash.crc ? ` · CRC ${data.hash.crc}` : "");
  box.innerHTML = "";
  (data.candidates || []).forEach(c => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ss-candidate";
    const scorePct = Math.round((c.score || 0) * 100);
    const idLabel = c.romset || c.ss_id || "?";
    btn.innerHTML =
      `<span class="ss-cand-name">${escapeHtml(c.name || idLabel)}</span>` +
      `<span class="ss-cand-meta">${escapeHtml(idLabel)}` +
      (c.system ? ` · ${escapeHtml(c.system)}` : "") +
      ` · similarité ${scorePct}%</span>`;
    btn.addEventListener("click", () => {
      closeSsModal();
      if (scrapeSource === "arcadeitalia") scrapeAdbGame(c.ss_id || c.romset);
      else scrapeCurrentGame(c.ss_id);
    });
    box.appendChild(btn);
  });
  openSsModal();
}

async function applySsSelection() {
  if (currentIndex === null || !ssLastProposed) return;
  if (ssBusy) return;
  const fields = [];
  document.querySelectorAll("#ss-fields input[data-ss-field]:checked").forEach(cb => {
    fields.push(cb.getAttribute("data-ss-field"));
  });
  if (!fields.length) {
    toast("Aucun champ sélectionné", "error");
    return;
  }
  setSsLoading(true, "Téléchargement / application…");
  setStatus("ScreenScraper : application…");
  try {
    const applyUrl = scrapeSource === "arcadeitalia"
      ? `/api/adb/apply/${currentIndex}`
      : `/api/ss/apply/${currentIndex}`;
    const data = await apiFetch(applyUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields, proposed: ssLastProposed }),
    });
    closeSsModal();
    await loadGames();
    let msg = `✓ ${(data.applied || []).length} champ(s) appliqué(s)`;
    if (data.errors && data.errors.length) msg += ` — ${data.errors.length} erreur(s)`;
    toast(msg);
    if (data.errors && data.errors.length) {
      console.warn("SS apply errors", data.errors);
    }
    setStatus("ScreenScraper terminé");
  } catch (e) {
    handleError(e, "ScreenScraper");
  } finally {
    setSsLoading(false);
  }
}

document.getElementById("btn-ss-save").addEventListener("click", saveSsConfig);
document.getElementById("btn-ss-test").addEventListener("click", testSsConfig);

async function scrapeAdbGame(romset) {
  if (currentIndex === null) return;
  if (ssBusy) return;
  if (romset != null && typeof romset !== "string" && typeof romset !== "number") romset = null;
  if (romset != null) romset = String(romset).trim() || null;

  setSsLoading(true, romset ? "Arcade Database : chargement…" : "Arcade Database : recherche…");
  setStatus("Arcade Database : recherche…");
  scrapeSource = "arcadeitalia";
  try {
    const opts = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(romset ? { romset } : {}),
    };
    let data;
    try {
      data = await apiFetch(`/api/adb/scrape/${currentIndex}`, opts);
    } catch (e) {
      throw new Error(e.message);
    }
    if (data.need_choice && data.candidates && data.candidates.length) {
      showSsCandidates(data);
      setStatus("Arcade Database : choix requis");
      return;
    }
    if (!data.proposed) throw new Error("Pas de proposition Arcade Database");
    ssLastProposed = data.proposed;
    scrapeSource = "arcadeitalia";
    const titleEl = document.getElementById("ss-modal-title");
    if (titleEl) titleEl.textContent = "🕹️ Arcade Database — appliquer les champs";
    const info = document.getElementById("ss-modal-info");
    info.textContent =
      `Romset « ${data.proposed.adb_romset || data.romset || "?"} » · « ${data.proposed.name || "?"} » · ` +
      `dossier ${data.system_folder || "?"} · match: ${data.match_method || "?"}`;
    document.getElementById("ss-fields").hidden = false;
    document.getElementById("ss-candidates").hidden = true;
    document.getElementById("ss-modal-apply").hidden = false;
    buildSsFieldRows(data.proposed, data.current || {});
    openSsModal();
    setStatus("Arcade Database : résultat prêt");
  } catch (e) {
    handleError(e, "Arcade Database");
  } finally {
    setSsLoading(false);
  }
}

document.getElementById("btn-ss-scrape").addEventListener("click", () => scrapeCurrentGame());
document.getElementById("btn-adb-scrape").addEventListener("click", () => scrapeAdbGame());
document.getElementById("ss-modal-close").addEventListener("click", closeSsModal);
document.getElementById("ss-modal-cancel").addEventListener("click", closeSsModal);
document.getElementById("ss-modal-apply").addEventListener("click", applySsSelection);
document.getElementById("ss-modal").addEventListener("click", e => {
  if (e.target.id === "ss-modal") closeSsModal();
});


boot();
