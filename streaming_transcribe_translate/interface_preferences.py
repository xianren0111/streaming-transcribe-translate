"""Non-secret interface preferences and operating-system language detection."""

import ctypes
import json
import locale
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from .env_preferences import env_defaults


LANGUAGES = {"ja": "日本語", "zh": "中文", "en": "English", "ko": "한국어"}


def system_language() -> str:
    if sys.platform == "win32":
        identifier = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        name = locale.windows_locale.get(identifier, "en")
    else:
        name = locale.getlocale()[0] or "en"
    language = name.replace("-", "_").split("_")[0].lower()
    return language if language in LANGUAGES else "en"


@dataclass
class InterfacePreferences:
    theme: str = "light"
    language: str = "system"

    def validate(self) -> None:
        if self.theme not in ("light", "dark"):
            raise ValueError("Invalid interface theme.")
        if self.language not in ("system", *LANGUAGES):
            raise ValueError("Invalid interface language.")

    @property
    def resolved_language(self) -> str:
        return system_language() if self.language == "system" else self.language

    @classmethod
    def load(cls, path: Path, *, env_file: Path | None = None):
        values = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(values, dict) or set(values) - {"theme", "language"}:
            raise ValueError("Invalid interface preferences.")
        preferences = cls(**env_defaults(asdict(cls()), "UI_", values, env_file))
        preferences.validate()
        return preferences

    def save(self, path: Path) -> None:
        self.validate()
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        temporary.replace(path)
