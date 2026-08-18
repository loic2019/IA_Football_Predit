"""
match_classification.py — Classification VERIFIED/UNVERIFIED/INVALID
================================================================================
Utilisé par historique.py (et réutilisable ailleurs). Ne touche à aucune
donnée existante — calcule une classification à la volée sur les matchs déjà
retournés par common.get_finished_matches() / coupon_tracker.get_recent_matches_with_results().

Logique (basée sur l'inspection réelle du code, pas une supposition) :

- Un match dont l'id NE commence PAS par "recent_" et dont le résultat a été
  lu directement depuis la ligne congobet.db elle-même (via
  coupon_tracker._lookup_result_free, tier 1) est le cas le plus solide :
  VERIFIED.

- Un match dont l'id commence par "recent_" a eu son résultat retrouvé par
  correspondance approximative NOM+DATE (±3 jours) contre historical_results.db
  (voir coupon_tracker._lookup_result_free, tier 2 : `home_team_name = ? AND
  away_team_name = ?`, pas de jointure par ID). Vraisemblablement correct,
  mais pas garanti — deux matchs différents peuvent partager les mêmes noms
  d'équipes à quelques jours d'intervalle (report, doublon de nom de club).
  Classé UNVERIFIED : l'info est là, mais la méthode de rapprochement n'est
  pas une preuve stricte.

- INVALID : équipe manquante, score manquant, ou date absente/invalide —
  n'importe lequel des critères de la Partie C non rempli.

- DUPLICATE (indépendant des 3 catégories ci-dessus) : un autre match du
  même lot partage (home, away, jour) — signale un même match compté deux
  fois (ex: présent à la fois via get_finished_matches ET recent_, avec un
  ID différent, donc non filtré par la dédup par ID existante).
"""

from collections import Counter


def match_date_value(m: dict) -> str:
    """Certaines sources utilisent 'date', d'autres 'start_time' (voir
    coupon_tracker.get_recent_matches_with_results, qui ne renseigne que
    'start_time') — un seul point pour lire la date, quelle que soit la clé."""
    return str(m.get("date") or m.get("start_time") or "").strip()


def classify_match(m: dict) -> str:
    """Retourne 'VERIFIED', 'UNVERIFIED' ou 'INVALID' pour un match donné."""
    home = str(m.get("home") or "").strip()
    away = str(m.get("away") or "").strip()
    home_score = m.get("home_score")
    away_score = m.get("away_score")
    date_value = match_date_value(m)

    if not home or not away or not date_value:
        return "INVALID"
    if home_score is None or away_score is None or home_score == "" or away_score == "":
        return "INVALID"
    try:
        int(home_score)
        int(away_score)
    except (TypeError, ValueError):
        return "INVALID"

    match_id = str(m.get("id") or "")
    if match_id.startswith("recent_"):
        return "UNVERIFIED"  # résultat retrouvé par correspondance nom+date, pas par ID exact
    return "VERIFIED"


def _duplicate_key(m: dict):
    home = str(m.get("home") or "").strip().lower()
    away = str(m.get("away") or "").strip().lower()
    day = match_date_value(m)[:10]  # jour seul (ignore l'heure) : deux imports d'un même
                                     # match peuvent différer de quelques minutes/heures
    return (home, away, day)


def annotate_matches(matches: list) -> list:
    """Ajoute _status ('VERIFIED'/'UNVERIFIED'/'INVALID') et _is_duplicate à
    chaque match (copie — ne modifie pas les dicts d'origine). Un match
    INVALID n'est jamais marqué doublon (pas assez d'info fiable pour
    comparer)."""
    keys = [
        _duplicate_key(m) if classify_match(m) != "INVALID" else None
        for m in matches
    ]
    key_counts = Counter(k for k in keys if k is not None)

    annotated = []
    seen_first = set()
    for m, key in zip(matches, keys):
        m2 = dict(m)
        m2["_status"] = classify_match(m)
        if key is not None and key_counts[key] > 1:
            # La première occurrence du groupe garde son statut normal, les
            # suivantes sont marquées DUPLICATE (comportement volontaire :
            # on veut voir laquelle est "l'originale" vs "le doublon").
            if key in seen_first:
                m2["_status"] = "DUPLICATE"
            else:
                seen_first.add(key)
        annotated.append(m2)
    return annotated


def summarize(annotated_matches: list) -> dict:
    counts = Counter(m["_status"] for m in annotated_matches)
    return {
        "verified": counts.get("VERIFIED", 0),
        "unverified": counts.get("UNVERIFIED", 0),
        "invalid": counts.get("INVALID", 0),
        "duplicate": counts.get("DUPLICATE", 0),
        "total": len(annotated_matches),
    }


STATUS_BADGE = {
    "VERIFIED": ("✓", "#2ecc87", "Vérifié"),
    "UNVERIFIED": ("⚠", "#f2b84b", "Non vérifié (correspondance approximative)"),
    "INVALID": ("✕", "#e2574c", "Invalide"),
    "DUPLICATE": ("↔", "#8891ab", "Doublon"),
}
