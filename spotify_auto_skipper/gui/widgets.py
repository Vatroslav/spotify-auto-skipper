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
