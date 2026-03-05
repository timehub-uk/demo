"""
Professional dark trading platform theme for PyQt6.
Inspired by Bloomberg Terminal / TradingView dark mode.
"""

ACCENT = "#00D4FF"      # Cyan accent
GREEN  = "#00E676"      # Profit / buy
RED    = "#FF1744"      # Loss / sell
YELLOW = "#FFD740"      # Warning / neutral
BG0    = "#0A0A12"      # Deepest background
BG1    = "#0E0E1A"      # Main background
BG2    = "#141420"      # Panel background
BG3    = "#1A1A2E"      # Card / widget background
BG4    = "#252540"      # Input / table row alt
BORDER = "#2A2A45"      # Border colour
FG0    = "#E8E8F0"      # Primary text
FG1    = "#A0A0B8"      # Secondary text
FG2    = "#606080"      # Disabled text


DARK_THEME = f"""
/* ── Global ─────────────────────────────────────────────────────── */
QWidget {{
    background-color: {BG1};
    color: {FG0};
    font-family: "SF Pro Display", "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
    font-size: 13px;
}}
QMainWindow {{
    background-color: {BG0};
}}

/* ── Menu bar ────────────────────────────────────────────────────── */
QMenuBar {{
    background-color: {BG0};
    color: {FG0};
    border-bottom: 1px solid {BORDER};
    padding: 2px 6px;
}}
QMenuBar::item:selected {{
    background-color: {BG3};
    border-radius: 4px;
}}
QMenu {{
    background-color: {BG3};
    color: {FG0};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item:selected {{
    background-color: {ACCENT}22;
    color: {ACCENT};
    border-radius: 4px;
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 10px;
}}

/* ── Tab bar ─────────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {BG2};
    border-radius: 6px;
}}
QTabBar::tab {{
    background-color: {BG3};
    color: {FG1};
    padding: 8px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background-color: {BG2};
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    background-color: {BG4};
    color: {FG0};
}}

/* ── Splitter ────────────────────────────────────────────────────── */
QSplitter::handle {{
    background-color: {BORDER};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical   {{ height: 1px; }}

/* ── Scroll bars ─────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {BG2};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BG4};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: {FG2}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}
QScrollBar:horizontal {{
    background: {BG2};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {BG4};
    border-radius: 4px;
    min-width: 20px;
}}

/* ── Buttons ─────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {BG4};
    color: {FG0};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 18px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {BG3};
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:pressed {{
    background-color: {ACCENT}33;
}}
QPushButton#btn_buy {{
    background-color: {GREEN}22;
    border-color: {GREEN};
    color: {GREEN};
    font-weight: 700;
    font-size: 14px;
}}
QPushButton#btn_buy:hover {{
    background-color: {GREEN}44;
}}
QPushButton#btn_sell {{
    background-color: {RED}22;
    border-color: {RED};
    color: {RED};
    font-weight: 700;
    font-size: 14px;
}}
QPushButton#btn_sell:hover {{
    background-color: {RED}44;
}}
QPushButton#btn_cancel {{
    background-color: {YELLOW}22;
    border-color: {YELLOW};
    color: {YELLOW};
}}
QPushButton#btn_primary {{
    background-color: {ACCENT}33;
    border-color: {ACCENT};
    color: {ACCENT};
    font-weight: 600;
}}
QPushButton#btn_primary:hover {{
    background-color: {ACCENT}55;
}}
QPushButton:disabled {{
    color: {FG2};
    border-color: {BG4};
    background-color: {BG2};
}}

/* ── Line edits / Inputs ──────────────────────────────────────────── */
QLineEdit, QDoubleSpinBox, QSpinBox {{
    background-color: {BG3};
    color: {FG0};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 10px;
    selection-background-color: {ACCENT}55;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
    border-color: {ACCENT};
}}
QComboBox {{
    background-color: {BG3};
    color: {FG0};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 10px;
}}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG3};
    color: {FG0};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT}33;
}}

/* ── Tables ──────────────────────────────────────────────────────── */
QTableWidget, QTableView {{
    background-color: {BG2};
    color: {FG0};
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-size: 12px;
}}
QTableWidget::item, QTableView::item {{
    padding: 4px 8px;
    border: none;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {ACCENT}22;
    color: {ACCENT};
}}
QHeaderView::section {{
    background-color: {BG3};
    color: {FG1};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
    padding: 6px 8px;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* ── Labels ──────────────────────────────────────────────────────── */
QLabel#label_price {{
    font-size: 28px;
    font-weight: 700;
    color: {FG0};
}}
QLabel#label_change_pos {{
    font-size: 16px;
    font-weight: 600;
    color: {GREEN};
}}
QLabel#label_change_neg {{
    font-size: 16px;
    font-weight: 600;
    color: {RED};
}}
QLabel#label_section {{
    font-size: 11px;
    font-weight: 700;
    color: {FG2};
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QLabel#label_value_green {{
    color: {GREEN};
    font-weight: 600;
}}
QLabel#label_value_red {{
    color: {RED};
    font-weight: 600;
}}
QLabel#label_accent {{
    color: {ACCENT};
    font-weight: 600;
}}

/* ── Group boxes ─────────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 16px;
    padding: 12px 8px 8px;
    font-weight: 600;
    color: {FG1};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    top: -8px;
    padding: 0 6px;
    background-color: {BG2};
    color: {ACCENT};
    font-size: 11px;
    letter-spacing: 0.5px;
}}

/* ── Progress bar ────────────────────────────────────────────────── */
QProgressBar {{
    background-color: {BG3};
    border: 1px solid {BORDER};
    border-radius: 5px;
    height: 12px;
    text-align: center;
    color: {FG0};
    font-size: 11px;
}}
QProgressBar::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}99, stop:1 {ACCENT}
    );
    border-radius: 4px;
}}

/* ── Checkboxes ──────────────────────────────────────────────────── */
QCheckBox {{
    color: {FG0};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid {BORDER};
    background: {BG3};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* ── Status bar ──────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {BG0};
    color: {FG1};
    border-top: 1px solid {BORDER};
    font-size: 11px;
}}

/* ── Tool tips ───────────────────────────────────────────────────── */
QToolTip {{
    background-color: {BG3};
    color: {FG0};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
}}
"""


def apply_theme(app) -> None:
    """Apply dark trading theme to a QApplication."""
    from PyQt6.QtGui import QPalette, QColor
    from PyQt6.QtCore import Qt

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG1))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(FG0))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG2))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG3))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG3))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(FG0))
    palette.setColor(QPalette.ColorRole.Text, QColor(FG0))
    palette.setColor(QPalette.ColorRole.Button, QColor(BG3))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(FG0))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT + "44"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(FG2))
    app.setPalette(palette)
    app.setStyleSheet(DARK_THEME)
