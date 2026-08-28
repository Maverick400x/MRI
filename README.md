# MRI Secure Transfer — Complete Application Documentation

**Version 2.0.0**

---

## Table of Contents

1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [Security Model](#security-model)
4. [Roles &amp; Access Control](#roles-access-control)
5. [Feature Documentation](#feature-documentation)
   - 5.1 Login & Authentication
   - 5.2 Doctor Workspace
   - 5.3 Patient Workspace
   - 5.4 Admin Panel
   - 5.5 Email Notifications
   - 5.6 AI-Assisted Features
6. [User Manual](#user-manual)
   - 6.1 For Doctors
   - 6.2 For Patients
   - 6.3 For Administrators
7. [Data Model (MongoDB Collections)](#data-model-mongodb-collections)
8. [File Reference](#file-reference)
9. [Known Limitations &amp; Disclaimers](#known-limitations-disclaimers)
10. [Installation &amp; Setup](#installation-setup)

---

## 1. Overview

**MRI Secure Transfer** is a desktop application (built with PyQt6) that lets a doctor upload a brain MRI slice, run tumor segmentation on it, and securely transfer the encrypted results to a patient — with OTP-based authentication at every step and a full administrative audit trail.

The application has three entry points:

| Entry point      | Who uses it        | What it opens                                                       |
| ---------------- | ------------------ | ------------------------------------------------------------------- |
| `main.py`      | Doctors & Patients | The main app — login, then Doctor or Patient Workspace             |
| `run_admin.py` | Administrators     | A standalone Admin Panel (doctor management, analytics, audit logs) |

The application targets a **classic native-desktop visual style** (gray panels, beveled buttons, sunken input fields) rather than a modern flat/web look, and is themed consistently across every screen via a shared `theme.py` widget factory.

---

## 2. System Architecture

### 2.1 Technology Stack

| Layer                | Technology                                               |
| -------------------- | -------------------------------------------------------- |
| UI framework         | PyQt6                                                    |
| Encryption           | `cryptography` (AES-256-GCM, PBKDF2-HMAC-SHA256)       |
| Database             | MongoDB (via`pymongo`), Atlas-hosted                   |
| Email                | Gmail SMTP (`smtplib`), HTML emails with inline images |
| PDF reports          | `reportlab`                                            |
| Image processing     | `numpy`, `Pillow`                                    |
| Optional AI features | Anthropic API (`anthropic` SDK) — tool-use/agentic    |
| Packaging            | PyInstaller (`main.spec`)                              |

### 2.2 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         main.py (entry)                       │
│                              │                                │
│                        main_window.py                         │
│              (top bar, screen stack, session state)           │
│         ┌────────────┬────────────────┬────────────────┐     │
│         │            │                │                 │     │
│    login.py      panels.py       panels.py          admin.py  │
│  (Login/OTP)   (DoctorPanel)   (PatientPanel)   (via run_admin)│
└─────────────────────────────────────────────────────────────┘
         │                │                │
    workers.py        imaging.py      email_service.py
  (QThread workers   (segmentation,   (HTML emails, PDF
   for async I/O)     quality/risk     report generation)
                       heuristics)
         │                │                │
                    config.py
      (DB access layer, crypto config, OTP stores,
       device info, all shared constants/colors)
                         │
                    crypto.py
              (AES-256-GCM primitives)
```

All screens share one visual language defined in **`theme.py`** — reusable widget factories (`mkbtn`, `mkcard`, `mkinp`, `mkbadge`, `BarChart`, `PieChart`, `LineChart`, etc.) so every panel looks and behaves consistently without duplicating styling code.

### 2.3 Why Two Entry Points

`main.py` is the clinical workflow (doctor/patient). `run_admin.py` is deliberately separate — administrators managing the approved-doctor roster and reviewing audit logs don't need (and shouldn't casually have) a doctor or patient session open at the same time. Both share the same `config.py`/MongoDB backend, so data is always consistent between them.

---

## 3. Security Model

### 3.1 Encryption

Every MRI bundle a doctor sends is encrypted with **AES-256-GCM** (authenticated encryption — tamper-evident, not just confidentiality) before it ever touches the shared folder or network.

- **Key derivation:** `PBKDF2-HMAC-SHA256`, **310,000 iterations**, from the OTP the doctor generates for that specific transfer. The OTP itself is never stored in the encrypted payload or transmitted alongside it — only the doctor's and patient's own copies (kept in-memory / sent by separate email) can derive the correct key.
- **Nonce & salt:** freshly random per encryption (`secrets.token_bytes`), stored alongside the ciphertext.
- **Patient anonymization:** the Patient ID is never stored in plaintext inside the encrypted bundle's metadata being logged to MongoDB — it's pseudonymized via `HMAC-SHA256` (`crypto.py: pseudonymise()`), producing an `ANON-XXXXXXXXXX` identifier. The email address is similarly stored only as a SHA-256 fingerprint for verification, never in plaintext in the audit log.

### 3.2 OTP-Based Authentication (multiple independent OTP flows)

The app uses **four separate OTP mechanisms**, each with its own store and TTL, so a leak or expiry in one flow never affects another:

| OTP flow                | Purpose                                              | TTL                  | Store                                     |
| ----------------------- | ---------------------------------------------------- | -------------------- | ----------------------------------------- |
| Login OTP               | Doctor/Patient login                                 | **60 seconds** | `LoginOTPStore` (keyed by role+user_id) |
| Scan-transfer OTP       | Encrypts/decrypts one specific MRI bundle            | 300 seconds (5 min)  | `OTPStore` (single active OTP)          |
| Doctor-verification OTP | Admin confirms a new doctor's email before approving | 300 seconds (5 min)  | `DoctorVerifyOTPStore`                  |

All OTPs are 8 characters (`OTP_LENGTH = 8`), drawn from uppercase letters + digits (`OTP_CHARS`), generated via `secrets.choice` (cryptographically secure). Every OTP entry field in the app **masks input** (dots, not plaintext) — login screen, Doctor Workspace verification field, Patient Workspace decrypt field, and the Admin panel's doctor-verification field.

### 3.3 Device / Location Awareness

Because this is a native desktop app (not a multi-client web server), "the device" for any session is simply the machine currently running the process. A `DEVICE_INFO` snapshot — hostname, local IP, OS, OS username, machine architecture, Python version, and an approximate geolocation (city/region/country, from the machine's public IP via a best-effort external lookup) — is computed once at startup and:

- Attached to every session log entry in MongoDB (visible in the Admin Panel's Sessions table)
- Embedded in every OTP-bearing email, so the recipient can see what system generated the code they received, with a warning to contact the administrator if it's unrecognized

The geolocation lookup is deliberately best-effort: it tries one free IP-geolocation service, falls back to a second if the first fails, and silently returns "Unknown" if neither is reachable — it must never block or crash app startup.

### 3.4 What Is *Not* a Certified Security Guarantee

- Gmail credentials are stored in **plaintext in `.env`** — the Settings screen explicitly warns about this and instructs never to commit `.env` to version control.
- The modality/quality/risk heuristics (below) are pixel-statistics screens, not clinically validated tools.

---

## 4. Roles & Access Control

| Role                    | How they're approved                                                                                                   | What they can do                                                                                                      |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Doctor**        | Must be pre-approved by an Administrator (Doctor ID + email added via Admin Panel, with email-verification OTP)        | Upload MRI scans, run segmentation, review AI-assisted analysis, encrypt & send scans to patients                     |
| **Patient**       | Self-registers on first login (no pre-approval step)                                                                   | Receive and decrypt scan bundles, view results, download files, generate their own copy of the report                 |
| **Administrator** | Runs`run_admin.py` directly — no in-app login screen; access is controlled by who can run the standalone admin tool | Manage the approved-doctor roster, view all audit logs (Scans, OTP events, Sessions, Users), view cross-app analytics |

---

## 5. Feature Documentation

### 5.1 Login & Authentication

**Screens:** `login.py` — `LoginScreen` (tab switcher) → `RoleLoginWidget` (Doctor/Patient tab) → `WelcomeScreen` (post-login transition)

Flow:

1. Enter ID (e.g. `DR-001` / `PT-001`) and registered email.
2. For doctors: the ID+email pair must match an admin-approved record, or login is refused with a clear message ("Contact your administrator").
3. Click **Send Login OTP** — an 8-character OTP is generated (`LoginOTPStore`, 60-second TTL) and emailed, with a live countdown timer on screen.
4. Enter the OTP (masked input) and click **Login as Doctor/Patient**.
5. On success, a session is created (`Session.set()`), a `login_success` event is logged (with device info), and the user proceeds to a brief animated **WelcomeScreen** before landing in their workspace.

The login and welcome cards are **responsive**: wrapped in a `QScrollArea` so content never clips or overlaps on small windows, and the card itself has a flexible width (320–480px) rather than a fixed size.

### 5.2 Doctor Workspace

Four sequential numbered sections, each a distinct card:

**Step 1 — MRI Scan Acquisition**

- **Modality gate:** every uploaded file is screened by `assess_scan_modality()` — a pixel-statistics heuristic (not a trained classifier) that reliably rejects color photos (channel-difference check) and flags likely X-rays (stark bimodal contrast, little soft-tissue gradation) or CT scans (a hard circular gantry-vignette cutoff detected via a ring-sampling technique). Flagged files trigger a confirm/override dialog rather than a silent block, since the heuristic can be wrong.
- **Scan Quality Analysis:** once an image is accepted, six metrics are computed and displayed with severity-color coding (red/amber/green):
  - *Normalization* — original pixel range mapped to 0–1
  - *Density* — % of pixels that are tissue vs. black background
  - *Noise* — high-frequency residual (box-blur difference), labeled Low/Moderate/High
  - *Tissue Contrast* — RMS intensity spread within the tissue region, labeled Low/Moderate/Good
  - *Border Sharpness* — Laplacian-variance blur metric, labeled Fuzzy/Moderate/Sharp
  - *Intensity Uniformity* — brightness spread across the slice's four quadrants (catches bias-field-style non-uniformity), labeled Stable/Moderate shift/High shift
- **Patient info panel:** Patient ID, Name, Age, Sex. Entering a Patient ID that's already on file (MongoDB `patients` collection) **auto-fills and locks** Name/Age/Sex; an unrecognized ID leaves them editable and required.
- **Check Previous Scans:** looks up the patient's scan history for a phase-over-phase comparison later in the workflow.

**Step 2 — Tumor Segmentation & Volumetric Analysis**

- **Run CBAM + UNet Segmentation** button triggers `simulate_segmentation()` — see *Section 9, Known Limitations* for an important caveat about what this actually does.
- Produces three region masks — **Necrotic**, **Edema**, **Enhancing** — each rendered as a colored overlay on the original slice, plus a **Total** stat card. Every card shows both the mm² value and its percentage share of the total.
- **Regional Area Distribution** bar chart, and a **Phase-over-Phase Comparison** grouped bar chart (Previous vs. Current) that appears automatically once "Check Previous Scans" has found history.
- **Preliminary Risk Indicator:** `assess_risk_level()` computes a heuristic band (Minimal/Low/Moderate/High/Critical) from total tumor area, bumped up one level if necrotic tissue exceeds 30% of the total (a rough aggressiveness proxy). Always labeled as an automated estimate requiring radiologist confirmation — never a diagnosis.
- **Agentic AI Analysis** (optional, off by default — see 5.6).

**Step 3 — Secure Patient Authentication**

- Enter the patient's email, click **Generate & Send OTP**.
- The OTP is emailed to both the doctor (for verification) and the patient (for decryption) via `send_dual_otp_emails()`.
- The doctor re-enters the OTP in a masked, monospace field to confirm before the transfer can proceed — a deliberate "confirm you received your own email" step.

**Step 4 — Encrypted Transfer & Delivery**

- **Encrypt Bundle & Send to Patient**: packs all selected files into an in-memory ZIP, builds a metadata header (algorithm, KDF details, area measurements, doctor/patient identifiers), and encrypts the whole payload with AES-256-GCM using a key derived from the OTP.
- Badges confirm the exact primitives used: `AES-256-GCM`, `PBKDF2·310k`, `OTP Auth`, `HMAC Anon`.
- A non-PHI sidecar `.manifest.json` is written alongside the `.enc` file for auditability without exposing patient data.
- A live **Activity Log** (dark terminal-style panel) streams every step as it happens.

### 5.3 Patient Workspace

Four parallel sections:

1. **Incoming Secure Transfers** — lists `.enc` bundles found in the shared folder.
2. **Identity Verification & Decryption** — the patient enters their email (must match the sender's intended recipient, verified via SHA-256 fingerprint comparison) and the OTP they received, then decrypts. A wrong OTP or tampered file fails the AES-GCM authentication tag check and is rejected outright — this is authenticated encryption, so corruption/tampering is cryptographically detected, not just guessed at.
3. **Scan File Retrieval** — download the decrypted files (images/GIFs) individually.
4. **Diagnostic Report Generation** — rebuilds the tumor overlay and results table from the decrypted data into a PDF report, optionally with an AI-drafted findings narrative (if AI features are enabled).

### 5.4 Admin Panel

Accessed via `run_admin.py` (standalone). Tabs:

- **Doctors** — add a new approved doctor (OTP-gated: the doctor's email must be verified before the record is saved), remove doctors, live roster table with search.
- **Analytics** — six charts aggregating live MongoDB data:

| Chart                      | Type | Shows                                              |
| -------------------------- | ---- | -------------------------------------------------- |
| Users by Role              | Pie  | Doctor vs. Patient account split                   |
| Scans by Risk Level        | Pie  | Minimal→Critical distribution across all scans    |
| Scans per Day (14d)        | Line | Daily scan-transfer activity trend                 |
| Avg. Region Area           | Bar  | Necrotic/Edema/Enhancing averaged across all scans |
| Top Patients by Scan Count | Bar  | Most-scanned patients                              |
| Logins per Day (14d)       | Line | Daily login activity trend                         |

  All charts are custom `QPainter` widgets (`PieChart`, `LineChart`, `BarChart` in `theme.py`) — no external plotting library dependency.

- **Encrypted Scans**, **OTP Audit**, **Sessions**, **Users** — read-only audit tables, each with a live search box (case-insensitive, filters across every column, shows an "X / Y match" count) that survives the panel's 15-second auto-refresh.
- **Sessions table** additionally shows the logged-in device's Host, IP, Location, OS, and OS User for every session event.
- The panel's top status bar shows the *current* admin session's own device summary (hostname, OS, IP, location) with a full tooltip.

### 5.5 Email Notifications

All emails (`email_service.py`) are HTML, dark-themed, and share:

- An **inline embedded logo** (the actual app icon, attached via `Content-ID` — not a hosted image URL, so it renders even for recipients who block remote images), with an emoji fallback `alt` text.
- A **"System Currently Online"** block on every OTP-bearing email — Device, Local IP, Public IP, Location, OS User, and timestamp — with a warning to contact the administrator if the device/location is unrecognized.
- Accurate, dynamic OTP expiry text (e.g. "Expires at 22:25 UTC — valid 1 minute") computed from the actual TTL constant for that specific OTP flow, not a hardcoded string.

Four distinct emails are sent across the app: Login OTP, Doctor-verification OTP, and the paired Doctor-OTP + Patient-credentials emails from the scan-transfer flow.

### 5.6 AI-Assisted Features (optional)

Gated by a single kill-switch, `AI_FEATURES_ENABLED` in `config.py` — when `False`, no API calls are made anywhere in the app, regardless of whether an API key is configured; reports are generated by the app itself with no AI narrative section.

Two distinct AI features exist:

- **AI Findings Narrative** (`ai_report.py`) — a single-completion draft of the report's narrative section (findings/impression/flags), given only the already-computed area measurements. Hedged clinical language, explicit "preliminary, requires radiologist confirmation" framing, never invents numbers.
- **Agentic AI Analysis** (`agent_analysis.py`) — genuinely agentic: uses Anthropic's tool-use API to let the model *decide for itself* whether to call one of four tools (`get_scan_history`, `get_patient_profile`, `get_quality_trend`, `get_risk_trend`) before producing its analysis, rather than only reasoning over pre-supplied numbers. Every tool call is visibly logged in the Activity Log as it happens.

Both are strictly optional per-click actions (never automatic), and both fail gracefully with a clean, actionable message (e.g. "Anthropic account has insufficient credits — add credits at console.anthropic.com") rather than a raw API error dump.

---

## 6. User Manual

### 6.1 For Doctors

1. Open the app, select the **Doctor** tab, enter your Doctor ID and registered email, click **Send Login OTP**.
2. Check your email for the OTP (valid 60 seconds), enter it, click **Login as Doctor**.
3. In **Step 1**, click **Add Images / GIFs** and select an MRI slice. If it doesn't look like an MRI (photo/X-ray/CT), you'll be asked to confirm or cancel.
4. Review the **Scan Quality Analysis** readout — if Contrast/Border/Intensity are flagged red, consider re-scanning.
5. Enter the **Patient ID**. If it's on file, Name/Age/Sex auto-fill — otherwise, fill them in yourself.
6. (Optional) Click **Check Previous Scans** if this patient has a prior visit on record.
7. In **Step 2**, click **Run CBAM + UNet Segmentation**. Review the area breakdown, charts, and the Preliminary Risk Indicator.
8. (Optional) Click **Run Agent** for an AI-assisted analysis, if enabled.
9. In **Step 3**, enter the patient's email and click **Generate & Send OTP**. Check your own email, re-enter the OTP to confirm.
10. In **Step 4**, click **Encrypt Bundle & Send to Patient**. Watch the Activity Log for confirmation.

### 6.2 For Patients

1. Select the **Patient** tab, log in the same way (ID + email + OTP).
2. In the workspace, your incoming encrypted transfer should appear automatically.
3. Enter your email and the OTP your doctor sent you, click to decrypt.
4. Download your files, or generate a PDF report of your results.

### 6.3 For Administrators

1. Run `run_admin.py` directly (separate from the main app).
2. **Doctors tab:** enter the new doctor's ID and email, click **Send Verification OTP** — this confirms the address is real before it's trusted. Enter the OTP the doctor receives, confirm to add them to the roster.
3. **Analytics tab:** review the six charts for a snapshot of app-wide activity.
4. **Scans / OTP Audit / Sessions / Users tabs:** use the search box above each table to filter by any visible field (Patient ID, event type, hostname, etc.).

---

## 7. Data Model (MongoDB Collections)

| Collection    | Purpose                                  | Key fields                                                                                      |
| ------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `scans`     | One record per encrypted transfer        | `patient_id`, `anon_id`, `areas_mm2`, `quality`, `risk`, `algorithm`, `timestamp` |
| `patients`  | Demographic profile, keyed by Patient ID | `patient_id`, `patient_name`, `age`, `sex`, `updated_at`                              |
| `users`     | Registered doctor/patient accounts       | `user_id`, `role`, `email`, `display_name`, `login_count`, `last_seen`              |
| `doctors`   | Admin-approved doctor roster             | `user_id`, `email`, `name`, `added_at`                                                  |
| `sessions`  | Every login/logout/transfer event        | `role`, `action`, `detail`, `timestamp`, `device` (full device snapshot)              |
| `otp_audit` | Every OTP lifecycle event                | `event`, `to`, `patient_id`, `ttl_sec`, `reason`, `timestamp`                       |

Indexes are created on `timestamp` (descending) for the audit collections, and unique compound indexes on `(user_id, role)` for `users`, `patient_id` for `patients`, and `user_id` for `doctors`.

---

## 8. File Reference

| File                   | Responsibility                                                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `main.py`            | App entry point — startup checks, launches`MainWindow`                                                                       |
| `main_window.py`     | Top-level window: top bar, screen stack (Login → Welcome → Doctor/Patient), global QSS theme                                  |
| `login.py`           | Login screen, role tabs, OTP entry, Welcome transition screen                                                                   |
| `panels.py`          | `DoctorPanel` and `PatientPanel` — the two large workspace screens                                                         |
| `admin.py`           | Standalone`AdminTab` — Doctors, Analytics, and audit-log tables                                                              |
| `run_admin.py`       | Entry point for the standalone Admin Panel window                                                                               |
| `config.py`          | All shared constants, color tokens, the`DB` class (MongoDB access layer), OTP stores, `DEVICE_INFO`, Gmail/AI config        |
| `crypto.py`          | AES-256-GCM encrypt/decrypt, PBKDF2 key derivation, HMAC pseudonymization                                                       |
| `imaging.py`         | `simulate_segmentation()`, `assess_scan_modality()`, `analyze_scan_quality()`, `assess_risk_level()`, overlay rendering |
| `workers.py`         | `QThread` background workers — encryption, email sending, decryption (keeps the UI responsive during I/O)                    |
| `email_service.py`   | All HTML email templates, inline logo embedding, PDF report generation                                                          |
| `ai_report.py`       | `AIFindingsWorker` — single-completion AI narrative drafting                                                                 |
| `agent_analysis.py`  | `AgentAnalysisWorker` — tool-use agentic analysis                                                                            |
| `theme.py`           | Shared widget factory: buttons, cards, inputs, badges, and the`BarChart`/`PieChart`/`LineChart` widgets                   |
| `settings_dialog.py` | Gmail SMTP + Anthropic API key configuration dialog                                                                             |
| `main.spec`          | PyInstaller packaging spec                                                                                                      |
| `requirements.txt`   | Python dependencies                                                                                                             |

---

## 9. Known Limitations & Disclaimers

These are important to understand — the application is built with the same transparent, hedged posture throughout, and this section consolidates every caveat mentioned elsewhere in this document:

1. **Segmentation is simulated, not a real trained model.** The "Run CBAM + UNet Segmentation" button runs `simulate_segmentation()` — a threshold/radius-based heuristic on pixel intensity, **not** actual inference from a trained CBAM-integrated U-Net. The button's label describes the target research architecture, not what currently executes. Wiring in real model inference is the highest-priority gap if this app is meant to demonstrate the trained model's actual output.
2. **Modality detection, quality analysis, and risk assessment are all pixel-statistics heuristics**, not validated/trained classifiers. They reliably catch obvious cases (a real photo, a starkly bimodal X-ray) but can be wrong on unusual images — which is why the modality check allows doctor override rather than a silent hard block.
3. **The AI features never see or analyze the image itself** — they only reason over already-computed numbers (areas, quality metrics, risk bands) that the app hands them, or that they retrieve themselves via tools. Every output is explicitly hedged and labeled as requiring radiologist confirmation.
4. **Geolocation is approximate** (city/region-level at best) and depends on outbound internet access to a third-party IP-geolocation service; it fails gracefully to "Unknown" otherwise.
5. **Gmail credentials are stored in plaintext** in the local `.env` file — never commit this file to version control.
6. This application is a research/academic prototype, not a certified medical device, and makes no diagnostic claims anywhere in its output.

---

## 10. Installation & Setup

### 10.1 Requirements

```
PyQt6>=6.4.0
cryptography>=41.0.0
pymongo[srv]>=4.6.0
numpy>=1.24.0
Pillow>=10.0.0
reportlab>=4.0.0
anthropic>=0.40.0
```

### 10.2 Setup Steps

1. Create and activate a virtual environment.
2. `pip install -r requirements.txt`
3. Create a `.env` file (or use the in-app Settings dialog) with:
   - `MONGO_URI` — your MongoDB Atlas connection string
   - Gmail sender email + App Password (not your regular Gmail password — generate one at myaccount.google.com → Security → App Passwords)
   - (Optional) `ANTHROPIC_API_KEY` — only needed if `AI_FEATURES_ENABLED = True` in `config.py`
4. Run the main app: `python3 main.py`
5. Run the admin panel (separately, as needed): `python3 run_admin.py`

### 10.3 First-Time Admin Setup

Before any doctor can log in, an administrator must add their Doctor ID + email via the Admin Panel's Doctors tab (email-verified via OTP). Patients require no pre-approval — they self-register on first login.

---

*End of documentation.*
