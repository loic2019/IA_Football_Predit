"""
canonical_match.py — Déduplication multi-sources des matchs À VENIR
================================================================================
Contexte réel (vérifié dans le code) : common.run_auto_cycle() lance CongoBet
+ 1xBet (scraper_multi.py) ET PremierBet (scraper_premierbet.py) par défaut
à chaque cycle (include_premierbet=True). Les trois écrivent dans la même
table `matches` de congobet.db, chacun avec ses propres IDs — rien
n'empêchait jusqu'ici le même vrai match d'apparaître deux fois avec deux IDs
différents et de finir deux fois dans le même coupon (deux fois la même
"sélection", avec potentiellement deux cotes différentes).

get_matches_for_prediction() (common.py) ne dédoublonnait que par ID exact
(`seen = set()`) — ce qui ne peut jamais attraper ce cas, puisque les IDs
sont justement différents d'une source à l'autre.

Approche VOLONTAIREMENT conservatrice (Partie D) : on ne fusionne QUE des
noms d'équipes strictement identiques après normalisation basique (casse,
accents, espaces, quelques suffixes de club neutres) + même jour. Pas de
correspondance floue/similarité — un faux rapprochement entre deux équipes
différentes serait pire qu'un doublon non détecté.
"""

import re
import unicodedata
from collections import defaultdict

# Suffixes/prefixes neutres, sans ambiguïté, uniquement en fin ou début de
# nom (jamais retirés au milieu, pour ne jamais transformer accidentellement
# un nom de club en un autre). Volontairement courte et prudente.
_NEUTRAL_TOKENS = {"fc", "cf", "sc", "ac", "afc", "cfc", "club"}


def normalize_team_name(name: str) -> str:
    """Normalisation basique et sûre : casse, accents, espaces, quelques
    tokens neutres en bordure. N'essaie PAS de résoudre les vrais alias
    (ex: 'PSG' vs 'Paris Saint-Germain') — ce sont deux chaînes différentes
    après normalisation, et resteront donc NON fusionnées : c'est le choix
    prudent (un faux négatif — doublon manqué — est sans danger ; un faux
    positif — deux équipes différentes fusionnées — corromprait des vraies
    prédictions)."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [t for t in text.split() if t]
    while tokens and tokens[0] in _NEUTRAL_TOKENS:
        tokens.pop(0)
    while tokens and tokens[-1] in _NEUTRAL_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def _match_day(match: dict) -> str:
    value = str(match.get("start_time") or match.get("date") or "").strip()
    return value[:10]  # jour seul — deux sources peuvent différer de quelques minutes/fuseaux


def canonical_key(match: dict):
    home = normalize_team_name(match.get("home", ""))
    away = normalize_team_name(match.get("away", ""))
    day = _match_day(match)
    if not home or not away or not day:
        return None  # jamais fusionné si l'un des trois manque — pas assez d'info pour être sûr
    return (home, away, day)


def _completeness_score(match: dict) -> tuple:
    """Sert à choisir LEQUEL des doublons garder comme canonique : priorité
    à celui qui a de vraies cotes (le plus utile pour predictor.py), puis au
    plus de champs renseignés."""
    has_odds = bool(match.get("markets"))
    filled_fields = sum(1 for v in match.values() if v not in (None, "", {}, []))
    return (has_odds, filled_fields)


def deduplicate_matches(matches: list) -> dict:
    """Regroupe les matchs par canonical_key. Pour chaque groupe de taille
    > 1, garde celui avec le meilleur _completeness_score comme canonique et
    écarte les autres (considérés comme le même vrai match vu par une autre
    source). Retourne {'matches': [...], 'report': {...}} — ne modifie
    jamais les dicts d'origine."""
    groups = defaultdict(list)
    unkeyed = []
    for m in matches:
        key = canonical_key(m)
        if key is None:
            unkeyed.append(m)
        else:
            groups[key].append(m)

    kept = []
    merged_report = []
    for key, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        group_sorted = sorted(group, key=_completeness_score, reverse=True)
        canonical = group_sorted[0]
        discarded = group_sorted[1:]
        kept.append(canonical)
        merged_report.append({
            "home": canonical.get("home"),
            "away": canonical.get("away"),
            "day": key[2],
            "kept_id": canonical.get("id"),
            "discarded_ids": [d.get("id") for d in discarded],
        })

    return {
        "matches": kept + unkeyed,
        "report": {
            "input_count": len(matches),
            "output_count": len(kept) + len(unkeyed),
            "duplicate_groups_merged": len(merged_report),
            "matches_discarded": sum(len(g["discarded_ids"]) for g in merged_report),
            "details": merged_report,
            "unkeyed_count": len(unkeyed),  # matchs sans date/nom exploitable, jamais dédupliqués
        },
    }
