# -*- coding: utf-8 -*-
"""
congobet_combos.py — Analyse des tickets combinés "Top paris" de CongoBet
================================================================================
CongoBet propose sur sa page d'accueil 2-3 tickets combinés pré-construits
("Top paris" — #1, #2, #3), chacun regroupant 12 à 20 sélections avec un
bonus et une cote totale. scraper_api.py interroge déjà l'API sous-jacente
(ENDPOINTS["top_combos"]) mais aplati chaque sélection individuellement dans
la table `matches` — le regroupement par ticket (quelles sélections vont
ensemble, quel ticket est lequel) est perdu.

Ce module :
1. Réinterroge le même endpoint SANS aplatir — garde chaque ticket intact
   (sa liste de sélections, son bonus, sa cote totale).
2. Pour chaque sélection de chaque ticket, calcule NOTRE propre probabilité
   (via predictor.py) pour ce même choix précis.
3. Combine ces probabilités pour estimer la probabilité de gain de chaque
   ticket complet (produit des probas des sélections — hypothèse
   d'indépendance, approximation standard pour ce genre de combiné).
4. Classe les tickets pour recommander celui qu'on estime le plus fiable.

⚠️ Comme pour scraper_besoccer.py, ce module n'a pas pu être testé contre la
vraie réponse de l'API depuis cet environnement (pas d'accès réseau). Si le
format de réponse diffère de ce qui est anticipé ici, `fetch_top_combos()`
sauvegarde automatiquement la réponse brute dans logs/ pour ajustement.

Lancement :
    python congobet_combos.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import requests

from scraper_api import BASE_EVENT_API, HEADERS, LANG, parse_event

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"congobet_combos_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

TOP_COMBOS_URL = f"{BASE_EVENT_API}/events/sports/top-combos"


def fetch_top_combos() -> list[dict]:
    """Récupère les tickets combinés bruts (JSON) depuis l'API CongoBet."""
    try:
        resp = requests.get(TOP_COMBOS_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Erreur de récupération des top-combos : {e}")
        return []


def _save_debug_json(data) -> str:
    path = LOG_DIR / f"congobet_combos_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.warning(f"Structure de ticket inattendue — réponse brute sauvegardée dans {path}.")
    except Exception as e:
        logger.error(f"Impossible de sauvegarder le debug JSON : {e}")
    return str(path)


def parse_combo_tickets(data) -> list[dict]:
    """
    Extrait les tickets combinés en gardant leurs sélections groupées.

    Stratégie défensive (comme scraper_besoccer.py) : plusieurs formats de
    réponse possibles selon l'API, testés dans l'ordre. Si aucun ne
    correspond, la réponse brute est sauvegardée pour ajustement plutôt que
    de renvoyer silencieusement une liste vide sans explication.
    """
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("result", "combos", "items", "data"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    tickets = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue

        lines = item.get("lines") or item.get("selections") or item.get("legs") or []
        if not lines:
            continue

        legs = []
        for line in lines:
            event_obj = line.get("event") if isinstance(line.get("event"), dict) else None
            if not event_obj:
                continue
            match = parse_event(event_obj)
            if not match:
                continue

            event_bet_type = line.get("eventBetType", {}) or {}
            market_name = event_bet_type.get("name", "")
            selected_label = None
            selected_odds = None
            # La sélection précise choisie dans ce ticket est généralement
            # marquée (isSelected / selected), sinon on prend le 1er item du
            # marché comme repli.
            market_items = event_bet_type.get("eventBetTypeItems", []) or []
            for mi in market_items:
                if mi.get("isSelected") or mi.get("selected"):
                    selected_label = mi.get("name") or mi.get("shortName")
                    selected_odds = mi.get("odds")
                    break
            if selected_label is None and market_items:
                selected_label = market_items[0].get("name") or market_items[0].get("shortName")
                selected_odds = market_items[0].get("odds")

            legs.append({
                "home": match["home"], "away": match["away"], "league": match["league"],
                "market": market_name, "selection": selected_label,
                "odds": float(selected_odds) if selected_odds else None,
                "match_id": match["id"],
            })

        if not legs:
            continue

        tickets.append({
            "ticket_rank": i + 1,
            "n_selections": len(legs),
            "bonus_pct": item.get("bonusPercentage") or item.get("bonus") or 0,
            "total_cote": item.get("totalOdds") or item.get("totalCote") or None,
            "legs": legs,
        })

    if not tickets:
        _save_debug_json(data)

    return tickets


def analyze_ticket(ticket: dict, predictor) -> dict:
    """
    Estime la fiabilité d'UN ticket de deux façons complémentaires :
    - estimated_win_prob : produit des probabilités de chaque sélection
      (proba réelle de gagner le ticket ENTIER) — mécaniquement minuscule
      dès qu'il y a beaucoup de sélections (ex: 0.4^20 est proche de 0),
      utile pour le gain potentiel mais PAS pour comparer des tickets de
      tailles différentes entre eux.
    - avg_leg_confidence : moyenne géométrique des probabilités par
      sélection — comparable équitablement entre un ticket de 7 et un
      ticket de 27 sélections, c'est LE critère utilisé pour recommander
      quel ticket jouer.
    """
    combined_prob = 1.0
    leg_analysis = []

    for leg in ticket["legs"]:
        match = {
            "home": leg["home"], "away": leg["away"], "league": leg["league"],
            "markets": {}, "start_time": "",
        }
        try:
            pred = predictor.predict(match)
            probs = pred.get("probabilities", {})
            market_lower = leg["market"].lower()
            # On ne sait estimer précisément que 1X2 et BTTS avec le modèle
            # actuel — les autres marchés (corners, handicap...) nécessitent
            # des données et des modèles dédiés qu'on n'a pas encore.
            if market_lower in ("résultat du match", "resultat du match", "1x2", "match result"):
                sel = leg["selection"]
                sel_key = {"1": "1", "X": "X", "2": "2", "Nul": "X"}.get(sel, sel)
                leg_prob = probs.get(sel_key)
            elif "les deux équipes marquent" in market_lower or "btts" in market_lower:
                btts_prob = pred.get("btts_probability")
                sel_lower = str(leg["selection"]).lower()
                if btts_prob is not None:
                    leg_prob = btts_prob if sel_lower in ("oui", "yes") else (1 - btts_prob)
                else:
                    leg_prob = None
            else:
                leg_prob = None
        except Exception:
            leg_prob = None

        leg_analysis.append({**leg, "model_prob": leg_prob})
        if leg_prob is not None:
            combined_prob *= leg_prob
        # Si on ne sait pas estimer une sélection (marché non couvert), on
        # ne la compte ni pour ni contre — on l'exclut du produit plutôt que
        # de fausser l'estimation avec une valeur arbitraire.

    n_estimated = sum(1 for l in leg_analysis if l["model_prob"] is not None)
    avg_leg_confidence = combined_prob ** (1 / n_estimated) if n_estimated else None
    return {
        **ticket,
        "leg_analysis": leg_analysis,
        "estimated_win_prob": round(combined_prob, 6) if n_estimated else None,
        "avg_leg_confidence": round(avg_leg_confidence, 4) if avg_leg_confidence is not None else None,
        "n_legs_estimated": n_estimated,
        "n_legs_total": len(ticket["legs"]),
    }


def get_best_combo_ticket() -> dict:
    """
    Point d'entrée principal : récupère les tickets CongoBet du moment, les
    analyse, et renvoie {tickets: [...], recommended: ticket_le_plus_sur}.
    """
    from predictor import Predictor

    raw = fetch_top_combos()
    tickets = parse_combo_tickets(raw)
    if not tickets:
        return {"tickets": [], "recommended": None}

    predictor = Predictor()
    analyzed = [analyze_ticket(t, predictor) for t in tickets]

    # On ne classe que les tickets où on a pu estimer une part significative
    # des sélections (au moins la moitié) — sinon le classement n'a pas de sens.
    # Le critère est la moyenne géométrique par sélection (avg_leg_confidence),
    # pas la probabilité brute du ticket entier : sinon un ticket à 7
    # sélections gagnerait quasi systématiquement contre un ticket à 27
    # sélections, indépendamment de la qualité de chacune.
    rankable = [t for t in analyzed if t["avg_leg_confidence"] is not None and t["n_legs_estimated"] >= t["n_legs_total"] / 2]
    recommended = max(rankable, key=lambda t: t["avg_leg_confidence"]) if rankable else None

    return {"tickets": analyzed, "recommended": recommended}


if __name__ == "__main__":
    result = get_best_combo_ticket()
    if not result["tickets"]:
        print("Aucun ticket combiné trouvé (voir logs/ pour la réponse brute si le format API a changé).")
    else:
        for t in result["tickets"]:
            marker = " ⭐ RECOMMANDÉ" if result["recommended"] and t["ticket_rank"] == result["recommended"]["ticket_rank"] else ""
            avg_txt = f"{t['avg_leg_confidence']:.1%}" if t["avg_leg_confidence"] is not None else "N/A"
            print(f"Ticket #{t['ticket_rank']} — {t['n_selections']} sélections, cote totale {t.get('total_cote')}, "
                  f"confiance moyenne/sélection {avg_txt} ({t['n_legs_estimated']}/{t['n_legs_total']} sélections évaluées){marker}")
