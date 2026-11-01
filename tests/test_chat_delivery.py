import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streaming_transcribe_translate.chat_delivery import MultipartSender, format_chat, send_recorded, split_message
from streaming_transcribe_translate.simul_streaming_adapter import BilibiliChatSender, YouTubeChatSender, MissevanChatSender
from streaming_transcribe_translate.subtitle_records import SessionRecords
from streaming_transcribe_translate.subtitle_settings import SubtitleSettings


class FakeMultipartSender(MultipartSender):
    def __init__(self, fail_at=None):
        self._init_delivery("bilibili")
        self.max_message_length = 5
        self.send_interval = 0
        self.messages = []
        self.attempts = 0
        self.fail_at = fail_at

    def _send_one(self, message, original=None):
        self.attempts += 1
        if self.attempts == self.fail_at:
            return False, "slow mode"
        self.messages.append(message)
        return True, ""


class ChatDeliveryTests(unittest.TestCase):
    def test_default_template_and_allowed_placeholders(self):
        self.assertEqual(format_chat(SubtitleSettings().chat_template, "hello", "speech", "en"), "【hello】")
        self.assertEqual(format_chat("{language}: {translation} ({original})", "hello", "speech", "en"), "英语: hello (speech)")
        for template in ("", "[转译]", "{unknown}", "{translation!r}", "{translation.foo}", "{translation}{translation}", "{"):
            with self.assertRaises(ValueError):
                format_chat(template, "a", "b", "en")

    def test_split_preserves_all_characters_and_utf16_boundaries(self):
        for limit in (20, 100, 200):
            for message in ("x" * limit, "x" * (limit + 1), "【" + "😃ab " * 80 + "】"):
                parts = split_message(message, limit)
                self.assertEqual("".join(parts), message)
                self.assertTrue(all(len(part.encode("utf-16-le")) // 2 <= limit for part in parts))

    def test_all_site_senders_use_serialized_multipart_delivery(self):
        for sender, limit in (
            (BilibiliChatSender("1"), 20), (YouTubeChatSender("1"), 200), (MissevanChatSender("1"), 100),
        ):
            sender.send_interval = 0
            with patch.object(sender, "_send_one", return_value=(True, "")) as send:
                self.assertTrue(sender.send("x" * (limit + 1))[0])
                self.assertEqual([len(call.args[0]) for call in send.call_args_list], [limit, 1])

    def test_partial_failure_retry_sends_only_remaining_parts(self):
        sender = FakeMultipartSender(fail_at=2)
        self.assertFalse(sender.send("abcdefghijk")[0])
        self.assertEqual(sender.messages, ["abcde"])
        self.assertFalse(sender.send("modified text")[0])
        self.assertTrue(sender.send("abcdefghijk")[0])
        self.assertEqual(sender.messages, ["abcde", "fghij", "k"])

    def test_minimum_interval_is_applied_between_parts_and_calls(self):
        sender = FakeMultipartSender()
        sender.send_interval = 2
        with patch("streaming_transcribe_translate.chat_delivery.time.monotonic", return_value=100), \
                patch("streaming_transcribe_translate.chat_delivery.time.sleep") as sleep:
            sender.send("abcdef")
            sender.send("next")
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 2])

    def test_each_acknowledged_part_recorded_once_across_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SessionRecords(Path(folder), started_at_ms=1000)
            caption = store.caption(1, 2000, 3000, 1000, "speech", "translation", target_language="en")
            sender = FakeMultipartSender(fail_at=2)
            self.assertFalse(send_recorded(sender, "abcdefghijk", None, store, caption)[0])
            self.assertEqual([entry.message for entry in store.sent], ["abcde"])
            self.assertEqual(store.reviewed, [])
            self.assertTrue(send_recorded(sender, "abcdefghijk", None, store, caption)[0])
            self.assertEqual([entry.message for entry in store.sent], ["abcde", "fghij", "k"])
            self.assertEqual([entry.message for entry in store.reviewed], ["abcdefghijk"])
            restored = SessionRecords.restore(store.directory)
            self.assertEqual([entry.message for entry in restored.sent], sender.messages)

    def test_disk_failure_does_not_resend_acknowledged_parts(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SessionRecords(Path(folder), started_at_ms=1000)
            caption = store.caption(1, 2000, 3000, 1000, "speech", "translation")
            sender = FakeMultipartSender()
            with patch.object(store, "success", side_effect=OSError("disk full")):
                success, detail = send_recorded(sender, "abcdefghijk", None, store, caption)
            self.assertTrue(success)
            self.assertIn("不要再次发送", detail)
            self.assertEqual(sender.messages, ["abcde", "fghij", "k"])
