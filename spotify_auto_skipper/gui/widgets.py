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
    Shows a list of artist names with X buttons for removal.
    Has a search field + Add button to search Spotify and add artists.
    Data model: list of {"id": str, "name": str} dicts.
    """

    def __init__(self, parent, search_fn=None, **kwargs):
        """
        search_fn: callable(query) -> list of {"id", "name"} dicts
                   (defaults to offline-only mode if None)
        """
        super().__init__(parent, **kwargs)
        self._artists = []  # list of {"id": str, "name": str}
        self._search_fn = search_fn

        # --- Artist list (scrollable) ---
        list_frame = ttk.Frame(self)
        list_frame.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(list_frame, height=100, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._canvas.yview)
        self._inner_frame = ttk.Frame(self._canvas)

        self._inner_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        )
        self._canvas.create_window((0, 0), window=self._inner_frame, anchor="nw")
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

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

    def get(self):
        """Return the list of {"id", "name"} dicts."""
        return list(self._artists)

    def set(self, artists):
        """Load a list of {"id", "name"} dicts."""
        self._artists = list(artists) if artists else []
        self._rebuild_list()

    def _rebuild_list(self):
        """Redraw the artist list."""
        for child in self._inner_frame.winfo_children():
            child.destroy()

        if not self._artists:
            ttk.Label(self._inner_frame, text="No artists added", foreground="gray").pack(anchor="w")
            return

        for i, artist in enumerate(self._artists):
            row = ttk.Frame(self._inner_frame)
            row.pack(fill="x", pady=1)

            name = artist.get("name") or artist.get("id", "Unknown")
            ttk.Label(row, text=name).pack(side="left", padx=(5, 0))

            # Show ID in parentheses if name is available (for transparency)
            if artist.get("name") and artist.get("id"):
                id_short = artist["id"][:8] + "..."
                ttk.Label(row, text=f"({id_short})", foreground="gray").pack(side="left", padx=(5, 0))

            remove_btn = ttk.Button(
                row, text="\u2715", width=3,
                command=lambda idx=i: self._remove_artist(idx)
            )
            remove_btn.pack(side="right", padx=(5, 0))

    def _remove_artist(self, index):
        if 0 <= index < len(self._artists):
            self._artists.pop(index)
            self._rebuild_list()

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
                chosen = results[sel[0]]
                # Don't add duplicates
                if not any(a["id"] == chosen["id"] for a in self._artists):
                    self._artists.append(chosen)
                    self._rebuild_list()
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
