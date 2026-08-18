# CongoBet AI — À copier dans ton projet existant

Tout est dans **un seul dossier**, prêt au copier-coller dans ton
installation actuelle (celle qui a déjà le venv créé).

## Ce que tu copies, et où

```
TonProjet/                     ← ton dossier existant (Scrapper_2)
├── common.py                  ← déjà là, INCHANGÉ
├── auth_firebase.py           ← déjà là, INCHANGÉ
├── pronostics.py               ← déjà là, INCHANGÉ
├── admin_config.py            ← déjà là, INCHANGÉ
├── statistiques.py            ← déjà là, INCHANGÉ
├── ... (tout le reste, inchangé)
│
├── api/                       ← 🆕 COPIE CE DOSSIER ICI (à la racine)
│   ├── main.py
│   ├── core/
│   ├── routes/
│   ├── services/
│   └── schemas/
│
└── frontend/                  ← 🆕 COPIE CE DOSSIER ICI (à la racine)
    ├── app/
    ├── components/
    └── lib/
```

Concrètement : dézippe l'archive, puis fais glisser `api/` et
`frontend/` à la racine de ton dossier `Scrapper_2` existant, à côté de
`common.py`. Rien d'autre à toucher — aucun de tes fichiers actuels
n'est modifié.

## Démarrer (ton venv existant)

```bash
cd TonProjet
source .venv/bin/activate        # ton venv déjà créé — inchangé
pip install -r api/requirements.txt   # ajoute juste FastAPI + JWT à ton venv existant
cp api/.env.example api/.env          # renseigne un JWT_SECRET aléatoire dedans
uvicorn api.main:app --reload --port 8000
```
→ teste http://localhost:8000/health

```bash
# Dans un second terminal, toujours depuis TonProjet
cd frontend
npm install
cp .env.example .env.local       # API_URL=http://localhost:8000
npm run dev
```
→ ouvre http://localhost:3000

## Pourquoi ça marche directement avec tes vraies données
`api/services/*.py` fait `import common`, `import auth_firebase`,
`from admin_config import ADMIN_EMAILS`, etc. — des imports directs,
sans wrapper. Comme `api/` est à la racine de ton projet (donc dans le
même `sys.path` que tes modules), Python les trouve tout de suite. Tes
`.db`, `firebase_config.py`, `.streamlit/secrets.toml` restent utilisés
tels quels, aucune configuration à dupliquer.

## Modules déjà branchés
`auth`, `dashboard` (matchs live/futurs, stats modèles), `predictions`
(pronostics + coupon ≥ 1.30 + combos), `stats` (statistiques
détaillées), `palmares` (tickets publics + série + évolution), `admin`
(scrapers). Voir `ARCHITECTURE.md` pour le détail et la suite (historique,
communauté, profil, chatbot, notifications temps réel).

## À vérifier chez toi
Je n'ai pas pu réellement exécuter ce code (pas d'accès réseau dans mon
environnement pour installer tes dépendances). J'ai vérifié :
- la syntaxe Python de tout `api/` (`py_compile`, aucune erreur) ;
- la syntaxe/structure TypeScript de tout `frontend/` (`tsc`, aucune
  erreur réelle — seules des erreurs "module introuvable" attendues tant
  que `npm install` n'a pas tourné).
Donc structurellement sain, mais le premier `uvicorn` + `npm run dev`
chez toi est le vrai test. Si une erreur d'import apparaît (ex. nom de
fonction différent de ce que j'ai supposé dans `services/`), dis-moi le
message exact et je corrige immédiatement.
