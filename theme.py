from PyQt6.QtWidgets import (
    QPushButton, QLineEdit, QFrame, QGroupBox, QLabel,
    QTextEdit, QProgressBar, QListWidget, QWidget,
    QHBoxLayout, QVBoxLayout,
)
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui  import QPainter, QColor, QFont, QPen, QBrush

from config import (
    BG, SURF, SURF2, SURF3, BORDER,
    BLUE, CYAN, RED, GREEN, AMBER, TEXT, DIM, DIM2,
    LOG_BG, LOG_FG, BEVEL_LT, BEVEL_DK,
)

# ── Design constants ─────────────────────────────────────────────────────────
# Classic native-app metrics: small, consistent corner radii (never pill-
# shaped), square data surfaces, gradient bevels on anything clickable.
BTN_H    = 26
INP_H    = 24
RADIUS   = 3
R_SMALL  = 2
CARD_PAD = (14, 12, 14, 12)

# ── UI helpers ─────────────────────────────────────────────────────────────────

def _ss(widget, css): widget.setStyleSheet(css); return widget

def _lighten(hex_color, amount=0.35):
    """Blend a #rrggbb color toward white by `amount` (0-1)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    r = round(r + (255 - r) * amount)
    g = round(g + (255 - g) * amount)
    b = round(b + (255 - b) * amount)
    return f"#{r:02x}{g:02x}{b:02x}"

def _darken(hex_color, amount=0.30):
    """Blend a #rrggbb color toward black by `amount` (0-1)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    r = round(r * (1 - amount))
    g = round(g * (1 - amount))
    b = round(b * (1 - amount))
    return f"#{r:02x}{g:02x}{b:02x}"

def mkbtn(text, color=BLUE, h=BTN_H, wide=False):
    """Raised, gradient-bevel button — like a classic Windows/macOS default button."""
    b = QPushButton(text); b.setFixedHeight(h)
    if wide: b.setMinimumWidth(180)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    top, bot   = _lighten(color, 0.10), _darken(color, 0.08)
    hov_top, hov_bot = _lighten(color, 0.18), _darken(color, 0.02)
    prs_top, prs_bot = _darken(color, 0.04), _darken(color, 0.14)
    b.setStyleSheet(f"""
        QPushButton{{
            background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {top},stop:1 {bot});
            color:white;border:1px solid {_darken(color,0.18)};
            border-radius:{R_SMALL}px;font-size:12px;font-weight:600;
            padding:0 18px;letter-spacing:0.1px;
        }}
        QPushButton:hover{{
            background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {hov_top},stop:1 {hov_bot});
        }}
        QPushButton:pressed{{
            background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {prs_top},stop:1 {prs_bot});
            padding-top:1px;
        }}
        QPushButton:disabled{{
            background:{SURF2};color:{DIM};border:1px solid {BORDER};
        }}
    """); return b

def mkbtn_ghost(text, color=DIM, h=BTN_H):
    """Flat outline button — like a secondary/Cancel button in a system dialog."""
    b = QPushButton(text); b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"""
        QPushButton{{
            background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {SURF},stop:1 {SURF3});
            color:{color};border:1px solid {BORDER};border-radius:{R_SMALL}px;
            font-size:12px;font-weight:600;padding:0 14px;
        }}
        QPushButton:hover{{border-color:{color};color:{TEXT};}}
        QPushButton:pressed{{background:{SURF3};padding-top:1px;}}
        QPushButton:disabled{{color:{BORDER};border-color:{BORDER};}}
    """); return b

def mkbtn_outline(text, color=BLUE, h=BTN_H):
    return mkbtn_ghost(text, color, h)

def mkinp(ph="", pw=False, mono=False, h=INP_H):
    """Sunken input well — inset border like a classic system text field."""
    e = QLineEdit(); e.setPlaceholderText(ph); e.setFixedHeight(h)
    if pw: e.setEchoMode(QLineEdit.EchoMode.Password)
    if mono:
        e.setStyleSheet(f"""
            QLineEdit{{
                background:{LOG_BG};color:{GREEN};
                border:1.5px solid {_darken(LOG_BG,0.2)};
                border-top-color:{_darken(LOG_BG,0.3)};border-left-color:{_darken(LOG_BG,0.3)};
                border-radius:{R_SMALL}px;
                padding:0 16px;font-size:20px;font-weight:900;
                font-family:'Courier New',monospace;letter-spacing:9px;
            }}
            QLineEdit:focus{{border:1.5px solid {CYAN};}}
        """)
    else:
        e.setStyleSheet(f"""
            QLineEdit{{
                background:{SURF2};color:{TEXT};
                border:1px solid {BORDER};
                border-top-color:{_darken(BORDER,0.12)};
                border-left-color:{_darken(BORDER,0.12)};
                border-radius:{R_SMALL}px;
                padding:0 10px;font-size:12.5px;
            }}
            QLineEdit:focus{{border:1px solid {BLUE};background:#ffffff;}}
            QLineEdit:hover{{border-color:{DIM2};}}
            QLineEdit:disabled{{background:{SURF};color:{DIM};}}
        """)
    return e

def mkcard(accent=None, pad=CARD_PAD, radius=RADIUS):
    """Raised panel — light top/left edge, dark bottom/right edge (classic bevel)."""
    f = QFrame()
    bc = accent if accent else BORDER
    f.setStyleSheet(f"""
        QFrame{{
            background:{SURF};border-radius:{radius}px;
            border:1px solid {bc};
            border-top-color:{BEVEL_LT if not accent else bc};
            border-left-color:{BEVEL_LT if not accent else bc};
            border-bottom-color:{BEVEL_DK if not accent else bc};
            border-right-color:{BEVEL_DK if not accent else bc};
        }}
    """)
    lay = QVBoxLayout(f); lay.setContentsMargins(*pad); lay.setSpacing(9)
    return f, lay

def mkgrp(title, accent=BLUE):
    """Etched group box — sunken frame with a system-style caption, like a
    classic 'Options' or 'Properties' box."""
    g = QGroupBox(title)
    g.setStyleSheet(f"""
        QGroupBox{{
            color:{DIM2};border:1px solid {_darken(BORDER,0.15)};
            border-top-color:{_darken(BORDER,0.2)};
            border-left-color:{_darken(BORDER,0.2)};
            border-bottom-color:{BEVEL_LT};border-right-color:{BEVEL_LT};
            border-radius:{RADIUS}px;margin-top:16px;
            font-size:11px;font-weight:700;letter-spacing:0.4px;
            padding:16px 12px 12px 12px;background:{SURF};
        }}
        QGroupBox::title{{
            subcontrol-origin:margin;left:12px;top:-1px;
            padding:1px 6px;color:{accent};background:{SURF};
        }}
    """); return g

def mklbl(text, color=DIM2, size=12, bold=False):
    l = QLabel(text)
    w = 700 if bold else 500
    l.setStyleSheet(f"color:{color};font-size:{size}px;font-weight:{w};"); return l

def mkbadge(text, color=BLUE, small=False):
    """Square-cornered status chip — like a classic toolbar indicator, not a
    modern pill."""
    l = QLabel(text); sz = 10 if small else 11
    l.setStyleSheet(
        f"background:{color}20;color:{color};"
        f"border:1px solid {color}70;border-radius:2px;"
        f"padding:2px 8px;font-size:{sz}px;font-weight:700;"); return l

def mklog(h=200):
    t = QTextEdit(); t.setReadOnly(True)
    t.setMinimumHeight(h); t.setMaximumHeight(h)
    t.setStyleSheet(f"""
        QTextEdit{{
            background:{LOG_BG};color:{LOG_FG};
            border:1.5px solid {_darken(LOG_BG,0.15)};
            border-top-color:{_darken(LOG_BG,0.25)};border-left-color:{_darken(LOG_BG,0.25)};
            border-bottom-color:{_lighten(LOG_BG,0.15)};
            border-right-color:{_lighten(LOG_BG,0.15)};
            border-radius:{R_SMALL}px;
            font-family:'Courier New',monospace;font-size:11.5px;
            padding:9px 11px;line-height:1.55;
        }}
    """); return t

def mkimg(size=252, label="No image"):
    l = QLabel(label); l.setFixedSize(size, size)
    l.setAlignment(Qt.AlignmentFlag.AlignCenter); l.setWordWrap(True)
    l.setStyleSheet(
        f"background:{SURF2};border:1px dashed {BORDER};"
        f"border-radius:{R_SMALL}px;color:{DIM};font-size:11px;"); return l

def mkprog(color=BLUE, h=14):
    """Segmented-look progress bar — square ends, visible sunken track."""
    p = QProgressBar(); p.setFixedHeight(h); p.setValue(0)
    p.setTextVisible(False)
    p.setStyleSheet(f"""
        QProgressBar{{
            background:{SURF2};border:1px solid {_darken(BORDER,0.12)};
            border-radius:{R_SMALL}px;
        }}
        QProgressBar::chunk{{
            background:qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {_lighten(color,0.12)},stop:0.5 {color},stop:1 {_darken(color,0.08)});
            border-radius:1px;margin:1px;
        }}
    """); return p

def mksep(vertical=False):
    """Etched separator — two-tone line, like a classic 3D groove."""
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine if vertical else QFrame.Shape.HLine)
    f.setStyleSheet(
        f"border:none;background:{_darken(BORDER,0.1)};")
    if not vertical: f.setMaximumHeight(1)
    else: f.setMaximumWidth(1)
    return f

def mkdivider(label="", color=BORDER):
    """Labelled divider line."""
    row = QHBoxLayout(); row.setSpacing(8)
    row.addWidget(mksep())
    if label:
        l = QLabel(label)
        l.setStyleSheet(f"color:{DIM};font-size:10px;letter-spacing:1px;")
        row.addWidget(l)
        row.addWidget(mksep())
    w = QWidget(); w.setLayout(row); w.setStyleSheet("background:transparent;")
    return w

def mksection_header(text, color=TEXT, icon=""):
    row = QWidget(); row.setStyleSheet("background:transparent;")
    lay = QHBoxLayout(row); lay.setContentsMargins(0, 4, 0, 2); lay.setSpacing(8)
    bar = QLabel(); bar.setFixedSize(3, 15)
    bar.setStyleSheet(f"background:{color};border-radius:0px;")
    lay.addWidget(bar)
    txt = f"{icon}  {text}" if icon else text
    lbl = QLabel(txt)
    lbl.setStyleSheet(f"color:{color};font-size:12px;font-weight:700;")
    lay.addWidget(lbl); lay.addStretch(); return row

def mkstatcard(label, value="—", unit="", color=BLUE):
    """Compact metric card."""
    f, lay = mkcard(accent=color, pad=(12, 9, 12, 9))
    t = QLabel(label.upper())
    t.setStyleSheet(f"color:{color};font-size:9px;font-weight:700;letter-spacing:1.2px;")
    v = QLabel(value)
    v.setStyleSheet(f"color:{TEXT};font-size:21px;font-weight:800;")
    u = QLabel(unit)
    u.setStyleSheet(f"color:{DIM};font-size:10px;")
    t.setAlignment(Qt.AlignmentFlag.AlignCenter)
    v.setAlignment(Qt.AlignmentFlag.AlignCenter)
    u.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(t); lay.addWidget(v); lay.addWidget(u)
    return f, v   # return frame + value label for updates

def mkstep_badge(n, color=BLUE):
    """Numbered step marker — square-ish with a slight bevel, not a full circle."""
    l = QLabel(str(n)); l.setFixedSize(24, 24)
    l.setAlignment(Qt.AlignmentFlag.AlignCenter)
    l.setStyleSheet(
        f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {_lighten(color,0.1)},stop:1 {_darken(color,0.08)});"
        f"color:white;border:1px solid {_darken(color,0.18)};border-radius:4px;"
        f"font-size:12px;font-weight:800;"); return l


class BarChart(QWidget):
    """
    Lightweight bar chart drawn with QPainter — no plotting dependency.
    Supports a single series (one bar per category) or two grouped series
    (e.g. Previous vs Current phase, side-by-side bars per category).
    """
    def __init__(self, height=140, unit="", parent=None):
        super().__init__(parent)
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        self._unit = unit
        self._categories = []
        self._series = []   # list of {"name": str, "color": "#hex", "values": [float,...]}

    def set_data(self, bars):
        """bars: list of (label, value, color_hex) — single-series chart."""
        self._categories = [b[0] for b in bars]
        self._series = [{"name": None, "color": None,
                          "values": [b[1] for b in bars],
                          "colors": [b[2] for b in bars]}]
        self.update()

    def set_grouped(self, categories, series):
        """
        categories: list[str]
        series: list of {"name": str, "color": "#hex", "values": list[float]}
                (values aligned to categories, same length)
        """
        self._categories = categories
        self._series = series
        self.update()

    def clear(self):
        self._categories = []; self._series = []; self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if not self._categories or not self._series:
            p.setPen(QColor(DIM))
            p.setFont(QFont("Helvetica Neue", 10))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "No data yet")
            p.end(); return

        pad_top, pad_bottom, pad_side = 22, 28, 12
        plot_h = h - pad_top - pad_bottom
        plot_w = w - pad_side * 2
        n_cat = len(self._categories)
        n_series = len(self._series)

        all_vals = [v for s in self._series for v in s["values"]]
        max_val = max(all_vals) if all_vals and max(all_vals) > 0 else 1.0

        group_w = plot_w / n_cat
        bar_gap = 4
        bar_w = (group_w - bar_gap * (n_series + 1)) / n_series

        p.setPen(QColor(DIM))
        p.setFont(QFont("Helvetica Neue", 8))

        for ci, cat in enumerate(self._categories):
            gx = pad_side + ci * group_w
            for si, s in enumerate(self._series):
                val = s["values"][ci]
                color = s["colors"][ci] if "colors" in s else s["color"]
                bar_h = (val / max_val) * plot_h if max_val else 0
                bx = gx + bar_gap + si * (bar_w + bar_gap)
                by = pad_top + (plot_h - bar_h)
                p.setBrush(QBrush(QColor(color)))
                p.setPen(QPen(QColor(_darken_hex(color)), 1))
                p.drawRoundedRect(QRectF(bx, by, bar_w, bar_h), 2, 2)
                # Value label above the bar
                p.setPen(QColor(TEXT))
                p.setFont(QFont("Helvetica Neue", 8, QFont.Weight.Bold))
                val_txt = f"{val:.0f}" if val >= 10 else f"{val:.1f}"
                p.drawText(QRectF(bx - 6, by - 15, bar_w + 12, 14),
                           Qt.AlignmentFlag.AlignCenter, val_txt)
            # Category label
            p.setPen(QColor(DIM))
            p.setFont(QFont("Helvetica Neue", 8))
            p.drawText(QRectF(gx, h - pad_bottom + 4, group_w, 14),
                       Qt.AlignmentFlag.AlignCenter, cat)

        # Legend (only for grouped/multi-series charts)
        if n_series > 1:
            lx = pad_side
            p.setFont(QFont("Helvetica Neue", 7.5))
            for s in self._series:
                p.setBrush(QBrush(QColor(s["color"])))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRect(QRectF(lx, 2, 8, 8))
                p.setPen(QColor(DIM))
                p.drawText(QRectF(lx + 11, 0, 90, 12), Qt.AlignmentFlag.AlignVCenter, s["name"])
                lx += 11 + p.fontMetrics().horizontalAdvance(s["name"]) + 14
        p.end()


def _darken_hex(hex_color, amount=0.25):
    return _darken(hex_color, amount)


# ── Doctor panel ──────────────────────────────────────────────────────────────
