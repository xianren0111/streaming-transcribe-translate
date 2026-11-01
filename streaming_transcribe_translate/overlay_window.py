"""Floating desktop subtitle window for the browser app (Tkinter, main thread).

Matches the reference desktop overlay: borderless, always on top, palette
background at the configured opacity with opaque text, draggable anywhere,
resizable from the corner grip, position/size remembered, and a toolbar that
appears on hover (text size, background, live drafts, original, timing,
pause, lock, close). Locking makes the window click-through
(``WS_EX_LAYERED | WS_EX_TRANSPARENT``); hovering the locked window shows an
unlock button for a few seconds, and the browser page has an unlock button too.

Other threads talk to Tk only through :class:`OverlayManager`'s command queue,
which the Tk loop polls with ``after()``.
"""

from __future__ import annotations

import json
import logging
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from typing import Any, Callable, Optional

from .paths import ROOT
from .subtitle_settings import PALETTES
from .ui_localization import Translator

log = logging.getLogger(__name__)

STATE_FILE = ROOT / "overlay_window.json"
FONT = "Microsoft YaHei UI"
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_LAYERED = 0x80000
TOOLBAR_HIDE_AFTER = 1.5
UNLOCK_VISIBLE_FOR = 3.0
TOOLBAR_BG = "#1d1d22"
TOOLBAR_FG = "#f2f2f5"
TOOLBAR_ACTIVE = "#3a3a44"


# ---------------------------------------------------------------- helpers

def set_click_through(window: tk.Misc, enabled: bool) -> bool:
    """Toggle mouse click-through on a top-level window (Windows only)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        window.update_idletasks()
        hwnd = int(window.wm_frame(), 16)
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        return True
    except (AttributeError, OSError, ValueError, tk.TclError) as error:
        log.warning("Could not change click-through: %s", type(error).__name__)
        return False


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def is_light(color: str) -> bool:
    r, g, b = _rgb(color)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.5


def key_color(background: str) -> str:
    """A colour one step away from the background, used as the transparent key.

    Anti-aliased text edges blend towards this colour, so keeping it next to the
    real background avoids visible fringes.
    """
    r, g, b = _rgb(background)
    r = r + 1 if r < 255 else r - 1
    return f"#{r:02x}{g:02x}{b:02x}"


def draft_color(background: str) -> str:
    return "#77757f" if is_light(background) else "#9a9aa2"


def palette(settings: dict[str, Any]) -> tuple[str, str]:
    colors = PALETTES.get(settings.get("palette", ""), PALETTES["黑白"])
    return colors[0], colors[1]


def overlay_lines(state: dict[str, Any], tr: Callable[[str], str] = lambda text: text) -> list[tuple[str, str]]:
    """Return ``(text, tag)`` rows for the window; drafts get the ``draft`` tags."""
    settings = state.get("subtitle_settings") or {}
    running = bool(state.get("running"))
    paused = bool(state.get("paused"))
    captions = list(state.get("captions") or [])
    if settings.get("display_mode") == "说完再出":
        captions = [caption for caption in captions if caption.get("is_final", True)]
    language_count = max(1, len(settings.get("reading_languages") or []))
    captions = captions[-max(1, int(settings.get("retained_sentences", 50) or 1)) * language_count:]
    lines: list[tuple[str, str]] = []
    if running and paused:
        lines.append(("⏸ " + tr("已暂停"), "status"))
    show_original = bool(settings.get("show_original", True))
    for caption in captions:
        final = caption.get("is_final", True) is not False
        original = str(caption.get("original") or "")
        translated = str(caption.get("translated") or "")
        if translated and language_count > 1 and caption.get("target_language"):
            translated = "[" + caption["target_language"] + "] " + translated
        if show_original and original:
            lines.append((original, "original" if final else "original_draft"))
        if not final:
            text = translated or ("" if show_original else original)
            if text:
                lines.append(("… " + text, "draft"))
            continue
        if translated:
            lines.append((translated, "final"))
        timing = caption.get("timing")
        if settings.get("show_stats") and isinstance(timing, dict):
            lines.append((
                "ASR " + str(timing.get("asr_ms", 0)) + tr(" ms · 翻译 ") + str(timing.get("mt_ms", 0)) + " ms",
                "stats",
            ))
    if not captions and not (running and paused):
        lines.append((tr("正在听…") if running else tr("字幕会显示在这里。"), "status"))
    return lines


def load_position(path: Path) -> Optional[tuple[int, int]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data["x"]), int(data["y"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_position(path: Path, x: int, y: int) -> None:
    try:
        path.write_text(json.dumps({"x": int(x), "y": int(y)}), encoding="utf-8")
    except OSError as error:
        log.warning("Could not save subtitle window position: %s", type(error).__name__)


# ---------------------------------------------------------------- window

class SubtitleOverlay:
    """The floating window itself. Every method runs on the Tk thread."""

    def __init__(
        self,
        root: tk.Misc,
        controller: Any,
        tr: Callable[[str], str],
        on_change: Callable[[], None],
        on_close: Callable[[], None],
        state_file: Path = STATE_FILE,
    ) -> None:
        self.root = root
        self.controller = controller
        self.tr = tr
        self.on_change = on_change
        self.on_close = on_close
        self.state_file = state_file
        self.locked = False
        self.state: dict[str, Any] = {}
        self._size = (0, 0)
        self._x = self._y = 0
        self._drag: Optional[tuple[int, int, int, int]] = None
        self._resize: Optional[tuple[int, int, int, int]] = None
        self._resize_job: Optional[str] = None
        self._last_inside = 0.0
        self._unlock_until = 0.0
        self._hover_job: Optional[str] = None
        self._closed = False
        self.transparent_text = True

        self.card = tk.Toplevel(root)
        self.front = tk.Toplevel(root)
        for window in (self.card, self.front):
            window.withdraw()
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            window.title("Subtitles")
        self.text = tk.Text(
            self.front, bd=0, highlightthickness=0, wrap="word", padx=16, pady=10,
            cursor="fleur", takefocus=0, relief="flat", exportselection=False,
        )
        self.text.pack(fill="both", expand=True)
        self.grip = tk.Label(self.front, text="⤡", cursor="size_nw_se", font=(FONT, 16, "bold"), bd=0)
        self.grip.place(relx=1.0, rely=1.0, anchor="se", width=32, height=32)

        for widget in (self.card, self.front, self.text):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag_to)
            widget.bind("<ButtonRelease-1>", self._end_drag)
            widget.bind("<Double-Button-1>", lambda event: "break")
        self.grip.bind("<ButtonPress-1>", self._start_resize)
        self.grip.bind("<B1-Motion>", self._resize_to)
        self.grip.bind("<ButtonRelease-1>", self._end_resize)

        self.toolbar = tk.Toplevel(root)
        self.toolbar.withdraw()
        self.toolbar.overrideredirect(True)
        self.toolbar.attributes("-topmost", True)
        self.toolbar.configure(bg=TOOLBAR_BG)
        self.buttons: dict[str, tk.Button] = {}
        self._build_toolbar()

        self.unlock_window = tk.Toplevel(root)
        self.unlock_window.withdraw()
        self.unlock_window.overrideredirect(True)
        self.unlock_window.attributes("-topmost", True)
        self.unlock_button = tk.Button(
            self.unlock_window, text=self.tr("解锁"), command=self.unlock,
            bg="#3b6cf6", fg="#ffffff", activebackground="#2f57c8", activeforeground="#ffffff",
            relief="flat", bd=0, padx=12, pady=4, font=(FONT, 10, "bold"), cursor="hand2",
        )
        self.unlock_button.pack()

    # -------------------------------------------------------------- toolbar

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self.toolbar, bg=TOOLBAR_BG, padx=6, pady=4)
        bar.pack()

        def label(text: str) -> None:
            tk.Label(bar, text=self.tr(text), bg=TOOLBAR_BG, fg="#a8a8b3", font=(FONT, 9)).pack(side="left", padx=(6, 2))

        def button(name: str, text: str, command: Callable[[], None]) -> None:
            widget = tk.Button(
                bar, text=text, command=command, bg=TOOLBAR_BG, fg=TOOLBAR_FG,
                activebackground=TOOLBAR_ACTIVE, activeforeground=TOOLBAR_FG,
                relief="flat", bd=0, padx=7, pady=2, font=(FONT, 9), cursor="hand2",
            )
            widget.pack(side="left", padx=1)
            self.buttons[name] = widget

        label("字号")
        button("font_down", "A−", lambda: self._step("font_size", -2))
        button("font_up", "A+", lambda: self._step("font_size", 2))
        label("背景")
        button("opacity_down", "−", lambda: self._step("opacity", -0.15))
        button("opacity_up", "+", lambda: self._step("opacity", 0.15))
        button("palette", "", self._cycle_palette)
        button("mode", "", self._toggle_mode)
        button("original", "", lambda: self._toggle("show_original"))
        button("stats", "", lambda: self._toggle("show_stats"))
        button("pause", "", self._toggle_pause)
        button("lock", self.tr("锁定"), self.lock)
        button("close", "✕", self.close)

    def _settings(self) -> dict[str, Any]:
        return dict(self.state.get("subtitle_settings") or {})

    def _save(self, values: dict[str, Any]) -> None:
        try:
            self.controller.save_subtitle_settings(values)
        except Exception as error:  # UserError or validation problems: keep the window usable.
            log.warning("Subtitle window setting not saved: %s", type(error).__name__)
            from tkinter import messagebox
            messagebox.showerror(
                self.tr("无法保存字幕设置"), self.tr(str(error)), parent=self.toolbar,
            )
            return
        self.apply_state(self.controller.snapshot())

    def _cycle_palette(self) -> None:
        names = list(PALETTES)
        current = self._settings().get("palette", "黑白")
        self._save({"palette": names[(names.index(current) + 1) % len(names)]})

    def _step(self, name: str, delta: float) -> None:
        settings = self._settings()
        if name == "font_size":
            value: Any = max(10, min(40, int(settings.get("font_size", 15)) + int(delta)))
        else:
            value = round(max(0.1, min(1.0, float(settings.get("opacity", 0.48)) + delta)), 2)
        self._save({name: value})

    def _toggle(self, name: str) -> None:
        self._save({name: not bool(self._settings().get(name))})

    def _toggle_mode(self) -> None:
        mode = self._settings().get("display_mode")
        self._save({"display_mode": "说完再出" if mode == "边听边出" else "边听边出"})

    def _toggle_pause(self) -> None:
        try:
            self.controller.toggle_pause()
        except Exception as error:
            log.info("Pause not available: %s", type(error).__name__)

    def _refresh_toolbar(self) -> None:
        settings = self._settings()
        self.buttons["palette"].configure(text=self.tr("配色") + ": " + self.tr(settings.get("palette", "黑白")))
        check = lambda on: "✓ " if on else ""  # noqa: E731
        self.buttons["mode"].configure(text=self.tr(settings.get("display_mode") or "边听边出"))
        self.buttons["original"].configure(text=check(settings.get("show_original")) + self.tr("原文"))
        self.buttons["stats"].configure(text=check(settings.get("show_stats")) + self.tr("用时"))
        running = bool(self.state.get("running"))
        self.buttons["pause"].configure(
            text=self.tr("继续" if self.state.get("paused") else "暂停"),
            state="normal" if running else "disabled",
        )

    # ------------------------------------------------------------ geometry

    def _target_size(self) -> tuple[int, int]:
        settings = self._settings()
        width = round(self.root.winfo_screenwidth() * float(settings.get("width_percent", 28)) / 100)
        height = round(self.root.winfo_screenheight() * float(settings.get("height_percent", 10)) / 100)
        return max(200, width), max(60, height)

    def _position(self) -> tuple[int, int]:
        return self.card.winfo_x(), self.card.winfo_y()

    def _place(self, x: int, y: int, width: int, height: int) -> None:
        geometry = f"{width}x{height}+{x}+{y}"
        self.card.geometry(geometry)
        self.front.geometry(geometry)
        self._size = (width, height)
        self._x, self._y = x, y
        if self.toolbar.winfo_viewable():
            self._place_toolbar()

    def _initial_position(self, width: int, height: int) -> tuple[int, int]:
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        saved = load_position(self.state_file)
        if saved is None:
            saved = getattr(self.controller, "overlay_position", None)
        if saved:
            x, y = saved
        else:
            x, y = (screen_w - width) // 2, screen_h - height - 120
        x = max(0, min(x, screen_w - min(width, screen_w)))
        y = max(0, min(y, screen_h - min(height, screen_h)))
        return x, y

    def _place_toolbar(self) -> None:
        self.toolbar.update_idletasks()
        height = self.toolbar.winfo_reqheight()
        y = self._y - height - 4
        if y < 0:
            y = self._y + self._size[1] + 4
        self.toolbar.geometry(f"+{self._x}+{y}")

    # ---------------------------------------------------------- interaction

    def _start_drag(self, event: tk.Event) -> str:
        if self.locked:
            return "break"
        # Windows activates the background through transparent foreground pixels.
        self.front.lift()
        self._drag = (event.x_root, event.y_root, self._x, self._y)
        return "break"

    def _drag_to(self, event: tk.Event) -> str:
        if self._drag is not None:
            start_x, start_y, x, y = self._drag
            self._place(x + event.x_root - start_x, y + event.y_root - start_y, *self._size)
        return "break"

    def _end_drag(self, event: tk.Event) -> str:
        if self._drag is not None:
            self._drag = None
            self.front.lift()
            save_position(self.state_file, self._x, self._y)
        return "break"

    def _start_resize(self, event: tk.Event) -> str:
        if not self.locked:
            self._resize = (event.x_root, event.y_root, *self._size)
            self.grip.grab_set()
            self._resize_job = self.root.after(16, self._track_resize)
        return "break"

    def _track_resize(self) -> None:
        self._resize_job = None
        if self._resize is None or self._closed:
            return
        event = tk.Event()
        event.x_root, event.y_root = self.root.winfo_pointerxy()
        self._resize_to(event)
        self._resize_job = self.root.after(16, self._track_resize)

    def _resize_to(self, event: tk.Event) -> str:
        if self._resize is not None:
            start_x, start_y, width, height = self._resize
            self._place(
                self._x, self._y,
                max(200, min(self.root.winfo_screenwidth(), width + event.x_root - start_x)),
                max(60, min(round(self.root.winfo_screenheight() * 0.8), height + event.y_root - start_y)),
            )
        return "break"

    def _end_resize(self, event: tk.Event) -> str:
        if self._resize is None:
            return "break"
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
            self._resize_job = None
        self._resize = None
        self.grip.grab_release()
        width, height = self._size
        self._save({
            "width_percent": width * 100 / self.root.winfo_screenwidth(),
            "height_percent": height * 100 / self.root.winfo_screenheight(),
        })
        save_position(self.state_file, self._x, self._y)
        return "break"

    def _inside(self, window: tk.Misc, x: int, y: int) -> bool:
        try:
            if not window.winfo_viewable():
                return False
            left, top = window.winfo_rootx(), window.winfo_rooty()
            return left <= x < left + window.winfo_width() and top <= y < top + window.winfo_height()
        except tk.TclError:
            return False

    def _watch_pointer(self) -> None:
        self._hover_job = None
        if self._closed:
            return
        try:
            x, y = self.root.winfo_pointerxy()
            now = time.monotonic()
            over_card = self._inside(self.card, x, y)
            if self.locked:
                if over_card or self._inside(self.unlock_window, x, y):
                    self._show_unlock()
                    self._unlock_until = now + UNLOCK_VISIBLE_FOR
                elif now > self._unlock_until:
                    self.unlock_window.withdraw()
            elif (
                over_card or self._inside(self.toolbar, x, y)
                or self._drag or self._resize
            ):
                self._last_inside = now
                if not self.toolbar.winfo_viewable():
                    self.toolbar.deiconify()
                    self._place_toolbar()
                    self.toolbar.lift()
            elif self.toolbar.winfo_viewable() and now - self._last_inside > TOOLBAR_HIDE_AFTER:
                self.toolbar.withdraw()
        except tk.TclError:
            return
        self._hover_job = self.root.after(150, self._watch_pointer)

    def _show_unlock(self) -> None:
        if not self.unlock_window.winfo_viewable():
            self.unlock_window.deiconify()
        self.unlock_window.update_idletasks()
        width = self.unlock_window.winfo_reqwidth()
        self.unlock_window.geometry(f"+{self._x + self._size[0] - width - 8}+{self._y + 8}")
        self.unlock_window.lift()

    # ----------------------------------------------------------- lock/state

    def lock(self) -> None:
        if self._resize is not None:
            self._end_resize(tk.Event())
        self.locked = True
        self.toolbar.withdraw()
        for window in (self.card, self.front):
            set_click_through(window, True)
        self.on_change()

    def unlock(self) -> None:
        self.locked = False
        self.unlock_window.withdraw()
        for window in (self.card, self.front):
            set_click_through(window, False)
        self.on_change()

    def show(self, state: dict[str, Any]) -> None:
        self.apply_state(state)
        width, height = self._target_size()
        x, y = self._initial_position(width, height)
        self._place(x, y, width, height)
        self.card.deiconify()
        self.front.deiconify()
        self.front.update_idletasks()
        self.front.lift()
        self._hover_job = self.root.after(150, self._watch_pointer)

    def apply_state(self, state: dict[str, Any]) -> None:
        self.state = state
        settings = self._settings()
        foreground, background = palette(settings)
        opacity = float(settings.get("opacity", 0.48))
        font_size = int(settings.get("font_size", 15))
        self.card.configure(bg=background)
        self.card.attributes("-alpha", max(0.1, min(1.0, opacity)))
        key = key_color(background)
        try:
            self.front.attributes("-transparentcolor", key)
            surface = key
        except tk.TclError:
            # No colour keying on this platform: one semi-transparent window instead.
            self.transparent_text = False
            surface = background
            self.front.attributes("-alpha", max(0.1, min(1.0, opacity)))
        self.front.configure(bg=surface)
        self.text.configure(bg=surface, fg=foreground, font=(FONT, font_size))
        self.grip.configure(bg=TOOLBAR_BG, fg=TOOLBAR_FG)
        dim = draft_color(background)
        small = max(9, round(font_size * 0.72))
        self.text.tag_configure("final", foreground=foreground, font=(FONT, font_size, "bold"))
        self.text.tag_configure("original", foreground=foreground, font=(FONT, small))
        self.text.tag_configure("original_draft", foreground=foreground, font=(FONT, small))
        self.text.tag_configure("draft", foreground=dim, font=(FONT, max(10, font_size - 2)))
        self.text.tag_configure("stats", foreground=dim, font=(FONT, max(8, round(font_size * 0.6))))
        self.text.tag_configure("status", foreground=dim, font=(FONT, max(10, font_size - 2)))
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for text, tag in overlay_lines(state, self.tr):
            self.text.insert("end", text + "\n", tag)
        self.text.configure(state="disabled")
        self.text.see("end")
        self._refresh_toolbar()
        if self._size != (0, 0) and self._resize is None and self._drag is None:
            target = self._target_size()
            if target != self._size:
                self._place(self._x, self._y, *target)

    def close(self) -> None:
        if self._closed:
            return
        self.destroy()
        self.on_close()

    def destroy(self) -> None:
        self._closed = True
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
            self._resize_job = None
        if self.grip.grab_current() is self.grip:
            self.grip.grab_release()
        if self._hover_job is not None:
            try:
                self.root.after_cancel(self._hover_job)
            except tk.TclError:
                pass
        for window in (self.unlock_window, self.toolbar, self.front, self.card):
            try:
                window.destroy()
            except tk.TclError:
                pass


# ---------------------------------------------------------------- manager

class OverlayManager:
    """Owns the hidden Tk root on the main thread and the floating window.

    ``open``/``close``/``unlock``/``toggle`` are safe to call from any thread.
    """

    def __init__(
        self,
        controller: Any,
        quit_event: threading.Event,
        root: Optional[tk.Tk] = None,
        poll_ms: int = 50,
        state_file: Path = STATE_FILE,
    ) -> None:
        self.controller = controller
        self.quit_event = quit_event
        self.root = root if root is not None else tk.Tk()
        self.root.withdraw()
        self.poll_ms = poll_ms
        self.state_file = state_file
        self.commands: queue.Queue = queue.Queue()
        self.window: Optional[SubtitleOverlay] = None
        self._latest_state: Optional[dict[str, Any]] = None
        self._state_lock = threading.Lock()
        self._stopped = False
        self._translators: dict[str, Translator] = {}
        self._unsubscribe = controller.subscribe(self._on_event)
        self._report()
        self._poll_job: Optional[str] = self.root.after(self.poll_ms, self._poll)

    # thread-safe API -----------------------------------------------------

    def open(self) -> None:
        self.commands.put("open")

    def close(self) -> None:
        self.commands.put("close")

    def unlock(self) -> None:
        self.commands.put("unlock")

    def choose_records_folder(self) -> None:
        self.commands.put("records_folder")

    def toggle(self) -> None:
        self.commands.put("toggle")

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self.shutdown()

    # Tk thread -------------------------------------------------------------

    def _on_event(self, event: dict[str, Any]) -> None:
        if event.get("type") == "state" and isinstance(event.get("state"), dict):
            with self._state_lock:
                self._latest_state = event["state"]

    def _tr(self) -> Callable[[str], str]:
        try:
            language = self.controller.interface_preferences.resolved_language
        except AttributeError:
            language = "zh"
        if language not in self._translators:
            self._translators[language] = Translator(language)
        return self._translators[language]

    def _report(self) -> None:
        window = self.window
        try:
            self.controller.set_overlay_state(
                True, window is not None, bool(window and window.locked),
            )
        except Exception:
            log.exception("Could not report subtitle window state")

    def _window_closed(self) -> None:
        self.window = None
        self._report()

    def handle(self, command: str) -> None:
        if command == "records_folder":
            folder = filedialog.askdirectory(
                parent=self.root, title=self._tr()("选择记录保存文件夹"),
                initialdir=str(self.controller.records_root), mustexist=True,
            )
            if folder:
                from .app_controller import UserError

                try:
                    self.controller.save_subtitle_settings({"records_folder": folder})
                except UserError as error:
                    self.controller._emit_error(error.title, error.message)
            return
        if command == "toggle":
            command = "close" if self.window is not None else "open"
        if command == "open":
            if self.window is None:
                self.window = SubtitleOverlay(
                    self.root, self.controller, self._tr(), self._report, self._window_closed,
                    state_file=self.state_file,
                )
                self.window.show(self.controller.snapshot())
                self._report()
            else:
                self.window.card.lift()
                self.window.front.lift()
        elif command == "close" and self.window is not None:
            self.window.close()
        elif command == "unlock" and self.window is not None:
            self.window.unlock()

    def pump(self) -> None:
        """Process queued commands and the newest controller state."""
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            try:
                self.handle(command)
            except tk.TclError:
                log.exception("Subtitle window command failed")
        with self._state_lock:
            state, self._latest_state = self._latest_state, None
        if state is not None and self.window is not None:
            try:
                self.window.tr = self._tr()
                self.window.apply_state(state)
            except tk.TclError:
                log.exception("Subtitle window update failed")

    def _poll(self) -> None:
        self._poll_job = None
        if self.quit_event.is_set():
            self.shutdown()
            return
        self.pump()
        if not self._stopped:
            self._poll_job = self.root.after(self.poll_ms, self._poll)

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._unsubscribe()
        if self.window is not None:
            self.window.destroy()
            self.window = None
        try:
            self.controller.set_overlay_state(False, False, False)
        except Exception:
            pass
        try:
            if self._poll_job is not None:
                self.root.after_cancel(self._poll_job)
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass
