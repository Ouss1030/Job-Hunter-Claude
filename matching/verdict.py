"""
JOB HUNTER BELGIUM
VERDICT LISIBLE PAR CRITERES EXPLICITES - VERSION 1.1

Pourquoi ce module
------------------
Le scoring historique rend un nombre. Un nombre ne se conteste pas : quand
une offre sort a 47, on ne sait ni pourquoi, ni quoi corriger.

Ce module rend un verdict lisible :

    ACCESSIBLE   aucune barriere, des atouts identifies
    A_VERIFIER   une alerte a lever soi-meme
    FERMEE       une barriere franche, avec la phrase qui la prouve
    INCONNU      pas assez de texte pour se prononcer

Chaque constat cite la phrase de l'annonce qui l'a declenche. Un verdict sans
sa preuve est un verdict qu'on ne peut pas corriger.

Trois regles de conception
--------------------------
1. « Non trouve » n'est pas « non exige ». Si l'annonce ne parle pas de
   diplome, on ne conclut pas qu'aucun diplome n'est requis. D'ou l'etat
   INCONNU, distinct de OK.

2. Les barrieres sont rares et sures. Tout ce qui est douteux devient une
   ALERTE, jamais un rejet : une offre ecartee a tort est invisible, une
   alerte se lit en trois secondes.

3. Frontieres de mots partout. C'est le defaut recurrent du projet — « labo »
   qui matche « elaboration », « QA » qui matche « Qatar ». Chaque motif est
   ancre, et l'audit teste les faux positifs autant que les vrais.

L'experience se compare par domaine
-----------------------------------
Le candidat a 3 ans en QC pharma et 0 an en data professionnelle. Une offre
QC demandant 3 ans d'experience n'est donc PAS une barriere, alors que la
meme exigence sur un poste data en est une. Comparer une exigence d'annees a
un total global serait faux dans les deux sens.

La verite candidat vient de config/candidate_truth.py, jamais recopiee ici :
une seule source, sinon les deux divergent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from config.candidate_truth import CANDIDATE_TRUTH


VERDICT_VERSION = "1.1"

ACCESSIBLE = "ACCESSIBLE"
A_VERIFIER = "A_VERIFIER"
FERMEE = "FERMEE"
INCONNU = "INCONNU"

BLOQUANT = "BLOQUANT"
ALERTE = "ALERTE"
OK = "OK"
NON_TROUVE = "NON_TROUVE"

# En dessous, le texte n'est qu'un bloc de metadonnees : se prononcer serait
# inventer une information.
MIN_TEXTE_UTILE = 300

_LEVEL_RANK = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}

# Les annonces ecrivent indifferemment "neerlandais" et "néerlandais",
# "experience" et "expérience". Une table de correspondance caractere pour
# caractere retire les accents SANS changer la longueur du texte : les
# positions restent valables, donc la phrase de preuve reste extraite du
# texte d'origine, accents compris.
_SANS_ACCENT = str.maketrans(
    "àâäáãåçèéêëìíîïñòóôöõùúûüýÿÀÂÄÁÃÅÇÈÉÊËÌÍÎÏÑÒÓÔÖÕÙÚÛÜÝ",
    "aaaaaaceeeeiiiinooooouuuuyyAAAAAACEEEEIIIINOOOOOUUUUY")


def dessaccentuer(texte: str) -> str:
    """Retire les accents en conservant la longueur, donc les positions."""
    return str(texte or "").translate(_SANS_ACCENT)


def _borne(motif: str) -> str:
    """Ancre un motif entre frontieres de mots."""
    return r"(?<![a-z0-9])(?:" + motif + r")(?![a-z0-9])"


# Séparateurs de phrase, du plus fort au plus faible.
_SEPARATEURS = (".", "\n", ";", "•")


def _phrase(texte: str, position: int, largeur: int = 150) -> str:
    """
    Phrase entourant une correspondance, pour servir de preuve.

    Piege corrige : rfind() renvoie -1 quand il ne trouve pas de separateur,
    ce qui ramenait le debut a zero et faisait citer le DEBUT de l'annonce au
    lieu du passage concerne. Comme les textes Actiris contiennent tres peu de
    points, toutes les preuves etaient fausses — et une preuve fausse est pire
    qu'une absence de preuve.
    """
    plancher = max(0, position - largeur)
    debut = plancher
    for separateur in _SEPARATEURS:
        trouve = texte.rfind(separateur, plancher, position)
        if trouve > debut:
            debut = trouve + 1

    plafond = min(len(texte), position + largeur)
    fin = plafond
    for separateur in _SEPARATEURS:
        trouve = texte.find(separateur, position, plafond)
        if trouve != -1:
            fin = min(fin, trouve)

    return " ".join(texte[debut:fin].split()).strip(" .;:-•")


@dataclass
class Constat:
    critere: str
    etat: str
    message: str
    preuve: str = ""


@dataclass
class Verdict:
    verdict: str
    barrieres: list[Constat] = field(default_factory=list)
    alertes: list[Constat] = field(default_factory=list)
    atouts: list[str] = field(default_factory=list)
    manques: list[str] = field(default_factory=list)
    formation: bool = False
    version: str = VERDICT_VERSION

    def resume(self) -> str:
        if self.verdict == FERMEE:
            return f"FERMEE — {self.barrieres[0].message}"
        if self.verdict == INCONNU:
            return "INCONNU — texte insuffisant"
        detail = f"{len(self.atouts)} atout(s)"
        if self.alertes:
            detail += f", {len(self.alertes)} alerte(s)"
        if self.formation:
            # Mis en avant : une offre qui forme leve les deux barrieres les
            # plus frequentes, le diplome et l'experience.
            detail += " — FORMATION PROPOSÉE"
        return f"{self.verdict} — {detail}"


# ============================================================
# CRITERE 1 — DIPLOME
# ============================================================

# Diplomes strictement superieurs a un bachelier. "bachelier" et "graduat"
# sont volontairement absents : ce sont les siens.
_DIPLOME_SUPERIEUR = re.compile(_borne(
    r"master|master's|licencie|licenciee|ingenieur civil|burgerlijk ingenieur|"
    r"doctorat|doctoraat|ph\.?d|universitair diploma|diplome universitaire"
), re.I)

# ------------------------------------------------------------------
# Domaines de diplome compatibles
# ------------------------------------------------------------------
# Le niveau ne suffit pas : un bachelier en chimie ne repond pas a une
# offre demandant « un bachelier ou un master EN INFORMATIQUE ». Le champ
# disciplinaire compte autant que le niveau, et l'oublier ouvrirait des
# offres qui sont en realite fermees.
_DOMAINES_COMPATIBLES = (
    "chimie", "chemie", "scheikunde", "chemistry", "biochimie", "biochemie",
    "biologie", "biology", "sciences", "wetenschappen", "laboratoire",
    "laboratorium", "pharmaceutique", "farmaceutisch", "pharma",
    "chimique", "chemical", "industriel", "industrieel", "qualite",
    "data", "donnees", "business data", "analyse", "statistiek", "statistique",
)

# Domaine cite JUSTE APRES le diplome : "master EN informatique".
#
# Le motif est ancre en debut de reste de phrase (employe avec .match), et
# non cherche n'importe ou. Cherche librement, il attrapait le premier
# "en / in / de / of" venu : sur une offre "Talent Pool - Capillary
# Electrophoresis", il concluait "diplome en capillary electrophoresis
# demande" et fermait une offre parfaitement ouverte.
_DOMAINE_APRES = re.compile(
    r"\s*(?:'?s)?\s*(?:(?:ou|of|or)\b)?\s*(?:(?:un|une|een|a)\b)?\s*"
    r"(?:en|in|de|of|dans)\s+(?:(?:la|le|les|het|een|de)\s+|l')?"
    r"([a-z][a-z' -]{2,39})", re.I)

# Mots qui terminent un champ disciplinaire : au-dela, on lit la suite de la
# phrase, plus le domaine du diplome.
_FIN_DE_CHAMP = re.compile(
    r"(?<![a-z])(?:on|et|and|ou|or|avec|with|est|is|sont|are|au|aux|du|des|"
    r"pour|for|dans|chez|ayant|experience|ervaring|niveau|orientation)"
    r"(?![a-z])", re.I)

# Mots qui suivent "master" quand il ne s'agit pas d'un diplome.
#
# "master dossiers" vient d'une offre reelle : « dossiers de lots vierges
# (master dossiers et instructions) ». Le mot y designe un document de
# reference pharmaceutique, jamais un diplome.
_MASTER_NON_DIPLOME = ("data", "plan", "class", "file", "batch", "record",
                       "agreement", "thesis", "chef", "bedroom",
                       "dossier", "document", "template", "list", "copy",
                       "schedule", "spec", "key", "sample", "label")


def _champ_du_diplome(phrase: str, diplome: str) -> str:
    """Champ disciplinaire cite juste apres le diplome, ou chaine vide."""
    depart = phrase.lower().find(diplome.lower())
    if depart < 0:
        return ""
    trouve = _DOMAINE_APRES.match(phrase[depart + len(diplome):])
    if not trouve:
        return ""
    champ = trouve.group(1)
    coupure = _FIN_DE_CHAMP.search(champ)
    if coupure:
        champ = champ[:coupure.start()]
    return champ.strip(" '-").lower()

# L'employeur forme lui-meme : c'est le cas le plus favorable qui soit.
#
# Une offre qui propose une formation leve a la fois l'exigence de diplome
# et celle d'experience — l'employeur accepte de prendre quelqu'un qui ne
# sait pas encore. Ces offres meritent d'etre remontees, pas ecartees.
_FORMATION_PROPOSEE = re.compile(
    r"formation\s+(?:avec\s+emploi|assur[eé]e|pr[eé]vue|compl[eè]te|"
    r"interne|continue|dispens[eé]e|sur\s+mesure|en\s+alternance)|"
    r"formation\s+(?:est|sera)\s+(?:pr[eé]vue|assur[eé]e|propos[eé]e)|"
    r"nous\s+vous\s+formons|on\s+vous\s+forme|we\s+leiden\s+je?\s+op|"
    r"opleiding\s+(?:wordt\s+)?(?:voorzien|aangeboden)|"
    r"debutant[es]?\s+accept[eé]|geen\s+ervaring\s+(?:vereist|nodig)|"
    r"aucune\s+experience\s+(?:requise|exigee|necessaire)|"
    r"formation\s+en\s+entreprise|contrat\s+de\s+formation", re.I)

# Le bachelier explicitement accepte a cote du master.
_BACHELIER_ACCEPTE = re.compile(
    r"bachel(?:ier|or)|graduat|bacheloropleiding", re.I)

# Equivalence explicitement offerte : ce n'est plus une barriere.
_EQUIVALENT = re.compile(
    r"(ou|of|or)\s+(equivalent|gelijkwaardig|equivalence)"
    r"|equivalent\s+par\s+(l')?experience"
    r"|gelijkwaardig\s+door\s+ervaring", re.I)

# Formulations qui rendent l'exigence facultative.
_SOUHAITE = re.compile(
    r"(atout|plus est|un plus|pluspunt|preference|preferably|is a plus|"
    r"souhaite|souhaitee|gewenst|nice to have)", re.I)


def evaluer_diplome(texte: str) -> Constat:
    for m in _DIPLOME_SUPERIEUR.finditer(texte):
        suite = texte[m.end():m.end() + 14].lower()
        # "Master Data Officer", "master plan", "masterclass" : le mot
        # designe un metier ou un document, pas un diplome. Sans ce garde,
        # un poste de Master Data Officer est ferme a tort.
        if any(suite.lstrip().startswith(x) for x in _MASTER_NON_DIPLOME):
            continue
        phrase = _phrase(texte, m.start())
        break
    else:
        return Constat("diplome", NON_TROUVE,
                       "aucune exigence de diplôme détectée")

    # Une formation proposée par l'employeur lève l'exigence de diplôme.
    if _FORMATION_PROPOSEE.search(phrase):
        return Constat("diplome", OK,
                       f"{m.group(0)} mentionné, mais une formation est "
                       f"proposée", phrase)

    # "master ou equivalent par experience" ouvre explicitement la porte.
    if _EQUIVALENT.search(phrase):
        return Constat("diplome", ALERTE,
                       f"{m.group(0)} demandé, mais équivalence par "
                       f"l'expérience acceptée", phrase)

    # Le domaine compte autant que le niveau.
    champ = _champ_du_diplome(phrase, m.group(0))
    if champ and not any(ok in champ for ok in _DOMAINES_COMPATIBLES):
        return Constat("diplome", BLOQUANT,
                       f"diplôme en {champ[:28]} demandé — votre bachelier "
                       f"est en chimie", phrase)

    # Ici, le domaine est compatible, ou n'est pas precise.
    #
    # Le bachelier explicitement accepte n'etait teste que si un domaine
    # avait pu etre extrait. « Bachelier ou master, orientation scientifique »
    # ne livre aucun domaine exploitable : l'offre etait fermee alors qu'elle
    # nomme votre diplome.
    if _BACHELIER_ACCEPTE.search(phrase):
        precision = f" en {champ[:24]}" if champ else ""
        return Constat("diplome", OK,
                       f"bachelier explicitement accepté{precision}", phrase)
    if _SOUHAITE.search(phrase):
        return Constat("diplome", ALERTE,
                       f"{m.group(0)} mentionné mais présenté comme un atout",
                       phrase)
    return Constat("diplome", BLOQUANT,
                   f"{m.group(0)} exigé — supérieur à votre bachelier", phrase)


# ============================================================
# CRITERE 2 — EXPERIENCE, COMPAREE PAR DOMAINE
# ============================================================

_ANNEES = re.compile(
    r"(?<![0-9])(\d{1,2})\s*(?:\+\s*)?(?:ans?|jaar|year|years)"
    r"[^.]{0,40}?(?:experience|ervaring|ervaringen)", re.I)

# Au-dela, ce n'est plus une exigence adressee au candidat.
#
# Cas mesure : « Forte de 70 ans d'experience dans le recrutement », lu comme
# « 70 ans exiges » — l'agence parlait d'elle-meme. Aucune offre reelle ne
# demande plus de quinze ans ; au-dela, le nombre decrit l'entreprise.
_ANNEES_PLAUSIBLES_MAX = 15

# L'entreprise ou l'agence annonce SON anciennete, pas la votre exigee.
_EXPERIENCE_DE_LA_SOCIETE = re.compile(
    r"(?:fort[e]?s?\s+de|riche\s+de|nous\s+(?:avons|comptons)|"
    r"notre\s+\w+|nos\s+\w+|depuis\s+plus\s+de|avec\s+ses|"
    r"met\s+meer\s+dan|ons\s+\w+)\s*$", re.I)

# Le secteur cite est celui du recruteur, pas celui du poste.
_EXPERIENCE_DU_RECRUTEUR = re.compile(
    r"(?:experience|ervaring)[^.]{0,30}?(?:dans\s+le\s+|in\s+de\s+)?"
    r"(?<![a-z])(?:recrutement|rekrutering|interim|uitzendsector|placement|"
    r"staffing|selection\s+de\s+personnel)(?![a-z])", re.I)

# « Data Centres de nouvelle generation » : le mot data y designe un
# batiment, dans le paragraphe de presentation de l'entreprise.
_DOMAINE_DATA = re.compile(_borne(
    r"data(?!\s+cent)|donnees|bi|business intelligence|analytics|power bi|"
    r"sql|python|etl"
), re.I)

# Marqueurs de laboratoire et de qualite.
#
# Ils l'emportent sur les marqueurs data, et c'est voulu : un « Data Reviewer
# Chimie » ou un « Inspecteur qualite » qui exploite des donnees contient bien
# le mot data, mais les annees qui comptent pour lui sont celles de
# laboratoire — celles que vous avez. L'ancienne regle prenait le premier
# marqueur croise dans les 1200 premiers caracteres et concluait « 3 ans
# exiges en data, vous en avez 0 », fermant des postes de laboratoire.
_DOMAINE_LABORATOIRE = re.compile(_borne(
    r"laboratoire|laboratorium|labo|hplc|gc-?ms|lc-?ms|chromatographie|"
    r"chromatography|spectrometrie|spectrometry|titration|karl fischer|"
    r"qc|qa|controle qualite|assurance qualite|quality control|"
    r"quality assurance|kwaliteitscontrole|gmp|gxp|bpf|"
    r"echantillon|echantillons|monsters|analyste|analytical|analytique|"
    r"pharmaceutique|farmaceutisch|pharma|chimie|chemie|chemical|chimique|"
    r"microbiologie|microbiology|dossier de lot|batch record"
), re.I)


# Voisinage lu autour de l'exigence pour en deviner le domaine.
_FENETRE_DOMAINE = 400


def _annees_candidat(texte: str, position: int | None = None
                     ) -> tuple[float, str]:
    """
    Annees defendables selon le domaine de l'offre.

    Trois ans de QC pharma ne valent pas trois ans de data. Comparer une
    exigence a un total global se tromperait dans les deux sens.

    Le domaine se lit d'abord AUTOUR de l'exigence, et seulement a defaut
    dans l'annonce entiere. Sur une offre d'inspecteur qualite mesuree le
    9 septembre 2026, la tete d'annonce vantait des « Data Centres » tandis
    que l'exigence disait « 3 ans dans l'inspection et l'assurance qualite
    (QA/QC) » : lire la tete donnait « 3 ans exiges en data, vous en avez 0 »
    et fermait un poste qui vous est ouvert.
    """
    exp = CANDIDATE_TRUTH.get("professional_experience", {}) or {}
    qc = float(exp.get("pharma_qc_years") or 0)
    data = float(exp.get("data_professional_years") or 0)

    fenetres = []
    if position is not None:
        fenetres.append(texte[max(0, position - _FENETRE_DOMAINE):
                              position + _FENETRE_DOMAINE])
    fenetres.append(texte[:2000])

    for fenetre in fenetres:
        if _DOMAINE_LABORATOIRE.search(fenetre):
            return qc, "QC / laboratoire"
        if _DOMAINE_DATA.search(fenetre):
            return data, "data"
    return qc, "QC / laboratoire"


def _exigence_annees(texte: str):
    """
    Premiere duree qui soit vraiment une exigence adressee au candidat.

    Les durees invraisemblables et celles ou l'entreprise decrit sa propre
    anciennete sont ignorees, pas transformees en barriere.
    """
    for m in _ANNEES.finditer(texte):
        if float(m.group(1)) > _ANNEES_PLAUSIBLES_MAX:
            continue
        avant = texte[max(0, m.start() - 40):m.start()]
        if _EXPERIENCE_DE_LA_SOCIETE.search(avant):
            continue
        if _EXPERIENCE_DU_RECRUTEUR.search(m.group(0)
                                           + texte[m.end():m.end() + 40]):
            continue
        return m
    return None


def evaluer_experience(texte: str) -> Constat:
    m = _exigence_annees(texte)
    if not m:
        return Constat("experience", NON_TROUVE,
                       "aucune durée d'expérience exigée")

    exigees = float(m.group(1))
    possedees, domaine = _annees_candidat(texte, m.start())
    phrase = _phrase(texte, m.start())

    # L'employeur qui forme accepte quelqu'un qui n'a pas encore l'expérience.
    if _FORMATION_PROPOSEE.search(phrase):
        return Constat("experience", OK,
                       f"{exigees:.0f} ans mentionnés, mais une formation "
                       f"est proposée", phrase)

    if _SOUHAITE.search(phrase):
        return Constat("experience", ALERTE,
                       f"{exigees:.0f} ans souhaités, présentés comme un atout",
                       phrase)
    if possedees >= exigees:
        return Constat("experience", OK,
                       f"{exigees:.0f} ans exigés, vous en avez "
                       f"{possedees:.0f} en {domaine}", phrase)
    if exigees - possedees <= 2:
        return Constat("experience", ALERTE,
                       f"{exigees:.0f} ans exigés en {domaine}, vous en avez "
                       f"{possedees:.0f} — écart franchissable", phrase)
    return Constat("experience", BLOQUANT,
                   f"{exigees:.0f} ans exigés en {domaine}, vous en avez "
                   f"{possedees:.0f}", phrase)


# ============================================================
# CRITERE 3 — LANGUES
# ============================================================

_LANGUES = {
    "Néerlandais": r"neerlandais|nederlands|dutch|flamand",
    "Anglais": r"anglais|engels|english",
    "Français": r"francais|frans|french",
}

# Deux niveaux d'exigence, associés au niveau CECR qu'ils supposent.
#
# La distinction est ce qui évite de traiter le néerlandais et l'anglais de
# la même façon : « connaissance professionnelle » suppose un B2, ce qui est
# hors de portée à A2 mais pratiquement atteint à B1.
_EXIGENCE_MOYENNE = (r"professionnel|professionnele|bonne connaissance|"
                     r"goede kennis|zeer goede|maitrise|B2")
_EXIGENCE_FORTE = (r"courant|couramment|fluent|vloeiend|native|moedertaal|"
                   r"parfaitement|perfect|excellente maitrise|uitstekende|C1|C2")

_MAITRISE = _EXIGENCE_MOYENNE + "|" + _EXIGENCE_FORTE

_NIVEAU_EXIGE = {"moyenne": _LEVEL_RANK["B2"], "forte": _LEVEL_RANK["C1"]}

# On ne bloque qu'au-delà d'un cran d'écart.
#
# Un écart de un cran (B1 face à une exigence B2) se rattrape dans la
# pratique et ne justifie pas d'écarter une offre définitivement : ces
# offres deviennent des alertes, visibles et jugeables. Au-delà de deux
# crans — A2 face à B2 — l'obstacle est réel.
_ECART_BLOQUANT = 2

_BILINGUE = re.compile(
    r"(tweetalig|bilingue)\s*(?:\(?\s*(?:fr|nl)\s*[/-]\s*(?:nl|fr))?", re.I)

# L'employeur propose lui-même de combler l'écart : ce n'est plus une porte
# fermée, seulement un point à confirmer.
_FORMATION_OFFERTE = re.compile(
    r"formation linguistique|taalopleiding|cours de langue|taallessen|"
    r"pret[e]?s?\s+a\s+suivre|bereid\s+.{0,20}opleiding|"
    r"formation\s+(?:sera|est)\s+(?:pr[eé]vue|assur[eé]e)", re.I)

_ALTERNATIVE = re.compile(
    r"(francais|frans)\s*(?:ou|of|or)\s*(?:du |de l')?\s*(neerlandais|nederlands)|"
    r"(neerlandais|nederlands)\s*(?:ou|of|or)\s*(?:du |de l')?\s*(francais|frans)", re.I)


def _niveau_candidat(langue: str) -> int:
    brut = str((CANDIDATE_TRUTH.get("languages") or {}).get(langue, ""))
    m = re.search(r"\b(A1|A2|B1|B2|C1|C2)\b", brut)
    return _LEVEL_RANK.get(m.group(1), 0) if m else 0


def evaluer_langues(texte: str) -> Constat:
    # "Français OU néerlandais" reste accessible : ne jamais bloquer dessus.
    if _ALTERNATIVE.search(texte):
        return Constat("langues", OK,
                       "français ou néerlandais accepté",
                       _phrase(texte, _ALTERNATIVE.search(texte).start()))

    m = _BILINGUE.search(texte)
    if m and _niveau_candidat("Néerlandais") < _LEVEL_RANK["B2"]:
        phrase = _phrase(texte, m.start())
        if _SOUHAITE.search(phrase):
            return Constat("langues", ALERTE,
                           "bilinguisme présenté comme un atout", phrase)
        if _FORMATION_OFFERTE.search(phrase):
            return Constat("langues", ALERTE,
                           "bilinguisme exigé, mais une formation "
                           "linguistique est proposée", phrase)
        return Constat("langues", BLOQUANT,
                       "bilingue FR/NL exigé — vous êtes A2 en néerlandais",
                       phrase)

    for langue, motif in _LANGUES.items():
        # Fenêtre volontairement étroite, et sans saut de ligne : les textes
        # Actiris comportent peu de points, donc une fenêtre large reliait
        # deux mots sans rapport situés à des endroits éloignés de l'annonce.
        exigence = re.compile(
            rf"(?:{motif})[^.\n]{{0,45}}?(?:{_MAITRISE})|"
            rf"(?:{_MAITRISE})[^.\n]{{0,30}}?(?:{motif})", re.I)
        m = exigence.search(texte)
        if not m:
            continue

        niveau = _niveau_candidat(langue)
        phrase = _phrase(texte, m.start())

        # Le niveau exigé se déduit des mots employés, pas de la langue.
        force = ("forte" if re.search(_EXIGENCE_FORTE, m.group(0), re.I)
                 else "moyenne")
        exige = _NIVEAU_EXIGE[force]
        if niveau >= exige:
            continue

        if _SOUHAITE.search(phrase):
            return Constat("langues", ALERTE,
                           f"{langue} présenté comme un atout", phrase)
        if _FORMATION_OFFERTE.search(phrase):
            # L'annonce propose elle-même une formation linguistique :
            # l'exigence n'est plus une porte fermée.
            return Constat("langues", ALERTE,
                           f"{langue} exigé, mais une formation est proposée",
                           phrase)

        ecart = exige - niveau
        if ecart < _ECART_BLOQUANT:
            return Constat("langues", ALERTE,
                           f"{langue} demandé à un niveau légèrement supérieur "
                           f"au vôtre — à juger vous-même", phrase)
        return Constat("langues", BLOQUANT,
                       f"{langue} exigé à un niveau hors de portée "
                       f"({ecart} crans d'écart)", phrase)

    return Constat("langues", NON_TROUVE, "aucune exigence de langue bloquante")


# ============================================================
# CRITERE 4 — HABILITATIONS
# ============================================================

_HABILITATIONS = {
    "permis C": r"permis\s*c\b|rijbewijs\s*c\b",
    "cariste": r"cariste|heftruck|clark\b",
    "permis de conduire": r"permis\s*b\b|rijbewijs\s*b\b",
}


def evaluer_habilitations(texte: str) -> Constat:
    for nom, motif in _HABILITATIONS.items():
        m = re.search(motif, texte, re.I)
        if not m:
            continue
        if nom == "permis de conduire":
            # Le candidat a le permis B : c'est un OK, pas une barriere.
            return Constat("habilitations", OK, "permis B exigé — vous l'avez",
                           _phrase(texte, m.start()))
        # Un permis C ou une formation cariste s'obtiennent : jamais bloquant.
        return Constat("habilitations", ALERTE,
                       f"{nom} demandé — à obtenir",
                       _phrase(texte, m.start()))
    return Constat("habilitations", NON_TROUVE, "aucune habilitation exigée")


# ============================================================
# CRITERE 5 — COMPETENCES
# ============================================================

def _competences_candidat() -> list[str]:
    return [str(x) for x in (CANDIDATE_TRUTH.get("supported_skills") or [])]


def _competences_interdites() -> list[str]:
    return [str(x) for x in
            (CANDIDATE_TRUTH.get("unsupported_or_not_proven") or [])]


def evaluer_competences(texte: str) -> tuple[list[str], list[str]]:
    """Renvoie (atouts trouves, competences demandees que vous n'avez pas)."""
    atouts = []
    for skill in _competences_candidat():
        noyau = re.escape(skill.strip())
        if not noyau or len(noyau) < 2:
            continue
        if re.search(_borne(noyau), texte, re.I):
            atouts.append(skill)

    manques = []
    for terme in _competences_interdites():
        # Ces entrees sont des phrases ("GC comme competence pratiquee") :
        # on ne garde que le premier mot significatif pour la recherche.
        mot = re.split(r"[ ,(]", str(terme).strip())[0]
        if len(mot) < 3:
            continue
        if re.search(_borne(re.escape(mot)), texte, re.I):
            manques.append(terme)

    return atouts, manques


# ============================================================
# VERDICT
# ============================================================

CRITERES = (evaluer_diplome, evaluer_experience,
            evaluer_langues, evaluer_habilitations)


def evaluer(texte: str) -> Verdict:
    texte = str(texte or "")
    if len(texte) < MIN_TEXTE_UTILE:
        return Verdict(INCONNU)

    plat = dessaccentuer(texte)
    constats = [critere(plat) for critere in CRITERES]

    # La formation est annoncée n'importe où dans l'annonce, rarement dans la
    # phrase qui pose l'exigence. La chercher seulement autour du diplôme
    # ratait le cas courant : « Nous vous formons à nos procédés. Un master
    # est demandé. » — deux phrases distinctes, une seule intention.
    formation = bool(_FORMATION_PROPOSEE.search(plat))
    if formation:
        # Un employeur qui forme accepte quelqu'un qui n'a pas encore le
        # diplôme ni l'expérience. Ces deux barrières tombent ; la langue et
        # les habilitations, non — une formation métier n'apprend pas le
        # néerlandais.
        constats = [
            Constat(c.critere, OK,
                    f"{c.message} — mais une formation est proposée", c.preuve)
            if c.etat in (BLOQUANT, ALERTE)
            and c.critere in ("diplome", "experience")
            else c
            for c in constats
        ]

    barrieres = [c for c in constats if c.etat == BLOQUANT]
    alertes = [c for c in constats if c.etat == ALERTE]
    atouts, manques = evaluer_competences(plat)

    if barrieres:
        verdict = FERMEE
    elif alertes:
        verdict = A_VERIFIER
    else:
        verdict = ACCESSIBLE

    return Verdict(verdict=verdict, barrieres=barrieres, alertes=alertes,
                   atouts=atouts, manques=manques, formation=formation)


def fiche(titre: str, texte: str) -> str:
    """Rendu lisible d'une offre, pour lecture humaine."""
    v = evaluer(texte)
    lignes = [f"{titre}", f"  {v.resume()}"]
    for c in v.barrieres:
        lignes.append(f"  BARRIERE  {c.message}")
        if c.preuve:
            lignes.append(f"            « {c.preuve[:110]} »")
    for c in v.alertes:
        lignes.append(f"  alerte    {c.message}")
    if v.atouts:
        lignes.append(f"  atouts    {', '.join(v.atouts[:8])}")
    if v.manques:
        lignes.append(f"  manques   {', '.join(str(x)[:30] for x in v.manques[:4])}")
    return "\n".join(lignes)
