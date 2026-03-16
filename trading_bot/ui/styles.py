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
FG2 = "#565680"          # Disabled / placeholder text (brightened for legibility)
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

/* ── Focus outline: 1px accent border when a widget is clicked / focused ── */
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QListWidget:focus, QTreeWidget:focus,
QTableWidget:focus, QTableView:focus,
QSlider:focus {{
    border: 1px solid {ACCENT};
    outline: none;
}}
QPushButton:focus, QToolButton:focus {{
    border: 1px solid {ACCENT}88;
    outline: none;
}}
QGroupBox:focus-within {{
    border-color: {ACCENT}66;
}}
QWidget {{
    background-color: {BG1};
    color: {FG0};
    font-family: "JetBrains Mono", "SF Mono", "Fira Code", "Cascadia Code",
                 "Consolas", "Courier New", monospace;
    font-size: 13px;
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
    padding: 3px 8px;
    font-size: 13px;
    spacing: 2px;
}}
QMenuBar::item {{
    padding: 5px 12px;
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
    font-size: 13px;
}}
QMenu::item {{
    padding: 8px 28px 8px 14px;
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
    padding: 8px 20px;
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    font-size: 12px;
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
    width: 3px;
    margin: 0px;
}}
QSplitter::handle:vertical {{
    height: 3px;
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
   BUTTONS  — 3-D raised style with gradient lift + pressed depth
   ══════════════════════════════════════════════════════════════════════ */
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {BG5}, stop:0.5 {BG4}, stop:1 {BG2});
    color: {FG1};
    border: 1px solid {BORDER2};
    border-top: 1px solid {BG5};
    border-bottom: 2px solid {BORDER};
    border-radius: 5px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 12px;
    letter-spacing: 0.5px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {GLOW}, stop:1 {BG3});
    border-color: {ACCENT};
    border-top-color: {ACCENT}66;
    border-bottom-color: {ACCENT}AA;
    color: {ACCENT};
}}
QPushButton:pressed {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {BG1}, stop:1 {BG3});
    border-top: 2px solid {BORDER};
    border-bottom: 1px solid {BG5};
    color: {ACCENT};
    padding-top: 9px;
    padding-bottom: 7px;
}}
QPushButton:disabled {{
    color: {FG2};
    border: 1px solid {BORDER};
    border-bottom: 2px solid {BORDER};
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {BG2}, stop:1 {BG1});
}}

/* Named button variants — all use 3-D gradient treatment */
QPushButton#btn_buy {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {GREEN}28, stop:1 {GREEN}0C);
    border: 1px solid {GREEN}88;
    border-top: 1px solid {GREEN}55;
    border-bottom: 2px solid {GREEN}AA;
    color: {GREEN};
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 1px;
}}
QPushButton#btn_buy:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {GREEN}50, stop:1 {GREEN}25);
    border-color: {GREEN};
}}
QPushButton#btn_buy:pressed {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {GREEN}10, stop:1 {GREEN}35);
    border-top: 2px solid {GREEN}AA;
    border-bottom: 1px solid {GREEN}55;
    padding-top: 9px; padding-bottom: 7px;
}}
QPushButton#btn_sell {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {RED}28, stop:1 {RED}0C);
    border: 1px solid {RED}88;
    border-top: 1px solid {RED}55;
    border-bottom: 2px solid {RED}AA;
    color: {RED};
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 1px;
}}
QPushButton#btn_sell:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {RED}50, stop:1 {RED}25);
    border-color: {RED};
}}
QPushButton#btn_sell:pressed {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {RED}10, stop:1 {RED}35);
    border-top: 2px solid {RED}AA;
    border-bottom: 1px solid {RED}55;
    padding-top: 9px; padding-bottom: 7px;
}}
QPushButton#btn_cancel {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {ORANGE}22, stop:1 {ORANGE}0A);
    border: 1px solid {ORANGE}88;
    border-bottom: 2px solid {ORANGE}AA;
    color: {ORANGE};
}}
QPushButton#btn_cancel:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {ORANGE}40, stop:1 {ORANGE}20);
    border-color: {ORANGE};
}}
QPushButton#btn_primary {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {ACCENT}28, stop:1 {ACCENT}0C);
    border: 1px solid {ACCENT}88;
    border-top: 1px solid {ACCENT}55;
    border-bottom: 2px solid {ACCENT}AA;
    color: {ACCENT};
    font-weight: 700;
    letter-spacing: 0.8px;
}}
QPushButton#btn_primary:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {ACCENT}50, stop:1 {ACCENT}25);
    border-color: {ACCENT};
}}
QPushButton#btn_primary:pressed {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {ACCENT}10, stop:1 {ACCENT}35);
    border-top: 2px solid {ACCENT}AA;
    border-bottom: 1px solid {ACCENT}55;
    padding-top: 9px; padding-bottom: 7px;
}}
QPushButton#btn_danger {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {RED}28, stop:1 {RED}0C);
    border: 1px solid {RED}88;
    border-bottom: 2px solid {RED}AA;
    color: {RED};
}}
QPushButton#btn_danger:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {RED}50, stop:1 {RED}25);
    border-color: {RED};
}}

/* btn_start — pulses gently via QPropertyAnimation in code */
QPushButton#btn_start {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {GREEN}20, stop:1 {GREEN}08);
    border: 1px solid {GREEN}55;
    border-top: 1px solid {GREEN}30;
    border-bottom: 2px solid {GREEN}88;
    color: {GREEN};
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QPushButton#btn_start:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {GREEN}40, stop:1 {GREEN}18);
    border-color: {GREEN};
}}
QPushButton#btn_start:pressed {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {GREEN}08, stop:1 {GREEN}30);
    border-top: 2px solid {GREEN}88;
    border-bottom: 1px solid {GREEN}30;
    padding-top: 9px; padding-bottom: 7px;
}}

/* btn_stop — turns grey when already stopped (set disabled=True in code) */
QPushButton#btn_stop {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {RED}20, stop:1 {RED}08);
    border: 1px solid {RED}55;
    border-top: 1px solid {RED}30;
    border-bottom: 2px solid {RED}88;
    color: {RED};
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QPushButton#btn_stop:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {RED}40, stop:1 {RED}18);
    border-color: {RED};
}}
QPushButton#btn_stop:disabled {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {BG3}, stop:1 {BG2});
    border: 1px solid {BORDER};
    border-bottom: 2px solid {BORDER};
    color: {FG2};
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
    padding: 7px 12px;
    selection-background-color: {ACCENT}44;
    font-family: "JetBrains Mono", "SF Mono", "Fira Code", monospace;
    font-size: 13px;
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
    padding: 7px 12px;
    font-size: 13px;
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
    font-size: 12px;
    font-family: "JetBrains Mono", "SF Mono", monospace;
    alternate-background-color: {BG3};
}}
QTableWidget::item, QTableView::item {{
    padding: 6px 10px;
    border: none;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {ACCENT}18;
    color: {ACCENT};
}}
QHeaderView::section {{
    background-color: {BG0};
    color: {FG1};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
    padding: 7px 10px;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 0.8px;
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
    font-size: 10px;
    font-weight: 700;
    color: {FG1};
    letter-spacing: 1.5px;
    text-transform: uppercase;
}}
QLabel#label_value_green  {{ color: {GREEN};  font-weight: 600; }}
QLabel#label_value_red    {{ color: {RED};    font-weight: 600; }}
QLabel#label_value_yellow {{ color: {YELLOW}; font-weight: 600; }}
QLabel#label_accent       {{ color: {ACCENT}; font-weight: 700; }}
QLabel#label_muted        {{ color: {FG2};    font-size: 12px;  }}

/* ══════════════════════════════════════════════════════════════════════
   GROUP BOXES
   ══════════════════════════════════════════════════════════════════════ */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 20px;
    padding: 16px 12px 12px;
    font-weight: 600;
    color: {FG1};
    background-color: {BG2};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: -10px;
    padding: 2px 10px;
    background-color: {BG2};
    color: {ACCENT};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.2px;
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
    height: 12px;
    text-align: center;
    color: transparent;
    font-size: 11px;
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
    spacing: 10px;
    font-size: 13px;
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
    color: {FG1};
    border-top: 1px solid {BORDER};
    font-size: 11px;
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
    font-size: 12px;
    titlebar-close-icon: url(none);
}}
QDockWidget::title {{
    background: {BG0};
    border-bottom: 1px solid {BORDER};
    padding: 7px 14px;
    text-align: left;
    letter-spacing: 0.8px;
    font-size: 11px;
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
    padding: 7px 12px;
    font-size: 12px;
}}

/* ══════════════════════════════════════════════════════════════════════
   FORM LAYOUT LABELS
   ══════════════════════════════════════════════════════════════════════ */
QFormLayout QLabel {{
    color: {FG1};
    font-size: 12px;
    min-width: 150px;
}}
"""


# ── Start-button pulse animation helper ──────────────────────────────────────

def attach_start_pulse(btn) -> None:
    """
    Attach a gentle glow-pulse animation to a QPushButton with
    objectName 'btn_start'.  The button fades its border opacity between
    0x33 and 0xCC every 1.2 s while it is enabled/idle.

    Usage:
        btn = QPushButton("▶  Start")
        btn.setObjectName("btn_start")
        attach_start_pulse(btn)
    """
    try:
        from PyQt6.QtCore import QEasingCurve, QVariantAnimation
        from PyQt6.QtGui import QColor

        anim = QVariantAnimation(btn)
        anim.setStartValue(QColor(f"{GREEN}33"))
        anim.setEndValue(QColor(f"{GREEN}BB"))
        anim.setDuration(1200)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        anim.setLoopCount(-1)   # infinite

        def _on_value(col: QColor) -> None:
            if not btn.isEnabled():
                return
            hex_col = col.name(QColor.NameFormat.HexArgb)[1:]   # drop leading #
            # rebuild just the border-color part; rest kept by objectName stylesheet
            btn.setStyleSheet(
                f"QPushButton#btn_start {{"
                f"  background-color:{GREEN}12;"
                f"  border:1px solid #{hex_col};"
                f"  color:{GREEN}; font-weight:700; letter-spacing:0.5px;"
                f"}}"
                f"QPushButton#btn_start:hover {{"
                f"  background-color:{GREEN}28; border-color:{GREEN};"
                f"}}"
            )

        anim.valueChanged.connect(_on_value)
        btn._pulse_anim = anim   # keep reference

        def _toggle(enabled: bool) -> None:
            if enabled:
                anim.setDirection(QVariantAnimation.Direction.Forward)
                anim.start()
            else:
                anim.stop()
                # Restore disabled appearance via stylesheet
                btn.setStyleSheet("")   # falls back to QSS #btn_stop:disabled rule

        # Start pulsing immediately if button is enabled
        if btn.isEnabled():
            anim.start()

        # Re-evaluate when enabled state changes
        _orig_setEnabled = btn.setEnabled
        def _new_setEnabled(state: bool) -> None:  # type: ignore[method-assign]
            _orig_setEnabled(state)
            _toggle(state)
        btn.setEnabled = _new_setEnabled  # type: ignore[method-assign]
    except Exception:
        pass   # silently skip if PyQt6 animation not available


# ── Available themes registry ─────────────────────────────────────────────────
THEMES: dict[str, str] = {
    "bitnfloat":   "BitNFloat (ThinkorSwim-inspired, default)",
    "futra_neon":  "Futra Neon (dark neon-noir)",
    "night_watch": "Night Watch (low-contrast red, for night trading)",
    "colorblind":  "Colorblind Safe (blue/orange, no red/green)",
    "grey_skill":  "Grey Skill (monochrome black-white-grey)",
    "invert_bitnfloat": "Invert BitNFloat (light charcoal inversion)",
}

DEFAULT_THEME = "bitnfloat"


def apply_theme(app, theme: str = DEFAULT_THEME) -> None:
    """
    Apply a named theme to a QApplication.

    Available themes (see THEMES dict):
      bitnfloat        — ThinkorSwim-inspired professional charcoal (DEFAULT)
      futra_neon       — Futuristic dark neon-noir (original)
      night_watch      — Low-contrast red for night trading
      colorblind       — Blue/orange safe palette (deuteranopia/protanopia)
      grey_skill       — Monochrome black-white-grey (no colour)
      invert_bitnfloat — Light inversion of BitNFloat
    """
    _THEME_MAP = {
        "bitnfloat":        _apply_bitnfloat_theme,
        "futra_neon":       _apply_default_theme,
        "default":          _apply_default_theme,   # alias
        "night_watch":      _apply_nightwatch_theme,
        "colorblind":       _apply_colorblind_theme,
        "grey_skill":       _apply_greyskill_theme,
        "invert_bitnfloat": _apply_invert_bitnfloat_theme,
    }
    fn = _THEME_MAP.get(theme, _apply_bitnfloat_theme)
    fn(app)


def _apply_default_theme(app) -> None:
    """Apply futuristic dark trading theme to a QApplication."""
    from PyQt6.QtGui import QPalette, QColor, QFont

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

    font = QFont()
    for name in ("JetBrains Mono", "SF Mono", "Fira Code", "Cascadia Code", "Consolas"):
        font.setFamily(name)
        if font.exactMatch():
            break
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(DARK_THEME)


# ── BitNFloat Theme (ThinkorSwim-inspired) ────────────────────────────────────

# ThinkorSwim colour palette — charcoal grey base, amber/orange accents,
# bright green BUY, red SELL, cream primary text.
BNF_BG0    = "#161616"   # deepest charcoal
BNF_BG1    = "#1C1C1C"   # main background
BNF_BG2    = "#222222"   # panel background
BNF_BG3    = "#2A2A2A"   # card / widget background
BNF_BG4    = "#323232"   # input / row alt
BNF_BG5    = "#3A3A3A"   # elevated surface

BNF_ACCENT  = "#E8A000"  # TOS amber — primary accent
BNF_ACCENT2 = "#CC6600"  # darker amber
BNF_GREEN   = "#48BB48"  # TOS profit green
BNF_RED     = "#E03030"  # TOS loss red
BNF_YELLOW  = "#E8C800"  # caution / neutral
BNF_ORANGE  = "#E06820"  # warning
BNF_CYAN    = "#50A0C8"  # info / secondary

BNF_BORDER  = "#383838"
BNF_BORDER2 = "#484848"

BNF_FG0 = "#E8E0D0"      # cream — primary text (TOS style)
BNF_FG1 = "#A09080"      # secondary text
BNF_FG2 = "#5A5040"      # disabled / placeholder
BNF_GLOW = "#E8A00022"   # amber glow

BITNFLOAT_THEME = f"""
/* ══════════════════════════════════════════════════════════════════════
   BITNFLOAT THEME — ThinkorSwim-Inspired Professional Trading Desk
   ══════════════════════════════════════════════════════════════════════ */
* {{
    outline: none;
}}
QWidget {{
    background-color: {BNF_BG1};
    color: {BNF_FG0};
    font-family: "Consolas", "JetBrains Mono", "Courier New", monospace;
    font-size: 12px;
}}
QMainWindow {{
    background-color: {BNF_BG0};
}}
QDialog {{
    background-color: {BNF_BG2};
    border: 1px solid {BNF_BORDER2};
    border-radius: 6px;
}}

/* ── MENU BAR ─── */
QMenuBar {{
    background-color: {BNF_BG0};
    color: {BNF_FG1};
    border-bottom: 1px solid {BNF_BORDER};
    padding: 2px 8px;
    font-size: 12px;
}}
QMenuBar::item {{ padding: 4px 10px; border-radius: 3px; }}
QMenuBar::item:selected {{
    background-color: {BNF_GLOW};
    color: {BNF_ACCENT};
    border: 1px solid {BNF_BORDER2};
}}
QMenu {{
    background-color: {BNF_BG3};
    color: {BNF_FG0};
    border: 1px solid {BNF_BORDER2};
    border-radius: 4px;
    padding: 4px 2px;
    font-size: 12px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 2px; margin: 1px 4px; }}
QMenu::item:selected {{
    background-color: {BNF_ACCENT}33;
    color: {BNF_ACCENT};
}}
QMenu::separator {{ height: 1px; background: {BNF_BORDER}; margin: 4px 12px; }}

/* ── TAB BAR ─── */
QTabWidget::pane {{
    border: 1px solid {BNF_BORDER};
    background-color: {BNF_BG2};
    border-radius: 0px 4px 4px 4px;
}}
QTabBar::tab {{
    background-color: {BNF_BG3};
    color: {BNF_FG2};
    padding: 6px 16px;
    border: 1px solid {BNF_BORDER};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
    font-size: 11px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    background-color: {BNF_BG2};
    color: {BNF_ACCENT};
    border-color: {BNF_BORDER2};
    border-bottom: 2px solid {BNF_ACCENT};
}}
QTabBar::tab:hover:!selected {{
    background-color: {BNF_BG4};
    color: {BNF_FG1};
}}

/* ── SPLITTER ─── */
QSplitter::handle {{ background-color: {BNF_BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background-color: {BNF_ACCENT}; }}

/* ── SCROLL BARS ─── */
QScrollBar:vertical {{
    background: {BNF_BG0}; width: 6px; border-radius: 3px; margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {BNF_BG5}; border-radius: 3px; min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: {BNF_ACCENT}88; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{
    background: {BNF_BG0}; height: 6px; border-radius: 3px; margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: {BNF_BG5}; border-radius: 3px; min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{ background: {BNF_ACCENT}88; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

/* ── BUTTONS ─── */
QPushButton {{
    background-color: {BNF_BG4};
    color: {BNF_FG1};
    border: 1px solid {BNF_BORDER2};
    border-radius: 3px;
    padding: 6px 14px;
    font-weight: 600;
    font-size: 11px;
}}
QPushButton:hover {{
    background-color: {BNF_ACCENT}22;
    border-color: {BNF_ACCENT};
    color: {BNF_ACCENT};
}}
QPushButton:pressed {{
    background-color: {BNF_ACCENT}33;
}}
QPushButton:disabled {{
    color: {BNF_FG2};
    border-color: {BNF_BORDER};
    background-color: {BNF_BG2};
}}

/* Named button variants */
QPushButton#btn_buy {{
    background-color: {BNF_GREEN}18;
    border: 1px solid {BNF_GREEN}88;
    color: {BNF_GREEN};
    font-weight: 700;
    font-size: 13px;
}}
QPushButton#btn_buy:hover {{
    background-color: {BNF_GREEN}33;
    border-color: {BNF_GREEN};
}}
QPushButton#btn_sell {{
    background-color: {BNF_RED}18;
    border: 1px solid {BNF_RED}88;
    color: {BNF_RED};
    font-weight: 700;
    font-size: 13px;
}}
QPushButton#btn_sell:hover {{
    background-color: {BNF_RED}33;
    border-color: {BNF_RED};
}}
QPushButton#btn_primary {{
    background-color: {BNF_ACCENT}20;
    border: 1px solid {BNF_ACCENT}88;
    color: {BNF_ACCENT};
    font-weight: 700;
}}
QPushButton#btn_primary:hover {{
    background-color: {BNF_ACCENT}40;
    border-color: {BNF_ACCENT};
}}
QPushButton#btn_danger {{
    background-color: {BNF_RED}18;
    border-color: {BNF_RED}88;
    color: {BNF_RED};
}}
QPushButton#nav_btn {{
    background: transparent;
    border: none;
    border-radius: 3px;
    color: {BNF_FG2};
    font-size: 10px;
    font-weight: 600;
    text-align: center;
    padding: 10px 4px;
}}
QPushButton#nav_btn:hover {{
    background: {BNF_GLOW};
    color: {BNF_FG1};
}}
QPushButton#nav_btn[active="true"] {{
    background: {BNF_ACCENT}18;
    color: {BNF_ACCENT};
    border-left: 2px solid {BNF_ACCENT};
    border-radius: 0px 3px 3px 0px;
}}

/* ── INPUTS ─── */
QLineEdit, QDoubleSpinBox, QSpinBox, QTextEdit, QPlainTextEdit {{
    background-color: {BNF_BG3};
    color: {BNF_FG0};
    border: 1px solid {BNF_BORDER2};
    border-radius: 3px;
    padding: 5px 8px;
    selection-background-color: {BNF_ACCENT}44;
    font-family: "Consolas", "Courier New", monospace;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {BNF_ACCENT};
    background-color: {BNF_BG4};
}}
QComboBox {{
    background-color: {BNF_BG3};
    color: {BNF_FG0};
    border: 1px solid {BNF_BORDER2};
    border-radius: 3px;
    padding: 5px 8px;
}}
QComboBox:focus {{ border-color: {BNF_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; background: transparent; }}
QComboBox QAbstractItemView {{
    background-color: {BNF_BG3};
    color: {BNF_FG0};
    border: 1px solid {BNF_BORDER2};
    selection-background-color: {BNF_ACCENT}22;
    selection-color: {BNF_ACCENT};
}}

/* ── TABLES ─── */
QTableWidget, QTableView {{
    background-color: {BNF_BG2};
    color: {BNF_FG0};
    gridline-color: {BNF_BORDER};
    border: 1px solid {BNF_BORDER};
    border-radius: 3px;
    font-size: 11px;
    alternate-background-color: {BNF_BG3};
}}
QTableWidget::item, QTableView::item {{ padding: 3px 6px; border: none; }}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {BNF_ACCENT}22;
    color: {BNF_ACCENT};
}}
QHeaderView::section {{
    background-color: {BNF_BG0};
    color: {BNF_FG2};
    border: none;
    border-bottom: 1px solid {BNF_BORDER};
    border-right: 1px solid {BNF_BORDER};
    padding: 4px 6px;
    font-weight: 700;
    font-size: 10px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}}

/* ── GROUP BOXES ─── */
QGroupBox {{
    border: 1px solid {BNF_BORDER};
    border-radius: 4px;
    margin-top: 16px;
    padding: 12px 8px 8px;
    font-weight: 600;
    color: {BNF_FG1};
    background-color: {BNF_BG2};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px; top: -8px;
    padding: 1px 6px;
    background-color: {BNF_BG2};
    color: {BNF_ACCENT};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    border: 1px solid {BNF_BORDER};
    border-radius: 3px;
}}

/* ── PROGRESS BAR ─── */
QProgressBar {{
    background-color: {BNF_BG4};
    border: 1px solid {BNF_BORDER};
    border-radius: 3px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {BNF_ACCENT2}, stop:1 {BNF_ACCENT}
    );
    border-radius: 2px;
}}

/* ── CHECKBOXES ─── */
QCheckBox {{
    color: {BNF_FG0};
    spacing: 8px;
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border-radius: 2px;
    border: 1px solid {BNF_BORDER2};
    background: {BNF_BG4};
}}
QCheckBox::indicator:hover {{ border-color: {BNF_ACCENT}; }}
QCheckBox::indicator:checked {{ background-color: {BNF_ACCENT}; border-color: {BNF_ACCENT}; }}

/* ── STATUS BAR ─── */
QStatusBar {{
    background-color: {BNF_BG0};
    color: {BNF_FG2};
    border-top: 1px solid {BNF_BORDER};
    font-size: 10px;
}}

/* ── DOCK WIDGETS ─── */
QDockWidget::title {{
    background: {BNF_BG0};
    border-bottom: 1px solid {BNF_BORDER};
    padding: 5px 10px;
    text-align: left;
    letter-spacing: 0.5px;
    font-size: 10px;
    color: {BNF_ACCENT};
    text-transform: uppercase;
}}

/* ── TOOL TIPS ─── */
QToolTip {{
    background-color: {BNF_BG5};
    color: {BNF_FG0};
    border: 1px solid {BNF_BORDER2};
    border-radius: 3px;
    padding: 5px 8px;
    font-size: 11px;
}}

/* ── LABELS (named) ─── */
QLabel#label_price {{
    font-size: 24px; font-weight: 700; color: {BNF_FG0};
    font-family: "Consolas", monospace;
}}
QLabel#label_change_pos  {{ font-size: 13px; font-weight: 600; color: {BNF_GREEN}; }}
QLabel#label_change_neg  {{ font-size: 13px; font-weight: 600; color: {BNF_RED}; }}
QLabel#label_section     {{
    font-size: 9px; font-weight: 700; color: {BNF_FG2};
    letter-spacing: 1.5px; text-transform: uppercase;
}}
QLabel#label_value_green  {{ color: {BNF_GREEN};  font-weight: 600; }}
QLabel#label_value_red    {{ color: {BNF_RED};    font-weight: 600; }}
QLabel#label_value_yellow {{ color: {BNF_YELLOW}; font-weight: 600; }}
QLabel#label_accent       {{ color: {BNF_ACCENT}; font-weight: 700; }}
QLabel#label_muted        {{ color: {BNF_FG2};    font-size: 11px;  }}
"""


def _apply_bitnfloat_theme(app) -> None:
    """Apply BitNFloat (ThinkorSwim-inspired) theme to a QApplication."""
    from PyQt6.QtGui import QPalette, QColor, QFont

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(BNF_BG1))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(BNF_FG0))
    palette.setColor(QPalette.ColorRole.Base,            QColor(BNF_BG2))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(BNF_BG3))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(BNF_BG5))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(BNF_FG0))
    palette.setColor(QPalette.ColorRole.Text,            QColor(BNF_FG0))
    palette.setColor(QPalette.ColorRole.Button,          QColor(BNF_BG3))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(BNF_FG0))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor(BNF_ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(BNF_ACCENT + "33"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(BNF_ACCENT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(BNF_FG2))
    palette.setColor(QPalette.ColorRole.Dark,            QColor(BNF_BG0))
    palette.setColor(QPalette.ColorRole.Mid,             QColor(BNF_BG3))
    palette.setColor(QPalette.ColorRole.Midlight,        QColor(BNF_BG4))
    app.setPalette(palette)

    font = QFont()
    for name in ("Consolas", "JetBrains Mono", "Courier New"):
        font.setFamily(name)
        if font.exactMatch():
            break
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(BITNFLOAT_THEME)


# ── Night Watch Theme — Low-contrast red for night trading ───────────────────
# Deep near-black background with muted crimson accents.
# Designed to preserve night vision — no bright blues or whites.

NW_BG0    = "#100808"   # near-black with red tint — deepest
NW_BG1    = "#150A0A"   # main background
NW_BG2    = "#1C0E0E"   # panel background
NW_BG3    = "#231212"   # card / widget background
NW_BG4    = "#2A1616"   # input / row alt
NW_BG5    = "#311A1A"   # elevated surface

NW_ACCENT  = "#CC3333"  # muted crimson — primary accent
NW_ACCENT2 = "#AA2222"  # darker crimson
NW_GREEN   = "#6A9050"  # olive/muted green — profit (not eye-straining)
NW_RED     = "#CC2222"  # dark red — loss / sell
NW_YELLOW  = "#A07030"  # dark amber — caution
NW_ORANGE  = "#884422"  # warning

NW_BORDER  = "#2A1212"
NW_BORDER2 = "#3A1818"

NW_FG0 = "#C0A0A0"      # muted rose-white — primary text
NW_FG1 = "#806060"      # secondary text
NW_FG2 = "#4A3030"      # disabled / placeholder
NW_GLOW = "#CC333322"   # crimson glow

NIGHTWATCH_THEME = f"""
/* ══════════════════════════════════════════════════════════════════════
   NIGHT WATCH THEME — Low-contrast red palette for night trading
   ══════════════════════════════════════════════════════════════════════ */
* {{ outline: none; }}
QWidget {{
    background-color: {NW_BG1};
    color: {NW_FG0};
    font-family: "Consolas", "JetBrains Mono", "Courier New", monospace;
    font-size: 12px;
}}
QMainWindow {{ background-color: {NW_BG0}; }}
QDialog {{
    background-color: {NW_BG2};
    border: 1px solid {NW_BORDER2};
    border-radius: 6px;
}}
QMenuBar {{
    background-color: {NW_BG0}; color: {NW_FG1};
    border-bottom: 1px solid {NW_BORDER}; padding: 2px 8px;
}}
QMenuBar::item {{ padding: 4px 10px; border-radius: 3px; }}
QMenuBar::item:selected {{ background-color: {NW_GLOW}; color: {NW_ACCENT}; }}
QMenu {{
    background-color: {NW_BG3}; color: {NW_FG0};
    border: 1px solid {NW_BORDER2}; border-radius: 4px; padding: 4px 2px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 2px; margin: 1px 4px; }}
QMenu::item:selected {{ background-color: {NW_ACCENT}33; color: {NW_ACCENT}; }}
QMenu::separator {{ height: 1px; background: {NW_BORDER}; margin: 4px 12px; }}
QTabWidget::pane {{ border: 1px solid {NW_BORDER}; background-color: {NW_BG2}; }}
QTabBar::tab {{
    background-color: {NW_BG3}; color: {NW_FG2};
    padding: 6px 16px; border: 1px solid {NW_BORDER}; border-bottom: none;
    border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px;
    font-size: 11px; font-weight: 600;
}}
QTabBar::tab:selected {{
    background-color: {NW_BG2}; color: {NW_ACCENT};
    border-color: {NW_BORDER2}; border-bottom: 2px solid {NW_ACCENT};
}}
QTabBar::tab:hover:!selected {{ background-color: {NW_BG4}; color: {NW_FG1}; }}
QSplitter::handle {{ background-color: {NW_BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background-color: {NW_ACCENT}; }}
QScrollBar:vertical {{
    background: {NW_BG0}; width: 5px; border-radius: 2px; margin: 0px;
}}
QScrollBar::handle:vertical {{ background: {NW_BG5}; border-radius: 2px; min-height: 20px; }}
QScrollBar::handle:vertical:hover {{ background: {NW_ACCENT}88; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{
    background: {NW_BG0}; height: 5px; border-radius: 2px; margin: 0px;
}}
QScrollBar::handle:horizontal {{ background: {NW_BG5}; border-radius: 2px; min-width: 20px; }}
QScrollBar::handle:horizontal:hover {{ background: {NW_ACCENT}88; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QPushButton {{
    background-color: {NW_BG4}; color: {NW_FG1};
    border: 1px solid {NW_BORDER2}; border-radius: 3px; padding: 6px 14px;
    font-weight: 600; font-size: 11px;
}}
QPushButton:hover {{ background-color: {NW_ACCENT}22; border-color: {NW_ACCENT}; color: {NW_ACCENT}; }}
QPushButton:pressed {{ background-color: {NW_ACCENT}33; }}
QPushButton:disabled {{ color: {NW_FG2}; border-color: {NW_BORDER}; background-color: {NW_BG2}; }}
QPushButton#btn_buy {{
    background-color: {NW_GREEN}18; border: 1px solid {NW_GREEN}88; color: {NW_GREEN};
    font-weight: 700; font-size: 13px;
}}
QPushButton#btn_buy:hover {{ background-color: {NW_GREEN}33; border-color: {NW_GREEN}; }}
QPushButton#btn_sell {{
    background-color: {NW_RED}18; border: 1px solid {NW_RED}88; color: {NW_RED};
    font-weight: 700; font-size: 13px;
}}
QPushButton#btn_sell:hover {{ background-color: {NW_RED}33; border-color: {NW_RED}; }}
QPushButton#btn_primary {{
    background-color: {NW_ACCENT}20; border: 1px solid {NW_ACCENT}88; color: {NW_ACCENT}; font-weight: 700;
}}
QPushButton#btn_primary:hover {{ background-color: {NW_ACCENT}40; border-color: {NW_ACCENT}; }}
QPushButton#btn_danger {{ background-color: {NW_RED}18; border-color: {NW_RED}88; color: {NW_RED}; }}
QPushButton#nav_btn {{
    background: transparent; border: none; border-radius: 3px;
    color: {NW_FG2}; font-size: 10px; font-weight: 600; text-align: center; padding: 10px 4px;
}}
QPushButton#nav_btn:hover {{ background: {NW_GLOW}; color: {NW_FG1}; }}
QPushButton#nav_btn[active="true"] {{
    background: {NW_ACCENT}18; color: {NW_ACCENT};
    border-left: 2px solid {NW_ACCENT}; border-radius: 0px 3px 3px 0px;
}}
QLineEdit, QDoubleSpinBox, QSpinBox, QTextEdit, QPlainTextEdit {{
    background-color: {NW_BG3}; color: {NW_FG0};
    border: 1px solid {NW_BORDER2}; border-radius: 3px; padding: 5px 8px;
    selection-background-color: {NW_ACCENT}44;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {NW_ACCENT}; background-color: {NW_BG4}; }}
QComboBox {{
    background-color: {NW_BG3}; color: {NW_FG0};
    border: 1px solid {NW_BORDER2}; border-radius: 3px; padding: 5px 8px;
}}
QComboBox:focus {{ border-color: {NW_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; background: transparent; }}
QComboBox QAbstractItemView {{
    background-color: {NW_BG3}; color: {NW_FG0};
    border: 1px solid {NW_BORDER2};
    selection-background-color: {NW_ACCENT}22; selection-color: {NW_ACCENT};
}}
QTableWidget, QTableView {{
    background-color: {NW_BG2}; color: {NW_FG0};
    gridline-color: {NW_BORDER}; border: 1px solid {NW_BORDER};
    border-radius: 3px; font-size: 11px; alternate-background-color: {NW_BG3};
}}
QTableWidget::item, QTableView::item {{ padding: 3px 6px; border: none; }}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {NW_ACCENT}22; color: {NW_ACCENT};
}}
QHeaderView::section {{
    background-color: {NW_BG0}; color: {NW_FG2};
    border: none; border-bottom: 1px solid {NW_BORDER};
    padding: 4px 6px; font-weight: 700; font-size: 10px; text-transform: uppercase;
}}
QGroupBox {{
    border: 1px solid {NW_BORDER}; border-radius: 4px; margin-top: 16px;
    padding: 12px 8px 8px; font-weight: 600; color: {NW_FG1}; background-color: {NW_BG2};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left; left: 12px; top: -8px;
    padding: 1px 6px; background-color: {NW_BG2}; color: {NW_ACCENT};
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    border: 1px solid {NW_BORDER}; border-radius: 3px;
}}
QProgressBar {{
    background-color: {NW_BG4}; border: 1px solid {NW_BORDER}; border-radius: 3px;
    height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{
    background-color: {NW_ACCENT2}; border-radius: 2px;
}}
QCheckBox {{ color: {NW_FG0}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border-radius: 2px;
    border: 1px solid {NW_BORDER2}; background: {NW_BG4};
}}
QCheckBox::indicator:hover {{ border-color: {NW_ACCENT}; }}
QCheckBox::indicator:checked {{ background-color: {NW_ACCENT}; border-color: {NW_ACCENT}; }}
QStatusBar {{
    background-color: {NW_BG0}; color: {NW_FG2};
    border-top: 1px solid {NW_BORDER}; font-size: 10px;
}}
QDockWidget::title {{
    background: {NW_BG0}; border-bottom: 1px solid {NW_BORDER};
    padding: 5px 10px; color: {NW_ACCENT}; text-transform: uppercase; font-size: 10px;
}}
QToolTip {{
    background-color: {NW_BG5}; color: {NW_FG0};
    border: 1px solid {NW_BORDER2}; border-radius: 3px; padding: 5px 8px; font-size: 11px;
}}
QLabel#label_price {{ font-size: 24px; font-weight: 700; color: {NW_FG0}; }}
QLabel#label_change_pos {{ font-size: 13px; font-weight: 600; color: {NW_GREEN}; }}
QLabel#label_change_neg {{ font-size: 13px; font-weight: 600; color: {NW_RED}; }}
QLabel#label_section {{ font-size: 9px; font-weight: 700; color: {NW_FG2}; text-transform: uppercase; }}
QLabel#label_value_green {{ color: {NW_GREEN}; font-weight: 600; }}
QLabel#label_value_red {{ color: {NW_RED}; font-weight: 600; }}
QLabel#label_value_yellow {{ color: {NW_YELLOW}; font-weight: 600; }}
QLabel#label_accent {{ color: {NW_ACCENT}; font-weight: 700; }}
QLabel#label_muted {{ color: {NW_FG2}; font-size: 11px; }}
"""


# ── Colorblind-Friendly Theme — Deuteranopia/Protanopia safe ─────────────────
# Uses blue/orange/yellow as primary signal colours instead of green/red.
# Based on the IBM Colorblind Safe palette and Paul Tol's bright scheme.
# BUY → bright blue  |  SELL → orange  |  NEUTRAL → yellow

CB_BG0    = "#0A0A12"
CB_BG1    = "#0D0D18"
CB_BG2    = "#121220"
CB_BG3    = "#181830"
CB_BG4    = "#1E1E3A"
CB_BG5    = "#242448"

CB_ACCENT  = "#5B9BD5"  # accessible blue — primary accent
CB_ACCENT2 = "#2E75B6"  # darker blue
CB_BUY     = "#5B9BD5"  # blue — replaces green for BUY/profit
CB_SELL    = "#E07B39"  # orange — replaces red for SELL/loss
CB_WARN    = "#F0C040"  # yellow — neutral / caution
CB_INFO    = "#9B6FCE"  # purple — info

CB_BORDER  = "#1E1E40"
CB_BORDER2 = "#2A2A58"

CB_FG0 = "#E8E8FF"
CB_FG1 = "#8888BB"
CB_FG2 = "#44446A"
CB_GLOW = "#5B9BD533"

COLORBLIND_THEME = f"""
/* ══════════════════════════════════════════════════════════════════════
   COLORBLIND THEME — Blue/Orange safe palette (deuteranopia / protanopia)
   BUY=blue  SELL=orange  NEUTRAL=yellow  — no red/green distinction needed
   ══════════════════════════════════════════════════════════════════════ */
* {{ outline: none; }}
QWidget {{
    background-color: {CB_BG1}; color: {CB_FG0};
    font-family: "JetBrains Mono", "Consolas", "Courier New", monospace;
    font-size: 12px;
}}
QMainWindow {{ background-color: {CB_BG0}; }}
QDialog {{ background-color: {CB_BG2}; border: 1px solid {CB_BORDER2}; border-radius: 8px; }}
QMenuBar {{
    background-color: {CB_BG0}; color: {CB_FG1};
    border-bottom: 1px solid {CB_BORDER}; padding: 2px 8px;
}}
QMenuBar::item {{ padding: 4px 10px; border-radius: 4px; }}
QMenuBar::item:selected {{ background-color: {CB_GLOW}; color: {CB_ACCENT}; }}
QMenu {{
    background-color: {CB_BG3}; color: {CB_FG0};
    border: 1px solid {CB_BORDER2}; border-radius: 6px; padding: 4px 2px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 3px; margin: 1px 4px; }}
QMenu::item:selected {{ background-color: {CB_ACCENT}33; color: {CB_ACCENT}; }}
QMenu::separator {{ height: 1px; background: {CB_BORDER}; margin: 4px 12px; }}
QTabWidget::pane {{ border: 1px solid {CB_BORDER}; background-color: {CB_BG2}; border-radius: 0px 6px 6px 6px; }}
QTabBar::tab {{
    background-color: {CB_BG3}; color: {CB_FG2};
    padding: 6px 16px; border: 1px solid {CB_BORDER}; border-bottom: none;
    border-top-left-radius: 5px; border-top-right-radius: 5px; margin-right: 2px;
    font-size: 11px; font-weight: 600;
}}
QTabBar::tab:selected {{ background-color: {CB_BG2}; color: {CB_ACCENT}; border-bottom: 2px solid {CB_ACCENT}; }}
QTabBar::tab:hover:!selected {{ background-color: {CB_BG4}; color: {CB_FG1}; }}
QSplitter::handle {{ background-color: {CB_BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background-color: {CB_ACCENT}; }}
QScrollBar:vertical {{
    background: {CB_BG0}; width: 6px; border-radius: 3px; margin: 0px;
}}
QScrollBar::handle:vertical {{ background: {CB_BG5}; border-radius: 3px; min-height: 20px; }}
QScrollBar::handle:vertical:hover {{ background: {CB_ACCENT}88; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{
    background: {CB_BG0}; height: 6px; border-radius: 3px; margin: 0px;
}}
QScrollBar::handle:horizontal {{ background: {CB_BG5}; border-radius: 3px; min-width: 20px; }}
QScrollBar::handle:horizontal:hover {{ background: {CB_ACCENT}88; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QPushButton {{
    background-color: {CB_BG4}; color: {CB_FG1};
    border: 1px solid {CB_BORDER2}; border-radius: 4px; padding: 6px 14px;
    font-weight: 600; font-size: 11px;
}}
QPushButton:hover {{ background-color: {CB_GLOW}; border-color: {CB_ACCENT}; color: {CB_ACCENT}; }}
QPushButton:pressed {{ background-color: {CB_ACCENT}22; }}
QPushButton:disabled {{ color: {CB_FG2}; border-color: {CB_BORDER}; background-color: {CB_BG2}; }}
/* BUY = blue, SELL = orange (colorblind safe) */
QPushButton#btn_buy {{
    background-color: {CB_BUY}18; border: 1px solid {CB_BUY}88; color: {CB_BUY};
    font-weight: 700; font-size: 13px;
}}
QPushButton#btn_buy:hover {{ background-color: {CB_BUY}33; border-color: {CB_BUY}; }}
QPushButton#btn_sell {{
    background-color: {CB_SELL}18; border: 1px solid {CB_SELL}88; color: {CB_SELL};
    font-weight: 700; font-size: 13px;
}}
QPushButton#btn_sell:hover {{ background-color: {CB_SELL}33; border-color: {CB_SELL}; }}
QPushButton#btn_primary {{
    background-color: {CB_ACCENT}20; border: 1px solid {CB_ACCENT}88; color: {CB_ACCENT}; font-weight: 700;
}}
QPushButton#btn_primary:hover {{ background-color: {CB_ACCENT}40; border-color: {CB_ACCENT}; }}
QPushButton#btn_danger {{ background-color: {CB_SELL}18; border-color: {CB_SELL}88; color: {CB_SELL}; }}
QPushButton#nav_btn {{
    background: transparent; border: none; border-radius: 5px;
    color: {CB_FG2}; font-size: 10px; font-weight: 600; text-align: center; padding: 10px 4px;
}}
QPushButton#nav_btn:hover {{ background: {CB_GLOW}; color: {CB_FG1}; }}
QPushButton#nav_btn[active="true"] {{
    background: {CB_ACCENT}18; color: {CB_ACCENT};
    border-left: 2px solid {CB_ACCENT}; border-radius: 0px 5px 5px 0px;
}}
QLineEdit, QDoubleSpinBox, QSpinBox, QTextEdit, QPlainTextEdit {{
    background-color: {CB_BG3}; color: {CB_FG0};
    border: 1px solid {CB_BORDER2}; border-radius: 4px; padding: 5px 8px;
    selection-background-color: {CB_ACCENT}44;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {CB_ACCENT}; background-color: {CB_BG4}; }}
QComboBox {{
    background-color: {CB_BG3}; color: {CB_FG0};
    border: 1px solid {CB_BORDER2}; border-radius: 4px; padding: 5px 8px;
}}
QComboBox:focus {{ border-color: {CB_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; background: transparent; }}
QComboBox QAbstractItemView {{
    background-color: {CB_BG3}; color: {CB_FG0}; border: 1px solid {CB_BORDER2};
    selection-background-color: {CB_ACCENT}22; selection-color: {CB_ACCENT};
}}
QTableWidget, QTableView {{
    background-color: {CB_BG2}; color: {CB_FG0};
    gridline-color: {CB_BORDER}; border: 1px solid {CB_BORDER};
    border-radius: 5px; font-size: 11px; alternate-background-color: {CB_BG3};
}}
QTableWidget::item, QTableView::item {{ padding: 3px 6px; border: none; }}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {CB_ACCENT}22; color: {CB_ACCENT};
}}
QHeaderView::section {{
    background-color: {CB_BG0}; color: {CB_FG2};
    border: none; border-bottom: 1px solid {CB_BORDER};
    padding: 4px 6px; font-weight: 700; font-size: 10px; text-transform: uppercase;
}}
QGroupBox {{
    border: 1px solid {CB_BORDER}; border-radius: 6px; margin-top: 16px;
    padding: 12px 8px 8px; font-weight: 600; color: {CB_FG1}; background-color: {CB_BG2};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left; left: 12px; top: -8px;
    padding: 1px 6px; background-color: {CB_BG2}; color: {CB_ACCENT};
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    border: 1px solid {CB_BORDER}; border-radius: 3px;
}}
QProgressBar {{
    background-color: {CB_BG4}; border: 1px solid {CB_BORDER};
    border-radius: 4px; height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {CB_ACCENT2}, stop:1 {CB_ACCENT});
    border-radius: 3px;
}}
QCheckBox {{ color: {CB_FG0}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border-radius: 3px;
    border: 1px solid {CB_BORDER2}; background: {CB_BG4};
}}
QCheckBox::indicator:hover {{ border-color: {CB_ACCENT}; }}
QCheckBox::indicator:checked {{ background-color: {CB_ACCENT}; border-color: {CB_ACCENT}; }}
QStatusBar {{
    background-color: {CB_BG0}; color: {CB_FG2};
    border-top: 1px solid {CB_BORDER}; font-size: 10px;
}}
QDockWidget::title {{
    background: {CB_BG0}; border-bottom: 1px solid {CB_BORDER};
    padding: 5px 10px; color: {CB_ACCENT}; text-transform: uppercase; font-size: 10px;
}}
QToolTip {{
    background-color: {CB_BG5}; color: {CB_FG0};
    border: 1px solid {CB_BORDER2}; border-radius: 5px; padding: 5px 8px; font-size: 11px;
}}
QLabel#label_price {{ font-size: 24px; font-weight: 700; color: {CB_FG0}; }}
QLabel#label_change_pos {{ font-size: 13px; font-weight: 600; color: {CB_BUY}; }}
QLabel#label_change_neg {{ font-size: 13px; font-weight: 600; color: {CB_SELL}; }}
QLabel#label_section {{ font-size: 9px; font-weight: 700; color: {CB_FG2}; text-transform: uppercase; }}
QLabel#label_value_green {{ color: {CB_BUY}; font-weight: 600; }}
QLabel#label_value_red {{ color: {CB_SELL}; font-weight: 600; }}
QLabel#label_value_yellow {{ color: {CB_WARN}; font-weight: 600; }}
QLabel#label_accent {{ color: {CB_ACCENT}; font-weight: 700; }}
QLabel#label_muted {{ color: {CB_FG2}; font-size: 11px; }}
"""


def _apply_bitnfloat_theme(app) -> None:
    """Apply BitNFloat (ThinkorSwim-inspired) theme to a QApplication."""
    from PyQt6.QtGui import QPalette, QColor, QFont

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(BNF_BG1))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(BNF_FG0))
    palette.setColor(QPalette.ColorRole.Base,            QColor(BNF_BG2))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(BNF_BG3))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(BNF_BG5))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(BNF_FG0))
    palette.setColor(QPalette.ColorRole.Text,            QColor(BNF_FG0))
    palette.setColor(QPalette.ColorRole.Button,          QColor(BNF_BG3))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(BNF_FG0))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor(BNF_ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(BNF_ACCENT + "33"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(BNF_ACCENT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(BNF_FG2))
    palette.setColor(QPalette.ColorRole.Dark,            QColor(BNF_BG0))
    palette.setColor(QPalette.ColorRole.Mid,             QColor(BNF_BG3))
    palette.setColor(QPalette.ColorRole.Midlight,        QColor(BNF_BG4))
    app.setPalette(palette)

    font = QFont()
    for name in ("Consolas", "JetBrains Mono", "Courier New"):
        font.setFamily(name)
        if font.exactMatch():
            break
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(BITNFLOAT_THEME)


def _apply_nightwatch_theme(app) -> None:
    """Apply Night Watch low-contrast red theme."""
    from PyQt6.QtGui import QPalette, QColor, QFont

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(NW_BG1))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(NW_FG0))
    palette.setColor(QPalette.ColorRole.Base,            QColor(NW_BG2))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(NW_BG3))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(NW_BG5))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(NW_FG0))
    palette.setColor(QPalette.ColorRole.Text,            QColor(NW_FG0))
    palette.setColor(QPalette.ColorRole.Button,          QColor(NW_BG3))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(NW_FG0))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor(NW_ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(NW_ACCENT + "33"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(NW_ACCENT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(NW_FG2))
    palette.setColor(QPalette.ColorRole.Dark,            QColor(NW_BG0))
    palette.setColor(QPalette.ColorRole.Mid,             QColor(NW_BG3))
    palette.setColor(QPalette.ColorRole.Midlight,        QColor(NW_BG4))
    app.setPalette(palette)

    font = QFont()
    for name in ("Consolas", "JetBrains Mono", "Courier New"):
        font.setFamily(name)
        if font.exactMatch():
            break
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(NIGHTWATCH_THEME)


def _apply_colorblind_theme(app) -> None:
    """Apply colorblind-friendly blue/orange theme."""
    from PyQt6.QtGui import QPalette, QColor, QFont

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(CB_BG1))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(CB_FG0))
    palette.setColor(QPalette.ColorRole.Base,            QColor(CB_BG2))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(CB_BG3))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(CB_BG5))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(CB_FG0))
    palette.setColor(QPalette.ColorRole.Text,            QColor(CB_FG0))
    palette.setColor(QPalette.ColorRole.Button,          QColor(CB_BG3))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(CB_FG0))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor(CB_ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(CB_ACCENT + "33"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(CB_ACCENT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(CB_FG2))
    palette.setColor(QPalette.ColorRole.Dark,            QColor(CB_BG0))
    palette.setColor(QPalette.ColorRole.Mid,             QColor(CB_BG3))
    palette.setColor(QPalette.ColorRole.Midlight,        QColor(CB_BG4))
    app.setPalette(palette)

    font = QFont()
    for name in ("JetBrains Mono", "Consolas", "Courier New"):
        font.setFamily(name)
        if font.exactMatch():
            break
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(COLORBLIND_THEME)


# ── Grey Skill Theme — Monochrome black/white/grey ────────────────────────────
# Pure greyscale — no colour signals at all. Useful for low-distraction focus.
# BUY uses light grey, SELL uses dark grey, neutral mid-grey.

GS_BG0    = "#0A0A0A"
GS_BG1    = "#111111"
GS_BG2    = "#181818"
GS_BG3    = "#202020"
GS_BG4    = "#282828"
GS_BG5    = "#303030"

GS_ACCENT  = "#CCCCCC"
GS_ACCENT2 = "#AAAAAA"
GS_BUY     = "#CCCCCC"  # light grey — profit
GS_SELL    = "#666666"  # dark grey — loss
GS_WARN    = "#999999"  # mid grey

GS_BORDER  = "#252525"
GS_BORDER2 = "#353535"

GS_FG0 = "#EEEEEE"
GS_FG1 = "#999999"
GS_FG2 = "#555555"

GREYSKILL_THEME = f"""
/* ══════════════════════════════════════════════════════════════════════
   GREY SKILL THEME — Pure monochrome, no colour distractions
   ══════════════════════════════════════════════════════════════════════ */
* {{ outline: none; }}
QWidget {{
    background-color: {GS_BG1}; color: {GS_FG0};
    font-family: "Consolas", "JetBrains Mono", "Courier New", monospace;
    font-size: 12px;
}}
QMainWindow {{ background-color: {GS_BG0}; }}
QDialog {{ background-color: {GS_BG2}; border: 1px solid {GS_BORDER2}; border-radius: 6px; }}
QMenuBar {{
    background-color: {GS_BG0}; color: {GS_FG1};
    border-bottom: 1px solid {GS_BORDER}; padding: 2px 8px;
}}
QMenuBar::item {{ padding: 4px 10px; border-radius: 3px; }}
QMenuBar::item:selected {{ background-color: {GS_BG3}; color: {GS_FG0}; }}
QMenu {{
    background-color: {GS_BG3}; color: {GS_FG0};
    border: 1px solid {GS_BORDER2}; border-radius: 4px; padding: 4px 2px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 2px; margin: 1px 4px; }}
QMenu::item:selected {{ background-color: {GS_BG4}; color: {GS_FG0}; }}
QMenu::separator {{ height: 1px; background: {GS_BORDER}; margin: 4px 12px; }}
QTabWidget::pane {{ border: 1px solid {GS_BORDER}; background-color: {GS_BG2}; }}
QTabBar::tab {{
    background-color: {GS_BG3}; color: {GS_FG2};
    padding: 6px 16px; border: 1px solid {GS_BORDER}; border-bottom: none;
    border-top-left-radius: 3px; border-top-right-radius: 3px; margin-right: 2px;
    font-size: 11px; font-weight: 600;
}}
QTabBar::tab:selected {{ background-color: {GS_BG2}; color: {GS_FG0}; border-bottom: 2px solid {GS_ACCENT}; }}
QTabBar::tab:hover:!selected {{ background-color: {GS_BG4}; color: {GS_FG1}; }}
QSplitter::handle {{ background-color: {GS_BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background-color: {GS_ACCENT}; }}
QScrollBar:vertical {{ background: {GS_BG0}; width: 5px; border-radius: 2px; margin: 0px; }}
QScrollBar::handle:vertical {{ background: {GS_BG5}; border-radius: 2px; min-height: 20px; }}
QScrollBar::handle:vertical:hover {{ background: {GS_ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{ background: {GS_BG0}; height: 5px; border-radius: 2px; margin: 0px; }}
QScrollBar::handle:horizontal {{ background: {GS_BG5}; border-radius: 2px; min-width: 20px; }}
QScrollBar::handle:horizontal:hover {{ background: {GS_ACCENT}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QPushButton {{
    background-color: {GS_BG4}; color: {GS_FG1};
    border: 1px solid {GS_BORDER2}; border-radius: 3px; padding: 6px 14px;
    font-weight: 600; font-size: 11px;
}}
QPushButton:hover {{ background-color: {GS_BG5}; border-color: {GS_ACCENT2}; color: {GS_FG0}; }}
QPushButton:pressed {{ background-color: {GS_BG3}; }}
QPushButton:disabled {{ color: {GS_FG2}; border-color: {GS_BORDER}; background-color: {GS_BG2}; }}
QPushButton#btn_buy {{ background-color: {GS_BG5}; border: 1px solid {GS_ACCENT2}; color: {GS_FG0}; font-weight: 700; font-size: 13px; }}
QPushButton#btn_buy:hover {{ background-color: {GS_ACCENT2}; color: {GS_BG0}; }}
QPushButton#btn_sell {{ background-color: {GS_BG3}; border: 1px solid {GS_FG2}; color: {GS_FG1}; font-weight: 700; font-size: 13px; }}
QPushButton#btn_sell:hover {{ background-color: {GS_BG4}; border-color: {GS_FG1}; color: {GS_FG0}; }}
QPushButton#btn_primary {{ background-color: {GS_BG4}; border: 1px solid {GS_ACCENT}; color: {GS_ACCENT}; font-weight: 700; }}
QPushButton#btn_primary:hover {{ background-color: {GS_BG5}; border-color: {GS_FG0}; }}
QPushButton#btn_danger {{ background-color: {GS_BG3}; border-color: {GS_FG2}; color: {GS_FG1}; }}
QPushButton#nav_btn {{
    background: transparent; border: none; border-radius: 3px;
    color: {GS_FG2}; font-size: 10px; font-weight: 600; text-align: center; padding: 10px 4px;
}}
QPushButton#nav_btn:hover {{ background: {GS_BG3}; color: {GS_FG1}; }}
QPushButton#nav_btn[active="true"] {{
    background: {GS_BG4}; color: {GS_FG0};
    border-left: 2px solid {GS_ACCENT}; border-radius: 0px 3px 3px 0px;
}}
QLineEdit, QDoubleSpinBox, QSpinBox, QTextEdit, QPlainTextEdit {{
    background-color: {GS_BG3}; color: {GS_FG0};
    border: 1px solid {GS_BORDER2}; border-radius: 3px; padding: 5px 8px;
    selection-background-color: {GS_ACCENT}44;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {GS_ACCENT}; background-color: {GS_BG4}; }}
QComboBox {{ background-color: {GS_BG3}; color: {GS_FG0}; border: 1px solid {GS_BORDER2}; border-radius: 3px; padding: 5px 8px; }}
QComboBox:focus {{ border-color: {GS_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; background: transparent; }}
QComboBox QAbstractItemView {{ background-color: {GS_BG3}; color: {GS_FG0}; border: 1px solid {GS_BORDER2}; selection-background-color: {GS_BG4}; selection-color: {GS_FG0}; }}
QTableWidget, QTableView {{
    background-color: {GS_BG2}; color: {GS_FG0};
    gridline-color: {GS_BORDER}; border: 1px solid {GS_BORDER};
    border-radius: 3px; font-size: 11px; alternate-background-color: {GS_BG3};
}}
QTableWidget::item, QTableView::item {{ padding: 3px 6px; border: none; }}
QTableWidget::item:selected, QTableView::item:selected {{ background-color: {GS_BG4}; color: {GS_FG0}; }}
QHeaderView::section {{
    background-color: {GS_BG0}; color: {GS_FG2};
    border: none; border-bottom: 1px solid {GS_BORDER};
    padding: 4px 6px; font-weight: 700; font-size: 10px; text-transform: uppercase;
}}
QGroupBox {{
    border: 1px solid {GS_BORDER}; border-radius: 4px; margin-top: 16px;
    padding: 12px 8px 8px; font-weight: 600; color: {GS_FG1}; background-color: {GS_BG2};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left; left: 12px; top: -8px;
    padding: 1px 6px; background-color: {GS_BG2}; color: {GS_FG1};
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    border: 1px solid {GS_BORDER}; border-radius: 3px;
}}
QProgressBar {{
    background-color: {GS_BG4}; border: 1px solid {GS_BORDER}; border-radius: 3px; height: 8px; color: transparent;
}}
QProgressBar::chunk {{ background-color: {GS_ACCENT2}; border-radius: 2px; }}
QCheckBox {{ color: {GS_FG0}; spacing: 8px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 2px; border: 1px solid {GS_BORDER2}; background: {GS_BG4}; }}
QCheckBox::indicator:hover {{ border-color: {GS_ACCENT}; }}
QCheckBox::indicator:checked {{ background-color: {GS_ACCENT}; border-color: {GS_ACCENT}; }}
QStatusBar {{ background-color: {GS_BG0}; color: {GS_FG2}; border-top: 1px solid {GS_BORDER}; font-size: 10px; }}
QDockWidget::title {{ background: {GS_BG0}; border-bottom: 1px solid {GS_BORDER}; padding: 5px 10px; color: {GS_FG1}; text-transform: uppercase; font-size: 10px; }}
QToolTip {{ background-color: {GS_BG5}; color: {GS_FG0}; border: 1px solid {GS_BORDER2}; border-radius: 3px; padding: 5px 8px; font-size: 11px; }}
QLabel#label_price {{ font-size: 24px; font-weight: 700; color: {GS_FG0}; }}
QLabel#label_change_pos {{ font-size: 13px; font-weight: 600; color: {GS_BUY}; }}
QLabel#label_change_neg {{ font-size: 13px; font-weight: 600; color: {GS_SELL}; }}
QLabel#label_section {{ font-size: 9px; font-weight: 700; color: {GS_FG2}; text-transform: uppercase; }}
QLabel#label_value_green {{ color: {GS_BUY}; font-weight: 600; }}
QLabel#label_value_red {{ color: {GS_SELL}; font-weight: 600; }}
QLabel#label_value_yellow {{ color: {GS_WARN}; font-weight: 600; }}
QLabel#label_accent {{ color: {GS_ACCENT}; font-weight: 700; }}
QLabel#label_muted {{ color: {GS_FG2}; font-size: 11px; }}
"""


# ── Invert BitNFloat Theme — Light charcoal inversion ─────────────────────────
# Inverts BNF: light beige/cream backgrounds, dark amber-tinted text.

IBF_BG0    = "#F5F0E8"   # lightest — deepest background (inverted)
IBF_BG1    = "#EDE8DC"
IBF_BG2    = "#E5E0D4"
IBF_BG3    = "#DDD8CC"
IBF_BG4    = "#D5D0C4"
IBF_BG5    = "#CDCABC"

IBF_ACCENT  = "#B06000"  # dark amber
IBF_ACCENT2 = "#884800"
IBF_BUY     = "#286820"  # dark forest green
IBF_SELL    = "#CC2020"  # standard dark red
IBF_WARN    = "#887000"

IBF_BORDER  = "#C8C4B8"
IBF_BORDER2 = "#B8B4A8"

IBF_FG0 = "#1A1510"   # near-black
IBF_FG1 = "#605850"   # secondary dark
IBF_FG2 = "#908880"   # disabled
IBF_GLOW = "#B0600033"

INVERT_BNF_THEME = f"""
/* ══════════════════════════════════════════════════════════════════════
   INVERT BITNFLOAT THEME — Light inversion of the BitNFloat charcoal theme
   ══════════════════════════════════════════════════════════════════════ */
* {{ outline: none; }}
QWidget {{
    background-color: {IBF_BG1}; color: {IBF_FG0};
    font-family: "Consolas", "JetBrains Mono", "Courier New", monospace;
    font-size: 12px;
}}
QMainWindow {{ background-color: {IBF_BG0}; }}
QDialog {{ background-color: {IBF_BG2}; border: 1px solid {IBF_BORDER2}; border-radius: 6px; }}
QMenuBar {{ background-color: {IBF_BG0}; color: {IBF_FG1}; border-bottom: 1px solid {IBF_BORDER}; padding: 2px 8px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 3px; }}
QMenuBar::item:selected {{ background-color: {IBF_GLOW}; color: {IBF_ACCENT}; }}
QMenu {{ background-color: {IBF_BG3}; color: {IBF_FG0}; border: 1px solid {IBF_BORDER2}; border-radius: 4px; padding: 4px 2px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 2px; margin: 1px 4px; }}
QMenu::item:selected {{ background-color: {IBF_ACCENT}22; color: {IBF_ACCENT}; }}
QMenu::separator {{ height: 1px; background: {IBF_BORDER}; margin: 4px 12px; }}
QTabWidget::pane {{ border: 1px solid {IBF_BORDER}; background-color: {IBF_BG2}; }}
QTabBar::tab {{ background-color: {IBF_BG3}; color: {IBF_FG2}; padding: 6px 16px; border: 1px solid {IBF_BORDER}; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; font-size: 11px; font-weight: 600; }}
QTabBar::tab:selected {{ background-color: {IBF_BG2}; color: {IBF_ACCENT}; border-bottom: 2px solid {IBF_ACCENT}; }}
QTabBar::tab:hover:!selected {{ background-color: {IBF_BG4}; color: {IBF_FG1}; }}
QSplitter::handle {{ background-color: {IBF_BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background-color: {IBF_ACCENT}; }}
QScrollBar:vertical {{ background: {IBF_BG0}; width: 6px; border-radius: 3px; margin: 0px; }}
QScrollBar::handle:vertical {{ background: {IBF_BG5}; border-radius: 3px; min-height: 20px; }}
QScrollBar::handle:vertical:hover {{ background: {IBF_ACCENT}88; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{ background: {IBF_BG0}; height: 6px; border-radius: 3px; margin: 0px; }}
QScrollBar::handle:horizontal {{ background: {IBF_BG5}; border-radius: 3px; min-width: 20px; }}
QScrollBar::handle:horizontal:hover {{ background: {IBF_ACCENT}88; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QPushButton {{ background-color: {IBF_BG4}; color: {IBF_FG1}; border: 1px solid {IBF_BORDER2}; border-radius: 3px; padding: 6px 14px; font-weight: 600; font-size: 11px; }}
QPushButton:hover {{ background-color: {IBF_ACCENT}22; border-color: {IBF_ACCENT}; color: {IBF_ACCENT}; }}
QPushButton:pressed {{ background-color: {IBF_ACCENT}33; }}
QPushButton:disabled {{ color: {IBF_FG2}; border-color: {IBF_BORDER}; background-color: {IBF_BG2}; }}
QPushButton#btn_buy {{ background-color: {IBF_BUY}15; border: 1px solid {IBF_BUY}88; color: {IBF_BUY}; font-weight: 700; font-size: 13px; }}
QPushButton#btn_buy:hover {{ background-color: {IBF_BUY}30; border-color: {IBF_BUY}; }}
QPushButton#btn_sell {{ background-color: {IBF_SELL}15; border: 1px solid {IBF_SELL}88; color: {IBF_SELL}; font-weight: 700; font-size: 13px; }}
QPushButton#btn_sell:hover {{ background-color: {IBF_SELL}30; border-color: {IBF_SELL}; }}
QPushButton#btn_primary {{ background-color: {IBF_ACCENT}18; border: 1px solid {IBF_ACCENT}88; color: {IBF_ACCENT}; font-weight: 700; }}
QPushButton#btn_primary:hover {{ background-color: {IBF_ACCENT}30; border-color: {IBF_ACCENT}; }}
QPushButton#btn_danger {{ background-color: {IBF_SELL}15; border-color: {IBF_SELL}88; color: {IBF_SELL}; }}
QPushButton#nav_btn {{ background: transparent; border: none; border-radius: 3px; color: {IBF_FG2}; font-size: 10px; font-weight: 600; text-align: center; padding: 10px 4px; }}
QPushButton#nav_btn:hover {{ background: {IBF_GLOW}; color: {IBF_FG1}; }}
QPushButton#nav_btn[active="true"] {{ background: {IBF_ACCENT}15; color: {IBF_ACCENT}; border-left: 2px solid {IBF_ACCENT}; border-radius: 0px 3px 3px 0px; }}
QLineEdit, QDoubleSpinBox, QSpinBox, QTextEdit, QPlainTextEdit {{ background-color: {IBF_BG0}; color: {IBF_FG0}; border: 1px solid {IBF_BORDER2}; border-radius: 3px; padding: 5px 8px; selection-background-color: {IBF_ACCENT}44; }}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {IBF_ACCENT}; background-color: {IBF_BG1}; }}
QComboBox {{ background-color: {IBF_BG0}; color: {IBF_FG0}; border: 1px solid {IBF_BORDER2}; border-radius: 3px; padding: 5px 8px; }}
QComboBox:focus {{ border-color: {IBF_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; background: transparent; }}
QComboBox QAbstractItemView {{ background-color: {IBF_BG3}; color: {IBF_FG0}; border: 1px solid {IBF_BORDER2}; selection-background-color: {IBF_ACCENT}22; selection-color: {IBF_ACCENT}; }}
QTableWidget, QTableView {{ background-color: {IBF_BG2}; color: {IBF_FG0}; gridline-color: {IBF_BORDER}; border: 1px solid {IBF_BORDER}; border-radius: 3px; font-size: 11px; alternate-background-color: {IBF_BG3}; }}
QTableWidget::item, QTableView::item {{ padding: 3px 6px; border: none; }}
QTableWidget::item:selected, QTableView::item:selected {{ background-color: {IBF_ACCENT}22; color: {IBF_ACCENT}; }}
QHeaderView::section {{ background-color: {IBF_BG0}; color: {IBF_FG2}; border: none; border-bottom: 1px solid {IBF_BORDER}; padding: 4px 6px; font-weight: 700; font-size: 10px; text-transform: uppercase; }}
QGroupBox {{ border: 1px solid {IBF_BORDER}; border-radius: 4px; margin-top: 16px; padding: 12px 8px 8px; font-weight: 600; color: {IBF_FG1}; background-color: {IBF_BG2}; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 12px; top: -8px; padding: 1px 6px; background-color: {IBF_BG2}; color: {IBF_ACCENT}; font-size: 10px; font-weight: 700; text-transform: uppercase; border: 1px solid {IBF_BORDER}; border-radius: 3px; }}
QProgressBar {{ background-color: {IBF_BG4}; border: 1px solid {IBF_BORDER}; border-radius: 3px; height: 8px; color: transparent; }}
QProgressBar::chunk {{ background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {IBF_ACCENT2}, stop:1 {IBF_ACCENT}); border-radius: 2px; }}
QCheckBox {{ color: {IBF_FG0}; spacing: 8px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 2px; border: 1px solid {IBF_BORDER2}; background: {IBF_BG4}; }}
QCheckBox::indicator:hover {{ border-color: {IBF_ACCENT}; }}
QCheckBox::indicator:checked {{ background-color: {IBF_ACCENT}; border-color: {IBF_ACCENT}; }}
QStatusBar {{ background-color: {IBF_BG0}; color: {IBF_FG2}; border-top: 1px solid {IBF_BORDER}; font-size: 10px; }}
QDockWidget::title {{ background: {IBF_BG0}; border-bottom: 1px solid {IBF_BORDER}; padding: 5px 10px; color: {IBF_ACCENT}; text-transform: uppercase; font-size: 10px; }}
QToolTip {{ background-color: {IBF_BG5}; color: {IBF_FG0}; border: 1px solid {IBF_BORDER2}; border-radius: 3px; padding: 5px 8px; font-size: 11px; }}
QLabel#label_price {{ font-size: 24px; font-weight: 700; color: {IBF_FG0}; }}
QLabel#label_change_pos {{ font-size: 13px; font-weight: 600; color: {IBF_BUY}; }}
QLabel#label_change_neg {{ font-size: 13px; font-weight: 600; color: {IBF_SELL}; }}
QLabel#label_section {{ font-size: 9px; font-weight: 700; color: {IBF_FG2}; text-transform: uppercase; }}
QLabel#label_value_green {{ color: {IBF_BUY}; font-weight: 600; }}
QLabel#label_value_red {{ color: {IBF_SELL}; font-weight: 600; }}
QLabel#label_value_yellow {{ color: {IBF_WARN}; font-weight: 600; }}
QLabel#label_accent {{ color: {IBF_ACCENT}; font-weight: 700; }}
QLabel#label_muted {{ color: {IBF_FG2}; font-size: 11px; }}
"""


def _apply_greyskill_theme(app) -> None:
    """Apply Grey Skill monochrome theme."""
    from PyQt6.QtGui import QPalette, QColor, QFont

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(GS_BG1))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(GS_FG0))
    palette.setColor(QPalette.ColorRole.Base,            QColor(GS_BG2))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(GS_BG3))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(GS_BG5))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(GS_FG0))
    palette.setColor(QPalette.ColorRole.Text,            QColor(GS_FG0))
    palette.setColor(QPalette.ColorRole.Button,          QColor(GS_BG3))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(GS_FG0))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor(GS_ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(GS_ACCENT + "33"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(GS_ACCENT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(GS_FG2))
    palette.setColor(QPalette.ColorRole.Dark,            QColor(GS_BG0))
    palette.setColor(QPalette.ColorRole.Mid,             QColor(GS_BG3))
    palette.setColor(QPalette.ColorRole.Midlight,        QColor(GS_BG4))
    app.setPalette(palette)

    font = QFont()
    for name in ("Consolas", "JetBrains Mono", "Courier New"):
        font.setFamily(name)
        if font.exactMatch():
            break
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(GREYSKILL_THEME)


def _apply_invert_bitnfloat_theme(app) -> None:
    """Apply Invert BitNFloat light theme."""
    from PyQt6.QtGui import QPalette, QColor, QFont

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(IBF_BG1))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(IBF_FG0))
    palette.setColor(QPalette.ColorRole.Base,            QColor(IBF_BG0))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(IBF_BG2))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(IBF_BG5))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(IBF_FG0))
    palette.setColor(QPalette.ColorRole.Text,            QColor(IBF_FG0))
    palette.setColor(QPalette.ColorRole.Button,          QColor(IBF_BG3))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(IBF_FG0))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor(IBF_ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(IBF_ACCENT + "33"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(IBF_ACCENT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(IBF_FG2))
    palette.setColor(QPalette.ColorRole.Dark,            QColor(IBF_BG5))
    palette.setColor(QPalette.ColorRole.Mid,             QColor(IBF_BG3))
    palette.setColor(QPalette.ColorRole.Midlight,        QColor(IBF_BG4))
    app.setPalette(palette)

    font = QFont()
    for name in ("Consolas", "JetBrains Mono", "Courier New"):
        font.setFamily(name)
        if font.exactMatch():
            break
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(INVERT_BNF_THEME)
