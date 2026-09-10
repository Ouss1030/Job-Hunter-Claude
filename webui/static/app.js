/*
   JOBHUNTER — INTERACTIONS DE L'ECRAN DES OFFRES

   Le pool tient dans quelques centaines de lignes : filtrer et trier cote
   navigateur repond instantanement, sans aller-retour serveur. Au-dela de
   quelques milliers de lignes il faudrait repasser cote serveur — ce n'est
   pas le cas ici et ca ne le sera pas : le pool est par nature une courte
   liste de finalistes.
*/

const OFFRES = window.OFFRES || [];

const etat = {
  recherche: "",
  filtres: { verdict: new Set(), recommended_action_v12: new Set(), source: new Set() },
  tri: { champ: "pool_rank_v12", sens: "asc" },
};

const $ = (sel) => document.querySelector(sel);

const LIBELLE_ACTION = {
  APPLY_NOW: "Postuler",
  APPLY_NEXT: "Ensuite",
  REVIEW_FIRST: "À relire",
  DO_NOT_APPLY: "Écartée",
};

const LIBELLE_VERDICT = {
  ACCESSIBLE: "Accessible",
  A_VERIFIER: "À vérifier",
  FERMEE: "Fermée",
  INCONNU: "Inconnu",
};

const classe = (valeur) => String(valeur || "inconnu").toLowerCase();

function echapper(texte) {
  const d = document.createElement("div");
  d.textContent = texte == null ? "" : String(texte);
  return d.innerHTML;
}

/* ------------------------------------------------------------- entete */

function dessinerStats(lignes) {
  const parVerdict = (v) => lignes.filter((o) => o.verdict === v).length;
  const aPostuler = lignes.filter(
    (o) => String(o.recommended_action_v12 || "").startsWith("APPLY")
  ).length;

  $("#stats-entete").innerHTML = `
    <div class="carte-stat"><div class="valeur">${aPostuler}</div><div class="legende">à postuler</div></div>
    <div class="carte-stat vert"><div class="valeur">${parVerdict("ACCESSIBLE")}</div><div class="legende">accessibles</div></div>
    <div class="carte-stat ambre"><div class="valeur">${parVerdict("A_VERIFIER")}</div><div class="legende">à vérifier</div></div>
    <div class="carte-stat rouge"><div class="valeur">${parVerdict("FERMEE")}</div><div class="legende">fermées</div></div>`;
}

/* ------------------------------------------------------------ filtres */

function construireFiltres() {
  const groupes = [
    { champ: "verdict", titre: "Verdict", libelles: LIBELLE_VERDICT,
      ordre: ["ACCESSIBLE", "A_VERIFIER", "FERMEE", "INCONNU"] },
    { champ: "recommended_action_v12", titre: "Action", libelles: LIBELLE_ACTION,
      ordre: ["APPLY_NOW", "APPLY_NEXT", "REVIEW_FIRST", "DO_NOT_APPLY"] },
  ];

  const html = groupes.map((g) => {
    const compte = {};
    OFFRES.forEach((o) => {
      const v = o[g.champ];
      if (v) compte[v] = (compte[v] || 0) + 1;
    });
    const valeurs = g.ordre.filter((v) => compte[v]);
    if (!valeurs.length) return "";
    const boutons = valeurs.map((v) =>
      `<button class="jeton" data-champ="${g.champ}" data-valeur="${v}" aria-pressed="false">
         ${echapper(g.libelles[v] || v)}<span class="n">${compte[v]}</span>
       </button>`).join("");
    return `<div class="groupe"><span class="titre-groupe">${g.titre}</span>${boutons}</div>`;
  }).join("");

  $("#groupes-filtres").innerHTML = html;
  $("#groupes-filtres").querySelectorAll(".jeton").forEach((b) => {
    b.addEventListener("click", () => {
      const { champ, valeur } = b.dataset;
      const jeu = etat.filtres[champ];
      if (jeu.has(valeur)) { jeu.delete(valeur); b.setAttribute("aria-pressed", "false"); }
      else { jeu.add(valeur); b.setAttribute("aria-pressed", "true"); }
      rendre();
    });
  });
}

function filtrer() {
  const q = etat.recherche.trim().toLowerCase();
  return OFFRES.filter((o) => {
    for (const [champ, jeu] of Object.entries(etat.filtres)) {
      if (jeu.size && !jeu.has(o[champ])) return false;
    }
    if (!q) return true;
    return [o.title, o.company, o.ville, o.source]
      .some((v) => String(v || "").toLowerCase().includes(q));
  });
}

function trier(lignes) {
  const { champ, sens } = etat.tri;
  const signe = sens === "asc" ? 1 : -1;
  return [...lignes].sort((a, b) => {
    const x = a[champ], y = b[champ];
    if (typeof x === "number" && typeof y === "number") return (x - y) * signe;
    return String(x ?? "").localeCompare(String(y ?? ""), "fr") * signe;
  });
}

/* ------------------------------------------------------------ tableau */

function rendre() {
  const lignes = trier(filtrer());
  const corps = $("#corps");

  corps.innerHTML = lignes.map((o) => `
    <tr data-cle="${echapper(o.stable_item_key)}">
      <td class="rang">${o.pool_rank_v12 ?? "—"}</td>
      <td class="intitule">
        ${o.preferred_location ? '<span class="epingle" title="Zone préférée">●</span>' : ""}
        ${echapper(o.title)}
        <span class="source">${echapper(o.source)}</span>
      </td>
      <td class="entreprise">${echapper(o.company)}</td>
      <td class="lieu">${echapper(o.ville)}</td>
      <td><span class="badge ${classe(o.verdict)}">${echapper(LIBELLE_VERDICT[o.verdict] || o.verdict || "—")}</span></td>
      <td><span class="action ${classe(o.recommended_action_v12)}">${echapper(LIBELLE_ACTION[o.recommended_action_v12] || o.recommended_action_v12 || "—")}</span></td>
      <td class="score">${o.final_score_v12 ?? "—"}</td>
    </tr>`).join("");

  corps.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => ouvrirPanneau(tr.dataset.cle));
  });

  $("#compte-affiche").textContent = lignes.length;
  $("#vide").hidden = lignes.length > 0;
  dessinerStats(lignes);

  const actif = etat.recherche || Object.values(etat.filtres).some((j) => j.size);
  $("#raz").hidden = !actif;
}

/* ------------------------------------------------------------ panneau */

function ouvrirPanneau(cle) {
  const o = OFFRES.find((x) => x.stable_item_key === cle);
  if (!o) return;

  document.querySelectorAll("tbody tr").forEach((tr) =>
    tr.classList.toggle("selectionnee", tr.dataset.cle === cle));

  const raisons = Array.isArray(o.reasons) ? o.reasons : [];

  $("#panneau").innerHTML = `
    <button class="fermer" aria-label="Fermer">×</button>
    <h2>${echapper(o.title)}</h2>
    <div class="employeur">${echapper(o.company)} — ${echapper(o.ville)}</div>

    <div class="rangee-badges">
      <span class="badge ${classe(o.verdict)}">${echapper(LIBELLE_VERDICT[o.verdict] || o.verdict)}</span>
      <span class="badge inconnu">${echapper(LIBELLE_ACTION[o.recommended_action_v12] || "—")}</span>
      <span class="badge inconnu">Priorité ${echapper(o.priority_v12 || "—")}</span>
      <span class="badge inconnu">${echapper(o.cv_track || o.track || "—")}</span>
    </div>

    ${o.verdict_obstacle ? `<div class="bloc"><h3>Obstacle identifié</h3>
        <div class="obstacle">${echapper(o.verdict_obstacle)}</div></div>` : ""}

    ${o.verdict_formation ? `<div class="bloc">
        <div class="formation">L'employeur propose une formation — les exigences
        de diplôme et d'expérience tombent.</div></div>` : ""}

    <div class="bloc">
      <h3>Fiche</h3>
      <dl class="faits">
        <dt>Score</dt><dd>${o.final_score_v12 ?? "—"}</dd>
        <dt>Rang</dt><dd>${o.pool_rank_v12 ?? "—"}</dd>
        <dt>Source</dt><dd>${echapper(o.source)}</dd>
        <dt>Filtre qualité</dt><dd>${echapper(o.guard_level || "—")}</dd>
        <dt>Suivi</dt><dd>${echapper(o.application_status || "non suivie")}</dd>
        <dt>Zone préférée</dt><dd>${o.preferred_location ? "oui" : "non"}</dd>
      </dl>
    </div>

    ${raisons.length ? `<div class="bloc"><h3>Décisions du pipeline</h3>
        <ul class="raisons">${raisons.map((r) => `<li>${echapper(r)}</li>`).join("")}</ul></div>` : ""}

    ${o.extrait ? `<div class="bloc"><h3>Extrait de l'annonce</h3>
        <div class="extrait">${echapper(o.extrait)}</div></div>` : ""}

    ${o.url ? `<a class="lien-offre" href="${echapper(o.url)}" target="_blank" rel="noopener">
        Ouvrir l'offre ↗</a>` : ""}`;

  $("#panneau").hidden = false;
  $("#voile").hidden = false;
  $("#panneau").scrollTop = 0;
  $("#panneau").querySelector(".fermer").addEventListener("click", fermerPanneau);
}

function fermerPanneau() {
  $("#panneau").hidden = true;
  $("#voile").hidden = true;
  document.querySelectorAll("tbody tr.selectionnee")
    .forEach((tr) => tr.classList.remove("selectionnee"));
}

/* ------------------------------------------------------------ liaisons */

$("#recherche").addEventListener("input", (e) => {
  etat.recherche = e.target.value;
  rendre();
});

$("#raz").addEventListener("click", () => {
  etat.recherche = "";
  $("#recherche").value = "";
  Object.values(etat.filtres).forEach((j) => j.clear());
  document.querySelectorAll(".jeton").forEach((b) => b.setAttribute("aria-pressed", "false"));
  rendre();
});

document.querySelectorAll("thead th[data-tri]").forEach((th) => {
  th.addEventListener("click", () => {
    const champ = th.dataset.tri;
    etat.tri = {
      champ,
      sens: etat.tri.champ === champ && etat.tri.sens === "asc" ? "desc" : "asc",
    };
    document.querySelectorAll("thead th").forEach((h) => h.removeAttribute("data-sens"));
    th.setAttribute("data-sens", etat.tri.sens);
    rendre();
  });
});

$("#voile").addEventListener("click", fermerPanneau);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") fermerPanneau();
  if (e.key === "/" && document.activeElement !== $("#recherche")) {
    e.preventDefault();
    $("#recherche").focus();
  }
});

construireFiltres();
document.querySelector('thead th[data-tri="pool_rank_v12"]').setAttribute("data-sens", "asc");
rendre();
