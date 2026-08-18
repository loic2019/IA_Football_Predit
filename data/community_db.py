"""
community_db.py — Profils, messagerie et stats des parieurs
=================================================================
Base dédiée `community.db`, séparée de `congobet.db` (aucun risque de
collision de schéma avec les scrapers). Ce module gère :
- les profils utilisateurs (liés à un compte Firebase Auth par firebase_uid)
- le salon de discussion public
- les messages privés entre 2 parieurs
- le suivi de pronostics + calcul du taux de réussite personnel

La vérification des résultats des pronostics suivis lit `congobet.db` en
lecture seule (aucune écriture) via les mêmes fonctions que common.py, donc
elle reste compatible quel que soit le scraper utilisé.
"""

import sqlite3
from pathlib import Path
from datetime import datetime

from admin_config import ADMIN_EMAILS

COMMUNITY_DB_PATH = Path("community.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(COMMUNITY_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn, table: str, column: str, col_type: str, default_sql: str = None):
    """ALTER TABLE ... ADD COLUMN idempotent (SQLite ne supporte pas IF NOT EXISTS ici)."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        stmt = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
        if default_sql is not None:
            stmt += f" DEFAULT {default_sql}"
        conn.execute(stmt)


def init_community_db() -> None:
    conn = _connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid    TEXT UNIQUE NOT NULL,
            email           TEXT NOT NULL,
            pseudo          TEXT UNIQUE NOT NULL,
            avatar_emoji    TEXT DEFAULT '⚽',
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            channel      TEXT NOT NULL CHECK (channel IN ('public', 'dm')),
            sender_id    INTEGER NOT NULL REFERENCES users(id),
            receiver_id  INTEGER REFERENCES users(id),
            content      TEXT NOT NULL,
            created_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel);
        CREATE INDEX IF NOT EXISTS idx_messages_dm ON messages(sender_id, receiver_id);

        CREATE TABLE IF NOT EXISTS followed_picks (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES users(id),
            match_id       TEXT NOT NULL,
            home           TEXT,
            away           TEXT,
            prediction     TEXT,
            confidence     REAL,
            cote           REAL,
            followed_at    TEXT NOT NULL,
            result_checked INTEGER DEFAULT 0,
            was_correct    INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_followed_user ON followed_picks(user_id);

        CREATE TABLE IF NOT EXISTS notifications (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id),
            type         TEXT NOT NULL,
            title        TEXT NOT NULL,
            message      TEXT NOT NULL,
            link_page    TEXT,
            is_read      INTEGER DEFAULT 0,
            created_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read);
        """
    )

    # Colonnes ajoutées après la 1ere version (admin, annonces, suivi de lecture) :
    # ajout idempotent pour ne jamais casser une base déjà existante.
    _ensure_column(conn, "users", "is_admin", "INTEGER", "0")
    _ensure_column(conn, "users", "last_public_read_id", "INTEGER", "0")
    _ensure_column(conn, "users", "is_banned", "INTEGER", "0")
    _ensure_column(conn, "users", "phone", "TEXT")
    _ensure_column(conn, "users", "avatar_image_b64", "TEXT")
    _ensure_column(conn, "messages", "is_announcement", "INTEGER", "0")
    _ensure_column(conn, "messages", "is_read", "INTEGER", "0")

    conn.commit()
    conn.close()


# ============================================================================
# PROFILS
# ============================================================================

def avatar_html(user: dict, size: int = 40) -> str:
    """Rendu HTML de l'avatar : photo (si uploadée) sinon emoji, dans un cercle."""
    if user and user.get("avatar_image_b64"):
        return (
            f'<img src="data:image/png;base64,{user["avatar_image_b64"]}" '
            f'style="width:{size}px;height:{size}px;border-radius:50%;object-fit:cover;'
            f'border:2px solid rgba(255,255,255,0.1);" />'
        )
    emoji = (user or {}).get("avatar_emoji") or "⚽"
    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:50%;background:var(--surface-hover,#171f30);'
        f'display:flex;align-items:center;justify-content:center;font-size:{int(size*0.55)}px;'
        f'border:2px solid rgba(255,255,255,0.1);">{emoji}</div>'
    )

def get_user_by_uid(firebase_uid: str):
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE firebase_uid = ?", (firebase_uid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def pseudo_taken(pseudo: str) -> bool:
    conn = _connect()
    try:
        row = conn.execute("SELECT 1 FROM users WHERE pseudo = ?", (pseudo,)).fetchone()
        return row is not None
    finally:
        conn.close()


def create_user_profile(
    firebase_uid: str,
    email: str,
    pseudo: str,
    avatar_emoji: str = "⚽",
    phone: str = None,
    avatar_image_b64: str = None,
):
    is_admin = 1 if email and email.lower() in [e.lower() for e in ADMIN_EMAILS] else 0
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO users
               (firebase_uid, email, pseudo, avatar_emoji, created_at, is_admin, phone, avatar_image_b64)
               VALUES (?,?,?,?,?,?,?,?)""",
            (firebase_uid, email or "", pseudo, avatar_emoji, datetime.now().isoformat(), is_admin, phone, avatar_image_b64),
        )
        conn.commit()
        return get_user_by_uid(firebase_uid)
    finally:
        conn.close()


def sync_admin_status(user_id: int, email: str) -> None:
    """Promeut automatiquement en admin si l'email est dans admin_config.ADMIN_EMAILS.
    Ne démote jamais automatiquement (un retrait se fait volontairement via le panel admin)."""
    if email.lower() in [e.lower() for e in ADMIN_EMAILS]:
        conn = _connect()
        try:
            conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
            conn.commit()
        finally:
            conn.close()


def update_profile(
    user_id: int,
    pseudo: str = None,
    avatar_emoji: str = None,
    avatar_image_b64: str = None,
    clear_avatar_image: bool = False,
    phone: str = None,
):
    conn = _connect()
    try:
        if pseudo:
            conn.execute("UPDATE users SET pseudo = ? WHERE id = ?", (pseudo, user_id))
        if avatar_emoji:
            conn.execute("UPDATE users SET avatar_emoji = ? WHERE id = ?", (avatar_emoji, user_id))
        if avatar_image_b64:
            conn.execute("UPDATE users SET avatar_image_b64 = ? WHERE id = ?", (avatar_image_b64, user_id))
        if clear_avatar_image:
            conn.execute("UPDATE users SET avatar_image_b64 = NULL WHERE id = ?", (user_id,))
        if phone:
            conn.execute("UPDATE users SET phone = ? WHERE id = ?", (phone, user_id))
        conn.commit()
    finally:
        conn.close()


def list_users(exclude_id: int = None):
    conn = _connect()
    try:
        if exclude_id:
            rows = conn.execute(
                "SELECT id, pseudo, avatar_emoji FROM users WHERE id != ? ORDER BY pseudo", (exclude_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT id, pseudo, avatar_emoji FROM users ORDER BY pseudo").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_by_id(user_id: int):
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ============================================================================
# MESSAGERIE — SALON PUBLIC
# ============================================================================

def post_public_message(user_id: int, content: str, is_announcement: bool = False):
    content = (content or "").strip()
    if not content:
        return
    conn = _connect()
    try:
        banned = conn.execute("SELECT is_banned FROM users WHERE id = ?", (user_id,)).fetchone()
        if banned and banned["is_banned"]:
            return
        conn.execute(
            "INSERT INTO messages (channel, sender_id, receiver_id, content, created_at, is_announcement) "
            "VALUES ('public', ?, NULL, ?, ?, ?)",
            (user_id, content, datetime.now().isoformat(), int(is_announcement)),
        )
        conn.commit()
    finally:
        conn.close()


def list_public_messages(limit: int = 100):
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT m.id, m.content, m.created_at, m.is_announcement, u.pseudo, u.avatar_emoji, u.avatar_image_b64
            FROM messages m JOIN users u ON u.id = m.sender_id
            WHERE m.channel = 'public'
            ORDER BY m.created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_unread_public_count(user_id: int) -> int:
    conn = _connect()
    try:
        user = conn.execute("SELECT last_public_read_id FROM users WHERE id = ?", (user_id,)).fetchone()
        last_read = user["last_public_read_id"] if user else 0
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE channel = 'public' AND id > ? AND sender_id != ?",
            (last_read, user_id),
        ).fetchone()[0]
        return count
    finally:
        conn.close()


def mark_public_read(user_id: int) -> None:
    conn = _connect()
    try:
        max_id = conn.execute("SELECT MAX(id) FROM messages WHERE channel = 'public'").fetchone()[0] or 0
        conn.execute("UPDATE users SET last_public_read_id = ? WHERE id = ?", (max_id, user_id))
        conn.commit()
    finally:
        conn.close()


# ============================================================================
# MESSAGERIE — PRIVÉE (DM)
# ============================================================================

def send_direct_message(sender_id: int, receiver_id: int, content: str):
    content = (content or "").strip()
    if not content:
        return
    conn = _connect()
    try:
        banned = conn.execute("SELECT is_banned FROM users WHERE id = ?", (sender_id,)).fetchone()
        if banned and banned["is_banned"]:
            return
        conn.execute(
            "INSERT INTO messages (channel, sender_id, receiver_id, content, created_at, is_read) VALUES ('dm', ?, ?, ?, ?, 0)",
            (sender_id, receiver_id, content, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    # Notification pour le destinataire — réutilise le système de pop-up déjà
    # en place (auto_cycle_worker / coupon_tracker) pour que les messages
    # privés déclenchent aussi une alerte, pas seulement les pronostics.
    try:
        sender = get_user_by_id(sender_id)
        sender_name = sender["pseudo"] if sender else "Quelqu'un"
        create_notification(
            user_id=receiver_id,
            type="dm_received",
            title=f"✉️ Nouveau message de {sender_name}",
            message=content[:80] + ("…" if len(content) > 80 else ""),
            link_page="Communauté",
        )
    except Exception:
        pass


def list_direct_messages(user_id: int, other_id: int, limit: int = 200):
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT m.id, m.content, m.created_at, m.sender_id, u.pseudo, u.avatar_emoji
            FROM messages m JOIN users u ON u.id = m.sender_id
            WHERE m.channel = 'dm'
              AND ((m.sender_id = ? AND m.receiver_id = ?) OR (m.sender_id = ? AND m.receiver_id = ?))
            ORDER BY m.created_at ASC
            LIMIT ?
            """,
            (user_id, other_id, other_id, user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_unread_dm_count(user_id: int) -> int:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE channel='dm' AND receiver_id=? AND is_read=0",
            (user_id,),
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def mark_dm_read(user_id: int, other_id: int) -> None:
    """Marque comme lus tous les messages reçus de other_id dans cette conversation."""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE messages SET is_read=1 WHERE channel='dm' AND receiver_id=? AND sender_id=? AND is_read=0",
            (user_id, other_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_conversations(user_id: int):
    """Renvoie la liste des interlocuteurs avec qui l'utilisateur a échangé, triés par dernier message."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT
                CASE WHEN m.sender_id = ? THEN m.receiver_id ELSE m.sender_id END AS other_id,
                MAX(m.created_at) AS last_at
            FROM messages m
            WHERE m.channel = 'dm' AND (m.sender_id = ? OR m.receiver_id = ?)
            GROUP BY other_id
            ORDER BY last_at DESC
            """,
            (user_id, user_id, user_id),
        ).fetchall()
        conversations = []
        for row in rows:
            other = get_user_by_id(row["other_id"])
            if not other:
                continue
            last_msg = conn.execute(
                """
                SELECT content, sender_id FROM messages
                WHERE channel = 'dm' AND created_at = ?
                  AND ((sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?))
                LIMIT 1
                """,
                (row["last_at"], user_id, other["id"], other["id"], user_id),
            ).fetchone()
            preview = ""
            if last_msg:
                prefix = "Toi : " if last_msg["sender_id"] == user_id else ""
                preview = f"{prefix}{last_msg['content'][:40]}"
            unread_row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE channel='dm' AND receiver_id=? AND sender_id=? AND is_read=0",
                (user_id, other["id"]),
            ).fetchone()
            conversations.append({
                **other, "last_at": row["last_at"], "preview": preview,
                "unread": unread_row[0] if unread_row else 0,
            })
        return conversations
    finally:
        conn.close()


# ============================================================================
# PRONOSTICS SUIVIS + STATS PERSO
# ============================================================================

def follow_pick(user_id: int, match_id: str, home: str, away: str, prediction: str, confidence: float, cote: float):
    conn = _connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM followed_picks WHERE user_id = ? AND match_id = ?", (user_id, match_id)
        ).fetchone()
        if exists:
            return False
        conn.execute(
            """INSERT INTO followed_picks
               (user_id, match_id, home, away, prediction, confidence, cote, followed_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (user_id, match_id, home, away, prediction, confidence, cote, datetime.now().isoformat()),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def list_followed_picks(user_id: int):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM followed_picks WHERE user_id = ? ORDER BY followed_at DESC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def refresh_followed_picks_results(user_id: int) -> int:
    """
    Vérifie les pronostics suivis pas encore validés contre les résultats réels
    et met à jour was_correct. Renvoie le nombre de pronostics nouvellement
    validés.

    Utilise le même filet à 3 niveaux que le règlement des coupons
    (coupon_tracker._lookup_result : congobet.db -> historical_results.db ->
    API-Football) — avant ce correctif, ça ne regardait QUE congobet.db, qui
    n'a quasiment jamais de résultat rempli (voir coupon_tracker.py), donc
    les pronostics suivis ne se validaient quasiment jamais non plus.
    """
    from common import get_db_connection
    from coupon_tracker import _lookup_result

    conn = _connect()
    try:
        pending = conn.execute(
            "SELECT * FROM followed_picks WHERE user_id = ? AND result_checked = 0", (user_id,)
        ).fetchall()
        if not pending:
            return 0

        cb_conn = get_db_connection()
        if not cb_conn:
            return 0

        updated = 0
        for pick in pending:
            res = _lookup_result(cb_conn, pick["match_id"], pick["home"] or "", pick["away"] or "", "")
            if res is None:
                continue

            actual = res["result"]
            was_correct = int(actual == pick["prediction"])
            conn.execute(
                "UPDATE followed_picks SET result_checked = 1, was_correct = ? WHERE id = ?",
                (was_correct, pick["id"]),
            )
            updated += 1

            if was_correct:
                create_notification(
                    user_id=user_id,
                    type="pick_won",
                    title="🎉 Pronostic gagnant !",
                    message=f"{pick['home']} vs {pick['away']} — ton pronostic ({pick['prediction']}) était le bon !",
                    link_page="Profil",
                )

        cb_conn.close()
        conn.commit()
        return updated
    finally:
        conn.close()


# ============================================================================
# NOTIFICATIONS
# ============================================================================

def create_notification(user_id: int | None, type: str, title: str, message: str, link_page: str = None) -> None:
    """
    Crée une notification. user_id=None => notification globale, visible par
    tout le monde (ex: "le coupon du jour a fait 7/8 !").
    """
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO notifications (user_id, type, title, message, link_page, created_at)
               VALUES (?,?,?,?,?,?)""",
            (user_id, type, title, message, link_page, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def list_notifications(user_id: int, limit: int = 20) -> list[dict]:
    """Notifications personnelles + globales (user_id IS NULL) pour cet utilisateur, plus récentes d'abord."""
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT * FROM notifications WHERE user_id = ? OR user_id IS NULL
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_unread_notification_count(user_id: int) -> int:
    conn = _connect()
    try:
        row = conn.execute(
            """SELECT COUNT(*) FROM notifications
               WHERE (user_id = ? OR user_id IS NULL) AND is_read = 0""",
            (user_id,),
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def mark_notifications_read(user_id: int) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? OR user_id IS NULL",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def get_user_stats(user_id: int) -> dict:
    conn = _connect()
    try:
        user = conn.execute("SELECT created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        messages_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE sender_id = ?", (user_id,)
        ).fetchone()[0]
        picks = conn.execute(
            "SELECT result_checked, was_correct FROM followed_picks WHERE user_id = ?", (user_id,)
        ).fetchall()

        followed_count = len(picks)
        checked = [p for p in picks if p["result_checked"]]
        correct = [p for p in checked if p["was_correct"]]
        success_rate = (len(correct) / len(checked) * 100) if checked else None

        return {
            "member_since": user["created_at"] if user else None,
            "messages_count": messages_count,
            "followed_count": followed_count,
            "checked_count": len(checked),
            "correct_count": len(correct),
            "success_rate": success_rate,
        }
    finally:
        conn.close()


# ============================================================================
# PANEL ADMINISTRATEUR
# ============================================================================

def is_user_admin(user_id: int) -> bool:
    conn = _connect()
    try:
        row = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row and row["is_admin"])
    finally:
        conn.close()


def set_admin(user_id: int, is_admin: bool) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id))
        conn.commit()
    finally:
        conn.close()


def set_banned(user_id: int, is_banned: bool) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE users SET is_banned = ? WHERE id = ?", (int(is_banned), user_id))
        conn.commit()
    finally:
        conn.close()


def list_all_users_admin() -> list[dict]:
    """Liste complète des utilisateurs avec compteurs, pour le panel admin."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT u.id, u.pseudo, u.email, u.avatar_emoji, u.avatar_image_b64, u.created_at, u.is_admin, u.is_banned,
                   (SELECT COUNT(*) FROM messages m WHERE m.sender_id = u.id) AS messages_count,
                   (SELECT COUNT(*) FROM followed_picks f WHERE f.user_id = u.id) AS followed_count
            FROM users u
            ORDER BY u.created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_message(message_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()
    finally:
        conn.close()


def list_recent_messages_admin(limit: int = 100) -> list[dict]:
    """Tous les messages récents (public + privés) pour modération, avec pseudo émetteur/destinataire."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT m.id, m.channel, m.content, m.created_at, m.is_announcement,
                   su.pseudo AS sender_pseudo, ru.pseudo AS receiver_pseudo
            FROM messages m
            JOIN users su ON su.id = m.sender_id
            LEFT JOIN users ru ON ru.id = m.receiver_id
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def admin_overview_stats() -> dict:
    """Vue d'ensemble communauté pour le panel admin."""
    conn = _connect()
    try:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        public_messages = conn.execute("SELECT COUNT(*) FROM messages WHERE channel = 'public'").fetchone()[0]
        dm_messages = conn.execute("SELECT COUNT(*) FROM messages WHERE channel = 'dm'").fetchone()[0]
        total_followed = conn.execute("SELECT COUNT(*) FROM followed_picks").fetchone()[0]
        banned_count = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1").fetchone()[0]
        admin_count = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]
        return {
            "total_users": total_users,
            "total_messages": total_messages,
            "public_messages": public_messages,
            "dm_messages": dm_messages,
            "total_followed": total_followed,
            "banned_count": banned_count,
            "admin_count": admin_count,
        }
    finally:
        conn.close()


# Initialise la base au premier import
init_community_db()
