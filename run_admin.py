import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QDialog, QLineEdit,
)
from PyQt6.QtCore import Qt

from config import (
    APP_NAME, VERSION, GMAIL, verify_admin_pin,
    BG, SURF, SURF2, BORDER, TEXT, DIM, DIM2, BLUE, RED, BEVEL_LT, BEVEL_DK,
)
from theme  import mkbtn, mklbl, R_SMALL
from admin  import AdminTab


class AdminLoginDialog(QDialog):
    """Gate access to the Admin Panel behind an Admin User ID + PIN — the
    standalone admin tool previously had no login check at all."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — Admin Login")
        self.setFixedSize(360, 340)
        self.setStyleSheet(f"QDialog{{background:{BG};}}")
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 26, 28, 24); lay.setSpacing(12)

        icon = QLabel("🔐"); icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size:34px;")
        lay.addWidget(icon)

        title = mklbl("Admin Login", TEXT, 17, bold=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        sub = mklbl("Restricted access — administrators only", DIM, 11)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(8)

        def _field(placeholder, pw=False):
            e = QLineEdit(); e.setPlaceholderText(placeholder); e.setFixedHeight(34)
            if pw: e.setEchoMode(QLineEdit.EchoMode.Password)
            e.setStyleSheet(f"""
                QLineEdit{{
                    background:{SURF2};color:{TEXT};border:1px solid {BORDER};
                    border-top-color:{BEVEL_DK};border-left-color:{BEVEL_DK};
                    border-bottom-color:{BEVEL_LT};border-right-color:{BEVEL_LT};
                    border-radius:{R_SMALL}px;padding:0 10px;font-size:13px;
                }}
                QLineEdit:focus{{border:1px solid {BLUE};background:#ffffff;}}
            """)
            return e

        lay.addWidget(mklbl("Admin User ID", DIM, 10.5))
        self.id_e = _field("Enter Admin ID")
        lay.addWidget(self.id_e)

        lay.addWidget(mklbl("PIN", DIM, 10.5))
        self.pin_e = _field("Enter Admin PIN", pw=True)
        self.pin_e.returnPressed.connect(self._try_login)
        lay.addWidget(self.pin_e)

        self.error_lbl = QLabel(""); self.error_lbl.setWordWrap(True)
        self.error_lbl.setStyleSheet(f"color:{RED};font-size:11px;")
        lay.addWidget(self.error_lbl)

        login_btn = mkbtn("Login", BLUE, wide=True, h=36)
        login_btn.clicked.connect(self._try_login)
        lay.addWidget(login_btn)
        lay.addStretch()

        self.id_e.setFocus()

    def _try_login(self):
        user_id = self.id_e.text().strip()
        pin     = self.pin_e.text().strip()
        if not user_id or not pin:
            self.error_lbl.setText("Enter both Admin User ID and PIN.")
            return
        if verify_admin_pin(user_id, pin):
            self.accept()
        else:
            self.error_lbl.setText("❌  Invalid Admin User ID or PIN.")
            self.pin_e.clear(); self.pin_e.setFocus()


class AdminWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — Admin Panel  v{VERSION}")
        self.setMinimumSize(1100, 750)
        self.setStyleSheet(f"QMainWindow, QWidget{{background:{BG};color:{TEXT};"
                            f"font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;"
                            f"font-size:13px;}}")
        self._build()

    def _build(self):
        cw = QWidget(); self.setCentralWidget(cw)
        root = QVBoxLayout(cw); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # Slim top bar: just a label showing Gmail status, since the admin
        # tool needs Gmail configured to send doctor-verification OTPs.
        tb = QFrame(); tb.setFixedHeight(48)
        tb.setStyleSheet(f"background:{SURF};border-bottom:1px solid {BORDER};")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(18, 0, 18, 0)
        title = QLabel("🗄️  MRI Secure Transfer — Admin Only")
        title.setStyleSheet(f"color:{TEXT};font-size:14px;font-weight:800;")
        tbl.addWidget(title)
        tbl.addStretch()

        self.gmail_lbl = QLabel("")
        self.gmail_lbl.setStyleSheet(f"color:{DIM2};font-size:11px;")
        tbl.addWidget(self.gmail_lbl)
        root.addWidget(tb)

        self.admin = AdminTab()
        root.addWidget(self.admin)

        self._update_gmail_label()

    def _update_gmail_label(self):
        if GMAIL.sender_email:
            self.gmail_lbl.setText(f"✉️  Gmail: {GMAIL.sender_email}")
        else:
            self.gmail_lbl.setText("✉️  Gmail not configured — doctor verification emails won't send")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    login = AdminLoginDialog()
    if login.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)   # cancelled or closed — never open the admin panel

    w = AdminWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
