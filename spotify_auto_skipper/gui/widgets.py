import io
import tkinter as tk
from tkinter import ttk, filedialog

import requests
from PIL import Image, ImageTk, ImageDraw


class LabeledDirectoryPicker(ttk.Frame):
    """A label + read-only entry + Browse button for choosing a directory."""

    def __init__(self, parent, label_text, toplevel=None, width=40, **kwargs):
        super().__init__(parent, **kwargs)
        self._toplevel = toplevel  # parent window for the dialog

        self.label = ttk.Label(self, text=label_text, width=16, anchor="w")
        self.label.pack(side="left", padx=(0, 5))

        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn = ttk.Button(self, text="Browse\u2026", width=8, command=self._browse)
        self.btn.pack(side="right")

    def _browse(self):
        current = self.var.get()
        chosen = filedialog.askdirectory(
            initialdir=current if current else None,
            title="Select folder",
            parent=self._toplevel,
        )
        if chosen:
            self.var.set(chosen)

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value if value else "")


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

    # Search result thumbnail size (pixels)
    _THUMB_SIZE = 56
    _PAGE_SIZE = 5

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

        # --- Search results popup ---
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
        """Add an artist (if not duplicate), sort, and rebuild.
        Only stores id + name — extra search fields are discarded."""
        if not any(a["id"] == artist["id"] for a in self._artists):
            self._artists.append({"id": artist["id"], "name": artist["name"]})
            self._sort_artists()
            self._rebuild_chips()

    # ----------------------------------------------------------
    # Search & Results popup
    # ----------------------------------------------------------

    def _on_search(self):
        query = self._search_var.get().strip()
        if not query or not self._search_fn:
            return

        self._close_results()

        # --- Show loading popup immediately ---
        popup = tk.Toplevel(self)
        self._results_popup = popup
        popup.title("Select Artist")
        popup.transient(self.winfo_toplevel())
        popup.grab_set()
        popup.resizable(False, False)

        popup._loading = ttk.Label(
            popup, text="  Searching Spotify\u2026  ",
            font=("Segoe UI", 10), padding=20,
        )
        popup._loading.pack()

        self._center_popup(popup)
        popup.update()

        # --- Fetch first page (blocking) ---
        results = self._search_fn(query)
        if not results:
            self._close_results()
            self._search_var.set("")
            return

        popup._loading.configure(text="  Loading images\u2026  ")
        popup.update()

        placeholder = self._create_placeholder()
        thumbnails = self._fetch_thumbnails(results, placeholder)

        # --- Build result UI ---
        popup._loading.destroy()

        popup._state = {
            "query": query,
            "pages": [results],
            "page_thumbs": [thumbnails],
            "current_page": 0,
            "has_more": len(results) >= self._PAGE_SIZE,
            "placeholder": placeholder,
            "selected": None,
            "rows": [],
        }

        ttk.Label(
            popup, text=f'Results for "{query}":', padding=5,
        ).pack(anchor="w")

        popup._results_frame = tk.Frame(
            popup, bg="white", relief="sunken", bd=1,
        )
        popup._results_frame.pack(fill="x", padx=10, pady=(0, 5))

        self._build_page_rows(popup)

        # Navigation: [← Back]  Page N  [Next →]
        nav_frame = tk.Frame(popup)
        popup._nav_frame = nav_frame

        popup._prev_btn = ttk.Button(
            nav_frame, text="\u2190 Back",
            command=lambda: self._go_prev(popup), width=10,
        )
        popup._prev_btn.pack(side="left")

        popup._page_label = ttk.Label(
            nav_frame, text="Page 1", font=("Segoe UI", 9),
        )
        popup._page_label.pack(side="left", expand=True)

        popup._next_btn = ttk.Button(
            nav_frame, text="Next \u2192",
            command=lambda: self._go_next(popup), width=10,
        )
        popup._next_btn.pack(side="right")

        if popup._state["has_more"]:
            nav_frame.pack(fill="x", padx=10, pady=(0, 5))

        self._update_nav(popup)

        # Add / Cancel buttons
        def on_select():
            s = popup._state
            if s["selected"] is not None:
                page = s["pages"][s["current_page"]]
                self._add_artist(page[s["selected"]])
            self._close_results()
            self._search_var.set("")

        popup._on_select = on_select

        btn_frame = ttk.Frame(popup)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Add Selected", command=on_select).pack(
            side="right", padx=(5, 0),
        )
        ttk.Button(btn_frame, text="Cancel", command=self._close_results).pack(
            side="right",
        )

        self._center_popup(popup)

    def _fetch_thumbnails(self, results, placeholder):
        """Download thumbnails for a batch of search results."""
        thumbnails = []
        for r in results:
            url = r.get("image_url", "")
            thumb = self._download_thumbnail(url) if url else None
            thumbnails.append(thumb or placeholder)
        return thumbnails

    def _build_page_rows(self, popup):
        """Clear and rebuild result rows for the current page."""
        frame = popup._results_frame
        state = popup._state

        for w in frame.winfo_children():
            w.destroy()
        state["rows"] = []
        state["selected"] = None

        page_idx = state["current_page"]
        results = state["pages"][page_idx]
        thumbnails = state["page_thumbs"][page_idx]

        _N = "white"
        _S = "#e3f2fd"

        def select_row(idx):
            prev = state["selected"]
            if prev is not None and prev < len(state["rows"]):
                for w in state["rows"][prev]:
                    try:
                        w.configure(background=_N)
                    except tk.TclError:
                        pass
            state["selected"] = idx
            for w in state["rows"][idx]:
                try:
                    w.configure(background=_S)
                except tk.TclError:
                    pass

        for i, artist in enumerate(results):
            if i > 0:
                tk.Frame(frame, bg="#eeeeee", height=1).pack(fill="x")

            row = tk.Frame(frame, bg=_N, cursor="hand2")
            row.pack(fill="x")

            img_label = tk.Label(row, image=thumbnails[i], bg=_N)
            img_label.pack(side="left", padx=(8, 10), pady=6)

            text_frame = tk.Frame(row, bg=_N)
            text_frame.pack(side="left", fill="x", expand=True, pady=6)

            name_label = tk.Label(
                text_frame, text=artist["name"], bg=_N,
                font=("Segoe UI", 10, "bold"), anchor="w",
            )
            name_label.pack(fill="x")

            info = self._format_result_info(artist)
            all_widgets = [row, img_label, text_frame, name_label]
            if info:
                info_label = tk.Label(
                    text_frame, text=info, bg=_N,
                    font=("Segoe UI", 8), fg="#888888", anchor="w",
                )
                info_label.pack(fill="x")
                all_widgets.append(info_label)

            state["rows"].append(all_widgets)

            for w in all_widgets:
                w.bind("<Button-1>", lambda e, idx=i: select_row(idx))
                w.bind(
                    "<Double-1>",
                    lambda e, idx=i: (select_row(idx), popup._on_select()),
                )

    def _go_prev(self, popup):
        """Navigate to the previous page (always cached, instant)."""
        if not popup.winfo_exists():
            return
        state = popup._state
        if state["current_page"] > 0:
            state["current_page"] -= 1
            self._build_page_rows(popup)
            self._update_nav(popup)

    def _go_next(self, popup):
        """Navigate to the next page (fetch from API if not cached)."""
        if not popup.winfo_exists():
            return
        state = popup._state
        next_page = state["current_page"] + 1

        if next_page < len(state["pages"]):
            state["current_page"] = next_page
            self._build_page_rows(popup)
            self._update_nav(popup)
            return

        # Need to fetch from API
        popup._next_btn.configure(text="Loading\u2026", state="disabled")
        popup.update()

        offset = sum(len(p) for p in state["pages"])
        try:
            new_results = self._search_fn(state["query"], offset=offset)
        except TypeError:
            state["has_more"] = False
            self._update_nav(popup)
            return

        if not new_results:
            state["has_more"] = False
            self._update_nav(popup)
            return

        new_thumbs = self._fetch_thumbnails(new_results, state["placeholder"])
        state["pages"].append(new_results)
        state["page_thumbs"].append(new_thumbs)
        state["has_more"] = len(new_results) >= self._PAGE_SIZE
        state["current_page"] = next_page

        self._build_page_rows(popup)
        self._update_nav(popup)

    def _update_nav(self, popup):
        """Update navigation button states and page label."""
        if not popup.winfo_exists():
            return
        state = popup._state
        page = state["current_page"]

        # Show nav bar once multiple pages exist (or might)
        if state["has_more"] or len(state["pages"]) > 1:
            popup._nav_frame.pack(fill="x", padx=10, pady=(0, 5))

        popup._prev_btn.configure(
            state="normal" if page > 0 else "disabled",
        )

        can_go_next = state["has_more"] or page < len(state["pages"]) - 1
        popup._next_btn.configure(
            text="Next \u2192",
            state="normal" if can_go_next else "disabled",
        )

        popup._page_label.configure(text=f"Page {page + 1}")

    def _center_popup(self, popup):
        """Center the popup over the parent window."""
        popup.update_idletasks()
        pw = self.winfo_toplevel()
        x = pw.winfo_x() + pw.winfo_width() // 2 - popup.winfo_width() // 2
        y = pw.winfo_y() + pw.winfo_height() // 2 - popup.winfo_height() // 2
        popup.geometry(f"+{x}+{y}")

    # ----------------------------------------------------------
    # Formatting & image helpers
    # ----------------------------------------------------------

    @staticmethod
    def _format_followers(n):
        """Format follower count: 1234567 -> '1.2M', 45000 -> '45K'."""
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.0f}K"
        return str(n)

    @classmethod
    def _format_result_info(cls, artist):
        """Format the info line: '52.3M followers · Rock, Classic Rock'."""
        parts = []
        followers = artist.get("followers", 0)
        if followers:
            parts.append(f"{cls._format_followers(followers)} followers")
        genres = artist.get("genres", [])
        if genres:
            parts.append(", ".join(g.title() for g in genres[:3]))
        return " \u00b7 ".join(parts)

    @classmethod
    def _download_thumbnail(cls, url):
        """Download image URL and return a circular PhotoImage thumbnail."""
        try:
            r = requests.get(url, timeout=5)
            if r.status_code != 200:
                return None
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            img = img.resize((cls._THUMB_SIZE, cls._THUMB_SIZE), Image.LANCZOS)

            # Circular mask
            mask = Image.new("L", (cls._THUMB_SIZE, cls._THUMB_SIZE), 0)
            ImageDraw.Draw(mask).ellipse(
                (0, 0, cls._THUMB_SIZE - 1, cls._THUMB_SIZE - 1), fill=255,
            )
            output = Image.new("RGBA", (cls._THUMB_SIZE, cls._THUMB_SIZE), (0, 0, 0, 0))
            output.paste(img, mask=mask)
            return ImageTk.PhotoImage(output)
        except Exception:
            return None

    @classmethod
    def _create_placeholder(cls):
        """Create a gray circle placeholder thumbnail."""
        img = Image.new("RGBA", (cls._THUMB_SIZE, cls._THUMB_SIZE), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse(
            (0, 0, cls._THUMB_SIZE - 1, cls._THUMB_SIZE - 1), fill=(200, 200, 200, 255),
        )
        return ImageTk.PhotoImage(img)

    def _close_results(self):
        if self._results_popup and self._results_popup.winfo_exists():
            self._results_popup.destroy()
        self._results_popup = None
