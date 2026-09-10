/*
   JOBHUNTER — ECRAN DU JOUR

   Lancement du pipeline et suivi en direct.

   L'original affiche « PID 1432 en cours » et le journal brut. Ici les
   etapes nommees defilent : progress_monitor sait deja les lire dans le
   manifeste, il suffisait de les demander.

   Le sondage ne tourne QUE pendant un run. Interroger le serveur toutes les
   trois secondes en permanence relirait le pool a chaque fois — cher, et
   pour rien.
*/

const $ = (sel) => document.querySelector(sel);

let sondage = null;

function notifier(message, type = "ok") {
  const n = $("#notification");
  n.textContent = message;
  n.className = `notification ${type}`;
  n.hidden = false;
  setTimeout(() => { n.hidden = true; }, 3200);
}

function echapper(texte) {
  const d = document.createElement("div");
  d.textContent = texte == null ? "" : String(texte);
  return d.innerHTML;
}

function peindre(etat) {
  const resume = $("#run-resume");
  if (!resume) return;

  resume.querySelector(".run-statut").textContent = etat.statut || "—";
  resume.querySelector(".run-statut").className =
    "run-statut " + String(etat.statut || "").toLowerCase();

  const metas = resume.querySelectorAll(".run-meta");
  if (metas[0]) metas[0].textContent = etat.run_id || "";
  if (metas[1]) metas[1].textContent = etat.duree || "";
  if (metas[2]) metas[2].textContent = `${etat.terminees}/${etat.total_etapes} étapes`;

  $("#etapes").innerHTML = (etat.etapes || []).map((e) => `
    <div class="etape ${String(e["État"] || "").includes("cours") ? "active" : ""}">
      <span class="puce">${echapper(String(e["État"] || "").slice(0, 1))}</span>
      <span class="nom">${echapper(e["Étape"])}</span>
      <span class="etat">${echapper(e["État"])}</span>
    </div>`).join("");

  // L'activite fine — quelle source, quelle offre — n'existe que pendant
  // l'etape en cours. La montrer quand elle est vide n'apprendrait rien.
  const activite = etat.activite || {};
  const details = Object.entries(activite)
    .filter(([, v]) => v !== null && v !== "" && v !== undefined)
    .map(([k, v]) => `${k} : ${v}`)
    .join(" · ");
  if (details) {
    const zone = $("#etapes");
    zone.insertAdjacentHTML("beforeend",
      `<div class="activite-fine">${echapper(details)}</div>`);
  }

  const journal = $("#journal");
  if (etat.en_cours && (etat.journal || []).length) {
    journal.textContent = etat.journal.join("\n");
    journal.hidden = false;
    journal.scrollTop = journal.scrollHeight;
  } else {
    journal.hidden = !etat.en_cours;
  }

  const bouton = $("#lancer-run");
  if (bouton) {
    bouton.disabled = etat.en_cours;
    bouton.textContent = etat.en_cours
      ? `Run en cours — ${etat.etape_courante || "…"}`
      : "Lancer un run complet";
  }
}

async function rafraichir() {
  try {
    const reponse = await fetch("/api/run");
    const etat = await reponse.json();
    peindre(etat);
    if (!etat.en_cours && sondage) {
      clearInterval(sondage);
      sondage = null;
      notifier("Run terminé. Rechargez pour voir les nouvelles offres.");
    }
  } catch (erreur) {
    // Un sondage qui echoue ne doit pas s'arreter : le serveur peut etre
    // momentanement occupe par le run lui-meme.
  }
}

function demarrerSondage() {
  if (sondage) return;
  sondage = setInterval(rafraichir, 3000);
  rafraichir();
}

const bouton = $("#lancer-run");
if (bouton) {
  bouton.addEventListener("click", async () => {
    bouton.disabled = true;
    try {
      const reponse = await fetch("/api/run/lancer", { method: "POST" });
      const data = await reponse.json();
      if (!reponse.ok) throw new Error(data.erreur || "Échec du lancement");
      notifier("Run lancé. Le suivi s'affiche ci-dessous.");
      demarrerSondage();
    } catch (erreur) {
      notifier(erreur.message, "erreur");
      bouton.disabled = false;
    }
  });
}

// Si un run tourne deja au chargement de la page, on reprend le suivi.
fetch("/api/run").then((r) => r.json()).then((etat) => {
  if (etat.en_cours) demarrerSondage();
}).catch(() => {});
