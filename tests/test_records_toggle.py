import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from streaming_transcribe_translate import app_controller
from streaming_transcribe_translate.app_controller import AppController, UserError
from streaming_transcribe_translate.subtitle_records import SessionRecords
from streaming_transcribe_translate.subtitle_settings import SubtitleSettings

T0 = 1_700_000_000_000


class RecordsSettingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_records_are_off_by_default_and_old_files_still_load(self):
        self.assertFalse(SubtitleSettings().save_records)
        path = self.root / "settings.json"
        path.write_text(json.dumps({"font_size": 30, "save_captions": True}), encoding="utf-8")
        loaded = SubtitleSettings.load(path)
        self.assertFalse(loaded.save_records)
        self.assertEqual(loaded.font_size, 30)

    def test_round_trip_and_validation(self):
        path = self.root / "settings.json"
        replace(SubtitleSettings(), save_records=True).save(path)
        self.assertTrue(SubtitleSettings.load(path).save_records)
        with self.assertRaises(ValueError):
            replace(SubtitleSettings(), save_records="yes").validate()


class SessionRecordsToggleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_disabled_records_write_nothing_but_stay_in_memory(self):
        store = SessionRecords(self.root, save_captions=True, diagnostics=True, enabled=False)
        store.event("started", detail="x")
        caption = store.caption(1, 1_000, 2_000, 1_000, "原文", "translated")
        store.success(caption, "translated", 3_000)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(len(store.captions), 1)
        self.assertEqual(len(store.sent), 1)

    def test_enabled_records_write_files(self):
        store = SessionRecords(self.root, save_captions=True, diagnostics=True, enabled=True)
        store.event("started")
        caption = store.caption(1, 1_000, 2_000, 1_000, "原文", "translated")
        store.success(caption, "translated", 3_000)
        names = {path.name for path in store.directory.iterdir()}
        self.assertTrue({"captions.jsonl", "sent_messages.jsonl", "diagnostics.jsonl"} <= names)


def bare_controller(records_root, save_records):
    controller = AppController.__new__(AppController)
    controller.records_root = Path(records_root)
    controller.subtitle_settings = replace(SubtitleSettings(), save_records=save_records)
    controller._record_stores = {}
    return controller


class ControllerRecordsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "records"

    def test_open_and_export_explain_that_records_are_off(self):
        controller = bare_controller(self.root, False)
        with self.assertRaises(UserError) as opened:
            controller.open_records()
        self.assertEqual(opened.exception.title, app_controller.RECORDS_OFF_TITLE)
        with self.assertRaises(UserError) as exported:
            controller.export_sent("missing")
        self.assertEqual(exported.exception.title, app_controller.RECORDS_OFF_TITLE)
        self.assertFalse(controller.records_hint()["enabled"])

    def test_records_on_keeps_regular_messages(self):
        controller = bare_controller(self.root, True)
        with self.assertRaises(UserError) as opened:
            controller.open_records()
        self.assertEqual(opened.exception.title, "没有记录")
        self.assertTrue(controller.records_hint()["enabled"])

    def test_disabled_in_memory_stores_are_not_exportable(self):
        controller = bare_controller(self.root, False)
        store = SessionRecords(self.root, enabled=False)
        caption = store.caption(1, 1_000, 2_000, 1_000, "a", "b")
        store.success(caption, "b", 3_000)
        controller._record_stores[store.session_id] = store
        self.assertEqual(controller.export_sessions(), {})

    def test_existing_record_folders_remain_exportable_when_off(self):
        old = SessionRecords(self.root, enabled=True, started_at_ms=T0)
        caption = old.caption(1, T0, T0 + 1_000, 1_000, "a", "b")
        old.success(caption, "b", T0 + 2_000)
        controller = bare_controller(self.root, False)
        self.assertIn(old.session_id, controller.export_sessions())
        result = controller.export_sent(old.session_id)
        self.assertTrue(Path(result["srt"]).is_file())


if __name__ == "__main__":
    unittest.main()
