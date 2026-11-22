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
{ key: "thumbnail", icon: "photo-square-rounded" },
{ key: "bezel",     icon: "frame" },
];
function getFields() {
  return FIELD_DEFS.map(f => ({
    ...f,
    label: t("fields." + f.key, null, f.key),
  }));
}

/* ========== i18n (client) ========== */
/* Keys are dotted paths in locale JSON. applyI18n() writes [data-i18n*] attributes. */
const LOCALE_KEY = "gme_locale";               // where older versions kept the language (browser)
const DEFAULT_LOCALE = "fr";
let I18N = {};
let currentLocale = DEFAULT_LOCALE;

/* --- Interface settings ------------------------------------------------------
 * Language, scrape source and required media per system: kept by the server in
 * ui_settings.json next to the app (gme/settings.py), not in the browser,
 * whose storage the app window can lose.
 */
let SETTINGS = { locale: null, theme: "dark", list_width: null, search_all_fields: false, scrapers: {}, required_media: {} };

/* Theme: dark (default), light, or as the system (follows Windows while open).
 * The page arrives with the saved theme already applied (templates/index.html). */
const THEMES = ["dark", "light", "system"];
const lightQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;
function applyTheme(pref) {
  const choice = THEMES.includes(pref) ? pref : "dark";
  const theme = choice === "system" ? (lightQuery && lightQuery.matches ? "light" : "dark") : choice;
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.dataset.themePref = choice;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === "light" ? "#f6f7fa" : "#13141c";
  document.querySelectorAll("[data-theme-choice]").forEach(b => {
    b.setAttribute("aria-pressed", b.dataset.themeChoice === choice ? "true" : "false");
  });
}
if (lightQuery) {
  const follow = () => { if (SETTINGS.theme === "system") applyTheme("system"); };
  if (lightQuery.addEventListener) lightQuery.addEventListener("change", follow);
  else if (lightQuery.addListener) lightQuery.addListener(follow);
}
document.getElementById("theme-choice").addEventListener("click", e => {
  const btn = e.target.closest("[data-theme-choice]");
  if (!btn) return;
  SETTINGS.theme = btn.dataset.themeChoice;
  applyTheme(SETTINGS.theme);
  saveSettings({ theme: SETTINGS.theme });
});

async function loadSettings() {
  try { SETTINGS = await apiFetch("/api/settings"); } catch (_) {}
  // Older versions kept the language and the sources in the browser: hand them over once
  const patch = {};
  let oldLocale = null, oldScrapers = null;
  try {
    oldLocale = localStorage.getItem(LOCALE_KEY);
    oldScrapers = JSON.parse(localStorage.getItem(SCRAPER_PREF_KEY) || "null");
  } catch (_) {}
  if (!SETTINGS.locale && /^[a-z]{2}/.test(oldLocale || "")) patch.locale = oldLocale.slice(0, 2);
  if (oldScrapers && typeof oldScrapers === "object" && !Object.keys(SETTINGS.scrapers).length) {
    const valid = Object.entries(oldScrapers).filter(([, v]) => SCRAPERS[v]);
    if (valid.length) patch.scrapers = Object.fromEntries(valid);
  }
  if (Object.keys(patch).length && !(await saveSettings(patch, { quiet: true }))) return;
  try {
    localStorage.removeItem(LOCALE_KEY);
    localStorage.removeItem(SCRAPER_PREF_KEY);
  } catch (_) {}
}

/** Save part of the settings ({locale}, {scrapers: {folder: source|null}}…). */
async function saveSettings(patch, { quiet = false } = {}) {
  try {
    SETTINGS = await apiFetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    return true;
  } catch (e) {
    if (!quiet) handleError(e);
    return false;
  }
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
  try { fillSsRegions(); } catch (_) {}
  try { selectionChanged(false); } catch (_) {}
  try { updateSearchModeUi(); } catch (_) {}
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
  if (ok) await saveSettings({ locale: currentLocale }, { quiet: true });
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
 * mediaFilter      : all | any (a required media missing) | one media key of FIELD_DEFS
 * genreFilter      : all | none (no genre) | "g:" + main genre in upper case (see genreKey)
 * flagFilter       : all | favorite | hidden | visible | kidgame
 */
let games = [];
let currentIndex = null;
let currentListIndex = null;
let mediaFilter = "all";
let genreFilter = "all";
let flagFilter = "all";
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
  const raw = !!options.raw;             // return the body as a Blob (file downloads)
  delete options.raw;
  const headers = new Headers(options.headers || {});
  if (!headers.has("X-Locale")) {
    headers.set("X-Locale", (typeof currentLocale !== "undefined" && currentLocale) ? currentLocale : "fr");
  }
  if (window.__gmeSession && !headers.has("X-Gamelist-Session")) {
    headers.set("X-Gamelist-Session", window.__gmeSession);
  }
  options.headers = headers;
  let res;
  try {
    res = await fetch(url, options);
  } catch (e) {
    const offline = (typeof navigator !== "undefined" && navigator.onLine === false);
    const err = new Error(offline ? t("errors.offline") : t("errors.server_down"));
    err.network = true;          // no answer at all (server stopped, offline)
    throw err;
  }

  let data = null;
  const ct = (res.headers.get("content-type") || "").toLowerCase();
  if (raw && res.ok && !ct.includes("application/json")) return res.blob();
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

/** "Label : value" with the punctuation of the interface language. */
function labelValue(label, value) {
  return t("common.label_value", { label, value });
}

/** Error toast; a source refusing for now (quota, maintenance) is a warning, not an error. */
function handleError(e, context) {
  const msg = (e && e.message) ? e.message : String(e);
  console.error(context || "", e);
  const isQuota = (e && e.code === "source_blocked") || isQuotaMessage(msg);
  toast(context ? labelValue(context, msg) : msg, isQuota ? "warning" : "error");
  setStatus(isQuota ? t("status.quota") : t("status.error"));
  return msg;
}
/* A replaced media usually keeps its file name: without a new URL the browser
 * shows the picture it already has. Each change stamps the paths it wrote. */
const MEDIA_STAMP = new Map();   // gamelist path → stamp
function stampMedia(paths) {
  const v = Date.now().toString(36);
  paths.forEach(p => { if (p) MEDIA_STAMP.set(p, v); });
}
function mediaUrl(relPath) {
  if (!relPath) return null;
  const v = MEDIA_STAMP.get(relPath);
  return "/media/" + relPath.replace(/^\.\//, "").split("/").map(encodeURIComponent).join("/") + (v ? "?v=" + v : "");
}
function thumbUrl(relPath) {
  const v = MEDIA_STAMP.get(relPath);
  return "/api/thumb?path=" + encodeURIComponent(relPath) + (v ? "&v=" + v : "");
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

/* Required media: what a game of this system needs to count as complete (list
 * counter, "Missing required media" filter, Next incomplete). Chosen per system
 * in Settings › Required media; arcade systems have no box by default. */
const DEFAULT_REQUIRED = ["image", "video", "marquee", "boxart"];
const DEFAULT_REQUIRED_ARCADE = ["image", "video", "marquee"];
function defaultRequired() {
  return currentSystem && currentSystem.scraper === "arcadeitalia" ? DEFAULT_REQUIRED_ARCADE : DEFAULT_REQUIRED;
}
function customRequired(folder) {
  const v = folder && SETTINGS.required_media && SETTINGS.required_media[folder];
  return Array.isArray(v) ? v : null;
}
function requiredKeys() {
  return customRequired(currentSystem && currentSystem.folder) || defaultRequired();
}
function missingRequired(g, keys) {
  return (keys || requiredKeys()).filter(k => !hasMedia(g, k));
}

function matchesMediaFilter(g, filterKey) {
  const key = filterKey !== undefined ? filterKey : mediaFilter;
  if (key === "all") return true;
  if (key === "any") return missingRequired(g).length > 0;
  return !hasMedia(g, key);
}

/* Search: name and ROM path by default (fast on 30 000 games); with the
 * "all fields" toggle, every metadata of the list too. The description is not
 * sent with the list (see LIST_FIELDS in gme/xml_store.py), so it is not searched. */
const SEARCH_EXTRA_FIELDS = ["genre", "developer", "publisher", "family", "players", "lang",
  "region", "releasedate", "arcadesystemname", "rating"];
let searchHay = new WeakMap();          // game → its lower-case text of every field, built once
function searchText(g) {
  let hay = searchHay.get(g);
  if (hay === undefined) {
    hay = [g.name, g.path, ...SEARCH_EXTRA_FIELDS.map(k => g[k] || "")].join("\n").toLowerCase();
    searchHay.set(g, hay);
  }
  return hay;
}
function matchesSearch(g, query) {
  if (!query) return true;
  const q = query.toLowerCase();
  if (SETTINGS.search_all_fields) return searchText(g).includes(q);
  return g.name.toLowerCase().includes(q) || g.path.toLowerCase().includes(q);
}
function updateSearchModeUi() {
  const on = !!SETTINGS.search_all_fields;
  const btn = document.getElementById("btn-search-all");
  btn.setAttribute("aria-pressed", String(on));
  btn.classList.toggle("is-on", on);
  const input = document.getElementById("search");
  input.dataset.i18nPlaceholder = on ? "sidebar.search_placeholder_all" : "sidebar.search_placeholder";
  input.placeholder = t(input.dataset.i18nPlaceholder);
}

/* Genre and flag filters. The genre filter groups by main genre (the part
 * before " / ", as the genre lists of the editor), case-insensitively. */
function genreKey(g) {
  const main = String(g.genre || "").split("/")[0].trim();
  return main ? "g:" + main.toUpperCase() : "none";
}
function isTrue(v) {
  return /^(true|1|yes)$/i.test(String(v || "").trim());
}
function matchesGenreFilter(g) {
  return genreFilter === "all" || genreKey(g) === genreFilter;
}
const FLAG_FILTERS = ["all", "favorite", "hidden", "visible", "kidgame"];
function matchesFlagFilter(g, key = flagFilter) {
  switch (key) {
    case "favorite": return isTrue(g.favorite);
    case "hidden": return isTrue(g.hidden);
    case "visible": return !isTrue(g.hidden);
    case "kidgame": return isTrue(g.kidgame);
    default: return true;
  }
}
function filtersActive() {
  return mediaFilter !== "all" || genreFilter !== "all" || flagFilter !== "all";
}

/** List indexes of the games shown under the current search + filters. */
function getFilteredGames(searchQuery) {
  const q = (searchQuery !== undefined
    ? searchQuery
    : document.getElementById("search").value).toLowerCase().trim();
  const out = [];
  for (let i = 0; i < games.length; i++) {
    const g = games[i];
    if (q && !matchesSearch(g, q)) continue;
    if (mediaFilter !== "all" && !matchesMediaFilter(g)) continue;
    if (genreFilter !== "all" && !matchesGenreFilter(g)) continue;
    if (flagFilter !== "all" && !matchesFlagFilter(g)) continue;
    out.push(i);
  }
  return out;
}

function updateGameCount(visibleCount) {
  const el = document.getElementById("game-count");
  if (!filtersActive() && !document.getElementById("search").value.trim()) {
    el.textContent = t("header.game_count", { n: games.length });
  } else {
    el.textContent = t("header.game_count_filtered", { visible: visibleCount, total: games.length });
  }
}

/** Filter menus, each option with its number of games. A menu counts the games
 * left by the search and the OTHER filters (what choosing that option would show). */
function updateFilterCounts(q) {
  const query = (q || "").toLowerCase().trim();
  const keys = FIELD_DEFS.map(f => f.key);
  const required = requiredKeys();
  const counts = { all: 0, any: 0 };
  keys.forEach(k => { counts[k] = 0; });
  const genres = new Map();             // key → { label, n }
  const flags = Object.fromEntries(FLAG_FILTERS.map(k => [k, 0]));
  let genreNone = 0;
  for (const g of games) {
    const gk = genreKey(g);
    if (gk !== "none" && !genres.has(gk)) {   // label: first spelling in the list, whatever is shown
      genres.set(gk, { label: String(g.genre).split("/")[0].trim(), n: 0 });
    }
    if (query && !matchesSearch(g, query)) continue;
    const okMedia = mediaFilter === "all" || matchesMediaFilter(g);
    const okGenre = matchesGenreFilter(g);
    const okFlag = matchesFlagFilter(g);
    if (okGenre && okFlag) {
      counts.all++;
      for (const k of keys) {
        if (!hasMedia(g, k)) counts[k]++;
      }
      if (missingRequired(g, required).length) counts.any++;
    }
    if (okMedia && okFlag) {
      if (gk === "none") genreNone++;
      else genres.get(gk).n++;
    }
    if (okMedia && okGenre) {
      for (const k of FLAG_FILTERS) if (matchesFlagFilter(g, k)) flags[k]++;
    }
  }
  fillGenreFilter(genres, genreNone);
  const flagSel = document.getElementById("flag-filter");
  if (flagSel.options.length !== FLAG_FILTERS.length) {
    flagSel.innerHTML = FLAG_FILTERS.map(k => `<option value="${k}"></option>`).join("");
  }
  // "All" carries no count (the header has it): the two menus share one row
  FLAG_FILTERS.forEach((k, i) => {
    flagSel.options[i].textContent = k === "all" ? t("sidebar.flag_all") : `${t("sidebar.flag_" + k)} (${fmtCount(flags[k])})`;
  });
  flagSel.value = flagFilter;
  flagSel.title = flagSel.selectedOptions[0] ? flagSel.selectedOptions[0].textContent : "";
  updateFilterHighlights();
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

/** Genre menu: the genres of this gamelist, sorted, plus "No genre". The chosen
 * one stays listed even when the search leaves no game in it. */
function fillGenreFilter(genres, none) {
  const sel = document.getElementById("genre-filter");
  if (genreFilter.startsWith("g:") && !genres.has(genreFilter)) {
    genres.set(genreFilter, { label: (sel.selectedOptions[0] && sel.selectedOptions[0].dataset.label) || genreFilter.slice(2), n: 0 });
  }
  const sorted = [...genres.entries()].filter(([k, e]) => e.n || k === genreFilter).sort((a, b) => a[1].label.localeCompare(b[1].label, currentLocale || "fr", { sensitivity: "base" }));
  const opt = (value, label, n, raw) =>
    `<option value="${escapeHtml(value)}"${raw ? ` data-label="${escapeHtml(raw)}"` : ""}>${escapeHtml(label)}${n === null ? "" : ` (${fmtCount(n)})`}</option>`;
  sel.innerHTML = opt("all", t("sidebar.genre_all"), null) +
    sorted.map(([k, e]) => opt(k, e.label, e.n, e.label)).join("") +
    (none || genreFilter === "none" ? opt("none", t("sidebar.genre_none"), none) : "");
  sel.value = genreFilter;
  sel.title = sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "";   // full text when cut
}

/** A filter that hides games is outlined, so a short list is never a surprise. */
function updateFilterHighlights() {
  [["media-filter", mediaFilter], ["genre-filter", genreFilter], ["flag-filter", flagFilter]].forEach(([id, v]) => {
    const el = document.getElementById(id);
    if (el) el.closest(".list-filter").classList.toggle("is-active", v !== "all");
  });
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
    bits.push(t("header.system_folder", { folder: system.folder }));
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
  const keepSession = window.__gmeSession;
  const pendingKeys = keepPath ? changedFields() : [];
  const pendingValues = pendingKeys.length ? readEditor() : null;
  try {
    const data = await apiFetch("/api/games");
    const loaded = data.loaded !== false && !!data.xml_path;
    const sameSession = !keepSession || keepSession === data.session_id;
    window.__gmeSession = data.session_id;
    window.__gmeLoaded = loaded;
    games = data.games || [];
    if (!loaded) {
      window.__gmeXmlPath = null;
      savedBatch = null;
      document.getElementById("saved-batch-entry").hidden = true;
      setNoGamelistUi(false);
      renderList();
      setStatus(t("status.no_gamelist"));
      return;
    }
    updateSystemBadge(data.system || null);
    window.__gmeXmlPath = data.xml_path;
    pruneSelection();
    setNoGamelistUi(true);          // the editor stays hidden until a game is selected
    if (currentIndex === null) document.getElementById("empty-state").hidden = false;
    if (!sameSession) {
      resetEditorSelection();
      selection.clear();
      renderList();
    } else if (keepIndex !== null) {
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
    await refreshSavedBatch();
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

function gameRowHtml(g, listIndex, pos, required) {
  const active = listIndex === currentListIndex;
  const ticked = selection.has(g.path);
  const missing = missingRequired(g, required);
  const present = required.length - missing.length;
  const title = missing.length
    ? t("sidebar.media_missing", { list: missing.map(fieldLabel).join(", ") })
    : t("sidebar.media_complete");
  const tp = thumbPath(g);
  const thumb = tp
    ? `<img src="${thumbUrl(tp)}" alt="" loading="lazy" decoding="async" />`
    : icon("device-gamepad-2");
  const countCls = !missing.length ? " is-complete" : present === 0 ? " is-empty" : "";
  return `<div class="game-item${active ? " active" : ""}${ticked ? " is-ticked" : ""}" role="option" id="gi-${listIndex}"` +
    ` data-list-index="${listIndex}" aria-selected="${active}" aria-setsize="${viewIndices.length}" aria-posinset="${pos + 1}">` +
    `<span class="gi-thumb">${thumb}<span class="gi-select"><input type="checkbox" tabindex="-1"${ticked ? " checked" : ""}` +
    ` aria-label="${escapeHtml(t("batch.tick", { name: g.name }))}" /></span></span>` +
    `<span class="gi-text"><span class="name" title="${escapeHtml(g.name)}">${escapeHtml(g.name)}</span><span class="path">${escapeHtml(g.path)}</span></span>` +
    `<span class="gi-count${countCls}" title="${escapeHtml(title)}">${required.length ? `${present}/${required.length}` : "–"}</span>` +
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
  const required = requiredKeys();
  for (let pos = first; pos < last; pos++) {
    const i = viewIndices[pos];
    html += gameRowHtml(games[i], i, pos, required);
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

/* --- Ticked games, for the batch scrape --------------------------------------
 * Kept by <path>, so they survive a reload of the list. Tick a row's box,
 * Ctrl+click a row or press X; Shift+click ticks every game shown in between.
 */
const selection = new Set();
let selectionAnchor = null;          // path of the last game ticked, for Shift+click

function toggleTicked(g, on) {
  if (!g) return;
  const tick = on === undefined ? !selection.has(g.path) : on;
  if (tick) selection.add(g.path);
  else selection.delete(g.path);
  selectionAnchor = g.path;
}
function selectRange(toListIndex) {
  const from = viewIndices.findIndex(i => games[i].path === selectionAnchor);
  const to = viewIndices.indexOf(toListIndex);
  if (from < 0 || to < 0) {
    toggleTicked(games[toListIndex]);
    return;
  }
  for (let p = Math.min(from, to); p <= Math.max(from, to); p++) selection.add(games[viewIndices[p]].path);
  selectionAnchor = games[toListIndex].path;
}
function pruneSelection() {
  if (!selection.size) return;
  const paths = new Set(games.map(g => g.path));
  [...selection].forEach(p => { if (!paths.has(p)) selection.delete(p); });
  selectionChanged(false);
}
function clearSelection() {
  selection.clear();
  selectionAnchor = null;
  selectionChanged();
}
/** Selection bar above the list; rows redrawn with their boxes. */
function selectionChanged(redraw = true) {
  const bar = document.getElementById("list-selection");
  bar.hidden = !selection.size;
  document.getElementById("list-selection-count").textContent = t("batch.selected", { n: fmtCount(selection.size) });
  document.getElementById("game-list").classList.toggle("has-selection", selection.size > 0);
  const copyItem = document.getElementById("btn-copy-selection-paths");
  copyItem.hidden = !selection.size;
  document.getElementById("copy-selection-sub").textContent = t("batch.selected", { n: fmtCount(selection.size) });
  if (redraw) renderListWindow(true);
}
document.getElementById("btn-selection-clear").addEventListener("click", clearSelection);

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

function markSaved(keys, submitted, updated) {
  if (!editorSnapshot) return;
  const now = readEditor();
  keys.forEach(k => {
    const saved = Object.prototype.hasOwnProperty.call(updated, k) ? updated[k] : submitted[k];
    // Normalize untouched inputs only: typing during the request remains dirty.
    if (now[k] === submitted[k]) EDITOR_FIELDS[k].set(saved);
    editorSnapshot[k] = saved;
  });
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
  const target = games.find(g => g.index === currentIndex);
  const session = window.__gmeSession;
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
    if (session !== window.__gmeSession) return false;
    const g = games.find(x => x.path === target.path);
    if (g && data.updated) { Object.assign(g, data.updated); searchHay.delete(g); }
    if (!g || currentIndex !== g.index) return true;
    markSaved(keys, now, data.updated || payload);
    if (keys.includes("name")) {
      games.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
      currentListIndex = games.findIndex(x => x.index === currentIndex);
      renderList(document.getElementById("search").value);
      scrollActiveIntoView();
    } else if (keys.some(k => k !== "desc")) {
      renderList(document.getElementById("search").value);      // genre, favorite… change the filters
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
  return await saveAllChanges() && !changedFields().length;
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
  ++_detailToken;
  const ta = document.getElementById("desc-textarea");
  ta.readOnly = !g._detail;
  ta.classList.toggle("is-loading", !g._detail);
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
  const session = window.__gmeSession;
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
  if (session !== window.__gmeSession || token !== _detailToken || currentIndex !== g.index) return;
  // A list refresh can restore an unsaved description while detail is loading.
  if (!editorSnapshot || ta.value === editorSnapshot.desc) ta.value = g.desc;
  ta.readOnly = false;
  ta.classList.remove("is-loading");
  if (editorSnapshot) editorSnapshot.desc = g.desc;
  updateUnsavedUi();
}
/* --- Media gallery ----------------------------------------------------------
 * Present media are shown large, each in its own shape (box art upright, logo
 * wide…) in a masonry of columns; missing media are grouped below as small drop targets. Dropping a
 * file or a web image on a tile replaces it; clicking a missing one (or the
 * upload button of a tile) opens a file picker.
 */
const MEDIA_SHAPE = {
  image: "4 / 3", video: "4 / 3", marquee: "3 / 1", manual: "16 / 10", boxart: "3 / 4",
  boxback: "3 / 4", cartridge: "1 / 1", fanart: "16 / 9", mix: "4 / 3", map: "1 / 1",
};
const MEDIA_ACCEPT = { video: "video/*", manual: "application/pdf,.pdf" };

/** Once the real size is known, the tile takes the media's own shape (within
 * limits, so a very tall or very wide image stays readable): nothing is cut,
 * no large empty band. MEDIA_SHAPE is only the shape while loading. */
function fitTileToMedia(tile, width, height) {
  if (!width || !height) return;
  const ratio = Math.min(4, Math.max(0.45, width / height));
  tile.style.setProperty("--ar", String(Math.round(ratio * 1000) / 1000));
}

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

function missingChipHtml(f, required) {
  const title = t("editor.choose_file", { field: f.label }) + (required ? ` (${t("editor.required")})` : "");
  return `<button type="button" class="missing-chip${required ? " is-required" : ""}" data-field="${f.key}" title="${escapeHtml(title)}">` +
    `${icon(f.icon)}<span>${escapeHtml(f.label)}</span>${icon("upload", "chip-add")}</button>`;
}

function renderZones(g) {
  const fields = getFields();
  const present = fields.filter(f => hasMedia(g, f.key));
  const missing = fields.filter(f => !hasMedia(g, f.key));
  const grid = document.getElementById("media-grid");
  grid.innerHTML = present.map(f => mediaTileHtml(g, f)).join("");
  grid.hidden = !present.length;
  // Required media first; the others after their own label
  const required = requiredKeys();
  const needed = missing.filter(f => required.includes(f.key));
  const optional = missing.filter(f => !required.includes(f.key));
  document.getElementById("missing-chips").innerHTML =
    needed.map(f => missingChipHtml(f, true)).join("") +
    (needed.length && optional.length ? `<span class="missing-sep">${escapeHtml(t("editor.missing_optional"))}</span>` : "") +
    optional.map(f => missingChipHtml(f, false)).join("");
  document.getElementById("media-missing").hidden = !missing.length;

  grid.querySelectorAll(".media-tile").forEach(tile => {
    const img = tile.querySelector("img");
    const dims = tile.querySelector(".tile-dims");
    if (img) {
      img.addEventListener("load", () => {
        dims.textContent = `${img.naturalWidth} × ${img.naturalHeight}`;
        fitTileToMedia(tile, img.naturalWidth, img.naturalHeight);
      });
      img.addEventListener("error", () => {
        tile.querySelector(".tile-media").innerHTML =
          `<div class="tile-broken">${icon("alert-triangle")}<span>${t("zone.preview_unavailable")}</span></div>`;
      });
      img.addEventListener("click", () => openLightbox(img.src, tile.querySelector(".tile-title").textContent.trim()));
    }
    const video = tile.querySelector("video");
    if (video) {
      video.addEventListener("loadedmetadata", () => {
        fitTileToMedia(tile, video.videoWidth, video.videoHeight);
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
  const target = games.find(g => g.index === currentIndex);
  const session = window.__gmeSession;
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
    if (session !== window.__gmeSession) return;
    const g = games.find(x => x.path === target.path);
    stampMedia([data.path]);
    if (g) {
      g[field] = data.path;
      if (currentIndex === g.index) renderZones(g);
    }
    renderList(document.getElementById("search").value);
    toast(t("toast.upload_ok", { field: fieldLabel(field), filename: data.filename }));
    setStatus(t("status.saved"));
  } catch (e) {
    handleError(e);
  }
}

async function clearField(field) {
  const target = games.find(g => g.index === currentIndex);
  const session = window.__gmeSession;
  // Detach media tag in XML only (file kept on disk)
  const choice = await askConfirm({
    title: t("confirm.clear_field_title", { field: fieldLabel(field) }),
    bodyHtml: t("confirm.clear_field_body"),
    showBackup: false,
    okLabel: t("zone.clear_title"),
  });
  if (!choice.confirmed) return;
  if (!target || session !== window.__gmeSession) return;
  try {
    await apiFetch(`/api/clear/${target.index}/${field}?path=${encodeURIComponent(target.path)}`, { method: "POST" });
    if (session !== window.__gmeSession) return;
    const g = games.find(x => x.path === target.path);
    if (g) {
      g[field] = "";
      if (currentIndex === g.index) renderZones(g);
    }
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
document.getElementById("genre-filter").addEventListener("change", e => {
  genreFilter = e.target.value || "all";
  listEls().list.scrollTop = 0;
  renderList();
});
document.getElementById("flag-filter").addEventListener("change", e => {
  flagFilter = FLAG_FILTERS.includes(e.target.value) ? e.target.value : "all";
  listEls().list.scrollTop = 0;
  renderList();
});
document.getElementById("btn-search-all").addEventListener("click", async () => {
  const on = !SETTINGS.search_all_fields;
  SETTINGS.search_all_fields = on;             // at once: the list follows the button
  updateSearchModeUi();
  renderList();
  await saveSettings({ search_all_fields: on });
  updateSearchModeUi();
});
(() => {
  const list = document.getElementById("game-list");
  list.addEventListener("click", e => {
    const row = e.target.closest(".game-item");
    if (!row) return;
    const listIndex = parseInt(row.dataset.listIndex, 10);
    // The box, Ctrl+click or Shift+click tick games for the batch scrape; a plain click opens
    if (e.target.closest(".gi-select") || e.ctrlKey || e.metaKey || e.shiftKey) {
      e.preventDefault();
      if (e.shiftKey && selectionAnchor) selectRange(listIndex);
      else toggleTicked(games[listIndex]);
      selectionChanged();
      return;
    }
    requestSelectGame(listIndex);
  });
  list.addEventListener("scroll", onListScroll, { passive: true });
  // Broken or missing thumbnail: show the placeholder icon instead
  list.addEventListener("error", e => {
    if (e.target.tagName === "IMG") e.target.outerHTML = icon("device-gamepad-2");
  }, true);
  if (window.ResizeObserver) new ResizeObserver(() => renderListWindow(false)).observe(list);
})();

/* --- Width of the game list ---------------------------------------------------
 * Drag the handle on the right edge of the list (mouse, pen or touch) to show
 * long names; the stage and its media tiles shrink while dragging (style.css,
 * .main). Keyboard: focus the handle, arrows (Shift: bigger steps), Home / End
 * for the narrowest / widest, Escape cancels a drag. A double-click goes back to
 * the default width. Saved in ui_settings.json when the drag ends.
 */
const LIST_WIDTH_MIN = 260;       // px, = --w-list-min in style.css
const LIST_CONTENT_MIN = 600;     // px left to the editor, = --w-content-min in style.css
const LIST_KEY_STEP = 16;
(function wireListResizer() {
  const main = document.getElementById("main");
  const sidebar = document.getElementById("sidebar");
  const handle = document.getElementById("list-resizer");
  if (!main || !sidebar || !handle) return;
  const maxWidth = () => Math.max(LIST_WIDTH_MIN, main.clientWidth - LIST_CONTENT_MIN);
  const clampWidth = w => Math.round(Math.min(maxWidth(), Math.max(LIST_WIDTH_MIN, w)));
  const shownWidth = () => Math.round(sidebar.getBoundingClientRect().width);
  let frame = 0, pending;          // one style change per frame while dragging
  let saveTimer = 0;
  let drag = null;

  function updateAria() {
    handle.setAttribute("aria-valuemin", LIST_WIDTH_MIN);
    handle.setAttribute("aria-valuemax", maxWidth());
    handle.setAttribute("aria-valuenow", shownWidth());
  }
  /** `w` in px, or null for the default width. */
  function apply(w) {
    pending = w;
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (pending === null) main.style.removeProperty("--w-list");
      else main.style.setProperty("--w-list", pending + "px");
      updateAria();
    });
  }
  /** The width about to be drawn (a key held down repeats faster than frames). */
  const targetWidth = () => (frame && pending !== null ? pending : shownWidth());
  function save(w, delay = 0) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      if (SETTINGS.list_width !== w) saveSettings({ list_width: w });
    }, delay);
  }
  function stopDrag(cancel) {
    const d = drag;
    drag = null;
    handle.classList.remove("is-dragging");
    document.body.classList.remove("is-resizing-list");
    if (handle.hasPointerCapture(d.id)) handle.releasePointerCapture(d.id);
    if (cancel) apply(d.before);
    else if (d.width !== undefined && d.width !== d.start) save(d.width);
  }

  handle.addEventListener("pointerdown", e => {
    if (e.button !== 0 || drag) return;
    e.preventDefault();                                     // no text selection, no focus ring
    handle.setPointerCapture(e.pointerId);
    const start = shownWidth();
    drag = { id: e.pointerId, x: e.clientX, start, before: main.style.getPropertyValue("--w-list") ? start : null };
    handle.classList.add("is-dragging");
    document.body.classList.add("is-resizing-list");
  });
  handle.addEventListener("pointermove", e => {
    if (!drag || e.pointerId !== drag.id) return;
    drag.width = clampWidth(drag.start + e.clientX - drag.x);
    apply(drag.width);
  });
  handle.addEventListener("pointerup", e => { if (drag && e.pointerId === drag.id) stopDrag(false); });
  handle.addEventListener("pointercancel", e => { if (drag && e.pointerId === drag.id) stopDrag(true); });
  handle.addEventListener("lostpointercapture", e => { if (drag && e.pointerId === drag.id) stopDrag(false); });
  document.addEventListener("keydown", e => {
    if (drag && e.key === "Escape") {
      e.preventDefault();
      e.stopImmediatePropagation();
      stopDrag(true);
    }
  }, true);
  handle.addEventListener("dblclick", () => {
    apply(null);
    save(null);
  });
  handle.addEventListener("keydown", e => {
    const step = e.shiftKey ? LIST_KEY_STEP * 4 : LIST_KEY_STEP;
    let w;
    if (e.key === "ArrowRight") w = targetWidth() + step;
    else if (e.key === "ArrowLeft") w = targetWidth() - step;
    else if (e.key === "Home") w = LIST_WIDTH_MIN;
    else if (e.key === "End") w = maxWidth();
    else return;
    e.preventDefault();
    e.stopPropagation();                                    // not the list shortcuts
    w = clampWidth(w);
    apply(w);
    save(w, 400);
  });
  window.addEventListener("resize", updateAria);
  updateAria();
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
  const backupsModal = document.getElementById("backups-modal");
  const confirmModal = document.getElementById("confirm-modal");
  if (backupsModal && backupsModal.classList.contains("open") &&
      !(confirmModal && confirmModal.classList.contains("open"))) {
    if (e.key === "Escape") { e.preventDefault(); closeBackups(); }
    return;
  }
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

  // Escape closes the scrape dialog
  const ssModal = document.getElementById("ss-modal");
  if (ssModal && ssModal.classList.contains("open")) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeSsModal();
    } else if (e.key === "Enter" && !(e.target.closest && e.target.closest("button"))) {
      // Enter on a ticked card or row applies, as on the Apply button
      const apply = document.getElementById("ss-modal-apply");
      if (!apply.hidden && !apply.disabled) {
        e.preventDefault();
        applyScrape();
      }
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
  const batchModal = document.getElementById("batch-modal");
  if (batchModal && batchModal.classList.contains("open")) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeBatch();               // not while running: Stop does that
    }
    return;
  }
  const checkModal = document.getElementById("check-modal");
  if (checkModal && checkModal.classList.contains("open")) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeCheck();
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
    if (key === "x" && !e.repeat && currentListIndex !== null) {
      e.preventDefault();
      toggleTicked(games[currentListIndex]);
      selectionChanged();
      return;
    }
    if (key === "Escape" && selection.size) {
      e.preventDefault();
      clearSelection();
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
/* --- Dialogs: Tab stays inside the open one -----------------------------------
 * The page behind a dialog cannot be reached with the keyboard. The confirm
 * dialog can open above another one, so it is looked at first. */
const DIALOG_IDS = ["confirm-modal", "media-lightbox", "ss-modal", "batch-modal", "check-modal", "backups-modal", "open-gamelist-modal",
  "settings-modal", "about-modal"];
function topDialog() {
  for (const id of DIALOG_IDS) {
    const el = document.getElementById(id);
    if (el && el.classList.contains("open")) return el;
  }
  return null;
}
document.addEventListener("keydown", e => {
  if (e.key !== "Tab") return;
  const dialog = topDialog();
  if (!dialog) return;
  const items = [...dialog.querySelectorAll("button, [href], input, select, textarea, [tabindex]")]
    .filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length && !el.closest("[hidden]"));
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1];
  const active = document.activeElement;
  if (!dialog.contains(active)) {
    e.preventDefault();
    (e.shiftKey ? last : first).focus();
  } else if (!e.shiftKey && active === last) {
    e.preventDefault();
    first.focus();
  } else if (e.shiftKey && active === first) {
    e.preventDefault();
    last.focus();
  }
}, true);

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
    // Enter on a button presses that button (the browser does it). Elsewhere
    // it confirms, except in a dialog that deletes: there, a click is needed.
    const danger = okClass === "btn-danger";
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      } else if (e.key === "Enter" && !(e.target.closest && e.target.closest("button"))) {
        e.preventDefault();
        if (!danger) onOk();
      }
    };
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    extraBtn.addEventListener("click", onExtra);
    overlay.addEventListener("click", onOverlay);
    document.addEventListener("keydown", onKey);
    (danger ? cancelBtn : okBtn).focus();
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
const SETTINGS_PANES = ["general", "ss", "sources", "required", "keys"];

function openSettings(pane) {
  closeMenu(null, false);
  wireLanguageControls();
  loadSsConfig();
  renderScrapeSources();
  renderRequiredMedia();
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
  const folders = folder === "*" ? Object.keys(scraperPrefs()) : [folder];
  folders.forEach(f => delete SETTINGS.scrapers[f]);
  updateScrapeButton();
  saveSettings({ scrapers: Object.fromEntries(folders.map(f => [f, null])) });
  renderScrapeSources();
  const first = document.querySelector("#sources-list button") || document.getElementById("tab-sources");
  first.focus();
});

/** Settings › Required media: ticks for the open system, and the other systems changed. */
function renderRequiredMedia() {
  const box = document.getElementById("required-box");
  const folder = currentSystem && currentSystem.folder;
  if (!folder) {
    box.innerHTML = `<p class="sources-empty">${escapeHtml(t("settings.required_no_system"))}</p>`;
    return;
  }
  const custom = customRequired(folder);
  const required = requiredKeys();
  const system = currentSystem.label || folder;
  let html = `<div class="required-head"><span>${escapeHtml(t("settings.required_for", { system }))}</span>` +
    `<span class="required-state">${escapeHtml(t(custom ? "settings.required_custom" : "settings.required_default"))}</span>` +
    (custom ? `<button type="button" class="btn btn-sm btn-ghost" data-required-reset="${escapeHtml(folder)}">${escapeHtml(t("settings.required_reset"))}</button>` : "") +
    `</div><div class="required-grid">` +
    getFields().map(f => `<label class="required-item"><input type="checkbox" data-required="${f.key}"` +
      `${required.includes(f.key) ? " checked" : ""} />${icon(f.icon)}<span>${escapeHtml(f.label)}</span></label>`).join("") +
    `</div>`;
  const others = Object.keys(SETTINGS.required_media || {}).filter(f => f !== folder).sort();
  if (others.length) {
    html += `<p class="required-others-title">${escapeHtml(t("settings.required_others"))}</p>` +
      others.map(f => `<div class="source-row"><code class="source-folder">${escapeHtml(f)}</code>` +
        `<span class="required-list">${escapeHtml(customRequired(f).map(fieldLabel).join(", ") || "–")}</span>` +
        `<button type="button" class="btn btn-sm btn-ghost" data-required-reset="${escapeHtml(f)}">` +
        `${escapeHtml(t("settings.required_reset"))}</button></div>`).join("");
  }
  box.innerHTML = html;
}
/** The list, the open game and the filter follow the new required media. */
function requiredMediaChanged() {
  renderList();
  const g = games.find(x => x.index === currentIndex);
  if (g) renderZones(g);
  renderRequiredMedia();
}
document.getElementById("required-box").addEventListener("change", async e => {
  if (!e.target.dataset.required) return;
  const folder = currentSystem && currentSystem.folder;
  if (!folder) return;
  const ticked = [...document.querySelectorAll("#required-box [data-required]:checked")].map(cb => cb.dataset.required);
  const def = defaultRequired();
  const same = ticked.length === def.length && def.every(k => ticked.includes(k));
  const focusKey = e.target.dataset.required;
  await saveSettings({ required_media: { [folder]: same ? null : ticked } });
  requiredMediaChanged();
  const again = document.querySelector(`#required-box [data-required="${focusKey}"]`);
  if (again) again.focus();
});
document.getElementById("required-box").addEventListener("click", async e => {
  const btn = e.target.closest("[data-required-reset]");
  if (!btn) return;
  await saveSettings({ required_media: { [btn.dataset.requiredReset]: null } });
  requiredMediaChanged();
  document.getElementById("tab-required").focus();
});
document.getElementById("btn-required-media").addEventListener("click", () => openSettings("required"));

/* --- Actions on the whole gamelist (app bar ⋯ menu) ----------------------- */
setupMenu("actions-menu", "btn-actions");
function setGamelistActionsEnabled(on) {
  ["btn-batch-scrape", "btn-manual-backup", "btn-backup-history", "btn-fill-arcade", "btn-rom-check", "btn-media-check", "btn-purge-regions"].forEach(id => {
    document.getElementById(id).disabled = !on;
  });
}

/* --- Checks (Actions › Check ROMs, Check media) ----------------------------
 * One report dialog for both: counters, sections of ticked rows, apply,
 * export. Each check is described in CHECKS; the server re-scans before
 * acting (gme/romcheck.py, gme/mediacheck.py). Long lists show their first
 * rows, the others follow the section's box.
 */
const CHECK_MAX_ROWS = 400;
const CHECK_IMAGE_EXTS = /\.(png|jpe?g|gif|webp|bmp)$/i;
let check = null;          // { def, report, sections, selected: { kind: Set } }

function fmtSize(bytes) {
  if (bytes == null) return "";
  const units = t("romcheck.size_units").split(",");
  let v = bytes, u = 0;
  while (v >= 1024 && u < units.length - 1) { v /= 1024; u++; }
  return (u ? v.toLocaleString(currentLocale || "fr", { maximumFractionDigits: 1 }) : v) + " " + units[u];
}
function fmtCount(n) {
  return Number(n).toLocaleString(currentLocale || "fr");
}
/** More than half missing: probably the wrong folder or a drive missing. */
function mostlyMissing(n, total, min) {
  return n > min && n > total / 2;
}

const CHECKS = {
  roms: {
    title: "romcheck.title",
    url: "/api/check-roms",
    applyUrl: "/api/check-roms/apply",
    options: [{ id: "backup", label: "romcheck.backup", on: true }],
    stats: r => [
      [t("romcheck.stat_games"), fmtCount(r.games)],
      [t("romcheck.stat_roms"), fmtCount(r.roms)],
      [t("romcheck.stat_unlisted"), fmtCount(r.unlisted.length), r.unlisted.length],
      [t("romcheck.stat_missing"), fmtCount(r.missing.length), r.missing.length],
      [t("romcheck.stat_duplicates"), fmtCount(r.duplicates.length), r.duplicates.length],
    ],
    allGood: "romcheck.all_good",
    sections: r => {
      const suspicious = mostlyMissing(r.missing.length, r.games, 5);
      return [
        { kind: "add", title: t("romcheck.unlisted_title"), desc: t("romcheck.unlisted_desc"), on: true,
          rows: r.unlisted.map(u => ({ key: u.path, name: u.name, path: u.path, meta: fmtSize(u.size) })) },
        { kind: "remove", title: t("romcheck.missing_title"), desc: t("romcheck.missing_desc"), on: !suspicious,
          warning: suspicious ? t("romcheck.missing_warning") : "",
          option: { id: "delete-media", label: t("romcheck.delete_media") },
          rows: r.missing.map(m => ({ key: m.path, name: m.name, path: m.path,
            meta: m.media ? t("romcheck.media_n", { n: m.media }) : "" })) },
        { kind: "merge", title: t("romcheck.duplicates_title"), desc: t("romcheck.duplicates_desc"), on: true,
          rows: r.duplicates.map(d => ({ key: d.path, name: d.entries.map(e => e.name || "—").join(" · "),
            path: d.path, meta: t("romcheck.copies_n", { n: d.entries.length }) })) },
      ];
    },
    notes: r => [r.non_file ? t("romcheck.non_file", { n: r.non_file }) : "", r.arcade ? t("romcheck.arcade_note") : ""],
    body: (sel, opt) => ({ add: [...sel.add], remove: [...sel.remove], merge: [...sel.merge],
      backup: opt.backup, delete_media: opt["delete-media"] }),
    done: d => t("romcheck.done", { added: d.added, removed: d.removed, merged: d.merged }) +
      (d.backup ? t("toast.purge_bak") : ""),
    applyLabel: ["romcheck.apply", "romcheck.apply_n"],
    exportName: "rom-check",
  },
  media: {
    title: "mediacheck.title",
    url: "/api/check-media",
    applyUrl: "/api/check-media/apply",
    options: [
      { id: "trash", label: "mediacheck.trash", on: true },
      { id: "backup", label: "romcheck.backup", on: true },
    ],
    stats: r => [
      [t("romcheck.stat_games"), fmtCount(r.games)],
      [t("mediacheck.stat_files"), fmtCount(r.files)],
      [t("mediacheck.stat_orphans"), fmtCount(r.orphans.length), r.orphans.length],
      [t("mediacheck.stat_size"), fmtSize(r.orphan_bytes), r.orphan_bytes],
      [t("mediacheck.stat_broken"), fmtCount(r.broken.length), r.broken.length],
    ],
    allGood: "mediacheck.all_good",
    sections: r => {
      const suspicious = mostlyMissing(r.orphans.length, r.files, 20);
      return [
        { kind: "delete", title: t("mediacheck.orphans_title"),
          desc: t("mediacheck.orphans_desc", { folders: (r.folders || []).join(", ") || "—" }), on: !suspicious,
          warning: suspicious ? t("mediacheck.orphans_warning") : "",
          rows: r.orphans.map(o => ({ key: o.path, name: o.path.split("/").pop(), path: o.path, meta: fmtSize(o.size),
            thumb: CHECK_IMAGE_EXTS.test(o.path) ? o.path : "" })) },
        { kind: "unlink", title: t("mediacheck.broken_title"), desc: t("mediacheck.broken_desc"), on: true,
          rows: r.broken.map(b => ({ key: b.path + "\u0001" + b.tag, name: b.name || b.path, path: b.value,
            meta: fieldLabel(b.tag) })) },
      ];
    },
    notes: () => [],
    body: (sel, opt) => ({
      delete: [...sel.delete],
      unlink: [...sel.unlink].map(k => { const [path, tag] = k.split("\u0001"); return { path, tag }; }),
      trash: opt.trash, backup: opt.backup,
    }),
    done: d => {
      let msg = t("mediacheck.done", { deleted: d.deleted, size: fmtSize(d.freed), unlinked: d.unlinked });
      if (d.deleted && d.trash) msg += t("mediacheck.done_trash");
      if (d.failed && d.failed.length) msg += t("mediacheck.done_failed", { n: d.failed.length });
      return msg;
    },
    applyLabel: ["mediacheck.apply", "mediacheck.apply_n"],
    exportName: "media-check",
  },
};

async function openCheck(id) {
  closeMenu(null, false);
  if (!(await confirmLeaveEditor())) return;
  const def = CHECKS[id];
  check = { def, report: null, sections: [], selected: {} };
  document.getElementById("check-title").innerHTML =
    icon(id === "roms" ? "list-details" : "photo") + `<span>${escapeHtml(t(def.title))}</span>`;
  document.getElementById("check-intro").textContent = t("romcheck.scanning");
  document.getElementById("check-stats").innerHTML = "";
  document.getElementById("check-body").innerHTML = "";
  document.getElementById("check-options").innerHTML = def.options.map(o =>
    `<label class="check-option"><input type="checkbox" data-check-option="${o.id}"${o.on ? " checked" : ""} />` +
    `<span>${escapeHtml(t(o.label))}</span></label>`).join("");
  document.getElementById("check-apply").disabled = true;
  document.getElementById("check-modal").classList.add("open");
  setStatus(t("romcheck.scanning"));
  try {
    setCheckReport(await apiFetch(def.url));
    setStatus(t("status.done"));
  } catch (e) {
    closeCheck();
    handleError(e);
  }
}
function closeCheck() {
  const modal = document.getElementById("check-modal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  check = null;
  document.getElementById("btn-actions").focus();
}

function setCheckReport(report) {
  check.report = report;
  check.sections = check.def.sections(report);
  check.selected = {};
  check.sections.forEach(s => { check.selected[s.kind] = new Set(s.on ? s.rows.map(r => r.key) : []); });
  renderCheck();
}

function renderCheck() {
  const { def, report: r, sections } = check;
  document.getElementById("check-intro").innerHTML =
    escapeHtml(t("romcheck.intro")) + ` <code>${escapeHtml(r.base_dir)}</code>`;
  document.getElementById("check-stats").innerHTML = def.stats(r).map(([label, value, issues]) =>
    `<div class="rc-stat${issues === undefined ? "" : issues ? " is-warn" : " is-ok"}">` +
    `<span class="rc-stat-n">${escapeHtml(String(value))}</span><span class="rc-stat-label">${escapeHtml(label)}</span></div>`).join("");
  let html = "";
  if (sections.every(s => !s.rows.length)) {
    html += `<div class="rc-all-good">${icon("circle-check")}<p>${escapeHtml(t(def.allGood))}</p></div>`;
  }
  html += sections.map(checkSectionHtml).join("");
  html += def.notes(r).filter(Boolean).map(n => `<p class="rc-note">${escapeHtml(n)}</p>`).join("");
  document.getElementById("check-body").innerHTML = html;
  updateCheckSelection();
}

function checkSectionHtml(s) {
  if (!s.rows.length) return "";
  const shown = s.rows.slice(0, CHECK_MAX_ROWS);
  const sel = check.selected[s.kind];
  let extra = "";
  if (s.warning) extra += `<p class="rc-warning">${icon("alert-triangle")}<span>${escapeHtml(s.warning)}</span></p>`;
  if (s.option) {
    extra += `<label class="rc-option"><input type="checkbox" data-check-option="${s.option.id}" />` +
      `<span>${escapeHtml(s.option.label)}</span></label>`;
  }
  return `<section class="rc-section" data-kind="${s.kind}">` +
    `<label class="rc-head"><input type="checkbox" data-rc-all="${s.kind}" />` +
    `<span class="rc-title">${escapeHtml(s.title)}</span><span class="rc-count">${fmtCount(s.rows.length)}</span></label>` +
    `<p class="rc-desc">${escapeHtml(s.desc)}</p>${extra}` +
    `<div class="rc-list">` + shown.map(row =>
      `<label class="rc-row${row.thumb !== undefined ? " has-thumb" : ""}">` +
      `<input type="checkbox" data-rc="${s.kind}" value="${escapeHtml(row.key)}"${sel.has(row.key) ? " checked" : ""} />` +
      (row.thumb !== undefined
        ? `<span class="rc-thumb">${row.thumb
          ? `<img src="${thumbUrl(row.thumb)}" alt="" loading="lazy" decoding="async" />`
          : icon(/\.pdf$/i.test(row.path) ? "file-text" : "movie")}</span>` : "") +
      `<span class="rc-name">${escapeHtml(row.name)}</span><code class="rc-path" title="${escapeHtml(row.path)}">${escapeHtml(row.path)}</code>` +
      `<span class="rc-meta">${escapeHtml(row.meta || "")}</span></label>`).join("") +
    (s.rows.length > shown.length
      ? `<p class="rc-more">${escapeHtml(t("romcheck.more", { n: fmtCount(s.rows.length - shown.length) }))}</p>` : "") +
    `</div></section>`;
}

function checkOptions() {
  const opt = {};
  document.querySelectorAll("#check-modal [data-check-option]").forEach(cb => { opt[cb.dataset.checkOption] = cb.checked; });
  return opt;
}
function updateCheckSelection() {
  let total = 0;
  check.sections.forEach(s => {
    const n = check.selected[s.kind].size;
    total += n;
    const all = document.querySelector(`[data-rc-all="${s.kind}"]`);
    if (!all) return;
    all.checked = n > 0 && n === s.rows.length;
    all.indeterminate = n > 0 && n < s.rows.length;
  });
  document.getElementById("check-apply").disabled = !total;
  const [label, labelN] = check.def.applyLabel;
  document.getElementById("check-apply-label").textContent = total ? t(labelN, { n: fmtCount(total) }) : t(label);
}
document.getElementById("check-body").addEventListener("change", e => {
  if (!check) return;
  const all = e.target.dataset && e.target.dataset.rcAll;
  if (all) {
    const section = check.sections.find(s => s.kind === all);
    check.selected[all] = new Set(e.target.checked ? section.rows.map(r => r.key) : []);
    document.querySelectorAll(`[data-rc="${all}"]`).forEach(cb => { cb.checked = e.target.checked; });
  } else if (e.target.dataset && e.target.dataset.rc) {
    const set = check.selected[e.target.dataset.rc];
    if (e.target.checked) set.add(e.target.value);
    else set.delete(e.target.value);
  }
  updateCheckSelection();
});

async function applyCheck() {
  if (!check) return;
  const def = check.def;
  document.getElementById("check-apply").disabled = true;
  setStatus(t("romcheck.applying"));
  try {
    const data = await apiFetch(def.applyUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(def.body(check.selected, checkOptions())),
    });
    toast(def.done(data), data.failed && data.failed.length ? "warning" : "success");
    await loadGames();
    if (check && check.def === def) setCheckReport(data.report);
    setStatus(t("status.done"));
  } catch (e) {
    handleError(e);
    if (check) updateCheckSelection();
  }
}

/** Plain-text report, saved as a file (Downloads folder). */
function exportCheck() {
  if (!check) return;
  const { def, report: r, sections } = check;
  const lines = [
    t(def.title) + " — Gamelist Media Editor",
    labelValue(t("romcheck.report_gamelist"), window.__gmeXmlPath || r.base_dir),
    labelValue(t("romcheck.report_date"), new Date().toLocaleString(currentLocale || "fr")),
    def.stats(r).map(([label, value]) => labelValue(label, value)).join(" · "),
    "",
  ];
  sections.forEach(s => {
    lines.push(`${s.title} (${s.rows.length})`);
    s.rows.forEach(row => lines.push(`  ${row.path}` + (row.name && row.name !== row.path ? `  —  ${row.name}` : "") +
      (row.meta ? `  (${row.meta})` : "")));
    lines.push("");
  });
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  const system = (currentSystem && currentSystem.folder) || "gamelist";
  a.href = URL.createObjectURL(blob);
  a.download = `${def.exportName}-${system}-${new Date().toISOString().slice(0, 10)}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

document.getElementById("btn-rom-check").addEventListener("click", () => openCheck("roms"));
document.getElementById("btn-media-check").addEventListener("click", () => openCheck("media"));
document.getElementById("check-close").addEventListener("click", closeCheck);
document.getElementById("check-cancel").addEventListener("click", closeCheck);
document.getElementById("check-apply").addEventListener("click", applyCheck);
document.getElementById("check-export").addEventListener("click", exportCheck);
document.getElementById("check-modal").addEventListener("click", e => {
  if (e.target.id === "check-modal") closeCheck();
});

/* --- Batch scrape (Actions › Scrape in batch, or the selection bar) ----------
 * The ticked games, else the games shown in the list, one after the other with
 * the source of the system: the same scrape and apply routes as one game, with
 * the fields computed from the comparison (missing only, or replace too).
 * A game the source does not recognise surely (several candidates) is skipped
 * and listed; quota or a stopped server ends the run. Nothing runs in the
 * background: closing the window stops it.
 */
const BATCH_MEDIA = ["image", "thumbnail", "marquee", "boxart", "boxback", "cartridge", "fanart", "mix", "map",
  "bezel", "video", "manual", "pad2key"];
const BATCH_INFO = ["desc", "genre", "rating", "releasedate", "developer", "publisher", "players", "lang", "region",
  "family", "arcadesystemname", "name"];
const batchPrefs = { mode: "missing", off: new Set(["name", "pad2key"]) };   // kept for the session
let batch = null;   // { phase, source, targets, i, stop, halted, results }
let savedBatch = null;

async function refreshSavedBatch() {
  const session = window.__gmeSession;
  try {
    const data = await apiFetch("/api/batch");
    if (session !== window.__gmeSession) return;
    savedBatch = data.job;
    const entry = document.getElementById("saved-batch-entry");
    entry.hidden = !savedBatch;
    if (savedBatch) entry.textContent = t("batch.saved", { done: fmtCount(savedBatch.i), total: fmtCount(savedBatch.targets.length) });
  } catch (_) { /* The next explicit open retries and displays any error. */ }
}

function savedBatchView(job) {
  return { ...job, phase: "done", session: window.__gmeSession,
    stop: job.i < job.targets.length && !job.halted };
}

function batchTargets() {
  if (selection.size) return games.filter(g => selection.has(g.path));
  return viewIndices.map(i => games[i]);
}

/** Arcade Database and Steam have no error code for "come back later": their messages tell. */
function isQuotaMessage(msg) {
  const low = String(msg || "").toLowerCase();
  return ["quota", "thread", "429", "503", "trop de requ", "too many", "maintenance", "satur", "limit"]
    .some(k => low.includes(k));
}

async function openBatch(forceNew = false) {
  closeMenu(null, false);
  if (!(await confirmLeaveEditor())) return;
  if (!forceNew) {
    await refreshSavedBatch();
    if (savedBatch) {
      batch = savedBatchView(savedBatch);
      renderBatch();
      document.getElementById("batch-modal").classList.add("open");
      document.getElementById(batch.i < batch.targets.length ? "batch-resume" : "batch-cancel").focus();
      return;
    }
  }
  const targets = batchTargets().map(g => ({ index: g.index, path: g.path, name: g.name }));
  if (!targets.length) {
    toast(t("batch.no_games"), "info");
    return;
  }
  batch = { phase: "setup", source: chosenScraper(), targets, session: window.__gmeSession,
    xmlPath: window.__gmeXmlPath, fromSelection: selection.size > 0, i: 0, stop: false,
    halted: "", results: { updated: [], nothing: [], uncertain: [], errors: [] } };
  renderBatch();
  document.getElementById("batch-modal").classList.add("open");
  document.getElementById("batch-start").focus();
}

function closeBatch() {
  if (!batch || batch.phase === "running") return;
  document.getElementById("batch-modal").classList.remove("open");
  batch = null;
}

function batchFieldsHtml(title, keys) {
  return `<section class="batch-group"><h4 class="ss-section-title">${escapeHtml(title)}</h4><div class="required-grid">` +
    keys.map(k => `<label class="required-item"><input type="checkbox" data-batch-field="${k}"` +
      `${batchPrefs.off.has(k) ? "" : " checked"} />${icon(SCRAPE_MEDIA_ICONS[k] || "list-details")}` +
      `<span>${escapeHtml(scrapeFieldLabel(k))}</span></label>`).join("") + `</div></section>`;
}

function renderBatch() {
  const b = batch;
  const sc = SCRAPERS[b.source];
  const system = (currentSystem && (currentSystem.label || currentSystem.folder)) || "—";
  document.getElementById("batch-title").innerHTML = icon(sc.icon) + `<span>${escapeHtml(t("batch.title"))}</span>`;
  document.getElementById("batch-intro").textContent = t(b.fromSelection ? "batch.intro_selection" : "batch.intro_list",
    { n: fmtCount(b.targets.length), source: sc.label, system });
  const body = document.getElementById("batch-body");
  const start = document.getElementById("batch-start");
  const cancel = document.getElementById("batch-cancel");
  const options = document.getElementById("batch-options");
  document.getElementById("batch-close").hidden = b.phase === "running";
  document.getElementById("batch-export").hidden = b.phase !== "done";
  document.getElementById("batch-new").hidden = b.phase !== "done";
  document.getElementById("batch-resume").hidden = !b.id || b.phase !== "done" || b.i >= b.targets.length;
  document.getElementById("batch-retry").hidden = b.phase !== "done" ||
    b.i < b.targets.length ||
    !(b.results.errors.length || b.results.updated.some(g => g.warnings.length));
  if (b.phase === "setup") {
    body.innerHTML =
      `<div class="ss-toolbar"><div class="segmented" role="group" aria-label="${escapeHtml(t("scrape.selection"))}">` +
      ["missing", "all"].map(m => `<button type="button" class="seg" data-batch-mode="${m}" aria-pressed="${batchPrefs.mode === m}">` +
        `<span>${escapeHtml(t(m === "missing" ? "scrape.preset_missing" : "scrape.preset_all"))}</span></button>`).join("") +
      `</div><span class="ss-count">${escapeHtml(t(batchPrefs.mode === "missing" ? "batch.mode_missing" : "batch.mode_all"))}</span></div>` +
      batchFieldsHtml(t("scrape.section_media"), BATCH_MEDIA) +
      batchFieldsHtml(t("scrape.section_info"), BATCH_INFO);
    options.innerHTML = `<label class="check-option"><input type="checkbox" id="batch-backup" checked />` +
      `<span>${escapeHtml(t("romcheck.backup"))}</span></label>`;
    cancel.textContent = t("confirm.cancel");
    start.hidden = false;
    document.getElementById("batch-start-label").textContent = t("batch.start", { n: fmtCount(b.targets.length) });
    updateBatchStart();
    return;
  }
  options.innerHTML = "";
  start.hidden = true;
  cancel.textContent = t(b.phase === "running" ? (b.stop ? "batch.stopping" : "batch.stop") : "tools.close");
  cancel.disabled = b.phase === "running" && b.stop;
  const r = b.results;
  const done = r.updated.length + r.nothing.length + r.uncertain.length + r.errors.length;
  const partial = r.updated.filter(g => g.warnings.length).length;
  const complete = r.updated.length - partial;
  const stats = [
    [t("batch.stat_updated"), complete, complete ? "is-ok" : ""],
    ...(partial ? [[t("batch.partial"), partial, "is-warn"]] : []),
    [t("batch.stat_nothing"), r.nothing.length, ""],
    [t("batch.stat_uncertain"), r.uncertain.length, r.uncertain.length ? "is-warn" : ""],
    [t("batch.stat_errors"), r.errors.length, r.errors.length ? "is-warn" : ""],
  ];
  let html = `<div class="batch-progress"><div class="batch-bar"><span style="width:${Math.round(done / b.targets.length * 100)}%"></span></div>` +
    `<span class="batch-now">${escapeHtml(b.phase === "running"
      ? t("batch.progress", { done: fmtCount(done), total: fmtCount(b.targets.length), name: (b.targets[b.i] || {}).name || "" })
      : t(b.halted ? "batch.halted" : b.stop ? "batch.stopped" : "batch.finished", { done: fmtCount(done), total: fmtCount(b.targets.length), reason: b.halted }))}</span></div>` +
    batchThreadsHtml(b) +
    `<div class="check-stats batch-stats">` + stats.map(([label, n, cls]) =>
      `<div class="rc-stat ${cls}"><span class="rc-stat-n">${fmtCount(n)}</span><span class="rc-stat-label">${escapeHtml(label)}</span></div>`).join("") + `</div>`;
  if (b.phase === "done") {
    const list = (title, desc, rows, rowHtml) => rows.length
      ? `<section class="rc-section"><div class="rc-head"><span class="rc-title">${escapeHtml(title)}</span><span class="rc-count">${fmtCount(rows.length)}</span></div>` +
        `<p class="rc-desc">${escapeHtml(desc)}</p><div class="rc-list">${rows.map(rowHtml).join("")}</div></section>` : "";
    html += list(t("batch.uncertain_title"), t("batch.uncertain_desc"), r.uncertain, g =>
      `<div class="batch-row"><span class="rc-name">${escapeHtml(g.name)}</span><code class="rc-path">${escapeHtml(g.path)}</code>` +
      `<button type="button" class="btn btn-sm" data-batch-pick="${escapeHtml(g.path)}">${escapeHtml(t("batch.pick"))}</button></div>`);
    html += list(t("batch.errors_title"), t("batch.errors_desc"), r.errors, g =>
      `<div class="batch-row"><span class="rc-name">${escapeHtml(g.name)}</span><span class="batch-msg" title="${escapeHtml(g.message)}">${escapeHtml(g.message)}</span>` +
      `<button type="button" class="btn btn-sm btn-ghost" data-batch-open="${escapeHtml(g.path)}">${escapeHtml(t("batch.open"))}</button></div>`);
    html += list(t("batch.updated_title"), t("batch.updated_desc"), r.updated, g =>
      `<div class="batch-row"><span class="rc-name">${escapeHtml(g.name)}</span><div class="batch-detail">` +
      `<span class="batch-msg">${escapeHtml(g.fields.map(scrapeFieldLabel).join(", "))}</span>` +
      (g.warnings.length ? `<strong class="batch-warning">${escapeHtml(t("batch.partial"))}</strong>` +
        `<ul class="batch-warning">${g.warnings.map(w => `<li>${escapeHtml(w)}</li>`).join("")}</ul>` : "") + `</div>` +
      `<button type="button" class="btn btn-sm btn-ghost" data-batch-open="${escapeHtml(g.path)}">${escapeHtml(t("batch.open"))}</button></div>`);
  }
  body.innerHTML = html;
}

/** ScreenScraper workers, thread limit and daily quota (from the last step) */
function batchThreadsHtml(b) {
  const th = b.phase === "running" && b.threads;
  if (!th) return "";
  const parts = [t("batch.threads", { active: Math.min(th.workers, th.limit), limit: th.limit })];
  if (th.per_day && th.today != null) parts.push(t("batch.quota_today", { used: fmtCount(th.today), max: fmtCount(th.per_day) }));
  let html = `<div class="batch-threads" id="batch-threads">${parts.map(p => `<span>${escapeHtml(p)}</span>`).join("")}</div>`;
  if (th.penalty) html += `<p class="batch-warning">${escapeHtml(t("batch.penalty"))}</p>`;
  return html;
}

function batchFields() {
  return [...document.querySelectorAll("#batch-body [data-batch-field]:checked")].map(cb => cb.dataset.batchField);
}
function updateBatchStart() {
  document.getElementById("batch-start").disabled = !batchFields().length;
}

document.getElementById("batch-body").addEventListener("change", e => {
  const key = e.target.dataset && e.target.dataset.batchField;
  if (!key) return;
  if (e.target.checked) batchPrefs.off.delete(key);
  else batchPrefs.off.add(key);
  updateBatchStart();
});

document.getElementById("batch-body").addEventListener("click", async e => {
  const mode = e.target.closest("[data-batch-mode]");
  if (mode && batch && batch.phase === "setup") {
    batchPrefs.mode = mode.dataset.batchMode;
    renderBatch();
    document.querySelector(`[data-batch-mode="${batchPrefs.mode}"]`).focus();
    return;
  }
  const pick = e.target.closest("[data-batch-pick], [data-batch-open]");
  if (!pick) return;
  // Open the game; for an uncertain one, its scrape shows the candidates to choose from
  const path = pick.dataset.batchPick || pick.dataset.batchOpen;
  const listIndex = games.findIndex(g => g.path === path);
  if (listIndex < 0) return;
  document.getElementById("batch-modal").classList.remove("open");
  await requestSelectGame(listIndex);
  if (pick.dataset.batchPick && games[listIndex] && currentIndex === games[listIndex].index) {
    runScrape(batch ? batch.source : chosenScraper());
  }
});

async function runBatch() {
  const b = batch;
  if (!b || b.phase !== "setup") return;
  const fields = batchFields();
  const mode = batchPrefs.mode;
  const backup = document.getElementById("batch-backup").checked;
  b.phase = "running";
  renderBatch();
  document.getElementById("batch-cancel").focus();
  try {
    const data = await apiFetch("/api/batch", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Gamelist-Session": b.session },
      body: JSON.stringify({ source: b.source, mode, fields, paths: b.targets.map(g => g.path), backup, fromSelection: b.fromSelection }),
    });
    Object.assign(b, data.job);
  } catch (e) {
    b.halted = e.message;
    handleError(e);
  }
  await advanceBatch(b);
}

async function resumeBatch(retry = false) {
  const b = batch;
  if (!b || b.phase !== "done") return;
  b.phase = "running";
  b.stop = false;
  renderBatch();
  try {
    const data = await apiFetch("/api/batch/claim", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Gamelist-Session": b.session },
      body: JSON.stringify({ id: b.id, retry }),
    });
    Object.assign(b, data.job);
  } catch (e) {
    b.halted = e.message;
    handleError(e);
  }
  await advanceBatch(b);
}

async function advanceBatch(b) {
  try {
    while (b.id && b.i < b.targets.length && !b.stop && !b.halted) {
      renderBatch();
      setStatus(t("batch.progress", { done: fmtCount(b.i), total: fmtCount(b.targets.length), name: b.targets[b.i].name }));
      const data = await apiFetch("/api/batch/step", {
        method: "POST", headers: { "Content-Type": "application/json", "X-Gamelist-Session": b.session },
        body: JSON.stringify({ id: b.id, owner: b.owner, i: b.i }),
      });
      if (data.threads) b.threads = data.threads;
      if (data.job) Object.assign(b, data.job);  // response to a repeated request
      else {
        b.results[data.result.kind].push(data.result.game);
        b.i = data.i;
        b.halted = data.halted;
      }
    }
  } catch (e) {
    b.halted = e.message;
    handleError(e);
  }
  b.phase = "done";
  await loadGames();
  // A response can be lost after the server checkpointed the game.
  if (savedBatch && savedBatch.id === b.id && b.session === window.__gmeSession) {
    const halted = b.halted;
    Object.assign(b, savedBatch);
    b.halted = halted || b.halted;
  }
  // New pictures, maybe under the same file names
  b.results.updated.forEach(u => {
    const g = games.find(x => x.path === u.path);
    if (g) stampMedia(u.fields.filter(f => FIELD_DEFS.some(d => d.key === f)).map(f => g[f]));
  });
  renderListWindow(true);
  const cur = games.find(x => x.index === currentIndex);
  if (cur) renderZones(cur);
  renderBatch();
  // The report is in the dialog; the status bar keeps the result once it is closed
  setStatus(t("batch.done_toast", { n: fmtCount(b.results.updated.length) }));
  document.getElementById("batch-cancel").focus();
}

/** Plain-text report, saved as a file (Downloads folder). */
function exportBatch() {
  if (!batch) return;
  const r = batch.results;
  const lines = [
    `${t("batch.title")} — ${SCRAPERS[batch.source].label} — Gamelist Media Editor`,
    labelValue(t("romcheck.report_gamelist"), batch.xmlPath || ""),
    labelValue(t("romcheck.report_date"), new Date().toLocaleString(currentLocale || "fr")),
    "",
  ];
  const section = (title, rows, extra) => {
    lines.push(`${title} (${rows.length})`);
    rows.forEach(g => lines.push(`  ${g.path}  —  ${g.name}` + (extra(g) ? `  (${extra(g)})` : "")));
    lines.push("");
  };
  section(t("batch.uncertain_title"), r.uncertain, () => "");
  section(t("batch.errors_title"), r.errors, g => g.message);
  section(t("batch.updated_title"), r.updated, g => g.fields.map(scrapeFieldLabel).join(", ") +
    (g.warnings.length ? ` — ${t("batch.partial")}: ${g.warnings.join("; ")}` : ""));
  section(t("batch.stat_nothing"), r.nothing, () => "");
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `batch-scrape-${(currentSystem && currentSystem.folder) || "gamelist"}-${new Date().toISOString().slice(0, 10)}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

document.getElementById("btn-batch-scrape").addEventListener("click", () => openBatch(true));
document.getElementById("btn-batch-selection").addEventListener("click", () => openBatch(true));
document.getElementById("saved-batch-entry").addEventListener("click", () => openBatch());
document.getElementById("batch-new").addEventListener("click", () => openBatch(true));
document.getElementById("batch-resume").addEventListener("click", () => resumeBatch());
document.getElementById("batch-retry").addEventListener("click", () => resumeBatch(true));
document.getElementById("batch-start").addEventListener("click", runBatch);
document.getElementById("batch-export").addEventListener("click", exportBatch);
document.getElementById("batch-close").addEventListener("click", closeBatch);
document.getElementById("batch-cancel").addEventListener("click", () => {
  if (batch && batch.phase === "running") {
    batch.stop = true;            // after the game in progress; the other workers stop now
    renderBatch();
    if (batch.id && batch.owner) {
      apiFetch("/api/batch/stop", {
        method: "POST", headers: { "Content-Type": "application/json", "X-Gamelist-Session": batch.session },
        body: JSON.stringify({ id: batch.id, owner: batch.owner }),
      }).catch(() => {});
    }
  } else {
    closeBatch();
  }
});
document.getElementById("batch-modal").addEventListener("click", e => {
  if (e.target.id === "batch-modal") closeBatch();
});

/* --- This game (header ⋯ menu) and "Next incomplete" ---------------------- */
setupMenu("game-menu", "btn-game-menu");

/** Full path of the selected game's ROM, with the separators of the gamelist path. */
function currentRomPath() {
  return romFullPath(games.find(x => x.index === currentIndex));
}
function romFullPath(g) {
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

/** Ticked games: their full ROM paths, one per line, in the order of the list. */
async function copySelectionPaths() {
  if (!selection.size) return;
  const paths = games.filter(g => selection.has(g.path)).map(romFullPath).filter(Boolean);
  if (!paths.length) return;
  const text = paths.join(navigator.platform && /win/i.test(navigator.platform) ? "\r\n" : "\n");
  try {
    await navigator.clipboard.writeText(text);
    toast(t("toast.paths_copied", { n: fmtCount(paths.length) }));
  } catch (_) {
    toast(t("toast.paths_copy_failed"), "warning");
  }
}
document.getElementById("btn-selection-copy").addEventListener("click", copySelectionPaths);
document.getElementById("btn-copy-selection-paths").addEventListener("click", copySelectionPaths);

/* --- Actions › Export the list (CSV) ---------------------------------------
 * The games shown (search and filters applied), in the order of the list. The
 * server writes the file from gamelist.xml (gme/csv_export.py): UTF-8 with a
 * BOM; ";" as separator except in English, as Excel expects in each language. */
async function exportCsv() {
  if (!window.__gmeLoaded) { toast(t("server.no_gamelist"), "warning"); return; }
  const shown = getVisibleListIndices().map(i => games[i].path);
  if (!shown.length) { toast(t("toast.csv_empty"), "info"); return; }
  setStatus(t("status.csv_export"));
  try {
    const blob = await apiFetch("/api/export-csv", {
      method: "POST", headers: { "Content-Type": "application/json" }, raw: true,
      body: JSON.stringify({ paths: shown, required: requiredKeys(), sep: (currentLocale || "fr") === "en" ? "," : ";" }),
    });
    const a = document.createElement("a");
    const system = (currentSystem && currentSystem.folder) || "gamelist";
    a.href = URL.createObjectURL(blob);
    a.download = `gamelist-${system}-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast(t("toast.csv_exported", { n: fmtCount(shown.length) }));
    setStatus(t("status.csv_exported", { n: fmtCount(shown.length) }));
  } catch (e) {
    handleError(e);
  }
}
document.getElementById("btn-export-csv").addEventListener("click", exportCsv);

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

/* --- Dated XML snapshots and reversible restoration ---------------------- */
let backupSession = null;
let backupEntries = [];
let restoringBackup = false;

async function openBackups() {
  closeMenu(null, false);
  if (!(await confirmLeaveEditor())) return;
  try {
    const data = await apiFetch("/api/backups");
    backupSession = data.session_id;
    backupEntries = data.backups;
    renderBackups();
    document.getElementById("backups-modal").classList.add("open");
    document.getElementById("backups-cancel").focus();
  } catch (e) { handleError(e); }
}

function renderBackups() {
  document.getElementById("backups-body").innerHTML = backupEntries.length
    ? backupEntries.map(entry => `<div class="backup-row"><div><time datetime="${escapeHtml(entry.created)}">` +
      `${escapeHtml(new Date(entry.created).toLocaleString(currentLocale || "fr"))}</time>` +
      `<p class="backup-reason">${escapeHtml(t(entry.reason === "restore" ? "backups.before_restore" : entry.reason === "legacy" ? "backups.legacy" : "backups.copy"))}</p></div>` +
      `<span>${escapeHtml(fmtSize(entry.size))}</span><button type="button" class="btn btn-sm" ` +
      `data-restore-backup="${escapeHtml(entry.id)}">${escapeHtml(t("backups.restore"))}</button></div>`).join("")
    : `<p class="tools-intro">${escapeHtml(t("backups.empty"))}</p>`;
}

function closeBackups() {
  if (restoringBackup) return;
  document.getElementById("backups-modal").classList.remove("open");
  document.getElementById("btn-actions").focus();
}

document.getElementById("btn-backup-history").addEventListener("click", openBackups);
document.getElementById("backups-close").addEventListener("click", closeBackups);
document.getElementById("backups-cancel").addEventListener("click", closeBackups);
document.getElementById("backups-modal").addEventListener("click", e => {
  if (e.target.id === "backups-modal") closeBackups();
});
document.getElementById("backups-create").addEventListener("click", async () => {
  const button = document.getElementById("backups-create");
  button.disabled = true;
  try {
    await apiFetch("/api/backup", { method: "POST", headers: { "X-Gamelist-Session": backupSession } });
    const data = await apiFetch("/api/backups", { headers: { "X-Gamelist-Session": backupSession } });
    backupEntries = data.backups;
    renderBackups();
  } catch (e) { handleError(e); }
  finally { button.disabled = false; }
});
document.getElementById("backups-body").addEventListener("click", async e => {
  const button = e.target.closest("[data-restore-backup]");
  if (!button || restoringBackup) return;
  const entry = backupEntries.find(b => b.id === button.dataset.restoreBackup);
  if (!entry) return;
  restoringBackup = true;
  try {
    const choice = await askConfirm({
      title: t("backups.restore"),
      bodyHtml: escapeHtml(t("backups.confirm", { date: new Date(entry.created).toLocaleString(currentLocale || "fr") })),
      showBackup: false, okLabel: t("backups.restore"),
    });
    if (!choice.confirmed) return;
    const data = await apiFetch("/api/backups/restore", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Gamelist-Session": backupSession },
      body: JSON.stringify({ id: entry.id }),
    });
    window.__gmeSession = data.session_id;
    resetEditorSelection();
    await loadGames();
    const history = await apiFetch("/api/backups");
    backupSession = history.session_id;
    backupEntries = history.backups;
    renderBackups();
    toast(t("backups.restored"));
    document.getElementById("backups-cancel").focus();
  } catch (error) { handleError(error); }
  finally {
    restoringBackup = false;
    if (button.isConnected) button.focus();
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
    await loadGames();             // the open game and the list lose their region too
    toast(msg);
    setStatus(t("status.done"));
  } catch (e) { handleError(e); }
});

/** The files a deletion will remove, from the server's dry run (gme/gamedelete.py). */
const DELETE_ROWS_SHOWN = 6;
function deletePlanHtml(plan) {
  const list = (title, rows, cls = "") => {
    if (!rows.length) return "";
    const shown = rows.slice(0, DELETE_ROWS_SHOWN).map(r =>
      `<li><code title="${escapeHtml(r.path)}">\u200e${escapeHtml(r.path)}${r.dir ? "/" : ""}\u200e</code>` +
      `<span>${escapeHtml(fmtSize(r.size))}</span></li>`).join("");
    const more = rows.length > DELETE_ROWS_SHOWN
      ? `<li class="del-more">${escapeHtml(t("confirm.delete_more", { n: rows.length - DELETE_ROWS_SHOWN }))}</li>` : "";
    return `<p class="del-h${cls}">${escapeHtml(title)}</p><ul class="del-list">${shown}${more}</ul>`;
  };
  return list(t("confirm.delete_files", { n: plan.files.length }), plan.files) +
    list(t("confirm.delete_media", { n: plan.media.length }), plan.media) +
    `<p class="del-h">${t("confirm.delete_entry")}</p>` +
    list(t("confirm.delete_kept", { n: plan.kept.length }), plan.kept, " is-kept") +
    `<label class="modal-backup del-trash"><input type="checkbox" id="delete-trash" checked />` +
    `<span>${escapeHtml(t("mediacheck.trash"))}</span></label>`;
}

document.getElementById("btn-delete-game").addEventListener("click", async () => {
  if (currentIndex === null) return;
  const g = games.find(x => x.index === currentIndex);
  const name = g ? g.name : t("confirm.this_game");
  let plan;
  try {
    plan = await apiFetch(gameUrl(`/api/delete-game/${currentIndex}/preview`), { method: "POST" });
  } catch (e) {
    handleError(e);
    return;
  }
  const choice = await askConfirm({
    title: t("confirm.delete_title", { name }),
    bodyHtml: deletePlanHtml(plan),
    okLabel: t("confirm.delete_ok"),
  });
  if (!choice.confirmed) return;
  const trash = document.getElementById("delete-trash").checked;

  setStatus(t("status.deleting_game"));
  try {
    const data = await apiFetch(gameUrl(`/api/delete-game/${currentIndex}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup: choice.backup, trash }),
    });
    const n = (data.deleted_files || []).length;
    let msg = t(data.trash ? "toast.delete_ok_trash" : "toast.delete_ok", { name: data.name, n });
    if ((data.kept_files || []).length) msg += t("toast.delete_kept", { n: data.kept_files.length });
    if ((data.failed_files || []).length) msg += t("mediacheck.done_failed", { n: data.failed_files.length });
    if (data.backup) msg += t("toast.purge_bak");
    toast(msg, (data.failed_files || []).length ? "warning" : "success");
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
const RECENT_GL_KEY = "gme_recent_gamelists";   // where older versions kept the list (browser)

/* Recent files (kept by the server in recent_gamelists.json, see gme/recent.py):
 * one click opens. The system folder (parent of gamelist.xml) comes first,
 * because long paths only differ at their end. */
const RECENT_SHOWN = 10;

function recentKey(path) {
  // Windows paths: same file whatever the case or the slashes
  return /^[a-zA-Z]:[\\/]|\\/.test(path) ? path.replace(/\//g, "\\").toLowerCase() : path;
}

/** Older versions kept the list in the browser: hand it to the server once. */
async function importBrowserRecents() {
  let old = null;
  try { old = JSON.parse(localStorage.getItem(RECENT_GL_KEY) || "null"); } catch (_) {}
  if (!Array.isArray(old) || !old.length) return;
  try {
    await apiFetch("/api/recent/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: old }),
    });
    localStorage.removeItem(RECENT_GL_KEY);
  } catch (_) {}
}

async function renderRecentGamelists(data) {
  const box = document.getElementById("open-gl-recent");
  if (!box) return;
  if (!data) {
    try { data = await apiFetch("/api/recent"); } catch (_) { data = { recent: [] }; }
  }
  const current = window.__gmeXmlPath ? recentKey(window.__gmeXmlPath) : null;
  const list = (data.recent || []).filter((r) => recentKey(r.path) !== current).slice(0, RECENT_SHOWN);
  if (!list.length) {
    box.innerHTML = `<div class="open-gl-recent-empty">${escapeHtml(t("open_gl.recent_empty"))}</div>`;
    return;
  }
  box.innerHTML = list.map(({ path: p, exists }) => {
    const parts = p.split(/[\\/]/).filter(Boolean);
    const folder = parts.length > 1 ? parts[parts.length - 2] : p;
    const title = exists ? p : `${p} (${t("open_gl.recent_missing")})`;
    return `<div class="open-gl-recent-row${exists ? "" : " is-missing"}" role="listitem">` +
      `<button type="button" class="open-gl-recent-item" data-path="${escapeHtml(p)}" title="${escapeHtml(title)}">` +
      `${icon(exists ? "device-gamepad-2" : "alert-triangle")}<span class="open-gl-recent-name">${escapeHtml(folder)}</span>` +
      `<span class="open-gl-recent-path">\u200e${escapeHtml(p)}\u200e</span></button>` +
      `<button type="button" class="btn btn-icon btn-sm open-gl-recent-forget" data-path="${escapeHtml(p)}"` +
      ` title="${escapeHtml(t("open_gl.recent_forget"))}" aria-label="${escapeHtml(t("open_gl.recent_forget"))}">${icon("x")}</button>` +
      `</div>`;
  }).join("");
}
document.getElementById("open-gl-recent").addEventListener("click", async (e) => {
  const forget = e.target.closest(".open-gl-recent-forget");
  if (forget) {
    try {
      const data = await apiFetch("/api/recent/forget", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: forget.dataset.path }),
      });
      renderRecentGamelists(data);
    } catch (err) {
      handleError(err);
    }
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
    window.__gmeSession = data.session_id;
    window.__gmeLoaded = true;
    games = data.games || [];
    setNoGamelistUi(true);
    resetEditorSelection();
    updateSystemBadge(data.system || null);
    const sysEl = document.getElementById("system-name");
    if (sysEl && data.xml_path) sysEl.title = data.xml_path;
    const searchEl = document.getElementById("search");
    if (searchEl) searchEl.value = "";
    genreFilter = "all";                     // the genres of another system differ
    selection.clear();
    selectionChanged(false);
    renderList("");
    closeGamelistModal();
    const label = (data.system && (data.system.label || data.system.folder)) || path;
    toast(t("toast.gamelist_opened", { name: label, n: data.count != null ? data.count : games.length }));
    setStatus(t("status.ready", { n: games.length }));
    refreshSavedBatch();
  } catch (e) {
    // A recent file that was moved or deleted: the server dropped it from the list
    if (e && e.code === "open_not_found") renderRecentGamelists();
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


/* --- About dialog --- */
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
  await loadSettings();
  applyTheme(SETTINGS.theme);
  updateSearchModeUi();
  await loadLocale(SETTINGS.locale || DEFAULT_LOCALE);
  wireLanguageControls();
  try {
    GENRES = await apiFetch("/static/genres.json");
  } catch (e) {
    handleError(e, t("errors.genres"));
    GENRES = {};
  }
  initGenreSelects();
  await importBrowserRecents();
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
/* ScreenScraper region codes, named in the interface language */
const SS_REGIONS = ["wor", "eu", "us", "jp", "fr", "de", "es", "it", "pt", "uk", "nl", "se", "no", "dk", "fi",
  "pl", "ru", "br", "au", "ca", "kr", "cn", "tw", "asi"];
function fillSsRegions(value) {
  const sel = document.getElementById("ss-region");
  const keep = value || sel.value || "fr";
  sel.innerHTML = SS_REGIONS.map(c => `<option value="${c}">${escapeHtml(regionLabel(c))} (${c})</option>`).join("");
  setSelectValue(sel, keep);
}
/* Thread setting: Auto = the member's maxthreads; a number can only lower it (server-side clamp) */
const SS_THREAD_CHOICES = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16];
function fillSsThreads(value, limits) {
  const sel = document.getElementById("ss-threads");
  const max = limits && limits.maxthreads;
  sel.innerHTML = `<option value="0">${escapeHtml(t("tools.ss_threads_auto"))}</option>` +
    SS_THREAD_CHOICES.map(n => `<option value="${n}">${n}</option>`).join("");
  setSelectValue(sel, String(value || 0));
  document.getElementById("ss-threads-hint").textContent = max
    ? t("tools.ss_threads_max", { n: max })
    : t("tools.ss_threads_unknown");
}
async function loadSsConfig() {
  try {
    const cfg = await apiFetch("/api/ss/config");
    document.getElementById("ss-ssid").value = cfg.ssid || "";
    fillSsRegions(cfg.prefer_region || "fr");
    fillSsThreads(cfg.threads, cfg.limits);
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

async function saveSsConfig({ quiet = false } = {}) {
  const payload = {
    ssid: document.getElementById("ss-ssid").value.trim(),
    prefer_region: document.getElementById("ss-region").value,
    threads: Number(document.getElementById("ss-threads").value) || 0,
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
    if (!quiet) toast(t("toast.ss_saved"));
    return true;
  } catch (e) {
    handleError(e);
    return false;
  }
}

async function testSsConfig() {
  if (ssBusy) return;
  const st = document.getElementById("ss-status");
  st.textContent = t("status.testing");
  st.className = "ss-status";
  setSsLoading(true, t("scrape.test_loading"));
  try {
    // A password typed but not yet saved (the field saves when it loses the focus)
    await saveSsConfig({ quiet: true });
    const data = await apiFetch("/api/ss/test", { method: "POST" });
    let msg = t("scrape.test_ok_short");
    if (data.mode === "user") {
      msg += " · " + t("scrape.test_level", { level: data.level || "?" });
      if (data.maxthreads) msg += " · " + t("scrape.test_threads", { n: data.maxthreads });
      if (data.limits) fillSsThreads(document.getElementById("ss-threads").value, data.limits);
    } else {
      msg += " · " + (data.message || t("scrape.test_dev_ok"));
    }
    st.textContent = msg;
    st.className = "ss-status ok";
    toast(msg);
  } catch (e) {
    st.textContent = e.message;
    st.className = "ss-status err";
    toast(labelValue("ScreenScraper", e.message), "error");
  } finally {
    setSsLoading(false);
  }
}

// Like the language, each ScreenScraper setting is saved as soon as it changes
["ss-ssid", "ss-sspassword", "ss-region", "ss-threads", "ss-type-image", "ss-type-boxart", "ss-type-mix"].forEach(id => {
  document.getElementById(id).addEventListener("change", () => saveSsConfig());
});
document.getElementById("btn-ss-test").addEventListener("click", testSsConfig);

const SCRAPERS = {
  screenscraper: { label: "ScreenScraper", icon: "cloud-download", scrape: "/api/ss/scrape/", apply: "/api/ss/apply/", idKey: "gameid" },
  arcadeitalia: { label: "Arcade Database", icon: "coin", scrape: "/api/adb/scrape/", apply: "/api/adb/apply/", idKey: "romset" },
  steam: { label: "Steam", icon: "brand-steam", scrape: "/api/steam/scrape/", apply: "/api/steam/apply/", idKey: "appid" },
};
const SCRAPER_PREF_KEY = "gme_scraper_by_system";     // where older versions kept it (browser)
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
  return SETTINGS.scrapers || {};
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
  const value = !source || source === autoScraper() ? null : source;
  if (value) SETTINGS.scrapers[folder] = value;        // shown at once, saved behind
  else delete SETTINGS.scrapers[folder];
  updateScrapeButton();
  saveSettings({ scrapers: { [folder]: value } });
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
    html += `<section class="ss-section" id="ss-sec-media"><h4 class="ss-section-title">${escapeHtml(t("scrape.section_media"))}</h4>` +
      `<div class="ss-media-grid">${media.map(scrapeMediaCardHtml).join("")}</div></section>`;
  }
  if (meta.length) {
    html += `<section class="ss-section" id="ss-sec-info"><h4 class="ss-section-title">${escapeHtml(t("scrape.section_info"))}</h4>` +
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
  // Both sections: shortcuts to each, the second one is often below the fold
  document.getElementById("ss-jump").innerHTML = media.length && meta.length
    ? [["media", "scrape.section_media", media.length], ["info", "scrape.section_info", meta.length]]
      .map(([k, label, n]) => `<button type="button" class="ss-jump-btn" data-jump="${k}">` +
        `${escapeHtml(t(label))}<span>${n}</span></button>`).join("")
    : "";
  document.getElementById("ss-candidates").hidden = true;
  document.getElementById("ss-select-bar").hidden = !actionable.length;
  document.getElementById("ss-hint").hidden = !actionable.length;
  document.getElementById("ss-modal-apply").hidden = false;
  applyScrapePreset("missing");
  openSsModal();
  box.scrollTop = 0;
  updateScrapeScrollHint();
}
/** A fade at the bottom while there is more below. */
function updateScrapeScrollHint() {
  const box = document.getElementById("ss-fields");
  box.classList.toggle("has-more", box.scrollTop + box.clientHeight < box.scrollHeight - 4);
}
document.getElementById("ss-fields").addEventListener("scroll", updateScrapeScrollHint, { passive: true });
window.addEventListener("resize", () => {
  if (document.getElementById("ss-modal").classList.contains("open")) updateScrapeScrollHint();
});
document.getElementById("ss-jump").addEventListener("click", e => {
  const btn = e.target.closest("[data-jump]");
  if (!btn) return;
  const box = document.getElementById("ss-fields");
  const section = document.getElementById("ss-sec-" + btn.dataset.jump);
  box.scrollTo({ top: section.offsetTop - box.offsetTop, behavior: "smooth" });
});

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
    const g = games.find(x => x.index === currentIndex);
    if (g && (data.applied || []).length) {
      // New pictures, maybe under the same file names
      stampMedia(data.applied.filter(f => FIELD_DEFS.some(d => d.key === f)).map(f => g[f]));
      renderZones(g);
      renderListWindow(true);
    }
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
  if (changedFields().length || (batch && batch.phase === "running")) { e.preventDefault(); e.returnValue = ""; }
});
document.getElementById("ss-modal-close").addEventListener("click", closeSsModal);
document.getElementById("ss-modal-cancel").addEventListener("click", closeSsModal);
document.getElementById("ss-modal-apply").addEventListener("click", applyScrape);
document.getElementById("ss-modal").addEventListener("click", e => {
  if (e.target.id === "ss-modal") closeSsModal();
});


boot();
