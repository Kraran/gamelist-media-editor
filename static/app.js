const FIELD_DEFS = [
{ key: "image",   icon: "🖼️" },
{ key: "video",   icon: "🎬" },
{ key: "marquee", icon: "🏷️" },
{ key: "manual",  icon: "📖" },
{ key: "boxback", icon: "📦" },
];
function getFields() {
  return FIELD_DEFS.map(f => ({
    ...f,
    label: t("fields." + f.key, null, f.key),
  }));
}
/** @deprecated use getFields() — kept as live view for older call sites */
let FIELDS = FIELD_DEFS.map(f => ({ ...f, label: f.key }));

/* ========== i18n ========== */
const LOCALE_KEY = "gme_locale";
const DEFAULT_LOCALE = "fr";
let I18N = {};
let currentLocale = DEFAULT_LOCALE;

function getStoredLocale() {
  try {
    const v = localStorage.getItem(LOCALE_KEY);
    if (v && /^[a-z]{2}(-[A-Z]{2})?$/.test(v)) return v.split("-")[0];
  } catch (_) {}
  return DEFAULT_LOCALE;
}

function t(key, params, fallback) {
  const parts = String(key || "").split(".");
  let cur = I18N;
  for (const p of parts) {
    if (cur && typeof cur === "object" && p in cur) cur = cur[p];
    else {
      cur = null;
      break;
    }
  }
  let s = (typeof cur === "string") ? cur : (fallback != null ? fallback : key);
  if (params && typeof params === "object") {
    s = s.replace(/\{(\w+)\}/g, (_, k) => (params[k] != null ? String(params[k]) : "{" + k + "}"));
  }
  return s;
}

function applyI18n() {
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    let params = null;
    const raw = el.getAttribute("data-i18n-params");
    if (raw) {
      try { params = JSON.parse(raw); } catch (_) {}
    }
    el.textContent = t(key, params);
  });
  document.querySelectorAll("[data-i18n-html]").forEach(el => {
    el.innerHTML = t(el.getAttribute("data-i18n-html"));
  });
  document.querySelectorAll("[data-i18n-title]").forEach(el => {
    el.title = t(el.getAttribute("data-i18n-title"));
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
    el.placeholder = t(el.getAttribute("data-i18n-placeholder"));
  });
  document.querySelectorAll("[data-i18n-aria]").forEach(el => {
    el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria")));
  });
  const root = document.documentElement;
  if (root) root.lang = currentLocale;
  FIELDS = getFields();
  // Refresh dynamic bits that depend on locale
  try {
    const mainSel = document.getElementById("meta-genre-main");
    if (mainSel && Object.keys(GENRES || {}).length) {
      const v = mainSel.value;
      initGenreSelects();
      if (v) mainSel.value = v;
    }
  } catch (_) {}
  try { updateFilterCounts(); } catch (_) {}
  try {
    if (typeof games !== "undefined" && games.length) {
      const badge = document.getElementById("game-count");
      if (badge) {
        const q = (document.getElementById("search") || {}).value || "";
        const filtered = typeof getFilteredGames === "function" ? getFilteredGames(q.toLowerCase().trim()) : games;
        if (filtered.length === games.length) {
          badge.textContent = t("header.game_count", { n: games.length });
        } else {
          badge.textContent = t("header.game_count_filtered", { visible: filtered.length, total: games.length });
        }
      }
    }
  } catch (_) {}
}

async function loadLocale(code) {
  const lang = (code || DEFAULT_LOCALE).split("-")[0];
  try {
    const res = await fetch("/static/locales/" + lang + ".json", { cache: "no-cache" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    I18N = await res.json();
    currentLocale = lang;
    try { localStorage.setItem(LOCALE_KEY, lang); } catch (_) {}
    applyI18n();
    return true;
  } catch (e) {
    console.error("locale load failed", lang, e);
    if (lang !== DEFAULT_LOCALE) return loadLocale(DEFAULT_LOCALE);
    return false;
  }
}

async function setLocale(code, { silent = false } = {}) {
  const ok = await loadLocale(code);
  const sel = document.getElementById("ui-lang");
  if (sel) sel.value = currentLocale;
  // Re-render open editor zones with new field labels
  try {
    if (currentIndex != null) {
      const g = games.find(x => x.index === currentIndex);
      if (g && typeof renderZones === "function") renderZones(g);
    }
  } catch (_) {}
  try {
    if (typeof renderList === "function") renderList();
  } catch (_) {}
  if (!silent) {
    toast(t("tools.lang_changed"), ok ? "success" : "error");
  }
  return ok;
}

function wireLanguageControls() {
  const sel = document.getElementById("ui-lang");
  const btn = document.getElementById("btn-lang-apply");
  if (sel) sel.value = currentLocale;
  if (btn && !btn.dataset.i18nWired) {
    btn.dataset.i18nWired = "1";
    btn.addEventListener("click", async () => {
      const code = (sel && sel.value) || currentLocale;
      btn.disabled = true;
      try {
        await setLocale(code);
      } finally {
        btn.disabled = false;
      }
    });
  }
  // Also apply on change for convenience (still has explicit button)
  if (sel && !sel.dataset.i18nWired) {
    sel.dataset.i18nWired = "1";
    sel.addEventListener("change", async () => {
      // Wait for explicit Apply — do not auto-switch
    });
  }
}

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
  options = { ...options };
  const headers = new Headers(options.headers || {});
  if (!headers.has("X-Locale")) {
    headers.set("X-Locale", (typeof currentLocale !== "undefined" && currentLocale) ? currentLocale : "fr");
  }
  options.headers = headers;
  let res;
  try {
    res = await fetch(url, options);
  } catch (e) {
    const offline = (typeof navigator !== "undefined" && navigator.onLine === false);
    throw new Error(
      offline
        ? t("errors.offline")
        : t("errors.server_down")
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
    let msg = serverMsg || t("errors.http", { status: res.status });
    if (res.status === 404 && !serverMsg) msg = t("errors.not_found");
    if (res.status === 413) msg = t("errors.too_large");
    if (res.status >= 500 && !serverMsg) msg = t("errors.internal", { status: res.status });
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
  setStatus(isQuota ? t("status.quota") : t("status.error"));
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
mainSel.innerHTML = '<option value="">' + t("editor.genre_choose") + '</option>';
Object.keys(GENRES).sort().forEach(main => {
const opt = document.createElement("option");
opt.value = main; opt.textContent = main;
mainSel.appendChild(opt);
});
}
function fillSubGenres(main, selectedSub = "") {
const subSel = document.getElementById("meta-genre-sub");
subSel.innerHTML = '<option value="">' + t('editor.genre_none') + '</option>';
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
    el.textContent = t("header.game_count", { n: games.length });
  } else {
    el.textContent = t("header.game_count_filtered", { visible: visibleCount, total: games.length });
  }
}

function updateFilterCounts(q) {
  const query = (q || "").toLowerCase().trim();
  const counts = { all: 0, image: 0, video: 0, marquee: 0, manual: 0, boxback: 0, any: 0 };
  games.forEach(g => {
    if (!matchesSearch(g, query)) return;
    counts.all++;
    getFields().forEach(f => {
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
    el.title = t("header.system_unknown");
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
  setStatus(t("status.loading"));
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
      if (data.xml_path) {
        window.__gmeXmlPath = data.xml_path;
        if (typeof pushRecentGamelist === "function") pushRecentGamelist(data.xml_path);
      }
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
    setStatus(t("status.ready", { n: games.length }));
  } catch (e) {
    handleError(e, t("errors.load"));
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
    const dots = getFields().map(f =>
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
    empty.innerHTML = games.length
      ? t("sidebar.empty_no_match")
      : t("sidebar.empty_no_games");
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
getFields().forEach(f => {
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
previewHtml = `<div class="placeholder"><div class="big">📄</div><div>${t("zone.manual_pdf")}</div><a class="manual-link" href="${url}" target="_blank" rel="noopener">${t("zone.open")}</a></div>`;
} else {
previewHtml = `<img src="${url}" alt="${f.label}" onerror="this.parentElement.innerHTML='<div class=\'placeholder\'><div class=\'big\'>⚠️</div>${t("zone.preview_unavailable")}</div>'" />`;
}
} else {
previewHtml = `<div class="placeholder"><div class="big">${f.icon}</div><div>${t("zone.drop")}</div></div>`;
}
zone.innerHTML = `
<div class="zone-header">
<div class="zone-title"><span class="icon">${f.icon}</span> ${f.label}</div>
<div class="zone-actions">${has ? `<button class="btn btn-danger" data-action="clear" title="${t("zone.clear_title")}">✕</button>` : ""}</div>
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
else toast(t("toast.no_file_url"), "error");
}
async function uploadMedia(field, { file, url }) {
  if (currentIndex === null) return;
  if (file && typeof file.size === "number" && file.size > MAX_UPLOAD_BYTES) {
    toast(t("toast.file_too_large", { n: MAX_UPLOAD_BYTES / (1024 * 1024) }), "error");
    return;
  }
  setStatus(file ? t("status.sending_file") : t("status.downloading"));
  const form = new FormData();
  if (file) form.append("file", file);
  if (url) form.append("url", url);
  try {
    const data = await apiFetch(`/api/upload/${currentIndex}/${field}`, { method: "POST", body: form });
    const g = games.find(x => x.index === currentIndex);
    if (g) { g[field] = data.path; renderZones(g); }
    renderList(document.getElementById("search").value);
    toast(t("toast.upload_ok", { field, filename: data.filename }));
    setStatus(t("status.saved"));
  } catch (e) {
    handleError(e);
  }
}

async function clearField(field) {
  // Detach media tag in XML only (file kept on disk)
  const choice = await askConfirm({
    title: t("confirm.clear_field_title", { field }),
    bodyHtml: t("confirm.clear_field_body"),
    showBackup: false,
  });
  if (!choice.confirmed) return;
  try {
    const data = await apiFetch(`/api/clear/${currentIndex}/${field}`, { method: "POST" });
    const g = games.find(x => x.index === currentIndex);
    if (g) { g[field] = ""; renderZones(g); }
    renderList(document.getElementById("search").value);
    toast(t("toast.field_cleared"));
  } catch (e) {
    handleError(e);
  }
}
async function saveName() {
  if (currentIndex === null) return true;
  const newName = document.getElementById("game-name-input").value.trim();
  if (!newName) { toast(t("toast.name_empty"), "error"); return false; }
  setStatus(t("status.saving_name"));
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
    toast(t("toast.name_saved"));
    setStatus(t("status.saved"));
    return true;
  } catch (e) {
    handleError(e);
    return false;
  }
}

async function saveDesc() {
  if (currentIndex === null) return true;
  const newDesc = document.getElementById("desc-textarea").value;
  setStatus(t("status.saving_desc"));
  try {
    const data = await apiFetch(`/api/desc/${currentIndex}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ desc: newDesc }),
    });
    const g = games.find(x => x.index === currentIndex);
    if (g) g.desc = newDesc;
    toast(t("toast.desc_saved"));
    setStatus(t("status.saved"));
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
  setStatus(t("status.saving_meta"));
  try {
    const data = await apiFetch(`/api/meta/${currentIndex}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const g = games.find(x => x.index === currentIndex);
    if (g && data.updated) Object.assign(g, data.updated);
    toast(t("toast.meta_saved"));
    setStatus(t("status.saved"));
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
function askConfirm({ title, bodyHtml, showBackup = true, okLabel, cancelLabel }) {
  return new Promise(resolve => {
    const overlay = document.getElementById("confirm-modal");
    document.getElementById("confirm-title").textContent = title;
    document.getElementById("confirm-body").innerHTML = bodyHtml;
    const okBtn = document.getElementById("confirm-ok");
    const cancelBtn = document.getElementById("confirm-cancel");
    if (okBtn) okBtn.textContent = okLabel || t("confirm.ok");
    if (cancelBtn) cancelBtn.textContent = cancelLabel || t("confirm.cancel");
    const bakSpan = document.querySelector('[data-i18n="confirm.backup_label"]');
    if (bakSpan) bakSpan.textContent = t("confirm.backup_label");
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
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    overlay.addEventListener("click", onOverlay);
    document.addEventListener("keydown", onKey);
    okBtn.focus();
  });
}

function openToolsPanel() {
  document.getElementById("tools-panel").classList.add("open");
  wireLanguageControls();
  const sel = document.getElementById("ui-lang");
  if (sel) sel.value = currentLocale;
  if (typeof loadSsConfig === "function") loadSsConfig();
}
function closeToolsPanel() {
  document.getElementById("tools-panel").classList.remove("open");
}

document.getElementById("btn-tools").addEventListener("click", openToolsPanel);

document.getElementById("btn-reload").addEventListener("click", async () => {
  await loadGames();
  toast(t("toast.list_reloaded"));
});


document.getElementById("btn-quit").addEventListener("click", async () => {
  const choice = await askConfirm({
    title: t("confirm.quit_title"),
    bodyHtml: t("confirm.quit_body"),
    showBackup: false,
  });
  if (!choice.confirmed) return;

  setStatus(t("confirm.quit_ok") + "…");
  try {
    await fetch("/api/shutdown", { method: "POST" });
  } catch (e) {
    // Server may die before the response — expected
  }

  document.body.innerHTML =
    '<div class="shutdown-screen">' +
    '<div class="shutdown-emoji">👋</div>' +
    '<div class="shutdown-title">' + t("status.shutdown_title") + '</div>' +
    '<div class="shutdown-msg">' + t("status.shutdown_msg") + "</div></div>";

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
  setStatus(t("status.backup_xml"));
  try {
    const data = await apiFetch("/api/backup", { method: "POST" });
    toast(t("toast.backup_ok", { filename: data.filename || "gamelist.xml.bak" }));
    setStatus(t("status.backup_ok_status"));
  } catch (e) {
    handleError(e);
  }
});

document.getElementById("btn-purge-regions").addEventListener("click", async () => {
  closeToolsPanel();
  const choice = await askConfirm({
    title: t("confirm.purge_title"),
    bodyHtml: t("confirm.purge_body"),
  });
  if (!choice.confirmed) return;

  setStatus(t("status.purging_regions"));
  try {
    const data = await apiFetch("/api/purge-regions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup: choice.backup }),
    });
    let msg = t("toast.purge_ok", { n: data.removed });
    if (data.backup) msg += t("toast.purge_bak");
    toast(msg);
    setStatus(t("status.done"));
  } catch (e) { handleError(e); }
});

document.getElementById("btn-delete-game").addEventListener("click", async () => {
  if (currentIndex === null) return;
  const g = games.find(x => x.index === currentIndex);
  const name = g ? g.name : t("confirm.this_game");
  const choice = await askConfirm({
    title: t("confirm.delete_title", { name }),
    bodyHtml: t("confirm.delete_body"),
  });
  if (!choice.confirmed) return;

  setStatus(t("status.deleting_game"));
  try {
    const data = await apiFetch(`/api/delete-game/${currentIndex}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup: choice.backup }),
    });
    const nFiles = (data.deleted_files || []).length;
    let msg = t("toast.delete_ok", { name: data.name, n: nFiles });
    if (data.backup) msg += t("toast.purge_bak");
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


/* --- Switch gamelist.xml without restart --------------------------------- */
const RECENT_GL_KEY = "gme_recent_gamelists";
const RECENT_GL_MAX = 8;

function getRecentGamelists() {
  try {
    const raw = localStorage.getItem(RECENT_GL_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((p) => typeof p === "string" && p) : [];
  } catch (_) {
    return [];
  }
}

function pushRecentGamelist(path) {
  if (!path) return;
  const list = getRecentGamelists().filter((p) => p !== path);
  list.unshift(path);
  localStorage.setItem(RECENT_GL_KEY, JSON.stringify(list.slice(0, RECENT_GL_MAX)));
}

function renderRecentGamelists() {
  const box = document.getElementById("open-gl-recent");
  if (!box) return;
  const list = getRecentGamelists();
  if (!list.length) {
    box.innerHTML = `<div class="open-gl-recent-empty">${escapeHtml(t("open_gl.recent_empty"))}</div>`;
    return;
  }
  box.innerHTML = list
    .map(
      (p) =>
        `<button type="button" class="open-gl-recent-item" role="listitem" data-path="${escapeHtml(p)}">${escapeHtml(p)}</button>`
    )
    .join("");
  box.querySelectorAll(".open-gl-recent-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.getElementById("open-gl-path").value = btn.getAttribute("data-path") || "";
    });
  });
}

let __browsePath = null;
let __browseParent = null;

async function browseDirectory(path) {
  const listing = document.getElementById("open-gl-listing");
  const pathEl = document.getElementById("open-gl-browse-path");
  const upBtn = document.getElementById("open-gl-up");
  const drivesEl = document.getElementById("open-gl-drives");
  if (listing) listing.innerHTML = `<div class="open-gl-listing-empty">${escapeHtml(t("open_gl.loading"))}</div>`;
  try {
    const q = path ? `?path=${encodeURIComponent(path)}` : "";
    const data = await apiFetch(`/api/browse${q}`);
    __browsePath = data.path || null;
    __browseParent = data.parent || null;
    if (pathEl) pathEl.textContent = __browsePath || "—";
    if (upBtn) upBtn.disabled = !__browseParent;

    if (drivesEl) {
      const drives = data.drives || [];
      if (drives.length) {
        drivesEl.hidden = false;
        drivesEl.innerHTML = drives
          .map(
            (d) =>
              `<button type="button" class="open-gl-drive" data-path="${escapeHtml(d.path)}">${escapeHtml(d.name)}</button>`
          )
          .join("");
        drivesEl.querySelectorAll(".open-gl-drive").forEach((btn) => {
          btn.addEventListener("click", () => browseDirectory(btn.getAttribute("data-path")));
        });
      } else {
        drivesEl.hidden = true;
        drivesEl.innerHTML = "";
      }
    }

    const dirs = data.dirs || [];
    const files = data.files || [];
    if (!dirs.length && !files.length) {
      listing.innerHTML = `<div class="open-gl-listing-empty">${escapeHtml(t("open_gl.empty_folder"))}</div>`;
      return;
    }

    const parts = [];
    for (const d of dirs) {
      parts.push(
        `<button type="button" class="open-gl-item open-gl-dir" role="listitem" data-path="${escapeHtml(d.path)}">` +
          `<span class="open-gl-item-icon">📁</span><span>${escapeHtml(d.name)}</span></button>`
      );
    }
    for (const f of files) {
      const cls = f.is_gamelist ? "open-gl-item open-gl-file is-gamelist" : "open-gl-item open-gl-file";
      const icon = f.is_gamelist ? "🎮" : "📄";
      parts.push(
        `<button type="button" class="${cls}" role="listitem" data-path="${escapeHtml(f.path)}">` +
          `<span class="open-gl-item-icon">${icon}</span><span>${escapeHtml(f.name)}</span></button>`
      );
    }
    listing.innerHTML = parts.join("");

    listing.querySelectorAll(".open-gl-dir").forEach((btn) => {
      btn.addEventListener("click", () => browseDirectory(btn.getAttribute("data-path")));
      btn.addEventListener("dblclick", () => browseDirectory(btn.getAttribute("data-path")));
    });
    listing.querySelectorAll(".open-gl-file").forEach((btn) => {
      btn.addEventListener("click", () => {
        listing.querySelectorAll(".open-gl-file.is-selected").forEach((el) => el.classList.remove("is-selected"));
        btn.classList.add("is-selected");
        const p = btn.getAttribute("data-path") || "";
        document.getElementById("open-gl-path").value = p;
      });
      btn.addEventListener("dblclick", () => {
        const p = btn.getAttribute("data-path") || "";
        document.getElementById("open-gl-path").value = p;
        applyOpenGamelist();
      });
    });
  } catch (e) {
    if (listing) {
      listing.innerHTML = `<div class="open-gl-listing-empty">${escapeHtml((e && e.message) || t("open_gl.browse_error"))}</div>`;
    }
  }
}

function openGamelistModal() {
  const modal = document.getElementById("open-gamelist-modal");
  const cur = document.getElementById("open-gl-current-path");
  const input = document.getElementById("open-gl-path");
  if (cur) cur.textContent = window.__gmeXmlPath || "—";
  if (input) input.value = "";
  renderRecentGamelists();
  modal.classList.add("open");
  // Default browse: parent of current gamelist (server decides when path omitted)
  browseDirectory(null);
  setTimeout(() => input && input.focus(), 50);
}

function closeGamelistModal() {
  document.getElementById("open-gamelist-modal").classList.remove("open");
}

function resetEditorSelection() {
  currentIndex = null;
  currentListIndex = null;
  const del = document.getElementById("btn-delete-game");
  if (del) del.disabled = true;
  const editor = document.getElementById("editor");
  const empty = document.getElementById("empty-state");
  if (editor) editor.hidden = true;
  if (empty) empty.hidden = false;
}

async function applyOpenGamelist() {
  const input = document.getElementById("open-gl-path");
  const path = (input && input.value || "").trim().replace(/^["']|["']$/g, "");
  if (!path) {
    toast(t("open_gl.need_path"), "error");
    return;
  }
  setStatus(t("status.opening_gamelist"));
  try {
    const data = await apiFetch("/api/open-gamelist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    window.__gmeXmlPath = data.xml_path || path;
    pushRecentGamelist(window.__gmeXmlPath);
    games = data.games || [];
    resetEditorSelection();
    updateSystemBadge(data.system || null);
    const sysEl = document.getElementById("system-name");
    if (sysEl && data.xml_path) sysEl.title = data.xml_path;
    const searchEl = document.getElementById("search");
    if (searchEl) searchEl.value = "";
    renderList("");
    closeGamelistModal();
    const label = (data.system && (data.system.label || data.system.folder)) || path;
    toast(t("toast.gamelist_opened", { name: label, n: data.count != null ? data.count : games.length }));
    setStatus(t("status.ready", { n: games.length }));
  } catch (e) {
    handleError(e);
  }
}


document.getElementById("open-gl-up").addEventListener("click", () => {
  if (__browseParent) browseDirectory(__browseParent);
});
document.getElementById("open-gl-refresh").addEventListener("click", () => {
  browseDirectory(__browsePath || null);
});

document.getElementById("btn-open-gamelist").addEventListener("click", openGamelistModal);
document.getElementById("open-gl-close").addEventListener("click", closeGamelistModal);
document.getElementById("open-gl-cancel").addEventListener("click", closeGamelistModal);
document.getElementById("open-gl-apply").addEventListener("click", applyOpenGamelist);
document.getElementById("open-gl-path").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    applyOpenGamelist();
  }
});
document.getElementById("open-gamelist-modal").addEventListener("click", (e) => {
  if (e.target.id === "open-gamelist-modal") closeGamelistModal();
});
document.getElementById("open-gl-path").addEventListener("dragover", (e) => e.preventDefault());
document.getElementById("open-gl-path").addEventListener("drop", (e) => {
  e.preventDefault();
  const dt = e.dataTransfer;
  if (!dt) return;
  const txt = (dt.getData("text/plain") || dt.getData("text") || "").trim();
  if (txt) {
    document.getElementById("open-gl-path").value = txt.replace(/^["']|["']$/g, "");
    return;
  }
  if (dt.files && dt.files.length) {
    toast(t("open_gl.drop_hint"), "error");
  }
});


/* --- About dialog (RomSet Verifier style) --- */
const APP_ABOUT = {
  version: "1.1.3",
  versionLabel: "v1.1.3",
  date: "2026-08-16",
  author: "Franck Fornasari",
  repo: "https://github.com/Kraran/gamelist-media-editor",
  authorUrl: "https://github.com/Kraran",
};

function openAbout() {
  const v = document.getElementById("about-version-label");
  const v2 = document.getElementById("about-version");
  const d = document.getElementById("about-date");
  const bv = document.getElementById("brand-version");
  if (v) v.textContent = APP_ABOUT.versionLabel;
  if (v2) v2.textContent = APP_ABOUT.version;
  if (d) d.textContent = APP_ABOUT.date;
  if (bv) bv.textContent = APP_ABOUT.versionLabel;
  const m = document.getElementById("about-modal");
  if (m) m.classList.add("open");
}

function closeAbout() {
  const m = document.getElementById("about-modal");
  if (m) m.classList.remove("open");
}

document.getElementById("btn-about")?.addEventListener("click", openAbout);
document.getElementById("about-close")?.addEventListener("click", closeAbout);
document.getElementById("about-close-primary")?.addEventListener("click", closeAbout);
document.getElementById("about-author-page")?.addEventListener("click", () => {
  window.open(APP_ABOUT.authorUrl, "_blank", "noopener");
});
document.getElementById("about-github")?.addEventListener("click", () => {
  window.open(APP_ABOUT.repo, "_blank", "noopener");
});
document.getElementById("about-modal")?.addEventListener("click", (e) => {
  if (e.target.id === "about-modal") closeAbout();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const m = document.getElementById("about-modal");
    if (m && m.classList.contains("open")) closeAbout();
  }
});

async function boot() {
  await loadLocale(getStoredLocale());
  wireLanguageControls();
  try {
    GENRES = await apiFetch("/static/genres.json");
  } catch (e) {
    handleError(e, t("errors.genres"));
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
      ? t("tools.ss_pass_saved_ph")
      : t("tools.ss_pass_optional_ph");
    const st = document.getElementById("ss-status");
    if (cfg.user_boost) {
      st.textContent = t("tools.ss_boost_on");
      st.className = "ss-status ok";
    } else {
      st.textContent = t("tools.ss_boost_off");
      st.className = "ss-status";
    }
  } catch (e) {
    document.getElementById("ss-status").textContent = t("tools.ss_cfg_err");
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
    toast(t("toast.ss_saved"));
  } catch (e) {
    handleError(e);
  }
}

async function testSsConfig() {
  if (ssBusy) return;
  const st = document.getElementById("ss-status");
  st.textContent = t("status.testing");
  st.className = "ss-status";
  setSsLoading(true, t("scrape.test_loading"));
  try {
    // Persist form fields first (ssid / region / password if typed)
    await saveSsConfig();
    const data = await apiFetch("/api/ss/test", { method: "POST" });
    let msg = t("scrape.test_ok_short");
    if (data.mode === "user") {
      msg += " · " + t("scrape.test_level", { level: data.level || "?" });
      if (data.maxthreads) msg += " · " + t("scrape.test_threads", { n: data.maxthreads });
    } else {
      msg += " · " + (data.message || t("scrape.test_dev_ok"));
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
    { key: "name", label: t("scrape.field_name") },
    { key: "desc", label: t("scrape.field_desc") },
    { key: "rating", label: t("scrape.field_rating") },
    { key: "releasedate", label: t("scrape.field_releasedate") },
    { key: "developer", label: t("scrape.field_developer") },
    { key: "publisher", label: t("scrape.field_publisher") },
    { key: "genre", label: t("scrape.field_genre") },
    { key: "players", label: t("scrape.field_players") },
    { key: "lang", label: t("scrape.field_lang") },
  ];
  const mediaFields = [
    { key: "image", label: t("scrape.field_image") },
    { key: "video", label: t("scrape.field_video") },
    { key: "marquee", label: t("scrape.field_marquee") },
    { key: "manual", label: t("scrape.field_manual") },
    { key: "boxback", label: t("scrape.field_boxback") },
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
          : "<em>" + t("scrape.empty_ss") + "</em>");
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
    ? t("scrape.ss_load_game")
    : t("scrape.ss_search");
  setSsLoading(true, loadingMsg);
  setStatus(t("scrape.ss_status_search"));
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
      setStatus(t("scrape.ss_status_choice"));
      return;
    }

    if (!data.proposed) throw new Error(t("scrape.no_proposal"));
    ssLastProposed = data.proposed;
    scrapeSource = data.source || "screenscraper";
    const titleEl = document.getElementById("ss-modal-title");
    if (titleEl) {
      titleEl.textContent = scrapeSource === "arcadeitalia"
        ? t("scrape.adb_modal_apply")
        : t("scrape.ss_modal_apply");
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
    setStatus(t("scrape.ss_status_ready"));
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
      ? t("scrape.adb_modal_choose")
      : t("scrape.ss_modal_choose");
  }
  const info = document.getElementById("ss-modal-info");
  info.textContent =
    (data.message || t("scrape.multiple_results")) +
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
      ` · ${t("scrape.similarity", { pct: scorePct })}</span>`;
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
    toast(t("toast.no_fields"), "error");
    return;
  }
  setSsLoading(true, t("status.applying_download"));
  setStatus(t("scrape.ss_status_apply"));
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
    let msg = t("scrape.apply_ok", { n: (data.applied || []).length });
    if (data.errors && data.errors.length) msg += t("scrape.apply_errors", { n: data.errors.length });
    toast(msg);
    if (data.errors && data.errors.length) {
      console.warn("SS apply errors", data.errors);
    }
    setStatus(t("scrape.ss_done"));
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

  setSsLoading(true, romset ? t("scrape.adb_load") : t("scrape.adb_search"));
  setStatus(t("scrape.adb_status_search"));
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
      setStatus(t("scrape.adb_status_choice"));
      return;
    }
    if (!data.proposed) throw new Error(t("scrape.no_proposal_adb"));
    ssLastProposed = data.proposed;
    scrapeSource = "arcadeitalia";
    const titleEl = document.getElementById("ss-modal-title");
    if (titleEl) titleEl.textContent = t("scrape.adb_modal_apply");
    const info = document.getElementById("ss-modal-info");
    info.textContent = t("scrape.adb_info", {
      romset: data.proposed.adb_romset || data.romset || "?",
      name: data.proposed.name || "?",
      folder: data.system_folder || "?",
      method: data.match_method || "?",
    });
    document.getElementById("ss-fields").hidden = false;
    document.getElementById("ss-candidates").hidden = true;
    document.getElementById("ss-modal-apply").hidden = false;
    buildSsFieldRows(data.proposed, data.current || {});
    openSsModal();
    setStatus(t("scrape.adb_status_ready"));
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
