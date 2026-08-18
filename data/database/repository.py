"""
database/repository.py — Repository Pattern pour SQLite optimisé
================================================================
WAL mode, index automatiques, requêtes préparées, connexion thread-safe.
Compatible avec congobet.db et historical_results.db existants.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from core.config import get_config
from core.paths import get_paths
from database.cache import get_or_set
from security.logger import get_logger

log = get_logger("congobet.db")


class MatchRepository:
    """Accès optimisé aux matchs (Repository Pattern)."""

    def __init__(self, db_path: Path | None = None):
        """
        Initialise le repository.

        Args:
            db_path: Chemin SQLite ; défaut congobet.db.
        """
        self.db_path = db_path or get_paths().db
        self._ensure_indexes()

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager connexion SQLite avec WAL et row_factory.

        Yields:
            Connexion sqlite3 configurée.
        """
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        if get_config().db_wal_mode:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA temp_store=MEMORY")
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_indexes(self) -> None:
        """Crée les index manquants pour accélérer les requêtes fréquentes."""
        if not self.db_path.exists():
            return
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_matches_start_time ON matches(start_time)",
            "CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league)",
            "CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status)",
            "CREATE INDEX IF NOT EXISTS idx_odds_match_id ON odds(match_id)",
        ]
        try:
            with self.connection() as conn:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = {row[0] for row in cursor.fetchall()}
                if "matches" not in tables and "football_matches" not in tables:
                    return
                for idx_sql in indexes:
                    try:
                        conn.execute(idx_sql)
                    except sqlite3.OperationalError:
                        pass
                conn.commit()
        except Exception as e:
            log.debug("Index creation skipped: %s", e)

    def load_matches(
        self,
        competition_id: str | None = None,
        limit: int = 1000,
        use_cache: bool = True,
    ) -> list[dict]:
        """
        Charge les matchs (délègue à predictor.load_matches_from_db avec cache).

        Args:
            competition_id: Filtre ligue optionnel.
            limit: Nombre max de lignes.
            use_cache: Activer le cache TTL.

        Returns:
            Liste de dicts match.
        """
        ttl = get_config().db_cache_ttl_seconds

        def _load():
            from predictor import load_matches_from_db
            return load_matches_from_db(competition_id=competition_id, limit=limit)

        if use_cache:
            return get_or_set("matches", ttl, _load, competition_id, limit)
        return _load()

    def backup(self, dest: Path | None = None) -> Path:
        """
        Sauvegarde la base via SQLite backup API.

        Args:
            dest: Chemin destination ; défaut data_exports/backup_YYYYMMDD.db.

        Returns:
            Chemin du fichier backup créé.
        """
        dest = dest or get_paths().exports / f"backup_{self.db_path.stem}.db"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as src:
            dest_conn = sqlite3.connect(dest)
            src.backup(dest_conn)
            dest_conn.close()
        log.info("Backup créé: %s", dest)
        return dest
