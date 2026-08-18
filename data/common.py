"""
common.py — Fonctions et ressources partagées entre toutes les pages
================================================================================
Centralise : connexion SQLite, requêtes réelles sur la base, moteur de
prédiction, scraping, CSS et état de session. Toutes les pages importent
ce module pour éviter la duplication de code.

MODIFICATIONS APPORTÉES (voir explications détaillées) :
- Import de `historical_data.get_historical_training_matches` : les résultats
  historiques (football-data.org, stockés dans historical_results.db par
  auto_scraper_all_competitions.py) sont désormais ajoutés à l'entraînement
  du modèle, EN PLUS des vrais matchs CongoBet/1xBet/BeSoccer, sans jamais
  toucher au schéma de congobet.db.
- `run_training_pipeline()` fusionne les deux sources avant d'entraîner.
"""

import io
import json
import subprocess
import sys
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

from historical_data import get_historical_training_matches

# ============================================================================
# CONFIGURATION
# ============================================================================

DB_PATH = Path("congobet.db")
MODEL_PATH = Path("model_data.json")
PREDICTIONS_PATH = Path("predictions_history.json")
AUTOMATION_STATE_PATH = Path("automation_state.json")
AUTO_CYCLE_MINUTES = 10


# ============================================================================
# SESSION STATE
# ============================================================================

def init_session_state():
    if "page" not in st.session_state:
        st.session_state.page = "🏠 Accueil"
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = [
            {
                "role": "bot",
                "content": "👋 Bonjour ! Je suis votre assistant football IA. Posez-moi une question sur les matchs, les prédictions ou les statistiques.",
                "time": datetime.now().strftime("%H:%M"),
            }
        ]
    if "conf_threshold" not in st.session_state:
        st.session_state.conf_threshold = 45
    if "selected_project_file" not in st.session_state:
        st.session_state.selected_project_file = None
    if "tool_output" not in st.session_state:
        st.session_state.tool_output = None
    if "auto_cycle_enabled" not in st.session_state:
        st.session_state.auto_cycle_enabled = True
    if "auto_cycle_output" not in st.session_state:
        st.session_state.auto_cycle_output = None
    if "theme" not in st.session_state:
        st.session_state.theme = "dark"


# ============================================================================
# CSS
# ============================================================================

def inject_css():
    """
    Identité visuelle CongoBet AI :
    - Police display : Space Grotesk (technique, géométrique — écrans de scores/stats)
    - Police body : Inter (lisible, dense — tables et texte courant)
    - Palette : nuit stade (#0a0e1a) + cyan projecteur (#33c7ff) + ambre cote (#f5c451)
      + vert pelouse (#2ecc87) + rouge alerte (#ff6b57)
    - Signature : liseré dégradé en haut de page + halo pulsé sur les indicateurs
      "en direct" (déjà utilisé pour l'auto-training, étendu à la connexion/live)
    """
    theme = st.session_state.get("theme", "dark")

    if theme == "light":
        palette = """
            --bg: #f4f6fb;
            --surface: #ffffff;
            --surface-hover: #eef1f8;
            --border: rgba(10,14,26,0.10);
            --text: #10131c;
            --text-muted: rgba(16,19,28,0.62);
            --accent: #0b8fd1;
            --accent-soft: rgba(11,143,209,0.10);
            --primary: #3f8322;
            --primary-hover: #336a1c;
            --gold: #a8720a;
            --gold-soft: rgba(168,114,10,0.10);
            --success: #1f9d5c;
            --success-soft: rgba(31,157,92,0.10);
            --danger: #d64030;
            --danger-soft: rgba(214,64,48,0.10);
        """
    else:
        palette = """
            --bg: #0a0e1a;
            --surface: #121826;
            --surface-hover: #171f30;
            --border: rgba(255,255,255,0.08);
            --text: #e8ecff;
            --text-muted: rgba(232,236,255,0.6);
            --accent: #33c7ff;
            --accent-soft: rgba(51,199,255,0.12);
            --primary: #8bc93c;
            --primary-hover: #79b32f;
            --gold: #f5c451;
            --gold-soft: rgba(245,196,81,0.12);
            --success: #2ecc87;
            --success-soft: rgba(46,204,135,0.12);
            --danger: #ff6b57;
            --danger-soft: rgba(255,107,87,0.12);
        """

    root_block = f"""
        :root {{
            {palette}
            --radius: 12px;
            --font-display: 'Space Grotesk', 'Inter', sans-serif;
            --font-body: 'Inter', -apple-system, sans-serif;
        }}
    """

    css_template = """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap');

        __ROOT_BLOCK__

        .stApp {
            background:
                linear-gradient(180deg, rgba(51,199,255,0.05) 0%, transparent 220px),
                var(--bg);
            color: var(--text);
            font-family: var(--font-body);
        }

        /* Bandeau signature en haut de page */
        .stApp::before {
            content: "";
            position: fixed;
            top: 0; left: 0; right: 0;
            height: 3px;
            background: linear-gradient(90deg, var(--accent), var(--gold), var(--success));
            z-index: 999;
        }

        h1, h2, h3, h4, [data-testid="stMetricValue"] {
            font-family: var(--font-display) !important;
            letter-spacing: -0.01em;
        }

        h1 { font-weight: 700 !important; }
        h2, h3 { font-weight: 600 !important; }

        p, span, div, label { font-family: var(--font-body); }

        /* Sidebar */
        [data-testid="stSidebar"] {
            background: var(--surface);
            border-right: 1px solid var(--border);
        }
        [data-testid="stSidebar"] h2 {
            font-family: var(--font-display) !important;
        }

        /* Metrics natifs Streamlit */
        [data-testid="stMetric"] {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 14px 18px;
        }
        [data-testid="stMetricValue"] {
            font-variant-numeric: tabular-nums;
            color: var(--accent);
        }
        [data-testid="stMetricLabel"] {
            color: var(--text-muted);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        /* Boutons */
        .stButton button {
            font-family: var(--font-body);
            font-weight: 600;
            border-radius: 10px;
            border: 1px solid var(--border);
            transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;
        }
        .stButton button:hover {
            transform: translateY(-1px);
            border-color: var(--accent);
        }
        .stButton button[kind="primary"] {
            background: var(--primary);
            border-color: var(--primary);
            color: #06210a;
        }
        .stButton button[kind="primary"]:hover {
            background: var(--primary-hover);
            border-color: var(--primary-hover);
        }
        .stFormSubmitButton button[kind="primary"] {
            background: var(--primary) !important;
            border-color: var(--primary) !important;
            color: #06210a !important;
        }

        /* Inputs / formulaires */
        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea,
        [data-testid="stSelectbox"] div {
            font-family: var(--font-body);
            border-radius: 8px !important;
        }

        /* Onglets */
        [data-testid="stTabs"] button {
            font-family: var(--font-display);
            font-weight: 600;
        }

        /* Conteneurs à bordure (st.container(border=True)) */
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: var(--radius) !important;
        }

        /* Tableaux de données */
        [data-testid="stDataFrame"] {
            border-radius: var(--radius);
            overflow: hidden;
            border: 1px solid var(--border);
        }

        /* Halo pulsé (statut en direct / connexion / auto-training) */
        @keyframes congobet-pulse {
            0%   { box-shadow: 0 0 0 0 rgba(46,204,135,0.55); }
            70%  { box-shadow: 0 0 0 8px rgba(46,204,135,0); }
            100% { box-shadow: 0 0 0 0 rgba(46,204,135,0); }
        }
        .live-dot {
            display: inline-block;
            width: 8px; height: 8px;
            border-radius: 50%;
            background: var(--success);
            animation: congobet-pulse 1.8s infinite;
        }

        .match-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 16px;
            margin-bottom: 12px;
            border-left: 4px solid var(--accent);
            transition: background 0.15s ease, transform 0.15s ease;
        }
        .match-card:hover { background: var(--surface-hover); transform: translateX(4px); }
        .match-card-finished { border-left-color: var(--success); }
        .match-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 8px;
        }
        .match-league {
            font-size: 11px;
            color: var(--text-muted);
            background: rgba(255,255,255,0.05);
            padding: 2px 10px;
            border-radius: 12px;
        }
        .match-datetime {
            font-size: 12px;
            color: var(--accent);
            background: var(--accent-soft);
            padding: 2px 12px;
            border-radius: 12px;
            border: 1px solid rgba(51,199,255,0.2);
        }
        .match-body {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 16px;
            padding: 8px 0;
            flex-wrap: wrap;
        }
        .match-team {
            font-family: var(--font-display);
            font-size: 16px;
            font-weight: 600;
            color: var(--text);
            min-width: 100px;
            text-align: center;
        }
        .match-score {
            font-family: var(--font-display);
            font-variant-numeric: tabular-nums;
            font-size: 24px;
            font-weight: 700;
            color: var(--accent);
            min-width: 60px;
            text-align: center;
        }
        .match-odds {
            display: flex;
            gap: 8px;
            justify-content: center;
            margin-top: 8px;
            flex-wrap: wrap;
        }
        .match-odds .odd {
            background: rgba(255,255,255,0.05);
            padding: 4px 14px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
            border: 1px solid var(--border);
            min-width: 50px;
            text-align: center;
        }
        .match-odds .odd-1 { color: var(--success); }
        .match-odds .odd-x { color: var(--gold); }
        .match-odds .odd-2 { color: var(--danger); }
        .match-prediction {
            margin-top: 10px;
            padding: 10px 14px;
            background: var(--accent-soft);
            border-radius: 10px;
            border: 1px solid rgba(51,199,255,0.1);
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            align-items: center;
            font-size: 14px;
        }
        .match-prediction .pred { font-family: var(--font-display); font-weight: 700; color: var(--accent); font-size: 18px; }
        .history-match {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 12px;
            border-bottom: 1px solid var(--border);
            flex-wrap: wrap;
            gap: 8px;
        }
        .history-match:last-child { border-bottom: none; }
        .history-match .teams { font-weight: 600; font-size: 14px; }
        .history-match .score { font-family: var(--font-display); font-weight: 700; font-size: 18px; color: var(--accent); }
        .btn-scraper {
            background: rgba(255,255,255,0.05);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 8px 16px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            margin-bottom: 8px;
        }
        .btn-scraper:hover { background: rgba(255,255,255,0.1); transform: translateY(-2px); }
        .btn-congobet { border-color: var(--gold); color: var(--gold); }
        .btn-1xbet { border-color: #9b59b6; color: #9b59b6; }
        .btn-besoccer { border-color: var(--accent); color: var(--accent); }
        .chat-container {
            height: 380px;
            overflow-y: auto;
            border-radius: var(--radius);
            padding: 12px;
            background: rgba(255,255,255,0.02);
            border: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .chat-msg {
            padding: 8px 14px;
            border-radius: 14px;
            max-width: 80%;
            font-size: 14px;
            line-height: 1.5;
        }
        .chat-msg.user {
            background: var(--accent-soft);
            align-self: flex-end;
            border-bottom-right-radius: 4px;
        }
        .chat-msg.bot {
            background: rgba(255,255,255,0.05);
            align-self: flex-start;
            border-bottom-left-radius: 4px;
        }
        .chat-time {
            font-size: 10px;
            color: var(--text-muted);
            margin-top: 2px;
        }
        .confidence-bar {
            height: 6px;
            border-radius: 3px;
            background: rgba(255,255,255,0.05);
            overflow: hidden;
            margin: 4px 0;
        }
        .confidence-bar .fill {
            height: 100%;
            border-radius: 3px;
            transition: width 0.5s ease;
        }
        .info-tile {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 12px 16px;
            margin-bottom: 8px;
            transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;
        }
        .info-tile:hover {
            transform: translateY(-3px);
            border-color: var(--accent);
            background: var(--surface-hover);
        }

        /* CORRECTIF CRITIQUE : le composant streamlit_navigation_bar force
           pointer-events:none sur [data-testid="stAppViewContainer"] (pour
           laisser sa propre iframe "fixed" recevoir les clics par-dessus le
           reste). Or pointer-events est une propriété HÉRITÉE en CSS : ce
           "none" se propage à TOUT ce qu'il contient — contenu principal ET
           sidebar — bloquant le scroll à la molette et les clics sur tous
           les boutons (confirmé avec Playwright : getComputedStyle renvoyait
           bien "none" sur stAppViewContainer). On restaure explicitement
           pointer-events:auto sur le contenu réel, sans toucher au
           mécanisme propre de la navbar (qui gère son propre clic à part).
        */
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"],
        [data-testid="stMain"] *,
        [data-testid="stSidebar"],
        [data-testid="stSidebarContent"],
        [data-testid="stSidebar"] * {
            pointer-events: auto !important;
        }

        /* Légère animation d'entrée sur le contenu de page (un peu de vie
           sans gêner la lecture ni ralentir l'interaction). */
        [data-testid="stMainBlockContainer"] {
            animation: cb-fade-in 0.35s ease-out;
        }
        @keyframes cb-fade-in {
            from { opacity: 0; transform: translateY(6px); }
            to   { opacity: 1; transform: translateY(0); }
        }

        /* En-tête de page réutilisable (voir render_page_header) */
        .cb-page-header {
            display: flex;
            align-items: center;
            gap: 14px;
            margin-bottom: 4px;
        }
        .cb-page-header .icon {
            font-size: 30px;
            width: 48px; height: 48px;
            display: flex; align-items: center; justify-content: center;
            background: var(--accent-soft);
            border-radius: 12px;
        }
        .cb-page-header .title {
            font-family: var(--font-display);
            font-size: 28px;
            font-weight: 700;
            margin: 0;
        }
        .cb-page-header .subtitle {
            color: var(--text-muted);
            font-size: 14px;
            margin: 2px 0 0 0;
        }
    </style>
    """

    st.markdown(css_template.replace("__ROOT_BLOCK__", root_block), unsafe_allow_html=True)


def goto_page(page_name: str):
    """Navigue vers une page depuis n'importe où dans l'app (carte, bouton,
    lien...), en gardant la barre de navigation du haut synchronisée. Voir
    app_dashboard.py pour le détail du mécanisme (top_nav_last)."""
    st.session_state.active_page = page_name
    st.session_state.top_nav_last = page_name
    st.rerun()


def render_page_header(icon: str, title: str, subtitle: str = None):
    """En-tête de page standardisé (icône + titre en police display + sous-titre).
    Optionnel : les pages existantes utilisant st.title() continuent de fonctionner
    (le style h1/h2/h3 s'applique déjà globalement), mais ce helper donne un rendu
    plus soigné pour les pages qui l'adoptent."""
    subtitle_html = f'<p class="subtitle">{subtitle}</p>' if subtitle else ""
    st.markdown(
        f"""
        <div class="cb-page-header">
            <div class="icon">{icon}</div>
            <div>
                <p class="title">{title}</p>
                {subtitle_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================================
# ACCÈS BASE DE DONNÉES (réel, aucune donnée simulée)
# ============================================================================

def _attach_enrichment(matches: list) -> list:
    """
    Ajoute les vraies données d'enrichissement (blessures, météo, arbitre,
    entraîneurs) aux matchs qui en ont en cache (voir enrichment_api_football.py).
    Ne fait AUCUN appel réseau ici (lecture cache seule) — l'enrichissement
    réel se fait à part (quota API limité), typiquement sur le coupon du jour.
    Les matchs sans enrichissement en cache gardent leur comportement actuel
    (proxy déterministe dans feature_engineering/builder.py).
    """
    try:
        from enrichment_api_football import get_enrichment_for_match, to_feature_dict
    except Exception:
        return matches
    for m in matches:
        match_id = m.get("id") or m.get("match_id")
        if not match_id:
            continue
        try:
            enrichment = get_enrichment_for_match(str(match_id))
            if enrichment:
                extra = to_feature_dict(enrichment, m.get("home", ""), m.get("away", ""))
                m["weather"] = extra["weather"]
                m["injuries"] = extra["injuries"]
        except Exception:
            continue
    return matches


def cleanup_stale_live_matches(max_hours: float = 3.5) -> int:
    """
    Filet de sécurité générique (toutes sources confondues) : un match ne
    devrait jamais rester marqué 'live' indéfiniment. Si un match a commencé
    il y a plus de `max_hours` (un match dure ~2h avec prolongations
    éventuelles, on prend une marge), on force is_live=0 même si aucune
    source n'a explicitement confirmé la fin du match. Corrige le bug
    observé où d'anciens matchs live restaient affichés indéfiniment dans
    Pronostics.
    """
    conn = get_db_connection()
    if not conn:
        return 0
    try:
        schema = _get_schema(conn)
        if not schema or not schema["live_col"]:
            return 0
        cutoff = (datetime.now() - timedelta(hours=max_hours)).isoformat()
        live_val = 1 if schema["live_mode"] == "bool" else "'LIVE'"
        marker_col, _ = _order_marker(schema)
        query = f"""
            UPDATE {schema['table']}
            SET {schema['live_col']} = 0
            WHERE {schema['live_col']} = {live_val}
            AND {marker_col} IS NOT NULL AND {marker_col} != ''
            AND {marker_col} < ?
        """
        cur = conn.execute(query, (cutoff,))
        conn.commit()
        return cur.rowcount
    except Exception:
        return 0
    finally:
        conn.close()


def get_db_connection():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _get_schema(conn):
    """
    Détecte dynamiquement le schéma réel de la table de matchs en base.
    Cette fonction ne considère QUE le schéma CongoBet/1xBet (BeSoccer vit dans une base séparée)
    (scraper_api.py / scraper_1xbet_api.py / scraper_multi.py). Les résultats
    historiques football-data.org vivent désormais dans un fichier séparé
    (historical_results.db, voir historical_data.py) et ne passent jamais
    par cette fonction.
    """
    tables = [t[0] for t in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]

    table = None
    if "matches" in tables:
        table = "matches"
    elif "football_matches" in tables:
        table = "football_matches"
    if not table:
        return None

    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    id_col = "match_id" if "match_id" in columns else "id"
    home_col = (
        "home_team_name" if "home_team_name" in columns
        else "home_team" if "home_team" in columns
        else "home"
    )
    away_col = (
        "away_team_name" if "away_team_name" in columns
        else "away_team" if "away_team" in columns
        else "away"
    )
    league_col = "competition_id" if "competition_id" in columns else "league"
    date_col = "utc_date" if "utc_date" in columns else "start_time"
    has_timestamp = "timestamp" in columns

    if "is_live" in columns:
        live_col, live_mode = "is_live", "bool"
    elif "status" in columns:
        live_col, live_mode = "status", "text"
    else:
        live_col, live_mode = None, None

    return {
        "table": table,
        "id_col": id_col,
        "home_col": home_col,
        "away_col": away_col,
        "league_col": league_col,
        "date_col": date_col,
        "has_timestamp": has_timestamp,
        "live_col": live_col,
        "live_mode": live_mode,
        "columns": columns,
    }


def _select_cols(schema):
    """Construit la liste de colonnes SELECT avec les bons alias selon le schéma détecté."""
    cols = f"""
        {schema['id_col']} as id,
        {schema['home_col']} as home,
        {schema['away_col']} as away,
        {schema['league_col']} as league,
        home_score,
        away_score,
        result,
        {schema['date_col']} as date
    """
    if schema["has_timestamp"]:
        cols += ", timestamp"
    return cols


def _order_marker(schema):
    """Retourne (colonne_de_tri, valeur_actuelle) pour comparer/trier les matchs dans le temps.
    Utilise `timestamp` (numérique) si dispo, sinon compare directement les
    dates ISO textuelles (fonctionne car le format YYYY-MM-DDTHH:MM:SS se
    trie correctement en comparaison de chaînes)."""
    if schema["has_timestamp"]:
        return "timestamp", datetime.now().timestamp()
    return schema["date_col"], datetime.now().isoformat()


def get_all_matches():
    conn = get_db_connection()
    if not conn:
        return 0
    try:
        schema = _get_schema(conn)
        if not schema:
            return 0
        return conn.execute(f"SELECT COUNT(*) FROM {schema['table']}").fetchone()[0]
    except Exception:
        return 0
    finally:
        conn.close()


def get_matches_by_source(source="all"):
    conn = get_db_connection()
    if not conn:
        return 0
    try:
        schema = _get_schema(conn)
        if not schema:
            return 0
        table, id_col = schema["table"], schema["id_col"]

        if source == "congobet":
            query = (
                f"SELECT COUNT(*) FROM {table} WHERE {id_col} NOT LIKE '%1xbet%' "
                f"AND {id_col} NOT LIKE '%sofascore%' AND {id_col} NOT LIKE '%premierbet%'"
            )
        elif source == "1xbet":
            query = f"SELECT COUNT(*) FROM {table} WHERE {id_col} LIKE '%1xbet%'"
        elif source == "sofascore":
            query = f"SELECT COUNT(*) FROM {table} WHERE {id_col} LIKE '%sofascore%'"
        elif source == "premierbet":
            query = f"SELECT COUNT(*) FROM {table} WHERE {id_col} LIKE '%premierbet%'"
        else:
            query = f"SELECT COUNT(*) FROM {table}"

        return conn.execute(query).fetchone()[0]
    except Exception:
        return 0
    finally:
        conn.close()


def get_future_matches_count():
    conn = get_db_connection()
    if not conn:
        return 0
    try:
        schema = _get_schema(conn)
        if not schema:
            return 0
        marker_col, now_value = _order_marker(schema)
        return conn.execute(
            f"SELECT COUNT(*) FROM {schema['table']} WHERE {marker_col} > ?", (now_value,)
        ).fetchone()[0]
    except Exception:
        return 0
    finally:
        conn.close()


def get_finished_matches_count():
    conn = get_db_connection()
    if not conn:
        return 0
    try:
        schema = _get_schema(conn)
        if not schema:
            return 0
        return conn.execute(
            f"SELECT COUNT(*) FROM {schema['table']} "
            f"WHERE home_score IS NOT NULL AND away_score IS NOT NULL"
        ).fetchone()[0]
    except Exception:
        return 0
    finally:
        conn.close()


def get_live_matches_count():
    conn = get_db_connection()
    if not conn:
        return 0
    try:
        schema = _get_schema(conn)
        if not schema or not schema["live_col"]:
            return 0
        if schema["live_mode"] == "bool":
            query = f"SELECT COUNT(*) FROM {schema['table']} WHERE {schema['live_col']} = 1"
        else:
            query = f"SELECT COUNT(*) FROM {schema['table']} WHERE {schema['live_col']} = 'LIVE'"
        return conn.execute(query).fetchone()[0]
    except Exception:
        return 0
    finally:
        conn.close()


def get_live_matches(limit=50):
    conn = get_db_connection()
    if not conn:
        return []
    try:
        schema = _get_schema(conn)
        if not schema or not schema["live_col"]:
            return []

        marker_col, _ = _order_marker(schema)
        if schema["live_mode"] == "bool":
            where = f"{schema['live_col']} = 1"
        else:
            where = f"{schema['live_col']} = 'LIVE'"

        query = f"""
            SELECT {_select_cols(schema)} FROM {schema['table']}
            WHERE {where}
            ORDER BY {marker_col} ASC
            LIMIT {int(limit)}
        """
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_future_matches(limit=50):
    conn = get_db_connection()
    if not conn:
        return []
    try:
        schema = _get_schema(conn)
        if not schema:
            return []
        marker_col, now_value = _order_marker(schema)
        query = f"""
            SELECT {_select_cols(schema)} FROM {schema['table']}
            WHERE {marker_col} > ?
            ORDER BY {marker_col} ASC
            LIMIT {int(limit)}
        """
        rows = conn.execute(query, (now_value,)).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_recent_matches(limit=50):
    conn = get_db_connection()
    if not conn:
        return []
    try:
        schema = _get_schema(conn)
        if not schema:
            return []
        marker_col, _ = _order_marker(schema)
        query = f"""
            SELECT {_select_cols(schema)} FROM {schema['table']}
            ORDER BY {marker_col} DESC
            LIMIT {int(limit)}
        """
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_finished_matches(limit=30):
    conn = get_db_connection()
    if not conn:
        return []
    try:
        schema = _get_schema(conn)
        if not schema:
            return []
        marker_col, _ = _order_marker(schema)
        query = f"""
            SELECT {_select_cols(schema)} FROM {schema['table']}
            WHERE home_score IS NOT NULL AND away_score IS NOT NULL
            ORDER BY {marker_col} DESC
            LIMIT {int(limit)}
        """
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_training_matches(limit=500):
    """Matchs réels terminés (CongoBet/1xBet) avec cotes, pour l'entraînement.

    Combine 2 sources :
    - get_finished_matches() : cas où congobet.db aurait lui-même le résultat
      rempli (n'arrive quasiment jamais en pratique, voir coupon_tracker.py,
      mais gardé par sécurité/compatibilité).
    - get_recent_matches_with_results() : le vrai correctif — retrouve le
      résultat des matchs récents via le filet de secours gratuit
      (historical_results.db), là où congobet.db ne le fournit jamais. Avant
      ce correctif, AUCUN match récent avec vraies cotes ne servait jamais à
      l'entraînement, qui se faisait à 100% sur historical_results.db (grandes
      ligues européennes, jusqu'à 2 ans d'ancienneté) — d'où un modèle qui ne
      reflétait pas la forme actuelle des équipes.
    """
    from coupon_tracker import get_recent_matches_with_results

    matches = get_finished_matches(limit)
    prepared = [prepare_match_for_predictor(match) for match in matches]

    recent = get_recent_matches_with_results(days_back=21, limit=limit)
    seen_ids = {m.get("id") for m in prepared}
    for m in recent:
        if m["id"] not in seen_ids:
            prepared.append(m)

    return prepared


def get_odds_for_match(match_id):
    conn = get_db_connection()
    if not conn:
        return {}
    try:
        query = "SELECT market, label, value FROM odds WHERE match_id = ?"
        rows = conn.execute(query, (match_id,)).fetchall()
        odds = {}
        for row in rows:
            odds.setdefault(row["market"], {})[row["label"]] = row["value"]
        return odds
    except Exception:
        return {}
    finally:
        conn.close()


def prepare_match_for_predictor(match):
    """Normalise un match issu du dashboard pour le moteur predictor.py."""
    prepared = dict(match)
    prepared["start_time"] = prepared.get("start_time") or prepared.get("date", "")
    prepared["markets"] = get_odds_for_match(prepared.get("id"))
    _attach_enrichment([prepared])
    return prepared


def get_matches_for_prediction(limit=200, include_recent_fallback=True):
    live_matches = get_live_matches(limit)
    future_matches = get_future_matches(limit)
    source_mode = "live_futur"

    if include_recent_fallback and not live_matches and not future_matches:
        future_matches = get_recent_matches(limit)
        source_mode = "recent"

    seen = set()
    prepared_matches = []
    for match in live_matches + future_matches:
        match_id = match.get("id")
        if match_id in seen:
            continue
        seen.add(match_id)
        prepared = prepare_match_for_predictor(match)
        if source_mode == "recent":
            prepared["home_score"] = None
            prepared["away_score"] = None
        prepared_matches.append(prepared)

    return {
        "live_matches": live_matches,
        "future_matches": future_matches,
        "matches": prepared_matches,
        "source_mode": source_mode,
    }


def load_automation_state():
    default = {
        "enabled": True,
        "interval_minutes": AUTO_CYCLE_MINUTES,
        "last_cycle_at": None,
        "last_cycle_status": "never",
        "last_cycle_summary": {},
    }
    if not AUTOMATION_STATE_PATH.exists():
        return default
    try:
        with open(AUTOMATION_STATE_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        default.update(saved)
    except Exception:
        pass
    return default


def save_automation_state(state):
    with open(AUTOMATION_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def seconds_until_next_cycle(state=None):
    state = state or load_automation_state()
    last_cycle_at = state.get("last_cycle_at")
    if not last_cycle_at:
        return 0
    try:
        last_dt = datetime.fromisoformat(last_cycle_at)
    except Exception:
        return 0
    interval = int(state.get("interval_minutes") or AUTO_CYCLE_MINUTES) * 60
    elapsed = (datetime.now() - last_dt).total_seconds()
    return max(0, int(interval - elapsed))


def run_prediction_pipeline(limit=200, min_confidence=0.0, min_cote=1.30):
    from predictor import Predictor

    data = get_matches_for_prediction(limit)
    predictor = Predictor()
    predictions = predictor.predict_all(data["matches"])
    # Le seuil de confiance ne s'applique qu'au coupon conseillé (via
    # build_coupon, qui filtre déjà en interne) — la liste "Toutes les
    # predictions" doit rester visible même si aucun match n'atteint le
    # seuil, sinon l'utilisateur ne voit plus rien du tout.
    coupon = predictor.build_coupon(predictions, size=8, min_confidence=min_confidence, min_cote=min_cote)

    snapshot = {
        "generated_at": datetime.now().isoformat(),
        "source_mode": data["source_mode"],
        "live_count": len(data["live_matches"]),
        "future_count": len(data["future_matches"]),
        "prediction_count": len(predictions),
        "coupon": coupon,
        "predictions": predictions,
    }
    with open(PREDICTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return snapshot


def run_training_pipeline(limit=500):
    """
    Entraîne le modèle avec :
    - les vrais matchs terminés CongoBet/1xBet (avec cotes réelles)
    - + les résultats historiques football-data.org (historical_results.db),
      qui n'ont pas de cotes mais enrichissent la forme des équipes et la
      calibration du modèle.
    Les deux sources ne partagent jamais le même schéma ni la même base :
    aucun risque d'écrasement.
    """
    from predictor import Predictor

    predictor = Predictor()
    real_matches = get_training_matches(limit)
    historical_matches = get_historical_training_matches(limit=2000)
    combined = real_matches + historical_matches
    return predictor.train_from_results(combined, limit=len(combined))


def run_auto_cycle(force=False, include_besoccer=False, include_premierbet=True):
    state = load_automation_state()
    if not force and seconds_until_next_cycle(state) > 0:
        return {
            "ran": False,
            "reason": "not_due",
            "next_in_seconds": seconds_until_next_cycle(state),
            "state": state,
        }

    started_at = datetime.now().isoformat()
    summary = {
        "started_at": started_at,
        "scrapers": [],
        "training": {},
        "prediction": {},
    }
    state["last_cycle_status"] = "running"
    state["last_cycle_at"] = started_at
    state["last_cycle_summary"] = summary
    save_automation_state(state)

    try:
        summary["scrapers"].append({"source": "all", **run_scraper("all")})
        if include_besoccer:
            summary["scrapers"].append({"source": "besoccer", **run_scraper("besoccer")})
        if include_premierbet:
            summary["scrapers"].append({"source": "premierbet", **run_scraper("premierbet")})

        # --- Filet de sécurité : nettoie les matchs marqués 'live' depuis
        # trop longtemps (bug corrigé, mais utile en garde-fou permanent). ---
        try:
            cleaned = cleanup_stale_live_matches()
            summary["stale_live_cleaned"] = cleaned
        except Exception as exc:
            summary["stale_live_cleaned"] = f"erreur: {exc}"

        training = run_training_pipeline(limit=500)
        prediction = run_prediction_pipeline(limit=250, min_confidence=0.0)
        summary["training"] = training
        summary["prediction"] = {
            "generated_at": prediction["generated_at"],
            "source_mode": prediction["source_mode"],
            "live_count": prediction["live_count"],
            "future_count": prediction["future_count"],
            "prediction_count": prediction["prediction_count"],
            "coupon_size": prediction["coupon"].get("size", 0),
            "coupon_total_cote": prediction["coupon"].get("total_cote", 0),
        }

        # --- Boucle de feedback : sauvegarde le coupon du jour (1x/jour) et
        # règle automatiquement les coupons passés dont les matchs sont
        # terminés, en poussant chaque résultat vers le meta-learner. ---
        try:
            from coupon_tracker import save_daily_coupon, settle_pending_coupons
            save_result = save_daily_coupon(prediction["coupon"])
            settle_result = settle_pending_coupons()
            summary["coupon_tracking"] = {"save": save_result, "settle": settle_result}

            # --- Auto-learning : le réajustement des poids par modèle se fait
            # déjà dans settle_pending_coupons() (record_model_outcome). Ce qui
            # manquait encore : la détection de dérive de performance et
            # l'élimination des modèles qui deviennent mauvais dans la durée
            # (auto_learning/engine.py existait mais n'était jamais appelé). ---
            if settle_result.get("settled", 0) > 0:
                try:
                    from auto_learning.engine import detect_drift, prune_underperforming_models
                    from predictor import ModelData

                    drift = detect_drift(ModelData().data)
                    disabled = prune_underperforming_models() if drift.get("drift_detected") else []
                    summary["auto_learning"] = {"drift": drift, "disabled_models": disabled}
                except Exception as exc:
                    summary["auto_learning"] = f"erreur: {exc}"

            # Enrichit le coupon du jour (blessures, arbitre, joueurs, entraîneurs,
            # météo) UNE SEULE FOIS par jour (quota API-Football gratuit limité).
            if save_result.get("saved"):
                try:
                    from core.config import get_config
                    if get_config().api_football_key:
                        from enrichment_api_football import enrich_coupon_matches
                        enrich_result = enrich_coupon_matches(prediction["coupon"])
                        summary["coupon_enrichment"] = {"matches_enriched": len(enrich_result)}
                    else:
                        summary["coupon_enrichment"] = "clé API-Football non configurée (API_FOOTBALL_KEY)"
                except Exception as exc:
                    summary["coupon_enrichment"] = f"erreur: {exc}"
        except Exception as exc:
            summary["coupon_tracking"] = {"error": str(exc)}

        # --- Vérifie les pronostics suivis de TOUS les utilisateurs (pas
        # seulement quand chacun ouvre sa page Profil individuellement). ---
        try:
            import community_db
            conn = community_db._connect()
            user_ids = [r["id"] for r in conn.execute("SELECT id FROM users").fetchall()]
            conn.close()
            total_updated = 0
            for uid in user_ids:
                total_updated += community_db.refresh_followed_picks_results(uid)
            summary["followed_picks_updated"] = total_updated
        except Exception as exc:
            summary["followed_picks_updated"] = f"erreur: {exc}"

        state["last_cycle_status"] = "success"
    except Exception as exc:
        summary["error"] = str(exc)
        state["last_cycle_status"] = "error"

    summary["finished_at"] = datetime.now().isoformat()
    state["last_cycle_summary"] = summary
    save_automation_state(state)
    return {"ran": True, "summary": summary, "state": state}


def get_project_files():
    roots = [
        Path("."),
        Path("logs"),
        Path("output"),
    ]
    suffixes = {".py", ".json", ".jsonl", ".csv", ".db", ".log", ".txt", ".md"}
    files = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*"):
            if path.is_file() and path.suffix.lower() in suffixes:
                files.append(path)
    return sorted(files, key=lambda p: (str(p.parent), p.name.lower()))


def run_python_file(script, *args, timeout=120):
    try:
        result = subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "command": " ".join([Path(sys.executable).name, str(script), *map(str, args)]),
            "output": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "command": str(script), "error": "Timeout"}
    except Exception as e:
        return {"success": False, "command": str(script), "error": str(e)}


def get_model_stats():
    if not MODEL_PATH.exists():
        return None
    try:
        with open(MODEL_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ============================================================================
# (Le moteur de prédiction a été retiré du dashboard : utilise directement
#  `python predictor.py --analyze` / `--coupon` / `--stats` en CLI, qui est
#  déjà ton outil de référence pour les pronostics.)
# ============================================================================


# ============================================================================
# SCRAPING
# ============================================================================

def run_scraper(source):
    try:
        script = {
            "congobet": "scraper_api.py",
            "1xbet": "scraper_1xbet_api.py",
            "besoccer": "scraper_besoccer.py",
            "premierbet": "scraper_premierbet.py",
            "all": "scraper_multi.py",
        }.get(source, "scraper_multi.py")

        args = [sys.executable, script]
        if source == "besoccer":
            args.append("--all")

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_besoccer_count():
    """Compte les matchs BeSoccer — base et table séparées (historical_results.db /
    results_history), voir scraper_besoccer.py. Ne peut pas passer par
    get_matches_by_source(), qui ne regarde que congobet.db."""
    try:
        conn = sqlite3.connect("historical_results.db")
        row = conn.execute(
            "SELECT COUNT(*) FROM results_history WHERE competition_id LIKE 'besoccer:%'"
        ).fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0


def get_recent_team_matches(team: str, limit: int = 5) -> list[dict]:
    """
    Derniers matchs TERMINÉS (avec score) d'une équipe, toutes sources
    confondues (congobet.db + historical_results.db), triés du plus récent
    au plus ancien. Utilisé pour afficher la forme récente d'une équipe dans
    l'interface — jusqu'ici calculée en interne (team_form) mais jamais
    montrée à l'utilisateur.
    """
    if not team:
        return []
    results = []

    try:
        conn = get_db_connection()
        if conn:
            rows = conn.execute(
                """SELECT home_team, away_team, home_score, away_score, start_time, league
                   FROM matches
                   WHERE (home_team = ? OR away_team = ?)
                     AND home_score IS NOT NULL AND away_score IS NOT NULL
                   ORDER BY start_time DESC LIMIT ?""",
                (team, team, limit),
            ).fetchall()
            for r in rows:
                is_home = r["home_team"] == team
                opponent = r["away_team"] if is_home else r["home_team"]
                gf = r["home_score"] if is_home else r["away_score"]
                ga = r["away_score"] if is_home else r["home_score"]
                results.append({
                    "date": r["start_time"], "opponent": opponent,
                    "score": f"{gf}-{ga}", "domicile": is_home,
                    "league": r["league"],
                    "result": "V" if gf > ga else "N" if gf == ga else "D",
                })
            conn.close()
    except Exception:
        pass

    try:
        hconn = sqlite3.connect("historical_results.db")
        hconn.row_factory = sqlite3.Row
        rows = hconn.execute(
            """SELECT home_team_name, away_team_name, home_score, away_score, utc_date, competition_id
               FROM results_history
               WHERE (home_team_name = ? OR away_team_name = ?)
                 AND home_score IS NOT NULL AND away_score IS NOT NULL
               ORDER BY utc_date DESC LIMIT ?""",
            (team, team, limit),
        ).fetchall()
        for r in rows:
            is_home = r["home_team_name"] == team
            opponent = r["away_team_name"] if is_home else r["home_team_name"]
            gf = r["home_score"] if is_home else r["away_score"]
            ga = r["away_score"] if is_home else r["home_score"]
            results.append({
                "date": r["utc_date"], "opponent": opponent,
                "score": f"{gf}-{ga}", "domicile": is_home,
                "league": r["competition_id"],
                "result": "V" if gf > ga else "N" if gf == ga else "D",
            })
        hconn.close()
    except Exception:
        pass

    results.sort(key=lambda x: x["date"] or "", reverse=True)
    return results[:limit]


def get_team_info_panel(match_id, home: str, away: str) -> dict:
    """
    Regroupe tout ce qui existe sur les 2 équipes d'un match pour
    l'affichage : forme récente (scores) + enrichissement en cache
    (blessures, arbitre, météo, entraîneurs) si disponible.
    """
    panel = {
        "home_recent": get_recent_team_matches(home, limit=5),
        "away_recent": get_recent_team_matches(away, limit=5),
        "enrichment": None,
    }
    try:
        from enrichment_api_football import get_enrichment_for_match
        panel["enrichment"] = get_enrichment_for_match(str(match_id))
    except Exception:
        pass
    return panel


def sidebar_scraping_panel():
    """Panneau de scraping partagé, affiché dans la sidebar sur toutes les pages."""
    st.markdown("### 🚀 Scraping")

    cb_count = get_matches_by_source("congobet")
    ox_count = get_matches_by_source("1xbet")
    pb_count = get_matches_by_source("premierbet")

    if st.button(":material/sync: Scraper tous", width="stretch", key="all_scrapers"):
        with st.spinner("Scraping CongoBet + 1xBet + Premierbet..."):
            r = run_auto_cycle(force=True, include_premierbet=True)
            st.session_state.auto_cycle_output = r
            if r.get("ran") and r.get("state", {}).get("last_cycle_status") == "success":
                st.success("Cycle complet termine.")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Cycle incomplet. Consulte le statut d'automatisation.")

    if st.button(f"🟡 CongoBet ({cb_count})", width="stretch", key="cb"):
        with st.spinner("Scraping CongoBet..."):
            r = run_scraper("congobet")
            if r["success"]:
                st.success("✅ CongoBet importé !")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"❌ Échec : {r.get('error') or r.get('stderr') or 'voir logs'}")

    if st.button(f"🟣 1xBet ({ox_count})", width="stretch", key="1x"):
        with st.spinner("Scraping 1xBet..."):
            r = run_scraper("1xbet")
            if r["success"]:
                st.success("✅ 1xBet importé !")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"❌ Échec : {r.get('error') or r.get('stderr') or 'voir logs'}")

    if st.button(f"🟢 Premierbet ({pb_count})", width="stretch", key="pb"):
        with st.spinner("Scraping Premierbet..."):
            r = run_scraper("premierbet")
            if r["success"]:
                st.success("✅ Premierbet importé !")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"❌ Échec : {r.get('error') or r.get('stderr') or 'voir logs'}")

    st.markdown("---")

    st.session_state.conf_threshold = st.slider(
        "Seuil confiance",
        0,
        100,
        st.session_state.conf_threshold,
        5,
        format="%d%%",
        width="stretch",
    )

    if st.button("🔄 Actualiser les données", width="stretch"):
        with st.spinner("Actualisation..."):
            time.sleep(0.3)
            st.rerun()

    st.markdown("---")
    st.markdown("### :material/autoplay: Automatisation")
    state = load_automation_state()
    st.session_state.auto_cycle_enabled = st.toggle(
        "Cycle auto 10 min",
        value=st.session_state.get("auto_cycle_enabled", state.get("enabled", True)),
        key="auto_cycle_toggle",
    )
    state["enabled"] = bool(st.session_state.auto_cycle_enabled)
    state["interval_minutes"] = AUTO_CYCLE_MINUTES
    save_automation_state(state)

    remaining = seconds_until_next_cycle(state)
    if state.get("last_cycle_at"):
        st.caption(f"Dernier cycle : {format_date(state['last_cycle_at'])}")
    st.caption(
        "Prochain cycle : maintenant"
        if remaining == 0
        else f"Prochain cycle : {remaining // 60}m {remaining % 60}s"
    )
    st.caption("ℹ️ Le cycle auto s'exécute via `auto_cycle_worker.py` (process séparé), pas dans le dashboard.")

    if st.button(":material/play_arrow: Lancer cycle maintenant", width="stretch", key="force_auto_cycle"):
        with st.spinner("Cycle auto en cours..."):
            st.session_state.auto_cycle_output = run_auto_cycle(force=True, include_premierbet=True)
            st.rerun()


def format_date(date_str, fmt="%d/%m/%Y %H:%M"):
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime(fmt)
    except Exception:
        return date_str[: len(fmt)] if date_str else "N/A"
