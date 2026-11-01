import tempfile
import sys
import threading
import tkinter as tk
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest import mock

from streaming_transcribe_translate import overlay_window
from streaming_transcribe_translate.overlay_window import (
    OverlayManager, draft_color, key_color, overlay_lines,
)
from streaming_transcribe_translate.subtitle_settings import SubtitleSettings
from tests.test_web_ui import WebTestCase


def settings(**values):
    return {**asdict(SubtitleSettings()), **values}


def caption(original, translated, final=True, timing=None):
    item = {"original": original, "translated": translated, "is_final": final}
    if timing:
        item["timing"] = timing
    return item


class OverlayLinesTests(unittest.TestCase):
    def test_drafts_are_marked_and_final_text_is_final(self):
        state = {
            "running": True,
            "subtitle_settings": settings(display_mode="边听边出", show_original=True),
            "captions": [caption("hello", "你好"), caption("wor", "世", final=False)],
        }
        self.assertEqual(overlay_lines(state), [
            ("hello", "original"), ("你好", "final"),
            ("wor", "original_draft"), ("… 世", "draft"),
        ])

    def test_finished_only_mode_hides_drafts_and_original(self):
        state = {
            "running": True,
            "subtitle_settings": settings(display_mode="说完再出", show_original=False),
            "captions": [caption("hello", "你好"), caption("wor", "世", final=False)],
        }
        self.assertEqual(overlay_lines(state), [("你好", "final")])

    def test_timing_paused_and_empty_states(self):
        state = {
            "running": True, "paused": True,
            "subtitle_settings": settings(show_original=False, show_stats=True),
            "captions": [caption("a", "b", timing={"asr_ms": 120, "mt_ms": 340})],
        }
        lines = overlay_lines(state)
        self.assertEqual(lines[0], ("⏸ 已暂停", "status"))
        self.assertEqual(lines[-1], ("ASR 120 ms · 翻译 340 ms", "stats"))
        self.assertEqual(overlay_lines({"running": True}), [("正在听…", "status")])
        self.assertEqual(overlay_lines({}), [("字幕会显示在这里。", "status")])

    def test_retained_sentences_limit(self):
        state = {
            "subtitle_settings": settings(show_original=False, retained_sentences=2),
            "captions": [caption(str(n), f"t{n}") for n in range(5)],
        }
        self.assertEqual([text for text, _ in overlay_lines(state)], ["t3", "t4"])

    def test_colours(self):
        self.assertNotEqual(key_color("#000000"), "#000000")
        self.assertNotEqual(key_color("#ffffff"), "#ffffff")
        self.assertNotEqual(draft_color("#000000"), draft_color("#ffffff"))


class FakeController:
    def __init__(self):
        self.listeners = []
        self.saved = []
        self.overlay_states = []
        self.paused = 0
        self.settings = settings()
        self.interface_preferences = type("Prefs", (), {"resolved_language": "zh"})()

    def subscribe(self, listener):
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def snapshot(self):
        return {"running": True, "paused": False, "subtitle_settings": dict(self.settings),
                "captions": [caption("hi", "你好"), caption("th", "这", final=False)]}

    def emit(self, state):
        for listener in list(self.listeners):
            listener({"type": "state", "state": state})

    def save_subtitle_settings(self, values):
        self.saved.append(values)
        self.settings.update(values)

    def toggle_pause(self):
        self.paused += 1

    def set_overlay_state(self, available, open, locked):
        self.overlay_states.append((available, open, locked))


class OverlayManagerTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk unavailable: {error}")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.controller = FakeController()
        self.quit = threading.Event()
        self.manager = OverlayManager(
            self.controller, self.quit, root=self.root, poll_ms=10_000,
            state_file=Path(self.tmp.name) / "overlay_window.json",
        )
        self.addCleanup(self.manager.shutdown)
        patcher = mock.patch.object(overlay_window, "set_click_through", return_value=True)
        self.click_through = patcher.start()
        self.addCleanup(patcher.stop)

    def open(self):
        self.manager.open()
        self.manager.pump()
        self.root.update_idletasks()
        return self.manager.window

    def test_open_shows_borderless_topmost_window_with_draft_style(self):
        self.assertEqual(self.controller.overlay_states[-1], (True, False, False))
        window = self.open()
        self.assertIsNotNone(window)
        self.assertEqual(self.controller.overlay_states[-1], (True, True, False))
        for toplevel in (window.card, window.front):
            self.assertTrue(toplevel.overrideredirect())
            self.assertTrue(toplevel.attributes("-topmost"))
        self.assertAlmostEqual(float(window.card.attributes("-alpha")), SubtitleSettings().opacity, places=2)
        text = window.text.get("1.0", "end")
        self.assertIn("你好", text)
        self.assertIn("… 这", text)
        self.assertTrue(window.text.tag_ranges("draft"))
        self.assertNotEqual(
            window.text.tag_cget("draft", "foreground"), window.text.tag_cget("final", "foreground"),
        )

    def test_controller_events_update_text(self):
        window = self.open()
        state = self.controller.snapshot()
        state["captions"] = [caption("new", "新的字幕")]
        self.controller.emit(state)
        self.manager.pump()
        self.assertIn("新的字幕", window.text.get("1.0", "end"))

    @unittest.skipUnless(overlay_window.sys.platform == "win32", "Windows window stacking")
    def test_text_layer_stays_above_background_when_opened_and_raised(self):
        import ctypes

        user32 = ctypes.windll.user32
        get_window = user32.GetWindow
        get_window.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        get_window.restype = ctypes.c_void_p
        window = self.open()
        for reopen in (False, True):
            if reopen:
                self.manager.handle("open")
            self.root.update()
            front = int(window.front.wm_frame(), 16)
            card = int(window.card.wm_frame(), 16)
            current = get_window(front, 2)  # GW_HWNDNEXT: next window below this one.
            below = set()
            while current and current not in below:
                below.add(current)
                current = get_window(current, 2)
            self.assertIn(card, below, "The background must not cover subtitle text")

    def test_toolbar_buttons_save_settings_and_pause(self):
        window = self.open()
        window.buttons["font_up"].invoke()
        window.buttons["opacity_down"].invoke()
        window.buttons["mode"].invoke()
        window.buttons["original"].invoke()
        window.buttons["stats"].invoke()
        window.buttons["pause"].invoke()
        default = SubtitleSettings()
        self.assertEqual(self.controller.saved, [
            {"font_size": default.font_size + 2},
            {"opacity": round(default.opacity - 0.15, 2)},
            {"display_mode": "说完再出" if default.display_mode == "边听边出" else "边听边出"},
            {"show_original": not default.show_original},
            {"show_stats": not default.show_stats},
        ])
        self.assertEqual(self.controller.paused, 1)

    def test_retention_control_is_on_queue_not_floating_toolbar(self):
        window = self.open()
        self.assertNotIn("settings", window.buttons)
        self.assertNotIn("retention_up", window.buttons)
        self.assertNotIn("retention_down", window.buttons)
        from streaming_transcribe_translate.paths import ROOT
        html = (ROOT / "streaming_transcribe_translate" / "web" / "index.html").read_text(encoding="utf-8")
        queue = html.split('id="draft-text"', 1)[1].split('id="queue"', 1)[0]
        self.assertIn('id="queue-retention"', queue)
        self.assertIn('data-opt="retained_sentences" min="1" max="200"', queue)
        self.assertLess(queue.index('id="queue-retention"'), queue.index('id="send-button"'))
        self.assertEqual(html.count('id="queue-retention"'), 1)

    def test_palette_button_cycles_all_themes_and_wraps(self):
        window = self.open()
        names = list(overlay_window.PALETTES)
        for name in names[1:] + names[:1]:
            window.buttons["palette"].invoke()
            self.assertEqual(self.controller.saved[-1], {"palette": name})
            self.assertEqual(window.state["subtitle_settings"]["palette"], name)
            self.assertIn(name, window.buttons["palette"].cget("text"))

    def test_original_and_draft_original_follow_every_palette(self):
        window = self.open()
        for name, (foreground, _) in overlay_window.PALETTES.items():
            self.controller.settings["palette"] = name
            window.apply_state(self.controller.snapshot())
            for tag in ("original", "original_draft", "final"):
                self.assertEqual(window.text.tag_cget(tag, "foreground"), foreground)

    def test_resize_arrow_changes_both_dimensions_and_persists_them(self):
        from types import SimpleNamespace

        window = self.open()
        self.assertGreaterEqual(window.grip.winfo_width(), 32)
        self.assertGreaterEqual(window.grip.winfo_height(), 32)
        self.assertNotEqual(window.grip.cget("bg"), window.front.cget("bg"))
        width, height = window._size
        window._start_resize(SimpleNamespace(x_root=100, y_root=100))
        window._resize_to(SimpleNamespace(x_root=180, y_root=150))
        self.assertEqual(window._size, (width + 80, height + 50))
        window._end_resize(SimpleNamespace())
        saved = self.controller.saved[-1]
        self.assertIn("width_percent", saved)
        self.assertIn("height_percent", saved)
        self.assertEqual(window._size, window._target_size())
        window.lock()
        window._start_resize(SimpleNamespace(x_root=100, y_root=100))
        self.assertIsNone(window._resize)

    def test_resize_tracks_pointer_when_windows_motion_event_is_missing(self):
        from types import SimpleNamespace

        window = self.open()
        window._place(100, 100, 650, 180)
        window._start_resize(SimpleNamespace(x_root=734, y_root=264))
        job = window._resize_job
        self.root.after_cancel(job)
        with mock.patch.object(self.root, "winfo_pointerxy", return_value=(814, 314)):
            window._track_resize()
        self.assertEqual(window._size, (730, 230))
        window.apply_state(self.controller.snapshot())
        self.assertEqual(window._size, (730, 230))
        window._end_resize(SimpleNamespace())
        self.assertIsNone(window._resize_job)
        self.assertEqual(window._size, (730, 230))

    @unittest.skipUnless(sys.platform == "win32", "Windows layer activation regression")
    def test_background_activation_does_not_cover_grip_across_twelve_resizes(self):
        import ctypes
        from types import SimpleNamespace

        window = self.open()
        user32 = ctypes.windll.user32

        class Point(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        user32.WindowFromPoint.argtypes = [Point]
        user32.WindowFromPoint.restype = ctypes.c_void_p
        window._place(100, 100, 650, 180)
        for index in range(12):
            window.card.lift()
            self.root.update()
            window._start_drag(SimpleNamespace(x_root=120, y_root=150))
            window._end_drag(SimpleNamespace())
            self.root.update()
            point = Point(window.grip.winfo_rootx() + 16, window.grip.winfo_rooty() + 16)
            self.assertEqual(user32.WindowFromPoint(point), window.grip.winfo_id())
            delta = 20 if index % 2 == 0 else -20
            width, height = window._size
            window.grip.event_generate("<ButtonPress-1>", x=16, y=16)
            window.grip.event_generate("<B1-Motion>", x=16 + delta, y=16 + delta)
            window.grip.event_generate("<ButtonRelease-1>", x=16, y=16)
            window.apply_state(self.controller.snapshot())
            self.root.update()
            self.assertEqual(window._size, (width + delta, height + delta))
            self.assertIsNone(self.root.grab_current())

    def test_palette_save_failure_is_visible_and_keeps_previous_theme(self):
        window = self.open()
        original = window.state["subtitle_settings"]["palette"]
        with mock.patch.object(self.controller, "save_subtitle_settings", side_effect=OSError("disk full")), \
                mock.patch("tkinter.messagebox.showerror") as showerror:
            window.buttons["palette"].invoke()
        self.assertEqual(window.state["subtitle_settings"]["palette"], original)
        showerror.assert_called_once_with("无法保存字幕设置", "disk full", parent=window.toolbar)

    def test_resize_widget_drag_keeps_exact_size_after_release_and_updates(self):
        window = self.open()
        window._place(100, 100, 400, 180)
        self.root.update()
        grip = window.grip
        grip.event_generate("<ButtonPress-1>", x=16, y=16)
        self.root.update()
        self.assertIs(self.root.grab_current(), grip)
        self.assertIsNone(window._drag)
        grip.event_generate("<B1-Motion>", x=-84, y=-44)
        self.root.update()
        expected = (300, 120)
        self.assertEqual(window._size, expected)
        # Caption updates while dragging must not restore the previous size.
        window.apply_state(self.controller.snapshot())
        self.assertEqual(window._size, expected)
        grip.event_generate("<ButtonRelease-1>", x=16, y=16)
        self.root.update()
        self.assertIsNone(self.root.grab_current())
        self.assertEqual(window._size, expected)
        window.apply_state(self.controller.snapshot())
        self.root.update()
        self.assertEqual(window._size, expected)
        self.assertEqual((window.front.winfo_width(), window.front.winfo_height()), expected)
        self.assertEqual((window.card.winfo_width(), window.card.winfo_height()), expected)

    def test_fractional_resize_persists_and_reopens_at_same_size(self):
        from types import SimpleNamespace
        from streaming_transcribe_translate.subtitle_settings import SubtitleSettings

        window = self.open()
        window._place(100, 100, 403, 183)
        window._start_resize(SimpleNamespace(x_root=100, y_root=100))
        window._end_resize(SimpleNamespace())
        saved = SubtitleSettings(**self.controller.settings)
        path = Path(self.tmp.name) / "settings.json"
        saved.save(path)
        self.controller.settings = asdict(SubtitleSettings.load(path))
        self.manager.handle("close")
        reopened = self.open()
        self.assertEqual(reopened._size, (403, 183))

    def test_browser_subtitle_tab_is_removed_and_other_tabs_remain(self):
        from streaming_transcribe_translate.paths import ROOT

        html = (ROOT / "streaming_transcribe_translate" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('data-tab="字幕"', html)
        self.assertNotIn('data-panel="字幕"', html)
        self.assertNotIn('id="opt-palette"', html)
        self.assertNotIn('id="save-preview"', html)
        for tab in ("翻译", "记录", "关于"):
            self.assertIn(f'data-tab="{tab}"', html)

    def test_lock_makes_click_through_and_unlock_restores(self):
        window = self.open()
        window.buttons["lock"].invoke()
        self.assertTrue(window.locked)
        self.assertEqual(self.controller.overlay_states[-1], (True, True, True))
        self.assertTrue(all(call.args[1] for call in self.click_through.call_args_list))
        self.manager.unlock()
        self.manager.pump()
        self.assertFalse(window.locked)
        self.assertFalse(self.click_through.call_args_list[-1].args[1])
        self.assertEqual(self.controller.overlay_states[-1], (True, True, False))

    def test_close_button_and_toggle(self):
        window = self.open()
        window.buttons["close"].invoke()
        self.assertIsNone(self.manager.window)
        self.assertEqual(self.controller.overlay_states[-1], (True, False, False))
        self.manager.toggle()
        self.manager.pump()
        self.assertIsNotNone(self.manager.window)
        self.manager.toggle()
        self.manager.pump()
        self.assertIsNone(self.manager.window)

    def test_quit_event_shuts_down_tk(self):
        self.open()
        self.quit.set()
        self.manager._poll()
        self.assertEqual(self.controller.overlay_states[-1], (False, False, False))
        self.assertEqual(self.controller.listeners, [])
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists()


class FakeOverlay:
    def __init__(self):
        self.calls = []

    def open(self):
        self.calls.append("open")

    def close(self):
        self.calls.append("close")

    def unlock(self):
        self.calls.append("unlock")


class OverlayRouteTests(WebTestCase):
    def test_routes_without_overlay_report_unavailable(self):
        status, body = self.request("POST", "/api/overlay/open", {})
        self.assertEqual(status, 400)

    def test_routes_drive_overlay(self):
        overlay = FakeOverlay()
        self.web.overlay = overlay
        for name in ("open", "unlock", "close"):
            status, _ = self.request("POST", f"/api/overlay/{name}", {})
            self.assertEqual(status, 200)
        self.assertEqual(overlay.calls, ["open", "unlock", "close"])

    def test_pause_requires_running_session(self):
        status, _ = self.request("POST", "/api/pause", {})
        self.assertEqual(status, 400)
        self.assertNotIn(b"Traceback", str(_).encode())

    def test_snapshot_reports_overlay_and_pause(self):
        self.controller.set_overlay_state(True, True, True)
        status, body = self.request("GET", "/api/snapshot")
        self.assertEqual(status, 200)
        state = body.get("state", body)
        self.assertEqual(state["desktop_overlay"], {"available": True, "open": True, "locked": True})
        self.assertFalse(state["paused"])


if __name__ == "__main__":
    unittest.main()
