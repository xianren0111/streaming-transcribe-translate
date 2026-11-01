"""Interface text translation without translating user content or stored values."""

import logging
import re
import tkinter as tk
from tkinter import ttk

from .ui_translations import TRANSLATIONS


log = logging.getLogger(__name__)


class Translator:
    def __init__(self, language: str):
        self.language = language
        self._missing = set()
        self._pattern = re.compile("|".join(re.escape(source) for source in sorted(TRANSLATIONS, key=len, reverse=True)))

    def __call__(self, text: str) -> str:
        if self.language == "zh" or not text:
            return text
        entry = TRANSLATIONS.get(text)
        if entry:
            return entry[self.language]
        # Dynamic status strings retain names, clocks and other variable data.
        result = self._pattern.sub(lambda match: TRANSLATIONS[match[0]][self.language], text)
        unmatched = self._pattern.sub("", text)
        if any("\u4e00" <= character <= "\u9fff" for character in unmatched):
            if text not in self._missing:
                self._missing.add(text)
                log.warning("Interface text is missing a translation")
        return result


class LocalizedText:
    def __init__(self, parent, *, translator, **kwargs):
        self.translator = translator
        self.source_text = kwargs.get("text", "")
        if "text" in kwargs:
            kwargs["text"] = self._render_text()
        super().__init__(parent, **kwargs)

    def _render_text(self):
        return self.source_text(self.translator) if callable(self.source_text) else self.translator(self.source_text)

    def configure(self, cnf=None, **kwargs):
        if cnf:
            if not isinstance(cnf, dict):
                return super().configure(cnf, **kwargs)
            kwargs = {**cnf, **kwargs}
        if "text" in kwargs:
            self.source_text = kwargs["text"]
            kwargs["text"] = self._render_text()
        return super().configure(**kwargs)

    config = configure

    def refresh_language(self):
        super().configure(text=self._render_text())


class LocalizedLabel(LocalizedText, tk.Label):
    pass


class LocalizedButton(LocalizedText, tk.Button):
    pass


class LocalizedCheckbutton(LocalizedText, tk.Checkbutton):
    pass


class LocalizedCombobox(ttk.Combobox):
    def __init__(self, parent, *, translator, textvariable, values=(), **kwargs):
        self.translator = translator
        self.canonical_variable = textvariable
        self.canonical_values = list(values)
        self.display_variable = tk.StringVar(master=parent)
        super().__init__(parent, textvariable=self.display_variable, **kwargs)
        self._trace = textvariable.trace_add("write", self._sync)
        self.bind("<<ComboboxSelected>>", self._selected)
        self.bind("<Destroy>", self._destroy_trace, add="+")
        self.refresh_language()

    def _destroy_trace(self, event):
        if event.widget is self:
            self.canonical_variable.trace_remove("write", self._trace)

    def _sync(self, *_):
        self.display_variable.set(self.translator(self.canonical_variable.get()))

    def _selected(self, _):
        index = self.current()
        if index >= 0:
            self.canonical_variable.set(self.canonical_values[index])

    def configure(self, cnf=None, **kwargs):
        if cnf:
            if not isinstance(cnf, dict):
                return super().configure(cnf, **kwargs)
            kwargs = {**cnf, **kwargs}
        if "values" in kwargs:
            self.canonical_values = list(kwargs.pop("values"))
            self.refresh_language()
        return super().configure(**kwargs)

    config = configure

    def refresh_language(self):
        super().configure(values=[self.translator(value) for value in self.canonical_values])
        self._sync()
