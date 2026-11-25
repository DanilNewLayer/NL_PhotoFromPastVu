# -*- coding: utf-8 -*-
"""Фоновые задачи: поиск фото и скачивание изображений."""

from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from qgis.core import QgsMessageLog, QgsTask, Qgis
from qgis.PyQt.QtCore import pyqtSignal

from .api import USER_AGENT, REFERER, photo_url
from .security import IMAGE_HOSTS, open_url, validate_https_url

_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


@dataclass
class DownloadItem:
    fid: int
    cid: object
    file: str
    year: object
    year2: object
    title: str
    dir: str


class SearchTask(QgsTask):
    """Запрос photo.getByBounds в отдельном потоке QGIS."""

    def __init__(self, client, geometry, zoom, year=None, year2=None,
                 is_painting=False):
        super().__init__("Поиск фотографий PastVu", QgsTask.Flag.CanCancel)
        self.client = client
        self.geometry = geometry
        self.zoom = zoom
        self.year = year
        self.year2 = year2
        self.is_painting = is_painting
        self.photos = []
        self.error = None

    def run(self):
        try:
            self.photos = self.client.get_by_bounds(
                self.geometry,
                self.zoom,
                year=self.year,
                year2=self.year2,
                is_painting=self.is_painting,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            self.error = exc
            return False


class _Cancelled(Exception):
    pass


class DownloadTask(QgsTask):
    """Скачивает изображения и складывает пути в results (fid -> путь)."""

    statusText = pyqtSignal(str)
    fileDone = pyqtSignal(object, str)
    fileFailed = pyqtSignal(object, str)

    def __init__(self, items, folder, size, template, overwrite=False):
        super().__init__("Скачивание фотографий PastVu", QgsTask.Flag.CanCancel)
        self.items = list(items)
        self.folder = folder
        self.size = size
        self.template = template or "{year}_{cid}_{title}"
        self.overwrite = bool(overwrite)
        self.results = {}
        self.failures = {}
        self.skipped = 0

    def run(self):
        total = max(len(self.items), 1)
        for index, item in enumerate(self.items):
            if self.isCanceled():
                return False
            self.setProgress(index * 100.0 / total)
            try:
                self._process_item(item, index, total)
            except _Cancelled:
                return False
            except Exception as exc:  # noqa: BLE001
                self.failures[item.fid] = str(exc)
                self.statusText.emit(
                    f"Ошибка: {item.title or item.cid or item.fid} — {exc}"
                )
                self.fileFailed.emit(item.fid, str(exc))
        self.setProgress(100)
        return True

    def _process_item(self, item, index, total):
        if not item.file:
            raise RuntimeError("у фотографии нет поля file")
        target = self._target_path(item)
        if os.path.exists(target) and not self.overwrite:
            self.results[item.fid] = target
            self.skipped += 1
            self.fileDone.emit(item.fid, target)
            return
        if self.isCanceled():
            raise _Cancelled()
        label = item.title.strip() or str(item.cid or item.fid)
        self.statusText.emit(f"Скачиваю {index + 1} из {total}: {label}")
        self._download(photo_url(item.file, self.size), target)
        self.results[item.fid] = target
        self.fileDone.emit(item.fid, target)

    def _target_path(self, item) -> str:
        values = {
            "cid": "" if item.cid is None else item.cid,
            "year": "" if item.year is None else item.year,
            "year2": "" if item.year2 is None else item.year2,
            "title": _sanitize(item.title, 70),
            "dir": item.dir or "",
        }
        try:
            name = self.template.format(**values)
        except (KeyError, IndexError, ValueError):
            name = "{cid}_{title}".format(**values)
        name = _sanitize(name, 120) or f"photo_{item.fid}"
        extension = _extension(item.file)
        if not name.lower().endswith(extension):
            name += extension
        return os.path.join(self.folder, name)

    def _download(self, url: str, target: str):
        url = validate_https_url(url, IMAGE_HOSTS)
        temporary = target + ".part"
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "Accept": "image/*,*/*;q=0.8",
        })
        try:
            with open_url(request, timeout=90, allowed_hosts=IMAGE_HOSTS) as response, \
                    open(temporary, "wb") as handle:
                content_type = (response.headers.get("Content-Type") or "").lower()
                if content_type and not content_type.startswith(
                        ("image/", "application/octet-stream")):
                    raise RuntimeError(f"сервер вернул не изображение ({content_type})")
                while True:
                    if self.isCanceled():
                        raise _Cancelled()
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    handle.write(chunk)
            if os.path.getsize(temporary) < 128:
                raise RuntimeError("файл изображения пустой")
            os.replace(temporary, target)
        except Exception:
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError as exc:
                QgsMessageLog.logMessage(
                    f"Не удалось удалить временный файл {temporary}: {exc}",
                    "NL_PhotoFromPastVu", Qgis.MessageLevel.Info,
                )
            raise


def _extension(file_value: str) -> str:
    path = urllib.parse.urlparse(str(file_value)).path
    extension = os.path.splitext(path)[1].lower()
    return extension if extension in _ALLOWED_EXTENSIONS else ".jpg"


def _sanitize(name: str, max_length: int) -> str:
    name = _INVALID_FILENAME.sub("_", str(name or ""))
    name = re.sub(r"\s+", " ", name).strip(" .")
    name = name[:max_length].rstrip(" .")
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        name = "_" + name
    return name

