"""Validated live-room routing shared by the UI and stream configuration."""

import re
from urllib.parse import urlparse


PLATFORMS = {"bilibili": "哔哩哔哩", "youtube": "YouTube", "missevan": "猫耳FM"}
PLATFORM_IDS = {"bilibili": "Bilibili", "youtube": "YouTube", "missevan": "MissEvan"}


def platform_key(value: str) -> str | None:
    return next(
        (key for key, name in PLATFORMS.items() if value in (key, name, PLATFORM_IDS[key])),
        None,
    )


def detect_platform(text: str) -> str | None:
    text = text.strip()
    if not text or text.isdecimal() or re.fullmatch(r"[A-Za-z0-9_-]{6,}", text):
        return None
    parsed = urlparse(text if "://" in text else "https://" + text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        raise ValueError("请输入有效的直播间链接，不要包含账号密码。")
    if host == "live.bilibili.com":
        return "bilibili"
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
        return "youtube"
    if host in ("missevan.com", "www.missevan.com", "fm.missevan.com"):
        return "missevan"
    raise ValueError("不支持此直播间地址；请选择哔哩哔哩、YouTube 或猫耳FM的直播链接。")


def missevan_room_id(text: str) -> str:
    text = text.strip()
    if text.isdecimal():
        return text
    if detect_platform(text) != "missevan":
        raise ValueError("请输入猫耳FM直播间链接或数字房间号。")
    parsed = urlparse(text if "://" in text else "https://" + text)
    match = re.fullmatch(r"/live/(\d+)/?", parsed.path)
    if not match:
        raise ValueError("请输入猫耳FM直播间链接或数字房间号。")
    return match[1]
