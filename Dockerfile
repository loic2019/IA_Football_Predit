# Dockerfile — Backend FastAPI (CongoBet AI)
# ==============================================================================
# Construit une image contenant ton API + tout le pipeline Python existant
# (scrapers, modèles ML, chatbot...). Le frontend Next.js se déploie
# séparément (voir frontend/README ou Vercel — pas besoin de Docker pour lui).
#
# Construire :   docker build -t congobet-api .
# Lancer :       docker run -p 8000:8000 --env-file .env congobet-api
# ==============================================================================

FROM python:3.11-slim

WORKDIR /app

# Dépendances système nécessaires à certains packages Python (catboost,
# lightgbm, playwright si jamais utilisé côté serveur pour le scraping)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
