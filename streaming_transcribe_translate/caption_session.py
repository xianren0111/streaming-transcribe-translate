"""
Caption Session - Main orchestrator.

Similar to simul-subtitle's CaptionSession - coordinates audio capture,
transcription, translation, and UI updates in a multi-threaded pipeline.

MIT License (inherited from Simul Subtitle)
Copyright (c) 2026 KorenKrita and Contributors
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from collections import deque
import re
import unicodedata
from copy import deepcopy
from typing import Optional, List, Dict, Any

from .simul_interfaces import (
    SessionHost, Caption, Timing, Setup, AudioSource, SpeechModels, Mt,
    Platform, Target, ChatSender, CaptionBoard, MtResult,
)

log = logging.getLogger(__name__)
SAMPLE_RATE = 16000
FRAME_SIZE = 512
from .subtitle_decisions import DecisionsClient
from .subtitle_records import CaptionRecord, SessionRecords
from .subtitle_settings import SubtitleSettings
from .chat_delivery import format_chat, send_recorded


def remove_repeated_text(text: str) -> str:
    words = text.split()
    for length in range(len(words) // 2, 0, -1):
        for start in range(len(words) - 2 * length + 1):
            if words[start:start + length] == words[start + length:start + 2 * length]:
                return " ".join(words[:start + length] + words[start + 2 * length:])
    return re.sub(r"(.{4,}?[。！？!?])\s*\1", r"\1", text)


_SOUND_ONLY = re.compile(
    r"(?:哈{2,}|呵{2,}|嘿{2,}|嘻{2,}|呜{2,}|哇{2,}|喵+|汪+|咩+|嘎{2,}|"
    r"砰+|嘭+|咚+|叮咚|滴答|噼里啪啦|"
    r"あ?は{2,}|ふ{2,}|へ{2,}|ひ{2,}|にゃ[ーん]*|わん|"
    r"どきどき|わくわく|ぱちぱち|ごろごろ|どん|ばん|"
    r"ふん|うん|あっ|えっ|"
    r"(?:ha){2,}|(?:he){2,}|(?:hi){2,}|(?:ho){2,}|"
    r"meow|woof|bowwow|moo|baa|oink|quack|bang|boom|"
    r"\u110f{2,}|\u1112{2,}|하{2,}|히{2,}|야옹|멍멍)+"
)


def is_sound_only(text: str) -> bool:
    """Match known sounds only; preserve unknown or mixed utterances."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = "".join(
        chr(ord(char) - 0x60) if "\u30a1" <= char <= "\u30f6" else char
        for char in normalized
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )
    return bool(normalized) and _SOUND_ONLY.fullmatch(normalized) is not None


class Segmenter:
    """Emit bounded utterances and periodic drafts from 32 ms VAD frames."""
    threshold = 0.5
    silence_ms = 400
    draft_every_ms = 700
    min_draft_ms = 600
    max_utterance_ms = 7000
    pre_roll_ms = 200
    min_final_ms = 400
    max_hold_silence_ms = 1500
    decision_wait_ms = 1000
    ask_silence_ms = 220
    early_cut_after_ms = 3000
    early_cut_silence_ms = 192

    def __init__(self, vad_models: SpeechModels, hold_hint=None, reset_hint=None,
                 max_utterance_ms: Optional[int] = None):
        self.vad_models = vad_models
        self.max_utterance_ms = max_utterance_ms or type(self).max_utterance_ms
        self.buffered_samples: List[float] = []
        self.pre_roll = deque(maxlen=self.pre_roll_ms // 32)
        self.pre_roll_times = deque(maxlen=self.pre_roll_ms // 32)
        self.frames: list[tuple[list[float], bool, int]] = []
        self.silent_samples = 0
        self.speech_samples = 0
        self.samples_since_draft = 0
        self.segment_id = 0
        self.hold_hint = hold_hint
        self.reset_hint = reset_hint
        self.decision_generation = 0
        self.pause_candidate = False
        self.candidate_samples_at = 0
        self.forced_candidate = False
        self.held_cut_index = 0
        self.received_at_ms = 0
        self.emitted_times: dict[int, tuple[int, int]] = {}
        self.candidate_ids: set[int] = set()

    def process_frame(self, samples: List[float], timestamp_ms: int) -> List[tuple]:
        """Count audio samples, not decoder read times, to measure pauses."""
        speech = self.vad_models.vad_prob(samples) >= self.threshold
        if not self.buffered_samples and not speech:
            self.pre_roll.append(list(samples))
            self.pre_roll_times.append(timestamp_ms)
            return []
        if not self.buffered_samples:
            self.received_at_ms = self.pre_roll_times[0] if self.pre_roll_times else timestamp_ms
            for prior, _at in zip(self.pre_roll, self.pre_roll_times):
                self.buffered_samples.extend(prior)
                self.frames.append((prior, False, _at))
            self.pre_roll.clear()
            self.pre_roll_times.clear()

        self.buffered_samples.extend(samples)
        self.frames.append((list(samples), speech, timestamp_ms))
        self.samples_since_draft += len(samples)
        if speech:
            self.speech_samples += len(samples)
            self.silent_samples = 0
        else:
            self.silent_samples += len(samples)

        duration_ms = len(self.buffered_samples) * 1000 // SAMPLE_RATE
        silence_ms = self.silent_samples * 1000 // SAMPLE_RATE
        speech_ms = self.speech_samples * 1000 // SAMPLE_RATE
        if speech and self.pause_candidate and not self.forced_candidate:
            self.pause_candidate = False
            self.candidate_ids.discard(self.segment_id)

        if self.hold_hint is not None and not self.pause_candidate and (
            (silence_ms >= self.ask_silence_ms and speech_ms >= self.min_final_ms)
            or duration_ms >= 5000
        ):
            self.pause_candidate = True
            self.forced_candidate = duration_ms >= 5000 and silence_ms < self.ask_silence_ms
            if self.forced_candidate and duration_ms >= self.max_utterance_ms:
                self.held_cut_index = self._forced_cut_index()
            self.candidate_samples_at = len(self.buffered_samples)
            if self.reset_hint:
                self.decision_generation = self.reset_hint(self.segment_id)
            self.candidate_ids.add(self.segment_id)
            self.emitted_times[self.segment_id] = (self.received_at_ms, timestamp_ms)
            return [(self.segment_id, self.buffered_samples.copy(), False)]

        hint = self.hold_hint(self.segment_id) if self.hold_hint is not None and self.pause_candidate else None
        decision_wait = (len(self.buffered_samples) - self.candidate_samples_at) * 1000 // SAMPLE_RATE
        if silence_ms >= self.silence_ms:
            if speech_ms < self.min_final_ms and silence_ms < self.max_hold_silence_ms:
                pass
            elif self.pause_candidate and hint is True and silence_ms < self.max_hold_silence_ms:
                pass
            elif self.pause_candidate and hint is None and decision_wait < self.decision_wait_ms:
                pass
            else:
                return [self._finalize(timestamp_ms)]

        if self.forced_candidate and duration_ms >= self.max_utterance_ms and not self.held_cut_index:
            self.held_cut_index = self._forced_cut_index()
        forced_due = duration_ms >= self.max_utterance_ms
        if forced_due and self.forced_candidate and hint is None and decision_wait < self.decision_wait_ms:
            forced_due = False
        hard_limit = self.max_utterance_ms * (2 if self.forced_candidate and hint is True else 1)
        if forced_due and duration_ms >= hard_limit:
            if self.hold_hint is not None and not self.pause_candidate and duration_ms < 2 * self.max_utterance_ms:
                self.pause_candidate = True
                self.forced_candidate = True
                self.candidate_samples_at = len(self.buffered_samples)
                if self.reset_hint:
                    self.decision_generation = self.reset_hint(self.segment_id)
                self.candidate_ids.add(self.segment_id)
                self.emitted_times[self.segment_id] = (self.received_at_ms, timestamp_ms)
                return [(self.segment_id, self.buffered_samples.copy(), False)]
            cut = self.held_cut_index or self._forced_cut_index()
            return [self._forced_finalize(cut, timestamp_ms)]

        if (self.hold_hint is None and self.early_cut_after_ms > 0
                and silence_ms >= self.early_cut_silence_ms
                and speech_ms >= self.early_cut_after_ms):
            return [self._finalize(timestamp_ms)]

        if (speech and duration_ms >= self.min_draft_ms
                and self.samples_since_draft * 1000 >= self.draft_every_ms * SAMPLE_RATE):
            self.samples_since_draft = 0
            self.emitted_times[self.segment_id] = (self.received_at_ms, timestamp_ms)
            return [(self.segment_id, self.buffered_samples.copy(), False)]
        return []

    def _finalize(self, timestamp_ms: int) -> tuple:
        result = (self.segment_id, self.buffered_samples.copy(), True)
        self.emitted_times = {self.segment_id: (self.received_at_ms, timestamp_ms)}
        self.segment_id += 1
        self._reset_current()
        return result

    def _forced_cut_index(self) -> int:
        total_frames = len(self.frames)
        first = total_frames // 3
        best_start, best_length = -1, 0
        index = first
        while index < total_frames:
            if self.frames[index][1]:
                index += 1
                continue
            begin = index
            while index < total_frames and not self.frames[index][1]:
                index += 1
            length = index - begin
            if length >= best_length:
                best_start, best_length = begin, length
        if best_length < 2:
            return len(self.buffered_samples)
        return sum(len(frame[0]) for frame in self.frames[:best_start + best_length // 2 + 1])

    def _forced_finalize(self, cut: int, timestamp_ms: int) -> tuple:
        cut = max(1, min(cut, len(self.buffered_samples)))
        result = (self.segment_id, self.buffered_samples[:cut].copy(), True)
        tail = self.buffered_samples[cut:]
        tail_frames = []
        offset = 0
        for frame, speech, at in self.frames:
            end = offset + len(frame)
            if end > cut:
                tail_frames.append((frame[max(0, cut - offset):], speech, at))
            offset = end
        self.emitted_times = {self.segment_id: (self.received_at_ms, timestamp_ms)}
        self.segment_id += 1
        self._reset_current()
        if tail:
            self.buffered_samples = tail
            self.frames = tail_frames
            self.received_at_ms = tail_frames[0][2] if tail_frames else timestamp_ms
            self.speech_samples = sum(len(frame) for frame, speech, _ in tail_frames if speech)
            self.silent_samples = 0
            for frame, speech, _ in reversed(tail_frames):
                if speech:
                    break
                self.silent_samples += len(frame)
        return result

    def flush(self) -> List[tuple]:
        """Finalize the remaining speech when the audio source ends normally."""
        if not self.buffered_samples:
            self.pre_roll.clear()
            self.pre_roll_times.clear()
            return []
        return [self._finalize(self.frames[-1][2] if self.frames else self.received_at_ms)]

    def _reset_current(self) -> None:
        self.buffered_samples.clear()
        self.frames.clear()
        self.silent_samples = self.speech_samples = self.samples_since_draft = 0
        self.pause_candidate = False
        self.candidate_samples_at = 0
        self.forced_candidate = False
        self.held_cut_index = 0
        self.candidate_ids.clear()


@dataclass
class PipelineMetrics:
    """Pipeline performance metrics."""
    start_time_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    audio_segments_received: int = 0
    transcriptions_completed: int = 0
    translations_completed: int = 0
    captions_shown: int = 0
    errors: int = 0
    
    def uptime_ms(self) -> int:
        return int(time.time() * 1000) - self.start_time_ms


class Pipeline:
    """Core transcription → translation pipeline with worker threads."""
    
    def __init__(
        self,
        host: SessionHost,
        chat_sender: Optional[ChatSender] = None,
        chat_mode: str = "automatic",
    ):
        self.host = host
        self.chat_sender = chat_sender
        self.chat_mode = chat_mode
        self.prefs = host.prefs
        self.options = deepcopy(getattr(self.prefs, "subtitle_settings", SubtitleSettings()))
        self.settings_lock = threading.Lock()
        self.records: Optional[SessionRecords] = getattr(host, "records", None)
        self.decision_hints: dict[int, Optional[bool]] = {}
        self.decision_generations: dict[int, int] = {}
        self.decision_lock = threading.Lock()
        self.decision_tasks: list[threading.Thread] = []
        self.decisions = None
        if self.options.smart_segmentation or self.options.check_translation:
            self.decisions = DecisionsClient(
                self.options,
                self.prefs.get_translation_key("jev") or "",
                self._notice, self.records.event if self.records else None,
            )
        self.previous: deque[tuple[str, str]] = deque(maxlen=8)
        self.previous_by_language: dict[str, deque[tuple[str, str]]] = {}
        self.translators: list[tuple[Target, Mt]] = []
        
        self.models: Optional[SpeechModels] = None
        self.audio: Optional[AudioSource] = None
        self.segmenter: Optional[Segmenter] = None
        self.setup: Optional[Setup] = None
        
        self.board = CaptionBoard(max_sentences=self.options.retained_sentences, max_chars=None)
        self.metrics = PipelineMetrics()
        
        self.asr_queue: queue.Queue = queue.Queue()
        self.mt_queue: queue.Queue = queue.Queue()
        self.pending_condition = threading.Condition()
        self.pending_final_audio_ms = 0
        self.pending_final_jobs = 0
        self.max_pending_audio_ms = 30_000
        self.max_drain_seconds = 60
        self.overloaded = False
        self.accepting = True
        self.contexts: dict[int | tuple[int, str], tuple[tuple[str, str], ...]] = {}
        self.context_settings = (self.options.use_context, self.options.previous_sentences)
        self.translation_cache: dict[tuple, MtResult] = {}
        self.finalized_segments: set[int] = set()
        self.latest_drafts: dict[int, str] = {}
        
        self.asr_thread: Optional[threading.Thread] = None
        self.mt_thread: Optional[threading.Thread] = None
        self.running = False

    def refresh_settings(self) -> None:
        with self.settings_lock:
            current = getattr(self.prefs, "subtitle_settings", self.options)
            if current == self.options:
                return
            self.options = deepcopy(current)
            self.board.max_sentences = current.retained_sentences * max(1, len(self.translators))
            if current.smart_segmentation or current.check_translation:
                if self.decisions is None:
                    self.decisions = DecisionsClient(
                        self.options, "", self._notice, self.records.event if self.records else None,
                    )
            else:
                self.decisions = None

    def start(self) -> None:
        """Start worker threads."""
        if self.running:
            return
        
        self.running = True
        self.asr_thread = threading.Thread(target=self._asr_worker, daemon=True)
        self.mt_thread = threading.Thread(target=self._mt_worker, daemon=True)
        self.asr_thread.start()
        self.mt_thread.start()
    
    def stop(self) -> None:
        """Stop workers immediately, as for a user-requested stop."""
        self.accepting = False
        self.running = False
        self._cancel_translations()
        current_thread = threading.current_thread()
        if self.asr_thread and self.asr_thread is not current_thread:
            self.asr_thread.join(timeout=5)
        if self.mt_thread and self.mt_thread is not current_thread:
            self.mt_thread.join(timeout=5)
        for task in self.decision_tasks:
            if task is not current_thread:
                task.join(timeout=1)

    def drain(self, timeout: Optional[float] = None) -> int:
        """Stop accepting audio and let queued finals finish, bounded to one minute."""
        self.accepting = False
        timeout = self.max_drain_seconds if timeout is None else min(timeout, self.max_drain_seconds)
        self._drop_queued_drafts(self.asr_queue)
        self._drop_queued_drafts(self.mt_queue)
        deadline = time.monotonic() + timeout
        with self.pending_condition:
            while self.pending_final_jobs and self.running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.pending_condition.wait(min(remaining, 0.1))
            abandoned = self.pending_final_jobs
        if abandoned:
            self._cancel_queued_finals()
            self._cancel_translations()
            self._notice(f"\u6392\u7a7a\u8d85\u65f6\uff0c\u5df2\u653e\u5f03 {abandoned} \u53e5\u672a\u5b8c\u6210\u7ffb\u8bd1\u3002")
        elif self.overloaded and self.running:
            self._notice("\u5f85\u5904\u7406\u5b57\u5e55\u5df2\u5168\u90e8\u7ffb\u8bd1\u5b8c\u3002")
        self.running = False
        current_thread = threading.current_thread()
        remaining = max(0.0, deadline - time.monotonic())
        if self.asr_thread and self.asr_thread is not current_thread:
            self.asr_thread.join(timeout=remaining)
        remaining = max(0.0, deadline - time.monotonic())
        if self.mt_thread and self.mt_thread is not current_thread:
            self.mt_thread.join(timeout=remaining)
        return abandoned

    def _cancel_translations(self) -> None:
        translators = [translator for _, translator in self.translators]
        if self.setup and all(translator is not self.setup.mt for translator in translators):
            translators.append(self.setup.mt)
        for translator in translators:
            cancel = getattr(translator, "cancel", None)
            if callable(cancel):
                cancel()

    @staticmethod
    def _drop_queued_drafts(pending: queue.Queue) -> None:
        with pending.mutex:
            pending.queue = deque(item for item in pending.queue if item.get("is_final"))
            pending.not_full.notify_all()

    def _cancel_queued_finals(self) -> None:
        abandoned_jobs: set[int] = set()
        for pending in (self.asr_queue, self.mt_queue):
            with pending.mutex:
                retained = deque()
                for item in pending.queue:
                    if item.get("is_final"):
                        abandoned_jobs.add(id(item.get("completion", {}).get("job", item)))
                    else:
                        retained.append(item)
                pending.queue = retained
                pending.not_full.notify_all()
        abandoned = len(abandoned_jobs)
        if abandoned:
            with self.pending_condition:
                self.pending_final_jobs = max(0, self.pending_final_jobs - abandoned)
                self.pending_final_audio_ms = 0 if self.pending_final_jobs == 0 else self.pending_final_audio_ms
                self.pending_condition.notify_all()

    def _complete_final(self, job: dict) -> None:
        if not job.get("is_final") or job.get("pending_completed"):
            return
        job["pending_completed"] = True
        parent = job.get("completion")
        if parent is not None:
            parent["remaining"] -= 1
            if parent["remaining"]:
                return
            job = parent["job"]
        with self.pending_condition:
            self.pending_final_jobs = max(0, self.pending_final_jobs - 1)
            self.pending_final_audio_ms = max(0, self.pending_final_audio_ms - job.get("audio_ms", 0))
            self.pending_condition.notify_all()

    def _notice(self, message: str) -> None:
        callback = getattr(self.host, "notice", None)
        if callable(callback):
            callback(message)
        else:
            log.warning("%s", message)

    def hold_hint(self, segment_id: int) -> Optional[bool]:
        with self.decision_lock:
            return self.decision_hints.get(segment_id)

    def reset_hint(self, segment_id: int) -> int:
        with self.decision_lock:
            generation = self.decision_generations.get(segment_id, 0) + 1
            self.decision_generations[segment_id] = generation
            self.decision_hints.pop(segment_id, None)
            for old in list(self.decision_generations):
                if old < segment_id - 2:
                    self.decision_generations.pop(old, None)
                    self.decision_hints.pop(old, None)
            return generation
    
    def add_audio_segment(
        self, seg_id: int, samples: List[float], is_final: bool, audio_end_ms: int,
        received_at_ms: Optional[int] = None, candidate: bool = False,
        decision_generation: int = 0,
    ) -> None:
        """Queue audio, replacing unstarted drafts but never a final."""
        if not self.accepting and not (self.overloaded and is_final):
            return
        audio_ms = len(samples) * 1000 // SAMPLE_RATE
        job = {
            "seg_id": seg_id, "samples": samples, "is_final": is_final,
            "audio_end_ms": audio_end_ms,
            "received_at_ms": received_at_ms if received_at_ms is not None else audio_end_ms,
            "candidate": candidate, "decision_generation": decision_generation,
            "queue_at_ms": int(time.time() * 1000), "audio_ms": audio_ms,
        }
        if not is_final and self.pending_final_jobs:
            return
        if is_final:
            with self.pending_condition:
                self.pending_final_audio_ms += audio_ms
                self.pending_final_jobs += 1
                if self.pending_final_audio_ms > self.max_pending_audio_ms and not self.overloaded:
                    self.overloaded = True
                    self.accepting = False
                    overloaded_now = True
                else:
                    overloaded_now = False
        else:
            overloaded_now = False
            self._replace_pending_draft(self.asr_queue, job)
            self.metrics.audio_segments_received += 1
            return
        self._enqueue_final(self.asr_queue, job)
        self.metrics.audio_segments_received += 1
        if overloaded_now:
            self._notice("\u5b57\u5e55\u5904\u7406\u4e0d\u8fc7\u6765\uff0c\u5df2\u505c\u6b62\u91c7\u96c6\u5e76\u5f00\u59cb\u6392\u7a7a\u5f85\u7ffb\u8bd1\u53e5\u5b50\u3002")

    @staticmethod
    def _enqueue_final(pending: queue.Queue, job: dict) -> None:
        with pending.mutex:
            finals = [item for item in pending.queue if item.get("is_final")]
            drafts = [item for item in pending.queue if not item.get("is_final")
                      and (item.get("seg_id"), item.get("target")) != (job["seg_id"], job.get("target"))]
            pending.queue = deque(finals + [job] + drafts)
            pending.not_empty.notify()

    @staticmethod
    def _replace_pending_draft(pending: queue.Queue, job: dict) -> None:
        segment_id = job["seg_id"]
        with pending.mutex:
            queued = list(pending.queue)
            if any((item.get("seg_id"), item.get("target")) == (segment_id, job.get("target"))
                   and item.get("is_final") for item in queued):
                return
            pending.queue = deque(
                item for item in queued
                if not ((item.get("seg_id"), item.get("target")) == (segment_id, job.get("target"))
                        and not item.get("is_final"))
            )
            pending.queue.append(job)
            pending.not_empty.notify()

    def _asr_worker(self) -> None:
        """Transcribe final jobs in order and collapse unstarted drafts."""
        if not self.models:
            return
        asr = self.models.asr
        while self.running:
            try:
                job = self.asr_queue.get(timeout=0.25)
                self.refresh_settings()
                if not job["is_final"] and self.pending_final_jobs:
                    continue
                start = int(time.time() * 1000)
                text = asr.recognize(job["samples"])
                if job["is_final"]:
                    text = self._repair_lost_opening(job["seg_id"], text)
                    self.latest_drafts.pop(job["seg_id"], None)
                else:
                    self.latest_drafts[job["seg_id"]] = text
                if self.options.ignore_onomatopoeia and is_sound_only(text):
                    log.debug("Skipped sound-only ASR segment %s", job["seg_id"])
                    self._complete_final(job)
                    continue
                if self.options.deduplicate:
                    text = remove_repeated_text(text)
                if not text.strip():
                    self._complete_final(job)
                    continue
                end = int(time.time() * 1000)
                show_original = getattr(self.host, "show_transcription", None)
                if callable(show_original):
                    self.host.post(lambda j=job, t=text, latency=end - start: show_original(
                        j["seg_id"], t, j["is_final"], latency
                    ))
                self.metrics.transcriptions_completed += 1
                if self.records:
                    self.records.event(
                        "asr", segment_id=job["seg_id"], original=text,
                        final=job["is_final"], received_at_ms=job["received_at_ms"],
                        elapsed_ms=end - start,
                    )
                decisions = self.decisions
                if decisions and job["candidate"]:
                    with self.decision_lock:
                        current_candidate = self.decision_generations.get(job["seg_id"]) == job["decision_generation"]
                        if current_candidate:
                            self.decision_hints.pop(job["seg_id"], None)

                    def decide(segment_id=job["seg_id"], recognized=text,
                               generation=job["decision_generation"], client=decisions):
                        try:
                            answer = client.unfinished(recognized)
                        except OSError as error:
                            log.error("Decision diagnostic record failed: %s", type(error).__name__)
                            self._notice("Decisions \u8bca\u65ad\u8bb0\u5f55\u4fdd\u5b58\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u78c1\u76d8\u7a7a\u95f4\uff1b\u5df2\u4f7f\u7528\u666e\u901a\u65ad\u53e5\u3002")
                            answer = None
                        with self.decision_lock:
                            if self.decision_generations.get(segment_id) == generation:
                                self.decision_hints[segment_id] = False if answer is None else answer

                    if current_candidate:
                        self.decision_tasks = [task for task in self.decision_tasks if task.is_alive()]
                        task = threading.Thread(target=decide, daemon=True)
                        self.decision_tasks.append(task)
                        task.start()
                if not job["is_final"] and self.options.display_mode == "\u8bf4\u5b8c\u518d\u51fa":
                    continue
                if not job["is_final"] and job["seg_id"] in self.finalized_segments:
                    continue
                mt_job = {
                    "seg_id": job["seg_id"], "text": text, "is_final": job["is_final"],
                    "audio_end_ms": job["audio_end_ms"], "received_at_ms": job["received_at_ms"],
                    "asr_latency_ms": end - start, "audio_ms": job["audio_ms"],
                    "queue_at_ms": int(time.time() * 1000),
                }
                if not self.translators:
                    if job["is_final"]:
                        self._enqueue_final(self.mt_queue, mt_job)
                    else:
                        self._replace_pending_draft(self.mt_queue, mt_job)
                    continue
                targets = self.translators
                completion = {"remaining": len(targets), "job": job}
                for target, translator in targets:
                    translated_job = {
                        **mt_job, "translator": translator, "target": target,
                        "completion": completion,
                    }
                    if job["is_final"]:
                        self._enqueue_final(self.mt_queue, translated_job)
                    else:
                        self._replace_pending_draft(self.mt_queue, translated_job)
            except queue.Empty:
                pass
            except Exception as error:
                log.error("ASR worker failed: %s", type(error).__name__)
                self.metrics.errors += 1
                self.host.post(lambda: self.host.show([], error="\u8bed\u97f3\u8bc6\u522b\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u6a21\u578b\u548c GPU \u8fd0\u884c\u5e93\u540e\u91cd\u8bd5\u3002"))
                self.running = False
                break

    def _repair_lost_opening(self, segment_id: int, final: str) -> str:
        # Kotlin Pipeline.kt:831+ uses ASR token timings; this adapter falls back to conservative text overlap.
        draft = self.latest_drafts.get(segment_id, "").strip()
        final = final.strip()
        if not draft or not final or draft in final or final.startswith(draft):
            return final
        for overlap in range(min(len(draft), len(final)), 3, -1):
            if draft[-overlap:] == final[:overlap]:
                return draft[:-overlap] + final
        draft_words, final_words = draft.split(), final.split()
        for overlap in range(min(len(draft_words), len(final_words)), 0, -1):
            if draft_words[-overlap:] == final_words[:overlap]:
                return " ".join(draft_words[:-overlap] + final_words)
        return final

    def _mt_worker(self) -> None:
        """Translate captions, showing streamed partial text but queuing only final results."""
        if not self.setup or not self.setup.mt:
            return
        while self.running:
            try:
                job = self.mt_queue.get(timeout=0.25)
                self.refresh_settings()
                translator = job.get("translator", self.setup.mt)
                target = job.get("target", self.prefs.target_lang)
                language = target.value
                context_id = (job["seg_id"], target.value) if self.translators else job["seg_id"]
                previous = self.previous_by_language.setdefault(target.value, deque(maxlen=8)) if self.translators else self.previous
                content = self.options.presets[self.options.preset]
                if hasattr(translator, "background"):
                    translator.background = content["background"]
                    translator.glossary = content["glossary"]
                if hasattr(translator, "history"):
                    context_settings = (self.options.use_context, self.options.previous_sentences)
                    if context_settings != self.context_settings:
                        self.contexts.clear()
                        self.context_settings = context_settings
                    previous_count = self.options.previous_sentences if self.options.use_context else 0
                    context = self.contexts.setdefault(
                        context_id, tuple(list(previous)[-previous_count:] if previous_count else ())
                    )
                    translator.history = list(context)
                    translator.correction = ""
                else:
                    context = ()
                context_key = tuple(context)
                system_builder = getattr(translator, "_system_message", None)
                system = system_builder() if callable(system_builder) else ""
                cache_key = (job["seg_id"], target.value, job["text"], context_key, system,
                             getattr(translator, "correction", ""))
                start = int(time.time() * 1000)

                def show_partial(text: str) -> None:
                    if not text.strip() or not self.running:
                        return
                    partial = Caption(
                        segment_id=job["seg_id"], revision=1, is_final=False,
                        original=job["text"], translated=text, timing=Timing(
                            audio_ms=job["audio_ms"], segment_wait_ms=0, asr_queue_ms=0,
                            asr_ms=job["asr_latency_ms"], mt_queue_ms=start - job["queue_at_ms"],
                            mt_ms=int(time.time() * 1000) - start,
                            mt_done_ms=int(time.time() * 1000) - job["audio_end_ms"],
                        ), audio_end_at_ms=job["audio_end_ms"],
                        audio_received_at_ms=job["received_at_ms"],
                        target_language=target.value,
                    )
                    self.board.add(partial)
                    self.host.post(self._show_captions)

                result = self.translation_cache.get(cache_key)
                if result is None:
                    stream_method = getattr(type(translator), "translate_with_updates", None)
                    result = (translator.translate_with_updates(job["text"], show_partial)
                              if callable(stream_method) else translator.translate(job["text"]))
                    if result and not result.error and result.text.strip():
                        self.translation_cache[cache_key] = result
                if not self.running:
                    return
                translation_failed = False
                if not result or result.error:
                    message = result.error if result else "\u7ffb\u8bd1\u670d\u52a1\u6ca1\u6709\u8fd4\u56de\u7ed3\u679c\u3002"
                    log.error("Translation failed: %s", message)
                    self.metrics.errors += 1
                    self.host.post(lambda error=message: self.host.show([], error=error))
                    if job["is_final"]:
                        translation_failed = True
                        result = MtResult(f"[\u7ffb\u8bd1\u5931\u8d25] {job['text']}")
                    else:
                        continue
                if not result.text.strip():
                    self._complete_final(job)
                    continue
                needs_review = False
                decisions = self.decisions
                if (job["is_final"] and not translation_failed and decisions
                        and self.options.check_translation):
                    problem = decisions.translation_problem(job["text"], result.text)
                    if problem not in (None, "ok"):
                        if hasattr(translator, "correction"):
                            translator.correction = problem
                        retry = translator.translate(job["text"])
                        if retry and retry.text and not retry.error:
                            result = retry
                            remaining = decisions.translation_problem(job["text"], result.text)
                            needs_review = remaining != "ok"
                        else:
                            needs_review = True
                        if needs_review:
                            self._notice("\u8bd1\u6587\u68c0\u67e5\u4ecd\u6709\u7591\u95ee\uff1b\u8bf7\u624b\u52a8\u5ba1\u6838\uff0c\u4e0d\u4f1a\u81ea\u52a8\u53d1\u9001\u3002")

                end = int(time.time() * 1000)
                timing = Timing(
                    audio_ms=job["audio_ms"], segment_wait_ms=0, asr_queue_ms=0,
                    asr_ms=job["asr_latency_ms"], mt_queue_ms=start - job["queue_at_ms"],
                    mt_ms=end - start, mt_done_ms=end - job["audio_end_ms"],
                )
                caption = Caption(
                    segment_id=job["seg_id"], revision=1, is_final=job["is_final"],
                    original=job["text"], translated=result.text, timing=timing,
                    audio_end_at_ms=job["audio_end_ms"], audio_received_at_ms=job["received_at_ms"],
                    target_language=target.value,
                )
                self.board.add(caption)
                self.metrics.translations_completed += 1
                self.metrics.captions_shown += 1
                record = None
                if self.records:
                    self.records.event(
                        "translation", segment_id=job["seg_id"], original=job["text"],
                        translated=result.text, final=job["is_final"],
                        prompt=getattr(translator, "last_messages", []), elapsed_ms=end - start,
                    )
                    if job["is_final"]:
                        record = self.records.caption(
                            job["seg_id"], job["received_at_ms"], job["audio_end_ms"],
                            job["audio_ms"], job["text"], result.text,
                            target_language=language,
                        )
                if job["is_final"]:
                    self.finalized_segments.add(job["seg_id"])
                    previous.append((job["text"], result.text))
                    self.contexts.pop(context_id, None)
                self.host.post(self._show_captions)

                sending_language = self.options.chat_language or (
                    self.translators[0][0].value if self.translators else self.prefs.target_lang.value
                )
                if (target.value == sending_language and job["is_final"]
                        and not translation_failed and self.chat_mode != "off" and
                        (self.chat_mode == "manual" or (self.chat_sender and self.chat_sender.can_send()))):
                    message = self._chat_message(result.text, target, job["text"])
                    if self.chat_mode == "manual" or needs_review:
                        review = getattr(self.host, "queue_chat_review", None)
                        if callable(review):
                            self.host.post(lambda m=message, s=self.chat_sender, o=job["text"], r=record:
                                           review(m, s, o, r))
                        else:
                            log.error("Manual chat review is not available on this host")
                    elif self.chat_mode == "automatic":
                        threading.Thread(target=self._send_chat, args=(message, job["text"], record), daemon=True).start()
                self._complete_final(job)
            except queue.Empty:
                pass
            except Exception as error:
                log.error("MT worker failed: %s", type(error).__name__)
                self.metrics.errors += 1
                self.host.post(lambda: self.host.show([], error="\u5b57\u5e55\u5904\u7406\u6216\u8bb0\u5f55\u4fdd\u5b58\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u8bbe\u7f6e\u548c\u78c1\u76d8\u7a7a\u95f4\u3002"))
                self.running = False
                break

    def _show_captions(self) -> None:
        """Display captions (UI thread)."""
        captions = self.board.get_display_captions(limit=self.options.retained_sentences * max(1, len(self.translators)))
        self.host.show(captions)
    
    def _chat_message(self, translated: str, target: Optional[Target] = None, original: str = "") -> str:
        return format_chat(self.options.chat_template, translated, original, (target or self.prefs.target_lang).value)

    def _send_chat(
        self, message: str, original: str, record: Optional[CaptionRecord] = None
    ) -> None:
        """Send to chat."""
        try:
            if not self.chat_sender:
                return
            success, detail = send_recorded(self.chat_sender, message, original, self.records, record)
        except Exception as e:
            log.error("Chat send failed: %s", type(e).__name__)
            self._notice("消息发送失败；请检查聊天状态。")
            return
        if not success:
            self._notice(detail or "消息发送失败；请检查聊天状态。")
            return
        if detail == "消息已发送，但本地记录保存失败；不要再次发送，请检查磁盘空间。":
            self._notice(detail)


class CaptionSession:
    """Main session controller."""
    
    def __init__(
        self,
        host: SessionHost,
        chat_sender: Optional[ChatSender] = None,
        chat_mode: str = "automatic",
    ):
        self.host = host
        self.chat_sender = chat_sender
        self.chat_mode = chat_mode
        self.pipeline: Optional[Pipeline] = None
        self.session_thread: Optional[threading.Thread] = None
        self.running = False
        self.stopping = False
    
    def start(self) -> None:
        """Start caption session."""
        if self.running:
            return
        
        self.running = True
        self.stopping = False
        self.session_thread = threading.Thread(
            target=self._session_loop,
            daemon=True,
        )
        self.session_thread.start()
    
    def stop(self) -> None:
        """Stop caption session."""
        if not self.running:
            return
        
        self.stopping = True
        self.running = False
        
        if self.pipeline:
            self.pipeline.stop()
            if self.pipeline.audio:
                self.pipeline.audio.close()
        
        if self.session_thread:
            self.session_thread.join(timeout=10)
    
    def _session_loop(self) -> None:
        """Main session thread loop."""
        try:
            # Load models
            self.pipeline = Pipeline(self.host, self.chat_sender, self.chat_mode)
            self.pipeline.models = self.host.load_models()
            
            # Create translator
            from .simul_streaming_adapter import StreamingProjectTranslator
            targets = getattr(self.host.prefs, "target_langs", (self.host.prefs.target_lang,))
            self.pipeline.translators = [
                (target, StreamingProjectTranslator(
                    self.host.prefs.source_lang, target,
                    api_key=self.host.prefs.get_translation_key("openai"),
                    base_url=self.host.prefs.get_translation_base_url(),
                    model=self.host.prefs.translation_model,
                    background=self.pipeline.options.presets[self.pipeline.options.preset]["background"],
                    glossary=self.pipeline.options.presets[self.pipeline.options.preset]["glossary"],
                )) for target in targets
            ]
            self.pipeline.board.max_sentences = self.pipeline.options.retained_sentences * len(targets)
            self.pipeline.setup = Setup(
                mt=self.pipeline.translators[0][1],
                source=self.host.prefs.source_lang,
                target=self.host.prefs.target_lang,
            )
            
            # Open audio
            self.pipeline.audio = self.host.open_audio()
            smart = self.pipeline.options.smart_segmentation
            self.pipeline.segmenter = Segmenter(
                self.pipeline.models,
                self.pipeline.hold_hint if smart else None,
                self.pipeline.reset_hint if smart else None,
                max_utterance_ms=5000 if smart else 7000,
            )
            
            # Start workers
            self.pipeline.start()
            
            # Capture loop
            frame = [0.0] * FRAME_SIZE
            
            while (self.running and not self.stopping and self.pipeline.running
                   and not self.pipeline.overloaded):
                end_ms = self.pipeline.audio.read(frame)
                if end_ms < 0:
                    reason = self.pipeline.audio.end_reason()
                    self.host.post(lambda: self.host.show([], error=reason))
                    break
                
                if self.pipeline.segmenter:
                    self.pipeline.refresh_settings()
                    smart = self.pipeline.options.smart_segmentation
                    self.pipeline.segmenter.hold_hint = self.pipeline.hold_hint if smart else None
                    self.pipeline.segmenter.reset_hint = self.pipeline.reset_hint if smart else None
                    self.pipeline.segmenter.max_utterance_ms = 5000 if smart else 7000
                    received_ms = getattr(self.pipeline.audio, "received_at_ms", end_ms)
                    segments = self.pipeline.segmenter.process_frame(frame, received_ms)
                    for seg_id, samples, is_final in segments:
                        first_ms, last_ms = self.pipeline.segmenter.emitted_times[seg_id]
                        candidate = seg_id in self.pipeline.segmenter.candidate_ids and not is_final
                        self.pipeline.add_audio_segment(
                            seg_id, samples, is_final, last_ms, first_ms,
                            candidate, self.pipeline.segmenter.decision_generation,
                        )
                        if candidate:
                            self.pipeline.segmenter.candidate_ids.discard(seg_id)

            if not self.stopping and self.pipeline.segmenter:
                for seg_id, samples, is_final in self.pipeline.segmenter.flush():
                    first_ms, last_ms = self.pipeline.segmenter.emitted_times[seg_id]
                    self.pipeline.add_audio_segment(seg_id, samples, is_final, last_ms, first_ms)
                self.pipeline.drain()
            self.host.post(self.host.on_session_ended)

        except Exception as e:
            log.error(f"Session: {e}", exc_info=True)
            self.host.post(lambda error=str(e): self.host.show([], error=error))
        finally:
            if self.pipeline:
                self.pipeline.stop()
                if self.pipeline.models:
                    self.pipeline.models.release()
                if self.pipeline.audio:
                    self.pipeline.audio.close()
            self.running = False
