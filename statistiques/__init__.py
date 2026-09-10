"""
JOB HUNTER BELGIUM
STATISTIQUES - VERSION 1.0

Tout ce que le projet mesurait jusqu'ici etait operationnel : le run s'est-il
bien passe, quelle source a rendu combien de lignes, quelle etape a pris
combien de secondes. Utile pour reparer la machine, inutile pour decider.

Ce paquet mesure autre chose : ce que les offres collectees disent du marche,
ou le tri perd des offres d'un run a l'autre, et ce que deviennent les
candidatures une fois envoyees.

Trois modules, trois questions
------------------------------
    marche        Que demande le marche belge pour ce profil, et que
                  faudrait-il apprendre pour ouvrir le plus de portes ?

    pipeline      Ou les offres se perdent-elles, run apres run, et la
                  situation s'ameliore-t-elle ou se degrade-t-elle ?

    candidatures  Que deviennent les candidatures envoyees : delais,
                  taux de reponse, par source et par filiere ?

Une precaution de lecture
-------------------------
« Mentionne dans N offres » n'est pas « exige par N offres ». Ces mesures
comptent des occurrences dans du texte, pas des exigences formelles. Le
nommer evite de transformer un comptage en certitude — un piege dans lequel
ce projet est deja tombe : le compteur de competences manquantes, avant
d'etre repare le 10 septembre 2026, annoncait 407 offres demandant la
« culture cellulaire » alors qu'il comptait des « culture d'entreprise ».

Lecture seule : aucun module d'ici n'ecrit en base.
"""

from __future__ import annotations

STATISTIQUES_VERSION = "1.0"

__all__ = ["STATISTIQUES_VERSION"]
