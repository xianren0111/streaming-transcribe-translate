"""Small visual primitives for the Tkinter desktop UI."""

import tkinter as tk


class RoundedCard(tk.Frame):
    def __init__(self, parent, *, fill: str, edge: str, page: str, **kwargs):
        super().__init__(parent, bg=fill, bd=0, **kwargs)
        self._fill, self._edge = fill, edge
        self._surface = tk.Canvas(self, bg=page, highlightthickness=0, bd=0)
        self._surface.place(x=0, y=0, relwidth=1, relheight=1)
        self.tk.call("lower", self._surface._w)
        self.bind("<Configure>", self._draw)

    def _draw(self, event):
        width, height = event.width - 1, event.height - 1
        radius = min(14, width / 2, height / 2)
        points = [
            radius, 1, width - radius, 1, width, 1, width, radius,
            width, height - radius, width, height, width - radius, height,
            radius, height, 1, height, 1, height - radius, 1, radius, 1, 1,
        ]
        self._surface.delete("surface")
        self._surface.create_polygon(
            points, smooth=True, splinesteps=24,
            fill=self._fill, outline=self._edge, tags="surface",
        )
