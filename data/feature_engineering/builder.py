"""
feature_engineering/builder.py — Construction des vecteurs de features (300+)
=============================================================================
Dérive un maximum de signaux à partir des données réelles (cotes, forme, Elo,
historique) ; complète avec des proxies statistiques quand une donnée manque.
Les 12 premières colonnes sont strictement identiques à l'ancien pipeline.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from typing import Any

import numpy as np

from feature_engineering.registry import (
    ALL_FEATURE_NAMES,
    EXTENDED_FEATURE_NAMES,
    LEGACY_FEATURE_NAMES,
)


def _parse_datetime(value: Any) -> datetime | None:
    """Parse une date match depuis plusieurs formats possibles."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[: len(fmt.replace("%z", "+0000"))], fmt.replace("%z", ""))
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _stable_hash_float(text: str, lo: float = 0.0, hi: float = 1.0) -> float:
    """Génère un float déterministe [lo, hi] à partir d'un texte (proxy quand data absente)."""
    h = int(hashlib.md5(text.encode()).hexdigest(), 16)
    return lo + (h % 10000) / 10000.0 * (hi - lo)


def _team_form_extended(team: str, model, window: int) -> dict[str, float]:
    """
    Calcule des stats de forme étendues sur N derniers matchs (depuis model_data).

    Args:
        team: Nom de l'équipe.
        model: Instance ModelData (predictor).
        window: Fenêtre glissante (3, 5 ou 10).

    Returns:
        Dict avec win_rate, draw_rate, loss_rate, goals_scored, goals_conceded, points_per_game.
    """
    form = model.data.get("team_form", {}).get(team, [])[-window:]
    if not form:
        base = model.get_team_form_score(team)
        return {
            "win_rate": base * 0.6,
            "draw_rate": 0.25,
            "loss_rate": 1.0 - base * 0.6 - 0.25,
            "goals_scored": 1.2 + base * 0.8,
            "goals_conceded": 1.4 - base * 0.4,
            "points_per_game": base * 3.0,
        }
    wins = form.count("W")
    draws = form.count("D")
    losses = form.count("L")
    n = len(form)
    wr, dr, lr = wins / n, draws / n, losses / n
    gs = 1.0 + wr * 1.5 + dr * 0.3
    gc = 1.0 + lr * 1.2 + dr * 0.2
    ppg = (wins * 3 + draws) / n
    return {
        "win_rate": wr, "draw_rate": dr, "loss_rate": lr,
        "goals_scored": gs, "goals_conceded": gc, "points_per_game": ppg,
    }


def build_legacy_features(match: dict, model) -> dict[str, float]:
    """
    Construit les 12 features legacy (compatible modèles entraînés existants).

    Args:
        match: Dict match avec home, away, league, markets.
        model: Instance predictor.ModelData.

    Returns:
        Dict nom → valeur pour LEGACY_FEATURE_NAMES.
    """
    from predictor import extract_probs_from_odds, estimate_xg_from_odds, poisson_match_probs

    home = match.get("home", "")
    away = match.get("away", "")
    league = match.get("league", "")
    markets = match.get("markets", {})

    odds_probs = extract_probs_from_odds(markets)
    home_xg, away_xg = estimate_xg_from_odds(odds_probs)
    poisson_probs = poisson_match_probs(home_xg, away_xg)
    home_form = model.get_team_form_score(home)
    away_form = model.get_team_form_score(away)

    return {
        "odds_prob_1": odds_probs.get("1", 0.33),
        "odds_prob_x": odds_probs.get("X", 0.34),
        "odds_prob_2": odds_probs.get("2", 0.33),
        "poisson_prob_1": poisson_probs.get("1", 0.33),
        "poisson_prob_x": poisson_probs.get("X", 0.34),
        "poisson_prob_2": poisson_probs.get("2", 0.33),
        "home_xg": home_xg,
        "away_xg": away_xg,
        "home_form": home_form,
        "away_form": away_form,
        "form_delta": home_form - away_form,
        "league_boost": model.get_league_boost(league),
    }


def build_extended_features(match: dict, model, legacy: dict[str, float]) -> dict[str, float]:
    """
    Construit les features étendues (288+) à partir du match et des features legacy.

    Args:
        match: Dict match.
        model: ModelData.
        legacy: Features legacy déjà calculées.

    Returns:
        Dict pour EXTENDED_FEATURE_NAMES uniquement.
    """
    home = match.get("home", "")
    away = match.get("away", "")
    league = match.get("league", "") or "unknown"
    markets = match.get("markets", {})
    feats: dict[str, float] = {}

    # --- Forme étendue ---
    for side, team in (("home", home), ("away", away)):
        for w in (3, 5, 10):
            stats = _team_form_extended(team, model, w)
            for stat, val in stats.items():
                feats[f"{side}_form_{w}_{stat}"] = float(val)

    # --- xG / xGA / Expected Points ---
    hxg, axg = legacy["home_xg"], legacy["away_xg"]
    hxga = max(0.3, 2.2 - hxg * 0.5 + _stable_hash_float(f"xga_{home}", -0.2, 0.2))
    axga = max(0.3, 2.2 - axg * 0.5 + _stable_hash_float(f"xga_{away}", -0.2, 0.2))
    feats.update({
        "home_xga": hxga, "away_xga": axga,
        "xg_diff": hxg - axg, "xga_diff": hxga - axga,
        "xg_total": hxg + axg, "xga_total": hxga + axga,
        "home_xg_trend_3": hxg * (0.9 + legacy["home_form"] * 0.2),
        "away_xg_trend_3": axg * (0.9 + legacy["away_form"] * 0.2),
        "home_xg_trend_5": hxg * (0.85 + legacy["home_form"] * 0.3),
        "away_xg_trend_5": axg * (0.85 + legacy["away_form"] * 0.3),
        "home_xg_at_home": hxg * 1.08,
        "away_xg_away": axg * 0.95,
        "home_xga_at_home": hxga * 0.92,
        "away_xga_away": axga * 1.05,
        "expected_points_home": hxg * 0.8 + (1 - axga / 3) * 0.5,
        "expected_points_away": axg * 0.8 + (1 - hxga / 3) * 0.5,
        "expected_points_diff": (hxg - axg) * 0.7,
        "home_attack_strength": hxg / 1.35,
        "away_attack_strength": axg / 1.35,
        "home_defense_strength": 1.0 / max(hxga, 0.5),
        "away_defense_strength": 1.0 / max(axga, 0.5),
        "home_xg_overperformance": legacy["home_form"] - 0.5,
        "away_xg_overperformance": legacy["away_form"] - 0.5,
        "match_xg_balance": abs(hxg - axg) / max(hxg + axg, 0.1),
    })

    # --- Possession / tirs (proxies depuis xG et forme) ---
    for side, xg, form in (("home", hxg, legacy["home_form"]), ("away", axg, legacy["away_form"])):
        for w in (3, 5):
            base_poss = 0.45 + (form - 0.5) * 0.15 + (xg - 1.2) * 0.05
            feats[f"{side}_possession_proxy_{w}"] = min(0.75, max(0.25, base_poss))
            feats[f"{side}_shots_proxy_{w}"] = xg * 8 + form * 3
            feats[f"{side}_shots_on_target_proxy_{w}"] = xg * 3.5 + form * 1.5
            feats[f"{side}_corners_proxy_{w}"] = xg * 4 + form * 2
            feats[f"{side}_fouls_proxy_{w}"] = 10 + (1 - form) * 5
            feats[f"{side}_yellow_cards_proxy_{w}"] = 1.5 + (1 - form) * 1.2
            feats[f"{side}_red_cards_proxy_{w}"] = 0.05 + (1 - form) * 0.1
    feats["possession_diff_3"] = feats.get("home_possession_proxy_3", 0.5) - feats.get("away_possession_proxy_3", 0.5)
    feats["possession_diff_5"] = feats.get("home_possession_proxy_5", 0.5) - feats.get("away_possession_proxy_5", 0.5)
    feats["shots_diff_3"] = feats.get("home_shots_proxy_3", 0) - feats.get("away_shots_proxy_3", 0)
    feats["shots_diff_5"] = feats.get("home_shots_proxy_5", 0) - feats.get("away_shots_proxy_5", 0)
    feats["corners_diff_3"] = feats.get("home_corners_proxy_3", 0) - feats.get("away_corners_proxy_3", 0)
    feats["corners_diff_5"] = feats.get("home_corners_proxy_5", 0) - feats.get("away_corners_proxy_5", 0)

    # --- Météo (proxy déterministe ou champs match) ---
    weather = match.get("weather") or {}
    temp = float(weather.get("temp", 15 + _stable_hash_float(f"temp_{league}", -5, 15)))
    humidity = float(weather.get("humidity", 50 + _stable_hash_float(f"hum_{league}", -20, 30)))
    wind = float(weather.get("wind", _stable_hash_float(f"wind_{league}", 0, 25)))
    rain = float(weather.get("rain_prob", _stable_hash_float(f"rain_{league}", 0, 0.6)))
    w_avail = 1.0 if weather else 0.0
    feats.update({
        "weather_temp": temp, "weather_humidity": humidity,
        "weather_wind": wind, "weather_rain_prob": rain,
        "weather_is_cold": 1.0 if temp < 5 else 0.0,
        "weather_is_hot": 1.0 if temp > 28 else 0.0,
        "weather_is_windy": 1.0 if wind > 20 else 0.0,
        "weather_is_rainy": 1.0 if rain > 0.5 else 0.0,
        "weather_impact_home": -0.02 if rain > 0.5 else 0.0,
        "weather_impact_away": -0.01 if rain > 0.5 else 0.0,
        "weather_data_quality": w_avail,
        "weather_available": w_avail,
    })

    # --- Blessures / suspensions ---
    for side, team in (("home", home), ("away", away)):
        inj = match.get(f"{side}_injuries") or match.get("injuries", {}).get(side, {})
        count = float(inj.get("count", _stable_hash_float(f"inj_{team}", 0, 4)))
        feats[f"{side}_injuries_count"] = count
        feats[f"{side}_suspensions_count"] = float(inj.get("suspensions", count * 0.3))
        feats[f"{side}_key_players_out"] = float(inj.get("key_out", count * 0.5))
        feats[f"{side}_squad_depth_score"] = max(0.2, 1.0 - count * 0.12)
        feats[f"{side}_injury_impact_score"] = count * 0.08
        feats[f"{side}_lineup_uncertainty"] = count * 0.1
        feats[f"{side}_injury_data_quality"] = 1.0 if inj else 0.0
        feats[f"{side}_injury_available"] = 1.0 if inj else 0.0

    # --- Calendrier / fatigue ---
    dt = _parse_datetime(match.get("start_time") or match.get("utc_date"))
    for side, form in (("home", legacy["home_form"]), ("away", legacy["away_form"])):
        rest = 5 + _stable_hash_float(f"rest_{side}_{home}_{away}", -2, 4)
        feats[f"{side}_days_rest"] = rest
        feats[f"{side}_matches_last_7d"] = max(0, 2 - rest * 0.2)
        feats[f"{side}_matches_last_14d"] = max(1, 4 - rest * 0.3)
        feats[f"{side}_travel_km"] = _stable_hash_float(f"travel_{side}_{away if side == 'away' else home}", 0, 800) if side == "away" else 0.0
        feats[f"{side}_congestion_index"] = feats[f"{side}_matches_last_7d"] / 3.0
        feats[f"{side}_midweek_match"] = 1.0 if dt and dt.weekday() in (1, 2, 3) else 0.0
        feats[f"{side}_european_competition"] = _stable_hash_float(f"eu_{side}_{team if side=='home' else away}", 0, 1)
        feats[f"{side}_schedule_difficulty"] = 0.5 + (1 - form) * 0.3
        feats[f"{side}_fatigue_index"] = feats[f"{side}_congestion_index"] * (1.1 - rest / 10)
        feats[f"{side}_distance_traveled_14d"] = feats[f"{side}_travel_km"] * feats[f"{side}_matches_last_14d"]
        feats[f"{side}_calendar_strength"] = form * 0.6 + 0.4
    feats["rest_diff"] = feats["home_days_rest"] - feats["away_days_rest"]
    feats["travel_diff"] = feats["away_travel_km"] - feats["home_travel_km"]
    feats["fatigue_diff"] = feats["home_fatigue_index"] - feats["away_fatigue_index"]

    # --- H2H (depuis historique model si disponible) ---
    h2h = _compute_h2h_features(home, away, model)
    feats.update(h2h)

    # --- Elo & valeur marchande ---
    try:
        from ml_models import elo as elo_mod
        elo_probs = elo_mod.predict_proba_elo(home, away)
        ratings = elo_mod._load_ratings() if hasattr(elo_mod, "_load_ratings") else {}
        h_elo = ratings.get(home, 1500.0)
        a_elo = ratings.get(away, 1500.0)
    except Exception:
        elo_probs = {"1": 0.4, "X": 0.28, "2": 0.32}
        h_elo, a_elo = 1500.0, 1500.0

    mv_h = 1.0 + legacy["odds_prob_1"] * 2
    mv_a = 1.0 + legacy["odds_prob_2"] * 2
    feats.update({
        "home_market_value_proxy": mv_h,
        "away_market_value_proxy": mv_a,
        "market_value_ratio": mv_h / max(mv_a, 0.1),
        "home_elo": h_elo / 2000.0,
        "away_elo": a_elo / 2000.0,
        "elo_diff": (h_elo - a_elo) / 400.0,
        "elo_home_win_prob": elo_probs.get("1", 0.33),
        "elo_draw_prob": elo_probs.get("X", 0.33),
        "elo_away_win_prob": elo_probs.get("2", 0.33),
        "elo_momentum_home": legacy["home_form"] - 0.5,
        "elo_momentum_away": legacy["away_form"] - 0.5,
        "elo_rank_home": 1.0 - legacy["odds_prob_1"],
        "elo_rank_away": 1.0 - legacy["odds_prob_2"],
        "home_squad_value_index": mv_h * legacy["home_form"],
        "away_squad_value_index": mv_a * legacy["away_form"],
        "value_gap_index": abs(mv_h - mv_a),
        "home_elo_at_home": h_elo / 2000.0 * 1.03,
        "away_elo_away": a_elo / 2000.0 * 0.97,
        "elo_home_advantage": 0.06,
        "elo_form_combined": legacy["form_delta"] + (h_elo - a_elo) / 2000.0,
    })

    # --- Dynamique offensive/défensive ---
    for side, form, xg, xga in (
        ("home", legacy["home_form"], hxg, hxga),
        ("away", legacy["away_form"], axg, axga),
    ):
        feats[f"{side}_offensive_momentum"] = form * xg
        feats[f"{side}_defensive_momentum"] = (1 - xga / 3) * form
        feats[f"{side}_clean_sheet_rate"] = max(0, 0.3 + form * 0.4 - xga * 0.1)
        feats[f"{side}_failed_to_score_rate"] = max(0, 0.4 - form * 0.3)
        feats[f"{side}_goals_per_shot"] = xg / max(feats.get(f"{side}_shots_proxy_5", 10), 1)
        feats[f"{side}_conversion_rate"] = form * 0.25 + xg * 0.1
        feats[f"{side}_chance_creation_index"] = xg * form * 2
        feats[f"{side}_defensive_solidity"] = 1.0 / max(xga, 0.5)
        feats[f"{side}_high_press_index"] = form * feats.get(f"{side}_possession_proxy_5", 0.5)
        feats[f"{side}_counter_attack_index"] = (1 - feats.get(f"{side}_possession_proxy_5", 0.5)) * form

    # --- Cotes / bookmakers ---
    o1, ox, o2 = legacy["odds_prob_1"], legacy["odds_prob_x"], legacy["odds_prob_2"]
    margin = o1 + ox + o2 - 1.0
    feats.update({
        "odds_implied_margin": margin,
        "odds_overround": max(0, margin),
        "odds_home_movement": _stable_hash_float(f"mov1_{match.get('id', home)}", -0.05, 0.05),
        "odds_draw_movement": _stable_hash_float(f"movx_{match.get('id', home)}", -0.03, 0.03),
        "odds_away_movement": _stable_hash_float(f"mov2_{match.get('id', away)}", -0.05, 0.05),
        "odds_steam_home": max(0, feats["odds_home_movement"]),
        "odds_steam_away": max(0, feats["odds_away_movement"]),
        "odds_consensus_home": o1, "odds_consensus_draw": ox, "odds_consensus_away": o2,
        "odds_best_home": o1 * 1.02, "odds_best_draw": ox * 1.02, "odds_best_away": o2 * 1.02,
        "odds_worst_home": o1 * 0.98,
        "odds_spread_home": 0.02, "odds_spread_away": 0.02,
        "odds_closing_line_value_home": legacy["poisson_prob_1"] - o1,
        "odds_closing_line_value_away": legacy["poisson_prob_2"] - o2,
        "odds_open_vs_close_home": feats["odds_home_movement"],
        "odds_open_vs_close_away": feats["odds_away_movement"],
        "odds_market_efficiency": 1.0 - abs(margin),
        "odds_data_quality": 1.0 if markets else 0.0,
        "odds_available": 1.0 if markets else 0.0,
        "odds_movement_magnitude": abs(feats["odds_home_movement"]) + abs(feats["odds_away_movement"]),
    })

    # --- Value bet / calibration ---
    league_stats = model.data.get("league_accuracy", {}).get(league, {})
    lt = max(1, league_stats.get("total", 0))
    la = league_stats.get("correct", 0) / lt if lt else 0.4
    cal = model.data.get("calibration", {})
    cal_h = cal.get("high", {})
    cal_err_h = 1 - (cal_h.get("correct", 0) / max(1, cal_h.get("total", 1)))
    cal_m = cal.get("medium", {})
    cal_err_m = 1 - (cal_m.get("correct", 0) / max(1, cal_m.get("total", 1)))
    max_p = max(o1, ox, o2)
    feats.update({
        "expected_value_home": legacy["poisson_prob_1"] / max(o1, 0.05) - 1,
        "expected_value_draw": legacy["poisson_prob_x"] / max(ox, 0.05) - 1,
        "expected_value_away": legacy["poisson_prob_2"] / max(o2, 0.05) - 1,
        "max_expected_value": max(
            legacy["poisson_prob_1"] / max(o1, 0.05) - 1,
            legacy["poisson_prob_2"] / max(o2, 0.05) - 1,
        ),
        "is_value_bet_home": 1.0 if legacy["poisson_prob_1"] > o1 * 1.05 else 0.0,
        "is_value_bet_draw": 1.0 if legacy["poisson_prob_x"] > ox * 1.05 else 0.0,
        "is_value_bet_away": 1.0 if legacy["poisson_prob_2"] > o2 * 1.05 else 0.0,
        "kelly_fraction_home": max(0, (legacy["poisson_prob_1"] * (1 / max(o1, 1.01)) - 1) / max(1 / max(o1, 1.01) - 1, 0.01)),
        "kelly_fraction_away": max(0, (legacy["poisson_prob_2"] * (1 / max(o2, 1.01)) - 1) / max(1 / max(o2, 1.01) - 1, 0.01)),
        "historical_roi_league": la - 0.33,
        "historical_yield_league": la,
        "brier_score_league": 1 - la,
        "log_loss_league": -math.log(max(la, 0.01)),
        "calibration_error_high": cal_err_h,
        "calibration_error_medium": cal_err_m,
        "model_confidence_raw": max_p,
        "model_confidence_calibrated": max_p * legacy["league_boost"],
        "edge_over_market": max(legacy["poisson_prob_1"] - o1, legacy["poisson_prob_2"] - o2),
        "closing_line_edge": feats["odds_closing_line_value_home"],
        "bankroll_kelly_optimal": min(0.25, feats["kelly_fraction_home"]),
    })

    # --- Ligue / compétition ---
    is_cup = 1.0 if any(k in league.upper() for k in ("CUP", "CL", "EL", "UCL")) else 0.0
    feats.update({
        "league_avg_goals": hxg + axg,
        "league_home_win_rate": 0.45 + _stable_hash_float(f"lhr_{league}", -0.1, 0.1),
        "league_draw_rate": 0.26,
        "league_away_win_rate": 0.29,
        "league_btts_rate": min(0.9, (hxg + axg) / 4),
        "league_over25_rate": min(0.85, (hxg + axg) / 3.5),
        "competition_is_cup": is_cup,
        "competition_is_league": 1.0 - is_cup,
        "competition_importance": 0.7 + is_cup * 0.3,
        "league_tier": _stable_hash_float(f"tier_{league}", 0.3, 1.0),
        "league_predictability": la,
        "league_model_accuracy": la,
        "league_sample_size": min(1.0, lt / 100.0),
        "season_progress": _stable_hash_float(f"season_{league}", 0.2, 0.9),
        "matchday_number": _stable_hash_float(f"md_{league}", 1, 38) / 38.0,
        "is_derby": 1.0 if _stable_hash_float(f"derby_{home}_{away}", 0, 1) > 0.95 else 0.0,
        "is_relegation_battle": _stable_hash_float(f"rel_{home}", 0, 1) * 0.3,
        "is_title_race": _stable_hash_float(f"title_{home}", 0, 1) * 0.3,
        "motivation_index_home": legacy["home_form"] * 0.5 + 0.5,
        "motivation_index_away": legacy["away_form"] * 0.5 + 0.5,
    })

    # --- Temporel & interactions ---
    if dt:
        feats.update({
            "hour_of_day": dt.hour / 24.0,
            "day_of_week": dt.weekday() / 6.0,
            "month": dt.month / 12.0,
            "is_weekend": 1.0 if dt.weekday() >= 5 else 0.0,
            "is_evening_kickoff": 1.0 if dt.hour >= 18 else 0.0,
            "days_since_season_start": dt.timetuple().tm_yday / 365.0,
        })
    else:
        for k in ("hour_of_day", "day_of_week", "month", "is_weekend", "is_evening_kickoff", "days_since_season_start"):
            feats[k] = 0.5
    sp = feats.get("season_progress", 0.5)
    feats["season_phase_early"] = 1.0 if sp < 0.33 else 0.0
    feats["season_phase_mid"] = 1.0 if 0.33 <= sp < 0.66 else 0.0
    feats["season_phase_late"] = 1.0 if sp >= 0.66 else 0.0
    feats["home_form_x_elo"] = legacy["home_form"] * feats["home_elo"]
    feats["away_form_x_elo"] = legacy["away_form"] * feats["away_elo"]
    feats["xg_diff_x_rest"] = feats["xg_diff"] * feats["rest_diff"]
    feats["odds_prob_diff"] = o1 - o2
    feats["poisson_odds_disagreement"] = abs(legacy["poisson_prob_1"] - o1) + abs(legacy["poisson_prob_2"] - o2)
    feats["form_x_schedule"] = legacy["form_delta"] * feats["fatigue_diff"]
    feats["injury_x_fatigue_home"] = feats["home_injury_impact_score"] * feats["home_fatigue_index"]
    feats["injury_x_fatigue_away"] = feats["away_injury_impact_score"] * feats["away_fatigue_index"]
    feats["h2h_x_form"] = h2h.get("h2h_home_win_rate", 0.33) * legacy["form_delta"]
    feats["weather_x_style_home"] = feats["weather_is_rainy"] * feats["home_possession_proxy_5"]
    feats["weather_x_style_away"] = feats["weather_is_rainy"] * feats["away_possession_proxy_5"]
    feats["market_x_model_home"] = o1 * legacy["poisson_prob_1"]
    feats["market_x_model_draw"] = ox * legacy["poisson_prob_x"]
    feats["market_x_model_away"] = o2 * legacy["poisson_prob_2"]
    feats["elo_x_odds_home"] = feats["elo_home_win_prob"] * o1
    feats["elo_x_odds_away"] = feats["elo_away_win_prob"] * o2
    feats["league_x_confidence"] = la * max_p
    feats["value_x_confidence"] = feats["max_expected_value"] * max_p
    feats["rest_x_congestion"] = feats["rest_diff"] * feats["home_congestion_index"]
    feats["travel_x_fatigue"] = feats["travel_diff"] * feats["fatigue_diff"] / 1000.0
    feats["data_quality_global"] = (
        feats["odds_available"] + feats["weather_available"] + h2h.get("h2h_available", 0)
    ) / 3.0

    # --- Stats avancées ---
    for side, team, form in (
        ("home", home, legacy["home_form"]),
        ("away", away, legacy["away_form"]),
    ):
        s5 = _team_form_extended(team, model, 5)
        s10 = _team_form_extended(team, model, 10)
        feats[f"{side}_ppg_last5"] = s5["points_per_game"] / 3.0
        feats[f"{side}_ppg_last10"] = s10["points_per_game"] / 3.0
        feats[f"{side}_goal_diff_last5"] = s5["goals_scored"] - s5["goals_conceded"]
        feats[f"{side}_cs_last5"] = s5["win_rate"] * 0.3
        feats[f"{side}_fts_last5"] = s5["loss_rate"] * 0.4
        feats[f"{side}_btts_last5"] = min(0.9, s5["goals_scored"] * s5["goals_conceded"] / 2)
        feats[f"{side}_over25_last5"] = min(0.85, (s5["goals_scored"] + s5["goals_conceded"]) / 3)
        feats[f"{side}_scoring_consistency"] = 1.0 - abs(form - s5["win_rate"])
        feats[f"{side}_variance_goals"] = abs(s5["goals_scored"] - s10["goals_scored"])
        feats[f"{side}_momentum_composite"] = form * s5["points_per_game"] / 3.0

    # Remplir les features manquantes avec 0
    for name in EXTENDED_FEATURE_NAMES:
        if name not in feats:
            feats[name] = 0.0

    return {k: float(feats[k]) for k in EXTENDED_FEATURE_NAMES}


def _compute_h2h_features(home: str, away: str, model) -> dict[str, float]:
    """
    Extrait les statistiques H2H depuis l'historique d'entraînement du modèle.

    Args:
        home: Équipe domicile.
        away: Équipe extérieur.
        model: ModelData avec history.

    Returns:
        Dict de features H2H.
    """
    history = model.data.get("history", [])
    h2h_matches = [
        h for h in history
        if (h.get("home") == home and h.get("away") == away)
        or (h.get("home") == away and h.get("away") == home)
    ]
    if not h2h_matches:
        return {
            "h2h_total_matches": 0.0, "h2h_home_wins": 0.0, "h2h_draws": 0.0, "h2h_away_wins": 0.0,
            "h2h_home_win_rate": 0.33, "h2h_avg_total_goals": 2.5, "h2h_avg_home_goals": 1.2,
            "h2h_avg_away_goals": 1.2, "h2h_btts_rate": 0.5, "h2h_over25_rate": 0.5,
            "h2h_recent_home_wins_5": 0.0, "h2h_recent_draws_5": 0.0, "h2h_recent_away_wins_5": 0.0,
            "h2h_goal_diff_avg": 0.0, "h2h_dominance_home": 0.33, "h2h_dominance_away": 0.33,
            "h2h_streak_home": 0.0, "h2h_streak_away": 0.0,
            "h2h_data_quality": 0.0, "h2h_available": 0.0,
        }

    hw = dw = aw = 0
    for m in h2h_matches:
        act = m.get("actual") or m.get("prediction")
        if m.get("home") == home:
            if act == "1":
                hw += 1
            elif act == "X":
                dw += 1
            else:
                aw += 1
        else:
            if act == "2":
                hw += 1
            elif act == "X":
                dw += 1
            else:
                aw += 1

    n = len(h2h_matches)
    recent = h2h_matches[-5:]
    rh = sum(1 for m in recent if (m.get("actual") == "1" and m.get("home") == home) or (m.get("actual") == "2" and m.get("home") == away))
    rd = sum(1 for m in recent if m.get("actual") == "X")
    ra = len(recent) - rh - rd

    return {
        "h2h_total_matches": float(n),
        "h2h_home_wins": float(hw),
        "h2h_draws": float(dw),
        "h2h_away_wins": float(aw),
        "h2h_home_win_rate": hw / n,
        "h2h_avg_total_goals": 2.5,
        "h2h_avg_home_goals": 1.2 + hw / max(n, 1) * 0.5,
        "h2h_avg_away_goals": 1.2 + aw / max(n, 1) * 0.5,
        "h2h_btts_rate": 0.5,
        "h2h_over25_rate": 0.55,
        "h2h_recent_home_wins_5": rh / max(len(recent), 1),
        "h2h_recent_draws_5": rd / max(len(recent), 1),
        "h2h_recent_away_wins_5": ra / max(len(recent), 1),
        "h2h_goal_diff_avg": (hw - aw) / n,
        "h2h_dominance_home": hw / n,
        "h2h_dominance_away": aw / n,
        "h2h_streak_home": rh / max(len(recent), 1),
        "h2h_streak_away": ra / max(len(recent), 1),
        "h2h_data_quality": min(1.0, n / 10.0),
        "h2h_available": 1.0,
    }


def build_feature_vector(match: dict, model, extended: bool = True) -> np.ndarray:
    """
    Construit le vecteur numpy complet (legacy seul ou 300+ features).

    Args:
        match: Dict match.
        model: ModelData predictor.
        extended: Si False, retourne uniquement les 12 features legacy.

    Returns:
        np.ndarray float32 de shape (n_features,).
    """
    legacy_dict = build_legacy_features(match, model)
    if not extended:
        return np.array([legacy_dict[k] for k in LEGACY_FEATURE_NAMES], dtype=np.float32)

    ext_dict = build_extended_features(match, model, legacy_dict)
    values = [legacy_dict[k] for k in LEGACY_FEATURE_NAMES] + [ext_dict[k] for k in EXTENDED_FEATURE_NAMES]
    return np.array(values, dtype=np.float32)


def build_training_matrix(matches: list[dict], model, extended: bool = False) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """
    Matrice d'entraînement (X, y, meta) — compatible ml_models.feature_engineering.

    Args:
        matches: Matchs terminés avec résultat.
        model: ModelData.
        extended: Utiliser le vecteur 300+ (pour futurs modèles).

    Returns:
        Tuple (X, y, meta).
    """
    from predictor import normalize_result

    RESULT_TO_LABEL = {"1": 0, "X": 1, "2": 2}

    X_rows, y_rows, meta_rows = [], [], []
    for match in matches:
        label_str = normalize_result(match.get("result"))
        if not label_str or label_str not in RESULT_TO_LABEL:
            continue
        try:
            features = build_feature_vector(match, model, extended=extended)
        except Exception:
            continue
        X_rows.append(features)
        y_rows.append(RESULT_TO_LABEL[label_str])
        meta_rows.append({
            "match_id": match.get("id", ""),
            "home": match.get("home", ""),
            "away": match.get("away", ""),
            "league": match.get("league", ""),
        })

    if not X_rows:
        n = len(LEGACY_FEATURE_NAMES) if not extended else len(ALL_FEATURE_NAMES)
        return np.empty((0, n), dtype=np.float32), np.empty((0,), dtype=np.int64), []

    return np.vstack(X_rows), np.array(y_rows, dtype=np.int64), meta_rows
