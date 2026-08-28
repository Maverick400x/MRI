import json
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox,
    QScrollArea, QGridLayout,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui  import QColor, QFont

from config import (
    DB, GMAIL, DOCTOR_VERIFY_STORE, OTP_LENGTH, DEVICE_INFO,
    SURF, SURF2, BORDER,
    BLUE, CYAN, RED, GREEN, AMBER, TEXT, DIM, DIM2, PURPLE,
)
from theme   import (
    mkbtn, mkbtn_ghost, mkinp, mklbl, mkcard, mkstep_badge,
    PieChart, LineChart, BarChart, RADIUS, R_SMALL,
)
from workers import DoctorVerifyEmailWorker

class AdminTab(QWidget):
    """
    Admin panel that queries MongoDB. Doctors sub-tab can write (add/remove
    approved doctors); Scans, OTP Audit, Sessions, and Users stay read-only.
    """

    def __init__(self):
        super().__init__()
        self._build()
        self._refresh_all()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # Header row
        hdr = QHBoxLayout()
        title = QLabel("🗄️  MongoDB Admin — mri_secure_transfer")
        title.setStyleSheet(f"color:{PURPLE};font-size:17px;font-weight:700;")
        hdr.addWidget(title)
        hdr.addStretch()

        self.refresh_btn = mkbtn("🔄  Refresh All", PURPLE, 34)
        self.refresh_btn.setFixedWidth(140)
        self.refresh_btn.clicked.connect(self._refresh_all)
        hdr.addWidget(self.refresh_btn)

        reconnect_btn = mkbtn_ghost("🔌  Reconnect", DIM, 34)
        reconnect_btn.setFixedWidth(120)
        reconnect_btn.clicked.connect(self._reconnect)
        hdr.addWidget(reconnect_btn)
        root.addLayout(hdr)

        # Connection status bar
        self.status_frame = QFrame()
        self.status_frame.setFixedHeight(38)
        self.status_frame.setStyleSheet(
            f"background:{SURF2};border:1px solid {BORDER};border-radius:3px;")
        sf_lay = QHBoxLayout(self.status_frame)
        sf_lay.setContentsMargins(14, 0, 14, 0)
        self.conn_dot  = QLabel("●")
        self.conn_dot.setStyleSheet(f"color:{DIM};font-size:14px;border:none;")
        self.conn_lbl  = QLabel("Checking connection…")
        self.conn_lbl.setStyleSheet(f"color:{DIM};font-size:12px;border:none;")
        self.counts_lbl = QLabel("")
        self.counts_lbl.setStyleSheet(f"color:{DIM};font-size:12px;border:none;")
        sf_lay.addWidget(self.conn_dot)
        sf_lay.addWidget(self.conn_lbl)
        sf_lay.addStretch()
        device_lbl = QLabel(
            f"🖥  {DEVICE_INFO['hostname']}  ({DEVICE_INFO['os']})  ·  {DEVICE_INFO['local_ip']}")
        device_lbl.setStyleSheet(f"color:{DIM2};font-size:11px;border:none;")
        device_lbl.setToolTip(
            f"OS user: {DEVICE_INFO['os_user']}\n"
            f"Machine: {DEVICE_INFO['machine']}\n"
            f"Python: {DEVICE_INFO['python']}\n"
            f"App version: {DEVICE_INFO['app_version']}")
        sf_lay.addWidget(device_lbl)
        sf_lay.addSpacing(14)
        sf_lay.addWidget(self.counts_lbl)
        root.addWidget(self.status_frame)

        # Sub-tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane{{
                border:1px solid {BORDER};border-radius:3px;
                background:{SURF};margin-top:-1px;
            }}
            QTabBar::tab{{
                background:{SURF2};color:{DIM};
                border:1px solid {BORDER};border-bottom:none;
                border-radius:3px 3px 0 0;
                padding:7px 20px;font-size:12px;font-weight:600;
                margin-right:3px;
            }}
            QTabBar::tab:selected{{
                background:{SURF};color:{PURPLE};
                border-bottom:2px solid {PURPLE};
            }}
            QTabBar::tab:hover{{background:{BORDER};color:{TEXT};}}
        """)

        self.scan_table    = self._make_table(
            ["Timestamp","Filename","Anon ID","Patient ID","Necrotic mm²",
             "Edema mm²","Enhancing mm²","File Size","Algorithm"])
        self.otp_table     = self._make_table(
            ["Timestamp","Event","Patient Email","Patient ID","TTL","Reason"])
        self.session_table = self._make_table(
            ["Timestamp","Role","Action","Detail","Host","IP","OS","OS User"])

        self.user_table     = self._make_table(
            ["User ID","Display Name","Role","Email","Created","Last Seen","Logins"])
        self.doctors_table  = self._make_table(
            ["Doctor ID","Email","Name","Added"])
        self.tabs.addTab(self._build_doctors_tab(),                           "🩺  Doctors")
        self.tabs.addTab(self._build_analytics_tab(),                         "📊  Analytics")
        self.tabs.addTab(self._wrap_table(self.scan_table,    "🔒 Encrypted Scans"),   "🔒  Scans")
        self.tabs.addTab(self._wrap_table(self.otp_table,     "🔑 OTP Audit Log"),     "🔑  OTP Audit")
        self.tabs.addTab(self._wrap_table(self.session_table, "👥 Session Log"),       "👥  Sessions")
        self.tabs.addTab(self._wrap_table(self.user_table,    "👤 Registered Users"),  "👤  Users")
        root.addWidget(self.tabs)

        # Auto-refresh every 15 seconds
        self._auto_timer = QTimer()
        self._auto_timer.timeout.connect(self._refresh_all)
        self._auto_timer.start(15_000)

    # ── Table factory ─────────────────────────────────────────────────────────
    def _make_table(self, headers: list) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        t.setStyleSheet(f"""
            QTableWidget{{
                background:{SURF};color:{TEXT};
                border:none;gridline-color:{BORDER};
                font-size:12px;
            }}
            QTableWidget::item{{padding:4px 8px;}}
            QTableWidget::item:selected{{background:{BLUE}44;color:{TEXT};}}
            QHeaderView::section{{
                background:{SURF2};color:{PURPLE};
                border:none;border-right:1px solid {BORDER};
                border-bottom:1px solid {BORDER};
                padding:6px 10px;font-size:11px;font-weight:700;
            }}
            QTableWidget{{alternate-background-color:{SURF2};}}
        """)
        return t

    def _wrap_table(self, table: QTableWidget, title: str) -> QWidget:
        w = QWidget(); w.setStyleSheet(f"background:{SURF};")
        lay = QVBoxLayout(w); lay.setContentsMargins(12, 12, 12, 12); lay.setSpacing(8)

        hdr_row = QHBoxLayout(); hdr_row.setSpacing(10)
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color:{PURPLE};font-size:13px;font-weight:700;")
        hdr_row.addWidget(lbl)
        hdr_row.addStretch()

        search = mkinp("🔎  Search this table…")
        search.setFixedWidth(260)
        search.textChanged.connect(lambda text, t=table: self._filter_table(t, text))
        hdr_row.addWidget(search)

        match_lbl = QLabel("")
        match_lbl.setStyleSheet(f"color:{DIM};font-size:11px;")
        hdr_row.addWidget(match_lbl)
        table._match_lbl = match_lbl     # stashed for _filter_table to update
        table._search_edit = search      # stashed so refreshes can reapply the filter

        lay.addLayout(hdr_row)
        lay.addWidget(table)
        return w

    def _filter_table(self, table: QTableWidget, text: str):
        """Case-insensitive filter — hides rows where no cell contains
        the search text. Empty search shows every row again."""
        text = text.strip().lower()
        visible = 0
        for r in range(table.rowCount()):
            if not text:
                match = True
            else:
                match = any(
                    text in (table.item(r, c).text().lower() if table.item(r, c) else "")
                    for c in range(table.columnCount())
                )
            table.setRowHidden(r, not match)
            if match: visible += 1
        lbl = getattr(table, "_match_lbl", None)
        if lbl is not None:
            total = table.rowCount()
            lbl.setText("" if not text else f"{visible} / {total} match")

    def _reapply_filter(self, table: QTableWidget):
        """Called after a table repopulates (auto-refresh) so an active
        search doesn't silently reset to showing every row again."""
        search = getattr(table, "_search_edit", None)
        if search is not None and search.text().strip():
            self._filter_table(table, search.text())

    # ── Analytics tab ────────────────────────────────────────────────────────
    def _build_analytics_tab(self) -> QWidget:
        outer = QWidget(); outer.setStyleSheet(f"background:{SURF};")
        outer_lay = QVBoxLayout(outer); outer_lay.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{border:none;background:{SURF};}}")
        outer_lay.addWidget(scroll)

        body = QWidget(); body.setStyleSheet(f"background:{SURF};")
        lay = QVBoxLayout(body); lay.setContentsMargins(14, 14, 14, 14); lay.setSpacing(14)
        scroll.setWidget(body)

        hdr = QLabel("📊  Cross-App Analytics — Doctors, Patients & Scan Activity")
        hdr.setStyleSheet(f"color:{PURPLE};font-size:14px;font-weight:700;")
        lay.addWidget(hdr)
        sub = QLabel("Aggregated from live MongoDB data — refreshes with the rest of the admin panel.")
        sub.setStyleSheet(f"color:{DIM};font-size:11px;")
        lay.addWidget(sub)

        grid = QGridLayout(); grid.setSpacing(14)
        lay.addLayout(grid)

        # 1. Users by role — pie
        c1, l1 = mkcard(accent=PURPLE)
        l1.addWidget(mklbl("USERS BY ROLE", PURPLE, 10, bold=True))
        self.chart_role_pie = PieChart(height=170)
        l1.addWidget(self.chart_role_pie)
        grid.addWidget(c1, 0, 0)

        # 2. Scans by risk level — pie
        c2, l2 = mkcard(accent=RED)
        l2.addWidget(mklbl("SCANS BY RISK LEVEL", RED, 10, bold=True))
        self.chart_risk_pie = PieChart(height=170)
        l2.addWidget(self.chart_risk_pie)
        grid.addWidget(c2, 0, 1)

        # 3. Scan activity over time — line
        c3, l3 = mkcard(accent=BLUE)
        l3.addWidget(mklbl("SCANS PER DAY (LAST 14 DAYS)", BLUE, 10, bold=True))
        self.chart_scans_line = LineChart(height=170, color=BLUE)
        l3.addWidget(self.chart_scans_line)
        grid.addWidget(c3, 1, 0)

        # 4. Aggregate tumor region composition — bar
        c4, l4 = mkcard(accent=CYAN)
        l4.addWidget(mklbl("AVG. REGION AREA ACROSS ALL SCANS (mm²)", CYAN, 10, bold=True))
        self.chart_region_bar = BarChart(height=170)
        l4.addWidget(self.chart_region_bar)
        grid.addWidget(c4, 1, 1)

        # 5. Top patients by scan count — bar
        c5, l5 = mkcard(accent=GREEN)
        l5.addWidget(mklbl("TOP PATIENTS BY SCAN COUNT", GREEN, 10, bold=True))
        self.chart_top_patients_bar = BarChart(height=170)
        l5.addWidget(self.chart_top_patients_bar)
        grid.addWidget(c5, 2, 0)

        # 6. Logins per day — line
        c6, l6 = mkcard(accent=AMBER)
        l6.addWidget(mklbl("LOGINS PER DAY (LAST 14 DAYS)", AMBER, 10, bold=True))
        self.chart_logins_line = LineChart(height=170, color=AMBER)
        l6.addWidget(self.chart_logins_line)
        grid.addWidget(c6, 2, 1)

        grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1)
        return outer

    def _refresh_analytics(self):
        if not DB.connected:
            for chart in (self.chart_role_pie, self.chart_risk_pie,
                          self.chart_scans_line, self.chart_region_bar,
                          self.chart_top_patients_bar, self.chart_logins_line):
                chart.clear()
            return

        users   = DB.get_users(limit=1000)
        scans   = DB.get_scans(limit=1000)
        sessions = DB.get_sessions(limit=1000)

        # 1. Users by role
        role_counts = Counter(u.get("role", "unknown") for u in users)
        role_colors = {"doctor": BLUE, "patient": GREEN, "unknown": DIM}
        self.chart_role_pie.set_data([
            (r.title(), c, role_colors.get(r, DIM)) for r, c in role_counts.items() if c
        ])

        # 2. Scans by risk level (older scans without a stored risk are skipped)
        risk_counts = Counter()
        for s in scans:
            level = (s.get("risk") or {}).get("level")
            if level: risk_counts[level] += 1
        risk_colors = {"Minimal": GREEN, "Low": CYAN, "Moderate": AMBER,
                       "High": RED, "Critical": RED}
        self.chart_risk_pie.set_data([
            (lvl, c, risk_colors.get(lvl, DIM)) for lvl, c in risk_counts.items() if c
        ])

        # 3 & 6. Scans / logins per day, last 14 days
        def _daily_counts(records, ts_key="timestamp", filt=None):
            today = datetime.now(timezone.utc).date()
            days = [today - timedelta(days=i) for i in range(13, -1, -1)]
            buckets = defaultdict(int)
            for r in records:
                if filt and not filt(r): continue
                ts = r.get(ts_key, "")
                try:
                    d = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
                except Exception:
                    continue
                if d in days: buckets[d] += 1
            labels = [d.strftime("%m/%d") for d in days]
            values = [buckets[d] for d in days]
            return labels, values

        labels, values = _daily_counts(scans)
        self.chart_scans_line.set_data(labels, values, color=BLUE)

        login_labels, login_values = _daily_counts(
            sessions, filt=lambda r: r.get("action") == "login_success")
        self.chart_logins_line.set_data(login_labels, login_values, color=AMBER)

        # 4. Average region area across all scans
        region_sums = defaultdict(float); region_n = defaultdict(int)
        for s in scans:
            for region, val in (s.get("areas_mm2") or {}).items():
                region_sums[region] += val; region_n[region] += 1
        region_colors = {"Necrotic": RED, "Edema": GREEN, "Enhancing": BLUE}
        bars = [
            (region, region_sums[region] / region_n[region], region_colors.get(region, BLUE))
            for region in region_sums if region_n[region]
        ]
        self.chart_region_bar.set_data(bars)

        # 5. Top patients by scan count
        patient_counts = Counter(s.get("patient_id", "—") for s in scans if s.get("patient_id"))
        top5 = patient_counts.most_common(5)
        self.chart_top_patients_bar.set_data([(pid, cnt, GREEN) for pid, cnt in top5])

    # ── Doctors tab ──────────────────────────────────────────────────────────
    def _build_doctors_tab(self) -> QWidget:
        self._pending_doctor = {}   # id/email/name awaiting OTP confirmation
        self._doc_verify_timer = QTimer()
        self._doc_verify_timer.timeout.connect(self._tick_doctor_verify)

        w = QWidget(); w.setStyleSheet(f"background:{SURF};")
        root = QVBoxLayout(w); root.setContentsMargins(16, 16, 16, 16); root.setSpacing(12)

        intro = QLabel(
            "Only Doctor IDs + emails added here can log in as a doctor. "
            "Adding one requires verifying the email with a one-time code first, "
            "so no one can register under an address they don't control.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{DIM};font-size:11.5px;")
        root.addWidget(intro)

        # ── Add-doctor card (OTP-gated) ─────────────────────────────────────
        card, cl = mkcard(accent=PURPLE)
        hdr = QHBoxLayout(); hdr.setSpacing(8)
        hdr.addWidget(mkstep_badge(1, PURPLE))
        hdr.addWidget(mklbl("Add Approved Doctor", TEXT, 13, bold=True))
        hdr.addStretch()
        self.doc_countdown = QLabel("")
        self.doc_countdown.setFixedWidth(72)
        self.doc_countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.doc_countdown.setStyleSheet(
            f"background:{SURF2};color:{AMBER};border:1px solid {AMBER}44;"
            f"border-radius:{R_SMALL}px;font-size:12px;font-weight:800;padding:3px 6px;")
        hdr.addWidget(self.doc_countdown)
        cl.addLayout(hdr)

        row1 = QHBoxLayout(); row1.setSpacing(10)
        c1 = QVBoxLayout(); c1.setSpacing(3)
        c1.addWidget(mklbl("Doctor ID", DIM, 10))
        self.new_doc_id = mkinp("e.g. DR-002")
        c1.addWidget(self.new_doc_id)
        c2 = QVBoxLayout(); c2.setSpacing(3)
        c2.addWidget(mklbl("Doctor Email", DIM, 10))
        self.new_doc_email = mkinp("doctor@hospital.com")
        c2.addWidget(self.new_doc_email)
        row1.addLayout(c1, 1); row1.addLayout(c2, 2)
        cl.addLayout(row1)

        c3 = QVBoxLayout(); c3.setSpacing(3)
        c3.addWidget(mklbl("Full Name (optional)", DIM, 10))
        self.new_doc_name = mkinp("Dr. Jane Doe")
        c3.addWidget(self.new_doc_name)
        cl.addLayout(c3)

        self.send_doc_otp_btn = mkbtn("📧  Send Verification OTP", PURPLE, wide=True)
        self.send_doc_otp_btn.clicked.connect(self._send_doctor_verify_otp)
        cl.addWidget(self.send_doc_otp_btn)

        self.doc_add_status = QLabel("")
        self.doc_add_status.setWordWrap(True)
        self.doc_add_status.setStyleSheet(
            f"color:{DIM};font-size:11px;padding:6px 8px;"
            f"background:{SURF2};border-radius:{R_SMALL}px;")
        cl.addWidget(self.doc_add_status)

        # Step 2 — confirm sub-block
        ver_f, ver_l = mkcard(accent=PURPLE, pad=(12, 10, 12, 10), radius=R_SMALL)
        ver_l.addWidget(mklbl("Enter the OTP sent to the doctor's email to confirm", PURPLE, 11))
        ver_row = QHBoxLayout(); ver_row.setSpacing(8)
        self.doc_verify_otp_e = mkinp("8-char OTP", pw=True, mono=True)
        self.doc_verify_otp_e.setMaxLength(8); self.doc_verify_otp_e.setEnabled(False)
        ver_row.addWidget(self.doc_verify_otp_e)
        self.confirm_doc_btn = mkbtn("✔ Confirm & Add", PURPLE)
        self.confirm_doc_btn.setFixedWidth(140); self.confirm_doc_btn.setEnabled(False)
        self.confirm_doc_btn.clicked.connect(self._confirm_add_doctor)
        ver_row.addWidget(self.confirm_doc_btn)
        ver_l.addLayout(ver_row)
        cl.addWidget(ver_f)
        root.addWidget(card)

        # ── Roster table ─────────────────────────────────────────────────────
        tbl_hdr = QHBoxLayout()
        tbl_hdr.addWidget(mklbl("Approved Doctors", PURPLE, 12, bold=True))
        tbl_hdr.addStretch()
        doc_search = mkinp("🔎  Search doctors…")
        doc_search.setFixedWidth(220)
        doc_search.textChanged.connect(lambda text: self._filter_table(self.doctors_table, text))
        self.doctors_table._search_edit = doc_search
        tbl_hdr.addWidget(doc_search)
        self.remove_doc_btn = mkbtn_ghost("🗑 Remove Selected", RED, h=30)
        self.remove_doc_btn.setFixedWidth(160)
        self.remove_doc_btn.clicked.connect(self._remove_doctor)
        tbl_hdr.addWidget(self.remove_doc_btn)
        root.addLayout(tbl_hdr)
        root.addWidget(self.doctors_table)

        return w

    def _send_doctor_verify_otp(self):
        uid   = self.new_doc_id.text().strip()
        email = self.new_doc_email.text().strip()
        name  = self.new_doc_name.text().strip()

        if not uid:
            self.doc_add_status.setText("Enter a Doctor ID.")
            self.doc_add_status.setStyleSheet(f"color:{RED};font-size:11px;padding:6px 8px;")
            return
        if "@" not in email or "." not in email:
            self.doc_add_status.setText("Enter a valid email address.")
            self.doc_add_status.setStyleSheet(f"color:{RED};font-size:11px;padding:6px 8px;")
            return
        if not DB.connected:
            self.doc_add_status.setText("Not connected to MongoDB — can't add doctors right now.")
            self.doc_add_status.setStyleSheet(f"color:{RED};font-size:11px;padding:6px 8px;")
            return
        if not GMAIL.sender_email:
            QMessageBox.warning(self, "Not Configured",
                "Open ⚙️ Gmail Settings in the top bar first.")
            return

        self._pending_doctor = {"user_id": uid, "email": email, "name": name}
        otp = DOCTOR_VERIFY_STORE.generate("doctor_verify", uid)

        self.doc_add_status.setText(f"Sending verification OTP to {email}...")
        self.doc_add_status.setStyleSheet(f"color:{AMBER};font-size:11px;padding:6px 8px;")
        self.send_doc_otp_btn.setEnabled(False)

        self._doc_verify_worker = DoctorVerifyEmailWorker(email, otp, uid)
        self._doc_verify_worker.done.connect(self._on_doctor_verify_email_done)
        self._doc_verify_worker.start()
        self._doc_verify_timer.start(1000)

    def _on_doctor_verify_email_done(self, ok: bool, msg: str):
        self.send_doc_otp_btn.setEnabled(True)
        if ok:
            self.doc_add_status.setText(
                "✅  Verification OTP sent — ask the doctor for the code, then confirm below.")
            self.doc_add_status.setStyleSheet(f"color:{GREEN};font-size:11px;padding:6px 8px;")
            self.doc_verify_otp_e.setEnabled(True)
            self.confirm_doc_btn.setEnabled(True)
        else:
            self.doc_add_status.setText(f"❌  {msg}")
            self.doc_add_status.setStyleSheet(f"color:{RED};font-size:11px;padding:6px 8px;")
            DOCTOR_VERIFY_STORE.clear("doctor_verify", self._pending_doctor.get("user_id", ""))
            self._doc_verify_timer.stop(); self.doc_countdown.setText("")

    def _confirm_add_doctor(self):
        uid = self._pending_doctor.get("user_id", "")
        candidate = self.doc_verify_otp_e.text().strip().upper()
        valid, reason = DOCTOR_VERIFY_STORE.verify("doctor_verify", uid, candidate)
        if not valid:
            self.doc_add_status.setText(f"❌  {reason}")
            self.doc_add_status.setStyleSheet(f"color:{RED};font-size:11px;padding:6px 8px;")
            return

        ok, msg = DB.add_doctor(
            uid, self._pending_doctor.get("email", ""), self._pending_doctor.get("name", ""))
        if ok:
            self.doc_add_status.setText(f"✅  {msg}")
            self.doc_add_status.setStyleSheet(f"color:{GREEN};font-size:11px;padding:6px 8px;")
            DB.log_session("system", "doctor_approved", f"{uid} added to approved doctors")
            self.new_doc_id.clear(); self.new_doc_email.clear(); self.new_doc_name.clear()
            self.doc_verify_otp_e.clear(); self.doc_verify_otp_e.setEnabled(False)
            self.confirm_doc_btn.setEnabled(False)
            self._doc_verify_timer.stop(); self.doc_countdown.setText("")
            self._pending_doctor = {}
            self._load_doctors()
        else:
            self.doc_add_status.setText(f"❌  {msg}")
            self.doc_add_status.setStyleSheet(f"color:{RED};font-size:11px;padding:6px 8px;")

    def _tick_doctor_verify(self):
        uid = self._pending_doctor.get("user_id", "")
        rem = DOCTOR_VERIFY_STORE.seconds_remaining("doctor_verify", uid)
        if rem <= 0:
            self._doc_verify_timer.stop()
            self.doc_countdown.setText("EXPIRED")
            self.doc_countdown.setStyleSheet(
                f"background:{SURF2};color:{RED};border:1px solid {RED}44;"
                f"border-radius:{R_SMALL}px;font-size:12px;font-weight:800;padding:3px 6px;")
            self.doc_verify_otp_e.setEnabled(False)
            self.confirm_doc_btn.setEnabled(False)
        else:
            m, s = divmod(rem, 60)
            self.doc_countdown.setText(f"{m:02d}:{s:02d}")
            c = RED if rem < 60 else AMBER
            self.doc_countdown.setStyleSheet(
                f"background:{SURF2};color:{c};border:1px solid {c}44;"
                f"border-radius:{R_SMALL}px;font-size:12px;font-weight:800;padding:3px 6px;")

    def _remove_doctor(self):
        row = self.doctors_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a Doctor",
                "Click a row in the table first.")
            return
        uid = self.doctors_table.item(row, 0).text()
        reply = QMessageBox.question(
            self, "Remove Doctor",
            f"Remove {uid} from the approved list? They won't be able to log in until re-added.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if DB.remove_doctor(uid):
            DB.log_session("system", "doctor_removed", f"{uid} removed from approved doctors")
            self._load_doctors()
        else:
            QMessageBox.warning(self, "Failed",
                "Could not remove doctor — check the MongoDB connection.")

    def _load_doctors(self):
        docs = DB.get_doctors()
        self.doctors_table.setRowCount(0)
        for doc in docs:
            r = self.doctors_table.rowCount(); self.doctors_table.insertRow(r)
            vals = [
                doc.get("user_id", ""),
                doc.get("email", ""),
                doc.get("name") or "—",
                (doc.get("added_at") or "")[:19],
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter)
                self.doctors_table.setItem(r, c, item)
        self._reapply_filter(self.doctors_table)

    # ── Refresh helpers ───────────────────────────────────────────────────────
    def _refresh_status(self):
        ok = DB.connected
        self.conn_dot.setStyleSheet(
            f"color:{GREEN if ok else RED};font-size:14px;border:none;")
        self.conn_lbl.setText(DB.status_msg)
        self.conn_lbl.setStyleSheet(
            f"color:{GREEN if ok else RED};font-size:12px;border:none;")
        if ok:
            c = DB.counts()
            self.counts_lbl.setText(
                f"Scans: {c['scans']}  ·  OTP events: {c['otp_audit']}  ·  Sessions: {c['sessions']}")

    def _refresh_all(self):
        self._refresh_status()
        self._load_doctors()
        self._load_scans()
        self._load_otp_audit()
        self._load_sessions()
        self._load_users()
        self._refresh_analytics()

    def _reconnect(self):
        DB.reconnect()
        self._refresh_status()

    def _fill_table(self, table: QTableWidget, rows: list, col_keys: list):
        table.setRowCount(0)
        for row_data in rows:
            r = table.rowCount(); table.insertRow(r)
            for c, key in enumerate(col_keys):
                val = row_data.get(key, "")
                if isinstance(val, dict):
                    # areas_mm2 sub-fields handled separately
                    val = json.dumps(val)
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                table.setItem(r, c, item)

    def _load_scans(self):
        docs = DB.get_scans()
        self.scan_table.setRowCount(0)
        for doc in docs:
            r = self.scan_table.rowCount(); self.scan_table.insertRow(r)
            areas = doc.get("areas_mm2", {})
            vals  = [
                doc.get("timestamp","")[:19],
                doc.get("filename",""),
                doc.get("anon_id",""),
                doc.get("patient_id",""),
                f"{areas.get('Necrotic',0):.2f}",
                f"{areas.get('Edema',0):.2f}",
                f"{areas.get('Enhancing',0):.2f}",
                f"{doc.get('file_size_b',0):,} B",
                doc.get("algorithm",""),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter)
                self.scan_table.setItem(r, c, item)
        self._reapply_filter(self.scan_table)

    def _load_otp_audit(self):
        docs = DB.get_otp_audit()
        self.otp_table.setRowCount(0)
        for doc in docs:
            r = self.otp_table.rowCount(); self.otp_table.insertRow(r)
            event = doc.get("event","")
            color = {
                "generated":             PURPLE,
                "email_sent":            GREEN,
                "email_failed":          RED,
                "doctor_verified":       CYAN,
                "doctor_verify_failed":  RED,
                "patient_verified":      GREEN,
                "patient_verify_failed": RED,
                "expired":               AMBER,
                "cleared":               DIM,
            }.get(event, TEXT)
            vals = [
                doc.get("timestamp","")[:19],
                event,
                doc.get("to",""),
                doc.get("patient_id",""),
                str(doc.get("ttl_sec","")),
                doc.get("reason",""),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter)
                if c == 1:   # event column coloured
                    item.setForeground(QColor(color))
                    f = QFont(); f.setBold(True); item.setFont(f)
                self.otp_table.setItem(r, c, item)
        self._reapply_filter(self.otp_table)

    def _load_users(self):
        docs = DB.get_users()
        self.user_table.setRowCount(0)
        for doc in docs:
            r = self.user_table.rowCount(); self.user_table.insertRow(r)
            role  = doc.get("role","")
            color = BLUE if role == "doctor" else GREEN
            vals  = [
                doc.get("user_id",""),
                doc.get("display_name","—"),
                role,
                doc.get("email",""),
                doc.get("created_at","")[:19],
                doc.get("last_seen","")[:19],
                str(doc.get("login_count",0)),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter)
                if c == 1:
                    item.setForeground(QColor(color))
                    f = QFont(); f.setBold(True); item.setFont(f)
                self.user_table.setItem(r, c, item)
        self._reapply_filter(self.user_table)

    def _load_sessions(self):
        docs = DB.get_sessions()
        self.session_table.setRowCount(0)
        for doc in docs:
            r = self.session_table.rowCount(); self.session_table.insertRow(r)
            role  = doc.get("role","")
            color = {
                "doctor":  BLUE,
                "patient": GREEN,
                "system":  DIM,
            }.get(role, TEXT)
            device = doc.get("device") or {}
            vals = [
                doc.get("timestamp","")[:19],
                role,
                doc.get("action",""),
                doc.get("detail",""),
                device.get("hostname","—"),
                device.get("local_ip","—"),
                device.get("os","—"),
                device.get("os_user","—"),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter)
                if c == 1:   # role column coloured
                    item.setForeground(QColor(color))
                    f = QFont(); f.setBold(True); item.setFont(f)
                self.session_table.setItem(r, c, item)
        self._reapply_filter(self.session_table)



