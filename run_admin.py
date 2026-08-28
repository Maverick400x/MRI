import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame,
)

from config import APP_NAME, VERSION, GMAIL, BG, SURF, BORDER, TEXT, DIM2
from admin  import AdminTab


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
    w = AdminWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
