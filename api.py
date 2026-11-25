# -*- coding: utf-8 -*-
"""Клиент публичного API PastVu (https://docs.pastvu.com/dev/api)."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from .config import API_URL, DEFAULT_TIMEOUT, REFERER, USER_AGENT

SIZE_PREFIXES = {
    "a": "https://img.pastvu.com/a/",
    "d": "https://img.pastvu.com/d/",
    "h": "https://img.pastvu.com/h/",
}

API_ERROR_MESSAGES = {
    "BAD_PARAMS": "PastVu отклонил параметры запроса.",
    "NO_SUCH_PHOTO": "Фотография не найдена или недоступна.",
    "COMMENT_NO_OBJECT": "Объект не найден или недоступен.",
}


class PastVuError(Exception):
    """Понятная пользователю ошибка сети или API PastVu."""


def photo_url(file_value, size: str = "d") -> str:
    """Собирает прямой адрес изображения по полю file из ответа API."""
    if not file_value:
        return ""
    file_value = str(file_value).strip()
    if file_value.startswith(("http://", "https://")):
        return file_value
    prefix = SIZE_PREFIXES.get(size, SIZE_PREFIXES["d"])
    return prefix + file_value.lstrip("/")


def _http_message(code: int) -> str:
    if code == 403:
        return ("PastVu запретил доступ (403). Проверьте прокси, VPN "
                "или антивирус, который может подменять сертификат.")
    if code == 404:
        return "Адрес API PastVu не найден (404)."
    if code == 429:
        return "Слишком много запросов к PastVu. Подождите немного и повторите."
    if code >= 500:
        return f"Сервер PastVu временно недоступен ({code})."
    return f"Ошибка HTTP {code} при запросе к PastVu."


def _network_message(exc) -> str:
    reason = getattr(exc, "reason", exc)
    text = str(reason)
    low = text.lower()
    if "timed out" in low or isinstance(exc, (socket.timeout, TimeoutError)):
        return ("PastVu не ответил вовремя. Проверьте интернет и повторите поиск.")
    if ("name or service not known" in low or "getaddrinfo" in low
            or "nodename nor servname" in low or "temporary failure in name resolution" in low):
        return "Нет соединения с api.pastvu.com. Проверьте интернет."
    if "certificate" in low or "ssl" in low:
        return "Не удалось проверить сертификат PastVu. Проверьте антивирус или прокси."
    return f"Не удалось связаться с PastVu: {text}"


def _parse_api_error(body: str):
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return None, None
    if isinstance(data, dict) and data.get("code"):
        return str(data["code"]), data.get("message")
    return None, None


def dedupe_photos(photos):
    """Убирает повторы по cid, сохраняя порядок ответа."""
    result = []
    seen = set()
    for photo in photos or []:
        if not isinstance(photo, dict):
            continue
        cid = photo.get("cid")
        if cid is not None:
            if cid in seen:
                continue
            seen.add(cid)
        result.append(photo)
    return result


class PastVuClient:
    """Минимальный клиент: только то, что нужно плагину."""

    def __init__(self, api_url: str = API_URL, timeout: int = DEFAULT_TIMEOUT):
        self.api_url = (api_url or API_URL).strip()
        self.timeout = int(timeout or DEFAULT_TIMEOUT)

    def get_by_bounds(self, geometry, z: int, year=None, year2=None,
                      is_painting: bool = False):
        """Возвращает все фотографии внутри GeoJSON-полигона.

        localWork=True — сервер не кластеризует и отдаёт каждый объект.
        """
        params = {
            "geometry": geometry,
            "z": int(z),
            "localWork": True,
        }
        if is_painting:
            params["isPainting"] = True
        if year is not None and year2 is not None:
            params["year"] = int(year)
            params["year2"] = int(year2)
        result = self._call("photo.getByBounds", params)
        photos = list(result.get("photos") or [])
        # На случай, если сервер всё же вернёт кластеры, забираем обложки.
        for cluster in result.get("clusters") or []:
            cover = cluster.get("p") if isinstance(cluster, dict) else None
            if isinstance(cover, dict):
                photos.append(cover)
        return dedupe_photos(photos)

    def test_connection(self) -> bool:
        """Проверка сети: ближайшее фото к центру Москвы."""
        result = self._call("photo.giveNearestPhotos", {
            "geo": [55.7558, 37.6173],
            "limit": 1,
        })
        return bool(result.get("photos"))

    def _call(self, method: str, params: dict) -> dict:
        payload = json.dumps(
            {"method": method, "params": params}, ensure_ascii=False
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
        }
        last_error = None
        raw = b""
        for attempt in range(2):
            request = urllib.request.Request(
                self.api_url, data=payload, method="POST", headers=headers
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                break
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    pass
                code, message = _parse_api_error(body)
                if code:
                    raise PastVuError(
                        API_ERROR_MESSAGES.get(code) or message
                        or f"Ошибка API PastVu: {code}"
                    ) from exc
                if exc.code in (429, 500, 502, 503, 504) and attempt == 0:
                    last_error = exc
                    continue
                raise PastVuError(_http_message(exc.code)) from exc
            except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
                last_error = exc
                if attempt == 0:
                    continue
                raise PastVuError(_network_message(exc)) from exc
        else:  # pragma: no cover - цикл всегда прерывается break/raise
            raise PastVuError(_network_message(last_error))

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PastVuError("PastVu вернул ответ, который не удалось разобрать.") from exc
        if not isinstance(data, dict):
            raise PastVuError("Неожиданный формат ответа PastVu.")
        if data.get("code"):
            code = str(data["code"])
            raise PastVuError(
                API_ERROR_MESSAGES.get(code) or data.get("message")
                or f"Ошибка API PastVu: {code}"
            )
        result = data.get("result")
        if not isinstance(result, dict):
            raise PastVuError("В ответе PastVu нет блока result.")
        return result
