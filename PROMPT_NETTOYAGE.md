# Prompt à transmettre — script de nettoyage

À envoyer avec `INVENTAIRE_ESSENTIEL_ET_SUPPRIMABLE.md` en pièce jointe.

---

## Le prompt

```
CONTEXTE

Le projet JobHunter (C:\Users\Aharr\Desktop\JobHunter) a accumulé beaucoup de
fichiers à usage unique. Un inventaire joint
(INVENTAIRE_ESSENTIEL_ET_SUPPRIMABLE.md) a établi par analyse du graphe
d'appels :

    572 modules Python au total
    153 essentiels
    419 non essentiels

    racine : 94 scripts .py, dont 3 seulement sont vivants
    racine : 227 fichiers .bat, dont 3 seulement lancent l'application
    racine : 197 fichiers .md
    diagnostics/ : 316 fichiers, dont 25 dans SUITE_ACTIVE

Environ 650 fichiers peuvent partir. Je veux un outil qui le fasse
proprement, pas une suppression manuelle.

OBJECTIF

Écris un script Python unique, database/cleanup_workspace.py, qui identifie
et met en quarantaine les fichiers inutiles, par lots, de façon entièrement
réversible.


CONTRAINTE DE SÉCURITÉ N°1 — LE PIÈGE DES SOUS-PROCESSUS

N'écris PAS un script qui décide par analyse d'imports seule. Ce serait faux.

daily_run.py lance ses étapes en sous-processus :

    subprocess.Popen([... "-m", "applications.application_preparation" ...])

Ce ne sont pas des `import`. Une analyse d'imports classique conclurait que
applications/application_preparation.py est mort, et le supprimerait. C'est le
cœur du pipeline.

Ton script doit donc chercher les références sous TROIS formes :

    1. les imports (ast)
    2. les chaînes de caractères désignant un module ("applications.xxx",
       "diagnostics.yyy") — y compris avec un suffixe ":VERSION"
    3. les mentions dans les fichiers .bat

Un fichier n'est candidat que s'il n'est trouvé sous AUCUNE des trois formes.


CONTRAINTE DE SÉCURITÉ N°2 — LISTE PROTÉGÉE EN DUR

Le script doit contenir une liste protégée, testée AVANT toute autre règle.
Un fichier protégé n'est jamais candidat, quelle que soit l'analyse.

PROTÉGÉ — dossiers entiers :
    applications/     interface/     matching/     database/
    config/           sources/       logs/         exports/
    backups/          .git/          .venv/

PROTÉGÉ — fichiers racine :
    main.py           daily_run.py          jobhunter_ui.py
    START_JOBHUNTER.bat   RESUME_DAILY_RUN.bat   TEST_DAILY_RUN.bat
    README.md         .gitignore            requirements*.txt

PROTÉGÉ — diagnostics :
    run_all.py
    + les 25 modules listés dans SUITE_ACTIVE de run_all.py, lus dynamiquement
      (ne pas les recopier en dur, les extraire du fichier)
    + tout module importé par l'un d'eux

PROTÉGÉ — données, jamais touchées :
    database/jobs.db          (n'est PAS dans git, irremplaçable)
    logs/                     (6 680 fichiers de cache, coûteux à reconstruire)
    exports/logs/             (1 439 rapports, seul historique de mesure)

Note : ai_document_generator.py n'est appelé par aucun module du runtime, mais
ai_document_generator_v1_audit (dans SUITE_ACTIVE) le teste. La règle « importé
par un audit actif » doit donc le protéger automatiquement.


MÉCANISME — QUARANTAINE, PAS SUPPRESSION

Ne supprime rien. Déplace vers un dossier daté en conservant l'arborescence :

    _quarantaine_20260904_HHMMSS/
        diagnostics/mega_batch5_10_recover4_specific.py
        upgrade_v39_batch2_4_registry.py
        README_SCIENSANO_V350.md
        ...
        MANIFESTE.json          ← chemin d'origine de chaque fichier

Avantages : réversible sans git, inspectable, et un simple script de
restauration suffit si un test casse.

Prévois donc DEUX modes :

    python database/cleanup_workspace.py --lot 1 --dry-run    (défaut)
    python database/cleanup_workspace.py --lot 1 --apply
    python database/cleanup_workspace.py --restaurer _quarantaine_20260904_143000


LES LOTS, DANS CET ORDRE

LOT 1 — certitude totale (124 fichiers)
    a) Dossiers de transit, avec tout leur contenu :
       _payload/  payload/  _patch_payload/  _step9_1_payload/
       _jobat_circuit_v1_payload/  _jobat_cookie_once_v1_payload/
       hardening_files/  hardening_step2_files/  hardening_step4b_files/
       hardening_step6b_files/  hardening_step7_files/
       lifecycle_step8f_b_files/

    b) Doublons versionnés dans applications/ — leur contenu est déjà fusionné
       dans le fichier de base. Le script doit LE VÉRIFIER avant de déplacer :
       lire la version déclarée dans le fichier de base et confirmer qu'elle est
       >= celle du doublon.

           application_preparation_v11.py   base = 1.1  ✓
           application_recheck_v11.py       base = 1.1  ✓
           delta_tracker_v11.py             base = 1.1  ✓
           final_application_pool_v12.py    base = 1.2  ✓
           job_refresh_v11.py               base = 1.2  ✓
           job_refresh_v12.py               base = 1.2  ✓

LOT 2 — migrations racine (75 fichiers)
    upgrade_*.py  install_*.py  apply_*.py  rollback_*.py  patch_*.py
    daily_run_v1*_candidate.py

    Déplace aussi le .bat et le README du même nom de base : ils forment un lot.

LOT 3 — scripts d'étape racine (16 fichiers)
    lifecycle_step8*.py  lifecycle.py
    main_smartrecruiters_shadow*.py  diagnose_jobat_prov.py
    export_full_performance_audit_v1.py  Resume_pour_gemini.py

LOT 4 — runners one-shot dans diagnostics/ (~90 fichiers)
    Motifs : mega_batch*  batch*_integrate*  run_batch*  install_*  upgrade_*
             validate_*  rollback_*
    Ce ne sont pas des diagnostics, ce sont des scripts de migration rangés
    dans le mauvais dossier.

LOT 5 — audits déclarés obsolètes : NE PAS SUPPRIMER

    ATTENTION — piège vérifié en conditions réelles.

    run_all.py contient un dictionnaire REPLACED associant chaque audit périmé
    à son successeur. Il est tentant de supprimer les clés. NE LE FAIS PAS.

    Testé : déplacer les 13 audits REPLACED d'un projet équivalent a cassé
    run_all immédiatement —

        [FAIL] Classification incomplète. Aucun diagnostic n'a été lancé.

    run_all vérifie que chaque nom cité dans ses listes de classification
    existe sur disque. La déclaration « remplacé » crée donc une dépendance :
    l'audit est obsolète pour l'exécution, mais son FICHIER reste requis par
    l'inventaire.

    Deux options, au choix, mais jamais la suppression seule :
      a) les laisser en place — ils ne coûtent presque rien ;
      b) les supprimer ET retirer leurs entrées du dictionnaire REPLACED dans
         le même geste, puis relancer run_all pour confirmer.

    C'est le meilleur exemple de la règle générale : ce qui paraît mort peut
    être requis par un inventaire. Toujours vérifier en exécutant.

LOT 6 — fichiers .bat (224 sur 227)
    Tous sauf les trois lanceurs protégés.

LOT 7 — README versionnés (97 sur 197)
    Motif README_*_V<numéro>.md quand une version supérieure du même composant
    existe. Garde toujours la plus récente de chaque famille.
    Exemple : README_SCIENSANO_V350/351/352/353/3531/354 → ne garder que V354.

LOT 8 — orphelins des dossiers du noyau — UN PAR UN, PAS EN LOT
    config/funnel_recall.py
    config/source_scout_targets.py  _batch2  _batch3
    database/activity.py  database/intrasource_audit.py
    matching/application_gate_v13_overlay.py
    sources/actiris_provenance.py  *_shadow.py  *_diagnostic.py
    sources/batch3_3_engine.py

    ATTENTION : config/source_scout_targets*.py contient probablement des listes
    d'employeurs cibles — de la connaissance métier, pas du code mort. Le script
    doit les SIGNALER, pas les déplacer. Je déciderai après lecture.


PROTOCOLE D'EXÉCUTION

Le script doit imposer cet ordre et le rappeler à chaque exécution :

    0. git add -A && git commit -m "Etat avant nettoyage"
       (4 commits seulement et 5 449 fichiers non commités aujourd'hui : sans
        ce commit, rien n'est réversible par git)

    1. --lot 1 --dry-run   puis   --lot 1 --apply
    2. python daily_run.py --check          doit rester vert
    3. python -m diagnostics.run_all        doit rester vert
    4. lot suivant

Si une vérification échoue, restaurer le dernier lot et s'arrêter.


CE QUE LE SCRIPT DOIT AFFICHER

En dry-run, pour chaque lot :

    LOT 2 — migrations racine
    ------------------------------------------------------------
    CANDIDAT   upgrade_v39_batch2_4_registry.py       0 référence
    CANDIDAT   RUN_BATCH2_4.bat                       lot associé
    PROTÉGÉ    main.py                                liste protégée
    GARDÉ      upgrade_something.py                   référencé par daily_run.py

    Candidats : 75    Protégés : 3    Gardés (référencés) : 2
    Taille totale : 1,2 Mo

Et un fichier de rapport horodaté dans exports/logs/diagnostics/.


LIVRAISON ATTENDUE

    1. database/cleanup_workspace.py
    2. Un audit diagnostics/cleanup_workspace_audit.py qui vérifie sur des
       fichiers factices, en dossier temporaire :
         - qu'un fichier protégé n'est jamais candidat
         - qu'un module référencé uniquement par une chaîne "applications.xxx"
           n'est PAS candidat  ← le test qui compte le plus
         - qu'un module cité seulement dans un .bat n'est PAS candidat
         - que la restauration remet chaque fichier à son chemin d'origine
    3. Le résultat du dry-run des 8 lots, sans rien appliquer.

Ne lance aucun --apply toi-même. Je veux voir le dry-run complet d'abord.


RÈGLE GÉNÉRALE

Compiler n'est pas tester. Un script de suppression qui compile parfaitement
peut effacer le cœur du pipeline. Le seul garde-fou qui vaut est l'audit du
point 2, en particulier le test sur les références par chaîne de caractères.
```

---

## Pourquoi le prompt est écrit comme ça

**La quarantaine plutôt que la suppression.** Un dossier daté qui conserve
l'arborescence et un manifeste rend l'opération réversible sans dépendre de git
— ce qui compte, puisque git n'a que 4 commits et 5 449 fichiers non commités.

**Le piège des sous-processus est mis en premier.** C'est l'erreur qui
détruirait le projet : une analyse d'imports seule conclut que
`applications/application_preparation.py` est mort. Le prompt l'annonce avant
toute autre consigne, et l'audit demandé le teste explicitement.

**La liste protégée est testée avant l'analyse**, pas après. Une règle qui
protège ne doit jamais dépendre d'un calcul qui peut se tromper.

**Le lot 8 signale au lieu de déplacer.** `config/source_scout_targets*.py`
ressemble à du code mort mais contient probablement des listes d'employeurs
cibles — du travail de recherche, pas du code. C'est à lire avant de jeter.

**Le dry-run complet est demandé avant tout `--apply`.** Cela vous laisse voir
les 650 fichiers proposés avant qu'un seul ne bouge.
