import unittest
from unittest.mock import Mock, patch

import requests

from streaming_transcribe_translate.simul_streaming_adapter import StreamingProjectTranslator, list_models


class TranslationRequestTests(unittest.TestCase):
    def _stream(self, text="Translation"):
        response = Mock(status_code=200)
        response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"' + text + '"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]
        return response

    def _cache_default_form(self, translator):
        translator._thinking_cache[(translator.base_url.rstrip("/"), translator.model)] = "thinking"

    def test_local_response_timeout_applies_to_connection_test_and_live_context(self):
        for host in ("localhost", "127.0.0.1", "[::1]"):
            for live_context in (False, True):
                with self.subTest(host=host, live_context=live_context):
                    translator = StreamingProjectTranslator(
                        base_url=f"http://{host}:11434/v1", model="gemma4:12b",
                    )
                    self._cache_default_form(translator)
                    if live_context:
                        translator.background = "A live conversation."
                        translator.history = [("Previous original", "Previous translation")]
                    with patch("requests.post", return_value=self._stream()) as post:
                        result = translator.translate("Synthetic speech")
                    self.assertIsNone(result.error)
                    self.assertEqual(post.call_args.kwargs["timeout"], (10, 120))
                    self.assertTrue(post.call_args.kwargs["stream"])
                    self.assertEqual(post.call_args.args[0], f"http://{host}:11434/v1/chat/completions")

    def test_remote_response_timeout_is_preserved(self):
        with patch("requests.post", side_effect=requests.ReadTimeout) as post:
            result = StreamingProjectTranslator(base_url="https://example.com/v1").translate("Synthetic speech")
        self.assertEqual(post.call_args.kwargs["timeout"], (10, 5))
        self.assertIn("\u54cd\u5e94\u8d85\u65f6", result.error)
        self.assertNotIn("\u65e0\u6cd5\u8fde\u63a5", result.error)

    def test_connection_failures_are_distinguished_from_slow_generation(self):
        for error, message in (
            (requests.ConnectTimeout, "\u8fde\u63a5\u7ffb\u8bd1\u670d\u52a1\u8d85\u65f6"),
            (requests.ConnectionError, "\u65e0\u6cd5\u8fde\u63a5\u7ffb\u8bd1\u670d\u52a1"),
        ):
            with self.subTest(error=error):
                with patch("requests.post", side_effect=error):
                    result = StreamingProjectTranslator(base_url="http://127.0.0.1:11434/v1").translate("Synthetic speech")
                self.assertIn(message, result.error)

class ModelDetectionTests(unittest.TestCase):
    def _response(self, status, payload=None):
        response = Mock(status_code=status, ok=200 <= status < 300)
        response.json.return_value = payload
        return response

    def test_openai_models_are_sorted_and_key_is_sent(self):
        payload = {"data": [{"id": "gpt-4o"}, {"id": "Claude"}, {"id": "gpt-4o"}]}
        with patch("requests.get", return_value=self._response(200, payload)) as get:
            models = list_models("https://api.example.com/v1/", "synthetic-key")
        self.assertEqual(models, ["Claude", "gpt-4o"])
        self.assertEqual(get.call_args.args[0], "https://api.example.com/v1/models")
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer synthetic-key"})
        self.assertEqual(get.call_args.kwargs["timeout"], (5, 15))

    def test_plain_ollama_address_falls_back_to_tags(self):
        responses = [self._response(404), self._response(404),
                     self._response(200, {"models": [{"name": "gemma4:12b"}]})]
        with patch("requests.get", side_effect=responses) as get:
            models = list_models("http://localhost:11434")
        self.assertEqual(models, ["gemma4:12b"])
        self.assertEqual(get.call_args.args[0], "http://localhost:11434/api/tags")
        self.assertEqual(get.call_args.kwargs["headers"], {})

    def test_errors_are_clear(self):
        cases = (
            (self._response(401), "API Key 无效"),
            (self._response(200, {"data": []}), "没有返回任何模型"),
            (requests.ConnectionError(), "无法连接翻译服务"),
        )
        for outcome, message in cases:
            with self.subTest(message=message):
                kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with patch("requests.get", **kwargs):
                    with self.assertRaisesRegex(ValueError, message):
                        list_models("https://api.example.com/v1")
        with self.assertRaisesRegex(ValueError, "有效的服务地址"):
            list_models("not a url")
