"""
JOB HUNTER BELGIUM
CONSEILS DE MARCHE - VERSION 1.0

Que demandent les postes que vous pouvez viser, et que vous manque-t-il ?

Le perimetre
------------
TOUTES les offres scrapees, actives ou non, y compris celles que le verdict
ferme. C'est un choix deliberе : les offres fermees disent ce qu'il vous
faudrait pour les ouvrir. Un conseil qui ne regarde que l'accessible ne
conseille rien — il decrit.

Le decoupage vient de statistiques/categories.py : LAB, DATA, PHARMA, trois
sous-categories chacune. Chaque mesure est rendue par famille ET par
sous-categorie, parce que « ce qui est demande en labo » melange QC, R&D et
microbiologie, dont les attentes different.

Ce qui est mesure
-----------------
    outils         logiciels, instruments, langages
    normes         referentiels et reglementations
    methodes       techniques et savoir-faire
    qualites       ce que les annonces attendent comme posture
    langues        exigences et niveaux
    experience     annees demandees
    diplome        niveau cite
    contrats       types de contrat
    salaires       quand l'annonce en donne un
    employeurs     qui recrute le plus
    villes         ou
    evolution      offres nouvelles par semaine
    publication    jour et heure ou les offres paraissent
    duree_de_vie   combien de temps une offre reste en ligne

Et, pour chaque categorie, le croisement avec VOS competences declarees :
ce qui est demande et que vous avez (a mettre en avant), ce qui est demande
et que vous n'avez pas (a acquerir, classe par frequence).

Une precaution de lecture, encore
---------------------------------
Ces comptages mesurent des MENTIONS dans le texte, pas des exigences
formelles. « HPLC » cite en passant compte comme « HPLC » exige. Le
classement relatif est fiable ; les valeurs absolues surestiment. Ce projet
a deja confondu les deux une fois.

Les vocabulaires sont curates, pas decouverts : un comptage de n-grammes
libres remonterait « environnement de travail » et « esprit d'equipe » en
tete de tout, et noierait l'utile. Chaque terme est cherche entre
frontieres de mots — « R » ne doit pas matcher chaque lettre R, « SAS » ne
doit pas matcher « société par actions simplifiée ».
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

from config.candidate_truth import CANDIDATE_TRUTH
from statistiques.categories import FAMILLES, LIBELLES, categoriser, famille
from statistiques.marche import _ville


CONSEILS_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"

# En dessous, un comptage n'est qu'un accident.
SEUIL = 3


# ------------------------------------------------------------------
# Vocabulaires
# ------------------------------------------------------------------
# Chaque entree : nom affiche -> motif (sans frontieres, ajoutees ensuite).
# Les noms courts et ambigus (R, SAS, API, PCR) recoivent un motif qui
# exige un contexte, ou sont ecrits en majuscules dans un texte en
# minuscules — voir _chercher, qui compare sans casse mais avec frontieres.

OUTILS = {
    # Chromatographie et analyse
    "HPLC": r"hplc", "UPLC": r"uplc", "GC": r"gc|gc-ms|gcms|chromatographie gazeuse|gas chromatograph\w*",
    "LC-MS": r"lc-?ms|lcms|masse|mass spec\w*", "ICP": r"icp-?(?:ms|oes)?",
    "Spectrophotométrie UV": r"uv-?vis|spectrophotom\w*", "FTIR": r"ftir|infrarouge|infrared",
    "Karl Fischer": r"karl fischer|kf", "Titration": r"titrat\w*|titreu\w*",
    "Dissolution": r"dissolution", "Microscopie": r"microscop\w*",
    # Systemes
    "LIMS": r"lims|labware|labvantage|starlims", "SAP": r"sap(?: qm| mm| pm| erp)?",
    "Empower": r"empower", "Chromeleon": r"chromeleon", "TrackWise": r"trackwise",
    "Veeva": r"veeva", "Documentum": r"documentum", "MES": r"mes|manufacturing execution",
    "ERP": r"erp", "Jira": r"jira", "Confluence": r"confluence",
    # Bureautique et data
    "Excel": r"excel", "Power BI": r"power ?bi", "Tableau": r"tableau (?:software|desktop|server)|tableau(?=[^.]{0,30}(?:power ?bi|qlik|dashboard))",
    "Qlik": r"qlik\w*", "SQL": r"sql|t-sql|postgres\w*|mysql|sql server", "Python": r"python",
    # La lettre R ne compte qu'accompagnee d'un contexte de programmation :
    # « Python et R », « R Studio », « R/Python ». Seule, elle est partout.
    "R": r"r(?= ?(?:studio|shiny|markdown|programming|language|/ ?python|, ?python| et python| and python| ou python| or python))"
         r"|(?<=python et )r|(?<=python and )r|(?<=python ou )r|(?<=python or )r|(?<=python, )r|(?<=python/)r|(?<=python / )r|(?<=sas, )r|(?<=sas et )r",
    "SAS": r"sas(?= (?:programming|base|enterprise|viya|9))|(?<=logiciel )sas", "SPSS": r"spss",
    "Minitab": r"minitab", "JMP": r"jmp", "Matlab": r"matlab",
    "Azure": r"azure", "AWS": r"aws", "Databricks": r"databricks", "Snowflake": r"snowflake",
    "Spark": r"spark|pyspark", "Airflow": r"airflow", "dbt": r"dbt", "Git": r"git|github|gitlab",
    "Pandas": r"pandas", "scikit-learn": r"scikit|sklearn", "TensorFlow / PyTorch": r"tensorflow|pytorch|keras",
    "SSIS / SSRS": r"ssis|ssrs|ssas", "VBA": r"vba", "Access": r"ms access|microsoft access",
}

NORMES = {
    "GMP / BPF": r"gmp|bpf|bonnes pratiques de fabrication|good manufacturing",
    "GLP / BPL": r"glp|bpl|bonnes pratiques de laboratoire|good laboratory",
    "GDP": r"gdp|good distribution", "GxP": r"gxp",
    "HACCP": r"haccp", "ISO 9001": r"iso ?9001", "ISO 17025": r"iso ?17025",
    "ISO 13485": r"iso ?13485", "ISO 14001": r"iso ?14001", "ISO 22000": r"iso ?22000",
    "ISO 45001": r"iso ?45001", "FDA": r"fda", "EMA": r"ema", "ICH": r"ich",
    "21 CFR Part 11": r"21 ?cfr|part 11", "GAMP": r"gamp", "Data integrity / ALCOA": r"data integrity|alcoa",
    "BRC / IFS": r"brc|ifs", "Pharmacopée": r"pharmacop\w*|usp|ep\b", "REACH": r"reach",
    "Annexe 1": r"annex(?:e)? 1|annex(?:e)? i\b", "5S / Lean": r"5s|lean|kaizen|six sigma",
    "CAPA / déviations": r"capa|deviation\w*|non-?conformit\w*|oos|oot",
}

METHODES = {
    "Chromatographie": r"chromatograph\w*", "Spectrométrie": r"spectrom\w*|spectroscop\w*",
    "Microbiologie": r"microbiolog\w*", "Culture cellulaire": r"culture cellulaire|cell culture|celkweek",
    "PCR / biologie moléculaire": r"pcr|qpcr|biologie moleculaire|molecular biology",
    "ELISA / immunoessais": r"elisa|immunoessai\w*|immunoassay\w*",
    "Bioburden / endotoxines": r"bioburden|biocharge|endotox\w*|lal\b",
    "Stérilité": r"sterilit\w*|sterility", "Environnement contrôlé": r"salle blanche|clean ?room|zone a atmosphere|environmental monitoring",
    "Validation de méthodes": r"validation de methode\w*|method validation|method transfer",
    "Études de stabilité": r"stabilit\w*", "Analyse physico-chimique": r"physico-?chimi\w*",
    "Échantillonnage": r"echantillon\w*|sampling|monster\w*", "Métrologie / calibration": r"metrolog\w*|calibrat\w*|etalonn\w*",
    # Pas « documentation » ni « procedure » seuls : presents dans une annonce
    # sur trois, ils gonflaient ce poste a 30 % sans rien dire.
    "Documentation qualité": r"sop|sops|batch record|dossier de lot|procedures? qualite|"
                             r"quality documentation|documentation gmp|master batch",
    "Audits": r"audit\w*", "Investigations": r"investigation\w*|root cause|analyse de cause",
    "Reporting / tableaux de bord": r"reporting|dashboard\w*|tableau\w* de bord|kpi",
    "Modélisation / statistiques": r"statisti\w*|modelis\w*|modeling|regression",
    "Machine learning": r"machine learning|apprentissage automatique|deep learning|ia\b|ai\b",
    "ETL / pipelines": r"etl|pipeline\w*|data warehouse|entrepot de donnees",
    "Nettoyage de données": r"data cleaning|nettoyage de donnees|data wrangling|data quality",
    "Visualisation": r"visualisation|visualization|dataviz",
}

QUALITES = {
    "Rigueur": r"rigueur|rigoureu\w*|nauwkeurig\w*|accurate|accuracy|precis\w*",
    "Autonomie": r"autonom\w*|zelfstandig\w*|independent\w*",
    "Esprit d'équipe": r"esprit d'equipe|team ?player|en equipe|teamwork|teamspirit",
    "Communication": r"communicat\w*", "Organisation": r"organis\w*|organiz\w*|planning",
    "Flexibilité": r"flexib\w*|adaptab\w*", "Proactivité": r"proacti\w*|initiative\w*",
    "Curiosité": r"curieu\w*|curious|curiosit\w*", "Analyse": r"esprit d'analyse|analytique|analytical",
    "Résolution de problèmes": r"problem[- ]solving|resolution de probleme\w*",
    "Gestion du stress": r"stress|pression|sous pression", "Orientation résultats": r"result\w*",
    "Sens du détail": r"detail\w*|oog voor detail", "Travail en équipes (shifts)": r"\d ?x ?8|2 ?pauses|3 ?pauses|shift\w*|pauses|equipes? tournantes|ploegen",
}

LANGUES = {
    "Néerlandais": r"neerlandais|nederlands|dutch|flamand|vlaams",
    "Anglais": r"anglais|engels|english",
    "Français": r"francais|frans|french",
    "Allemand": r"allemand|duits|german",
}

_NIVEAU_FORT = re.compile(r"courant|couramment|fluent|vloeiend|native|moedertaal|parfait\w*|perfect|bilingue|tweetalig|c1|c2", re.I)
_NIVEAU_MOYEN = re.compile(r"professionnel\w*|bonne connaissance|goede kennis|zeer goede|maitrise|b2|good knowledge|good command", re.I)

DIPLOMES = {
    "Bachelier": r"bachel\w*|graduat|baccalaur\w*|professionele bachelor",
    "Master": r"master\w*|licenci\w*|universitair|ingenieur civil|burgerlijk ingenieur",
    "Doctorat": r"doctor\w*|ph\.?d",
    "Secondaire": r"secondaire|ceSS|secundair|a2\b|technique",
}

_ANNEES = re.compile(r"(?<![0-9])(\d{1,2})\s*(?:\+\s*)?(?:ans?|jaar|years?)[^.]{0,40}?(?:experience|ervaring)", re.I)
_SALAIRE = re.compile(r"(?:€|eur(?:os?)?)\s*(\d{1,3}(?:[ .]\d{3})+|\d{4,5})|(\d{1,3}(?:[ .]\d{3})+|\d{4,5})\s*(?:€|eur(?:os?)?)", re.I)

_CONTRATS = (
    ("CDI", r"duree indeterminee|cdi|onbepaalde duur|permanent|vast contract|full-?time"),
    ("Intérim", r"interim|uitzend\w*|interimaire"),
    ("CDD", r"duree determinee|cdd|bepaalde duur|temporary|tijdelijk"),
    ("Étudiant", r"etudiant\w*|student\w*|jobstudent"),
    ("Indépendant / freelance", r"independant|freelance|zelfstandig"),
)


def _plat(texte: str) -> str:
    t = unicodedata.normalize("NFKD", str(texte or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", t)


def _compiler(vocabulaire: dict[str, str]) -> dict[str, re.Pattern]:
    return {nom: re.compile(r"(?<![a-z0-9])(?:" + motif + r")(?![a-z0-9])", re.I)
            for nom, motif in vocabulaire.items()}


_OUTILS = _compiler(OUTILS)
_NORMES = _compiler(NORMES)
_METHODES = _compiler(METHODES)
_QUALITES = _compiler(QUALITES)
_LANGUES = _compiler(LANGUES)
_DIPLOMES = _compiler(DIPLOMES)


def _presents(texte: str, motifs: dict[str, re.Pattern]) -> set[str]:
    return {nom for nom, m in motifs.items() if m.search(texte)}


# ------------------------------------------------------------------
# Competences du candidat, alignees sur les vocabulaires
# ------------------------------------------------------------------
# Les competences declarees sont des mots libres (« SAP QM/MM », « Endosafe
# MCS »). On les rattache aux entrees des vocabulaires pour pouvoir dire
# « demande et vous l'avez » / « demande et vous ne l'avez pas ».
_ALIAS_CANDIDAT = {
    "sap qm/mm": "SAP", "sap": "SAP", "lims": "LIMS", "trackwise": "TrackWise",
    "hplc": "HPLC", "uplc": "UPLC", "excel": "Excel", "power bi": "Power BI",
    "sql": "SQL", "sql server": "SQL", "ssis": "SSIS / SSRS", "ssms": "SQL",
    "python": "Python", "pandas": "Pandas", "scikit-learn": "scikit-learn",
    "r": "R", "etl": "ETL / pipelines", "gmp": "GMP / BPF", "bpf": "GMP / BPF",
    "sop": "Documentation qualité", "microbiologie": "Microbiologie",
    "biocharge": "Bioburden / endotoxines", "endosafe mcs": "Bioburden / endotoxines",
    "asepsie": "Stérilité", "alcoa+": "Data integrity / ALCOA",
    "data integrity": "Data integrity / ALCOA", "statistiques": "Modélisation / statistiques",
    "machine learning": "Machine learning", "random forest": "Machine learning",
    "data cleaning": "Nettoyage de données", "ph": None, "conductivité": None,
    "voltampérométrie": None,
}


# Ce qu'une competence declaree implique. Power BI sans reporting n'existe
# pas ; conseiller d'acquerir le reporting a qui declare Power BI serait
# absurde. Chaque implication est etroite et evidente — pas d'inference
# large qui finirait par tout accorder.
_IMPLICATIONS = {
    "Power BI": {"Reporting / tableaux de bord", "Visualisation"},
    "SSIS / SSRS": {"ETL / pipelines"},
    "Pandas": {"Nettoyage de données"},
    "HPLC": {"Chromatographie"},
    "UPLC": {"Chromatographie"},
    "GMP / BPF": {"GxP"},
}


def competences_candidat() -> set[str]:
    declarees = [str(x).strip().lower() for x in
                 (CANDIDATE_TRUTH.get("supported_skills") or [])]
    alignees = set()
    for c in declarees:
        cible = _ALIAS_CANDIDAT.get(c, c)
        if cible:
            alignees.add(cible if cible in _ALIAS_CANDIDAT.values() else c.title())
    for base, impliquees in _IMPLICATIONS.items():
        if base in alignees:
            alignees |= impliquees
    return alignees


# ------------------------------------------------------------------
# Analyse
# ------------------------------------------------------------------

def _charger(chemin: Path) -> list[dict]:
    connexion = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True)
    connexion.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in connexion.execute(
            "SELECT title, company, location, source, contract_type, "
            "       date_published, first_seen, last_seen, is_active, "
            "       COALESCE(detail_matching_text, description, '') AS texte "
            "FROM raw_jobs")]
    finally:
        connexion.close()


def _date(valeur) -> datetime | None:
    brut = str(valeur or "")[:19]
    for forme in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(brut[:len(forme) + (forme.count("%") - 1)], forme)
        except ValueError:
            continue
    return None


def _classer(compteur: Counter, total: int, limite: int = 12) -> list[dict]:
    return [{"nom": n, "offres": k, "part": round(100.0 * k / total, 1) if total else 0.0}
            for n, k in compteur.most_common(limite) if k >= SEUIL]


class _Agregat:
    """Compteurs d'une categorie (ou d'une famille, ou du tout)."""

    def __init__(self):
        self.n = 0
        self.outils = Counter(); self.normes = Counter(); self.methodes = Counter()
        self.qualites = Counter(); self.langues = Counter(); self.langues_fort = Counter()
        self.diplomes = Counter(); self.contrats = Counter(); self.employeurs = Counter()
        self.villes = Counter(); self.sources = Counter()
        self.annees = []; self.salaires = []; self.durees_de_vie = []
        self.semaines = Counter(); self.jours = Counter(); self.heures = Counter()

    def ajouter(self, o: dict, texte: str) -> None:
        self.n += 1
        for nom in _presents(texte, _OUTILS): self.outils[nom] += 1
        for nom in _presents(texte, _NORMES): self.normes[nom] += 1
        for nom in _presents(texte, _METHODES): self.methodes[nom] += 1
        for nom in _presents(texte, _QUALITES): self.qualites[nom] += 1
        for nom in _presents(texte, _DIPLOMES): self.diplomes[nom] += 1

        for langue, motif in _LANGUES.items():
            m = motif.search(texte)
            if not m:
                continue
            self.langues[langue] += 1
            voisinage = texte[max(0, m.start() - 60): m.end() + 60]
            if _NIVEAU_FORT.search(voisinage):
                self.langues_fort[langue] += 1

        m = _ANNEES.search(texte)
        if m and int(m.group(1)) <= 15:
            self.annees.append(int(m.group(1)))

        for m in _SALAIRE.finditer(texte):
            brut = (m.group(1) or m.group(2) or "").replace(" ", "").replace(".", "")
            if brut.isdigit():
                v = int(brut)
                # Mensuel brut plausible en Belgique ; les annuels sont ramenes.
                if 1500 <= v <= 9000: self.salaires.append(v)
                elif 20000 <= v <= 120000: self.salaires.append(round(v / 13.92))

        contrat = _plat(o.get("contract_type") or "") + " " + texte[:400]
        for nom, motif in _CONTRATS:
            if re.search(r"(?<![a-z0-9])(?:" + motif + r")(?![a-z0-9])", contrat):
                self.contrats[nom] += 1
                break

        if o.get("company"):
            self.employeurs[str(o["company"]).strip()] += 1
        if o.get("location"):
            self.villes[_ville(o["location"])] += 1
        if o.get("source"):
            self.sources[str(o["source"])] += 1

        vu = _date(o.get("first_seen"))
        if vu:
            self.semaines[vu.strftime("%G-S%V")] += 1
        pub = _date(o.get("date_published"))
        if pub:
            self.jours[pub.strftime("%a")] += 1
            if "T" in str(o.get("date_published") or "") or " " in str(o.get("date_published") or "").strip():
                self.heures[pub.hour] += 1
        if not o.get("is_active"):
            debut, fin = _date(o.get("first_seen")), _date(o.get("last_seen"))
            if debut and fin and fin >= debut:
                self.durees_de_vie.append((fin - debut).days)

    def resultat(self, competences: set[str]) -> dict:
        n = self.n
        demandes = self.outils + self.normes + self.methodes
        a_valoriser = [x for x in _classer(demandes, n, 40) if x["nom"] in competences][:12]
        a_acquerir = [x for x in _classer(demandes, n, 40) if x["nom"] not in competences][:12]

        jours_ordre = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        jours_fr = {"Mon": "lun", "Tue": "mar", "Wed": "mer", "Thu": "jeu",
                    "Fri": "ven", "Sat": "sam", "Sun": "dim"}
        return {
            "offres": n,
            "outils": _classer(self.outils, n), "normes": _classer(self.normes, n),
            "methodes": _classer(self.methodes, n), "qualites": _classer(self.qualites, n, 10),
            "langues": [
                {"nom": l, "offres": k, "part": round(100.0 * k / n, 1) if n else 0.0,
                 "niveau_fort": self.langues_fort.get(l, 0)}
                for l, k in self.langues.most_common()],
            "diplomes": _classer(self.diplomes, n, 4),
            "contrats": _classer(self.contrats, n, 5),
            "experience": {
                "offres_avec_exigence": len(self.annees),
                "mediane_ans": median(self.annees) if self.annees else None,
                "repartition": dict(sorted(Counter(min(a, 10) for a in self.annees).items())),
            },
            "salaire": {
                "offres_avec_montant": len(self.salaires),
                "mediane_brut_mensuel": int(median(self.salaires)) if self.salaires else None,
                "quartiles": (
                    [int(sorted(self.salaires)[len(self.salaires) * q // 4])
                     for q in (1, 2, 3)] if len(self.salaires) >= 4 else []),
            },
            "employeurs": _classer(self.employeurs, n, 10),
            "villes": _classer(self.villes, n, 10),
            "sources": _classer(self.sources, n, 8),
            "evolution": [{"semaine": s, "offres": k} for s, k in sorted(self.semaines.items())],
            "publication_jours": [{"jour": jours_fr[j], "offres": self.jours.get(j, 0)} for j in jours_ordre],
            "publication_heures": [{"heure": h, "offres": self.heures.get(h, 0)} for h in range(24)],
            "duree_de_vie": {
                "offres_disparues": len(self.durees_de_vie),
                "mediane_jours": median(self.durees_de_vie) if self.durees_de_vie else None,
                # La purge du 10 septembre 2026 a supprime les offres
                # disparues depuis plus de sept jours. Ce qui reste est donc
                # biaise vers les vies courtes : c'est une estimation BASSE,
                # et l'interface doit le dire.
                "estimation": "basse — les offres disparues depuis plus de 7 jours sont purgées",
            },
            "a_valoriser": a_valoriser,
            "a_acquerir": a_acquerir,
        }


def analyser(chemin_base: Path | None = None) -> dict:
    """
    Le portrait complet : global, par famille, par sous-categorie.

    Le calcul lit toute la base et passe chaque offre au crible de tous les
    vocabulaires — quelques secondes. Il n'a a etre refait qu'apres une
    collecte ; l'appelant est cense le memoriser.
    """
    chemin = chemin_base or DB_PATH
    if not chemin.exists():
        return {"erreur": f"base introuvable : {chemin}"}

    offres = _charger(chemin)
    competences = competences_candidat()

    par_categorie: dict[str, _Agregat] = defaultdict(_Agregat)
    par_famille: dict[str, _Agregat] = defaultdict(_Agregat)
    cibles = _Agregat()
    hors_cible = 0

    for o in offres:
        categorie = categoriser(o.get("title") or "", o.get("texte") or "")
        if categorie == "AUTRE":
            hors_cible += 1
            continue
        texte = _plat(o.get("title") or "") + " " + _plat(o.get("texte") or "")
        par_categorie[categorie].ajouter(o, texte)
        par_famille[famille(categorie)].ajouter(o, texte)
        cibles.ajouter(o, texte)

    return {
        "version": CONSEILS_VERSION,
        "offres_scrapees": len(offres),
        "offres_cibles": cibles.n,
        "hors_cible": hors_cible,
        "competences_candidat": sorted(competences),
        "libelles": LIBELLES,
        "familles": {
            f: {
                "libelle": LIBELLES[f],
                **par_famille[f].resultat(competences),
                "sous_categories": {
                    c: {"libelle": LIBELLES[c], **par_categorie[c].resultat(competences)}
                    for c in sorted(par_categorie) if c.startswith(f + "/")
                },
            }
            for f in FAMILLES
        },
        "ensemble": cibles.resultat(competences),
    }
