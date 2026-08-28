from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QLineEdit, QTabWidget, QMessageBox, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from config import (
    GMAIL, DB, Session, LOGIN_OTP_STORE, OTP_LENGTH, VERSION,
    BLUE, RED, GREEN, AMBER, BEVEL_LT, BEVEL_DK,
)
from workers import LoginEmailWorker
from theme   import mkbtn, mklbl, _lighten, _darken

# ── Classic-chrome theme tokens (local to these two screens only) ──────────
L_BG     = "#e8e8ea"
L_SURF   = "#f4f4f4"
L_SURF2  = "#fbfbfb"
L_BORDER = "#a8a8ac"
L_TEXT   = "#1c1c1e"
L_DIM    = "#5a5a5e"
ACCENT   = BLUE          # single accent for both roles

_SUBTITLE = {"doctor": "Access your secure dashboard",
             "patient": "Access your encrypted MRI scans"}
_CONTACT  = {"doctor": "Don't have an account?  Contact Administrator",
             "patient": "Don't have access?  Contact your doctor"}


def _hr() -> QFrame:
    f = QFrame(); f.setFixedHeight(1)
    f.setStyleSheet(f"background:{L_BORDER};border:none;")
    return f


def _scrollable_center(parent: QWidget, bg: str) -> QVBoxLayout:
    """
    Wraps `parent`'s content in a QScrollArea so nothing ever clips or
    overlaps on small/narrow windows — the content scrolls instead.
    Returns the QVBoxLayout to add the centered card into.
    """
    root = QVBoxLayout(parent)
    root.setContentsMargins(0, 0, 0, 0)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(f"QScrollArea{{background:{bg};border:none;}}")
    root.addWidget(scroll)

    container = QWidget()
    container.setStyleSheet(f"background:{bg};")
    outer = QVBoxLayout(container)
    outer.setContentsMargins(24, 40, 24, 40)
    outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
    scroll.setWidget(container)
    return outer


def _responsive_card(min_w: int = 320, max_w: int = 480) -> QFrame:
    """A card that shrinks down to min_w on narrow windows instead of a
    fixed pixel width."""
    card = QFrame()
    card.setMinimumWidth(min_w)
    card.setMaximumWidth(max_w)
    card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    return card


def _field(placeholder: str, mono: bool = False, pw: bool = False, h: int = 26) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setFixedHeight(h)
    if pw: e.setEchoMode(QLineEdit.EchoMode.Password)
    if mono:
        e.setStyleSheet(f"""
            QLineEdit{{
                background:{L_SURF2};color:{L_TEXT};
                border:1px solid {L_BORDER};
                border-top-color:{_darken(L_BORDER,0.1)};border-left-color:{_darken(L_BORDER,0.1)};
                border-radius:2px;
                padding:0 12px;font-size:16px;font-weight:700;
                font-family:'Courier New',monospace;letter-spacing:6px;
            }}
            QLineEdit:focus{{border:1.5px solid {ACCENT};}}
        """)
    else:
        e.setStyleSheet(f"""
            QLineEdit{{
                background:{L_SURF2};color:{L_TEXT};
                border:1px solid {L_BORDER};
                border-top-color:{_darken(L_BORDER,0.1)};border-left-color:{_darken(L_BORDER,0.1)};
                border-radius:2px;
                padding:0 10px;font-size:12.5px;
            }}
            QLineEdit:focus{{border:1.5px solid {ACCENT};background:#ffffff;}}
        """)
    return e


# ── Login panel ──────────────────────────────────────────────────────────────
class RoleLoginWidget(QWidget):
    login_success = pyqtSignal(dict)

    def __init__(self, role: str):
        super().__init__()
        self.role   = role
        self.icon   = "🩺" if role == "doctor" else "👤"
        self.label  = "Doctor" if role == "doctor" else "Patient"
        self._user_id = self._email = ""
        self._worker  = None
        self._countdown_timer = QTimer()
        self._countdown_timer.timeout.connect(self._tick)
        self._build()

    def _build(self):
        self.setStyleSheet(f"background:{L_BG};")
        outer = _scrollable_center(self, L_BG)

        card = _responsive_card(320, 480)
        card.setStyleSheet(f"""
            QFrame{{
                background:{L_SURF};border-radius:4px;
                border:1px solid {L_BORDER};
                border-top-color:{BEVEL_LT};border-left-color:{BEVEL_LT};
                border-bottom-color:{BEVEL_DK};border-right-color:{BEVEL_DK};
            }}
        """)
        cl = QVBoxLayout(card); cl.setContentsMargins(44, 40, 44, 38); cl.setSpacing(14)

        # Avatar + title + subtitle
        av = QLabel(self.icon); av.setFixedSize(66, 66)
        av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        av.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {_lighten(ACCENT,0.55)},stop:1 {_lighten(ACCENT,0.35)});"
            f"border:1px solid {_darken(ACCENT,0.1)};"
            f"border-radius:8px;font-size:27px;")
        av_row = QHBoxLayout(); av_row.addStretch(); av_row.addWidget(av); av_row.addStretch()
        cl.addLayout(av_row)

        title = mklbl(f"{self.label} Login", L_TEXT, 23, bold=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(title)

        sub = mklbl(_SUBTITLE[self.role], L_DIM, 13)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(sub)
        cl.addSpacing(8)
        cl.addWidget(_hr())
        cl.addSpacing(8)

        # ── Identify yourself ────────────────────────────────────────────
        cl.addWidget(mklbl(f"{self.label} ID", L_DIM, 11.5))
        self.id_edit = _field(f"e.g. {'DR-001' if self.role=='doctor' else 'PT-001'}", h=34)
        cl.addWidget(self.id_edit)

        cl.addWidget(mklbl("Registered Email", L_DIM, 11.5))
        self.email_edit = _field("your@email.com", h=34)
        cl.addWidget(self.email_edit)

        self.send_otp_btn = mkbtn("Send Login OTP", ACCENT, wide=True, h=38)
        self.send_otp_btn.clicked.connect(self._send_otp)
        cl.addWidget(self.send_otp_btn)

        self.step1_status = QLabel("")
        self.step1_status.setWordWrap(True)
        self.step1_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.step1_status.setStyleSheet(f"color:{L_DIM};font-size:11px;")
        cl.addWidget(self.step1_status)

        # ── OTP step (revealed after send) ──────────────────────────────
        self.otp_block = QWidget(); self.otp_block.setStyleSheet("background:transparent;")
        ob = QVBoxLayout(self.otp_block); ob.setContentsMargins(0, 6, 0, 0); ob.setSpacing(10)
        ob.addWidget(_hr())

        row = QHBoxLayout(); row.setSpacing(6)
        row.addWidget(mklbl("Enter OTP from Email", L_DIM, 10.5))
        row.addStretch()
        self.countdown_lbl = QLabel("")
        self.countdown_lbl.setStyleSheet(f"color:{L_DIM};font-size:11px;font-weight:700;")
        row.addWidget(self.countdown_lbl)
        ob.addLayout(row)

        self.otp_edit = _field("8-character OTP", mono=True, pw=True, h=38)
        self.otp_edit.setMaxLength(8)
        ob.addWidget(self.otp_edit)

        self.verify_btn = mkbtn(f"Login as {self.label}", ACCENT, wide=True, h=38)
        self.verify_btn.clicked.connect(self._verify_otp)
        ob.addWidget(self.verify_btn)

        self.step2_status = QLabel("")
        self.step2_status.setWordWrap(True)
        self.step2_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.step2_status.setStyleSheet(f"color:{L_DIM};font-size:11px;")
        ob.addWidget(self.step2_status)

        cl.addWidget(self.otp_block)
        self.otp_block.setVisible(False)

        cl.addSpacing(4)
        contact = mklbl(_CONTACT[self.role], L_DIM, 10.5)
        contact.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(contact)

        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

    # ── State helpers ─────────────────────────────────────────────────────
    def _set_step(self, step: int):
        self.otp_block.setVisible(step == 2)
        self.verify_btn.setEnabled(step == 2)

    def _append_log(self, msg: str):
        pass  # no activity log in the minimal layout

    # ── Actions ───────────────────────────────────────────────────────────
    def _send_otp(self):
        uid   = self.id_edit.text().strip()
        email = self.email_edit.text().strip()

        if not uid:
            self.step1_status.setText(f"Enter your {self.label} ID")
            self.step1_status.setStyleSheet(f"color:{RED};font-size:11px;")
            return
        if "@" not in email or "." not in email:
            self.step1_status.setText("Enter a valid email address")
            self.step1_status.setStyleSheet(f"color:{RED};font-size:11px;")
            return
        if self.role == "doctor" and not DB.is_doctor_approved(uid, email):
            self.step1_status.setText(
                "This Doctor ID / email isn't on the approved list. "
                "Contact your administrator.")
            self.step1_status.setStyleSheet(f"color:{RED};font-size:11px;")
            return
        if not GMAIL.sender_email:
            QMessageBox.warning(self, "Not Configured",
                "Gmail sender credentials are not configured. "
                "Set them in the app's .env file first.")
            return

        self._user_id = uid
        self._email   = email

        otp = LOGIN_OTP_STORE.generate(self.role, uid)
        self._append_log(f"Login OTP generated for {self.label} [{uid}]")

        self.send_otp_btn.setEnabled(False)
        self.step1_status.setText(f"Sending OTP to {email}...")
        self.step1_status.setStyleSheet(f"color:{AMBER};font-size:11px;")

        self._worker = LoginEmailWorker(email, otp, self.role, uid)
        self._worker.log.connect(self._append_log)
        self._worker.done.connect(self._on_email_done)
        self._worker.start()
        self._countdown_timer.start(1000)

    def _on_email_done(self, ok: bool, msg: str):
        self.send_otp_btn.setEnabled(True)
        if ok:
            self._append_log(msg)
            self.step1_status.setText("OTP sent — check your email")
            self.step1_status.setStyleSheet(f"color:{GREEN};font-size:11px;")
            self._set_step(2)
            DB.log_otp_event("login_otp_sent",
                {"role": self.role, "user_id": self._user_id, "to": self._email})
            DB.log_session(self.role, "login_otp_sent",
                f"{self.label} [{self._user_id}] requested login OTP")
        else:
            self._append_log(msg)
            self.step1_status.setText(msg)
            self.step1_status.setStyleSheet(f"color:{RED};font-size:11px;")
            LOGIN_OTP_STORE.clear(self.role, self._user_id)
            self._countdown_timer.stop()
            self.countdown_lbl.setText("")

    def _verify_otp(self):
        candidate = self.otp_edit.text().strip().upper()
        if len(candidate) != OTP_LENGTH:
            self.step2_status.setText(f"OTP must be {OTP_LENGTH} characters")
            self.step2_status.setStyleSheet(f"color:{RED};font-size:11px;")
            return

        valid, reason = LOGIN_OTP_STORE.verify(self.role, self._user_id, candidate)
        if not valid:
            self.step2_status.setText(reason)
            self.step2_status.setStyleSheet(f"color:{RED};font-size:11px;")
            self._append_log(f"Login OTP failed: {reason}")
            DB.log_otp_event("login_otp_failed",
                {"role": self.role, "user_id": self._user_id, "reason": reason})
            return

        self._countdown_timer.stop()
        self.countdown_lbl.setText("")
        self.verify_btn.setEnabled(False)
        self.step2_status.setText("OTP verified — logging in...")
        self.step2_status.setStyleSheet(f"color:{GREEN};font-size:11px;")

        default_name = (f"Dr. {self._user_id}" if self.role == "doctor"
                        else f"Patient {self._user_id}")
        user_doc = DB.upsert_user(
            self._user_id, self.role, self._email, default_name)
        Session.set(self.role, user_doc)

        DB.log_otp_event("login_otp_verified",
            {"role": self.role, "user_id": self._user_id})
        DB.log_session(self.role, "login_success",
            f"{self.label} [{self._user_id}] logged in — "
            f"total logins: {user_doc.get('login_count', 1)}")

        self._append_log(f"Welcome, {self.label} [{self._user_id}]!")
        self.login_success.emit(user_doc)

    def _tick(self):
        rem = LOGIN_OTP_STORE.seconds_remaining(self.role, self._user_id)
        if rem <= 0:
            self._countdown_timer.stop()
            self.countdown_lbl.setText("Expired")
            self.countdown_lbl.setStyleSheet(f"color:{RED};font-size:11px;font-weight:700;")
            self.verify_btn.setEnabled(False)
            self.step2_status.setText("OTP expired — send a new one")
            self.step2_status.setStyleSheet(f"color:{AMBER};font-size:11px;")
            self._set_step(1)
            self.otp_edit.clear()
        else:
            m, s = divmod(rem, 60)
            self.countdown_lbl.setText(f"{m:02d}:{s:02d}")
            c = RED if rem < 60 else L_DIM
            self.countdown_lbl.setStyleSheet(f"color:{c};font-size:11px;font-weight:700;")

    def reset(self):
        """Reset to fresh state for re-login."""
        self.id_edit.clear(); self.email_edit.clear(); self.otp_edit.clear()
        self.step1_status.setText(""); self.step2_status.setText("")
        self.countdown_lbl.setText("")
        self._countdown_timer.stop()
        self._set_step(1)
        self.send_otp_btn.setEnabled(True)


class LoginScreen(QWidget):
    login_success = pyqtSignal(str, dict)   # (role, user_doc)

    def __init__(self):
        super().__init__(); self._build()

    def _build(self):
        self.setStyleSheet(f"background:{L_BG};")
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        topbar = QFrame(); topbar.setFixedHeight(52)
        topbar.setStyleSheet(f"""
            QFrame{{
                background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {L_SURF},stop:1 {_darken(L_SURF,0.06)});
                border-bottom:1px solid {L_BORDER};
            }}
        """)
        tl = QHBoxLayout(topbar); tl.setContentsMargins(24, 0, 24, 0)
        tl.addStretch()
        root.addWidget(topbar)

        self.role_tabs = QTabWidget()
        self.role_tabs.setDocumentMode(True)
        self.role_tabs.setStyleSheet(f"""
            QTabWidget::pane{{border:none;background:{L_BG};}}
            QTabBar{{background:{L_SURF};border-bottom:1px solid {L_BORDER};}}
            QTabBar::tab{{
                background:transparent;color:{L_DIM};border:none;
                border-bottom:2px solid transparent;
                padding:11px 38px;font-size:12.5px;font-weight:700;
            }}
            QTabBar::tab:selected{{color:{ACCENT};border-bottom:2px solid {ACCENT};}}
            QTabBar::tab:hover{{color:{L_TEXT};}}
        """)

        for role, label, icon in [("doctor", "Doctor", "🩺"), ("patient", "Patient", "👤")]:
            widget = RoleLoginWidget(role)
            widget.login_success.connect(lambda doc, r=role: self._on_login(r, doc))
            self.role_tabs.addTab(widget, f"{icon}  {label}")
            setattr(self, f"{role}_widget", widget)
        root.addWidget(self.role_tabs)

        footer = QFrame(); footer.setFixedHeight(30)
        footer.setStyleSheet(f"background:{L_SURF};border-top:1px solid {L_BORDER};")
        fl = QHBoxLayout(footer); fl.setContentsMargins(24, 0, 24, 0)
        fl.addWidget(mklbl("All data is encrypted end-to-end", L_DIM, 10.5))
        fl.addStretch()
        fl.addWidget(mklbl(f"v{VERSION}", L_DIM, 10.5))
        root.addWidget(footer)

    def _on_login(self, role, user_doc): self.login_success.emit(role, user_doc)
    def reset_role(self, role):
        getattr(self, f"{role}_widget").reset(); Session.clear(role)


class WelcomeScreen(QWidget):
    proceed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._role = "doctor"
        self._timer = QTimer(); self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.proceed.emit(self._role))
        self._build()

    def _build(self):
        self.setStyleSheet(f"background:{L_BG};")
        root = _scrollable_center(self, L_BG)

        card = _responsive_card(320, 480)
        card.setStyleSheet(f"""
            QFrame{{
                background:{L_SURF};border-radius:4px;
                border:1px solid {L_BORDER};
                border-top-color:{BEVEL_LT};border-left-color:{BEVEL_LT};
                border-bottom-color:{BEVEL_DK};border-right-color:{BEVEL_DK};
            }}
        """)
        cl = QVBoxLayout(card); cl.setContentsMargins(36, 32, 36, 32); cl.setSpacing(12)

        ic_lbl = QLabel("✅"); ic_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic_lbl.setStyleSheet("font-size:38px;background:transparent;")
        cl.addWidget(ic_lbl)

        title = mklbl("Authenticated", L_TEXT, 18, bold=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(title)

        self.role_lbl = mklbl("", L_DIM, 12)
        self.role_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.role_lbl.setWordWrap(True)
        cl.addWidget(self.role_lbl)

        self.last_lbl = mklbl("", L_DIM, 10.5)
        self.last_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.last_lbl)

        cl.addSpacing(4)
        cl.addWidget(_hr())
        cl.addSpacing(4)

        self.cd_lbl = mklbl("Entering workspace in 5 seconds…", L_DIM, 11.5)
        self.cd_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.cd_lbl)

        self.proc_btn = mkbtn("Enter Workspace", ACCENT, h=44, wide=True)
        cl.addWidget(self.proc_btn)

        root.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        self._cd_timer = QTimer(); self._cd_timer.timeout.connect(self._update_cd)
        self._cd_remaining = 5

    def populate(self, role, user_doc):
        self._role = role
        icon  = "🩺" if role == "doctor" else "👤"
        uid   = user_doc.get("user_id", "—")
        name  = user_doc.get("display_name", uid)
        email = user_doc.get("email", "—")
        count = user_doc.get("login_count", 1)

        self.role_lbl.setText(f"{icon}  {name}  [{uid}]  ·  {email}  ·  login #{count}")
        self.last_lbl.setText(f"Last seen: {user_doc.get('last_seen','—')[:19]} UTC")

        try: self.proc_btn.clicked.disconnect()
        except: pass
        self.proc_btn.clicked.connect(lambda: self.proceed.emit(self._role))

        self._cd_remaining = 5
        self._cd_timer.start(1000)
        self._timer.start(5000)

    def _update_cd(self):
        self._cd_remaining -= 1
        if self._cd_remaining <= 0:
            self._cd_timer.stop(); self.cd_lbl.setText("Entering workspace…")
        else:
            self.cd_lbl.setText(f"Entering workspace in {self._cd_remaining} seconds…")