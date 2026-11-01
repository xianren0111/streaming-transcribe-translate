import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from streaming_transcribe_translate import paths, portable_app


class PortableTests(unittest.TestCase):
    def test_first_run_download_success_opens_real_tk_dialog(self):
        real_tk = portable_app.tk.Tk
        def create_window():
            root = real_tk()
            root.withdraw()
            def click():
                buttons = root.winfo_children()[0].winfo_children()[-1].winfo_children()
                buttons[0].invoke()
            root.after(10, click)
            root.after(3000, root.destroy)
            return root
        with patch("streaming_transcribe_translate.setup_models.reazonspeech_ready", return_value=False), patch(
            "streaming_transcribe_translate.setup_models.whisper_ready", return_value=False,
        ), patch("streaming_transcribe_translate.setup_models.download_reazonspeech") as asr, patch(
            "streaming_transcribe_translate.setup_models.download_whisper",
        ) as whisper, patch.object(portable_app.tk, "Tk", side_effect=create_window):
            self.assertTrue(portable_app.ensure_models())
        asr.assert_called_once()
        whisper.assert_called_once()

    def test_failed_download_reports_error_then_allows_retry(self):
        real_tk = portable_app.tk.Tk
        root = real_tk()
        root.withdraw()
        def click():
            root.winfo_children()[0].winfo_children()[-1].winfo_children()[0].invoke()
        root.after(10, click)
        def retry(*args, **kwargs):
            root.after(20, click)
        with patch("streaming_transcribe_translate.setup_models.reazonspeech_ready", return_value=False), patch(
            "streaming_transcribe_translate.setup_models.whisper_ready", return_value=False,
        ), patch("streaming_transcribe_translate.setup_models.download_reazonspeech",
                 side_effect=[RuntimeError("network unavailable"), None]) as asr, patch(
            "streaming_transcribe_translate.setup_models.download_whisper",
        ) as whisper, patch.object(portable_app.tk, "Tk", return_value=root), patch.object(
            portable_app.messagebox, "showerror", side_effect=retry,
        ) as dialog, self.assertLogs(portable_app.log, level="ERROR"):
            self.assertTrue(portable_app.ensure_models())
        self.assertEqual(asr.call_count, 2)
        whisper.assert_called_once()
        dialog.assert_called_once()

    def test_frozen_data_paths_are_next_to_executable(self):
        original = paths.ROOT
        try:
            with patch("sys.frozen", True, create=True), patch("sys.executable", r"C:\Portable\LiveSubtitles.exe"), patch(
                "sys._MEIPASS", r"C:\Portable\_internal", create=True,
            ):
                importlib.reload(paths)
                self.assertEqual(paths.ROOT, Path(r"C:\Portable"))
                self.assertEqual(paths.RESOURCE_ROOT, Path(r"C:\Portable\_internal"))
        finally:
            importlib.reload(paths)
        self.assertEqual(paths.ROOT, original)

    def test_complete_model_setup_does_not_create_a_dialog(self):
        with patch("streaming_transcribe_translate.setup_models.reazonspeech_ready", return_value=True), patch(
            "streaming_transcribe_translate.setup_models.whisper_ready", return_value=True,
        ), patch.object(portable_app.tk, "Tk") as window:
            self.assertTrue(portable_app.ensure_models())
            window.assert_not_called()

    def test_runtime_uses_bundled_ffmpeg_and_local_hub_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ffmpeg").mkdir()
            with patch.object(portable_app, "ROOT", root), patch.object(portable_app, "RESOURCE_ROOT", root), patch.dict(
                "os.environ", {"PATH": "original"},
            ):
                portable_app.configure_runtime()
                self.assertTrue(portable_app.os.environ["PATH"].startswith(str(root / "ffmpeg")))
                self.assertEqual(portable_app.os.environ["HF_HOME"], str(root / "models" / ".hub-cache"))

    def test_self_test_reports_success_without_starting_a_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.json"
            with patch.object(portable_app, "ROOT", root), patch.object(
                portable_app, "configure_runtime",
            ), patch.object(portable_app, "self_test", return_value={"ok": True}), patch.object(
                portable_app, "ensure_models",
            ) as models, patch("sys.argv", ["app", "--self-test-report", str(report)]):
                portable_app.main()
            self.assertEqual(json.loads(report.read_text()), {"ok": True})
            models.assert_not_called()

    def test_failed_self_test_reports_failure_and_raises(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.json"
            with patch.object(portable_app, "ROOT", root), patch.object(
                portable_app, "configure_runtime",
            ), patch.object(portable_app, "self_test", side_effect=RuntimeError("missing native dependency")), patch(
                "sys.argv", ["app", "--self-test-report", str(report)],
            ):
                with self.assertRaises(RuntimeError):
                    portable_app.main()
            self.assertFalse(json.loads(report.read_text())["ok"])

    def test_download_setup_can_be_cancelled_without_starting_app(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(portable_app, "ROOT", Path(temporary)), patch.object(
            portable_app, "configure_runtime",
        ), patch.object(portable_app, "ensure_models", return_value=False), patch(
            "streaming_transcribe_translate.web_server.main",
        ) as web, patch("sys.argv", ["app", "--setup-models"]):
            portable_app.main()
            web.assert_not_called()
