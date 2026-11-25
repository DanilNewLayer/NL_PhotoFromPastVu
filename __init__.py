# -*- coding: utf-8 -*-
"""Инициализация плагина NL_PhotoFromPastVu."""

from __future__ import annotations


def classFactory(iface):  # noqa: N802
    from .plugin import PhotoFromPastVuPlugin

    return PhotoFromPastVuPlugin(iface)
