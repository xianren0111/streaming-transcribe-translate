"""Normalize environment choices without changing localized UI values."""

import logging
import json
from pathlib import Path
from typing import Any, Mapping

from dotenv import dotenv_values


log = logging.getLogger(__name__)

AUDIO_INPUTS = ("直播间声音", "麦克风", "电脑声音")
CHAT_MODES = ("手动确认", "自动发送")
_CHOICES = {
    "AUDIO_INPUT": (
        AUDIO_INPUTS,
        dict(zip(("stream", "microphone", "system"), AUDIO_INPUTS)),
    ),
    "CHAT_MODE": (
        CHAT_MODES,
        dict(zip(("manual", "automatic"), CHAT_MODES)),
    ),
}


def normalize_env_choices(config: dict[str, str]) -> dict[str, str]:
    normalized = dict(config)
    for key, (choices, aliases) in _CHOICES.items():
        value = config.get(key, "").strip()
        value = aliases.get(value.lower(), value)
        if value and value not in choices:
            log.warning("Unsupported %s value; using the default choice.", key)
        normalized[key] = value if value in choices else choices[0]
    return normalized


def env_defaults(
    defaults: dict[str, Any], prefix: str, saved: Mapping[str, Any],
    env_file: Path | None,
) -> dict[str, Any]:
    values = dotenv_values(env_file) if env_file is not None else {}
    result = dict(defaults)
    for name, default in defaults.items():
        key = prefix + name.upper()
        if name in saved or key not in values:
            continue
        raw = values[key]
        if raw is None:
            raise ValueError(f"{key} requires a value.")
        try:
            if isinstance(default, bool):
                if raw.strip().lower() not in ("true", "false"):
                    raise ValueError("Expected true or false.")
                value = raw.strip().lower() == "true"
            elif isinstance(default, (int, float)):
                value = json.loads(raw)
                if type(value) not in (int, float) or (type(default) is int and type(value) is not int):
                    raise ValueError("Expected a number.")
            elif isinstance(default, (list, dict)):
                value = json.loads(raw)
                if not isinstance(value, type(default)):
                    raise ValueError("Wrong JSON type.")
            else:
                value = raw
        except (ValueError, TypeError) as error:
            raise ValueError(f"Invalid {key}: {error}") from error
        result[name] = value
    result.update(saved)
    return result


def overlay_position(env_file: Path | None) -> tuple[int, int] | None:
    values = dotenv_values(env_file) if env_file is not None else {}
    if not any(key in values for key in ("OVERLAY_X", "OVERLAY_Y")):
        return None
    if not all(key in values for key in ("OVERLAY_X", "OVERLAY_Y")):
        raise ValueError("OVERLAY_X and OVERLAY_Y must be specified together.")
    result = env_defaults({"x": 0, "y": 0}, "OVERLAY_", {}, env_file)
    return result["x"], result["y"]
