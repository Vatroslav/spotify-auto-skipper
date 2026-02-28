import base64
import sys

import requests
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGroupBox, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from spotify_auto_skipper.config import Config, load_config
from spotify_auto_skipper.utils import resource_path
from spotify_auto_skipper.gui import theme
from spotify_auto_skipper.gui.widgets import (
    LabeledEntry, LabeledSpinbox, LabeledCheckbox,
    AccentButton, create_link_label,
)


class SetupWizard(QWidget):
    """
    Multi-step first-run wizard with dark Spotify theme.
    Blocks until complete. If user cancels, exits the app.
    """

    def __init__(self):
        super().__init__()
        self._cfg = Config()
        self._step = 0
        self._fields = {}
        self._steps = [
            self._build_step_lastfm,
            self._build_step_spotify,
            self._build_step_settings,
            self._build_step_summary,
        ]
        self._completed = False

        self.setWindowTitle("Spotify Auto-Skipper Setup")
        self.setWindowIcon(QIcon(resource_path("assets/app.ico")))
        self.setFixedWidth(580)
        self._setup_ui()

    @property
    def completed(self):
        return self._completed

    def run(self):
        """Show wizard and block until finished."""
        app = theme.ensure_app()
        self.show()
        self._center_on_screen()
        app.exec()
        return self._completed

    def _center_on_screen(self):
        self.adjustSize()
        screen = self.screen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Content area
        self._content_frame = QWidget()
        self._content_layout = QVBoxLayout(self._content_frame)
        self._content_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.addWidget(self._content_frame, 1)

        # Border
        border = QFrame()
        border.setFixedHeight(1)
        border.setStyleSheet(f"background-color: {theme.BORDER_SECONDARY};")
        main_layout.addWidget(border)

        # Navigation bar
        nav = QFrame()
        nav.setStyleSheet(f"background-color: {theme.BG_HEADER};")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(16, 10, 16, 10)

        self._back_btn = QPushButton("Back")
        self._back_btn.clicked.connect(self._go_back)
        nav_layout.addWidget(self._back_btn)

        nav_layout.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_close)
        nav_layout.addWidget(self._cancel_btn)

        self._next_btn = AccentButton("Next")
        self._next_btn.clicked.connect(self._go_next)
        nav_layout.addWidget(self._next_btn)

        main_layout.addWidget(nav)

        self._show_step()

    # ----------------------------------------------------------
    # Step management
    # ----------------------------------------------------------

    def _clear_content(self):
        while self._content_layout.count() > 0:
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    @staticmethod
    def _clear_layout(layout):
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                SetupWizard._clear_layout(item.layout())

    def _show_step(self):
        self._clear_content()
        self._steps[self._step](self._content_layout)
        self._content_layout.addStretch()
        self._back_btn.setEnabled(self._step > 0)
        self._next_btn.setText("Finish" if self._step == len(self._steps) - 1 else "Next")

    # ----------------------------------------------------------
    # Step builders
    # ----------------------------------------------------------

    def _build_step_lastfm(self, layout):
        title = QLabel("Step 1: Last.fm Credentials")
        title.setStyleSheet("font-size: 12pt; font-weight: bold;")
        layout.addWidget(title)

        desc_row = QHBoxLayout()
        desc_row.addWidget(QLabel("Enter your Last.fm username and API key. Create one at"))
        desc_row.addWidget(create_link_label("last.fm/api/account/create",
                                             "https://www.last.fm/api/account/create"))
        desc_row.addStretch()
        layout.addLayout(desc_row)

        guide = QGroupBox("What to fill in on the Last.fm form")
        guide_layout = QVBoxLayout(guide)
        for label, hint in [
            ("Application name:", 'anything, e.g. "Spotify Auto-Skipper"'),
            ("Description:", "anything, or leave empty"),
            ("Callback URL:", "leave empty"),
            ("Application homepage:", "leave empty"),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet("font-weight: bold; font-size: 9pt;")
            lbl.setFixedWidth(150)
            row.addWidget(lbl)
            hint_lbl = QLabel(hint)
            hint_lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
            row.addWidget(hint_lbl, 1)
            guide_layout.addLayout(row)
        note = QLabel("After submitting, Last.fm will show your API key. Copy it and paste it below.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 9pt;")
        guide_layout.addWidget(note)
        layout.addWidget(guide)

        f = LabeledEntry(label_text="Username:")
        if "lastfm_username" in self._fields:
            f.set(self._fields["lastfm_username"].get())
        self._fields["lastfm_username"] = f
        layout.addWidget(f)

        f = LabeledEntry(label_text="API Key:")
        if "lastfm_api_key" in self._fields:
            f.set(self._fields["lastfm_api_key"].get())
        self._fields["lastfm_api_key"] = f
        layout.addWidget(f)

        test_row = QHBoxLayout()
        self._lastfm_status = QLabel()
        self._lastfm_status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt;")
        test_row.addWidget(self._lastfm_status, 1)
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._test_lastfm)
        test_row.addWidget(test_btn)
        layout.addLayout(test_row)

    def _build_step_spotify(self, layout):
        title = QLabel("Step 2: Spotify Credentials")
        title.setStyleSheet("font-size: 12pt; font-weight: bold;")
        layout.addWidget(title)

        # Part 1
        p1 = QHBoxLayout()
        p1.addWidget(QLabel("1. Create an app at"))
        p1.addWidget(create_link_label("developer.spotify.com/dashboard",
                                       "https://developer.spotify.com/dashboard"))
        p1.addStretch()
        layout.addLayout(p1)

        guide1 = QGroupBox("What to fill in on the Spotify form")
        g1_layout = QVBoxLayout(guide1)
        for label, hint in [
            ("App name:", 'anything, e.g. "Spotify Auto-Skipper"'),
            ("App description:", 'anything, e.g. "Auto-skip recently played songs"'),
            ("Redirect URI:", "paste the URL from step 2 below"),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet("font-weight: bold; font-size: 9pt;")
            lbl.setFixedWidth(120)
            row.addWidget(lbl)
            hint_lbl = QLabel(hint)
            hint_lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
            row.addWidget(hint_lbl, 1)
            g1_layout.addLayout(row)
        note = QLabel("After creating the app, copy the Client ID and Client Secret from the app settings.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 9pt;")
        g1_layout.addWidget(note)
        layout.addWidget(guide1)

        # Part 2
        p2 = QHBoxLayout()
        p2.addWidget(QLabel("2. Get a Refresh Token using"))
        p2.addWidget(create_link_label("Spotify Refresh Token Generator",
                                       "https://spotify-refresh-token-generator.netlify.app"))
        p2.addStretch()
        layout.addLayout(p2)

        guide2 = QGroupBox("How to get your Refresh Token")
        g2_layout = QVBoxLayout(guide2)
        steps = [
            "Enter your Client ID and Client Secret on the site",
            "Select these scopes: user-read-playback-state,\n"
            "user-modify-playback-state, user-library-read, playlist-read-private",
            'Click "Get Refresh Token" and log in to Spotify',
            "Copy the Refresh Token and paste it below",
        ]
        for i, text in enumerate(steps, 1):
            row = QHBoxLayout()
            num = QLabel(f"{i}.")
            num.setStyleSheet("font-weight: bold; font-size: 9pt;")
            num.setFixedWidth(20)
            num.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            row.addWidget(num)
            step_lbl = QLabel(text)
            step_lbl.setWordWrap(True)
            row.addWidget(step_lbl, 1)
            g2_layout.addLayout(row)
        layout.addWidget(guide2)

        heading = QLabel("3. Paste all three values below:")
        heading.setStyleSheet("font-weight: bold; font-size: 9pt;")
        layout.addWidget(heading)

        f = LabeledEntry(label_text="Client ID:")
        if "spotify_client_id" in self._fields:
            f.set(self._fields["spotify_client_id"].get())
        self._fields["spotify_client_id"] = f
        layout.addWidget(f)

        f = LabeledEntry(label_text="Client Secret:")
        if "spotify_client_secret" in self._fields:
            f.set(self._fields["spotify_client_secret"].get())
        self._fields["spotify_client_secret"] = f
        layout.addWidget(f)

        f = LabeledEntry(label_text="Refresh Token:")
        if "spotify_refresh_token" in self._fields:
            f.set(self._fields["spotify_refresh_token"].get())
        self._fields["spotify_refresh_token"] = f
        layout.addWidget(f)

        test_row = QHBoxLayout()
        self._spotify_status = QLabel()
        self._spotify_status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt;")
        test_row.addWidget(self._spotify_status, 1)
        test_btn = QPushButton("Test Token")
        test_btn.clicked.connect(self._test_spotify)
        test_row.addWidget(test_btn)
        layout.addLayout(test_row)

    def _build_step_settings(self, layout):
        title = QLabel("Step 3: Settings")
        title.setStyleSheet("font-size: 12pt; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("Configure how the auto-skipper behaves.")
        desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        layout.addWidget(desc)

        layout.addSpacing(10)

        f = LabeledSpinbox(label_text="Skip window (days):", from_=1, to=365)
        if "skip_window_days" in self._fields:
            f.set(self._fields["skip_window_days"].get())
        else:
            f.set(60)
        self._fields["skip_window_days"] = f
        layout.addWidget(f)

        f = LabeledSpinbox(label_text="Poll interval (seconds):", from_=5, to=600)
        if "poll_interval_seconds" in self._fields:
            f.set(self._fields["poll_interval_seconds"].get())
        else:
            f.set(120)
        self._fields["poll_interval_seconds"] = f
        layout.addWidget(f)

        f = LabeledCheckbox(label_text="Always play liked songs")
        if "always_play_liked_songs" in self._fields:
            f.set(self._fields["always_play_liked_songs"].get())
        else:
            f.set(True)
        self._fields["always_play_liked_songs"] = f
        layout.addWidget(f)

    def _build_step_summary(self, layout):
        title = QLabel("Step 4: Summary")
        title.setStyleSheet("font-size: 12pt; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("Review your settings and click Finish to save.")
        desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        layout.addWidget(desc)

        layout.addSpacing(10)

        summary = QFrame()
        summary.setStyleSheet(f"""
            QFrame {{ background-color: {theme.BG_INPUT};
                      border: 1px solid {theme.BORDER_PRIMARY};
                      border-radius: 4px; }}
        """)
        s_layout = QVBoxLayout(summary)
        s_layout.setContentsMargins(12, 8, 12, 8)

        for label_text, field in [
            ("Last.fm user:", self._fields.get("lastfm_username")),
            ("Spotify Client ID:", self._fields.get("spotify_client_id")),
            ("Skip window:", self._fields.get("skip_window_days")),
            ("Poll interval:", self._fields.get("poll_interval_seconds")),
            ("Always play liked:", self._fields.get("always_play_liked_songs")),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(150)
            lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; background: transparent;")
            row.addWidget(lbl)
            val = str(field.get()) if field else "N/A"
            val_lbl = QLabel(val)
            val_lbl.setStyleSheet("background: transparent;")
            row.addWidget(val_lbl, 1)
            s_layout.addLayout(row)

        layout.addWidget(summary)

    # ----------------------------------------------------------
    # Navigation
    # ----------------------------------------------------------

    def _go_back(self):
        if self._step > 0:
            self._step -= 1
            self._show_step()

    def _go_next(self):
        if self._step == 0:
            if not self._fields["lastfm_username"].get().strip():
                QMessageBox.warning(self, "Missing field", "Last.fm username is required.")
                return
            if not self._fields["lastfm_api_key"].get().strip():
                QMessageBox.warning(self, "Missing field", "Last.fm API key is required.")
                return
        elif self._step == 1:
            if not self._fields["spotify_client_id"].get().strip():
                QMessageBox.warning(self, "Missing field", "Spotify Client ID is required.")
                return
            if not self._fields["spotify_client_secret"].get().strip():
                QMessageBox.warning(self, "Missing field", "Spotify Client Secret is required.")
                return
            if not self._fields["spotify_refresh_token"].get().strip():
                QMessageBox.warning(self, "Missing field", "Spotify Refresh Token is required.")
                return

        if self._step == len(self._steps) - 1:
            self._save_and_finish()
            return

        self._step += 1
        self._show_step()

    def _save_and_finish(self):
        keys = [
            "lastfm_username", "lastfm_api_key",
            "spotify_client_id", "spotify_client_secret", "spotify_refresh_token",
            "skip_window_days", "poll_interval_seconds",
            "always_play_liked_songs",
        ]
        for key in keys:
            if key in self._fields:
                self._cfg.set(key, self._fields[key].get())

        self._cfg.save()
        load_config()
        self._completed = True
        self.close()

    def _on_close(self):
        reply = QMessageBox.question(
            self, "Cancel Setup",
            "Are you sure you want to cancel? The app cannot run without configuration.",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.close()
            sys.exit(0)

    def closeEvent(self, event):
        event.accept()

    # ----------------------------------------------------------
    # Test buttons
    # ----------------------------------------------------------

    def _test_lastfm(self):
        username = self._fields["lastfm_username"].get().strip()
        api_key = self._fields["lastfm_api_key"].get().strip()
        if not username or not api_key:
            self._lastfm_status.setText("Fill in both fields first")
            self._lastfm_status.setStyleSheet(f"color: {theme.COLOR_ERROR}; font-size: 9pt;")
            return

        self._lastfm_status.setText("Testing...")
        self._lastfm_status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt;")
        self.repaint()

        try:
            r = requests.get(
                "https://ws.audioscrobbler.com/2.0/",
                params={"method": "user.getinfo", "user": username,
                        "api_key": api_key, "format": "json"},
                timeout=10,
            )
            if r.status_code == 200 and "user" in r.json():
                self._lastfm_status.setText("Connection successful!")
                self._lastfm_status.setStyleSheet(f"color: {theme.COLOR_SUCCESS}; font-size: 9pt;")
            else:
                self._lastfm_status.setText("Invalid credentials")
                self._lastfm_status.setStyleSheet(f"color: {theme.COLOR_ERROR}; font-size: 9pt;")
        except Exception as e:
            self._lastfm_status.setText(f"Error: {e}")
            self._lastfm_status.setStyleSheet(f"color: {theme.COLOR_ERROR}; font-size: 9pt;")

    def _test_spotify(self):
        client_id = self._fields["spotify_client_id"].get().strip()
        client_secret = self._fields["spotify_client_secret"].get().strip()
        refresh_token = self._fields["spotify_refresh_token"].get().strip()

        if not client_id or not client_secret or not refresh_token:
            self._spotify_status.setText("Fill in all fields first")
            self._spotify_status.setStyleSheet(f"color: {theme.COLOR_ERROR}; font-size: 9pt;")
            return

        self._spotify_status.setText("Testing...")
        self._spotify_status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt;")
        self.repaint()

        try:
            auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            r = requests.post(
                "https://accounts.spotify.com/api/token",
                headers={"Authorization": f"Basic {auth}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                timeout=10,
            )
            if r.status_code == 200 and "access_token" in r.json():
                self._spotify_status.setText("Token refresh successful!")
                self._spotify_status.setStyleSheet(f"color: {theme.COLOR_SUCCESS}; font-size: 9pt;")
            else:
                self._spotify_status.setText("Invalid credentials or token")
                self._spotify_status.setStyleSheet(f"color: {theme.COLOR_ERROR}; font-size: 9pt;")
        except Exception as e:
            self._spotify_status.setText(f"Error: {e}")
            self._spotify_status.setStyleSheet(f"color: {theme.COLOR_ERROR}; font-size: 9pt;")
