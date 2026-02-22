import sys
import os
import logging
from datetime import datetime

sys.path.append(os.path.abspath("."))

# Video açınca konsol logunu azalt
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")
os.environ.setdefault("AV_LOG_LEVEL", "-8")

# Log önce konsola, case açılınca dosyaya yazar
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _setup_logging():
    """Önce konsol, case açılınca dosyaya da yaz."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    root.addHandler(ch)


def _add_case_log_file(case_dir: str, evidence_id: str | None):
    """Logu case cache klasörüne yönlendir."""
    root = logging.getLogger()
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    for h in root.handlers[:]:
        if isinstance(h, logging.FileHandler):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
    try:
        if evidence_id:
            from backend.engine.evidence.evidence_manager import EvidenceManager
            cache_dir = EvidenceManager().get_cache_dir(case_dir, evidence_id)
        else:
            cache_dir = os.path.join(os.path.abspath(case_dir), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        log_file = os.path.join(cache_dir, f"forensic_{datetime.now().strftime('%Y-%m-%d')}.log")
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(formatter)
        root.addHandler(fh)
        logging.info("Log dosyası: %s", log_file)
    except Exception as e:
        logging.warning("Case cache log dosyası açılamadı: %s", e)


_setup_logging()


def main():
    from PyQt6.QtWidgets import QApplication, QDialog
    from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
    from frontend.gui.case_dialog import CaseDialog
    from frontend.gui.main_window import MainWindow

    def _qt_message_handler(msg_type, context, message):
        msg = message or ""
        if "QObject::disconnect" in msg and "wildcard call disconnects" in msg:
            return
        if msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()

    qInstallMessageHandler(_qt_message_handler)
    app = QApplication(sys.argv)
    dialog = CaseDialog()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    case_dir = dialog.get_case_dir()
    evidence_id = dialog.get_evidence_id()
    if not case_dir or not os.path.isdir(case_dir):
        return
    _add_case_log_file(case_dir, evidence_id)
    logging.info("Case açıldı: %s — kanıt: %s", case_dir, evidence_id or "(yok)")
    window = MainWindow(case_dir, evidence_id=evidence_id)
    window.show()
    logging.info("Uygulama penceresi gösterildi.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
