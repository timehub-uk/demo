"""
BinanceML Pro – SVG Icon System

All icons are defined as inline SVG strings and rendered into QIcon objects
via QPixmap + QPainter + QSvgRenderer. This ensures crisp, resolution-
independent rendering on all screens including HiDPI/Retina displays.

Usage:
    from ui.icons import icon, svg_icon
    button.setIcon(icon("trading", color="#00D4FF", size=22))
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSize, QByteArray, QRectF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtSvg import QSvgRenderer


# ── SVG definitions ───────────────────────────────────────────────────────────
# All icons are 24×24 viewBox. Color is injected as `{color}`.

_SVGS: dict[str, str] = {

    # ── Navigation ────────────────────────────────────────────────────────────

    "trading": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <rect x="3" y="3" width="18" height="18" rx="2" stroke="{color}" stroke-width="1.5"/>
  <polyline points="7,14 10,10 13,13 17,8" stroke="{color}" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round" fill="none"/>
  <line x1="7" y1="17" x2="17" y2="17" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
</svg>""",

    "autotrader": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <circle cx="12" cy="8" r="3" stroke="{color}" stroke-width="1.5"/>
  <path d="M6 20v-1a6 6 0 0 1 12 0v1" stroke="{color}" stroke-width="1.5"
        stroke-linecap="round"/>
  <circle cx="19" cy="6" r="2" fill="{color}" opacity="0.9"/>
  <line x1="19" y1="4" x2="19" y2="2" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="21" y1="6" x2="23" y2="6" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="19.7" y1="4.3" x2="21.1" y2="2.9" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
</svg>""",

    "ml": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <circle cx="12" cy="5"  r="2" stroke="{color}" stroke-width="1.5"/>
  <circle cx="5"  cy="17" r="2" stroke="{color}" stroke-width="1.5"/>
  <circle cx="19" cy="17" r="2" stroke="{color}" stroke-width="1.5"/>
  <circle cx="12" cy="12" r="2.5" fill="{color}" opacity="0.85"/>
  <line x1="12" y1="7"  x2="12" y2="9.5"  stroke="{color}" stroke-width="1.2" stroke-linecap="round"/>
  <line x1="7"  y1="16" x2="10" y2="13.5" stroke="{color}" stroke-width="1.2" stroke-linecap="round"/>
  <line x1="17" y1="16" x2="14" y2="13.5" stroke="{color}" stroke-width="1.2" stroke-linecap="round"/>
</svg>""",

    "risk": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <polygon points="12,3 22,21 2,21" stroke="{color}" stroke-width="1.5"
           stroke-linejoin="round" fill="{color}" fill-opacity="0.12"/>
  <line x1="12" y1="10" x2="12" y2="15" stroke="{color}" stroke-width="2"
        stroke-linecap="round"/>
  <circle cx="12" cy="18" r="1" fill="{color}"/>
</svg>""",

    "connections": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <circle cx="5"  cy="12" r="2.5" stroke="{color}" stroke-width="1.5"/>
  <circle cx="19" cy="5"  r="2.5" stroke="{color}" stroke-width="1.5"/>
  <circle cx="19" cy="19" r="2.5" stroke="{color}" stroke-width="1.5"/>
  <line x1="7.5" y1="11" x2="16.5" y2="6.5"  stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="7.5" y1="13" x2="16.5" y2="17.5" stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
</svg>""",

    "settings": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <circle cx="12" cy="12" r="3.5" stroke="{color}" stroke-width="1.5"/>
  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"
        stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",

    "help": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <circle cx="12" cy="12" r="9" stroke="{color}" stroke-width="1.5"/>
  <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" stroke="{color}" stroke-width="1.5"
        stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="12" cy="17" r="0.8" fill="{color}"/>
</svg>""",

    # ── Status / Connection ────────────────────────────────────────────────────

    "dot_green": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <circle cx="12" cy="12" r="5" fill="#00E676"/>
  <circle cx="12" cy="12" r="8" fill="#00E67633"/>
</svg>""",

    "dot_red": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <circle cx="12" cy="12" r="5" fill="#FF1744"/>
  <circle cx="12" cy="12" r="8" fill="#FF174433"/>
</svg>""",

    "dot_yellow": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <circle cx="12" cy="12" r="5" fill="#FFD740"/>
  <circle cx="12" cy="12" r="8" fill="#FFD74033"/>
</svg>""",

    "dot_grey": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <circle cx="12" cy="12" r="5" fill="#44446A"/>
</svg>""",

    # ── Actions ───────────────────────────────────────────────────────────────

    "buy": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <polyline points="18,15 12,9 6,15" stroke="{color}" stroke-width="2.5"
            stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",

    "sell": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <polyline points="6,9 12,15 18,9" stroke="{color}" stroke-width="2.5"
            stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",

    "scan": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <circle cx="11" cy="11" r="7" stroke="{color}" stroke-width="1.5"/>
  <line x1="16.5" y1="16.5" x2="21" y2="21" stroke="{color}" stroke-width="2"
        stroke-linecap="round"/>
  <line x1="11" y1="8" x2="11" y2="14" stroke="{color}" stroke-width="1.5"
        stroke-linecap="round"/>
  <line x1="8" y1="11" x2="14" y2="11" stroke="{color}" stroke-width="1.5"
        stroke-linecap="round"/>
</svg>""",

    "target": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <circle cx="12" cy="12" r="9" stroke="{color}" stroke-width="1.5"/>
  <circle cx="12" cy="12" r="5" stroke="{color}" stroke-width="1.5"/>
  <circle cx="12" cy="12" r="1.5" fill="{color}"/>
  <line x1="12" y1="2"  x2="12" y2="5"  stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="12" y1="19" x2="12" y2="22" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="2"  y1="12" x2="5"  y2="12" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="19" y1="12" x2="22" y2="12" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
</svg>""",

    "stop": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <rect x="4" y="4" width="16" height="16" rx="3" stroke="{color}" stroke-width="1.5"
        fill="{color}" fill-opacity="0.2"/>
</svg>""",

    "play": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <polygon points="6,4 20,12 6,20" fill="{color}" fill-opacity="0.9"
           stroke="{color}" stroke-width="1" stroke-linejoin="round"/>
</svg>""",

    "exit": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" stroke="{color}" stroke-width="1.5"
        stroke-linecap="round"/>
  <polyline points="16,17 21,12 16,7" stroke="{color}" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="21" y1="12" x2="9" y2="12" stroke="{color}" stroke-width="1.5"
        stroke-linecap="round"/>
</svg>""",

    "refresh": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <polyline points="23,4 23,10 17,10" stroke="{color}" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" stroke="{color}" stroke-width="1.5"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",

    "close": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <line x1="18" y1="6" x2="6" y2="18" stroke="{color}" stroke-width="2"
        stroke-linecap="round"/>
  <line x1="6" y1="6" x2="18" y2="18" stroke="{color}" stroke-width="2"
        stroke-linecap="round"/>
</svg>""",

    "copy": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <rect x="9" y="9" width="13" height="13" rx="2" stroke="{color}" stroke-width="1.5"/>
  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"
        stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
</svg>""",

    "save": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"
        stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>
  <polyline points="17,21 17,13 7,13 7,21" stroke="{color}" stroke-width="1.5"
            stroke-linejoin="round"/>
  <polyline points="7,3 7,8 15,8" stroke="{color}" stroke-width="1.5"
            stroke-linejoin="round"/>
</svg>""",

    # ── Finance / data ────────────────────────────────────────────────────────

    "chart": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <rect x="2" y="14" width="4" height="7" rx="1" fill="{color}" fill-opacity="0.8"/>
  <rect x="8" y="9"  width="4" height="12" rx="1" fill="{color}"/>
  <rect x="14" y="5" width="4" height="16" rx="1" fill="{color}" fill-opacity="0.8"/>
  <rect x="20" y="11" width="2" height="10" rx="1" fill="{color}" fill-opacity="0.6"/>
</svg>""",

    "wallet": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <path d="M21 8H3a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h18a1 1 0 0 0 1-1V9a1 1 0 0 0-1-1z"
        stroke="{color}" stroke-width="1.5"/>
  <path d="M3 8V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2" stroke="{color}" stroke-width="1.5"/>
  <circle cx="17" cy="14" r="1.5" fill="{color}"/>
</svg>""",

    "bolt": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <polygon points="13,2 3,14 12,14 11,22 21,10 12,10 13,2" fill="{color}" fill-opacity="0.85"
           stroke="{color}" stroke-width="1" stroke-linejoin="round"/>
</svg>""",

    "brain": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <path d="M12 5C8.5 5 6 7 6 10c0 1.5.5 2.5 1 3.5C5.5 14 5 15 5 16.5 5 19 7 21 9 21h6c2 0 4-2 4-4.5 0-1.5-.5-2.5-2-3C17.5 12.5 18 11.5 18 10c0-3-2.5-5-6-5z"
        stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>
  <line x1="12" y1="5"  x2="12" y2="21" stroke="{color}" stroke-width="1" stroke-dasharray="2,2"/>
  <path d="M9 10 C9.5 9 10.5 8.5 12 8.5" stroke="{color}" stroke-width="1" stroke-linecap="round"/>
  <path d="M9 15 C9.5 14 10.5 13.5 12 13.5" stroke="{color}" stroke-width="1" stroke-linecap="round"/>
</svg>""",

    "plug": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <path d="M18 8h-1V3H7v5H6a2 2 0 0 0-2 2v4a8 8 0 0 0 8 8 8 8 0 0 0 8-8v-4a2 2 0 0 0-2-2z"
        stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>
  <line x1="10" y1="3"  x2="10" y2="8"  stroke="{color}" stroke-width="2" stroke-linecap="round"/>
  <line x1="14" y1="3"  x2="14" y2="8"  stroke="{color}" stroke-width="2" stroke-linecap="round"/>
</svg>""",

    "telegram": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <circle cx="12" cy="12" r="10" stroke="{color}" stroke-width="1.5"/>
  <path d="M8 12l2 2 4-4" stroke="{color}" stroke-width="1.5"
        stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M5 10l9.5-4 .5 9-4.5-2.5L8 14" stroke="{color}" stroke-width="1.3"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",

    "database": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <ellipse cx="12" cy="6" rx="8" ry="3" stroke="{color}" stroke-width="1.5"/>
  <path d="M4 6v6c0 1.66 3.58 3 8 3s8-1.34 8-3V6" stroke="{color}" stroke-width="1.5"/>
  <path d="M4 12v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6" stroke="{color}" stroke-width="1.5"/>
</svg>""",

    "redis": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <rect x="3" y="4" width="18" height="16" rx="2" stroke="{color}" stroke-width="1.5"/>
  <line x1="3" y1="9"  x2="21" y2="9"  stroke="{color}" stroke-width="1" stroke-dasharray="2,2"/>
  <line x1="3" y1="14" x2="21" y2="14" stroke="{color}" stroke-width="1" stroke-dasharray="2,2"/>
  <circle cx="7" cy="6.5" r="1" fill="{color}"/>
</svg>""",

    "api": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <polyline points="16,18 22,12 16,6" stroke="{color}" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round"/>
  <polyline points="8,6 2,12 8,18" stroke="{color}" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="14" y1="4" x2="10" y2="20" stroke="{color}" stroke-width="1.5"
        stroke-linecap="round"/>
</svg>""",

    "logo": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none">
  <!-- Hexagon frame -->
  <polygon points="16,2 28,9 28,23 16,30 4,23 4,9"
           stroke="{color}" stroke-width="1.5" fill="{color}" fill-opacity="0.1"/>
  <!-- Inner chart bars -->
  <rect x="9"  y="18" width="3" height="8"  rx="1" fill="{color}" opacity="0.7"/>
  <rect x="14" y="13" width="3" height="13" rx="1" fill="{color}"/>
  <rect x="19" y="15" width="3" height="11" rx="1" fill="{color}" opacity="0.7"/>
  <!-- Up trend line -->
  <polyline points="9,18 12.5,11 19.5,14 22,10"
            stroke="{color}" stroke-width="1.5" stroke-linecap="round"
            stroke-linejoin="round" fill="none"/>
</svg>""",

    "keyboard": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <rect x="2" y="6" width="20" height="13" rx="2" stroke="{color}" stroke-width="1.5"/>
  <line x1="6"  y1="10" x2="6"  y2="10" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
  <line x1="10" y1="10" x2="10" y2="10" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
  <line x1="14" y1="10" x2="14" y2="10" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
  <line x1="18" y1="10" x2="18" y2="10" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
  <line x1="8"  y1="14" x2="16" y2="14" stroke="{color}" stroke-width="2" stroke-linecap="round"/>
</svg>""",

    "info": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <circle cx="12" cy="12" r="10" stroke="{color}" stroke-width="1.5"/>
  <line x1="12" y1="8" x2="12" y2="8" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="12" y1="12" x2="12" y2="16" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
</svg>""",
    # Bar-chart icon used for the Reports nav button
    "reports": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <rect x="3" y="12" width="4" height="9" rx="1" stroke="{color}" stroke-width="1.5"/>
  <rect x="10" y="7"  width="4" height="14" rx="1" stroke="{color}" stroke-width="1.5"/>
  <rect x="17" y="3"  width="4" height="18" rx="1" stroke="{color}" stroke-width="1.5"/>
  <line x1="2" y1="21" x2="22" y2="21" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
</svg>""",

    # ── Nav-specific icons (previously fell back to "info") ────────────────────

    "backtest": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <polyline points="1,4 1,10 7,10" stroke="{color}" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M3.51 15a9 9 0 1 0 .49-3" stroke="{color}" stroke-width="1.5"
        stroke-linecap="round" stroke-linejoin="round"/>
  <polyline points="12,7 12,12 15,14" stroke="{color}" stroke-width="1.5"
            stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",

    "journal": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" stroke="{color}" stroke-width="1.5"
        stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"
        stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>
  <line x1="9" y1="7"  x2="16" y2="7"  stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="9" y1="11" x2="16" y2="11" stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="9" y1="15" x2="13" y2="15" stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
</svg>""",

    "strategy": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <rect x="3"  y="3"  width="7" height="7" rx="1" stroke="{color}" stroke-width="1.5"/>
  <rect x="14" y="3"  width="7" height="7" rx="1" stroke="{color}" stroke-width="1.5"/>
  <rect x="14" y="14" width="7" height="7" rx="1" stroke="{color}" stroke-width="1.5"/>
  <rect x="3"  y="14" width="7" height="7" rx="1" stroke="{color}" stroke-width="1.5"/>
  <line x1="10"  y1="6.5"  x2="14"  y2="6.5"  stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="6.5" y1="10"   x2="6.5" y2="14"   stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="17.5" y1="10"  x2="17.5" y2="14"  stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="10"  y1="17.5" x2="14"  y2="17.5" stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
</svg>""",

    "simulation": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <circle cx="12" cy="12" r="9" stroke="{color}" stroke-width="1.5" stroke-dasharray="3,2"/>
  <circle cx="12" cy="12" r="4" stroke="{color}" stroke-width="1.5"/>
  <circle cx="12" cy="12" r="1.5" fill="{color}"/>
  <line x1="12" y1="3"  x2="12" y2="8"  stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="21" y1="12" x2="16" y2="12" stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="12" y1="21" x2="12" y2="16" stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="3"  y1="12" x2="8"  y2="12" stroke="{color}" stroke-width="1.3" stroke-linecap="round"/>
</svg>""",

    "mltools": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <circle cx="5"  cy="8"  r="2"   stroke="{color}" stroke-width="1.5"/>
  <circle cx="12" cy="5"  r="2"   stroke="{color}" stroke-width="1.5"/>
  <circle cx="19" cy="8"  r="2"   stroke="{color}" stroke-width="1.5"/>
  <circle cx="12" cy="12" r="2.5" fill="{color}" opacity="0.9"/>
  <circle cx="5"  cy="16" r="2"   stroke="{color}" stroke-width="1.5"/>
  <circle cx="19" cy="16" r="2"   stroke="{color}" stroke-width="1.5"/>
  <line x1="7"  y1="9"  x2="10" y2="11" stroke="{color}" stroke-width="1.2" stroke-linecap="round"/>
  <line x1="12" y1="7"  x2="12" y2="9.5" stroke="{color}" stroke-width="1.2" stroke-linecap="round"/>
  <line x1="17" y1="9"  x2="14" y2="11" stroke="{color}" stroke-width="1.2" stroke-linecap="round"/>
  <line x1="7"  y1="15" x2="10" y2="13" stroke="{color}" stroke-width="1.2" stroke-linecap="round"/>
  <line x1="17" y1="15" x2="14" y2="13" stroke="{color}" stroke-width="1.2" stroke-linecap="round"/>
</svg>""",

    "market": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"
        stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>
  <polyline points="9,22 9,12 15,12 15,22" stroke="{color}" stroke-width="1.5"
            stroke-linejoin="round"/>
  <circle cx="19" cy="6" r="3" fill="{color}" fill-opacity="0.9"/>
  <line x1="19" y1="4.5" x2="19" y2="7.5" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="17.5" y1="6" x2="20.5" y2="6" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
</svg>""",
}


# ── Renderer ──────────────────────────────────────────────────────────────────

def svg_icon(
    name: str,
    color: str = "#00D4FF",
    size: int = 20,
) -> QIcon:
    """
    Render an SVG icon by name and return a QIcon.

    Args:
        name:   Key into _SVGS dictionary.
        color:  Hex color string (e.g. "#00D4FF").
        size:   Output pixel size (square).
    """
    svg_src = _SVGS.get(name, _SVGS["info"])
    svg_data = svg_src.replace("{color}", color)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    renderer = QSvgRenderer(QByteArray(svg_data.encode()))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()

    return QIcon(pixmap)


def svg_pixmap(name: str, color: str = "#00D4FF", size: int = 20) -> QPixmap:
    """Same as svg_icon but returns a QPixmap."""
    svg_src = _SVGS.get(name, _SVGS["info"])
    svg_data = svg_src.replace("{color}", color)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    renderer = QSvgRenderer(QByteArray(svg_data.encode()))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def status_icon(connected: bool, warn: bool = False) -> QIcon:
    """Convenience: green/yellow/red dot based on state."""
    if connected:
        return svg_icon("dot_green", size=14)
    elif warn:
        return svg_icon("dot_yellow", size=14)
    else:
        return svg_icon("dot_red", size=14)
