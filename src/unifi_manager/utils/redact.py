"""Общий рекурсивный санитайзер секретов для shared use (audit full, export).

UniFi `/stat/device` payload несёт секреты устройств top-level (x_authkey,
x_aes_gcm, x_ssh_hostkey_fingerprint, x_vwirekey, ...) и потенциально вложенно.
`redact_secrets` рекурсивно вырезает любой ключ, чьё имя похоже на секрет —
единая политика для всех путей, отдающих сырые dict наружу (JSON/CSV/лог).
"""

from __future__ import annotations

from typing import Any

# Любой ключ, содержащий один из токенов (case-insensitive), считается секретным.
SECRET_TOKENS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "auth",
    "fingerprint",
    "aes",
    "vwire",
    "ssh",
    "cert",
    "private",
    "key",
)


def is_secret_key(key: str) -> bool:
    """True если имя ключа похоже на секрет (по подстроке, case-insensitive)."""
    k = key.lower()
    return any(tok in k for tok in SECRET_TOKENS)


def redact_secrets(value: Any) -> Any:
    """Рекурсивно вырезает секретные ключи из dict/list-структур.

    dict: ключи, проходящие is_secret_key, удаляются целиком; значения остальных
    рекурсивно санитизируются. list: каждый элемент санитизируется. Скаляры — as-is.
    """
    if isinstance(value, dict):
        return {
            k: redact_secrets(v)
            for k, v in value.items()
            if not (isinstance(k, str) and is_secret_key(k))
        }
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    return value
