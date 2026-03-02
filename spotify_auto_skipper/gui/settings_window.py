import os
import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QPushButton, QFrame, QMessageBox,
)
from PySide6.QtCore import Qt, QCoreApplication, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QIcon

from spotify_auto_skipper import APP_VERSION
from spotify_auto_skipper.config import Config, load_config
from spotify_auto_skipper.startup import set_startup
from spotify_auto_skipper.utils import get_config_dir, get_log_dir, set_log_dir, resource_path
from spotify_auto_skipper.gui import theme
from spotify_auto_skipper.gui.widgets import (
    LabeledEntry, LabeledSpinbox, LabeledCheckbox,
    LabeledDirectoryPicker, PlaylistPicker, ArtistListWidget,
    AccentButton, create_separator, create_link_label,
)


class SettingsWindow(QWidget):
    """
    Singleton settings window with dark Spotify theme.
    Frameless window: Header → QTabWidget → Footer.
    """
    _instance = None

    @classmethod
    def open(cls):
        if cls._instance is not None and cls._instance.isVisible():
            cls._bring_to_front(cls._instance)
            return cls._instance
        inst = cls()
        cls._instance = inst
        inst.show()
        cls._bring_to_front(inst)
        return inst

    @staticmethod
    def _bring_to_front(window):
        """Force-bring window to front on Windows (bypass focus-stealing prevention)."""
        window.setWindowFlags(window.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        window.show()
        window.setWindowFlags(window.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        window.show()
        window.raise_()
        window.activateWindow()

    def __init__(self):
        super().__init__()
        self._cfg = Config()
        self._fields = {}
        self._drag_pos = None

        self.setWindowTitle("Spotify Auto-Skipper Settings")
        self.setWindowIcon(QIcon(resource_path("assets/app.ico")))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self._maximized = False
        self._normal_geometry = None
        self.setFixedSize(1000, 750)

        self._setup_ui()
        self._load_values()
        self._center_on_screen()

    def _center_on_screen(self):
        screen = self.screen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

    def paintEvent(self, event):
        """Draw 1px border around the frameless window."""
        painter = QPainter(self)
        painter.setPen(QPen(QColor(theme.BORDER_SECONDARY), 1))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)
        painter.end()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)  # 1px for the border
        layout.setSpacing(0)

        self._header = self._create_header()
        layout.addWidget(self._header)
        layout.addWidget(self._create_tabs(), 1)
        layout.addWidget(self._create_footer())

    # ----------------------------------------------------------
    # Window dragging (via header)
    # ----------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Only allow drag from the header area
            header_rect = self._header.geometry()
            if header_rect.contains(event.position().toPoint()):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        """Double-click header to toggle maximize."""
        header_rect = self._header.geometry()
        if header_rect.contains(event.position().toPoint()):
            self._toggle_maximize()

    def _toggle_maximize(self):
        if self._maximized:
            # Restore
            self.setFixedSize(1000, 750)
            if self._normal_geometry:
                self.setGeometry(self._normal_geometry)
            else:
                self._center_on_screen()
            self._maximize_btn.setText("\uE922")  # ChromeMaximize
            self._maximized = False
        else:
            # Maximize
            self._normal_geometry = self.geometry()
            screen = self.screen().availableGeometry()
            self.setFixedSize(screen.width(), screen.height())
            self.move(screen.topLeft())
            self._maximize_btn.setText("\uE923")  # ChromeRestore
            self._maximized = True

    # ----------------------------------------------------------
    # Header
    # ----------------------------------------------------------

    def _create_header(self):
        header = QFrame()
        header.setStyleSheet(f"""
            QFrame {{ background-color: {theme.BG_HEADER}; }}
            QFrame QLabel {{ background: transparent; }}
        """)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)

        # Title + subtitle
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        title = QLabel("Spotify Auto-Skipper")
        title.setStyleSheet(f"font-size: 19pt; font-weight: 600; color: {theme.TEXT_PRIMARY};")
        text_layout.addWidget(title)

        subtitle = QLabel("Configure your auto-skip preferences")
        subtitle.setStyleSheet(f"font-size: 13pt; color: {theme.TEXT_SECONDARY};")
        text_layout.addWidget(subtitle)

        layout.addWidget(text_widget, 1)

        # Window control buttons (Segoe MDL2 Assets icons for crisp rendering)
        mdl2 = "Segoe MDL2 Assets"
        btn_base = f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 0;
                color: {theme.TEXT_SECONDARY}; font-family: "{mdl2}"; font-size: 10pt;
                padding: 0; margin: 0;
                qproperty-iconSize: 0px;
            }}
        """
        btn_style = btn_base + f"""
            QPushButton:hover {{ background-color: {theme.BG_HOVER}; color: {theme.TEXT_PRIMARY}; }}
        """
        close_style = btn_base + f"""
            QPushButton:hover {{ background-color: #c42b1c; color: white; }}
        """

        minimize_btn = QPushButton("\uE921")  # ChromeMinimize
        minimize_btn.setFixedSize(46, 32)
        minimize_btn.setStyleSheet(btn_style)
        minimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        minimize_btn.clicked.connect(self.showMinimized)
        layout.addWidget(minimize_btn)

        self._maximize_btn = QPushButton("\uE922")  # ChromeMaximize
        self._maximize_btn.setFixedSize(46, 32)
        self._maximize_btn.setStyleSheet(btn_style)
        self._maximize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._maximize_btn.clicked.connect(self._toggle_maximize)
        layout.addWidget(self._maximize_btn)

        close_btn = QPushButton("\uE8BB")  # ChromeClose
        close_btn.setFixedSize(46, 32)
        close_btn.setStyleSheet(close_style)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        return header

    # ----------------------------------------------------------
    # Tabs
    # ----------------------------------------------------------

    def _create_tabs(self):
        tabs = QTabWidget()
        tabs.addTab(self._create_settings_tab(), "\u2699  Settings")
        tabs.addTab(self._create_never_skip_tab(), "\u266B  Never-skip Artists")
        tabs.addTab(self._create_restart_pattern_tab(), "\u21BB  Restart Pattern")
        tabs.addTab(self._create_remote_control_tab(), "\U0001F4F1  Remote Control")
        tabs.addTab(self._create_credentials_tab(), "\U0001F511  Credentials")
        return tabs

    def _create_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        f = LabeledSpinbox(label_text="Skip window (days):", from_=1, to=365)
        layout.addWidget(f)
        self._fields["skip_window_days"] = f

        f = LabeledSpinbox(label_text="Poll interval (seconds):", from_=5, to=600)
        layout.addWidget(f)
        self._fields["poll_interval_seconds"] = f

        f = LabeledSpinbox(label_text="Log retention (days):", from_=1, to=365)
        layout.addWidget(f)
        self._fields["log_retention_days"] = f

        layout.addWidget(create_separator())

        f = LabeledCheckbox(label_text="Always play liked songs")
        layout.addWidget(f)
        self._fields["always_play_liked_songs"] = f

        f = LabeledCheckbox(label_text="Start with Windows")
        layout.addWidget(f)
        self._fields["start_with_windows"] = f

        notif_row = QHBoxLayout()
        f = LabeledCheckbox(label_text="Notify when Smart Shuffle recommends a song not in the current playlist")
        notif_row.addWidget(f, 1)
        self._fields["enable_recommendation_notifications"] = f

        test_notif_btn = QPushButton("Test")
        test_notif_btn.setFixedWidth(70)
        test_notif_btn.clicked.connect(self._test_notification)
        notif_row.addWidget(test_notif_btn)
        layout.addLayout(notif_row)

        layout.addWidget(create_separator())

        heading = QLabel("Storage Locations:")
        heading.setStyleSheet(f"font-weight: 600; font-size: 13pt; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(heading)

        self._config_dir_picker = LabeledDirectoryPicker(label_text="Config folder:")
        layout.addWidget(self._config_dir_picker)

        self._log_dir_picker = LabeledDirectoryPicker(label_text="Log folder:")
        layout.addWidget(self._log_dir_picker)

        layout.addStretch()
        return tab

    def _create_never_skip_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        desc = QLabel("Songs by these artists will never be skipped, regardless of how recently they were played.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        layout.addWidget(desc)

        from spotify_auto_skipper.spotify_api import search_artists
        self._artist_widget = ArtistListWidget(search_fn=search_artists)
        layout.addWidget(self._artist_widget, 1)

        return tab

    def _create_restart_pattern_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        f = LabeledCheckbox(label_text="Enable restart-pattern detection")
        layout.addWidget(f)
        self._fields["enable_restart_pattern"] = f

        desc = QLabel(
            "Sometimes Spotify plays songs in the same order as a few days ago, "
            "causing the skipper to skip many songs in a row. When this is detected, "
            "the app briefly switches to a different playlist and back to reset the shuffle."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        layout.addWidget(desc)

        f = LabeledSpinbox(label_text="How many skips in a row?", from_=2, to=20, label_width=200)
        layout.addWidget(f)
        self._fields["restart_pattern_song_count"] = f

        f = LabeledSpinbox(label_text="Max day gap between them?", from_=0, to=30, label_width=200)
        layout.addWidget(f)
        self._fields["restart_pattern_day_diff"] = f

        layout.addWidget(create_separator())

        f = PlaylistPicker(label_text="Reset playlist:",
                           description="The playlist used for the brief switch. "
                                       "It won't actually be played \u2014 any playlist will do.")
        layout.addWidget(f)
        self._fields["dummy_playlist_id"] = f

        layout.addStretch()
        return tab

    def _create_remote_control_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        desc = QLabel(
            "Since the app communicates with Spotify over the internet, it works even when "
            "you're listening on your phone (e.g. in the car) \u2014 as long as the app is running "
            "on a PC that isn't asleep.\n\n"
            "To control skipping remotely, create a text file in Dropbox or Google Drive and "
            "paste its shared link below. Write ON in the file to enable skipping, or OFF to "
            "pause it. The app checks this file before every skip.\n\n"
            "This way you can pause the skipper from your phone whenever you want to listen "
            "freely, and turn it back on when you're done. Leave the URL empty to disable "
            "remote control (skipping is always on)."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; line-height: 1.5;")
        layout.addWidget(desc)

        row = QHBoxLayout()
        f = LabeledEntry(label_text="URL:", label_width=40)
        row.addWidget(f, 1)
        self._fields["remote_control_url"] = f

        self._rc_test_btn = QPushButton("Test")
        self._rc_test_btn.setFixedWidth(70)
        self._rc_test_btn.clicked.connect(self._test_remote_control)
        row.addWidget(self._rc_test_btn)
        layout.addLayout(row)

        self._rc_result = QLabel()
        self._rc_result.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11pt;")
        layout.addWidget(self._rc_result)

        layout.addStretch()
        return tab

    def _create_credentials_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        # Last.fm
        heading = QLabel("Last.fm")
        heading.setStyleSheet(f"font-size: 14pt; font-weight: 600; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(heading)

        desc_row = QHBoxLayout()
        desc_lbl = QLabel("Your Last.fm username and API key. Create one at")
        desc_lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        desc_row.addWidget(desc_lbl)
        desc_row.addWidget(create_link_label("last.fm/api/account/create",
                                             "https://www.last.fm/api/account/create"))
        desc_row.addStretch()
        layout.addLayout(desc_row)

        f = LabeledEntry(label_text="Username:", label_width=120)
        layout.addWidget(f)
        self._fields["lastfm_username"] = f

        f = LabeledEntry(label_text="API Key:", show="*", label_width=120)
        layout.addWidget(f)
        self._fields["lastfm_api_key"] = f

        layout.addWidget(create_separator())

        # Spotify
        heading = QLabel("Spotify")
        heading.setStyleSheet(f"font-size: 14pt; font-weight: 600; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(heading)

        desc_row2 = QHBoxLayout()
        desc_lbl2 = QLabel("Create an app at")
        desc_lbl2.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        desc_row2.addWidget(desc_lbl2)
        desc_row2.addWidget(create_link_label("developer.spotify.com/dashboard",
                                              "https://developer.spotify.com/dashboard"))
        desc_row2.addStretch()
        layout.addLayout(desc_row2)

        extra_desc = QLabel("and copy the Client ID and Secret. The refresh token "
                            "is generated automatically during the first-run setup.")
        extra_desc.setWordWrap(True)
        extra_desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        layout.addWidget(extra_desc)

        f = LabeledEntry(label_text="Client ID:", label_width=120)
        layout.addWidget(f)
        self._fields["spotify_client_id"] = f

        f = LabeledEntry(label_text="Client Secret:", show="*", label_width=120)
        layout.addWidget(f)
        self._fields["spotify_client_secret"] = f

        f = LabeledEntry(label_text="Refresh Token:", show="*", label_width=120)
        layout.addWidget(f)
        self._fields["spotify_refresh_token"] = f

        layout.addStretch()
        return tab

    # ----------------------------------------------------------
    # Footer
    # ----------------------------------------------------------

    def _create_footer(self):
        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(0)

        # Top border
        border = QFrame()
        border.setFixedHeight(1)
        border.setStyleSheet(f"background-color: {theme.BORDER_SECONDARY};")
        wrapper_layout.addWidget(border)

        footer = QFrame()
        footer.setStyleSheet(f"background-color: {theme.BG_HEADER};")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        # Left: Exit App + version
        exit_btn = QPushButton("Exit App")
        exit_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {theme.TEXT_PRIMARY}; padding: 8px 16px;
            }}
            QPushButton:hover {{ background-color: {theme.BG_INPUT}; border-radius: 4px; }}
        """)
        exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_btn.clicked.connect(self._on_exit_app)
        layout.addWidget(exit_btn)

        version = QLabel(APP_VERSION)
        version.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 13pt; background: transparent;")
        layout.addWidget(version)

        layout.addStretch()

        # Right: Cancel + Save
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {theme.TEXT_PRIMARY}; padding: 8px 24px;
            }}
            QPushButton:hover {{ background-color: {theme.BG_INPUT}; border-radius: 4px; }}
        """)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.close)
        layout.addWidget(cancel_btn)

        save_btn = AccentButton("Save")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)

        wrapper_layout.addWidget(footer)
        return wrapper

    # ----------------------------------------------------------
    # Remote control test
    # ----------------------------------------------------------

    def _test_remote_control(self):
        import requests
        from spotify_auto_skipper.spotify_api import _normalize_remote_url
        url = self._fields["remote_control_url"].get().strip()
        if not url:
            self._rc_result.setText("No URL set.")
            self._rc_result.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11pt;")
            return

        url = _normalize_remote_url(url)
        self._rc_result.setText("Testing...")
        self._rc_result.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11pt;")
        QCoreApplication.processEvents()

        try:
            r = requests.get(url, timeout=10)
            first_line = r.text.strip().splitlines()[0].strip()
            value = first_line.lower()
            if value == "on":
                self._rc_result.setText(f"\u2714 File says ON \u2014 skipping is enabled")
                self._rc_result.setStyleSheet(f"color: {theme.COLOR_SUCCESS}; font-size: 11pt;")
            elif value == "off":
                self._rc_result.setText(f"\u2714 File says OFF \u2014 skipping is paused")
                self._rc_result.setStyleSheet(f"color: {theme.COLOR_WARNING}; font-size: 11pt;")
            else:
                self._rc_result.setText(f'\u26a0 File contains "{first_line}" \u2014 expected ON or OFF')
                self._rc_result.setStyleSheet(f"color: {theme.COLOR_ERROR}; font-size: 11pt;")
        except Exception as e:
            self._rc_result.setText(f"\u2716 Failed: {e}")
            self._rc_result.setStyleSheet(f"color: {theme.COLOR_ERROR}; font-size: 11pt;")

    # ----------------------------------------------------------
    # Test notification
    # ----------------------------------------------------------

    def _test_notification(self):
        try:
            from winotify import Notification, audio
            toast = Notification(
                app_id="Spotify Auto-Skipper",
                title="Smart Shuffle Recommendation",
                msg="This is a test notification.",
                duration="long",
                icon=os.path.abspath(resource_path("assets/app.ico")),
                launch="spotify:",
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
        except Exception as e:
            QMessageBox.warning(self, "Notification Error", f"Failed to show notification: {e}")

    # ----------------------------------------------------------
    # Load / Save
    # ----------------------------------------------------------

    def _load_values(self):
        for key, widget in self._fields.items():
            widget.set(self._cfg.get(key))
        self._artist_widget.set(self._cfg.get("never_skip_artists", []))
        self._config_dir_picker.set(get_config_dir())
        self._log_dir_picker.set(get_log_dir())

    def _on_save(self):
        values = {}
        for key, widget in self._fields.items():
            values[key] = widget.get()

        values["never_skip_artists"] = self._artist_widget.get()

        if values["poll_interval_seconds"] < 5:
            QMessageBox.warning(self, "Invalid value",
                                "Poll interval must be at least 5 seconds.")
            return

        if values["skip_window_days"] < 1:
            QMessageBox.warning(self, "Invalid value",
                                "Skip window must be at least 1 day.")
            return

        for key, value in values.items():
            self._cfg.set(key, value)

        new_config_dir = self._config_dir_picker.get().strip()
        if new_config_dir and os.path.normcase(os.path.normpath(new_config_dir)) != \
           os.path.normcase(os.path.normpath(get_config_dir())):
            self._cfg.move_to(new_config_dir)
        else:
            self._cfg.save()

        new_log_dir = self._log_dir_picker.get().strip()
        if new_log_dir and os.path.normcase(os.path.normpath(new_log_dir)) != \
           os.path.normcase(os.path.normpath(get_log_dir())):
            set_log_dir(new_log_dir)

        set_startup(values.get("start_with_windows", False))
        load_config()

        print("\u2705 Settings saved.")
        self.close()

    def _on_exit_app(self):
        reply = QMessageBox.question(
            self, "Exit App",
            "Are you sure you want to exit Spotify Auto-Skipper?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.close()
            print("\U0001f6d1 Exit requested from Settings window.")
            sys.stdout.flush()
            os._exit(0)

    def closeEvent(self, event):
        SettingsWindow._instance = None
        event.accept()
