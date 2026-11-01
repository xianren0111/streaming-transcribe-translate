"""API keys in ``.env`` protected with Windows DPAPI (current Windows user only).

Each secret ``NAME`` is stored as base64 DPAPI ciphertext under ``NAME_DPAPI`` and the
plaintext ``NAME`` entry is left blank. A plaintext value found on load is migrated.
Values are never logged or printed.
"""

from __future__ import annotations

import base64
import logging
import sys
from pathlib import Path
from typing import Mapping, Optional

log = logging.getLogger(__name__)

SECRET_KEYS = ("OPENAI_API_KEY", "JEV_API_KEY")
SUFFIX = "_DPAPI"
_ENTROPY = b"streaming-transcribe-translate/api-key"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
DECRYPT_FAILED_TITLE = "无法读取已保存的 API Key"
DECRYPT_FAILED_MESSAGE = (
    "已保存的 API Key 只能由保存它的 Windows 账户解密（可能换了电脑或账户）。"
    "请在「设置 → 翻译」重新填写 API Key 并保存。"
)


class SecretStoreError(Exception):
    """Protecting or unprotecting a secret failed (the message never contains it)."""


def available() -> bool:
    return sys.platform == "win32"


def _blob_functions():
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    def blob(data: bytes) -> tuple[DATA_BLOB, object]:
        buffer = ctypes.create_string_buffer(data, len(data))
        return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    def take(result: DATA_BLOB) -> bytes:
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))

    return ctypes, DATA_BLOB, crypt32, blob, take


def _crypt_protect(data: bytes) -> bytes:
    ctypes, DATA_BLOB, crypt32, blob, take = _blob_functions()
    data_in, _keep = blob(data)
    entropy, _keep_entropy = blob(_ENTROPY)
    result = DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(data_in), "api-key", ctypes.byref(entropy), None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result),
    ):
        raise SecretStoreError(f"CryptProtectData failed ({ctypes.GetLastError()})")
    return take(result)


def _crypt_unprotect(data: bytes) -> bytes:
    ctypes, DATA_BLOB, crypt32, blob, take = _blob_functions()
    data_in, _keep = blob(data)
    entropy, _keep_entropy = blob(_ENTROPY)
    result = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result),
    ):
        raise SecretStoreError(f"CryptUnprotectData failed ({ctypes.GetLastError()})")
    return take(result)


def protect(text: str) -> str:
    """Encrypt ``text`` for the current Windows user; returns base64 text."""
    return base64.b64encode(_crypt_protect(text.encode("utf-8"))).decode("ascii")


def unprotect(encoded: str) -> str:
    """Decrypt base64 DPAPI ciphertext created by :func:`protect`."""
    try:
        raw = base64.b64decode(encoded.strip(), validate=True)
        return _crypt_unprotect(raw).decode("utf-8")
    except SecretStoreError:
        raise
    except (ValueError, UnicodeDecodeError) as error:
        raise SecretStoreError("stored value is not valid DPAPI data") from error
    except OSError as error:
        raise SecretStoreError(f"DPAPI unavailable ({type(error).__name__})") from error


def env_updates(values: Mapping[str, str]) -> dict[str, str]:
    """Map in-memory config values to the entries written to ``.env``.

    Secrets become ``NAME_DPAPI`` ciphertext and a blank plaintext ``NAME``.
    Raises :class:`OSError` when a secret cannot be protected so callers keep
    their existing "could not save" handling.
    """
    result: dict[str, str] = {}
    for name, value in values.items():
        if name in SECRET_KEYS and available():
            try:
                result[name + SUFFIX] = protect(value) if value else ""
            except SecretStoreError as error:
                raise OSError("无法加密保存 API Key。") from error
            result[name] = ""
        else:
            result[name] = value
    return result


def write_env(env_file: Path, values: Mapping[str, str]) -> None:
    """Write config values to ``.env``, encrypting secrets."""
    from dotenv import set_key

    for name, value in env_updates(values).items():
        success, _, _ = set_key(str(env_file), name, value, quote_mode="always")
        if not success:
            raise OSError(f"无法保存配置项 {name}。")


def load_secrets(
    env_file: Optional[Path], values: Mapping[str, Optional[str]], migrate: bool = True,
) -> tuple[dict[str, str], list[str]]:
    """Return ``(secrets, failed_names)`` from raw ``.env`` values.

    Plaintext secrets are encrypted into ``NAME_DPAPI`` and blanked in ``env_file``
    (when ``migrate``). Ciphertext that cannot be decrypted yields an empty secret
    and its name in ``failed_names``; it is left in the file until replaced.
    """
    secrets: dict[str, str] = {}
    failed: list[str] = []
    to_migrate: dict[str, str] = {}
    for name in SECRET_KEYS:
        plain = str(values.get(name) or "")
        encrypted = str(values.get(name + SUFFIX) or "")
        if plain:
            secrets[name] = plain
            if available():
                to_migrate[name] = plain
        elif encrypted:
            if not available():
                failed.append(name)
                secrets[name] = ""
                continue
            try:
                secrets[name] = unprotect(encrypted)
            except SecretStoreError as error:
                log.warning("Saved %s could not be decrypted: %s", name, error)
                failed.append(name)
                secrets[name] = ""
        else:
            secrets[name] = ""
    if migrate and to_migrate and env_file is not None and Path(env_file).exists():
        try:
            write_env(Path(env_file), to_migrate)
            log.info("Moved %s plaintext secret(s) to Windows DPAPI storage", len(to_migrate))
        except OSError as error:
            log.warning("Could not migrate plaintext secrets: %s", type(error).__name__)
    return secrets, failed


def read_env_secrets(env_file: Path) -> tuple[dict[str, str], list[str]]:
    """Read ``env_file`` and return its decrypted secrets (migrating plaintext)."""
    from dotenv import dotenv_values

    values = dotenv_values(env_file) if Path(env_file).exists() else {}
    return load_secrets(env_file, values)
