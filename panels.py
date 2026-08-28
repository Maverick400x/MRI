"""
panels.py — Doctor and Patient workspace panels.

    DoctorPanel   load MRI files → segment → send OTP → encrypt & deliver
    PatientPanel  select encrypted scan → decrypt → view & download files
"""
import os, json, zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QSplitter, QScrollArea, QListWidget, QListWidgetItem,
    QMessageBox, QFileDialog, QAbstractItemView, QSizePolicy,
    QTextEdit, QComboBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui  import QColor, QFont, QPixmap, QImage

from config import (
    SHARED_FOLDER, ENC_SUFFIX, OTP_STORE, OTP_TTL_SEC, PIXEL_SPACING,
    LOGIN_OTP_STORE, OTP_LENGTH,
    GMAIL, AI_CFG, AI_FEATURES_ENABLED, DB, Session, CRYPTO_OK,
    BG, SURF, SURF2, SURF3, BORDER,
    BLUE, CYAN, RED, GREEN, AMBER, PURPLE, TEXT, DIM, DIM2, LOG_BG, LOG_FG, LOG_DIM,
)
from imaging       import (
    simulate_segmentation, overlay_pixmap, overlay_array, arr_to_pixmap,
    assess_scan_modality, analyze_scan_quality, assess_risk_level,
)
from workers       import EncryptWorker, EmailWorker, DecryptWorker, LoginEmailWorker
from email_service import generate_patient_report_pdf
from ai_report      import AIFindingsWorker
from agent_analysis import AgentAnalysisWorker
from theme import (
    mkbtn, mkbtn_ghost, mkbtn_outline, mkinp, mkcard, mkgrp, mklbl,
    mkbadge, mklog, mkimg, mkprog, mksep, mksection_header,
    mkstatcard, mkstep_badge, BarChart, RADIUS, R_SMALL, BTN_H, INP_H, CARD_PAD,
)

# ── Doctor panel ──────────────────────────────────────────────────────────────
class DoctorPanel(QWidget):
    sent = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.file_paths  = []
        self.img_array   = None
        self.seg         = None
        self._active_otp = None
        self.enc_worker = self.email_worker = self.ai_worker = None
        self.agent_worker = None
        self._pending_report = None
        self._previous_scan = None   # most recent prior scan for the current Patient ID, if any
        self._build()

    def _build(self):
        # ── Root: horizontal splitter fills entire panel ──────────────────
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(f"QSplitter::handle{{background:{BORDER};}}")
        root.addWidget(splitter)

        # ════════════════════════════════════════════════════════════════════
        # LEFT PANE — files + segmentation
        # ════════════════════════════════════════════════════════════════════
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setStyleSheet(f"QScrollArea{{background:{BG};border:none;}}")
        left_inner = QWidget(); left_inner.setStyleSheet(f"background:{BG};")
        left = QVBoxLayout(left_inner)
        left.setContentsMargins(20, 20, 12, 20); left.setSpacing(14)
        left_scroll.setWidget(left_inner)

        # ── Panel header ──────────────────────────────────────────────────
        dr_hdr = QFrame()
        dr_hdr.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {BLUE},stop:1 {CYAN});"
            f"border-radius:{RADIUS}px;border:1px solid {BLUE};")
        hlay = QHBoxLayout(dr_hdr); hlay.setContentsMargins(16, 12, 16, 12); hlay.setSpacing(12)
        ic = QLabel("🩺"); ic.setStyleSheet("font-size:22px;background:transparent;")
        hlay.addWidget(ic)
        tc = QVBoxLayout(); tc.setSpacing(1)
        tl = QLabel("Doctor Workspace"); tl.setStyleSheet("color:white;font-size:15px;font-weight:800;background:transparent;")
        sl = QLabel("Load scans  ·  Segment  ·  Deliver")
        sl.setStyleSheet("color:rgba(255,255,255,0.7);font-size:11px;background:transparent;")
        tc.addWidget(tl); tc.addWidget(sl); hlay.addLayout(tc); hlay.addStretch()
        self.session_badge_lbl = QLabel("Not logged in")
        self.session_badge_lbl.setStyleSheet(
            "color:white;font-size:10px;font-weight:600;"
            "background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.3);"
            "border-radius:3px;padding:3px 10px;")
        hlay.addWidget(self.session_badge_lbl)
        left.addWidget(dr_hdr)

        # ── Step 1 card: File selector ────────────────────────────────────
        s1f, s1l = mkcard(accent=BLUE)
        row_s1_hdr = QHBoxLayout(); row_s1_hdr.setSpacing(8)
        row_s1_hdr.addWidget(mkstep_badge(1, BLUE))
        row_s1_hdr.addWidget(mklbl("MRI Scan Acquisition", TEXT, 13, bold=True))
        row_s1_hdr.addStretch()
        self.file_count_badge = mkbadge("0 files", DIM, small=True)
        row_s1_hdr.addWidget(self.file_count_badge)
        s1l.addLayout(row_s1_hdr)
        s1l.addWidget(mksep())

        # File buttons
        fb_row = QHBoxLayout(); fb_row.setSpacing(8)
        add_btn = mkbtn("➕  Add Images / GIFs", BLUE)
        add_btn.clicked.connect(self._browse); fb_row.addWidget(add_btn)
        clr_btn = mkbtn_ghost("🗑 Clear", RED); clr_btn.setFixedWidth(80)
        clr_btn.clicked.connect(self._clear_files); fb_row.addWidget(clr_btn)
        s1l.addLayout(fb_row)

        self.files_list = QListWidget()
        self.files_list.setFixedHeight(96)
        self.files_list.setStyleSheet(f"""
            QListWidget{{background:{LOG_BG};color:{LOG_DIM};
                border:1px solid {BORDER};border-radius:{R_SMALL}px;
                font-size:11.5px;font-family:'Courier New',monospace;padding:4px;}}
            QListWidget::item{{padding:4px 6px;border-radius:3px;}}
            QListWidget::item:hover{{background:{SURF2};color:{TEXT};}}
        """)
        s1l.addWidget(self.files_list)

        # Patient info row
        pi_row = QHBoxLayout(); pi_row.setSpacing(10)
        pi_col1 = QVBoxLayout(); pi_col1.setSpacing(3)
        pi_col1.addWidget(mklbl("Patient ID", DIM, 10))
        self.pid_e = mkinp("PT-2020-001"); pi_col1.addWidget(self.pid_e)
        pi_col2 = QVBoxLayout(); pi_col2.setSpacing(3)
        pi_col2.addWidget(mklbl("Patient Name", DIM, 10))
        self.pname_e = mkinp("Full name"); pi_col2.addWidget(self.pname_e)
        pi_row.addLayout(pi_col1, 1); pi_row.addLayout(pi_col2, 2)
        s1l.addLayout(pi_row)

        # Age / Sex row — only required for a new (not-on-file) Patient ID;
        # auto-filled and locked once a record is found for that ID.
        as_row = QHBoxLayout(); as_row.setSpacing(10)
        as_col1 = QVBoxLayout(); as_col1.setSpacing(3)
        as_col1.addWidget(mklbl("Age", DIM, 10))
        self.page_e = mkinp("e.g. 45")
        self.page_e.setFixedWidth(70)
        as_col1.addWidget(self.page_e)
        as_col2 = QVBoxLayout(); as_col2.setSpacing(3)
        as_col2.addWidget(mklbl("Sex", DIM, 10))
        self.psex_cb = QComboBox(); self.psex_cb.addItems(["", "M", "F"])
        self.psex_cb.setFixedWidth(70); self.psex_cb.setFixedHeight(INP_H)
        self.psex_cb.setStyleSheet(f"""
            QComboBox{{
                background:{SURF2};color:{TEXT};border:1px solid {BORDER};
                border-radius:{R_SMALL}px;padding:0 8px;font-size:12.5px;
            }}
            QComboBox:focus{{border:1px solid {BLUE};}}
            QComboBox::drop-down{{border:none;width:18px;}}
        """)
        as_col2.addWidget(self.psex_cb)
        as_row.addLayout(as_col1); as_row.addLayout(as_col2); as_row.addStretch()
        s1l.addLayout(as_row)

        self.patient_lookup_lbl = QLabel("")
        self.patient_lookup_lbl.setWordWrap(True)
        self.patient_lookup_lbl.setStyleSheet(f"color:{DIM};font-size:10.5px;")
        s1l.addWidget(self.patient_lookup_lbl)

        self.pid_e.editingFinished.connect(self._lookup_patient)

        # ── Previous-phase lookup ───────────────────────────────────────────
        # The app only ever compares the current scan against the most
        # recent PRIOR scan for the same Patient ID — never a full
        # longitudinal history — so this stays a simple "check + show".
        prev_row = QHBoxLayout(); prev_row.setSpacing(8)
        self.check_prev_btn = mkbtn_ghost("🕓  Check Previous Scans", CYAN, h=30)
        self.check_prev_btn.clicked.connect(self._check_previous_scans)
        prev_row.addWidget(self.check_prev_btn)
        prev_row.addStretch()
        s1l.addLayout(prev_row)

        self.prev_scan_panel = QFrame()
        self.prev_scan_panel.setVisible(False)
        self.prev_scan_panel.setStyleSheet(
            f"background:{SURF2};border:1px solid {CYAN}44;border-radius:{R_SMALL}px;")
        psp_lay = QVBoxLayout(self.prev_scan_panel)
        psp_lay.setContentsMargins(10, 8, 10, 8); psp_lay.setSpacing(4)
        self.prev_scan_lbl = QLabel("")
        self.prev_scan_lbl.setWordWrap(True)
        self.prev_scan_lbl.setStyleSheet(f"color:{TEXT};font-size:11px;")
        psp_lay.addWidget(self.prev_scan_lbl)
        s1l.addWidget(self.prev_scan_panel)

        # ── Uploaded scan preview + quality analysis ────────────────────────
        # The uploaded MRI slice and its normalization/density/noise readout
        # live here in Step 1, right after upload — before segmentation runs.
        s1l.addWidget(mksep())
        qa_row = QHBoxLayout(); qa_row.setSpacing(12)
        prev_col = QVBoxLayout(); prev_col.setSpacing(4)
        prev_h = mklbl("UPLOADED SCAN", DIM, 9)
        prev_h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_col.addWidget(prev_h)
        self.orig_lbl = mkimg(260)
        prev_col.addWidget(self.orig_lbl)
        qa_row.addLayout(prev_col)

        qa_col = QVBoxLayout(); qa_col.setSpacing(6)
        qa_col.addWidget(mklbl("SCAN QUALITY ANALYSIS", DIM, 9, bold=True))
        self.qa_stats = {}
        for key, label, color in [("norm","Normalization",BLUE),
                                   ("density","Density",CYAN),
                                   ("noise","Noise",AMBER),
                                   ("contrast","Tissue Contrast",PURPLE),
                                   ("border","Border Sharpness",RED),
                                   ("shift","Intensity Uniformity",GREEN)]:
            row = QHBoxLayout(); row.setSpacing(6)
            row.addWidget(mklbl(f"{label}:", DIM, 10.5))
            row.addStretch()
            v = mklbl("—", color, 10.5, bold=True)
            row.addWidget(v)
            self.qa_stats[key] = v
            qa_col.addLayout(row)
        qa_row.addLayout(qa_col, 1)
        s1l.addLayout(qa_row)

        left.addWidget(s1f)

        # ── Step 2 card: Segmentation ─────────────────────────────────────
        s2f, s2l = mkcard(accent=CYAN)
        row_s2_hdr = QHBoxLayout(); row_s2_hdr.setSpacing(8)
        row_s2_hdr.addWidget(mkstep_badge(2, CYAN))
        row_s2_hdr.addWidget(mklbl("Tumor Segmentation & Volumetric Analysis", TEXT, 13, bold=True))
        s2l.addLayout(row_s2_hdr)
        s2l.addWidget(mksep())

        # Segmented result preview (original scan already shown in Step 1)
        seg_col = QVBoxLayout(); seg_col.setSpacing(4)
        seg_h = mklbl("SEGMENTED", CYAN, 9)
        seg_h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seg_col.addWidget(seg_h)
        self.seg_lbl = mkimg(300)
        seg_col.addWidget(self.seg_lbl)
        seg_row = QHBoxLayout(); seg_row.addStretch(); seg_row.addLayout(seg_col); seg_row.addStretch()
        s2l.addLayout(seg_row)

        seg_btn = mkbtn("🔬  Run CBAM + UNet Segmentation", CYAN, wide=True)
        seg_btn.clicked.connect(self._segment); s2l.addWidget(seg_btn)

        # Area stat cards
        area_row = QHBoxLayout(); area_row.setSpacing(8)
        self.area_vals = {}
        self.area_pcts = {}
        for name, col in [("Necrotic", RED), ("Edema", GREEN), ("Enhancing", BLUE), ("Total", PURPLE)]:
            fc, vl = mkstatcard(name, "—", "mm²", col)
            pc = mklbl("—", col, 10.5, bold=True)
            pc.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fc.layout().addWidget(pc)
            area_row.addWidget(fc)
            self.area_vals[name] = vl
            self.area_pcts[name] = pc
        s2l.addLayout(area_row)

        # Regional area distribution chart — visual companion to the stat cards
        s2l.addWidget(mklbl("REGIONAL AREA DISTRIBUTION (mm²)", DIM, 9, bold=True))
        self.area_chart = BarChart(height=130)
        s2l.addWidget(self.area_chart)

        # Phase-over-phase comparison chart — only populated when a previous
        # scan was found for this Patient ID (see _check_previous_scans).
        self.compare_hdr_lbl = mklbl("PHASE-OVER-PHASE COMPARISON (mm²)", DIM, 9, bold=True)
        self.compare_hdr_lbl.setVisible(False)
        s2l.addWidget(self.compare_hdr_lbl)
        self.compare_chart = BarChart(height=130)
        self.compare_chart.setVisible(False)
        s2l.addWidget(self.compare_chart)

        # Preliminary risk / life-threat indicator — automated heuristic,
        # requires radiologist confirmation (not a diagnosis).
        self.risk_panel = QFrame()
        self.risk_panel.setStyleSheet(
            f"background:{SURF2};border:1px solid {BORDER};border-radius:{R_SMALL}px;")
        risk_lay = QVBoxLayout(self.risk_panel)
        risk_lay.setContentsMargins(12, 9, 12, 9); risk_lay.setSpacing(3)
        risk_hdr = QHBoxLayout(); risk_hdr.setSpacing(8)
        risk_hdr.addWidget(mklbl("PRELIMINARY RISK INDICATOR", DIM, 9, bold=True))
        risk_hdr.addStretch()
        self.risk_badge = mkbadge("— Not yet segmented", DIM, small=True)
        risk_hdr.addWidget(self.risk_badge)
        risk_lay.addLayout(risk_hdr)
        self.risk_note = QLabel(
            "Run segmentation to compute a preliminary risk band from the "
            "segmented area — an automated estimate only, not a diagnosis.")
        self.risk_note.setWordWrap(True)
        self.risk_note.setStyleSheet(f"color:{DIM};font-size:10px;")
        risk_lay.addWidget(self.risk_note)
        s2l.addWidget(self.risk_panel)

        # ── Agentic AI analysis ─────────────────────────────────────────────
        # Unlike the fixed risk band above, this gives the model tools to
        # pull this patient's scan history / on-file profile from MongoDB
        # itself before it answers — an agent, not a single fixed prompt.
        # Wrapped in its own container so it can be hidden as one unit while
        # AI_FEATURES_ENABLED is off — the report still generates fine
        # without it (see _on_enc_done), the app just skips the AI step.
        self.agent_section = QWidget()
        agent_sec_lay = QVBoxLayout(self.agent_section)
        agent_sec_lay.setContentsMargins(0, 0, 0, 0); agent_sec_lay.setSpacing(9)
        agent_sec_lay.addWidget(mksep())
        agent_hdr = QHBoxLayout(); agent_hdr.setSpacing(8)
        agent_hdr.addWidget(mklbl("🤖  Agentic AI Analysis", PURPLE, 12, bold=True))
        agent_hdr.addStretch()
        self.agent_btn = mkbtn_ghost("Run Agent", PURPLE, h=28)
        self.agent_btn.setFixedWidth(110)
        self.agent_btn.clicked.connect(self._run_agent_analysis)
        agent_hdr.addWidget(self.agent_btn)
        agent_sec_lay.addLayout(agent_hdr)

        self.agent_status = QLabel(
            "Runs after segmentation. The agent can look up this patient's "
            "scan history and on-file profile itself before answering.")
        self.agent_status.setWordWrap(True)
        self.agent_status.setStyleSheet(f"color:{DIM};font-size:10px;")
        agent_sec_lay.addWidget(self.agent_status)

        self.agent_result = QTextEdit()
        self.agent_result.setReadOnly(True)
        self.agent_result.setVisible(False)
        self.agent_result.setMinimumHeight(160)
        self.agent_result.setMaximumHeight(220)
        self.agent_result.setStyleSheet(f"""
            QTextEdit{{
                background:{SURF2};color:{TEXT};border:1px solid {PURPLE}44;
                border-radius:{R_SMALL}px;font-size:11.5px;padding:8px 10px;
            }}
        """)
        agent_sec_lay.addWidget(self.agent_result)
        s2l.addWidget(self.agent_section)
        self.agent_section.setVisible(AI_FEATURES_ENABLED)

        left.addWidget(s2f)
        left.addStretch()

        # ════════════════════════════════════════════════════════════════════
        # RIGHT PANE — OTP + encrypt + log
        # ════════════════════════════════════════════════════════════════════
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet(f"QScrollArea{{background:{BG};border:none;}}")
        right_inner = QWidget(); right_inner.setStyleSheet(f"background:{BG};")
        right = QVBoxLayout(right_inner)
        right.setContentsMargins(12, 20, 20, 20); right.setSpacing(14)
        right_scroll.setWidget(right_inner)

        # Progress strip
        self.prog = mkprog(BLUE, h=4)
        right.addWidget(self.prog)

        # ── Step 3 card: OTP email ────────────────────────────────────────
        s3f, s3l = mkcard(accent=AMBER)
        row_s3_hdr = QHBoxLayout(); row_s3_hdr.setSpacing(8)
        row_s3_hdr.addWidget(mkstep_badge(3, AMBER))
        row_s3_hdr.addWidget(mklbl("Secure Patient Authentication", TEXT, 13, bold=True))
        row_s3_hdr.addStretch()
        self.countdown = QLabel("")
        self.countdown.setFixedWidth(72); self.countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown.setStyleSheet(
            f"background:{SURF2};color:{AMBER};border:1px solid {AMBER}44;"
            f"border-radius:{R_SMALL}px;font-size:13px;font-weight:800;padding:4px;")
        row_s3_hdr.addWidget(self.countdown)
        s3l.addLayout(row_s3_hdr)
        s3l.addWidget(mksep())

        pe_col = QVBoxLayout(); pe_col.setSpacing(3)
        pe_col.addWidget(mklbl("Patient Email", DIM, 10))
        self.email_e = mkinp("patient@hospital.com"); pe_col.addWidget(self.email_e)
        s3l.addLayout(pe_col)

        self.otp_btn = mkbtn("📧  Generate & Send OTP", AMBER, wide=True)
        self.otp_btn.clicked.connect(self._send_otp); s3l.addWidget(self.otp_btn)

        self.otp_status = QLabel("OTP not yet generated")
        self.otp_status.setWordWrap(True)
        self.otp_status.setStyleSheet(
            f"color:{DIM};font-size:11px;padding:6px 8px;"
            f"background:{SURF2};border-radius:{R_SMALL}px;")
        s3l.addWidget(self.otp_status)

        # OTP verify sub-section
        ver_f, ver_l = mkcard(accent=AMBER, pad=(12,10,12,10), radius=R_SMALL)
        ver_l.addWidget(mklbl("Doctor verification — re-enter OTP to confirm", AMBER, 11))
        ver_row = QHBoxLayout(); ver_row.setSpacing(8)
        self.doc_otp_e = mkinp("8-char OTP (e.g. X7K2P9QA)", pw=True, mono=True)
        self.doc_otp_e.setMaxLength(8); self.doc_otp_e.setEnabled(False)
        ver_row.addWidget(self.doc_otp_e)
        self.verify_btn = mkbtn("✔ Verify", AMBER)
        self.verify_btn.setFixedWidth(88); self.verify_btn.setEnabled(False)
        self.verify_btn.clicked.connect(self._verify_otp)
        ver_row.addWidget(self.verify_btn); ver_l.addLayout(ver_row)
        self.verify_status = QLabel("")
        self.verify_status.setWordWrap(True)
        self.verify_status.setStyleSheet(f"color:{DIM};font-size:11px;")
        ver_l.addWidget(self.verify_status); s3l.addWidget(ver_f)
        right.addWidget(s3f)

        # ── Step 4 card: Encrypt ──────────────────────────────────────────
        s4f, s4l = mkcard(accent=RED)
        row_s4_hdr = QHBoxLayout(); row_s4_hdr.setSpacing(8)
        row_s4_hdr.addWidget(mkstep_badge(4, RED))
        row_s4_hdr.addWidget(mklbl("Encrypted Transfer & Delivery", TEXT, 13, bold=True))
        s4l.addLayout(row_s4_hdr)
        s4l.addWidget(mksep())
        self.enc_btn = mkbtn("🔐  Encrypt Bundle & Send to Patient", RED, h=44, wide=True)
        self.enc_btn.setEnabled(False); self.enc_btn.clicked.connect(self._encrypt)
        s4l.addWidget(self.enc_btn)
        # Security badge strip
        brow = QHBoxLayout(); brow.setSpacing(6)
        for txt, c in [("AES-256-GCM",BLUE),("PBKDF2·310k",CYAN),("OTP Auth",AMBER),("HMAC Anon",GREEN)]:
            brow.addWidget(mkbadge(txt, c, small=True))
        brow.addStretch(); s4l.addLayout(brow)
        right.addWidget(s4f)

        # ── Activity log ──────────────────────────────────────────────────
        log_f, log_l = mkcard()
        log_l.addWidget(mksection_header("Activity Log", DIM2, "⬛"))
        self.log = mklog(h=240); log_l.addWidget(self.log)
        clr_l = mkbtn_ghost("Clear log", DIM, h=26)
        clr_l.setFixedWidth(80); clr_l.clicked.connect(self.log.clear)
        log_l.addWidget(clr_l)
        right.addWidget(log_f)
        right.addStretch()

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_scroll)
        splitter.setSizes([580, 420])

        self._timer = QTimer(); self._timer.timeout.connect(self._tick)
        self.session_badge = dr_hdr   # alias for compatibility


    def populate_session(self):
        """Called after login — fill session badge from Session.doctor."""
        dr   = Session.doctor or {}
        uid  = dr.get("user_id","—")
        name = dr.get("display_name", f"Dr. {uid}")
        email= dr.get("email","—")
        self.session_badge_lbl.setText(f"🩺  {name}  ·  {uid}  ·  {email}")
        self.session_badge_lbl.setStyleSheet(
            "color:white;font-size:11px;font-weight:600;"
            "background:rgba(255,255,255,0.18);"
            "border:1px solid rgba(255,255,255,0.35);"
            "border-radius:3px;padding:4px 12px;")

    def _browse(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select MRI Images / GIFs", "",
            "Images & GIFs (*.png *.jpg *.jpeg *.bmp *.tiff *.gif)")
        if not paths:
            return

        accepted, rejected = [], []
        for p in paths:
            if p in self.file_paths:
                continue
            check = assess_scan_modality(p)
            modality = check["modality"]
            if modality == "mri":
                accepted.append(p)
            elif modality == "unknown":
                rejected.append((p, check["reason"]))
                self._log(f"❌  Skipped {os.path.basename(p)} — {check['reason']}")
            else:
                # Doctor can override a heuristic misfire — this is pixel-
                # statistics screening, not a certified modality classifier.
                reply = QMessageBox.warning(
                    self, "Doesn't Look Like an MRI",
                    f"{os.path.basename(p)}\n\n{check['reason']}\n\n"
                    f"This app is for MRI brain scans only. Add this file anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    accepted.append(p)
                    self._log(f"⚠️   Added {os.path.basename(p)} despite {modality.upper()}-like check (doctor override).")
                else:
                    rejected.append((p, check["reason"]))
                    self._log(f"🚫  Rejected {os.path.basename(p)} — looks like {modality.upper()}, not MRI.")

        for p in accepted:
            self.file_paths.append(p)
        self._refresh_file_list()
        if accepted:
            self._log(f"📂  Added {len(accepted)} file(s)  —  {len(self.file_paths)} total")
        if rejected:
            QMessageBox.information(self, "Some Files Skipped",
                f"{len(rejected)} file(s) were not added because they don't "
                f"look like MRI scans. See the log for details.")

        # Preview first image-like file + run quality analysis
        for p in self.file_paths:
            if p.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff")):
                try:
                    pil = Image.open(p).convert("L").resize((252,252), Image.LANCZOS)
                    self.img_array = np.array(pil, dtype=np.uint8)
                    self.orig_lbl.setPixmap(arr_to_pixmap(self.img_array).scaled(
                        260, 260, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
                    self._update_quality_analysis()
                except Exception as e:
                    self._log(f"❌  Couldn't read {os.path.basename(p)}: {e}")
                    self.img_array = None
                break

    def _update_quality_analysis(self):
        """Normalization / density / noise / contrast / border / intensity-
        uniformity readout — Step 1, right after upload."""
        if self.img_array is None:
            for v in self.qa_stats.values(): v.setText("—")
            return
        q = analyze_scan_quality(self.img_array)
        self.qa_stats["norm"].setText(f"{q['orig_range']} → 0.00–1.00 (μ {q['norm_mean']:.2f})")
        self.qa_stats["density"].setText(f"{q['density_pct']:.1f}% tissue")
        self.qa_stats["noise"].setText(f"{q['noise_label']} ({q['noise_val']:.3f})")

        sev_color = {
            "Low": RED, "Fuzzy": RED, "High shift": RED,
            "Moderate": AMBER, "Moderate shift": AMBER,
            "Good": GREEN, "Sharp": GREEN, "Stable": GREEN,
        }
        self.qa_stats["contrast"].setText(f"{q['contrast_label']} ({q['contrast_val']:.3f})")
        self.qa_stats["contrast"].setStyleSheet(
            f"color:{sev_color.get(q['contrast_label'],TEXT)};font-size:10.5px;font-weight:700;")
        self.qa_stats["border"].setText(f"{q['border_label']} ({q['edge_var']:.4f})")
        self.qa_stats["border"].setStyleSheet(
            f"color:{sev_color.get(q['border_label'],TEXT)};font-size:10.5px;font-weight:700;")
        self.qa_stats["shift"].setText(f"{q['shift_label']} (Δ{q['intensity_shift']:.3f})")
        self.qa_stats["shift"].setStyleSheet(
            f"color:{sev_color.get(q['shift_label'],TEXT)};font-size:10.5px;font-weight:700;")

        self._log(f"📊  Quality — density {q['density_pct']:.1f}% · noise {q['noise_label']} "
                   f"· contrast {q['contrast_label']} · borders {q['border_label']} "
                   f"· intensity {q['shift_label']}")
        warnings = []
        if q["contrast_label"] == "Low": warnings.append("low tissue contrast")
        if q["border_label"] == "Fuzzy": warnings.append("fuzzy borders")
        if q["shift_label"] == "High shift": warnings.append("shifting intensity levels")
        if warnings:
            self._log(f"⚠️   Scan quality flag: {', '.join(warnings)} — may affect segmentation reliability.")

    def _clear_files(self):
        self.file_paths.clear()
        self.files_list.clear()
        self.file_count_badge.setText("0 files")
        self.img_array = None
        self.seg = None
        self.orig_lbl.setText("No image loaded")
        self.seg_lbl.setText("No image loaded")
        for v in self.area_vals.values():
            v.setText("— mm²")
        for v in self.area_pcts.values():
            v.setText("—")
        for v in self.qa_stats.values():
            v.setText("—")
        self.area_chart.clear()
        self.compare_chart.clear()
        self.compare_hdr_lbl.setVisible(False)
        self.compare_chart.setVisible(False)
        self.risk_badge.setText("— Not yet segmented")
        self.risk_badge.setStyleSheet(
            f"background:{DIM}18;color:{DIM};border:1px solid {DIM}44;"
            f"border-radius:3px;padding:2px 8px;font-size:10px;font-weight:700;")
        self.risk_note.setText(
            "Run segmentation to compute a preliminary risk band from the "
            "segmented area — an automated estimate only, not a diagnosis.")
        self.agent_result.clear()
        self.agent_result.setVisible(False)
        self.agent_status.setText(
            "Runs after segmentation. The agent can look up this patient's "
            "scan history and on-file profile itself before answering.")
        self.agent_status.setStyleSheet(f"color:{DIM};font-size:10px;")
        self._previous_scan = None
        self.prev_scan_panel.setVisible(False)
        self._log("🗑  File list cleared.")

    def _lookup_patient(self):
        """
        Auto-fill on Patient ID entry: if this ID is already on file in
        MongoDB, pull the saved name/age/sex and lock those fields (no need
        to re-type them). If it's not on file, unlock the fields so the
        doctor can enter them for this new patient.
        """
        pid = self.pid_e.text().strip()
        if not pid:
            self._set_patient_fields_locked(False)
            self.patient_lookup_lbl.setText("")
            return
        if not DB.connected:
            self._set_patient_fields_locked(False)
            self.patient_lookup_lbl.setText(
                "⚠️  Not connected to MongoDB — enter patient details manually.")
            return

        rec = DB.get_patient(pid)
        if rec:
            self.pname_e.setText(rec.get("patient_name", ""))
            self.page_e.setText(str(rec.get("age", "") or ""))
            sex = rec.get("sex", "") or ""
            idx = self.psex_cb.findText(sex)
            self.psex_cb.setCurrentIndex(idx if idx >= 0 else 0)
            self._set_patient_fields_locked(True)
            self.patient_lookup_lbl.setText(f"✅  {pid} is on file — details auto-filled.")
            self._log(f"👤  Patient {pid} found on file — auto-filled name/age/sex.")
        else:
            self.pname_e.clear(); self.page_e.clear(); self.psex_cb.setCurrentIndex(0)
            self._set_patient_fields_locked(False)
            self.patient_lookup_lbl.setText(
                f"🆕  {pid} not on file — enter patient name, age and sex.")

    def _set_patient_fields_locked(self, locked: bool):
        """Lock/unlock name+age+sex once a patient record has been retrieved."""
        self.pname_e.setEnabled(not locked)
        self.page_e.setEnabled(not locked)
        self.psex_cb.setEnabled(not locked)

    def _check_previous_scans(self):
        """
        Look up prior scans for the Patient ID currently entered. Only the
        single most recent prior scan is kept for comparison — the app
        deliberately compares consecutive phases (previous vs current),
        not a full history, since that's the clinically relevant contrast
        for tracking tumour progression/regression between visits.
        """
        pid = self.pid_e.text().strip()
        if not pid:
            QMessageBox.information(self, "Enter Patient ID",
                "Enter a Patient ID first, then check for previous scans.")
            return
        if not DB.connected:
            self.prev_scan_panel.setVisible(True)
            self.prev_scan_lbl.setText("⚠️  Not connected to MongoDB — can't look up history right now.")
            self._previous_scan = None
            return

        records = DB.get_scans_by_patient(pid, limit=20)
        self.prev_scan_panel.setVisible(True)

        if not records:
            self.prev_scan_lbl.setText(
                f"No previous scans found for {pid} — this will be treated as the baseline phase.")
            self._previous_scan = None
            self._log(f"🕓  No previous scans for {pid} (baseline).")
            return

        latest = records[0]
        areas  = latest.get("areas_mm2", {})
        ts     = (latest.get("timestamp") or "")[:19].replace("T", "  ")
        n_prior = len(records)

        parts = [f"{n:<10}: {v:.2f} mm²" for n, v in areas.items()]
        self.prev_scan_lbl.setText(
            f"✅  {n_prior} previous scan{'s' if n_prior != 1 else ''} found for {pid}. "
            f"Comparing current phase against the most recent — {ts} UTC:\n"
            + "   ·   ".join(parts))

        self._previous_scan = {"timestamp": ts, "areas": areas}
        self._log(f"🕓  Loaded previous scan for {pid} ({ts} UTC) — will compare current vs previous phase.")
        if self.seg:
            self._update_area_chart()

    def _refresh_file_list(self):
        self.files_list.clear()
        imgs = gifs = 0
        for p in self.file_paths:
            ext = Path(p).suffix.lower()
            icon = "🎞  " if ext == ".gif" else "🖼  "
            item = QListWidgetItem(f"{icon}{os.path.basename(p)}")
            self.files_list.addItem(item)
            if ext == ".gif": gifs += 1
            else: imgs += 1
        total = len(self.file_paths)
        parts = []
        if imgs: parts.append(f"{imgs} image{'s' if imgs>1 else ''}")
        if gifs: parts.append(f"{gifs} GIF{'s' if gifs>1 else ''}")
        badge = f"{total} file{'s' if total>1 else ''}" + (f"  ({', '.join(parts)})" if parts else "")
        self.file_count_badge.setText(badge)
        c = GREEN if total > 0 else DIM
        self.file_count_badge.setStyleSheet(
            f"background:{c}15;color:{c};border:1px solid {c}44;"            f"border-radius:3px;padding:4px 10px;font-size:11px;font-weight:700;")

    def _segment(self):
        if not self.file_paths:
            QMessageBox.warning(self,"No Files","Add at least one MRI image first."); return
        if self.img_array is None:
            QMessageBox.warning(self,"No Image","No image file found in the selection."); return
        self.seg = simulate_segmentation(self.img_array)
        self.seg_lbl.setPixmap(overlay_pixmap(self.img_array, self.seg).scaled(
            300,300,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        total = sum(self.seg["areas"].values()) or 1.0
        for name, val in self.seg["areas"].items():
            pct = val / total * 100
            self.area_vals[name].setText(f"{val:.1f} mm²")
            self.area_pcts[name].setText(f"{pct:.1f}%")
        self.area_vals["Total"].setText(f"{total:.1f} mm²")
        self.area_pcts["Total"].setText("100%")
        self._update_area_chart()
        self._update_risk_indicator()
        self._log("✅  Segmentation complete.")

    def _update_area_chart(self):
        """Regional area distribution bar chart, plus a Previous-vs-Current
        comparison chart if a prior scan was found for this Patient ID."""
        if not self.seg:
            self.area_chart.clear(); return
        colors = {"Necrotic": RED, "Edema": GREEN, "Enhancing": BLUE}
        bars = [(name, val, colors.get(name, BLUE))
                for name, val in self.seg["areas"].items()]
        self.area_chart.set_data(bars)

        if self._previous_scan and self._previous_scan.get("areas"):
            prev_areas = self._previous_scan["areas"]
            cats = list(self.seg["areas"].keys())
            self.compare_chart.set_grouped(cats, [
                {"name": "Previous", "color": DIM,
                 "values": [prev_areas.get(c, 0) for c in cats]},
                {"name": "Current", "color": CYAN,
                 "values": [self.seg["areas"].get(c, 0) for c in cats]},
            ])
            self.compare_hdr_lbl.setVisible(True)
            self.compare_chart.setVisible(True)
        else:
            self.compare_hdr_lbl.setVisible(False)
            self.compare_chart.setVisible(False)

    def _update_risk_indicator(self):
        """Preliminary risk band from the segmented areas — automated
        estimate only; always requires radiologist confirmation."""
        if not self.seg:
            return
        risk = assess_risk_level(self.seg["areas"])
        color_map = {"GREEN": GREEN, "CYAN": CYAN, "AMBER": AMBER, "RED": RED}
        c = color_map.get(risk["color"], DIM)
        self.risk_badge.setText(f"{risk['level']}")
        self.risk_badge.setStyleSheet(
            f"background:{c}20;color:{c};border:1px solid {c}70;"
            f"border-radius:3px;padding:2px 8px;font-size:10.5px;font-weight:800;")
        self.risk_note.setText(
            f"Total segmented area {risk['total_area']:.1f} mm²  ·  "
            f"necrotic {risk['necrotic_pct']:.1f}% of tumor.  {risk['note']}")
        self._log(f"⚠️   Preliminary risk indicator: {risk['level']} "
                   f"(total {risk['total_area']:.1f} mm², necrotic {risk['necrotic_pct']:.1f}%)")

    def _run_agent_analysis(self):
        if not AI_FEATURES_ENABLED:
            return
        if not self.seg:
            QMessageBox.warning(self,"Segment First",
                "Run segmentation before starting the agent analysis."); return
        if not AI_CFG.api_key:
            QMessageBox.information(self, "Not Configured",
                "Add an Anthropic API key to the app's .env file to enable "
                "AI-assisted analysis (ANTHROPIC_API_KEY)."); return
        if self.agent_worker and self.agent_worker.isRunning():
            return

        pid = self.pid_e.text().strip()
        quality = analyze_scan_quality(self.img_array) if self.img_array is not None else {}
        risk = assess_risk_level(self.seg["areas"])
        dr_name = (Session.doctor or {}).get("display_name", "")

        self.agent_btn.setEnabled(False)
        self.agent_status.setText("🤖  Agent is analyzing — it may look up this patient's history...")
        self.agent_status.setStyleSheet(f"color:{PURPLE};font-size:10px;font-weight:600;")
        self.agent_result.setVisible(False)

        self.agent_worker = AgentAnalysisWorker(
            pid, self.seg["areas"], quality, risk, doctor_name=dr_name)
        self.agent_worker.log.connect(self._log)
        self.agent_worker.done.connect(self._on_agent_done)
        self.agent_worker.start()

    def _on_agent_done(self, ok: bool, result: dict):
        self.agent_btn.setEnabled(True)
        if not ok:
            reason = result.get("error", "unknown error")
            if reason == "no_api_key":
                self.agent_status.setText(
                    "Runs after segmentation. The agent can look up this patient's "
                    "scan history and on-file profile itself before answering.")
                self.agent_status.setStyleSheet(f"color:{DIM};font-size:10px;")
            else:
                self.agent_status.setText(f"⚠️   Agent analysis failed — {reason}")
                self.agent_status.setStyleSheet(f"color:{RED};font-size:10px;")
            return

        self.agent_status.setText("✅  Agent analysis complete — preliminary, requires radiologist confirmation.")
        self.agent_status.setStyleSheet(f"color:{GREEN};font-size:10px;font-weight:600;")

        recs = "\n".join(f"  •  {r}" for r in result.get("recommendations", [])) or "  —"
        flags = "\n".join(f"  ⚑  {f}" for f in result.get("flags_for_review", [])) or "  —"
        text = (
            f"SUMMARY\n{result.get('summary','—')}\n\n"
            f"HISTORICAL TREND\n{result.get('historical_trend','—')}\n\n"
            f"QUALITY TREND\n{result.get('quality_trend','—')}\n\n"
            f"AGENT RISK ASSESSMENT\n{result.get('risk_assessment','—')}\n\n"
            f"RECOMMENDATIONS\n{recs}\n\n"
            f"FLAGS FOR REVIEW\n{flags}"
        )
        self.agent_result.setPlainText(text)
        self.agent_result.setVisible(True)

    def _send_otp(self):
        if not self.file_paths:
            QMessageBox.warning(self,"No Files","Add MRI files first."); return
        if self.seg is None:
            QMessageBox.warning(self,"Segment First","Run segmentation before sending OTP."); return
        pid = self.pid_e.text().strip()
        if not pid:
            QMessageBox.warning(self,"Missing Patient ID","Enter a Patient ID first."); return
        pat_name = self.pname_e.text().strip()
        pat_age  = self.page_e.text().strip()
        pat_sex  = self.psex_cb.currentText().strip()
        if self.pname_e.isEnabled():
            # Not on file — doctor must supply name, age, and sex for a new patient.
            if not pat_name or not pat_age or not pat_sex:
                QMessageBox.warning(self,"Missing Patient Details",
                    "This Patient ID isn't on file yet — enter Patient Name, "
                    "Age and Sex (M/F) before sending the OTP."); return
            if not pat_age.isdigit():
                QMessageBox.warning(self,"Invalid Age","Age must be a number."); return
        email = self.email_e.text().strip()
        if "@" not in email:
            QMessageBox.warning(self,"Invalid Email","Enter a valid patient email."); return
        if not GMAIL.sender_email:
            QMessageBox.warning(self,"Not Configured",
                "Gmail sender credentials are not configured. "
                "Set them in the app's .env file first."); return

        # Save/refresh the patient's demographic profile so this ID
        # auto-fills next time it's entered.
        DB.upsert_patient(pid, pat_name, pat_age, pat_sex)

        otp = OTP_STORE.generate()
        self._active_otp = otp
        self._log(f"🔑  OTP generated: {otp}  (valid 5 min)")
        DB.log_otp_event("generated", {"patient_email": email, "ttl_sec": OTP_TTL_SEC})
        DB.log_session("doctor", "otp_generated", f"OTP for {email}")
        self.otp_status.setText(f"Sending OTP to {email}...")
        self.otp_status.setStyleSheet(f"color:{AMBER};font-size:11px;padding:2px 4px;")
        self.otp_btn.setEnabled(False)
        # Get doctor ID from session if available
        dr_doc    = Session.doctor or {}
        doctor_id = dr_doc.get("user_id", "Doctor")
        areas     = self.seg["areas"] if self.seg else {}

        dr_name  = dr_doc.get("display_name", f"Dr. {doctor_id}")
        pat_name = self.pname_e.text().strip() if hasattr(self,"pname_e") else ""

        self.email_worker = EmailWorker(
            GMAIL.sender_email,   # doctor receives OTP to verify
            email,                # patient receives credentials + OTP
            otp, self.pid_e.text(), doctor_id, areas,
            patient_name=pat_name,
            doctor_name=dr_name,
        )
        self.email_worker.log.connect(self._log)
        self.email_worker.done.connect(self._on_email_done)
        self.email_worker.start()
        self._timer.start(1000)

    def _on_email_done(self, ok, msg):
        self.otp_btn.setEnabled(True)
        if ok:
            self._log(f"✅  {msg}")
            self.otp_status.setText("✅  Doctor OTP + Patient credentials sent — verify OTP below")
            self.otp_status.setStyleSheet(f"color:{GREEN};font-size:11px;padding:2px 4px;")
            # Enable verify step — enc_btn stays locked until doctor confirms OTP
            self.doc_otp_e.setEnabled(True)
            self.verify_btn.setEnabled(True)
            self.verify_status.setText("Enter the OTP you received to confirm it matches")
            self.verify_status.setStyleSheet(f"color:{AMBER};font-size:11px;padding:2px 4px;")
        else:
            self._log(f"❌  {msg}")
            self.otp_status.setText("❌  Email failed — check Settings")
            self.otp_status.setStyleSheet(f"color:{RED};font-size:11px;padding:2px 4px;")
            OTP_STORE.clear()

    def _verify_otp(self):
        entered = self.doc_otp_e.text().strip().upper()
        valid, reason = OTP_STORE.verify(entered)
        if valid:
            self.verify_status.setText("✅  OTP verified — encryption unlocked")
            self.verify_status.setStyleSheet(f"color:{GREEN};font-size:11px;padding:2px 4px;")
            self.enc_btn.setEnabled(True)
            self.verify_btn.setEnabled(False)
            self.doc_otp_e.setEnabled(False)
            self._log("✅  Doctor OTP verification passed.")
            DB.log_otp_event("doctor_verified")
            DB.log_session("doctor", "otp_verified", "Doctor confirmed OTP before encrypting")
        else:
            self.verify_status.setText(f"❌  {reason}")
            self.verify_status.setStyleSheet(f"color:{RED};font-size:11px;padding:2px 4px;")
            self._log(f"❌  OTP verify failed: {reason}")
            DB.log_otp_event("doctor_verify_failed", {"reason": reason})

    def _encrypt(self):
        if not CRYPTO_OK:
            QMessageBox.critical(self,"Missing","pip install cryptography"); return
        if OTP_STORE.seconds_remaining() == 0:
            QMessageBox.warning(self,"OTP Expired","OTP expired. Please resend."); return
        self.enc_btn.setEnabled(False); self.prog.setValue(0)
        dr       = Session.doctor or {}
        dr_name  = dr.get("display_name", f"Dr. {dr.get('user_id','')}")
        if not self.file_paths:
            QMessageBox.warning(self,"No Files","Add MRI files before encrypting."); return
        self.enc_worker = EncryptWorker(
            self.file_paths,
            self.pid_e.text(),
            self.pname_e.text().strip() or f"Patient {self.pid_e.text()}",
            self.email_e.text().strip(),
            self._active_otp,
            self.seg,
            doctor_name=dr_name,
            quality=analyze_scan_quality(self.img_array) if self.img_array is not None else None,
            risk=assess_risk_level(self.seg["areas"]) if self.seg else None,
        )
        self.enc_worker.progress.connect(self.prog.setValue)
        self.enc_worker.log.connect(self._log)
        self.enc_worker.done.connect(self._on_enc_done)
        self.enc_worker.err.connect(
            lambda m: (self.enc_btn.setEnabled(True), self._log(f"❌ {m}")))
        self.enc_worker.start()

    def _on_enc_done(self, path: str, anon_id: str, areas: dict):
        self.enc_btn.setEnabled(True)
        OTP_STORE.clear(); self._timer.stop(); self.countdown.setText("")
        self._active_otp = None
        self.doc_otp_e.clear(); self.doc_otp_e.setEnabled(False)
        self.verify_btn.setEnabled(False)
        self.verify_status.setText("")

        # Stash everything _finish_report will need once we're ready to build
        # the PDF — either right away, or after the AI worker returns.
        self._pending_report = dict(
            path=path, anon_id=anon_id, areas=areas,
            doctor_id=(Session.doctor or {}).get("user_id", "Doctor"),
            pat_email=self.email_e.text().strip(),
            pat_id=self.pid_e.text().strip(),
            overlay=overlay_array(self.img_array, self.seg) if (self.img_array is not None and self.seg) else None,
            previous_areas=(self._previous_scan or {}).get("areas"),
            previous_timestamp=(self._previous_scan or {}).get("timestamp"),
        )

        if AI_FEATURES_ENABLED and AI_CFG.api_key:
            dr_name = (Session.doctor or {}).get("display_name", "")
            self.ai_worker = AIFindingsWorker(
                areas, self._pending_report["pat_id"], dr_name,
                previous_areas=self._pending_report["previous_areas"])
            self.ai_worker.log.connect(self._log)
            self.ai_worker.done.connect(self._on_ai_findings_done)
            self.ai_worker.start()
        else:
            # AI disabled (or no API key) — app generates the report itself,
            # straight from the computed numbers, no AI narrative section.
            self._finish_report(None)

    def _on_ai_findings_done(self, ok: bool, result: dict):
        if not ok:
            reason = result.get("error", "unknown error")
            if reason != "no_api_key":
                self._log(f"⚠️   AI findings skipped — {reason}")
        self._finish_report(result if ok else None)

    def _finish_report(self, ai_findings: dict | None):
        r = self._pending_report
        self._log("📄  Generating patient report...")
        report_path = generate_patient_report_pdf(
            patient_id          = r["pat_id"],
            anon_id             = r["anon_id"],
            doctor_id           = r["doctor_id"],
            patient_email       = r["pat_email"],
            areas               = r["areas"],
            enc_filename        = os.path.basename(r["path"]),
            img_array           = self.img_array,
            overlay_array       = r["overlay"],
            ai_findings         = ai_findings,
            previous_areas      = r["previous_areas"],
            previous_timestamp  = r["previous_timestamp"],
        )
        # Reset file list after successful send
        self._clear_files()
        if report_path:
            ext = "PDF" if report_path.endswith(".pdf") else "TXT"
            suffix = " (+ AI findings)" if ai_findings else ""
            self._log(f"✅  Report ({ext}){suffix} → {report_path}")
            DB.log_session("doctor", "report_generated",
                f"{ext} report for {r['pat_id']} → {os.path.basename(report_path)}")
        else:
            self._log("⚠️   Report generation failed (install reportlab for PDF)")

        self._pending_report = None
        self.sent.emit()

    def _tick(self):
        rem = OTP_STORE.seconds_remaining()
        if rem <= 0:
            self._timer.stop(); self.countdown.setText("EXPIRED")
            self.countdown.setStyleSheet(
                f"background:{SURF2};color:{RED};border:1px solid {RED}55;"
                f"border-radius:3px;font-size:13px;font-weight:700;padding:4px 8px;")
            self.enc_btn.setEnabled(False)
            self._log("⏰  OTP expired. Regenerate and resend.")
            DB.log_otp_event("expired")
            DB.log_session("system", "otp_expired", "OTP TTL elapsed")
        else:
            m, s = divmod(rem, 60)
            self.countdown.setText(f"⏱ {m:02d}:{s:02d}")
            c = RED if rem < 60 else AMBER
            self.countdown.setStyleSheet(
                f"background:{SURF2};color:{c};border:1px solid {c}55;"
                f"border-radius:3px;font-size:13px;font-weight:700;padding:4px 8px;")

    def _log(self, msg): self.log.append(msg)


# ── Patient panel ─────────────────────────────────────────────────────────────


class PatientPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self._decrypted_files = []
        self._decrypted_arr   = None
        self._decrypted_meta  = None
        self.ai_worker_pt = None
        self._last_ai_error = None
        self._pending_patient_report = None
        self._last_report_path = None
        self._build(); self._refresh()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(f"QSplitter::handle{{background:{BORDER};}}")
        root.addWidget(splitter)

        # ════════════════════════════════════════════════════════════════════
        # LEFT PANE — incoming scans + decrypt
        # ════════════════════════════════════════════════════════════════════
        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True)
        left_scroll.setStyleSheet(f"QScrollArea{{background:{BG};border:none;}}")
        left_inner = QWidget(); left_inner.setStyleSheet(f"background:{BG};")
        left = QVBoxLayout(left_inner)
        left.setContentsMargins(20, 20, 12, 20); left.setSpacing(14)
        left_scroll.setWidget(left_inner)

        # Header
        pt_hdr = QFrame()
        pt_hdr.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {GREEN},stop:1 {CYAN});"
            f"border-radius:{RADIUS}px;border:1px solid {GREEN};")
        hl = QHBoxLayout(pt_hdr); hl.setContentsMargins(16, 12, 16, 12); hl.setSpacing(12)
        ic2 = QLabel("👤"); ic2.setStyleSheet("font-size:22px;background:transparent;")
        hl.addWidget(ic2)
        tc2 = QVBoxLayout(); tc2.setSpacing(1)
        tl2 = QLabel("Patient Workspace"); tl2.setStyleSheet("color:white;font-size:15px;font-weight:800;background:transparent;")
        sl2 = QLabel("Select encrypted scan  ·  Enter OTP  ·  Download")
        sl2.setStyleSheet("color:rgba(255,255,255,0.7);font-size:11px;background:transparent;")
        tc2.addWidget(tl2); tc2.addWidget(sl2); hl.addLayout(tc2); hl.addStretch()
        left.addWidget(pt_hdr)

        # ── Incoming scans card ───────────────────────────────────────────
        sc_f, sc_l = mkcard(accent=GREEN)
        sc_hdr = QHBoxLayout(); sc_hdr.setSpacing(8)
        sc_hdr.addWidget(mkstep_badge(1, GREEN))
        sc_hdr.addWidget(mklbl("Incoming Secure Transfers", TEXT, 13, bold=True))
        sc_hdr.addStretch()
        ref_btn = mkbtn_ghost("🔄 Refresh", GREEN, h=30); ref_btn.setFixedWidth(96)
        ref_btn.clicked.connect(self._refresh); sc_hdr.addWidget(ref_btn)
        self.file_count_lbl = mkbadge("0", DIM, small=True); sc_hdr.addWidget(self.file_count_lbl)
        sc_l.addLayout(sc_hdr)
        sc_l.addWidget(mksep())

        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(200); self.file_list.setMaximumHeight(260)
        self.file_list.setSpacing(2)
        self.file_list.setStyleSheet(f"""
            QListWidget{{background:{SURF2};color:{TEXT};
                border:1px solid {BORDER};border-radius:{R_SMALL}px;
                font-size:11.5px;padding:4px;outline:none;}}
            QListWidget::item{{padding:8px 10px;border-radius:2px;}}
            QListWidget::item:selected{{background:{GREEN}18;color:{GREEN};border:1px solid {GREEN}33;}}
            QListWidget::item:hover{{background:{SURF3};}}
        """)
        sc_l.addWidget(self.file_list)
        self.selected_lbl = QLabel("No file selected")
        self.selected_lbl.setStyleSheet(f"color:{DIM};font-size:11px;")
        sc_l.addWidget(self.selected_lbl)
        self.file_list.currentItemChanged.connect(self._on_file_selected)
        left.addWidget(sc_f)

        # ── Decrypt card ──────────────────────────────────────────────────
        dc_f, dc_l = mkcard(accent=GREEN)
        dc_hdr = QHBoxLayout(); dc_hdr.setSpacing(8)
        dc_hdr.addWidget(mkstep_badge(2, GREEN))
        dc_hdr.addWidget(mklbl("Identity Verification & Decryption", TEXT, 13, bold=True))
        dc_l.addLayout(dc_hdr)
        dc_l.addWidget(mksep())

        # Hint
        hint_f, hint_l = mkcard(pad=(10, 8, 10, 8), radius=R_SMALL)
        hint_row = QHBoxLayout(); hint_row.setSpacing(6)
        hint_row.addWidget(QLabel("💡"))
        self.hint_lbl = QLabel("Enter your email and the OTP sent by your doctor.")
        self.hint_lbl.setStyleSheet(f"color:{DIM2};font-size:11px;")
        self.hint_lbl.setWordWrap(True); hint_row.addWidget(self.hint_lbl)
        hint_l.addLayout(hint_row); dc_l.addWidget(hint_f)

        em_col = QVBoxLayout(); em_col.setSpacing(3)
        em_col.addWidget(mklbl("Your Email", DIM, 10))
        self.pat_email_e = mkinp("your@email.com"); em_col.addWidget(self.pat_email_e)
        dc_l.addLayout(em_col)

        otp_col = QVBoxLayout(); otp_col.setSpacing(3)
        otp_col.addWidget(mklbl("Decryption OTP", DIM, 10))
        otp_irow = QHBoxLayout(); otp_irow.setSpacing(8)
        self.otp_e = mkinp("Enter 8-char OTP", pw=True, mono=True); self.otp_e.setMaxLength(8)
        otp_irow.addWidget(self.otp_e)
        self.resend_btn = mkbtn_ghost("🔄 New OTP", AMBER)
        self.resend_btn.setFixedWidth(104)
        self.resend_btn.setToolTip("Request a fresh OTP")
        self.resend_btn.clicked.connect(self._resend_otp)
        otp_irow.addWidget(self.resend_btn); otp_col.addLayout(otp_irow)
        self.resend_status = QLabel("")
        self.resend_status.setStyleSheet(f"color:{DIM};font-size:10px;")
        otp_col.addWidget(self.resend_status); dc_l.addLayout(otp_col)

        self.dec_btn = mkbtn("🔓  Decrypt MRI Bundle", GREEN, h=44, wide=True)
        self.dec_btn.clicked.connect(self._decrypt); dc_l.addWidget(self.dec_btn)
        self.prog = mkprog(GREEN, h=4); dc_l.addWidget(self.prog)
        left.addWidget(dc_f)

        # Activity log (left)
        log_f2, log_l2 = mkcard()
        log_l2.addWidget(mksection_header("Activity", DIM2, "⬛"))
        self.log = mklog(h=160); log_l2.addWidget(self.log)
        left.addWidget(log_f2)
        left.addStretch()

        # ════════════════════════════════════════════════════════════════════
        # RIGHT PANE — MRI viewer + report + download
        # ════════════════════════════════════════════════════════════════════
        right_scroll = QScrollArea(); right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet(f"QScrollArea{{background:{BG};border:none;}}")
        right_inner = QWidget(); right_inner.setStyleSheet(f"background:{BG};")
        right = QVBoxLayout(right_inner)
        right.setContentsMargins(12, 20, 20, 20); right.setSpacing(14)
        right_scroll.setWidget(right_inner)

        # ── MRI viewer card ───────────────────────────────────────────────
        mv_f, mv_l = mkcard(accent=CYAN)
        mv_l.addWidget(mksection_header("Decrypted MRI Preview", CYAN, "🖼"))
        mv_l.addWidget(mksep())
        viewer_row = QHBoxLayout(); viewer_row.setSpacing(14)

        img_col = QVBoxLayout(); img_col.setSpacing(4)
        img_col.addWidget(mklbl("MRI SCAN", DIM, 9))
        self.mri_lbl = mkimg(234)
        self.mri_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_col.addWidget(self.mri_lbl)
        viewer_row.addLayout(img_col)

        rep_col = QVBoxLayout(); rep_col.setSpacing(4)
        rep_col.addWidget(mklbl("TUMOUR REPORT", DIM, 9))
        self.report = QTextEdit(); self.report.setReadOnly(True)
        self.report.setFixedSize(210, 234)
        self.report.setStyleSheet(f"""
            QTextEdit{{
                background:{LOG_BG};color:{LOG_DIM};
                border:1px solid {BORDER};border-radius:{R_SMALL}px;
                font-size:11px;font-family:'Courier New',monospace;
                padding:10px;line-height:1.6;
            }}
        """)
        self.report.setPlaceholderText("Tumour report appears after decryption…")
        rep_col.addWidget(self.report)
        viewer_row.addLayout(rep_col)
        mv_l.addLayout(viewer_row)
        right.addWidget(mv_f)

        # ── Download card ─────────────────────────────────────────────────
        dl_f, dl_l = mkcard(accent=GREEN)
        dl_hdr = QHBoxLayout(); dl_hdr.setSpacing(8)
        dl_hdr.addWidget(mkstep_badge(3, GREEN))
        dl_hdr.addWidget(mklbl("Scan File Retrieval", TEXT, 13, bold=True))
        dl_hdr.addStretch()
        self.dl_count_lbl = mkbadge("0 files", DIM, small=True)
        dl_hdr.addWidget(self.dl_count_lbl)
        dl_l.addLayout(dl_hdr)
        dl_l.addWidget(mksep())

        self.dl_list = QListWidget()
        self.dl_list.setFixedHeight(100)
        self.dl_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.dl_list.setStyleSheet(f"""
            QListWidget{{background:{SURF2};color:{TEXT};
                border:1px solid {BORDER};border-radius:{R_SMALL}px;
                font-size:11.5px;font-family:'Courier New',monospace;padding:4px;}}
            QListWidget::item{{padding:6px 8px;border-radius:3px;}}
            QListWidget::item:selected{{background:{GREEN}22;color:{GREEN};}}
            QListWidget::item:hover{{background:{SURF3};}}
        """)
        dl_l.addWidget(self.dl_list)

        dl_btn_row = QHBoxLayout(); dl_btn_row.setSpacing(8)
        self.dl_zip_btn = mkbtn("📦  Download All as ZIP", GREEN, h=42)
        self.dl_zip_btn.setEnabled(False); self.dl_zip_btn.clicked.connect(self._download_zip)
        dl_btn_row.addWidget(self.dl_zip_btn)
        self.dl_sel_btn = mkbtn("💾  Save Selected", CYAN, h=42)
        self.dl_sel_btn.setEnabled(False); self.dl_sel_btn.clicked.connect(self._download_selected)
        dl_btn_row.addWidget(self.dl_sel_btn)
        dl_l.addLayout(dl_btn_row)

        self.dl_status = QLabel("Decrypt a bundle to see files here.")
        self.dl_status.setStyleSheet(
            f"color:{DIM};font-size:11px;padding:4px 8px;"
            f"background:{SURF2};border-radius:{R_SMALL}px;")
        self.dl_status.setWordWrap(True); dl_l.addWidget(self.dl_status)
        right.addWidget(dl_f)

        # ── PDF report card ─────────────────────────────────────────────────
        rp_f, rp_l = mkcard(accent=CYAN)
        rp_hdr = QHBoxLayout(); rp_hdr.setSpacing(8)
        rp_hdr.addWidget(mkstep_badge(4, CYAN))
        rp_hdr.addWidget(mklbl("Diagnostic Report Generation", TEXT, 13, bold=True))
        rp_hdr.addStretch()
        ai_on = AI_FEATURES_ENABLED and bool(AI_CFG.api_key)
        rp_hdr.addWidget(mkbadge(
            "🤖 AI findings on" if ai_on else "AI findings off",
            PURPLE if ai_on else DIM, small=True))
        rp_l.addLayout(rp_hdr)
        rp_l.addWidget(mksep())

        rp_note = QLabel(
            "Rebuilds the tumor localization overlay and results table from "
            "your decrypted scan, matching the report your doctor generated. "
            "Enable an API key in ⚙ Settings to include a draft AI narrative.")
        rp_note.setWordWrap(True)
        rp_note.setStyleSheet(f"color:{DIM};font-size:11px;")
        rp_l.addWidget(rp_note)

        rp_btn_row = QHBoxLayout(); rp_btn_row.setSpacing(8)
        self.report_btn = mkbtn("📄  Generate PDF Report", CYAN, h=42)
        self.report_btn.setEnabled(False)
        self.report_btn.clicked.connect(self._generate_pdf_report)
        rp_btn_row.addWidget(self.report_btn)
        self.save_report_btn = mkbtn("💾  Save Report As...", GREEN, h=42)
        self.save_report_btn.setEnabled(False)
        self.save_report_btn.clicked.connect(self._save_report_copy)
        rp_btn_row.addWidget(self.save_report_btn)
        rp_l.addLayout(rp_btn_row)

        self.report_status = QLabel("Decrypt a bundle first.")
        self.report_status.setWordWrap(True)
        self.report_status.setStyleSheet(
            f"color:{DIM};font-size:11px;padding:4px 8px;"
            f"background:{SURF2};border-radius:{R_SMALL}px;")
        rp_l.addWidget(self.report_status)
        right.addWidget(rp_f)

        right.addStretch()

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_scroll)
        splitter.setSizes([500, 500])


    def refresh(self):
        self._refresh()
        self._autofill_email()

    def _autofill_email(self):
        """Auto-fill email from patient session if logged in."""
        pat = Session.patient
        if pat and pat.get("email"):
            email = pat["email"]
            self.pat_email_e.setText(email)
            self.hint_lbl.setText(
                f"✅  Email auto-filled from session: {email}")
        else:
            self.hint_lbl.setText(
                "Enter the email your doctor sent the OTP to.")

    def _resend_otp(self):
        """Send a fresh OTP to the patient's email."""
        pat = Session.patient
        if not pat:
            self.resend_status.setText("❌  Not logged in")
            self.resend_status.setStyleSheet(f"color:{RED};font-size:11px;padding:2px;")
            return
        if not GMAIL.sender_email:
            self.resend_status.setText("❌  Gmail not configured")
            self.resend_status.setStyleSheet(f"color:{RED};font-size:11px;padding:2px;")
            return
        uid   = pat.get("user_id","")
        email = pat.get("email","")
        otp   = LOGIN_OTP_STORE.generate("patient", uid)
        self.resend_status.setText(f"📧  Sending fresh OTP to {email}...")
        self.resend_status.setStyleSheet(f"color:{AMBER};font-size:11px;padding:2px;")
        self.resend_btn.setEnabled(False)
        self._resend_worker = LoginEmailWorker(email, otp, "patient", uid)
        self._resend_worker.log.connect(self._log)
        self._resend_worker.done.connect(self._on_resend_done)
        self._resend_worker.start()

    def _on_resend_done(self, ok: bool, msg: str):
        self.resend_btn.setEnabled(True)
        if ok:
            self.resend_status.setText(f"✅  Fresh OTP sent — check your email")
            self.resend_status.setStyleSheet(f"color:{GREEN};font-size:11px;padding:2px;")
            self.otp_e.clear(); self.otp_e.setFocus()
            self._log(f"📧  Fresh OTP sent: {msg}")
            DB.log_otp_event("patient_otp_resent",
                {"user_id": Session.patient.get("user_id","") if Session.patient else ""})
        else:
            self.resend_status.setText(f"❌  {msg}")
            self.resend_status.setStyleSheet(f"color:{RED};font-size:11px;padding:2px;")

    def _refresh(self):
        self.file_list.clear()
        # Sort newest first by modification time
        files = sorted(
            Path(SHARED_FOLDER).glob(f"*{ENC_SUFFIX}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            it = QListWidgetItem("  No encrypted scans yet — waiting for doctor to send...")
            it.setForeground(QColor(DIM))
            self.file_list.addItem(it)
            if hasattr(self, "file_count_lbl"):
                self.file_count_lbl.setText("0 files")
            return

        if hasattr(self, "file_count_lbl"):
            self.file_count_lbl.setText(f"{len(files)} file{'s' if len(files)!=1 else ''}")

        # Build a quick lookup from DB scans for patient_id + timestamp
        db_scans = {s.get("filename",""): s for s in DB.get_scans(limit=500)}

        for idx, p in enumerate(files, 1):
            fname    = p.name
            size_kb  = p.stat().st_size / 1024
            mtime    = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            time_str = mtime.strftime("%Y-%m-%d  %H:%M")

            # Enrich: try sidecar manifest first, then DB
            manifest_path = str(p).replace(ENC_SUFFIX, ".manifest.json")
            manifest_rec  = {}
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path) as mf:
                        manifest_rec = json.load(mf)
                except Exception:
                    pass

            db_rec     = db_scans.get(fname, {})
            merged     = {**db_rec, **manifest_rec}   # manifest wins
            patient_id   = merged.get("patient_id", "—")
            patient_name = merged.get("patient_name", "")
            doctor_id    = merged.get("doctor_id", "")
            doctor_name  = merged.get("doctor_name", "")
            anon_id      = merged.get("anon_id", "")
            algorithm    = merged.get("algorithm", "AES-256-GCM")
            # Use manifest timestamp if available (more precise)
            if manifest_rec.get("timestamp"):
                try:
                    mtime    = datetime.fromisoformat(
                        manifest_rec["timestamp"].replace("Z",""))
                    time_str = mtime.strftime("%Y-%m-%d  %H:%M")
                except Exception:
                    pass

            # Parse original scan name from filename stem
            # Format: <original_stem>_ANON-XXXXXXXXXX.enc
            stem = p.stem   # e.g. volume_1_slice_97_ANON-D4AF12B2F6
            parts = stem.rsplit("_ANON-", 1)
            scan_name = parts[0] if len(parts) == 2 else stem

            # Build display line
            name_display = (f"{patient_name}  ({patient_id})"
                            if patient_name else f"ID: {patient_id}")
            dr_display   = (f"Dr. {doctor_id}"
                            if doctor_id else "—")
            line = (
                f"  {idx:>2}.  "
                f"{'🔒  ' + scan_name:<36}  "
                f"{name_display:<28}  "
                f"From: {dr_display:<14}  "
                f"{time_str}  "
                f"{size_kb:>6.1f} KB"
            )

            it = QListWidgetItem(line)
            it.setData(Qt.ItemDataRole.UserRole, str(p))

            # Colour newest (first) more prominently
            if idx == 1:
                it.setForeground(QColor(TEXT))
                f = QFont(); f.setBold(True); it.setFont(f)
            else:
                it.setForeground(QColor(GREEN))

            # Tooltip with full details
            tooltip = "\n".join([
                f"File:         {fname}",
                f"Patient Name: {patient_name or '—'}",
                f"Patient ID:   {patient_id}",
                f"Anon ID:      {anon_id or '—'}",
                f"Doctor:       {doctor_name or '—'}  ({doctor_id or '—'})",
                f"Sent:         {time_str} UTC",
                f"Size:         {p.stat().st_size:,} bytes",
                f"Algorithm:    {algorithm}",
                f"Path:         {str(p)}",
            ])
            it.setToolTip(tooltip)
            self.file_list.addItem(it)

        # Auto-select the newest (most likely intended for this patient)
        if self.file_list.count() > 0:
            self.file_list.setCurrentRow(0)

    def _decrypt(self):
        if not CRYPTO_OK:
            QMessageBox.critical(self,"Missing","pip install cryptography"); return
        sel = self.file_list.currentItem()
        if not sel or not sel.data(Qt.ItemDataRole.UserRole):
            QMessageBox.warning(self,"No File","Select an encrypted file first."); return
        email = self.pat_email_e.text().strip()
        if "@" not in email or "." not in email:
            QMessageBox.warning(self,"Invalid Email",
                "Enter the email address your doctor sent the OTP to."); return
        otp = self.otp_e.text().strip().upper()
        if len(otp) != OTP_LENGTH:
            QMessageBox.warning(self,"Invalid OTP",
                f"OTP must be exactly {OTP_LENGTH} characters."); return
        self.dec_btn.setEnabled(False); self.prog.setValue(0)
        self.worker = DecryptWorker(sel.data(Qt.ItemDataRole.UserRole), email, otp)
        self.worker.progress.connect(self.prog.setValue)
        self.worker.log.connect(self._log)
        self.worker.done.connect(self._on_done)   # (arr, meta, file_list)
        self.worker.err.connect(self._on_err)
        self.worker.start()

    def _on_file_selected(self, current, previous):
        """Update the selected file label when user clicks a row."""
        if not current or not current.data(Qt.ItemDataRole.UserRole):
            if hasattr(self, "selected_lbl"):
                self.selected_lbl.setText("No file selected")
            return
        path = current.data(Qt.ItemDataRole.UserRole)
        fname = Path(path).name
        # Extract scan name from filename
        stem  = Path(path).stem
        parts = stem.rsplit("_ANON-", 1)
        scan  = parts[0] if len(parts) == 2 else stem
        if hasattr(self, "selected_lbl"):
            self.selected_lbl.setText(f"Selected: {scan}")
            self.selected_lbl.setStyleSheet(
                f"color:{GREEN};font-size:11px;font-weight:600;")

    def _on_done(self, arr: np.ndarray, meta: dict, file_list: list):
        self.dec_btn.setEnabled(True)
        self._decrypted_files = file_list
        self._decrypted_arr   = arr
        self._decrypted_meta  = meta
        self.report_btn.setEnabled(True)
        self.save_report_btn.setEnabled(False)
        self.report_status.setText("Decrypted — click above to generate a PDF report.")
        self.report_status.setStyleSheet(
            f"color:{DIM};font-size:11px;padding:4px 8px;"
            f"background:{SURF2};border-radius:{R_SMALL}px;")

        self.mri_lbl.setPixmap(arr_to_pixmap(arr).scaled(
            262, 262, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

        areas    = meta.get("areas_mm2", {}); total = sum(areas.values())
        pat_name = meta.get("patient_name", "—")
        dr_name  = meta.get("doctor_name",  "—")
        dr_id    = meta.get("doctor_id",    "—")
        n_files  = meta.get("file_count",   len(file_list))
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "   TUMOUR AREA REPORT",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  Patient  : {pat_name}",
            f"  Anon ID  : {meta.get('anon_id','—')}",
            f"  Doctor   : {dr_name}  [{dr_id}]",
            f"  Date     : {meta.get('timestamp','')[:10]}",
            f"  Files    : {n_files}",
            "", "  Segmented Regions:",
        ]
        for n in ("Necrotic", "Edema", "Enhancing"):
            lines.append(f"   • {n:<12} {areas.get(n, 0.0):.2f} mm²")
        lines += [
            "", f"  Total    : {total:.2f} mm²", "",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "  Security",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "  Enc : AES-256-GCM ✅",
            "  OTP : Verified   ✅",
            "  Mail: Verified   ✅",
            "  ID  : Anonymised ✅",
        ]
        self.report.setText("\n".join(lines))

        # ── Populate download file list ────────────────────────────────────
        self.dl_list.clear()
        for name, data in file_list:
            ext  = Path(name).suffix.lower()
            icon = "🎞  " if ext == ".gif" else "🖼  "
            sz   = f"  ({len(data)/1024:.1f} KB)"
            self.dl_list.addItem(f"{icon}{name}{sz}")
        n = len(file_list)
        self.dl_count_lbl.setText(f"{n} file{'s' if n!=1 else ''}")
        self.dl_zip_btn.setEnabled(n > 0)
        self.dl_sel_btn.setEnabled(n > 0)
        self.dl_status.setText("Select files then Save, or Download Full ZIP.")
        self.dl_status.setStyleSheet(f"color:{GREEN};font-size:11px;padding:2px;")

    def _download_zip(self):
        if not self._decrypted_files:
            return
        pid   = (Session.patient or {}).get("user_id", "patient")
        fname = f"mri_bundle_{pid}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save ZIP Bundle", fname, "ZIP files (*.zip)")
        if not save_path:
            return
        try:
            with zipfile.ZipFile(save_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, data in self._decrypted_files:
                    zf.writestr(name, data)
            sz = os.path.getsize(save_path) / 1024
            self.dl_status.setText(
                f"✅  Saved: {os.path.basename(save_path)}  ({sz:.1f} KB)")
            self.dl_status.setStyleSheet(f"color:{GREEN};font-size:11px;padding:2px;")
            self._log(f"📦  ZIP saved → {save_path}")
            DB.log_session("patient", "downloaded_zip", os.path.basename(save_path))
        except Exception as e:
            self.dl_status.setText(f"❌  {e}")
            self.dl_status.setStyleSheet(f"color:{RED};font-size:11px;padding:2px;")

    def _download_selected(self):
        selected_rows = [idx.row() for idx in self.dl_list.selectedIndexes()]
        if not selected_rows:
            QMessageBox.information(self, "Select Files",
                "Click one or more files in the list to select them first.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose Save Folder")
        if not folder:
            return
        try:
            saved = 0
            for row in selected_rows:
                name, data = self._decrypted_files[row]
                out = os.path.join(folder, name)
                with open(out, "wb") as f:
                    f.write(data)
                saved += 1
                self._log(f"💾  Saved: {name}")
            self.dl_status.setText(f"✅  {saved} file(s) saved to {folder}")
            self.dl_status.setStyleSheet(f"color:{GREEN};font-size:11px;padding:2px;")
            DB.log_session("patient", "downloaded_selected", f"{saved} file(s) → {folder}")
        except Exception as e:
            self.dl_status.setText(f"❌  {e}")
            self.dl_status.setStyleSheet(f"color:{RED};font-size:11px;padding:2px;")
            self._log(f"❌  Save failed: {e}")

    def _on_err(self, msg):
        self.dec_btn.setEnabled(True); self._log(f"❌  {msg}")
        QMessageBox.critical(self, "Decryption Failed", msg)

    # ── PDF report generation (patient-side) ────────────────────────────────
    def _generate_pdf_report(self):
        if self._decrypted_arr is None or not self._decrypted_meta:
            QMessageBox.information(self, "Decrypt First",
                "Decrypt a bundle before generating a report.")
            return

        self.report_btn.setEnabled(False)
        self.save_report_btn.setEnabled(False)
        self.report_status.setText("Rebuilding tumor overlay from decrypted scan...")
        self.report_status.setStyleSheet(
            f"color:{AMBER};font-size:11px;padding:4px 8px;"
            f"background:{SURF2};border-radius:{R_SMALL}px;")

        meta  = self._decrypted_meta
        arr   = self._decrypted_arr
        areas = meta.get("areas_mm2", {})
        # Recompute masks locally (same deterministic algorithm the doctor
        # used) purely to render the overlay image — the numbers themselves
        # come from the doctor's original areas_mm2, not this recomputation.
        seg     = simulate_segmentation(arr)
        overlay = overlay_array(arr, seg)

        self._pending_patient_report = dict(meta=meta, arr=arr, areas=areas, overlay=overlay)

        if AI_FEATURES_ENABLED and AI_CFG.api_key:
            self.report_status.setText("Drafting AI-assisted findings...")
            self.ai_worker_pt = AIFindingsWorker(
                areas, meta.get("anon_id", ""), meta.get("doctor_name", ""))
            self.ai_worker_pt.log.connect(self._log)
            self.ai_worker_pt.done.connect(self._on_pt_ai_findings_done)
            self.ai_worker_pt.start()
        else:
            self._finish_patient_report(None)

    def _on_pt_ai_findings_done(self, ok: bool, result: dict):
        self._last_ai_error = None if ok else result.get("error", "unknown error")
        if not ok and self._last_ai_error != "no_api_key":
            self._log(f"⚠️   AI findings skipped — {self._last_ai_error}")
        self._finish_patient_report(result if ok else None)

    def _finish_patient_report(self, ai_findings: dict | None):
        p    = self._pending_patient_report
        meta = p["meta"]
        self._log("📄  Generating patient-side PDF report...")

        report_path = generate_patient_report_pdf(
            patient_id     = meta.get("anon_id", "patient"),
            anon_id        = meta.get("anon_id", ""),
            doctor_id      = meta.get("doctor_id", ""),
            patient_email  = self.pat_email_e.text().strip(),
            areas          = p["areas"],
            enc_filename   = "decrypted_bundle",
            img_array      = p["arr"],
            overlay_array  = p["overlay"],
            ai_findings    = ai_findings,
        )
        self.report_btn.setEnabled(True)
        self._pending_patient_report = None

        if not report_path:
            self.report_status.setText(
                "⚠️  Report generation failed (install reportlab for PDF).")
            self.report_status.setStyleSheet(
                f"color:{RED};font-size:11px;padding:4px 8px;"
                f"background:{SURF2};border-radius:{R_SMALL}px;")
            return

        self._last_report_path = report_path
        ext    = "PDF" if report_path.endswith(".pdf") else "TXT"
        suffix = " + AI findings" if ai_findings else ""
        note   = ""
        ai_err = getattr(self, "_last_ai_error", None)
        if not ai_findings and ai_err and ai_err != "no_api_key":
            note = f"  ⚠️ AI findings skipped: {ai_err}"
        self.report_status.setText(
            f"✅  Report ({ext}{suffix}) generated → {os.path.basename(report_path)}. "
            f"Click 'Save Report As...' to keep a copy.{note}")
        self.report_status.setStyleSheet(
            f"color:{AMBER if note else GREEN};font-size:11px;padding:4px 8px;"
            f"background:{SURF2};border-radius:{R_SMALL}px;")
        self.save_report_btn.setEnabled(True)
        self._log(f"✅  Patient report ({ext}{suffix}) → {report_path}")
        DB.log_session("patient", "report_generated",
            f"{ext} report generated in Patient Workspace{suffix}")

    def _save_report_copy(self):
        if not self._last_report_path or not os.path.exists(self._last_report_path):
            QMessageBox.information(self, "No Report",
                "Generate a report first.")
            return
        default_name = os.path.basename(self._last_report_path)
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Report Copy", default_name,
            "PDF files (*.pdf)" if default_name.endswith(".pdf") else "Text files (*.txt)")
        if not save_path:
            return
        try:
            with open(self._last_report_path, "rb") as src, open(save_path, "wb") as dst:
                dst.write(src.read())
            self.report_status.setText(f"✅  Saved copy → {save_path}")
            self.report_status.setStyleSheet(
                f"color:{GREEN};font-size:11px;padding:4px 8px;"
                f"background:{SURF2};border-radius:{R_SMALL}px;")
            self._log(f"💾  Report copy saved → {save_path}")
            DB.log_session("patient", "report_saved", os.path.basename(save_path))
        except Exception as e:
            self.report_status.setText(f"❌  {e}")
            self.report_status.setStyleSheet(
                f"color:{RED};font-size:11px;padding:4px 8px;"
                f"background:{SURF2};border-radius:{R_SMALL}px;")

    def _log(self, msg): self.log.append(msg)