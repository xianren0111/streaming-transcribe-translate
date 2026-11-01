import json
import unittest
from unittest.mock import Mock, patch

import requests

from streaming_transcribe_translate.simul_interfaces import Lang, Target
from streaming_transcribe_translate.simul_streaming_adapter import StreamingProjectTranslator


class TranslationParityTests(unittest.TestCase):
    def setUp(self):
        with StreamingProjectTranslator._cache_lock:
            StreamingProjectTranslator._thinking_cache.clear()

    @staticmethod
    def response(events, status=200):
        response = Mock(status_code=status)
        response.iter_lines.return_value = [
            "data: " + json.dumps(event, ensure_ascii=True) for event in events
        ] + ["data: [DONE]"]
        return response

    @classmethod
    def answer(cls, *parts, reasoning=None):
        events = []
        for part in parts:
            delta = {"content": part}
            if reasoning:
                delta.update(reasoning)
            events.append({"choices": [{"delta": delta}]})
        events.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        return cls.response(events)

    def test_sse_stream_yields_cumulative_partials_and_final_translation(self):
        translator = StreamingProjectTranslator(
            Lang.JA, Target.ZH_CN, base_url="https://api.example/v1", model="test-model",
        )
        probe = self.answer("ok")
        final = self.answer("\u4eca\u5929", "\u5929\u6c14\u771f\u597d\u3002")
        partials = []
        with patch("requests.post", side_effect=[probe, final]) as post:
            result = translator.translate_with_updates("\u4eca\u65e5\u306f\u3044\u3044\u5929\u6c17\u3067\u3059\u306d\u3002", partials.append)
        self.assertEqual(result.text, "\u4eca\u5929\u5929\u6c14\u771f\u597d\u3002")
        self.assertEqual(partials, ["\u4eca\u5929", "\u4eca\u5929\u5929\u6c14\u771f\u597d\u3002"])
        self.assertEqual(post.call_count, 2)
        request = post.call_args.kwargs
        self.assertEqual(post.call_args.args[0], "https://api.example/v1/chat/completions")
        self.assertTrue(request["stream"])
        self.assertEqual(request["timeout"], (10, 5))
        self.assertEqual(request["json"]["temperature"], 0)
        self.assertEqual(request["json"]["max_tokens"], 160)
        self.assertEqual(final.encoding, "utf-8")

    def test_reasoning_forms_probe_in_reference_order_and_cache_by_service_model(self):
        translator = StreamingProjectTranslator(base_url="https://api.example/v1", model="probe-model")
        rejected = self.response([], status=400)
        detected = self.answer("ok")
        actual = self.answer("done")
        with patch("requests.post", side_effect=[rejected, detected, actual, self.answer("next")]) as post:
            result = translator.translate("sentence")
            translator.translate("another sentence")
        self.assertEqual(result.text, "done")
        bodies = [call.kwargs["json"] for call in post.call_args_list]
        self.assertEqual(
            [name for name, _params, _note in translator.THINKING_OFF],
            ["thinking", "template", "enable", "reasoning", "effort", "minimal", "none"],
        )
        expected = [
            {"type": "disabled"},
            {"enable_thinking": False, "thinking": False},
            {"enable_thinking": False, "thinking": False},
            {"enable_thinking": False, "thinking": False},
        ]
        self.assertEqual([body.get("thinking", body.get("chat_template_kwargs")) for body in bodies], expected)
        self.assertEqual(post.call_count, 4)

    def test_reasoning_only_probe_advances_instead_of_being_mistaken_for_timeout(self):
        translator = StreamingProjectTranslator(base_url="http://localhost:11434/v1", model="reason-only")
        response = self.response([
            {"choices": [{"delta": {"content": "", "reasoning": "thinking"},
                          "finish_reason": "stop"}]},
        ])
        with patch("requests.post", return_value=response):
            result = translator._request_stream("source", "thinking", None, probe=True)
        self.assertEqual(result.error, "reasoning still enabled")
        self.assertEqual(result.http_status, 200)

    def test_fatal_probe_status_aborts_without_retry(self):
        translator = StreamingProjectTranslator(base_url="https://api.example/v1", model="fatal-model")
        with patch("requests.post", return_value=self.response([], status=403)) as post:
            result = translator.translate("sentence")
        self.assertEqual(result.http_status, 403)
        self.assertEqual(post.call_count, 1)

    def test_probe_retries_400_but_not_network_failure(self):
        translator = StreamingProjectTranslator(base_url="https://api.example/v1", model="network-model")
        with patch("requests.post", side_effect=requests.ConnectionError("network")) as post:
            result = translator.translate("sentence")
        self.assertIn("\u65e0\u6cd5\u8fde\u63a5", result.error)
        self.assertEqual(post.call_count, 1)

    def test_reasoning_channels_never_reach_live_partial_text(self):
        translator = StreamingProjectTranslator(base_url="https://api.example/v1", model="reasoning-model")
        translator._thinking_cache[(translator.base_url, translator.model)] = "thinking"
        response = self.answer("\u53ef\u89c1", "<think>private reasoning</think>", "\u8bd1\u6587")
        partials = []
        with patch("requests.post", return_value=response):
            result = translator.translate_with_updates("source", partials.append)
        self.assertEqual(result.text, "\u53ef\u89c1\u8bd1\u6587")
        self.assertTrue(all("private" not in partial for partial in partials))
        self.assertEqual(partials[-1], "\u53ef\u89c1\u8bd1\u6587")

    def test_glossary_is_chinese_only_and_context_is_finalized_source_text(self):
        translator = StreamingProjectTranslator(
            Lang.JA, Target.EN, base_url="https://api.example/v1", glossary="term: \u8bd1\u6cd5",
        )
        translator.history = [("prior source", "prior translation")]
        messages = translator._messages("current source")
        self.assertNotIn("term:", messages[0]["content"])
        self.assertIn("prior source", messages[1]["content"])
        self.assertNotIn("prior translation", messages[1]["content"])
        self.assertIn("current source", messages[1]["content"])

    def test_chinese_presets_use_160_tokens_and_other_targets_256(self):
        for target, cap in ((Target.ZH_CN, 160), (Target.ZH_TW, 160), (Target.EN, 256)):
            translator = StreamingProjectTranslator(target_lang=target, base_url="http://localhost:11434/v1")
            with patch("requests.post", side_effect=requests.ReadTimeout) as post:
                request = translator._request_stream("source", "none", None)
            self.assertIn("\u54cd\u5e94\u8d85\u65f6", request.error)
            self.assertEqual(post.call_args.kwargs["timeout"], (10, 120))
            self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], cap)


if __name__ == "__main__":
    unittest.main()
