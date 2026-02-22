"""
Evidence management: add evidence to case, manifest per evidence.
Evidence folder: manifest.json, cache/, logs/, temp/.
"""
import json
import os
import uuid


def _normalize_path(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


class EvidenceManager:
    def add_evidence(self, case_dir: str, e01_path: str) -> str:
        """
        Add E01 to case: create evidence/<evidence_id>/, manifest.json, cache/, logs/, temp/.
        Aynı klasördeki E02, E03... açılışta pyewf.glob ile otomatik bulunur.
        Returns evidence_id (UUID hex).
        """
        case_dir = os.path.abspath(case_dir)
        e01_path = _normalize_path(e01_path)
        if not os.path.isfile(e01_path):
            raise FileNotFoundError(f"E01 not found: {e01_path}")

        evidence_id = uuid.uuid4().hex
        evidence_path = os.path.join(case_dir, "evidence", evidence_id)
        os.makedirs(evidence_path, exist_ok=True)
        os.makedirs(os.path.join(evidence_path, "cache"), exist_ok=True)
        os.makedirs(os.path.join(evidence_path, "logs"), exist_ok=True)
        os.makedirs(os.path.join(evidence_path, "temp"), exist_ok=True)
        os.makedirs(os.path.join(evidence_path, "reports"), exist_ok=True)
        os.makedirs(os.path.join(evidence_path, "exports"), exist_ok=True)

        try:
            stat = os.stat(e01_path)
            file_size = stat.st_size
            last_modified = stat.st_mtime
        except OSError:
            file_size = 0
            last_modified = 0

        manifest = {
            "evidence_id": evidence_id,
            "original_e01_path": e01_path,
            "normalized_path": e01_path,
            "file_size": file_size,
            "last_modified": last_modified,
            "fast_hash_sha1": None,
            "partition_start": None,
            "partition_mode": None,
        }
        manifest_path = os.path.join(evidence_path, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        case_file = os.path.join(case_dir, "case.json")
        with open(case_file, "r", encoding="utf-8") as f:
            case_data = json.load(f)
        if evidence_id not in case_data["evidence_ids"]:
            case_data["evidence_ids"].append(evidence_id)
        with open(case_file, "w", encoding="utf-8") as f:
            json.dump(case_data, f, indent=2)

        return evidence_id

    def load_evidence_manifest(self, case_dir: str, evidence_id: str) -> dict:
        """Manifest yükle."""
        manifest_path = os.path.join(
            os.path.abspath(case_dir), "evidence", evidence_id, "manifest.json"
        )
        if not os.path.isfile(manifest_path):
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_evidence_dir(self, case_dir: str, evidence_id: str) -> str:
        """Kanıt klasörü yolu."""
        return os.path.join(os.path.abspath(case_dir), "evidence", evidence_id)

    def get_cache_dir(self, case_dir: str, evidence_id: str) -> str:
        """Kanıt cache yolu."""
        return os.path.join(self.get_evidence_dir(case_dir, evidence_id), "cache")
