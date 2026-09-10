JobHunter UI V1.2.1 - correctif du lanceur Windows

Ce patch ne modifie ni le pipeline ni l'interface V1.2.
Il remplace uniquement START_JOBHUNTER.bat.

Ce lanceur :
- ne se ferme plus silencieusement en cas d'erreur ;
- teste Python et Streamlit ;
- verifie le code de l'interface ;
- detecte si le port 8501 est deja utilise ;
- ouvre l'instance existante si un serveur ecoute deja sur 8501 ;
- ecrit le diagnostic dans exports\logs\ui\startup_ui.log.

Installation :
1. Fermer JobHunter si possible.
2. Copier START_JOBHUNTER.bat dans C:\Users\Aharr\Desktop\JobHunter
3. Accepter le remplacement.
4. Double-cliquer sur START_JOBHUNTER.bat.
