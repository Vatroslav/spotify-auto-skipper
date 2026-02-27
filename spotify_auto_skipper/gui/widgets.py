import tkinter as tk
from tkinter import ttk


class LabeledEntry(ttk.Frame):
    """A label + entry pair, optionally masked for passwords."""

    def __init__(self, parent, label_text, show=None, width=40, **kwargs):
        super().__init__(parent, **kwargs)
        self.label = ttk.Label(self, text=label_text, width=28, anchor="w")
        self.label.pack(side="left", padx=(0, 5))
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        if show:
            self.entry.configure(show=show)
        self.entry.pack(side="left", fill="x", expand=True)

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value)


class LabeledSpinbox(ttk.Frame):
    """A label + spinbox for numeric values."""

    def __init__(self, parent, label_text, from_=1, to=9999, width=8, **kwargs):
        super().__init__(parent, **kwargs)
        self.label = ttk.Label(self, text=label_text, width=28, anchor="w")
        self.label.pack(side="left", padx=(0, 5))
        self.var = tk.IntVar()
        self.spinbox = ttk.Spinbox(
            self, textvariable=self.var, from_=from_, to=to, width=width
        )
        self.spinbox.pack(side="left")

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(int(value))


class LabeledCheckbox(ttk.Frame):
    """A checkbox with a label."""

    def __init__(self, parent, label_text, **kwargs):
        super().__init__(parent, **kwargs)
        self.var = tk.BooleanVar()
        self.check = ttk.Checkbutton(self, text=label_text, variable=self.var)
        self.check.pack(side="left")

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(bool(value))


class ArtistListWidget(ttk.Frame):
    """
    Widget for managing never-skip artists.
    Displays artists as Material-style chips in a flowing layout.
    Has a search field + Add button to search Spotify and add artists.
    Data model: list of {"id": str, "name": str} dicts, sorted alphabetically.
    """

    # Chip style constants
    _CHIP_BG = "#e8e8e8"
    _CHIP_FG = "#333333"
    _CHIP_X_FG = "#666666"
    _CHIP_X_HOVER = "#cc0000"
    _CHIP_FONT = ("Segoe UI", 9)
    _CHIP_X_FONT = ("Segoe UI", 8, "bold")
    _CHIP_PADX = 6
    _CHIP_PADY = 3

    def __init__(self, parent, search_fn=None, **kwargs):
        """
        search_fn: callable(query) -> list of {"id", "name"} dicts
                   (defaults to offline-only mode if None)
        """
        super().__init__(parent, **kwargs)
        self._artists = []  # list of {"id": str, "name": str}
        self._search_fn = search_fn

        # --- Chip area (scrollable Text widget for flow layout) ---
        list_frame = ttk.Frame(self)
        list_frame.pack(fill="both", expand=True)

        self._text = tk.Text(
            list_frame, height=5, wrap="word", cursor="arrow",
            state="disabled", relief="sunken", borderwidth=1,
            background="#fafafa", highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=scrollbar.set)

        self._text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse-wheel scrolling
        self._text.bind("<MouseWheel>", self._on_mousewheel)
        self._text.bind("<Enter>", self._bind_global_mousewheel)
        self._text.bind("<Leave>", self._unbind_global_mousewheel)

        # --- Search bar ---
        search_frame = ttk.Frame(self)
        search_frame.pack(fill="x", pady=(5, 0))

        self._search_var = tk.StringVar()
        self._search_entry = ttk.Entry(search_frame, textvariable=self._search_var)
        self._search_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self._search_entry.bind("<Return>", lambda e: self._on_search())

        self._search_btn = ttk.Button(search_frame, text="Search & Add", command=self._on_search)
        self._search_btn.pack(side="right")

        # --- Search results popup (Listbox) ---
        self._results_popup = None

    # ----------------------------------------------------------
    # Mouse-wheel scrolling
    # ----------------------------------------------------------

    def _on_mousewheel(self, event):
        self._text.yview_scroll(-1 * (event.delta // 120), "units")
        return "break"

    def _bind_global_mousewheel(self, event):
        self._text.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_global_mousewheel(self, event):
        self._text.unbind_all("<MouseWheel>")

    # ----------------------------------------------------------
    # Data access
    # ----------------------------------------------------------

    def get(self):
        """Return the list of {"id", "name"} dicts (sorted alphabetically)."""
        return list(self._artists)

    def set(self, artists):
        """Load a list of {"id", "name"} dicts."""
        self._artists = list(artists) if artists else []
        self._sort_artists()
        self._rebuild_chips()

    def _sort_artists(self):
        """Sort artists alphabetically by name (case-insensitive)."""
        self._artists.sort(
            key=lambda a: (a.get("name") or a.get("id", "")).lower()
        )

    # ----------------------------------------------------------
    # Chip rendering
    # ----------------------------------------------------------

    def _rebuild_chips(self):
        """Redraw all artist chips in a flowing layout."""
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")

        if not self._artists:
            self._text.insert("1.0", "  No artists added")
            self._text.configure(state="disabled", foreground="gray")
            return

        self._text.configure(foreground=self._CHIP_FG)

        for i, artist in enumerate(self._artists):
            chip = self._create_chip(artist, i)
            self._text.window_create("end", window=chip, padx=3, pady=3)

        self._text.configure(state="disabled")

    def _create_chip(self, artist, index):
        """Create a single chip widget for an artist."""
        name = artist.get("name") or artist.get("id", "Unknown")

        chip = tk.Frame(
            self._text, background=self._CHIP_BG,
            padx=self._CHIP_PADX, pady=self._CHIP_PADY,
        )

        label = tk.Label(
            chip, text=name, background=self._CHIP_BG,
            foreground=self._CHIP_FG, font=self._CHIP_FONT,
            cursor="arrow",
        )
        label.pack(side="left", padx=(2, 4))

        x_btn = tk.Label(
            chip, text="\u2715", background=self._CHIP_BG,
            foreground=self._CHIP_X_FG, font=self._CHIP_X_FONT,
            cursor="hand2",
        )
        x_btn.pack(side="left", padx=(0, 2))

        # Hover effect on X button
        x_btn.bind("<Enter>", lambda e: x_btn.configure(foreground=self._CHIP_X_HOVER))
        x_btn.bind("<Leave>", lambda e: x_btn.configure(foreground=self._CHIP_X_FG))
        x_btn.bind("<Button-1>", lambda e, idx=index: self._remove_artist(idx))

        # Forward mouse wheel from chip elements to the text widget
        for w in (chip, label, x_btn):
            w.bind("<MouseWheel>", self._on_mousewheel)

        return chip

    # ----------------------------------------------------------
    # Add / Remove
    # ----------------------------------------------------------

    def _remove_artist(self, index):
        if 0 <= index < len(self._artists):
            self._artists.pop(index)
            self._rebuild_chips()

    def _add_artist(self, artist):
        """Add an artist (if not duplicate), sort, and rebuild."""
        if not any(a["id"] == artist["id"] for a in self._artists):
            self._artists.append(artist)
            self._sort_artists()
            self._rebuild_chips()

    def _on_search(self):
        query = self._search_var.get().strip()
        if not query:
            return

        if self._search_fn is None:
            return

        # Close existing popup
        self._close_results()

        results = self._search_fn(query)
        if not results:
            self._search_var.set("")
            return

        # Show results in a popup listbox
        self._results_popup = tk.Toplevel(self)
        self._results_popup.title("Select Artist")
        self._results_popup.transient(self.winfo_toplevel())
        self._results_popup.grab_set()
        self._results_popup.resizable(False, False)

        ttk.Label(self._results_popup, text=f'Results for "{query}":', padding=5).pack(anchor="w")

        listbox = tk.Listbox(self._results_popup, height=min(len(results), 8), width=50)
        listbox.pack(padx=10, pady=(0, 5), fill="x")

        for r in results:
            listbox.insert("end", r["name"])

        def on_select():
            sel = listbox.curselection()
            if sel:
                self._add_artist(results[sel[0]])
            self._close_results()
            self._search_var.set("")

        btn_frame = ttk.Frame(self._results_popup)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Add Selected", command=on_select).pack(side="right", padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=self._close_results).pack(side="right")

        listbox.bind("<Double-1>", lambda e: on_select())

        # Center popup on parent
        self._results_popup.update_idletasks()
        pw = self.winfo_toplevel()
        x = pw.winfo_x() + pw.winfo_width() // 2 - self._results_popup.winfo_width() // 2
        y = pw.winfo_y() + pw.winfo_height() // 2 - self._results_popup.winfo_height() // 2
        self._results_popup.geometry(f"+{x}+{y}")

    def _close_results(self):
        if self._results_popup and self._results_popup.winfo_exists():
            self._results_popup.destroy()
        self._results_popup = None
