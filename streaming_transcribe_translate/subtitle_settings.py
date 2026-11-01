"""Non-secret subtitle options and editable translation content presets."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from dotenv import dotenv_values
from .env_preferences import env_defaults


PALETTES = {
    "黑白": ("#ffffff", "#202024"),
    "经典白": ("#ffffff", "#10121b"),
    "影院黄": ("#ffe369", "#181818"),
    "薄荷绿": ("#98f0ce", "#15221f"),
    "天空蓝": ("#8cdaff", "#131e29"),
    "樱花粉": ("#ffc5de", "#241822"),
    "白底黑字": ("#161616", "#ffffff"),
}

JEV_PROVIDERS = {
    "OpenCode Zen（免费，不用 key）": ("https://opencode.ai/zen/v1/systemone", "jev-1.13-free"),
}


def default_presets() -> dict[str, dict[str, str]]:
    return {
        "主播模式": {
            "background": "Live streamer speech addressing an audience. Preserve informal tone, speaker intent, and streaming terminology regardless of platform.",
            "glossary": "弹幕: live chat\n舰长: channel supporter\n上舰: join channel membership\nSuper Chat: paid highlighted chat\nmembership: channel membership",
        },
        "对话模式": {"background": "Everyday spoken conversation. Preserve natural dialogue, speaker intent, and conversational tone.", "glossary": ""},
    }


@dataclass
class SubtitleSettings:
    preset: str = "主播模式"
    presets: dict[str, dict[str, str]] = field(default_factory=default_presets)
    use_context: bool = False
    previous_sentences: int = 2
    display_mode: str = "边听边出"
    deduplicate: bool = False
    ignore_onomatopoeia: bool = True
    smart_segmentation: bool = False
    check_translation: bool = False
    jev_provider: str = "OpenCode Zen（免费，不用 key）"
    jev_url: str = ""
    jev_model: str = ""
    palette: str = "黑白"
    reading_languages: list[str] = field(default_factory=list)
    chat_template: str = "【{translation}】"
    chat_template_custom: bool = False
    chat_language: str = ""
    font_size: int = 15
    opacity: float = 0.48
    show_original: bool = True
    show_stats: bool = True
    width_percent: float = 28.0
    height_percent: float = 10.0
    retained_sentences: int = 50
    save_records: bool = False
    records_folder: str = ""
    save_captions: bool = True
    diagnostics: bool = False
    recording_start: str = ""

    def validate(self) -> None:
        self.jev_provider = "OpenCode Zen（免费，不用 key）"
        self.jev_url = ""
        self.jev_model = ""
        for name in ("preset", "display_mode", "jev_provider", "jev_url", "jev_model", "palette", "recording_start", "records_folder"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"设置 {name} 必须为文字。")
        if self.records_folder and not Path(self.records_folder).is_absolute():
            raise ValueError("请选择完整的记录文件夹路径。")
        from .simul_interfaces import Target
        from .chat_delivery import validate_template
        validate_template(self.chat_template)
        if self.chat_language not in ("", *(target.value for target in Target)):
            raise ValueError("请选择有效的发送语言。")
        if self.reading_languages and self.chat_language and self.chat_language not in self.reading_languages:
            raise ValueError("发送语言必须包含在阅读语言中。")
        if (
            not isinstance(self.reading_languages, list)
            or any(not isinstance(code, str) or code not in {target.value for target in Target}
                   for code in self.reading_languages)
            or len(set(self.reading_languages)) != len(self.reading_languages)
        ):
            raise ValueError("请选择有效且不重复的字幕语言。")

        for name, low, high in (
            ("previous_sentences", 0, 8), ("font_size", 10, 40),
            ("retained_sentences", 1, 200),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"设置 {name} 必须在 {low} 到 {high} 之间。")
        for name, high in (("width_percent", 100), ("height_percent", 80)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= high:
                raise ValueError(f"设置 {name} 必须在 1 到 {high} 之间。")
        if type(self.opacity) not in (float, int) or not math.isfinite(self.opacity) or not 0.1 <= self.opacity <= 1:
            raise ValueError("背景浓淡必须在 10% 到 100% 之间。")
        for name in (
            "use_context", "deduplicate", "ignore_onomatopoeia", "smart_segmentation", "check_translation",
            "show_original", "show_stats", "save_records", "save_captions", "diagnostics",
            "chat_template_custom",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"设置 {name} 必须为开关值。")
        if self.palette not in PALETTES or self.jev_provider not in JEV_PROVIDERS:
            raise ValueError("未知的字幕配色或 Decisions 服务。")
        if self.display_mode not in ("边听边出", "说完再出"):
            raise ValueError("未知的字幕显示方式。")
        if not isinstance(self.presets, dict) or not self.presets or self.preset not in self.presets:
            raise ValueError("请选择有效的内容类型。")
        for name, content in self.presets.items():
            if (
                not isinstance(name, str) or not name.strip()
                or not isinstance(content, dict)
                or set(content) != {"background", "glossary"}
                or not all(isinstance(text, str) for text in content.values())
            ):
                raise ValueError("内容背景和术语表格式无效。")

    def record_directory(self, default: Path) -> Path:
        return Path(self.records_folder) if self.records_folder else default

    @classmethod
    def load(cls, path: Path, *, env_file: Path | None = None) -> SubtitleSettings:
        values = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(values, dict) or set(values) - set(cls.__dataclass_fields__):
            raise ValueError("字幕设置文件格式无效。")
        merged = env_defaults(asdict(cls()), "SUBTITLE_", values, env_file)
        settings = cls(**merged)
        if "chat_template_custom" not in values and (
            env_file is None or "SUBTITLE_CHAT_TEMPLATE_CUSTOM" not in dotenv_values(env_file)
        ) and merged["chat_template"] != "【{translation}】":
            settings.chat_template_custom = True
        settings.validate()
        selected = settings.preset
        modes = default_presets()
        for mode, content in modes.items():
            settings.presets.setdefault(mode, content)
        if selected not in modes:
            mode = "对话模式" if selected == "一般对话" else "主播模式"
            settings.presets[mode] = dict(settings.presets[selected])
            settings.preset = mode
        return settings

    def save(self, path: Path) -> None:
        self.validate()
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
