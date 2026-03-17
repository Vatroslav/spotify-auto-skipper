"""
Logs tab widget for the Settings window.
Displays today's (or any day's) log file in a scrollable text area
with auto-refresh, date navigation, and utility buttons.
"""

import os
import subprocess
import threading
from datetime import date, datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QFrame, QScrollArea, QComboBox, QApplication,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QTextCursor

from spotify_auto_skipper.gui import theme
from spotify_auto_skipper.gui.widgets import create_separator


# Text-based markers for identifying core song-entry lines.
_SONG_TEXT = "Currently playing"
_SCROBBLE_TEXT = "Last scrobble"
_SKIPPED_TEXT = "\u2014 skipping"          # — skipping (not "skipping the check")
_SKIP_EXCLUDE = "skipping the check"
_KEPT_TEXT = "\u2014 not skipping"         # — not skipping
_WARNING_LINE = "\u26a0"                   # ⚠️
_ERROR_LINE = "\u274c"                     # ❌


def _split_into_blocks(text: str) -> list[list[str]]:
    """Split log text into blocks separated by blank lines."""
    blocks = []
    current = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _is_decision_line(line: str, decision_text: str) -> bool:
    """Check if a line is a real decision line (not 'skipping the check')."""
    if decision_text not in line:
        return False
    if decision_text == _SKIPPED_TEXT and _SKIP_EXCLUDE in line:
        return False
    return True


def _filter_song_blocks(text: str, decision_text: str) -> str:
    """Extract compact song entries: Currently playing + Last scrobble + decision.

    Only includes blocks that contain a real decision line.
    """
    blocks = _split_into_blocks(text)
    result = []
    for block in blocks:
        if not any(_is_decision_line(ln, decision_text) for ln in block):
            continue
        core = [
            ln for ln in block
            if _SONG_TEXT in ln or _SCROBBLE_TEXT in ln
            or _is_decision_line(ln, decision_text)
        ]
        if core:
            result.append("\n".join(core))
    return "\n\n".join(result)


def _filter_blocks_by_marker(text: str, marker: str) -> str:
    """Show full blocks that contain the marker."""
    blocks = _split_into_blocks(text)
    matched = [b for b in blocks if any(marker in ln for ln in b)]
    return "\n\n".join("\n".join(b) for b in matched)


class LogsTab(QWidget):
    """Self-contained Logs tab with date navigation, auto-refresh, and filtering."""

    _content_ready = Signal(str)  # log text payload

    def __init__(self, parent=None):
        super().__init__(parent)

        from spotify_auto_skipper import utils
        self._log_dir = utils.get_log_dir()

        self._available_dates = []
        self._current_index = -1
        self._last_size = -1  # track file size for smart refresh

        self._content_ready.connect(self._on_content_ready)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        self._build_date_nav(root)
        root.addWidget(create_separator())
        self._build_toolbar(root)
        self._build_log_view(root)

        # Auto-refresh every 5 seconds
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start(5000)

        # Initial load
        self._refresh_dates()

    # ── Date navigation ───────────────────────────────────────────

    def _build_date_nav(self, parent_layout):
        row = QHBoxLayout()
        row.setSpacing(8)

        nav_btn_style = (
            f"QPushButton {{ font-size: 18px; font-weight: bold; padding: 4px; }}"
            f"QPushButton:disabled {{ color: {theme.BORDER_PRIMARY}; "
            f"background-color: {theme.BG_MAIN}; border: 1px solid {theme.BORDER_SECONDARY}; }}"
        )

        self._btn_prev = QPushButton("<")
        self._btn_prev.setFixedSize(40, 36)
        self._btn_prev.setStyleSheet(nav_btn_style)
        self._btn_prev.clicked.connect(self._go_prev)

        self._date_label = QLabel()
        self._date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._date_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 19px; font-weight: bold;"
        )

        self._btn_next = QPushButton(">")
        self._btn_next.setFixedSize(40, 36)
        self._btn_next.setStyleSheet(nav_btn_style)
        self._btn_next.clicked.connect(self._go_next)

        self._btn_today = QPushButton("Today")
        self._btn_today.setFixedSize(80, 36)
        self._btn_today.setStyleSheet("font-size: 16px; padding: 4px 8px;")
        self._btn_today.clicked.connect(self._go_today)

        row.addWidget(self._btn_prev)
        row.addWidget(self._date_label, 1)
        row.addWidget(self._btn_next)
        row.addWidget(self._btn_today)

        parent_layout.addLayout(row)

    def _refresh_dates(self):
        from spotify_auto_skipper.insights import get_available_dates
        self._available_dates = get_available_dates(self._log_dir)
        today = date.today().isoformat()
        if today in self._available_dates:
            self._current_index = self._available_dates.index(today)
        elif self._available_dates:
            self._current_index = len(self._available_dates) - 1
        else:
            self._current_index = -1
        self._last_size = -1
        self._load_current()

    def _go_prev(self):
        if self._current_index > 0:
            self._current_index -= 1
            self._last_size = -1
            self._load_current()

    def _go_next(self):
        if self._current_index < len(self._available_dates) - 1:
            self._current_index += 1
            self._last_size = -1
            self._load_current()

    def _go_today(self):
        self._refresh_dates()

    def _is_viewing_today(self):
        if self._current_index < 0 or not self._available_dates:
            return False
        return self._available_dates[self._current_index] == date.today().isoformat()

    # ── Toolbar ───────────────────────────────────────────────────

    def _build_toolbar(self, parent_layout):
        row = QHBoxLayout()
        row.setSpacing(8)

        # Filter dropdown
        filter_label = QLabel("Filter:")
        filter_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        row.addWidget(filter_label)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["All", "Skipped", "Kept", "Warning", "Error"])
        self._filter_combo.setFixedWidth(120)
        self._filter_combo.currentTextChanged.connect(self._apply_filter)
        row.addWidget(self._filter_combo)

        row.addStretch()

        # Copy button
        btn_copy = QPushButton("Copy to Clipboard")
        btn_copy.setFixedHeight(32)
        btn_copy.clicked.connect(self._copy_to_clipboard)
        row.addWidget(btn_copy)

        # Open folder button
        btn_folder = QPushButton("Open Logs Folder")
        btn_folder.setFixedHeight(32)
        btn_folder.clicked.connect(self._open_logs_folder)
        row.addWidget(btn_folder)

        parent_layout.addLayout(row)

    # ── Log view ──────────────────────────────────────────────────

    def _build_log_view(self, parent_layout):
        self._text_edit = QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont(QFont("Consolas", 10))
        self._text_edit.setStyleSheet(
            f"QPlainTextEdit {{"
            f"  background-color: {theme.BG_INPUT};"
            f"  color: {theme.TEXT_PRIMARY};"
            f"  border: 1px solid {theme.BORDER_PRIMARY};"
            f"  border-radius: 6px;"
            f"  padding: 8px;"
            f"}}"
            f"QScrollBar:vertical {{"
            f"  background: {theme.BG_INPUT};"
            f"  width: 8px;"
            f"  margin: 0;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"  background: {theme.BORDER_PRIMARY};"
            f"  border-radius: 4px;"
            f"  min-height: 20px;"
            f"}}"
            f"QScrollBar::handle:vertical:hover {{"
            f"  background: {theme.BG_HOVER};"
            f"}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{"
            f"  background: none;"
            f"  height: 0;"
            f"}}"
            f"QScrollBar:horizontal {{"
            f"  background: {theme.BG_INPUT};"
            f"  height: 8px;"
            f"  margin: 0;"
            f"}}"
            f"QScrollBar::handle:horizontal {{"
            f"  background: {theme.BORDER_PRIMARY};"
            f"  border-radius: 4px;"
            f"  min-width: 20px;"
            f"}}"
            f"QScrollBar::handle:horizontal:hover {{"
            f"  background: {theme.BG_HOVER};"
            f"}}"
            f"QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,"
            f"QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{"
            f"  background: none;"
            f"  width: 0;"
            f"}}"
        )
        self._text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        parent_layout.addWidget(self._text_edit, 1)

    # ── Loading ───────────────────────────────────────────────────

    def _load_current(self):
        self._btn_prev.setEnabled(self._current_index > 0)
        self._btn_next.setEnabled(
            self._current_index < len(self._available_dates) - 1
        )

        if self._current_index < 0 or not self._available_dates:
            self._date_label.setText("No logs available")
            self._text_edit.setPlainText("")
            return

        date_str = self._available_dates[self._current_index]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            self._date_label.setText(dt.strftime("%B %d, %Y"))
        except ValueError:
            self._date_label.setText(date_str)

        threading.Thread(
            target=self._read_log_file,
            args=(date_str,),
            daemon=True,
        ).start()

    def _read_log_file(self, date_str: str):
        log_path = os.path.join(self._log_dir, f"{date_str}.txt")
        try:
            size = os.path.getsize(log_path)
            if size == self._last_size:
                return  # no changes
            self._last_size = size
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            self._content_ready.emit(content)
        except FileNotFoundError:
            self._content_ready.emit("")
        except OSError:
            self._content_ready.emit("")

    def _on_content_ready(self, content: str):
        self._full_content = content
        self._apply_filter()

    def _apply_filter(self):
        if not hasattr(self, "_full_content"):
            return

        filter_key = self._filter_combo.currentText().lower()
        content = self._full_content

        if filter_key == "skipped":
            content = _filter_song_blocks(content, _SKIPPED_TEXT)
        elif filter_key == "kept":
            content = _filter_song_blocks(content, _KEPT_TEXT)
        elif filter_key == "warning":
            content = _filter_blocks_by_marker(content, _WARNING_LINE)
        elif filter_key == "error":
            content = _filter_blocks_by_marker(content, _ERROR_LINE)

        # Preserve scroll position if user scrolled up, else auto-scroll to bottom
        scrollbar = self._text_edit.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 10

        self._text_edit.setPlainText(content)

        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    # ── Auto-refresh ──────────────────────────────────────────────

    def _auto_refresh(self):
        if not self._is_viewing_today():
            return
        if self._current_index < 0 or not self._available_dates:
            return
        date_str = self._available_dates[self._current_index]
        threading.Thread(
            target=self._read_log_file,
            args=(date_str,),
            daemon=True,
        ).start()

    # ── Actions ───────────────────────────────────────────────────

    def _copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self._text_edit.toPlainText())

    def _open_logs_folder(self):
        os.startfile(self._log_dir)


def create_logs_tab(parent=None) -> QWidget:
    """Factory function called from settings_window.py."""
    return LogsTab(parent)
