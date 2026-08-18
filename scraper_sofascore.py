# -*- coding: utf-8 -*-
"""
scraper_sofascore.py — ⚠️ ATTENTION : ce fichier ne scrape PAS Sofascore
================================================================================================
CE QUE CE FICHIER FAIT VRAIMENT
----------------------------------
Malgré son nom, ce script interroge l'API football-data.org (voir CONFIG["base_url"]
plus bas), pas Sofascore. C'est très probablement un renommage accidentel d'un
fichier auparavant appelé `auto_scraper_all_competitions.py`. Dans common.py, le
bouton sidebar "🔵 Sofascore" et l'option `include_sofascore=True` du cycle auto
appellent CE fichier — donc "scraper Sofascore" déclenche en réalité un import de
résultats historiques (Premier League, Bundesliga, etc.) via football-data.org.

Ce n'est pas grave en soi tant que ça reste isolé, MAIS ce fichier écrivait
JUSQU'ICI dans la table `matches` de `congobet.db`, LA MÊME table que
scraper_api.py / scraper_1xbet_api.py / scraper_multi.py utilisent avec un
schéma de colonnes totalement différent (id/home_team/away_team vs
match_id/competition_id/home_team_name). Comme ce script tourne à CHAQUE cycle
auto (10 min) via include_sofascore=True, il écrasait régulièrement les vrais
matchs CongoBet/1xBet scrapés en live — c'est la cause principale du bug
"le modèle n'arrive pas à prédire les matchs futurs scrapés sur 1xBet/CongoBet".

CE QUI CHANGE ICI (le nom du fichier ne change pas, pour ne rien casser
ailleurs dans le projet — voir common.py et fichiers.py qui le référencent) :
- Base et table séparées : `historical_results.db` / table `results_history`,
  plus aucune écriture dans congobet.db.
- Migration sécurisée : ne migre que si elle retrouve la signature exacte de
  SON PROPRE ancien schéma, et renomme au lieu de supprimer (aucune perte
  possible de données CongoBet/1xBet).

RECOMMANDATION : renomme ce bouton dans l'UI (sidebar + page Fichiers) en
"Historique football-data" pour éviter toute confusion future avec un vrai
scraper Sofascore que tu voudrais ajouter un jour. Dis-le-moi si tu veux que
je fasse ce renommage cosmétique dans common.py / fichiers.py.
"""

import json
import sqlite3
import time
import logging
import sys
import io
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set, Tuple
import requests
from collections import deque
import threading
import signal
import platform

# Forcer l'encodage UTF-8 sur la console Windows (voir scraper_api.py pour le detail)
try:
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    "api_key": "fe50fdb0b9074d04b5533deaafbfe099",
    "base_url": "https://api.football-data.org/v4",
    # IMPORTANT : base séparée de congobet.db pour ne jamais entrer en collision
    # avec le schéma utilisé par scraper_api.py / scraper_1xbet_api.py / scraper_multi.py
    "db_path": "historical_results.db",
    "cache_dir": ".football_cache",
    "log_dir": "logs",
    "fetch_interval_minutes": 10,
}

TABLE_NAME = "results_history"

# TOUTES les competitions disponibles
ALL_COMPETITIONS = {
    "PL": "Premier League",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "PD": "La Liga",
    "FL1": "Ligue 1",
    "CL": "UEFA Champions League",
    "EL": "UEFA Europa League",
}

# Saisons à récupérer (années de début)
SEASONS = [
    (2024, 2025),  # Saison 2024-2025
    (2025, 2026),  # Saison 2025-2026
    # (2026, 2027),  # Saison 2026-2027 (pas encore commencée)
]

# ============================================================================
# COULEURS
# ============================================================================

class Colors:
    def __init__(self):
        self.enabled = True
        if platform.system() == "Windows":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except:
                self.enabled = False

    def _color(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def green(self, text: str) -> str: return self._color("92", text)
    def red(self, text: str) -> str: return self._color("91", text)
    def yellow(self, text: str) -> str: return self._color("93", text)
    def blue(self, text: str) -> str: return self._color("94", text)
    def cyan(self, text: str) -> str: return self._color("96", text)
    def magenta(self, text: str) -> str: return self._color("95", text)
    def bold(self, text: str) -> str: return self._color("1", text)

colors = Colors()

# ============================================================================
# LOGGING
# ============================================================================

LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / f"historical_scraper_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# CLASSES
# ============================================================================

class APIMonitor:
    def __init__(self, max_requests: int = 10, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.lock = threading.Lock()
        self.start_time = datetime.now()

    def get_stats(self) -> Dict:
        with self.lock:
            now = time.time()
            while self.requests and now - self.requests[0] > self.time_window:
                self.requests.popleft()

            used = len(self.requests)
            remaining = self.max_requests - used
            reset_time = self.time_window
            if self.requests:
                oldest = self.requests[0]
                reset_time = max(0, self.time_window - (now - oldest))

            return {
                "used": used,
                "remaining": max(0, remaining),
                "max": self.max_requests,
                "reset_in": reset_time,
                "total": self.total_requests,
                "success": self.successful_requests,
                "failed": self.failed_requests,
                "success_rate": (self.successful_requests / max(1, self.total_requests)) * 100
            }

    def record_request(self, success: bool = True):
        with self.lock:
            self.requests.append(time.time())
            self.total_requests += 1
            if success:
                self.successful_requests += 1
            else:
                self.failed_requests += 1

    def print_status(self):
        stats = self.get_stats()
        bar_length = 20
        filled = int((stats["used"] / stats["max"]) * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)

        if stats["used"] / stats["max"] > 0.8:
            bar = colors.red(bar)
        elif stats["used"] / stats["max"] > 0.5:
            bar = colors.yellow(bar)
        else:
            bar = colors.green(bar)

        print(f"\r{colors.cyan('[API]')} {bar} {stats['used']}/{stats['max']} req", end="")
        print(f" {colors.blue('reset:')}{stats['reset_in']:.0f}s", end="")
        print(f" {colors.green('OK:')}{stats['success']}", end="")
        print(f" {colors.red('ERR:')}{stats['failed']}", end="")
        print(f" {colors.magenta('rate:')}{stats['success_rate']:.0f}%", end="")
        print(" " * 15, end="")
        sys.stdout.flush()


class RateLimiter:
    def __init__(self, max_requests: int = 10, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.monitor = APIMonitor(max_requests, time_window)
        self.lock = threading.Lock()
        self.is_waiting = False

    def wait_if_needed(self):
        with self.lock:
            now = time.time()
            while self.requests and now - self.requests[0] > self.time_window:
                self.requests.popleft()

            if len(self.requests) >= self.max_requests:
                wait_time = self.requests[0] + self.time_window - now
                if wait_time > 0:
                    self.is_waiting = True
                    print(f"\n{colors.yellow('[WAIT]')} API limit reached. Waiting {wait_time:.1f}s...")

                    for i in range(int(wait_time), 0, -1):
                        bar = "█" * (int(i / wait_time * 20))
                        print(f"\r  [COUNTDOWN] {i:2d}s [{bar:20s}]", end="")
                        time.sleep(1)
                    print("\r  [WAIT] Done!     ")
                    time.sleep(0.5)
                    self.is_waiting = False

            self.requests.append(time.time())
            self.monitor.record_request()

    def get_monitor(self) -> APIMonitor:
        return self.monitor


class CompetitionTracker:
    """
    Gère la base `historical_results.db` (table `results_history`).
    La migration ne s'applique QU'À CETTE BASE, et uniquement si elle contient
    déjà une table créée par une VERSION ANTÉRIEURE de ce même scraper
    (ancien nom de table `matches`, ancien schéma football-data). Elle ne
    touche jamais congobet.db.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.migrate_legacy_table_if_present()
        self.init_tables()

    def migrate_legacy_table_if_present(self):
        """
        Migration sûre : ne migre QUE si on retrouve une ancienne table nommée
        `matches` qui possède la signature EXACTE de l'ancien schéma football-data
        (match_id + competition_id + home_team_name). Si la table `matches`
        existe mais n'a pas cette signature (par ex. c'est le schéma
        CongoBet/1xBet de scraper_api.py), on NE TOUCHE À RIEN.
        Par sécurité, l'ancienne table est renommée (jamais supprimée).
        """
        if not Path(self.db_path).exists():
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='matches'")
            if not cursor.fetchone():
                return  # rien à migrer

            cursor.execute("PRAGMA table_info(matches)")
            columns = {col[1] for col in cursor.fetchall()}

            legacy_signature = {"match_id", "competition_id", "home_team_name", "away_team_name"}
            if not legacy_signature.issubset(columns):
                print(colors.yellow(
                    "[MIGRATE] Une table 'matches' existe dans "
                    f"{self.db_path} mais ne correspond pas au schéma attendu "
                    "de l'ancien scraper historique — on ne la modifie pas par sécurité."
                ))
                return

            # Si la table cible existe déjà, ne pas écraser silencieusement
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{TABLE_NAME}'")
            if cursor.fetchone():
                print(colors.yellow(
                    f"[MIGRATE] La table '{TABLE_NAME}' existe déjà : ancienne table "
                    "'matches' laissée telle quelle (pas de fusion automatique)."
                ))
                return

            print(colors.yellow(f"[MIGRATE] Migration de l'ancienne table 'matches' vers '{TABLE_NAME}'..."))
            cursor.execute(f"ALTER TABLE matches RENAME TO {TABLE_NAME}")
            conn.commit()
            print(colors.green(f"[MIGRATE] Migration terminée : table renommée en '{TABLE_NAME}'."))

        except Exception as e:
            print(colors.red(f"[MIGRATE] Erreur (aucune donnée supprimée) : {e}"))
        finally:
            conn.close()

    def init_tables(self):
        conn = sqlite3.connect(self.db_path)

        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                match_id INTEGER PRIMARY KEY,
                competition_id TEXT,
                home_team_id INTEGER,
                away_team_id INTEGER,
                home_team_name TEXT,
                away_team_name TEXT,
                home_score INTEGER,
                away_score INTEGER,
                result TEXT,
                status TEXT,
                utc_date TEXT,
                timestamp INTEGER,
                season_id INTEGER,
                matchday INTEGER,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS competitions (
                competition_id TEXT PRIMARY KEY,
                name TEXT,
                last_fetch TEXT,
                last_match_id INTEGER,
                total_matches INTEGER,
                enabled BOOLEAN DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS fetch_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                competition_id TEXT,
                fetch_date TEXT,
                new_matches INTEGER,
                updated_matches INTEGER,
                total_matches INTEGER,
                status TEXT,
                error TEXT,
                duration REAL
            )
        """)

        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_results_comp ON {TABLE_NAME}(competition_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_results_status ON {TABLE_NAME}(status)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_results_timestamp ON {TABLE_NAME}(timestamp)")

        conn.commit()
        conn.close()

    def get_existing_match_ids(self, competition_id: str) -> Set[int]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            f"SELECT match_id FROM {TABLE_NAME} WHERE competition_id = ?",
            (competition_id,)
        )
        ids = {row[0] for row in cursor.fetchall()}
        conn.close()
        return ids

    def update_competition(self, competition_id: str, name: str, total_matches: int):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT OR REPLACE INTO competitions (
                competition_id, name, last_fetch, total_matches
            ) VALUES (?,?,?,?)
        """, (
            competition_id,
            name,
            datetime.now().isoformat(),
            total_matches
        ))
        conn.commit()
        conn.close()

    def log_fetch(self, competition_id: str, new_matches: int, updated_matches: int,
                  total_matches: int, status: str, error: str = "", duration: float = 0):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO fetch_logs (
                competition_id, fetch_date, new_matches,
                updated_matches, total_matches, status, error, duration
            ) VALUES (?,?,?,?,?,?,?,?)
        """, (
            competition_id,
            datetime.now().isoformat(),
            new_matches,
            updated_matches,
            total_matches,
            status,
            error,
            duration
        ))
        conn.commit()
        conn.close()


class AutoScraper:
    def __init__(self, config: Dict):
        self.config = config
        self.rate_limiter = RateLimiter(max_requests=10, time_window=60)
        self.tracker = CompetitionTracker(config["db_path"])
        self.running = True
        self.last_run = None
        self.stats = {
            "total_new": 0,
            "total_updated": 0,
            "total_matches": 0,
            "cycles": 0,
            "errors": 0
        }
        self.competition_failures = {}
        self.processed_seasons = set()

        self.init_competitions()
        self.setup_signal_handlers()

        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, sig, frame):
        print(f"\n{colors.yellow('[STOP]')} Shutdown requested...")
        self.running = False

    def _monitor_loop(self):
        while self.running:
            time.sleep(1)
            if hasattr(self.rate_limiter, 'monitor'):
                self.rate_limiter.monitor.print_status()

    def init_competitions(self):
        conn = sqlite3.connect(self.config["db_path"])
        for comp_id, name in ALL_COMPETITIONS.items():
            conn.execute("""
                INSERT OR IGNORE INTO competitions (competition_id, name, enabled)
                VALUES (?, ?, 1)
            """, (comp_id, name))
        conn.commit()
        conn.close()
        print(colors.green(f"[INIT] {len(ALL_COMPETITIONS)} competitions initialized"))
        print(colors.blue(f"[SEASONS] {len(SEASONS)} seasons to fetch"))
        print(colors.cyan(f"[DB] Base historique : {Path(self.config['db_path']).resolve()}"))

    def make_request(self, url: str) -> Optional[Dict]:
        self.rate_limiter.wait_if_needed()

        headers = {"X-Auth-Token": self.config["api_key"]}

        for attempt in range(3):
            try:
                response = requests.get(url, headers=headers, timeout=30)

                if response.status_code == 429:
                    print(colors.red("[API] Rate limit exceeded. Waiting 60s..."))
                    time.sleep(60)
                    continue

                if response.status_code == 403:
                    print(colors.yellow("[API] 403 Forbidden - Competition may not be available"))
                    return None

                if response.status_code != 200:
                    if attempt < 2:
                        time.sleep(10)
                        continue
                    return None

                return response.json()

            except Exception as e:
                print(colors.red(f"[API] Error: {e}"))
                if attempt < 2:
                    time.sleep(10)
                    continue
                return None

        return None

    def fetch_matches(self, competition_id: str, date_from: str, date_to: str) -> List[Dict]:
        url = f"{self.config['base_url']}/competitions/{competition_id}/matches"
        url += f"?dateFrom={date_from}&dateTo={date_to}&limit=100"

        data = self.make_request(url)
        if not data:
            return []

        return data.get("matches", [])

    def save_matches(self, matches: List[Dict], competition_id: str) -> Tuple[int, int]:
        if not matches:
            return 0, 0

        existing_ids = self.tracker.get_existing_match_ids(competition_id)
        new_matches = 0
        updated_matches = 0

        conn = sqlite3.connect(self.config["db_path"])

        for match in matches:
            match_id = match.get("id")
            if not match_id:
                continue

            if match_id in existing_ids:
                current = conn.execute(
                    f"SELECT status FROM {TABLE_NAME} WHERE match_id = ?",
                    (match_id,)
                ).fetchone()

                if current and current[0] == match.get("status"):
                    continue
                updated_matches += 1
            else:
                new_matches += 1
                existing_ids.add(match_id)

            score = match.get("score", {})
            home_team = match.get("homeTeam", {})
            away_team = match.get("awayTeam", {})

            home_score = score.get("fullTime", {}).get("home")
            away_score = score.get("fullTime", {}).get("away")

            result = None
            if home_score is not None and away_score is not None:
                if home_score > away_score:
                    result = "H"
                elif home_score < away_score:
                    result = "A"
                else:
                    result = "D"

            utc_date = match.get("utcDate", "")
            timestamp = None
            if utc_date:
                try:
                    dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
                    timestamp = int(dt.timestamp())
                except:
                    pass

            try:
                conn.execute(f"""
                    INSERT OR REPLACE INTO {TABLE_NAME} (
                        match_id, competition_id, home_team_id, away_team_id,
                        home_team_name, away_team_name,
                        home_score, away_score, result,
                        status, utc_date, timestamp,
                        season_id, matchday, last_updated
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                """, (
                    match_id,
                    competition_id,
                    home_team.get("id"),
                    away_team.get("id"),
                    home_team.get("name", ""),
                    away_team.get("name", ""),
                    home_score,
                    away_score,
                    result,
                    match.get("status"),
                    utc_date,
                    timestamp,
                    match.get("season", {}).get("id"),
                    match.get("matchday"),
                ))
            except Exception as e:
                # On ne masque plus l'erreur : elle remonte dans les stats de cycle.
                logger.error(f"Erreur insertion match {match_id}: {e}")
                self.stats["errors"] += 1

        conn.commit()
        conn.close()

        return new_matches, updated_matches

    def process_season(self, competition_id: str, start_year: int, end_year: int) -> Dict:
        start_time = time.time()
        result = {
            "competition_id": competition_id,
            "season": f"{start_year}/{end_year}",
            "new": 0,
            "updated": 0,
            "total": 0,
            "status": "success",
            "error": ""
        }

        try:
            date_from = f"{start_year}-08-01"
            date_to = f"{end_year}-05-31"

            comp_name = ALL_COMPETITIONS.get(competition_id, competition_id)
            print(f"  [SEASON] {start_year}/{end_year} ({date_from} -> {date_to})")

            matches = self.fetch_matches(competition_id, date_from, date_to)

            if matches is None:
                result["status"] = "error"
                result["error"] = "No response from API"
                return result

            if not matches:
                print(f"    {colors.yellow('[INFO]')} No matches found")
                return result

            finished = [m for m in matches if m.get("status") == "FINISHED" and
                       m.get("score", {}).get("fullTime", {}).get("home") is not None]

            if not finished:
                print(f"    {colors.yellow('[INFO]')} No finished matches with scores")
                return result

            new, updated = self.save_matches(finished, competition_id)
            total = len(finished)

            result["new"] = new
            result["updated"] = updated
            result["total"] = total

            status_parts = []
            if new > 0:
                status_parts.append(colors.green("NEW: " + str(new)))
            if updated > 0:
                status_parts.append(colors.blue("UPD: " + str(updated)))
            if status_parts:
                print(f"    {colors.green('[OK]')} {' | '.join(status_parts)} (Total: {total})")
            else:
                print(f"    {colors.yellow('[INFO]')} No changes (Total: {total})")

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            print(f"    {colors.red('[ERROR]')} {e}")

        finally:
            duration = time.time() - start_time
            self.tracker.log_fetch(
                competition_id + "_" + str(start_year),
                result["new"],
                result["updated"],
                result["total"],
                result["status"],
                result["error"],
                duration
            )

        return result

    def print_header(self, cycle_num: int):
        print("\n" + "=" * 70)
        print(colors.bold(colors.cyan("[CYCLE #" + str(cycle_num) + "] " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))))
        print("=" * 70)

        if self.stats["total_matches"] > 0:
            print(colors.magenta("[STATS] Total: " + str(self.stats["total_matches"]) + " matches | "))
            print(colors.green("New: " + str(self.stats["total_new"]) + " | "))
            print(colors.blue("Updated: " + str(self.stats["total_updated"])))
        print(colors.blue("[SEASONS] " + ", ".join([f"{s[0]}/{s[1]}" for s in SEASONS])))

    def run_cycle(self):
        if not self.running:
            return

        self.stats["cycles"] += 1
        self.print_header(self.stats["cycles"])

        cycle_start = time.time()
        cycle_new = 0
        cycle_updated = 0
        cycle_total = 0

        for comp_id in ALL_COMPETITIONS.keys():
            if not self.running:
                break

            comp_name = ALL_COMPETITIONS.get(comp_id, comp_id)
            print(f"\n{colors.cyan('[COMP]')} {colors.bold(comp_name)} ({comp_id})")

            for start_year, end_year in SEASONS:
                if not self.running:
                    break

                season_key = f"{comp_id}_{start_year}"
                if season_key in self.processed_seasons:
                    print(f"  [SEASON] {start_year}/{end_year} - Already processed")
                    continue

                result = self.process_season(comp_id, start_year, end_year)

                if result["status"] == "success" and result["total"] > 0:
                    self.processed_seasons.add(season_key)

                cycle_new += result["new"]
                cycle_updated += result["updated"]
                cycle_total += result["total"]

                self.stats["total_new"] += result["new"]
                self.stats["total_updated"] += result["updated"]
                self.stats["total_matches"] += result["total"]

                if result["status"] == "error":
                    self.stats["errors"] += 1

                if self.running:
                    time.sleep(2)

        duration = time.time() - cycle_start
        print("\n" + "=" * 70)
        print(colors.bold(colors.green("[CYCLE #" + str(self.stats["cycles"]) + "] Completed in " + str(round(duration, 1)) + "s")))
        print("[SUMMARY] " + colors.green("NEW: " + str(cycle_new)) + " | " + colors.blue("UPD: " + str(cycle_updated)) + " | " + colors.magenta("TOTAL: " + str(cycle_total)))
        if self.stats["errors"] > 0:
            print(colors.yellow("[WARN] Errors: " + str(self.stats["errors"])))
        print("=" * 70)

        monitor = self.rate_limiter.get_monitor()
        stats = monitor.get_stats()
        print(colors.cyan("[API] Used: " + str(stats["used"]) + "/" + str(stats["max"]) + " requests"))
        print(colors.blue("[API] Reset in: " + str(round(stats["reset_in"])) + "s"))
        print(colors.magenta("[API] Success rate: " + str(round(stats["success_rate"], 1)) + "%"))

        self.last_run = datetime.now()

    def countdown_to_next_cycle(self):
        if not self.running:
            return

        interval = self.config["fetch_interval_minutes"] * 60
        print(f"\n{colors.yellow('[WAIT]')} Next cycle in {self.config['fetch_interval_minutes']} minutes...")

        for remaining in range(interval, 0, -10):
            if not self.running:
                break
            if remaining % 60 == 0:
                minutes = remaining // 60
                print(f"\r  [COUNTDOWN] {minutes:2d} minutes remaining", end="")
            elif remaining % 10 == 0:
                print(f"\r  [COUNTDOWN] {remaining:3d}s remaining", end="")
            time.sleep(10)

        print("\r  [COUNTDOWN] Starting next cycle...", end="")
        time.sleep(1)
        print("\r" + " " * 40 + "\r", end="")

    def run(self):
        print("\n" + "=" * 70)
        print(colors.bold(colors.cyan("HISTORICAL SCRAPER (football-data.org)")))
        print("=" * 70)
        print("[CONFIG] Competitions: " + str(len(ALL_COMPETITIONS)))
        print("[CONFIG] Interval: " + str(self.config["fetch_interval_minutes"]) + " minutes")
        print("[CONFIG] Seasons: " + ", ".join([f"{s[0]}/{s[1]}" for s in SEASONS]))
        print("[CONFIG] DB: " + self.config["db_path"] + f" (table `{TABLE_NAME}`)")
        print("[CONFIG] API Key: " + self.config["api_key"][:8] + "...")
        print("=" * 70)
        print(colors.green("[START] Running... (Press Ctrl+C to stop)"))
        print("=" * 70)

        while self.running:
            try:
                self.run_cycle()

                if self.running:
                    self.countdown_to_next_cycle()

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(colors.red("[ERROR] Cycle error: " + str(e)))
                if self.running:
                    print(colors.yellow("[WAIT] Waiting 60 seconds before retry..."))
                    time.sleep(60)

        print("\n" + colors.green("[STOP] Scraper stopped"))
        print(colors.magenta("[FINAL] Total matches: " + str(self.stats["total_matches"])))
        print(colors.green("[FINAL] New: " + str(self.stats["total_new"]) + " | " + colors.blue("Updated: " + str(self.stats["total_updated"]))))
        print(colors.blue("[FINAL] Cycles: " + str(self.stats["cycles"])))


def main():
    scraper = AutoScraper(CONFIG)
    scraper.run()


if __name__ == "__main__":
    main()
