"""Localhost browser interface: static pages, JSON API and Server-Sent Events."""

from __future__ import annotations

import hmac
import json
import logging
import queue
import secrets
import sys
import threading
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlsplit

from dotenv import dotenv_values

from .app_controller import AppController, UserError
from .paths import LOG_FILE, LOGS_ROOT, ROOT, RESOURCE_ROOT
from .ui_translations import TRANSLATIONS

log = logging.getLogger(__name__)

WEB_DIR = RESOURCE_ROOT / "streaming_transcribe_translate" / "web"
URL_FILE = ROOT / "web_url.txt"
PREFERRED_PORT = 8765
APP_ID = "streaming-transcribe-translate"
MAX_BODY = 2_000_000
PAGES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/overlay": ("overlay.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
    "/overlay.js": ("overlay.js", "text/javascript; charset=utf-8"),
}
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


def configured_port() -> int:
    value = (dotenv_values(ROOT / ".env").get("WEB_PORT") or "").strip()
    if not value:
        return PREFERRED_PORT
    if not value.isascii() or not value.isdecimal() or not 0 <= int(value) <= 65535:
        raise ValueError("WEB_PORT must be an integer from 0 to 65535 (0 selects a free port).")
    return int(value)


class _Broker:
    """Fan-out of controller events to every connected browser page."""

    def __init__(self) -> None:
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def add(self) -> queue.Queue:
        client: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._clients.add(client)
        return client

    def remove(self, client: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(client)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.put_nowait(event)
            except queue.Full:
                try:
                    while True:
                        client.get_nowait()
                except queue.Empty:
                    pass
                client.put_nowait({"type": "resync"})


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # On Windows reuse would let two apps share one port.


class WebApp:
    """Owns the HTTP server, token and controller wiring."""

    def __init__(
        self,
        controller: Optional[AppController],
        *,
        token: Optional[str] = None,
        port: int = PREFERRED_PORT,
        startup_error: Optional[dict[str, str]] = None,
        web_dir: Path = WEB_DIR,
    ) -> None:
        self.controller = controller
        self.token = token or secrets.token_urlsafe(24)
        self.startup_error = startup_error
        self.web_dir = Path(web_dir)
        self.broker = _Broker()
        self.quit_event = threading.Event()
        handler = _make_handler(self)
        try:
            self.httpd = _Server(("127.0.0.1", port), handler)
        except OSError:
            log.warning("Could not bind the preferred web port %d; selecting a free port.", port)
            self.httpd = _Server(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.httpd.web_app = self  # type: ignore[attr-defined]
        self.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self._thread: Optional[threading.Thread] = None
        self.overlay: Any = None  # Desktop subtitle window manager (set by main()).
        self._unsubscribe: Callable[[], None] = lambda: None
        if controller is not None:
            self._unsubscribe = controller.subscribe(self.broker.publish)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._unsubscribe()
        self.httpd.shutdown()
        self.httpd.server_close()


def _make_handler(web: WebApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SubtitleApp"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return  # URLs carry the session token; never log them.

        # -- plumbing ------------------------------------------------------

        def _send(self, status: int, body: bytes, content_type: str, extra: Optional[dict] = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: Any, status: int = 200) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _error(self, title: str, message: str, status: int = 400, action: str = "") -> None:
            self._json({"ok": False, "error": {"title": title, "message": message, "action": action}}, status)

        def _authorized(self, query: dict[str, list[str]]) -> bool:
            if self.headers.get("Host", "") not in web.allowed_hosts:
                self._send(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain; charset=utf-8")
                return False
            supplied = self.headers.get("X-Token") or (query.get("t") or [""])[0]
            if not hmac.compare_digest(supplied.encode(), web.token.encode()):
                self._send(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain; charset=utf-8")
                return False
            return True

        def _body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                raise UserError("请求无效", "提交的内容无法读取。")
            if not length:
                return {}
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as error:
                raise UserError("请求无效", "提交的内容无法读取。") from error
            if not isinstance(data, dict):
                raise UserError("请求无效", "提交的内容无法读取。")
            return data

        # -- verbs ---------------------------------------------------------

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            if not self._authorized(query):
                return
            path = parts.path
            try:
                if path in PAGES:
                    name, content_type = PAGES[path]
                    text = (web.web_dir / name).read_text(encoding="utf-8")
                    self._send(200, text.replace("__TOKEN__", web.token).encode("utf-8"), content_type)
                elif path == "/api/ping":
                    self._json({"app": APP_ID})
                elif path == "/api/i18n":
                    self._json(TRANSLATIONS)
                elif path == "/api/snapshot":
                    self._json(self._snapshot())
                elif path == "/api/events":
                    self._events()
                elif path == "/api/records":
                    self._json({
                        "sessions": self._controller().list_export_sessions(),
                        "records": self._controller().records_hint(),
                    })
                elif path == "/api/login/qr/status":
                    self._json(self._controller().qr_status((query.get("id") or [""])[0]))
                else:
                    self._send(404, b"Not found", "text/plain; charset=utf-8")
            except UserError as error:
                self._error(error.title, error.message, action=error.action)
            except (BrokenPipeError, ConnectionError):
                pass
            except Exception:
                log.exception("Web request failed")
                self._error("出错了", "发生了意外错误，请重试。", 500)

        def do_POST(self) -> None:
            parts = urlsplit(self.path)
            if not self._authorized(parse_qs(parts.query)):
                return
            try:
                handler = ROUTES.get(parts.path)
                if handler is None:
                    self._send(404, b"Not found", "text/plain; charset=utf-8")
                    return
                self._json(handler(self, self._body()))
            except UserError as error:
                self._error(error.title, error.message, action=error.action)
            except Exception:
                log.exception("Web request failed")
                self._error("出错了", "发生了意外错误，请重试。", 500)

        # -- helpers -------------------------------------------------------

        def _controller(self) -> AppController:
            if web.controller is None:
                raise UserError("同传字幕无法启动", (web.startup_error or {}).get("message", ""))
            return web.controller

        def _snapshot(self) -> dict[str, Any]:
            if web.controller is None:
                return {"startup_error": web.startup_error or {"title": "同传字幕无法启动", "message": ""}}
            snapshot = web.controller.snapshot()
            snapshot["startup_notices"] = list(web.controller.startup_notices)
            return snapshot

        def _events(self) -> None:
            client = web.broker.add()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                self._write_event({"type": "state", "state": self._snapshot()})
                while not web.quit_event.is_set():
                    try:
                        events = [client.get(timeout=10)]
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    while True:
                        try:
                            events.append(client.get_nowait())
                        except queue.Empty:
                            break
                    # Only the newest full state matters; other events keep their order.
                    last_state = max((i for i, e in enumerate(events) if e.get("type") == "state"), default=-1)
                    for index, event in enumerate(events):
                        if event.get("type") != "state" or index == last_state:
                            self._write_event(event)
            except (BrokenPipeError, ConnectionError, OSError):
                pass
            finally:
                web.broker.remove(client)

        def _write_event(self, event: dict[str, Any]) -> None:
            data = json.dumps(event, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
            self.wfile.flush()

    return Handler


def _state(handler: Any, controller: Optional[AppController] = None) -> dict[str, Any]:
    return {"ok": True, "state": (controller or handler._controller()).snapshot()}


def _route_home(handler: Any, body: dict) -> dict:
    handler._controller().update_home(body)
    return _state(handler)


def _route_start(handler: Any, body: dict) -> dict:
    confirm = body.pop("confirm_auto", False) is True
    handler._controller().start_session(body, confirm_auto=confirm)
    return _state(handler)


def _route_stop(handler: Any, body: dict) -> dict:
    handler._controller().stop_session()
    return _state(handler)


def _route_draft(handler: Any, body: dict) -> dict:
    handler._controller().set_draft(str(body.get("text", "")))
    return {"ok": True}


def _route_send(handler: Any, body: dict) -> dict:
    text = body.get("text")
    handler._controller().send_pending_chat(text if isinstance(text, str) else None)
    return _state(handler)


def _route_skip(handler: Any, body: dict) -> dict:
    handler._controller().skip_pending_chat(str(body["text"]) if "text" in body else None)
    return _state(handler)


def _route_microphones(handler: Any, body: dict) -> dict:
    return {"ok": True, **handler._controller().refresh_microphones()}


def _route_login_cookies(handler: Any, body: dict) -> dict:
    result = handler._controller().login_with_cookies(
        str(body.get("platform", "")), str(body.get("text", ""))
    )
    return {"ok": True, **result}


def _route_login_firefox(handler: Any, body: dict) -> dict:
    result = handler._controller().login_with_cookies(str(body.get("platform", "")), firefox=True)
    return {"ok": True, **result}


def _route_qr_start(handler: Any, body: dict) -> dict:
    return {"ok": True, **handler._controller().start_qr_login()}


def _route_qr_cancel(handler: Any, body: dict) -> dict:
    handler._controller().cancel_qr_login()
    return {"ok": True}


def _route_youtube_confirm(handler: Any, body: dict) -> dict:
    result = handler._controller().confirm_youtube_account(str(body.get("import_id", "")), body.get("index"))
    return {"ok": True, **result}


def _route_youtube_cancel(handler: Any, body: dict) -> dict:
    handler._controller().cancel_youtube_import()
    return {"ok": True}


def _route_save_api(handler: Any, body: dict) -> dict:
    handler._controller().save_api_settings(
        str(body.get("base", "")), str(body.get("model", "")), str(body.get("key", ""))
    )
    return _state(handler)


def _route_clear_key(handler: Any, body: dict) -> dict:
    handler._controller().clear_saved_key()
    return _state(handler)


def _route_test(handler: Any, body: dict) -> dict:
    result = handler._controller().test_connection(
        str(body.get("base", "")), str(body.get("model", "")), str(body.get("key", ""))
    )
    return {"ok": True, **result}


def _route_detect(handler: Any, body: dict) -> dict:
    models = handler._controller().detect_models(str(body.get("base", "")), str(body.get("key", "")))
    return {"ok": True, "models": models}


def _route_subtitle(handler: Any, body: dict) -> dict:
    handler._controller().save_subtitle_settings(body)
    return _state(handler)


def _route_open_records(handler: Any, body: dict) -> dict:
    handler._controller().open_records()
    return {"ok": True}


def _route_export(handler: Any, body: dict) -> dict:
    result = handler._controller().export_sent(str(body.get("session", "")))
    return {"ok": True, **result}


def _route_interface(handler: Any, body: dict) -> dict:
    handler._controller().set_interface(body.get("theme"), body.get("language"))
    return _state(handler)


def _route_quit(handler: Any, body: dict) -> dict:
    web = handler.server.web_app
    threading.Timer(0.3, web.quit_event.set).start()
    return {"ok": True}


def _overlay(handler: Any) -> Any:
    overlay = getattr(handler.server.web_app, "overlay", None)
    if overlay is None:
        raise UserError("悬浮窗不可用", "字幕悬浮窗在此模式下不可用，请使用下面的浏览器字幕页。")
    return overlay


def _route_overlay_open(handler: Any, body: dict) -> dict:
    _overlay(handler).open()
    return {"ok": True}

def _route_records_folder(handler: Any, body: dict) -> dict:
    _overlay(handler).choose_records_folder()
    return {"ok": True}


def _route_overlay_close(handler: Any, body: dict) -> dict:
    _overlay(handler).close()
    return {"ok": True}


def _route_overlay_unlock(handler: Any, body: dict) -> dict:
    _overlay(handler).unlock()
    return {"ok": True}


def _route_pause(handler: Any, body: dict) -> dict:
    handler._controller().toggle_pause()
    return _state(handler)


ROUTES: dict[str, Callable[[Any, dict], dict]] = {
    "/api/home": _route_home,
    "/api/start": _route_start,
    "/api/stop": _route_stop,
    "/api/draft": _route_draft,
    "/api/chat/send": _route_send,
    "/api/chat/skip": _route_skip,
    "/api/microphones/refresh": _route_microphones,
    "/api/login/cookies": _route_login_cookies,
    "/api/login/firefox": _route_login_firefox,
    "/api/login/qr/start": _route_qr_start,
    "/api/login/qr/cancel": _route_qr_cancel,
    "/api/login/youtube/confirm": _route_youtube_confirm,
    "/api/login/youtube/cancel": _route_youtube_cancel,
    "/api/settings/api": _route_save_api,
    "/api/settings/clear-key": _route_clear_key,
    "/api/settings/test": _route_test,
    "/api/settings/subtitle": _route_subtitle,
    "/api/models/detect": _route_detect,
    "/api/records/open": _route_open_records,
    "/api/records/folder": _route_records_folder,
    "/api/records/export": _route_export,
    "/api/interface": _route_interface,
    "/api/overlay/open": _route_overlay_open,
    "/api/overlay/close": _route_overlay_close,
    "/api/overlay/unlock": _route_overlay_unlock,
    "/api/pause": _route_pause,
    "/api/quit": _route_quit,
}


def _running_instance_url() -> Optional[str]:
    """Return the saved URL when an earlier instance still answers on it."""
    try:
        url = URL_FILE.read_text(encoding="utf-8").strip()
        parts = urlsplit(url)
        token = (parse_qs(parts.query).get("t") or [""])[0]
        if parts.hostname != "127.0.0.1" or not token or not parts.port:
            return None
        request = urllib.request.Request(
            f"http://127.0.0.1:{parts.port}/api/ping", headers={"X-Token": token}
        )
        with urllib.request.urlopen(request, timeout=1.5) as response:
            return url if json.load(response).get("app") == APP_ID else None
    except Exception:
        return None


def _say(text: str) -> None:
    # pythonw has no console: sys.stdout is None there.
    if sys.stdout is not None:
        print(text, flush=True)


def _wait_for_quit(web: WebApp, controller: Optional[AppController]) -> None:
    """Run the desktop subtitle window's Tk loop on the main thread until quit.

    Without Tk (or without a controller) this simply waits for the quit event.
    """
    manager = None
    if controller is not None:
        try:
            from .overlay_window import OverlayManager

            manager = OverlayManager(controller, web.quit_event)
        except Exception as error:
            log.warning("Desktop subtitle window unavailable: %s", type(error).__name__)
            manager = None
    if manager is None:
        while not web.quit_event.wait(0.5):
            pass
        return
    web.overlay = manager
    try:
        manager.run()
    finally:
        web.overlay = None


def main(argv: Optional[list[str]] = None) -> None:
    existing = _running_instance_url()
    if existing:
        _say(f"Already running: {existing}")
        webbrowser.open(existing)
        return
    LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=handlers,
    )
    controller: Optional[AppController] = None
    startup_error = None
    port = PREFERRED_PORT
    try:
        port = configured_port()
        controller = AppController()
        controller.start_monitor()
    except Exception as error:
        log.exception("Could not initialize the application")
        startup_error = {"title": "同传字幕无法启动", "message": f"应用初始化失败：{error}"}
    web = WebApp(controller, port=port, startup_error=startup_error)
    web.start()
    try:
        URL_FILE.write_text(web.url + "\n", encoding="utf-8")
    except OSError:
        log.warning("Could not write web_url.txt")
    _say(f"Subtitle app is running at: {web.url}")
    _say("Press Ctrl+C here, or click 'Quit app' in the page, to stop.")
    webbrowser.open(web.url)
    try:
        _wait_for_quit(web, controller)
    except KeyboardInterrupt:
        pass
    finally:
        if controller is not None:
            controller.close()
        web.stop()
        try:
            if URL_FILE.read_text(encoding="utf-8").strip() == web.url:
                URL_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main(sys.argv[1:])
