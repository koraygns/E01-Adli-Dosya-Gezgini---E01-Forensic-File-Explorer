"""
Etiketler QSettings'te saklanır. Tanım: isim, kısayol, renk. Atama: evidence_id, inode, etiket, not.
"""
import json
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor

SETTINGS_ORG = "ForensicAxiom"
SETTINGS_APP = "Tags"
KEY_DEFINITIONS = "tag_definitions"
KEY_ASSIGNMENTS = "tag_assignments"

DEFAULT_COLORS = ["#3b82f6", "#ef4444", "#22c55e", "#eab308", "#a855f7", "#ec4899", "#06b6d4", "#f97316"]


def _settings() -> QSettings:
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, SETTINGS_ORG, SETTINGS_APP)


def load_definitions() -> list[dict]:
    """Etiket tanımları."""
    s = _settings()
    raw = s.value(KEY_DEFINITIONS)
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_definitions(defs: list[dict]) -> None:
    _settings().setValue(KEY_DEFINITIONS, json.dumps(defs, ensure_ascii=False))


def load_assignments() -> list[dict]:
    """Atamalar: [{evidence_id, inode, tag_name, note}, ...]"""
    s = _settings()
    raw = s.value(KEY_ASSIGNMENTS)
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_assignments(assignments: list[dict]) -> None:
    _settings().setValue(KEY_ASSIGNMENTS, json.dumps(assignments, ensure_ascii=False))


def add_assignment(evidence_id: str, inode: int, tag_name: str, note: str = "") -> None:
    a = load_assignments()
    a.append({"evidence_id": evidence_id, "inode": int(inode), "tag_name": tag_name, "note": note or ""})
    save_assignments(a)


def remove_assignment(evidence_id: str, inode: int, tag_name: str) -> None:
    a = load_assignments()
    a = [x for x in a if not (x.get("evidence_id") == evidence_id and x.get("inode") == inode and x.get("tag_name") == tag_name)]
    save_assignments(a)


def get_assignments_for_evidence(evidence_id: str) -> list[dict]:
    return [x for x in load_assignments() if x.get("evidence_id") == evidence_id]


def get_tag_color(definitions: list[dict], tag_name: str) -> str:
    for d in definitions:
        if d.get("name") == tag_name:
            return d.get("color") or "#6b7280"
    return "#6b7280"


def has_assignment(evidence_id: str, inode: int, tag_name: str) -> bool:
    """Bu inode'da bu etiket var mı?"""
    for a in load_assignments():
        if (a.get("evidence_id") == evidence_id and
                a.get("inode") == int(inode) and
                a.get("tag_name") == tag_name):
            return True
    return False


def get_tag_color_for_inode(evidence_id: str, inode: int) -> str | None:
    """İnode'un ilk etiket rengi; yoksa None."""
    defs = load_definitions()
    for a in load_assignments():
        if a.get("evidence_id") != evidence_id or a.get("inode") != int(inode):
            continue
        return get_tag_color(defs, a.get("tag_name", ""))
    return None
