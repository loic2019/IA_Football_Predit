# DEPLOYMENT.md — Mettre CongoBet AI en ligne

## Ce qui a été préparé (aucun impact sur ton usage local actuel)

- `Dockerfile` — construit une image du backend FastAPI
- `.dockerignore` — évite d'embarquer `.venv`, `frontend`, les gros dossiers de données
- `.env.example` (racine, backend) — toutes les variables d'environnement possibles
- `frontend/.env.example` — variable d'environnement du frontend
- CORS configurable via `ALLOWED_ORIGINS` (défaut : localhost, rien à changer en local)
- Clé football-data.org configurable via `FOOTBALL_DATA_API_KEY` (défaut conservé)

## Étapes pour déployer

1. **Backend** : choisis un hébergeur qui supporte Docker et tourne en continu (Railway, Render, ou un VPS classique type Hetzner/DigitalOcean — évite le "serverless" pur, ton pipeline ML est trop lourd/long pour ça).
   ```bash
   docker build -t congobet-api .
   docker run -p 8000:8000 --env-file .env congobet-api
   ```
   Configure les variables d'environnement (voir `.env.example`) dans les réglages de ton hébergeur.

2. **Le scraper automatique** doit tourner **sur ce même serveur**, pas sur ton PC. Le plus simple : lance `auto_cycle_worker.py` comme un second process sur le serveur (la plupart des hébergeurs permettent plusieurs "services"/process dans un même projet), ou intègre son appel dans le Dockerfile via un script de démarrage.

3. **Frontend** : déploie le dossier `frontend/` sur Vercel (le plus simple pour Next.js, gratuit pour un usage perso) :
   ```bash
   cd frontend
   npx vercel
   ```
   Configure `NEXT_PUBLIC_API_URL` dans les réglages Vercel pour pointer vers ton API en ligne (ex: `https://api.tondomaine.com`).

4. **CORS** : une fois ton frontend en ligne, ajoute son URL dans la variable `ALLOWED_ORIGINS` du backend.

5. **Firebase** : dans la console Firebase → Authentication → Settings → Authorized domains, ajoute ton nom de domaine en ligne.

6. **Secrets** : ne mets JAMAIS `.streamlit/secrets.toml` ni `.env` dans un dépôt Git public — ils sont déjà dans `.gitignore`/`.dockerignore`.

## Ce qui ne change PAS

Tout ce qui tourne en local aujourd'hui (Streamlit, `start_all.bat`, la tâche planifiée Windows) continue de fonctionner exactement pareil — ces changements sont additifs, pas des remplacements.
