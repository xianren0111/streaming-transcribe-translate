"""Optional bounded Decisions API assistance; failures explicitly bypass assistance."""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

import requests

from .subtitle_settings import JEV_PROVIDERS, SubtitleSettings


class DecisionsClient:
    def __init__(
        self, settings: SubtitleSettings, key: str = "",
        notify: Optional[Callable[[str], None]] = None,
        event: Optional[Callable[..., None]] = None,
    ):
        self.settings, self.notify, self.event = settings, notify, event
        self.url, self.model = JEV_PROVIDERS["OpenCode Zen（免费，不用 key）"]
        self.key = ""
        self.paused_until = 0.0

    def ask(self, state: dict[str, str], question: dict) -> Optional[dict]:
        if time.monotonic() < self.paused_until:
            return None
        try:
            response = requests.post(
                self.url,
                headers={"Authorization": f"Bearer {self.key}"} if self.key else {},
                json={"model": self.model, "state": state, "questions": {"x": question}},
                timeout=1,
            )
            if response.status_code == 429:
                delay = response.headers.get("Retry-After", "30")
                self.paused_until = time.monotonic() + min(300, max(1, float(delay))) if delay.isdigit() else time.monotonic() + 30
                self._failure("Decisions 服务限流，暂时跳过辅助；字幕继续。", pause=False)
                return None
            response.raise_for_status()
            answer = response.json()["answers"]["x"]
            if not isinstance(answer, dict):
                raise ValueError("invalid answer")
        except (requests.RequestException, ValueError, TypeError, KeyError) as error:
            self._failure(f"Decisions 辅助不可用（{type(error).__name__}）；字幕继续。")
            return None
        if self.event:
            self.event("decision", state=state, question=question, answer=answer)
        return answer

    def _failure(self, message: str, pause: bool = True) -> None:
        if pause:
            self.paused_until = time.monotonic() + 30
        if self.notify:
            self.notify(message)
        if self.event:
            self.event("decision_unavailable", message=message)

    def unfinished(self, text: str) -> Optional[bool]:
        answer = self.ask({"current": text}, {
            "type": "noul",
            "instructions": "Determine whether this spoken sentence needs following words to complete its meaning.",
            "criteria": {"true": "Incomplete sentence or cut-off clause", "false": "Complete statement or standalone reaction"},
        })
        if answer is None:
            return None
        probability = answer.get("noul")
        if isinstance(probability, (int, float)) and not isinstance(probability, bool) and math.isfinite(probability) and 0 <= probability <= 1:
            return probability >= 0.5
        self._failure("Decisions 断句结果无效，已使用普通断句。")
        return None

    def translation_problem(self, original: str, translated: str) -> Optional[str]:
        categories = {
            "ok": "Accurate translation",
            "omission": "Important source meaning missing",
            "reversal": "Meaning or polarity reversed",
            "hallucination": "Meaning added that is absent from source",
            "terminology": "Incorrect names or domain terms",
        }
        answer = self.ask({"ja": original, "zh": translated}, {
            "type": "choice",
            "instructions": "Compare the original speech and translation. Choose the most important translation issue, or ok.",
            "criteria": categories,
        })
        if answer is None:
            return None
        choice = answer.get("choice")
        if not isinstance(choice, str) or choice not in categories:
            self._failure("Decisions 译文检查结果无效，已跳过检查。")
            return None
        return choice
