# -*- coding: utf-8 -*-
"""Точка входа плагина NL_PhotoFromPastVu."""

from __future__ import annotations

import os

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QMenu, QMessageBox

try:
    from qgis.PyQt.QtWidgets import QAction
except ImportError:  # Qt6
    from qgis.PyQt.QtGui import QAction

from . import config
from .dialog import PhotoFromPastVuDialog


class PhotoFromPastVuPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dialog = None
        self.menu = None
        self.action_search = None
        self.plugin_dir = os.path.dirname(__file__)

    # ------------------------------------------------------------- lifecycle
    def initGui(self):  # noqa: N802
        icon = self._icon()

        self.action_search = QAction(icon, config.PLUGIN_NAME, self.iface.mainWindow())
        self.action_search.setToolTip("NL_PhotoFromPastVu: фото из PastVu по охвату карты")
        self.action_search.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action_search)

        self.menu = QMenu(config.PLUGIN_NAME, self.iface.mainWindow())
        self.menu.setIcon(icon)
        action_open = self.menu.addAction(icon, "Поиск фотографий…")
        action_open.triggered.connect(self.run)
        self.menu.addSeparator()
        action_help = self.menu.addAction("Справка…")
        action_help.triggered.connect(self.show_help)
        action_about = self.menu.addAction("О плагине…")
        action_about.triggered.connect(self.show_about)
        self.iface.addPluginToMenu(config.MENU_NAME, self.menu.menuAction())

    def unload(self):
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None
        if self.menu is not None:
            self.iface.removePluginMenu(config.MENU_NAME, self.menu.menuAction())
            self.menu.deleteLater()
            self.menu = None
        if self.action_search is not None:
            self.iface.removeToolBarIcon(self.action_search)
            self.action_search.deleteLater()
            self.action_search = None

    # ------------------------------------------------------------------- UI
    def run(self):
        if self.dialog is None:
            self.dialog = PhotoFromPastVuDialog(self.iface)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def show_help(self):
        path = os.path.join(self.plugin_dir, "README.md")
        if os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(
                self.iface.mainWindow(), "Справка",
                "Файл README.md не найден рядом с плагином."
            )

    def show_about(self):
        QMessageBox.about(
            self.iface.mainWindow(),
            f"О {config.PLUGIN_NAME}",
            f"<h3>{config.PLUGIN_NAME} {config.PLUGIN_VERSION}</h3>"
            "<p>Поиск и загрузка ретрофотографий с "
            "<a href='https://pastvu.com'>PastVu</a> прямо в QGIS.</p>"
            "<p>Охват берётся из текущего окна карты или из экстента слоя "
            "и пересчитывается в WGS84, поэтому работает в любой системе "
            "координат проекта.</p>"
            "<p>Фотографии можно скачать на диск — локальные пути "
            "записываются в поле <b>local_path</b>.</p>"
            "<p>Разработано в градостроительной мастерской «Новый слой»: "
            "<a href='https://newlayer.ru/'>newlayer.ru</a>.</p>"
            f"<p><a href='{config.REPOSITORY}'>GitHub</a> · "
            f"<a href='{config.TRACKER}'>Сообщить об ошибке</a></p>"
            "<p>Лицензия GPL-2.0. Данные и изображения — PastVu.</p>"
        )

    def _icon(self):
        path = os.path.join(self.plugin_dir, "icon.png")
        if os.path.exists(path):
            return QIcon(path)
        return QgsApplication.getThemeIcon("mActionAddPhotoLayer.svg")
