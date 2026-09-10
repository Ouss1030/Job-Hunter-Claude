"""
JOB HUNTER BELGIUM
MOTEUR DE VERDICT - AUDIT V1.0 (HORS LIGNE)

    python -m diagnostics.verdict_v1_audit

Aucun reseau, aucune base : uniquement des textes d'annonce construits pour
figer un comportement precis.

Pourquoi cet audit compte particulierement
------------------------------------------
Chaque cas ci-dessous correspond a un defaut REELLEMENT rencontre pendant la
mise au point, sur des annonces reelles :

  - « Master Data Officer » ferme pour cause de diplome, alors que le mot
    designe un metier ;
  - « titulaire d'un master ou equivalent par experience » traite comme une
    barriere alors que l'annonce ouvre la porte ;
  - « Maitrise du neerlandais ou du francais » lu comme une exigence de
    neerlandais alors que c'est une alternative ;
  - toutes les phrases de preuve citant le DEBUT de l'annonce, parce que
    rfind() renvoie -1 quand il ne trouve pas de separateur ;
  - « neerlandais » sans accent non reconnu.

Ce dernier point est le plus insidieux : la preuve servait aussi a decider si
une exigence etait facultative. Une preuve fausse produisait donc de fausses
alertes — le defaut d'affichage etait devenu un defaut de jugement.

Ces cas ne se voient pas a la lecture du code et passent py_compile sans
broncher. Ils ne se voient qu'ici.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from diagnostics.version_support import at_least
from matching.verdict import (
    ACCESSIBLE,
    A_VERIFIER,
    FERMEE,
    INCONNU,
    VERDICT_VERSION,
    dessaccentuer,
    evaluer,
    evaluer_competences,
    _phrase,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

# Rembourrage : le moteur refuse de se prononcer en dessous de 300 caracteres,
# ce qui est voulu. Les cas de test doivent donc depasser ce seuil.
BOURRAGE = (" Nous offrons un environnement de travail agreable, une equipe "
            "soudee et des possibilites de developpement. Le poste est a "
            "pourvoir immediatement dans nos installations belges. " * 3)


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def verdict_de(texte: str) -> str:
    return evaluer(texte + BOURRAGE).verdict


def main():
    print("=" * 92)
    print(f"MOTEUR DE VERDICT V{VERDICT_VERSION} - AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = []

    print("A. LES QUATRE ETATS")
    print("-" * 92)
    tests.append(check("Texte trop court : INCONNU, on ne se prononce pas",
                       evaluer("Technicien de laboratoire.").verdict == INCONNU))
    tests.append(check("Annonce neutre : ACCESSIBLE",
                       verdict_de("Poste de technicien de laboratoire en "
                                  "controle qualite.") == ACCESSIBLE))
    tests.append(check("Master exige : FERMEE",
                       verdict_de("Vous etes titulaire d'un Master en "
                                  "sciences.") == FERMEE))
    tests.append(check("Exigence facultative : A_VERIFIER",
                       verdict_de("Un Master est un atout pour ce poste.")
                       == A_VERIFIER))

    print()
    print("B. DIPLOME — LES FAUX POSITIFS RENCONTRES")
    print("-" * 92)
    # "Master Data Officer" est un metier. Sans garde, le poste etait ferme.
    for titre in ("Master Data Officer, gestion des donnees de reference.",
                  "Vous participez au master plan industriel du site.",
                  "Une masterclass est organisee chaque trimestre."):
        tests.append(check(f"Pas un diplome : {titre[:44]}",
                           verdict_de(titre) != FERMEE))

    tests.append(check(
        "Equivalence par l'experience : alerte, pas barriere",
        verdict_de("Vous etes titulaire d'un master ou equivalent par "
                   "experience.") == A_VERIFIER))
    tests.append(check(
        "Gelijkwaardig door ervaring reconnu aussi",
        verdict_de("Je hebt een masterdiploma of gelijkwaardig door "
                   "ervaring.") != FERMEE))
    tests.append(check(
        "Bachelier demande : jamais une barriere",
        verdict_de("Vous etes titulaire d'un bachelier en chimie.")
        == ACCESSIBLE))

    print()
    print("C. EXPERIENCE — COMPAREE PAR DOMAINE")
    print("-" * 92)
    # 3 ans de QC ne valent pas 3 ans de data : comparer a un total global
    # se tromperait dans les deux sens.
    tests.append(check(
        "3 ans exiges en QC : vous les avez",
        verdict_de("Vous disposez de 3 ans d'experience en controle qualite "
                   "GMP et LIMS.") == ACCESSIBLE))
    tests.append(check(
        "5 ans exiges en data : hors de portee",
        verdict_de("Vous avez 5 ans d'experience en data analytics, SQL et "
                   "Power BI.") == FERMEE))
    tests.append(check(
        "2 ans exiges en data : ecart franchissable, alerte",
        verdict_de("Vous avez 2 ans d'experience en data et reporting SQL.")
        == A_VERIFIER))

    print()
    print("D. LANGUES — SEUILS PAR ECART DE NIVEAU")
    print("-" * 92)
    # Le candidat est C2 francais, B1 anglais, A2 neerlandais.
    # On ne ferme qu'a partir de deux crans d'ecart.
    cas_langues = [
        ("anglais professionnel (B2, 1 cran)", "Vous disposez d'une "
         "connaissance professionnelle de l'anglais.", A_VERIFIER),
        ("anglais courant (C1, 2 crans)", "Vous maitrisez couramment "
         "l'anglais.", FERMEE),
        ("anglais C1 explicite", "Un niveau d'anglais C1 est requis.", FERMEE),
        ("neerlandais bonne connaissance (2 crans)", "Je hebt een goede "
         "kennis van het Nederlands.", FERMEE),
        ("neerlandais courant", "Vloeiend Nederlands is vereist.", FERMEE),
        ("francais courant : vous etes C2", "Vous maitrisez couramment le "
         "francais.", ACCESSIBLE),
    ]
    for nom, texte, attendu in cas_langues:
        tests.append(check(f"{nom} -> {attendu}",
                           verdict_de(texte) == attendu, verdict_de(texte)))

    print()
    print("E. LANGUES — LES ECHAPPATOIRES A NE PAS MANQUER")
    print("-" * 92)
    tests.append(check(
        "« francais OU neerlandais » n'est pas une exigence",
        verdict_de("Maitrise du francais ou du neerlandais.") == ACCESSIBLE))
    tests.append(check(
        "L'alternative accepte un determinant",
        verdict_de("Maitrise du neerlandais ou du francais.") == ACCESSIBLE))
    tests.append(check(
        "Formation linguistique proposee : alerte, pas barriere",
        verdict_de("Bilingue neerlandais et francais, ou vous etes pret a "
                   "suivre une formation linguistique intensive.")
        == A_VERIFIER))
    tests.append(check(
        "« neerlandais est un atout » ne bloque pas",
        verdict_de("Le neerlandais est un atout.") == ACCESSIBLE))
    tests.append(check(
        "Bilingue exige : barriere",
        verdict_de("Vous etes parfaitement bilingue NL/FR.") == FERMEE))

    print()
    print("F. ACCENTS — LES DEUX ORTHOGRAPHES")
    print("-" * 92)
    # Les annonces ecrivent indifferemment "neerlandais" et "néerlandais".
    tests.append(check("Sans accent detecte",
                       verdict_de("Vloeiend Nederlands vereist.") == FERMEE))
    tests.append(check("Avec accents detecte",
                       verdict_de("La maîtrise du néerlandais courant est "
                                  "exigée.") == FERMEE))
    tests.append(check("Desaccentuation preserve la longueur",
                       len(dessaccentuer("éàçüî")) == len("éàçüî"),
                       "sinon les positions de preuve seraient decalees"))

    print()
    print("G. LES PREUVES — LE DEFAUT LE PLUS COUTEUX")
    print("-" * 92)
    # rfind() renvoyait -1 sans separateur proche, ramenant le debut a zero :
    # toutes les preuves citaient l'en-tete de l'annonce.
    long_sans_point = ("Titre de l annonce " + "mot " * 80
                       + "vloeiend Nederlands vereist " + "suite " * 20)
    v = evaluer(long_sans_point)
    preuve = v.barrieres[0].preuve if v.barrieres else ""
    tests.append(check("Barriere detectee dans un texte sans ponctuation",
                       bool(v.barrieres)))
    tests.append(check("La preuve cite le passage, pas le debut de l'annonce",
                       "Nederlands" in preuve, preuve[:56]))
    tests.append(check("La preuve ne commence pas par le titre",
                       not preuve.startswith("Titre de l annonce")))
    tests.append(check("Sans separateur, la fenetre reste bornee",
                       len(_phrase("a" * 1000, 500)) <= 320))

    print()
    print("H. COMPETENCES")
    print("-" * 92)
    atouts, _ = evaluer_competences(
        "Vous maitrisez Python, SQL et Power BI pour vos analyses.")
    tests.append(check("Competences defendables reconnues",
                       {"Python", "SQL"} <= set(atouts), ", ".join(atouts[:6])))
    atouts_vides, _ = evaluer_competences("Poste de jardinier paysagiste.")
    tests.append(check("Aucune competence inventee sur une annonce hors sujet",
                       not atouts_vides, str(atouts_vides)))

    print()
    print("I. FRONTIERES DE MOTS — LE DEFAUT RECURRENT DU PROJET")
    print("-" * 92)
    # « labo » ne doit pas matcher « elaboration », « QA » ne doit pas
    # matcher « Qatar ». Meme famille que le bug V.I.E historique.
    pieges = [
        ("Elaboration de projets", "labo"),
        ("Poste base au Qatar", "QA"),
        ("Fabrication de pieces", "fabric"),
    ]
    for texte, terme in pieges:
        atouts, _ = evaluer_competences(texte)
        tests.append(check(
            f"« {texte} » ne declenche pas « {terme} »",
            not any(terme.lower() in a.lower() for a in atouts),
            str(atouts)))

    print()
    print("K. DOMAINE DU DIPLOME — LE NIVEAU NE SUFFIT PAS")
    print("-" * 92)
    # Un bachelier en chimie ne repond pas a « bachelier ou master EN
    # INFORMATIQUE ». Sans ce controle, l'offre serait declaree accessible.
    tests.append(check(
        "Bachelier accepte mais en INFORMATIQUE : ferme",
        verdict_de("Vous etes titulaire d'un diplome de bachelier ou de "
                   "master en informatique.") == FERMEE))
    tests.append(check(
        "Bachelier accepte en CHIMIE : accessible",
        verdict_de("Vous etes titulaire d'un bachelier ou d'un master en "
                   "chimie.") == ACCESSIBLE))
    tests.append(check(
        "Master en droit : ferme (domaine incompatible)",
        verdict_de("Vous avez un master en droit des affaires.") == FERMEE))
    tests.append(check(
        "Master en biologie : ferme malgre le domaine proche",
        verdict_de("Vous avez un master en biologie analytique.") == FERMEE,
        "le domaine est compatible mais le niveau reste un master"))

    print()
    print("L. FORMATION PROPOSEE — LE CAS LE PLUS FAVORABLE")
    print("-" * 92)
    # Un employeur qui forme accepte quelqu'un qui ne sait pas encore :
    # le diplome et l'experience cessent d'etre des barrieres.
    for nom, texte in (
            ("formation avec emploi",
             "Developpeur Odoo. Formation avec emploi, aucune experience requise."),
            ("nous vous formons",
             "Nous vous formons a nos procedes. Un master est demande."),
            ("formation malgre 5 ans exiges",
             "Formation assuree en interne. 5 ans d'experience en data souhaites."),
            ("opleiding aangeboden",
             "Opleiding wordt aangeboden. Een masterdiploma is vereist.")):
        tests.append(check(f"{nom} -> accessible", verdict_de(texte) == ACCESSIBLE))

    tests.append(check(
        "La formation est signalee dans le verdict",
        evaluer("Formation avec emploi assuree." + BOURRAGE).formation))
    tests.append(check(
        "« FORMATION PROPOSÉE » apparait dans le resume",
        "FORMATION" in evaluer("Formation avec emploi assuree."
                               + BOURRAGE).resume()))
    # Une formation metier n'apprend pas le neerlandais : la langue reste
    # une barriere, sinon on ouvrirait des offres reellement fermees.
    tests.append(check(
        "La formation ne leve PAS la barriere de langue",
        verdict_de("Formation assuree en interne. Vloeiend Nederlands "
                   "vereist.") == FERMEE))

    print()
    print("M. LES QUATRE FAUX POSITIFS MESURES SUR LE POOL REEL")
    print("-" * 92)
    # Ces quatre offres etaient classees FERMEE et atteignaient malgre tout
    # APPLY_NOW. Elles ont ete lues une par une : aucune n'est fermee. Elles
    # sont figees ici parce qu'un juge qui se trompe est pire qu'aucun juge —
    # c'est sur lui qu'on branche le filtre du pipeline.

    # 1. L'agence parle de sa propre anciennete.
    tests.append(check(
        "70 ans d'experience de l'agence : pas une exigence",
        verdict_de("Forte de 70 ans d'experience dans le recrutement, notre "
                   "agence recherche un technicien en chimie pour son client. "
                   "Vous realisez les analyses de routine au laboratoire.")
        != FERMEE))
    tests.append(check(
        "Une duree invraisemblable est ignoree, pas transformee en barriere",
        evaluer("Notre societe possede 40 ans d'experience dans le secteur. "
                "Nous cherchons un analyste de laboratoire." + BOURRAGE
                ).barrieres == []))
    tests.append(check(
        "Mais une duree plausible reste evaluee",
        any(c.critere == "experience" for c in evaluer(
            "Nous demandons 8 ans d'experience en developpement logiciel "
            "Java et Kubernetes." + BOURRAGE).barrieres)))

    # 2. Le mot "data" dans une offre de laboratoire.
    tests.append(check(
        "Data Reviewer en chimie : les annees comptees sont celles du labo",
        verdict_de("Data Reviewer Chimie. Vous revoyez les donnees "
                   "analytiques des lots au laboratoire de controle qualite. "
                   "3 ans d'experience sont demandes.") != FERMEE))
    tests.append(check(
        "Inspecteur qualite exploitant des donnees : pas ferme non plus",
        verdict_de("Inspecteur qualite. Vous exploitez les data de "
                   "production et realisez les controles en laboratoire "
                   "selon les GMP. 3 ans d'experience requis.") != FERMEE))
    tests.append(check(
        "Un vrai poste data sans laboratoire reste une barriere",
        verdict_de("Data Engineer. Vous construisez les pipelines SQL et "
                   "les traitements ETL de l'entreprise. Nous demandons "
                   "5 ans d'experience.") == FERMEE))

    # 3. "master dossiers" est un document pharmaceutique.
    tests.append(check(
        "master dossiers : un document, pas un diplome",
        verdict_de("Assurance qualite. Vous preparez les dossiers de lots "
                   "vierges (master dossiers et instructions de "
                   "fabrication).") != FERMEE))

    # 4. Le champ disciplinaire doit suivre le diplome.
    tests.append(check(
        "Aucun diplome cite : le titre du poste n'en fait pas une exigence",
        verdict_de("Talent Pool - Capillary Electrophoresis. Rejoignez notre "
                   "vivier de talents en electrophorese capillaire pour nos "
                   "futurs postes en laboratoire.") != FERMEE))
    tests.append(check(
        "Le domaine reste extrait quand il suit vraiment le diplome",
        verdict_de("Vous etes titulaire d'un bachelier ou d'un master en "
                   "informatique de gestion.") == FERMEE))
    tests.append(check(
        "Bachelier accepte sans domaine precise : plus une barriere",
        verdict_de("Vous disposez d'un bachelier ou d'un master, orientation "
                   "scientifique.") != FERMEE))

    print()
    print("N. COMPETENCES MANQUANTES — L'EXPRESSION, PAS SON PREMIER MOT")
    print("-" * 92)
    # L'ancienne version ne cherchait que le premier mot de chaque terme.
    # « culture cellulaire » devenait « culture », et 407 offres ouvertes
    # portaient un faux manque — 10 % d'entre elles. Un faux manque fait
    # douter d'une offre accessible ; ces cas verrouillent les deux sens.
    def manques_de(texte):
        return sorted(evaluer_competences(dessaccentuer(texte))[1])

    for etiquette, texte in (
        ("culture d'entreprise", "Vous rejoignez une culture d'entreprise."),
        ("culture qualite", "Nous cultivons une culture de la qualite."),
        ("tableau de bord", "Vous produisez des tableaux de bord mensuels."),
        ("societe agreee", "Notre societe agreee vous accueille."),
        ("experience banale", "Une belle experience professionnelle vous attend."),
        ("GC dans une reference", "Reference produit GC-4471 en stock."),
    ):
        tests.append(check(f"Aucun faux manque : {etiquette}",
                           manques_de(texte) == [], str(manques_de(texte))))

    for etiquette, texte, attendu in (
        ("culture cellulaire", "Experience en culture cellulaire exigee.",
         "culture cellulaire"),
        ("HACCP", "Connaissance HACCP requise.", "HACCP"),
        ("brevet cariste", "Brevet cariste obligatoire.", "brevet cariste"),
        ("GC-MS qualifie", "Analyses par GC-MS au laboratoire.", "GC"),
        ("Tableau qualifie", "Maitrise de Tableau Desktop et Power BI.",
         "Tableau"),
        ("visa technologue", "Visa de technologue de laboratoire medical exige.",
         "technologue"),
    ):
        trouve = manques_de(texte)
        tests.append(check(f"Manque reel detecte : {etiquette}",
                           any(attendu.lower() in m.lower() for m in trouve),
                           str(trouve)))

    # PL/SQL n'est pas « PL » et « SQL » : SQL est une competence POSSEDEE,
    # et ce seul faux decoupage produisait 123 faux manques.
    tests.append(check(
        "SQL seul n'est jamais un manque",
        manques_de("Maitrise de SQL et Power BI exigee.") == []))
    tests.append(check(
        "Mais PL/SQL en est un",
        any("PL/SQL" in m for m in
            manques_de("Developpement PL/SQL sous Oracle."))))

    print()
    print("O. TROIS FAUX POSITIFS REVELES PAR L'AFFICHAGE DES PREUVES")
    print("-" * 92)
    # Ces trois-la n'ont pas ete trouves en relisant du code, mais en lisant
    # a l'ecran la phrase que le moteur citait pour justifier sa barriere.
    # Aucun n'aurait ete visible avec un verdict sans preuve.

    # 1. « Master Program Madrid », dans un bloc « autres offres ».
    tests.append(check(
        "« Master Program » est un intitule, pas un diplome",
        verdict_de("QC Analyst Life Sciences. EMC Engineer Aerospace M/F "
                   "OPERATIONS Master Program Madrid 14/06/2026 Privacy "
                   "policy.") != FERMEE))

    # 2. « baccalaureat » : le mot qu'emploient beaucoup d'annonces belges
    #    pour le bachelier. Il manquait a la liste des diplomes acceptes.
    tests.append(check(
        "« au minimum baccalaureat ou Master » accepte votre niveau",
        verdict_de("Qualifications requises : Diplome au minimum baccalaureat "
                   "ou Master avec orientation scientifique.") != FERMEE))
    tests.append(check(
        "« baccalaureaat of master » aussi",
        verdict_de("Je hebt een baccalaureaat of master in een "
                   "wetenschappelijke richting.") != FERMEE))

    # 3. « Bilingue francais - allemand » n'est pas du bilinguisme FR/NL.
    #    Le verdict pouvait rester juste par accident ; le motif affiche
    #    etait faux, et c'est le motif que l'utilisateur lit.
    motifs_allemand = [
        c.message for c in evaluer(
            "Bilingue francais - allemand pour les echanges avec les clients."
            + BOURRAGE).barrieres]
    tests.append(check(
        "Aucun motif « FR/NL » sur une offre francais-allemand",
        not any("FR/NL" in m for m in motifs_allemand),
        str(motifs_allemand)))
    tests.append(check(
        "Ni sur francais-anglais",
        not any("FR/NL" in c.message for c in evaluer(
            "Bilingue francais-anglais souhaite." + BOURRAGE).barrieres)))

    # Mais le vrai bilinguisme FR/NL reste une barriere.
    for etiquette, texte in (
        ("bilingue francais/neerlandais",
         "Vous etes bilingue francais/neerlandais pour ce poste de contact."),
        ("tweetalig NL/FR", "Tweetalig NL/FR is een must voor deze functie."),
    ):
        tests.append(check(
            f"Vrai bilinguisme FR/NL toujours bloquant : {etiquette}",
            verdict_de(texte) == FERMEE))

    print()
    print("J. STABILITE")
    print("-" * 92)
    tests.append(check("Texte vide : INCONNU, pas d'exception",
                       evaluer("").verdict == INCONNU))
    tests.append(check("None accepte sans planter",
                       evaluer(None).verdict == INCONNU))
    tests.append(check("Le resume est lisible",
                       "—" in evaluer(
                           "Vous etes titulaire d'un Master." + BOURRAGE
                       ).resume()))
    tests.append(check("Version au moins 1.2",
                       at_least(VERDICT_VERSION, "1.2"), VERDICT_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"verdict_v1_audit_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "verdict_version": VERDICT_VERSION,
                    "passed": passed, "total": total},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if passed != total:
        raise SystemExit("[FAIL] MOTEUR DE VERDICT NON VALIDE.")
    print("[PASS] MOTEUR DE VERDICT VALIDE HORS LIGNE.")


if __name__ == "__main__":
    main()
