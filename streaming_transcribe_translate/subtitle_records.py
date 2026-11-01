"""Local caption and successful-send records, aligned to a recording clock."""

from __future__ import annotations

import csv
import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path


def clock_text(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).astimezone().isoformat(timespec="milliseconds")


def recording_clock(text: str) -> int:
    text = text.strip()
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?",
        text,
    ):
        raise ValueError("请输入录像开始日期和时间，例如 2026-10-31 23:00:00。")
    try:
        value = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError("请输入录像开始日期和时间，例如 2026-10-31 23:00:00。") from error
    if value.year < 2000:
        raise ValueError("录像开始时间必须包含完整日期。")
    return round(value.timestamp() * 1000)


def srt_clock(milliseconds: int) -> str:
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


@dataclass(frozen=True)
class CaptionRecord:
    session_id: str
    segment_id: int
    received_at_ms: int
    audio_end_at_ms: int
    audio_duration_ms: int
    original: str
    translated: str
    platform: str
    room: str
    audio_source: str
    target_language: str = ""
    speaker_id: int | None = None


@dataclass(frozen=True)
class SentMessage:
    caption: CaptionRecord
    message: str
    sent_at_ms: int


@dataclass(frozen=True)
class ReviewedCaption:
    caption: CaptionRecord
    message: str
    reviewed_at_ms: int
    action: str


class SessionRecords:
    def __init__(
        self, root: Path, save_captions: bool = True, diagnostics: bool = False,
        platform: str = "", room: str = "", audio_source: str = "", enabled: bool = True,
        started_at_ms: int | None = None,
    ):
        self.started_at_ms = round(time.time() * 1000) if started_at_ms is None else started_at_ms
        if type(self.started_at_ms) is not int or self.started_at_ms <= 0:
            raise ValueError("字幕会话开始时间无效。")
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self.directory = root / self.session_id
        # When disabled, records stay in memory only (chat review still needs them).
        self.enabled = enabled
        self.save_captions = save_captions
        self.diagnostics = diagnostics
        self.platform, self.room, self.audio_source = platform, room, audio_source
        self.captions: list[CaptionRecord] = []
        self.sent: list[SentMessage] = []
        self.reviewed: list[ReviewedCaption] = []
        self._lock = threading.RLock()
        self._final_ids: set[tuple[int, str]] = set()
        self._reviewed_ids: set[tuple[int, str]] = set()
        self._metadata_saved = False

    def _append(self, name: str, value: dict) -> None:
        if not self.enabled:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self._metadata_saved:
            (self.directory / "session.json").write_text(
                json.dumps({"started_at_ms": self.started_at_ms}), encoding="utf-8",
            )
            self._metadata_saved = True
        with (self.directory / name).open("a", encoding="utf-8") as output:
            output.write(json.dumps(value, ensure_ascii=False) + "\n")

    def event(self, kind: str, **data) -> None:
        if self.enabled and self.diagnostics:
            # Callers pass selected text/timing fields, never headers or credentials.
            with self._lock:
                self._append("diagnostics.jsonl", {
                    "at": clock_text(round(time.time() * 1000)), "event": kind, **data,
                })

    def caption(
        self, segment_id: int, received_at_ms: int, audio_end_at_ms: int,
        audio_duration_ms: int, original: str, translated: str,
        target_language: str = "",
        speaker_id: int | None = None,
    ) -> CaptionRecord:
        if received_at_ms <= 0 or audio_end_at_ms < received_at_ms:
            raise ValueError("音频接收时间无效，不能生成剪辑记录。")
        record = CaptionRecord(
            self.session_id, segment_id, received_at_ms, audio_end_at_ms,
            audio_duration_ms, original, translated, self.platform, self.room, self.audio_source, target_language, speaker_id,
        )
        with self._lock:
            key = (segment_id, target_language)
            if key not in self._final_ids:
                self.captions.append(record)
                self._final_ids.add(key)
        return record

    def _save_review(self, caption: CaptionRecord, message: str, action: str, reviewed_at_ms: int) -> None:
        if caption.session_id != self.session_id:
            raise ValueError("发送记录属于不同的字幕会话。")
        key = (caption.segment_id, caption.target_language)
        if key in self._reviewed_ids:
            return
        if self.enabled and self.save_captions:
            self._append("captions.jsonl", {
                **asdict(replace(caption, translated=message)),
                "ai_translation": caption.translated,
                "action": action, "reviewed_at_ms": reviewed_at_ms,
            })
            with (self.directory / "captions.txt").open("a", encoding="utf-8") as output:
                output.write(
                    f"[{clock_text(caption.received_at_ms)}] [{action}]"
                    f"{' [Speaker ' + str(caption.speaker_id) + ']' if caption.speaker_id else ''}"
                    f"\n{caption.original}\n{message}\n\n"
                )
        self._reviewed_ids.add(key)
        self.reviewed.append(ReviewedCaption(caption, message, reviewed_at_ms, action))

    def skip(self, caption: CaptionRecord, message: str, reviewed_at_ms: int) -> None:
        with self._lock:
            self._save_review(caption, message, "skipped", reviewed_at_ms)

    def success(self, caption: CaptionRecord, message: str, sent_at_ms: int, *, save_review: bool = True) -> None:
        if caption.session_id != self.session_id:
            raise ValueError("发送记录属于不同的字幕会话。")
        entry = SentMessage(caption, message, sent_at_ms)
        with self._lock:
            self.sent.append(entry)
            self._append("sent_messages.jsonl", {
                **asdict(caption), "message": message, "sent_at_ms": sent_at_ms,
            })
            if save_review:
                self._save_review(caption, message, "sent", sent_at_ms)

    def complete_send(self, caption: CaptionRecord, message: str, sent_at_ms: int) -> None:
        with self._lock:
            self._save_review(caption, message, "sent", sent_at_ms)

    def export(
        self, directory: Path, recording_start_ms: int | None = None, *, include_skipped: bool = False,
    ) -> tuple[Path, Path]:
        if recording_start_ms is None:
            recording_start_ms = self.started_at_ms
        with self._lock:
            entries = [
                ReviewedCaption(item.caption, item.message, item.sent_at_ms, "sent")
                for item in self.sent
            ]
            if include_skipped:
                entries.extend(item for item in self.reviewed if item.action == "skipped")
            sent = sorted(entries, key=lambda item: (
                item.caption.received_at_ms, item.caption.segment_id, item.reviewed_at_ms
            ))
        if not sent:
            if include_skipped:
                raise ValueError("还没有已发送或已跳过的字幕，不能导出。")
            raise ValueError("还没有成功发送的消息，不能导出已发送字幕。")
        directory.mkdir(parents=True, exist_ok=True)
        suffix = "reviewed" if include_skipped else "sent"
        csv_path = directory / f"{self.session_id}-{suffix}.csv"
        srt_path = directory / f"{self.session_id}-{suffix}.srt"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            columns = [
                "session_id", "segment_id", "audio_received_clock", "audio_received_epoch_ms",
                "audio_end_clock", "sent_clock", "recording_offset_ms", "original",
                "translated", "actual_sent_message", "platform", "room", "audio_source",
            ]
            if include_skipped:
                columns.extend(["action", "reviewed_clock", "actual_reviewed_text", "target_language"])
            if any(item.caption.speaker_id is not None for item in sent):
                columns.append("speaker_id")
            writer.writerow(columns)
            for item in sent:
                caption = item.caption
                row = [
                    caption.session_id, caption.segment_id, clock_text(caption.received_at_ms),
                    caption.received_at_ms, clock_text(caption.audio_end_at_ms),
                    clock_text(item.reviewed_at_ms) if item.action == "sent" else "",
                    caption.received_at_ms - recording_start_ms,
                    caption.original, caption.translated, item.message if item.action == "sent" else "",
                    caption.platform, caption.room, caption.audio_source,
                ]
                if include_skipped:
                    row.extend([item.action, clock_text(item.reviewed_at_ms), item.message, caption.target_language])
                if "speaker_id" in columns:
                    row.append(caption.speaker_id if caption.speaker_id is not None else "")
                writer.writerow(row)
        cues = []
        for item in sent:
            caption = item.caption
            start = caption.received_at_ms - recording_start_ms
            end = max(
                caption.audio_end_at_ms - recording_start_ms,
                start + max(1, caption.audio_duration_ms),
            )
            if end <= 0:
                continue
            text = (f"[Speaker {caption.speaker_id}] " if caption.speaker_id else "") + item.message
            cues.append((max(0, start), end, text))
        if not cues:
            if include_skipped:
                raise ValueError("字幕都在会话开始之前；CSV 已导出，请检查会话时间。")
            raise ValueError("已发送消息都在录像开始之前；CSV 已导出，请检查录像开始时间后重试 SRT。")
        # Simultaneous/repeated sends become one cue; clip overlaps to the next cue.
        grouped: list[tuple[int, int, str]] = []
        for start, end, text in cues:
            if grouped and grouped[-1][0] == start:
                previous = grouped.pop()
                grouped.append((start, max(end, previous[1]), previous[2] + "\n" + text))
            else:
                grouped.append((start, end, text))
        with srt_path.open("w", encoding="utf-8") as output:
            for index, (start, end, text) in enumerate(grouped):
                if index + 1 < len(grouped):
                    end = min(end, grouped[index + 1][0])
                clean = "\n".join(line for line in text.replace("\r", "").splitlines() if line.strip())
                output.write(
                    f"{index + 1}\n{srt_clock(start)} --> {srt_clock(max(start + 1, end))}\n{clean}\n\n"
                )
        return srt_path, csv_path

    @classmethod
    def restore(cls, directory: Path) -> SessionRecords:
        store = cls(directory.parent)
        store.directory = directory
        store.session_id = directory.name
        metadata = directory / "session.json"
        if metadata.exists():
            data = json.loads(metadata.read_text(encoding="utf-8"))
            timestamp = data["started_at_ms"]
            if type(timestamp) is not int or timestamp <= 0:
                raise ValueError("字幕会话开始时间无效。")
            store.started_at_ms = timestamp
        else:
            # Legacy session names contain their creation time in local time.
            store.started_at_ms = round(datetime.strptime(directory.name[:15], "%Y%m%d-%H%M%S").timestamp() * 1000)
        store._metadata_saved = True
        path = directory / "sent_messages.jsonl"
        reviews = directory / "captions.jsonl"
        if not path.is_file() and not reviews.is_file():
            raise ValueError("没有可导出的字幕记录。")
        if path.is_file():
            with path.open(encoding="utf-8") as source:
                for line in source:
                    data = json.loads(line)
                    message, sent_at_ms = data.pop("message"), data.pop("sent_at_ms")
                    caption = CaptionRecord(**data)
                    if caption.session_id != store.session_id:
                        raise ValueError("记录文件的会话编号不匹配。")
                    store.sent.append(SentMessage(caption, message, sent_at_ms))
        if reviews.is_file():
            with reviews.open(encoding="utf-8") as source:
                for line in source:
                    data = json.loads(line)
                    action = data.pop("action", None)
                    if action is None:
                        # Legacy captions were saved before review, not on Send/Skip.
                        continue
                    if action not in ("sent", "skipped"):
                        raise ValueError("字幕记录的审核状态无效。")
                    reviewed_at_ms = data.pop("reviewed_at_ms")
                    message = data["translated"]
                    data["translated"] = data.pop("ai_translation")
                    caption = CaptionRecord(**data)
                    if caption.session_id != store.session_id:
                        raise ValueError("记录文件的会话编号不匹配。")
                    store.reviewed.append(ReviewedCaption(caption, message, reviewed_at_ms, action))
        return store
