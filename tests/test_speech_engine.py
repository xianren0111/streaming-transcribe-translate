import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from streaming_transcribe_translate import reazon_asr
from streaming_transcribe_translate.desktop_app_example import DesktopSessionHost, DesktopSessionPrefs
from streaming_transcribe_translate.setup_models import MODELS
from streaming_transcribe_translate.ui_translations import TRANSLATIONS


class SpeechEngineTests(unittest.TestCase):
    def test_model_list_matches_simul_subtitle(self):
        names = [name for name, *_ in MODELS]
        self.assertEqual(names, [
            "asr/encoder.int8.onnx", "asr/decoder.onnx", "asr/joiner.int8.onnx",
            "asr/tokens.txt", "vad/silero_vad.onnx",
        ])
        self.assertTrue(all("12b44671ff48b9aed622551d64e02fea9a2cf870" in url for name, url, *_ in MODELS if name.startswith("asr/")))

    def test_japanese_english_and_auto_use_reazonspeech(self):
        for language in (None, "ja", "en"):
            with self.subTest(language=language):
                with patch.object(reazon_asr, "ReazonSpeechAsr", return_value="reazon") as engine:
                    self.assertEqual(reazon_asr.create_asr(language), "reazon")
                engine.assert_called_once_with()

    def test_chinese_uses_local_whisper_folder(self):
        with patch.object(reazon_asr, "whisper_ready", return_value=True), \
                patch("streaming_transcribe_translate.simul_streaming_adapter.StreamingProjectAsr") as whisper:
            reazon_asr.create_asr("zh")
        path, language = whisper.call_args.args
        self.assertTrue(path.endswith("whisper-base"))
        self.assertEqual(language, "zh")

    def test_missing_models_never_download_and_show_friendly_message(self):
        with patch.object(reazon_asr, "reazonspeech_ready", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "Setup Models.bat"):
                reazon_asr.ReazonSpeechAsr()
        with patch.object(reazon_asr, "whisper_ready", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "Setup Models.bat"):
                reazon_asr.create_asr("zh")
        self.assertIn(reazon_asr.MODELS_MISSING, TRANSLATIONS)

    def test_session_host_loads_engine_for_source_language(self):
        prefs = DesktopSessionPrefs()
        prefs._source_lang = SimpleNamespace(value="ja")
        host = DesktopSessionHost(prefs)
        fake = Mock()
        with patch("streaming_transcribe_translate.reazon_asr.create_asr", return_value=fake) as create, \
                patch("streaming_transcribe_translate.simul_streaming_adapter.StreamingSpeechModels._load_vad"):
            models = host.load_models()
        create.assert_called_once_with("ja")
        self.assertIs(models.asr, fake)


if __name__ == "__main__":
    unittest.main()
