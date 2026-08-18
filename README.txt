SMARTRECRUITERS V1.1
====================

REMPLACE
-------
sources/smartrecruiters.py

AJOUTE
------
diagnostics/smartrecruiters_v11_audit.py

NE CHANGE PAS
-------------
config/smartrecruiters_sources.py
main.py
Matcher
Gate
Queue
DB

POURQUOI V1.1 ?
---------------
Le test V1.0 a parfaitement validé l'API :
- SGS : 54 offres Belgique
- Eurofins : 41
- Sopra Steria : 125
- 30/30 détails récupérés sur le test
- 0 erreur

Mais companyDescription contaminait le Matcher :
Real Estate / HR / KYC / Security pouvaient devenir faussement pertinents
simplement parce que le texte corporate parlait de pharma, labo, data, etc.

V1.1 :
- description = uniquement contenu du POSTE
- company_description = texte corporate conservé séparément

TEST 1
------
python -m diagnostics.smartrecruiters_v11_audit --synthetic-only

Attendu :
Tests synthétiques : 7/7
✅ SMARTRECRUITERS V1.1 VALIDÉ SUR LE DIAGNOSTIC SYNTHÉTIQUE.

TEST 2
------
python -m diagnostics.smartrecruiters_v11_audit --limit-per-company 10

Envoyer :
exports/logs/smartrecruiters_v11_audit_*.txt
exports/logs/smartrecruiters_v11_audit_*.json

Si le bruit baisse correctement, lancer ensuite le test complet :
python -m diagnostics.smartrecruiters_v11_audit

main.py ne sera modifié qu'après validation du run complet.
