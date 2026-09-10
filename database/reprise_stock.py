"""
JOB HUNTER BELGIUM
REPRISE DU STOCK ACTIF - VERSION 1.0

Le probleme
-----------
Le pipeline ne juge que la recolte du jour. `collect_all_jobs()` rend ce que
les connecteurs viennent de rapporter, et c'est cette liste-la, et elle
seule, qui traverse la pre-selection, l'enrichissement, le gate et la file.

La base, elle, accumule. Mesure du 9 septembre 2026 :

    offres actives                              6 960
    revues au dernier run                       1 570   (23 %)
    jamais reexaminees depuis leur collecte     5 390

Une offre collectee le 6 septembre, toujours ouverte le 9, n'a donc ete
jugee qu'une seule fois — avec le texte qu'elle avait ce jour-la, parfois
avant meme que l'etape d'enrichissement existe. Son texte s'est enrichi
depuis, le matcheur s'est corrige depuis, le moteur de verdict est ne
depuis : rien de tout cela ne lui a jamais ete applique.

Consequence mesuree : 1 043 groupes canoniques actifs, pertinents et sans
aucune barriere prouvee etaient absents de la file — dont un « Technicien de
Laboratoire » chez GSK et un « Analyst Quality Assurance » chez Johnson &
Johnson, notes 100 et 99 par le matcheur du projet lui-meme.

Ce que fait ce module
---------------------
Il relit les offres actives de la base et les rend sous la forme d'objets
JobOffer identiques a ceux que produisent les connecteurs, pour qu'elles
rejoignent le circuit de notation au meme titre que la recolte du jour.

Il ne collecte rien et ne touche pas au reseau : tout est deja en base.
La deduplication canonique, en aval, fusionne naturellement une offre reprise
avec sa version fraiche quand les deux sont presentes.

Ce qu'il ne fait pas
--------------------
Il ne rejuge pas les offres inactives. Une offre fermee est fermee ; la
reprendre reviendrait a proposer des postes qui n'existent plus.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from database.models import JobOffer


REPRISE_STOCK_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"

# Colonnes recopiees telles quelles sur l'objet. Elles portent le meme nom
# que l'attribut correspondant : c'est main.py qui les y a ecrites.
_COLONNES_DIRECTES = (
    "collection_channel", "origin_source", "source",
    "title", "company", "location", "description", "url",
    "date_published", "contract_type", "language", "salary",
    "date_collected", "first_seen", "last_seen",
    "detail_enrichment_attempted", "detail_enrichment_success",
    "detail_matching_text", "detail_matching_text_length",
    "detail_from_cache", "detail_enrichment_error",
    "degree_requirement", "experience_requirement",
    "application_deadline", "restriction_text",
    "source_eligibility_status", "source_eligibility_reason",
)

# Colonnes dont le nom en base differe du nom d'attribut attendu.
_RENOMMAGES = {"source_external_id": "external_id"}


def _ouvrir(chemin: Path) -> sqlite3.Connection:
    """Lecture seule : une reprise de stock ne modifie jamais la base."""
    connexion = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro",
                                uri=True)
    connexion.row_factory = sqlite3.Row
    return connexion


def _vers_offre(ligne: sqlite3.Row) -> JobOffer:
    offre = JobOffer(
        source=ligne["source"] or "",
        external_id=ligne["source_external_id"] or "",
        title=ligne["title"] or "",
        company=ligne["company"] or "",
        location=ligne["location"] or "",
        description=ligne["description"] or "",
        url=ligne["url"] or "",
    )
    for colonne in _COLONNES_DIRECTES:
        setattr(offre, colonne, ligne[colonne])
    for colonne, attribut in _RENOMMAGES.items():
        setattr(offre, attribut, ligne[colonne])

    # Marque de provenance : une offre reprise du stock doit pouvoir se
    # distinguer d'une offre fraiche partout en aval, ne serait-ce que pour
    # comprendre un compteur qui bouge.
    offre.reprise_du_stock = True
    return offre


def charger_stock_actif(cles_deja_presentes: set[tuple[str, str]] | None = None,
                        chemin_base: Path | None = None) -> list[JobOffer]:
    """
    Offres actives de la base absentes de la recolte en cours.

    `cles_deja_presentes` contient les couples (canal de collecte, identifiant
    externe) deja rapportes par les connecteurs. Ils sont ecartes ici plutot
    que laisses a la deduplication canonique : inutile de noter deux fois la
    meme offre, et le representant choisi doit rester la version fraiche.
    """
    chemin = chemin_base or DB_PATH
    if not chemin.exists():
        return []

    deja = cles_deja_presentes or set()
    connexion = _ouvrir(chemin)
    try:
        lignes = connexion.execute(
            "SELECT * FROM raw_jobs WHERE is_active = 1"
        ).fetchall()
    finally:
        connexion.close()

    reprises = []
    for ligne in lignes:
        canal = str(ligne["collection_channel"] or ligne["source"] or "").upper()
        identifiant = str(ligne["source_external_id"] or "")
        if (canal, identifiant) in deja:
            continue
        reprises.append(_vers_offre(ligne))
    return reprises


def cles_de_collecte(offres) -> set[tuple[str, str]]:
    """Couples (canal, identifiant externe) d'une liste d'offres collectees."""
    cles = set()
    for offre in offres or []:
        canal = str(getattr(offre, "collection_channel", None)
                    or getattr(offre, "source", "") or "").upper()
        identifiant = str(getattr(offre, "external_id", "") or "")
        cles.add((canal, identifiant))
    return cles
