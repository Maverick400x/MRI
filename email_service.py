import os, json, time, secrets, hashlib, io
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from email.mime.image     import MIMEImage
import smtplib
from pathlib import Path

import numpy as np
from PIL import Image

from config import (
    SHARED_FOLDER, PIXEL_SPACING, OTP_TTL_SEC, LOGIN_OTP_TTL_SEC, PBKDF2_ITERS,
    GMAIL, DB, Session, DEVICE_INFO, LOGO_SVG,
)

# ── Email sender ──────────────────────────────────────────────────────────────
def _attach_logo(msg: MIMEMultipart) -> None:
    """
    Embeds the app's actual logo (icons/logo.png) as an inline image with
    Content-ID 'logo' — reference it in HTML via <img src="cid:logo">.
    Silently skipped if the logo file is missing, so email sending never
    breaks because of it.
    """
    try:
        if LOGO_SVG.exists():
            with open(LOGO_SVG, "rb") as f:
                img = MIMEImage(f.read())
            img.add_header("Content-ID", "<logo>")
            img.add_header("Content-Disposition", "inline", filename="logo.png")
            msg.attach(img)
    except Exception:
        pass


def _logo_img_tag(size: int = 30) -> str:
    """<img> tag referencing the inline logo, with an emoji fallback alt
    text for clients that block remote/embedded images by default."""
    return (f'<img src="cid:logo" width="{size}" height="{size}" alt="🏥" '
            f'style="vertical-align:middle;border-radius:7px;margin-right:9px;'
            f'display:inline-block;">')


def _build_email(subject: str, html: str,
                  from_addr: str, to_addr: str) -> MIMEMultipart:
    """Helper — assemble a MIMEMultipart email with the inline logo attached."""
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"]    = f"MRI Secure Transfer <{from_addr}>"
    msg["To"]      = to_addr
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html, "html"))
    msg.attach(alt)
    _attach_logo(msg)
    return msg


def _device_info_html() -> str:
    """
    Small "this is the system that's currently online / sent this OTP"
    block — inserted into every OTP-bearing email so the recipient can
    verify the request came from a device/location they recognize.
    """
    d = DEVICE_INFO
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""
    <div style="background:#0a0e1a;border:1px solid #2a3550;border-radius:8px;
                padding:12px 14px;margin-top:14px;">
      <div style="color:#64748b;font-size:10px;letter-spacing:1px;
                  text-transform:uppercase;font-weight:700;margin-bottom:6px;">
        🖥 System Currently Online
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:11px;color:#94a3b8;">
        <tr>
          <td style="padding:2px 0;width:90px;color:#64748b;">Device</td>
          <td style="padding:2px 0;">{d['hostname']}  ({d['os']})</td>
        </tr>
        <tr>
          <td style="padding:2px 0;color:#64748b;">Local IP</td>
          <td style="padding:2px 0;">{d['local_ip']}</td>
        </tr>
        <tr>
          <td style="padding:2px 0;color:#64748b;">Public IP</td>
          <td style="padding:2px 0;">{d['public_ip']}</td>
        </tr>
        <tr>
          <td style="padding:2px 0;color:#64748b;">Location</td>
          <td style="padding:2px 0;">📍 {d['location']}</td>
        </tr>
        <tr>
          <td style="padding:2px 0;color:#64748b;">OS User</td>
          <td style="padding:2px 0;">{d['os_user']}</td>
        </tr>
        <tr>
          <td style="padding:2px 0;color:#64748b;">Time</td>
          <td style="padding:2px 0;">{now_str}</td>
        </tr>
      </table>
      <div style="color:#f59e0b;font-size:10px;margin-top:8px;">
        ⚠️ Don't recognize this device or location? Don't share this code — contact your administrator.
      </div>
    </div>
    """


def send_dual_otp_emails(
    doctor_email:  str,
    patient_email: str,
    otp:           str,
    patient_id:    str,
    doctor_id:     str,
    areas:         dict,
    patient_name:  str = "",
    doctor_name:   str = "",
) -> tuple:
    """
    Send TWO emails in one SMTP session:

    1. → Doctor's inbox
         Subject: "🔑 MRI OTP Verification — please confirm before encrypting"
         Body:    OTP to re-enter in the app to unlock encryption.

    2. → Patient's inbox
         Subject: "🏥 Your MRI Scan is Ready — login credentials inside"
         Body:    Their Patient ID + the same OTP to decrypt the scan
                  + tumour area summary.

    Returns (ok: bool, message: str)
    """
    if not GMAIL.sender_email or not GMAIL.app_password:
        return False, "Gmail not configured. Open ⚙️ Settings first."

    exp_str  = datetime.fromtimestamp(
        time.time() + OTP_TTL_SEC, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Email 1: Doctor verification OTP ─────────────────────────────────────
    doc_html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#0a0e1a;
                       color:#e2e8f0;padding:30px;">
      <div style="max-width:460px;margin:auto;background:#111827;
                  border-radius:16px;border:1px solid #2a3550;overflow:hidden;">
        <div style="background:linear-gradient(135deg,#1e3a5f,#0f2040);
                    padding:24px 28px 16px;">
          <div style="font-size:20px;font-weight:700;color:#3b82f6;">
            {_logo_img_tag()}MRI Secure Transfer
          </div>
          <div style="font-size:12px;color:#64748b;margin-top:3px;">
            Doctor Verification Required
          </div>
        </div>
        <div style="padding:24px 28px;">
          <p style="color:#94a3b8;font-size:13px;margin:0 0 14px;">
            Hello <strong style="color:#3b82f6;">Dr. {doctor_id}</strong>,<br><br>
            You requested to encrypt and send an MRI scan for patient
            <strong style="color:#e2e8f0;">{patient_id}</strong>.<br>
            Re-enter the OTP below in the app to confirm and unlock encryption.
          </p>
          <div style="background:#0a0e1a;border:2px solid #3b82f6;border-radius:12px;
                      padding:20px;text-align:center;margin:14px 0;">
            <div style="color:#64748b;font-size:11px;letter-spacing:2px;
                        text-transform:uppercase;margin-bottom:8px;">
              Doctor Verification OTP
            </div>
            <div style="font-size:36px;font-weight:900;letter-spacing:10px;
                        color:#06b6d4;font-family:'Courier New',monospace;">
              {otp}
            </div>
            <div style="color:#f59e0b;font-size:11px;margin-top:10px;">
              ⏱ Expires: {exp_str}
            </div>
          </div>
          <table style="width:100%;border-collapse:collapse;margin:14px 0;">
            <tr><td style="color:#64748b;font-size:11px;padding:5px 0;">For Patient</td>
                <td style="color:#e2e8f0;font-size:11px;text-align:right;
                    font-family:monospace;">{patient_id}</td></tr>
            <tr><td style="color:#64748b;font-size:11px;padding:5px 0;">Patient Email</td>
                <td style="color:#e2e8f0;font-size:11px;text-align:right;">{patient_email}</td></tr>
            <tr><td style="color:#64748b;font-size:11px;padding:5px 0;">Issued</td>
                <td style="color:#e2e8f0;font-size:11px;text-align:right;">{now_str}</td></tr>
          </table>
          {_device_info_html()}
          <div style="background:#1c2537;border-radius:8px;padding:12px;
                      border-left:3px solid #ef4444;">
            <div style="color:#ef4444;font-size:10px;font-weight:700;
                        text-transform:uppercase;letter-spacing:1px;">Action Required</div>
            <div style="color:#94a3b8;font-size:11px;margin-top:5px;line-height:1.5;">
              Enter this OTP in the "Doctor OTP Verification" field in the app,
              then click Encrypt &amp; Send. The same OTP has been forwarded to
              the patient for decryption.
            </div>
          </div>
        </div>
        <div style="background:#0a0e1a;padding:12px 28px;text-align:center;
                    border-top:1px solid #2a3550;">
          <span style="color:#2a3550;font-size:10px;">
            MRI Secure Transfer · AES-256-GCM · PBKDF2
          </span>
        </div>
      </div>
    </body></html>"""

    # ── Email 2: Patient credentials + OTP ───────────────────────────────────
    area_rows = "".join(
        f'<tr><td style="color:#64748b;font-size:11px;padding:4px 0;">{n}</td>'
        f'<td style="color:#e2e8f0;font-size:11px;text-align:right;'
        f'font-weight:700;">{v:.2f} mm²</td></tr>'
        for n, v in areas.items()
    )
    total_area = sum(areas.values())

    pat_html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#0a0e1a;
                       color:#e2e8f0;padding:30px;">
      <div style="max-width:480px;margin:auto;background:#111827;
                  border-radius:16px;border:1px solid #2a3550;overflow:hidden;">
        <div style="background:linear-gradient(135deg,#0f2a1a,#0a1a0f);
                    padding:24px 28px 16px;">
          <div style="font-size:20px;font-weight:700;color:#22c55e;">
            {_logo_img_tag()}MRI Secure Transfer
          </div>
          <div style="font-size:12px;color:#64748b;margin-top:3px;">
            Your MRI Scan Results Are Ready
          </div>
        </div>
        <div style="padding:24px 28px;">
          <p style="color:#94a3b8;font-size:13px;margin:0 0 14px;">
            Hello,<br><br>
            Your doctor <strong style="color:#3b82f6;">Dr. {doctor_id}</strong>
            has securely sent your MRI scan results.<br>
            Use the credentials below to log in and decrypt your scan.
          </p>

          <!-- Login credentials box -->
          <div style="background:#0a1a0f;border:2px solid #22c55e;
                      border-radius:12px;padding:18px;margin:14px 0;">
            <div style="color:#64748b;font-size:11px;letter-spacing:2px;
                        text-transform:uppercase;margin-bottom:10px;">
              Your Login Credentials
            </div>
            <table style="width:100%;border-collapse:collapse;">
              <tr>
                <td style="color:#64748b;font-size:12px;padding:6px 0;width:40%;">
                  Patient ID
                </td>
                <td style="color:#22c55e;font-size:18px;font-weight:900;
                    text-align:right;font-family:'Courier New',monospace;
                    letter-spacing:3px;">{patient_id}</td>
              </tr>
              <tr>
                <td style="color:#64748b;font-size:12px;padding:6px 0;">
                  Email (login)
                </td>
                <td style="color:#e2e8f0;font-size:12px;text-align:right;">
                  {patient_email}
                </td>
              </tr>
            </table>
          </div>

          <!-- OTP box -->
          <div style="background:#0a0e1a;border:2px solid #06b6d4;
                      border-radius:12px;padding:18px;text-align:center;margin:14px 0;">
            <div style="color:#64748b;font-size:11px;letter-spacing:2px;
                        text-transform:uppercase;margin-bottom:8px;">
              Decryption OTP
            </div>
            <div style="font-size:34px;font-weight:900;letter-spacing:10px;
                        color:#06b6d4;font-family:'Courier New',monospace;">
              {otp}
            </div>
            <div style="color:#f59e0b;font-size:11px;margin-top:8px;">
              ⏱ Expires: {exp_str}
            </div>
          </div>
          {_device_info_html()}

          <!-- Tumour area summary -->
          <div style="background:#1c2537;border-radius:10px;padding:16px;margin:14px 0;">
            <div style="color:#a78bfa;font-size:11px;font-weight:700;
                        text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">
              Preliminary Tumour Area Summary
            </div>
            <table style="width:100%;border-collapse:collapse;">
              {area_rows}
              <tr style="border-top:1px solid #2a3550;">
                <td style="color:#e2e8f0;font-size:12px;padding:6px 0;
                    font-weight:700;">Total Area</td>
                <td style="color:#a78bfa;font-size:14px;text-align:right;
                    font-weight:900;">{total_area:.2f} mm²</td>
              </tr>
            </table>
          </div>

          <!-- Steps -->
          <div style="background:#0f1729;border-radius:8px;padding:14px;
                      border-left:3px solid #3b82f6;">
            <div style="color:#3b82f6;font-size:10px;font-weight:700;
                        text-transform:uppercase;letter-spacing:1px;">
              How to Access Your Results
            </div>
            <ol style="color:#94a3b8;font-size:11px;margin:8px 0 0;
                       padding-left:18px;line-height:1.8;">
              <li>Open the MRI Secure Transfer app</li>
              <li>Click the <strong>Patient</strong> tab on the login screen</li>
              <li>Enter your Patient ID: <code
                  style="color:#22c55e;">{patient_id}</code>
                  and your email</li>
              <li>Check your email for the login OTP and enter it</li>
              <li>Select your encrypted scan file and enter the Decryption OTP above</li>
            </ol>
          </div>
        </div>
        <div style="background:#0a0e1a;padding:12px 28px;text-align:center;
                    border-top:1px solid #2a3550;">
          <span style="color:#2a3550;font-size:10px;">
            MRI Secure Transfer · AES-256-GCM · PBKDF2 · End-to-End Encrypted
          </span>
        </div>
      </div>
    </body></html>"""

    try:
        doc_msg = _build_email(
            f"🔑 MRI OTP Verification — confirm before encrypting ({patient_id})",
            doc_html, GMAIL.sender_email, doctor_email)
        pat_msg = _build_email(
            f"🏥 Your MRI Scan Is Ready — Patient ID & OTP inside",
            pat_html, GMAIL.sender_email, patient_email)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL.sender_email, GMAIL.app_password)
            s.sendmail(GMAIL.sender_email, doctor_email,  doc_msg.as_string())
            s.sendmail(GMAIL.sender_email, patient_email, pat_msg.as_string())

        return True, (f"✉️  Doctor OTP → {doctor_email}  |  "
                      f"Patient credentials → {patient_email}")
    except smtplib.SMTPAuthenticationError:
        return False, "Gmail auth failed. Check App Password in ⚙️ Settings."
    except Exception as e:
        return False, str(e)


# kept for backwards compatibility (login OTP uses this)
def send_otp_email(to_email, otp, patient_id):
    """Send scan-transfer OTP to patient only (legacy wrapper)."""
    return send_dual_otp_emails(
        GMAIL.sender_email, to_email, otp, patient_id, "Doctor", {})


# ── Patient Report PDF ────────────────────────────────────────────────────────
def generate_patient_report_pdf(
    patient_id:  str,
    anon_id:     str,
    doctor_id:   str,
    patient_email: str,
    areas:       dict,
    enc_filename: str,
    img_array:      "np.ndarray | None" = None,
    overlay_array:  "np.ndarray | None" = None,
    ai_findings:    "dict | None" = None,
    previous_areas:     "dict | None" = None,
    previous_timestamp: "str | None" = None,
) -> str:
    """
    Generate a professional PDF medical report for the patient.
    Saved to SHARED_FOLDER/reports/<patient_id>_report.pdf
    Returns the output path, or "" on failure.

    overlay_array : optional (H,W,3) uint8 array from imaging.overlay_array() —
                    the MRI slice with tumor sub-region masks painted on top.
                    Shown alongside the plain thumbnail so the report visually
                    shows WHERE the tumor is, not just the raw scan.
    previous_areas / previous_timestamp : optional — the single most recent
                    PRIOR scan's area dict + timestamp for this Patient ID
                    (from DB.get_scans_by_patient). When present, a
                    Previous-vs-Current comparison table is rendered. Only
                    ever compares two consecutive phases, never a full history.
    ai_findings   : optional dict {"findings","impression","flags_for_review"}
                    from ai_report.AIFindingsWorker. Always rendered with a
                    clear DRAFT / requires-review label. If None, this section
                    is simply omitted — nothing else about the report changes.

    Uses only the stdlib + optional reportlab.
    Falls back to a plain-text .txt report if reportlab is not installed.
    """
    import os
    reports_dir = os.path.join(SHARED_FOLDER, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total   = sum(areas.values())

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles    import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units     import mm
        from reportlab.lib           import colors
        from reportlab.platypus      import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, Image as RLImage,
        )
        import io, tempfile

        out_path = os.path.join(reports_dir, f"{patient_id}_report.pdf")
        doc      = SimpleDocTemplate(out_path, pagesize=A4,
                                     leftMargin=20*mm, rightMargin=20*mm,
                                     topMargin=20*mm, bottomMargin=20*mm)

        styles  = getSampleStyleSheet()
        C_DARK  = colors.HexColor("#0a0e1a")
        C_BLUE  = colors.HexColor("#3b82f6")
        C_CYAN  = colors.HexColor("#06b6d4")
        C_GREEN = colors.HexColor("#22c55e")
        C_AMBER = colors.HexColor("#f59e0b")
        C_RED   = colors.HexColor("#ef4444")
        C_TEXT  = colors.HexColor("#1e293b")
        C_DIM   = colors.HexColor("#64748b")
        C_SURF  = colors.HexColor("#f1f5f9")

        h1 = ParagraphStyle("h1", parent=styles["Heading1"],
                             fontSize=20, textColor=C_BLUE,
                             spaceAfter=4, leading=24)
        h2 = ParagraphStyle("h2", parent=styles["Heading2"],
                             fontSize=13, textColor=C_TEXT,
                             spaceAfter=3, leading=16)
        body = ParagraphStyle("body", parent=styles["Normal"],
                               fontSize=10, textColor=C_TEXT,
                               leading=14, spaceAfter=4)
        dim  = ParagraphStyle("dim",  parent=styles["Normal"],
                               fontSize=9, textColor=C_DIM, leading=12)
        bold_blue = ParagraphStyle("bb", parent=styles["Normal"],
                                   fontSize=11, textColor=C_BLUE,
                                   fontName="Helvetica-Bold")

        story = []

        # ── Header ────────────────────────────────────────────────────────
        story.append(Paragraph("🏥  MRI Secure Transfer", h1))
        story.append(Paragraph("Brain Tumour Segmentation Report", h2))
        story.append(HRFlowable(width="100%", thickness=1,
                                color=C_BLUE, spaceAfter=8))

        # ── Patient info table ────────────────────────────────────────────
        info_data = [
            ["Field", "Value"],
            ["Patient ID",       patient_id],
            ["Anonymised ID",    anon_id],
            ["Patient Email",    patient_email],
            ["Referring Doctor", doctor_id],
            ["Report Date",      now_str],
            ["Encrypted File",   enc_filename],
            ["Encryption",       "AES-256-GCM  ·  PBKDF2-HMAC-SHA256"],
        ]
        info_table = Table(info_data, colWidths=[55*mm, 115*mm])
        info_table.setStyle(TableStyle([
            ("BACKGROUND",   (0,0), (-1,0),  C_BLUE),
            ("TEXTCOLOR",    (0,0), (-1,0),  colors.white),
            ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",     (0,0), (-1,0),  10),
            ("BACKGROUND",   (0,1), (-1,-1), C_SURF),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.white, C_SURF]),
            ("FONTNAME",     (0,1), (0,-1),  "Helvetica-Bold"),
            ("FONTSIZE",     (0,1), (-1,-1), 9),
            ("TEXTCOLOR",    (0,1), (-1,-1), C_TEXT),
            ("GRID",         (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING",   (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",(0,0), (-1,-1), 5),
            ("LEFTPADDING",  (0,0), (-1,-1), 8),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 10*mm))

        # ── Tumour area results ───────────────────────────────────────────
        story.append(Paragraph("Tumour Segmentation Results", h2))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=C_DIM, spaceAfter=6))

        area_colors = {"Necrotic": C_RED, "Edema": C_GREEN, "Enhancing": C_BLUE}
        area_data   = [["Region", "Area (mm²)", "% of Total", "Clinical Note"]]
        notes       = {
            "Necrotic":  "Dead tumour core — reduced perfusion",
            "Edema":     "Surrounding oedema — cerebral swelling",
            "Enhancing": "Active tumour — blood-brain barrier breakdown",
        }
        for name, val in areas.items():
            pct = (val / total * 100) if total > 0 else 0
            area_data.append([
                name,
                f"{val:.2f}",
                f"{pct:.1f}%",
                notes.get(name, ""),
            ])
        area_data.append(["TOTAL", f"{total:.2f}", "100.0%", ""])

        area_table = Table(area_data, colWidths=[35*mm, 30*mm, 25*mm, 80*mm])
        ts = TableStyle([
            ("BACKGROUND",   (0,0), (-1,0),  colors.HexColor("#1e293b")),
            ("TEXTCOLOR",    (0,0), (-1,0),  colors.white),
            ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",     (0,0), (-1,-1), 9),
            ("ROWBACKGROUNDS",(0,1),(-1,-2), [colors.white, C_SURF]),
            ("BACKGROUND",   (0,-1),(-1,-1), colors.HexColor("#f8fafc")),
            ("FONTNAME",     (0,-1),(-1,-1), "Helvetica-Bold"),
            ("TEXTCOLOR",    (0,1), (-1,-1), C_TEXT),
            ("GRID",         (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING",   (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",(0,0), (-1,-1), 5),
            ("LEFTPADDING",  (0,0), (-1,-1), 8),
            ("ALIGN",        (1,0), (2,-1),  "CENTER"),
        ])
        for i, name in enumerate(areas.keys(), start=1):
            c = area_colors.get(name, C_TEXT)
            ts.add("TEXTCOLOR", (0,i), (0,i), c)
            ts.add("FONTNAME",  (0,i), (0,i), "Helvetica-Bold")
        area_table.setStyle(ts)
        story.append(area_table)
        story.append(Spacer(1, 8*mm))

        # ── Previous vs Current phase comparison (optional) ────────────────
        if previous_areas:
            story.append(Paragraph("Phase Comparison — Previous vs Current", h2))
            story.append(HRFlowable(width="100%", thickness=0.5,
                                    color=C_DIM, spaceAfter=6))
            if previous_timestamp:
                story.append(Paragraph(
                    f"Previous phase recorded: {previous_timestamp} UTC  ·  "
                    f"comparing that single prior phase against the current one only.",
                    dim))
                story.append(Spacer(1, 3*mm))

            cmp_data = [["Region", "Previous (mm²)", "Current (mm²)", "Change"]]
            all_regions = list(dict.fromkeys(list(previous_areas.keys()) + list(areas.keys())))
            for name in all_regions:
                prev_v = previous_areas.get(name, 0.0)
                cur_v  = areas.get(name, 0.0)
                if prev_v > 0:
                    delta_pct = (cur_v - prev_v) / prev_v * 100
                    arrow = "▲" if delta_pct > 0.5 else ("▼" if delta_pct < -0.5 else "≈")
                    change_str = f"{arrow} {delta_pct:+.1f}%"
                else:
                    change_str = "new" if cur_v > 0 else "—"
                cmp_data.append([name, f"{prev_v:.2f}", f"{cur_v:.2f}", change_str])
            prev_total = sum(previous_areas.values())
            if prev_total > 0:
                delta_pct = (total - prev_total) / prev_total * 100
                arrow = "▲" if delta_pct > 0.5 else ("▼" if delta_pct < -0.5 else "≈")
                total_change = f"{arrow} {delta_pct:+.1f}%"
            else:
                total_change = "—"
            cmp_data.append(["TOTAL", f"{prev_total:.2f}", f"{total:.2f}", total_change])

            cmp_table = Table(cmp_data, colWidths=[35*mm, 35*mm, 35*mm, 35*mm])
            cmp_ts = TableStyle([
                ("BACKGROUND",   (0,0), (-1,0),  colors.HexColor("#1e293b")),
                ("TEXTCOLOR",    (0,0), (-1,0),  colors.white),
                ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
                ("FONTSIZE",     (0,0), (-1,-1), 9),
                ("ROWBACKGROUNDS",(0,1),(-1,-2), [colors.white, C_SURF]),
                ("BACKGROUND",   (0,-1),(-1,-1), colors.HexColor("#f8fafc")),
                ("FONTNAME",     (0,-1),(-1,-1), "Helvetica-Bold"),
                ("TEXTCOLOR",    (0,1), (-1,-1), C_TEXT),
                ("GRID",         (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING",   (0,0), (-1,-1), 5),
                ("BOTTOMPADDING",(0,0), (-1,-1), 5),
                ("LEFTPADDING",  (0,0), (-1,-1), 8),
                ("ALIGN",        (1,0), (3,-1),  "CENTER"),
            ])
            for i, row in enumerate(cmp_data[1:-1], start=1):
                change_txt = row[3]
                if change_txt.startswith("▲"):
                    cmp_ts.add("TEXTCOLOR", (3,i), (3,i), C_RED)
                elif change_txt.startswith("▼"):
                    cmp_ts.add("TEXTCOLOR", (3,i), (3,i), C_GREEN)
            cmp_table.setStyle(cmp_ts)
            story.append(cmp_table)
            story.append(Spacer(1, 8*mm))

        # ── MRI thumbnail + tumor localization overlay ────────────────────
        if img_array is not None:
            try:
                from PIL import Image as PILImage

                def _rl_image(arr, w_mm=55):
                    pil = PILImage.fromarray(arr)
                    buf = io.BytesIO()
                    pil.save(buf, format="PNG")
                    buf.seek(0)
                    return RLImage(buf, width=w_mm*mm, height=w_mm*mm)

                story.append(Paragraph("MRI Scan & Tumor Localization", h2))
                story.append(HRFlowable(width="100%", thickness=0.5,
                                        color=C_DIM, spaceAfter=6))

                if overlay_array is not None:
                    img_row = Table(
                        [[_rl_image(img_array), _rl_image(overlay_array)],
                         [Paragraph("Original scan", dim),
                          Paragraph("Segmentation overlay — colored regions show "
                                    "tumor sub-area locations", dim)]],
                        colWidths=[60*mm, 60*mm],
                    )
                    img_row.setStyle(TableStyle([
                        ("ALIGN", (0,0), (-1,-1), "CENTER"),
                        ("TOPPADDING", (0,0), (-1,-1), 4),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                    ]))
                    story.append(img_row)
                else:
                    story.append(_rl_image(img_array, w_mm=60))
                story.append(Spacer(1, 6*mm))
            except Exception:
                pass

        # ── AI-assisted preliminary findings (optional, clearly labeled) ───
        if ai_findings and ai_findings.get("findings"):
            story.append(Paragraph("AI-Assisted Preliminary Findings", h2))
            story.append(HRFlowable(width="100%", thickness=0.5,
                                    color=C_AMBER, spaceAfter=6))
            story.append(Paragraph(
                "<b>⚠ DRAFT — Generated from the measurements above. "
                "Not a diagnosis. Requires radiologist confirmation before "
                "clinical use.</b>",
                ParagraphStyle("aiwarn", parent=styles["Normal"],
                               fontSize=9, textColor=C_AMBER, leading=13,
                               spaceAfter=6)))
            story.append(Paragraph(f"<b>Findings:</b> {ai_findings['findings']}", body))
            if ai_findings.get("impression"):
                story.append(Paragraph(f"<b>Impression:</b> {ai_findings['impression']}", body))
            flags = ai_findings.get("flags_for_review") or []
            if flags:
                story.append(Paragraph(
                    "<b>Flagged for radiologist review:</b> " + "; ".join(flags),
                    dim))
            story.append(Spacer(1, 8*mm))

        # ── Security attestation ──────────────────────────────────────────
        story.append(Paragraph("Security & Privacy Attestation", h2))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=C_DIM, spaceAfter=6))
        attest_data = [
            ["Check",              "Status",    "Details"],
            ["AES-256-GCM",        "✅ Applied", "Authenticated encryption — integrity guaranteed"],
            ["PBKDF2 Key Deriv.",  "✅ Applied", "310,000 iterations — brute-force resistant"],
            ["OTP Authentication", "✅ Passed",  "Single-use, 5-min expiry, email-delivered"],
            ["Doctor Verification","✅ Passed",  "Doctor re-entered OTP before encryption"],
            ["Patient ID",         "✅ Anon",    f"Pseudonymised → {anon_id}"],
            ["Email Hash",         "✅ Stored",  "SHA-256 — never stored in plaintext"],
        ]
        sec_table = Table(attest_data, colWidths=[45*mm, 25*mm, 100*mm])
        sec_table.setStyle(TableStyle([
            ("BACKGROUND",   (0,0), (-1,0),  colors.HexColor("#1e293b")),
            ("TEXTCOLOR",    (0,0), (-1,0),  colors.white),
            ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",     (0,0), (-1,-1), 9),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.white, C_SURF]),
            ("TEXTCOLOR",    (0,1), (-1,-1), C_TEXT),
            ("TEXTCOLOR",    (1,1), (1,-1),  C_GREEN),
            ("FONTNAME",     (1,1), (1,-1),  "Helvetica-Bold"),
            ("GRID",         (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING",   (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",(0,0), (-1,-1), 5),
            ("LEFTPADDING",  (0,0), (-1,-1), 8),
        ]))
        story.append(sec_table)
        story.append(Spacer(1, 8*mm))

        # ── Disclaimer ────────────────────────────────────────────────────
        story.append(HRFlowable(width="100%", thickness=1,
                                color=C_BLUE, spaceBefore=4, spaceAfter=6))
        story.append(Paragraph(
            "<b>Disclaimer:</b> This report is generated automatically by the "
            "MRI Secure Transfer system. Segmentation results are preliminary "
            "and for reference only. Final clinical decisions must be made by "
            "a qualified radiologist or physician.", dim))
        story.append(Paragraph(
            f"Report generated: {now_str}  ·  "
            f"System: MRI Secure Transfer v2.0  ·  "
            f"Algorithm: U-Net + CBAM  ·  Pixel spacing: 1.0 mm × 1.0 mm", dim))

        doc.build(story)
        return out_path

    except ImportError:
        # Fallback: plain text report
        out_path = os.path.join(reports_dir, f"{patient_id}_report.txt")
        lines = [
            "=" * 60,
            "  MRI SECURE TRANSFER — PATIENT REPORT",
            "=" * 60,
            f"  Patient ID      : {patient_id}",
            f"  Anonymised ID   : {anon_id}",
            f"  Patient Email   : {patient_email}",
            f"  Referring Doctor: {doctor_id}",
            f"  Report Date     : {now_str}",
            f"  Encrypted File  : {enc_filename}",
            "",
            "  TUMOUR AREAS",
            "-" * 60,
        ]
        for name, val in areas.items():
            pct = (val / total * 100) if total > 0 else 0
            lines.append(f"  {name:<14}: {val:>10.2f} mm²  ({pct:.1f}%)")
        lines += [f"  {'TOTAL':<14}: {total:>10.2f} mm²", ""]
        if previous_areas:
            lines += [
                "  PHASE COMPARISON — PREVIOUS vs CURRENT",
                "-" * 60,
            ]
            if previous_timestamp:
                lines.append(f"  Previous phase: {previous_timestamp} UTC (single prior phase only)")
            all_regions = list(dict.fromkeys(list(previous_areas.keys()) + list(areas.keys())))
            for name in all_regions:
                prev_v = previous_areas.get(name, 0.0)
                cur_v  = areas.get(name, 0.0)
                if prev_v > 0:
                    delta_pct = (cur_v - prev_v) / prev_v * 100
                    change_str = f"{delta_pct:+.1f}%"
                else:
                    change_str = "new" if cur_v > 0 else "—"
                lines.append(f"  {name:<14}: {prev_v:>8.2f} -> {cur_v:>8.2f} mm²  ({change_str})")
            prev_total = sum(previous_areas.values())
            if prev_total > 0:
                total_change = f"{(total - prev_total) / prev_total * 100:+.1f}%"
            else:
                total_change = "—"
            lines.append(f"  {'TOTAL':<14}: {prev_total:>8.2f} -> {total:>8.2f} mm²  ({total_change})")
            lines.append("")
        if ai_findings and ai_findings.get("findings"):
            lines += [
                "  AI-ASSISTED PRELIMINARY FINDINGS (DRAFT — NOT A DIAGNOSIS)",
                "-" * 60,
                f"  Findings: {ai_findings['findings']}",
            ]
            if ai_findings.get("impression"):
                lines.append(f"  Impression: {ai_findings['impression']}")
            flags = ai_findings.get("flags_for_review") or []
            if flags:
                lines.append(f"  Flagged for review: {'; '.join(flags)}")
            lines.append("")
        lines += [
            "  SECURITY",
            "-" * 60,
            "  Encryption    : AES-256-GCM",
            "  Key derivation: PBKDF2-HMAC-SHA256 (310k iter)",
            "  OTP auth      : Verified",
            "  Identity      : Anonymised (HMAC-SHA256)",
            "=" * 60,
            "  Install reportlab for PDF:  pip install reportlab",
            "=" * 60,
        ]
        with open(out_path, "w") as f:
            f.write("\n".join(lines))
        return out_path
    except Exception:
        return ""


# ── Login OTP email ──────────────────────────────────────────────────────────
def send_login_otp_email(to_email: str, otp: str,
                          role: str, user_id: str) -> tuple:
    """Send a login OTP email. Returns (ok, message)."""
    if not GMAIL.sender_email or not GMAIL.app_password:
        return False, "Gmail not configured. Open ⚙️ Settings first."

    role_label  = "Doctor" if role == "doctor" else "Patient"
    role_color  = "#3b82f6" if role == "doctor" else "#22c55e"
    exp_str     = datetime.fromtimestamp(
        time.time() + LOGIN_OTP_TTL_SEC, tz=timezone.utc).strftime("%H:%M UTC")
    ttl_label   = (f"{LOGIN_OTP_TTL_SEC} seconds" if LOGIN_OTP_TTL_SEC < 60
                   else f"{LOGIN_OTP_TTL_SEC // 60} minute"
                        f"{'s' if LOGIN_OTP_TTL_SEC // 60 != 1 else ''}")

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#0a0e1a;
                       color:#e2e8f0;padding:30px;">
      <div style="max-width:460px;margin:auto;background:#111827;
                  border-radius:16px;border:1px solid #2a3550;overflow:hidden;">
        <div style="background:linear-gradient(135deg,#0f2040,#1a1a2e);
                    padding:26px 30px 18px;">
          <div style="font-size:20px;font-weight:700;color:{role_color};">
            {_logo_img_tag()}MRI Secure Transfer
          </div>
          <div style="font-size:12px;color:#64748b;margin-top:3px;">
            {role_label} Login Verification
          </div>
        </div>
        <div style="padding:26px 30px;">
          <p style="color:#94a3b8;font-size:13px;margin:0 0 16px;">
            Login requested for <strong style="color:{role_color};">
            {role_label} ID: {user_id}</strong><br>
            Enter this OTP to complete your login.
          </p>
          <div style="background:#0a0e1a;border:2px solid {role_color};
                      border-radius:12px;padding:22px;text-align:center;margin:16px 0;">
            <div style="color:#64748b;font-size:11px;letter-spacing:2px;
                        text-transform:uppercase;margin-bottom:8px;">
              Login OTP
            </div>
            <div style="font-size:36px;font-weight:900;letter-spacing:10px;
                        color:#06b6d4;font-family:'Courier New',monospace;">
              {otp}
            </div>
            <div style="color:#f59e0b;font-size:11px;margin-top:10px;">
              ⏱ Expires at {exp_str} — valid {ttl_label}
            </div>
          </div>
          {_device_info_html()}
          <div style="background:#1c2537;border-radius:8px;padding:12px;
                      border-left:3px solid #ef4444;margin-top:14px;">
            <div style="color:#ef4444;font-size:10px;font-weight:700;
                        text-transform:uppercase;letter-spacing:1px;">
              Security Notice
            </div>
            <div style="color:#94a3b8;font-size:11px;margin-top:5px;line-height:1.5;">
              If you did not request this login, ignore this email.
              Never share this OTP with anyone.
            </div>
          </div>
        </div>
        <div style="background:#0a0e1a;padding:12px 30px;text-align:center;
                    border-top:1px solid #2a3550;">
          <span style="color:#2a3550;font-size:10px;">
            MRI Secure Transfer · AES-256-GCM · End-to-End Encrypted
          </span>
        </div>
      </div>
    </body></html>"""

    try:
        msg = _build_email(
            f"🔐 MRI Secure — {role_label} Login OTP",
            html, GMAIL.sender_email, to_email)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL.sender_email, GMAIL.app_password)
            s.sendmail(GMAIL.sender_email, to_email, msg.as_string())
        return True, f"Login OTP sent to {to_email}"
    except smtplib.SMTPAuthenticationError:
        return False, "Gmail auth failed. Check App Password in ⚙️ Settings."
    except Exception as e:
        return False, str(e)


# ── Doctor registration verification ─────────────────────────────────────────
def send_doctor_verification_otp(to_email: str, otp: str, user_id: str) -> tuple:
    """
    Sent when an admin adds a Doctor ID + email to the approved list, to
    confirm the address is real and reachable before it's trusted for
    future logins. Returns (ok, message).
    """
    if not GMAIL.sender_email or not GMAIL.app_password:
        return False, "Gmail not configured. Open ⚙️ Settings first."

    exp_str = datetime.fromtimestamp(
        time.time() + OTP_TTL_SEC, tz=timezone.utc).strftime("%H:%M UTC")

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#0a0e1a;
                       color:#e2e8f0;padding:30px;">
      <div style="max-width:460px;margin:auto;background:#111827;
                  border-radius:16px;border:1px solid #2a3550;overflow:hidden;">
        <div style="background:linear-gradient(135deg,#2a1a4a,#1a1030);
                    padding:26px 30px 18px;">
          <div style="font-size:20px;font-weight:700;color:#a78bfa;">
            {_logo_img_tag()}MRI Secure Transfer
          </div>
          <div style="font-size:12px;color:#64748b;margin-top:3px;">
            Doctor Registration Verification
          </div>
        </div>
        <div style="padding:26px 30px;">
          <p style="color:#94a3b8;font-size:13px;margin:0 0 16px;">
            An administrator is adding <strong style="color:#a78bfa;">
            Doctor ID: {user_id}</strong> to the approved doctors list for
            this address.<br>
            Share this code with the administrator to confirm it's really you.
          </p>
          <div style="background:#0a0e1a;border:2px solid #a78bfa;
                      border-radius:12px;padding:22px;text-align:center;margin:16px 0;">
            <div style="color:#64748b;font-size:11px;letter-spacing:2px;
                        text-transform:uppercase;margin-bottom:8px;">
              Verification Code
            </div>
            <div style="font-size:36px;font-weight:900;letter-spacing:10px;
                        color:#06b6d4;font-family:'Courier New',monospace;">
              {otp}
            </div>
            <div style="color:#f59e0b;font-size:11px;margin-top:10px;">
              ⏱ Expires at {exp_str} — valid 5 minutes
            </div>
          </div>
          {_device_info_html()}
          <div style="background:#1c2537;border-radius:8px;padding:12px;
                      border-left:3px solid #ef4444;margin-top:14px;">
            <div style="color:#ef4444;font-size:10px;font-weight:700;
                        text-transform:uppercase;letter-spacing:1px;">
              Security Notice
            </div>
            <div style="color:#94a3b8;font-size:11px;margin-top:5px;line-height:1.5;">
              If you did not expect this, do not share this code —
              someone may be trying to register under your address.
            </div>
          </div>
        </div>
        <div style="background:#0a0e1a;padding:12px 30px;text-align:center;
                    border-top:1px solid #2a3550;">
          <span style="color:#2a3550;font-size:10px;">
            MRI Secure Transfer · AES-256-GCM · End-to-End Encrypted
          </span>
        </div>
      </div>
    </body></html>"""

    try:
        msg = _build_email(
            f"🔐 MRI Secure — Doctor Registration Verification ({user_id})",
            html, GMAIL.sender_email, to_email)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL.sender_email, GMAIL.app_password)
            s.sendmail(GMAIL.sender_email, to_email, msg.as_string())
        return True, f"Verification OTP sent to {to_email}"
    except smtplib.SMTPAuthenticationError:
        return False, "Gmail auth failed. Check App Password in ⚙️ Settings."
    except Exception as e:
        return False, str(e)

