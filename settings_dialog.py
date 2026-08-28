from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QDialogButtonBox, QLabel, QLineEdit, QFrame, QPushButton,
)
from PyQt6.QtCore import Qt

from config import (
    GMAIL, AI_CFG,
    BG, SURF, SURF2, BORDER, BLUE, GREEN, AMBER, PURPLE, TEXT, DIM,
)

# ── Settings dialog ───────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(530, 460)
        self.setStyleSheet(
            f"QDialog{{background:{SURF};color:{TEXT};}}"
            f"QLabel{{color:{TEXT};}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24,20,24,20); lay.setSpacing(12)

        title = QLabel("⚙️  Gmail SMTP Configuration")
        title.setStyleSheet(f"color:{BLUE};font-size:16px;font-weight:700;")
        lay.addWidget(title)

        note = QLabel(
            "Use a Gmail App Password — NOT your regular password.\n"
            "Enable at: myaccount.google.com → Security → App Passwords"
        )
        note.setStyleSheet(f"color:{DIM};font-size:12px;")
        note.setWordWrap(True)
        lay.addWidget(note)

        def _inp(ph, pw=False):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            e.setFixedHeight(38)
            if pw: e.setEchoMode(QLineEdit.EchoMode.Password)
            e.setStyleSheet(f"""
                QLineEdit{{background:{BG};color:{TEXT};border:1px solid {BORDER};
                           border-radius:2px;padding:0 10px;font-size:13px;}}
                QLineEdit:focus{{border:1px solid {BLUE};}}
            """)
            return e

        form = QFormLayout(); form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.email_e = _inp("yourname@gmail.com"); self.email_e.setText(GMAIL.sender_email)
        self.pass_e  = _inp("xxxx xxxx xxxx xxxx", pw=True); self.pass_e.setText(GMAIL.app_password)
        form.addRow(QLabel("Sender Gmail:"), self.email_e)
        form.addRow(QLabel("App Password:"), self.pass_e)
        for i in range(form.rowCount()):
            lbl_item = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
            if lbl_item and lbl_item.widget():
                lbl_item.widget().setStyleSheet(f"color:{TEXT};font-size:13px;")
        lay.addLayout(form)

        ai_title = QLabel("🤖  AI-Assisted Report (optional)")
        ai_title.setStyleSheet(f"color:{PURPLE};font-size:14px;font-weight:700;")
        lay.addWidget(ai_title)

        ai_note = QLabel(
            "Adds a draft narrative findings section to patient reports.\n"
            "Leave blank to skip — reports work fine without it."
        )
        ai_note.setStyleSheet(f"color:{DIM};font-size:11px;")
        ai_note.setWordWrap(True)
        lay.addWidget(ai_note)

        ai_form = QFormLayout(); ai_form.setSpacing(10)
        ai_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.ai_key_e = _inp("sk-ant-...", pw=True)
        self.ai_key_e.setText(AI_CFG.api_key)
        ai_form.addRow(QLabel("Anthropic API Key:"), self.ai_key_e)
        for i in range(ai_form.rowCount()):
            lbl_item = ai_form.itemAt(i, QFormLayout.ItemRole.LabelRole)
            if lbl_item and lbl_item.widget():
                lbl_item.widget().setStyleSheet(f"color:{TEXT};font-size:13px;")
        lay.addLayout(ai_form)

        # .env path indicator
        env_frame = QFrame()
        env_frame.setStyleSheet(
            f"background:{SURF2};border:1.5px solid {BORDER};"
            f"border-radius:2px;padding:2px;")
        ef_lay = QHBoxLayout(env_frame); ef_lay.setContentsMargins(10,6,10,6)
        ef_icon = QLabel("📄")
        ef_icon.setStyleSheet("border:none;font-size:14px;")
        ef_lay.addWidget(ef_icon)
        ef_col = QVBoxLayout(); ef_col.setSpacing(1)
        ef_title = QLabel("Saved to .env file")
        ef_title.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:700;border:none;background:transparent;")
        ef_path = QLabel(GMAIL.env_path)
        ef_path.setStyleSheet(f"color:{DIM};font-size:10px;font-family:monospace;border:none;")
        ef_path.setWordWrap(True)
        ef_col.addWidget(ef_title); ef_col.addWidget(ef_path)
        ef_lay.addLayout(ef_col)
        lay.addWidget(env_frame)

        # Warning
        warn = QLabel("⚠️  Credentials are stored in plain text in .env  —  "
                      "never commit .env to Git.")
        warn.setStyleSheet(f"color:{AMBER};font-size:11px;")
        warn.setWordWrap(True)
        lay.addWidget(warn)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.setStyleSheet(f"""
            QPushButton{{background:{BLUE};color:white;border:none;
                         border-radius:2px;padding:7px 22px;font-size:13px;}}
            QPushButton:hover{{background:{BLUE}cc;}}
        """)
        btns.accepted.connect(self._save); btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _save(self):
        GMAIL.sender_email = self.email_e.text().strip()
        GMAIL.app_password = self.pass_e.text().strip().replace(" ", "")
        GMAIL.persist()   # ← write back to .env
        AI_CFG.api_key = self.ai_key_e.text().strip()
        AI_CFG.persist()
        self.accept()


# ── Design constants ─────────────────────────────────────────────────────────