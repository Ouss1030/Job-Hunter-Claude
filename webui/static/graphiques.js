/*
   JOBHUNTER — GRAPHIQUES SVG

   Trois formes suffisent : des barres pour classer, une courbe pour suivre
   dans le temps, une grille pour croiser deux dimensions (jour × heure).
   Dessinees a la main en SVG : aucune bibliotheque a charger, aucune
   dependance a installer, et un rendu qui suit exactement la feuille de
   style — meme palette, memes polices, memes animations.

   Chaque fonction rend une chaine SVG. Les valeurs sont echappees ; les
   nombres sont formates a l'affichage, jamais dans les donnees.
*/

const G = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const fmt = (n) => (Math.abs(n) >= 1000 ? Math.round(n).toLocaleString("fr-BE") : String(n));

  /* Barres horizontales : [{nom, valeur, part?}] → classement lisible. */
  function barres(lignes, { largeur = 520, hauteurLigne = 26, max = null, unite = "" } = {}) {
    if (!lignes || !lignes.length) return `<p class="rien">Rien de significatif.</p>`;
    const m = max ?? Math.max(...lignes.map((l) => l.valeur));
    const gauche = 170, droite = 56, zone = largeur - gauche - droite;
    const h = lignes.length * hauteurLigne + 6;
    const corps = lignes.map((l, i) => {
      const y = i * hauteurLigne + 4;
      const w = m ? Math.max(2, (l.valeur / m) * zone) : 0;
      return `
        <text x="${gauche - 10}" y="${y + 15}" text-anchor="end">${esc(l.nom)}</text>
        <rect class="barre" x="${gauche}" y="${y + 6}" width="${w}" height="${hauteurLigne - 12}" rx="3"
              style="animation-delay:${i * 30}ms; transform-origin:${gauche}px 0"></rect>
        <text class="etiquette-valeur" x="${gauche + w + 8}" y="${y + 15}">${fmt(l.valeur)}${esc(unite)}</text>`;
    }).join("");
    return `<svg class="graphique" viewBox="0 0 ${largeur} ${h}" preserveAspectRatio="xMinYMin meet">${corps}</svg>`;
  }

  /* Courbe : [{x, y}] avec x = etiquette, y = nombre. */
  function courbe(points, { largeur = 720, hauteur = 180, aire = true } = {}) {
    if (!points || points.length < 2) return `<p class="rien">Pas assez de points.</p>`;
    const g = 36, d = 12, ht = 24, hb = 28;
    const w = largeur - g - d, h = hauteur - ht - hb;
    const max = Math.max(...points.map((p) => p.y), 1);
    const px = (i) => g + (i / (points.length - 1)) * w;
    const py = (v) => ht + h - (v / max) * h;
    const chemin = points.map((p, i) => `${i ? "L" : "M"}${px(i).toFixed(1)},${py(p.y).toFixed(1)}`).join(" ");
    const zoneAire = `${chemin} L${px(points.length - 1).toFixed(1)},${(ht + h).toFixed(1)} L${g},${(ht + h).toFixed(1)} Z`;

    const pas = Math.max(1, Math.ceil(points.length / 8));
    const etiquettes = points.map((p, i) => (i % pas === 0 || i === points.length - 1)
      ? `<text x="${px(i).toFixed(1)}" y="${hauteur - 8}" text-anchor="middle">${esc(p.x)}</text>` : "").join("");
    const graduations = [0, 0.5, 1].map((t) => {
      const y = py(max * t).toFixed(1);
      return `<line class="axe" x1="${g}" x2="${largeur - d}" y1="${y}" y2="${y}"></line>
              <text x="${g - 8}" y="${+y + 4}" text-anchor="end">${fmt(Math.round(max * t))}</text>`;
    }).join("");
    const pts = points.map((p, i) =>
      `<circle class="point" cx="${px(i).toFixed(1)}" cy="${py(p.y).toFixed(1)}" r="3"><title>${esc(p.x)} : ${fmt(p.y)}</title></circle>`).join("");

    return `<svg class="graphique" viewBox="0 0 ${largeur} ${hauteur}" preserveAspectRatio="xMinYMin meet">
      ${graduations}
      ${aire ? `<path class="aire" d="${zoneAire}"></path>` : ""}
      <path class="courbe" d="${chemin}"></path>
      ${pts}${etiquettes}</svg>`;
  }

  /* Colonnes verticales : [{x, y}] — jours de la semaine, heures. */
  function colonnes(points, { largeur = 720, hauteur = 150, doux = false } = {}) {
    if (!points || !points.length) return `<p class="rien">Aucune donnée.</p>`;
    const g = 36, d = 12, ht = 16, hb = 26;
    const w = largeur - g - d, h = hauteur - ht - hb;
    const max = Math.max(...points.map((p) => p.y), 1);
    const lw = w / points.length, bw = Math.max(4, lw * 0.62);
    const corps = points.map((p, i) => {
      const bh = (p.y / max) * h, x = g + i * lw + (lw - bw) / 2, y = ht + h - bh;
      return `<rect class="barre ${doux ? "douce" : ""}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="2"
                    style="animation-delay:${i * 18}ms; transform-origin:0 ${(ht + h).toFixed(1)}px"><title>${esc(p.x)} : ${fmt(p.y)}</title></rect>
              <text x="${(x + bw / 2).toFixed(1)}" y="${hauteur - 8}" text-anchor="middle">${esc(p.x)}</text>`;
    }).join("");
    const base = `<line class="axe" x1="${g}" x2="${largeur - d}" y1="${ht + h}" y2="${ht + h}"></line>`;
    return `<svg class="graphique" viewBox="0 0 ${largeur} ${hauteur}" preserveAspectRatio="xMinYMin meet">${base}${corps}</svg>`;
  }

  /* Grille jour × heure : {jours:[...], heures:[...], valeur(j,h)}. */
  function grille(jours, heures, valeur, { largeur = 720 } = {}) {
    const g = 40, ht = 18, cw = (largeur - g - 8) / heures.length, ch = 18;
    let max = 1;
    jours.forEach((j) => heures.forEach((h) => { max = Math.max(max, valeur(j, h)); }));
    const cellules = jours.map((j, ji) => heures.map((h, hi) => {
      const v = valeur(j, h), o = v ? 0.12 + 0.88 * (v / max) : 0.04;
      return `<rect class="cellule" x="${(g + hi * cw).toFixed(1)}" y="${ht + ji * ch}" width="${(cw - 2).toFixed(1)}" height="${ch - 2}" rx="2"
                    fill="var(--accent)" opacity="${o.toFixed(2)}"><title>${esc(j)} ${esc(h)}h : ${v}</title></rect>`;
    }).join("")).join("");
    const etiqJ = jours.map((j, i) => `<text x="${g - 8}" y="${ht + i * ch + 13}" text-anchor="end">${esc(j)}</text>`).join("");
    const etiqH = heures.map((h, i) => (i % 3 === 0 ? `<text x="${(g + i * cw + cw / 2).toFixed(1)}" y="${ht + jours.length * ch + 14}" text-anchor="middle">${esc(h)}</text>` : "")).join("");
    return `<svg class="graphique" viewBox="0 0 ${largeur} ${ht + jours.length * ch + 22}" preserveAspectRatio="xMinYMin meet">${cellules}${etiqJ}${etiqH}</svg>`;
  }

  /* Ligne de conseil : nom + barre proportionnelle + part. */
  function conseil(x, genre, max) {
    const w = max ? Math.max(3, (x.part / max) * 100) : 0;
    return `<div class="conseil ${genre}">
      <span class="nom">${esc(x.nom)}</span>
      <span class="barre"><i style="width:${w.toFixed(0)}%"></i></span>
      <span class="part">${x.part.toFixed(1)} %</span>
      <span class="k">${x.offres}</span></div>`;
  }

  return { barres, courbe, colonnes, grille, conseil, esc, fmt };
})();
