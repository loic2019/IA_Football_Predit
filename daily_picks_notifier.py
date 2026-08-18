# -*- coding: utf-8 -*-
"""
daily_picks_notifier.py — Notification des pronostics du jour les plus surs
================================================================================
IMPORTANT — POURQUOI IL N'Y A JAMAIS DE "100%" ICI
------------------------------------------------------------------------------
Aucun modèle statistique de football (Poisson, Dixon-Coles, XGBoost, réseau de
neurones...) ne peut garantir un résultat à 100%. Un match de football garde
toujours une part d'aléa (blessure de dernière minute, erreur d'arbitrage,
carton rouge précoce...). Afficher "100% de confiance" à des utilisateurs qui
peuvent ensuite miser de l'argent réel sur cette base serait trompeur et
pourrait leur causer un préjudice financier réel — c'est pour cette raison que
ce module :
  1. Affiche toujours le VRAI pourcentage calculé par le modèle (jamais 100%,
     jamais arrondi vers le haut au-delà de ce qui est mesuré) ;
  2. Plafonne l'affichage à 95% même si le calcul brut dépasse ce seuil, pour
     ne jamais donner une impression de certitude absolue ;
  3. Ajoute systématiquement un rappel "aucun pronostic n'est garanti" dans
     le message envoyé.

Ce module s'appuie sur l'infrastructure de notifications déjà présente dans
community_db.py (create_notification) — il ne crée pas de nouveau système,
il vient simplement générer, une fois par jour, une notification globale
récapitulative des meilleures sélections du jour.
"""

from datetime import datetime, date

import community_db

DISCLAIMER = "⚠️ Aucun pronostic n'est garanti : ceci reflète le niveau de confiance du modèle, pas une certitude."
DISPLAY_CAP = 0.95  # jamais afficher plus que ça, même si le calcul brut est supérieur
MIN_CONFIDENCE_FOR_ALERT = 0.75  # seuil pour qu'un pick soit jugé "à confiance élevée"
MAX_PICKS_IN_NOTIFICATION = 5


def _display_confidence(raw_confidence: float) -> float:
    """Confiance réelle, plafonnée pour ne jamais laisser croire à une certitude absolue."""
    return min(float(raw_confidence), DISPLAY_CAP)


def build_daily_digest(predictions: list[dict]) -> dict | None:
    """
    À partir de la liste de prédictions du jour (issues de predictor.predict_all),
    construit le contenu d'une notification récapitulative honnête, ou None si
    aucun pick n'atteint le seuil de confiance.
    """
    eligible = [p for p in predictions if p.get("confidence", 0) >= MIN_CONFIDENCE_FOR_ALERT]
    if not eligible:
        return None

    eligible.sort(key=lambda p: p["confidence"], reverse=True)
    top_picks = eligible[:MAX_PICKS_IN_NOTIFICATION]

    lines = []
    for p in top_picks:
        conf = _display_confidence(p["confidence"])
        pick_label = {"1": "victoire domicile", "X": "match nul", "2": "victoire extérieur"}.get(
            p.get("prediction", ""), p.get("prediction", "")
        )
        lines.append(f"• {p.get('home','?')} vs {p.get('away','?')} — {pick_label} (confiance {conf:.0%})")

    message = "\n".join(lines) + "\n\n" + DISCLAIMER
    title = f"📊 Pronostics à confiance élevée du {date.today().strftime('%d/%m/%Y')}"

    return {"title": title, "message": message, "picks": top_picks}


def notify_daily_high_confidence_picks(prediction_snapshot: dict) -> dict:
    """
    Appelé une fois par cycle (voir common.run_auto_cycle) : génère au plus une
    notification globale par jour (pas de spam à chaque cycle de scraping).
    """
    predictions = prediction_snapshot.get("predictions", [])
    digest = build_daily_digest(predictions)
    if digest is None:
        return {"sent": False, "reason": "no_pick_above_threshold"}

    # Anti-spam : une seule notification "digest" par jour calendaire.
    today_key = date.today().isoformat()
    existing = community_db.list_notifications(user_id=0, limit=30)  # user_id=0 : on ne filtre que sur le contenu global
    for n in existing:
        if n.get("type") == "daily_digest" and n.get("created_at", "").startswith(today_key):
            return {"sent": False, "reason": "already_sent_today"}

    community_db.create_notification(
        user_id=None,  # notification globale, visible par tous les utilisateurs connectés
        type="daily_digest",
        title=digest["title"],
        message=digest["message"],
        link_page="Pronostics",
    )
    return {"sent": True, "picks_count": len(digest["picks"])}
