"""
Streaming Project Adapter - Bridges Simul Subtitle interfaces with Streaming project.

Implements simul_interfaces using the transcription and translation modules
from the Streaming project (github.com/Nyanko7/Streaming).

MIT License (inherited from both projects)
"""

from __future__ import annotations

import logging
import os
import queue
from importlib.metadata import PackageNotFoundError, distribution
import threading
import time
from typing import Optional, List, Tuple, Callable, Dict

from .simul_interfaces import (
    Asr, Mt, MtResult, AudioSource, SpeechModels, SessionPrefs,
    Lang, Target, ChatSender,
)

log = logging.getLogger(__name__)

# pythonw has no console, so child processes would otherwise open a terminal window.
_NO_CONSOLE_WINDOW = 0x08000000 if os.name == "nt" else 0


# ============================================================================
# ASR Implementation (using faster-whisper from Streaming project)
# ============================================================================

class StreamingProjectAsr(Asr):
    """Speech-to-text using faster-whisper (from Streaming project)."""
    
    def __init__(self, model_size: str = "base", language: Optional[str] = None):
        self.model_size = model_size
        self.language = language
        self.model = None
        self._cuda_dll_handles = []
        self._load_model()
    
    def _load_model(self) -> None:
        """Load Whisper model."""
        try:
            import ctranslate2
            from faster_whisper import WhisperModel
            
            log.info(f"Loading Whisper model: {self.model_size}")
            device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
            if device == "cuda" and os.name == "nt":
                for package, library in (
                    ("nvidia-cublas-cu12", "cublas"),
                    ("nvidia-cudnn-cu12", "cudnn"),
                ):
                    try:
                        directory = distribution(package).locate_file(
                            f"nvidia/{library}/bin"
                        )
                    except PackageNotFoundError:
                        log.warning(
                            "%s is not installed; CUDA libraries must be on PATH", package
                        )
                        continue
                    if directory.is_dir():
                        self._cuda_dll_handles.append(os.add_dll_directory(str(directory)))
                        current_path = os.environ.get("PATH", "")
                        if str(directory) not in current_path.split(os.pathsep):
                            os.environ["PATH"] = str(directory) + os.pathsep + current_path
            compute_type = "float16" if device == "cuda" else "int8"
            self.model = WhisperModel(
                self.model_size,
                device=device,
                compute_type=compute_type,
            )
            log.info("Warming up Whisper on %s (%s)", device, compute_type)
            self.recognize([0.0] * 16000)
            log.info("Whisper model ready on %s (%s)", device, compute_type)
        except ImportError as e:
            log.error("faster-whisper not installed: pip install faster-whisper")
            raise
        except Exception as e:
            log.error(f"Failed to load Whisper: {e}")
            raise
    
    def recognize(self, samples: List[float]) -> str:
        """Recognize speech."""
        if not self.model:
            return ""
        
        try:
            import numpy as np
            audio_array = np.array(samples, dtype=np.float32)
            
            segments, info = self.model.transcribe(
                audio_array,
                language=self.language,
                beam_size=1,
                condition_on_previous_text=False,
            )
            
            text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
            return text
        
        except Exception as e:
            log.error(f"Transcription error: {e}")
            raise


# ============================================================================
# MT Implementation (using Streaming project's translate module)
# ============================================================================

def list_models(base_url: str, api_key: str = "") -> List[str]:
    """Return model IDs offered by an OpenAI-compatible (or Ollama) service."""
    import requests
    from urllib.parse import urlparse

    base = base_url.strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("请填写有效的服务地址，例如 https://api.openai.com/v1。")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    candidates = [f"{base}/models"]
    if not base.endswith("/v1"):
        # Plain Ollama addresses (http://localhost:11434) expose /api/tags.
        candidates += [f"{base}/v1/models", f"{base}/api/tags"]
    last_error = "服务没有返回模型列表。"
    for url in candidates:
        try:
            response = requests.get(url, headers=headers, timeout=(5, 15))
        except requests.Timeout:
            raise ValueError("连接翻译服务超时，请检查服务地址。") from None
        except requests.RequestException:
            raise ValueError("无法连接翻译服务，请检查服务地址和网络。") from None
        if response.status_code in (401, 403):
            raise ValueError("API Key 无效或没有权限读取模型列表。")
        if response.status_code == 404:
            last_error = "此服务地址不支持读取模型列表，请手动填写模型 ID。"
            continue
        if not response.ok:
            raise ValueError(f"服务返回错误（HTTP {response.status_code}）。")
        try:
            payload = response.json()
        except ValueError:
            last_error = "服务返回的模型列表格式无法识别。"
            continue
        items = []
        if isinstance(payload, dict):
            items = payload.get("data") or payload.get("models") or []
        elif isinstance(payload, list):
            items = payload
        names = set()
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict):
                name = item.get("id") or item.get("name") or item.get("model")
            else:
                name = item
            if isinstance(name, str) and name.strip():
                names.add(name.strip())
        if names:
            return sorted(names, key=str.lower)
        last_error = "服务没有返回任何模型。"
    raise ValueError(last_error)


class StreamingProjectTranslator(Mt):
    """Translation using an OpenAI-compatible streaming API or Streaming project."""

    # Exact probe order from the reference Translation.kt:683-702.
    THINKING_OFF = (
        ("thinking", {"thinking": {"type": "disabled"}}, ""),
        ("template", {"chat_template_kwargs": {"enable_thinking": False, "thinking": False}}, ""),
        ("enable", {"enable_thinking": False}, ""),
        ("reasoning", {"reasoning": {"enabled": False}}, ""),
        ("effort", {"reasoning_effort": "none"}, ""),
        ("minimal", {"reasoning_effort": "minimal"},
         "CRITICAL: Do not think and do not output any reasoning steps. "
         "Directly output the translation result only.\n"
         "\u76f4\u63a5\u8f93\u51fa\u7ffb\u8bd1\u7ed3\u679c\uff0c\u7981\u6b62\u8f93\u51fa\u4efb\u4f55\u601d\u8003\u8fc7\u7a0b\u4e0e\u63a8\u7406\u8bf4\u660e."),
        ("none", {}, ""),
    )
    _thinking_cache: dict[tuple[str, str], Optional[str]] = {}
    _cache_lock = threading.Lock()

    def __init__(
        self,
        source_lang: Optional[Lang] = None,
        target_lang: Target = Target.ZH_CN,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
        background: str = "",
        glossary: str = "",
    ):
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.api_key = api_key
        self.use_api = bool(api_key or base_url)
        self.base_url = base_url or "https://api.openai.com/v1"
        self.model = model
        self.background = background
        self.glossary = glossary
        self.history: List[Tuple[str, str]] = []
        self.correction = ""
        self.last_messages: list[dict[str, str]] = []
        self.cancel_flag = False
        self._lock = threading.Lock()
        self._active_response = None

    def translate(self, prompt: str) -> Optional[MtResult]:
        """Return the final translation; partial streaming updates are opt-in."""
        return self.translate_with_updates(prompt)

    def translate_with_updates(
        self, prompt: str, on_partial: Optional[Callable[[str], None]] = None,
    ) -> Optional[MtResult]:
        """Translate and report cumulative, reasoning-free text as it arrives."""
        if self.cancel_flag:
            return None
        if self.use_api:
            return self._translate_with_api(prompt, on_partial)
        try:
            from src import translate as translate_module
            translated, _source_lang = translate_module.get_translation(
                prompt, self._map_language(self.target_lang),
            )
            if not translated:
                return None
            return MtResult(text=translated, http_status=200, latency_ms=0)
        except ImportError:
            log.error("Streaming project not available")
            return MtResult(text="", error="Translation API key and Streaming project are unavailable")
        except Exception as error:
            log.error("Translation error: %s", type(error).__name__)
            return MtResult(text="", error=str(error))

    def _language_name(self, language: Optional[Lang], *, source: bool = False) -> str:
        if language is None:
            return "\u5916\u8bed" if source else "\u4e2d\u6587"
        return {
            Lang.JA: "\u65e5\u8bed", Lang.EN: "\u82f1\u8bed", Lang.ZH: "\u4e2d\u6587",
        }.get(language, language.value)

    def _system_message(self) -> str:
        source = self._language_name(self.source_lang, source=True)
        target = {
            Target.ZH_CN: "\u7b80\u4f53\u4e2d\u6587", Target.ZH_TW: "\u7e41\u4f53\u4e2d\u6587",
            Target.EN: "\u82f1\u8bed", Target.JA: "\u65e5\u8bed", Target.KO: "\u97e9\u8bed",
        }.get(self.target_lang, self._map_language(self.target_lang))
        system = (
            f"\u4f60\u662f\u76f4\u64ad\u5b57\u5e55\u7ffb\u8bd1\u3002\u628a\u3010\u5f53\u524d\u53e5\u3011\u7684{source}"
            f"\u7ffb\u8bd1\u6210\u81ea\u7136\u3001\u53e3\u8bed\u5316\u7684{target}\uff0c\u51c6\u786e\u4fdd\u7559\u539f\u610f\u3001\u80af\u5b9a\u5426\u5b9a\u548c\u4eba\u7269\u5173\u7cfb\uff1b"
            "\u4fdd\u7559\u4eba\u540d\uff0c\u4e0d\u51ed\u7a7a\u8865\u5145\u5185\u5bb9\u3002"
            "\u5b57\u5e55\u8981\u7b80\u77ed\uff0c\u53ef\u4ee5\u7701\u7565\u65e0\u610f\u4e49\u7684\u53e3\u5934\u91cd\u590d\u3002"
            "\u3010\u524d\u6587\u3011\u53ea\u7528\u4e8e\u7406\u89e3\u5f53\u524d\u53e5\u7684\u6307\u4ee3\u548c\u7701\u7565\uff0c\u4e0d\u8981\u7ffb\u8bd1\u3001\u4e0d\u8981\u8f93\u51fa\u3002"
            "\u3010\u6ce8\u610f\u3011\u662f\u8fd9\u4e00\u53e5\u7684\u989d\u5916\u8981\u6c42\u3002"
            "\u53ea\u8f93\u51fa\u5f53\u524d\u53e5\u7684\u8bd1\u6587\uff0c\u4e0d\u8981\u89e3\u91ca\u3001\u6ce8\u91ca\u6216\u5176\u4ed6\u6587\u5b57\u3002"
        )
        if self.background.strip():
            system += "\n\n\u80cc\u666f\uff1a" + self.background.strip()
        if self.glossary.strip() and self.target_lang in (Target.ZH_CN, Target.ZH_TW):
            system += "\n\n\u672f\u8bed\uff08\u539f\u6587\u51fa\u73b0\u65f6\u5fc5\u987b\u8fd9\u6837\u8bd1\uff09\uff1a" + self.glossary.strip()
        return system

    def _messages(self, prompt: str, system_note: str = "") -> list[dict[str, str]]:
        system = self._system_message()
        if system_note:
            system += "\n\n" + system_note
        previous = [original.strip() for original, _translation in self.history if original.strip()]
        user = ""
        if previous:
            user = "\u3010\u524d\u6587\u3011\n" + "\n".join(previous) + "\n\n"
        user += "\u3010\u5f53\u524d\u53e5\u3011\n" + prompt
        if self.correction.strip():
            user += "\n\n\u3010\u6ce8\u610f\u3011" + self.correction.strip()
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    @staticmethod
    def _is_local_host(base_url: str) -> bool:
        from urllib.parse import urlparse
        hostname = (urlparse(base_url).hostname or "").lower()
        return hostname in ("localhost", "127.0.0.1", "::1")

    @staticmethod
    def _visible_text(raw: str) -> str:
        """Strip think channels and withhold a trailing partial marker from live captions."""
        openers = ("<think>", "<|channel>thought")
        closers = ("</think>", "<channel|>")
        visible: list[str] = []
        position = 0
        thinking = False
        while position < len(raw):
            markers = closers if thinking else openers
            found = [(raw.find(marker, position), marker) for marker in markers]
            found = [(at, marker) for at, marker in found if at >= 0]
            if found:
                at, marker = min(found, key=lambda item: item[0])
                if not thinking:
                    visible.append(raw[position:at])
                    thinking = True
                else:
                    thinking = False
                position = at + len(marker)
                continue
            if not thinking:
                tail = raw[position:]
                pending = max(
                    (n for marker in openers for n in range(1, min(len(marker), len(tail)) + 1)
                     if marker.startswith(tail[-n:])), default=0,
                )
                visible.append(tail[:-pending] if pending else tail)
            break
        return "".join(visible)

    @staticmethod
    def _set_read_timeout(response, seconds: float) -> None:
        """Update requests/urllib3's socket timeout once the first answer token arrives."""
        try:
            response.raw._fp.fp.raw._sock.settimeout(max(0.05, seconds))
        except (AttributeError, OSError, TypeError):
            pass

    def _request_stream(
        self, prompt: str, variant: Optional[str], on_partial: Optional[Callable[[str], None]],
        *, probe: bool = False,
    ) -> MtResult:
        import json
        import requests
        started = time.monotonic()
        # Preserve Ollama's model-load allowance; remote first-token and post-token limits are 5 s and 8 s.
        first_allowance = 120 if self._is_local_host(self.base_url) else 5
        system_note = ""
        extra: dict[str, Any] = {}
        if variant is not None:
            _name, extra, system_note = next(item for item in self.THINKING_OFF if item[0] == variant)
        messages = self._messages(prompt, system_note)
        self.last_messages = messages
        body = {
            "model": self.model, "messages": messages, "temperature": 0,
            "max_tokens": 160 if self.target_lang in (Target.ZH_CN, Target.ZH_TW) else 256,
            "stream": True,
        }
        body.update(extra)
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        raw = ""
        visible = ""
        first_token_at: Optional[float] = None
        saw_done = False
        finish_reason = None
        reasoning = False
        status = 0
        response = None
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}/chat/completions", headers=headers, json=body,
                timeout=(10, first_allowance), stream=True,
            )
            status = response.status_code
            # requests defaults charset-less SSE responses to ISO-8859-1; SSE payloads are UTF-8.
            response.encoding = "utf-8"
            with self._lock:
                self._active_response = response
                cancelled = self.cancel_flag
            if cancelled:
                response.close()
                return MtResult(text="", error="cancelled")
            if status != 200:
                return MtResult(text="", http_status=status, latency_ms=(time.monotonic() - started) * 1000,
                                error=self._http_error(status))
            for line in response.iter_lines(decode_unicode=True):
                now = time.monotonic()
                if first_token_at is not None and now - first_token_at > 8:
                    return MtResult(text=visible.strip(), http_status=status,
                                    latency_ms=(now - started) * 1000,
                                    error="\u7ffb\u8bd1\u670d\u52a1\u54cd\u5e94\u8d85\u65f6\uff0c\u6a21\u578b\u53ef\u80fd\u4ecd\u5728\u52a0\u8f7d\u6216\u5904\u7406\u957f\u6587\u672c\u3002\u8bf7\u68c0\u67e5\u6a21\u578b\u901f\u5ea6\u548c\u7cfb\u7edf\u8d44\u6e90\u540e\u91cd\u8bd5\u3002")
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    saw_done = True
                    break
                try:
                    event = json.loads(data)
                except (TypeError, ValueError):
                    return MtResult(text="", http_status=status, latency_ms=(time.monotonic() - started) * 1000,
                                    error="\u7ffb\u8bd1\u670d\u52a1\u8fd4\u56de\u4e86\u65e0\u6cd5\u8bc6\u522b\u7684\u5185\u5bb9\uff0c\u8bf7\u68c0\u67e5\u670d\u52a1\u5730\u5740\u548c\u6a21\u578b\u3002")
                if not isinstance(event, dict) or event.get("error") is not None:
                    return MtResult(text="", http_status=status, latency_ms=(time.monotonic() - started) * 1000,
                                    error="\u7ffb\u8bd1\u670d\u52a1\u8fd4\u56de\u4e86\u65e0\u6cd5\u8bc6\u522b\u7684\u5185\u5bb9\uff0c\u8bf7\u68c0\u67e5\u670d\u52a1\u5730\u5740\u548c\u6a21\u578b\u3002")
                choices = event.get("choices", [])
                if not isinstance(choices, list):
                    return MtResult(text="", http_status=status, latency_ms=(time.monotonic() - started) * 1000,
                                    error="\u7ffb\u8bd1\u670d\u52a1\u8fd4\u56de\u4e86\u65e0\u6cd5\u8bc6\u522b\u7684\u5185\u5bb9\uff0c\u8bf7\u68c0\u67e5\u670d\u52a1\u5730\u5740\u548c\u6a21\u578b\u3002")
                if choices:
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        return MtResult(text="", http_status=status, latency_ms=(time.monotonic() - started) * 1000,
                                        error="\u7ffb\u8bd1\u670d\u52a1\u8fd4\u56de\u4e86\u65e0\u6cd5\u8bc6\u522b\u7684\u5185\u5bb9\uff0c\u8bf7\u68c0\u67e5\u670d\u52a1\u5730\u5740\u548c\u6a21\u578b\u3002")
                    delta = choice.get("delta") or {}
                    if not isinstance(delta, dict):
                        return MtResult(text="", http_status=status, latency_ms=(time.monotonic() - started) * 1000,
                                        error="\u7ffb\u8bd1\u670d\u52a1\u8fd4\u56de\u4e86\u65e0\u6cd5\u8bc6\u522b\u7684\u5185\u5bb9\uff0c\u8bf7\u68c0\u67e5\u670d\u52a1\u5730\u5740\u548c\u6a21\u578b\u3002")
                    reasoning = reasoning or any(
                        isinstance(delta.get(key), str) and bool(delta[key])
                        for key in ("reasoning_content", "reasoning")
                    )
                    content = delta.get("content")
                    if content is not None and not isinstance(content, str):
                        return MtResult(text="", http_status=status, latency_ms=(time.monotonic() - started) * 1000,
                                        error="\u7ffb\u8bd1\u670d\u52a1\u8fd4\u56de\u4e86\u65e0\u6cd5\u8bc6\u522b\u7684\u5185\u5bb9\uff0c\u8bf7\u68c0\u67e5\u670d\u52a1\u5730\u5740\u548c\u6a21\u578b\u3002")
                    if content:
                        raw += content
                        reasoning = reasoning or "<think>" in raw or "<|channel>thought" in raw
                        updated = self._visible_text(raw)
                        if updated.strip() and first_token_at is None:
                            first_token_at = now
                            self._set_read_timeout(response, 8)
                        if updated != visible:
                            visible = updated
                            if on_partial and visible.strip():
                                on_partial(visible.strip())
                    finish_reason = choice.get("finish_reason") or finish_reason
                usage = event.get("usage")
                if isinstance(usage, dict):
                    details = usage.get("completion_tokens_details")
                    if isinstance(details, dict) and (details.get("reasoning_tokens") or 0) > 0:
                        reasoning = True
            if not saw_done or finish_reason not in ("stop", "length"):
                return MtResult(text="", http_status=status, latency_ms=(time.monotonic() - started) * 1000,
                                error="\u7ffb\u8bd1\u670d\u52a1\u8fd4\u56de\u4e86\u65e0\u6cd5\u8bc6\u522b\u7684\u5185\u5bb9\uff0c\u8bf7\u68c0\u67e5\u670d\u52a1\u5730\u5740\u548c\u6a21\u578b\u3002")
            if not first_token_at:
                error = "reasoning still enabled" if probe and reasoning else (
                    "\u7ffb\u8bd1\u670d\u52a1\u54cd\u5e94\u8d85\u65f6\uff0c\u6a21\u578b\u53ef\u80fd\u4ecd\u5728\u52a0\u8f7d\u6216\u5904\u7406\u957f\u6587\u672c\u3002\u8bf7\u68c0\u67e5\u6a21\u578b\u901f\u5ea6\u548c\u7cfb\u7edf\u8d44\u6e90\u540e\u91cd\u8bd5\u3002"
                )
                return MtResult(text="", http_status=status,
                                latency_ms=(time.monotonic() - started) * 1000, error=error)
            text = self._visible_text(raw).strip()
            error = ("reasoning still enabled" if probe and reasoning else
                     (None if text else ("\u6a21\u578b\u4e00\u76f4\u5728\u601d\u8003\uff0c\u6ca1\u6709\u7ed9\u51fa\u8bd1\u6587" if reasoning else "\u7ffb\u8bd1\u670d\u52a1\u8fd4\u56de\u4e86\u7a7a\u8bd1\u6587\u3002")))
            return MtResult(text=text, http_status=status, latency_ms=(time.monotonic() - started) * 1000, error=error)
        except requests.ConnectTimeout:
            return MtResult(text="", latency_ms=(time.monotonic() - started) * 1000,
                            error="\u8fde\u63a5\u7ffb\u8bd1\u670d\u52a1\u8d85\u65f6\uff0c\u8bf7\u786e\u8ba4\u670d\u52a1\u5df2\u542f\u52a8\u5e76\u68c0\u67e5\u670d\u52a1\u5730\u5740\u3002")
        except requests.ReadTimeout:
            return MtResult(text="", latency_ms=(time.monotonic() - started) * 1000,
                            error="\u7ffb\u8bd1\u670d\u52a1\u54cd\u5e94\u8d85\u65f6\uff0c\u6a21\u578b\u53ef\u80fd\u4ecd\u5728\u52a0\u8f7d\u6216\u5904\u7406\u957f\u6587\u672c\u3002\u8bf7\u68c0\u67e5\u6a21\u578b\u901f\u5ea6\u548c\u7cfb\u7edf\u8d44\u6e90\u540e\u91cd\u8bd5\u3002")
        except requests.ConnectionError:
            return MtResult(text="", latency_ms=(time.monotonic() - started) * 1000,
                            error="\u65e0\u6cd5\u8fde\u63a5\u7ffb\u8bd1\u670d\u52a1\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc\u548c\u670d\u52a1\u5730\u5740\u3002")
        except requests.RequestException as error:
            log.error("Translation request failed: %s", type(error).__name__)
            return MtResult(text="", latency_ms=(time.monotonic() - started) * 1000,
                            error="\u65e0\u6cd5\u8fde\u63a5\u7ffb\u8bd1\u670d\u52a1\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc\u548c\u670d\u52a1\u5730\u5740\u3002")
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            with self._lock:
                if self._active_response is response:
                    self._active_response = None

    @staticmethod
    def _http_error(status: int) -> str:
        if status in (401, 403):
            return "\u7ffb\u8bd1\u670d\u52a1\u62d2\u7edd\u8bbf\u95ee\uff0c\u8bf7\u68c0\u67e5 API Key \u548c\u670d\u52a1\u5730\u5740\u3002"
        if status == 404:
            return "\u7ffb\u8bd1\u670d\u52a1\u627e\u4e0d\u5230\u5730\u5740\u6216\u6a21\u578b\uff08HTTP 404\uff09\uff0c\u8bf7\u68c0\u67e5\u670d\u52a1\u8bbe\u7f6e\u3002"
        if status == 429:
            return "\u7ffb\u8bd1\u670d\u52a1\u6682\u65f6\u9650\u6d41\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u6216\u68c0\u67e5\u8d26\u6237\u989d\u5ea6\u3002"
        return f"\u7ffb\u8bd1\u670d\u52a1\u8fd4\u56de HTTP {status}\uff0c\u8bf7\u68c0\u67e5\u670d\u52a1\u8bbe\u7f6e\u540e\u91cd\u8bd5\u3002"

    def _translate_with_api(
        self, prompt: str, on_partial: Optional[Callable[[str], None]] = None,
    ) -> MtResult:
        cache_key = (self.base_url.rstrip("/"), self.model)
        with self._cache_lock:
            cached = cache_key in self._thinking_cache
            selected = self._thinking_cache.get(cache_key)
        if not cached:
            probe_results = []
            for name, _params, _note in self.THINKING_OFF:
                probe = self._request_stream("\u3053\u3093\u306b\u3061\u306f\u3001\u4eca\u65e5\u3082\u3088\u308d\u3057\u304f\u304a\u9858\u3044\u3057\u307e\u3059\u3002", name, None, probe=True)
                probe_results.append(probe)
                if probe.error is None and probe.text.strip():
                    selected = name
                    with self._cache_lock:
                        self._thinking_cache[cache_key] = selected
                    break
                if probe.http_status in (401, 403, 404, 429) or (probe.http_status == 0 and probe.error and "\u8d85\u65f6" not in probe.error):
                    return probe
                if probe.error and "\u8d85\u65f6" in probe.error:
                    return probe
            else:
                conclusive = all(
                    result.error == "reasoning still enabled" or result.http_status in (400, 422)
                    for result in probe_results
                )
                if (len(probe_results) == len(self.THINKING_OFF) and conclusive
                        and any(result.error == "reasoning still enabled" for result in probe_results)):
                    with self._cache_lock:
                        self._thinking_cache[cache_key] = None
                else:
                    return probe_results[-1] if probe_results else MtResult(
                        text="", error="\u7ffb\u8bd1\u670d\u52a1\u8fd4\u56de\u4e86\u65e0\u6cd5\u8bc6\u522b\u7684\u5185\u5bb9\uff0c\u8bf7\u68c0\u67e5\u670d\u52a1\u5730\u5740\u548c\u6a21\u578b\u3002",
                    )
        return self._request_stream(prompt, selected, on_partial)

    def cancel(self) -> None:
        """Cancel the active stream and future translation requests."""
        with self._lock:
            self.cancel_flag = True
            response = self._active_response
        if response is not None:
            response.close()

    @staticmethod
    def _map_language(target: Target) -> str:
        mapping = {
            Target.ZH_CN: "zh-CN", Target.ZH_TW: "zh-TW", Target.EN: "en",
            Target.JA: "ja", Target.KO: "ko",
        }
        return mapping.get(target, "zh-CN")


# ============================================================================
# Audio Source Implementation (system audio capture)
# ============================================================================

class MicrophoneAudioSource(AudioSource):
    """Capture local mono microphone audio in the pipeline's 16 kHz format."""

    @staticmethod
    def devices() -> Dict[str, Optional[int]]:
        import sounddevice as sd

        return {
            f"{index}: {device['name']}": index
            for index, device in enumerate(sd.query_devices())
            if device["max_input_channels"] > 0
        }

    def __init__(self, device: Optional[int] = None):
        import sounddevice as sd

        self.cancelled = threading.Event()
        self.frames = queue.Queue(maxsize=64)
        self._end_reason = None
        self.stream = None
        try:
            sd.check_input_settings(device=device, channels=1, dtype="float32", samplerate=16000)
            self.stream = sd.InputStream(
                device=device, channels=1, dtype="float32", samplerate=16000,
                blocksize=512, callback=self._capture,
            )
            self.stream.start()
        except Exception:
            if self.stream is not None:
                self.stream.close()
            raise

    def _capture(self, data, frames, timing, status) -> None:
        if self.cancelled.is_set():
            return
        if status:
            self._end_reason = "麦克风录音中断或溢出，请检查设备后重新开始。"
            log.error("Microphone capture status: %s", status)
            self.cancelled.set()
            return
        try:
            import time

            self.frames.put_nowait((data[:, 0].tolist(), round(time.time() * 1000)))
        except queue.Full:
            self._end_reason = "麦克风音频处理队列已满，请停止后重新开始。"
            log.error("Microphone capture queue full")
            self.cancelled.set()

    def read(self, frame: List[float]) -> int:
        import time

        while not self.cancelled.is_set():
            try:
                samples, received_at_ms = self.frames.get(timeout=0.1)
            except queue.Empty:
                if self.stream is not None and not self.stream.active:
                    self._end_reason = "麦克风已断开，请检查设备后重新开始。"
                    log.error("Microphone stream stopped unexpectedly")
                    return -1
                continue
            if len(samples) != len(frame):
                self._end_reason = "麦克风音频帧大小不匹配，请重新开始。"
                log.error("Microphone frame size mismatch: %s versus %s", len(samples), len(frame))
                return -1
            frame[:] = samples
            self.received_at_ms = received_at_ms
            return int(time.time() * 1000)
        return -1

    @property
    def estimated(self) -> bool:
        return True

    def end_reason(self) -> Optional[str]:
        return self._end_reason

    def close(self) -> None:
        self.cancelled.set()
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.abort()
            finally:
                stream.close()

    def cancel(self) -> None:
        self.close()


class SystemAudioSource(AudioSource):
    """Capture system audio output (local listening preserved)."""
    
    def __init__(self, platform: str = "windows"):
        self.platform = platform
        self.process = None
        self.running = False
        self.cancelled = False
        self._end_reason = None
    
    def read(self, frame: List[float]) -> int:
        """Read audio frame."""
        if self.cancelled:
            return -1
        
        try:
            import subprocess
            
            # FFmpeg command to capture system audio
            cmd = self._build_ffmpeg_command()
            
            if not self.process:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=4096,
                    creationflags=_NO_CONSOLE_WINDOW,
                )
            
            # Read audio data
            frame_bytes = len(frame) * 2  # 16-bit samples
            data = self.process.stdout.read(frame_bytes)
            
            if not data:
                self._end_reason = "Audio stream ended"
                return -1
            
            # Convert bytes to floats
            import struct
            samples = struct.unpack(f"{len(data)//2}h", data)
            for i, s in enumerate(samples[:len(frame)]):
                frame[i] = s / 32768.0
            
            import time
            return int(time.time() * 1000)
        
        except Exception as e:
            log.error(f"Audio read error: {e}")
            self._end_reason = str(e)
            return -1
    
    @property
    def estimated(self) -> bool:
        """Timestamp is estimated (not HAL capture time)."""
        return True
    
    def end_reason(self) -> Optional[str]:
        """Why audio ended."""
        return self._end_reason
    
    def close(self) -> None:
        """Release resources."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                self.process.kill()
            self.process = None
        self.running = False
    
    def cancel(self) -> None:
        """Stop audio capture."""
        self.cancelled = True
        self.close()
    
    def _build_ffmpeg_command(self) -> List[str]:
        """Build FFmpeg command for system audio."""
        if self.platform == "windows":
            return [
                "ffmpeg",
                "-f", "dshow",
                "-i", "audio=\"Stereo Mix\"",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                "-f", "s16",
                "-bufsize", "32k",
                "pipe:1",
            ]
        elif self.platform == "macos":
            return [
                "ffmpeg",
                "-f", "avfoundation",
                "-i", ":0",  # Default audio device
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                "-f", "s16",
                "-bufsize", "32k",
                "pipe:1",
            ]
        else:  # Linux
            return [
                "ffmpeg",
                "-f", "pulse",
                "-i", "default",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                "-f", "s16",
                "-bufsize", "32k",
                "pipe:1",
            ]


class StreamAudioSource(AudioSource):
    """Capture audio from YouTube, Bilibili, or Missevan streams."""
    
    def __init__(self, stream_url: str, platform: str):
        self.stream_url = stream_url
        self.platform = platform
        self.process = None
        self.cancelled = False
        self._end_reason = None
    
    def read(self, frame: List[float]) -> int:
        """Read audio from stream."""
        if self.cancelled:
            return -1
        
        import struct
        import time

        max_retries = 3
        for attempt in range(max_retries + 1):
            if self.cancelled:
                return -1
            try:
                if not self.process:
                    self._start_process()

                data = self.process.stdout.read(len(frame) * 2)
                if data:
                    samples = struct.unpack(f"{len(data)//2}h", data)
                    for i, sample in enumerate(samples[:len(frame)]):
                        frame[i] = sample / 32768.0
                    for i in range(len(samples), len(frame)):
                        frame[i] = 0.0
                    self._end_reason = None
                    self.received_at_ms = int(time.time() * 1000)
                    return self.received_at_ms

                return_code = self.process.poll()
                self._end_reason = (
                    f"Stream decoder exited with code {return_code}"
                    if return_code is not None
                    else "Stream ended"
                )
                self.close()
            except Exception as e:
                self._end_reason = f"Stream audio error: {e}"
                self.close()

            if attempt < max_retries and not self.cancelled:
                log.warning(
                    "Stream interrupted; reconnecting (%d/%d)",
                    attempt + 1,
                    max_retries,
                )
                time.sleep(min(2 ** attempt, 5))

        log.error("Stream audio stopped: %s", self._end_reason)
        return -1
    
    @property
    def estimated(self) -> bool:
        return True
    
    def end_reason(self) -> Optional[str]:
        return self._end_reason
    
    def close(self) -> None:
        import subprocess

        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            if self.process.stdout:
                self.process.stdout.close()
            self.process = None
    
    def cancel(self) -> None:
        self.cancelled = True
        self.close()

    def _start_process(self) -> None:
        import subprocess
        if self.platform == "missevan":
            from .platforms import missevan_room_id
            from .streaming_bridge import resolve_missevan_audio
            audio_url = resolve_missevan_audio(missevan_room_id(self.stream_url))
        else:
            from yt_dlp import YoutubeDL
            with YoutubeDL({
                "quiet": True,
                "no_warnings": True,
                "format": "bestaudio/best" if self.platform == "youtube" else "best[protocol=https]/best",
                "noplaylist": True,
            }) as ydl:
                stream_info = ydl.extract_info(self.stream_url, download=False)
            audio_url = stream_info["url"]

        cmd = [
            "ffmpeg",
            "-nostdin",
            "-loglevel", "error",
            "-i", audio_url,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-f", "s16le",
            "-bufsize", "32k",
            "pipe:1",
        ]
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=4096,
            creationflags=_NO_CONSOLE_WINDOW,
        )


# ============================================================================
# Speech Models Implementation
# ============================================================================

class StreamingSpeechModels(SpeechModels):
    """Speech recognition and VAD models."""
    
    def __init__(self, model_size: str = "base", language: Optional[str] = None, asr: Optional[Asr] = None):
        self._asr = asr or StreamingProjectAsr(model_size, language)
        self._vad_model = None
        self._load_vad()
    
    def _load_vad(self) -> None:
        """Load Silero VAD model."""
        try:
            import silero_vad
            self._vad_model = silero_vad.load_silero_vad()
            log.info("Silero VAD loaded")
        except ImportError:
            log.warning("silero_vad not available, VAD will be basic")
        except Exception as e:
            log.warning(f"Failed to load VAD: {e}")
    
    @property
    def asr(self) -> Asr:
        return self._asr
    
    def vad_prob(self, frame: List[float]) -> float:
        """Voice activity detection probability."""
        if not self._vad_model:
            if not frame:
                return 0.0
            rms = (sum(sample * sample for sample in frame) / len(frame)) ** 0.5
            return min(1.0, rms / 0.025)
        
        try:
            import torch
            import numpy as np
            
            audio = np.array(frame, dtype=np.float32)
            prob = self._vad_model(torch.from_numpy(audio), sr=16000)
            return float(prob)
        
        except Exception as e:
            log.warning(f"VAD error: {e}")
            return 0.5
    
    def release(self) -> None:
        """Release models."""
        self._asr = None
        self._vad_model = None


# ============================================================================
# Chat Sender Implementations
# ============================================================================

from .chat_delivery import MultipartSender


class YouTubeChatSender(MultipartSender, ChatSender):
    """Send messages to YouTube live chat."""
    
    def __init__(
        self,
        video_id: str,
        cookies: Optional[Dict[str, str]] = None,
        status_callback: Optional[Callable[[bool, str], None]] = None,
        page_id: str = "",
    ):
        self.video_id = video_id
        self.cookies = dict(cookies or {})
        self.status_callback = status_callback
        self.page_id = page_id
        self._init_delivery("youtube")
    
    def _send_one(self, message: str, original: Optional[str] = None) -> Tuple[bool, str]:
        """Send message."""
        try:
            from .streaming_bridge import send_youtube_message

            result = send_youtube_message(self.video_id, message, self.cookies, self.page_id)
            self._report(*result)
            return result
        
        except Exception as e:
            log.error("YouTube send failed: %s", type(e).__name__)
            result = (False, "发送失败，请检查 YouTube 登录状态和直播间权限。")
            self._report(*result)
            return result
    
    def can_send(self) -> bool:
        return bool(
            self.cookies.get("SAPISID") or self.cookies.get("__Secure-3PAPISID")
        )

    def _report(self, success: bool, message: str) -> None:
        if self.status_callback:
            self.status_callback(success, message)


class BilibiliChatSender(MultipartSender, ChatSender):
    """Send messages to Bilibili live chat."""
    
    def __init__(
        self,
        room_id: str,
        cookies: Optional[Dict[str, str]] = None,
        status_callback: Optional[Callable[[bool, str], None]] = None,
    ):
        self.room_id = room_id
        self.cookies = dict(cookies or {})
        self.status_callback = status_callback
        self._init_delivery("bilibili")
    
    def _send_one(self, message: str, original: Optional[str] = None) -> Tuple[bool, str]:
        """Send message."""
        try:
            from .streaming_bridge import send_bilibili_danmaku

            result = send_bilibili_danmaku(self.room_id, message, self.cookies)
            self._report(*result)
            return result
        
        except Exception as e:
            log.error("Bilibili send failed: %s", type(e).__name__)
            result = (
                False,
                "发送失败，请检查 Bilibili 登录状态、直播间权限和弹幕频率。",
            )
            self._report(*result)
            return result
    
    def can_send(self) -> bool:
        return bool(self.cookies.get("SESSDATA") and self.cookies.get("bili_jct"))

    def _report(self, success: bool, message: str) -> None:
        if self.status_callback:
            self.status_callback(success, message)


class MissevanChatSender(MultipartSender, ChatSender):
    """Send messages to Missevan live chat."""
    
    def __init__(
        self, room_id: str, cookies: Optional[Dict[str, str]] = None,
        status_callback: Optional[Callable[[bool, str], None]] = None,
    ):
        self.room_id = room_id
        self.cookies = dict(cookies or {})
        self.status_callback = status_callback
        self._init_delivery("missevan")
    
    def _send_one(self, message: str, original: Optional[str] = None) -> Tuple[bool, str]:
        """Send message."""
        try:
            from .streaming_bridge import send_missevan_message
            result = send_missevan_message(self.room_id, message, self.cookies)
        
        except Exception as e:
            log.error("Missevan send failed: %s", type(e).__name__)
            result = (False, "MissEvan 发送失败，请检查登录状态和直播间权限。")
        if self.status_callback:
            self.status_callback(*result)
        return result
    
    def can_send(self) -> bool:
        return bool(self.cookies)
