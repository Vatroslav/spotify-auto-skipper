"""
Insights tab widget for the Settings window.
Displays daily listening statistics and rule-based observations
parsed from existing log files.
"""

import os
import threading
from datetime import date, datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal

from spotify_auto_skipper.gui import theme
from spotify_auto_skipper.gui.widgets import create_separator


class InsightsTab(QWidget):
    """Self-contained Insights tab with date navigation and threaded loading."""

    _data_ready = Signal(dict)   # metrics + insights payload

    def __init__(self, parent=None):
        super().__init__(parent)

        from spotify_auto_skipper import utils
        self._log_dir = utils.get_log_dir()

        self._available_dates = []
        self._current_index = -1

        self._data_ready.connect(self._populate)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Scroll area wrapping the content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        self._layout = QVBoxLayout(inner)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(12)

        self._build_date_nav()
        self._layout.addWidget(create_separator())
        self._build_metrics_grid()
        self._layout.addWidget(create_separator())
        self._build_details_section()
        self._layout.addWidget(create_separator())
        self._build_observations_section()
        self._layout.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll)

        # Initial load
        self._refresh_dates()

    # ── Date navigation ───────────────────────────────────────────

    def _build_date_nav(self):
        row = QHBoxLayout()
        row.setSpacing(8)

        nav_btn_style = (
            f"QPushButton {{ font-size: 18px; font-weight: bold; padding: 4px; }}"
            f"QPushButton:disabled {{ color: {theme.BORDER_PRIMARY}; background-color: {theme.BG_MAIN}; border: 1px solid {theme.BORDER_SECONDARY}; }}"
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

        self._layout.addLayout(row)

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
        self._load_current()

    def _go_prev(self):
        if self._current_index > 0:
            self._current_index -= 1
            self._load_current()

    def _go_next(self):
        if self._current_index < len(self._available_dates) - 1:
            self._current_index += 1
            self._load_current()

    def _go_today(self):
        self._refresh_dates()

    def _load_current(self):
        self._btn_prev.setEnabled(self._current_index > 0)
        self._btn_next.setEnabled(
            self._current_index < len(self._available_dates) - 1
        )

        if self._current_index < 0 or not self._available_dates:
            self._date_label.setText("No logs available")
            self._show_empty()
            return

        date_str = self._available_dates[self._current_index]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            self._date_label.setText(dt.strftime("%B %d, %Y"))
        except ValueError:
            self._date_label.setText(date_str)

        self._show_loading()
        threading.Thread(
            target=self._parse_in_background,
            args=(date_str,),
            daemon=True,
        ).start()

    def _parse_in_background(self, date_str: str):
        from spotify_auto_skipper.insights import (
            parse_log_file, compute_metrics, generate_insights,
        )
        from spotify_auto_skipper import config

        summary = parse_log_file(self._log_dir, date_str)
        if summary is None:
            self._data_ready.emit({
                "metrics": None,
                "insights": [{"icon": "info", "title": "No data",
                              "detail": "Log file not found for this date."}],
            })
            return

        metrics = compute_metrics(summary)
        insights = generate_insights(metrics, config.SKIP_WINDOW_DAYS)
        self._data_ready.emit({"metrics": metrics, "insights": insights})

    # ── Metrics grid ──────────────────────────────────────────────

    def _build_metrics_grid(self):
        self._metrics_grid = QGridLayout()
        self._metrics_grid.setSpacing(8)

        self._metric_labels = {}
        defs = [
            ("songs_played",  "Songs played"),
            ("skip_rate",     "Skip rate"),
            ("songs_skipped", "Songs skipped"),
            ("unique_songs",  "Unique songs"),
            ("songs_kept",    "Songs kept"),
            ("unique_artists","Unique artists"),
        ]
        for i, (key, label_text) in enumerate(defs):
            row, col = divmod(i, 2)
            lbl = QLabel(f"{label_text}:")
            lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
            val = QLabel("\u2014")
            val.setStyleSheet(
                f"color: {theme.ACCENT}; font-weight: bold; font-size: 14px;"
            )
            self._metrics_grid.addWidget(lbl, row, col * 3)
            self._metrics_grid.addWidget(val, row, col * 3 + 1)
            # Spacer column between the two metric columns
            if col == 0:
                self._metrics_grid.setColumnMinimumWidth(col * 3 + 2, 24)
            self._metric_labels[key] = val

        self._layout.addLayout(self._metrics_grid)

    # ── Details (most skipped, streaks, etc.) ─────────────────────

    def _build_details_section(self):
        self._details_container = QVBoxLayout()
        self._details_container.setSpacing(4)

        self._detail_labels = {}
        for key in ("most_skipped", "most_played", "longest_skip_streak", "avg_skip_days"):
            lbl = QLabel()
            lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
            lbl.setWordWrap(True)
            self._details_container.addWidget(lbl)
            self._detail_labels[key] = lbl

        self._layout.addLayout(self._details_container)

    # ── Observations ──────────────────────────────────────────────

    def _build_observations_section(self):
        self._obs_header = QLabel("Observations")
        self._obs_header.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;"
        )
        self._layout.addWidget(self._obs_header)

        self._obs_container = QVBoxLayout()
        self._obs_container.setSpacing(10)
        self._layout.addLayout(self._obs_container)

    # ── Populate / clear ──────────────────────────────────────────

    def _show_loading(self):
        self._clear_metrics()
        self._clear_observations()
        self._obs_header.setText("Loading...")

    def _show_empty(self):
        self._clear_metrics()
        self._clear_observations()

    def _clear_metrics(self):
        for val in self._metric_labels.values():
            val.setText("\u2014")
        for val in self._detail_labels.values():
            val.setText("")

    def _clear_observations(self):
        while self._obs_container.count():
            item = self._obs_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _populate(self, data: dict):
        self._obs_header.setText("Observations")
        metrics = data.get("metrics")
        insights = data.get("insights", [])

        if metrics:
            self._metric_labels["songs_played"].setText(str(metrics["songs_played"]))
            self._metric_labels["songs_skipped"].setText(str(metrics["songs_skipped"]))
            self._metric_labels["songs_kept"].setText(str(metrics["songs_kept"]))
            self._metric_labels["skip_rate"].setText(f"{metrics['skip_rate']:.0f}%")
            self._metric_labels["unique_songs"].setText(str(metrics["unique_songs"]))
            self._metric_labels["unique_artists"].setText(str(metrics["unique_artists"]))

            # Details
            ms = metrics.get("most_skipped")
            if ms:
                (artist, song), count = ms
                self._detail_labels["most_skipped"].setText(
                    f"Most skipped:  {artist} \u2013 {song}  ({count}x)"
                )

            mp = metrics.get("most_played")
            if mp:
                (artist, song), count = mp
                self._detail_labels["most_played"].setText(
                    f"Most played:  {artist} \u2013 {song}  ({count}x)"
                )

            streak = metrics.get("longest_skip_streak", 0)
            if streak > 0:
                self._detail_labels["longest_skip_streak"].setText(
                    f"Longest skip streak:  {streak}"
                )

            avg = metrics.get("avg_skip_days")
            if avg is not None:
                self._detail_labels["avg_skip_days"].setText(
                    f"Avg skip age:  {avg:.0f} days"
                )
        else:
            self._clear_metrics()

        # Observations
        self._clear_observations()
        for obs in insights:
            row = self._create_observation_row(obs)
            self._obs_container.addWidget(row)

    def _create_observation_row(self, obs: dict) -> QWidget:
        icon_map = {
            "warning": f'<span style="color: {theme.COLOR_WARNING};">\u26a0</span>',
            "info":    f'<span style="color: {theme.ACCENT};">\u2139</span>',
        }
        icon_html = icon_map.get(obs.get("icon", "info"), icon_map["info"])

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        icon_label = QLabel(icon_html)
        icon_label.setTextFormat(Qt.TextFormat.RichText)
        icon_label.setFixedWidth(20)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title = QLabel(obs.get("title", ""))
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-weight: bold;"
        )

        detail = QLabel(obs.get("detail", ""))
        detail.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        detail.setWordWrap(True)

        text_col.addWidget(title)
        text_col.addWidget(detail)

        layout.addWidget(icon_label)
        layout.addLayout(text_col, 1)

        return row


def create_insights_tab(parent=None) -> QWidget:
    """Factory function called from settings_window.py."""
    return InsightsTab(parent)
