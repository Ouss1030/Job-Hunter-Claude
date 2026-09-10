/*
   JOBHUNTER — INTERACTIONS DE L'ECRAN DES OFFRES

   Le pool tient dans quelques centaines de lignes : filtrer et trier cote
   navigateur repond instantanement, sans aller-retour serveur. Au-dela de
   quelques milliers de lignes il faudrait repasser cote serveur — ce n'est
   pas le cas ici et ca ne le sera pas : le pool est par nature une courte
   liste de finalistes.

   Le triage, lui, ecrit en base. Chaque action part en arriere-plan et la
   ligne se met a jour seule : trier cent offres ne doit pas couter cent
   rechargements de page.
*/

const OFFRES = window.OFFRES || [];
const TRIAGE = window.TRIAGE || [];

const etat = {
  recherche: "",
  filtres: { verdict: new Set(), recommended_action_v12: new Set(), source: new Set() },
  tri: { champ: "pool_rank_v12", sens: "asc" },
  curseur: 0,        // ligne active pour le clavier
  visibles: [],      // lignes actuellement affichees, dans l'ordre affiche
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

const LIBELLE_STATUT = {
  DISCOVERED: "À revoir",
  SHORTLISTED: "Intéressé",
  READY: "Prête",
  DOCUMENTS_READY: "Dossier prêt",
  APPLIED: "Postulé",
  INTERVIEW: "Entretien",
  OFFER: "Offre",
  REJECTED: "Refus",
  WITHDRAWN: "Écartée",
  CLOSED: "Close",
};

const classe = (valeur) => String(valeur || "inconnu").toLowerCase();

function echapper(texte) {
  const d = document.createElement("div");
  d.textContent = texte == null ? "" : String(texte);
  return d.innerHTML;
}

/* ------------------------------------------------------- notifications */

let minuteurNotif = null;
function notifier(message, type = "ok") {
  const n = $("#notification");
  n.textContent = message;
  n.className = `notification ${type}`;
  n.hidden = false;
  clearTimeout(minuteurNotif);
  minuteurNotif = setTimeout(() => { n.hidden = true; }, 2600);
}

async function envoyer(route, charge) {
  const reponse = await fetch(route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(charge),
  });
  const data = await reponse.json();
  if (!reponse.ok) throw new Error(data.erreur || "Erreur inconnue");
  return data;
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

function celluleSuivi(o) {
  const statut = o.application_status;
  const relance = o.suivi && o.suivi.next_action_date;
  let html = statut
    ? `<span class="statut ${classe(statut)}">${echapper(LIBELLE_STATUT[statut] || statut)}</span>`
    : `<span class="statut vide">—</span>`;
  if (relance) {
    const due = relance <= new Date().toISOString().slice(0, 10);
    html += `<span class="relance ${due ? "due" : ""}" title="Relance prévue">${echapper(relance.slice(5))}</span>`;
  }
  return html;
}

function rendre() {
  const lignes = trier(filtrer());
  etat.visibles = lignes;
  if (etat.curseur >= lignes.length) etat.curseur = Math.max(0, lignes.length - 1);

  $("#corps").innerHTML = lignes.map((o, i) => `
    <tr data-cle="${echapper(o.stable_item_key)}" data-index="${i}">
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
      <td class="suivi">${celluleSuivi(o)}</td>
      <td class="score">${o.final_score_v12 ?? "—"}</td>
    </tr>`).join("");

  $("#corps").querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      etat.curseur = Number(tr.dataset.index);
      ouvrirPanneau(tr.dataset.cle);
    });
  });

  $("#compte-affiche").textContent = lignes.length;
  $("#vide").hidden = lignes.length > 0;
  dessinerStats(lignes);
  marquerCurseur();

  const actif = etat.recherche || Object.values(etat.filtres).some((j) => j.size);
  $("#raz").hidden = !actif;
}

function marquerCurseur() {
  document.querySelectorAll("#corps tr").forEach((tr, i) => {
    tr.classList.toggle("curseur", i === etat.curseur);
  });
}

function deplacerCurseur(pas) {
  if (!etat.visibles.length) return;
  etat.curseur = Math.min(etat.visibles.length - 1, Math.max(0, etat.curseur + pas));
  marquerCurseur();
  const tr = document.querySelector(`#corps tr[data-index="${etat.curseur}"]`);
  if (tr) tr.scrollIntoView({ block: "nearest" });
}

/* ------------------------------------------------------------- triage */

async function trierOffre(offre, statut, libelle) {
  try {
    await envoyer("/api/statut", { cle: offre.stable_item_key, statut });
    offre.application_status = statut;
    notifier(`${libelle} — ${offre.title.slice(0, 44)}`);
    rendre();
  } catch (erreur) {
    notifier(erreur.message, "erreur");
  }
}

function offreCourante() {
  return etat.visibles[etat.curseur] || null;
}

/* ------------------------------------------------------------ panneau */

/*
   L'analyse d'ecart.

   L'original rend « exigences / correspondances / ecarts » par offre, sans
   montrer sur quoi il se fonde. Le notre cite la PHRASE de l'annonce qui
   porte chaque obstacle : un obstacle qu'on peut relire est un obstacle
   qu'on peut contester — et le moteur s'est deja trompe cinq fois en une
   seule journee, ce qui rend la preuve indispensable.
*/
function blocEcart(o) {
  const e = o.ecart || {};
  const barrieres = e.barrieres || [];
  const alertes = e.alertes || [];
  const atouts = e.atouts || [];
  const manques = e.manques || [];

  if (!barrieres.length && !alertes.length && !atouts.length
      && !manques.length && !e.formation) return "";

  const constat = (c, genre) => `
    <div class="constat ${genre}">
      <div class="constat-message">${echapper(c.message)}</div>
      ${c.preuve ? `<div class="constat-preuve">\u00ab ${echapper(c.preuve)} \u00bb</div>` : ""}
    </div>`;

  return `
    <div class="bloc">
      <h3>Ce que dit l'annonce</h3>

      ${e.formation ? `<div class="formation">L'employeur propose une formation —
         les exigences de diplôme et d'expérience tombent.</div>` : ""}

      ${barrieres.map((c) => constat(c, "barriere")).join("")}
      ${alertes.map((c) => constat(c, "alerte")).join("")}

      ${atouts.length ? `
        <div class="etiquettes">
          <span class="titre-etiquettes">Ce qui vous sert</span>
          ${atouts.map((a) => `<span class="etiquette atout">${echapper(a)}</span>`).join("")}
        </div>` : ""}

      ${manques.length ? `
        <div class="etiquettes">
          <span class="titre-etiquettes">Ce qui vous manque</span>
          ${manques.map((m) => `<span class="etiquette manque">${echapper(m)}</span>`).join("")}
        </div>` : ""}
    </div>`;
}


function blocSuivi(o) {
  const s = o.suivi || {};
  const dejaPostule = o.application_status === "APPLIED";
  return `
    <div class="bloc">
      <h3>Suivi de candidature</h3>
      <div class="triage">
        ${TRIAGE.map((t) => `
          <button class="bouton-triage ${o.application_status === t.statut ? "actif" : ""}"
                  data-statut="${t.statut}">
            ${echapper(t.libelle)}<kbd>${echapper(t.touche)}</kbd>
          </button>`).join("")}
      </div>

      <div class="formulaire-suivi">
        <label>Relance prévue
          <input type="date" id="f-relance" value="${echapper(s.next_action_date || "")}">
        </label>
        <div class="raccourcis-date">
          <button data-jours="3">+3 j</button>
          <button data-jours="7">+1 sem.</button>
          <button data-jours="30">+1 mois</button>
          <button data-jours="0">effacer</button>
        </div>
        <label>Contact
          <input type="text" id="f-contact" placeholder="Nom du recruteur"
                 value="${echapper(s.contact_name || "")}">
        </label>
        <label>Canal
          <input type="text" id="f-canal" placeholder="Courriel, téléphone, LinkedIn…"
                 value="${echapper(s.contact_channel || "")}">
        </label>
        <button class="enregistrer" id="f-enregistrer">Enregistrer le suivi</button>
      </div>

      <div class="zone-postule ${dejaPostule ? "faite" : ""}">
        ${dejaPostule
          ? `<span class="deja">✓ Candidature marquée comme envoyée.</span>`
          : `<label class="confirmation">
               <input type="checkbox" id="f-confirme">
               Je confirme avoir envoyé cette candidature
             </label>
             <button class="postule" id="f-postule" disabled>Marquer comme postulée</button>`}
      </div>
    </div>`;
}

function ouvrirPanneau(cle) {
  const o = OFFRES.find((x) => x.stable_item_key === cle);
  if (!o) return;

  document.querySelectorAll("#corps tr").forEach((tr) =>
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

    ${blocEcart(o)}

    ${blocSuivi(o)}

    <div class="bloc">
      <h3>Fiche</h3>
      <dl class="faits">
        <dt>Score</dt><dd>${o.final_score_v12 ?? "—"}</dd>
        <dt>Rang</dt><dd>${o.pool_rank_v12 ?? "—"}</dd>
        <dt>Source</dt><dd>${echapper(o.source)}</dd>
        <dt>Filtre qualité</dt><dd>${echapper(o.guard_level || "—")}</dd>
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
  brancherPanneau(o);
}

function brancherPanneau(o) {
  const p = $("#panneau");
  p.querySelector(".fermer").addEventListener("click", fermerPanneau);

  p.querySelectorAll(".bouton-triage").forEach((b) => {
    b.addEventListener("click", async () => {
      const t = TRIAGE.find((x) => x.statut === b.dataset.statut);
      await trierOffre(o, b.dataset.statut, t ? t.libelle : b.dataset.statut);
      ouvrirPanneau(o.stable_item_key);
    });
  });

  p.querySelectorAll(".raccourcis-date button").forEach((b) => {
    b.addEventListener("click", () => {
      const jours = Number(b.dataset.jours);
      if (!jours) { p.querySelector("#f-relance").value = ""; return; }
      const d = new Date();
      d.setDate(d.getDate() + jours);
      p.querySelector("#f-relance").value = d.toISOString().slice(0, 10);
    });
  });

  p.querySelector("#f-enregistrer").addEventListener("click", async () => {
    try {
      const data = await envoyer("/api/suivi", {
        cle: o.stable_item_key,
        next_action_date: p.querySelector("#f-relance").value,
        contact_name: p.querySelector("#f-contact").value,
        contact_channel: p.querySelector("#f-canal").value,
      });
      o.suivi = data.suivi;
      notifier("Suivi enregistré.");
      rendre();
    } catch (erreur) {
      notifier(erreur.message, "erreur");
    }
  });

  // La case a cocher commande le bouton : c'est la regle du projet — la
  // machine ne declare jamais une candidature envoyee — rendue impossible
  // a contourner par distraction.
  const confirme = p.querySelector("#f-confirme");
  const postule = p.querySelector("#f-postule");
  if (confirme && postule) {
    confirme.addEventListener("change", () => { postule.disabled = !confirme.checked; });
    postule.addEventListener("click", async () => {
      try {
        await envoyer("/api/postule", { cle: o.stable_item_key, confirme: true });
        o.application_status = "APPLIED";
        notifier("Candidature enregistrée comme envoyée.");
        rendre();
        ouvrirPanneau(o.stable_item_key);
      } catch (erreur) {
        notifier(erreur.message, "erreur");
      }
    });
  }
}

function fermerPanneau() {
  $("#panneau").hidden = true;
  $("#voile").hidden = true;
  document.querySelectorAll("#corps tr.selectionnee")
    .forEach((tr) => tr.classList.remove("selectionnee"));
}

/* ---------------------------------------------------------- raccourcis */

function afficherRaccourcis() {
  const zone = $("#raccourcis");
  zone.innerHTML = `
    <div class="carte-raccourcis">
      <h3>Raccourcis</h3>
      <dl>
        <dt>j / k</dt><dd>descendre / monter</dd>
        <dt>↵</dt><dd>ouvrir le détail</dd>
        ${TRIAGE.map((t) => `<dt>${echapper(t.touche)}</dt><dd>${echapper(t.libelle)}</dd>`).join("")}
        <dt>/</dt><dd>rechercher</dd>
        <dt>Échap</dt><dd>fermer</dd>
      </dl>
      <p>Le triage s'applique à la ligne active, sans ouvrir le détail.</p>
    </div>`;
  zone.hidden = false;
}

/* ------------------------------------------------------------ liaisons */

$("#recherche").addEventListener("input", (e) => {
  etat.recherche = e.target.value;
  etat.curseur = 0;
  rendre();
});

$("#raz").addEventListener("click", () => {
  etat.recherche = "";
  $("#recherche").value = "";
  Object.values(etat.filtres).forEach((j) => j.clear());
  document.querySelectorAll(".jeton").forEach((b) => b.setAttribute("aria-pressed", "false"));
  rendre();
});

$("#aide-clavier").addEventListener("click", afficherRaccourcis);
$("#raccourcis").addEventListener("click", () => { $("#raccourcis").hidden = true; });

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
  const dansUnChamp = ["INPUT", "TEXTAREA", "SELECT"].includes(
    document.activeElement.tagName);

  if (e.key === "Escape") {
    if (!$("#raccourcis").hidden) { $("#raccourcis").hidden = true; return; }
    fermerPanneau();
    if (dansUnChamp) document.activeElement.blur();
    return;
  }
  if (dansUnChamp) return;

  if (e.key === "/") { e.preventDefault(); $("#recherche").focus(); return; }
  if (e.key === "?") { afficherRaccourcis(); return; }
  if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); deplacerCurseur(1); return; }
  if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); deplacerCurseur(-1); return; }
  if (e.key === "Enter") {
    const o = offreCourante();
    if (o) ouvrirPanneau(o.stable_item_key);
    return;
  }

  const action = TRIAGE.find((t) => t.touche === e.key);
  if (action) {
    const o = offreCourante();
    if (!o) return;
    e.preventDefault();
    trierOffre(o, action.statut, action.libelle).then(() => deplacerCurseur(1));
  }
});

construireFiltres();
document.querySelector('thead th[data-tri="pool_rank_v12"]').setAttribute("data-sens", "asc");
rendre();
