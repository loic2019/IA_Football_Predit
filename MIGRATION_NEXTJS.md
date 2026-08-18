# CongoBet AI — Migration vers Next.js / FastAPI

## Ce qui est fait et testé

**Backend** (`api/`, dans le projet Python existant) :
- Démarré réellement avec `uvicorn`, toutes les routes vérifiées (200/401 corrects)
- `auth.py` — inscription/connexion/profil (réutilise `auth_firebase.py` + `community_db.py` tels quels)
- `dashboard.py` — résumé, métriques (réutilise `monitoring/metrics.py`), historique d'entraînement
- `predictions.py` — génère le snapshot complet (réutilise `common.run_prediction_pipeline`)
- `coupons.py` — sauvegarde, règlement, historique, diagnostic des paris en attente

**Frontend** (`frontend/`, projet Next.js séparé) :
- Next.js 16 + TypeScript + Tailwind v4 + Framer Motion — **build de production vérifiée** (compilation + TypeScript + lint, zéro erreur)
- Design system complet : palette noir/blanc/gris + un accent discret, dark/light, coins arrondis modérés, ombres douces, transitions premium, `prefers-reduced-motion` respecté
- Composants façon shadcn écrits à la main (le registre `ui.shadcn.com` n'était pas joignable depuis mon environnement) : Button, Card, Badge, Tabs, Progress, Skeleton
- Authentification Firebase (REST, miroir exact du backend), sidebar animée, page de connexion/inscription
- **2 écrans complets et fonctionnels** : Dashboard (ticker live, KPIs, jeu de calibration) et Pronostics (coupon conseillé + coupons combinés de 10 en onglets + sauvegarde)

## Démarrage

**1. Backend** (depuis la racine du projet Python, à côté de `app_dashboard.py`) :
```powershell
pip install fastapi "uvicorn[standard]"
uvicorn api.main:app --reload --port 8000
```
Vérifie sur http://localhost:8000/health → `{"status":"ok"}`

**2. Frontend** (dans le dossier `frontend/`) :
```powershell
npm install
npm run dev
```
Ouvre http://localhost:3000 → redirige vers `/login`.

**3. Premier compte** : inscris-toi via le formulaire — le profil local (`community_db`) est créé automatiquement à l'inscription.

## Ce qu'il reste à migrer (dans l'ordre suggéré)

| Écran | Complexité | Notes |
|---|---|---|
| Historique / Statistiques | Faible | Lecture seule, endpoints simples à ajouter dans `api/routers/` |
| Palmarès | Faible | Idem |
| Challenge (portefeuille virtuel) | Moyenne | Nécessite des endpoints pour `community_db.place_wallet_bet`, `place_wallet_coupon_bet`, historique |
| Communauté (messagerie) | Moyenne-haute | Nécessite du temps réel (polling ou WebSocket) pour le salon public + DM |
| Chatbot vocal | Haute | L'avatar animé + micro + TTS doivent être reconstruits en React (Web Audio API), le backend Claude/Groq peut être exposé tel quel |
| Administration | Moyenne | Protégée par `get_admin_user` (déjà prête côté backend) |

**Pattern à suivre pour chaque nouvel écran** : ajouter un router dans `api/routers/`, qui appelle tes fonctions Python existantes sans les modifier ; puis une page Next.js dans `frontend/src/app/(app)/<écran>/page.tsx` utilisant `useApiData()` + les composants UI déjà en place. Le design system et l'auth sont déjà branchés — chaque nouvel écran héritera automatiquement de la cohérence visuelle.

## Sécurité conservée
- Authentification Firebase identique (même projet, mêmes comptes)
- Rôles/permissions (`is_admin`) identiques, dépendance `get_admin_user` prête pour les routes sensibles
- Aucune logique métier dupliquée ou modifiée — l'API appelle ton code existant

## Limite connue à surveiller
`common.py` importe `streamlit` en tête de fichier — l'API fonctionne (Streamlit est dans ton environnement), mais si tu veux un jour un backend 100% indépendant de Streamlit, il faudra extraire la logique pure de `common.py` dans un module séparé (sans rien casser côté Streamlit, qui continuerait à l'importer aussi).
