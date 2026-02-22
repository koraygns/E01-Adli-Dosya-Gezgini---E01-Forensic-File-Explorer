"""
Case management: create/open case folder, validate structure.
Case folder layout: case.json, evidence/<id>/, logs/, temp/, reports/, exports/.
"""
import json
import os
from datetime import datetime

APP_VERSION = "1.0.0"
DEFAULT_BASE_DIR = "cases"


def _default_temp_path(case_dir: str) -> str:
    return os.path.join(case_dir, "temp")


class CaseManager:
    def __init__(self, base_dir: str = DEFAULT_BASE_DIR):
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)

    def create_case(self, case_name: str) -> str:
        """Case klasörü oluştur."""
        case_id = case_name.replace(" ", "_").lower()
        case_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in case_id)
        case_path = os.path.join(self.base_dir, case_id)
        os.makedirs(case_path, exist_ok=True)
        os.makedirs(os.path.join(case_path, "evidence"), exist_ok=True)
        os.makedirs(os.path.join(case_path, "logs"), exist_ok=True)
        os.makedirs(os.path.join(case_path, "temp"), exist_ok=True)
        os.makedirs(os.path.join(case_path, "reports"), exist_ok=True)
        os.makedirs(os.path.join(case_path, "exports"), exist_ok=True)

        case_data = {
            "case_name": case_name,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "app_version": APP_VERSION,
            "default_temp_path": _default_temp_path(case_path),
            "evidence_ids": [],
        }
        case_file = os.path.join(case_path, "case.json")
        with open(case_file, "w", encoding="utf-8") as f:
            json.dump(case_data, f, indent=2)
        return case_path

    def create_case_in_folder(self, folder_path: str, case_name: str | None = None) -> str:
        """Klasörde case oluştur."""
        case_path = os.path.abspath(folder_path)
        os.makedirs(case_path, exist_ok=True)
        os.makedirs(os.path.join(case_path, "evidence"), exist_ok=True)
        os.makedirs(os.path.join(case_path, "logs"), exist_ok=True)
        os.makedirs(os.path.join(case_path, "temp"), exist_ok=True)
        os.makedirs(os.path.join(case_path, "reports"), exist_ok=True)
        os.makedirs(os.path.join(case_path, "exports"), exist_ok=True)
        name = case_name or os.path.basename(case_path) or "New Case"
        case_data = {
            "case_name": name,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "app_version": APP_VERSION,
            "default_temp_path": _default_temp_path(case_path),
            "evidence_ids": [],
        }
        case_file = os.path.join(case_path, "case.json")
        with open(case_file, "w", encoding="utf-8") as f:
            json.dump(case_data, f, indent=2)
        return case_path

    def open_case(self, case_dir: str) -> dict:
        """
        Open existing case: read case.json, validate structure.
        Returns case data dict. Raises if invalid.
        """
        case_dir = os.path.abspath(case_dir)
        if not self.validate_structure(case_dir):
            raise ValueError(f"Invalid case structure: {case_dir}")
        case_file = os.path.join(case_dir, "case.json")
        with open(case_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def validate_structure(self, case_dir: str) -> bool:
        """Case yapısını doğrula."""
        case_dir = os.path.abspath(case_dir)
        case_file = os.path.join(case_dir, "case.json")
        if not os.path.isfile(case_file):
            return False
        try:
            with open(case_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False
        return isinstance(data.get("evidence_ids"), list) and "case_name" in data
