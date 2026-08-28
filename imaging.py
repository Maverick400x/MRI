import numpy as np
from PIL import Image
from PyQt6.QtGui  import QPixmap, QImage

from config import PIXEL_SPACING, TUMOR_COLORS

# ── Modality / quality checks ─────────────────────────────────────────────────
# NOTE: these are lightweight pixel-statistics heuristics, not a trained
# classifier — the same "simulated" spirit as simulate_segmentation() below.
# They catch obviously-wrong uploads (color photos, high-contrast X-rays,
# CT's circular gantry field-of-view) but are not a diagnostic tool.

def assess_scan_modality(path: str) -> dict:
    """
    Heuristic check of what kind of image was uploaded. Returns
    {"modality": "mri"|"xray"|"ct"|"photo"|"unknown", "confidence": 0-1, "reason": str}

    This is pixel-statistics screening, not a trained classifier — same
    "simulated" spirit as simulate_segmentation() below. It reliably catches
    color photos, and flags likely X-ray (stark black/white, no soft-tissue
    gradation) and CT (a hard circular gantry-vignette cutoff, sampled as an
    abrupt step in a ring near the image edge) — but it can be wrong on
    unusual images, so callers should let the doctor confirm/override rather
    than silently discard files.
    """
    try:
        pil = Image.open(path)
        pil.seek(0)   # first frame if animated
        rgb = np.array(pil.convert("RGB"), dtype=np.float32)
    except Exception as e:
        return {"modality": "unknown", "confidence": 0.0,
                "reason": f"Couldn't read the image ({e})."}

    # ── Photo check — real photos have meaningfully different R/G/B channels
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    channel_spread = float(np.mean(np.abs(r-g)) + np.mean(np.abs(g-b)) + np.mean(np.abs(r-b))) / 3
    if channel_spread > 8:
        return {"modality": "photo",
                "confidence": min(0.95, channel_spread / 40),
                "reason": "This looks like a color photo, not a grayscale medical scan."}

    gray = np.array(pil.convert("L"), dtype=np.float32)
    h, w = gray.shape
    norm = gray / 255.0

    # Extreme-value fraction — X-rays are strongly bimodal: near-black
    # background/soft-tissue with stark white bone, little in between.
    extreme_frac = float(np.mean((norm < 0.06) | (norm > 0.92)))
    midtone_frac = float(np.mean((norm > 0.15) & (norm < 0.85)))

    # CT check — sample a ring of points near the image edge at two close
    # radii. A genuine CT gantry vignette crops to a circle with an abrupt
    # step (dark just outside, bright just inside); an MRI's background
    # fades gradually with anatomy, not as a hard geometric cutoff.
    cy, cx = h / 2, w / 2
    ang = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    def _ring_mean(rad):
        ys = np.clip((cy + rad * np.sin(ang)).astype(int), 0, h - 1)
        xs = np.clip((cx + rad * np.cos(ang)).astype(int), 0, w - 1)
        return float(gray[ys, xs].mean())
    r_out, r_in = 0.49 * min(h, w), 0.42 * min(h, w)
    outer_mean, inner_mean = _ring_mean(r_out), _ring_mean(r_in)
    step = inner_mean - outer_mean

    if outer_mean < 12 and step > 60:
        return {"modality": "ct", "confidence": min(1.0, step / 120),
                "reason": "A sharp circular field-of-view cutoff near the "
                          "image edge looks like a CT gantry vignette, not an MRI."}
    if extreme_frac > 0.6 and midtone_frac < 0.2:
        return {"modality": "xray", "confidence": extreme_frac,
                "reason": "High black/white contrast with little soft-tissue "
                          "gradation looks like an X-ray, not an MRI."}

    return {"modality": "mri", "confidence": max(0.4, midtone_frac),
            "reason": "Grayscale image with soft-tissue gradation, "
                      "consistent with an MRI slice."}


def analyze_scan_quality(arr) -> dict:
    """
    Basic normalization / density / noise readout for the uploaded slice —
    shown in Step 1 right after upload, before segmentation runs. Also flags
    three common MRI-quality issues: low tissue contrast, fuzzy borders
    (blur), and shifting intensity levels (non-uniform bias-field-like
    brightness across the slice) — same pixel-statistics-heuristic spirit
    as the rest of this module, not a diagnostic measurement.
    """
    gray = arr.astype(np.float32)
    orig_min, orig_max = float(gray.min()), float(gray.max())
    norm = gray / 255.0 if gray.max() > 1 else gray.copy()
    mean_norm = float(norm.mean())
    h, w = norm.shape

    # Density — share of pixels that are actual tissue (not black background).
    tissue_mask = norm > 0.08
    density_pct = float(np.mean(tissue_mask)) * 100

    # Noise — std-dev of a simple high-frequency residual (image minus a
    # 3x3 box-blur of itself); higher residual energy ≈ noisier image.
    pad = np.pad(norm, 1, mode="edge")
    smooth = sum(
        pad[i:i + norm.shape[0], j:j + norm.shape[1]]
        for i in range(3) for j in range(3)
    ) / 9.0
    residual = norm - smooth
    noise_val = float(residual.std())
    if noise_val < 0.015:
        noise_label = "Low"
    elif noise_val < 0.035:
        noise_label = "Moderate"
    else:
        noise_label = "High"

    # Tissue contrast — RMS (std-dev) spread of intensities within the
    # tissue region only. Low spread means the tissue reads as flat/washed
    # out, with little separation between structures.
    tissue_px = norm[tissue_mask] if tissue_mask.any() else norm.ravel()
    contrast_val = float(tissue_px.std())
    if contrast_val < 0.12:
        contrast_label = "Low"
    elif contrast_val < 0.22:
        contrast_label = "Moderate"
    else:
        contrast_label = "Good"

    # Border sharpness / fuzziness — variance of a discrete Laplacian.
    # Sharp, well-defined boundaries produce a high-variance Laplacian;
    # blurry, fuzzy borders produce a low-variance one (a standard
    # no-reference blur metric).
    up    = pad[0:h,   1:w+1]
    down  = pad[2:h+2, 1:w+1]
    left  = pad[1:h+1, 0:w]
    right = pad[1:h+1, 2:w+2]
    laplacian = (up + down + left + right - 4 * norm)
    edge_var = float(laplacian.var())
    if edge_var < 0.0008:
        border_label = "Fuzzy"
    elif edge_var < 0.003:
        border_label = "Moderate"
    else:
        border_label = "Sharp"

    # Shifting intensity levels — split the slice into a 2x2 grid and
    # compare mean brightness across quadrants. A big spread suggests
    # non-uniform illumination/intensity drift across the slice (a common
    # MRI bias-field artifact), rather than a stable, even scan.
    hh, hw = h // 2, w // 2
    quads = [norm[:hh, :hw], norm[:hh, hw:], norm[hh:, :hw], norm[hh:, hw:]]
    quad_means = [float(q.mean()) for q in quads if q.size]
    intensity_shift = float(max(quad_means) - min(quad_means)) if quad_means else 0.0
    if intensity_shift < 0.08:
        shift_label = "Stable"
    elif intensity_shift < 0.18:
        shift_label = "Moderate shift"
    else:
        shift_label = "High shift"

    return {
        "orig_range":     f"{orig_min:.0f}–{orig_max:.0f}",
        "norm_mean":      mean_norm,
        "density_pct":    density_pct,
        "noise_val":      noise_val,
        "noise_label":    noise_label,
        "contrast_val":   contrast_val,
        "contrast_label": contrast_label,
        "edge_var":       edge_var,
        "border_label":   border_label,
        "intensity_shift": intensity_shift,
        "shift_label":    shift_label,
    }


def assess_risk_level(areas: dict) -> dict:
    """
    Preliminary, heuristic risk band from segmented region sizes — total
    tumor burden plus necrotic-tissue proportion (a rough proxy for
    aggressiveness). This is an automated estimate to flag for review, NOT
    a diagnosis — always requires radiologist confirmation.
    """
    total = sum(areas.values())
    necrotic_pct = (areas.get("Necrotic", 0) / total * 100) if total else 0.0

    if total < 200:
        level, color = "Minimal", "GREEN"
    elif total < 800:
        level, color = "Low", "CYAN"
    elif total < 2000:
        level, color = "Moderate", "AMBER"
    elif total < 5000:
        level, color = "High", "RED"
    else:
        level, color = "Critical", "RED"

    # Bump one band up if necrotic tissue makes up a large share — necrosis
    # is generally associated with more aggressive lesions.
    bands = ["Minimal", "Low", "Moderate", "High", "Critical"]
    colors = ["GREEN", "CYAN", "AMBER", "RED", "RED"]
    if necrotic_pct > 30 and level != "Critical":
        idx = min(bands.index(level) + 1, len(bands) - 1)
        level, color = bands[idx], colors[idx]

    return {
        "level": level,
        "color": color,
        "total_area": total,
        "necrotic_pct": necrotic_pct,
        "note": "Automated preliminary indicator based on segmented area — "
                "requires radiologist confirmation, not a diagnosis.",
    }


# ── Image helpers ─────────────────────────────────────────────────────────────
def simulate_segmentation(arr):
    gray = arr.astype(np.float32)
    if gray.max() > 1: gray /= 255.0
    h, w = gray.shape
    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt((X - w//2)**2 + (Y - h//2)**2)
    masks = {
        "Enhancing": (gray > 0.75).astype(np.uint8),
        "Necrotic":  ((gray > 0.55) & (gray <= 0.75) & (dist < min(h,w)*0.25)).astype(np.uint8),
        "Edema":     ((gray > 0.40) & (gray <= 0.60) & (dist < min(h,w)*0.40)).astype(np.uint8),
    }
    areas = {n: round(int(m.sum()) * PIXEL_SPACING**2, 2) for n, m in masks.items()}
    return {"masks": masks, "areas": areas}

def overlay_array(arr, seg):
    """
    Returns the raw uint8 RGB (H, W, 3) array with tumor sub-region masks
    painted on top of the MRI slice — the deterministic "where is the
    tumor" visualization, computed straight from the segmentation masks
    (not guessed by any AI model). Used both for the on-screen preview
    (via overlay_pixmap) and for embedding in the PDF report.
    """
    rgb = np.stack([arr]*3, axis=-1) if arr.ndim == 2 else arr[:,:,:3].copy()
    if rgb.max() <= 1.0: rgb = (rgb*255).astype(np.uint8)
    out = rgb.astype(np.float32)
    for name, mask in seg["masks"].items():
        if mask.sum() == 0: continue
        r, g, b, a = TUMOR_COLORS[name]
        alpha = a / 255.0
        for ch, val in enumerate((r, g, b)):
            out[:,:,ch] = np.where(mask>0, out[:,:,ch]*(1-alpha)+val*alpha, out[:,:,ch])
    return np.clip(out, 0, 255).astype(np.uint8)

def overlay_pixmap(arr, seg):
    out = overlay_array(arr, seg)
    h, w, _ = out.shape
    return QPixmap.fromImage(QImage(out.data, w, h, 3*w, QImage.Format.Format_RGB888))

def arr_to_pixmap(arr):
    if arr.ndim == 2: arr = np.stack([arr]*3, axis=-1)
    if arr.max() <= 1.0: arr = (arr*255).astype(np.uint8)
    else: arr = arr.astype(np.uint8)
    h, w, _ = arr.shape
    return QPixmap.fromImage(QImage(arr.data, w, h, 3*w, QImage.Format.Format_RGB888))


# ── Worker threads ────────────────────────────────────────────────────────────