"""
Önizleme önbelleği (case cache). Kanıta yazmaz.
"""
from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.engine.pipeline.engine_session import EngineSession


class CacheLayer:
    """Case/evidence cache yolları."""

    def __init__(self, case_dir: str, evidence_id: str, base_subdir: str = "preview"):
        self.case_dir = os.path.abspath(case_dir)
        self.evidence_id = evidence_id
        self.base_subdir = base_subdir
        self._root: str | None = None

    def get_cache_root(self, session: EngineSession | None = None) -> str:
        """Cache kök yolu."""
        if self._root is not None:
            return self._root
        if session is not None:
            self._root = os.path.join(
                session.evidence_manager.get_cache_dir(self.case_dir, self.evidence_id),
                self.base_subdir,
            )
        else:
            from backend.engine.evidence.evidence_manager import EvidenceManager
            em = EvidenceManager()
            cache_dir = em.get_cache_dir(self.case_dir, self.evidence_id)
            self._root = os.path.join(cache_dir, self.base_subdir)
        os.makedirs(self._root, exist_ok=True)
        return self._root

    def path_for_inode(self, inode: int, suffix: str, session: EngineSession | None = None) -> str:
        """İnode için cache yolu."""
        root = self.get_cache_root(session)
        return os.path.join(root, f"inode_{inode}{suffix}")

    def path_for_content_hash(self, content_hash: str, suffix: str, session: EngineSession | None = None) -> str:
        """Hash ile cache yolu."""
        root = self.get_cache_root(session)
        safe = content_hash[:32] if len(content_hash) > 32 else content_hash
        return os.path.join(root, f"hash_{safe}{suffix}")

    @staticmethod
    def compute_content_hash(data: bytes) -> str:
        """İçerik hash (SHA256)."""
        return hashlib.sha256(data).hexdigest()
