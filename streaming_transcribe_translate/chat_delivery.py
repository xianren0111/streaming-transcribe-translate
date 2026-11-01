"""Shared chat templates and serialized, resumable multipart delivery."""

from __future__ import annotations

import logging
import string
import threading
import time
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .simul_interfaces import ChatSender
    from .subtitle_records import CaptionRecord, SessionRecords

log = logging.getLogger(__name__)
LANGUAGE_NAMES = {"zh-CN": "简体中文", "zh-TW": "繁體中文", "en": "英语", "ja": "日语", "ko": "韩语"}
DEFAULT_CHAT_TEMPLATES = {
    "zh": "【{translation}】", "en": "[{translation}]",
    "ja": "「{translation}」", "ko": "[{translation}]",
}
# Conservative application defaults; room/account restrictions may be stricter.
CHAT_LIMITS = {"bilibili": (20, 2.0), "youtube": (200, 2.0), "missevan": (100, 2.0)}


def validate_template(template: str) -> None:
    if not isinstance(template, str) or not template.strip():
        raise ValueError("发送模板不能为空。")
    fields = []
    try:
        for _, name, spec, conversion in string.Formatter().parse(template):
            if name is not None:
                if name not in ("translation", "original", "language") or spec or conversion:
                    raise ValueError("模板仅支持 {translation}、{original}、{language}。")
                fields.append(name)
    except ValueError as error:
        raise ValueError("模板格式不正确，仅支持 {translation}、{original}、{language}。") from error
    if fields.count("translation") != 1:
        raise ValueError("模板必须包含一次 {translation}。")


def format_chat(template: str, translation: str, original: str, language: str) -> str:
    validate_template(template)
    return template.format(
        translation=translation, original=original, language=LANGUAGE_NAMES.get(language, language),
    )


def split_message(message: str, limit: int) -> list[str]:
    """Count UTF-16 units conservatively, never splitting a Unicode code point."""
    if type(limit) is not int or limit < 2:
        raise ValueError("聊天长度限制必须至少为 2。")
    parts, current, units = [], "", 0
    for character in message:
        size = 2 if ord(character) > 0xFFFF else 1
        if units + size > limit:
            parts.append(current)
            current, units = "", 0
        current += character
        units += size
    if current:
        parts.append(current)
    return parts


@dataclass
class DeliveryProgress:
    message: str
    parts: list[str]
    completed: int = 0


class MultipartSender:
    def _init_delivery(self, platform: str) -> None:
        self.chat_platform = platform
        self.max_message_length, self.send_interval = CHAT_LIMITS[platform]
        self._delivery_lock = threading.Lock()
        self._delivery_progress: DeliveryProgress | None = None
        self._next_send_at = 0.0

    def send(self, message: str, original: str | None = None) -> tuple[bool, str]:
        return self.send_with_updates(message, original)

    def send_with_updates(
        self, message: str, original: str | None = None,
        on_sent: Callable[[str], None] | None = None,
    ) -> tuple[bool, str]:
        with self._delivery_lock:
            progress = self._delivery_progress
            if progress is not None and progress.message != message:
                return False, "上一条消息已部分发送；请先用原内容重试，避免重复发送。"
            if progress is None:
                if not message.strip():
                    return False, "请输入要发送的文字，或点击「跳过」。"
                progress = DeliveryProgress(message, split_message(message, self.max_message_length))
                self._delivery_progress = progress
            while progress.completed < len(progress.parts):
                delay = self._next_send_at - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                part = progress.parts[progress.completed]
                self._next_send_at = time.monotonic() + self.send_interval
                success, detail = self._send_one(part, original)
                if not success:
                    if not progress.completed:
                        self._delivery_progress = None
                    if len(progress.parts) == 1:
                        return False, detail
                    return False, f"已发送 {progress.completed}/{len(progress.parts)} 条；{detail}"
                progress.completed += 1
                if on_sent:
                    on_sent(part)
            self._delivery_progress = None
            return (True, detail) if len(progress.parts) == 1 else (True, f"发送成功 · {len(progress.parts)} 条")

    def _send_one(self, message: str, original: str | None = None) -> tuple[bool, str]:
        raise NotImplementedError

    def abandon_partial(self) -> None:
        with self._delivery_lock:
            if self._delivery_progress and self._delivery_progress.completed:
                log.warning("Remaining chat parts explicitly skipped after partial delivery")
            self._delivery_progress = None


def send_recorded(
    sender: ChatSender, message: str, original: str | None,
    store: SessionRecords | None = None, record: CaptionRecord | None = None,
) -> tuple[bool, str]:
    """Record each acknowledged part; never retry a network send due to disk failure."""
    if record is not None and store is None:
        log.error("Chat delivery blocked: recording session is missing")
        return False, "字幕记录会话丢失，未发送消息；请重新开始字幕。"
    failures: list[OSError | ValueError] = []

    def acknowledged(part: str) -> None:
        if store is not None and record is not None:
            try:
                store.success(record, part, round(time.time() * 1000), save_review=False)
            except (OSError, ValueError) as error:
                log.error("Acknowledged chat part record failed: %s", type(error).__name__)
                failures.append(error)

    method = getattr(type(sender), "send_with_updates", None)
    if callable(method):
        result = sender.send_with_updates(message, original, acknowledged)
    else:
        result = sender.send(message) if original is None else sender.send(message, original)
        if result[0]:
            acknowledged(message)
    if result[0] and store is not None and record is not None:
        try:
            store.complete_send(record, message, round(time.time() * 1000))
        except (OSError, ValueError) as error:
            log.error("Reviewed chat record failed: %s", type(error).__name__)
            failures.append(error)
    if failures:
        return result[0], "消息已发送，但本地记录保存失败；不要再次发送，请检查磁盘空间。"
    return result
