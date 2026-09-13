/*
   JOBHUNTER — APPLICATION D'UN SEUL TENANT

   Le serveur ne rend qu'une coquille. Ce fichier dessine les ecrans a
   partir de JSON, anime les transitions, et garde en memoire ce qu'il a
   deja recu : revenir sur un ecran ne coute rien.

   Quatre ecrans : Aujourd'hui, Offres, Conseils, Statistiques.
   Tout ce que les versions 0.x savaient faire est conserve — triage au
   clavier, fiche de suivi, analyse d'ecart avec preuves, run en direct.
*/

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = G.esc;

/* ------------------------------------------------------------- reseau */

const cache = new Map();

async function lire(route, { frais = false } = {}) {
  if (!frais && cache.has(route)) return cache.get(route);
  const r = await fetch(route);
  const d = await r.json();
  if (!r.ok) throw new Error(d.erreur || "Erreur inconnue");
  cache.set(route, d);
  return d;
}

async function envoyer(route, charge) {
  const r = await fetch(route, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(charge || {}) });
  const d = await r.json();
  if (!r.ok) throw new Error(d.erreur || "Erreur inconnue");
  return d;
}

function invalider(...routes) { routes.forEach((r) => cache.delete(r)); }

let minuteurNotif = null;
function notifier(message, type = "ok") {
  const n = $("#notification");
  n.textContent = message; n.className = `notification ${type}`; n.hidden = false;
  clearTimeout(minuteurNotif);
  minuteurNotif = setTimeout(() => { n.hidden = true; }, 2800);
}

/* ------------------------------------------------------------ libelles */

const L = {
  action: { APPLY_NOW: "Postuler", APPLY_NEXT: "Ensuite", REVIEW_FIRST: "À relire", DO_NOT_APPLY: "Écartée" },
  verdict: { ACCESSIBLE: "Accessible", A_VERIFIER: "À vérifier", FERMEE: "Fermée", INCONNU: "Inconnu" },
  statut: { DISCOVERED: "À revoir", SHORTLISTED: "Intéressé", READY: "Prête", DOCUMENTS_READY: "Dossier prêt",
            APPLIED: "Postulé", INTERVIEW: "Entretien", OFFER: "Offre", REJECTED: "Refus", WITHDRAWN: "Écartée", CLOSED: "Close" },
};
const cls = (v) => String(v || "inconnu").toLowerCase();

/* ------------------------------------------------------------- routeur */

const ECRANS = { "/": "jour", "/offres": "offres", "/conseils": "conseils", "/statistiques": "statistiques" };
const RENDUS = {};

async function naviguer(chemin, pousser = true) {
  const nom = ECRANS[chemin] || "jour";
  if (pousser) history.pushState({}, "", chemin);
  $$(".onglets a").forEach((a) => a.classList.toggle("actif", a.dataset.ecran === nom));

  const ecran = $("#ecran");
  ecran.classList.add("sortant");
  await new Promise((r) => setTimeout(r, 130));
  ecran.classList.remove("sortant");
  ecran.innerHTML = `<div class="chargement">Chargement</div>`;
  fermerPanneau();
  try {
    await RENDUS[nom]();
  } catch (e) {
    ecran.innerHTML = `<div class="chargement">Impossible de charger cet écran.<br><small>${esc(e.message)}</small></div>`;
  }
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-lien]");
  if (!a) return;
  e.preventDefault();
  naviguer(a.getAttribute("href"));
});
window.addEventListener("popstate", () => naviguer(location.pathname, false));

function entete(titre, sous, droite = "") {
  return `<header class="entete"><div><h1>${titre}</h1>${sous ? `<p>${sous}</p>` : ""}</div><div>${droite}</div></header>`;
}

/* ============================================================ AUJOURD'HUI */

RENDUS.jour = async () => {
  const d = await lire("/api/jour", { frais: true });
  const j = d.jour, run = d.run;
  const dues = j.relances_dues || [];
  majPastilles(dues.length, d.total);

  $("#ecran").innerHTML = `
    ${entete("Aujourd'hui", "Ce qui demande une décision, et rien d'autre.",
      `<button class="bouton" id="lancer-run" ${run.en_cours ? "disabled" : ""}>${run.en_cours ? "Run en cours…" : "Lancer un run"}</button>`)}

    <div class="grille">
      <div class="carte ${dues.length ? "urgente" : ""}">
        <h3>Relances</h3><div class="grand">${dues.length}</div>
        <div class="sous">${dues.length ? "à faire aujourd'hui ou en retard" : "aucune relance programmée"}</div>
        ${dues.slice(0, 5).map((r) => `<div class="sous"><span class="num" style="color:var(--ambre)">${esc(r.next_action_date)}</span> — ${esc(r.title || "")}</div>`).join("")}
      </div>
      <div class="carte">
        <h3>À trier</h3><div class="grand">${j.a_postuler_non_triees}</div>
        <div class="sous">offres recommandées sans décision ${j.non_triees !== j.a_postuler_non_triees ? `<br><small style="color:var(--texte-3)">${j.non_triees} au total</small>` : ""}</div>
        <a class="lien" href="/offres" data-lien>Trier →</a>
      </div>
      <div class="carte">
        <h3>Nouveautés</h3><div class="grand">${j.nouveautes?.nouvelles ?? 0}</div>
        <div class="sous">nouvelles offres au dernier run${j.nouveautes?.disparues ? `<br><small style="color:var(--texte-3)">${j.nouveautes.disparues} disparue(s)</small>` : ""}</div>
      </div>
    </div>

    ${j.prioritaires?.length ? `
    <h2 class="section">Les mieux notées, en attente de décision</h2>
    <div class="tableau"><table><tbody>
      ${j.prioritaires.map((p) => `<tr data-ouvrir="${esc(p.cle)}">
        <td class="score" style="text-align:left;width:60px">${p.score}</td>
        <td class="intitule">${esc(p.titre)}<small>${esc(p.entreprise)} — ${esc(p.ville)}</small></td>
        <td><span class="badge ${cls(p.verdict)}">${esc(L.verdict[p.verdict] || p.verdict)}</span></td></tr>`).join("")}
    </tbody></table></div>` : ""}

    <h2 class="section">Dernier run</h2>
    <div class="run" id="run"></div>
    <pre class="journal" id="journal" hidden></pre>`;

  peindreRun(run);
  $("#lancer-run").addEventListener("click", lancerRun);
  $$("tr[data-ouvrir]").forEach((tr) => tr.addEventListener("click", async () => {
    await naviguer("/offres"); ouvrirPanneau(tr.dataset.ouvrir);
  }));
  if (run.en_cours) demarrerSondage();
};

function majPastilles(dues, total) {
  const p = $("#pastille-dues"); p.textContent = dues; p.hidden = !dues; p.classList.toggle("alerte", !!dues);
  const o = $("#pastille-offres"); o.textContent = total; o.hidden = !total;
}

/* ---------------------------------------------------------------- run */

let sondage = null;
function peindreRun(e) {
  const zone = $("#run"); if (!zone) return;
  zone.innerHTML = `
    <div class="run-entete">
      <span class="run-statut ${cls(e.statut)}">${esc(e.statut || "—")}</span>
      <span class="run-meta">${esc(e.run_id || "")}</span><span class="run-meta">${esc(e.duree || "")}</span>
      <span class="run-meta">${e.terminees}/${e.total_etapes} étapes</span></div>
    <div class="etapes">${(e.etapes || []).map((s) => `
      <div class="etape ${String(s["État"] || "").includes("cours") ? "active" : ""}">
        <span class="puce">${esc(String(s["État"] || "").slice(0, 1))}</span>
        <span class="nom">${esc(s["Étape"])}</span><span class="etat">${esc(s["État"])}</span></div>`).join("")}</div>`;
  const j = $("#journal");
  if (j) { if (e.en_cours && e.journal?.length) { j.textContent = e.journal.join("\n"); j.hidden = false; j.scrollTop = j.scrollHeight; } else j.hidden = true; }
  const b = $("#lancer-run");
  if (b) { b.disabled = !!e.en_cours; b.textContent = e.en_cours ? `Run en cours — ${e.etape_courante || "…"}` : "Lancer un run"; }
}
async function rafraichirRun() {
  try {
    const e = await lire("/api/run", { frais: true });
    peindreRun(e);
    if (!e.en_cours && sondage) { clearInterval(sondage); sondage = null; invalider("/api/jour", "/api/offres", "/api/statistiques", "/api/conseils"); notifier("Run terminé."); }
  } catch (_) { /* le serveur peut etre occupe par le run lui-meme */ }
}
function demarrerSondage() { if (sondage) return; sondage = setInterval(rafraichirRun, 3000); rafraichirRun(); }
async function lancerRun() {
  const b = $("#lancer-run"); b.disabled = true;
  try { await envoyer("/api/run/lancer"); notifier("Run lancé."); demarrerSondage(); }
  catch (e) { notifier(e.message, "erreur"); b.disabled = false; }
}

/* ================================================================ OFFRES */

const etatOffres = { recherche: "", filtres: { verdict: new Set(), recommended_action_v12: new Set() }, tri: { champ: "pool_rank_v12", sens: "asc" }, curseur: 0, visibles: [] };
let OFFRES = [], TRIAGE = [];

RENDUS.offres = async () => {
  const d = await lire("/api/offres", { frais: true });
  OFFRES = d.offres; TRIAGE = d.triage;
  $("#ecran").innerHTML = `
    ${entete("Offres", `Pool final — <b id="compte">${OFFRES.length}</b> sur ${OFFRES.length}`, `<div class="chiffres" id="chiffres"></div>`)}
    <div class="filtres">
      <div class="recherche"><input id="recherche" type="search" placeholder="Intitulé, entreprise, ville…" autocomplete="off"></div>
      <div id="groupes" style="display:flex;gap:14px;flex-wrap:wrap"></div>
      <button class="lien-discret" id="raz" hidden>Réinitialiser</button>
      <button class="jeton" id="aide" title="Raccourcis">⌨</button>
    </div>
    <div class="tableau"><table><thead><tr>
      <th data-tri="pool_rank_v12" data-sens="asc">#</th><th data-tri="title">Intitulé</th>
      <th data-tri="company">Entreprise</th><th data-tri="ville">Lieu</th><th data-tri="verdict">Verdict</th>
      <th data-tri="recommended_action_v12">Action</th><th data-tri="application_status">Suivi</th>
      <th data-tri="final_score_v12" class="droite">Score</th></tr></thead><tbody id="corps"></tbody></table>
      <p class="vide" id="vide" hidden>Aucune offre ne correspond.</p></div>`;

  construireFiltres(); rendreOffres();
  $("#recherche").addEventListener("input", (e) => { etatOffres.recherche = e.target.value; etatOffres.curseur = 0; rendreOffres(); });
  $("#raz").addEventListener("click", () => { etatOffres.recherche = ""; $("#recherche").value = ""; Object.values(etatOffres.filtres).forEach((s) => s.clear()); $$(".jeton[data-champ]").forEach((b) => b.setAttribute("aria-pressed", "false")); rendreOffres(); });
  $("#aide").addEventListener("click", afficherRaccourcis);
  $$("thead th[data-tri]").forEach((th) => th.addEventListener("click", () => {
    const c = th.dataset.tri; etatOffres.tri = { champ: c, sens: etatOffres.tri.champ === c && etatOffres.tri.sens === "asc" ? "desc" : "asc" };
    $$("thead th").forEach((h) => h.removeAttribute("data-sens")); th.setAttribute("data-sens", etatOffres.tri.sens); rendreOffres();
  }));
};

function construireFiltres() {
  const groupes = [
    { champ: "verdict", titre: "Verdict", lib: L.verdict, ordre: ["ACCESSIBLE", "A_VERIFIER", "FERMEE", "INCONNU"] },
    { champ: "recommended_action_v12", titre: "Action", lib: L.action, ordre: ["APPLY_NOW", "APPLY_NEXT", "REVIEW_FIRST", "DO_NOT_APPLY"] },
  ];
  $("#groupes").innerHTML = groupes.map((g) => {
    const n = {}; OFFRES.forEach((o) => { if (o[g.champ]) n[o[g.champ]] = (n[o[g.champ]] || 0) + 1; });
    const vals = g.ordre.filter((v) => n[v]); if (!vals.length) return "";
    return `<div class="groupe"><span class="titre">${g.titre}</span>${vals.map((v) =>
      `<button class="jeton" data-champ="${g.champ}" data-valeur="${v}" aria-pressed="false">${esc(g.lib[v] || v)}<span class="n">${n[v]}</span></button>`).join("")}</div>`;
  }).join("");
  $$(".jeton[data-champ]").forEach((b) => b.addEventListener("click", () => {
    const s = etatOffres.filtres[b.dataset.champ]; const v = b.dataset.valeur;
    if (s.has(v)) { s.delete(v); b.setAttribute("aria-pressed", "false"); } else { s.add(v); b.setAttribute("aria-pressed", "true"); }
    rendreOffres();
  }));
}

function filtrerOffres() {
  const q = etatOffres.recherche.trim().toLowerCase();
  return OFFRES.filter((o) => {
    for (const [c, s] of Object.entries(etatOffres.filtres)) if (s.size && !s.has(o[c])) return false;
    return !q || [o.title, o.company, o.ville, o.source].some((v) => String(v || "").toLowerCase().includes(q));
  });
}

function rendreOffres() {
  const { champ, sens } = etatOffres.tri, signe = sens === "asc" ? 1 : -1;
  const lignes = filtrerOffres().sort((a, b) => {
    const x = a[champ], y = b[champ];
    return (typeof x === "number" && typeof y === "number") ? (x - y) * signe : String(x ?? "").localeCompare(String(y ?? ""), "fr") * signe;
  });
  etatOffres.visibles = lignes;
  if (etatOffres.curseur >= lignes.length) etatOffres.curseur = Math.max(0, lignes.length - 1);

  $("#corps").innerHTML = lignes.map((o, i) => {
    const relance = o.suivi?.next_action_date;
    const due = relance && relance <= new Date().toISOString().slice(0, 10);
    return `<tr data-cle="${esc(o.stable_item_key)}" data-i="${i}">
      <td class="rang">${o.pool_rank_v12 ?? "—"}</td>
      <td class="intitule">${esc(o.title)}<small>${esc(o.source)}</small></td>
      <td class="doux">${esc(o.company)}</td><td class="doux">${esc(o.ville)}</td>
      <td><span class="badge ${cls(o.verdict)}">${esc(L.verdict[o.verdict] || "—")}</span></td>
      <td><span class="action ${cls(o.recommended_action_v12)}">${esc(L.action[o.recommended_action_v12] || "—")}</span></td>
      <td>${o.application_status ? `<span class="statut ${cls(o.application_status)}">${esc(L.statut[o.application_status] || o.application_status)}</span>` : `<span class="statut vide">—</span>`}
          ${relance ? `<span class="relance ${due ? "due" : ""}">${esc(relance.slice(5))}</span>` : ""}</td>
      <td class="score">${o.final_score_v12 ?? "—"}</td></tr>`;
  }).join("");
  $$("#corps tr").forEach((tr) => tr.addEventListener("click", () => { etatOffres.curseur = +tr.dataset.i; ouvrirPanneau(tr.dataset.cle); }));

  $("#compte").textContent = lignes.length; $("#vide").hidden = lignes.length > 0;
  const n = (v) => lignes.filter((o) => o.verdict === v).length;
  $("#chiffres").innerHTML = `
    <div class="chiffre"><b>${lignes.filter((o) => String(o.recommended_action_v12 || "").startsWith("APPLY")).length}</b><span>à postuler</span></div>
    <div class="chiffre vert"><b>${n("ACCESSIBLE")}</b><span>accessibles</span></div>
    <div class="chiffre ambre"><b>${n("A_VERIFIER")}</b><span>à vérifier</span></div>
    <div class="chiffre rouge"><b>${n("FERMEE")}</b><span>fermées</span></div>`;
  marquerCurseur();
  $("#raz").hidden = !(etatOffres.recherche || Object.values(etatOffres.filtres).some((s) => s.size));
}

function marquerCurseur() { $$("#corps tr").forEach((tr, i) => tr.classList.toggle("curseur", i === etatOffres.curseur)); }
function deplacerCurseur(pas) {
  if (!etatOffres.visibles.length) return;
  etatOffres.curseur = Math.min(etatOffres.visibles.length - 1, Math.max(0, etatOffres.curseur + pas));
  marquerCurseur(); $(`#corps tr[data-i="${etatOffres.curseur}"]`)?.scrollIntoView({ block: "nearest" });
}
const offreCourante = () => etatOffres.visibles[etatOffres.curseur] || null;

async function trierOffre(o, statut, libelle) {
  try { await envoyer("/api/statut", { cle: o.stable_item_key, statut }); o.application_status = statut; invalider("/api/jour"); notifier(`${libelle} — ${o.title.slice(0, 44)}`); rendreOffres(); }
  catch (e) { notifier(e.message, "erreur"); }
}

/* -------------------------------------------------------------- panneau */

function blocEcart(o) {
  const e = o.ecart || {}, b = e.barrieres || [], a = e.alertes || [], at = e.atouts || [], m = e.manques || [];
  if (!b.length && !a.length && !at.length && !m.length && !e.formation) return "";
  const c = (x, g) => `<div class="constat ${g}"><b>${esc(x.message)}</b>${x.preuve ? `<i>« ${esc(x.preuve)} »</i>` : ""}</div>`;
  return `<div class="bloc"><h3>Ce que dit l'annonce</h3>
    ${e.formation ? `<div class="formation">L'employeur propose une formation — diplôme et expérience ne sont plus des barrières.</div>` : ""}
    ${b.map((x) => c(x, "barriere")).join("")}${a.map((x) => c(x, "alerte")).join("")}
    ${at.length ? `<div class="etiquettes"><small>Ce qui vous sert</small>${at.map((x) => `<span class="etiquette atout">${esc(x)}</span>`).join("")}</div>` : ""}
    ${m.length ? `<div class="etiquettes"><small>Ce qui vous manque</small>${m.map((x) => `<span class="etiquette">${esc(x)}</span>`).join("")}</div>` : ""}</div>`;
}

function blocSuivi(o) {
  const s = o.suivi || {}, fait = o.application_status === "APPLIED";
  return `<div class="bloc"><h3>Suivi</h3>
    <div class="triage">${TRIAGE.map((t) => `<button class="bouton-triage ${o.application_status === t.statut ? "actif" : ""}" data-statut="${t.statut}">${esc(t.libelle)}<kbd>${esc(t.touche)}</kbd></button>`).join("")}</div>
    <div class="formulaire">
      <label>Relance prévue<input type="date" id="f-relance" value="${esc(s.next_action_date || "")}"></label>
      <div class="dates"><button data-j="3">+3 j</button><button data-j="7">+1 sem.</button><button data-j="30">+1 mois</button><button data-j="0">effacer</button></div>
      <label>Contact<input type="text" id="f-contact" placeholder="Nom du recruteur" value="${esc(s.contact_name || "")}"></label>
      <label>Canal<input type="text" id="f-canal" placeholder="Courriel, téléphone, LinkedIn…" value="${esc(s.contact_channel || "")}"></label>
      <button class="bouton second" id="f-enregistrer" style="align-self:flex-start">Enregistrer</button></div>
    <div class="zone-postule ${fait ? "faite" : ""}">${fait ? "✓ Candidature envoyée" :
      `<label class="confirmation"><input type="checkbox" id="f-confirme"> Je confirme avoir envoyé cette candidature</label>
       <button class="bouton vert" id="f-postule" disabled>Marquer comme postulée</button>`}</div></div>`;
}

function ouvrirPanneau(cle) {
  const o = OFFRES.find((x) => x.stable_item_key === cle); if (!o) return;
  $$("#corps tr").forEach((tr) => tr.classList.toggle("selectionnee", tr.dataset.cle === cle));
  const p = $("#panneau");
  p.innerHTML = `
    <button class="fermer" aria-label="Fermer">×</button>
    <h2>${esc(o.title)}</h2><div class="employeur">${esc(o.company)} — ${esc(o.ville)}</div>
    <div class="badges"><span class="badge ${cls(o.verdict)}">${esc(L.verdict[o.verdict] || o.verdict)}</span>
      <span class="badge neutre">${esc(L.action[o.recommended_action_v12] || "—")}</span>
      <span class="badge neutre">Priorité ${esc(o.priority_v12 || "—")}</span><span class="badge neutre">${esc(o.cv_track || o.track || "—")}</span></div>
    ${blocEcart(o)}${blocSuivi(o)}
    <div class="bloc"><h3>Fiche</h3><dl class="faits">
      <dt>Score</dt><dd>${o.final_score_v12 ?? "—"}</dd><dt>Rang</dt><dd>${o.pool_rank_v12 ?? "—"}</dd>
      <dt>Source</dt><dd>${esc(o.source)}</dd><dt>Filtre qualité</dt><dd>${esc(o.guard_level || "—")}</dd>
      <dt>Zone préférée</dt><dd>${o.preferred_location ? "oui" : "non"}</dd></dl></div>
    ${(o.reasons || []).length ? `<div class="bloc"><h3>Décisions du pipeline</h3><ul class="raisons">${o.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>` : ""}
    ${o.extrait ? `<div class="bloc"><h3>Extrait</h3><div class="extrait">${esc(o.extrait)}</div></div>` : ""}
    ${o.url ? `<a class="lien-offre" href="${esc(o.url)}" target="_blank" rel="noopener">Ouvrir l'offre ↗</a>` : ""}`;
  p.hidden = false; $("#voile").hidden = false; p.scrollTop = 0;

  $(".fermer", p).addEventListener("click", fermerPanneau);
  $$(".bouton-triage", p).forEach((b) => b.addEventListener("click", async () => {
    const t = TRIAGE.find((x) => x.statut === b.dataset.statut);
    await trierOffre(o, b.dataset.statut, t?.libelle || b.dataset.statut); ouvrirPanneau(cle);
  }));
  $$(".dates button", p).forEach((b) => b.addEventListener("click", () => {
    const j = +b.dataset.j; if (!j) { $("#f-relance").value = ""; return; }
    const d = new Date(); d.setDate(d.getDate() + j); $("#f-relance").value = d.toISOString().slice(0, 10);
  }));
  $("#f-enregistrer", p).addEventListener("click", async () => {
    try { const d = await envoyer("/api/suivi", { cle, next_action_date: $("#f-relance").value, contact_name: $("#f-contact").value, contact_channel: $("#f-canal").value });
      o.suivi = d.suivi; invalider("/api/jour"); notifier("Suivi enregistré."); rendreOffres(); }
    catch (e) { notifier(e.message, "erreur"); }
  });
  const conf = $("#f-confirme", p), post = $("#f-postule", p);
  if (conf && post) {
    conf.addEventListener("change", () => { post.disabled = !conf.checked; });
    post.addEventListener("click", async () => {
      try { await envoyer("/api/postule", { cle, confirme: true }); o.application_status = "APPLIED"; invalider("/api/jour", "/api/statistiques"); notifier("Candidature enregistrée comme envoyée."); rendreOffres(); ouvrirPanneau(cle); }
      catch (e) { notifier(e.message, "erreur"); }
    });
  }
}
function fermerPanneau() { $("#panneau").hidden = true; $("#voile").hidden = true; $$("#corps tr.selectionnee").forEach((tr) => tr.classList.remove("selectionnee")); }

function afficherRaccourcis() {
  $("#raccourcis").innerHTML = `<div class="carte-raccourcis"><h3>Raccourcis</h3><dl>
    <dt>j / k</dt><dd>descendre / monter</dd><dt>↵</dt><dd>ouvrir le détail</dd>
    ${TRIAGE.map((t) => `<dt>${esc(t.touche)}</dt><dd>${esc(t.libelle)}</dd>`).join("")}
    <dt>/</dt><dd>rechercher</dd><dt>Échap</dt><dd>fermer</dd></dl>
    <p>Le triage s'applique à la ligne active, sans ouvrir le détail.</p></div>`;
  $("#raccourcis").hidden = false;
}

/* ============================================================== CONSEILS */

const etatConseils = { famille: "LAB", sous: null };

RENDUS.conseils = async () => {
  // Premiere fois apres une collecte : l'artefact se calcule (~50 s).
  // On le dit, et on attend la reponse complete.
  let d = await lire("/api/conseils");
  if (d.en_cours) {
    $("#ecran").innerHTML = `<div class="chargement">Première analyse de toutes les offres scrapées<br><small style="color:var(--texte-3)">une cinquantaine de secondes, une seule fois par collecte</small></div>`;
    cache.delete("/api/conseils");
    d = await lire("/api/conseils?attendre=1", { frais: true });
    cache.set("/api/conseils", d);
  }
  const { famille, sous } = etatConseils;
  const fam = d.familles[famille];
  const cible = sous && fam.sous_categories[sous] ? fam.sous_categories[sous] : fam;
  const libCible = sous ? fam.sous_categories[sous].libelle : fam.libelle;

  $("#ecran").innerHTML = `
    ${entete("Conseils", `Ce que demandent les <b>${d.offres_cibles}</b> offres visées, sur ${G.fmt(d.offres_scrapees)} scrapées — fermées comprises.`)}
    <div class="familles">${["LAB", "DATA", "PHARMA"].map((f) =>
      `<button class="famille ${f === famille ? "actif" : ""}" data-fam="${f}"><b>${esc(d.familles[f].libelle)}</b><span>${d.familles[f].offres} offres</span></button>`).join("")}</div>
    <div class="sous-cats">
      <button class="jeton ${!sous ? "actif" : ""}" data-sous="">Toute la famille<span class="n">${fam.offres}</span></button>
      ${Object.entries(fam.sous_categories).map(([k, v]) => `<button class="jeton ${k === sous ? "actif" : ""}" data-sous="${k}">${esc(v.libelle)}<span class="n">${v.offres}</span></button>`).join("")}
    </div>
    <div class="avertissement">Ces comptages mesurent des <b>mentions</b> dans les annonces, pas des exigences formelles. Le classement relatif est fiable ; les valeurs absolues surestiment.</div>

    <h2 class="section">${esc(libCible)} — ce qui vous manque le plus</h2>
    <p class="aide">Demandé par les annonces, absent de votre profil. Classé par fréquence : c'est votre liste d'apprentissage.</p>
    <div>${cible.a_acquerir.length ? cible.a_acquerir.map((x) => G.conseil(x, "manque", cible.a_acquerir[0].part)).join("") : `<p class="rien">Rien de significatif.</p>`}</div>

    <h2 class="section">Ce que vous avez et qu'ils demandent</h2>
    <p class="aide">À écrire en tête de CV, dans ces mots-là.</p>
    <div>${cible.a_valoriser.length ? cible.a_valoriser.map((x) => G.conseil(x, "atout", cible.a_valoriser[0].part)).join("") : `<p class="rien">Rien de significatif.</p>`}</div>

    <div class="grille deux" style="margin-top:32px">
      <section><h2 class="section">Outils et logiciels</h2>${G.barres(cible.outils.map((x) => ({ nom: x.nom, valeur: x.part })), { unite: " %" })}</section>
      <section><h2 class="section">Normes et référentiels</h2>${G.barres(cible.normes.map((x) => ({ nom: x.nom, valeur: x.part })), { unite: " %" })}</section>
      <section><h2 class="section">Méthodes</h2>${G.barres(cible.methodes.map((x) => ({ nom: x.nom, valeur: x.part })), { unite: " %" })}</section>
      <section><h2 class="section">Qualités attendues</h2>${G.barres(cible.qualites.map((x) => ({ nom: x.nom, valeur: x.part })), { unite: " %" })}</section>
    </div>

    <h2 class="section">Conditions</h2>
    <div class="grille">
      <div class="carte"><h3>Langues</h3>${cible.langues.map((l) => `<div class="sous"><b style="color:var(--texte)">${esc(l.nom)}</b> ${l.part} %${l.niveau_fort ? ` <span style="color:var(--texte-3)">· niveau fort dans ${l.niveau_fort}</span>` : ""}</div>`).join("") || "<p class='rien'>—</p>"}</div>
      <div class="carte"><h3>Expérience</h3><div class="grand">${cible.experience.mediane_ans ?? "—"}<small style="font-size:14px;color:var(--texte-3)"> ans</small></div><div class="sous">médiane, sur ${cible.experience.offres_avec_exigence} offres qui en exigent</div></div>
      <div class="carte"><h3>Salaire</h3><div class="grand">${cible.salaire.mediane_brut_mensuel ? G.fmt(cible.salaire.mediane_brut_mensuel) + "<small style='font-size:14px;color:var(--texte-3)'> €</small>" : "—"}</div><div class="sous">brut mensuel médian, ${cible.salaire.offres_avec_montant} offres l'indiquent${cible.salaire.quartiles?.length ? `<br><small style="color:var(--texte-3)">quartiles ${cible.salaire.quartiles.map(G.fmt).join(" · ")}</small>` : ""}</div></div>
      <div class="carte"><h3>Contrats</h3>${cible.contrats.map((c) => `<div class="sous"><b style="color:var(--texte)">${esc(c.nom)}</b> ${c.part} %</div>`).join("") || "<p class='rien'>—</p>"}</div>
      <div class="carte"><h3>Diplôme cité</h3>${cible.diplomes.map((c) => `<div class="sous"><b style="color:var(--texte)">${esc(c.nom)}</b> ${c.part} %</div>`).join("") || "<p class='rien'>—</p>"}</div>
      <div class="carte"><h3>Durée de vie d'une offre</h3><div class="grand">${cible.duree_de_vie.mediane_jours ?? "—"}<small style="font-size:14px;color:var(--texte-3)"> j</small></div><div class="sous">médiane sur ${cible.duree_de_vie.offres_disparues} offres disparues<br><small style="color:var(--texte-3)">estimation ${esc(cible.duree_de_vie.estimation || "")}</small></div></div>
    </div>

    <div class="grille deux" style="margin-top:32px">
      <section><h2 class="section">Qui recrute</h2>${G.barres(cible.employeurs.map((x) => ({ nom: x.nom.slice(0, 26), valeur: x.offres })))}</section>
      <section><h2 class="section">Où</h2>${G.barres(cible.villes.map((x) => ({ nom: x.nom.slice(0, 26), valeur: x.offres })))}</section>
    </div>

    <h2 class="section">Nouvelles offres par semaine</h2>
    ${G.courbe(cible.evolution.map((x) => ({ x: x.semaine.replace(/^\d{4}-/, ""), y: x.offres })))}

    <div class="grille deux" style="margin-top:32px">
      <section><h2 class="section">Jour de publication</h2>${G.colonnes(cible.publication_jours.map((x) => ({ x: x.jour, y: x.offres })))}</section>
      <section><h2 class="section">Heure de publication</h2>${G.colonnes(cible.publication_heures.filter((x) => x.heure >= 6 && x.heure <= 22).map((x) => ({ x: x.heure + "h", y: x.offres })), { doux: true })}</section>
    </div>`;

  $$(".famille").forEach((b) => b.addEventListener("click", () => { etatConseils.famille = b.dataset.fam; etatConseils.sous = null; RENDUS.conseils(); }));
  $$(".sous-cats .jeton").forEach((b) => b.addEventListener("click", () => { etatConseils.sous = b.dataset.sous || null; RENDUS.conseils(); }));
};

/* ========================================================== STATISTIQUES */

RENDUS.statistiques = async () => {
  const d = await lire("/api/statistiques");
  const m = d.marche, ent = d.entonnoir || [], ev = d.evolution, rend = d.rendement || [], cand = d.candidatures || {};
  $("#ecran").innerHTML = `
    ${entete("Statistiques", "Où le tri perd des offres, quelles sources rendent, ce que deviennent vos candidatures.")}

    <h2 class="section">L'entonnoir, run après run</h2>
    ${ent.length ? G.courbe(ent.map((x) => ({ x: x.quand.slice(5, 10), y: x.pretes }))) : "<p class='rien'>Aucun artefact.</p>"}
    <p class="aide" style="margin-top:8px">Offres prêtes (READY_APPLY) à chaque run.</p>
    ${ent.length ? `<div class="tableau" style="margin-top:14px"><table><thead><tr><th>Quand</th><th class="droite">File</th><th class="droite">Prêtes</th><th class="droite">À tension</th><th class="droite">À vérifier</th><th class="droite">Écartées</th><th class="droite">Pool</th></tr></thead>
      <tbody>${ent.map((x) => `<tr><td class="doux num">${esc(x.quand)}</td><td class="droite num">${x.file}</td><td class="droite num fort">${x.pretes}</td><td class="droite num">${x.a_tension}</td><td class="droite num">${x.a_verifier}</td><td class="droite num faible">${x.ecartees}</td><td class="droite num">${x.pool ?? "—"}</td></tr>`).join("")}</tbody></table></div>` : ""}
    ${ev?.ecarts ? `<div class="chiffres" style="margin-top:14px">${Object.entries(ev.ecarts).map(([k, v]) => `<div class="chiffre"><b>${v.apres}</b><span>${esc(k.replace("_", " "))} <em style="color:${v.delta >= 0 ? "var(--vert)" : "var(--rouge)"};font-style:normal">${v.delta >= 0 ? "+" : ""}${v.delta}</em></span></div>`).join("")}</div>` : ""}

    <h2 class="section">Rendement réel des sources</h2>
    <p class="aide">Offres <b>prêtes</b> produites, pas lignes déposées. Une source volumineuse peut ne rien produire.</p>
    ${G.barres(rend.slice(0, 12).map((x) => ({ nom: `${x.source}  (${x.offres})`, valeur: x.pretes })))}

    <h2 class="section">Le marché accessible</h2>
    <div class="chiffres"><div class="chiffre"><b>${m.offres_actives}</b><span>analysées</span></div><div class="chiffre vert"><b>${m.offres_ouvertes}</b><span>sans barrière</span></div><div class="chiffre rouge"><b>${m.verdicts?.FERMEE || 0}</b><span>fermées</span></div></div>
    <div class="grille deux" style="margin-top:16px">
      <section><h3 style="font-size:13px;margin:0 0 8px">À acquérir</h3>${G.barres(m.a_acquerir.map((x) => ({ nom: x.nom, valeur: x.part })), { unite: " %" })}</section>
      <section><h3 style="font-size:13px;margin:0 0 8px">À mettre en avant</h3>${G.barres(m.a_valoriser.map((x) => ({ nom: x.nom, valeur: x.part })), { unite: " %" })}</section>
    </div>
    <p class="aide" style="margin-top:8px">${d.complet ? "Base complète." : "Aperçu sur 1 500 offres — <a href='#' id='complet' style='color:var(--accent)'>analyser toute la base</a>."} Pour le détail par catégorie, voir <a href="/conseils" data-lien style="color:var(--accent)">Conseils</a>.</p>

    <h2 class="section">Candidatures</h2>
    ${cand.etat === "AUCUNE_CANDIDATURE_ENVOYEE" ? `<div class="carte"><div class="sous">${esc(cand.message)}</div><div class="sous">Dossiers suivis : ${cand.dossiers_suivis}</div></div>` :
      cand.erreur ? `<p class="rien">${esc(cand.erreur)}</p>` :
      `<div class="chiffres"><div class="chiffre"><b>${cand.envoyees}</b><span>envoyées</span></div><div class="chiffre"><b>${cand.avec_retour}</b><span>avec retour</span></div><div class="chiffre vert"><b>${cand.taux_de_reponse} %</b><span>réponse</span></div><div class="chiffre"><b>${cand.delai_median_jours ?? "—"}</b><span>délai médian (j)</span></div></div>`}`;

  $("#complet")?.addEventListener("click", async (e) => { e.preventDefault(); cache.delete("/api/statistiques"); cache.set("/api/statistiques", await lire("/api/statistiques?complet=1", { frais: true })); RENDUS.statistiques(); });
};

/* ------------------------------------------------------------- clavier */

document.addEventListener("keydown", (e) => {
  const champ = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
  if (e.key === "Escape") { if (!$("#raccourcis").hidden) { $("#raccourcis").hidden = true; return; } fermerPanneau(); if (champ) document.activeElement.blur(); return; }
  if (champ) return;
  if (e.key === "?") { afficherRaccourcis(); return; }
  const surOffres = location.pathname === "/offres";
  if (!surOffres) return;
  if (e.key === "/") { e.preventDefault(); $("#recherche")?.focus(); return; }
  if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); deplacerCurseur(1); return; }
  if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); deplacerCurseur(-1); return; }
  if (e.key === "Enter") { const o = offreCourante(); if (o) ouvrirPanneau(o.stable_item_key); return; }
  const t = TRIAGE.find((x) => x.touche === e.key);
  if (t) { const o = offreCourante(); if (!o) return; e.preventDefault(); trierOffre(o, t.statut, t.libelle).then(() => deplacerCurseur(1)); }
});
$("#voile").addEventListener("click", fermerPanneau);
$("#raccourcis").addEventListener("click", () => { $("#raccourcis").hidden = true; });

/* ------------------------------------------------------------ demarrage */

naviguer(location.pathname, false);
