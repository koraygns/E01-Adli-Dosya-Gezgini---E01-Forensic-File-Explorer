"""
Case session: imaj + SnapshotDB. Cache-first liste, read-only.
"""
import fnmatch
import json
import os
import threading
from collections import deque

from backend.engine.io.ewf_reader import open_ewf_image
from backend.engine.volume.volume_parser import parse_partitions
from backend.engine.fs.lazy_tree import LazyTreeEngine, LazyFSNode
from backend.engine.metadata.inspector import ForensicInspector
from backend.engine.evidence.evidence_manager import EvidenceManager
from backend.engine.cache.snapshot_db import SnapshotDB

BATCH_SIZE = 5000


def _node_dict_to_lazy_fs_node(d: dict) -> LazyFSNode:
    return LazyFSNode(
        name=d.get("name", ""),
        inode=d["inode"],
        is_dir=d.get("is_dir", False),
        size=d.get("size", 0),
    )


class EngineSession:
    """Case session: manifest'ten aç, cache-first tree."""

    def __init__(self, case_dir: str, evidence_id: str):
        self.case_dir = os.path.abspath(case_dir)
        self.evidence_id = evidence_id
        self.evidence_manager = EvidenceManager()
        self.manifest = self.evidence_manager.load_evidence_manifest(self.case_dir, evidence_id)
        self.e01_path = os.path.normpath(os.path.abspath(self.manifest["normalized_path"]))
        if not os.path.isfile(self.e01_path):
            raise FileNotFoundError(f"E01 not found: {self.e01_path}")

        try:
            self.img = open_ewf_image(self.e01_path)
            self.partitions = parse_partitions(self.img)
        except RuntimeError as e:
            err = str(e).lower()
            if "segment" in err or "missing" in err or "offset" in err or "chunk" in err or "parça" in err:
                raise RuntimeError(
                    "E01 parça dosyaları eksik. Tüm segment dosyalarının (E01, E02, E03, ...) "
                    "aynı klasörde olduğundan emin olun; sadece ilk dosyayı (E01) eklemiş olabilirsiniz."
                ) from e
            raise
        self.data_partition = None
        # 0 boyutlu partition atlanır
        def _has_size(p):
            return getattr(p, "length", 0) and p.length > 0

        for p in self.partitions:
            if not _has_size(p):
                continue
            desc = (p.desc or "").upper()
            if any(fs in desc for fs in ["FAT", "NTFS", "EXFAT", "EXT", "HFS", "APFS"]):
                self.data_partition = p
                break
        if not self.data_partition:
            for p in self.partitions:
                if not _has_size(p):
                    continue
                try:
                    LazyTreeEngine(self.img, p.start)
                    self.data_partition = p
                    break
                except Exception:
                    continue
        if not self.data_partition:
            try:
                LazyTreeEngine(self.img, 0)
                self.data_partition = type("RawPartition", (), {"start": 0, "desc": "RAW Filesystem (no partition table)"})()
            except Exception:
                raise RuntimeError("No mountable partition and raw FS at 0 failed.")

        self.partition_start = self.data_partition.start
        self.lazy = LazyTreeEngine(self.img, self.data_partition.start)
        self.volume_label = self.lazy.get_volume_label()
        self.inspector = ForensicInspector(self.lazy.fs, self.img)

        cache_dir = self.evidence_manager.get_cache_dir(self.case_dir, evidence_id)
        db_path = os.path.join(cache_dir, SnapshotDB.DB_FILENAME)
        self.snapshot = SnapshotDB(db_path)
        self.snapshot.init_db()

        # pytsk3 thread-safe değil, kilit kullan
        self._fs_lock = threading.Lock()

        self.manifest["partition_start"] = self.partition_start
        self.manifest["partition_mode"] = "raw" if self.partition_start == 0 else "partition"
        _save_manifest(self.case_dir, self.evidence_id, self.manifest)

    def list_root(self):
        """Kök (imajdan)."""
        return self.lazy.list_directory(None)

    def list_children(self, inode: int):
        """Çocuklar (imajdan, cache yok)."""
        with self._fs_lock:
            return self.lazy.list_directory(inode)

    def list_root_cached(self, log_callback=None):
        """
        Root children: cache-first. On hit return from DB; on miss read image, upsert, return.
        log_callback ile Türkçe mesaj (önbellek hit/miss) isteğe bağlı.
        Returns list of LazyFSNode.
        """
        if self.snapshot.has_cached_children(None):
            if log_callback:
                log_callback("Önbellek: kök klasör zaten yüklü (root).")
            rows = self.snapshot.get_children(None)
            return [_node_dict_to_lazy_fs_node(r) for r in rows]
        if log_callback:
            log_callback("Önbellek yok: kök klasör imajdan okunuyor (root).")
        with self._fs_lock:
            nodes_meta = self.lazy.list_directory_meta(None)
        if nodes_meta:
            self.snapshot.upsert_nodes(
                None,
                nodes_meta,
                partition_start=self.partition_start,
                discovered_via="lazy",
            )
        return [_node_dict_to_lazy_fs_node(n) for n in nodes_meta]

    def list_children_cached(self, inode: int, log_callback=None):
        """İnode çocukları: cache-first."""
        if self.snapshot.has_cached_children(inode):
            if log_callback:
                log_callback(f"Önbellek: klasör zaten yüklü (inode={inode}).")
            rows = self.snapshot.get_children(inode)
            return [_node_dict_to_lazy_fs_node(r) for r in rows]
        if log_callback:
            log_callback(f"Önbellek yok: imajdan okunuyor (inode={inode}).")
        with self._fs_lock:
            nodes_meta = self.lazy.list_directory_meta(inode)
        if nodes_meta:
            self.snapshot.upsert_nodes(
                inode,
                nodes_meta,
                partition_start=self.partition_start,
                discovered_via="lazy",
            )
        return [_node_dict_to_lazy_fs_node(n) for n in nodes_meta]

    def _query_to_like_pattern(self, query: str) -> str:
        """
        Kullanıcı aramasını SQL LIKE kalıbına çevirir.
        * -> % (wildcard); *.jpg -> %.jpg; aksi halde substring: kelime -> %kelime%.
        % ve _ özel karakter olarak escape edilir (\\% ve \\_).
        """
        q = (query or "").strip()
        if not q:
            return ""
        # Önce \ sonra % ve _ escape et (SQL LIKE için)
        q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        # * -> SQL wildcard %
        q = q.replace("*", "%")
        # Hiç % yoksa substring: her iki yana % ekle
        if "%" not in q:
            q = f"%{q}%"
        return q

    def search_in_directory(self, from_inode: int | None, query: str, log_callback=None):
        """
        Dizinde tam arama: önce önbellekte (SQL) arar (hızlı, E01'e dokunmaz).
        Önbellekte sonuç yoksa veya cache çok boşsa E01 üzerinden BFS fallback.
        query: *.jpg, %kelime%, veya düz metin (substring).
        Returns list of node dicts (inode, name, is_dir, size, mtime, ...).
        """
        if not query or not query.strip():
            return []
        like_pattern = self._query_to_like_pattern(query)
        if not like_pattern:
            return []

        # 1) Önce önbellekte ara (E01'e dokunmaz)
        try:
            results = self.snapshot.search_nodes(like_pattern, root_inode=from_inode)
            if log_callback:
                log_callback(f"Arama önbellekte yapıldı (E01 kullanılmadı): {len(results)} sonuç.")
            if results:
                return results
            # Önbellekte hiç node var mı?
            cached_count = self.snapshot.count_nodes()
            if cached_count > 0:
                # Cache var ama eşleşme yok
                return []
            # Cache boş: E01 fallback
            if log_callback:
                log_callback("Önbellek boş; arama E01 üzerinden yapılıyor (yavaş olabilir)...")
        except Exception as e:
            if log_callback:
                log_callback(f"Önbellek araması atlandı: {e}; E01 üzerinden deneniyor...")

        # 2) Fallback: E01 üzerinden BFS (yavaş)
        q_lower = query.strip().lower()
        results = []
        queue = deque([from_inode])
        seen = set()
        while queue:
            parent = queue.popleft()
            if parent in seen:
                continue
            seen.add(parent)
            try:
                if parent is None:
                    children = self.list_root_cached(log_callback=log_callback)
                else:
                    children = self.list_children_cached(parent, log_callback=log_callback)
            except Exception as e:
                if log_callback:
                    log_callback(f"Arama atlandı (inode={parent}): {e}")
                continue
            for node in children:
                name = (node.name or "").strip()
                name_lower = name.lower()
                # Wildcard uyumu: * -> her şey; *.jpg -> .jpg ile biten
                if "*" in q_lower:
                    if not fnmatch.fnmatch(name_lower, q_lower):
                        continue
                else:
                    if q_lower not in name_lower:
                        continue
                row = {
                    "inode": node.inode,
                    "name": name,
                    "is_dir": node.is_dir,
                    "size": getattr(node, "size", 0) or 0,
                    "parent_inode": parent,
                }
                full = self.snapshot.get_node(node.inode)
                if full:
                    row.update(full)
                results.append(row)
                if node.is_dir and node.inode not in seen:
                    queue.append(node.inode)
        if log_callback and results:
            log_callback(f"E01 araması tamamlandı: {len(results)} sonuç.")
        return results

    def build_full_snapshot(self, stop_flag=None, progress_callback=None):
        """Tüm volume BFS ile tara, node'ları kaydet."""
        if progress_callback:
            progress_callback("[SNAPSHOT] Starting full volume snapshot (BFS)...")
        queue = deque([None])
        seen = {None}
        total = 0
        batch = []
        while queue:
            if stop_flag and stop_flag():
                if progress_callback:
                    progress_callback("[SNAPSHOT] Cancelled.")
                break
            parent = queue.popleft()
            try:
                with self._fs_lock:
                    nodes_meta = self.lazy.list_directory_meta(parent)
            except Exception as e:
                if progress_callback:
                    progress_callback(f"[SNAPSHOT] Skip parent {parent}: {e}")
                continue
            if nodes_meta:
                self.snapshot.upsert_nodes(
                    parent,
                    nodes_meta,
                    partition_start=self.partition_start,
                    discovered_via="full_scan",
                )
                total += len(nodes_meta)
                for n in nodes_meta:
                    if n["is_dir"] and n["inode"] not in seen:
                        seen.add(n["inode"])
                        queue.append(n["inode"])
            if progress_callback and total > 0 and total % 10000 == 0:
                progress_callback(f"[SNAPSHOT] Indexed {total} nodes...")
        if progress_callback:
            progress_callback(f"[SNAPSHOT] Done. Total nodes: {total}")

    def read_file_content(self, inode: int, offset: int = 0, max_size: int | None = None) -> bytes | None:
        """Dosya içeriği oku."""
        with self._fs_lock:
            return self.inspector.read_file_content(inode, offset=offset, max_size=max_size)

    def get_metadata(self, inode: int, name: str | None = None):
        meta = self.inspector.get_basic_metadata(inode)
        if meta is None:
            return None
        meta["name"] = name if name is not None else meta.get("name", "")
        # Forensic/EXIF: resim ve video dosyalarında GPS, cihaz, tarih vb.
        if meta.get("type") == "File" and name:
            from backend.engine.metadata.forensic_extractor import (
                extract_forensic_metadata,
                EXIF_READ_LIMIT,
                VIDEO_READ_LIMIT,
                VIDEO_EXTENSIONS,
            )
            ext = "." + (name.rsplit(".", 1)[-1].lower() if "." in name else "")
            read_limit = VIDEO_READ_LIMIT if ext in VIDEO_EXTENSIONS else EXIF_READ_LIMIT
            try:
                data = self.read_file_content(inode, offset=0, max_size=read_limit)
                if data:
                    forensic = extract_forensic_metadata(data, name)
                    meta["forensic"] = forensic
            except Exception:
                meta["forensic"] = {}
        else:
            meta["forensic"] = {}
        return meta

    def get_hashes(self, inode: int):
        return self.inspector.compute_hashes(inode)

    def is_deleted(self, inode: int):
        return self.inspector.is_deleted(inode)

    def validate_signature(self, inode: int, name: str | None = None):
        return self.inspector.validate_signature(inode, name=name)

    def close(self):
        if getattr(self, "snapshot", None):
            self.snapshot.close()

    def save_manifest(self) -> None:
        """Manifest'i diske yaz."""
        _save_manifest(self.case_dir, self.evidence_id, self.manifest)


def _save_manifest(case_dir: str, evidence_id: str, manifest: dict) -> None:
    evidence_path = os.path.join(os.path.abspath(case_dir), "evidence", evidence_id)
    path = os.path.join(evidence_path, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
