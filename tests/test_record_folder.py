import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest import TestCase

from streaming_transcribe_translate.app_controller import AppController
from streaming_transcribe_translate.subtitle_records import SessionRecords
from streaming_transcribe_translate.subtitle_settings import SubtitleSettings
from tests import test_overlay_window
from tests.test_web_ui import FakeBackend, WebTestCase


class RecordFolderTests(WebTestCase):
    def test_folder_is_saved_and_restored_without_moving_active_session(self):
        default = self.controller.records_root
        active = SessionRecords(default, enabled=True, started_at_ms=1000)
        caption = active.caption(1, 2000, 3000, 1000, "a", "b")
        active.skip(caption, "b", 4000)
        self.controller.app.host.records = active
        self.controller._record_stores[active.session_id] = active
        original_directory = active.directory
        with tempfile.TemporaryDirectory() as selected:
            status, data = self.request("POST", "/api/settings/subtitle", {"records_folder": selected})
            self.assertEqual(status, 200)
            self.assertEqual(data["state"]["records_folder"], selected)
            self.assertEqual(active.directory, original_directory)
            self.assertTrue((original_directory / "captions.jsonl").exists())
            self.assertFalse((Path(selected) / active.session_id).exists())
            restored = AppController(
                FakeBackend(), env_file=self.env, settings_file=self.controller.settings_file,
                interface_file=self.controller.interface_file, records_root=default,
            )
            self.assertEqual(restored.records_root, Path(selected))
            self.assertEqual(restored.subtitle_settings.record_directory(default), Path(selected))

    def test_invalid_folder_is_reported_and_previous_setting_remains(self):
        old = self.controller.records_root
        status, data = self.request("POST", "/api/settings/subtitle", {
            "records_folder": str(Path(self.tmp.name) / "missing"),
        })
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["title"], "无法保存字幕设置")
        self.assertEqual(self.controller.records_root, old)
        self.assertEqual(self.controller.subtitle_settings.records_folder, "")

    def test_unwritable_folder_does_not_change_setting(self):
        with mock.patch("tempfile.TemporaryFile", side_effect=PermissionError("permission denied")):
            status, _ = self.request("POST", "/api/settings/subtitle", {"records_folder": self.tmp.name})
        self.assertEqual(status, 400)
        self.assertEqual(self.controller.subtitle_settings.records_folder, "")

    def test_folder_picker_route_queues_ui_request(self):
        picker = mock.Mock()
        self.web.overlay = SimpleNamespace(choose_records_folder=picker)
        status, data = self.request("POST", "/api/records/folder")
        self.assertEqual((status, data["ok"]), (200, True))
        picker.assert_called_once_with()

    def test_exports_include_old_default_and_use_selected_destination(self):
        default = self.controller.records_root
        old = SessionRecords(default, started_at_ms=1000)
        caption = old.caption(1, 2000, 3000, 1000, "a", "b")
        old.success(caption, "b", 4000)
        with tempfile.TemporaryDirectory() as selected:
            self.controller.save_subtitle_settings({"records_folder": selected})
            self.assertIn(old.session_id, self.controller.export_sessions())
            result = self.controller.export_sent(old.session_id)
            self.assertEqual(Path(result["folder"]), Path(selected) / "exports")
            self.assertTrue(Path(result["srt"]).exists())

    def test_old_settings_keep_default_directory(self):
        settings = SubtitleSettings()
        self.assertEqual(settings.record_directory(Path(self.tmp.name)), Path(self.tmp.name))


class FolderPickerTests(TestCase):
    setUp = test_overlay_window.OverlayManagerTests.setUp

    def test_picker_cancel_keeps_saved_folder(self):
        self.controller.records_root = Path(self.tmp.name)
        with mock.patch("streaming_transcribe_translate.overlay_window.filedialog.askdirectory", return_value=""):
            self.manager.choose_records_folder()
            self.manager.pump()
        self.assertEqual(self.controller.saved, [])

    def test_picker_saves_selected_folder_on_tk_thread(self):
        self.controller.records_root = Path(self.tmp.name)
        with mock.patch(
            "streaming_transcribe_translate.overlay_window.filedialog.askdirectory",
            return_value=self.tmp.name,
        ) as picker:
            self.manager.choose_records_folder()
            self.assertEqual(self.controller.saved, [])
            self.manager.pump()
        self.assertEqual(self.controller.saved, [{"records_folder": self.tmp.name}])
        self.assertIs(picker.call_args.kwargs["parent"], self.root)
