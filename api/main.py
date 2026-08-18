# -*- coding: utf-8 -*-
"""
api/main.py — Backend FastAPI pour le nouveau frontend Next.js.
================================================================================
Ce fichier ne contient AUCUNE logique métier : il expose ton code Python
existant (common.py, predictor.py, coupon_tracker.py, community_db.py,
auth_firebase.py...) tel quel, via des routes REST. Zéro duplication.

Lancement (depuis la racine du projet, à côté de app_dashboard.py) :
    uvicorn api.main:app --reload --port 8000

Le frontend Next.js (voir /frontend) appelle cette API sur http://localhost:8000.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import auth, dashboard, predictions, coupons, history, stats, palmares, challenge, public, profile, system

app = FastAPI(title="CongoBet AI API", version="1.0.0")

# CORS : autorise le(s) frontend(s) à appeler cette API.
# Local (défaut) : http://localhost:3000
# En ligne : définis ALLOWED_ORIGINS="https://tondomaine.com,https://www.tondomaine.com"
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(predictions.router)
app.include_router(coupons.router)
app.include_router(history.router)
app.include_router(stats.router)
app.include_router(palmares.router)
app.include_router(challenge.router)
app.include_router(public.router)
app.include_router(profile.router)
app.include_router(system.router)


@app.get("/health")
def health():
    return {"status": "ok"}
