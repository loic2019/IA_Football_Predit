"""
security/validation.py — Validation des données entrantes
===========================================================
Anti-corruption : vérifie la cohérence des matchs avant prédiction/entraînement.
"""

from typing import Any


def validate_match(match: dict) -> tuple[bool, str]:
    """
    Valide qu'un dict match contient les champs minimum pour une prédiction.

    Args:
        match: Dictionnaire match (home, away, markets optionnels).

    Returns:
        Tuple (valide, message_erreur).
    """
    if not isinstance(match, dict):
        return False, "match doit être un dict"
    home = str(match.get("home") or "").strip()
    away = str(match.get("away") or "").strip()
    if not home or not away:
        return False, "home et away requis"
    if home.lower() == away.lower():
        return False, "home et away identiques"
    markets = match.get("markets")
    if markets is not None and not isinstance(markets, dict):
        return False, "markets doit être un dict ou absent"
    return True, ""


def validate_prediction_input(match: dict, raise_on_error: bool = False) -> bool:
    """
    Valide un match ; optionnellement lève ValueError.

    Args:
        match: Match à valider.
        raise_on_error: Si True, lève ValueError au lieu de retourner False.

    Returns:
        True si valide.

    Raises:
        ValueError: Si raise_on_error et validation échoue.
    """
    ok, msg = validate_match(match)
    if not ok and raise_on_error:
        raise ValueError(msg)
    return ok


def sanitize_odds_value(value: Any, default: float = 2.0) -> float:
    """
    Nettoie une cote : borne [1.01, 1000], défaut si invalide.

    Args:
        value: Cote brute (str, float, None).
        default: Valeur par défaut si invalide.

    Returns:
        Cote float sécurisée.
    """
    try:
        v = float(value)
        if v <= 1.0 or v > 1000:
            return default
        return v
    except (TypeError, ValueError):
        return default
