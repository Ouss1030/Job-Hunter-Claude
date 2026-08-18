# Mettre Job Hunter sur GitHub — guide débutant Windows

## Option recommandée : GitHub Desktop

C'est la méthode la plus simple si tu n'as jamais utilisé Git.

### 1. Créer un compte GitHub

Va sur GitHub et crée ton compte si tu n'en as pas encore un.

### 2. Installer GitHub Desktop

Installe **GitHub Desktop**, puis connecte-toi avec ton compte GitHub.

### 3. Copier les fichiers de ce Starter Pack

Place à la racine de :

```text
C:\Users\Aharr\Desktop\Job Hunter
```

les fichiers :

```text
.gitignore
README.md
```

Le fichier `.gitignore` est CRITIQUE : il empêche notamment de publier la base locale,
les logs, les CV, les lettres, les fichiers générés et les secrets.

### 4. Ajouter le projet dans GitHub Desktop

Dans GitHub Desktop :

```text
File
→ Add local repository
```

Sélectionne :

```text
C:\Users\Aharr\Desktop\Job Hunter
```

Si GitHub Desktop indique que le dossier n'est pas encore un dépôt Git,
choisis l'option permettant de **Create a repository here**.

### 5. Premier commit

Dans GitHub Desktop, regarde la liste des fichiers qui vont être inclus.

Tu ne dois PAS voir notamment :

```text
database/jobs.db
.venv/
exports/logs/
exports/applications/
CV_....pdf
CV_....docx
.env
config/profile.py
```

Si un de ces fichiers apparaît, NE PUBLIE PAS encore.

Dans le champ Summary, écris par exemple :

```text
Initial Job Hunter Belgium project
```

Puis clique :

```text
Commit to main
```

### 6. Publier sur GitHub

Clique :

```text
Publish repository
```

Nom conseillé :

```text
job-hunter-belgium
```

Description possible :

```text
Belgian job collection, matching, deduplication and application prioritization pipeline
```

IMPORTANT :

```text
✓ Keep this code private
```

doit rester coché pour le premier envoi.

Puis clique :

```text
Publish Repository
```

Ton projet est maintenant sauvegardé sur GitHub.

---

# Après chaque modification

Tu n'as pas besoin d'apprendre toutes les commandes Git.

Dans GitHub Desktop :

1. tu modifies tes fichiers normalement ;
2. GitHub Desktop affiche automatiquement les changements ;
3. écris un petit résumé, par exemple :

```text
Add SmartRecruiters V1.1
```

4. clique `Commit to main` ;
5. clique `Push origin`.

C'est tout.

---

# Les 4 mots à connaître

## Repository

Le projet GitHub.

## Commit

Un point de sauvegarde de ton code.

## Push

Envoie tes nouveaux commits de ton PC vers GitHub.

## Pull

Récupère sur ton PC les changements présents sur GitHub.

---

# Alternative PowerShell

Si plus tard tu veux utiliser Git directement :

```powershell
cd "C:\Users\Aharr\Desktop\Job Hunter"
git init
git add .gitignore README.md
git add applications config database diagnostics matching sources main.py
git status
git commit -m "Initial Job Hunter Belgium project"
git branch -M main
```

Ensuite, après avoir créé un dépôt VIDE `job-hunter-belgium` sur GitHub :

```powershell
git remote add origin https://github.com/TON-USERNAME/job-hunter-belgium.git
git push -u origin main
```

Avant le premier `git add`, vérifie toujours le `.gitignore`.

---

# Avant de rendre le dépôt public

Un dépôt privé pourra être transformé en portfolio plus tard.

Avant cela, il faudra :

- retirer toutes les données personnelles ;
- créer un `config/profile.example.py` fictif ;
- vérifier l'historique Git pour s'assurer qu'aucun secret n'a été commité ;
- éventuellement créer une petite base de démonstration anonymisée ;
- améliorer le README ;
- ajouter une architecture / captures d'écran / exemples de sortie anonymisés.

Ne rends pas le dépôt public immédiatement avec les données actuelles.
