"""Persistent session storage backed by SQLite.

Replaces the in-memory dict with a durable store so sessions survive
server restarts and tab switches. Conversation history is stored as
JSON alongside session metadata.

The store also supports conversation summarization: when history grows
beyond a threshold, older messages are compressed into a summary that
preserves key context without consuming the full token budget.
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from agent.models import (
    AgentSession,
    ExecutionResult,
    FileChange,
    ChangeType,
    SessionStatus,
)

logger = logging.getLogger(__name__)

# Default path for the session database
DEFAULT_DB_PATH = "data/sessions.db"


class SessionStore:
    """SQLite-backed session persistence.

    Thread-safe: uses a per-thread connection via threading.local().
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._local = threading.local()

        # Ensure parent directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Create tables on first init
        self._init_db()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local SQLite connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id     TEXT PRIMARY KEY,
                workspace_path TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'planning',
                error          TEXT,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_conv_session
                ON conversation_history(session_id);

            CREATE TABLE IF NOT EXISTS conversation_summaries (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT NOT NULL,
                summary         TEXT NOT NULL,
                messages_covered INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_summary_session
                ON conversation_summaries(session_id);

            CREATE TABLE IF NOT EXISTS file_changes (
                change_id        TEXT PRIMARY KEY,
                session_id       TEXT NOT NULL,
                file_path        TEXT NOT NULL,
                change_type      TEXT NOT NULL,
                original_content TEXT,
                new_content      TEXT,
                diff             TEXT NOT NULL DEFAULT '',
                applied          INTEGER NOT NULL DEFAULT 0,
                created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_changes_session
                ON file_changes(session_id);
            """
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def save_session(self, session: AgentSession) -> None:
        """Insert or update a session."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO sessions (session_id, workspace_path, status, error,
                                  created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                workspace_path = excluded.workspace_path,
                status         = excluded.status,
                error          = excluded.error,
                updated_at     = excluded.updated_at
            """,
            (
                session.session_id,
                session.workspace_path,
                session.status.value,
                session.error,
                session.created_at.isoformat(),
                session.updated_at.isoformat(),
            ),
        )
        conn.commit()

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Load a session by ID, including its conversation history."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()

        if row is None:
            return None

        session = AgentSession(
            session_id=row["session_id"],
            workspace_path=row["workspace_path"],
            status=SessionStatus(row["status"]),
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

        # Load conversation history
        session.conversation_history = self.get_history(session_id)

        # Load file changes into execution_result
        changes = self.get_file_changes(session_id)
        if changes:
            session.execution_result = ExecutionResult(
                plan_id="agent_loop",
                status="completed",
                completed_tasks=["agent_loop"],
                failed_tasks=[],
                all_changes=changes,
            )

        return session

    def delete_session(self, session_id: str) -> None:
        """Delete a session and all related data."""
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM conversation_history WHERE session_id = ?",
            (session_id,),
        )
        conn.execute(
            "DELETE FROM conversation_summaries WHERE session_id = ?",
            (session_id,),
        )
        conn.execute(
            "DELETE FROM file_changes WHERE session_id = ?",
            (session_id,),
        )
        conn.execute(
            "DELETE FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()

    def list_sessions(
        self, workspace_path: Optional[str] = None, limit: int = 50
    ) -> List[Dict]:
        """List recent sessions, optionally filtered by workspace."""
        conn = self._get_conn()
        if workspace_path:
            rows = conn.execute(
                """SELECT session_id, workspace_path, status, created_at, updated_at
                   FROM sessions
                   WHERE workspace_path = ?
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (workspace_path, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT session_id, workspace_path, status, created_at, updated_at
                   FROM sessions
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()

        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Conversation history
    # ------------------------------------------------------------------

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """Append a message to a session's conversation history."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO conversation_history (session_id, role, content, created_at)
               VALUES (?, ?, ?, ?)""",
            (session_id, role, content, datetime.now().isoformat()),
        )
        conn.commit()

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """Get full conversation history for a session."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT role, content FROM conversation_history
               WHERE session_id = ?
               ORDER BY id ASC""",
            (session_id,),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def get_recent_history(
        self, session_id: str, limit: int = 20
    ) -> List[Dict[str, str]]:
        """Get the most recent N messages for a session."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT role, content FROM (
                   SELECT id, role, content FROM conversation_history
                   WHERE session_id = ?
                   ORDER BY id DESC
                   LIMIT ?
               ) sub ORDER BY id ASC""",
            (session_id, limit),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def get_message_count(self, session_id: str) -> int:
        """Get total number of messages in a session."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_history WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # Conversation summaries
    # ------------------------------------------------------------------

    def save_summary(
        self, session_id: str, summary: str, messages_covered: int
    ) -> None:
        """Save a conversation summary."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO conversation_summaries
               (session_id, summary, messages_covered, created_at)
               VALUES (?, ?, ?, ?)""",
            (session_id, summary, messages_covered, datetime.now().isoformat()),
        )
        conn.commit()

    def get_latest_summary(self, session_id: str) -> Optional[str]:
        """Get the most recent summary for a session."""
        conn = self._get_conn()
        row = conn.execute(
            """SELECT summary FROM conversation_summaries
               WHERE session_id = ?
               ORDER BY id DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
        return row["summary"] if row else None

    # ------------------------------------------------------------------
    # File changes
    # ------------------------------------------------------------------

    def save_file_changes(
        self, session_id: str, changes: List[FileChange]
    ) -> None:
        """Save file changes for a session."""
        conn = self._get_conn()
        for change in changes:
            conn.execute(
                """INSERT INTO file_changes
                   (change_id, session_id, file_path, change_type,
                    original_content, new_content, diff, applied)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(change_id) DO UPDATE SET
                       applied = excluded.applied""",
                (
                    change.change_id,
                    session_id,
                    change.file_path,
                    change.change_type.value,
                    change.original_content,
                    change.new_content,
                    change.diff,
                    1 if change.applied else 0,
                ),
            )
        conn.commit()

    def get_file_changes(self, session_id: str) -> List[FileChange]:
        """Load file changes for a session."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM file_changes
               WHERE session_id = ?
               ORDER BY rowid ASC""",
            (session_id,),
        ).fetchall()

        return [
            FileChange(
                change_id=r["change_id"],
                file_path=r["file_path"],
                change_type=ChangeType(r["change_type"]),
                original_content=r["original_content"],
                new_content=r["new_content"],
                diff=r["diff"],
                applied=bool(r["applied"]),
            )
            for r in rows
        ]

    def mark_changes_applied(
        self, session_id: str, change_ids: List[str]
    ) -> int:
        """Mark specific file changes as applied. Returns count updated."""
        if not change_ids:
            return 0
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in change_ids)
        cursor = conn.execute(
            f"""UPDATE file_changes SET applied = 1
                WHERE session_id = ? AND change_id IN ({placeholders})""",
            [session_id] + change_ids,
        )
        conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the thread-local connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
