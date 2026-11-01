import csv
import json
from pathlib import Path
from unittest import mock

from streaming_transcribe_translate.subtitle_records import SessionRecords
from tests.test_web_ui import FakeSender, WebTestCase


class ReviewRecordsTests(WebTestCase):
    def queue_record(self, sender=None, enabled=True):
        store = SessionRecords(self.controller.records_root, started_at_ms=1000, enabled=enabled)
        record = store.caption(1, 2000, 4000, 2000, "original speech", "AI translation")
        self.controller._record_stores[store.session_id] = store
        self.controller._enqueue_chat_review("queued translation", sender, record.original, record)
        return store, record

    def test_translation_arrival_does_not_save_caption_files(self):
        store, _ = self.queue_record()
        self.assertFalse(store.directory.exists())

    def test_skip_saves_current_editor_text_without_draft_debounce(self):
        store, _ = self.queue_record()
        self.controller.set_draft("stale draft")
        status, _ = self.request("POST", "/api/chat/skip", {"text": "fresh edited text"})
        self.assertEqual(status, 200)
        row = json.loads((store.directory / "captions.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["original"], "original speech")
        self.assertEqual(row["translated"], "fresh edited text")
        self.assertEqual(row["ai_translation"], "AI translation")
        self.assertEqual(row["action"], "skipped")
        self.assertIn("fresh edited text", (store.directory / "captions.txt").read_text(encoding="utf-8"))
        self.assertEqual(self.controller.snapshot()["pending"], [])
        self.assertFalse((store.directory / "sent_messages.jsonl").exists())

    def test_successful_send_saves_actual_edited_message(self):
        sender = FakeSender()
        store, _ = self.queue_record(sender)
        self.controller.send_pending_chat(" edited message ")
        self.controller._send_thread.join(5)
        self.assertEqual(sender.sent, ["edited message"])
        row = json.loads((store.directory / "captions.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["translated"], sender.sent[0])
        self.assertEqual(row["original"], "original speech")
        self.assertEqual(row["action"], "sent")
        sent = json.loads((store.directory / "sent_messages.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(sent["message"], sender.sent[0])
        restored = SessionRecords.restore(store.directory)
        srt, _ = restored.export(store.directory / "exports")
        self.assertIn(sender.sent[0], srt.read_text(encoding="utf-8"))

    def test_failed_send_saves_nothing_and_keeps_item_for_skip(self):
        store, _ = self.queue_record(FakeSender((False, "failure")))
        self.controller.send_pending_chat("edited failed send")
        self.controller._send_thread.join(5)
        self.assertFalse(store.directory.exists())
        self.assertEqual(len(self.controller.snapshot()["pending"]), 1)
        self.controller.skip_pending_chat()
        row = json.loads((store.directory / "captions.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["translated"], "edited failed send")
        self.assertEqual(row["action"], "skipped")

    def test_skip_save_failure_keeps_item_and_reports_error(self):
        store, _ = self.queue_record()
        with mock.patch.object(store, "skip", side_effect=OSError("disk full")):
            status, data = self.request("POST", "/api/chat/skip", {"text": "edited"})
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["title"], "记录未保存")
        self.assertEqual(len(self.controller.snapshot()["pending"]), 1)
        self.assertEqual(self.controller.snapshot()["draft"], "edited")

    def test_skip_with_records_off_writes_nothing(self):
        store, _ = self.queue_record(enabled=False)
        self.controller.skip_pending_chat("edited")
        self.assertFalse(store.directory.exists())

    def test_review_is_not_saved_twice(self):
        store, record = self.queue_record()
        store.skip(record, "edited", 5000)
        store.skip(record, "edited", 6000)
        self.assertEqual(len((store.directory / "captions.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_skipped_only_session_is_selectable_and_exportable_after_restart(self):
        store, _ = self.queue_record()
        self.controller.skip_pending_chat("edited skip")
        for restarted in (False, True):
            if restarted:
                self.controller._record_stores.clear()
            status, data = self.request("GET", "/api/records")
            self.assertEqual(status, 200)
            self.assertIn(store.session_id, data["sessions"])
            status, result = self.request("POST", "/api/records/export", {"session": store.session_id})
            self.assertEqual(status, 200)
            srt = Path(result["srt"]).read_text(encoding="utf-8")
            self.assertIn("00:00:01,000 --> 00:00:03,000", srt)
            self.assertIn("edited skip", srt)
            self.assertNotIn("AI translation", srt)
            with Path(result["csv"]).open(encoding="utf-8-sig", newline="") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["action"], "skipped")
            self.assertEqual(rows[0]["actual_reviewed_text"], "edited skip")
            self.assertEqual(rows[0]["translated"], "AI translation")
            self.assertEqual(rows[0]["sent_clock"], "")
            self.assertEqual(rows[0]["actual_sent_message"], "")

    def test_mixed_export_excludes_unreviewed_and_does_not_duplicate_sends(self):
        store, first = self.queue_record()
        store.skip(first, "edited skip", 5000)
        second = store.caption(2, 4000, 6000, 2000, "speech two", "AI two")
        store.success(second, "edited send", 7000)
        store.caption(3, 6000, 8000, 2000, "unreviewed", "not exported")
        restored = SessionRecords.restore(store.directory)
        srt, csv_path = restored.export(store.directory / "exports", include_skipped=True)
        text = srt.read_text(encoding="utf-8")
        self.assertEqual(text.count("edited skip"), 1)
        self.assertEqual(text.count("edited send"), 1)
        self.assertNotIn("not exported", text)
        with csv_path.open(encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
        self.assertEqual([row["action"] for row in rows], ["skipped", "sent"])
        sent_srt, _ = restored.export(store.directory / "sent-only")
        self.assertNotIn("edited skip", sent_srt.read_text(encoding="utf-8"))
