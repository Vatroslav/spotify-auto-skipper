"""
PySide6 custom widgets for the Spotify Auto-Skipper GUI.
"""

import io
import threading

import requests
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QSpinBox,
    QCheckBox, QPushButton, QFrame, QScrollArea, QFileDialog, QDialog,
    QSizePolicy,
)
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QCursor
from PySide6.QtCore import Qt, Signal, QTimer, QCoreApplication

from spotify_auto_skipper.gui import theme


# -----------------------------------------------------------------
# Accent button (green primary)
# -----------------------------------------------------------------

class AccentButton(QPushButton):
    """Green primary button — styled via QSS type selector."""
    pass


# -----------------------------------------------------------------
# Separator
# -----------------------------------------------------------------

def create_separator():
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setFixedHeight(1)
    sep.setStyleSheet(f"background-color: {theme.BORDER_PRIMARY}; border: none;")
    return sep


# -----------------------------------------------------------------
# Link label
# -----------------------------------------------------------------

def create_link_label(text, url):
    """Create a clickable green hyperlink label."""
    label = QLabel(f'<a href="{url}" style="color: {theme.ACCENT};">{text}</a>')
    label.setOpenExternalLinks(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


# -----------------------------------------------------------------
# Basic labeled widgets
# -----------------------------------------------------------------

class LabeledEntry(QWidget):
    """Label + QLineEdit, optionally masked for passwords."""

    def __init__(self, parent=None, label_text="", show=None, label_width=180):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(16)

        self._label = QLabel(label_text)
        self._label.setMinimumWidth(label_width)
        self._label.setStyleSheet(f"font-weight: 500; font-size: 13pt; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(self._label)

        self._entry = QLineEdit()
        if show == "*":
            self._entry.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._entry, 1)

    def get(self):
        return self._entry.text()

    def set(self, value):
        self._entry.setText(str(value) if value else "")


class LabeledSpinbox(QWidget):
    """Label + QSpinBox."""

    def __init__(self, parent=None, label_text="", from_=1, to=9999, label_width=180):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(16)

        self._label = QLabel(label_text)
        self._label.setMinimumWidth(label_width)
        self._label.setStyleSheet(f"font-weight: 500; font-size: 13pt; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(self._label)

        self._spinbox = QSpinBox()
        self._spinbox.setRange(from_, to)
        self._spinbox.setFixedWidth(128)
        layout.addWidget(self._spinbox)
        layout.addStretch()

    def get(self):
        return self._spinbox.value()

    def set(self, value):
        self._spinbox.setValue(int(value))


class LabeledCheckbox(QWidget):
    """QCheckBox wrapper with get/set API."""

    def __init__(self, parent=None, label_text=""):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        self._check = QCheckBox(label_text)
        self._check.setStyleSheet(f"font-weight: 500; font-size: 13pt; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(self._check)
        layout.addStretch()

    def get(self):
        return self._check.isChecked()

    def set(self, value):
        self._check.setChecked(bool(value))


class LabeledDirectoryPicker(QWidget):
    """Label + read-only entry + Browse button."""

    def __init__(self, parent=None, label_text="", label_width=100):
        super().__init__(parent)
        self._parent_window = parent
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(16)

        self._label = QLabel(label_text)
        self._label.setMinimumWidth(label_width)
        self._label.setStyleSheet(f"font-weight: 500; font-size: 13pt; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(self._label)

        self._entry = QLineEdit()
        layout.addWidget(self._entry, 1)

        self._btn = QPushButton("\U0001F4C1 Browse\u2026")
        self._btn.clicked.connect(self._browse)
        layout.addWidget(self._btn)

    def _browse(self):
        current = self._entry.text()
        chosen = QFileDialog.getExistingDirectory(self, "Select folder", current)
        if chosen:
            self._entry.setText(chosen)

    def get(self):
        return self._entry.text()

    def set(self, value):
        self._entry.setText(value if value else "")


class PlaylistPicker(QWidget):
    """Playlist link/ID entry + Resolve button + status label."""

    def __init__(self, parent=None, label_text="Playlist:", description=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if description:
            desc = QLabel(description)
            desc.setWordWrap(True)
            desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
            layout.addWidget(desc)

        row = QHBoxLayout()
        row.setSpacing(16)
        lbl = QLabel(label_text)
        lbl.setMinimumWidth(100)
        lbl.setStyleSheet(f"font-weight: 500; font-size: 13pt; color: {theme.TEXT_PRIMARY};")
        row.addWidget(lbl)

        self._entry = QLineEdit()
        row.addWidget(self._entry, 1)

        self._btn = QPushButton("Resolve")
        self._btn.clicked.connect(self._resolve)
        row.addWidget(self._btn)
        layout.addLayout(row)

        self._status = QLabel()
        self._status.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11pt;")
        layout.addWidget(self._status)

        self._playlist_id = None

    def _resolve(self):
        from spotify_auto_skipper.spotify_api import extract_playlist_id, get_playlist_name
        raw = self._entry.text().strip()
        if not raw:
            self._status.setText("")
            self._playlist_id = None
            return

        pid = extract_playlist_id(raw)
        if not pid:
            self._status.setText("Invalid link or ID")
            self._playlist_id = None
            return

        self._playlist_id = pid
        self._status.setText("Resolving...")

        name = get_playlist_name(pid)
        if name:
            self._entry.setText(pid)
            self._status.setText(f"\u2714 {name}")
            self._status.setStyleSheet(f"color: {theme.COLOR_SUCCESS}; font-size: 11pt;")
        else:
            self._status.setText("Playlist not found")
            self._status.setStyleSheet(f"color: {theme.COLOR_ERROR}; font-size: 11pt;")
            self._playlist_id = None

    def get(self):
        return self._playlist_id or self._entry.text().strip()

    def set(self, value):
        self._entry.setText(value if value else "")
        self._playlist_id = value if value else None
        self._status.setText("")
        if value:
            self._try_resolve_on_load(value)

    def _try_resolve_on_load(self, playlist_id):
        def _resolve():
            try:
                from spotify_auto_skipper.spotify_api import get_playlist_name
                name = get_playlist_name(playlist_id)
                if name:
                    QTimer.singleShot(0, lambda: self._status.setText(f"\u2714 {name}"))
            except Exception:
                pass

        threading.Thread(target=_resolve, daemon=True).start()


# -----------------------------------------------------------------
# Image helpers (pure Qt, no PIL needed)
# -----------------------------------------------------------------

THUMB_SIZE = 64


def make_circular_pixmap(data, size=THUMB_SIZE):
    """Create a circular QPixmap from raw image bytes."""
    source = QPixmap()
    source.loadFromData(data)
    if source.isNull():
        return make_placeholder_pixmap(size)

    scaled = source.scaled(size, size,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    x = (scaled.width() - size) // 2
    y = (scaled.height() - size) // 2
    cropped = scaled.copy(x, y, size, size)

    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, cropped)
    painter.end()
    return result


def make_placeholder_pixmap(size=THUMB_SIZE):
    """Create a dark gray circle placeholder."""
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(*theme.PLACEHOLDER_COLOR))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return result


def download_thumbnail(url, size=THUMB_SIZE):
    """Download an image URL and return a circular QPixmap."""
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return make_circular_pixmap(r.content, size)
    except Exception:
        pass
    return None


# -----------------------------------------------------------------
# Artist card
# -----------------------------------------------------------------

class ArtistCard(QFrame):
    """Single artist row with thumbnail, name, info, and hover remove button."""
    remove_clicked = Signal(int)

    def __init__(self, index, name, info_text="", pixmap=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._index = index

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # Thumbnail
        self._thumb = QLabel()
        self._thumb.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        if pixmap:
            self._thumb.setPixmap(pixmap)
        else:
            self._thumb.setPixmap(make_placeholder_pixmap())
        layout.addWidget(self._thumb)

        # Text column
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        name_label = QLabel(name)
        name_label.setObjectName("artist_name")
        text_layout.addWidget(name_label)

        if info_text:
            info_label = QLabel(info_text)
            info_label.setObjectName("artist_info")
            text_layout.addWidget(info_label)

        layout.addWidget(text_widget, 1)

        # Remove button
        remove_btn = QPushButton("\u2715")
        remove_btn.setObjectName("remove_btn")
        remove_btn.setFixedSize(32, 32)
        remove_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self._index))
        layout.addWidget(remove_btn)

    def set_pixmap(self, pixmap):
        self._thumb.setPixmap(pixmap)


# -----------------------------------------------------------------
# Search result row
# -----------------------------------------------------------------

class SearchResultRow(QFrame):
    """Clickable artist row in the search popup."""
    clicked = Signal(int)
    double_clicked = Signal(int)

    def __init__(self, index, name, info_text="", pixmap=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._index = index
        self._selected = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        thumb = QLabel()
        thumb.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        thumb.setPixmap(pixmap or make_placeholder_pixmap())
        layout.addWidget(thumb)

        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: bold; font-size: 13pt;")
        text_layout.addWidget(name_label)

        if info_text:
            info_label = QLabel(info_text)
            info_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11pt;")
            text_layout.addWidget(info_label)

        layout.addWidget(text_widget, 1)

    def set_selected(self, selected):
        self._selected = selected
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        self.clicked.emit(self._index)

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self._index)


# -----------------------------------------------------------------
# Search artist dialog
# -----------------------------------------------------------------

class SearchArtistDialog(QDialog):
    """Modal dialog for searching and selecting a Spotify artist."""

    _PAGE_SIZE = 5

    def __init__(self, parent, search_fn, query):
        super().__init__(parent)
        self.setWindowTitle("Select Artist")
        self.setModal(True)
        self.setFixedSize(560, 600)

        self._search_fn = search_fn
        self._query = query
        self._selected_artist = None
        self._selected_idx = None
        self._rows = []
        self._state = {
            "pages": [],
            "page_thumbs": [],
            "current_page": 0,
            "has_more": False,
        }

        self._setup_ui()
        self._results_label.setText(f'Searching for "{query}"\u2026')
        QTimer.singleShot(0, lambda: self._do_search(query))

    def _setup_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)

        self._results_label = QLabel()
        self._results_label.setStyleSheet("font-size: 13pt;")
        header_layout.addWidget(self._results_label, 1)
        self._layout.addWidget(header)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {theme.BORDER_PRIMARY};")
        self._layout.addWidget(sep)

        # Scroll area for results
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        self._results_widget = QWidget()
        self._results_layout = QVBoxLayout(self._results_widget)
        self._results_layout.setContentsMargins(8, 4, 8, 4)
        self._results_layout.setSpacing(2)
        self._results_layout.addStretch()
        self._scroll.setWidget(self._results_widget)
        self._layout.addWidget(self._scroll, 1)

        # Navigation
        self._nav_widget = QWidget()
        self._nav_widget.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        nav_layout = QHBoxLayout(self._nav_widget)
        nav_layout.setContentsMargins(12, 4, 12, 4)

        self._prev_btn = QPushButton("\u2190 Back")
        self._prev_btn.setFixedWidth(90)
        self._prev_btn.clicked.connect(self._go_prev)
        nav_layout.addWidget(self._prev_btn)

        self._page_label = QLabel("Page 1")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(self._page_label, 1)

        self._next_btn = QPushButton("Next \u2192")
        self._next_btn.setFixedWidth(90)
        self._next_btn.clicked.connect(self._go_next)
        nav_layout.addWidget(self._next_btn)

        self._nav_widget.setVisible(False)
        self._layout.addWidget(self._nav_widget)

        # Footer
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background-color: {theme.BORDER_PRIMARY};")
        self._layout.addWidget(sep2)

        footer = QWidget()
        footer.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 8, 12, 8)
        footer_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        footer_layout.addWidget(cancel_btn)

        self._add_btn = AccentButton("Add Selected")
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._on_add)
        footer_layout.addWidget(self._add_btn)

        self._layout.addWidget(footer)

    def _do_search(self, query):
        QCoreApplication.processEvents()
        results = self._search_fn(query)
        if not results:
            self._results_label.setText("No results found.")
            return

        self._results_label.setText(f'Results for "{query}":')
        QCoreApplication.processEvents()
        thumbs = self._fetch_thumbnails(results)
        self._state["pages"] = [results]
        self._state["page_thumbs"] = [thumbs]
        self._state["current_page"] = 0
        self._state["has_more"] = len(results) >= self._PAGE_SIZE

        self._build_page_rows()
        self._update_nav()

    def _fetch_thumbnails(self, results):
        thumbnails = []
        placeholder = make_placeholder_pixmap()
        for r in results:
            url = r.get("image_url", "")
            thumb = download_thumbnail(url) if url else None
            thumbnails.append(thumb or placeholder)
        return thumbnails

    def _build_page_rows(self):
        # Clear existing rows
        while self._results_layout.count() > 0:
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._rows = []
        self._selected_idx = None
        self._selected_artist = None
        self._add_btn.setEnabled(False)

        state = self._state
        page_idx = state["current_page"]
        results = state["pages"][page_idx]
        thumbnails = state["page_thumbs"][page_idx]

        for i, artist in enumerate(results):
            info = _format_result_info(artist)
            row = SearchResultRow(i, artist["name"], info, thumbnails[i])
            row.clicked.connect(self._select_row)
            row.double_clicked.connect(self._double_click_row)
            self._results_layout.addWidget(row)
            self._rows.append(row)

        self._results_layout.addStretch()

    def _select_row(self, idx):
        # Deselect previous
        if self._selected_idx is not None and self._selected_idx < len(self._rows):
            self._rows[self._selected_idx].set_selected(False)

        self._selected_idx = idx
        self._rows[idx].set_selected(True)

        page_idx = self._state["current_page"]
        self._selected_artist = self._state["pages"][page_idx][idx]
        self._add_btn.setEnabled(True)

    def _double_click_row(self, idx):
        self._select_row(idx)
        self._on_add()

    def _on_add(self):
        if self._selected_artist:
            self.accept()

    def get_selected(self):
        return self._selected_artist

    def _go_prev(self):
        state = self._state
        if state["current_page"] > 0:
            state["current_page"] -= 1
            self._build_page_rows()
            self._update_nav()

    def _go_next(self):
        state = self._state
        next_page = state["current_page"] + 1

        if next_page < len(state["pages"]):
            state["current_page"] = next_page
            self._build_page_rows()
            self._update_nav()
            return

        # Fetch from API
        self._next_btn.setText("Loading\u2026")
        self._next_btn.setEnabled(False)
        self.repaint()

        offset = sum(len(p) for p in state["pages"])
        try:
            new_results = self._search_fn(self._query, offset=offset)
        except TypeError:
            state["has_more"] = False
            self._update_nav()
            return

        if not new_results:
            state["has_more"] = False
            self._update_nav()
            return

        new_thumbs = self._fetch_thumbnails(new_results)
        state["pages"].append(new_results)
        state["page_thumbs"].append(new_thumbs)
        state["has_more"] = len(new_results) >= self._PAGE_SIZE
        state["current_page"] = next_page

        self._build_page_rows()
        self._update_nav()

    def _update_nav(self):
        state = self._state
        page = state["current_page"]
        show_nav = state["has_more"] or len(state["pages"]) > 1
        self._nav_widget.setVisible(show_nav)

        self._prev_btn.setEnabled(page > 0)
        can_next = state["has_more"] or page < len(state["pages"]) - 1
        self._next_btn.setText("Next \u2192")
        self._next_btn.setEnabled(can_next)
        self._page_label.setText(f"Page {page + 1}")


# -----------------------------------------------------------------
# Artist list widget
# -----------------------------------------------------------------

class ArtistListWidget(QWidget):
    """
    Full artist management widget: scrollable card list + search bar.
    """
    _refresh_needed = Signal()

    def __init__(self, parent=None, search_fn=None):
        super().__init__(parent)
        self._artists = []
        self._details = {}
        self._thumbs = {}
        self._search_fn = search_fn
        self._cards = []
        self._details_loaded = False

        self._refresh_needed.connect(self._rebuild_cards)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Scrollable card area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()

        self._scroll.setWidget(self._list_widget)
        layout.addWidget(self._scroll, 1)

        # Search bar
        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 5, 0, 0)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search for an artist\u2026")
        self._search_input.returnPressed.connect(self._on_search)
        search_layout.addWidget(self._search_input, 1)

        self._search_btn = QPushButton("Search && Add")
        self._search_btn.clicked.connect(self._on_search)
        search_layout.addWidget(self._search_btn)

        layout.addLayout(search_layout)

    # --- Data API ---

    def get(self):
        result = []
        for a in self._artists:
            entry = {"id": a["id"], "name": a["name"]}
            detail = self._details.get(a["id"])
            if detail:
                entry["image_url"] = detail.get("image_url", "")
                entry["followers"] = detail.get("followers", 0)
                entry["genres"] = detail.get("genres", [])
            result.append(entry)
        return result

    def set(self, artists):
        self._artists = []
        for a in (artists or []):
            self._artists.append({"id": a["id"], "name": a["name"]})
            if a.get("image_url") or a.get("followers") or a.get("genres"):
                self._details[a["id"]] = a
        self._sort_artists()
        self._details_loaded = False
        self._rebuild_cards()

    def _sort_artists(self):
        self._artists.sort(key=lambda a: (a.get("name") or a.get("id", "")).lower())

    # --- Card management ---

    def _rebuild_cards(self):
        # Clear layout
        while self._list_layout.count() > 0:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._cards = []

        if not self._artists:
            empty = QLabel("  No artists added")
            empty.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; padding: 10px;")
            self._list_layout.addWidget(empty)
            self._list_layout.addStretch()
            return

        for i, artist in enumerate(self._artists):
            if i > 0:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background-color: {theme.BORDER_PRIMARY};")
                self._list_layout.addWidget(sep)

            info = _format_result_info(self._details.get(artist["id"], {}))
            pixmap = self._thumbs.get(artist["id"])
            card = ArtistCard(i, artist.get("name", "Unknown"), info, pixmap)
            card.remove_clicked.connect(self._remove_artist)
            self._list_layout.addWidget(card)
            self._cards.append(card)

        self._list_layout.addStretch()

        if not self._details_loaded:
            threading.Thread(target=self._load_details_async, daemon=True).start()

    def _load_details_async(self):
        missing_ids = [a["id"] for a in self._artists if a["id"] not in self._details]
        if missing_ids:
            try:
                from spotify_auto_skipper.spotify_api import get_artist_details
                details = get_artist_details(missing_ids)
                for d in details:
                    self._details[d["id"]] = d
            except Exception:
                pass

        needs_refresh = False
        for a in self._artists:
            if a["id"] not in self._thumbs:
                detail = self._details.get(a["id"])
                url = detail.get("image_url", "") if detail else ""
                if url:
                    thumb = download_thumbnail(url)
                    if thumb:
                        self._thumbs[a["id"]] = thumb
                        needs_refresh = True

        self._details_loaded = True

        if needs_refresh:
            try:
                self._refresh_needed.emit()
            except Exception:
                pass

    def _remove_artist(self, index):
        if 0 <= index < len(self._artists):
            self._artists.pop(index)
            self._rebuild_cards()

    def _add_artist(self, artist):
        if not any(a["id"] == artist["id"] for a in self._artists):
            self._artists.append({"id": artist["id"], "name": artist["name"]})
            self._details[artist["id"]] = artist
            url = artist.get("image_url", "")
            if url and artist["id"] not in self._thumbs:
                thumb = download_thumbnail(url)
                if thumb:
                    self._thumbs[artist["id"]] = thumb
            self._sort_artists()
            self._rebuild_cards()

    def _on_search(self):
        query = self._search_input.text().strip()
        if not query or not self._search_fn:
            return

        dialog = SearchArtistDialog(self.window(), self._search_fn, query)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            artist = dialog.get_selected()
            if artist:
                self._add_artist(artist)
        self._search_input.clear()


# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------

def _format_followers(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _format_result_info(artist):
    parts = []
    followers = artist.get("followers", 0)
    if followers:
        parts.append(f"{_format_followers(followers)} followers")
    genres = artist.get("genres", [])
    if genres:
        parts.append(", ".join(g.title() for g in genres[:3]))
    return " \u00b7 ".join(parts)
