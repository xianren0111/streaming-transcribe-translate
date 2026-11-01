import tempfile
import json
from io import StringIO
from dataclasses import asdict
import unittest
from pathlib import Path
from unittest.mock import patch

from streaming_transcribe_translate.app_controller import AppController
from streaming_transcribe_translate.desktop_app import TranslationApp
from streaming_transcribe_translate.env_preferences import normalize_env_choices
from streaming_transcribe_translate.env_preferences import overlay_position
from streaming_transcribe_translate.subtitle_settings import SubtitleSettings
from streaming_transcribe_translate.interface_preferences import InterfacePreferences
from streaming_transcribe_translate.platforms import PLATFORMS, platform_key
from dotenv import dotenv_values
from tests.test_web_ui import FakeBackend


class EnvPreferenceTests(unittest.TestCase):
    def test_single_room_url_routes_all_sites_and_saves_only_one_room_key(self):
        for url, key in (
            ("https://live.bilibili.com/25760587", "bilibili"),
            ("https://youtube.com/live/abc123def45", "youtube"),
            ("https://fm.missevan.com/live/869215180", "missevan"),
        ):
            with self.subTest(platform=key), tempfile.TemporaryDirectory() as temporary, patch(
                "streaming_transcribe_translate.app_controller.dotenv_values",
                return_value={"LIVE_ROOM_URL": url},
            ), patch("streaming_transcribe_translate.secret_store.load_secrets", return_value=({}, [])), patch(
                "streaming_transcribe_translate.env_preferences.dotenv_values", return_value={},
            ):
                root = Path(temporary)
                config = root / "config"
                config.touch()
                app = AppController(
                    FakeBackend(), env_file=config, settings_file=root / "settings.json",
                    interface_file=root / "interface.json", records_root=root / "records",
                )
                self.assertEqual(app.platform, key)
                self.assertEqual(app.room_url, url)
                with patch.object(app, "_write_env") as write:
                    app._persist_home_preferences(url)
                saved = write.call_args.args[0]
                self.assertEqual(saved["LIVE_ROOM_URL"], url)
                self.assertEqual([name for name in saved if name.endswith("_ROOM_URL")], ["LIVE_ROOM_URL"])

    def test_platform_names_and_legacy_aliases(self):
        self.assertEqual(PLATFORMS["bilibili"], "哔哩哔哩")
        self.assertEqual(PLATFORMS["missevan"], "猫耳FM")
        for name, key in (
            ("Bilibili", "bilibili"), ("哔哩哔哩", "bilibili"),
            ("MissEvan", "missevan"), ("猫耳FM", "missevan"), ("YouTube", "youtube"),
        ):
            self.assertEqual(platform_key(name), key)

    def test_documented_example_parses_and_lists_every_subtitle_field(self):
        document = (Path(__file__).resolve().parent.parent / "docs" / "ENV_CONFIGURATION.md").read_text(encoding="utf-8")
        for field in SubtitleSettings.__dataclass_fields__:
            self.assertIn("`SUBTITLE_" + field.upper() + "`", document)
        example = document.split("```dotenv\n", 1)[1].split("```", 1)[0]
        values = dotenv_values(stream=StringIO(example))
        with tempfile.TemporaryDirectory() as temporary, patch(
            "streaming_transcribe_translate.env_preferences.dotenv_values", return_value=values,
        ), patch("streaming_transcribe_translate.subtitle_settings.dotenv_values", return_value=values):
            path = Path(temporary)
            settings = SubtitleSettings.load(path / "settings.json", env_file=path / "config")
            self.assertEqual(settings.reading_languages, ["zh-CN", "en"])
            self.assertTrue(settings.chat_template_custom)
            self.assertEqual(settings.presets["主播模式"]["glossary"], "ASR: speech recognition")

    def test_controller_wires_all_default_groups_and_source_language(self):
        values = {
            "SOURCE_LANGUAGE": "en", "SUBTITLE_FONT_SIZE": "20",
            "SUBTITLE_READING_LANGUAGES": '["en"]', "UI_LANGUAGE": "ja",
            "UI_THEME": "dark", "OVERLAY_X": "100", "OVERLAY_Y": "200",
        }
        with tempfile.TemporaryDirectory() as temporary, patch(
            "streaming_transcribe_translate.env_preferences.dotenv_values", return_value=values,
        ), patch("streaming_transcribe_translate.subtitle_settings.dotenv_values", return_value=values), patch(
            "streaming_transcribe_translate.app_controller.dotenv_values", return_value=values,
        ), patch("streaming_transcribe_translate.secret_store.load_secrets", return_value=({}, [])):
            root = Path(temporary)
            config_file = root / "config"
            config_file.touch()
            def controller():
                return AppController(
                    FakeBackend(), env_file=config_file, settings_file=root / "settings.json",
                    interface_file=root / "interface.json", records_root=root / "records",
                )
            app = controller()
            self.assertEqual(app.source_language, "英语")
            self.assertEqual(app.subtitle_settings.font_size, 20)
            self.assertEqual(app.interface_preferences.theme, "dark")
            self.assertEqual(app.subtitle_settings.chat_template, "「{translation}」")
            self.assertEqual(app.overlay_position, (100, 200))
            self.assertEqual(app.startup_notices, [])
            (root / "overlay_window.json").write_text('{"x": 1, "y": 2}')
            values["OVERLAY_X"] = "invalid"
            self.assertIsNone(controller().overlay_position)

    def test_invalid_env_defaults_surface_startup_notices(self):
        values = {"SUBTITLE_FONT_SIZE": "invalid", "UI_THEME": "invalid", "OVERLAY_X": "1"}
        with tempfile.TemporaryDirectory() as temporary, patch(
            "streaming_transcribe_translate.env_preferences.dotenv_values", return_value=values,
        ), patch("streaming_transcribe_translate.app_controller.dotenv_values", return_value={}), patch(
            "streaming_transcribe_translate.secret_store.load_secrets", return_value=({}, []),
        ), self.assertLogs(level="ERROR"):
            root = Path(temporary)
            config = root / "config"
            config.touch()
            app = AppController(
                FakeBackend(), env_file=config, settings_file=root / "settings.json",
                interface_file=root / "interface.json", records_root=root / "records",
            )
            self.assertEqual(len(app.startup_notices), 3)
            self.assertEqual(app.subtitle_settings.font_size, 15)

    def test_all_subtitle_fields_accept_typed_env_defaults(self):
        defaults = asdict(SubtitleSettings())
        values = {
            "SUBTITLE_" + name.upper(): value if isinstance(value, str) else json.dumps(value)
            for name, value in defaults.items()
        }
        values.update({
            "SUBTITLE_READING_LANGUAGES": '["en", "ja"]',
            "SUBTITLE_CHAT_LANGUAGE": "en",
            "SUBTITLE_CHAT_TEMPLATE": "[{translation}]",
            "SUBTITLE_CHAT_TEMPLATE_CUSTOM": "true",
            "SUBTITLE_FONT_SIZE": "20",
            "SUBTITLE_WIDTH_PERCENT": "31.25",
            "SUBTITLE_USE_CONTEXT": "true",
        })
        with tempfile.TemporaryDirectory() as temporary, patch(
            "streaming_transcribe_translate.env_preferences.dotenv_values", return_value=values,
        ), patch("streaming_transcribe_translate.subtitle_settings.dotenv_values", return_value=values):
            path = Path(temporary) / "settings.json"
            settings = SubtitleSettings.load(path, env_file=Path(temporary) / "config")
            self.assertEqual(settings.reading_languages, ["en", "ja"])
            self.assertEqual(settings.chat_language, "en")
            self.assertEqual(settings.font_size, 20)
            self.assertEqual(settings.width_percent, 31.25)
            self.assertTrue(settings.use_context)
            self.assertTrue(settings.chat_template_custom)
            self.assertFalse(path.exists())

    def test_saved_fields_override_even_invalid_env_defaults(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "streaming_transcribe_translate.env_preferences.dotenv_values",
            return_value={"SUBTITLE_FONT_SIZE": "invalid", "SUBTITLE_OPACITY": "0.7"},
        ):
            path = Path(temporary) / "settings.json"
            path.write_text('{"font_size": 18}', encoding="utf-8")
            settings = SubtitleSettings.load(path, env_file=Path(temporary) / "config")
            self.assertEqual(settings.font_size, 18)
            self.assertEqual(settings.opacity, 0.7)
            settings.save(path)
            with patch("streaming_transcribe_translate.env_preferences.dotenv_values",
                       return_value={"SUBTITLE_OPACITY": "0.2"}):
                self.assertEqual(SubtitleSettings.load(path, env_file=Path(temporary) / "config").opacity, 0.7)

    def test_invalid_env_types_and_ranges_are_rejected(self):
        for key, value in (
            ("SUBTITLE_SHOW_ORIGINAL", "yes"), ("SUBTITLE_FONT_SIZE", "15.5"),
            ("SUBTITLE_FONT_SIZE", "100"), ("SUBTITLE_OPACITY", "NaN"),
            ("SUBTITLE_READING_LANGUAGES", "en,ja"),
            ("SUBTITLE_READING_LANGUAGES", '["invalid"]'),
            ("SUBTITLE_PRESETS", "[]"), ("SUBTITLE_CHAT_TEMPLATE", "no placeholder"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary, patch(
                "streaming_transcribe_translate.env_preferences.dotenv_values", return_value={key: value},
            ), patch("streaming_transcribe_translate.subtitle_settings.dotenv_values", return_value={key: value}):
                with self.assertRaises(ValueError):
                    SubtitleSettings.load(Path(temporary) / "settings.json", env_file=Path(temporary) / "config")

    def test_interface_defaults_and_saved_precedence(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "streaming_transcribe_translate.env_preferences.dotenv_values",
            return_value={"UI_THEME": "dark", "UI_LANGUAGE": "ja"},
        ):
            path = Path(temporary) / "interface.json"
            config = Path(temporary) / "config"
            self.assertEqual(InterfacePreferences.load(path, env_file=config),
                             InterfacePreferences(theme="dark", language="ja"))
            path.write_text('{"language": "en"}')
            self.assertEqual(InterfacePreferences.load(path, env_file=config),
                             InterfacePreferences(theme="dark", language="en"))

    def test_overlay_defaults_require_both_integer_coordinates(self):
        for values, expected in (
            ({}, None), ({"OVERLAY_X": "100", "OVERLAY_Y": "200"}, (100, 200)),
            ({"OVERLAY_X": "-10", "OVERLAY_Y": "0"}, (-10, 0)),
        ):
            with patch("streaming_transcribe_translate.env_preferences.dotenv_values", return_value=values):
                self.assertEqual(overlay_position(Path("config")), expected)
        for values in ({"OVERLAY_X": "1"}, {"OVERLAY_X": "1.5", "OVERLAY_Y": "2"}):
            with patch("streaming_transcribe_translate.env_preferences.dotenv_values", return_value=values):
                with self.assertRaises(ValueError):
                    overlay_position(Path("config"))

    def test_english_and_chinese_choices(self):
        for audio, expected_audio in (
            ("stream", "直播间声音"),
            ("microphone", "麦克风"),
            ("system", "电脑声音"),
            ("直播间声音", "直播间声音"),
            ("麦克风", "麦克风"),
            ("电脑声音", "电脑声音"),
            (" SYSTEM ", "电脑声音"),
        ):
            for mode, expected_mode in (
                ("manual", "手动确认"),
                ("automatic", "自动发送"),
                ("手动确认", "手动确认"),
                ("自动发送", "自动发送"),
                (" AUTOMATIC ", "自动发送"),
            ):
                with self.subTest(audio=audio, mode=mode):
                    values = {"AUDIO_INPUT": audio, "CHAT_MODE": mode}
                    result = normalize_env_choices(values)
                    self.assertEqual(result["AUDIO_INPUT"], expected_audio)
                    self.assertEqual(result["CHAT_MODE"], expected_mode)
                    self.assertEqual(values, {"AUDIO_INPUT": audio, "CHAT_MODE": mode})

    def test_defaults_and_invalid_choices(self):
        for values in ({}, {"AUDIO_INPUT": "", "CHAT_MODE": " "}):
            self.assertEqual(normalize_env_choices(values), {
                "AUDIO_INPUT": "直播间声音", "CHAT_MODE": "手动确认",
            })
        with self.assertLogs("streaming_transcribe_translate.env_preferences", level="WARNING") as logs:
            result = normalize_env_choices({"AUDIO_INPUT": "invalid", "CHAT_MODE": "invalid"})
        self.assertEqual(result, {"AUDIO_INPUT": "直播间声音", "CHAT_MODE": "手动确认"})
        self.assertEqual(len(logs.output), 2)

    def test_browser_and_tk_load_english_choices_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_file = root / "config"
            config_file.touch()
            for audio, expected_audio in (
                ("stream", "直播间声音"),
                ("microphone", "麦克风"),
                ("system", "电脑声音"),
            ):
                for mode, expected_mode in (("manual", "手动确认"), ("automatic", "自动发送")):
                    with (
                        self.subTest(audio=audio, mode=mode),
                        patch("streaming_transcribe_translate.app_controller.dotenv_values",
                              return_value={"AUDIO_INPUT": audio, "CHAT_MODE": mode}),
                        patch("streaming_transcribe_translate.desktop_app.dotenv_values",
                              return_value={"AUDIO_INPUT": audio, "CHAT_MODE": mode}),
                        patch("streaming_transcribe_translate.secret_store.load_secrets",
                              return_value=({}, [])),
                        patch("streaming_transcribe_translate.secret_store.write_env") as write,
                    ):
                        controller = AppController(
                            FakeBackend(), env_file=config_file,
                            settings_file=root / "settings.json",
                            interface_file=root / "interface.json",
                            records_root=root / "records",
                        )
                        self.assertEqual(controller.audio_input, expected_audio)
                        self.assertEqual(controller.chat_mode, expected_mode)
                        tk_config = TranslationApp._read_api_config(TranslationApp.__new__(TranslationApp))
                        self.assertEqual(tk_config["AUDIO_INPUT"], expected_audio)
                        self.assertEqual(tk_config["CHAT_MODE"], expected_mode)
                        write.assert_not_called()
