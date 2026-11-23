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
{ key: "titleshot", icon: "heading" },
{ key: "video",     icon: "movie" },
{ key: "marquee",   icon: "tag" },
{ key: "wheel",     icon: "steering-wheel" },
{ key: "manual",    icon: "book" },
{ key: "boxart",    icon: "box" },
{ key: "boxback",   icon: "flip-horizontal" },
{ key: "cartridge", icon: "device-sd-card" },
{ key: "fanart",    icon: "wallpaper" },
{ key: "mix",       icon: "layout-collage" },
{ key: "map",       icon: "map" },
{ key: "thumbnail", icon: "photo-square-rounded" },
{ key: "bezel",     icon: "frame" },
{ key: "music",     icon: "music" },
];
/* ES-DE (gme/esde.py) holds fewer media than RetroBat (no wheel, map, bezel,
 * music): the open gamelist's profile lists the ones it can hold. */
function profileFields() {
  const p = typeof currentSystem !== "undefined" && currentSystem && currentSystem.profile;
  return p && Array.isArray(p.fields) ? p.fields : null;
}
function isEsde() {
  const p = typeof currentSystem !== "undefined" && currentSystem && currentSystem.profile;
  return !!(p && p.kind === "esde");
}
/** Media fields of the open gamelist (``all``: every field GME knows). */
function getFields(all = false) {
  const only = all ? null : profileFields();
  return FIELD_DEFS.filter(f => !only || only.includes(f.key)).map(f => ({
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
  try { fillColFilter(); } catch (_) {}
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

/** Message at the bottom; ``action`` ({label, run}) adds a button (e.g. Undo) and keeps it longer. */
function toast(msg, type = "success", action = null) {
  const el = document.getElementById("toast");
  if (!el) return;
  const ico = { error: "alert-circle", warning: "alert-triangle", info: "info-circle" }[type] || "circle-check";
  el.innerHTML = icon(ico) + `<span>${escapeHtml(String(msg || ""))}</span>` +
    (action ? `<button type="button" class="btn btn-sm toast-action">${escapeHtml(action.label)}</button>` : "");
  el.className = "toast " + type + " show";
  if (action) {
    el.querySelector(".toast-action").addEventListener("click", () => {
      el.classList.remove("show");
      action.run();
    }, { once: true });
  }
  if (_toastTimer) clearTimeout(_toastTimer);
  const ms = action ? 15000 : type === "error" ? 6500 : type === "warning" ? 4500 : 3200;
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

/* --- Loading ring ------------------------------------------------------------
 * One style (.spinner in style.css). It appears only after SPINNER_DELAY_MS, so
 * a fast answer never flickers:
 * - the status bar ring turns while any API request has been running that long;
 * - setBusy(button) disables a button (no double submit) and turns a ring in it,
 *   over its icon when it has one; withBusy(button, fn) always clears it, error or not;
 * - busyHtml(text) is a "working" line for a panel (role=status).
 */
const SPINNER_DELAY_MS = 200;
let apiInFlight = 0;
let apiBusyTimer = null;
function apiBusy(delta) {
  apiInFlight = Math.max(0, apiInFlight + delta);
  const ring = document.getElementById("status-spinner");
  if (!ring) return;
  if (apiInFlight && !apiBusyTimer && ring.hidden) {
    apiBusyTimer = setTimeout(() => {
      apiBusyTimer = null;
      if (apiInFlight) { ring.hidden = false; document.querySelector(".status-bar").setAttribute("aria-busy", "true"); }
    }, SPINNER_DELAY_MS);
  } else if (!apiInFlight) {
    clearTimeout(apiBusyTimer);
    apiBusyTimer = null;
    ring.hidden = true;
    document.querySelector(".status-bar").removeAttribute("aria-busy");
  }
}
function spinnerHtml(extra = "") {
  return `<span class="spinner spinner-sm spinner-delay${extra ? " " + extra : ""}" aria-hidden="true"></span>`;
}
function busyHtml(text, cls = "", tag = "div") {
  return `<${tag} class="busy-line${cls ? " " + cls : ""}" role="status" aria-live="polite">${spinnerHtml()}` +
    `<span>${escapeHtml(text || t("common.loading"))}</span></${tag}>`;
}
function setBusy(el, on, { restore = true } = {}) {
  if (!el) return;
  if (on) {
    if (el.dataset.busy) return;
    el.dataset.busy = "1";
    el._busyWasDisabled = !!el.disabled;
    if ("disabled" in el) el.disabled = true;
    el.setAttribute("aria-busy", "true");
    el.classList.add("is-busy");
    const icon = el.querySelector(":scope > .icon");
    if (icon) {
      icon.insertAdjacentHTML("beforebegin", spinnerHtml("on-icon"));
      const ring = icon.previousElementSibling;
      // SVG icons have no offsetLeft: place the ring from the bounding boxes.
      const box = el.getBoundingClientRect(), ib = icon.getBoundingClientRect();
      ring.style.left = (ib.left - box.left - el.clientLeft + (ib.width - 14) / 2) + "px";
      ring.style.top = (ib.top - box.top - el.clientTop + (ib.height - 14) / 2) + "px";
    } else {
      el.insertAdjacentHTML("afterbegin", spinnerHtml());
    }
  } else {
    if (!el.dataset.busy) return;
    delete el.dataset.busy;
    el.removeAttribute("aria-busy");
    el.classList.remove("is-busy");
    el.querySelectorAll(":scope > .spinner").forEach(r => r.remove());
    if (restore && "disabled" in el) el.disabled = el._busyWasDisabled;
  }
}
async function withBusy(el, fn, opts) {
  setBusy(el, true);
  try { return await fn(); } finally { setBusy(el, false, opts); }
}

/** Fetch JSON API; attaches X-Locale so server messages match the UI language. */
async function apiFetch(url, options = {}) {
  apiBusy(1);
  try {
    return await apiFetchInner(url, options);
  } finally {
    apiBusy(-1);
  }
}
async function apiFetchInner(url, options = {}) {
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
  const keys = customRequired(currentSystem && currentSystem.folder) || defaultRequired();
  const only = profileFields();
  return only ? keys.filter(k => only.includes(k)) : keys;
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
  return mediaFilter !== "all" || genreFilter !== "all" || flagFilter !== "all" || colFilterActive();
}

/* Custom column filter: one column, one condition (contains, starts with, is
 * empty…), case-insensitive; combined with the search and the other filters. */
const COL_META = ["name", "path", "genre", "developer", "publisher", "releasedate", "players", "rating", "lang",
  "region", "family", "arcadesystemname"];
const COL_OPS = ["contains", "not_contains", "starts", "ends", "equals", "empty", "not_empty"];
const colFilter = { on: false, field: "name", op: "contains", value: "" };
function colFieldLabel(key) {
  if (key === "path") return t("colfilter.field_path");
  if (COL_META.includes(key)) return t("scrape.field_" + key);
  return fieldLabel(key);
}
function colFilterActive() {
  return colFilter.on && (colFilter.op === "empty" || colFilter.op === "not_empty" || colFilter.value.trim() !== "");
}
function matchesColFilter(g) {
  if (!colFilterActive()) return true;
  const v = String(g[colFilter.field] || "").trim().toLowerCase();
  const q = colFilter.value.trim().toLowerCase();
  switch (colFilter.op) {
    case "contains": return v.includes(q);
    case "not_contains": return !v.includes(q);
    case "starts": return v.startsWith(q);
    case "ends": return v.endsWith(q);
    case "equals": return v === q;
    case "empty": return !v;
    case "not_empty": return !!v;
    default: return true;
  }
}
function fillColFilter() {
  const field = document.getElementById("col-field");
  const op = document.getElementById("col-op");
  const keys = [...COL_META, ...FIELD_DEFS.map(f => f.key)];
  field.innerHTML = `<optgroup label="${escapeHtml(t("colfilter.group_info"))}">` +
    COL_META.map(k => `<option value="${k}">${escapeHtml(colFieldLabel(k))}</option>`).join("") +
    `</optgroup><optgroup label="${escapeHtml(t("colfilter.group_media"))}">` +
    FIELD_DEFS.map(f => `<option value="${f.key}">${escapeHtml(colFieldLabel(f.key))}</option>`).join("") + "</optgroup>";
  op.innerHTML = COL_OPS.map(k => `<option value="${k}">${escapeHtml(t("colfilter.op_" + k))}</option>`).join("");
  field.value = keys.includes(colFilter.field) ? colFilter.field : "name";
  op.value = colFilter.op;
  updateColFilterUi();
}
function updateColFilterUi() {
  const noValue = colFilter.op === "empty" || colFilter.op === "not_empty";
  document.getElementById("col-value").hidden = noValue;
  document.getElementById("col-filter").hidden = !colFilter.on;
  const btn = document.getElementById("btn-col-filter");
  btn.setAttribute("aria-pressed", String(colFilter.on));
  btn.classList.toggle("is-on", colFilter.on);
  document.getElementById("col-filter").classList.toggle("is-active", colFilterActive());
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
    if (!matchesColFilter(g)) continue;
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
    if (!matchesColFilter(g)) continue;
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
    const prof = document.getElementById("system-profile");
    if (prof) prof.hidden = true;
    el.textContent = "—";
    el.title = t("header.system_unknown");
    el.dataset.empty = "1";
    return;
  }
  el.textContent = system.label;
  el.dataset.empty = "0";
  const prof = document.getElementById("system-profile");
  const esde = system.profile && system.profile.kind === "esde";
  if (prof) {
    prof.hidden = !esde;
    prof.title = esde ? t("esde.badge_title", { media: system.profile.media_dir, roms: system.profile.rom_dir }) : "";
  }
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
/** Tick every game the list shows (search and filters applied): Ctrl+A. */
function selectShown() {
  if (!viewIndices.length) return;
  viewIndices.forEach(i => selection.add(games[i].path));
  selectionAnchor = games[viewIndices[viewIndices.length - 1]].path;
  selectionChanged();
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
  setBusy(document.getElementById("btn-save"), true);
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
    setBusy(document.getElementById("btn-save"), false, { restore: false });
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
  titleshot: "4 / 3", wheel: "3 / 1", music: "2 / 1",
};
const MEDIA_ACCEPT = { video: "video/*", manual: "application/pdf,.pdf", music: "audio/*,.mp3,.ogg,.wav,.flac" };

/** Once the real size is known, the tile takes the media's own shape (within
 * limits, so a very tall or very wide image stays readable): nothing is cut,
 * no large empty band. MEDIA_SHAPE is only the shape while loading. */
function fitTileToMedia(tile, width, height) {
  if (!width || !height) return;
  const ratio = Math.min(4, Math.max(0.45, width / height));
  tile.style.setProperty("--ar", String(Math.round(ratio * 1000) / 1000));
}

function fieldLabel(key) {
  const f = getFields(true).find(x => x.key === key);
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
  } else if (f.key === "music") {
    media = `<div class="tile-audio">${icon("music")}<audio src="${url}" controls preload="metadata"></audio></div>`;
  } else if (f.key === "manual") {
    media = `<a class="tile-doc" href="${url}" target="_blank" rel="noopener">${icon("file-text")}<span>${t("zone.open")}</span></a>`;
  } else {
    media = `<img src="${url}" alt="${escapeHtml(f.label)}" title="${t("zone.zoom_title")}" loading="lazy" decoding="async" />`;
  }
  return `<figure class="media-tile" data-field="${f.key}" style="--ar: ${MEDIA_SHAPE[f.key] || "4 / 3"}">
    <figcaption class="tile-head">
      <span class="tile-title">${icon(f.icon)}<span>${escapeHtml(f.label)}</span></span>
      <span class="tile-actions">
${isImageField(f.key) ? `<button type="button" class="btn btn-icon btn-sm" data-action="edit" title="${escapeHtml(t("imgedit.title"))}" aria-label="${escapeHtml(t("imgedit.title"))}">${icon("photo-edit")}</button>` : ""}
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
    const audio = tile.querySelector("audio");
    if (audio) {
      audio.addEventListener("loadedmetadata", () => {
        const s = Math.round(audio.duration || 0);
        if (s && isFinite(audio.duration)) dims.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
      });
      audio.addEventListener("error", () => {
        tile.querySelector(".tile-media").innerHTML =
          `<div class="tile-broken">${icon("alert-triangle")}<span>${t("zone.preview_unavailable")}</span></div>`;
      });
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
    else if (actionBtn && actionBtn.dataset.action === "edit") openImageEditor(field);
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
  const tile = document.querySelector(`.media-tile[data-field="${field}"]`);
  setTileBusy(tile, true);
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
  } finally {
    setTileBusy(tile, false);
  }
}
/** A ring over a media tile while its file is sent or downloaded (the tile may be re-rendered meanwhile). */
function setTileBusy(tile, on) {
  if (!tile) return;
  if (on) {
    tile.setAttribute("aria-busy", "true");
    tile.insertAdjacentHTML("beforeend", `<div class="tile-busy" role="status">${spinnerHtml()}<span>${escapeHtml(t("common.loading"))}</span></div>`);
  } else {
    tile.removeAttribute("aria-busy");
    tile.querySelectorAll(".tile-busy").forEach(el => el.remove());
  }
}

async function clearField(field) {
  const target = games.find(g => g.index === currentIndex);
  const session = window.__gmeSession;
  // Detach media tag in XML only (file kept on disk). ES-DE has no media tag:
  // the file itself goes to the Recycle Bin.
  const choice = await askConfirm({
    title: t("confirm.clear_field_title", { field: fieldLabel(field) }),
    bodyHtml: t(isEsde() ? "esde.clear_field_body" : "confirm.clear_field_body"),
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
(() => {
  let timer = null;
  const changed = () => {
    updateColFilterUi();
    listEls().list.scrollTop = 0;
    renderList();
  };
  document.getElementById("btn-col-filter").addEventListener("click", () => {
    colFilter.on = !colFilter.on;
    changed();
    if (colFilter.on) document.getElementById(colFilter.op === "empty" || colFilter.op === "not_empty" ? "col-op" : "col-value").focus();
  });
  document.getElementById("col-clear").addEventListener("click", () => {
    colFilter.on = false;
    colFilter.value = "";
    document.getElementById("col-value").value = "";
    changed();
    document.getElementById("btn-col-filter").focus();
  });
  document.getElementById("col-field").addEventListener("change", e => { colFilter.field = e.target.value; changed(); });
  document.getElementById("col-op").addEventListener("change", e => { colFilter.op = e.target.value; changed(); });
  document.getElementById("col-value").addEventListener("input", e => {
    colFilter.value = e.target.value;
    clearTimeout(timer);
    timer = setTimeout(changed, SEARCH_DEBOUNCE_MS);
  });
  document.getElementById("btn-select-shown").addEventListener("click", selectShown);
})();
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
  for (const [id, close] of [["imgedit-modal", () => closeImageEditor()], ["bulk-modal", () => closeBulk()], ["stats-modal", () => closeStats()], ["mbatch-modal", () => closeMultiBatch()], ["overview-modal", () => closeOverview()],
    ["dat-modal", () => closeDatTool()], ["newgl-modal", () => closeNewGamelist()]]) {
    const el = document.getElementById(id);
    if (el && el.classList.contains("open")) {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
      return;
    }
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

  // Ctrl+A (not in a text field): tick every game shown
  if (ctrl && e.key.toLowerCase() === "a" && !typing) {
    e.preventDefault();
    selectShown();
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
const DIALOG_IDS = ["confirm-modal", "media-lightbox", "ss-modal", "batch-modal", "check-modal", "backups-modal", "bulk-modal",
  "imgedit-modal", "stats-modal", "mbatch-modal", "overview-modal", "dat-modal", "newgl-modal", "open-gamelist-modal",
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
const SETTINGS_PANES = ["general", "ss", "sources", "fallback", "ssmedia", "required", "keys"];

function openSettings(pane) {
  closeMenu(null, false);
  wireLanguageControls();
  loadSsConfig();
  loadFallbackConfig();
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
  ["btn-bulk", "btn-stats", "btn-batch-scrape", "btn-manual-backup", "btn-backup-history", "btn-fill-arcade", "btn-rom-check", "btn-dat-tool", "btn-media-check"].forEach(id => {
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
  document.getElementById("check-intro").innerHTML = busyHtml(t("romcheck.scanning"), "", "span");
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
  const applyBtn = document.getElementById("check-apply");
  setBusy(applyBtn, true);
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
  } finally {
    setBusy(applyBtn, false, { restore: false });
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
const BATCH_MEDIA = ["image", "titleshot", "thumbnail", "marquee", "wheel", "boxart", "boxback", "cartridge", "fanart", "mix", "map",
  "bezel", "video", "manual", "pad2key"];
const BATCH_INFO = ["desc", "genre", "rating", "releasedate", "developer", "publisher", "players", "lang", "region",
  "family", "arcadesystemname", "name"];
const batchPrefs = { mode: "missing", off: new Set(["name", "pad2key"]) };   // kept for the session
/** Media a batch scrape can fill in the open gamelist (ES-DE: no wheel, map, bezel, Pad2Key). */
function batchMedia() {
  const only = profileFields();
  return only ? BATCH_MEDIA.filter(k => only.includes(k)) : BATCH_MEDIA;
}
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
      batchFieldsHtml(t("scrape.section_media"), batchMedia()) +
      batchFieldsHtml(t("scrape.section_info"), BATCH_INFO);
    options.innerHTML = `<label class="check-option"><input type="checkbox" id="batch-backup" checked />` +
      `<span>${escapeHtml(t("romcheck.backup"))}</span></label>` +
      (b.source === "screenscraper" ? `<label class="check-option" title="${escapeHtml(t("batch.refresh_hint"))}">` +
        `<input type="checkbox" id="batch-refresh" /><span>${escapeHtml(t("batch.refresh"))}</span></label>` : "");
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
  const refreshBox = document.getElementById("batch-refresh");
  const refresh = !!(refreshBox && refreshBox.checked);
  b.phase = "running";
  renderBatch();
  document.getElementById("batch-cancel").focus();
  try {
    const data = await apiFetch("/api/batch", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Gamelist-Session": b.session },
      body: JSON.stringify({ source: b.source, mode, fields, paths: b.targets.map(g => g.path), backup, refresh, fromSelection: b.fromSelection }),
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
  const actions = document.getElementById("btn-actions");
  setBusy(actions, true);
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
  } finally {
    setBusy(actions, false);
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
  await withBusy(document.getElementById("btn-reload"), loadGames);
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
    const data = await withBusy(document.getElementById("btn-actions"), () => apiFetch("/api/backup", { method: "POST" }));
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
    const data = await withBusy(document.getElementById("btn-actions"), () => apiFetch("/api/backups"));
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
  setBusy(button, true);
  try {
    await apiFetch("/api/backup", { method: "POST", headers: { "X-Gamelist-Session": backupSession } });
    const data = await apiFetch("/api/backups", { headers: { "X-Gamelist-Session": backupSession } });
    backupEntries = data.backups;
    renderBackups();
  } catch (e) { handleError(e); }
  finally { setBusy(button, false); }
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
    setBusy(button, true);
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
    setBusy(button, false);
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
    const data = await withBusy(document.getElementById("btn-actions"), () => apiFetch("/api/fill-arcadesystem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup: choice.backup }),
    }));
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
  const gameMenu = document.getElementById("btn-game-menu");
  try {
    plan = await withBusy(gameMenu, () => apiFetch(gameUrl(`/api/delete-game/${currentIndex}/preview`), { method: "POST" }));
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
    const data = await withBusy(gameMenu, () => apiFetch(gameUrl(`/api/delete-game/${currentIndex}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup: choice.backup, trash }),
    }));
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
  if (listing) {
    listing.innerHTML = busyHtml(t("open_gl.loading"), "open-gl-listing-empty");
    listing.setAttribute("aria-busy", "true");
  }
  try {
    const q = path ? `?path=${encodeURIComponent(path)}` : "";
    const data = await apiFetch(`/api/browse${q}`);
    __browsePath = data.path || null;
    __browseParent = data.parent || null;
    if (pathEl) pathEl.textContent = __browsePath || "—";
    const newBtn = document.getElementById("open-gl-new");
    if (newBtn) {
      newBtn.hidden = !__browsePath;
      newBtn.dataset.mode = data.has_gamelist ? "add" : "new";
      newBtn.dataset.xml = (data.files || []).filter(f => f.is_gamelist).map(f => f.path)[0] || "";
      document.getElementById("open-gl-new-label").textContent = t(data.has_gamelist ? "newgl.add_missing" : "newgl.here");
    }
    const esdeBox = document.getElementById("open-gl-esde");
    if (esdeBox) {
      esdeBox.hidden = !data.esde;
      esdeBox.dataset.path = data.esde ? data.esde.home : "";
    }
    // ES-DE writes its gamelists itself, in ES-DE/gamelists: no "Create a gamelist here"
    if (newBtn && data.esde) newBtn.hidden = true;
    if (upBtn) upBtn.disabled = !__browseParent;
    const rootBtn = document.getElementById("open-gl-root");
    if (rootBtn) rootBtn.hidden = !__browsePath;

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
  } finally {
    if (listing) listing.removeAttribute("aria-busy");
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
  renderRecentRoots();
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
  const openBtn = document.getElementById("open-gl-apply");
  if (openBtn.dataset.busy) return;
  setBusy(openBtn, true);
  try {
    const data = await apiFetch("/api/open-gamelist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    gamelistOpened(data, path);
    const label = (data.system && (data.system.label || data.system.folder)) || path;
    toast(t("toast.gamelist_opened", { name: label, n: data.count != null ? data.count : games.length }));
  } catch (e) {
    // A recent file that was moved or deleted: the server dropped it from the list
    if (e && e.code === "open_not_found") renderRecentGamelists();
    handleError(e);
  } finally {
    setBusy(openBtn, false);
  }
}

/** The server switched to another gamelist (opened or just created): show it. */
function gamelistOpened(data, path) {
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
  setStatus(t("status.ready", { n: games.length }));
  refreshSavedBatch();
  refreshSystemsSwitcher();
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
  fillColFilter();
  try {
    GENRES = await apiFetch("/static/genres.json");
  } catch (e) {
    handleError(e, t("errors.genres"));
    GENRES = {};
  }
  initGenreSelects();
  await importBrowserRecents();
  await loadGames();
  refreshSystemsSwitcher();
  reattachMultiBatch();
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
/* Answer cache: on/off, lifetime, size and "Empty the cache" */
const SS_CACHE_DAYS = [7, 14, 30, 60, 90, 180, 365];
function fillSsCache(cfg) {
  document.getElementById("ss-cache-enabled").checked = cfg.cache_enabled !== false;
  const sel = document.getElementById("ss-cache-days");
  const days = cfg.cache_days || 30;
  const choices = SS_CACHE_DAYS.includes(days) ? SS_CACHE_DAYS : [...SS_CACHE_DAYS, days].sort((a, b) => a - b);
  sel.innerHTML = choices.map(n => `<option value="${n}">${escapeHtml(t("tools.ss_cache_days_n", { n }))}</option>`).join("");
  setSelectValue(sel, String(days));
  sel.disabled = cfg.cache_enabled === false;
  showSsCacheStats(cfg.cache);
}
function showSsCacheStats(stats) {
  const s = stats || { entries: 0, bytes: 0 };
  document.getElementById("ss-cache-stats").textContent =
    t("tools.ss_cache_stats", { n: fmtCount(s.entries), size: fmtSize(s.bytes) });
  document.getElementById("btn-ss-cache-clear").disabled = !s.entries;
}
document.getElementById("btn-ss-cache-clear").addEventListener("click", async () => {
  try {
    const data = await apiFetch("/api/ss/cache/clear", { method: "POST" });
    showSsCacheStats(data);
    toast(t("toast.ss_cache_cleared"));
  } catch (e) {
    handleError(e);
  }
});

/* Settings › ScreenScraper media: per field, on/off, the ScreenScraper type
 * and the region asked first (gme/scrapers/ss.py SS_MEDIA_CHOICES). The rows
 * come from the server's list of choices; a change saves at once. */
let ssMediaReady = false;
function ssTypeLabel(code) {
  const key = "ssmedia.type_" + code.toLowerCase().replace(/-/g, "_");
  return `${t(key, null, code)} (${code})`;
}
function fillSsMedia(cfg) {
  const box = document.getElementById("ssm-rows");
  if (!box) return;
  const choices = cfg.media_choices || {};
  const types = cfg.media_types || {};
  const enabled = cfg.media_enabled || {};
  const regions = cfg.media_regions || {};
  const regionChoices = cfg.media_region_choices || [];
  const preferred = cfg.prefer_region || "fr";
  const focused = box.contains(document.activeElement) ? document.activeElement.id : null;
  box.innerHTML = getFields().filter(f => choices[f.key]).map(f => {
    const opts = choices[f.key].map(c => `<option value="${escapeHtml(c)}">${escapeHtml(ssTypeLabel(c))}</option>`).join("");
    const regs = `<option value="">${escapeHtml(t("ssmedia.region_auto", { region: regionLabel(preferred) }))}</option>` +
      regionChoices.map(c => `<option value="${c}">${escapeHtml(regionLabel(c))} (${c})</option>`).join("");
    return `<div class="ssm-row" role="row" data-field="${f.key}">` +
      `<label class="check-option" role="cell"><input type="checkbox" class="ssm-on" id="ssm-on-${f.key}"${enabled[f.key] ? " checked" : ""} />` +
      `${icon(f.icon)}<span>${escapeHtml(f.label)}</span></label>` +
      `<select class="ssm-type" id="ssm-type-${f.key}" role="cell" aria-label="${escapeHtml(f.label + " · " + t("ssmedia.col_type"))}"${choices[f.key].length < 2 ? " disabled" : ""}>${opts}</select>` +
      `<select class="ssm-region" id="ssm-region-${f.key}" role="cell" aria-label="${escapeHtml(f.label + " · " + t("ssmedia.col_region"))}">${regs}</select></div>`;
  }).join("");
  box.querySelectorAll(".ssm-row").forEach(row => {
    const field = row.dataset.field;
    setSelectValue(row.querySelector(".ssm-type"), types[field] || choices[field][0]);
    setSelectValue(row.querySelector(".ssm-region"), regions[field] || "");
    row.classList.toggle("is-off", !enabled[field]);
  });
  if (focused && document.getElementById(focused)) document.getElementById(focused).focus();
  ssMediaReady = true;
}
function ssMediaPayload() {
  if (!ssMediaReady) return {};
  const out = { media_types: {}, media_enabled: {}, media_regions: {} };
  document.querySelectorAll("#ssm-rows .ssm-row").forEach(row => {
    const field = row.dataset.field;
    out.media_types[field] = row.querySelector(".ssm-type").value;
    out.media_enabled[field] = row.querySelector(".ssm-on").checked;
    out.media_regions[field] = row.querySelector(".ssm-region").value;
  });
  return out;
}
document.getElementById("ssm-rows").addEventListener("change", e => {
  const row = e.target.closest(".ssm-row");
  if (!row) return;
  row.classList.toggle("is-off", !row.querySelector(".ssm-on").checked);
  saveSsConfig();
});

async function loadSsConfig() {
  try {
    const cfg = await apiFetch("/api/ss/config");
    document.getElementById("ss-ssid").value = cfg.ssid || "";
    fillSsRegions(cfg.prefer_region || "fr");
    fillSsThreads(cfg.threads, cfg.limits);
    fillSsCache(cfg);
    fillSsMedia(cfg);
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
    cache_enabled: document.getElementById("ss-cache-enabled").checked,
    cache_days: Number(document.getElementById("ss-cache-days").value) || 30,
    ...ssMediaPayload(),
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
["ss-ssid", "ss-sspassword", "ss-region", "ss-threads", "ss-cache-enabled", "ss-cache-days"].forEach(id => {
  document.getElementById(id).addEventListener("change", () => saveSsConfig());
});
document.getElementById("btn-ss-test").addEventListener("click", testSsConfig);

/* --- Settings › Fallback sources (LaunchBox, TheGamesDB, IGDB) ------------- */
// Fields in the scrape dialog's order (gme/scrapers/compare.py META_KEYS + MEDIA_KEYS)
const SCRAPE_FIELD_ORDER = ["name", "desc", "rating", "releasedate", "developer", "publisher", "genre", "players",
  "image", "titleshot", "thumbnail", "marquee", "wheel", "boxart", "boxback", "cartridge", "fanart"];
const FB_LABELS = { screenscraper: "ScreenScraper", launchbox: "LaunchBox", thegamesdb: "TheGamesDB", igdb: "IGDB" };
let fbConfig = null;
let lbPollTimer = 0;

async function loadFallbackConfig() {
  try {
    fbConfig = await apiFetch("/api/sources/config");
  } catch (e) {
    return;
  }
  renderFallback();
}

function fbFocusKey() {
  const el = document.activeElement;
  if (!el || !el.closest || !el.closest("#pane-fallback")) return null;
  for (const attr of ["data-fb-enable", "data-fb-move", "data-fb-field"]) {
    if (el.hasAttribute(attr)) return `[${attr}="${el.getAttribute(attr)}"]` + (el.dataset.src ? `[data-src="${el.dataset.src}"]` : "");
  }
  return null;
}

function renderFallback() {
  const cfg = fbConfig;
  if (!cfg) return;
  const focus = fbFocusKey();
  const order = cfg.order || [];
  document.getElementById("fb-order").innerHTML = order.map((src, i) => {
    const label = FB_LABELS[src] || src;
    const main = src === "screenscraper";
    const on = main || !!cfg.enabled[src];
    const ready = main || !!cfg.configured[src];
    const state = main ? "main" : !on ? "off" : ready ? "on" : "setup";
    const note = t("fallback.state_" + state);
    const check = main
      ? `<span class="fb-check-spacer" aria-hidden="true"></span>`
      : `<input type="checkbox" data-fb-enable="${src}" ${on ? "checked" : ""} aria-label="${escapeHtml(t("fallback.enable", { source: label }))}">`;
    const move = (dir, ic, key, disabled) =>
      `<button type="button" class="btn btn-sm btn-ghost fb-move" data-fb-move="${dir}" data-src="${src}" ` +
      `aria-label="${escapeHtml(t(key, { source: label }))}" data-tip="${escapeHtml(t(key, { source: label }))}"${disabled ? " disabled" : ""}>${icon(ic)}</button>`;
    return `<li class="fb-row" data-src="${src}" data-state="${state}">${check}` +
      `<span class="fb-rank">${i + 1}</span><span class="fb-name">${escapeHtml(label)}</span>` +
      `<span class="fb-note">${escapeHtml(note)}</span>` +
      move(-1, "arrow-up", "fallback.up", i === 0) + move(1, "arrow-down", "fallback.down", i === order.length - 1) +
      `</li>`;
  }).join("");
  document.getElementById("fb-continue").checked = cfg.on_ss_quota !== "stop";
  const keyPh = set => set ? t("fallback.key_saved") : "";
  document.getElementById("fb-tgdb-key").placeholder = keyPh(cfg.tgdb_apikey_set);
  document.getElementById("fb-igdb-id").placeholder = keyPh(cfg.igdb_client_id_set);
  document.getElementById("fb-igdb-cs").placeholder = keyPh(cfg.igdb_client_secret_set);
  document.getElementById("btn-tgdb-clear").hidden = !cfg.tgdb_apikey_set;
  document.getElementById("btn-igdb-clear").hidden = !(cfg.igdb_client_id_set || cfg.igdb_client_secret_set);
  // Field × source grid, sources in the chain order
  const fbs = order.filter(s => s !== "screenscraper");
  const fields = SCRAPE_FIELD_ORDER.filter(f => fbs.some(s => (cfg.supported[s] || []).includes(f)));
  document.getElementById("fb-fields").innerHTML = `<table class="fb-table"><thead><tr><th scope="col">${escapeHtml(t("fallback.col_field"))}</th>` +
    fbs.map(s => `<th scope="col">${escapeHtml(FB_LABELS[s])}</th>`).join("") + `</tr></thead><tbody>` +
    fields.map(f => `<tr><th scope="row">${escapeHtml(scrapeFieldLabel(f))}</th>` + fbs.map(s => {
      if (!(cfg.supported[s] || []).includes(f)) return `<td class="fb-na" aria-label="${escapeHtml(t("fallback.na"))}">—</td>`;
      const on = (cfg.fields[s] || []).includes(f);
      return `<td><input type="checkbox" data-fb-field="${f}" data-src="${s}" ${on ? "checked" : ""} ` +
        `aria-label="${escapeHtml(scrapeFieldLabel(f) + " · " + FB_LABELS[s])}"></td>`;
    }).join("") + `</tr>`).join("") + `</tbody></table>`;
  renderLaunchboxStatus(cfg.launchbox || {});
  if (focus) {
    const el = document.querySelector("#pane-fallback " + focus);
    if (el && !el.disabled) el.focus();
    else if (el) document.getElementById("fb-order").querySelector("button:not([disabled]), input")?.focus();
  }
}

function renderLaunchboxStatus(lb) {
  const st = document.getElementById("lb-status");
  const btn = document.getElementById("btn-lb-update");
  const bar = document.getElementById("lb-progress");
  const label = btn.querySelector("span");
  label.textContent = t(lb.ready ? "fallback.lb_update" : "fallback.lb_download");
  bar.hidden = !lb.running;
  btn.disabled = !!lb.running || (lb.ready && lb.next_in > 0);
  btn.removeAttribute("data-tip");
  if (lb.ready && lb.next_in > 0 && !lb.running) {
    btn.dataset.tip = t("fallback.lb_next", { hours: Math.max(1, Math.ceil(lb.next_in / 3600)) });
  }
  st.className = "ss-status";
  if (lb.running) {
    const pct = lb.total ? Math.min(100, Math.round(lb.done * 100 / lb.total)) : 0;
    document.getElementById("lb-progress-bar").style.width = (lb.phase === "download" ? pct : 100) + "%";
    st.textContent = lb.phase === "download"
      ? t("fallback.lb_downloading", { pct })
      : t("fallback.lb_indexing", { n: fmtCount(lb.done || 0) });
    clearTimeout(lbPollTimer);
    lbPollTimer = setTimeout(pollLaunchbox, 1000);
    return;
  }
  if (lb.error) {
    st.textContent = t("fallback.lb_error", { detail: lb.error });
    st.className = "ss-status err";
  } else if (lb.ready) {
    const when = new Date((lb.downloaded || 0) * 1000).toLocaleString(currentLocale || "fr", { dateStyle: "medium", timeStyle: "short" });
    st.textContent = t("fallback.lb_ready", { date: when, n: fmtCount(lb.games) });
    st.className = "ss-status ok";
  } else {
    st.textContent = t("fallback.lb_missing");
  }
}

async function pollLaunchbox() {
  const modal = document.getElementById("settings-modal");
  try {
    const lb = await apiFetchInner("/api/sources/launchbox");
    const wasRunning = fbConfig && fbConfig.launchbox && fbConfig.launchbox.running;
    if (fbConfig) fbConfig.launchbox = lb;
    if (!lb.running && wasRunning) {
      await loadFallbackConfig();       // ready now: the chain's states change
      if (lb.ready) toast(t("fallback.lb_done", { n: fmtCount(lb.games) }));
      return;
    }
    if (modal.classList.contains("open") || lb.running) renderLaunchboxStatus(lb);
  } catch (_) { /* next open of the settings shows it */ }
}

async function saveFallback(patch) {
  try {
    const res = await apiFetch("/api/sources/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    fbConfig = res.config;
    renderFallback();
    return true;
  } catch (e) {
    handleError(e);
    return false;
  }
}

document.getElementById("fb-order").addEventListener("change", e => {
  const box = e.target.closest("[data-fb-enable]");
  if (!box) return;
  saveFallback({ enabled: { [box.dataset.fbEnable]: box.checked } });
});
document.getElementById("fb-order").addEventListener("click", e => {
  const btn = e.target.closest("[data-fb-move]");
  if (!btn || !fbConfig) return;
  const order = fbConfig.order.slice();
  const i = order.indexOf(btn.dataset.src);
  const j = i + Number(btn.dataset.fbMove);
  if (i < 0 || j < 0 || j >= order.length) return;
  [order[i], order[j]] = [order[j], order[i]];
  saveFallback({ order });
});
document.getElementById("fb-fields").addEventListener("change", e => {
  const box = e.target.closest("[data-fb-field]");
  if (!box || !fbConfig) return;
  const src = box.dataset.src;
  const list = new Set(fbConfig.fields[src] || []);
  if (box.checked) list.add(box.dataset.fbField); else list.delete(box.dataset.fbField);
  saveFallback({ fields: { [src]: [...list] } });
});
document.getElementById("fb-continue").addEventListener("change", e => {
  saveFallback({ on_ss_quota: e.target.checked ? "continue" : "stop" });
});
[["fb-tgdb-key", "tgdb_apikey"], ["fb-igdb-id", "igdb_client_id"], ["fb-igdb-cs", "igdb_client_secret"]].forEach(([id, key]) => {
  const input = document.getElementById(id);
  input.addEventListener("change", async () => {
    const value = input.value.trim();
    if (!value) return;
    if (await saveFallback({ [key]: value })) {
      input.value = "";
      toast(t("fallback.key_saved_toast"));
    }
  });
});
document.getElementById("btn-tgdb-clear").addEventListener("click", () => saveFallback({ clear_tgdb_apikey: true }));
document.getElementById("btn-igdb-clear").addEventListener("click", () =>
  saveFallback({ clear_igdb_client_id: true, clear_igdb_client_secret: true }));

async function testFallbackSource(src, statusId, inputs) {
  const st = document.getElementById(statusId);
  // A key typed but not saved yet (it saves when the field loses the focus)
  const patch = {};
  inputs.forEach(([id, key]) => {
    const v = document.getElementById(id).value.trim();
    if (v) patch[key] = v;
  });
  if (Object.keys(patch).length) {
    if (!(await saveFallback(patch))) return;
    inputs.forEach(([id]) => { document.getElementById(id).value = ""; });
  }
  st.textContent = t("status.testing");
  st.className = "ss-status";
  try {
    const data = await apiFetch("/api/sources/test/" + src, { method: "POST" });
    let msg = t("scrape.test_ok_short");
    if (src === "thegamesdb" && data.remaining != null) {
      msg += " · " + t("fallback.tgdb_left", { n: fmtCount((data.remaining || 0) + (data.extra || 0)) });
    }
    st.textContent = msg;
    st.className = "ss-status ok";
  } catch (e) {
    st.textContent = e.message;
    st.className = "ss-status err";
  }
}
document.getElementById("btn-tgdb-test").addEventListener("click", () =>
  testFallbackSource("thegamesdb", "tgdb-status", [["fb-tgdb-key", "tgdb_apikey"]]));
document.getElementById("btn-igdb-test").addEventListener("click", () =>
  testFallbackSource("igdb", "igdb-status", [["fb-igdb-id", "igdb_client_id"], ["fb-igdb-cs", "igdb_client_secret"]]));
document.getElementById("btn-lb-update").addEventListener("click", async () => {
  try {
    const lb = await apiFetch("/api/sources/launchbox/update", { method: "POST" });
    if (fbConfig) fbConfig.launchbox = lb;
    renderLaunchboxStatus(lb);
  } catch (e) {
    handleError(e);
  }
});

const SCRAPERS = {
  screenscraper: { label: "ScreenScraper", icon: "cloud-download", scrape: "/api/ss/scrape/", apply: "/api/ss/apply/", idKey: "gameid" },
  arcadeitalia: { label: "Arcade Database", icon: "coin", scrape: "/api/adb/scrape/", apply: "/api/adb/apply/", idKey: "romset" },
  steam: { label: "Steam", icon: "brand-steam", scrape: "/api/steam/scrape/", apply: "/api/steam/apply/", idKey: "appid" },
};
const SCRAPER_PREF_KEY = "gme_scraper_by_system";     // where older versions kept it (browser)
const SCRAPE_MEDIA_ICONS = {
  image: "photo", titleshot: "heading", thumbnail: "photo", marquee: "tag", wheel: "steering-wheel", boxart: "box", boxback: "flip-horizontal",
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
let lastScrape = null;   // { source, forcedId }: "Refresh from ScreenScraper" repeats it without the cache
async function runScrape(source, forcedId, refresh = false) {
  if (currentIndex === null || ssBusy) return;
  const sc = SCRAPERS[source] || SCRAPERS.screenscraper;
  if (forcedId != null) forcedId = String(forcedId).trim() || null;
  lastScrape = { source, forcedId };
  setSsLoading(true, t(forcedId ? "scrape.loading_game" : "scrape.searching", { source: sc.label }));
  setStatus(t("scrape.status_search", { source: sc.label }));
  try {
    let data;
    try {
      data = await apiFetch(gameUrl(sc.scrape + currentIndex), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...(forcedId ? { [sc.idKey]: forcedId } : {}), ...(refresh ? { refresh: true } : {}) }),
      });
    } catch (e) {
      const d = e.data || {};
      let msg = e.message;
      if (d.hash && d.hash.crc && !msg.includes("CRC")) msg += ` · CRC ${d.hash.crc}`;
      throw new Error(msg);
    }
    showScrapeCacheNote(data);
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

/** "Answer from the cache (date)" + a button to ask ScreenScraper again. */
function showScrapeCacheNote(data) {
  const note = document.getElementById("ss-cache-note");
  const c = data && data.cache;
  note.hidden = !(c && c.hits && !c.sent);
  if (note.hidden) return;
  const when = c.time ? new Date(c.time * 1000).toLocaleDateString(currentLocale || "fr") : "?";
  document.getElementById("ss-cache-text").textContent = t("scrape.from_cache", { date: when });
}
document.getElementById("ss-cache-refresh").addEventListener("click", () => {
  if (lastScrape) runScrape(lastScrape.source, lastScrape.forcedId, true);
});

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
  return t("scrape.field_" + key, null, fieldLabel(key));
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
  const fb = data.fallback;
  if (fb) {
    const extra = (fb.used || []).filter(s => s !== "screenscraper").map(s => FB_LABELS[s] || s);
    if (fb.ss !== "ok") {
      const matched = Object.values(fb.matches || {}).find(m => m && m.name);
      let txt = t("fallback.found_only", { name: p.name || (matched && matched.name) || "?", sources: extra.join(", ") || "?" });
      txt += " · " + t(fb.ss === "blocked" ? "fallback.ss_blocked_note" : "fallback.ss_missing_note");
      return txt + fallbackErrorsText(fb);
    }
    if (extra.length) {
      return scrapeInfoTextBase(source, data, picked) + " · " + t("fallback.completed", { sources: extra.join(", ") }) +
        fallbackErrorsText(fb);
    }
    return scrapeInfoTextBase(source, data, picked) + fallbackErrorsText(fb);
  }
  return scrapeInfoTextBase(source, data, picked);
}
function fallbackErrorsText(fb) {
  return Object.entries(fb.errors || {}).map(([s, msg]) => " · " + labelValue(FB_LABELS[s] || s, msg)).join("");
}
function scrapeInfoTextBase(source, data, picked) {
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
/** "ScreenScraper, LaunchBox…": the sources asked for this scrape. */
function scrapeSourcesLabel(sc, data) {
  const chain = (data.fallback && data.fallback.chain) || [];
  return [sc.label, ...chain.map(s => FB_LABELS[s] || s)].join(", ");
}
/** Where a field comes from when it is not ScreenScraper (fallback sources). */
function scrapeSourceChip(r) {
  if (!r.source || r.source === "screenscraper") return "";
  const label = FB_LABELS[r.source] || r.source;
  return `<span class="ss-src" data-src="${escapeHtml(r.source)}" title="${escapeHtml(t("fallback.from", { source: label }))}">${escapeHtml(label)}</span>`;
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
    `<span class="ss-card-title">${icon(ic)}<span>${escapeHtml(label)}</span></span>${scrapeSourceChip(r)}${scrapeBadge(r.status)}</span>` +
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
    `<span class="ss-meta-label"><span>${escapeHtml(scrapeFieldLabel(r.key))}</span>${scrapeSourceChip(r)}${scrapeBadge(r.status)}</span>` +
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
  if (none.length) rest.push(`<p class="ss-rest">${icon("x")}<span><b>${escapeHtml(t("scrape.rest_unavailable", { source: scrapeSourcesLabel(sc, data) }))}</b> ${names(none)}</span></p>`);
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

/* ========== Edit in bulk (Actions › Edit in bulk, selection bar) ==========
 * Scope: the ticked games, the games shown, or the whole gamelist. Every
 * operation is previewed first (/api/bulk/preview), and Apply stays disabled
 * until a preview found something to change; any change to the form drops the
 * preview. The server makes a dated snapshot before writing and returns its
 * id: the toast's Undo restores it (/api/backups/restore). Removing games only
 * takes entries out of gamelist.xml (media to the Recycle Bin on request, ROMs
 * never), see gme/bulk.py.
 */
const BULK_SET_FIELDS = ["genre", "developer", "publisher", "releasedate", "rating", "players", "lang", "region",
  "family", "arcadesystemname", "favorite", "hidden", "kidgame"];
const BULK_FLAGS = ["favorite", "hidden", "kidgame"];
const BULK_REPLACE_FIELDS = ["name", "desc", "genre", "developer", "publisher", "players", "lang", "region",
  "family", "arcadesystemname"];
/* Clear fields: the whole elements go (gme/bulk.py CLEAR_FIELDS); the
 * technical tags after BULK_CLEAR_MAIN are only listed when some game has them. */
const BULK_CLEAR_MAIN = ["genre", "developer", "publisher", "releasedate", "rating", "players", "lang", "region",
  "family", "arcadesystemname", "desc", "favorite", "hidden", "kidgame"];
const BULK_CLEAR_EXTRA = ["sortname", "playcount", "lastplayed", "gametime", "genreid", "md5", "crc32", "cheevosId", "cheevosHash"];
const BULK_TABS = ["set", "clear_fields", "replace", "reset_name", "images", "solid", "clear_media", "delete"];
let bulk = null;   // { tab, preview: {...} | null, busy, form: {...} }

function bulkFieldLabel(key) {
  if (BULK_FLAGS.includes(key)) return t("editor." + key);
  if (BULK_CLEAR_EXTRA.includes(key)) return t("bulk.tag_" + key.toLowerCase());
  if (key === "desc" || COL_META.includes(key)) return t("scrape.field_" + key);
  return fieldLabel(key);
}
function bulkPaths(scope) {
  const out = new Set();
  if (scope === "checked") {
    const known = new Set(games.map(g => g.path));
    selection.forEach(p => { if (known.has(p)) out.add(p); });
  } else if (scope === "shown") {
    viewIndices.forEach(i => out.add(games[i].path));
  } else {
    games.forEach(g => out.add(g.path));
  }
  return [...out];
}
function fillBulkScope(preferred) {
  const sel = document.getElementById("bulk-scope");
  const counts = { checked: bulkPaths("checked").length, shown: bulkPaths("shown").length, all: bulkPaths("all").length };
  sel.innerHTML = ["checked", "shown", "all"].map(k =>
    `<option value="${k}"${counts[k] ? "" : " disabled"}>${escapeHtml(t("bulk.scope_" + k, { n: fmtCount(counts[k]) }))}</option>`
  ).join("");
  const order = [preferred, "checked", "shown", "all"].filter(Boolean);
  sel.value = order.find(k => counts[k]) || "all";
}
function openBulk(tab, opts) {
  if (!window.__gmeLoaded || !games.length) return;
  if (changedFields().length) {
    toast(t("bulk.unsaved"), "warning");
    return;
  }
  opts = opts || {};
  bulk = { tab: BULK_TABS.includes(tab) ? tab : "set", preview: null, busy: false, nameSource: opts.source || "file", dat: null,
    clear: new Set(opts.fields || []), counts: null };
  fillBulkScope(opts.scope || (selection.size ? "checked" : "shown"));
  renderBulkForm();
  document.getElementById("bulk-modal").classList.add("open");
  const first = document.querySelector("#bulk-form select, #bulk-form input");
  (first || document.getElementById("bulk-scope")).focus();
}
function closeBulk() {
  const modal = document.getElementById("bulk-modal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  bulk = null;
  document.getElementById("bulk-form").innerHTML = "";
  document.getElementById("bulk-preview").innerHTML = "";
}
function renderBulkForm() {
  document.querySelectorAll("#bulk-tabs [data-bulk-tab]").forEach(b => {
    const on = b.dataset.bulkTab === bulk.tab;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
  });
  const form = document.getElementById("bulk-form");
  const opt = (k, label) => `<option value="${k}">${escapeHtml(label)}</option>`;
  const check = (id, key, on) =>
    `<label class="bulk-check"><input type="checkbox" id="${id}"${on ? " checked" : ""}> <span>${escapeHtml(t(key))}</span></label>`;
  let html = "";
  if (bulk.tab === "set") {
    html = `<div class="bulk-grid">
      <label><span>${escapeHtml(t("bulk.field"))}</span><select id="bulk-set-field">${BULK_SET_FIELDS.map(k => opt(k, bulkFieldLabel(k))).join("")}</select></label>
      <label><span>${escapeHtml(t("bulk.value"))}</span><span id="bulk-set-value-wrap"></span></label>
    </div><p class="bulk-hint" id="bulk-set-hint"></p>`;
  } else if (bulk.tab === "replace") {
    html = `<div class="bulk-grid">
      <label><span>${escapeHtml(t("bulk.in_field"))}</span><select id="bulk-rep-field">${opt("all", t("bulk.all_fields"))}${BULK_REPLACE_FIELDS.map(k => opt(k, bulkFieldLabel(k))).join("")}</select></label>
      <label><span>${escapeHtml(t("bulk.find"))}</span><input type="text" id="bulk-rep-find" spellcheck="false" autocomplete="off" maxlength="1000"></label>
      <label><span>${escapeHtml(t("bulk.replace_with"))}</span><input type="text" id="bulk-rep-with" spellcheck="false" autocomplete="off"></label>
    </div><div class="bulk-checks">${check("bulk-rep-regex", "bulk.regex", false)}${check("bulk-rep-case", "bulk.case", false)}</div>
    <p class="bulk-hint">${escapeHtml(t("bulk.replace_hint"))}</p>`;
  } else if (bulk.tab === "reset_name") {
    const src = bulk.nameSource;
    const radio = (v, key) => `<label class="bulk-check"><input type="radio" name="bulk-name-src" value="${v}"${src === v ? " checked" : ""}> <span>${escapeHtml(t(key))}</span></label>`;
    html = `<div class="bulk-checks bulk-name-src">${radio("file", "bulk.names_from_file")}${radio("dat", "bulk.names_from_dat")}</div>
      <p class="bulk-hint">${escapeHtml(t(src === "dat" ? "bulk.names_dat_hint" : "bulk.names_hint"))}</p>
      ${src === "dat" ? `<div class="bulk-dat" id="bulk-dat"><span class="bulk-dat-info" id="bulk-dat-info">${busyHtml(t("stats.loading"), "", "span")}</span><div class="dat-load" id="bulk-dat-load"></div></div>` : ""}
      <div class="bulk-checks">${check("bulk-name-tags", "bulk.strip_tags", src !== "dat")}</div>`;
  } else if (bulk.tab === "images") {
    const fields = getFields().filter(f => isImageField(f.key));
    html = `<p class="bulk-hint">${escapeHtml(t("imgedit.batch_hint"))}</p>
      <div class="bulk-grid bulk-img-grid">
        <label><span>${escapeHtml(t("imgedit.batch_field"))}</span><select id="bulk-img-field">${fields.map(f => opt(f.key, f.label)).join("")}</select></label>
        <label><span>${escapeHtml(t("imgedit.max_w"))}</span><input type="number" id="bulk-img-max-w" min="0" max="16384" placeholder="—"></label>
        <label><span>${escapeHtml(t("imgedit.max_h"))}</span><input type="number" id="bulk-img-max-h" min="0" max="16384" placeholder="—"></label>
        <label><span>${escapeHtml(t("imgedit.format"))}</span><select id="bulk-img-format">${opt("keep", t("imgedit.format_keep"))}${opt("png", "PNG")}${opt("jpg", "JPG")}${opt("webp", "WebP")}</select></label>
        <label><span>${escapeHtml(t("imgedit.quality"))}</span><input type="number" id="bulk-img-quality" min="1" max="100" value="90"></label>
      </div>
      <div class="bulk-checks">${check("bulk-img-trim", "imgedit.trim_hint", false)}${check("bulk-img-upscale", "imgedit.upscale", false)}</div>`;
  } else if (bulk.tab === "clear_fields") {
    html = `<p class="bulk-hint">${escapeHtml(t("bulk.clear_hint"))}</p>
      <div class="bulk-checks bulk-clear-list" id="bulk-clear-list" aria-busy="true">${busyHtml(t("stats.loading"), "bulk-empty", "span")}</div>`;
  } else if (bulk.tab === "solid") {
    /* Solid images: pictures of one colour or fully transparent (gme/solidimages.py). */
    html = `<p class="bulk-hint">${escapeHtml(t("bulk.solid_hint"))}</p>
      <div class="bulk-checks bulk-media-list">${getFields().filter(f => isImageField(f.key)).map(f =>
        `<label class="bulk-check"><input type="checkbox" data-bulk-solid="${f.key}" checked> ${icon(f.icon)}<span>${escapeHtml(f.label)}</span></label>`).join("")}</div>
      <div class="bulk-checks">${check("bulk-solid-files", "bulk.solid_files", false)}</div>
      <p class="bulk-hint">${icon("shield-check")}<span>${escapeHtml(t("bulk.solid_files_hint"))}</span></p>`;
  } else if (bulk.tab === "clear_media") {
    html = `<p class="bulk-hint">${escapeHtml(t("bulk.media_hint"))}</p>
      <div class="bulk-checks bulk-media-list">${getFields().map(f =>
        `<label class="bulk-check"><input type="checkbox" data-bulk-media="${f.key}"> ${icon(f.icon)}<span>${escapeHtml(f.label)}</span></label>`).join("")}</div>`;
  } else {
    html = `<p class="bulk-hint bulk-warn">${icon("alert-triangle")}<span>${escapeHtml(t("bulk.delete_hint"))}</span></p>
      <div class="bulk-checks">${check("bulk-del-media", "bulk.delete_media", false)}</div>`;
  }
  form.innerHTML = html;
  if (bulk.tab === "set") renderBulkSetValue();
  if (bulk.tab === "reset_name" && bulk.nameSource === "dat") refreshBulkDat();
  if (bulk.tab === "clear_fields") refreshBulkClear();
  invalidateBulkPreview();
}
/* Edit in bulk › Clear fields: one box per tag, with the number of games of
 * the scope that have it (/api/bulk/fields); re-counted when the scope changes. */
async function refreshBulkClear() {
  if (!bulk || bulk.tab !== "clear_fields") return;
  const paths = bulkPaths(document.getElementById("bulk-scope").value);
  let counts = {};
  try {
    const d = await apiFetch("/api/bulk/fields", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paths }),
    });
    counts = d.counts || {};
  } catch (e) { handleError(e); }
  const box = document.getElementById("bulk-clear-list");
  if (!bulk || bulk.tab !== "clear_fields" || !box) return;
  bulk.counts = counts;
  const keys = BULK_CLEAR_MAIN.concat(BULK_CLEAR_EXTRA.filter(k => counts[k]));
  box.removeAttribute("aria-busy");
  box.innerHTML = keys.map(k => {
    const n = counts[k] || 0;
    return `<label class="bulk-check${n ? "" : " is-empty"}"><input type="checkbox" data-bulk-clear="${k}"${bulk.clear.has(k) ? " checked" : ""}>` +
      ` <span>${escapeHtml(bulkFieldLabel(k))}</span> <code class="bulk-tag">&lt;${k}&gt;</code>` +
      `<span class="bulk-count" title="${escapeHtml(t("bulk.clear_count", { n: fmtCount(n) }))}">${escapeHtml(fmtCount(n))}</span></label>`;
  }).join("");
}
/* Edit in bulk › Names › from a DAT / MAME list: the one loaded in the DAT
 * tool, or one loaded here with the same controls. */
async function refreshBulkDat(d) {
  try {
    d = d || await apiFetch("/api/dat");
  } catch (e) { d = { dat: null }; }
  if (!bulk || bulk.tab !== "reset_name" || bulk.nameSource !== "dat") return;
  bulk.dat = d.dat;
  const info = document.getElementById("bulk-dat-info");
  info.innerHTML = `${icon("database")}<span>${escapeHtml(datInfoText(d.dat))}</span>` +
    (d.report ? `<span class="bulk-dat-matched">${escapeHtml(t("bulk.names_dat_report"))}</span>` : "");
  const load = document.getElementById("bulk-dat-load");
  load.innerHTML = datLoadControlsHtml("bulk-dat", d.mame_xml);
  bindDatLoadControls("bulk-dat", async source => {
    info.innerHTML = `${icon("database")}${busyHtml(t("dat.loading", { pct: 0 }), "", "span")}`;
    load.querySelectorAll("button, input").forEach(el => { el.disabled = true; });
    try {
      const done = await datLoad(source, s => {
        const j = s.job;
        if (j && j.state === "running") {
          info.innerHTML = `${icon("database")}${busyHtml(t("dat.loading", { pct: j.total ? Math.round(j.done * 100 / j.total) : 0 }), "", "span")}`;
        }
      });
      refreshBulkDat(done);
      invalidateBulkPreview();
    } catch (e) {
      handleError(e);
      refreshBulkDat();
    }
  });
}
function renderBulkSetValue() {
  const field = document.getElementById("bulk-set-field").value;
  const wrap = document.getElementById("bulk-set-value-wrap");
  if (BULK_FLAGS.includes(field)) {
    wrap.innerHTML = `<select id="bulk-set-value"><option value="true">${escapeHtml(t("bulk.flag_on"))}</option>` +
      `<option value="">${escapeHtml(t("bulk.flag_off"))}</option></select>`;
  } else {
    const ph = field === "releasedate" ? t("bulk.date_placeholder") : field === "rating" ? "0 – 1" : "";
    wrap.innerHTML = `<input type="text" id="bulk-set-value" autocomplete="off" spellcheck="false" placeholder="${escapeHtml(ph)}">`;
  }
  const hint = document.getElementById("bulk-set-hint");
  hint.textContent = BULK_FLAGS.includes(field) ? "" :
    field === "releasedate" ? t("bulk.date_hint") : field === "rating" ? t("bulk.rating_hint") : t("bulk.empty_clears");
}
function bulkOp() {
  const v = id => document.getElementById(id);
  if (bulk.tab === "set") return { kind: "set", field: v("bulk-set-field").value, value: v("bulk-set-value").value };
  if (bulk.tab === "replace") {
    const f = v("bulk-rep-field").value;
    return { kind: "replace", fields: f === "all" ? "all" : [f], find: v("bulk-rep-find").value,
      replace: v("bulk-rep-with").value, regex: v("bulk-rep-regex").checked, case: v("bulk-rep-case").checked };
  }
  if (bulk.tab === "reset_name") {
    return { kind: bulk.nameSource === "dat" ? "dat_name" : "reset_name", strip_tags: v("bulk-name-tags").checked };
  }
  if (bulk.tab === "images") {
    const ops = { format: v("bulk-img-format").value, quality: Number(v("bulk-img-quality").value) || 90 };
    if (v("bulk-img-trim").checked) ops.trim = { tolerance: 5 };
    const mw = parseInt(v("bulk-img-max-w").value, 10) || 0, mh = parseInt(v("bulk-img-max-h").value, 10) || 0;
    if (mw > 0 || mh > 0) ops.resize = { max_w: Math.max(0, mw), max_h: Math.max(0, mh), upscale: v("bulk-img-upscale").checked };
    return { kind: "images", field: v("bulk-img-field").value, ops };
  }
  if (bulk.tab === "clear_fields") {
    return { kind: "clear_fields", fields: [...document.querySelectorAll("[data-bulk-clear]:checked")].map(c => c.dataset.bulkClear) };
  }
  if (bulk.tab === "solid") {
    return { kind: "solid", fields: [...document.querySelectorAll("[data-bulk-solid]:checked")].map(c => c.dataset.bulkSolid),
      files: v("bulk-solid-files").checked };
  }
  if (bulk.tab === "clear_media") {
    return { kind: "clear_media", fields: [...document.querySelectorAll("[data-bulk-media]:checked")].map(c => c.dataset.bulkMedia) };
  }
  return null;
}
function invalidateBulkPreview() {
  if (!bulk) return;
  bulk.preview = null;
  const apply = document.getElementById("bulk-apply");
  apply.disabled = true;
  const danger = bulk.tab === "delete" || (bulk.tab === "solid" && document.getElementById("bulk-solid-files").checked);
  apply.classList.toggle("btn-danger", danger);
  apply.classList.toggle("btn-accent", !danger);
  document.getElementById("bulk-apply-label").textContent = t(bulk.tab === "delete" ? "bulk.remove" : "bulk.apply");
  document.getElementById("bulk-note").textContent = t(bulk.tab === "images" ? "imgedit.batch_note" : "bulk.backup_note");
  document.getElementById("bulk-preview").innerHTML = `<p class="bulk-empty">${escapeHtml(t("bulk.preview_first"))}</p>`;
}
async function runBulkPreview() {
  if (!bulk || bulk.busy) return;
  const paths = bulkPaths(document.getElementById("bulk-scope").value);
  const box = document.getElementById("bulk-preview");
  if (bulk.tab === "clear_media" && !bulkOp().fields.length) {
    box.innerHTML = `<p class="bulk-empty">${escapeHtml(t("bulk.pick_media"))}</p>`;
    return;
  }
  if (bulk.tab === "solid" && !bulkOp().fields.length) {
    box.innerHTML = `<p class="bulk-empty">${escapeHtml(t("bulk.pick_media"))}</p>`;
    return;
  }
  if (bulk.tab === "clear_fields" && !bulkOp().fields.length) {
    box.innerHTML = `<p class="bulk-empty">${escapeHtml(t("bulk.pick_field"))}</p>`;
    return;
  }
  bulk.busy = true;
  const tab = bulk.tab;
  const previewBtn = document.getElementById("bulk-preview-btn");
  setBusy(previewBtn, true);
  box.setAttribute("aria-busy", "true");
  box.innerHTML = busyHtml(t(tab === "solid" ? "bulk.solid_scanning" : "imgedit.loading"));
  try {
    let data;
    if (tab === "delete") {
      const media = document.getElementById("bulk-del-media").checked;
      data = await apiFetch("/api/bulk-delete/preview", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paths, media }),
      });
      if (!bulk || bulk.tab !== tab) return;
      bulk.preview = { paths, media, data };
      box.innerHTML = bulkDeletePreviewHtml(data, media);
    } else if (tab === "solid") {
      const op = bulkOp();
      data = await apiFetch("/api/solid-images/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths, fields: op.fields, files: op.files }),
      });
      if (!bulk || bulk.tab !== tab) return;
      bulk.preview = data.total ? { paths, op, data } : null;
      box.innerHTML = bulkSolidPreviewHtml(data, op.files);
    } else if (tab === "images") {
      const op = bulkOp();
      data = await apiFetch("/api/image-edit/batch/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths, field: op.field, ops: op.ops }),
      });
      if (!bulk || bulk.tab !== tab) return;
      const worth = data.total && (data.rows.length || data.checked < data.total);
      bulk.preview = worth ? { paths, op, data } : null;
      box.innerHTML = bulkImagesPreviewHtml(data);
    } else {
      const op = bulkOp();
      data = await apiFetch("/api/bulk/preview", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paths, op }),
      });
      if (!bulk || bulk.tab !== tab) return;
      bulk.preview = data.total ? { paths, op, data } : null;
      box.innerHTML = bulkPreviewHtml(data, op);
    }
    const n = tab === "delete" ? data.games : tab === "images" ? (bulk.preview ? data.total : 0) : data.total;
    const apply = document.getElementById("bulk-apply");
    apply.disabled = !n;
    document.getElementById("bulk-apply-label").textContent = n
      ? t(tab === "delete" ? "bulk.remove_n" : tab === "images" ? "imgedit.batch_apply_n" : "bulk.apply_n", { n: fmtCount(n) })
      : t(tab === "delete" ? "bulk.remove" : "bulk.apply");
  } catch (e) {
    if (bulk) {
      bulk.preview = null;
      box.innerHTML = `<p class="bulk-empty bulk-error">${icon("alert-circle")}<span>${escapeHtml(e.message || String(e))}</span></p>`;
    }
  } finally {
    if (bulk) bulk.busy = false;
    setBusy(previewBtn, false);
    box.removeAttribute("aria-busy");
  }
}
function bulkDiffHtml(text) {
  return text === "" ? `<em class="bulk-none">${escapeHtml(t("bulk.empty_value"))}</em>` : escapeHtml(text);
}
function bulkPreviewHtml(data, op) {
  if (!data.total) return `<p class="bulk-empty">${escapeHtml(t("bulk.nothing"))}</p>`;
  const rows = data.changes.map(c => `<tr>
      <td class="bulk-game" title="${escapeHtml(c.path)}">${escapeHtml(c.name || c.path)}</td>
      <td class="bulk-field">${escapeHtml(bulkFieldLabel(c.field))}</td>
      <td class="bulk-before">${bulkDiffHtml(op.kind !== "replace" && BULK_FLAGS.includes(c.field) ? (c.before ? t("bulk.flag_on") : "") : c.before)}</td>
      <td class="bulk-arrow" aria-hidden="true">→</td>
      <td class="bulk-after">${op.kind === "clear_fields" ? `<em class="bulk-none">${escapeHtml(t("bulk.tag_removed"))}</em>`
        : bulkDiffHtml(op.kind === "set" && BULK_FLAGS.includes(c.field) ? (c.after ? t("bulk.flag_on") : "") : c.after)}</td>
    </tr>`).join("");
  const more = data.total > data.changes.length
    ? `<p class="bulk-more">${escapeHtml(t("bulk.more", { n: fmtCount(data.total - data.changes.length) }))}</p>` : "";
  return `<p class="bulk-summary">${escapeHtml(t("bulk.summary", { changes: fmtCount(data.total), games: fmtCount(data.games) }))}</p>
    <table class="bulk-table"><thead><tr><th>${escapeHtml(t("bulk.col_game"))}</th><th>${escapeHtml(t("bulk.field"))}</th>
    <th>${escapeHtml(t("bulk.col_before"))}</th><th></th><th>${escapeHtml(t("bulk.col_after"))}</th></tr></thead>
    <tbody>${rows}</tbody></table>${more}`;
}
function bulkSolidPreviewHtml(data, files) {
  let html = `<p class="bulk-summary">${escapeHtml(t("bulk.solid_summary", { n: fmtCount(data.total), games: fmtCount(data.games), checked: fmtCount(data.checked) }))}</p>`;
  if (data.missing) html += `<p class="bulk-hint">${escapeHtml(t("bulk.solid_missing", { n: fmtCount(data.missing) }))}</p>`;
  if (!data.total) return html + `<p class="bulk-empty">${escapeHtml(t("bulk.solid_none"))}</p>`;
  const swatch = c => c === "transparent"
    ? `<span class="solid-swatch is-transparent" aria-hidden="true"></span><span>${escapeHtml(t("bulk.solid_transparent"))}</span>`
    : `<span class="solid-swatch" style="background:${escapeHtml(c)}" aria-hidden="true"></span><code>${escapeHtml(c)}</code>`;
  const rows = data.rows.map(r => `<tr>
      <td class="solid-thumb"><img src="${escapeHtml(thumbUrl(r.file))}" alt="" loading="lazy"></td>
      <td class="bulk-game" title="${escapeHtml(r.path)}">${escapeHtml(r.name || r.path)}</td>
      <td class="bulk-field">${escapeHtml(fieldLabel(r.field))}</td>
      <td class="solid-colour">${swatch(r.colour)}</td>
      <td class="bulk-field" title="${escapeHtml(r.file)}">${escapeHtml(baseName(r.file))} <span class="bulk-size">${r.width} × ${r.height}</span></td>
    </tr>`).join("");
  html += `<table class="bulk-table solid-table"><thead><tr><th></th><th>${escapeHtml(t("bulk.col_game"))}</th><th>${escapeHtml(t("bulk.col_media"))}</th>
    <th>${escapeHtml(t("bulk.col_colour"))}</th><th>${escapeHtml(t("imgedit.col_file"))}</th></tr></thead><tbody>${rows}</tbody></table>`;
  if (data.total > data.rows.length) {
    html += `<p class="bulk-more">${escapeHtml(t("bulk.more", { n: fmtCount(data.total - data.rows.length) }))}</p>`;
  }
  if (files) {
    html += `<p class="bulk-summary">${escapeHtml(t("bulk.solid_files_summary", { n: fmtCount(data.delete_total), size: fmtSize(data.delete_bytes) }))}</p>`;
    if (data.kept_total) {
      html += `<p class="bulk-hint">${escapeHtml(t("bulk.solid_kept", { n: fmtCount(data.kept_total) }))}</p>` +
        `<ul class="bulk-list">${data.kept.map(k => `<li><code>${escapeHtml(k.path)}</code> <span class="bulk-size">${escapeHtml(t("bulk.solid_kept_" + k.reason))}</span></li>`).join("")}</ul>`;
    }
  }
  return html;
}
function bulkImgSide(s) {
  return `${s.width} × ${s.height} · ${escapeHtml(String(s.format).toUpperCase())} · ${escapeHtml(fmtSize(s.bytes))}`;
}
function bulkImagesPreviewHtml(data) {
  let html = `<p class="bulk-summary">${escapeHtml(t("imgedit.batch_summary", { n: fmtCount(data.total), checked: fmtCount(data.checked),
    changed: fmtCount(data.rows.length), same: fmtCount(data.unchanged) }))}</p>`;
  if (data.missing) html += `<p class="bulk-hint">${escapeHtml(t("imgedit.batch_missing", { n: fmtCount(data.missing) }))}</p>`;
  if (data.failed) html += `<p class="bulk-hint bulk-warn">${icon("alert-triangle")}<span>${escapeHtml(t("imgedit.batch_failed", { n: fmtCount(data.failed) }))}</span></p>`;
  if (!data.rows.length) return html + (data.checked >= data.total ? `<p class="bulk-empty">${escapeHtml(t("bulk.nothing"))}</p>` : "");
  const rows = data.rows.map(r => `<tr>
      <td class="bulk-game" title="${escapeHtml(r.path)}">${escapeHtml(r.name || r.path)}</td>
      <td class="bulk-field" title="${escapeHtml(r.file)}">${escapeHtml(baseName(r.file))}</td>
      <td class="bulk-before">${bulkImgSide(r.before)}</td>
      <td class="bulk-arrow" aria-hidden="true">→</td>
      <td class="bulk-after">${bulkImgSide(r.after)}</td>
    </tr>`).join("");
  return html + `<table class="bulk-table"><thead><tr><th>${escapeHtml(t("bulk.col_game"))}</th><th>${escapeHtml(t("imgedit.col_file"))}</th>
    <th>${escapeHtml(t("bulk.col_before"))}</th><th></th><th>${escapeHtml(t("bulk.col_after"))}</th></tr></thead>
    <tbody>${rows}</tbody></table>` +
    (data.checked < data.total ? `<p class="bulk-more">${escapeHtml(t("bulk.more", { n: fmtCount(data.total - data.checked) }))}</p>` : "");
}
function bulkDeletePreviewHtml(data, media) {
  const list = items => `<ul class="bulk-list">${items.join("")}</ul>`;
  let html = `<p class="bulk-summary">${escapeHtml(t("bulk.delete_summary", { n: fmtCount(data.games) }))}</p>` +
    list(data.names.map(n => `<li>${escapeHtml(n)}</li>`));
  if (data.games > data.names.length) {
    html += `<p class="bulk-more">${escapeHtml(t("bulk.more", { n: fmtCount(data.games - data.names.length) }))}</p>`;
  }
  if (media) {
    html += `<p class="bulk-summary">${escapeHtml(t("bulk.delete_media_summary", { n: fmtCount(data.media_total), size: fmtSize(data.media_bytes) }))}</p>`;
    if (data.media.length) html += list(data.media.map(m => `<li><code>${escapeHtml(m.path)}</code> <span class="bulk-size">${escapeHtml(fmtSize(m.size))}</span></li>`));
    if (data.kept_total) {
      html += `<p class="bulk-hint">${escapeHtml(t("bulk.delete_kept", { n: fmtCount(data.kept_total) }))}</p>`;
    }
  }
  html += `<p class="bulk-hint">${icon("shield-check")}<span>${escapeHtml(t("bulk.roms_kept"))}</span></p>`;
  return html;
}
async function applyBulk() {
  if (!bulk || bulk.busy || !bulk.preview) return;
  const { paths } = bulk.preview;
  const tab = bulk.tab;
  if (tab === "delete") {
    const { media, data } = bulk.preview;
    const body = `<p>${escapeHtml(t("bulk.delete_confirm", { n: fmtCount(data.games) }))}</p>` +
      (media && data.media_total ? `<p>${escapeHtml(t("bulk.delete_media_summary", { n: fmtCount(data.media_total), size: fmtSize(data.media_bytes) }))}</p>` : "") +
      `<p class="muted">${escapeHtml(t("bulk.roms_kept"))}</p>`;
    const choice = await askConfirm({ title: t("bulk.delete_title"), bodyHtml: body, showBackup: false,
      okLabel: t("bulk.remove_n", { n: fmtCount(data.games) }), okClass: "btn-danger" });
    if (!choice.confirmed || !bulk) return;
  }
  if (tab === "solid") {
    const { op, data } = bulk.preview;
    let body = `<p>${escapeHtml(t("bulk.solid_confirm", { n: fmtCount(data.total), games: fmtCount(data.games) }))}</p>`;
    if (op.files && data.delete_total) {
      body += `<p class="bulk-warn"><strong>${escapeHtml(t("bulk.solid_confirm_files", { n: fmtCount(data.delete_total), size: fmtSize(data.delete_bytes) }))}</strong></p>`;
    }
    if (op.files && data.kept_total) body += `<p>${escapeHtml(t("bulk.solid_kept", { n: fmtCount(data.kept_total) }))}</p>`;
    body += `<p class="muted">${escapeHtml(t("bulk.roms_kept"))}</p>`;
    const choice = await askConfirm({ title: t("bulk.solid_title"), bodyHtml: body, showBackup: false,
      okLabel: op.files && data.delete_total ? t("bulk.solid_ok_files", { n: fmtCount(data.delete_total) }) : t("bulk.solid_ok", { n: fmtCount(data.total) }),
      okClass: "btn-danger" });
    if (!choice.confirmed || !bulk) return;
  }
  if (tab === "clear_fields") {
    const { op, data } = bulk.preview;
    const body = `<p>${escapeHtml(t("bulk.clear_confirm", { fields: op.fields.map(bulkFieldLabel).join(", "), n: fmtCount(data.games) }))}</p>` +
      `<p class="muted">${escapeHtml(t("bulk.backup_note"))}</p>`;
    const choice = await askConfirm({ title: t("bulk.clear_title"), bodyHtml: body, showBackup: false,
      okLabel: t("bulk.clear_n", { n: fmtCount(data.games) }), okClass: "btn-danger" });
    if (!choice.confirmed || !bulk) return;
  }
  bulk.busy = true;
  const applyBtn = document.getElementById("bulk-apply");
  setBusy(applyBtn, true);
  try {
    let res, msg;
    if (tab === "delete") {
      res = await apiFetch("/api/bulk-delete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths, media: bulk.preview.media, trash: true }),
      });
      paths.forEach(p => selection.delete(p));
      selectionChanged(false);
      msg = t("bulk.removed", { n: fmtCount(res.removed) });
      if (res.deleted_files.length) msg += " " + t("bulk.removed_files", { n: fmtCount(res.deleted_files.length) });
      if (res.failed_files.length) msg += " " + t("bulk.failed_files", { n: fmtCount(res.failed_files.length) });
    } else if (tab === "solid") {
      const op = bulk.preview.op;
      res = await apiFetch("/api/solid-images", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths, fields: op.fields, files: op.files }),
      });
      msg = t("bulk.solid_applied", { n: fmtCount(res.removed), games: fmtCount(res.games) });
      if (res.deleted_files.length) msg += " " + t("bulk.removed_files", { n: fmtCount(res.deleted_files.length) });
      if (res.failed_files.length) msg += " " + t("bulk.failed_files", { n: fmtCount(res.failed_files.length) });
    } else if (tab === "images") {
      const op = bulk.preview.op;
      res = await apiFetch("/api/image-edit/batch", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths, field: op.field, ops: op.ops }),
      });
      stampMedia(res.paths);
      msg = t("imgedit.batch_applied", { n: fmtCount(res.changed) });
      if (res.renamed) msg += " " + t("imgedit.batch_renamed", { n: fmtCount(res.renamed) });
      if (res.failed.length) msg += " " + t("imgedit.batch_failed", { n: fmtCount(res.failed.length) });
      closeBulk();
      await loadGames();
      const undo = res.undo, renamed = !!res.renamed;
      toast(msg, res.failed.length ? "warning" : "success",
        undo ? { label: t("bulk.undo"), run: () => undoImageEdit(undo, renamed) } : null);
      return;
    } else {
      res = await apiFetch("/api/bulk", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths, op: bulk.preview.op }),
      });
      msg = t("bulk.applied", { changes: fmtCount(res.changed), games: fmtCount(res.games) });
    }
    closeBulk();
    if (tab === "delete") resetEditorSelection();
    await loadGames();
    const snapshot = res.snapshot;
    toast(msg, res.failed_files && res.failed_files.length ? "warning" : "success",
      snapshot ? { label: t("bulk.undo"), run: () => undoBulk(snapshot, (tab === "delete" || tab === "solid") && res.deleted_files.length) } : null);
  } catch (e) {
    handleError(e);
    if (bulk) { bulk.busy = false; invalidateBulkPreview(); }
  } finally {
    if (bulk) bulk.busy = false;
    setBusy(applyBtn, false, { restore: false });
  }
}
async function undoBulk(snapshot, filesInTrash) {
  if (changedFields().length) {
    const choice = await askConfirm({ title: t("bulk.undo"), bodyHtml: `<p>${escapeHtml(t("bulk.undo_unsaved"))}</p>`,
      showBackup: false, okLabel: t("bulk.undo") });
    if (!choice.confirmed) return;
  }
  try {
    const data = await apiFetch("/api/backups/restore", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: snapshot }),
    });
    window.__gmeSession = data.session_id;
    resetEditorSelection();
    await loadGames();
    toast(filesInTrash ? t("bulk.undone_trash") : t("bulk.undone"), filesInTrash ? "info" : "success");
  } catch (e) { handleError(e); }
}

document.getElementById("btn-bulk").addEventListener("click", () => openBulk());
document.getElementById("btn-bulk-selection").addEventListener("click", () => openBulk());
document.getElementById("bulk-close").addEventListener("click", closeBulk);
document.getElementById("bulk-cancel").addEventListener("click", closeBulk);
document.getElementById("bulk-modal").addEventListener("click", e => { if (e.target.id === "bulk-modal") closeBulk(); });
document.getElementById("bulk-tabs").addEventListener("click", e => {
  const b = e.target.closest("[data-bulk-tab]");
  if (!b || !bulk || bulk.busy) return;
  bulk.tab = b.dataset.bulkTab;
  renderBulkForm();
});
document.getElementById("bulk-scope").addEventListener("change", () => {
  invalidateBulkPreview();
  refreshBulkClear();
});
document.getElementById("bulk-form").addEventListener("input", invalidateBulkPreview);
document.getElementById("bulk-form").addEventListener("change", e => {
  if (e.target.name === "bulk-name-src" && bulk) {
    bulk.nameSource = e.target.value;
    renderBulkForm();
    return;
  }
  if (e.target.id === "bulk-set-field") renderBulkSetValue();
  if (e.target.dataset && e.target.dataset.bulkClear && bulk) {
    bulk.clear[e.target.checked ? "add" : "delete"](e.target.dataset.bulkClear);
  }
  invalidateBulkPreview();
});
document.getElementById("bulk-form").addEventListener("keydown", e => {
  if (e.key === "Enter" && e.target.tagName === "INPUT" && e.target.type === "text") {
    e.preventDefault();
    runBulkPreview();
  }
});
document.getElementById("bulk-preview-btn").addEventListener("click", runBulkPreview);
document.getElementById("bulk-apply").addEventListener("click", applyBulk);

/* ========== Image editor (tile button "Edit image") ==========
 * Crop on the original (free or a fixed ratio), rotate / flip, transparent
 * background (flood from the edges or one colour everywhere), auto-trim,
 * maximum size, format and quality. The server (gme/imageedit.py, Pillow)
 * renders the live preview and writes nothing until "Save"; saving keeps a
 * copy of the original, and the toast's "Undo" puts it back.
 */
const IMG_EDIT_FIELDS_SKIP = ["video", "manual", "music"];
let imgEdit = null;   // { path, index, field, rel, nat: {w, h}, crop, rotate, flipH, flipV, seq, timer }

function isImageField(key) { return !IMG_EDIT_FIELDS_SKIP.includes(key); }
function imgEditEl(id) { return document.getElementById("imgedit-" + id); }

function openImageEditor(field) {
  const g = games.find(x => x.index === currentIndex);
  if (!g || !g[field] || !isImageField(field)) return;
  imgEdit = { path: g.path, index: g.index, field, rel: g[field], nat: null, crop: null, rotate: 0,
    flipH: false, flipV: false, seq: 0, timer: null, busy: false };
  imgEditEl("sub").textContent = `${fieldLabel(field)} · ${baseName(g[field])}`;
  resetImageEditorForm();
  const src = imgEditEl("src");
  src.onload = () => {
    if (!imgEdit) return;
    imgEdit.nat = { w: src.naturalWidth, h: src.naturalHeight };
    drawImgEditCrop();
    scheduleImgEditPreview(0);
  };
  src.src = mediaUrl(g[field]);
  imgEditEl("out").removeAttribute("src");
  imgEditEl("out-info").textContent = "";
  imgEditEl("src-info").textContent = "";
  imgEditEl("save").disabled = true;
  document.getElementById("imgedit-modal").classList.add("open");
  imgEditEl("ratio").focus();
}
function closeImageEditor() {
  const modal = document.getElementById("imgedit-modal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  if (imgEdit) clearTimeout(imgEdit.timer);
  imgEdit = null;
  const src = imgEditEl("src");
  src.removeAttribute("src");
  src.style.width = src.style.height = "";
  imgEditEl("out").removeAttribute("src");
}
function resetImageEditorForm() {
  imgEditEl("ratio").value = "free";
  imgEditEl("bg-mode").value = "off";
  imgEditEl("bg-auto").checked = true;
  imgEditEl("bg-color").disabled = true;
  imgEditEl("bg-tol").value = 10;
  imgEditEl("trim").checked = false;
  imgEditEl("trim-tol").value = 5;
  imgEditEl("max-w").value = "";
  imgEditEl("max-h").value = "";
  imgEditEl("upscale").checked = false;
  imgEditEl("format").value = "keep";
  imgEditEl("quality").value = 90;
  imgEditEl("matte").value = "#ffffff";
  document.querySelector('input[name="imgedit-mode"][value="overwrite"]').checked = true;
  if (imgEdit) Object.assign(imgEdit, { crop: null, rotate: 0, flipH: false, flipV: false });
  syncImageEditorForm();
}
function syncImageEditorForm() {
  const fmt = imgEditEl("format").value;
  imgEditEl("quality-wrap").hidden = !(fmt === "jpg" || fmt === "webp");
  imgEditEl("matte-wrap").hidden = fmt !== "jpg";
  imgEditEl("bg-color").disabled = imgEditEl("bg-auto").checked || imgEditEl("bg-mode").value === "off";
  imgEditEl("bg-auto").disabled = imgEditEl("bg-mode").value === "off";
  imgEditEl("bg-tol").disabled = imgEditEl("bg-mode").value === "off";
  imgEditEl("trim-tol").disabled = !imgEditEl("trim").checked;
  ["bg-tol", "trim-tol", "quality"].forEach(id => { imgEditEl(id + "-out").textContent = imgEditEl(id).value; });
  imgEditEl("flip-h").setAttribute("aria-pressed", String(!!(imgEdit && imgEdit.flipH)));
  imgEditEl("flip-v").setAttribute("aria-pressed", String(!!(imgEdit && imgEdit.flipV)));
}
function imageEditOps() {
  const v = id => imgEditEl(id);
  const ops = { rotate: imgEdit.rotate, flip_h: imgEdit.flipH, flip_v: imgEdit.flipV,
    format: v("format").value, quality: Number(v("quality").value), matte: v("matte").value };
  if (imgEdit.crop) ops.crop = { ...imgEdit.crop };
  if (v("bg-mode").value !== "off") {
    ops.bg = { mode: v("bg-mode").value, color: v("bg-auto").checked ? null : v("bg-color").value,
      tolerance: Number(v("bg-tol").value) };
  }
  if (v("trim").checked) ops.trim = { tolerance: Number(v("trim-tol").value) };
  const mw = parseInt(v("max-w").value, 10) || 0, mh = parseInt(v("max-h").value, 10) || 0;
  if (mw > 0 || mh > 0) ops.resize = { max_w: Math.max(0, mw), max_h: Math.max(0, mh), upscale: v("upscale").checked };
  return ops;
}
function imgEditUrl(suffix) {
  return `/api/image-edit/${imgEdit.index}/${encodeURIComponent(imgEdit.field)}${suffix}?path=${encodeURIComponent(imgEdit.path)}`;
}
function scheduleImgEditPreview(delay) {
  if (!imgEdit || !imgEdit.nat) return;
  syncImageEditorForm();
  clearTimeout(imgEdit.timer);
  imgEditEl("save").disabled = true;
  imgEdit.timer = setTimeout(runImgEditPreview, delay === undefined ? 250 : delay);
}
async function runImgEditPreview() {
  if (!imgEdit) return;
  const seq = ++imgEdit.seq;
  const state = imgEdit;
  imgEditEl("busy").hidden = false;
  try {
    const d = await apiFetch(imgEditUrl("/preview"), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ops: imageEditOps() }),
    });
    if (imgEdit !== state || seq !== state.seq) return;
    imgEditEl("out").src = d.data;
    const src = d.source;
    imgEditEl("src-info").textContent = t("imgedit.info", { w: src.width, h: src.height, fmt: src.format.toUpperCase(), size: fmtSize(src.bytes) });
    imgEditEl("out-info").textContent = d.exact
      ? t("imgedit.info", { w: d.width, h: d.height, fmt: d.format.toUpperCase(), size: fmtSize(d.bytes) })
      : t("imgedit.info_approx", { w: d.width, h: d.height, fmt: d.format.toUpperCase() });
    const warn = imgEditEl("warn");
    const note = d.empty ? t("imgedit.empty_result") : d.alpha_lost ? t("imgedit.alpha_lost") : "";
    warn.hidden = !note;
    warn.textContent = note;
    const webp = imgEditEl("format").querySelector('option[value="webp"]');
    webp.disabled = !d.webp;
    imgEditEl("save").disabled = !!d.empty;
  } catch (e) {
    if (imgEdit !== state || seq !== state.seq) return;
    imgEditEl("out").removeAttribute("src");
    imgEditEl("out-info").textContent = "";
    const warn = imgEditEl("warn");
    warn.hidden = false;
    warn.textContent = e.message || String(e);
  } finally {
    if (imgEdit === state && seq === state.seq) imgEditEl("busy").hidden = true;
  }
}

/* --- Crop rectangle on the original (natural pixels) --- */
function imgEditRatio() {
  const v = imgEditEl("ratio").value;
  if (v === "free" || !imgEdit || !imgEdit.nat) return null;
  let r = v === "original" ? imgEdit.nat.w / imgEdit.nat.h : Number(v);
  // The ratio is the one of the result: a quarter turn swaps it on the original
  if (v !== "original" && imgEdit.rotate % 180) r = 1 / r;
  return r > 0 ? r : null;
}
function fitCropToRatio() {
  const r = imgEditRatio();
  if (!r || !imgEdit.nat) return;
  const { w: W, h: H } = imgEdit.nat;
  const base = imgEdit.crop || { x: 0, y: 0, w: W, h: H };
  let w = base.w, h = Math.round(w / r);
  if (h > base.h) { h = base.h; w = Math.round(h * r); }
  w = Math.max(1, Math.min(W, w)); h = Math.max(1, Math.min(H, h));
  const x = Math.round(base.x + (base.w - w) / 2), y = Math.round(base.y + (base.h - h) / 2);
  imgEdit.crop = { x: Math.max(0, Math.min(W - w, x)), y: Math.max(0, Math.min(H - h, y)), w, h };
}
/** The original fills its pane (the crop box is drawn over the image itself). */
function fitImgEditSrc() {
  const img = imgEditEl("src"), stage = imgEditEl("src-stage");
  if (!imgEdit || !imgEdit.nat) return;
  const k = Math.min((stage.clientWidth - 16) / imgEdit.nat.w, (stage.clientHeight - 16) / imgEdit.nat.h, 4);
  img.style.width = Math.max(1, Math.floor(imgEdit.nat.w * k)) + "px";
  img.style.height = Math.max(1, Math.floor(imgEdit.nat.h * k)) + "px";
}
function drawImgEditCrop() {
  const box = imgEditEl("crop");
  const img = imgEditEl("src");
  fitImgEditSrc();
  if (!imgEdit || !imgEdit.crop || !imgEdit.nat || !img.clientWidth) { box.hidden = true; return; }
  const s = img.clientWidth / imgEdit.nat.w;
  const c = imgEdit.crop;
  Object.assign(box.style, { left: c.x * s + "px", top: c.y * s + "px", width: c.w * s + "px", height: c.h * s + "px" });
  box.hidden = false;
}
(() => {
  const wrap = imgEditEl("src-wrap");
  let drag = null;
  const point = e => {
    const img = imgEditEl("src");
    const rect = img.getBoundingClientRect();
    const s = imgEdit.nat.w / rect.width;
    return { x: Math.max(0, Math.min(imgEdit.nat.w, (e.clientX - rect.left) * s)),
      y: Math.max(0, Math.min(imgEdit.nat.h, (e.clientY - rect.top) * s)) };
  };
  // A rectangle from an anchor corner to the pointer, at the chosen ratio
  const rectFrom = (a, p) => {
    const { w: W, h: H } = imgEdit.nat;
    let w = Math.abs(p.x - a.x), h = Math.abs(p.y - a.y);
    const r = imgEditRatio();
    if (r) {
      if (w / r > h) h = w / r; else w = h * r;
      const maxW = p.x >= a.x ? W - a.x : a.x, maxH = p.y >= a.y ? H - a.y : a.y;
      const k = Math.min(1, maxW / w || 1, maxH / h || 1);
      w *= k; h *= k;
    }
    const x = p.x >= a.x ? a.x : a.x - w, y = p.y >= a.y ? a.y : a.y - h;
    return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
  };
  wrap.addEventListener("pointerdown", e => {
    if (!imgEdit || !imgEdit.nat || e.button !== 0) return;
    e.preventDefault();
    const p = point(e);
    const handle = e.target.closest(".imgedit-handle");
    const c = imgEdit.crop;
    if (handle && c) {
      const h = handle.dataset.h;
      drag = { kind: "size", anchor: { x: h.includes("w") ? c.x + c.w : c.x, y: h.includes("n") ? c.y + c.h : c.y } };
    } else if (c && e.target.closest(".imgedit-crop")) {
      drag = { kind: "move", start: p, from: { ...c } };
    } else {
      drag = { kind: "size", anchor: p };
    }
    wrap.setPointerCapture(e.pointerId);
  });
  wrap.addEventListener("pointermove", e => {
    if (!drag || !imgEdit) return;
    const p = point(e);
    if (drag.kind === "move") {
      const { w: W, h: H } = imgEdit.nat, f = drag.from;
      imgEdit.crop = { ...f, x: Math.round(Math.max(0, Math.min(W - f.w, f.x + p.x - drag.start.x))),
        y: Math.round(Math.max(0, Math.min(H - f.h, f.y + p.y - drag.start.y))) };
    } else {
      imgEdit.crop = rectFrom(drag.anchor, p);
    }
    drawImgEditCrop();
  });
  const end = () => {
    if (!drag || !imgEdit) return;
    drag = null;
    const c = imgEdit.crop;
    if (c && (c.w < 4 || c.h < 4)) imgEdit.crop = null;   // a click is not a crop
    drawImgEditCrop();
    scheduleImgEditPreview(0);
  };
  wrap.addEventListener("pointerup", end);
  wrap.addEventListener("pointercancel", end);
  window.addEventListener("resize", () => { if (imgEdit) drawImgEditCrop(); });
})();

async function saveImageEdit() {
  if (!imgEdit || imgEditEl("save").disabled) return;
  const state = imgEdit;
  const session = window.__gmeSession;
  const mode = document.querySelector('input[name="imgedit-mode"]:checked').value;
  const saveBtn = imgEditEl("save");
  setBusy(saveBtn, true);
  try {
    const d = await apiFetch(imgEditUrl(""), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ops: imageEditOps(), mode }),
    });
    if (session !== window.__gmeSession) return;
    stampMedia([d.path, d.old_path]);
    const g = games.find(x => x.path === state.path);
    if (g) {
      g[state.field] = d.path;
      if (currentIndex === g.index) renderZones(g);
    }
    renderList(document.getElementById("search").value);
    closeImageEditor();
    const msg = d.shared ? t("imgedit.saved_shared", { file: baseName(d.path) }) : t("imgedit.saved", { file: baseName(d.path) });
    toast(msg, d.shared ? "info" : "success",
      { label: t("bulk.undo"), run: () => undoImageEdit(d.undo, d.path_changed) });
    setStatus(t("status.saved"));
  } catch (e) {
    handleError(e);
  } finally {
    setBusy(saveBtn, false);
  }
}
/** Puts the originals back; when the gamelist changed (new file, new format)
 * its snapshot is restored too, which reloads the list. */
async function undoImageEdit(id, xmlChanged) {
  if (xmlChanged && changedFields().length) {
    const choice = await askConfirm({ title: t("bulk.undo"), bodyHtml: `<p>${escapeHtml(t("bulk.undo_unsaved"))}</p>`,
      showBackup: false, okLabel: t("bulk.undo") });
    if (!choice.confirmed) return;
  }
  try {
    const d = await apiFetch("/api/image-edit/undo", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }),
    });
    stampMedia(d.paths);
    if (d.session_id) {
      window.__gmeSession = d.session_id;
      resetEditorSelection();
      await loadGames();
    } else {
      const g = games.find(x => x.index === currentIndex);
      if (g) renderZones(g);
      renderList(document.getElementById("search").value);
    }
    toast(t("imgedit.undone"));
  } catch (e) { handleError(e); }
}

imgEditEl("close").addEventListener("click", closeImageEditor);
imgEditEl("cancel").addEventListener("click", closeImageEditor);
imgEditEl("save").addEventListener("click", saveImageEdit);
imgEditEl("reset").addEventListener("click", () => {
  resetImageEditorForm();
  drawImgEditCrop();
  scheduleImgEditPreview(0);
});
document.getElementById("imgedit-modal").addEventListener("click", e => { if (e.target.id === "imgedit-modal") closeImageEditor(); });
imgEditEl("crop-clear").addEventListener("click", () => {
  if (!imgEdit) return;
  imgEdit.crop = null;
  imgEditEl("ratio").value = "free";
  drawImgEditCrop();
  scheduleImgEditPreview(0);
});
imgEditEl("ratio").addEventListener("change", () => {
  if (!imgEdit) return;
  fitCropToRatio();
  drawImgEditCrop();
  scheduleImgEditPreview(0);
});
imgEditEl("rot-left").addEventListener("click", () => {
  if (!imgEdit) return;
  imgEdit.rotate = (imgEdit.rotate + 270) % 360;
  if (imgEdit.crop && imgEditRatio()) fitCropToRatio();
  drawImgEditCrop();
  scheduleImgEditPreview(0);
});
imgEditEl("rot-right").addEventListener("click", () => {
  if (!imgEdit) return;
  imgEdit.rotate = (imgEdit.rotate + 90) % 360;
  if (imgEdit.crop && imgEditRatio()) fitCropToRatio();
  drawImgEditCrop();
  scheduleImgEditPreview(0);
});
imgEditEl("flip-h").addEventListener("click", () => { if (imgEdit) { imgEdit.flipH = !imgEdit.flipH; scheduleImgEditPreview(0); } });
imgEditEl("flip-v").addEventListener("click", () => { if (imgEdit) { imgEdit.flipV = !imgEdit.flipV; scheduleImgEditPreview(0); } });
imgEditEl("tools").addEventListener("input", e => {
  if (e.target.type === "range") syncImageEditorForm();
  scheduleImgEditPreview();
});
imgEditEl("tools").addEventListener("change", () => scheduleImgEditPreview());

/* ========== Statistics (Actions › Statistics) ==========
 * Read-only figures for the open gamelist (/api/stats, gme/stats.py): media
 * present / broken (tag but no file) / missing, scraped and complete games
 * (complete = every required media of this system present), genres, plays.
 * "Show" on a media row filters the list on the games missing it.
 */
async function openStats() {
  if (!window.__gmeLoaded) return;
  const modal = document.getElementById("stats-modal");
  const body = document.getElementById("stats-body");
  document.getElementById("stats-system").textContent = currentSystem && currentSystem.label ? " · " + currentSystem.label : "";
  body.innerHTML = busyHtml(t("stats.loading"), "bulk-empty");
  modal.classList.add("open");
  document.getElementById("stats-close").focus();
  try {
    const data = await apiFetch("/api/stats?required=" + encodeURIComponent(requiredKeys().join(",")));
    if (!modal.classList.contains("open")) return;
    body.innerHTML = statsHtml(data);
  } catch (e) {
    body.innerHTML = `<p class="bulk-empty bulk-error">${icon("alert-circle")}<span>${escapeHtml(e.message || String(e))}</span></p>`;
  }
}
function closeStats() {
  const modal = document.getElementById("stats-modal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  document.getElementById("stats-body").innerHTML = "";
}
function fmtPlayTime(seconds) {
  const h = Math.floor(seconds / 3600), m = Math.round((seconds % 3600) / 60);
  return h ? t("stats.hours", { h: fmtCount(h), m }) : t("stats.minutes", { m });
}
function statsHtml(d) {
  const total = d.games || 0;
  const pct = n => total ? Math.round(n * 100 / total) : 0;
  const card = (ico, label, value, sub) => `<div class="stat-card">${icon(ico)}<div><div class="stat-value">${escapeHtml(value)}</div>` +
    `<div class="stat-label">${escapeHtml(label)}</div>${sub ? `<div class="stat-sub">${escapeHtml(sub)}</div>` : ""}</div></div>`;
  const ofTotal = n => t("stats.percent", { p: pct(n) });
  let html = `<div class="stat-cards">
    ${card("device-gamepad-2", t("stats.games"), fmtCount(total), "")}
    ${card("cloud-download", t("stats.scraped"), fmtCount(d.scraped), ofTotal(d.scraped))}
    ${card("circle-check", t("stats.complete"), fmtCount(d.complete), d.required.length ? ofTotal(d.complete) : t("stats.no_required"))}
    ${card("file-text", t("stats.with_desc"), fmtCount(d.with_desc), ofTotal(d.with_desc))}
    ${card("star", t("stats.rated"), fmtCount(d.rated), ofTotal(d.rated))}
    ${card("calendar", t("stats.dated"), fmtCount(d.dated), ofTotal(d.dated))}
    ${card("heart", t("editor.favorite"), fmtCount(d.favorite), "")}
    ${card("eye-off", t("editor.hidden"), fmtCount(d.hidden), "")}
    ${card("player-play", t("stats.played"), fmtCount(d.played),
      d.playcount ? t("stats.plays", { n: fmtCount(d.playcount) }) + (d.gametime ? " · " + fmtPlayTime(d.gametime) : "") : "")}
  </div>`;
  const req = new Set(d.required || []);
  html += `<h4 class="stats-h">${escapeHtml(t("stats.media"))}</h4><table class="stats-table"><thead><tr>
    <th>${escapeHtml(t("stats.col_media"))}</th><th class="stats-bar-col"></th><th>${escapeHtml(t("stats.present"))}</th>
    <th>${escapeHtml(t("stats.broken"))}</th><th>${escapeHtml(t("stats.missing"))}</th><th></th></tr></thead><tbody>`;
  const byKey = Object.fromEntries(d.media.map(m => [m.field, m]));
  getFields().forEach(f => {
    const m = byKey[f.key];
    if (!m) return;
    const p = pct(m.present), b = pct(m.broken);
    html += `<tr${req.has(f.key) ? ' class="is-required"' : ""}>
      <td>${icon(f.icon)}<span>${escapeHtml(f.label)}</span>${req.has(f.key) ? `<span class="stats-req">${escapeHtml(t("stats.required"))}</span>` : ""}</td>
      <td class="stats-bar-col"><span class="stats-bar" title="${p} %"><span class="ok" style="width:${p}%"></span><span class="bad" style="width:${b}%"></span></span></td>
      <td>${fmtCount(m.present)}</td><td>${m.broken ? `<span class="stats-broken">${fmtCount(m.broken)}</span>` : "0"}</td><td>${fmtCount(m.missing)}</td>
      <td>${m.missing ? `<button type="button" class="btn btn-sm" data-stats-missing="${f.key}">${escapeHtml(t("stats.show_missing"))}</button>` : ""}</td>
    </tr>`;
  });
  html += `</tbody></table>`;
  if (d.media.some(m => m.broken)) html += `<p class="bulk-hint">${escapeHtml(t("stats.broken_hint"))}</p>`;
  if (d.genres.length) {
    const max = d.genres[0].n || 1;
    html += `<h4 class="stats-h">${escapeHtml(t("stats.genres", { n: fmtCount(d.genre_count) }))}</h4><ul class="stats-genres">` +
      d.genres.map(g => `<li><span class="stats-genre">${escapeHtml(g.genre)}</span><span class="stats-bar"><span class="ok" style="width:${Math.round(g.n * 100 / max)}%"></span></span><span>${fmtCount(g.n)}</span></li>`).join("") +
      `</ul>`;
  }
  if (d.no_genre) html += `<p class="bulk-hint">${escapeHtml(t("stats.no_genre", { n: fmtCount(d.no_genre) }))}</p>`;
  if (d.most_played) html += `<p class="bulk-hint">${escapeHtml(t("stats.most_played", { name: d.most_played.name, n: fmtCount(d.most_played.playcount) }))}</p>`;
  return html;
}
document.getElementById("btn-stats").addEventListener("click", openStats);
document.getElementById("stats-close").addEventListener("click", closeStats);
document.getElementById("stats-cancel").addEventListener("click", closeStats);
document.getElementById("stats-modal").addEventListener("click", e => {
  if (e.target.id === "stats-modal") { closeStats(); return; }
  const b = e.target.closest("[data-stats-missing]");
  if (!b) return;
  // the games without this media: the column filter "is empty" on it
  colFilter.on = true;
  colFilter.field = b.dataset.statsMissing;
  colFilter.op = "empty";
  document.getElementById("col-field").value = colFilter.field;
  document.getElementById("col-op").value = "empty";
  closeStats();
  updateColFilterUi();
  listEls().list.scrollTop = 0;
  renderList();
});


/* ========== DAT tool (Actions › DAT tool) ==========
 * Load a DAT the user has (Logiqx XML from No-Intro / Redump / FBNeo, MAME
 * -listxml, ClrMamePro text), by picking the file, typing its path or using
 * the mame.xml found near the gamelist. The server parses it and compares the
 * system's ROM files in the background (gme/dattool.py); this dialog polls
 * /api/dat for the progress. Hashing is opt-in. Nothing here writes: names
 * from the DAT go through Edit in bulk › Names (preview, backup, undo).
 */
const DAT_STATUSES = ["ok", "renamed", "bad", "incomplete", "unknown", "missing"];
let datView = { open: false, state: null, status: "", hideClones: false, hideBios: false, polling: false };

function datSleep(ms) { return new Promise(r => setTimeout(r, ms)); }

/** Poll /api/dat until the running job ends; ``onTick(state)`` on each answer. */
async function datWait(onTick) {
  for (;;) {
    const d = await apiFetch("/api/dat");
    if (onTick) onTick(d);
    if (!d.job || d.job.state !== "running") return d;
    await datSleep(250);
  }
}
async function datLoad(source, onTick) {
  if (source instanceof File) {
    const fd = new FormData();
    fd.append("file", source, source.name);
    await apiFetch("/api/dat/load", { method: "POST", body: fd });
  } else {
    await apiFetch("/api/dat/load", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: source }),
    });
  }
  const d = await datWait(onTick);
  if (d.job && d.job.state === "error") throw new Error(d.job.error || t("dat.load_failed"));
  return d;
}
function datInfoText(info) {
  if (!info) return t("dat.none");
  return t("dat.loaded", { title: info.title || info.source, games: fmtCount(info.games),
    clones: fmtCount(info.clones), bios: fmtCount(info.bios) });
}
/** The load controls (file, path, mame.xml found), shared by this dialog and Edit in bulk › Names. */
function datLoadControlsHtml(prefix, mame) {
  return `<label class="btn btn-sm dat-file-btn">${icon("upload")}<span>${escapeHtml(t("dat.pick"))}</span>` +
    `<input type="file" id="${prefix}-file" accept=".dat,.xml" hidden></label>` +
    `<input type="text" id="${prefix}-path" class="dat-path" spellcheck="false" autocomplete="off" placeholder="${escapeHtml(t("dat.path_ph"))}">` +
    `<button type="button" class="btn btn-sm" id="${prefix}-path-load">${escapeHtml(t("dat.load"))}</button>` +
    (mame ? `<button type="button" class="btn btn-sm" id="${prefix}-mame" data-path="${escapeHtml(mame)}" title="${escapeHtml(mame)}">${icon("cpu")}<span>${escapeHtml(t("dat.use_mame"))}</span></button>` : "");
}
function bindDatLoadControls(prefix, run) {
  const file = document.getElementById(prefix + "-file");
  const path = document.getElementById(prefix + "-path");
  file.addEventListener("change", () => { if (file.files && file.files[0]) run(file.files[0]); file.value = ""; });
  document.getElementById(prefix + "-path-load").addEventListener("click", () => { if (path.value.trim()) run(path.value.trim()); });
  path.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); if (path.value.trim()) run(path.value.trim()); } });
  const mame = document.getElementById(prefix + "-mame");
  if (mame) mame.addEventListener("click", () => run(mame.dataset.path));
}

async function openDatTool() {
  if (!window.__gmeLoaded) return;
  datView = { open: true, state: null, status: "", hideClones: false, hideBios: false, polling: false };
  document.getElementById("dat-modal").classList.add("open");
  const report = document.getElementById("dat-report");
  report.innerHTML = busyHtml(t("common.loading"), "bulk-empty");
  updateDatHashHint();
  try {
    const d = await apiFetch("/api/dat");
    renderDatState(d);
    if (d.job && d.job.state === "running") { report.innerHTML = ""; followDatJob(); }
    else if (d.report) loadDatReport();
    else report.innerHTML = "";
  } catch (e) { report.innerHTML = ""; handleError(e); }
  document.getElementById("dat-hash").focus();
}
function closeDatTool() {
  const modal = document.getElementById("dat-modal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  datView.open = false;              // a running job goes on; reopening shows it
}
function renderDatState(d) {
  datView.state = d;
  const running = !!(d.job && d.job.state === "running");
  const src = document.getElementById("dat-source");
  src.innerHTML = `${icon("database")}<span>${escapeHtml(datInfoText(d.dat))}</span>`;
  src.classList.toggle("is-empty", !d.dat);
  const load = document.getElementById("dat-load");
  if (!load.dataset.ready || load.dataset.mame !== (d.mame_xml || "")) {
    load.innerHTML = datLoadControlsHtml("dat", d.mame_xml);
    load.dataset.ready = "1";
    load.dataset.mame = d.mame_xml || "";
    bindDatLoadControls("dat", runDatLoad);
  }
  load.querySelectorAll("button, input").forEach(el => { el.disabled = running; });
  document.getElementById("dat-compare").disabled = running || !d.dat;
  document.getElementById("dat-hash").disabled = running;
  const prog = document.getElementById("dat-progress");
  prog.hidden = !running;
  const report = document.getElementById("dat-report");
  if (running) report.setAttribute("aria-busy", "true");
  else report.removeAttribute("aria-busy");
  if (running) {
    const j = d.job;
    const pct = j.total ? Math.min(100, Math.round(j.done * 100 / j.total)) : 0;
    document.getElementById("dat-bar").style.width = pct + "%";
    const amount = j.unit === "files" ? t("dat.progress_files", { done: fmtCount(j.done), total: fmtCount(j.total) })
      : t("dat.progress_bytes", { done: fmtSize(j.done), total: fmtSize(j.total) });
    document.getElementById("dat-progress-text").textContent =
      t(j.kind === "load" ? "dat.loading" : "dat.comparing", { pct }) + " · " + amount + (j.current ? " · " + j.current : "");
  }
  document.getElementById("dat-export").disabled = running || !d.report;
  document.getElementById("dat-names").disabled = running || !d.dat;
}
async function followDatJob() {
  if (datView.polling) return;
  datView.polling = true;
  try {
    const d = await datWait(s => { if (datView.open) renderDatState(s); });
    if (!datView.open) return;
    renderDatState(d);
    const j = d.job || {};
    if (j.state === "error") toast(j.error || t("dat.load_failed"), "error");
    else if (j.state === "stopped") toast(t("dat.stopped"), "info");
    else if (j.kind === "load" && d.dat) toast(datInfoText(d.dat));
    if (j.kind === "compare" && d.report) { datView.status = ""; loadDatReport(); }
    else if (j.kind === "load") document.getElementById("dat-report").innerHTML = "";
  } catch (e) {
    handleError(e);
  } finally {
    datView.polling = false;
  }
}
async function runDatLoad(source) {
  try {
    if (source instanceof File) {
      const fd = new FormData();
      fd.append("file", source, source.name);
      await apiFetch("/api/dat/load", { method: "POST", body: fd });
    } else {
      await apiFetch("/api/dat/load", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: source }),
      });
    }
  } catch (e) { handleError(e); return; }
  followDatJob();
}
function updateDatHashHint() {
  const mode = document.getElementById("dat-hash").value;
  document.getElementById("dat-hash-hint").textContent = t("dat.hint_" + mode);
}
async function runDatCompare() {
  const hash = document.getElementById("dat-hash").value;
  const btn = document.getElementById("dat-compare");
  if (btn.dataset.busy) return;
  setBusy(btn, true);
  try {
    await apiFetch("/api/dat/compare", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hash }),
    });
  } catch (e) { setBusy(btn, false); handleError(e); return; }
  setBusy(btn, false, { restore: false });
  document.getElementById("dat-report").innerHTML = "";
  followDatJob();
}
function datQuery(extra) {
  const q = new URLSearchParams();
  if (datView.status) q.set("status", datView.status);
  if (datView.hideClones) q.set("hide_clones", "1");
  if (datView.hideBios) q.set("hide_bios", "1");
  Object.entries(extra || {}).forEach(([k, v]) => q.set(k, v));
  return q.toString();
}
async function loadDatReport() {
  const box = document.getElementById("dat-report");
  box.setAttribute("aria-busy", "true");
  if (!box.querySelector(".dat-chips")) box.innerHTML = busyHtml(t("common.loading"), "bulk-empty");
  try {
    const rep = await apiFetch("/api/dat/report?" + datQuery());
    if (datView.open) box.innerHTML = datReportHtml(rep);
  } catch (e) {
    box.innerHTML = `<p class="bulk-empty bulk-error">${icon("alert-circle")}<span>${escapeHtml(e.message || String(e))}</span></p>`;
  } finally {
    box.removeAttribute("aria-busy");
  }
}
function datDetail(r) {
  if (r.detail === "dat_baddump") return t("dat.detail_baddump");
  if (!r.detail) return "";
  if (r.status === "incomplete") return t("dat.detail_missing", { roms: r.detail });
  if (r.status === "bad") return t("dat.detail_bad", { roms: r.detail });
  return r.detail;
}
function datReportHtml(rep) {
  const chips = DAT_STATUSES.map(s => `<button type="button" class="dat-chip dat-${s}${datView.status === s ? " active" : ""}" data-dat-status="${s}" aria-pressed="${datView.status === s}">` +
    `<strong>${fmtCount(rep.counts[s])}</strong><span>${escapeHtml(t("dat.status_" + s))}</span></button>`).join("");
  const filters = `<label class="bulk-check"><input type="checkbox" data-dat-filter="clones"${datView.hideClones ? " checked" : ""}> <span>${escapeHtml(t("dat.hide_clones"))}</span></label>` +
    `<label class="bulk-check"><input type="checkbox" data-dat-filter="bios"${datView.hideBios ? " checked" : ""}> <span>${escapeHtml(t("dat.hide_bios"))}</span></label>`;
  let html = `<div class="dat-chips">${chips}</div><div class="dat-filters">${filters}` +
    `<span class="bulk-hint">${escapeHtml(t("dat.mode_" + rep.hash))}</span></div>`;
  if (!rep.rows.length) return html + `<p class="bulk-empty">${escapeHtml(t("dat.no_rows"))}</p>`;
  const rows = rep.rows.map(r => {
    const flags = r.flags.map(f => `<span class="dat-flag dat-flag-${f}">${escapeHtml(t("dat.flag_" + f))}</span>`).join("");
    const file = r.file ? `<span title="${escapeHtml(r.path)}">${escapeHtml(r.file)}</span>` : `<em class="bulk-none">${escapeHtml(t("dat.no_file"))}</em>`;
    const game = r.dat ? `<span class="dat-game" title="${escapeHtml(r.dat)}">${escapeHtml(r.desc || r.dat)}</span>` +
      (r.parent ? `<span class="dat-parent">${escapeHtml(t("dat.clone_of", { name: r.parent }))}</span>` : "") : "";
    return `<tr><td><span class="dat-status dat-${r.status}">${escapeHtml(t("dat.status_" + r.status))}</span></td>` +
      `<td class="dat-file">${file}</td><td>${game}</td><td class="dat-detail">${flags}${escapeHtml(datDetail(r))}</td></tr>`;
  }).join("");
  html += `<table class="bulk-table dat-table"><thead><tr><th>${escapeHtml(t("dat.col_status"))}</th><th>${escapeHtml(t("dat.col_file"))}</th>` +
    `<th>${escapeHtml(t("dat.col_game"))}</th><th>${escapeHtml(t("dat.col_detail"))}</th></tr></thead><tbody>${rows}</tbody></table>`;
  if (rep.total > rep.rows.length) {
    html += `<p class="bulk-more">${escapeHtml(t("dat.more", { n: fmtCount(rep.total - rep.rows.length) }))}</p>`;
  }
  return html;
}
async function exportDatReport() {
  const btn = document.getElementById("dat-export");
  if (btn.dataset.busy) return;
  setBusy(btn, true);
  try {
    const blob = await apiFetch("/api/dat/report?" + datQuery({ format: "csv" }), { raw: true });
    const a = document.createElement("a");
    const system = (currentSystem && currentSystem.folder) || "gamelist";
    a.href = URL.createObjectURL(blob);
    a.download = `dat-${system}-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } catch (e) { handleError(e); }
  finally { setBusy(btn, false); }
}
document.getElementById("btn-dat-tool").addEventListener("click", openDatTool);
document.getElementById("dat-close").addEventListener("click", closeDatTool);
document.getElementById("dat-cancel").addEventListener("click", closeDatTool);
document.getElementById("dat-modal").addEventListener("click", e => { if (e.target.id === "dat-modal") closeDatTool(); });
document.getElementById("dat-hash").addEventListener("change", updateDatHashHint);
document.getElementById("dat-compare").addEventListener("click", runDatCompare);
document.getElementById("dat-stop").addEventListener("click", () => apiFetch("/api/dat/stop", { method: "POST" }).catch(handleError));
document.getElementById("dat-export").addEventListener("click", exportDatReport);
document.getElementById("dat-names").addEventListener("click", () => {
  closeDatTool();
  openBulk("reset_name", { scope: "all", source: "dat" });
});
document.getElementById("dat-report").addEventListener("click", e => {
  const chip = e.target.closest("[data-dat-status]");
  if (!chip) return;
  datView.status = datView.status === chip.dataset.datStatus ? "" : chip.dataset.datStatus;
  loadDatReport();
});
document.getElementById("dat-report").addEventListener("change", e => {
  const f = e.target.closest("[data-dat-filter]");
  if (!f) return;
  if (f.dataset.datFilter === "clones") datView.hideClones = f.checked;
  else datView.hideBios = f.checked;
  loadDatReport();
});

/* ========== New gamelist from a ROM folder (Gamelist… › Create a gamelist here) ==========
 * The folder browsed in the Open dialog has no gamelist.xml: list its ROMs
 * with the system's usual extensions (editable), preview, then write and open
 * the new gamelist (gme/newgamelist.py). A folder that has one gets "Add the
 * missing ROMs…" instead: it opens it and runs Check ROMs (preview + backup).
 */
let newgl = null;   // { folder, preview, busy }

function openNewGamelist(folder) {
  closeGamelistModal();
  newgl = { folder, preview: null, busy: false, extsTouched: false };
  document.getElementById("newgl-folder").textContent = folder;
  document.getElementById("newgl-exts").value = "";
  document.getElementById("newgl-tags").checked = false;
  document.getElementById("newgl-modal").classList.add("open");
  runNewGamelistPreview();
}
function closeNewGamelist() {
  const modal = document.getElementById("newgl-modal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  newgl = null;
  document.getElementById("newgl-preview").innerHTML = "";
}
function newglBody() {
  const exts = document.getElementById("newgl-exts").value.trim();
  return { folder: newgl.folder, exts: newgl.extsTouched && exts ? exts : null,
    strip_tags: document.getElementById("newgl-tags").checked };
}
function invalidateNewGamelist() {
  if (!newgl) return;
  newgl.preview = null;
  document.getElementById("newgl-create").disabled = true;
  document.getElementById("newgl-create-label").textContent = t("newgl.create");
  document.getElementById("newgl-preview").innerHTML = `<p class="bulk-empty">${escapeHtml(t("bulk.preview_first"))}</p>`;
}
async function runNewGamelistPreview() {
  if (!newgl || newgl.busy) return;
  newgl.busy = true;
  const box = document.getElementById("newgl-preview");
  const previewBtn = document.getElementById("newgl-preview-btn");
  setBusy(previewBtn, true);
  box.setAttribute("aria-busy", "true");
  box.innerHTML = busyHtml(t("imgedit.loading"));
  try {
    const body = newglBody();
    const d = await apiFetch("/api/new-gamelist/preview", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!newgl) return;
    if (!newgl.extsTouched) document.getElementById("newgl-exts").value = d.exts.join(", ");
    document.getElementById("newgl-hint").textContent = d.all_exts ? t("newgl.all_exts", { system: d.system || d.label })
      : d.custom ? t("newgl.custom_exts") : t("newgl.system_exts", { system: d.system });
    if (d.exists) {
      newgl.preview = null;
      box.innerHTML = `<p class="bulk-hint bulk-warn">${icon("alert-triangle")}<span>${escapeHtml(t("newgl.exists"))}</span></p>`;
      document.getElementById("newgl-create").disabled = true;
      return;
    }
    newgl.preview = d.total ? { body, d } : null;
    const rows = d.roms.map(r => `<tr><td class="bulk-game"><code>${escapeHtml(r.path)}</code></td><td>${escapeHtml(r.name)}</td></tr>`).join("");
    box.innerHTML = d.total
      ? `<p class="bulk-summary">${escapeHtml(t("newgl.summary", { n: fmtCount(d.total) }))}</p>` +
        `<table class="bulk-table"><thead><tr><th>${escapeHtml(t("newgl.col_path"))}</th><th>${escapeHtml(t("newgl.col_name"))}</th></tr></thead><tbody>${rows}</tbody></table>` +
        (d.total > d.roms.length ? `<p class="bulk-more">${escapeHtml(t("bulk.more", { n: fmtCount(d.total - d.roms.length) }))}</p>` : "") +
        `<p class="bulk-hint">${icon("shield-check")}<span>${escapeHtml(t("newgl.safe"))}</span></p>`
      : `<p class="bulk-empty">${escapeHtml(t("newgl.no_roms"))}</p>`;
    const btn = document.getElementById("newgl-create");
    btn.disabled = !d.total;
    document.getElementById("newgl-create-label").textContent = d.total ? t("newgl.create_n", { n: fmtCount(d.total) }) : t("newgl.create");
  } catch (e) {
    if (newgl) {
      newgl.preview = null;
      box.innerHTML = `<p class="bulk-empty bulk-error">${icon("alert-circle")}<span>${escapeHtml(e.message || String(e))}</span></p>`;
    }
  } finally {
    if (newgl) newgl.busy = false;
    setBusy(previewBtn, false);
    box.removeAttribute("aria-busy");
  }
}
async function createNewGamelist() {
  if (!newgl || newgl.busy || !newgl.preview) return;
  if (window.__gmeLoaded && changedFields().length) {
    toast(t("bulk.unsaved"), "warning");
    return;
  }
  newgl.busy = true;
  const createBtn = document.getElementById("newgl-create");
  setBusy(createBtn, true);
  try {
    const data = await apiFetch("/api/new-gamelist", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(newgl.preview.body),
    });
    closeNewGamelist();
    gamelistOpened(data, data.xml_path);
    toast(t("newgl.created", { n: fmtCount(data.created), name: (data.system && data.system.label) || "" }));
  } catch (e) {
    handleError(e);
    if (newgl) { newgl.busy = false; invalidateNewGamelist(); }
  } finally {
    setBusy(createBtn, false, { restore: false });
  }
}
document.getElementById("open-gl-new").addEventListener("click", async () => {
  const btn = document.getElementById("open-gl-new");
  if (!__browsePath) return;
  if (btn.dataset.mode === "add") {
    // the folder has a gamelist: open it, then Check ROMs adds what is missing
    document.getElementById("open-gl-path").value = btn.dataset.xml;
    await applyOpenGamelist();
    if (window.__gmeXmlPath && recentKey(window.__gmeXmlPath) === recentKey(btn.dataset.xml)) openCheck("roms");
    return;
  }
  openNewGamelist(__browsePath);
});
document.getElementById("newgl-close").addEventListener("click", closeNewGamelist);
document.getElementById("newgl-cancel").addEventListener("click", closeNewGamelist);
document.getElementById("newgl-modal").addEventListener("click", e => { if (e.target.id === "newgl-modal") closeNewGamelist(); });
document.getElementById("newgl-preview-btn").addEventListener("click", runNewGamelistPreview);
document.getElementById("newgl-create").addEventListener("click", createNewGamelist);
document.getElementById("newgl-exts").addEventListener("input", () => { if (newgl) newgl.extsTouched = true; invalidateNewGamelist(); });
document.getElementById("newgl-exts").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); runNewGamelistPreview(); } });
document.getElementById("newgl-tags").addEventListener("change", invalidateNewGamelist);


/* ========== Multi-system overview ==========
 * A "roms" root (RetroBat / Batocera / Recalbox) opened from the folder browser:
 * every system folder with its counts (gme/overview.py), scanned in the
 * background with a progress bar; a click opens the system in the editor and
 * the ▾ switcher next to the system name goes to another one or back here.
 * Read only: nothing is written by the scan.
 */
const OV_MEDIA = ["image", "thumbnail", "marquee", "wheel", "video"];
const OV_META = [["desc", "overview.col_no_desc"], ["genre", "overview.col_no_genre"], ["releasedate", "overview.col_no_date"]];
let overview = { root: null, data: null, sort: { key: "label", dir: 1 }, timer: null, seq: 0, picked: new Set() };
let rootSystems = { root: null, systems: [] };

function ovMediaPct(s, f) {
  const m = s.media && s.media[f];
  return m && s.games ? Math.round(m.present * 100 / s.games) : null;
}
function ovSortValue(s, key) {
  if (key === "label") return (s.label || s.folder || "").toLowerCase();
  if (!s.xml || s.error) return -1;
  if (key.startsWith("media:")) return ovMediaPct(s, key.slice(6));
  if (key.startsWith("meta:")) return (s.meta_missing || {})[key.slice(5)] || 0;
  return s[key] || 0;
}
function ovSorted(systems) {
  const { key, dir } = overview.sort;
  return [...systems].sort((a, b) => {
    const x = ovSortValue(a, key), y = ovSortValue(b, key);
    if (x < y) return -dir;
    if (x > y) return dir;
    return (a.folder || "").localeCompare(b.folder || "");
  });
}
function ovTotalsHtml(systems) {
  const withXml = systems.filter(s => s.xml && !s.error);
  const sum = k => withXml.reduce((n, s) => n + (s[k] || 0), 0);
  const games = sum("games");
  const pct = n => t("stats.percent", { p: games ? Math.round(n * 100 / games) : 0 });
  const media = f => withXml.reduce((n, s) => n + ((s.media || {})[f] ? s.media[f].present : 0), 0);
  const card = (ico, label, value, sub, warn) => `<div class="stat-card${warn ? " is-warn" : ""}">${icon(ico)}<div><div class="stat-value">${escapeHtml(value)}</div>` +
    `<div class="stat-label">${escapeHtml(label)}</div>${sub ? `<div class="stat-sub">${escapeHtml(sub)}</div>` : ""}</div></div>`;
  const noXml = systems.filter(s => !s.xml).length;
  return `<div class="stat-cards overview-totals" id="overview-totals">` +
    card("device-gamepad-2", t("overview.totals_systems"), fmtCount(systems.length), noXml ? t("overview.totals_no_gamelist", { n: fmtCount(noXml) }) : "") +
    card("list-details", t("overview.totals_games"), fmtCount(games), "") +
    card("cloud-download", t("stats.scraped"), fmtCount(sum("scraped")), pct(sum("scraped"))) +
    card("photo", t("fields.image", null, "image"), fmtCount(media("image")), pct(media("image"))) +
    card("movie", t("fields.video", null, "video"), fmtCount(media("video")), pct(media("video"))) +
    card("alert-triangle", t("overview.col_roms_missing"), fmtCount(sum("roms_missing")), "", sum("roms_missing") > 0) +
    card("file", t("overview.col_roms_unlisted"), fmtCount(sum("roms_unlisted")), "", false) +
    `</div>`;
}
function ovHeader(key, label, title) {
  const active = overview.sort.key === key;
  const aria = active ? (overview.sort.dir > 0 ? "ascending" : "descending") : "none";
  return `<th aria-sort="${aria}"${title ? ` title="${escapeHtml(title)}"` : ""}><button type="button" class="ov-sort" data-ov-sort="${key}">` +
    `<span>${escapeHtml(label)}</span>${active ? icon("arrow-up", overview.sort.dir > 0 ? "ov-sort-dir" : "ov-sort-dir is-desc") : ""}</button></th>`;
}
function ovRowHtml(s, fields, current) {
  const isCurrent = s.xml && current && recentKey(s.xml) === current;
  const name = `<span class="ov-name">${escapeHtml(s.label)}</span>` +
    (s.label.toLowerCase() !== s.folder.toLowerCase() ? `<span class="ov-folder">${escapeHtml(s.folder)}</span>` : "");
  let first;
  if (s.xml) {
    first = `<button type="button" class="ov-open" data-ov-open="${escapeHtml(s.xml)}" title="${escapeHtml(t("overview.open_title", { system: s.label }))}">${name}</button>` +
      (s.profile === "esde" ? `<span class="ov-chip is-esde" title="${escapeHtml(t("esde.chip_title"))}">ES-DE</span>` : "") +
      (isCurrent ? `<span class="ov-chip is-current">${escapeHtml(t("overview.current"))}</span>` : "");
  } else {
    first = `<span class="ov-open is-static">${name}</span>`;
  }
  const pickable = s.xml && !s.error;
  const picked = pickable && [...overview.picked].some(x => recentKey(x) === recentKey(s.xml));
  const pick = `<td class="ov-pick">${pickable ? `<input type="checkbox" data-ov-pick="${escapeHtml(s.xml)}"${picked ? " checked" : ""}` +
    ` aria-label="${escapeHtml(t("multibatch.pick", { system: s.label }))}" />` : ""}</td>`;
  if (!s.xml) {
    return `<tr class="is-no-xml">${pick}<td class="ov-system">${first}</td>` +
      `<td colspan="${3 + OV_MEDIA.length + OV_META.length}" class="ov-note"><span class="ov-chip">${escapeHtml(t("overview.no_gamelist"))}</span>` +
      `<span>${escapeHtml(t("overview.roms_count", { n: fmtCount(s.roms_unlisted || 0) }))}</span>` +
      (s.roms_unlisted ? `<button type="button" class="btn btn-sm" data-ov-create="${escapeHtml(s.path)}" title="${escapeHtml(t("overview.create_title"))}">${icon("folder-plus")}<span>${escapeHtml(t("overview.create"))}</span></button>` : "") +
      `</td></tr>`;
  }
  if (s.error) {
    return `<tr class="is-error">${pick}<td class="ov-system">${first}</td><td colspan="${3 + OV_MEDIA.length + OV_META.length}" class="ov-note">` +
      `<span class="ov-chip is-error" title="${escapeHtml(s.error_detail || "")}">${icon("alert-circle")}${escapeHtml(t("overview." + s.error))}</span></td></tr>`;
  }
  const num = (n, warn) => `<td class="ov-num${warn && n ? " is-warn" : ""}">${n ? fmtCount(n) : `<span class="ov-zero">0</span>`}</td>`;
  const media = fields.map(f => {
    if (s.profile === "esde" && !s.media[f.key]) {      // a media ES-DE has no folder for (wheel…)
      return `<td class="ov-media is-na" title="${escapeHtml(t("esde.no_such_media"))}"><span class="ov-pct">–</span></td>`;
    }
    const m = s.media[f.key] || { present: 0, broken: 0, missing: 0 };
    const p = s.games ? Math.round(m.present * 100 / s.games) : 0, b = s.games ? Math.round(m.broken * 100 / s.games) : 0;
    const title = t("overview.media_title", { present: fmtCount(m.present), broken: fmtCount(m.broken), missing: fmtCount(m.missing) });
    return `<td class="ov-media${p === 100 ? " is-full" : ""}" title="${escapeHtml(title)}"><span class="ov-pct">${s.games ? p + " %" : "–"}</span>` +
      `<span class="stats-bar"><span class="ok" style="width:${p}%"></span><span class="bad" style="width:${b}%"></span></span></td>`;
  }).join("");
  const meta = OV_META.map(([k]) => `<td class="ov-num">${s.meta_missing[k] ? fmtCount(s.meta_missing[k]) : `<span class="ov-zero">0</span>`}</td>`).join("");
  const cls = [isCurrent ? "is-current" : "", picked ? "is-picked" : ""].filter(Boolean).join(" ");
  return `<tr${cls ? ` class="${cls}"` : ""}>${pick}<td class="ov-system">${first}</td>${num(s.games)}${num(s.roms_missing, true)}${num(s.roms_unlisted)}${media}${meta}</tr>`;
}
function renderOverview() {
  const d = overview.data;
  const body = document.getElementById("overview-body");
  document.getElementById("overview-root").textContent = (d && d.root) || overview.root || "—";
  const prog = document.getElementById("overview-progress");
  const running = !!(d && d.state === "running");
  prog.hidden = !running;
  if (running) body.setAttribute("aria-busy", "true");
  else body.removeAttribute("aria-busy");
  if (d && running) {
    document.getElementById("overview-bar").style.width = (d.total ? Math.round(d.done * 100 / d.total) : 0) + "%";
    document.getElementById("overview-progress-text").textContent = d.current
      ? t("overview.progress_current", { done: fmtCount(d.done), total: fmtCount(d.total), system: d.current })
      : t("overview.progress", { done: fmtCount(d.done), total: fmtCount(d.total) });
  }
  if (!d || !(d.systems || []).length) updateOverviewActions();
  if (!d) { body.innerHTML = busyHtml(t("common.loading"), "bulk-empty"); return; }
  const systems = d.systems || [];
  if (!systems.length) {
    body.innerHTML = running ? busyHtml(t("overview.progress", { done: 0, total: fmtCount(d.total) }), "bulk-empty")
      : `<p class="bulk-empty">${escapeHtml(t("overview.empty"))}</p>`;
    return;
  }
  const byKey = Object.fromEntries(getFields(true).map(f => [f.key, f]));
  const fields = OV_MEDIA.map(k => byKey[k]).filter(Boolean);
  const current = window.__gmeXmlPath ? recentKey(window.__gmeXmlPath) : null;
  const scroll = body.querySelector(".overview-table-wrap");
  const top = scroll ? scroll.scrollTop : 0;
  let html = ovTotalsHtml(systems);
  if (d.state === "stopped") html += `<p class="bulk-hint bulk-warn">${icon("alert-triangle")}<span>${escapeHtml(t("overview.stopped", { done: fmtCount(d.done), total: fmtCount(d.total) }))}</span></p>`;
  html += `<div class="overview-table-wrap"><table class="overview-table" id="overview-table"><thead><tr>` +
    `<th class="ov-pick"><input type="checkbox" id="ov-pick-all" aria-label="${escapeHtml(t("multibatch.pick_all"))}" title="${escapeHtml(t("multibatch.pick_all"))}" /></th>` +
    ovHeader("label", t("overview.col_system")) + ovHeader("games", t("overview.col_games")) +
    ovHeader("roms_missing", t("overview.col_roms_missing"), t("overview.col_roms_missing_title")) +
    ovHeader("roms_unlisted", t("overview.col_roms_unlisted"), t("overview.col_roms_unlisted_title")) +
    fields.map(f => ovHeader("media:" + f.key, f.label, t("overview.col_media_title", { media: f.label }))).join("") +
    OV_META.map(([k, label]) => ovHeader("meta:" + k, t(label))).join("") +
    `</tr></thead><tbody>${ovSorted(systems).map(s => ovRowHtml(s, fields, current)).join("")}</tbody></table></div>`;
  body.innerHTML = html;
  const wrap = body.querySelector(".overview-table-wrap");
  if (wrap) wrap.scrollTop = top;
  updateOverviewActions();
}
async function pollOverview(seq) {
  clearTimeout(overview.timer);
  try {
    const d = await apiFetch("/api/overview");
    if (seq !== overview.seq || !document.getElementById("overview-modal").classList.contains("open")) return;
    overview.data = d;
    overview.root = d.root;
    renderOverview();
    if (d.state === "running") overview.timer = setTimeout(() => pollOverview(seq), 400);
  } catch (e) {
    if (seq === overview.seq) handleError(e);
  }
}
/** Open the overview of ``path`` (else the current root); ``refresh`` rescans everything. */
async function openOverview({ path = null, refresh = false } = {}) {
  const modal = document.getElementById("overview-modal");
  const seq = ++overview.seq;
  overview.data = null;
  modal.classList.add("open");
  renderOverview();
  document.getElementById("overview-close").focus();
  try {
    const d = await apiFetch("/api/overview/scan", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: path || overview.root || rootSystems.root || null, refresh }),
    });
    if (seq !== overview.seq) return;
    overview.data = d;
    overview.root = d.root;
    renderOverview();
    refreshSystemsSwitcher();
    pollOverview(seq);
  } catch (e) {
    if (seq !== overview.seq) return;
    document.getElementById("overview-body").innerHTML =
      `<p class="bulk-empty bulk-error">${icon("alert-circle")}<span>${escapeHtml(e.message || String(e))}</span></p>`;
    document.getElementById("overview-body").removeAttribute("aria-busy");
  }
}
function closeOverview() {
  const modal = document.getElementById("overview-modal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  overview.seq++;
  clearTimeout(overview.timer);
}
/** Open a system's gamelist from the overview or the switcher. */
async function openSystem(xml, trigger) {
  if (!(await confirmLeaveEditor())) return;
  setStatus(t("status.opening_gamelist"));
  setBusy(trigger, true);
  try {
    const data = await apiFetch("/api/open-gamelist", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: xml }),
    });
    closeOverview();
    gamelistOpened(data, xml);
    const label = (data.system && (data.system.label || data.system.folder)) || xml;
    toast(t("toast.gamelist_opened", { name: label, n: data.count != null ? data.count : games.length }));
  } catch (e) {
    handleError(e);
  } finally {
    setBusy(trigger, false);
  }
}
async function refreshSystemsSwitcher() {
  try {
    const d = await apiFetch("/api/overview/systems");
    rootSystems = { root: d.root, systems: d.systems || [] };
    if (d.root) overview.root = d.root;
  } catch (_) {
    rootSystems = { root: null, systems: [] };
  }
  document.getElementById("systems-wrap").hidden = !rootSystems.root;
}
function renderSystemsMenu() {
  const menu = document.getElementById("systems-menu");
  const current = window.__gmeXmlPath ? recentKey(window.__gmeXmlPath) : null;
  const root = rootSystems.root || "";
  const items = rootSystems.systems.filter(s => s.xml).map(s => {
    const on = current && recentKey(s.xml) === current;
    return `<button type="button" class="menu-item" role="menuitemradio" aria-checked="${on ? "true" : "false"}" data-ov-open="${escapeHtml(s.xml)}">` +
      `${icon("device-gamepad-2")}<span class="menu-item-text"><span class="menu-item-title">${escapeHtml(s.label)}</span>` +
      `<span class="menu-item-sub">${escapeHtml(s.folder)}</span></span>${icon("check", "menu-check")}</button>`;
  }).join("");
  menu.innerHTML = `<button type="button" class="menu-item" role="menuitem" data-ov-overview="1">${icon("chart-bar")}<span class="menu-item-text">` +
    `<span class="menu-item-title">${escapeHtml(t("overview.menu_overview"))}</span><span class="menu-item-sub">\u200e${escapeHtml(root)}\u200e</span></span></button>` +
    `<div class="menu-sep" role="separator"></div><div class="menu-label">${escapeHtml(t("overview.menu_systems"))}</div>` +
    `<div class="systems-menu-list">${items}</div>`;
}
setupMenu("systems-menu", "btn-systems", renderSystemsMenu);
document.getElementById("systems-menu").addEventListener("click", e => {
  const item = e.target.closest("[data-ov-open], [data-ov-overview]");
  if (!item) return;
  closeMenu("systems-menu", false);
  if (item.dataset.ovOverview) openOverview();
  else if (!(window.__gmeXmlPath && recentKey(window.__gmeXmlPath) === recentKey(item.dataset.ovOpen))) openSystem(item.dataset.ovOpen, document.getElementById("btn-systems"));
});
document.getElementById("overview-modal").addEventListener("click", e => {
  if (e.target.id === "overview-modal") { closeOverview(); return; }
  const sort = e.target.closest("[data-ov-sort]");
  if (sort) {
    const key = sort.dataset.ovSort;
    overview.sort = overview.sort.key === key ? { key, dir: -overview.sort.dir } : { key, dir: key === "label" ? 1 : -1 };
    renderOverview();
    const again = document.querySelector(`[data-ov-sort="${key}"]`);
    if (again) again.focus();
    return;
  }
  const open = e.target.closest("[data-ov-open]");
  if (open) { openSystem(open.dataset.ovOpen, open); return; }
  const create = e.target.closest("[data-ov-create]");
  if (create) {
    closeOverview();
    openNewGamelist(create.dataset.ovCreate);
  }
});
document.getElementById("overview-close").addEventListener("click", closeOverview);
document.getElementById("overview-cancel").addEventListener("click", closeOverview);
document.getElementById("overview-refresh").addEventListener("click", () => openOverview({ refresh: true }));
document.getElementById("overview-change").addEventListener("click", () => { closeOverview(); openGamelistModal(); });
document.getElementById("overview-stop").addEventListener("click", async () => {
  try { await apiFetch("/api/overview/stop", { method: "POST" }); } catch (e) { handleError(e); }
});
document.getElementById("open-gl-esde-overview").addEventListener("click", () => {
  const path = document.getElementById("open-gl-esde").dataset.path;
  if (!path) return;
  closeGamelistModal();
  openOverview({ path });
});
document.getElementById("open-gl-root").addEventListener("click", () => {
  const typed = (document.getElementById("open-gl-path").value || "").trim().replace(/^["']|["']$/g, "");
  const path = typed && !/\.xml$/i.test(typed) ? typed : __browsePath;
  if (!path) return;
  closeGamelistModal();
  openOverview({ path });
});
async function renderRecentRoots(data) {
  const box = document.getElementById("open-gl-roots");
  const wrap = document.getElementById("open-gl-roots-wrap");
  if (!data) {
    try { data = await apiFetch("/api/overview/recent"); } catch (_) { data = { recent: [] }; }
  }
  const list = data.recent || [];
  wrap.hidden = !list.length;
  box.innerHTML = list.map(({ path: p, exists }) => {
    const parts = p.split(/[\\/]/).filter(Boolean);
    const name = parts.slice(-2).join("/") || p;
    const title = exists ? p : `${p} (${t("open_gl.recent_missing")})`;
    return `<div class="open-gl-recent-row${exists ? "" : " is-missing"}" role="listitem">` +
      `<button type="button" class="open-gl-recent-item open-gl-root-item" data-path="${escapeHtml(p)}" title="${escapeHtml(title)}">` +
      `${icon(exists ? "chart-bar" : "alert-triangle")}<span class="open-gl-recent-name">${escapeHtml(name)}</span>` +
      `<span class="open-gl-recent-path">\u200e${escapeHtml(p)}\u200e</span></button>` +
      `<button type="button" class="btn btn-icon btn-sm open-gl-root-forget" data-path="${escapeHtml(p)}"` +
      ` title="${escapeHtml(t("open_gl.recent_forget"))}" aria-label="${escapeHtml(t("open_gl.recent_forget"))}">${icon("x")}</button></div>`;
  }).join("");
}
document.getElementById("open-gl-roots").addEventListener("click", async e => {
  const forget = e.target.closest(".open-gl-root-forget");
  if (forget) {
    try {
      renderRecentRoots(await apiFetch("/api/overview/recent/forget", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: forget.dataset.path }),
      }));
    } catch (err) { handleError(err); }
    return;
  }
  const item = e.target.closest(".open-gl-root-item");
  if (!item) return;
  closeGamelistModal();
  openOverview({ path: item.dataset.path });
});


/* ========== Actions on several systems (gme/multibatch.py) ==========
 * Systems ticked in the overview, then the chosen operations run one system at
 * a time on the server, through the single-system routes (same checks, dated
 * backup before every change, Recycle Bin). Deleting files needs its own box
 * and a danger confirmation, as in the single-system windows. */
const MB_OPS = ["roms", "media", "solid", "clear", "scrape"];
const MB_OP_ICONS = { roms: "list-check", media: "photo-cog", solid: "photo-square-rounded", clear: "eraser", scrape: "cloud-download" };
let mbatch = {
  phase: "setup", systems: [], data: null, timer: null, seq: 0, options: null, stopping: false,
  prefs: {
    roms: { on: false, add: true, remove: false, delete_media: false },
    media: { on: false, unlink: true, delete: false },
    solid: { on: false, off: new Set(), files: false },
    clear: { on: false, fields: new Set() },
    scrape: { on: false, mode: "missing", off: new Set(["name", "pad2key"]) },
  },
};

function ovPickable() {
  return ((overview.data && overview.data.systems) || []).filter(s => s.xml && !s.error);
}
function ovPicked() {
  const keys = new Set([...overview.picked].map(recentKey));
  return ovPickable().filter(s => keys.has(recentKey(s.xml)));
}
function updateOverviewActions() {
  const n = ovPicked().length;
  const running = !!(overview.data && overview.data.state === "running");
  const btn = document.getElementById("overview-actions");
  btn.disabled = !n || running;
  document.getElementById("overview-actions-label").textContent = n ? t("multibatch.open_n", { n: fmtCount(n) }) : t("multibatch.open");
  const all = document.getElementById("ov-pick-all");
  if (all) {
    const total = ovPickable().length;
    all.checked = !!total && n === total;
    all.indeterminate = n > 0 && n < total;
  }
}

function mbOpLabel(op) { return t("multibatch.op_" + op); }
function mbCheck(attr, label, on, { danger = false, disabled = false, hint = "" } = {}) {
  return `<label class="check-option${danger ? " is-danger" : ""}"${hint ? ` title="${escapeHtml(hint)}"` : ""}>` +
    `<input type="checkbox" ${attr}${on ? " checked" : ""}${disabled ? " disabled" : ""} />` +
    `${danger ? icon("trash") : ""}<span>${escapeHtml(label)}</span></label>`;
}
function mbFieldGrid(op, keys, isOn, labelOf, iconOf) {
  return `<div class="required-grid mbatch-fields">` + keys.map(k =>
    `<label class="required-item"><input type="checkbox" data-mb-field="${op}" value="${escapeHtml(k)}"${isOn(k) ? " checked" : ""} />` +
    `${icon(iconOf(k))}<span>${escapeHtml(labelOf(k))}</span></label>`).join("") + `</div>`;
}
function mbSectionHtml(op, inner, desc) {
  const p = mbatch.prefs[op];
  return `<section class="mbatch-section${p.on ? " is-on" : ""}" data-mb-section="${op}">` +
    `<label class="mbatch-section-head"><input type="checkbox" data-mb-on="${op}"${p.on ? " checked" : ""} />` +
    `${icon(MB_OP_ICONS[op])}<span class="mbatch-section-title">${escapeHtml(mbOpLabel(op))}</span></label>` +
    `<p class="bulk-hint">${escapeHtml(desc)}</p><div class="mbatch-section-body">${inner}</div></section>`;
}
function mbSetupHtml() {
  const o = mbatch.options || {};
  const p = mbatch.prefs;
  const byKey = Object.fromEntries(getFields(true).map(f => [f.key, f]));
  const systems = `<div class="mbatch-systems"><span class="mbatch-systems-label">${escapeHtml(t("multibatch.systems", { n: fmtCount(mbatch.systems.length) }))}</span>` +
    mbatch.systems.map(s => `<span class="ov-chip" title="${escapeHtml(s.xml)}">${escapeHtml(s.label)}</span>`).join("") + `</div>`;
  const roms = mbSectionHtml("roms", `<div class="check-options">` +
    mbCheck('data-mb-opt="roms.add"', t("multibatch.roms_add"), p.roms.add) +
    mbCheck('data-mb-opt="roms.remove"', t("multibatch.roms_remove"), p.roms.remove) +
    mbCheck('data-mb-opt="roms.delete_media"', t("romcheck.delete_media"), p.roms.delete_media, { danger: true, disabled: !p.roms.remove }) +
    `</div>`, t("multibatch.roms_desc"));
  const media = mbSectionHtml("media", `<div class="check-options">` +
    mbCheck('data-mb-opt="media.unlink"', t("multibatch.media_unlink"), p.media.unlink) +
    mbCheck('data-mb-opt="media.delete"', t("multibatch.media_delete"), p.media.delete, { danger: true }) +
    `</div>`, t("multibatch.media_desc"));
  const solid = mbSectionHtml("solid",
    mbFieldGrid("solid", o.image_fields || [], k => !p.solid.off.has(k), k => (byKey[k] ? byKey[k].label : k), k => (byKey[k] ? byKey[k].icon : "photo")) +
    `<div class="check-options">${mbCheck('data-mb-opt="solid.files"', t("bulk.solid_files"), p.solid.files, { danger: true, hint: t("bulk.solid_files_hint") })}</div>`,
    t("bulk.solid_hint"));
  const clear = mbSectionHtml("clear",
    mbFieldGrid("clear", o.clear_fields || [], k => p.clear.fields.has(k), bulkFieldLabel, () => "eraser"),
    t("multibatch.clear_desc"));
  const known = new Set(o.scrape_fields || []);
  const scrapeKeys = list => list.filter(k => known.has(k));
  const scrape = mbSectionHtml("scrape",
    `<div class="ss-toolbar"><div class="segmented" role="group" aria-label="${escapeHtml(t("scrape.selection"))}">` +
    ["missing", "all"].map(m => `<button type="button" class="seg" data-mb-mode="${m}" aria-pressed="${p.scrape.mode === m}">` +
      `<span>${escapeHtml(t(m === "missing" ? "scrape.preset_missing" : "scrape.preset_all"))}</span></button>`).join("") +
    `</div><span class="ss-count">${escapeHtml(t(p.scrape.mode === "missing" ? "multibatch.scrape_missing" : "batch.mode_all"))}</span></div>` +
    `<h4 class="ss-section-title">${escapeHtml(t("scrape.section_media"))}</h4>` +
    mbFieldGrid("scrape", scrapeKeys(BATCH_MEDIA), k => !p.scrape.off.has(k), scrapeFieldLabel, k => SCRAPE_MEDIA_ICONS[k] || "list-details") +
    `<h4 class="ss-section-title">${escapeHtml(t("scrape.section_info"))}</h4>` +
    mbFieldGrid("scrape", scrapeKeys(BATCH_INFO), k => !p.scrape.off.has(k), scrapeFieldLabel, () => "list-details") +
    `<p class="bulk-hint">${icon("shield-check")}<span>${escapeHtml(t("multibatch.scrape_limits"))}</span></p>`,
    t("multibatch.scrape_desc"));
  return systems + roms + media + solid + clear + scrape;
}
/** The operations as /api/multibatch expects them (only the ticked sections). */
function mbOps() {
  const p = mbatch.prefs, o = mbatch.options || {};
  const ops = {};
  if (p.roms.on && (p.roms.add || p.roms.remove)) ops.roms = { add: p.roms.add, remove: p.roms.remove, delete_media: p.roms.remove && p.roms.delete_media };
  if (p.media.on && (p.media.unlink || p.media.delete)) ops.media = { unlink: p.media.unlink, delete: p.media.delete };
  if (p.solid.on) {
    const fields = (o.image_fields || []).filter(k => !p.solid.off.has(k));
    if (fields.length) ops.solid = { fields, files: p.solid.files };
  }
  if (p.clear.on && p.clear.fields.size) ops.clear = { fields: (o.clear_fields || []).filter(k => p.clear.fields.has(k)) };
  if (p.scrape.on) {
    const known = new Set(o.scrape_fields || []);
    const fields = [...BATCH_MEDIA, ...BATCH_INFO].filter(k => known.has(k) && !p.scrape.off.has(k));
    if (fields.length) ops.scrape = { mode: p.scrape.mode, fields };
  }
  return ops;
}
function mbDeletions(ops) {
  const out = [];
  if (ops.roms && ops.roms.delete_media) out.push(t("romcheck.delete_media"));
  if (ops.media && ops.media.delete) out.push(t("multibatch.media_delete"));
  if (ops.solid && ops.solid.files) out.push(t("bulk.solid_files"));
  return out;
}
function mbUpdateSetup() {
  const p = mbatch.prefs;
  for (const op of MB_OPS) {
    const sec = document.querySelector(`[data-mb-section="${op}"]`);
    if (!sec) continue;
    sec.classList.toggle("is-on", p[op].on);
    sec.querySelectorAll(".mbatch-section-body input, .mbatch-section-body button").forEach(el => {
      el.disabled = !p[op].on || (el.dataset.mbOpt === "roms.delete_media" && !p.roms.remove);
    });
  }
  const n = Object.keys(mbOps()).length;
  document.getElementById("mbatch-start").disabled = !n;
  document.getElementById("mbatch-start-label").textContent = t("multibatch.start_n", { n: fmtCount(mbatch.systems.length) });
}

function mbResultText(op, step) {
  if (step.state === "error") return step.error || t("errors.internal");
  const r = step.result;
  if (!r) return "";
  const parts = [];
  if (r.skipped === "saved_batch") parts.push(t("multibatch.r_saved_batch"));
  else if (r.nothing) parts.push(t("multibatch.r_nothing"));
  else if (op === "roms") {
    parts.push(t("multibatch.r_roms", { added: fmtCount(r.added), removed: fmtCount(r.removed) }));
    if (r.media_deleted) parts.push(t("multibatch.r_files_deleted", { n: fmtCount(r.media_deleted) }));
  } else if (op === "media") {
    parts.push(t("multibatch.r_media", { unlinked: fmtCount(r.unlinked), deleted: fmtCount(r.deleted) }));
    if (r.failed) parts.push(t("multibatch.r_failed", { n: fmtCount(r.failed) }));
  } else if (op === "solid") {
    parts.push(t("multibatch.r_solid", { removed: fmtCount(r.removed), games: fmtCount(r.games) }));
    if (r.deleted) parts.push(t("multibatch.r_files_deleted", { n: fmtCount(r.deleted) }));
    if (r.failed) parts.push(t("multibatch.r_failed", { n: fmtCount(r.failed) }));
  } else if (op === "clear") {
    parts.push(t("multibatch.r_clear", { changed: fmtCount(r.changed), games: fmtCount(r.games) }));
  } else if (op === "scrape") {
    parts.push(t("multibatch.r_scrape", { updated: fmtCount(r.updated), done: fmtCount(r.done), total: fmtCount(r.total) }));
    if (r.uncertain || r.errors) parts.push(t("multibatch.r_scrape_more", { uncertain: fmtCount(r.uncertain), errors: fmtCount(r.errors) }));
    if (r.stopped) parts.push(t("multibatch.r_stopped"));
  }
  if (r.suspicious) parts.push(t(op === "roms" ? "multibatch.r_suspicious_roms" : "multibatch.r_suspicious_media", { n: fmtCount(r.suspicious) }));
  if (op === "scrape" && r.source && SCRAPERS[r.source]) parts.push(SCRAPERS[r.source].label);
  return parts.join(" · ");
}
function mbStateChip(state) {
  const ico = { done: "circle-check", error: "alert-circle", running: null, stopped: "player-stop", skipped: "player-skip-forward" }[state];
  return `<span class="ov-chip mb-state is-${state}">${state === "running" ? spinnerHtml("spinner-sm") : (ico ? icon(ico) : "")}` +
    `${escapeHtml(t("multibatch.state_" + state))}</span>`;
}
function mbRunHtml(d) {
  let html = "";
  if (d.state === "halted") html += `<p class="bulk-hint bulk-error mbatch-banner">${icon("alert-circle")}<span>${escapeHtml(t("multibatch.halted", { reason: d.halted }))}</span></p>`;
  else if (d.state === "stopped") html += `<p class="bulk-hint bulk-warn mbatch-banner">${icon("alert-triangle")}<span>${escapeHtml(t("multibatch.stopped"))}</span></p>`;
  else if (d.state === "done") {
    const errors = d.systems.filter(s => s.state === "error").length;
    html += `<p class="bulk-hint mbatch-banner ${errors ? "bulk-warn" : "is-ok"}">${icon(errors ? "alert-triangle" : "circle-check")}` +
      `<span>${escapeHtml(t(errors ? "multibatch.done_errors" : "multibatch.done", { n: fmtCount(d.systems.length), errors: fmtCount(errors) }))}</span></p>`;
  }
  const ops = MB_OPS.filter(op => d.ops && d.ops[op]);
  html += `<div class="overview-table-wrap"><table class="overview-table mbatch-table" id="mbatch-table"><thead><tr>` +
    `<th><span class="ov-th">${escapeHtml(t("overview.col_system"))}</span></th>` +
    ops.map(op => `<th><span class="ov-th">${icon(MB_OP_ICONS[op])}${escapeHtml(mbOpLabel(op))}</span></th>`).join("") +
    `</tr></thead><tbody>` + d.systems.map(s => {
      const steps = Object.fromEntries(s.steps.map(x => [x.op, x]));
      return `<tr class="mb-row is-${s.state}" data-mb-system="${escapeHtml(s.folder)}"><td class="ov-system"><span class="ov-name">${escapeHtml(s.label)}</span>` +
        `<div>${mbStateChip(s.state)}${s.error ? `<span class="mb-error">${escapeHtml(s.error)}</span>` : ""}</div></td>` +
        ops.map(op => {
          const step = steps[op] || { state: "skipped" };
          const text = mbResultText(op, step);
          const bak = step.result && step.result.backup ? `<span class="ov-chip mb-backup" title="${escapeHtml(t("multibatch.r_backup_title"))}">${icon("device-floppy")}${escapeHtml(t("multibatch.r_backup"))}</span>` : "";
          return `<td class="mb-step is-${step.state}" data-mb-step="${op}">${step.state === "done" ? "" : mbStateChip(step.state)}` +
            `${text ? `<span class="mb-text">${escapeHtml(text)}</span>` : ""}${bak}</td>`;
        }).join("") + `</tr>`;
    }).join("") + `</tbody></table></div>`;
  if (d.state !== "running") {
    html += `<p class="bulk-hint">${icon("arrow-back-up")}<span>${escapeHtml(t(d.reopened ? "multibatch.reopened" : "multibatch.closed_after"))}</span></p>`;
  }
  return html;
}
function renderMultiBatch() {
  const body = document.getElementById("mbatch-body");
  const start = document.getElementById("mbatch-start");
  const cancel = document.getElementById("mbatch-cancel");
  const back = document.getElementById("mbatch-back");
  const prog = document.getElementById("mbatch-progress");
  const closeBtn = document.getElementById("mbatch-close");
  if (mbatch.phase === "setup") {
    prog.hidden = true;
    back.hidden = true;
    start.hidden = false;
    closeBtn.hidden = false;
    cancel.disabled = false;
    cancel.textContent = t("confirm.cancel");
    body.innerHTML = mbSetupHtml();
    mbUpdateSetup();
    return;
  }
  const d = mbatch.data;
  const running = !!d && d.state === "running";
  start.hidden = true;
  closeBtn.hidden = running;
  back.hidden = running;
  cancel.textContent = t(running ? (mbatch.stopping ? "multibatch.stopping" : "batch.stop") : "tools.close");
  cancel.disabled = running && mbatch.stopping;
  prog.hidden = !running;
  if (!d) { body.innerHTML = busyHtml(t("common.loading"), "bulk-empty"); return; }
  if (running) {
    body.setAttribute("aria-busy", "true");
    const n = d.systems.length || 1;
    const c = d.current;
    let frac = d.systems.filter(s => !["pending", "running"].includes(s.state)).length;
    let text = t("multibatch.progress_wait");
    if (c) {
      const ops = MB_OPS.filter(op => d.ops[op]);
      const at = c.op ? ops.indexOf(c.op) : 0;
      frac = c.index + (Math.max(0, at) + (c.total ? c.done / c.total : 0)) / (ops.length || 1);
      text = t("multibatch.progress", { i: fmtCount(c.index + 1), n: fmtCount(d.systems.length), system: c.label }) +
        (c.op ? " · " + mbOpLabel(c.op) + (c.total ? ` ${fmtCount(c.done)}/${fmtCount(c.total)}` : "") : "");
    }
    document.getElementById("mbatch-bar").style.width = Math.min(100, Math.round(frac * 100 / n)) + "%";
    document.getElementById("mbatch-progress-text").textContent = text;
  } else {
    body.removeAttribute("aria-busy");
  }
  const wrap = body.querySelector(".overview-table-wrap");
  const top = wrap ? wrap.scrollTop : 0;
  body.innerHTML = mbRunHtml(d);
  const again = body.querySelector(".overview-table-wrap");
  if (again) again.scrollTop = top;
}
async function pollMultiBatch(seq) {
  clearTimeout(mbatch.timer);
  try {
    const d = await apiFetch("/api/multibatch");
    if (seq !== mbatch.seq) return;
    const wasRunning = mbatch.data && mbatch.data.state === "running";
    mbatch.data = d;
    renderMultiBatch();
    if (d.state === "running") mbatch.timer = setTimeout(() => pollMultiBatch(seq), 500);
    else if (wasRunning || mbatch.reload) {
      mbatch.reload = false;
      mbatch.stopping = false;
      renderMultiBatch();
      await loadGames();                     // the gamelist open before is open again (or none)
      refreshSystemsSwitcher();
    }
  } catch (e) {
    if (seq === mbatch.seq) {
      handleError(e);
      mbatch.timer = setTimeout(() => pollMultiBatch(seq), 1500);
    }
  }
}
async function openMultiBatch() {
  const systems = ovPicked();
  if (!systems.length) return;
  try {
    const d = await apiFetch("/api/multibatch");
    mbatch.options = d.options;
    if (d.state === "running") { showMultiBatchRun(d); return; }
  } catch (e) { handleError(e); return; }
  mbatch.phase = "setup";
  mbatch.systems = systems.map(s => ({ xml: s.xml, label: s.label, folder: s.folder }));
  document.getElementById("mbatch-modal").classList.add("open");
  renderMultiBatch();
  document.getElementById("mbatch-close").focus();
}
function showMultiBatchRun(d) {
  mbatch.phase = "run";
  mbatch.data = d;
  mbatch.stopping = false;
  mbatch.reload = true;
  document.getElementById("mbatch-modal").classList.add("open");
  renderMultiBatch();
  pollMultiBatch(++mbatch.seq);
}
function closeMultiBatch() {
  const modal = document.getElementById("mbatch-modal");
  if (!modal.classList.contains("open")) return;
  if (mbatch.phase === "run" && mbatch.data && mbatch.data.state === "running") return;   // Stop first
  modal.classList.remove("open");
  mbatch.seq++;
  clearTimeout(mbatch.timer);
  if (mbatch.phase === "run") {
    mbatch.phase = "setup";
    if (document.getElementById("overview-modal").classList.contains("open")) openOverview();
  }
}
async function startMultiBatch() {
  const ops = mbOps();
  if (!Object.keys(ops).length) return;
  if (!(await confirmLeaveEditor())) return;
  const deletions = mbDeletions(ops);
  let body = `<p>${escapeHtml(t("multibatch.confirm", { n: fmtCount(mbatch.systems.length) }))}</p>` +
    `<ul class="bulk-list">${MB_OPS.filter(op => ops[op]).map(op => `<li>${escapeHtml(mbOpLabel(op))}</li>`).join("")}</ul>` +
    `<p class="bulk-hint">${escapeHtml(t("multibatch.confirm_backup"))}</p>`;
  if (ops.scrape) body += `<p class="bulk-hint">${escapeHtml(t("multibatch.confirm_scrape"))}</p>`;
  if (deletions.length) {
    body += `<p class="bulk-warn"><strong>${escapeHtml(t("multibatch.confirm_delete"))}</strong></p>` +
      `<ul class="bulk-list bulk-warn">${deletions.map(x => `<li>${escapeHtml(x)}</li>`).join("")}</ul>`;
  }
  const choice = await askConfirm({
    title: t("multibatch.title"), bodyHtml: body, showBackup: false,
    okLabel: t(deletions.length ? "multibatch.ok_delete" : "multibatch.ok", { n: fmtCount(mbatch.systems.length) }),
    okClass: deletions.length ? "btn-danger" : "btn-accent",
  });
  if (!choice.confirmed) return;
  const startBtn = document.getElementById("mbatch-start");
  setBusy(startBtn, true);
  try {
    const d = await apiFetch("/api/multibatch", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ systems: mbatch.systems.map(s => s.xml), ops, confirm_delete: deletions.length ? true : undefined }),
    });
    mbatch.reload = false;
    mbatch.phase = "run";
    mbatch.data = d;
    mbatch.stopping = false;
    renderMultiBatch();
    pollMultiBatch(++mbatch.seq);
  } catch (e) {
    handleError(e);
  } finally {
    setBusy(startBtn, false);
  }
}
document.getElementById("overview-actions").addEventListener("click", openMultiBatch);
document.getElementById("overview-modal").addEventListener("change", e => {
  const pick = e.target.closest("[data-ov-pick]");
  if (pick) {
    if (pick.checked) overview.picked.add(pick.dataset.ovPick);
    else for (const x of [...overview.picked]) if (recentKey(x) === recentKey(pick.dataset.ovPick)) overview.picked.delete(x);
    pick.closest("tr").classList.toggle("is-picked", pick.checked);
    updateOverviewActions();
    return;
  }
  if (e.target.id === "ov-pick-all") {
    overview.picked = new Set(e.target.checked ? ovPickable().map(s => s.xml) : []);
    document.querySelectorAll("[data-ov-pick]").forEach(cb => {
      cb.checked = e.target.checked;
      cb.closest("tr").classList.toggle("is-picked", cb.checked);
    });
    updateOverviewActions();
  }
});
document.getElementById("mbatch-modal").addEventListener("change", e => {
  const p = mbatch.prefs;
  const el = e.target;
  if (el.dataset.mbOn) p[el.dataset.mbOn].on = el.checked;
  else if (el.dataset.mbOpt) {
    const [op, key] = el.dataset.mbOpt.split(".");
    p[op][key] = el.checked;
    if (el.dataset.mbOpt === "roms.remove" && !el.checked) {
      p.roms.delete_media = false;
      const dm = document.querySelector('[data-mb-opt="roms.delete_media"]');
      if (dm) dm.checked = false;
    }
  } else if (el.dataset.mbField) {
    const op = el.dataset.mbField;
    if (op === "clear") { if (el.checked) p.clear.fields.add(el.value); else p.clear.fields.delete(el.value); }
    else if (el.checked) p[op].off.delete(el.value);
    else p[op].off.add(el.value);
  } else return;
  mbUpdateSetup();
});
document.getElementById("mbatch-modal").addEventListener("click", e => {
  if (e.target.id === "mbatch-modal") { closeMultiBatch(); return; }
  const mode = e.target.closest("[data-mb-mode]");
  if (mode && !mode.disabled) {
    mbatch.prefs.scrape.mode = mode.dataset.mbMode;
    renderMultiBatch();
    const again = document.querySelector(`[data-mb-mode="${mode.dataset.mbMode}"]`);
    if (again) again.focus();
  }
});
document.getElementById("mbatch-start").addEventListener("click", startMultiBatch);
document.getElementById("mbatch-close").addEventListener("click", closeMultiBatch);
document.getElementById("mbatch-back").addEventListener("click", () => {
  closeMultiBatch();
  if (!document.getElementById("overview-modal").classList.contains("open")) openOverview();
});
document.getElementById("mbatch-cancel").addEventListener("click", async () => {
  if (mbatch.phase === "run" && mbatch.data && mbatch.data.state === "running") {
    mbatch.stopping = true;
    renderMultiBatch();
    try { await apiFetch("/api/multibatch/stop", { method: "POST" }); } catch (err) { handleError(err); }
    return;
  }
  closeMultiBatch();
});
/** A run started before a reload: show it again. */
async function reattachMultiBatch() {
  try {
    const d = await apiFetch("/api/multibatch");
    mbatch.options = d.options;
    if (d.state === "running") showMultiBatchRun(d);
  } catch (_) { /* older server */ }
}

boot();
