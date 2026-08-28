from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QStackedWidget,
    QScrollArea, QMessageBox, QTabWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui  import QPixmap, QIcon

from config  import (
    APP_NAME, VERSION, SHARED_FOLDER, DB, Session, LOGO_SVG,
    BG, SURF, SURF2, SURF3, BORDER,
    BLUE, CYAN, RED, TEXT, DIM, DIM2, BEVEL_LT, BEVEL_DK,
)
from theme           import mkbtn, mkbadge, RADIUS, R_SMALL, _lighten, _darken
from panels          import DoctorPanel, PatientPanel
from login           import LoginScreen, WelcomeScreen

class MainWindow(QMainWindow):
    SCREEN_LOGIN   = 0
    SCREEN_WELCOME = 1
    SCREEN_DOCTOR  = 2
    SCREEN_PATIENT = 3

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{VERSION}")
        self.setMinimumSize(1300, 860)
        self._apply_global_style()
        self._build()

    def _apply_global_style(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget{{
                background:{BG};color:{TEXT};
                font-family:'Helvetica Neue','Segoe UI','Tahoma',Arial,sans-serif;font-size:12.5px;
            }}
            QScrollBar:vertical{{background:{SURF2};width:15px;border:1px solid {BORDER};margin:0;}}
            QScrollBar::handle:vertical{{
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {SURF3},stop:0.5 {SURF},stop:1 {SURF3});
                border:1px solid {BORDER};border-radius:2px;min-height:24px;
            }}
            QScrollBar::handle:vertical:hover{{background:{_lighten(BLUE,0.5)};}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}
            QScrollBar:horizontal{{background:{SURF2};height:15px;border:1px solid {BORDER};margin:0;}}
            QScrollBar::handle:horizontal{{
                background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {SURF3},stop:0.5 {SURF},stop:1 {SURF3});
                border:1px solid {BORDER};border-radius:2px;min-width:24px;
            }}
            QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{{width:0;}}
            QGroupBox{{
                color:{DIM2};border:1px solid {_darken(BORDER,0.15)};
                border-top-color:{_darken(BORDER,0.2)};border-left-color:{_darken(BORDER,0.2)};
                border-bottom-color:{BEVEL_LT};border-right-color:{BEVEL_LT};
                border-radius:{RADIUS}px;margin-top:18px;
                font-size:11px;font-weight:700;letter-spacing:0.4px;
                padding:16px 14px 14px 14px;background:{SURF};
            }}
            QGroupBox::title{{
                subcontrol-origin:margin;left:14px;top:-1px;
                padding:1px 7px;color:{BLUE};background:{SURF};
            }}
            QLineEdit{{
                background:{SURF2};color:{TEXT};
                border:1px solid {BORDER};
                border-top-color:{_darken(BORDER,0.12)};border-left-color:{_darken(BORDER,0.12)};
                border-radius:{R_SMALL}px;
                padding:0 10px;font-size:12.5px;
            }}
            QLineEdit:focus{{border:1px solid {BLUE};background:#ffffff;}}
            QLineEdit:disabled{{background:{SURF};color:{DIM};}}
            QTextEdit{{background:{SURF};color:{TEXT};border:1px solid {_darken(BORDER,0.15)};
                border-top-color:{_darken(BORDER,0.2)};border-left-color:{_darken(BORDER,0.2)};
                border-bottom-color:{BEVEL_LT};border-right-color:{BEVEL_LT};
                border-radius:{RADIUS}px;}}
            QListWidget{{background:{SURF};color:{TEXT};border:1px solid {_darken(BORDER,0.15)};
                border-top-color:{_darken(BORDER,0.2)};border-left-color:{_darken(BORDER,0.2)};
                border-bottom-color:{BEVEL_LT};border-right-color:{BEVEL_LT};
                border-radius:{RADIUS}px;outline:none;}}
            QListWidget::item:selected{{background:{BLUE};color:white;}}
            QTabWidget::pane{{border:1px solid {BORDER};border-radius:{RADIUS}px;background:{SURF};margin-top:-1px;}}
            QTabBar::tab{{
                background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {SURF},stop:1 {SURF2});
                color:{DIM};border:1px solid {BORDER};border-bottom:none;
                border-radius:{RADIUS}px {RADIUS}px 0 0;padding:7px 20px;font-size:12px;font-weight:600;margin-right:1px;
            }}
            QTabBar::tab:selected{{
                background:{SURF};color:{BLUE};border-bottom:2px solid {BLUE};font-weight:700;
            }}
            QTabBar::tab:hover{{background:{SURF3};color:{TEXT};}}
            QProgressBar{{background:{SURF2};border:1px solid {_darken(BORDER,0.12)};border-radius:{R_SMALL}px;color:transparent;}}
            QProgressBar::chunk{{
                background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {_lighten(BLUE,0.12)},stop:0.5 {BLUE},stop:1 {_darken(BLUE,0.08)});
                border-radius:1px;margin:1px;
            }}
            QTableWidget{{background:{SURF};color:{TEXT};border:1px solid {_darken(BORDER,0.15)};
                gridline-color:{BORDER};font-size:12px;outline:none;}}
            QTableWidget::item{{padding:5px 10px;}}
            QTableWidget::item:selected{{background:{BLUE};color:white;}}
            QHeaderView::section{{
                background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {SURF},stop:1 {SURF3});
                color:{DIM2};border:none;
                border-right:1px solid {BORDER};border-bottom:1px solid {_darken(BORDER,0.15)};
                padding:6px 10px;font-size:11px;font-weight:700;letter-spacing:0.3px;
            }}
            QMessageBox{{background:{SURF};}} QDialog{{background:{BG};}}
            QStatusBar{{background:{SURF};color:{DIM};font-size:11px;border-top:1px solid {BORDER};}}
            QSplitter::handle{{background:{SURF2};border:1px solid {BORDER};}}
            QSplitter::handle:hover{{background:{_lighten(BLUE,0.6)};}}
            QToolTip{{background:#ffffe1;color:#000000;border:1px solid #000000;
                border-radius:0px;padding:3px 6px;font-size:11px;}}
        """)

    def _build(self):
        cw = QWidget(); self.setCentralWidget(cw)
        root = QVBoxLayout(cw); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # ── Top bar ───────────────────────────────────────────────────────
        tb = QFrame(); tb.setFixedHeight(52)
        tb.setStyleSheet(f"""
            QFrame{{
                background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {SURF},stop:1 {SURF3});
                border-bottom:1px solid {_darken(BORDER,0.15)};
            }}
        """)
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(20, 0, 20, 0); tbl.setSpacing(10)

        logo_row = QHBoxLayout(); logo_row.setSpacing(8)
        if LOGO_SVG.exists():
            self.setWindowIcon(QIcon(str(LOGO_SVG)))
            logo_icon = QLabel()
            logo_icon.setFixedSize(28, 28)
            logo_icon.setPixmap(
                QPixmap(str(LOGO_SVG)).scaled(
                    28, 28, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            logo_row.addWidget(logo_icon)
            logo = QLabel("MRI Secure Transfer")
        else:
            logo = QLabel("🏥  MRI Secure Transfer")
        logo.setStyleSheet(f"color:{TEXT};font-size:16px;font-weight:900;letter-spacing:0.3px;")
        logo_row.addWidget(logo)
        tbl.addLayout(logo_row)

        # Version badge
        ver = mkbadge(f"v{VERSION}", DIM, small=True); tbl.addWidget(ver)
        tbl.addStretch()

        self.session_info = QLabel("")
        self.session_info.setStyleSheet(
            f"color:{DIM2};font-size:11px;"
            f"background:{SURF2};border:1px solid {BORDER};"
            f"border-radius:{R_SMALL}px;padding:3px 10px;")
        tbl.addWidget(self.session_info)
        tbl.addSpacing(4)

        self.logout_btn = QPushButton("🚪  Logout"); self.logout_btn.setFixedHeight(26)
        self.logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_btn.setStyleSheet(f"""
            QPushButton{{
                background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {SURF},stop:1 {SURF2});
                color:{RED};border:1px solid {RED}70;border-radius:{R_SMALL}px;
                font-size:12px;padding:0 12px;font-weight:600;}}
            QPushButton:hover{{background:{RED}18;}}
            QPushButton:pressed{{background:{RED}30;padding-top:1px;}}
        """)
        self.logout_btn.setVisible(False)
        self.logout_btn.clicked.connect(self._logout)
        tbl.addWidget(self.logout_btn)
        root.addWidget(tb)

        # ── Stacked content ───────────────────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background:{BG};")

        self.login_screen = LoginScreen()
        self.login_screen.login_success.connect(self._on_login_success)
        self.stack.addWidget(self.login_screen)                     # 0

        self.welcome_screen = WelcomeScreen()
        self.welcome_screen.proceed.connect(self._show_workspace)
        self.stack.addWidget(self.welcome_screen)                   # 1

        self._doctor_built = self._patient_built = False
        self._dr_placeholder = QWidget()
        self._pt_placeholder = QWidget()
        self.stack.addWidget(self._dr_placeholder)                  # 2
        self.stack.addWidget(self._pt_placeholder)                  # 3
        root.addWidget(self.stack)

        self.statusBar().showMessage(
            "Log in as Doctor or Patient to begin")

    def _build_doctor_workspace(self):
        if self._doctor_built: return
        self._doctor_built = True
        outer, tabs = self._workspace_shell()

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"border:none;background:{BG};")
        self.doctor = DoctorPanel()
        self.doctor.sent.connect(self._on_transfer)
        self.doctor.populate_session()
        scroll.setWidget(self.doctor)

        tabs.addTab(scroll, "🩺  Doctor Workspace")
        tabs.tabBar().setVisible(False)

        self.stack.removeWidget(self._dr_placeholder)
        self.stack.insertWidget(self.SCREEN_DOCTOR, outer)

    def _build_patient_workspace(self):
        if self._patient_built: return
        self._patient_built = True
        outer, tabs = self._workspace_shell()

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"border:none;background:{BG};")
        self.patient = PatientPanel()
        self.patient._autofill_email()
        scroll.setWidget(self.patient)

        tabs.addTab(scroll, "👤  Patient Workspace")
        tabs.tabBar().setVisible(False)

        self.stack.removeWidget(self._pt_placeholder)
        self.stack.insertWidget(self.SCREEN_PATIENT, outer)

    def _workspace_shell(self):
        outer = QWidget(); outer.setStyleSheet(f"background:{BG};")
        lay = QVBoxLayout(outer); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        tabs = QTabWidget()
        tabs.setStyleSheet(f"""
            QTabWidget::pane{{border:none;background:{BG};margin-top:0px;}}
            QTabBar{{background:{SURF};border-bottom:1px solid {BORDER};}}
            QTabBar::tab{{
                background:transparent;color:{DIM};border:none;
                border-bottom:2px solid transparent;
                padding:10px 28px;font-size:13px;font-weight:600;margin-right:2px;
            }}
            QTabBar::tab:selected{{color:{TEXT};border-bottom:2px solid {BLUE};font-weight:700;}}
            QTabBar::tab:hover{{background:{SURF2};}}
        """)
        lay.addWidget(tabs)
        return outer, tabs

    def _on_login_success(self, role, user_doc):
        Session.set(role, user_doc)
        icon = "🩺" if role == "doctor" else "👤"
        uid  = user_doc.get("user_id","")
        name = user_doc.get("display_name", uid)
        self.session_info.setText(f"{icon} {name}  [{uid}]")
        self.logout_btn.setVisible(True)
        DB.log_session(role, "login_success", f"{role} [{uid}] via OTP")
        self.welcome_screen.populate(role, user_doc)
        self.stack.setCurrentIndex(self.SCREEN_WELCOME)
        self.statusBar().showMessage(f"✅  {role.title()} [{uid}] logged in")

    def _show_workspace(self, role):
        if role == "doctor":
            self._build_doctor_workspace()
            self.stack.setCurrentIndex(self.SCREEN_DOCTOR)
        else:
            self._build_patient_workspace()
            self.stack.setCurrentIndex(self.SCREEN_PATIENT)
        self.statusBar().showMessage(
            f"Session active  ·  MongoDB: "
            f"{'✅ Connected' if DB.connected else '❌ ' + DB.status_msg}"
            f"  ·  Shared folder: {SHARED_FOLDER}")

    def _logout(self):
        role = "doctor" if Session.doctor else "patient"
        doc  = Session.current(role) or {}
        uid  = doc.get("user_id","—")
        reply = QMessageBox.question(
            self, "Logout",
            f"Log out {role.title()} [{uid}]?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        DB.log_session(role, "logout", f"{role} [{uid}] logged out")
        Session.clear(role)
        self.login_screen.reset_role(role)
        self.session_info.setText("")
        self.logout_btn.setVisible(False)
        self.stack.setCurrentIndex(self.SCREEN_LOGIN)
        self.statusBar().showMessage(f"{role.title()} [{uid}] logged out")

    def _on_tab_change(self, idx): pass

    def _on_transfer(self):
        if self._patient_built and hasattr(self, "patient"):
            self.patient.refresh()
        self.statusBar().showMessage("✅  Bundle ready — patient can decrypt")
        DB.log_session("system","transfer_complete","Encrypted file written")