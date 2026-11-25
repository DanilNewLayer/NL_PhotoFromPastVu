# -*- coding: utf-8 -*-
"""Безопасная работа с внешними URL плагина.

Плагин обращается только к публичным HTTPS-адресам PastVu. Проверка схемы,
домена и порта не даёт открыть file://, ftp:// или сторонний хост.
"""

from __future__ import annotations

import urllib.parse
import urllib.request

API_HOSTS = ("api.pastvu.com",)
IMAGE_HOSTS = ("img.pastvu.com", "pastvu.com")


def validate_https_url(url: str, allowed_hosts) -> str:
    """Проверяет URL и возвращает его нормализованный вариант.

    Разрешены только https, стандартный порт 443 и указанные домены
    (включая их поддомены). Учётные данные в URL запрещены.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL не задан.")
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme.lower() != "https":
        raise ValueError("Разрешены только HTTPS-адреса.")
    if parts.username or parts.password:
        raise ValueError("Учётные данные в URL запрещены.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("В URL не указан домен.")
    if not any(host == allowed or host.endswith("." + allowed)
               for allowed in allowed_hosts):
        raise ValueError(f"Домен {host} не разрешён.")
    if parts.port not in (None, 443):
        raise ValueError("Разрешён только HTTPS-порт 443.")
    return urllib.parse.urlunsplit(parts)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Не даёт redirect увести запрос на file:// или чужой домен."""

    def __init__(self, allowed_hosts):
        super().__init__()
        self.allowed_hosts = tuple(allowed_hosts)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        validate_https_url(target, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, target)


def open_url(request: urllib.request.Request, timeout: int, allowed_hosts):
    """Открывает только проверенный HTTPS-запрос с безопасными redirect."""
    validate_https_url(request.full_url, allowed_hosts)
    opener = urllib.request.build_opener(
        _SafeRedirectHandler(allowed_hosts)
    )
    return opener.open(request, timeout=timeout)
