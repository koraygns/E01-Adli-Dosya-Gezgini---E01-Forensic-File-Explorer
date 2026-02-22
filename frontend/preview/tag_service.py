"""
Etiket servisi (SQLite, kanıta dokunmaz).
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any


class TagService:
    """
    add_tag(file_id, tag), remove_tag(file_id, tag), list_tags(file_id),
    filter_by_tags(tags[]) → list of file_ids (for building a filtered CollectionModel).
    Persist in SQLite by default; interface allows swap to MongoDB.
    """

    def __init__(self, case_dir: str, evidence_id: str, db_path: str | None = None):
        self.case_dir = os.path.abspath(case_dir)
        self.evidence_id = evidence_id
        if db_path is None:
            from backend.engine.evidence.evidence_manager import EvidenceManager
            em = EvidenceManager()
            cache_dir = em.get_cache_dir(self.case_dir, self.evidence_id)
            db_path = os.path.join(cache_dir, "tags.sqlite")
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tags (file_id INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (file_id, tag))"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_file ON tags(file_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag)")

    def add_tag(self, file_id: int, tag: str) -> None:
        """Etiket ekle."""
        tag = (tag or "").strip()
        if not tag:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO tags (file_id, tag) VALUES (?, ?)", (file_id, tag))

    def remove_tag(self, file_id: int, tag: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM tags WHERE file_id = ? AND tag = ?", (file_id, tag))

    def list_tags(self, file_id: int) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT tag FROM tags WHERE file_id = ? ORDER BY tag", (file_id,))
            return [row[0] for row in cur.fetchall()]

    def filter_by_tags(self, tags: list[str], require_all: bool = False) -> list[int]:
        """
        Return file_ids that have the given tags.
        require_all: if True, file must have every tag; else any tag.
        """
        if not tags:
            return []
        with sqlite3.connect(self.db_path) as conn:
            if require_all:
                placeholders = ",".join("?" * len(tags))
                cur = conn.execute(
                    f"SELECT file_id FROM tags WHERE tag IN ({placeholders}) GROUP BY file_id HAVING COUNT(DISTINCT tag) = ?",
                    (*tags, len(tags)),
                )
            else:
                placeholders = ",".join("?" * len(tags))
                cur = conn.execute(
                    f"SELECT DISTINCT file_id FROM tags WHERE tag IN ({placeholders})",
                    tags,
                )
            return [row[0] for row in cur.fetchall()]
