# -*- coding: utf-8 -*-
"""Константы и сохранённые параметры плагина NL_PhotoFromPastVu.

Отдельного окна настроек нет: всё, что нужно менять пользователю
(папка, размер, шаблон имени), задаётся прямо в окне скачивания
и запоминается между запусками в QgsSettings.
"""

from __future__ import annotations

import os

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QStandardPaths

PLUGIN_NAME = "NL_PhotoFromPastVu"
PLUGIN_VERSION = "1.3.3"
PLUGIN_TITLE = "Фото из PastVu"

MENU_NAME = "&Модули newlayer.ru"
GROUP_NAME = "NL_PhotoFromPastVu"

HOMEPAGE = "https://github.com/DanilNewLayer/NL_PhotoFromPastVu#readme"
REPOSITORY = "https://github.com/DanilNewLayer/NL_PhotoFromPastVu"
TRACKER = "https://github.com/DanilNewLayer/NL_PhotoFromPastVu/issues"

API_URL = "https://api.pastvu.com/api2"
USER_AGENT = "NL_PhotoFromPastVu/1.3 (+QGIS; https://pastvu.com)"
REFERER = "https://pastvu.com/"

DEFAULT_LAYER_NAME = "Retro_Photo"
DEFAULT_TIMEOUT = 30

SIZE_ORIGINAL = "a"
SIZE_STANDARD = "d"
SIZE_THUMB = "h"

DEFAULT_FILENAME_TEMPLATE = "{year}_{cid}_{title}"
DEFAULT_DOWNLOAD_SIZE = SIZE_ORIGINAL

PREFIX = "nl_photofrompastvu"


def _location(kind: str) -> str:
    """Кросс-версионное получение стандартной папки Qt."""
    try:
        location_enum = getattr(QStandardPaths, "StandardLocation")
        location = getattr(location_enum, kind)
    except AttributeError:
        location = getattr(QStandardPaths, kind)
    return QStandardPaths.writableLocation(location)


def default_download_dir() -> str:
    """Папка по умолчанию: Изображения/PastVu (с запасными вариантами)."""
    pictures = _location("PicturesLocation")
    if not pictures:
        pictures = os.path.join(os.path.expanduser("~"), "Pictures")
    return os.path.normpath(os.path.join(pictures, "PastVu"))


def _settings() -> QgsSettings:
    return QgsSettings()


def get_value(key: str, default=None):
    raw = _settings().value(f"{PREFIX}/{key}", default)
    if isinstance(default, bool):
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    if raw is None:
        return default
    return str(raw)


def set_value(key: str, value) -> None:
    _settings().setValue(f"{PREFIX}/{key}", value)


def download_dir() -> str:
    folder = get_value("download_dir", "")
    return folder or default_download_dir()


def download_size() -> str:
    size = get_value("download_size", DEFAULT_DOWNLOAD_SIZE)
    return size if size in (SIZE_ORIGINAL, SIZE_STANDARD, SIZE_THUMB) else DEFAULT_DOWNLOAD_SIZE


def filename_template() -> str:
    return get_value("filename_template", DEFAULT_FILENAME_TEMPLATE) or DEFAULT_FILENAME_TEMPLATE


def overwrite_existing() -> bool:
    return bool(get_value("overwrite", False))
