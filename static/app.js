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
function toast(msg, type = "success") {
const el = document.getElementById("toast");
el.textContent = msg;
el.className = "toast " + type + " show";
setTimeout(() => el.classList.remove("show"), 3200);
}
function setStatus(txt) { document.getElementById("status").textContent = txt; }
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

async function loadGames() {
  setStatus("Chargement…");
  const keepIndex = currentIndex;
  try {
    const res = await fetch("/api/games");
    games = await res.json();
    if (games.error) throw new Error(games.error);
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
        renderList();
      }
    } else {
      renderList();
    }
    setStatus("Prêt — " + games.length + " jeux chargés");
  } catch (e) {
    toast("Erreur chargement : " + e.message, "error");
    setStatus("Erreur");
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
    const res = await fetch(`/api/upload/${currentIndex}/${field}`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Erreur serveur");
    const g = games.find(x => x.index === currentIndex);
    if (g) { g[field] = data.path; renderZones(g); }
    renderList(document.getElementById("search").value);
    toast(`✓ ${field} → ${data.filename}`);
    setStatus("Enregistré");
  } catch (e) {
    toast("Erreur : " + e.message, "error");
    setStatus("Erreur");
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
    const res = await fetch(`/api/clear/${currentIndex}/${field}`, { method: "POST" });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Erreur");
    const g = games.find(x => x.index === currentIndex);
    if (g) { g[field] = ""; renderZones(g); }
    renderList(document.getElementById("search").value);
    toast("Champ retiré du XML");
  } catch (e) {
    toast("Erreur : " + e.message, "error");
  }
}
async function saveName() {
  if (currentIndex === null) return true;
  const newName = document.getElementById("game-name-input").value.trim();
  if (!newName) { toast("Le nom ne peut pas être vide", "error"); return false; }
  setStatus("Enregistrement du nom…");
  try {
    const res = await fetch(`/api/name/${currentIndex}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Erreur serveur");
    const g = games.find(x => x.index === currentIndex);
    if (g) g.name = newName;
    games.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    currentListIndex = games.findIndex(x => x.index === currentIndex);
    renderList(document.getElementById("search").value);
    toast("✓ Nom enregistré");
    setStatus("Enregistré");
    return true;
  } catch (e) {
    toast("Erreur : " + e.message, "error");
    setStatus("Erreur");
    return false;
  }
}

async function saveDesc() {
  if (currentIndex === null) return true;
  const newDesc = document.getElementById("desc-textarea").value;
  setStatus("Enregistrement de la description…");
  try {
    const res = await fetch(`/api/desc/${currentIndex}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ desc: newDesc }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Erreur serveur");
    const g = games.find(x => x.index === currentIndex);
    if (g) g.desc = newDesc;
    toast("✓ Description enregistrée");
    setStatus("Enregistré");
    return true;
  } catch (e) {
    toast("Erreur : " + e.message, "error");
    setStatus("Erreur");
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
    const res = await fetch(`/api/meta/${currentIndex}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Erreur serveur");
    const g = games.find(x => x.index === currentIndex);
    if (g && data.updated) Object.assign(g, data.updated);
    toast("✓ Métadonnées enregistrées");
    setStatus("Enregistré");
    return true;
  } catch (e) {
    toast("Erreur : " + e.message, "error");
    setStatus("Erreur");
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

  // Escape closes tools panel
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
    const res = await fetch("/api/backup", { method: "POST" });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Erreur serveur");
    toast("✓ Sauvegarde créée : " + (data.filename || "gamelist.xml.bak"));
    setStatus("Sauvegarde .bak OK");
  } catch (e) {
    toast("Erreur : " + e.message, "error");
    setStatus("Erreur");
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
    const res = await fetch("/api/purge-regions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup: choice.backup }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Erreur serveur");
    let msg = `✓ ${data.removed} balise(s) <region> supprimée(s)`;
    if (data.backup) msg += " — sauvegarde .bak créée";
    toast(msg);
    setStatus("Terminé");
  } catch (e) { toast("Erreur : " + e.message, "error"); setStatus("Erreur"); }
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
    const res = await fetch(`/api/delete-game/${currentIndex}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup: choice.backup }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Erreur serveur");
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
    toast("Erreur : " + e.message, "error");
    setStatus("Erreur");
  }
});

async function boot() {
  try {
    const res = await fetch("/static/genres.json");
    if (!res.ok) throw new Error("HTTP " + res.status);
    GENRES = await res.json();
  } catch (e) {
    console.error(e);
    toast("Impossible de charger les genres : " + e.message, "error");
  }
  initGenreSelects();
  loadGames();
}

boot();
