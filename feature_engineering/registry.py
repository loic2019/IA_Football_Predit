"""
feature_engineering/registry.py — Registre des 300+ features
==============================================================
Définit l'ordre canonique des colonnes pour l'entraînement ML étendu.
Les 12 premières colonnes restent IDENTIQUES à ml_models/feature_engineering.py
(pour compatibilité avec les modèles déjà entraînés).
"""

# --- 12 features legacy (NE PAS MODIFIER L'ORDRE) ---
LEGACY_FEATURE_NAMES: list[str] = [
    "odds_prob_1", "odds_prob_x", "odds_prob_2",
    "poisson_prob_1", "poisson_prob_x", "poisson_prob_2",
    "home_xg", "away_xg",
    "home_form", "away_form", "form_delta",
    "league_boost",
]

# --- Catégories étendues (générées dynamiquement) ---
_FORM_WINDOWS = (3, 5, 10)
_STAT_SUFFIXES = ("goals_scored", "goals_conceded", "win_rate", "draw_rate", "loss_rate", "points_per_game")
_SIDE_PREFIXES = ("home", "away")

# Forme étendue : 2 sides × 3 windows × 6 stats = 36
_FORM_EXTENDED = [
    f"{side}_form_{w}_{stat}"
    for side in _SIDE_PREFIXES
    for w in _FORM_WINDOWS
    for stat in _STAT_SUFFIXES
]

# xG / xGA / Expected Points : 24 features
_XG_FEATURES = [
    "home_xga", "away_xga", "xg_diff", "xga_diff", "xg_total", "xga_total",
    "home_xg_trend_3", "away_xg_trend_3", "home_xg_trend_5", "away_xg_trend_5",
    "home_xg_at_home", "away_xg_away", "home_xga_at_home", "away_xga_away",
    "expected_points_home", "expected_points_away", "expected_points_diff",
    "home_attack_strength", "away_attack_strength",
    "home_defense_strength", "away_defense_strength",
    "home_xg_overperformance", "away_xg_overperformance",
    "match_xg_balance",
]

# Possession / tirs / corners / fautes / cartons (proxies) : 40
_POSSESSION_FEATURES = [
    f"{side}_{metric}_{w}"
    for side in _SIDE_PREFIXES
    for metric in ("possession_proxy", "shots_proxy", "shots_on_target_proxy",
                   "corners_proxy", "fouls_proxy", "yellow_cards_proxy", "red_cards_proxy")
    for w in (3, 5)
] + ["possession_diff_3", "possession_diff_5", "shots_diff_3", "shots_diff_5",
     "corners_diff_3", "corners_diff_5"]

# Météo : 12
_WEATHER_FEATURES = [
    "weather_temp", "weather_humidity", "weather_wind", "weather_rain_prob",
    "weather_is_cold", "weather_is_hot", "weather_is_windy", "weather_is_rainy",
    "weather_impact_home", "weather_impact_away", "weather_data_quality", "weather_available",
]

# Blessures / suspensions : 16
_INJURY_FEATURES = [
    f"{side}_{k}"
    for side in _SIDE_PREFIXES
    for k in ("injuries_count", "suspensions_count", "key_players_out",
              "squad_depth_score", "injury_impact_score", "lineup_uncertainty",
              "injury_data_quality", "injury_available")
]

# Fatigue / calendrier / repos : 24
_SCHEDULE_FEATURES = [
    "home_days_rest", "away_days_rest", "rest_diff",
    "home_matches_last_7d", "away_matches_last_7d",
    "home_matches_last_14d", "away_matches_last_14d",
    "home_travel_km", "away_travel_km", "travel_diff",
    "home_congestion_index", "away_congestion_index",
    "home_midweek_match", "away_midweek_match",
    "home_european_competition", "away_european_competition",
    "schedule_difficulty_home", "schedule_difficulty_away",
    "home_fatigue_index", "away_fatigue_index", "fatigue_diff",
    "home_distance_traveled_14d", "away_distance_traveled_14d",
    "calendar_strength_home", "calendar_strength_away",
]

# H2H : 20
_H2H_FEATURES = [
    "h2h_total_matches", "h2h_home_wins", "h2h_draws", "h2h_away_wins",
    "h2h_home_win_rate", "h2h_avg_total_goals", "h2h_avg_home_goals", "h2h_avg_away_goals",
    "h2h_btts_rate", "h2h_over25_rate", "h2h_recent_home_wins_5",
    "h2h_recent_draws_5", "h2h_recent_away_wins_5", "h2h_goal_diff_avg",
    "h2h_dominance_home", "h2h_dominance_away", "h2h_streak_home", "h2h_streak_away",
    "h2h_data_quality", "h2h_available",
]

# Valeur marchande / Elo : 20
_MARKET_ELO_FEATURES = [
    "home_market_value_proxy", "away_market_value_proxy", "market_value_ratio",
    "home_elo", "away_elo", "elo_diff", "elo_home_win_prob", "elo_draw_prob", "elo_away_win_prob",
    "elo_momentum_home", "elo_momentum_away", "elo_rank_home", "elo_rank_away",
    "home_squad_value_index", "away_squad_value_index", "value_gap_index",
    "home_elo_at_home", "away_elo_away", "elo_home_advantage", "elo_form_combined",
]

# Dynamique offensive / défensive : 20
_DYNAMICS_FEATURES = [
    f"{side}_{dyn}"
    for side in _SIDE_PREFIXES
    for dyn in ("offensive_momentum", "defensive_momentum", "clean_sheet_rate",
                "failed_to_score_rate", "goals_per_shot", "conversion_rate",
                "chance_creation_index", "defensive_solidity", "high_press_index", "counter_attack_index")
]

# Bookmakers / mouvements cotes : 24
_ODDS_FEATURES = [
    "odds_implied_margin", "odds_overround", "odds_home_movement", "odds_draw_movement",
    "odds_away_movement", "odds_steam_home", "odds_steam_away", "odds_consensus_home",
    "odds_consensus_draw", "odds_consensus_away", "odds_best_home", "odds_best_draw",
    "odds_best_away", "odds_worst_home", "odds_spread_home", "odds_spread_away",
    "odds_closing_line_value_home", "odds_closing_line_value_away",
    "odds_open_vs_close_home", "odds_open_vs_close_away",
    "odds_market_efficiency", "odds_data_quality", "odds_available", "odds_movement_magnitude",
]

# Value bet / EV / ROI / calibration : 20
_BETTING_FEATURES = [
    "expected_value_home", "expected_value_draw", "expected_value_away", "max_expected_value",
    "is_value_bet_home", "is_value_bet_draw", "is_value_bet_away", "kelly_fraction_home",
    "kelly_fraction_away", "historical_roi_league", "historical_yield_league",
    "brier_score_league", "log_loss_league", "calibration_error_high", "calibration_error_medium",
    "model_confidence_raw", "model_confidence_calibrated", "edge_over_market",
    "closing_line_edge", "bankroll_kelly_optimal",
]

# Contexte ligue / compétition : 20
_LEAGUE_FEATURES = [
    "league_avg_goals", "league_home_win_rate", "league_draw_rate", "league_away_win_rate",
    "league_btts_rate", "league_over25_rate", "competition_is_cup", "competition_is_league",
    "competition_importance", "league_tier", "league_predictability", "league_model_accuracy",
    "league_sample_size", "season_progress", "matchday_number", "is_derby", "is_relegation_battle",
    "is_title_race", "motivation_index_home", "motivation_index_away",
]

# Temporel / interactions : 30
_TEMPORAL_FEATURES = [
    "hour_of_day", "day_of_week", "month", "is_weekend", "is_evening_kickoff",
    "season_phase_early", "season_phase_mid", "season_phase_late",
    "days_since_season_start", "home_form_x_elo", "away_form_x_elo",
    "xg_diff_x_rest", "odds_prob_diff", "poisson_odds_disagreement",
    "form_x_schedule", "injury_x_fatigue_home", "injury_x_fatigue_away",
    "h2h_x_form", "weather_x_style_home", "weather_x_style_away",
    "market_x_model_home", "market_x_model_draw", "market_x_model_away",
    "elo_x_odds_home", "elo_x_odds_away", "league_x_confidence",
    "value_x_confidence", "rest_x_congestion", "travel_x_fatigue",
    "data_quality_global",
]

# Statistiques avancées dérivées : 20
_ADVANCED_STATS = [
    "home_ppg_last5", "away_ppg_last5", "home_ppg_last10", "away_ppg_last10",
    "home_goal_diff_last5", "away_goal_diff_last5", "home_cs_last5", "away_cs_last5",
    "home_fts_last5", "away_fts_last5", "home_btts_last5", "away_btts_last5",
    "home_over25_last5", "away_over25_last5", "scoring_consistency_home",
    "scoring_consistency_away", "variance_goals_home", "variance_goals_away",
    "momentum_composite_home", "momentum_composite_away",
]

EXTENDED_FEATURE_NAMES: list[str] = (
    _FORM_EXTENDED + _XG_FEATURES + _POSSESSION_FEATURES + _WEATHER_FEATURES
    + _INJURY_FEATURES + _SCHEDULE_FEATURES + _H2H_FEATURES + _MARKET_ELO_FEATURES
    + _DYNAMICS_FEATURES + _ODDS_FEATURES + _BETTING_FEATURES + _LEAGUE_FEATURES
    + _TEMPORAL_FEATURES + _ADVANCED_STATS
)

# Vérification : pas de doublons avec legacy
assert not set(LEGACY_FEATURE_NAMES) & set(EXTENDED_FEATURE_NAMES)

ALL_FEATURE_NAMES: list[str] = LEGACY_FEATURE_NAMES + EXTENDED_FEATURE_NAMES

FEATURE_COUNT: int = len(ALL_FEATURE_NAMES)


def get_feature_index(name: str) -> int:
    """
    Retourne l'index d'une feature dans le vecteur complet.

    Args:
        name: Nom canonique de la feature.

    Returns:
        Index entier dans ALL_FEATURE_NAMES.

    Raises:
        KeyError: Si la feature est inconnue.
    """
    return ALL_FEATURE_NAMES.index(name)


def legacy_slice_end() -> int:
    """Retourne la taille du bloc legacy (12) pour les modèles existants."""
    return len(LEGACY_FEATURE_NAMES)
