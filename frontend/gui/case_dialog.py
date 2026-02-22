"""
Başlangıç: yeni imaj ekle veya mevcut case aç.
"""
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


# Minik ve kapat sembolleri
MINIMIZE_CHAR = "\u2212"   # − (minus)
CLOSE_CHAR = "\u00D7"     # × (times)


class CaseDialog(QDialog):
    """İmaj seç veya case aç."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Başlangıç")
        self.case_dir = None
        self.evidence_id = None

        flags = (
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setWindowFlags(flags)
        self.setFixedSize(620, 440)

        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(28, 28, 28, 28)

        # Başlık ve butonlar
        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        title = QLabel("Başlangıç")
        title.setObjectName("mainTitle")
        top_row.addWidget(title)
        top_row.addStretch()
        self.btn_minimize = QPushButton(MINIMIZE_CHAR)
        self.btn_minimize.setObjectName("winBtn")
        self.btn_minimize.setFixedSize(40, 40)
        self.btn_minimize.setToolTip("Simge durumuna küçült")
        self.btn_minimize.clicked.connect(self.showMinimized)
        self.btn_close = QPushButton(CLOSE_CHAR)
        self.btn_close.setObjectName("winBtn")
        self.btn_close.setFixedSize(40, 40)
        self.btn_close.setToolTip("Kapat")
        self.btn_close.clicked.connect(self.reject)
        top_row.addWidget(self.btn_minimize)
        top_row.addWidget(self.btn_close)
        layout.addLayout(top_row)

        subtitle = QLabel("Yeni imaj ekleyin veya kayıtlı bir case açın.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        # İki seçenek kartı
        cards_row = QHBoxLayout()
        cards_row.setSpacing(24)
        card_left = self._make_card(
            "Yeni imaj ile başla",
            "E01 imajı seçin (aynı klasördeki E02, E03... otomatik algılanır). Case klasörü belirleyin.",
            "İmaj seç",
            self._on_new_image,
        )
        card_right = self._make_card(
            "Case aç",
            "Daha önce kaydettiğiniz case klasörünü seçin. Veriler SQL'den yüklenir.",
            "Case aç",
            self._on_open_case,
        )
        card_left.setMinimumSize(260, 220)
        card_right.setMinimumSize(260, 220)
        cards_row.addWidget(card_left, 1)
        cards_row.addWidget(card_right, 1)
        layout.addLayout(cards_row, 1)

        self._apply_theme()

    def _make_card(self, header: str, description: str, button_text: str, callback):
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        ly = QVBoxLayout(card)
        ly.setSpacing(16)
        ly.setContentsMargins(24, 24, 24, 24)
        lbl_header = QLabel(header)
        lbl_header.setObjectName("cardHeader")
        lbl_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_header.setWordWrap(True)
        ly.addWidget(lbl_header)
        lbl_desc = QLabel(description)
        lbl_desc.setObjectName("cardDesc")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_desc.setWordWrap(True)
        lbl_desc.setMinimumHeight(48)
        ly.addWidget(lbl_desc)
        ly.addStretch()
        btn = QPushButton(button_text)
        btn.setObjectName("cardBtn")
        btn.setMinimumHeight(44)
        btn.clicked.connect(callback)
        ly.addWidget(btn)
        return card

    def _apply_theme(self):
        font_win = QFont()
        font_win.setPointSize(18)
        font_win.setBold(False)
        self.btn_minimize.setFont(font_win)
        self.btn_close.setFont(font_win)

        self.setStyleSheet("""
            QDialog { background-color: #252528; }
            QLabel#mainTitle { color: #f0f0f0; font-size: 20px; font-weight: 500; }
            QLabel#subtitle { color: #9a9a9c; font-size: 13px; }
            QFrame#card {
                background-color: #2d2d30;
                border: 1px solid #3d3d40;
            }
            QLabel#cardHeader { color: #f0f0f0; font-size: 14px; font-weight: 500; }
            QLabel#cardDesc { color: #9a9a9c; font-size: 12px; }
            QPushButton#cardBtn {
                background-color: #3d3d40;
                color: #f0f0f0;
                border: 1px solid #4d4d50;
                padding: 10px 18px;
                font-size: 13px;
            }
            QPushButton#cardBtn:hover { background-color: #454548; }
            QPushButton#cardBtn:pressed { background-color: #353538; }
            QPushButton#winBtn {
                background-color: #3d3d40;
                color: #e0e0e2;
                border: 1px solid #4d4d50;
                padding: 0;
                font-size: 18px;
            }
            QPushButton#winBtn:hover { background-color: #454548; }
            QPushButton#winBtn:pressed { background-color: #353538; }
        """)

    def _on_new_image(self):
        e01_path, _ = QFileDialog.getOpenFileName(
            self, "E01 İmajı Seç", "", "E01 Dosyaları (*.E01 *.e01)"
        )
        if not e01_path:
            return
        e01_path = os.path.normpath(os.path.abspath(e01_path))
        case_folder = QFileDialog.getExistingDirectory(
            self, "Case klasörü seçin (mevcut veya yeni case için)"
        )
        if not case_folder:
            return
        case_folder = os.path.normpath(os.path.abspath(case_folder))
        case_json = os.path.join(case_folder, "case.json")
        try:
            from backend.engine.case.case_manager import CaseManager
            from backend.engine.evidence.evidence_manager import EvidenceManager
            cm = CaseManager()
            if os.path.isfile(case_json):
                self.case_dir = case_folder
            else:
                self.case_dir = cm.create_case_in_folder(case_folder)
            em = EvidenceManager()
            self.evidence_id = em.add_evidence(self.case_dir, e01_path)
            self.accept()
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Hata", f"İmaj case'e eklenemedi: {e}")

    def _on_open_case(self):
        case_folder = QFileDialog.getExistingDirectory(self, "Case klasörü seçin")
        if not case_folder:
            return
        case_folder = os.path.normpath(os.path.abspath(case_folder))
        case_json = os.path.join(case_folder, "case.json")
        if not os.path.isfile(case_json):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Uyarı", "Bu klasör geçerli bir case değil (case.json bulunamadı)."
            )
            return
        try:
            from backend.engine.case.case_manager import CaseManager
            if not CaseManager().validate_structure(case_folder):
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Uyarı", "Bu klasör geçerli bir case yapısında değil.")
                return
            self.case_dir = case_folder
            self.evidence_id = None
            self.accept()
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Hata", f"Case açılamadı: {e}")

    def get_case_dir(self):
        return self.case_dir

    def get_evidence_id(self):
        return self.evidence_id
