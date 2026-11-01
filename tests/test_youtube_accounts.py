from contextlib import contextmanager
import unittest
from unittest.mock import Mock, patch

from streaming_transcribe_translate import streaming_bridge
from streaming_transcribe_translate.simul_streaming_adapter import YouTubeChatSender, StreamAudioSource


class YouTubeAccountsTests(unittest.TestCase):
    def test_youtube_audio_accepts_audio_only_live_formats(self):
        source = StreamAudioSource("https://www.youtube.com/watch?v=NCycSRKpZUw", "youtube")
        with (
            patch("yt_dlp.YoutubeDL") as downloader,
            patch("subprocess.Popen") as process,
        ):
            downloader.return_value.__enter__.return_value.extract_info.return_value = {"url": "https://audio.example/live.m3u8"}
            source._start_process()
        self.assertEqual(downloader.call_args.args[0]["format"], "bestaudio/best")
        command = process.call_args.args[0]
        self.assertEqual(command[command.index("-i") + 1], "https://audio.example/live.m3u8")

    def test_selected_channel_is_isolated_in_send_context(self):
        active = {}

        @contextmanager
        def using(values):
            active.update(values)
            try:
                yield
            finally:
                active.clear()

        login, youtube = Mock(), Mock()
        login.using.side_effect = using

        def send(video_id, message):
            self.assertEqual(active, {"youtube": {"SAPISID": "test"}, "youtube_page_id": "brand-id"})
            return True, "sent"

        youtube.send_message.side_effect = send
        with patch.object(streaming_bridge, "_modules", return_value=(Mock(), login, Mock(), youtube)):
            sender = YouTubeChatSender("abc123def45", {"SAPISID": "test"}, page_id="brand-id")
            self.assertEqual(sender.send("edited message"), (True, "sent"))
        youtube.send_message.assert_called_once_with("abc123def45", "edited message")
        self.assertEqual(active, {})

    def test_discovery_uses_explicit_cookies_and_reports_failures(self):
        login, youtube = Mock(), Mock()

        @contextmanager
        def using(values):
            self.assertEqual(values, {"youtube": {"SAPISID": "test"}})
            yield

        login.using.side_effect = using
        channels = [{"name": "Brand channel", "handle": "@brand", "page_id": "brand-id", "selected": True}]
        with patch.object(streaming_bridge, "_modules", return_value=(Mock(), login, Mock(), youtube)):
            youtube.list_channels.return_value = {"channels": channels}
            self.assertEqual(streaming_bridge.list_youtube_channels({"SAPISID": "test"}), channels)
            for response in ({"channels": []}, {"channels": [], "error": "private response"}):
                youtube.list_channels.return_value = response
                with self.assertRaises(streaming_bridge.LoginError) as error:
                    streaming_bridge.list_youtube_channels({"SAPISID": "test"})
                self.assertNotIn("private response", str(error.exception))

    def test_auto_selection_uses_selected_brand_not_first_account(self):
        channels = [
            {"name": "Main", "handle": "", "page_id": "", "selected": False},
            {"name": "Brand", "handle": "@brand", "page_id": "brand-id", "selected": True},
        ]
        with patch.object(streaming_bridge, "list_youtube_channels", return_value=channels):
            self.assertEqual(streaming_bridge.current_youtube_channel({"SAPISID": "test"}), channels[1])
            channels[1]["selected"] = False
            with self.assertRaises(streaming_bridge.LoginError):
                streaming_bridge.current_youtube_channel({"SAPISID": "test"})
        with patch.object(streaming_bridge, "list_youtube_channels", return_value=[channels[1]]):
            self.assertEqual(streaming_bridge.current_youtube_channel({"SAPISID": "test"})["page_id"], "brand-id")
