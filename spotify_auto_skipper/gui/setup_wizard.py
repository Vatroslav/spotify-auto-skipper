import tkinter as tk
from tkinter import ttk, messagebox
import base64
import sys
import requests

from spotify_auto_skipper.config import Config, load_config
from spotify_auto_skipper.gui.widgets import LabeledEntry, LabeledSpinbox, LabeledCheckbox


class SetupWizard:
    """
    Multi-step first-run wizard. Launches when no config file is found.
    Steps:
      1. Last.fm credentials + Test Connection
      2. Spotify credentials + Test Token
      3. Settings (skip window, poll interval)
      4. Summary + Finish (saves config)
    Blocks until complete. If user cancels, exits the app.
    """

    def __init__(self):
        self._cfg = Config()
        self._root = tk.Tk()
        self._root.title("Spotify Auto-Skipper Setup")
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._step = 0
        self._fields = {}
        self._steps = [
            self._build_step_lastfm,
            self._build_step_spotify,
            self._build_step_settings,
            self._build_step_summary,
        ]
        self._completed = False

        # Container for step content (swapped on navigation)
        self._content_frame = ttk.Frame(self._root, padding=15)
        self._content_frame.pack(fill="both", expand=True)

        # Navigation bar
        self._nav_frame = ttk.Frame(self._root, padding=(15, 0, 15, 15))
        self._nav_frame.pack(fill="x")

        self._back_btn = ttk.Button(self._nav_frame, text="Back", command=self._go_back)
        self._back_btn.pack(side="left")

        self._next_btn = ttk.Button(self._nav_frame, text="Next", command=self._go_next)
        self._next_btn.pack(side="right")

        self._cancel_btn = ttk.Button(self._nav_frame, text="Cancel", command=self._on_close)
        self._cancel_btn.pack(side="right", padx=(0, 5))

        self._show_step()

        # Center
        self._root.update_idletasks()
        w = self._root.winfo_width()
        h = self._root.winfo_height()
        x = (self._root.winfo_screenwidth() // 2) - (w // 2)
        y = (self._root.winfo_screenheight() // 2) - (h // 2)
        self._root.geometry(f"+{x}+{y}")

    def run(self):
        """Run the wizard. Returns True if completed, False if cancelled."""
        self._root.mainloop()
        return self._completed

    # ----------------------------------------------------------
    # Step builders
    # ----------------------------------------------------------

    def _clear_content(self):
        for child in self._content_frame.winfo_children():
            child.destroy()

    def _show_step(self):
        self._clear_content()
        self._steps[self._step](self._content_frame)
        self._back_btn.configure(state="normal" if self._step > 0 else "disabled")
        if self._step == len(self._steps) - 1:
            self._next_btn.configure(text="Finish")
        else:
            self._next_btn.configure(text="Next")

    def _build_step_lastfm(self, parent):
        ttk.Label(parent, text="Step 1: Last.fm Credentials", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))
        ttk.Label(parent, text="Enter your Last.fm username and API key.\nYou can get an API key at last.fm/api/account/create", wraplength=420).pack(anchor="w", pady=(0, 10))

        f = LabeledEntry(parent, "Username:")
        f.pack(fill="x", pady=3)
        if "lastfm_username" in self._fields:
            f.set(self._fields["lastfm_username"].get())
        self._fields["lastfm_username"] = f

        f = LabeledEntry(parent, "API Key:")
        f.pack(fill="x", pady=3)
        if "lastfm_api_key" in self._fields:
            f.set(self._fields["lastfm_api_key"].get())
        self._fields["lastfm_api_key"] = f

        test_frame = ttk.Frame(parent)
        test_frame.pack(fill="x", pady=(10, 0))
        self._lastfm_status = ttk.Label(test_frame, text="")
        self._lastfm_status.pack(side="left")
        ttk.Button(test_frame, text="Test Connection", command=self._test_lastfm).pack(side="right")

    def _build_step_spotify(self, parent):
        ttk.Label(parent, text="Step 2: Spotify Credentials", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))
        ttk.Label(parent, text="Enter your Spotify API credentials.\nCreate an app at developer.spotify.com/dashboard", wraplength=420).pack(anchor="w", pady=(0, 10))

        f = LabeledEntry(parent, "Client ID:")
        f.pack(fill="x", pady=3)
        if "spotify_client_id" in self._fields:
            f.set(self._fields["spotify_client_id"].get())
        self._fields["spotify_client_id"] = f

        f = LabeledEntry(parent, "Client Secret:")
        f.pack(fill="x", pady=3)
        if "spotify_client_secret" in self._fields:
            f.set(self._fields["spotify_client_secret"].get())
        self._fields["spotify_client_secret"] = f

        f = LabeledEntry(parent, "Refresh Token:")
        f.pack(fill="x", pady=3)
        if "spotify_refresh_token" in self._fields:
            f.set(self._fields["spotify_refresh_token"].get())
        self._fields["spotify_refresh_token"] = f

        test_frame = ttk.Frame(parent)
        test_frame.pack(fill="x", pady=(10, 0))
        self._spotify_status = ttk.Label(test_frame, text="")
        self._spotify_status.pack(side="left")
        ttk.Button(test_frame, text="Test Token", command=self._test_spotify).pack(side="right")

    def _build_step_settings(self, parent):
        ttk.Label(parent, text="Step 3: Settings", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))
        ttk.Label(parent, text="Configure how the auto-skipper behaves.", wraplength=420).pack(anchor="w", pady=(0, 10))

        f = LabeledSpinbox(parent, "Skip window (days):", from_=1, to=365)
        f.pack(fill="x", pady=3)
        if "skip_window_days" in self._fields:
            f.set(self._fields["skip_window_days"].get())
        else:
            f.set(60)
        self._fields["skip_window_days"] = f

        f = LabeledSpinbox(parent, "Poll interval (seconds):", from_=5, to=600)
        f.pack(fill="x", pady=3)
        if "poll_interval_seconds" in self._fields:
            f.set(self._fields["poll_interval_seconds"].get())
        else:
            f.set(120)
        self._fields["poll_interval_seconds"] = f

        f = LabeledCheckbox(parent, "Always play liked songs")
        f.pack(fill="x", pady=3)
        if "always_play_liked_songs" in self._fields:
            f.set(self._fields["always_play_liked_songs"].get())
        else:
            f.set(True)
        self._fields["always_play_liked_songs"] = f

        f = LabeledCheckbox(parent, "Enable restart-pattern detection")
        f.pack(fill="x", pady=3)
        if "enable_restart_pattern" in self._fields:
            f.set(self._fields["enable_restart_pattern"].get())
        else:
            f.set(True)
        self._fields["enable_restart_pattern"] = f

    def _build_step_summary(self, parent):
        ttk.Label(parent, text="Step 4: Summary", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))
        ttk.Label(parent, text="Review your settings and click Finish to save.", wraplength=420).pack(anchor="w", pady=(0, 10))

        summary = ttk.Frame(parent, padding=10, relief="groove", borderwidth=1)
        summary.pack(fill="x")

        rows = [
            ("Last.fm user:", self._fields.get("lastfm_username", None)),
            ("Spotify Client ID:", self._fields.get("spotify_client_id", None)),
            ("Skip window:", self._fields.get("skip_window_days", None)),
            ("Poll interval:", self._fields.get("poll_interval_seconds", None)),
            ("Always play liked:", self._fields.get("always_play_liked_songs", None)),
            ("Restart pattern:", self._fields.get("enable_restart_pattern", None)),
        ]
        for label, field in rows:
            row = ttk.Frame(summary)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=label, width=22, anchor="w").pack(side="left")
            val = str(field.get()) if field else "N/A"
            ttk.Label(row, text=val).pack(side="left")

    # ----------------------------------------------------------
    # Navigation
    # ----------------------------------------------------------

    def _go_back(self):
        if self._step > 0:
            self._step -= 1
            self._show_step()

    def _go_next(self):
        # Validate current step
        if self._step == 0:
            if not self._fields["lastfm_username"].get().strip():
                messagebox.showwarning("Missing field", "Last.fm username is required.", parent=self._root)
                return
            if not self._fields["lastfm_api_key"].get().strip():
                messagebox.showwarning("Missing field", "Last.fm API key is required.", parent=self._root)
                return

        elif self._step == 1:
            if not self._fields["spotify_client_id"].get().strip():
                messagebox.showwarning("Missing field", "Spotify Client ID is required.", parent=self._root)
                return
            if not self._fields["spotify_client_secret"].get().strip():
                messagebox.showwarning("Missing field", "Spotify Client Secret is required.", parent=self._root)
                return
            if not self._fields["spotify_refresh_token"].get().strip():
                messagebox.showwarning("Missing field", "Spotify Refresh Token is required.", parent=self._root)
                return

        # Last step → save and finish
        if self._step == len(self._steps) - 1:
            self._save_and_finish()
            return

        self._step += 1
        self._show_step()

    def _save_and_finish(self):
        """Save all collected values to config and close."""
        keys_to_save = [
            "lastfm_username", "lastfm_api_key",
            "spotify_client_id", "spotify_client_secret", "spotify_refresh_token",
            "skip_window_days", "poll_interval_seconds",
            "always_play_liked_songs", "enable_restart_pattern",
        ]
        for key in keys_to_save:
            if key in self._fields:
                self._cfg.set(key, self._fields[key].get())

        self._cfg.save()
        load_config()
        self._completed = True
        self._root.destroy()

    def _on_close(self):
        if messagebox.askyesno(
            "Cancel Setup",
            "Are you sure you want to cancel? The app cannot run without configuration.",
            parent=self._root,
        ):
            self._root.destroy()
            sys.exit(0)

    # ----------------------------------------------------------
    # Test buttons
    # ----------------------------------------------------------

    def _test_lastfm(self):
        username = self._fields["lastfm_username"].get().strip()
        api_key = self._fields["lastfm_api_key"].get().strip()
        if not username or not api_key:
            self._lastfm_status.configure(text="Fill in both fields first", foreground="red")
            return

        self._lastfm_status.configure(text="Testing...", foreground="gray")
        self._root.update()

        try:
            r = requests.get(
                "https://ws.audioscrobbler.com/2.0/",
                params={
                    "method": "user.getinfo",
                    "user": username,
                    "api_key": api_key,
                    "format": "json",
                },
                timeout=10,
            )
            if r.status_code == 200 and "user" in r.json():
                self._lastfm_status.configure(text="Connection successful!", foreground="green")
            else:
                self._lastfm_status.configure(text="Invalid credentials", foreground="red")
        except Exception as e:
            self._lastfm_status.configure(text=f"Error: {e}", foreground="red")

    def _test_spotify(self):
        client_id = self._fields["spotify_client_id"].get().strip()
        client_secret = self._fields["spotify_client_secret"].get().strip()
        refresh_token = self._fields["spotify_refresh_token"].get().strip()

        if not client_id or not client_secret or not refresh_token:
            self._spotify_status.configure(text="Fill in all fields first", foreground="red")
            return

        self._spotify_status.configure(text="Testing...", foreground="gray")
        self._root.update()

        try:
            auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            r = requests.post(
                "https://accounts.spotify.com/api/token",
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=10,
            )
            if r.status_code == 200 and "access_token" in r.json():
                self._spotify_status.configure(text="Token refresh successful!", foreground="green")
            else:
                self._spotify_status.configure(text="Invalid credentials or token", foreground="red")
        except Exception as e:
            self._spotify_status.configure(text=f"Error: {e}", foreground="red")
