"""
security/logger.py — Journalisation structurée production
==========================================================
Logs rotatifs, format JSON-compatible, intégration avec le dossier logs/.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.paths import get_paths


def setup_logging(level: str = "INFO", name: str = "congobet") -> logging.Logger:
    """
    Configure le logger racine avec console UTF-8 + fichier rotatif.

    Args:
        level: Niveau logging (DEBUG, INFO, WARNING, ERROR).
        name: Nom du logger applicatif.

    Returns:
        Logger configuré prêt à l'emploi.
    """
    log_dir = get_paths().logs
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "congobet_ai.log"

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        pass

    return logger


def get_logger(name: str = "congobet") -> logging.Logger:
    """
    Retourne un logger enfant (crée le parent si nécessaire).

    Args:
        name: Suffixe du logger (ex: 'congobet.ensemble').

    Returns:
        logging.Logger configuré.
    """
    setup_logging()
    return logging.getLogger(name)
