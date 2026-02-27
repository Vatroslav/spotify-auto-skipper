import tkinter as tk
from tkinter import ttk, messagebox

from spotify_auto_skipper.config import Config, load_config
from spotify_auto_skipper.startup import set_startup
from spotify_auto_skipper.gui.widgets import LabeledEntry, LabeledSpinbox, LabeledCheckbox, ArtistListWidget


class SettingsWindow:
    """
    Singleton settings window with 3 tabs:
      - Settings (skip window, polling, feature toggles)
      - Advanced (dummy playlist, remote control, never-skip artists, autostart)
      - Credentials (Last.fm + Spotify)
    """
    _instance = None

    @classmethod
    def open(cls, parent=None):
        """Open the settings window, or bring existing one to front."""
        if cls._instance is not None and cls._instance._window.winfo_exists():
            cls._instance._window.lift()
            cls._instance._window.focus_force()
            return cls._instance
        inst = cls(parent)
        cls._instance = inst
        return inst

    def __init__(self, parent=None):
        self._cfg = Config()
        self._parent = parent
        self._window = tk.Toplevel(parent) if parent else tk.Tk()
        self._window.title("Spotify Auto-Skipper Settings")
        self._window.resizable(False, False)
        self._window.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Build the UI
        self._fields = {}
        self._build_notebook()
        self._build_buttons()
        self._load_values()

        # Center on screen
        self._window.update_idletasks()
        w = self._window.winfo_width()
        h = self._window.winfo_height()
        x = (self._window.winfo_screenwidth() // 2) - (w // 2)
        y = (self._window.winfo_screenheight() // 2) - (h // 2)
        self._window.geometry(f"+{x}+{y}")

    # ----------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------

    def _build_notebook(self):
        notebook = ttk.Notebook(self._window)
        notebook.pack(padx=10, pady=(10, 0), fill="both", expand=True)

        self._build_settings_tab(notebook)
        self._build_advanced_tab(notebook)
        self._build_credentials_tab(notebook)

    def _build_credentials_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=15)
        notebook.add(frame, text="Credentials")

        # Last.fm section
        lbl = ttk.Label(frame, text="Last.fm", font=("Segoe UI", 10, "bold"))
        lbl.pack(anchor="w", pady=(0, 5))

        f = LabeledEntry(frame, "Username:")
        f.pack(fill="x", pady=2)
        self._fields["lastfm_username"] = f

        f = LabeledEntry(frame, "API Key:", show="*")
        f.pack(fill="x", pady=2)
        self._fields["lastfm_api_key"] = f

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)

        # Spotify section
        lbl = ttk.Label(frame, text="Spotify", font=("Segoe UI", 10, "bold"))
        lbl.pack(anchor="w", pady=(0, 5))

        f = LabeledEntry(frame, "Client ID:")
        f.pack(fill="x", pady=2)
        self._fields["spotify_client_id"] = f

        f = LabeledEntry(frame, "Client Secret:", show="*")
        f.pack(fill="x", pady=2)
        self._fields["spotify_client_secret"] = f

        f = LabeledEntry(frame, "Refresh Token:", show="*")
        f.pack(fill="x", pady=2)
        self._fields["spotify_refresh_token"] = f

    def _build_settings_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=15)
        notebook.add(frame, text="Settings")

        f = LabeledSpinbox(frame, "Skip window (days):", from_=1, to=365)
        f.pack(fill="x", pady=2)
        self._fields["skip_window_days"] = f

        f = LabeledSpinbox(frame, "Poll interval (seconds):", from_=5, to=600)
        f.pack(fill="x", pady=2)
        self._fields["poll_interval_seconds"] = f

        f = LabeledSpinbox(frame, "Log retention (days):", from_=1, to=365)
        f.pack(fill="x", pady=2)
        self._fields["log_retention_days"] = f

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)

        f = LabeledCheckbox(frame, "Always play liked songs")
        f.pack(fill="x", pady=2)
        self._fields["always_play_liked_songs"] = f

        f = LabeledCheckbox(frame, "Enable restart-pattern detection")
        f.pack(fill="x", pady=2)
        self._fields["enable_restart_pattern"] = f

        # Restart pattern sub-settings
        sub = ttk.Frame(frame, padding=(20, 0, 0, 0))
        sub.pack(fill="x")

        f = LabeledSpinbox(sub, "Consecutive skips:", from_=2, to=20)
        f.pack(fill="x", pady=2)
        self._fields["restart_pattern_song_count"] = f

        f = LabeledSpinbox(sub, "Day difference threshold:", from_=0, to=30)
        f.pack(fill="x", pady=2)
        self._fields["restart_pattern_day_diff"] = f

    def _build_advanced_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=15)
        notebook.add(frame, text="Advanced")

        f = LabeledEntry(frame, "Dummy Playlist ID:")
        f.pack(fill="x", pady=2)
        self._fields["dummy_playlist_id"] = f

        f = LabeledEntry(frame, "Remote Control URL:")
        f.pack(fill="x", pady=2)
        self._fields["remote_control_url"] = f

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)

        lbl = ttk.Label(frame, text="Never-skip Artists:", font=("Segoe UI", 10, "bold"))
        lbl.pack(anchor="w", pady=(0, 3))

        from spotify_auto_skipper.spotify_api import search_artists
        self._artist_widget = ArtistListWidget(frame, search_fn=search_artists)
        self._artist_widget.pack(fill="both", expand=True, pady=2)

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)

        f = LabeledCheckbox(frame, "Start with Windows")
        f.pack(fill="x", pady=2)
        self._fields["start_with_windows"] = f

    def _build_buttons(self):
        btn_frame = ttk.Frame(self._window)
        btn_frame.pack(fill="x", padx=10, pady=10)

        ttk.Button(btn_frame, text="Save", command=self._on_save).pack(
            side="right", padx=(5, 0)
        )
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(
            side="right"
        )

    # ----------------------------------------------------------
    # Load / Save
    # ----------------------------------------------------------

    def _load_values(self):
        """Populate all fields from the current Config."""
        for key, widget in self._fields.items():
            widget.set(self._cfg.get(key))
        # Load artist list
        self._artist_widget.set(self._cfg.get("never_skip_artists", []))

    def _on_save(self):
        """Validate, save to Config, reload module-level vars, close."""
        # Read values
        values = {}
        for key, widget in self._fields.items():
            values[key] = widget.get()

        # Artist list (special handling — not in _fields)
        values["never_skip_artists"] = self._artist_widget.get()

        # Validation
        if values["poll_interval_seconds"] < 5:
            messagebox.showwarning(
                "Invalid value",
                "Poll interval must be at least 5 seconds.",
                parent=self._window,
            )
            return

        if values["skip_window_days"] < 1:
            messagebox.showwarning(
                "Invalid value",
                "Skip window must be at least 1 day.",
                parent=self._window,
            )
            return

        # Apply to Config
        for key, value in values.items():
            self._cfg.set(key, value)
        self._cfg.save()

        # Sync Windows startup registry with checkbox
        set_startup(values.get("start_with_windows", False))

        # Reload module-level variables so the running app picks up changes
        load_config()

        print("\u2705 Settings saved.")
        self._close()

    def _on_cancel(self):
        self._close()

    def _close(self):
        self._window.destroy()
        SettingsWindow._instance = None
        # If opened with a hidden root, destroy it to exit mainloop
        if self._parent:
            try:
                self._parent.destroy()
            except tk.TclError:
                pass

    def wait(self):
        """Block until the settings window is closed (for wizard-like usage)."""
        self._window.wait_window()
