import os, json, secrets, hashlib, hmac, zipfile
import io as _io
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal

from config import (
    SHARED_FOLDER, ENC_SUFFIX, PIXEL_SPACING, PBKDF2_ITERS,
    Session, DB,
)
from crypto        import encrypt_bytes, decrypt_bytes, pseudonymise
from email_service import (
    send_login_otp_email, send_dual_otp_emails, send_doctor_verification_otp,
)

class LoginEmailWorker(QThread):
    """Sends a login OTP email in background."""
    log  = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, to_email: str, otp: str, role: str, user_id: str):
        super().__init__()
        self.to_email = to_email
        self.otp      = otp
        self.role     = role
        self.user_id  = user_id

    def run(self):
        self.log.emit(f"📧  Sending login OTP to {self.to_email}...")
        ok, msg = send_login_otp_email(
            self.to_email, self.otp, self.role, self.user_id)
        self.done.emit(ok, msg)


class DoctorVerifyEmailWorker(QThread):
    """Sends the admin-side doctor registration verification OTP."""
    log  = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, to_email: str, otp: str, user_id: str):
        super().__init__()
        self.to_email = to_email
        self.otp      = otp
        self.user_id  = user_id

    def run(self):
        self.log.emit(f"📧  Sending verification OTP to {self.to_email}...")
        ok, msg = send_doctor_verification_otp(self.to_email, self.otp, self.user_id)
        self.done.emit(ok, msg)


class EncryptWorker(QThread):
    """
    Packs all selected files (PNGs + GIFs) into an in-memory ZIP,
    prepends a JSON metadata header, then AES-256-GCM encrypts the
    whole bundle into a single .enc file.

    Payload layout (bytes):
        [4B meta_len] [meta_len bytes JSON] [ZIP bytes]
    """
    progress = pyqtSignal(int)
    log      = pyqtSignal(str)
    done     = pyqtSignal(str, str, dict)   # out_path, anon_id, areas
    err      = pyqtSignal(str)

    def __init__(self, file_paths: list, patient_id: str, patient_name: str,
                 patient_email: str, otp: str, seg: dict, doctor_name: str = "",
                 quality: dict | None = None, risk: dict | None = None):
        super().__init__()
        # file_paths: list of absolute paths (PNGs, GIFs, etc.)
        self.file_paths    = file_paths
        self.patient_id    = patient_id
        self.patient_name  = patient_name
        self.patient_email = patient_email
        self.otp           = otp
        self.seg           = seg
        self.doctor_name   = doctor_name
        self.quality       = quality or {}
        self.risk          = risk or {}

    def run(self):
        try:
            n = len(self.file_paths)
            self.log.emit(f"📂  Packing {n} file(s) into encrypted bundle...")
            self.progress.emit(8)

            # ── Build in-memory ZIP ────────────────────────────────────────
            zip_buf = _io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, fpath in enumerate(self.file_paths):
                    arcname = os.path.basename(fpath)
                    with open(fpath, "rb") as f:
                        zf.writestr(arcname, f.read())
                    pct = 8 + int(32 * (i + 1) / n)
                    self.progress.emit(pct)
                    self.log.emit(f"    + {arcname}")
            zip_bytes = zip_buf.getvalue()
            self.log.emit(f"    ZIP size: {len(zip_bytes):,} bytes  ({n} files)")
            self.progress.emit(42)

            # ── Anonymise patient ID ───────────────────────────────────────
            self.log.emit("🔏  Anonymising patient ID (HMAC-SHA256)...")
            secret     = secrets.token_bytes(32)
            anon_id    = pseudonymise(self.patient_id, secret)
            email_hash = hashlib.sha256(
                self.patient_email.strip().lower().encode()).hexdigest()
            self.log.emit(f"    {self.patient_id}  →  {anon_id}")
            self.log.emit(f"📧  Email fingerprint: {email_hash[:16]}…")
            self.progress.emit(52)

            # ── Metadata ───────────────────────────────────────────────────
            self.log.emit("🔑  Deriving AES-256 key (PBKDF2, 310k iter)...")
            dr = Session.doctor or {}
            file_list = [os.path.basename(p) for p in self.file_paths]
            metadata = {
                "anon_id":       anon_id,
                "email_hash":    email_hash,
                "timestamp":     datetime.now(timezone.utc).isoformat(),
                "areas_mm2":     self.seg["areas"],
                "pixel_spacing": PIXEL_SPACING,
                "algorithm":     "AES-256-GCM",
                "kdf":           f"PBKDF2-HMAC-SHA256 ({PBKDF2_ITERS} iter)",
                "otp_auth":      "OTP-derived key",
                "patient_name":  self.patient_name,
                "doctor_id":     dr.get("user_id", "—"),
                "doctor_name":   self.doctor_name or dr.get("display_name", "—"),
                "file_count":    n,
                "file_list":     file_list,
                "bundle_type":   "zip",
            }
            self.progress.emit(60)

            # ── Encrypt ────────────────────────────────────────────────────
            self.log.emit("🔐  Encrypting bundle with AES-256-GCM...")
            meta_b  = json.dumps(metadata).encode()
            payload = len(meta_b).to_bytes(4, "big") + meta_b + zip_bytes
            enc     = encrypt_bytes(payload, self.otp)
            self.progress.emit(80)

            # ── Save .enc file ─────────────────────────────────────────────
            stem     = Path(self.file_paths[0]).stem if n == 1 else f"mri_bundle_{self.patient_id}"
            out_path = os.path.join(SHARED_FOLDER, f"{stem}_{anon_id}{ENC_SUFFIX}")
            with open(out_path, "wb") as f:
                f.write(enc)
            self.progress.emit(92)
            self.log.emit(f"✅  Saved: {os.path.basename(out_path)}")
            self.log.emit(f"    Size : {len(enc):,} bytes  ({n} files inside)")

            # ── Sidecar manifest (no PHI) ──────────────────────────────────
            manifest = {
                "filename":     os.path.basename(out_path),
                "patient_id":   self.patient_id,
                "patient_name": self.patient_name,
                "anon_id":      anon_id,
                "doctor_id":    metadata["doctor_id"],
                "doctor_name":  metadata["doctor_name"],
                "timestamp":    metadata["timestamp"],
                "areas_mm2":    self.seg["areas"],
                "algorithm":    "AES-256-GCM",
                "size_bytes":   len(enc),
                "file_count":   n,
                "file_list":    file_list,
            }
            manifest_path = out_path.replace(ENC_SUFFIX, ".manifest.json")
            with open(manifest_path, "w") as mf:
                json.dump(manifest, mf, indent=2)
            self.log.emit(f"    Manifest → {os.path.basename(manifest_path)}")
            self.log.emit("📤  Patient can decrypt + download the full ZIP.")

            # ── MongoDB ────────────────────────────────────────────────────
            DB.log_scan({
                "filename":    os.path.basename(out_path),
                "anon_id":     anon_id,
                "email_hash":  email_hash,
                "patient_id":  self.patient_id,
                "areas_mm2":   self.seg["areas"],
                "file_size_b": len(enc),
                "file_count":  n,
                "algorithm":   "AES-256-GCM",
                "kdf":         f"PBKDF2-HMAC-SHA256 ({PBKDF2_ITERS} iter)",
                "quality":     {
                    "density_pct": self.quality.get("density_pct"),
                    "noise_val":   self.quality.get("noise_val"),
                    "noise_label": self.quality.get("noise_label"),
                } if self.quality else None,
                "risk": {
                    "level":         self.risk.get("level"),
                    "total_area":    self.risk.get("total_area"),
                    "necrotic_pct":  self.risk.get("necrotic_pct"),
                } if self.risk else None,
            })
            DB.log_session("doctor", "encrypt_send",
                f"{n} file(s) encrypted for {anon_id} → {os.path.basename(out_path)}")
            self.progress.emit(100)
            self.done.emit(out_path, anon_id, self.seg["areas"])
        except Exception as e:
            self.err.emit(str(e))


class EmailWorker(QThread):
    log  = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, doctor_email: str, patient_email: str,
                 otp: str, patient_id: str, doctor_id: str, areas: dict,
                 patient_name: str = "", doctor_name: str = ""):
        super().__init__()
        self.doctor_email  = doctor_email
        self.patient_email = patient_email
        self.otp           = otp
        self.patient_id    = patient_id
        self.doctor_id     = doctor_id
        self.areas         = areas
        self.patient_name  = patient_name
        self.doctor_name   = doctor_name

    def run(self):
        self.log.emit("📧  Connecting to Gmail SMTP (ssl:465)...")
        self.log.emit(f"    → Doctor OTP   : {self.doctor_email}")
        self.log.emit(f"    → Patient creds: {self.patient_email}")
        DB.log_otp_event("email_sending", {
            "doctor_email": self.doctor_email,
            "patient_email": self.patient_email,
            "patient_id": self.patient_id,
        })
        ok, msg = send_dual_otp_emails(
            self.doctor_email, self.patient_email,
            self.otp, self.patient_id, self.doctor_id, self.areas,
            patient_name=self.patient_name,
            doctor_name=self.doctor_name)
        if ok:
            DB.log_otp_event("email_sent", {
                "doctor_email": self.doctor_email,
                "patient_email": self.patient_email,
            })
            DB.log_session("doctor", "dual_email_sent",
                f"Doctor OTP → {self.doctor_email}  "
                f"Patient creds → {self.patient_email}")
        else:
            DB.log_otp_event("email_failed", {"error": msg})
        self.done.emit(ok, msg)


class DecryptWorker(QThread):
    """
    Decrypts the .enc bundle, verifies email + AES-GCM tag,
    extracts the inner ZIP, and returns all files to the patient panel.
    """
    progress  = pyqtSignal(int)
    log       = pyqtSignal(str)
    done      = pyqtSignal(np.ndarray, dict, list)   # img, meta, [(name,bytes)]
    err       = pyqtSignal(str)

    def __init__(self, enc_path: str, patient_email: str, otp: str):
        super().__init__()
        self.enc_path      = enc_path
        self.patient_email = patient_email
        self.otp           = otp

    def run(self):
        try:
            self.log.emit("📂  Reading encrypted bundle..."); self.progress.emit(12)
            with open(self.enc_path, "rb") as f:
                enc = f.read()
            self.log.emit(f"    {len(enc):,} bytes")
            self.log.emit("🔑  Deriving key from OTP (PBKDF2)..."); self.progress.emit(30)
            payload = decrypt_bytes(enc, self.otp)
            if payload is None:
                self.err.emit(
                    "Decryption FAILED\n"
                    "Wrong OTP or file has been tampered with.\n"
                    "AES-GCM authentication tag mismatch.")
                return
            self.log.emit("✅  AES-GCM tag verified — bundle is authentic.")
            self.progress.emit(48)

            meta_len  = int.from_bytes(payload[:4], "big")
            metadata  = json.loads(payload[4:4 + meta_len].decode())
            zip_bytes = payload[4 + meta_len:]

            # ── Email verification ─────────────────────────────────────────
            self.log.emit("📧  Verifying patient email...")
            stored_hash   = metadata.get("email_hash", "")
            supplied_hash = hashlib.sha256(
                self.patient_email.strip().lower().encode()).hexdigest()
            if stored_hash and not hmac.compare_digest(stored_hash, supplied_hash):
                DB.log_otp_event("patient_verify_failed", {"reason": "email_mismatch"})
                DB.log_session("patient", "decrypt_failed", "Email mismatch")
                self.err.emit(
                    "Email Verification FAILED\n"
                    "The email you entered does not match the intended recipient.\n"
                    "Please check your email address and try again.")
                return
            self.log.emit("✅  Email verified — you are the intended recipient.")
            DB.log_otp_event("patient_verified", {"anon_id": metadata.get("anon_id", "")})
            DB.log_session("patient", "decrypt_success",
                f"Bundle decrypted  anon_id={metadata.get('anon_id','')}")
            self.progress.emit(62)

            # ── Extract ZIP ────────────────────────────────────────────────
            self.log.emit("📦  Extracting ZIP bundle...")
            file_list = []
            first_img = None
            with zipfile.ZipFile(_io.BytesIO(zip_bytes), "r") as zf:
                names = zf.namelist()
                self.log.emit(f"    {len(names)} file(s): {', '.join(names)}")
                for i, name in enumerate(names):
                    data = zf.read(name)
                    file_list.append((name, data))
                    if first_img is None and name.lower().endswith(
                            (".png", ".jpg", ".jpeg", ".bmp")):
                        try:
                            first_img = np.array(
                                Image.open(_io.BytesIO(data)).convert("L"),
                                dtype=np.uint8)
                        except Exception:
                            pass
                    self.progress.emit(62 + int(32 * (i + 1) / max(len(names), 1)))

            if first_img is None:
                first_img = np.zeros((128, 128), dtype=np.uint8)

            self.log.emit(f"👤  Patient  : {metadata.get('anon_id','—')}")
            self.log.emit(f"🕐  Issued   : {metadata.get('timestamp','')[:19]}")
            for n, v in metadata.get("areas_mm2", {}).items():
                self.log.emit(f"    {n:<12}: {v:.2f} mm²")
            self.progress.emit(100)
            self.log.emit("🖼️   Bundle ready — download files below.")
            self.done.emit(first_img, metadata, file_list)
        except Exception as e:
            self.err.emit(str(e))


# ── Settings dialog ───────────────────────────────────────────────────────────