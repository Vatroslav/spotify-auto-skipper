"""
Centralized dark Spotify theme for PySide6.

Uses Qt Fusion style + dark QPalette as base, then applies QSS
for fine-grained control over borders, accent colors, and custom widgets.
"""

import os
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

from spotify_auto_skipper.utils import resource_path

# -----------------------------------------------------------------
# Colour palette (matches Figma design)
# -----------------------------------------------------------------

BG_MAIN = "#121212"
BG_HEADER = "#1a1a1a"
BG_INPUT = "#282828"
BG_HOVER = "#333333"

TEXT_PRIMARY = "#FFFFFF"
TEXT_SECONDARY = "#a0a0a0"
TEXT_MUTED = "#6B7280"

BORDER_PRIMARY = "#404040"
BORDER_SECONDARY = "#333333"

ACCENT = "#1DB954"
ACCENT_HOVER = "#1ed760"

REMOVE_FG = "#666666"
REMOVE_HOVER = "#ff4444"

PLACEHOLDER_COLOR = (80, 80, 80)

# Status feedback colours (readable on dark bg)
COLOR_SUCCESS = "#4ade80"
COLOR_WARNING = "#fb923c"
COLOR_ERROR = "#f87171"


# -----------------------------------------------------------------
# QSS stylesheet
# -----------------------------------------------------------------

def _build_stylesheet():
    # QSS url() needs forward slashes, even on Windows
    checkbox_checked = resource_path("assets/checkbox_checked.png").replace("\\", "/")
    return f"""
    /* ===== Global ===== */
    QWidget {{
        font-family: "Segoe UI";
        font-size: 13pt;
    }}

    /* ===== Inputs ===== */
    QLineEdit, QSpinBox {{
        background-color: {BG_INPUT};
        border: 1px solid {BORDER_PRIMARY};
        border-radius: 4px;
        padding: 6px 12px;
        color: {TEXT_PRIMARY};
        font-size: 13pt;
        selection-background-color: {ACCENT};
    }}

    QLineEdit:focus, QSpinBox:focus {{
        border-color: {ACCENT};
    }}

    QSpinBox::up-button, QSpinBox::down-button {{
        width: 0;
        height: 0;
        border: none;
    }}

    /* ===== Buttons ===== */
    QPushButton {{
        background-color: {BG_INPUT};
        border: 1px solid {BORDER_PRIMARY};
        border-radius: 4px;
        padding: 7px 16px;
        color: {TEXT_PRIMARY};
        font-size: 13pt;
    }}

    QPushButton:hover {{
        border-color: {ACCENT};
    }}

    QPushButton:pressed {{
        background-color: {BG_HOVER};
    }}

    QPushButton:disabled {{
        color: {TEXT_MUTED};
    }}

    AccentButton {{
        background-color: {ACCENT};
        border: 1px solid {ACCENT};
        color: white;
        font-weight: 500;
        padding: 8px 24px;
        font-size: 13pt;
    }}

    AccentButton:hover {{
        background-color: {ACCENT_HOVER};
        border-color: {ACCENT_HOVER};
    }}

    AccentButton:pressed {{
        background-color: {ACCENT};
    }}

    /* ===== Checkboxes ===== */
    QCheckBox {{
        spacing: 12px;
        font-size: 13pt;
    }}

    QCheckBox::indicator {{
        width: 19px;
        height: 19px;
        border: 1px solid {BORDER_PRIMARY};
        border-radius: 3px;
        background-color: {BG_INPUT};
    }}

    QCheckBox::indicator:checked {{
        image: url({checkbox_checked});
        border: none;
    }}

    QCheckBox::indicator:hover {{
        border-color: {ACCENT};
    }}

    /* ===== Tab Widget ===== */
    QTabWidget::pane {{
        border: none;
        border-top: 1px solid {BORDER_SECONDARY};
    }}

    QTabBar {{
        background-color: {BG_HEADER};
    }}

    QTabBar::tab {{
        background-color: {BG_HEADER};
        color: {TEXT_SECONDARY};
        padding: 12px 16px;
        border: none;
        border-bottom: 2px solid transparent;
        font-size: 13pt;
    }}

    QTabBar::tab:selected {{
        color: {TEXT_PRIMARY};
        border-bottom-color: {ACCENT};
    }}

    QTabBar::tab:hover:!selected {{
        color: {TEXT_PRIMARY};
    }}

    /* ===== Scrollbar ===== */
    QScrollArea {{
        border: none;
    }}

    QScrollBar:vertical {{
        background: {BG_MAIN};
        width: 8px;
        margin: 0;
    }}

    QScrollBar::handle:vertical {{
        background: {BG_INPUT};
        border-radius: 4px;
        min-height: 20px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {BG_HOVER};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
        height: 0;
    }}

    /* ===== Group Box (wizard guide frames) ===== */
    QGroupBox {{
        border: 1px solid {BORDER_PRIMARY};
        border-radius: 4px;
        margin-top: 1.2em;
        padding-top: 0.8em;
        font-weight: bold;
        font-size: 11pt;
    }}

    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
    }}

    /* ===== Artist Cards ===== */
    ArtistCard {{
        background-color: transparent;
        border: none;
        border-radius: 4px;
    }}

    ArtistCard:hover {{
        background-color: {BG_INPUT};
    }}

    ArtistCard QLabel {{
        background: transparent;
    }}

    ArtistCard #artist_name {{
        font-weight: 500;
        font-size: 13pt;
    }}

    ArtistCard #artist_info {{
        color: {TEXT_SECONDARY};
        font-size: 11pt;
    }}

    ArtistCard #remove_btn {{
        background: transparent;
        border: none;
        color: transparent;
        font-size: 14pt;
        padding: 0;
    }}

    ArtistCard:hover #remove_btn {{
        color: {REMOVE_FG};
    }}

    ArtistCard:hover #remove_btn:hover {{
        color: {REMOVE_HOVER};
    }}

    /* ===== Dialogs ===== */
    QDialog {{
        background-color: {BG_INPUT};
    }}

    /* ===== Search result rows ===== */
    SearchResultRow {{
        background-color: transparent;
        border: none;
        border-radius: 4px;
    }}

    SearchResultRow QLabel {{
        background: transparent;
    }}

    SearchResultRow[selected="true"] {{
        background-color: {BG_HOVER};
        border: 1px solid {ACCENT};
    }}

    SearchResultRow:hover {{
        background-color: {BG_HOVER};
    }}
    """


# -----------------------------------------------------------------
# Theme application
# -----------------------------------------------------------------

def apply_theme(app):
    """Apply dark Spotify theme to the QApplication."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_MAIN))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_INPUT))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_HEADER))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor(BG_INPUT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG_INPUT))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT_PRIMARY))
    app.setPalette(palette)

    app.setStyleSheet(_build_stylesheet())


def ensure_app():
    """Get or create QApplication with dark theme applied."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        apply_theme(app)
    return app
