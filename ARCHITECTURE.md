# CongoBet AI — Nouvelle architecture (Next.js + FastAPI)

## Principe directeur
**Zéro réécriture de logique métier.** Le dossier `(à côté, dans ton dossier projet) ` est
une copie conforme de ton projet Python actuel (Scrapper_2). L'API
FastAPI (`api/`) n'est qu'une couche de traduction HTTP ↔
fonctions Python existantes. Le frontend Next.js ne fait aucun calcul :
il affiche ce que l'API renvoie.

```
utilisateur
   │
   ▼
Next.js (React, Tailwind, shadcn/ui, Framer Motion)   ← nouvelle interface
   │  fetch /api/*  (proxy same-origin, cookie httpOnly)
   ▼
FastAPI (api/)                                ← nouvelle couche mince
   │  appelle directement
   ▼
Code métier existant ((à côté, dans ton dossier projet)  = Scrapper_2, inchangé)
   │
   ▼
SQLite / Firebase / modèles ML (inchangés)
```

## Ce qui a été construit dans ce scaffold
- **Backend** : config, sécurité JWT, dépendances d'auth/rôles, services
  (`auth_service`, `match_service`, `prediction_service`) qui enveloppent
  `auth_firebase.py`, `common.py`, `pronostics.py` sans les modifier,
  routers (`/auth`, `/dashboard`, `/predictions`, `/admin`).
- **Frontend** : layout global (thème sombre/clair via `next-themes`),
  sidebar animée, page de connexion, dashboard (cartes temps réel),
  page pronostics (coupon filtré cote ≥ 1.30 — logique déjà dans
  `common.run_prediction_pipeline`), middleware de protection des routes,
  client API centralisé.

## Sécurité — ce qui est conservé
- **Authentification** : toujours Firebase (`auth_firebase.py` inchangé) ;
  l'API échange l'id_token Firebase contre un JWT applicatif stocké en
  cookie **httpOnly** (illisible en JS, protection XSS).
- **Rôles/permissions** : `admin_config.ADMIN_EMAILS` reste la source de
  vérité ; les routes `/admin/*` sont gardées par `require_admin`.
- **Journalisation** : le logger FastAPI (`app/main.py`) est le point
  d'entrée pour brancher les logs existants (`monitoring/metrics.py`).
- **Chiffrement** : cookies `secure` + `httponly`, CORS restreint aux
  origines listées dans `Settings.CORS_ORIGINS`.

## Pourquoi FastAPI "juste comme couche d'API" et pas plus
Conformément à ta demande : FastAPI ne contient **aucune règle métier**.
Chaque endpoint fait au maximum 3 choses : valider l'entrée (Pydantic),
appeler une fonction de tes fichiers existants, sérialiser la sortie. Toute évolution
de règle (seuils de confiance, filtrage de cote, calcul ELO, etc.) se
fait toujours dans le code Python existant — jamais dans `app/`.

## Feuille de route pour couvrir 100% des fonctionnalités actuelles
Chaque page Streamlit restante suit le même pattern déjà appliqué à
`pronostics.py` (voir `backend/README.md` → "Étendre l'API"). Ordre
suggéré, du plus simple au plus dépendant :

| Phase | Module Streamlit source | Nouvel endpoint | Nouvelle page Next.js |
|---|---|---|---|
| 1 ✅ | `auth_firebase.py` | `/auth/*` | `(auth)/login` |
| 1 ✅ | `common.py` (dashboard) | `/dashboard/*` | `dashboard` |
| 1 ✅ | `pronostics.py` | `/predictions/*` | `dashboard/pronostics` |
| 2 ✅ | `statistiques.py` | `/stats` | `dashboard/statistiques` |
| 2 | `palmares.py` | `/palmares` | `dashboard/palmares` |
| 3 | `historique.py`, `coupon_tracker.py` | `/history/*` | `dashboard/historique` |
| 3 | `communaute.py`, `community_db.py` | `/community/*` | `dashboard/communaute` |
| 4 | `profil.py`, `max_avatar.py` | `/users/me*` | `dashboard/profil` |
| 4 | `admin.py`, `admin_config.py` | `/admin/*` (étendre) | `dashboard/admin` |
| 5 | `chatbot.py`, `chatbot_ai.py` | `/chat` (SSE) | composant flottant |
| 5 | `backtest_ui.py`, `backtesting/engine.py` | `/backtest` | `dashboard/backtest` |
| 6 | notifications temps réel (cloche/pop-up) | WebSocket `/ws/notifications` | provider global + toasts shadcn |

Le système de notifications déjà construit (toasts + cloche sidebar,
voir mémoire projet) se prête bien à un WebSocket FastAPI natif — chaque
événement (pronostic gagnant, ticket réglé) pousse un message que le
frontend affiche en toast animé (Framer Motion + shadcn `toast`).

## Démarrage rapide (local)
```bash
# Backend
cd backend
cp -r /chemin/vers/Scrapper_2/*    # si pas déjà fait
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # renseigner JWT_SECRET
uvicorn app.main:app --reload --port 8000

# Frontend (autre terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev
```
Puis ouvrir http://localhost:3000 — redirection auto vers `/login`.
