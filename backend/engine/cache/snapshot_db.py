"""
Volume snapshot SQLite (sadece meta, içerik yok).
"""
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

def _int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class SnapshotDB:
    """Volume metadata SQLite önbelleği."""
    DB_FILENAME = "volume_snapshot.sqlite"

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path) if isinstance(db_path, str) else str(db_path)
        self._conn: sqlite3.Connection | None = None

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            # Worker thread'den oluşturulup GUI'den kullanılır
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def init_db(self) -> None:
        """Şema oluştur."""
        conn = self._ensure_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inode INTEGER NOT NULL,
                parent_inode INTEGER,
                name TEXT NOT NULL,
                is_dir INTEGER NOT NULL,
                size INTEGER NOT NULL,
                mtime INTEGER,
                atime INTEGER,
                ctime INTEGER,
                crtime INTEGER,
                flags INTEGER,
                deleted INTEGER NOT NULL DEFAULT 0,
                partition_start INTEGER,
                discovered_via TEXT,
                first_seen INTEGER,
                last_seen INTEGER,
                UNIQUE(inode)
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_inode);
            CREATE INDEX IF NOT EXISTS idx_nodes_inode ON nodes(inode);
            CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
            CREATE INDEX IF NOT EXISTS idx_nodes_deleted ON nodes(deleted);
        """)
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def upsert_nodes(
        self,
        parent_inode: int | None,
        nodes: list[dict],
        partition_start: int | None = None,
        discovered_via: str = "lazy",
    ) -> None:
        """Node ekle/güncelle."""
        if not nodes:
            return
        conn = self._ensure_conn()
        now = int(time.time())
        rows = []
        for n in nodes:
            rows.append((
                n.get("inode"),
                parent_inode,
                n.get("name", ""),
                1 if n.get("is_dir") else 0,
                int(n.get("size") or 0),
                _int_or_none(n.get("mtime")),
                _int_or_none(n.get("atime")),
                _int_or_none(n.get("ctime")),
                _int_or_none(n.get("crtime")),
                _int_or_none(n.get("flags")),
                1 if n.get("deleted") else 0,
                partition_start,
                discovered_via,
                now,
                now,
            ))
        conn.executemany(
            """
            INSERT INTO nodes (inode, parent_inode, name, is_dir, size, mtime, atime, ctime, crtime, flags, deleted, partition_start, discovered_via, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(inode) DO UPDATE SET
                parent_inode=excluded.parent_inode,
                name=excluded.name,
                is_dir=excluded.is_dir,
                size=excluded.size,
                mtime=excluded.mtime,
                atime=excluded.atime,
                ctime=excluded.ctime,
                crtime=excluded.crtime,
                flags=excluded.flags,
                deleted=excluded.deleted,
                partition_start=excluded.partition_start,
                discovered_via=excluded.discovered_via,
                last_seen=excluded.last_seen
            """,
            rows,
        )
        conn.commit()

    def get_children(self, parent_inode: int | None) -> list[dict]:
        """parent_inode çocukları (None=kök)."""
        conn = self._ensure_conn()
        if parent_inode is None:
            cur = conn.execute(
                "SELECT inode, parent_inode, name, is_dir, size, mtime, atime, ctime, crtime, flags, deleted FROM nodes WHERE parent_inode IS NULL ORDER BY name",
                (),
            )
        else:
            cur = conn.execute(
                "SELECT inode, parent_inode, name, is_dir, size, mtime, atime, ctime, crtime, flags, deleted FROM nodes WHERE parent_inode = ? ORDER BY name",
                (parent_inode,),
            )
        out = []
        for row in cur:
            out.append({
                "inode": row[0],
                "parent_inode": row[1],
                "name": row[2],
                "is_dir": bool(row[3]),
                "size": row[4],
                "mtime": row[5],
                "atime": row[6],
                "ctime": row[7],
                "crtime": row[8],
                "flags": row[9],
                "deleted": bool(row[10]),
            })
        return out

    def has_cached_children(self, parent_inode: int | None) -> bool:
        """Bu parent'ın cache'de çocuğu var mı."""
        conn = self._ensure_conn()
        if parent_inode is None:
            cur = conn.execute("SELECT 1 FROM nodes WHERE parent_inode IS NULL LIMIT 1")
        else:
            cur = conn.execute("SELECT 1 FROM nodes WHERE parent_inode = ? LIMIT 1", (parent_inode,))
        return cur.fetchone() is not None

    def get_node(self, inode: int) -> dict | None:
        """Tek node veya None."""
        conn = self._ensure_conn()
        cur = conn.execute(
            "SELECT inode, parent_inode, name, is_dir, size, mtime, atime, ctime, crtime, flags, deleted FROM nodes WHERE inode = ?",
            (inode,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "inode": row[0],
            "parent_inode": row[1],
            "name": row[2],
            "is_dir": bool(row[3]),
            "size": row[4],
            "mtime": row[5],
            "atime": row[6],
            "ctime": row[7],
            "crtime": row[8],
            "flags": row[9],
            "deleted": bool(row[10]),
        }

    def count_nodes(self) -> int:
        """Toplam önbellekteki node sayısı (cache dolu mu kontrolü)."""
        conn = self._ensure_conn()
        cur = conn.execute("SELECT COUNT(*) FROM nodes")
        return cur.fetchone()[0] or 0

    def search_nodes(
        self,
        name_like_pattern: str,
        root_inode: int | None = None,
    ) -> list[dict]:
        """
        Önbellekte (SQL) hızlı arama. E01'e dokunmaz.
        name_like_pattern: SQL LIKE kalıbı (örn. %jpg, %.jpg, %rapor%). % ve _ özel karakter.
        root_inode: None = tüm volume; int = sadece bu inode altındaki (recursive) eşleşenler.
        """
        if not name_like_pattern:
            return []
        conn = self._ensure_conn()
        sel = "inode, parent_inode, name, is_dir, size, mtime, atime, ctime, crtime, flags, deleted"
        # LOWER ile büyük/küçük harf duyarsız (örn. *.jpg = .JPG dosyaları)
        like_clause = "LOWER(name) LIKE LOWER(?)"
        if root_inode is None:
            cur = conn.execute(
                f"SELECT {sel} FROM nodes WHERE {like_clause} ORDER BY name",
                (name_like_pattern,),
            )
        else:
            # Sadece root_inode alt ağacındaki node'lar (recursive CTE)
            cur = conn.execute(
                f"""
                WITH RECURSIVE subtree(inode) AS (
                    SELECT ?
                    UNION ALL
                    SELECT n.inode FROM nodes n
                    INNER JOIN subtree s ON n.parent_inode = s.inode
                )
                SELECT {sel} FROM nodes
                WHERE inode IN (SELECT inode FROM subtree)
                  AND {like_clause}
                ORDER BY name
                """,
                (root_inode, name_like_pattern),
            )
        out = []
        for row in cur:
            out.append({
                "inode": row[0],
                "parent_inode": row[1],
                "name": row[2],
                "is_dir": bool(row[3]),
                "size": row[4],
                "mtime": row[5],
                "atime": row[6],
                "ctime": row[7],
                "crtime": row[8],
                "flags": row[9],
                "deleted": bool(row[10]),
            })
        return out
