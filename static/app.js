/**
 * Gamelist Media Editor — front-end (vanilla JS).
 *
 * Talks to the local Flask API on the same origin.
 * i18n: static/locales/{code}.json loaded via loadLocale(); server messages use X-Locale.
 * State: `games` (sorted list from XML), `currentIndex` (XML index), `currentListIndex` (filtered list).
 * No gamelist at start: setNoGamelistUi(false) + openGamelistModal() from boot().
 */
/** SVG icon from the embedded sprite (templates/_icons.svg, Tabler Icons). */
function icon(name, cls = "") {
  return `<svg class="icon${cls ? " " + cls : ""}" aria-hidden="true" focusable="false"><use href="#i-${name}"></use></svg>`;
}

const FIELD_DEFS = [
{ key: "image",     icon: "photo" },
{ key: "video",     icon: "movie" },
{ key: "marquee",   icon: "tag" },
{ key: "manual",    icon: "book" },
{ key: "boxart",    icon: "box" },
{ key: "boxback",   icon: "flip-horizontal" },
{ key: "cartridge", icon: "device-sd-card" },
{ key: "fanart",    icon: "wallpaper" },
{ key: "mix",       icon: "layout-collage" },
{ key: "map",       icon: "map" },
];
function getFields() {
  return FIELD_DEFS.map(f => ({
    ...f,
    label: t("fields." + f.key, null, f.key),
  }));
}
/** @deprecated use getFields() — kept as live view for older call sites */
let FIELDS = FIELD_DEFS.map(f => ({ ...f, label: f.key }));

/* ========== i18n (client) ========== */
/* Keys are dotted paths in locale JSON. applyI18n() writes [data-i18n*] attributes. */
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
  try { initCodeSelects(); renderRating(); renderReleaseDate(); updateUnsavedUi(); } catch (_) {}
  try { updateScrapeButton(); } catch (_) {}
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

/** Settings › General: the language applies as soon as it is picked. */
function wireLanguageControls() {
  const sel = document.getElementById("ui-lang");
  if (!sel) return;
  sel.value = currentLocale;
  if (sel.dataset.i18nWired) return;
  sel.dataset.i18nWired = "1";
  sel.addEventListener("change", async () => {
    sel.disabled = true;
    try {
      await setLocale(sel.value || currentLocale);
    } finally {
      sel.disabled = false;
    }
  });
}

let GENRES = {};
/**
 * UI logic — Gamelist Media Editor
 * games[]          : sorted by name; each item has .index = original XML position
 * currentIndex     : XML index (API routes)
 * currentListIndex : index inside games[] (list selection)
 * mediaFilter      : all | image | video | marquee | manual | boxart | boxback | cartridge | fanart | mix | any
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
  const ico = { error: "alert-circle", warning: "alert-triangle", info: "info-circle" }[type] || "circle-check";
  el.innerHTML = icon(ico) + `<span>${escapeHtml(String(msg || ""))}</span>`;
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
/**
 * Per-game API URL: appends ?path=<game path> so the server can check that
 * the XML index still designates this game (gamelist.xml may have changed
 * since the list was loaded) and re-target it if the game moved.
 */
function gameUrl(url) {
  const g = games.find(x => x.index === currentIndex);
  if (!g || !g.path) return url;
  return url + (url.includes("?") ? "&" : "?") + "path=" + encodeURIComponent(g.path);
}

let _gameListReloadQueued = false;
/** Reload the list once, after the current handler finished (selection kept by path). */
function queueGameListReload() {
  if (_gameListReloadQueued) return;
  _gameListReloadQueued = true;
  setTimeout(() => {
    _gameListReloadQueued = false;
    loadGames();
  }, 0);
}

/** Fetch JSON API; attaches X-Locale so server messages match the UI language. */
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
    if (err.code === "stale_game") queueGameListReload();
    throw err;
  }
  // The server re-targeted the request because the game moved in gamelist.xml:
  // our XML indexes are stale, refresh them.
  if (res.headers.get("X-Game-Reindexed") !== null) queueGameListReload();

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
const mainSel = document.getElementById("meta-genre-main");
mainSel.querySelectorAll("option[data-custom]").forEach(o => o.remove());
const raw = String(genreStr || "").trim();
const { main, sub } = parseGenre(raw);
// Only use the lists when they reproduce the stored value; otherwise keep the
// value as-is (e.g. "Platform" from ScreenScraper EN): saving must never drop it.
const rebuilt = main ? (sub ? `${main} / ${sub}` : main) : "";
const norm = v => v.toUpperCase().replace(/\s*\/\s*/g, " / ");
if (raw && norm(rebuilt) !== norm(raw)) {
  const opt = new Option(raw, raw);
  opt.dataset.custom = "1";
  mainSel.add(opt, 1);
  mainSel.value = raw;
  fillSubGenres("");
  return;
}
mainSel.value = main;
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

/** List indexes of the games shown under the current search + media filter. */
function getFilteredGames(searchQuery) {
  const q = (searchQuery !== undefined
    ? searchQuery
    : document.getElementById("search").value).toLowerCase().trim();
  const out = [];
  for (let i = 0; i < games.length; i++) {
    const g = games[i];
    if (q && !matchesSearch(g, q)) continue;
    if (mediaFilter !== "all" && !matchesMediaFilter(g)) continue;
    out.push(i);
  }
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

/** Filter menu: one option per media, each with the number of games missing it. */
function updateFilterCounts(q) {
  const query = (q || "").toLowerCase().trim();
  const keys = FIELD_DEFS.map(f => f.key);
  const counts = { all: 0, any: 0 };
  keys.forEach(k => { counts[k] = 0; });
  for (const g of games) {
    if (query && !matchesSearch(g, query)) continue;
    counts.all++;
    let missing = false;
    for (const k of keys) {
      if (!hasMedia(g, k)) { counts[k]++; missing = true; }
    }
    if (missing) counts.any++;
  }
  const sel = document.getElementById("media-filter");
  if (!sel) return;
  const labels = { all: t("sidebar.filter_all"), any: t("sidebar.filter_any") };
  keys.forEach(k => { labels[k] = t("sidebar.filter_" + k); });
  const order = ["all", "any", ...keys];
  if (sel.options.length !== order.length) {
    sel.innerHTML = order.map(k => `<option value="${k}"></option>`).join("");
  }
  order.forEach((k, i) => { sel.options[i].textContent = `${labels[k]} (${counts[k]})`; });
  sel.value = mediaFilter;
}

function updateSystemBadge(system) {
  currentSystem = system || null;
  updateScrapeButton();
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


/** True when a gamelist.xml is currently loaded in the session. */
window.__gmeLoaded = false;

/**
 * Toggle empty-state panels and disable destructive actions when no XML is loaded.
 * @param {boolean} loaded
 */
function setNoGamelistUi(loaded) {
  window.__gmeLoaded = !!loaded;
  const empty = document.getElementById("empty-state");
  const emptySelect = document.getElementById("empty-state-select");
  const emptyOpen = document.getElementById("empty-state-open");
  const editor = document.getElementById("editor");
  const del = document.getElementById("btn-delete-game");
  const reload = document.getElementById("btn-reload");
  if (editor) editor.hidden = true;
  if (del) del.disabled = true;
  if (reload) reload.disabled = !loaded;
  setScrapeEnabled(false);
  setGamelistActionsEnabled(!!loaded);
  if (!loaded) {
    if (empty) empty.hidden = false;
    if (emptySelect) emptySelect.hidden = true;
    if (emptyOpen) emptyOpen.hidden = false;
    const badge = document.getElementById("game-count");
    if (badge) {
      badge.setAttribute("data-i18n-params", JSON.stringify({ n: 0 }));
      badge.textContent = t("header.game_count", { n: 0 });
    }
    updateSystemBadge(null);
    window.__gmeXmlPath = null;
  } else {
    if (emptyOpen) emptyOpen.hidden = true;
    if (emptySelect) emptySelect.hidden = false;
  }
}

/** Load / refresh the game list; handles the no-gamelist (loaded:false) response. */
async function loadGames() {
  setStatus(t("status.loading"));
  const keepIndex = currentIndex;
  const keepGame = games.find(g => g.index === currentIndex);
  const keepPath = keepGame ? keepGame.path : "";
  const pendingKeys = keepPath ? changedFields() : [];
  const pendingValues = pendingKeys.length ? readEditor() : null;
  try {
    const data = await apiFetch("/api/games");
    // Back-compat: array or { games, system }
    if (Array.isArray(data)) {
      games = data;
      updateSystemBadge(null);
      window.__gmeLoaded = games.length >= 0;
    } else {
      const loaded = data.loaded !== false && !!(data.xml_path);
      window.__gmeLoaded = loaded;
      games = data.games || [];
      if (!loaded) {
        setNoGamelistUi(false);
        renderList();
        setStatus(t("status.no_gamelist"));
        return;
      }
      updateSystemBadge(data.system || null);
      if (data.xml_path) {
        window.__gmeXmlPath = data.xml_path;
        if (typeof pushRecentGamelist === "function") pushRecentGamelist(data.xml_path);
      }
      setNoGamelistUi(true);
      // restore empty-state-select visibility (editor still hidden until selection)
      const emptySelect = document.getElementById("empty-state-select");
      const emptyOpen = document.getElementById("empty-state-open");
      if (emptyOpen) emptyOpen.hidden = true;
      if (emptySelect) emptySelect.hidden = false;
      const empty = document.getElementById("empty-state");
      if (empty && currentIndex === null) empty.hidden = false;
    }
    if (keepIndex !== null) {
      // Same game = same <path> (its XML index may have changed on disk)
      const listIdx = keepPath
        ? games.findIndex(g => g.path === keepPath)
        : games.findIndex(g => g.index === keepIndex);
      if (listIdx >= 0) {
        currentListIndex = listIdx;
        renderList();
        selectGame(listIdx);
        if (pendingValues) {
          // Re-apply what the user was typing; the snapshot stays the fresh disk state
          pendingKeys.forEach(k => EDITOR_FIELDS[k].set(pendingValues[k]));
          updateUnsavedUi();
        }
      } else {
        currentIndex = null;
        currentListIndex = null;
        document.getElementById("editor").hidden = true;
        document.getElementById("empty-state").hidden = false;
        document.getElementById("btn-delete-game").disabled = true;
        setScrapeEnabled(false);
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
/* --- Game list (virtualized) ---------------------------------------------
 * Only the rows in view exist in the page (about 40), whatever the size of the
 * gamelist: 30 000 MAME games scroll, filter and select instantly.
 * `viewIndices` holds the list indexes shown under the search + filter.
 */
const ROW_H = 56;            // px, keep in sync with .game-item height in style.css
const ROW_OVERSCAN = 8;
let viewIndices = [];
let winFirst = -1, winLast = -1;

function listEls() {
  const list = document.getElementById("game-list");
  if (!list.querySelector(".vlist-spacer")) {
    list.innerHTML =
      '<div class="vlist-spacer"><div class="vlist-window"></div></div>' +
      '<div class="filter-empty" hidden></div>';
  }
  return {
    list,
    spacer: list.querySelector(".vlist-spacer"),
    win: list.querySelector(".vlist-window"),
    empty: list.querySelector(".filter-empty"),
  };
}

/** Recompute which games are shown (search, filter, data change) and redraw. */
function renderList(filter) {
  if (games !== _suggestGames) { _suggestGames = games; invalidateSuggestions(); }
  const q = (filter !== undefined ? filter : document.getElementById("search").value).toLowerCase().trim();
  viewIndices = getFilteredGames(q);
  const { spacer, empty } = listEls();
  spacer.style.height = viewIndices.length * ROW_H + "px";
  empty.hidden = viewIndices.length > 0;
  if (!viewIndices.length) {
    empty.innerHTML = games.length ? t("sidebar.empty_no_match") : t("sidebar.empty_no_games");
  }
  renderListWindow(true);
  updateGameCount(viewIndices.length);
  updateFilterCounts(q);
}

/** Thumbnail source for the list: screenshot, else box, else mix, else logo. */
function thumbPath(g) {
  return g.image || g.boxart || g.mix || g.marquee || "";
}

function gameRowHtml(g, listIndex, pos) {
  const active = listIndex === currentListIndex;
  const fields = getFields();
  const missing = fields.filter(f => !hasMedia(g, f.key));
  const present = fields.length - missing.length;
  const title = missing.length
    ? t("sidebar.media_missing", { list: missing.map(f => f.label).join(", ") })
    : t("sidebar.media_complete");
  const tp = thumbPath(g);
  const thumb = tp
    ? `<img src="/api/thumb?path=${encodeURIComponent(tp)}" alt="" loading="lazy" decoding="async" />`
    : icon("device-gamepad-2");
  const countCls = present === fields.length ? " is-complete" : present === 0 ? " is-empty" : "";
  return `<div class="game-item${active ? " active" : ""}" role="option" id="gi-${listIndex}"` +
    ` data-list-index="${listIndex}" aria-selected="${active}" aria-setsize="${viewIndices.length}" aria-posinset="${pos + 1}">` +
    `<span class="gi-thumb">${thumb}</span>` +
    `<span class="gi-text"><span class="name">${escapeHtml(g.name)}</span><span class="path">${escapeHtml(g.path)}</span></span>` +
    `<span class="gi-count${countCls}" title="${escapeHtml(title)}">${present}/${fields.length}</span>` +
    `</div>`;
}

/** Draw the rows in view (cheap: about 40 rows). `force` redraws even if the range is unchanged. */
function renderListWindow(force) {
  const { list, win } = listEls();
  const height = list.clientHeight || 600;
  const first = Math.max(0, Math.floor(list.scrollTop / ROW_H) - ROW_OVERSCAN);
  const last = Math.min(viewIndices.length, Math.ceil((list.scrollTop + height) / ROW_H) + ROW_OVERSCAN);
  if (!force && first === winFirst && last === winLast) return;
  winFirst = first; winLast = last;
  let html = "";
  for (let pos = first; pos < last; pos++) {
    const i = viewIndices[pos];
    html += gameRowHtml(games[i], i, pos);
  }
  win.style.transform = `translateY(${first * ROW_H}px)`;
  win.innerHTML = html;
  const activeRow = currentListIndex !== null ? document.getElementById("gi-" + currentListIndex) : null;
  if (activeRow) list.setAttribute("aria-activedescendant", activeRow.id);
  else list.removeAttribute("aria-activedescendant");
}

function getVisibleListIndices() {
  return viewIndices;
}

/** Scroll the list just enough to show the selected game, then redraw. */
function scrollActiveIntoView() {
  const { list } = listEls();
  const pos = viewIndices.indexOf(currentListIndex);
  if (pos >= 0) {
    const top = pos * ROW_H;
    const height = list.clientHeight;
    if (top < list.scrollTop) list.scrollTop = top;
    else if (top + ROW_H > list.scrollTop + height) list.scrollTop = top + ROW_H - height;
  }
  renderListWindow(true);
}

let _listScrollFrame = 0;
function onListScroll() {
  if (_listScrollFrame) return;
  _listScrollFrame = requestAnimationFrame(() => { _listScrollFrame = 0; renderListWindow(false); });
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
  requestSelectGame(visible[nextPos]);
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

/* --- Metadata widgets -----------------------------------------------------
 * Language and region: named lists in the interface language (the browser
 * knows every name: Intl.DisplayNames), the stored code stays as it is.
 * A value outside the list (e.g. "en,fr") is kept as its own option.
 */
const LANG_CODES = ["en", "fr", "de", "es", "it", "pt", "nl", "sv", "no", "da", "fi", "pl",
  "cs", "hu", "el", "tr", "ru", "ja", "ko", "zh", "ar"];
const REGION_CODES = ["wor", "eu", "us", "jp", "fr", "de", "es", "it", "uk", "nl", "se", "dk",
  "no", "fi", "pt", "br", "au", "ca", "kr", "cn", "tw", "asi", "ru", "pl"];
// ScreenScraper / EmulationStation region codes that are not ISO country codes
const REGION_ZONES = { wor: "editor.region_world", eu: "editor.region_europe", asi: "editor.region_asia" };
const REGION_TO_ISO = { uk: "GB" };

function displayName(type, code) {
  try {
    return new Intl.DisplayNames([currentLocale || "fr", "en"], { type }).of(code) || code;
  } catch (_) {
    return code;
  }
}
function langLabel(value) {
  return value.split(/\s*,\s*/).filter(Boolean)
    .map(c => (c.length >= 2 && c.length <= 3 ? displayName("language", c) : c)).join(", ");
}
function regionLabel(value) {
  return value.split(/\s*,\s*/).filter(Boolean).map(c => {
    const code = c.toLowerCase();
    if (REGION_ZONES[code]) return t(REGION_ZONES[code]);
    const iso = REGION_TO_ISO[code] || c.toUpperCase();
    return /^[A-Z]{2}$/.test(iso) ? displayName("region", iso) : c;
  }).join(", ");
}

/** Fill a code <select>: "none" first, then the known codes sorted by name. */
function fillCodeSelect(sel, codes, labelFor, pinned) {
  const current = sel.value;
  const items = codes.map(c => ({ c, label: labelFor(c) }));
  const head = items.filter(x => pinned.includes(x.c)).sort((a, b) => pinned.indexOf(a.c) - pinned.indexOf(b.c));
  const rest = items.filter(x => !pinned.includes(x.c))
    .sort((a, b) => a.label.localeCompare(b.label, currentLocale || "fr"));
  sel.innerHTML = `<option value="" aria-label="${escapeHtml(t("editor.none"))}">—</option>` +
    [...head, ...rest].map(x => `<option value="${x.c}">${escapeHtml(x.label)}</option>`).join("");
  if (current) setSelectValue(sel, current, labelFor);
}
function initCodeSelects() {
  fillCodeSelect(document.getElementById("meta-lang"), LANG_CODES, langLabel, ["en", "fr"]);
  fillCodeSelect(document.getElementById("meta-region"), REGION_CODES, regionLabel, ["wor", "eu", "us", "jp"]);
}

/** Select `value`, adding it as an option when it is not in the list. */
function setSelectValue(sel, value, labelFor) {
  sel.querySelectorAll("option[data-custom]").forEach(o => o.remove());
  value = value || "";
  if (value && ![...sel.options].some(o => o.value === value)) {
    const opt = new Option(labelFor ? labelFor(value) : value, value);
    opt.dataset.custom = "1";
    sel.add(opt, 1);
  }
  sel.value = value;
}

/* Rating: stored 0–1 ("0.85"), shown as 5 stars; set in half stars. */
function renderRating() {
  const raw = document.getElementById("meta-rating").value;
  const v = raw === "" ? null : Math.max(0, Math.min(1, parseFloat(raw) || 0));
  const stars = v === null ? 0 : v * 5;
  const el = document.getElementById("rating-stars");
  document.getElementById("rating-fill").style.width = (stars / 5 * 100) + "%";
  el.setAttribute("aria-valuenow", String(Math.round(stars * 10) / 10));
  el.setAttribute("aria-valuetext", v === null ? t("editor.none") : t("editor.rating_value", { n: fmtStars(stars) }));
  document.getElementById("rating-value").textContent = v === null ? "" : fmtStars(stars);
  document.getElementById("rating-clear").hidden = v === null;
}
function fmtStars(n) {
  return (Math.round(n * 10) / 10).toLocaleString(currentLocale || "fr");
}
function setRatingStars(stars) {
  const input = document.getElementById("meta-rating");
  input.value = stars === null ? "" : String(Math.round(stars * 2) / 2 / 5);
  renderRating();
  updateUnsavedUi();
}
(() => {
  const el = document.getElementById("rating-stars");
  const starsAt = e => {
    const r = el.getBoundingClientRect();
    return Math.max(0.5, Math.ceil(((e.clientX - r.left) / r.width) * 10) / 2);
  };
  el.addEventListener("click", e => setRatingStars(starsAt(e)));
  el.addEventListener("keydown", e => {
    const raw = document.getElementById("meta-rating").value;
    const cur = raw === "" ? 0 : Math.round(parseFloat(raw) * 10) / 2;
    const step = { ArrowRight: 0.5, ArrowUp: 0.5, ArrowLeft: -0.5, ArrowDown: -0.5 }[e.key];
    if (step !== undefined) {
      e.preventDefault();
      e.stopPropagation();          // arrows here change the rating, not the game
      setRatingStars(Math.max(0, Math.min(5, cur + step)));
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      e.stopPropagation();
      setRatingStars(e.key === "Home" ? 0 : 5);
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      setRatingStars(null);
    }
  });
  document.getElementById("rating-clear").addEventListener("click", () => setRatingStars(null));
})();

/* Release date: stored "YYYYMMDDTHHMMSS", edited with the browser's date picker.
 * A stored value the picker cannot show is kept untouched and displayed as text. */
function renderReleaseDate() {
  const raw = document.getElementById("meta-releasedate").value;
  const input = document.getElementById("meta-releasedate-input");
  const hint = document.getElementById("releasedate-raw");
  const m = /^(\d{4})(\d{2})(\d{2})T\d{6}$/.exec(raw);
  input.value = m ? `${m[1]}-${m[2]}-${m[3]}` : "";
  hint.hidden = !raw || !!m;
  hint.textContent = raw && !m ? t("editor.date_raw", { raw }) : "";
}
document.getElementById("meta-releasedate-input").addEventListener("change", e => {
  const v = e.target.value;                       // "1997-09-15" or ""
  document.getElementById("meta-releasedate").value = v ? v.replace(/-/g, "") + "T000000" : "";
  renderReleaseDate();
  updateUnsavedUi();
});

/* Suggestions: values already used in this gamelist, most frequent first. */
const SUGGEST_FIELDS = ["developer", "publisher", "family", "players", "arcadesystemname"];
const _suggestBuilt = new Set();
let _suggestGames = null;
function buildSuggestions(field) {
  if (_suggestBuilt.has(field)) return;
  const counts = new Map();
  for (const g of games) {
    const v = g[field];
    if (v) counts.set(v, (counts.get(v) || 0) + 1);
  }
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 300);
  document.getElementById("dl-" + field).innerHTML = top.map(([v]) => `<option value="${escapeHtml(v)}"></option>`).join("");
  _suggestBuilt.add(field);
}
function invalidateSuggestions(fields) {
  (fields || SUGGEST_FIELDS).forEach(f => _suggestBuilt.delete(f));
}
SUGGEST_FIELDS.forEach(f => document.getElementById("meta-" + f).addEventListener("focus", () => buildSuggestions(f)));

/* --- Unsaved changes ------------------------------------------------------
 * The editor keeps a snapshot of the values shown when a game is selected.
 * Saving sends only the fields that differ from it (an untouched field can
 * never be rewritten), and leaving the game with changes asks first.
 */
const EDITOR_FIELDS = (() => {
  const val = id => ({
    id,
    get: () => document.getElementById(id).value,
    set: v => { document.getElementById(id).value = v; },
  });
  // <select> whose stored value may be outside the list (kept as its own option)
  const choice = (id, labelFor) => ({
    id,
    get: () => document.getElementById(id).value,
    set: v => setSelectValue(document.getElementById(id), v, labelFor),
  });
  const flag = id => ({
    id,
    get: () => (document.getElementById(id).checked ? "true" : ""),
    set: v => { document.getElementById(id).checked = v === "true"; },
  });
  return {
    name: { ...val("game-name-input"), label: "scrape.field_name" },
    desc: { ...val("desc-textarea"), label: "scrape.field_desc" },
    genre: { id: "meta-genre-main", get: () => buildGenreValue(), set: v => setGenreUI(v), label: "scrape.field_genre" },
    rating: { ...val("meta-rating"), set: v => { document.getElementById("meta-rating").value = v; renderRating(); }, label: "scrape.field_rating" },
    releasedate: { ...val("meta-releasedate"), set: v => { document.getElementById("meta-releasedate").value = v; renderReleaseDate(); }, label: "scrape.field_releasedate" },
    developer: { ...val("meta-developer"), label: "scrape.field_developer" },
    publisher: { ...val("meta-publisher"), label: "scrape.field_publisher" },
    family: { ...val("meta-family"), label: "scrape.field_family" },
    players: { ...val("meta-players"), label: "scrape.field_players" },
    lang: { ...choice("meta-lang", langLabel), label: "scrape.field_lang" },
    region: { ...choice("meta-region", regionLabel), label: "editor.region" },
    arcadesystemname: { ...val("meta-arcadesystemname"), label: "editor.arcadesystemname" },
    favorite: { ...flag("meta-favorite"), label: "editor.favorite" },
    hidden: { ...flag("meta-hidden"), label: "editor.hidden" },
    kidgame: { ...flag("meta-kidgame"), label: "editor.kidgame" },
  };
})();
const META_KEYS = Object.keys(EDITOR_FIELDS).filter(k => k !== "name" && k !== "desc");

let editorSnapshot = null;   // values as loaded / last saved, for the current game

function readEditor() {
  const out = {};
  for (const [k, f] of Object.entries(EDITOR_FIELDS)) out[k] = f.get();
  return out;
}

function snapshotEditor() {
  editorSnapshot = currentIndex === null ? null : readEditor();
  updateUnsavedUi();
}

/** Keys whose value differs from the snapshot (optionally among `keys`). */
function changedFields(keys) {
  if (!editorSnapshot || currentIndex === null) return [];
  const now = readEditor();
  return (keys || Object.keys(now)).filter(k => now[k] !== editorSnapshot[k]);
}

function markSaved(keys) {
  if (!editorSnapshot) return;
  const now = readEditor();
  keys.forEach(k => { editorSnapshot[k] = now[k]; });
  updateUnsavedUi();
}

function fieldLabels(keys) {
  return keys.map(k => t(EDITOR_FIELDS[k].label)).join(", ");
}

/** Element framing a field, marked while the field has an unsaved change. */
function fieldWrap(key) {
  const el = document.getElementById(EDITOR_FIELDS[key].id);
  return el && el.closest(".meta-field, .flag-toggle, .title-row, .insp-block");
}

function updateUnsavedUi() {
  const changed = changedFields();
  for (const key of Object.keys(EDITOR_FIELDS)) {
    const wrap = fieldWrap(key);
    if (wrap) wrap.classList.toggle("is-changed", changed.includes(key));
  }
  const bar = document.getElementById("save-bar");
  if (!bar) return;
  bar.hidden = !changed.length;
  if (changed.length) {
    document.getElementById("save-bar-text").textContent = t(
      changed.length === 1 ? "editor.unsaved_one" : "editor.unsaved_many",
      { n: changed.length, fields: fieldLabels(changed) });
  }
}

/** Save every changed field of the game in one request (one write of gamelist.xml). */
let _saving = false;
async function saveAllChanges() {
  if (currentIndex === null) return true;
  const keys = changedFields();
  if (!keys.length) return true;
  if (_saving) return false;
  const now = readEditor();
  if (keys.includes("name") && !now.name.trim()) {
    toast(t("toast.name_empty"), "error");
    document.getElementById("game-name-input").focus();
    return false;
  }
  const payload = {};
  keys.forEach(k => { payload[k] = k === "name" ? now.name.trim() : now[k]; });
  _saving = true;
  document.getElementById("btn-save").disabled = true;
  setStatus(t("editor.saving"));
  try {
    const data = await apiFetch(gameUrl(`/api/game/${currentIndex}`), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const g = games.find(x => x.index === currentIndex);
    if (g && data.updated) Object.assign(g, data.updated);
    if (keys.includes("name")) document.getElementById("game-name-input").value = payload.name;
    markSaved(keys);
    if (keys.includes("name")) {
      games.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
      currentListIndex = games.findIndex(x => x.index === currentIndex);
      renderList(document.getElementById("search").value);
      scrollActiveIntoView();
    }
    invalidateSuggestions(keys);
    toast(t("editor.saved"));
    setStatus(t("status.saved"));
    return true;
  } catch (e) {
    handleError(e);
    return false;
  } finally {
    _saving = false;
    document.getElementById("btn-save").disabled = false;
  }
}

/** Put every changed field back to its saved value. */
function revertChanges() {
  if (!editorSnapshot) return;
  for (const k of changedFields()) EDITOR_FIELDS[k].set(editorSnapshot[k]);
  updateUnsavedUi();
}

/**
 * Before leaving the current game (another game, reload, other gamelist,
 * scrape, quit): if something is unsaved, ask Save / Don't save / Cancel.
 * Resolves true when it is OK to go on.
 */
async function confirmLeaveEditor() {
  const changed = changedFields();
  if (!changed.length) return true;
  const g = games.find(x => x.index === currentIndex);
  const choice = await askConfirm({
    title: t("confirm.unsaved_title"),
    bodyHtml: escapeHtml(t("confirm.unsaved_body", {
      name: g ? g.name : t("confirm.this_game"),
      fields: fieldLabels(changed),
    })),
    showBackup: false,
    okLabel: t("confirm.save"),
    okClass: "btn-accent",
    extraLabel: t("confirm.discard"),
  });
  if (choice.extra) {
    snapshotEditor();          // drop the changes
    return true;
  }
  if (!choice.confirmed) return false;
  return saveAllChanges();
}

/** User-initiated selection (click, keys): asks before losing changes. */
async function requestSelectGame(listIndex) {
  if (listIndex === currentListIndex && currentIndex !== null) return;
  if (!(await confirmLeaveEditor())) return;
  selectGame(listIndex);
}

function selectGame(listIndex) {
const g = games[listIndex];
if (!g) return;
currentIndex = g.index;
currentListIndex = listIndex;
document.getElementById("empty-state").hidden = true;
document.getElementById("editor").hidden = false;
document.getElementById("btn-delete-game").disabled = false;
setScrapeEnabled(!ssBusy);
document.getElementById("game-path").textContent = g.path;
for (const [k, f] of Object.entries(EDITOR_FIELDS)) {
  const v = g[k] || "";
  f.set(["favorite", "hidden", "kidgame"].includes(k) ? (v.toLowerCase() === "true" ? "true" : "") : v);
}
renderZones(g);
scrollActiveIntoView();
snapshotEditor();
if (!g._detail) loadGameDetail(g);
}

/**
 * The game list has no descriptions (they are most of a large gamelist):
 * fetch the opened game's description. The field stays read-only until it
 * arrives, so nothing typed can be overwritten.
 */
let _detailToken = 0;
async function loadGameDetail(g) {
  const ta = document.getElementById("desc-textarea");
  const token = ++_detailToken;
  ta.readOnly = true;
  ta.classList.add("is-loading");
  let data;
  try {
    data = await apiFetch(`/api/game/${g.index}?path=${encodeURIComponent(g.path)}`);
  } catch (e) {
    if (token === _detailToken) handleError(e);
    return;
  }
  g.desc = data.desc || "";
  g._detail = true;
  if (data.index !== g.index) queueGameListReload();     // gamelist.xml changed meanwhile
  if (token !== _detailToken || currentIndex !== g.index) return;
  ta.value = g.desc;
  ta.readOnly = false;
  ta.classList.remove("is-loading");
  if (editorSnapshot) editorSnapshot.desc = ta.value;
  updateUnsavedUi();
}
/* --- Media gallery ----------------------------------------------------------
 * Present media are shown large, each in its own shape (box art upright, logo
 * wide…) in a masonry of columns; missing media are grouped below as small drop targets. Dropping a
 * file or a web image on a tile replaces it; clicking a missing one (or the
 * upload button of a tile) opens a file picker.
 */
const MEDIA_SHAPE = {
  image: "4 / 3", video: "4 / 3", marquee: "3 / 1", manual: "3 / 4", boxart: "3 / 4",
  boxback: "3 / 4", cartridge: "1 / 1", fanart: "16 / 9", mix: "4 / 3", map: "1 / 1",
};
const MEDIA_ACCEPT = { video: "video/*", manual: "application/pdf,.pdf" };

function fieldLabel(key) {
  const f = getFields().find(x => x.key === key);
  return f ? f.label : key;
}

function baseName(path) {
  return String(path || "").split(/[\\/]/).pop();
}

function mediaTileHtml(g, f) {
  const url = mediaUrl(g[f.key]);
  let media;
  if (f.key === "video") {
    media = `<video src="${url}" controls muted preload="metadata"></video>`;
  } else if (f.key === "manual") {
    media = `<a class="tile-doc" href="${url}" target="_blank" rel="noopener">${icon("file-text")}<span>${t("zone.open")}</span></a>`;
  } else {
    media = `<img src="${url}" alt="${escapeHtml(f.label)}" title="${t("zone.zoom_title")}" loading="lazy" decoding="async" />`;
  }
  return `<figure class="media-tile" data-field="${f.key}" style="--ar: ${MEDIA_SHAPE[f.key] || "4 / 3"}">
    <figcaption class="tile-head">
      <span class="tile-title">${icon(f.icon)}<span>${escapeHtml(f.label)}</span></span>
      <span class="tile-actions">
        <button type="button" class="btn btn-icon btn-sm" data-action="pick" title="${escapeHtml(t("editor.replace"))}" aria-label="${escapeHtml(t("editor.replace"))}">${icon("upload")}</button>
        <button type="button" class="btn btn-icon btn-sm tile-delete" data-action="clear" title="${t("zone.clear_title")}" aria-label="${t("zone.clear_title")}">${icon("trash")}</button>
      </span>
    </figcaption>
    <div class="tile-media">${media}</div>
    <div class="tile-foot"><span class="tile-dims"></span><span class="tile-file" title="${escapeHtml(g[f.key])}">${escapeHtml(baseName(g[f.key]))}</span></div>
  </figure>`;
}

function missingChipHtml(f) {
  const title = t("editor.choose_file", { field: f.label });
  return `<button type="button" class="missing-chip" data-field="${f.key}" title="${escapeHtml(title)}">` +
    `${icon(f.icon)}<span>${escapeHtml(f.label)}</span>${icon("upload", "chip-add")}</button>`;
}

function renderZones(g) {
  const fields = getFields();
  const present = fields.filter(f => hasMedia(g, f.key));
  const missing = fields.filter(f => !hasMedia(g, f.key));
  const grid = document.getElementById("media-grid");
  grid.innerHTML = present.map(f => mediaTileHtml(g, f)).join("");
  grid.hidden = !present.length;
  document.getElementById("missing-chips").innerHTML = missing.map(missingChipHtml).join("");
  document.getElementById("media-missing").hidden = !missing.length;

  grid.querySelectorAll(".media-tile").forEach(tile => {
    const img = tile.querySelector("img");
    const dims = tile.querySelector(".tile-dims");
    if (img) {
      img.addEventListener("load", () => { dims.textContent = `${img.naturalWidth} × ${img.naturalHeight}`; });
      img.addEventListener("error", () => {
        tile.querySelector(".tile-media").innerHTML =
          `<div class="tile-broken">${icon("alert-triangle")}<span>${t("zone.preview_unavailable")}</span></div>`;
      });
      img.addEventListener("click", () => openLightbox(img.src, tile.querySelector(".tile-title").textContent.trim()));
    }
    const video = tile.querySelector("video");
    if (video) {
      video.addEventListener("loadedmetadata", () => {
        const s = Math.round(video.duration || 0);
        dims.textContent = `${video.videoWidth} × ${video.videoHeight}` + (s ? ` · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "");
      });
    }
  });
}

/** Drop targets: present tiles (replace) and missing chips (add). */
function mediaDropTarget(e) {
  return e.target.closest && e.target.closest(".media-tile, .missing-chip");
}
(() => {
  const stage = document.querySelector(".stage");
  stage.addEventListener("dragover", e => {
    const target = mediaDropTarget(e);
    if (!target) return;
    e.preventDefault();
    target.classList.add("drag-over");
  });
  stage.addEventListener("dragleave", e => {
    const target = mediaDropTarget(e);
    if (target && !target.contains(e.relatedTarget)) target.classList.remove("drag-over");
  });
  stage.addEventListener("drop", e => {
    const target = mediaDropTarget(e);
    if (!target) return;
    target.classList.remove("drag-over");
    onDrop(e, target.dataset.field);
  });
  stage.addEventListener("click", e => {
    const actionBtn = e.target.closest("[data-action]");
    const tile = e.target.closest(".media-tile, .missing-chip");
    if (!tile) return;
    const field = tile.dataset.field;
    if (actionBtn && actionBtn.dataset.action === "clear") clearField(field);
    else if (tile.classList.contains("missing-chip") || (actionBtn && actionBtn.dataset.action === "pick")) pickMediaFile(field);
  });
  document.getElementById("media-file-input").addEventListener("change", e => {
    const file = e.target.files && e.target.files[0];
    const field = e.target.dataset.field;
    e.target.value = "";
    if (file && field) uploadMedia(field, { file });
  });
})();

function pickMediaFile(field) {
  if (currentIndex === null) return;
  const input = document.getElementById("media-file-input");
  input.dataset.field = field;
  input.accept = MEDIA_ACCEPT[field] || "image/*";
  input.click();
}

async function onDrop(e, field) {
  e.preventDefault();
  e.stopPropagation();
  if (currentIndex === null || !field) return;
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
    const data = await apiFetch(gameUrl(`/api/upload/${currentIndex}/${field}`), { method: "POST", body: form });
    const g = games.find(x => x.index === currentIndex);
    if (g) { g[field] = data.path; renderZones(g); }
    renderList(document.getElementById("search").value);
    toast(t("toast.upload_ok", { field: fieldLabel(field), filename: data.filename }));
    setStatus(t("status.saved"));
  } catch (e) {
    handleError(e);
  }
}

async function clearField(field) {
  // Detach media tag in XML only (file kept on disk)
  const choice = await askConfirm({
    title: t("confirm.clear_field_title", { field: fieldLabel(field) }),
    bodyHtml: t("confirm.clear_field_body"),
    showBackup: false,
    okLabel: t("zone.clear_title"),
  });
  if (!choice.confirmed) return;
  try {
    const data = await apiFetch(gameUrl(`/api/clear/${currentIndex}/${field}`), { method: "POST" });
    const g = games.find(x => x.index === currentIndex);
    if (g) { g[field] = ""; renderZones(g); }
    renderList(document.getElementById("search").value);
    toast(t("toast.field_cleared"));
  } catch (e) {
    handleError(e);
  }
}
document.getElementById("btn-save").addEventListener("click", () => {
  if (!changedFields().length) { toast(t("toast.nothing_to_save")); return; }
  saveAllChanges();
});
document.getElementById("btn-revert").addEventListener("click", revertChanges);
document.getElementById("game-name-input").addEventListener("keydown", e => {
  if (e.key === "Enter") { e.preventDefault(); saveAllChanges(); }
});
// Any edit in the form refreshes the unsaved indicators
["input", "change"].forEach(ev => document.getElementById("editor").addEventListener(ev, () => updateUnsavedUi()));
document.getElementById("search").addEventListener("input", e => {
  const value = e.target.value;
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => renderList(value), SEARCH_DEBOUNCE_MS);
});
document.getElementById("meta-genre-main").addEventListener("change", e => fillSubGenres(e.target.value));

document.getElementById("media-filter").addEventListener("change", e => {
  mediaFilter = e.target.value || "all";
  listEls().list.scrollTop = 0;
  renderList();
});
(() => {
  const list = document.getElementById("game-list");
  list.addEventListener("click", e => {
    const row = e.target.closest(".game-item");
    if (row) requestSelectGame(parseInt(row.dataset.listIndex, 10));
  });
  list.addEventListener("scroll", onListScroll, { passive: true });
  // Broken or missing thumbnail: show the placeholder icon instead
  list.addEventListener("error", e => {
    if (e.target.tagName === "IMG") e.target.outerHTML = icon("device-gamepad-2");
  }, true);
  if (window.ResizeObserver) new ResizeObserver(() => renderListWindow(false)).observe(list);
})();

function openLightbox(src, label) {
  const overlay = document.getElementById("media-lightbox");
  const img = document.getElementById("lightbox-img");
  if (!overlay || !img || !src) return;
  img.src = src;
  img.alt = label || "";
  overlay.classList.add("open");
}
function closeLightbox() {
  const overlay = document.getElementById("media-lightbox");
  const img = document.getElementById("lightbox-img");
  if (overlay) overlay.classList.remove("open");
  if (img) img.removeAttribute("src");
}
document.getElementById("lightbox-close")?.addEventListener("click", e => {
  e.stopPropagation();
  closeLightbox();
});
document.getElementById("media-lightbox")?.addEventListener("click", e => {
  if (e.target.id === "media-lightbox" || e.target.id === "lightbox-img") closeLightbox();
});

document.addEventListener("keydown", e => {
  const lightbox = document.getElementById("media-lightbox");
  if (lightbox && lightbox.classList.contains("open")) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeLightbox();
    }
    return;
  }
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
  const openGl = document.getElementById("open-gamelist-modal");
  if (openGl && openGl.classList.contains("open")) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeGamelistModal();
    }
    return;
  }
  const settings = document.getElementById("settings-modal");
  if (settings && settings.classList.contains("open")) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeSettings();
    }
    return;
  }
  const about = document.getElementById("about-modal");
  if (about && about.classList.contains("open")) return;
  if (openMenuId) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeMenu(openMenuId, true);
    }
    return;
  }

  const typing = isTypingTarget(e.target);
  const ctrl = e.ctrlKey || e.metaKey;

  // Ctrl+S : save according to focus (or everything if editor open)
  if (ctrl && e.key.toLowerCase() === "s") {
    e.preventDefault();
    if (currentIndex === null) return;
    if (!changedFields().length) { toast(t("toast.nothing_to_save")); return; }
    saveAllChanges();
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

  // Letters (not while typing, no modifier): J/K next/previous, N next
  // incomplete, S scrape, ? shortcuts. Same list in Settings › Shortcuts.
  if (!typing && !ctrl && !e.altKey) {
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (key === "j" || key === "k") {
      e.preventDefault();
      navigateGame(key === "j" ? 1 : -1);
      return;
    }
    if (key === "n" && !e.repeat) {
      e.preventDefault();
      nextIncomplete();
      return;
    }
    if (key === "s" && !e.repeat) {
      const btn = document.getElementById("btn-scrape");
      if (currentIndex === null || btn.disabled) return;
      e.preventDefault();
      btn.click();
      return;
    }
    if (key === "?") {
      e.preventDefault();
      openSettings("keys");
      return;
    }
  }

  // Home / End → first / last visible game (not while typing)
  if ((e.key === "Home" || e.key === "End") && !typing) {
    const visible = getVisibleListIndices();
    if (!visible.length) return;
    e.preventDefault();
    requestSelectGame(e.key === "Home" ? visible[0] : visible[visible.length - 1]);
    return;
  }

  // PageUp / PageDown → jump ~10 games
  if ((e.key === "PageDown" || e.key === "PageUp") && !typing) {
    e.preventDefault();
    navigateGame(e.key === "PageDown" ? 10 : -10);
    return;
  }
});
function askConfirm({ title, bodyHtml, showBackup = true, okLabel, cancelLabel, okClass = "btn-danger", extraLabel }) {
  return new Promise(resolve => {
    const overlay = document.getElementById("confirm-modal");
    document.getElementById("confirm-title").textContent = title;
    document.getElementById("confirm-body").innerHTML = bodyHtml;
    const okBtn = document.getElementById("confirm-ok");
    const cancelBtn = document.getElementById("confirm-cancel");
    if (okBtn) {
      okBtn.textContent = okLabel || t("confirm.ok");
      okBtn.classList.remove("btn-danger", "btn-accent");
      okBtn.classList.add(okClass);
    }
    const extraBtn = document.getElementById("confirm-extra");
    extraBtn.hidden = !extraLabel;
    extraBtn.textContent = extraLabel || "";
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
      extraBtn.removeEventListener("click", onExtra);
      overlay.removeEventListener("click", onOverlay);
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onOk = () => cleanup({
      confirmed: true,
      backup: document.getElementById("confirm-backup").checked,
    });
    const onCancel = () => cleanup({ confirmed: false, backup: false });
    const onExtra = () => cleanup({ confirmed: false, backup: false, extra: true });
    const onOverlay = (e) => { if (e.target === overlay) onCancel(); };
    const onKey = (e) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onOk();
    };
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    extraBtn.addEventListener("click", onExtra);
    overlay.addEventListener("click", onOverlay);
    document.addEventListener("keydown", onKey);
    okBtn.focus();
  });
}

/* --- Menus (scrape source, game actions, gamelist actions) ---------------
 * A button with aria-haspopup="menu" opens the menu below it. Arrows move
 * between items, Escape closes and gives the focus back, a click outside or
 * on an item closes it.
 */
const MENUS = {};
let openMenuId = null;

function menuItems(menu) {
  return [...menu.querySelectorAll('[role="menuitem"], [role="menuitemradio"]')]
    .filter(el => !el.hidden && !el.disabled);
}
function openMenu(id) {
  const m = MENUS[id];
  if (!m) return;
  if (openMenuId && openMenuId !== id) closeMenu(openMenuId, false);
  if (m.onOpen) m.onOpen();
  m.menu.hidden = false;
  m.button.setAttribute("aria-expanded", "true");
  openMenuId = id;
  const first = m.menu.querySelector('[aria-checked="true"]:not(:disabled)') || menuItems(m.menu)[0];
  if (first) first.focus();
  document.addEventListener("pointerdown", onMenuOutside, true);
}
function closeMenu(id, focusButton) {
  const m = MENUS[id || openMenuId];
  if (!m || m.menu.hidden) return;
  m.menu.hidden = true;
  m.button.setAttribute("aria-expanded", "false");
  if (openMenuId === m.id) openMenuId = null;
  document.removeEventListener("pointerdown", onMenuOutside, true);
  if (focusButton) m.button.focus();
}
function onMenuOutside(e) {
  const m = MENUS[openMenuId];
  if (m && !m.menu.contains(e.target) && !m.button.contains(e.target)) closeMenu(m.id, false);
}
function setupMenu(id, buttonId, onOpen) {
  const button = document.getElementById(buttonId);
  const menu = document.getElementById(id);
  MENUS[id] = { id, button, menu, onOpen };
  button.addEventListener("click", () => (menu.hidden ? openMenu(id) : closeMenu(id, true)));
  button.addEventListener("keydown", e => {
    if (e.key === "ArrowDown" && menu.hidden) {
      e.preventDefault();
      e.stopPropagation();
      openMenu(id);
    }
  });
  menu.addEventListener("keydown", e => {
    e.stopPropagation();                       // arrows move in the menu, not in the game list
    const items = menuItems(menu);
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      items[(i + step + items.length) % items.length].focus();
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      items[e.key === "Home" ? 0 : items.length - 1].focus();
    } else if (e.key === "Escape") {
      e.preventDefault();
      closeMenu(id, true);
    } else if (e.key === "Tab") {
      closeMenu(id, false);
    }
  });
  // Capture phase: the menu is closed before the item's action opens a dialog
  menu.addEventListener("click", e => {
    const item = e.target.closest('[role="menuitem"], [role="menuitemradio"]');
    if (item && !item.disabled) closeMenu(id, true);
  }, true);
}

/* --- Settings: General, ScreenScraper, scrape sources, shortcuts --------- */
const SETTINGS_PANES = ["general", "ss", "sources", "keys"];

function openSettings(pane) {
  closeMenu(null, false);
  wireLanguageControls();
  loadSsConfig();
  renderScrapeSources();
  document.getElementById("settings-modal").classList.add("open");
  showSettingsPane(pane || "general", true);
}
function closeSettings() {
  const modal = document.getElementById("settings-modal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  document.getElementById("btn-settings").focus();
}
function showSettingsPane(pane, focusTab) {
  if (!SETTINGS_PANES.includes(pane)) pane = "general";
  SETTINGS_PANES.forEach(p => {
    const tab = document.getElementById("tab-" + p);
    const on = p === pane;
    tab.setAttribute("aria-selected", on ? "true" : "false");
    tab.tabIndex = on ? 0 : -1;
    document.getElementById("pane-" + p).hidden = !on;
    if (on && focusTab) tab.focus();
  });
}
document.querySelectorAll(".settings-tab").forEach(tab => {
  tab.addEventListener("click", () => showSettingsPane(tab.dataset.pane));
  tab.addEventListener("keydown", e => {
    const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    e.stopPropagation();
    const i = SETTINGS_PANES.indexOf(tab.dataset.pane);
    showSettingsPane(SETTINGS_PANES[(i + step + SETTINGS_PANES.length) % SETTINGS_PANES.length], true);
  });
});
document.getElementById("btn-settings").addEventListener("click", () => openSettings());
document.getElementById("settings-close").addEventListener("click", closeSettings);
document.getElementById("settings-modal").addEventListener("click", e => {
  if (e.target.id === "settings-modal") closeSettings();
});
document.getElementById("btn-kbd-help").addEventListener("click", () => openSettings("keys"));

/** Settings › Sources: the per-system choices made in the Scrape menu. */
function renderScrapeSources() {
  const box = document.getElementById("sources-list");
  const prefs = scraperPrefs();
  const folders = Object.keys(prefs).filter(f => SCRAPERS[prefs[f]]).sort();
  if (!folders.length) {
    box.innerHTML = `<p class="sources-empty">${escapeHtml(t("settings.sources_none"))}</p>`;
    return;
  }
  box.innerHTML = folders.map(f => {
    const sc = SCRAPERS[prefs[f]];
    return `<div class="source-row"><code class="source-folder">${escapeHtml(f)}</code>` +
      `<span class="source-name">${icon(sc.icon)}${escapeHtml(sc.label)}</span>` +
      `<button type="button" class="btn btn-sm btn-ghost" data-reset-folder="${escapeHtml(f)}">` +
      `${escapeHtml(t("editor.scrape_auto"))}</button></div>`;
  }).join("") +
    `<div class="sources-foot"><button type="button" class="btn btn-sm" data-reset-folder="*">` +
    `${escapeHtml(t("settings.sources_reset_all"))}</button></div>`;
}
document.getElementById("sources-list").addEventListener("click", e => {
  const btn = e.target.closest("[data-reset-folder]");
  if (!btn) return;
  const folder = btn.dataset.resetFolder;
  const prefs = scraperPrefs();
  if (folder === "*") Object.keys(prefs).forEach(k => delete prefs[k]);
  else delete prefs[folder];
  try { localStorage.setItem(SCRAPER_PREF_KEY, JSON.stringify(prefs)); } catch (_) {}
  updateScrapeButton();
  renderScrapeSources();
  const first = document.querySelector("#sources-list button") || document.getElementById("tab-sources");
  first.focus();
});

/* --- Actions on the whole gamelist (app bar ⋯ menu) ----------------------- */
setupMenu("actions-menu", "btn-actions");
function setGamelistActionsEnabled(on) {
  ["btn-manual-backup", "btn-fill-arcade", "btn-purge-regions"].forEach(id => {
    document.getElementById(id).disabled = !on;
  });
}

/* --- This game (header ⋯ menu) and "Next incomplete" ---------------------- */
setupMenu("game-menu", "btn-game-menu");

/** Full path of the selected game's ROM, with the separators of the gamelist path. */
function currentRomPath() {
  const g = games.find(x => x.index === currentIndex);
  if (!g) return "";
  if (/^([a-zA-Z]:)?[\\/]/.test(g.path)) return g.path;     // already absolute
  const xml = window.__gmeXmlPath || "";
  const sep = xml.includes("\\") ? "\\" : "/";
  const dir = xml.slice(0, Math.max(xml.lastIndexOf("/"), xml.lastIndexOf("\\")));
  const rel = g.path.replace(/^\.[\\/]/, "").replace(/[\\/]/g, sep);
  return dir ? dir + sep + rel : rel;
}
document.getElementById("btn-copy-path").addEventListener("click", async () => {
  const path = currentRomPath();
  if (!path) return;
  try {
    await navigator.clipboard.writeText(path);
    toast(t("toast.path_copied", { path }));
  } catch (_) {
    toast(path, "info");
  }
});

/** A game the "Next incomplete" button stops on: missing media (or matching the media filter). */
function isIncomplete(g) {
  return mediaFilter === "all" ? matchesMediaFilter(g, "any") : matchesMediaFilter(g);
}
function nextIncomplete() {
  const visible = getVisibleListIndices();
  if (!visible.length) return;
  const pos = visible.indexOf(currentListIndex);
  for (let step = 1; step <= visible.length; step++) {
    const listIndex = visible[(pos + step + visible.length) % visible.length];
    if (listIndex === currentListIndex) break;
    if (isIncomplete(games[listIndex])) {
      requestSelectGame(listIndex);
      return;
    }
  }
  toast(t("toast.no_incomplete"), "info");
}
document.getElementById("btn-next-incomplete").addEventListener("click", nextIncomplete);

document.getElementById("btn-reload").addEventListener("click", async () => {
  if (!(await confirmLeaveEditor())) return;
  await loadGames();
  toast(t("toast.list_reloaded"));
});


document.getElementById("btn-quit").addEventListener("click", async () => {
  if (!(await confirmLeaveEditor())) return;
  const choice = await askConfirm({
    title: t("confirm.quit_title"),
    bodyHtml: t("confirm.quit_body"),
    showBackup: false,
    okLabel: t("confirm.quit_ok"),
  });
  if (!choice.confirmed) return;

  setStatus(t("confirm.quit_ok") + "…");
  try {
    await fetch("/api/shutdown", { method: "POST" });
  } catch (e) {
    // Server may die before the response — expected
  }

  const sprite = document.querySelector(".icon-sprite");
  document.body.innerHTML =
    (sprite ? sprite.outerHTML : "") +
    '<div class="shutdown-screen">' +
    '<div class="shutdown-emoji">' + icon("power") + '</div>' +
    '<div class="shutdown-title">' + t("status.shutdown_title") + '</div>' +
    '<div class="shutdown-msg">' + t("status.shutdown_msg") + "</div></div>";

  // Often blocked by the browser if the tab was not opened by script
  setTimeout(() => {
    try { window.close(); } catch (e) {}
    try { window.open("", "_self"); window.close(); } catch (e) {}
  }, 300);
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

document.getElementById("btn-fill-arcade").addEventListener("click", async () => {
  const choice = await askConfirm({
    title: t("confirm.arcade_sys_title"),
    bodyHtml: t("confirm.arcade_sys_body"),
    okLabel: t("tools.arcade_sys_btn"),
    okClass: "btn-accent",
  });
  if (!choice.confirmed) return;
  setStatus(t("status.filling_arcade"));
  try {
    const data = await apiFetch("/api/fill-arcadesystem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup: choice.backup }),
    });
    toast(t("toast.arcade_sys_ok", {
      n: data.filled || 0,
      skip: data.skipped || 0,
      miss: data.missing || 0,
    }));
    await loadGames();
  } catch (e) {
    handleError(e);
  }
});

document.getElementById("btn-purge-regions").addEventListener("click", async () => {
  const choice = await askConfirm({
    title: t("confirm.purge_title"),
    bodyHtml: t("confirm.purge_body"),
    okLabel: t("confirm.purge_ok"),
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
    okLabel: t("confirm.delete_ok"),
  });
  if (!choice.confirmed) return;

  setStatus(t("status.deleting_game"));
  try {
    const data = await apiFetch(gameUrl(`/api/delete-game/${currentIndex}`), {
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

/* Recent files: one click opens. The system folder (parent of gamelist.xml)
 * comes first, because long paths only differ at their end. */
function recentKey(path) {
  // Windows paths: same file whatever the case or the slashes
  return /^[a-zA-Z]:[\\/]|\\/.test(path) ? path.replace(/\//g, "\\").toLowerCase() : path;
}
function getRecentGamelists() {
  try {
    const raw = localStorage.getItem(RECENT_GL_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((p) => typeof p === "string" && p) : [];
  } catch (_) {
    return [];
  }
}
function saveRecentGamelists(list) {
  try { localStorage.setItem(RECENT_GL_KEY, JSON.stringify(list.slice(0, RECENT_GL_MAX))); } catch (_) {}
}
function pushRecentGamelist(path) {
  if (!path) return;
  const key = recentKey(path);
  saveRecentGamelists([path, ...getRecentGamelists().filter((p) => recentKey(p) !== key)]);
}
function forgetRecentGamelist(path) {
  const key = recentKey(path);
  saveRecentGamelists(getRecentGamelists().filter((p) => recentKey(p) !== key));
}

function renderRecentGamelists() {
  const box = document.getElementById("open-gl-recent");
  if (!box) return;
  const current = window.__gmeXmlPath ? recentKey(window.__gmeXmlPath) : null;
  const list = getRecentGamelists().filter((p) => recentKey(p) !== current);
  if (!list.length) {
    box.innerHTML = `<div class="open-gl-recent-empty">${escapeHtml(t("open_gl.recent_empty"))}</div>`;
    return;
  }
  box.innerHTML = list.map((p) => {
    const parts = p.split(/[\\/]/).filter(Boolean);
    const folder = parts.length > 1 ? parts[parts.length - 2] : p;
    return `<div class="open-gl-recent-row" role="listitem">` +
      `<button type="button" class="open-gl-recent-item" data-path="${escapeHtml(p)}" title="${escapeHtml(p)}">` +
      `${icon("device-gamepad-2")}<span class="open-gl-recent-name">${escapeHtml(folder)}</span>` +
      `<span class="open-gl-recent-path">\u200e${escapeHtml(p)}\u200e</span></button>` +
      `<button type="button" class="btn btn-icon btn-sm open-gl-recent-forget" data-path="${escapeHtml(p)}"` +
      ` title="${escapeHtml(t("open_gl.recent_forget"))}" aria-label="${escapeHtml(t("open_gl.recent_forget"))}">${icon("x")}</button>` +
      `</div>`;
  }).join("");
}
document.getElementById("open-gl-recent").addEventListener("click", (e) => {
  const forget = e.target.closest(".open-gl-recent-forget");
  if (forget) {
    forgetRecentGamelist(forget.dataset.path);
    renderRecentGamelists();
    return;
  }
  const item = e.target.closest(".open-gl-recent-item");
  if (!item) return;
  document.getElementById("open-gl-path").value = item.dataset.path || "";
  applyOpenGamelist();
});

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
          `<span class="open-gl-item-icon">${icon("folder")}</span><span>${escapeHtml(d.name)}</span></button>`
      );
    }
    for (const f of files) {
      const cls = f.is_gamelist ? "open-gl-item open-gl-file is-gamelist" : "open-gl-item open-gl-file";
      const fileIcon = icon(f.is_gamelist ? "device-gamepad-2" : "file");
      parts.push(
        `<button type="button" class="${cls}" role="listitem" data-path="${escapeHtml(f.path)}">` +
          `<span class="open-gl-item-icon">${fileIcon}</span><span>${escapeHtml(f.name)}</span></button>`
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

/** Open the in-app folder browser (defaults to parent of current gamelist or RetroBat/roms). */
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

/** POST /api/open-gamelist then refresh list + system badge. */
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
    window.__gmeLoaded = true;
    pushRecentGamelist(window.__gmeXmlPath);
    games = data.games || [];
    setNoGamelistUi(true);
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
    // A recent file that was moved or deleted: drop it from the list
    if (e && e.code === "open_not_found") {
      forgetRecentGamelist(path);
      renderRecentGamelists();
    }
    handleError(e);
  }
}


document.getElementById("open-gl-up").addEventListener("click", () => {
  if (__browseParent) browseDirectory(__browseParent);
});
document.getElementById("open-gl-refresh").addEventListener("click", () => {
  browseDirectory(__browsePath || null);
});

document.getElementById("btn-open-gamelist").addEventListener("click", async () => {
  if (await confirmLeaveEditor()) openGamelistModal();
});

document.getElementById("btn-empty-open-gamelist")?.addEventListener("click", () => {
  if (typeof openGamelistModal === "function") openGamelistModal();
});

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
// Version / date come from app.py (APP_VERSION, APP_RELEASE_DATE) via <body data-*>
const APP_ABOUT = {
  version: document.body.dataset.appVersion || "",
  versionLabel: "v" + (document.body.dataset.appVersion || ""),
  date: document.body.dataset.appDate || "",
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

/** App entry: locale → genres → games; auto-open file picker if nothing loaded. */
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
  await loadGames();
  // First launch / no gamelist: open the file browser automatically
  if (!window.__gmeLoaded && typeof openGamelistModal === "function") {
    setTimeout(() => openGamelistModal(), 350);
  }
}


/* ========== Scrape ==========
 * One "Scrape" button. Its source depends on the system (server default:
 * system.scraper, see gme/systems.py) and can be forced from the ▾ menu; the
 * choice is remembered per system in this browser.
 * Flow: scrape → candidate list if ambiguous → comparison dialog → apply.
 * The dialog is built from the server's `compare` rows (gme/scrapers/compare.py):
 * what is missing is checked, nothing is replaced unless the user asks.
 * Proposed images come from /api/scrape/preview/<key>: downloaded once by the
 * server, then reused when applied (ScreenScraper counts every download).
 */
let ssBusy = false;

function setSsLoading(on, message) {
  ssBusy = !!on;
  const el = document.getElementById("ss-loading");
  const txt = document.getElementById("ss-loading-text");
  if (txt && message) txt.textContent = message;
  if (el) el.hidden = !on;
  document.body.classList.toggle("ss-busy", on);
  setScrapeEnabled(!on && currentIndex !== null);
  const applyBtn = document.getElementById("ss-modal-apply");
  if (applyBtn && !applyBtn.hidden) applyBtn.disabled = on || !selectedScrapeFields().length;
  const testBtn = document.getElementById("btn-ss-test");
  if (testBtn) testBtn.disabled = on;
}
async function loadSsConfig() {
  try {
    const cfg = await apiFetch("/api/ss/config");
    document.getElementById("ss-ssid").value = cfg.ssid || "";
    document.getElementById("ss-region").value = cfg.prefer_region || "fr";
    const mt = cfg.media_types || {};
    const img = document.getElementById("ss-type-image");
    const box = document.getElementById("ss-type-boxart");
    const mix = document.getElementById("ss-type-mix");
    if (img) img.value = mt.image || "ss";
    if (box) box.value = mt.boxart || "box-3D";
    if (mix) mix.value = mt.mix || "mixrbv2";
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
    media_types: {
      image: document.getElementById("ss-type-image").value,
      boxart: document.getElementById("ss-type-boxart").value,
      mix: document.getElementById("ss-type-mix").value,
    },
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
    st.textContent = e.message;
    st.className = "ss-status err";
    toast("ScreenScraper : " + e.message, "error");
  } finally {
    setSsLoading(false);
  }
}

document.getElementById("btn-ss-save").addEventListener("click", saveSsConfig);
document.getElementById("btn-ss-test").addEventListener("click", testSsConfig);

const SCRAPERS = {
  screenscraper: { label: "ScreenScraper", icon: "cloud-download", scrape: "/api/ss/scrape/", apply: "/api/ss/apply/", idKey: "gameid" },
  arcadeitalia: { label: "Arcade Database", icon: "coin", scrape: "/api/adb/scrape/", apply: "/api/adb/apply/", idKey: "romset" },
  steam: { label: "Steam", icon: "brand-steam", scrape: "/api/steam/scrape/", apply: "/api/steam/apply/", idKey: "appid" },
};
const SCRAPER_PREF_KEY = "gme_scraper_by_system";
const SCRAPE_MEDIA_ICONS = {
  image: "photo", thumbnail: "photo", marquee: "tag", boxart: "box", boxback: "flip-horizontal",
  cartridge: "device-sd-card", fanart: "wallpaper", mix: "layout-collage", map: "map", bezel: "frame",
  video: "movie", manual: "book", pad2key: "keyboard",
};
const SCRAPE_NOT_IMAGES = ["video", "manual", "pad2key"];
// Same presets as the server (gme/scrapers/compare.py PRESETS)
const SCRAPE_PRESETS = { missing: ["new"], all: ["new", "different", "replace"], none: [] };
const SCRAPE_BADGES = { new: "scrape.status_new", different: "scrape.status_different", replace: "scrape.status_replace" };

let currentSystem = null;   // { folder, label, id, scraper } from /api/games
let scrapeState = null;     // { source, proposed, rows } while the comparison is open

/* --- Source: automatic per system, or forced from the menu --- */
function scraperPrefs() {
  try {
    const v = JSON.parse(localStorage.getItem(SCRAPER_PREF_KEY) || "{}");
    return v && typeof v === "object" ? v : {};
  } catch (_) {
    return {};
  }
}
function autoScraper() {
  const s = currentSystem && currentSystem.scraper;
  return SCRAPERS[s] ? s : "screenscraper";
}
function forcedScraper() {
  const folder = currentSystem && currentSystem.folder;
  const v = folder ? scraperPrefs()[folder] : null;
  return SCRAPERS[v] ? v : null;
}
function chosenScraper() {
  return forcedScraper() || autoScraper();
}
function rememberScraper(source) {
  const folder = currentSystem && currentSystem.folder;
  if (!folder) return;
  const prefs = scraperPrefs();
  if (!source || source === autoScraper()) delete prefs[folder];
  else prefs[folder] = source;
  try { localStorage.setItem(SCRAPER_PREF_KEY, JSON.stringify(prefs)); } catch (_) {}
  updateScrapeButton();
}
function updateScrapeButton() {
  const source = chosenScraper();
  const sc = SCRAPERS[source];
  const name = document.getElementById("scrape-source-name");
  if (name) name.textContent = sc.label;
  const use = document.querySelector("#btn-scrape svg use");
  if (use) use.setAttribute("href", "#i-" + sc.icon);
  document.querySelectorAll("#scrape-menu .menu-item[data-source]").forEach(item => {
    item.setAttribute("aria-checked", item.dataset.source === source ? "true" : "false");
  });
  const forced = !!forcedScraper();
  const system = (currentSystem && (currentSystem.label || currentSystem.folder)) || "—";
  const note = document.getElementById("scrape-menu-note");
  if (note) note.textContent = t(forced ? "editor.scrape_note_forced" : "editor.scrape_note_auto", { system });
  const auto = document.getElementById("scrape-menu-auto");
  if (auto) auto.hidden = !forced;
}
function setScrapeEnabled(on) {
  ["btn-scrape", "btn-scrape-menu"].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.disabled = !on;
  });
  if (!on) closeScrapeMenu(false);
}

setupMenu("scrape-menu", "btn-scrape-menu", updateScrapeButton);
function closeScrapeMenu(focusButton) {
  closeMenu("scrape-menu", focusButton);
}
document.querySelectorAll("#scrape-menu .menu-item[data-source]").forEach(item => {
  item.addEventListener("click", async () => {
    const source = item.dataset.source;
    rememberScraper(source);
    if (await confirmLeaveEditor()) runScrape(source);
  });
});
document.getElementById("scrape-menu-auto").addEventListener("click", () => rememberScraper(null));
document.getElementById("btn-scrape").addEventListener("click", async () => {
  if (await confirmLeaveEditor()) runScrape(chosenScraper());
});

/* --- Scrape one game --- */
async function runScrape(source, forcedId) {
  if (currentIndex === null || ssBusy) return;
  const sc = SCRAPERS[source] || SCRAPERS.screenscraper;
  if (forcedId != null) forcedId = String(forcedId).trim() || null;
  setSsLoading(true, t(forcedId ? "scrape.loading_game" : "scrape.searching", { source: sc.label }));
  setStatus(t("scrape.status_search", { source: sc.label }));
  try {
    let data;
    try {
      data = await apiFetch(gameUrl(sc.scrape + currentIndex), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(forcedId ? { [sc.idKey]: forcedId } : {}),
      });
    } catch (e) {
      const d = e.data || {};
      let msg = e.message;
      if (d.hash && d.hash.crc && !msg.includes("CRC")) msg += ` · CRC ${d.hash.crc}`;
      throw new Error(msg);
    }
    if (data.need_choice && data.candidates && data.candidates.length) {
      showScrapeCandidates(source, data);
      setStatus(t("scrape.status_choice", { source: sc.label }));
      return;
    }
    if (!data.proposed) throw new Error(t("scrape.no_proposal"));
    showScrapeCompare(source, data, !!forcedId);
    setStatus(t("scrape.status_ready", { source: sc.label }));
  } catch (e) {
    handleError(e, sc.label);
  } finally {
    setSsLoading(false);
    focusSsModal();
  }
}

/** Keyboard: Enter applies what is checked; in the candidate list, the best match. */
function focusSsModal() {
  const modal = document.getElementById("ss-modal");
  if (!modal.classList.contains("open")) return;
  const apply = document.getElementById("ss-modal-apply");
  const target = !apply.hidden && !apply.disabled ? apply
    : modal.querySelector(".ss-candidate, .seg, #ss-modal-cancel");
  if (target) target.focus();
}

function setScrapeTitle(source, text) {
  const sc = SCRAPERS[source];
  document.getElementById("ss-modal-title").innerHTML = icon(sc.icon) + `<span>${escapeHtml(text)}</span>`;
}
function scrapeFieldLabel(key) {
  return t("scrape.field_" + key, null, key);
}
function scrapeMatchLabel(method, picked) {
  if (picked) return t("scrape.match_pick");
  if (!method) return "?";
  if (method.startsWith("hash")) return t("scrape.match_hash");
  if (["gameid", "romset", "appid"].includes(method)) return t("scrape.match_id");
  return t("scrape.match_name");
}
function scrapeInfoText(source, data, picked) {
  const p = data.proposed || {};
  const id = source === "steam" ? "AppID " + (p.steam_appid || data.steam_appid || "?")
    : source === "arcadeitalia" ? (p.adb_romset || data.romset || "?")
    : "#" + (p.ss_id || "?");
  let txt = t("scrape.found", { name: p.name || "?", id, how: scrapeMatchLabel(data.match_method, picked) });
  if (data.hash && data.hash.crc) txt += ` · CRC ${data.hash.crc}`;
  return txt;
}

/** Values as the editor shows them: stars, dates, language and region names. */
function fmtScrapeValue(key, value) {
  const v = String(value || "").trim();
  if (!v) return "";
  if (key === "rating") {
    const n = parseFloat(v);
    if (!isNaN(n)) return t("editor.rating_value", { n: fmtStars(Math.max(0, Math.min(1, n)) * 5) });
  }
  if (key === "releasedate") {
    const m = /^(\d{4})(\d{2})(\d{2})/.exec(v);
    if (m) {
      const d = new Date(+m[1], +m[2] - 1, +m[3]);
      try {
        return d.toLocaleDateString(currentLocale || "fr", { year: "numeric", month: "long", day: "numeric" });
      } catch (_) {
        return `${m[1]}-${m[2]}-${m[3]}`;
      }
    }
  }
  if (key === "lang") return langLabel(v);
  if (key === "region") return regionLabel(v);
  return v;
}
function scrapeBadge(status) {
  const key = SCRAPE_BADGES[status];
  return key ? `<span class="ss-badge" data-status="${status}">${escapeHtml(t(key))}</span>` : "";
}
function scrapeMediaCardHtml(r) {
  const label = scrapeFieldLabel(r.key);
  const ic = SCRAPE_MEDIA_ICONS[r.key] || "photo";
  const isFile = SCRAPE_NOT_IMAGES.includes(r.key);
  const fileBox = text => `<span class="ss-file">${icon(ic)}<span>${escapeHtml(text)}</span></span>`;
  const current = !r.current
    ? `<span class="ss-empty">${escapeHtml(t("scrape.none"))}</span>`
    : isFile ? fileBox(r.current.split("/").pop())
    : `<img src="${escapeHtml(mediaUrl(r.current))}" alt="" loading="lazy">`;
  const facts = [r.media_type, r.quality, r.bytes ? t("scrape.size_mb", { n: Math.round(r.bytes / 1048576) }) : "", r.trailer]
    .filter(Boolean).map(String);
  const proposed = r.preview
    ? `<span class="ss-shimmer" aria-hidden="true"></span><img src="${escapeHtml(r.preview)}" alt="" loading="lazy">`
    : fileBox(facts.join(" · ") || label);
  // New media: only the proposed frame (nothing to compare with)
  const single = r.status === "new";
  const typeTitle = r.media_type ? ` title="${escapeHtml(r.media_type)}"` : "";
  return `<label class="ss-media-card" data-status="${r.status}">` +
    `<span class="ss-card-head"><input type="checkbox" data-ss-field="${r.key}">` +
    `<span class="ss-card-title">${icon(ic)}<span>${escapeHtml(label)}</span></span>${scrapeBadge(r.status)}</span>` +
    `<span class="ss-pair${single ? " is-single" : ""}">` +
    (single ? "" :
      `<span class="ss-pane is-current"><span class="ss-frame">${current}</span>` +
      `<span class="ss-cap">${escapeHtml(t("scrape.current"))}<span class="ss-dims"></span></span></span>`) +
    `<span class="ss-pane is-proposed"><span class="ss-frame"${typeTitle}>${proposed}</span>` +
    `<span class="ss-cap">${escapeHtml(t("scrape.proposed"))}<span class="ss-dims"></span></span></span>` +
    `</span></label>`;
}
function scrapeMetaRowHtml(r) {
  const cur = fmtScrapeValue(r.key, r.current);
  const nw = fmtScrapeValue(r.key, r.proposed);
  const star = r.key === "rating" ? icon("star", "ss-star") : "";
  return `<label class="ss-meta-row${r.key === "desc" ? " is-long" : ""}" data-status="${r.status}">` +
    `<input type="checkbox" data-ss-field="${r.key}">` +
    `<span class="ss-meta-label"><span>${escapeHtml(scrapeFieldLabel(r.key))}</span>${scrapeBadge(r.status)}</span>` +
    `<span class="ss-val is-current" title="${escapeHtml(cur)}">${cur ? `<span class="ss-old">${star}${escapeHtml(cur)}</span>` : `<span class="ss-none">${escapeHtml(t("scrape.none"))}</span>`}</span>` +
    `<span class="ss-arrow" aria-hidden="true">→</span>` +
    `<span class="ss-val is-proposed" title="${escapeHtml(nw)}">${star}${escapeHtml(nw)}</span>` +
    `</label>`;
}

function showScrapeCompare(source, data, picked) {
  const sc = SCRAPERS[source];
  const rows = Array.isArray(data.compare) ? data.compare : [];
  scrapeState = { source, proposed: data.proposed, rows };
  setScrapeTitle(source, sc.label);
  document.getElementById("ss-modal-info").textContent = scrapeInfoText(source, data, picked);

  const actionable = rows.filter(r => SCRAPE_PRESETS.all.includes(r.status));
  const media = actionable.filter(r => r.kind === "media");
  const meta = actionable.filter(r => r.kind === "meta");
  const same = rows.filter(r => r.status === "same");
  const none = rows.filter(r => r.status === "unavailable");
  const names = list => list.map(r => escapeHtml(scrapeFieldLabel(r.key))).join(", ");
  let html = "";
  if (media.length) {
    html += `<section class="ss-section"><h4 class="ss-section-title">${escapeHtml(t("scrape.section_media"))}</h4>` +
      `<div class="ss-media-grid">${media.map(scrapeMediaCardHtml).join("")}</div></section>`;
  }
  if (meta.length) {
    html += `<section class="ss-section"><h4 class="ss-section-title">${escapeHtml(t("scrape.section_info"))}</h4>` +
      `<div class="ss-meta-table"><div class="ss-meta-head" aria-hidden="true"><span></span><span></span>` +
      `<span>${escapeHtml(t("scrape.current"))}</span><span></span><span>${escapeHtml(t("scrape.proposed"))}</span></div>` +
      meta.map(scrapeMetaRowHtml).join("") + `</div></section>`;
  }
  if (!actionable.length) {
    html += `<div class="ss-nothing">${icon("circle-check")}<p>${escapeHtml(t("scrape.nothing_new", { source: sc.label }))}</p></div>`;
  }
  const rest = [];
  if (same.length) rest.push(`<p class="ss-rest">${icon("check")}<span><b>${escapeHtml(t("scrape.rest_same"))}</b> ${names(same)}</span></p>`);
  if (none.length) rest.push(`<p class="ss-rest">${icon("x")}<span><b>${escapeHtml(t("scrape.rest_unavailable", { source: sc.label }))}</b> ${names(none)}</span></p>`);
  if (rest.length) html += `<div class="ss-rests">${rest.join("")}</div>`;

  const box = document.getElementById("ss-fields");
  box.innerHTML = html;
  box.querySelectorAll(".ss-pane img").forEach(img => {
    const pane = img.closest(".ss-pane");
    img.addEventListener("load", () => {
      pane.classList.add("is-loaded");
      pane.querySelector(".ss-dims").textContent = ` · ${img.naturalWidth} × ${img.naturalHeight}`;
    });
    img.addEventListener("error", () => {
      pane.classList.add("is-loaded");
      pane.querySelector(".ss-frame").innerHTML =
        `<span class="ss-empty is-error">${icon("alert-triangle")}<span>${escapeHtml(t("zone.preview_unavailable"))}</span></span>`;
    });
  });
  box.hidden = false;
  document.getElementById("ss-candidates").hidden = true;
  document.getElementById("ss-select-bar").hidden = !actionable.length;
  document.getElementById("ss-hint").hidden = !actionable.length;
  document.getElementById("ss-modal-apply").hidden = false;
  applyScrapePreset("missing");
  openSsModal();
  box.scrollTop = 0;
}

function showScrapeCandidates(source, data) {
  scrapeState = null;
  setScrapeTitle(source, t("scrape.choose_title", { source: SCRAPERS[source].label }));
  let info = t("scrape.choose_info", { search: data.search || data.local_name || data.romset || "?", n: data.candidates.length });
  if (data.hash && data.hash.crc) info += ` · CRC ${data.hash.crc}`;
  document.getElementById("ss-modal-info").textContent = info;
  const box = document.getElementById("ss-candidates");
  box.innerHTML = "";
  data.candidates.forEach(c => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ss-candidate";
    const idLabel = c.romset || c.ss_id || c.appid || "?";
    btn.innerHTML =
      `<span class="ss-cand-name">${escapeHtml(c.name || idLabel)}</span>` +
      `<span class="ss-cand-meta">${escapeHtml(String(idLabel))}` +
      (c.system ? ` · ${escapeHtml(c.system)}` : "") +
      ` · ${escapeHtml(t("scrape.similarity", { pct: Math.round((c.score || 0) * 100) }))}</span>`;
    btn.addEventListener("click", () => {
      closeSsModal();
      runScrape(source, c.ss_id || c.romset || c.appid);
    });
    box.appendChild(btn);
  });
  box.hidden = false;
  document.getElementById("ss-fields").hidden = true;
  document.getElementById("ss-select-bar").hidden = true;
  document.getElementById("ss-hint").hidden = true;
  document.getElementById("ss-modal-apply").hidden = true;
  openSsModal();
}

/* --- Selection: presets and count --- */
function scrapeCheckboxes() {
  return [...document.querySelectorAll("#ss-fields input[data-ss-field]")];
}
function selectedScrapeFields() {
  return scrapeCheckboxes().filter(cb => cb.checked).map(cb => cb.dataset.ssField);
}
function scrapeStatusOf(key) {
  const row = scrapeState && scrapeState.rows.find(r => r.key === key);
  return row ? row.status : "";
}
function applyScrapePreset(preset) {
  const wanted = SCRAPE_PRESETS[preset] || [];
  scrapeCheckboxes().forEach(cb => { cb.checked = wanted.includes(scrapeStatusOf(cb.dataset.ssField)); });
  updateScrapeSelection();
}
function updateScrapeSelection() {
  const boxes = scrapeCheckboxes();
  const chosen = new Set(selectedScrapeFields());
  boxes.forEach(cb => cb.closest(".ss-media-card, .ss-meta-row").classList.toggle("is-checked", cb.checked));
  const n = chosen.size;
  document.getElementById("ss-count").textContent = t("scrape.selected", { n });
  document.getElementById("ss-apply-label").textContent = n ? t("scrape.apply_n", { n }) : t("scrape.apply");
  const apply = document.getElementById("ss-modal-apply");
  apply.disabled = !n || ssBusy;
  // The first preset matching the selection exactly is shown as active
  const match = Object.keys(SCRAPE_PRESETS).find(p => boxes.every(cb =>
    SCRAPE_PRESETS[p].includes(scrapeStatusOf(cb.dataset.ssField)) === cb.checked));
  document.querySelectorAll("#ss-select-bar .seg").forEach(b => {
    b.setAttribute("aria-pressed", b.dataset.preset === match ? "true" : "false");
  });
}
document.getElementById("ss-fields").addEventListener("change", e => {
  if (e.target.matches("input[data-ss-field]")) updateScrapeSelection();
});
document.querySelectorAll("#ss-select-bar .seg").forEach(b => {
  b.addEventListener("click", () => applyScrapePreset(b.dataset.preset));
});

async function applyScrape() {
  if (currentIndex === null || !scrapeState || ssBusy) return;
  const fields = selectedScrapeFields();
  if (!fields.length) {
    toast(t("toast.no_fields"), "error");
    return;
  }
  const sc = SCRAPERS[scrapeState.source];
  setSsLoading(true, t("status.applying_download"));
  setStatus(t("scrape.status_apply", { source: sc.label }));
  try {
    const data = await apiFetch(gameUrl(sc.apply + currentIndex), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields, proposed: scrapeState.proposed }),
    });
    closeSsModal();
    await loadGames();
    const errors = data.errors || [];
    let msg = t("scrape.apply_ok", { n: (data.applied || []).length });
    if (errors.length) {
      msg += t("scrape.apply_errors", { n: errors.length }) + " — " + errors[0];
      console.warn("scrape apply errors", errors);
    }
    toast(msg, errors.length ? "warning" : "success");
    setStatus(t("scrape.status_done", { source: sc.label }));
  } catch (e) {
    handleError(e, sc.label);
  } finally {
    setSsLoading(false);
  }
}

function openSsModal() {
  document.getElementById("ss-modal").classList.add("open");
}
function closeSsModal() {
  const modal = document.getElementById("ss-modal");
  const wasOpen = modal.classList.contains("open");
  modal.classList.remove("open");
  scrapeState = null;
  const cand = document.getElementById("ss-candidates");
  const fields = document.getElementById("ss-fields");
  cand.hidden = true;
  cand.innerHTML = "";
  fields.innerHTML = "";
  fields.hidden = false;
  if (wasOpen) document.getElementById("btn-scrape").focus();
}

// Closing the window / tab with unsaved changes: the browser asks
window.addEventListener("beforeunload", e => {
  if (changedFields().length) { e.preventDefault(); e.returnValue = ""; }
});
document.getElementById("ss-modal-close").addEventListener("click", closeSsModal);
document.getElementById("ss-modal-cancel").addEventListener("click", closeSsModal);
document.getElementById("ss-modal-apply").addEventListener("click", applyScrape);
document.getElementById("ss-modal").addEventListener("click", e => {
  if (e.target.id === "ss-modal") closeSsModal();
});


boot();
