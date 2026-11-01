"""Use the Streaming dashboard's local cookie login and platform chat APIs."""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from types import ModuleType
from typing import Optional, TypedDict
from urllib.parse import urlsplit

import requests
from .paths import ROOT, RESOURCE_ROOT
from .platforms import PLATFORMS


_STREAMING_ROOT = RESOURCE_ROOT / "Streaming" if getattr(sys, "frozen", False) else ROOT.parent / "Streaming"
_modules_cache: Optional[tuple[ModuleType, ModuleType, ModuleType, ModuleType]] = None


class LoginError(ValueError):
    """Cookie login could not be verified or the login helper is unavailable."""


class BilibiliQrLogin:
    """Bilibili web QR login without saving the QR token or cookies to disk."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com/",
        })
        self.key = ""

    def _request(self, endpoint: str, params: dict[str, str]) -> dict:
        try:
            response = self.session.get(
                f"https://passport.bilibili.com/x/passport-login/web/qrcode/{endpoint}",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise LoginError("二维码登录连接失败，请检查网络后重试。") from error
        if (
            not isinstance(payload, dict)
            or payload.get("code") != 0
            or not isinstance(payload.get("data"), dict)
        ):
            raise LoginError("Bilibili 未能完成二维码登录请求，请重试。")
        return payload["data"]

    def generate(self) -> bytes:
        import qrcode

        data = self._request("generate", {"source": "main-fe-header"})
        key, link = data.get("qrcode_key"), data.get("url")
        if not isinstance(key, str) or not key or not isinstance(link, str) or not link:
            raise LoginError("Bilibili 没有返回有效二维码，请重试。")
        self.key = key
        output = BytesIO()
        qrcode.make(link).save(output, format="PNG")
        return output.getvalue()

    def poll(self) -> tuple[str, dict[str, str]]:
        if not self.key:
            raise LoginError("请先生成二维码。")
        data = self._request(
            "poll", {"qrcode_key": self.key, "source": "main-fe-header"}
        )
        states = {86101: "scan", 86090: "confirm", 86038: "expired", 0: "done"}
        state = states.get(data.get("code"))
        if state is None:
            raise LoginError("Bilibili 返回了未知的二维码登录状态，请重试。")
        if state != "done":
            return state, {}
        cookies = {
            name: value
            for pair in urlsplit(str(data.get("url") or "")).query.split("&")
            if "=" in pair
            for name, value in [pair.split("=", 1)]
            if name in ("SESSDATA", "bili_jct", "DedeUserID") and value
        }
        cookies.update({
            name: value
            for name, value in self.session.cookies.get_dict().items()
            if name in ("SESSDATA", "bili_jct", "DedeUserID", "buvid3")
        })
        if not cookies.get("SESSDATA") or not cookies.get("bili_jct"):
            raise LoginError("扫码登录未返回完整凭证，请重新生成二维码。")
        return state, cookies

    def close(self) -> None:
        self.session.close()


def _modules() -> tuple[ModuleType, ModuleType, ModuleType, ModuleType]:
    global _modules_cache
    if _modules_cache is not None:
        return _modules_cache
    root = _STREAMING_ROOT
    if not (root / "src" / "browser_cookies.py").is_file():
        raise LoginError(
            "找不到 Streaming 登录组件；请将 Streaming 文件夹放在本应用旁边。"
        )
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        from src import bilibili, browser_cookies, user_login, youtube_web
    except ImportError as error:
        raise LoginError(
            "Streaming 登录组件缺少依赖；请先按照 Streaming 项目的说明安装依赖。"
        ) from error

    _modules_cache = browser_cookies, user_login, bilibili, youtube_web
    return _modules_cache


def read_firefox_cookies(platform: str) -> dict[str, str]:
    domain = _cookie_domain(platform)
    browser_cookies, _, _, _ = _modules()
    try:
        cookies = browser_cookies.read_cookies("firefox", domain)
    except Exception as error:
        raise LoginError(
            "无法读取 Firefox Cookie。请先在 Firefox 登录对应网站并关闭 Firefox 后重试，"
            "或改用粘贴 Cookie。"
        ) from error
    if not cookies:
        raise LoginError("Firefox 中没有找到该网站的登录 Cookie，请先登录网站。")
    return cookies


def parse_cookie_text(text: str, platform: str) -> dict[str, str]:
    domain = _cookie_domain(platform)
    browser_cookies, _, _, _ = _modules()
    try:
        cookies = browser_cookies.parse_cookie_text(text, domain)
    except Exception as error:
        raise LoginError("无法读取 Cookie 内容，请粘贴 Cookie 或导出的 JSON 文件内容。") from error
    if not cookies:
        raise LoginError("没有找到对应网站的 Cookie。")
    return cookies


def verify_login(platform: str, cookies: dict[str, str]) -> str:
    _cookie_domain(platform)
    browser_cookies, _, _, youtube_web = _modules()
    if platform == "bilibili":
        if not (cookies.get("SESSDATA") and cookies.get("bili_jct")):
            raise LoginError("Bilibili Cookie 缺少 SESSDATA 或 bili_jct。")
        result = browser_cookies.verify_bilibili_login(cookies)
    elif platform == "youtube":
        if not (
            cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID")
        ):
            raise LoginError("YouTube Cookie 中没有可用的登录凭证。")
        result = youtube_web.verify_login(cookies)
    else:
        if not cookies:
            raise LoginError("MissEvan Cookie 中没有可用的登录凭证。")
        result = _missevan_module().verify_login(dict(cookies))
    if not result.get("is_login"):
        raise LoginError("登录验证失败或网络暂时不可用；请重新登录后再试。")
    return str(result.get("uname") or result.get("name") or result.get("username") or "已登录")


def _cookie_domain(platform: str) -> str:
    if platform not in PLATFORMS:
        raise LoginError("不支持此登录平台。")
    return {"bilibili": "bilibili.com", "youtube": "youtube.com", "missevan": "missevan.com"}[platform]


def _missevan_module() -> ModuleType:
    _modules()
    try:
        from src import missevan
    except ImportError as error:
        raise LoginError("Streaming 登录组件缺少依赖；请先按照 Streaming 项目的说明安装依赖。") from error
    return missevan


def resolve_missevan_audio(room_id: str) -> str:
    module = _missevan_module()
    try:
        return module.get_live_audio_url(room_id)
    except (requests.RequestException, ValueError, RuntimeError, TypeError, KeyError) as error:
        raise RuntimeError("MissEvan 音频连接失败，请确认房间正在直播并检查网络。") from error


def send_missevan_message(
    room_id: str, message: str, cookies: dict[str, str],
) -> tuple[bool, str]:
    if not cookies:
        return False, "MissEvan Cookie 中没有可用的登录凭证。"
    _, user_login, _, _ = _modules()
    missevan = _missevan_module()
    with user_login.using({"missevan": dict(cookies)}):
        success, _ = missevan.send_message(room_id, message)
    return (
        (True, "发送成功") if success
        else (False, "MissEvan 发送失败，请检查登录状态和直播间权限。")
    )


def send_bilibili_danmaku(
    room_id: str,
    message: str,
    cookies: dict[str, str],
) -> tuple[bool, str]:
    _, user_login, bilibili, _ = _modules()
    with user_login.using({"bilibili": dict(cookies)}):
        return bilibili.send_danmaku(room_id, message)


def send_youtube_message(
    video_id: str,
    message: str,
    cookies: dict[str, str],
    page_id: str = "",
) -> tuple[bool, str]:
    _, user_login, _, youtube_web = _modules()
    with user_login.using({"youtube": dict(cookies), "youtube_page_id": page_id}):
        return youtube_web.send_message(video_id, message)


class YouTubeChannel(TypedDict):
    name: str
    handle: str
    page_id: str
    selected: bool


def list_youtube_channels(cookies: dict[str, str]) -> list[YouTubeChannel]:
    _, user_login, _, youtube_web = _modules()
    with user_login.using({"youtube": dict(cookies)}):
        result = youtube_web.list_channels(dict(cookies))
    if result.get("error"):
        raise LoginError("无法读取 YouTube 账号，请检查登录状态和网络后重试。")
    channels = result.get("channels")
    if not isinstance(channels, list) or not channels:
        raise LoginError("没有找到可用的 YouTube 账号或频道。")
    if any(
        not isinstance(channel, dict)
        or any(not isinstance(channel.get(key, ""), str) for key in ("name", "handle", "page_id"))
        or not isinstance(channel.get("selected", False), bool)
        for channel in channels
    ):
        raise LoginError("无法读取 YouTube 账号，请检查登录状态和网络后重试。")
    return [
        YouTubeChannel(
            name=channel.get("name", ""), handle=channel.get("handle", ""),
            page_id=channel.get("page_id", ""), selected=channel.get("selected", False),
        )
        for channel in channels
    ]


def current_youtube_channel(cookies: dict[str, str]) -> YouTubeChannel:
    channels = list_youtube_channels(cookies)
    selected = [channel for channel in channels if channel["selected"]]
    if len(selected) == 1:
        return selected[0]
    if not selected and len(channels) == 1:
        return channels[0]
    raise LoginError("YouTube 未指明当前频道，请使用切换账号手动选择。")
