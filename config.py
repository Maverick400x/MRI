import os, sys, json, hmac, hashlib, secrets, string, smtplib, time
import threading, zipfile, io as _io
import platform, socket, getpass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2  import PBKDF2HMAC
    from cryptography.hazmat.primitives              import hashes
    from cryptography.exceptions                     import InvalidTag
    CRYPTO_OK = True
except ImportError:
    CRYPTO_OK = False

try:
    from pymongo import MongoClient, DESCENDING
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
    MONGO_OK = True
except ImportError:
    MONGO_OK = False

# ── Constants ─────────────────────────────────────────────────────────────────
APP_NAME      = "MRI Secure Transfer"
VERSION       = "2.0.0"# Resolved relative to this file, not the current working directory — so the
# logo loads correctly whether the app is launched via `python3 main.py`,
# a desktop shortcut, or a packaged .app/.exe.
APP_ROOT      = Path(__file__).resolve().parent
LOGO_SVG      = APP_ROOT / "icons" / "logo.png"
SHARED_FOLDER = os.path.join(tempfile.gettempdir(), "mri_secure_shared")
SALT_BYTES    = 32
NONCE_BYTES   = 12
KEY_BYTES     = 32
PBKDF2_ITERS  = 310_000
ENC_SUFFIX    = ".enc"
PIXEL_SPACING = 1.0
OTP_LENGTH    = 8
OTP_TTL_SEC   = 300
LOGIN_OTP_TTL_SEC = 60   # login OTP is short-lived — 1 minute only
OTP_CHARS     = string.ascii_uppercase + string.digits

# ── Device / system info snapshot ─────────────────────────────────────────
# This is a native desktop app — every session logged happens on the same
# machine currently running the process, so this is computed once at
# import time and attached to every session-log entry for the admin panel
# ("logged-in device" details): hostname, OS, local user, IP, app version,
# and an approximate location from the machine's public IP.

def _lookup_geo() -> dict:
    """
    Best-effort approximate location from the machine's public IP, via a
    free no-key geolocation lookup. Purely informational — IP geolocation
    is city/region-level accuracy at best, not precise. Tries a primary
    HTTPS service, falls back to a secondary one, and fails silently
    (short timeouts) if there's no internet or both are unreachable, since
    this must never block or break app startup.
    """
    import urllib.request

    try:
        with urllib.request.urlopen("https://ipapi.co/json/", timeout=3) as resp:
            data = json.loads(resp.read().decode())
        city    = data.get("city", "") or ""
        region  = data.get("region", "") or ""
        country = data.get("country_name", "") or ""
        ip      = data.get("ip", "")
        if ip:
            return {"public_ip": ip, "city": city, "region": region,
                     "country": country,
                     "location": ", ".join(p for p in (city, region, country) if p) or "Unknown"}
    except Exception:
        pass

    try:
        with urllib.request.urlopen("http://ip-api.com/json/", timeout=3) as resp:
            data = json.loads(resp.read().decode())
        if data.get("status") == "success":
            city    = data.get("city", "") or ""
            region  = data.get("regionName", "") or ""
            country = data.get("country", "") or ""
            return {"public_ip": data.get("query", "unknown"),
                     "city": city, "region": region, "country": country,
                     "location": ", ".join(p for p in (city, region, country) if p) or "Unknown"}
    except Exception:
        pass

    return {"public_ip": "unknown", "city": "", "region": "",
            "country": "", "location": "Unknown"}


def _snapshot_device_info() -> dict:
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"
    try:
        local_ip = socket.gethostbyname(hostname)
        if local_ip.startswith("127."):
            # Loopback isn't useful — try the outbound-socket trick instead.
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            except Exception:
                pass
            finally:
                s.close()
    except Exception:
        local_ip = "unknown"
    try:
        os_name = f"{platform.system()} {platform.release()}"
    except Exception:
        os_name = "unknown"
    try:
        os_user = getpass.getuser()
    except Exception:
        os_user = "unknown"
    info = {
        "hostname":   hostname,
        "local_ip":   local_ip,
        "os":         os_name,
        "os_user":    os_user,
        "machine":    platform.machine(),
        "python":     platform.python_version(),
        "app_version": VERSION,
    }
    info.update(_lookup_geo())
    return info

DEVICE_INFO = _snapshot_device_info()

TUMOR_COLORS  = {
    "Necrotic":  (255,  50,  50, 160),
    "Edema":     ( 50, 200,  50, 160),
    "Enhancing": ( 50, 100, 255, 160),
}

# ── Classic native desktop theme — MRI Secure Transfer ───────────────────────
# Styled after the classic Windows/macOS "system chrome" era: neutral gray
# panels, gradient-bevel buttons, sunken input wells, small (not pill-shaped)
# corner radii, and a restrained system-blue accent — not a flat web palette.
BG     = "#e8e8ea"   # app/window background — neutral system gray
SURF   = "#f4f4f4"   # card / panel face — light gray, slightly lifted off BG
SURF2  = "#fbfbfb"   # sunken input well background
SURF3  = "#dcdde0"   # hover / active state surface
BORDER = "#a8a8ac"   # bevel border — visible, not a hairline
BLUE   = "#3465a4"   # primary — classic system blue (title-bar / default button)
CYAN   = "#2a7f8f"   # accent — scanner teal
RED    = "#a83232"   # danger / necrotic — muted brick red, not neon
GREEN  = "#3a7d3a"   # success / patient — muted forest green
AMBER  = "#b8860b"   # warning / OTP — dark goldenrod
PURPLE = "#6a5296"   # admin / secondary accent — muted plum
TEXT   = "#1c1c1e"   # primary text
DIM    = "#5a5a5e"   # muted text
DIM2   = "#3c3c40"   # slightly darker muted — more emphasis than DIM
LOG_DIM= "#8a8a8e"   # muted text for the dark terminal-style log/file-list widgets only
DR_BG  = "#e4ecf5"   # doctor panel tint
PT_BG  = "#e6f0e6"   # patient panel tint
LOG_BG = "#1e1e1e"   # terminal log background — kept dark by design (console aesthetic)
LOG_FG = "#4ec94e"   # terminal log text
BEVEL_LT = "#ffffff"  # raised-edge highlight (top/left)
BEVEL_DK = "#c4c4c8"  # raised-edge shadow (bottom/right) — soft, not high-contrast
SIDE_W = 220         # sidebar width in pixels

os.makedirs(SHARED_FOLDER, exist_ok=True)


# ── OTP Store ─────────────────────────────────────────────────────────────────
class OTPStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._otp  = None
        self._exp  = 0.0

    def generate(self) -> str:
        otp = "".join(secrets.choice(OTP_CHARS) for _ in range(OTP_LENGTH))
        with self._lock:
            self._otp = otp
            self._exp = time.time() + OTP_TTL_SEC
        return otp

    def verify(self, candidate: str) -> tuple:
        with self._lock:
            if self._otp is None:
                return False, "No OTP has been generated yet."
            if time.time() > self._exp:
                return False, "OTP has expired. Ask the doctor to resend."
            if not hmac.compare_digest(self._otp.upper(), candidate.strip().upper()):
                return False, "Incorrect OTP."
            return True, "OK"

    def seconds_remaining(self) -> int:
        with self._lock:
            return max(0, int(self._exp - time.time()))

    def clear(self):
        with self._lock:
            self._otp = None
            self._exp = 0.0

OTP_STORE = OTPStore()


# ── .env loader ───────────────────────────────────────────────────────────────
def _find_env_file() -> str:
    """
    Search for .env starting from the script's directory, then CWD.
    Returns the path if found, otherwise returns a default path to create it.
    """
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]   # default: next to this script

ENV_PATH = _find_env_file()

def load_env() -> dict:
    """
    Parse a .env file into a dict.
    Handles:
      KEY=value          standard format
      KEY="value"        quoted value
      mongodb+srv://...  bare Atlas URI (auto-assigned to MONGO_URI)
    Skips blank lines and comments (#).
    """
    result = {}
    if not os.path.exists(ENV_PATH):
        return result
    with open(ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # ── Bare MongoDB Atlas URI (no KEY= prefix) ───────────────────
            if line.startswith("mongodb+srv://") or line.startswith("mongodb://"):
                result["MONGO_URI"] = line
                continue
            # ── Standard KEY=value ────────────────────────────────────────
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            result[key] = val
    return result

def save_env(updates: dict) -> None:
    """
    Write/update specific keys in the .env file.
    Preserves existing lines (comments, other keys).
    Creates the file if it does not exist.
    """
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            lines = f.readlines()

    written = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}\n")
            written.add(key)
        else:
            new_lines.append(line)

    # Append any keys not already in the file
    for key, val in updates.items():
        if key not in written:
            new_lines.append(f"{key}={val}\n")

    with open(ENV_PATH, "w") as f:
        f.writelines(new_lines)


# ── Gmail config — loaded from .env ──────────────────────────────────────────
class GmailConfig:
    """
    Reads GMAIL_SENDER and GMAIL_APP_PASSWORD from .env on startup.
    Settings dialog writes changes back to .env via save_env().
    """
    def __init__(self):
        env = load_env()
        self.sender_email : str = env.get("GMAIL_SENDER", "")
        self.app_password : str = env.get("GMAIL_APP_PASSWORD", "")
        self.env_path     : str = ENV_PATH

    def reload(self):
        env = load_env()
        self.sender_email = env.get("GMAIL_SENDER", "")
        self.app_password = env.get("GMAIL_APP_PASSWORD", "")

    def persist(self):
        """Save current values back to .env."""
        save_env({
            "GMAIL_SENDER":       self.sender_email,
            "GMAIL_APP_PASSWORD": self.app_password,
        })

GMAIL = GmailConfig()


# ── AI report config — loaded from .env ──────────────────────────────────────
class AIConfig:
    """
    Reads ANTHROPIC_API_KEY from .env on startup. Optional — if unset,
    reports are generated exactly as before (results table + overlay
    image, no AI narrative section).
    """
    def __init__(self):
        env = load_env()
        self.api_key: str = env.get("ANTHROPIC_API_KEY", "")
        self.model:   str = env.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    def reload(self):
        env = load_env()
        self.api_key = env.get("ANTHROPIC_API_KEY", "")
        self.model   = env.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    def persist(self):
        save_env({"ANTHROPIC_API_KEY": self.api_key, "ANTHROPIC_MODEL": self.model})

AI_CFG = AIConfig()

# ── Temporary AI kill-switch ──────────────────────────────────────────────
# Set to False to disable all AI features app-wide (AI findings narrative +
# agentic analysis) even if an API key is configured — reports are still
# generated normally, just without the AI-drafted sections. Flip back to
# True to re-enable everything; no other code changes needed.
AI_FEATURES_ENABLED = False


# ── MongoDB layer ─────────────────────────────────────────────────────────────
class MongoDB:
    """
    Thin wrapper around pymongo.  All writes are fire-and-forget via a
    background thread so the UI never blocks on DB operations.

    Collections
    -----------
    scans      — one doc per encrypted scan transfer
    otp_audit  — one doc per OTP lifecycle event
    sessions   — one doc per user action (doctor / patient)
    """

    def __init__(self):
        env              = load_env()
        self.uri         = env.get("MONGO_URI", "mongodb+srv://ranganathsrinivasa95_db_user:VyZyFUMmHzl4Ngnf@k90.zufkrss.mongodb.net/?appName=k90")
        self.db_name     = env.get("MONGO_DB",  "mri_secure_transfer")
        self._client     = None
        self._db         = None
        self.connected   = False
        self.status_msg  = "Not connected"
        self._connect()

    def _connect(self):
        if not MONGO_OK:
            self.status_msg = "pymongo not installed  (pip install pymongo)"
            return
        try:
            self._client   = MongoClient(self.uri, serverSelectionTimeoutMS=3000)
            self._client.admin.command("ping")          # raises if unreachable
            self._db       = self._client[self.db_name]
            self.connected = True
            self.status_msg = f"Connected  ·  {self.uri}  ·  db: {self.db_name}"
            self._ensure_indexes()
        except Exception as e:
            self.connected  = False
            self.status_msg = f"Connection failed: {e}"

    def _col(self, name):
        return self._db[name] if self.connected and self._db is not None else None

    def _async(self, fn, *args):
        """Run fn(*args) in a daemon thread — non-blocking."""
        t = threading.Thread(target=fn, args=args, daemon=True)
        t.start()

    # ── Public write methods (called from workers / UI) ──────────────────────

    def log_scan(self, doc: dict):
        """Record a completed encrypted scan transfer."""
        def _w():
            try:
                col = self._col("scans")
                if col is None: return
                col.insert_one({**doc, "timestamp": datetime.now(timezone.utc).isoformat()})
            except Exception:
                pass
        self._async(_w)

    def log_otp_event(self, event: str, extra: dict = None):
        """
        event: 'generated' | 'email_sent' | 'email_failed' |
               'doctor_verified' | 'doctor_verify_failed' |
               'patient_verified' | 'patient_verify_failed' |
               'expired' | 'cleared'
        """
        def _w():
            try:
                col = self._col("otp_audit")
                if col is None: return
                col.insert_one({
                    "event":     event,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **(extra or {}),
                })
            except Exception:
                pass
        self._async(_w)

    def log_session(self, role: str, action: str, detail: str = ""):
        """role: 'doctor' | 'patient' | 'system'"""
        def _w():
            try:
                col = self._col("sessions")
                if col is None: return
                col.insert_one({
                    "role":      role,
                    "action":    action,
                    "detail":    detail,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "device":    DEVICE_INFO,
                })
            except Exception:
                pass
        self._async(_w)

    # ── Public read methods (called from Admin tab) ──────────────────────────

    def get_scans(self, limit=100) -> list:
        col = self._col("scans")
        if col is None: return []
        try:
            return list(col.find({}, {"_id": 0}).sort("timestamp", DESCENDING).limit(limit))
        except Exception:
            return []

    def get_scans_by_patient(self, patient_id: str, limit=20) -> list:
        """
        Scan history for one patient, newest first. Used by the Doctor
        Workspace's "Check Previous Scans" lookup so a phase-over-phase
        comparison (previous vs current) can be built — the app only
        compares consecutive phases, never a full longitudinal series.
        """
        col = self._col("scans")
        if col is None or not patient_id: return []
        try:
            return list(col.find({"patient_id": patient_id}, {"_id": 0})
                        .sort("timestamp", DESCENDING).limit(limit))
        except Exception:
            return []

    def get_otp_audit(self, limit=200) -> list:
        col = self._col("otp_audit")
        if col is None: return []
        try:
            return list(col.find({}, {"_id": 0}).sort("timestamp", DESCENDING).limit(limit))
        except Exception:
            return []

    def get_sessions(self, limit=200) -> list:
        col = self._col("sessions")
        if col is None: return []
        try:
            return list(col.find({}, {"_id": 0}).sort("timestamp", DESCENDING).limit(limit))
        except Exception:
            return []

    def counts(self) -> dict:
        if not self.connected:
            return {"scans": 0, "otp_audit": 0, "sessions": 0}
        try:
            return {
                "scans":     self._db["scans"].count_documents({}),
                "otp_audit": self._db["otp_audit"].count_documents({}),
                "sessions":  self._db["sessions"].count_documents({}),
            }
        except Exception:
            return {"scans": 0, "otp_audit": 0, "sessions": 0}

    def reconnect(self):
        self._connect()

    # ── Patient profile methods (name / age / sex on file, keyed by ID) ──────

    def get_patient(self, patient_id: str) -> dict | None:
        """Return the stored demographic profile for a Patient ID, if any."""
        col = self._col("patients")
        if col is None or not patient_id: return None
        try:
            return col.find_one({"patient_id": patient_id}, {"_id": 0})
        except Exception:
            return None

    def upsert_patient(self, patient_id: str, name: str, age, sex: str) -> None:
        """Save/update the demographic profile for a Patient ID so it can be
        auto-retrieved next time a doctor enters the same ID."""
        col = self._col("patients")
        if col is None or not patient_id: return
        def _w():
            try:
                col.update_one(
                    {"patient_id": patient_id},
                    {"$set": {
                        "patient_id": patient_id,
                        "patient_name": name,
                        "age":  age,
                        "sex":  sex,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }},
                    upsert=True)
            except Exception:
                pass
        self._async(_w)

    # ── User / auth methods ──────────────────────────────────────────────────

    def _ensure_indexes(self):
        try:
            self._db["scans"].create_index([("timestamp", DESCENDING)])
            self._db["otp_audit"].create_index([("timestamp", DESCENDING)])
            self._db["sessions"].create_index([("timestamp", DESCENDING)])
            self._db["users"].create_index(
                [("user_id", 1), ("role", 1)], unique=True)
            self._db["doctors"].create_index("user_id", unique=True)
            self._db["patients"].create_index("patient_id", unique=True)
        except Exception:
            pass

    def get_user(self, user_id: str, role: str) -> dict | None:
        """Return user doc or None if not found."""
        col = self._col("users")
        if col is None: return None
        try:
            return col.find_one({"user_id": user_id, "role": role}, {"_id": 0})
        except Exception:
            return None

    def upsert_user(self, user_id: str, role: str, email: str,
                    display_name: str = "") -> dict:
        """
        Create user if not exists (auto-register on first login).
        Always updates last_seen, email and display_name.
        Returns the upserted doc.
        """
        col = self._col("users")
        now = datetime.now(timezone.utc).isoformat()
        # Default display name: "Dr. <ID>" or "Patient <ID>"
        if not display_name:
            display_name = (f"Dr. {user_id}" if role == "doctor"
                            else f"Patient {user_id}")
        doc = {
            "user_id":      user_id,
            "role":         role,
            "email":        email,
            "display_name": display_name,
            "created_at":   now,
            "last_seen":    now,
            "login_count":  1,
        }
        if col is None:
            return doc
        try:
            existing = col.find_one({"user_id": user_id, "role": role})
            if existing:
                col.update_one(
                    {"user_id": user_id, "role": role},
                    {"$set": {"last_seen": now, "email": email,
                              "display_name": display_name or
                              existing.get("display_name", display_name)},
                     "$inc": {"login_count": 1}},
                )
                existing.update({"last_seen": now, "email": email})
                existing["login_count"] = existing.get("login_count", 0) + 1
                if not existing.get("display_name"):
                    existing["display_name"] = display_name
                return existing
            else:
                col.insert_one(doc.copy())
                return doc
        except Exception:
            return doc

    def get_users(self, role: str = None, limit: int = 200) -> list:
        col = self._col("users")
        if col is None: return []
        try:
            q = {"role": role} if role else {}
            return list(col.find(q, {"_id": 0}).sort("last_seen", DESCENDING).limit(limit))
        except Exception:
            return []

    # ── Doctor whitelist ───────────────────────────────────────────────────
    # Separate from `users`: this is the admin-curated list of who is
    # *allowed* to log in as a doctor at all. `users` records who actually
    # has, once they've cleared that gate.

    def add_doctor(self, user_id: str, email: str, name: str = "") -> tuple:
        """
        Add (or update) an approved doctor. Returns (ok: bool, message: str).
        Call only after the email has been OTP-verified — this method itself
        does not verify anything, it just persists the record.
        """
        if not self.connected:
            return False, "Not connected to MongoDB — nothing was saved."
        col = self._col("doctors")
        if col is None:
            return False, "Not connected to MongoDB — nothing was saved."
        try:
            now = datetime.now(timezone.utc).isoformat()
            email = email.strip().lower()
            existing = col.find_one({"user_id": user_id})
            if existing:
                col.update_one(
                    {"user_id": user_id},
                    {"$set": {"email": email, "name": name, "updated_at": now}},
                )
                return True, f"Updated approved doctor {user_id}."
            col.insert_one({
                "user_id":  user_id,
                "email":    email,
                "name":     name,
                "added_at": now,
            })
            return True, f"{user_id} added to the approved doctors list."
        except Exception as e:
            return False, str(e)

    def remove_doctor(self, user_id: str) -> bool:
        col = self._col("doctors")
        if col is None: return False
        try:
            col.delete_one({"user_id": user_id})
            return True
        except Exception:
            return False

    def get_doctors(self, limit: int = 200) -> list:
        col = self._col("doctors")
        if col is None: return []
        try:
            return list(col.find({}, {"_id": 0}).sort("added_at", DESCENDING).limit(limit))
        except Exception:
            return []

    def is_doctor_approved(self, user_id: str, email: str) -> bool:
        """
        True only if this exact Doctor ID has been pre-approved with this
        email (case-insensitive on the email). Fails CLOSED: any error, or
        no DB connection, returns False rather than letting the login through.
        """
        col = self._col("doctors")
        if col is None:
            return False
        try:
            rec = col.find_one({"user_id": user_id})
            if not rec:
                return False
            return rec.get("email", "").strip().lower() == email.strip().lower()
        except Exception:
            return False

DB = MongoDB()


# ── Session state ─────────────────────────────────────────────────────────────
class Session:
    """Holds the currently logged-in user for each role."""
    doctor  : dict | None = None   # {user_id, email, role, ...}
    patient : dict | None = None

    @classmethod
    def is_logged_in(cls, role: str) -> bool:
        return cls.doctor is not None if role == "doctor" else cls.patient is not None

    @classmethod
    def current(cls, role: str) -> dict | None:
        return cls.doctor if role == "doctor" else cls.patient

    @classmethod
    def set(cls, role: str, user_doc: dict):
        if role == "doctor":
            cls.doctor = user_doc
        else:
            cls.patient = user_doc

    @classmethod
    def clear(cls, role: str):
        if role == "doctor":
            cls.doctor = None
        else:
            cls.patient = None


class LoginOTPStore:
    """
    Separate OTP store for login (independent of scan-transfer OTP).
    Keyed by (role, user_id) so doctor and patient OTPs never collide.
    """
    def __init__(self):
        self._lock   = threading.Lock()
        self._otps   = {}   # (role, user_id) → (otp, expiry)

    def generate(self, role: str, user_id: str) -> str:
        otp = "".join(secrets.choice(OTP_CHARS) for _ in range(OTP_LENGTH))
        with self._lock:
            self._otps[(role, user_id)] = (otp, time.time() + LOGIN_OTP_TTL_SEC)
        return otp

    def verify(self, role: str, user_id: str, candidate: str) -> tuple:
        with self._lock:
            entry = self._otps.get((role, user_id))
            if not entry:
                return False, "No OTP generated for this account."
            otp, exp = entry
            if time.time() > exp:
                return False, "OTP has expired. Request a new one."
            if not hmac.compare_digest(otp.upper(), candidate.strip().upper()):
                return False, "Incorrect OTP."
            del self._otps[(role, user_id)]   # single-use
            return True, "OK"

    def seconds_remaining(self, role: str, user_id: str) -> int:
        with self._lock:
            entry = self._otps.get((role, user_id))
            if not entry: return 0
            return max(0, int(entry[1] - time.time()))

    def clear(self, role: str, user_id: str):
        with self._lock:
            self._otps.pop((role, user_id), None)

LOGIN_OTP_STORE = LoginOTPStore()

# Separate store for the admin "verify a doctor's email before whitelisting
# them" flow. Kept apart from LOGIN_OTP_STORE so an in-progress admin
# verification can never collide with an in-progress login attempt for the
# same ID.
DOCTOR_VERIFY_STORE = LoginOTPStore()

