const FIELDS = [
{ key: "image",   label: "Image (screenshot)", icon: "🖼️" },
{ key: "video",   label: "Vidéo",              icon: "🎬" },
{ key: "marquee", label: "Marquee",            icon: "🏷️" },
{ key: "manual",  label: "Manuel (PDF)",       icon: "📖" },
{ key: "boxback", label: "Box Back",           icon: "📦" },
];
const SPECIAL_FLAGS = { wr: "🌍", world: "🌍", multi: "🌐", unk: "🏳️", xx: "🏳️" };
const LANG_TO_FLAGCDN = { en: "gb", jp: "jp", ja: "jp", ko: "kr", zh: "cn", cn: "cn", us: "us", br: "br", eu: "eu" };
const GENRES = {
"ACTION": ["AVENTURE","CASSE BRIQUES","ESCALADE","LABYRINTHE"],
"ADULTE": [],
"AVENTURE": ["3D TEMPS RÉEL","FILM INTERACTIF","GRAPHIQUE","POINT AND CLICK","ROMAN VISUEL","SURVIE HORREUR","TEXTE"],
"BEAT'EM ALL": [],
"CASINO": ["CARTES","COURSE","LOTERIE","MACHINE A SOUS","ROULETTE"],
"CASUAL GAME": [],
"CHASSE ET PECHE": ["CHASSE","PECHE"],
"COMBAT": ["2.5D","2D","3D","VERSUS","VERSUS CO-OP","VERTICAL"],
"COMPILATION": [],
"COURSE, CONDUITE": ["AVION","BATEAU","COURSE","COURSE DE MOTO VUE 1ER PERS.","COURSE DE MOTO VUE 3EME PERS.","COURSE VUE 1ERE PERS.","COURSE VUE 3EME PERS.","DELTAPLANE","MOTO"],
"DEMO": [],
"DIVERS": ["ELECTRO-MECANIQUE","PRINT CLUB","SYSTÈME","UTILITAIRES"],
"FLIPPER": [],
"JEU DE CARTES": [],
"JEU DE RÔLES": ["ACTION RPG","DUNGEON RPG","JEU DE RÔLE JAPONAIS","JEU DE RÔLE TACTIQUE","JEU DE RÔLES EN ÉQUIPE","MMORPG"],
"JEU DE SOCIETE / PLATEAU": [],
"JEU DE SOCIETE ASIATIQUE": ["GO","HANAFUDA","MAHJONG","OTHELLO","RENJU","SHOUGI"],
"LUDO-EDUCATIF": [],
"MUSIQUE ET DANSE": ["RYTHME"],
"PACHINKO": [],
"PLATEFORME": ["FIGHTER SCROLLING","RUN JUMP","RUN JUMP SCROLLING","SHOOTER SCROLLING"],
"PUZZLE-GAME": ["EGALER","GLISSER","LANCER","TOMBER"],
"QUIZ": ["ALLEMAND","ANGLAIS","CORÉEN","ESPAGNOL","FRANÇAIS","ITALIEN","JAPONAIS","MUSICAL ANGLAIS","MUSICAL JAPONAIS"],
"RÉFLEXION": [],
"SHOOT'EM UP": ["DIAGONAL","HORIZONTAL","VERTICAL","SHOOTER SMALL"],
"SIMULATION": ["CONSTRUCTION & MANAGEMENT","SCIENCE FICTION","VÉHICULES","VIE"],
"SPORT": ["BASEBALL","BASKETBALL","BILLARD","BOWLING","BOXE","BRAS DE FER","COMBAT","COURSE A PIED","DODGEBALL","FLECHETTE","FOOTBALL","FOOTBALL AMÉRICAIN","GOLF","HANDBALL","HOCKEY","JEU DE PALET","LUTTE","NATATION","PARACHUTISME","PING PONG","RUGBY","SKATEBOARD","SKI","SUMO","TENNIS","VOLLEYBALL"],
"SPORT AVEC ANIMAUX": ["COURSE DE CHEVAUX"],
"STRATÉGIE": [],
"TIR": ["1ERE PERSONNE","3EME PERSONNE","A PIED","AVION","AVION, 1ERE PERSONNE","AVION, 3EME PERSONNE","HORIZONTAL","MISSILE COMMAND LIKE","RUN AND GUN","SPACE INVADERS LIKE","VÉHICULE, 1ERE PERSONNE","VEHICULE, 3EME PERSONNE","VÉHICULE, DIAGONAL","VÉHICULE, HORIZONTAL","VÉHICULE, VERTICAL","VERTICAL"],
"TIR AVEC ACCESSOIRE": []
};
let games = [];
let currentIndex = null;
let currentListIndex = null;
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
return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
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
async function loadGames() {
setStatus("Chargement…");
try {
const res = await fetch("/api/games");
games = await res.json();
if (games.error) throw new Error(games.error);
document.getElementById("game-count").textContent = games.length + " jeux";
renderList();
setStatus("Prêt — " + games.length + " jeux chargés");
} catch (e) {
toast("Erreur chargement : " + e.message, "error");
setStatus("Erreur");
}
}
function renderList(filter = "") {
const list = document.getElementById("game-list");
const q = filter.toLowerCase().trim();
list.innerHTML = "";
games.forEach((g, i) => {
if (q && !g.name.toLowerCase().includes(q) && !g.path.toLowerCase().includes(q)) return;
const div = document.createElement("div");
div.className = "game-item" + (currentListIndex === i ? " active" : "");
div.dataset.listIndex = i;
const dots = FIELDS.map(f => `<span class="dot ${g[f.key] ? "filled" : ""}" title="${f.label}"></span>`).join("");
div.innerHTML = `<div class="name">${escapeHtml(g.name)}</div><div class="path">${escapeHtml(g.path)}</div><div class="media-dots">${dots}</div>`;
div.addEventListener("click", () => selectGame(i));
list.appendChild(div);
});
}
function selectGame(listIndex) {
const g = games[listIndex];
currentIndex = g.index;
currentListIndex = listIndex;
document.getElementById("empty-state").style.display = "none";
document.getElementById("editor").style.display = "flex";
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
el.classList.toggle("active", parseInt(el.dataset.listIndex) === listIndex);
});
renderZones(g);
}
function updateLangFlag(code) {
const key = (code || "").toLowerCase().trim();
const img = document.getElementById("lang-flag-img");
const fallback = document.getElementById("lang-flag-fallback");
const container = document.getElementById("lang-flag");
container.title = key ? key.toUpperCase() : "";
if (SPECIAL_FLAGS[key]) {
img.style.display = "none"; img.removeAttribute("src");
fallback.style.display = "inline"; fallback.textContent = SPECIAL_FLAGS[key];
return;
}
if (!key) {
img.style.display = "none"; fallback.style.display = "inline"; fallback.textContent = "🌐";
return;
}
const flagCode = LANG_TO_FLAGCDN[key] || key;
img.onload = () => { img.style.display = "block"; fallback.style.display = "none"; };
img.onerror = () => { img.style.display = "none"; fallback.style.display = "inline"; fallback.textContent = "🏳️"; };
img.src = `https://flagcdn.com/24x18/${flagCode}.png`;
img.alt = key.toUpperCase();
}
function renderZones(g) {
const grid = document.getElementById("media-grid");
grid.innerHTML = "";
FIELDS.forEach(f => {
const has = !!g[f.key];
const zone = document.createElement("div");
zone.className = "drop-zone" + (has ? " has-media" : "");
zone.dataset.field = f.key;
let previewHtml = "";
if (has) {
const url = mediaUrl(g[f.key]);
if (f.key === "video") {
previewHtml = `<video src="${url}" controls muted style="max-height:140px"></video>`;
} else if (f.key === "manual") {
previewHtml = `<div class="placeholder"><div class="big">📄</div><div>Manuel PDF</div><a href="${url}" target="_blank" style="color:var(--accent);font-size:0.8rem">Ouvrir</a></div>`;
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
if (dt.files && dt.files.length > 0) { await uploadFile(field, dt.files[0]); return; }
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
if (url) await uploadUrl(field, url);
else toast("Aucun fichier ou URL détecté", "error");
}
async function uploadFile(field, file) {
setStatus("Envoi du fichier…");
const form = new FormData(); form.append("file", file);
try {
const res = await fetch(`/api/upload/${currentIndex}/${field}`, { method: "POST", body: form });
const data = await res.json();
if (!res.ok || data.error) throw new Error(data.error || "Erreur serveur");
const g = games.find(x => x.index === currentIndex);
if (g) { g[field] = data.path; renderZones(g); }
renderList(document.getElementById("search").value);
toast(`✓ ${field} mis à jour → ${data.filename}`);
setStatus("Enregistré");
} catch (e) { toast("Erreur : " + e.message, "error"); setStatus("Erreur"); }
}
async function uploadUrl(field, url) {
setStatus("Téléchargement depuis le web…");
const form = new FormData(); form.append("url", url);
try {
const res = await fetch(`/api/upload/${currentIndex}/${field}`, { method: "POST", body: form });
const data = await res.json();
if (!res.ok || data.error) throw new Error(data.error || "Erreur serveur");
const g = games.find(x => x.index === currentIndex);
if (g) { g[field] = data.path; renderZones(g); }
renderList(document.getElementById("search").value);
toast(`✓ ${field} téléchargé → ${data.filename}`);
setStatus("Enregistré");
} catch (e) { toast("Erreur : " + e.message, "error"); setStatus("Erreur"); }
}
async function clearField(field) {
if (!confirm(`Supprimer le champ « ${field} » ?`)) return;
try {
const res = await fetch(`/api/clear/${currentIndex}/${field}`, { method: "POST" });
const data = await res.json();
if (!res.ok || data.error) throw new Error(data.error || "Erreur");
const g = games.find(x => x.index === currentIndex);
if (g) { g[field] = ""; renderZones(g); }
renderList(document.getElementById("search").value);
toast("Champ supprimé");
} catch (e) { toast("Erreur : " + e.message, "error"); }
}
async function saveName() {
if (currentIndex === null) return;
const newName = document.getElementById("game-name-input").value.trim();
if (!newName) { toast("Le nom ne peut pas être vide", "error"); return; }
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
toast("✓ Nom enregistré"); setStatus("Enregistré");
} catch (e) { toast("Erreur : " + e.message, "error"); setStatus("Erreur"); }
}
async function saveDesc() {
if (currentIndex === null) return;
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
toast("✓ Description enregistrée"); setStatus("Enregistré");
} catch (e) { toast("Erreur : " + e.message, "error"); setStatus("Erreur"); }
}
async function saveMeta() {
if (currentIndex === null) return;
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
toast("✓ Métadonnées enregistrées"); setStatus("Enregistré");
} catch (e) { toast("Erreur : " + e.message, "error"); setStatus("Erreur"); }
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
document.getElementById("search").addEventListener("input", e => renderList(e.target.value));
document.getElementById("meta-genre-main").addEventListener("change", e => fillSubGenres(e.target.value));
document.getElementById("btn-purge-regions").addEventListener("click", async () => {
if (!confirm("Supprimer TOUTES les balises <region>…</region> de TOUS les jeux ?\n\nAction irréversible.")) return;
setStatus("Suppression des <region>…");
try {
const res = await fetch("/api/purge-regions", { method: "POST" });
const data = await res.json();
if (!res.ok || data.error) throw new Error(data.error || "Erreur serveur");
toast(`✓ ${data.removed} balise(s) <region> supprimée(s)`);
setStatus("Terminé");
} catch (e) { toast("Erreur : " + e.message, "error"); setStatus("Erreur"); }
});
document.getElementById("btn-delete-game").addEventListener("click", async () => {
if (currentIndex === null) return;
const g = games.find(x => x.index === currentIndex);
const name = g ? g.name : "ce jeu";
const ok = confirm(
`Supprimer définitivement « ${name} » ?\n\n` +
`Cela effacera :\n` +
`• la ROM\n• l'image, la vidéo, le marquee, le manuel, le boxback\n` +
`• et toute l'entrée dans gamelist.xml\n\n` +
`Cette action est IRRÉVERSIBLE.`
);
if (!ok) return;
setStatus("Suppression du jeu…");
try {
const res = await fetch(`/api/delete-game/${currentIndex}`, { method: "POST" });
const data = await res.json();
if (!res.ok || data.error) throw new Error(data.error || "Erreur serveur");
const nFiles = (data.deleted_files || []).length;
toast(`✓ « ${data.name} » supprimé (${nFiles} fichier(s) effacé(s))`);
currentIndex = null;
currentListIndex = null;
document.getElementById("btn-delete-game").disabled = true;
document.getElementById("editor").style.display = "none";
document.getElementById("empty-state").style.display = "flex";
await loadGames();
} catch (e) {
toast("Erreur : " + e.message, "error");
setStatus("Erreur");
}
});
initGenreSelects();
loadGames();
