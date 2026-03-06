"""
BinanceML Pro – Futuristic Trading Desk Theme
Inspired by sci-fi trading terminals, Bloomberg dark, and neon-noir aesthetics.
"""

# ── Core palette ──────────────────────────────────────────────────────────────

ACCENT  = "#00D4FF"      # Electric cyan – primary accent
ACCENT2 = "#7B2FFF"      # Violet – secondary accent
GREEN   = "#00E676"      # Profit / buy
GREEN2  = "#00BFA5"      # Teal green variant
RED     = "#FF1744"      # Loss / sell
ORANGE  = "#FF6D00"      # Warning
YELLOW  = "#FFD740"      # Caution / neutral
PURPLE  = "#AA00FF"      # ML / AI

BG0    = "#05050F"       # Void black – deepest background
BG1    = "#080812"       # Main background
BG2    = "#0C0C1E"       # Panel background
BG3    = "#111128"       # Card / widget background
BG4    = "#181830"       # Input / table row alt
BG5    = "#1E1E3A"       # Elevated surface

BORDER  = "#1E1E3C"      # Standard border
BORDER2 = "#2A2A50"      # Highlighted border
GLOW    = "#00D4FF33"    # Accent glow (transparent)

FG0 = "#E8E8FF"          # Primary text (slightly blue-white)
FG1 = "#8888AA"          # Secondary text
FG2 = "#44446A"          # Disabled / placeholder text
FG3 = "#BBBBDD"          # Sub-primary text

# ── Derived helpers ───────────────────────────────────────────────────────────

def hex_alpha(color: str, alpha: int) -> str:
    """Append 2-digit hex alpha to a #RRGGBB color."""
    return f"{color}{alpha:02X}"


# ── Full stylesheet ───────────────────────────────────────────────────────────

DARK_THEME = f"""
/* ══════════════════════════════════════════════════════════════════════
   GLOBAL
   ══════════════════════════════════════════════════════════════════════ */
* {{
    outline: none;
}}
QWidget {{
    background-color: {BG1};
    color: {FG0};
    font-family: "JetBrains Mono", "SF Mono", "Fira Code", "Cascadia Code",
                 "Consolas", "Courier New", monospace;
    font-size: 12px;
}}
QMainWindow {{
    background-color: {BG0};
}}
QDialog {{
    background-color: {BG2};
    border: 1px solid {BORDER2};
    border-radius: 10px;
}}

/* ══════════════════════════════════════════════════════════════════════
   MENU BAR
   ══════════════════════════════════════════════════════════════════════ */
QMenuBar {{
    background-color: {BG0};
    color: {FG1};
    border-bottom: 1px solid {BORDER};
    padding: 2px 8px;
    font-size: 12px;
    spacing: 2px;
}}
QMenuBar::item {{
    padding: 4px 10px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background-color: {GLOW};
    color: {ACCENT};
    border: 1px solid {BORDER2};
}}
QMenu {{
    background-color: {BG3};
    color: {FG0};
    border: 1px solid {BORDER2};
    border-radius: 8px;
    padding: 6px 4px;
    font-size: 12px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
    margin: 1px 4px;
}}
QMenu::item:selected {{
    background-color: {GLOW};
    color: {ACCENT};
    border-left: 2px solid {ACCENT};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 12px;
}}
QMenu::icon {{
    padding-left: 8px;
}}

/* ══════════════════════════════════════════════════════════════════════
   TOOLBAR
   ══════════════════════════════════════════════════════════════════════ */
QToolBar {{
    background-color: {BG0};
    border: none;
    padding: 0px;
    spacing: 0px;
}}
QToolBar::separator {{
    background: {BORDER};
    width: 1px;
    margin: 6px 4px;
}}

/* ══════════════════════════════════════════════════════════════════════
   TAB BAR
   ══════════════════════════════════════════════════════════════════════ */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {BG2};
    border-radius: 0px 8px 8px 8px;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background-color: {BG3};
    color: {FG2};
    padding: 7px 18px;
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QTabBar::tab:selected {{
    background-color: {BG2};
    color: {ACCENT};
    border-color: {BORDER2};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    background-color: {BG4};
    color: {FG1};
    border-color: {BORDER2};
}}

/* ══════════════════════════════════════════════════════════════════════
   SPLITTER
   ══════════════════════════════════════════════════════════════════════ */
QSplitter::handle {{
    background-color: {BORDER};
}}
QSplitter::handle:horizontal {{
    width: 1px;
    margin: 0px;
}}
QSplitter::handle:vertical {{
    height: 1px;
    margin: 0px;
}}
QSplitter::handle:hover {{
    background-color: {ACCENT};
}}

/* ══════════════════════════════════════════════════════════════════════
   SCROLL BARS
   ══════════════════════════════════════════════════════════════════════ */
QScrollBar:vertical {{
    background: {BG0};
    width: 6px;
    border-radius: 3px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {BG5};
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT}88;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {BG0};
    height: 6px;
    border-radius: 3px;
    margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: {BG5};
    border-radius: 3px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {ACCENT}88;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ══════════════════════════════════════════════════════════════════════
   BUTTONS
   ══════════════════════════════════════════════════════════════════════ */
QPushButton {{
    background-color: {BG4};
    color: {FG1};
    border: 1px solid {BORDER2};
    border-radius: 5px;
    padding: 7px 16px;
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 0.5px;
}}
QPushButton:hover {{
    background-color: {GLOW};
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:pressed {{
    background-color: {ACCENT}22;
    border-color: {ACCENT};
}}
QPushButton:disabled {{
    color: {FG2};
    border-color: {BORDER};
    background-color: {BG2};
}}

/* Named button variants */
QPushButton#btn_buy {{
    background-color: {GREEN}18;
    border: 1px solid {GREEN}88;
    color: {GREEN};
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 1px;
}}
QPushButton#btn_buy:hover {{
    background-color: {GREEN}33;
    border-color: {GREEN};
}}
QPushButton#btn_sell {{
    background-color: {RED}18;
    border: 1px solid {RED}88;
    color: {RED};
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 1px;
}}
QPushButton#btn_sell:hover {{
    background-color: {RED}33;
    border-color: {RED};
}}
QPushButton#btn_cancel {{
    background-color: {ORANGE}15;
    border-color: {ORANGE}88;
    color: {ORANGE};
}}
QPushButton#btn_primary {{
    background-color: {ACCENT}20;
    border: 1px solid {ACCENT}88;
    color: {ACCENT};
    font-weight: 700;
    letter-spacing: 0.8px;
}}
QPushButton#btn_primary:hover {{
    background-color: {ACCENT}40;
    border-color: {ACCENT};
}}
QPushButton#btn_danger {{
    background-color: {RED}18;
    border-color: {RED}88;
    color: {RED};
}}
QPushButton#btn_danger:hover {{
    background-color: {RED}33;
}}
QPushButton#nav_btn {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {FG2};
    font-size: 10px;
    font-weight: 600;
    text-align: center;
    padding: 10px 4px;
    letter-spacing: 0.5px;
}}
QPushButton#nav_btn:hover {{
    background: {GLOW};
    color: {FG1};
}}
QPushButton#nav_btn[active="true"] {{
    background: {ACCENT}18;
    color: {ACCENT};
    border-left: 2px solid {ACCENT};
    border-radius: 0px 8px 8px 0px;
}}

/* ══════════════════════════════════════════════════════════════════════
   INPUTS
   ══════════════════════════════════════════════════════════════════════ */
QLineEdit, QDoubleSpinBox, QSpinBox, QTextEdit, QPlainTextEdit {{
    background-color: {BG3};
    color: {FG0};
    border: 1px solid {BORDER2};
    border-radius: 5px;
    padding: 6px 10px;
    selection-background-color: {ACCENT}44;
    font-family: "JetBrains Mono", "SF Mono", "Fira Code", monospace;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
    background-color: {BG4};
}}
QLineEdit:read-only {{
    color: {FG1};
    background-color: {BG2};
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button {{
    background: {BG5};
    border: none;
    width: 16px;
}}
QComboBox {{
    background-color: {BG3};
    color: {FG0};
    border: 1px solid {BORDER2};
    border-radius: 5px;
    padding: 6px 10px;
    font-size: 12px;
}}
QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
    background: transparent;
}}
QComboBox::down-arrow {{
    width: 10px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG3};
    color: {FG0};
    border: 1px solid {BORDER2};
    border-radius: 6px;
    selection-background-color: {ACCENT}22;
    selection-color: {ACCENT};
    padding: 4px;
}}

/* ══════════════════════════════════════════════════════════════════════
   SLIDER
   ══════════════════════════════════════════════════════════════════════ */
QSlider::groove:horizontal {{
    background: {BG5};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    border: 2px solid {BG3};
}}
QSlider::handle:horizontal:hover {{
    background: {FG0};
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT2}99, stop:1 {ACCENT});
    border-radius: 2px;
}}

/* ══════════════════════════════════════════════════════════════════════
   TABLES
   ══════════════════════════════════════════════════════════════════════ */
QTableWidget, QTableView {{
    background-color: {BG2};
    color: {FG0};
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-size: 11px;
    font-family: "JetBrains Mono", "SF Mono", monospace;
    alternate-background-color: {BG3};
}}
QTableWidget::item, QTableView::item {{
    padding: 4px 8px;
    border: none;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {ACCENT}18;
    color: {ACCENT};
}}
QHeaderView::section {{
    background-color: {BG0};
    color: {FG2};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
    padding: 5px 8px;
    font-weight: 700;
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QHeaderView::section:first {{
    border-left: none;
}}

/* ══════════════════════════════════════════════════════════════════════
   LABELS (named)
   ══════════════════════════════════════════════════════════════════════ */
QLabel#label_price {{
    font-size: 26px;
    font-weight: 700;
    color: {FG0};
    font-family: "JetBrains Mono", monospace;
    letter-spacing: -0.5px;
}}
QLabel#label_change_pos {{
    font-size: 14px;
    font-weight: 600;
    color: {GREEN};
}}
QLabel#label_change_neg {{
    font-size: 14px;
    font-weight: 600;
    color: {RED};
}}
QLabel#label_section {{
    font-size: 9px;
    font-weight: 700;
    color: {FG2};
    letter-spacing: 2px;
    text-transform: uppercase;
}}
QLabel#label_value_green  {{ color: {GREEN};  font-weight: 600; }}
QLabel#label_value_red    {{ color: {RED};    font-weight: 600; }}
QLabel#label_value_yellow {{ color: {YELLOW}; font-weight: 600; }}
QLabel#label_accent       {{ color: {ACCENT}; font-weight: 700; }}
QLabel#label_muted        {{ color: {FG2};    font-size: 11px;  }}

/* ══════════════════════════════════════════════════════════════════════
   GROUP BOXES
   ══════════════════════════════════════════════════════════════════════ */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 18px;
    padding: 14px 10px 10px;
    font-weight: 600;
    color: {FG1};
    background-color: {BG2};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: -9px;
    padding: 1px 8px;
    background-color: {BG2};
    color: {ACCENT};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    border: 1px solid {BORDER};
    border-radius: 4px;
}}

/* ══════════════════════════════════════════════════════════════════════
   PROGRESS BAR
   ══════════════════════════════════════════════════════════════════════ */
QProgressBar {{
    background-color: {BG4};
    border: 1px solid {BORDER};
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: transparent;
    font-size: 10px;
}}
QProgressBar::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT2}, stop:0.5 {ACCENT}, stop:1 {GREEN}
    );
    border-radius: 4px;
}}

/* ══════════════════════════════════════════════════════════════════════
   CHECKBOXES & RADIO
   ══════════════════════════════════════════════════════════════════════ */
QCheckBox {{
    color: {FG0};
    spacing: 8px;
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {BORDER2};
    background: {BG4};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
QRadioButton {{
    color: {FG0};
    spacing: 8px;
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 7px;
    border: 1px solid {BORDER2};
    background: {BG4};
}}
QRadioButton::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* ══════════════════════════════════════════════════════════════════════
   STATUS BAR
   ══════════════════════════════════════════════════════════════════════ */
QStatusBar {{
    background-color: {BG0};
    color: {FG2};
    border-top: 1px solid {BORDER};
    font-size: 10px;
    font-family: "JetBrains Mono", monospace;
    letter-spacing: 0.3px;
}}
QStatusBar::item {{
    border: none;
}}

/* ══════════════════════════════════════════════════════════════════════
   DOCK WIDGETS
   ══════════════════════════════════════════════════════════════════════ */
QDockWidget {{
    color: {FG1};
    font-weight: 600;
    font-size: 11px;
    titlebar-close-icon: url(none);
}}
QDockWidget::title {{
    background: {BG0};
    border-bottom: 1px solid {BORDER};
    padding: 6px 12px;
    text-align: left;
    letter-spacing: 1px;
    font-size: 10px;
    color: {ACCENT};
    text-transform: uppercase;
}}
QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: 2px;
    border-radius: 4px;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background: {BG4};
}}

/* ══════════════════════════════════════════════════════════════════════
   FRAMES
   ══════════════════════════════════════════════════════════════════════ */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {BORDER};
}}

/* ══════════════════════════════════════════════════════════════════════
   TOOL TIPS
   ══════════════════════════════════════════════════════════════════════ */
QToolTip {{
    background-color: {BG5};
    color: {FG0};
    border: 1px solid {BORDER2};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 11px;
}}

/* ══════════════════════════════════════════════════════════════════════
   FORM LAYOUT LABELS
   ══════════════════════════════════════════════════════════════════════ */
QFormLayout QLabel {{
    color: {FG1};
    font-size: 11px;
    min-width: 140px;
}}
"""


def apply_theme(app) -> None:
    """Apply futuristic dark trading theme to a QApplication."""
    from PyQt6.QtGui import QPalette, QColor, QFont
    from PyQt6.QtCore import Qt

    # Palette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(BG1))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(FG0))
    palette.setColor(QPalette.ColorRole.Base,            QColor(BG2))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(BG3))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(BG5))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(FG0))
    palette.setColor(QPalette.ColorRole.Text,            QColor(FG0))
    palette.setColor(QPalette.ColorRole.Button,          QColor(BG3))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(FG0))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(ACCENT + "33"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(FG2))
    palette.setColor(QPalette.ColorRole.Dark,            QColor(BG0))
    palette.setColor(QPalette.ColorRole.Mid,             QColor(BG3))
    palette.setColor(QPalette.ColorRole.Midlight,        QColor(BG4))
    app.setPalette(palette)

    # Font
    font = QFont()
    for name in ("JetBrains Mono", "SF Mono", "Fira Code", "Cascadia Code", "Consolas"):
        font.setFamily(name)
        if font.exactMatch():
            break
    font.setPointSize(11)
    app.setFont(font)

    app.setStyleSheet(DARK_THEME)
