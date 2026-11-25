# -*- coding: utf-8 -*-
"""Главное окно NL_PhotoFromPastVu."""

from __future__ import annotations

import os

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsMapLayer,
    QgsMessageLog,
    QgsNetworkAccessManager,
    QgsProject,
    QgsSettings,
)
from qgis.PyQt.QtCore import QSize, QUrl, Qt
from qgis.PyQt.QtGui import QDesktopServices, QIcon, QPixmap
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import config, geo
from .api import PastVuClient, photo_url
from .security import IMAGE_HOSTS, validate_https_url
from .download_dialog import DownloadDialog
from .download_task import SearchTask
from .layer_builder import (
    DIRECTION_RU,
    DIRECTION_SHORT,
    add_layer_to_project,
    create_layer,
    open_saved_layer,
    replace_layer_in_project,
    save_layer_as,
)
from .ui import ClickableLabel, apply_theme_text, build_stylesheet, theme_icon

USER_ROLE = Qt.ItemDataRole.UserRole
CHECKED_STATE = Qt.CheckState.Checked
UNCHECKED_STATE = Qt.CheckState.Unchecked
ITEM_FLAGS = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
CHECK_FLAGS = ITEM_FLAGS | Qt.ItemFlag.ItemIsUserCheckable


def _year_text(photo) -> str:
    year = photo.get("year")
    year2 = photo.get("year2")
    if year is None and year2 is None:
        return "—"
    if year2 is None or year2 == year:
        return str(year)
    if year is None:
        return f"до {year2}"
    return f"{year}–{year2}"


def _count_text(value: int) -> str:
    return f"{value:,}".replace(",", " ")


class PhotoFromPastVuDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.photos = []
        self.layer = None
        self.search_task = None
        self.download_dialog = None
        self._preview_cache = {}
        self._preview_reply = None
        self._current_photo = None
        self._searching = False
        self._style_refreshed = False

        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle("NL_PhotoFromPastVu — фото из PastVu")
        self.resize(1160, 740)
        self.setMinimumSize(980, 620)

        self._build_ui()
        self.setStyleSheet(build_stylesheet(self.palette()))
        apply_theme_text(self)
        self._restore_window_state()
        self._reload_layers()
        self._update_extent_info()

        self.iface.mapCanvas().extentsChanged.connect(self._update_extent_info)
        QgsProject.instance().layersAdded.connect(self._reload_layers)
        QgsProject.instance().layersRemoved.connect(self._reload_layers)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)
        root.addWidget(self._build_header())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._build_left_panel())
        self.splitter.addWidget(self._build_results_panel())
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([370, 760])
        root.addWidget(self.splitter, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.status_label = QLabel("Задайте охват и нажмите «Найти фотографии».")
        self.status_label.setObjectName("Hint")
        self.status_label.setWordWrap(True)
        bottom.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(180)
        self.progress.setVisible(False)
        bottom.addWidget(self.progress)
        signature = QLabel("разработано в градостроительной мастерской «Новый слой»")
        signature.setObjectName("Footer")
        signature.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(signature)
        root.addLayout(bottom)

    def _build_header(self):
        header = QFrame()
        header.setObjectName("Header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(12)

        logo_path = os.path.join(
            os.path.dirname(__file__), "assets", "newlayer_logo.png"
        )
        if os.path.exists(logo_path):
            logo_pixmap = QPixmap(logo_path)
            if not logo_pixmap.isNull():
                logo_pixmap = logo_pixmap.scaledToHeight(48, Qt.TransformationMode.SmoothTransformation)
                logo = ClickableLabel()
                logo.setObjectName("Logo")
                logo.setPixmap(logo_pixmap)
                logo.setFixedSize(logo_pixmap.size())
                logo.setCursor(Qt.CursorShape.PointingHandCursor)
                logo.setToolTip("newlayer.ru — градостроительная мастерская «Новый слой»")
                logo.clicked.connect(self._open_newlayer)
                layout.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("NL_PhotoFromPastVu")
        title.setObjectName("HeaderTitle")
        subtitle = QLabel("Фото из PastVu · поиск по окну карты или охвату слоя")
        subtitle.setObjectName("HeaderSubtitle")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        layout.addLayout(titles, 1)

        link = QLabel('<a href="https://pastvu.com" style="color:#ffffff;">pastvu.com</a>')
        link.setObjectName("HeaderLink")
        link.setOpenExternalLinks(True)
        layout.addWidget(link, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return header

    def _open_newlayer(self):
        QDesktopServices.openUrl(QUrl("https://newlayer.ru/"))

    def _build_left_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(340)
        panel.setMaximumWidth(420)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(10)

        extent_group = QGroupBox("Охват поиска")
        extent_layout = QVBoxLayout(extent_group)
        extent_layout.setSpacing(5)

        self.radio_canvas = QRadioButton("Текущее окно карты")
        self.radio_canvas.setChecked(True)
        self.radio_layer = QRadioButton("Охват слоя")
        self.canvas_hint = QLabel("Видимый прямоугольник карты в любой системе координат проекта.")
        self.canvas_hint.setObjectName("Hint")
        self.canvas_hint.setWordWrap(True)
        extent_layout.addWidget(self.radio_canvas)
        extent_layout.addWidget(self.canvas_hint)
        extent_layout.addSpacing(4)
        extent_layout.addWidget(self.radio_layer)

        layer_row = QHBoxLayout()
        layer_row.setSpacing(4)
        self.layer_combo = QComboBox()
        self.layer_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.layer_combo.setMinimumContentsLength(16)
        self.refresh_layers_btn = QToolButton()
        self.refresh_layers_btn.setIcon(theme_icon("mActionRefresh.svg") or QIcon())
        self.refresh_layers_btn.setIconSize(QSize(18, 18))
        self.refresh_layers_btn.setToolTip("Обновить список слоёв")
        self.refresh_layers_btn.clicked.connect(self._reload_layers)
        layer_row.addWidget(self.layer_combo, 1)
        layer_row.addWidget(self.refresh_layers_btn)
        extent_layout.addLayout(layer_row)

        self.extent_info = QLabel()
        self.extent_info.setObjectName("Hint")
        self.extent_info.setWordWrap(True)
        extent_layout.addWidget(self.extent_info)
        self.extent_warning = QLabel()
        self.extent_warning.setObjectName("Warning")
        self.extent_warning.setWordWrap(True)
        self.extent_warning.setVisible(False)
        extent_layout.addWidget(self.extent_warning)
        layout.addWidget(extent_group)

        filters_group = QGroupBox("Фильтры")
        filters_layout = QVBoxLayout(filters_group)
        filters_layout.setSpacing(7)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Тип:"))
        self.type_combo = QComboBox()
        self.type_combo.addItem("Фотографии", False)
        self.type_combo.addItem("Картины", True)
        type_row.addWidget(self.type_combo, 1)
        filters_layout.addLayout(type_row)

        self.year_check = QCheckBox("Фильтр по годам")
        filters_layout.addWidget(self.year_check)
        year_row = QHBoxLayout()
        year_row.setSpacing(6)
        year_row.addWidget(QLabel("с"))
        self.year_from = QSpinBox()
        self.year_from.setRange(1826, 2000)
        self.year_from.setValue(1900)
        self.year_from.setFixedWidth(78)
        year_row.addWidget(self.year_from)
        year_row.addWidget(QLabel("по"))
        self.year_to = QSpinBox()
        self.year_to.setRange(1826, 2000)
        self.year_to.setValue(2000)
        self.year_to.setFixedWidth(78)
        year_row.addWidget(self.year_to)
        year_row.addStretch(1)
        filters_layout.addLayout(year_row)
        self.year_hint = QLabel("API учитывает только первый год датировки.")
        self.year_hint.setObjectName("Hint")
        self.year_hint.setWordWrap(True)
        filters_layout.addWidget(self.year_hint)
        layout.addWidget(filters_group)

        self.search_btn = QPushButton("Найти фотографии")
        self.search_btn.setObjectName("Primary")
        self.search_btn.setMinimumHeight(42)
        self.search_btn.clicked.connect(self._start_search)
        layout.addWidget(self.search_btn)

        tips_group = QGroupBox("Как это работает")
        tips_layout = QVBoxLayout(tips_group)
        tips = QLabel(
            "1. Выберите охват → 2. Найдите фото → 3. Добавьте в проект → "
            "4. Скачайте файлы.\n\n"
            "Слой создаётся в EPSG:4326, QGIS автоматически показывает его "
            "в системе координат проекта."
        )
        tips.setWordWrap(True)
        tips.setObjectName("Hint")
        tips_layout.addWidget(tips)
        layout.addWidget(tips_group)

        source = QLabel("Данные: pastvu.com · публичный API")
        source.setObjectName("Hint")
        source.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(source)
        layout.addStretch(1)

        self.radio_canvas.toggled.connect(self._on_extent_mode_changed)
        self.layer_combo.currentIndexChanged.connect(self._update_extent_info)
        self.year_check.toggled.connect(self._update_year_state)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._update_year_state()
        return panel

    def _build_results_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.count_label = QLabel("Найдено: 0")
        self.count_label.setObjectName("Count")
        toolbar.addWidget(self.count_label)
        toolbar.addStretch(1)

        self.select_all_btn = QToolButton()
        self.select_all_btn.setIcon(theme_icon("mActionSelectAll.svg") or QIcon())
        self.select_all_btn.setText("Все")
        self.select_all_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.select_all_btn.setToolTip("Отметить все фотографии")
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))

        self.select_none_btn = QToolButton()
        self.select_none_btn.setIcon(theme_icon("mActionDeselectAll.svg") or QIcon())
        self.select_none_btn.setText("Ничего")
        self.select_none_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.select_none_btn.setToolTip("Снять все отметки")
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))

        toolbar.addWidget(self.select_all_btn)
        toolbar.addWidget(self.select_none_btn)

        self.add_btn = QPushButton("Добавить в проект")
        self.add_btn.setObjectName("Primary")
        self.add_btn.setIcon(theme_icon("mActionAddLayer.svg") or QIcon())
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add_to_project)
        toolbar.addWidget(self.add_btn)

        self.download_btn = QPushButton("Скачать фото…")
        self.download_btn.setIcon(theme_icon("mActionFileSaveAs.svg") or QIcon())
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._open_download)
        toolbar.addWidget(self.download_btn)

        self.save_btn = QPushButton("Сохранить…")
        self.save_btn.setIcon(theme_icon("mActionFileSave.svg") or QIcon())
        self.save_btn.setEnabled(False)
        self.save_btn.setToolTip("Сохранить слой в GeoPackage, GeoJSON или Shapefile")
        self.save_btn.clicked.connect(self._save_layer)
        toolbar.addWidget(self.save_btn)
        layout.addLayout(toolbar)

        results_splitter = QSplitter(Qt.Orientation.Horizontal)
        results_splitter.setChildrenCollapsible(False)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "Год", "Название", "Направление", "CID"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 34)
        self.table.setColumnWidth(1, 84)
        self.table.setColumnWidth(3, 136)
        self.table.setColumnWidth(4, 82)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        results_splitter.addWidget(self.table)

        results_splitter.addWidget(self._build_preview_panel())
        results_splitter.setStretchFactor(0, 1)
        results_splitter.setStretchFactor(1, 0)
        results_splitter.setSizes([500, 280])
        layout.addWidget(results_splitter, 1)
        return panel

    def _build_preview_panel(self):
        frame = QFrame()
        frame.setObjectName("PreviewCard")
        frame.setFixedWidth(286)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.preview_image = QLabel("Выберите фотографию")
        self.preview_image.setObjectName("PreviewImage")
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setFixedSize(258, 172)
        layout.addWidget(self.preview_image)

        self.preview_title = QLabel()
        self.preview_title.setWordWrap(True)
        self.preview_title.setMinimumHeight(38)
        self.preview_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.preview_title)

        self.preview_meta = QLabel()
        self.preview_meta.setObjectName("Hint")
        self.preview_meta.setWordWrap(True)
        layout.addWidget(self.preview_meta)

        self.preview_cid = QLabel()
        self.preview_cid.setObjectName("Hint")
        layout.addWidget(self.preview_cid)

        self.preview_link = QPushButton("Открыть на PastVu")
        self.preview_link.setEnabled(False)
        self.preview_link.clicked.connect(self._open_current_pastvu)
        layout.addWidget(self.preview_link)
        layout.addStretch(1)

        hint = QLabel("Двойной клик по строке тоже открывает фото на сайте.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return frame

    # ------------------------------------------------------------- layers
    def _reload_layers(self):
        current = self.layer_combo.currentData()
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() != QgsMapLayer.LayerType.VectorLayer:
                continue
            if not layer.crs().isValid():
                continue
            self.layer_combo.addItem(layer.name(), layer.id())
        self.layer_combo.blockSignals(False)

        has_layers = self.layer_combo.count() > 0
        self.layer_combo.setEnabled(has_layers and self.radio_layer.isChecked())
        self.radio_layer.setEnabled(has_layers)
        if not has_layers and self.radio_layer.isChecked():
            self.radio_canvas.setChecked(True)
        elif current is not None:
            index = self.layer_combo.findData(current)
            if index >= 0:
                self.layer_combo.setCurrentIndex(index)
        self._update_extent_info()

    def _selected_layer(self):
        layer_id = self.layer_combo.currentData()
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    def _on_extent_mode_changed(self):
        self.layer_combo.setEnabled(self.radio_layer.isChecked())
        self._update_extent_info()

    def _on_type_changed(self):
        if self.type_combo.currentData():
            self.year_from.setRange(-100, 1980)
            self.year_to.setRange(-100, 1980)
            if self.year_from.value() < -100:
                self.year_from.setValue(1800)
            if self.year_to.value() > 1980:
                self.year_to.setValue(1980)
        else:
            self.year_from.setRange(1826, 2000)
            self.year_to.setRange(1826, 2000)
            if self.year_from.value() < 1826:
                self.year_from.setValue(1900)
            if self.year_to.value() < 1900:
                self.year_to.setValue(2000)

    def _update_year_state(self):
        enabled = self.year_check.isChecked() and not self._searching
        self.year_from.setEnabled(enabled)
        self.year_to.setEnabled(enabled)

    # ------------------------------------------------------------- extent
    def _current_extent(self):
        width = max(self.iface.mapCanvas().width(), 1)
        if self.radio_layer.isChecked():
            return geo.extent_from_layer(self._selected_layer(), width)
        return geo.extent_from_canvas(self.iface, width)

    def _update_extent_info(self):
        try:
            info = self._current_extent()
        except geo.ExtentError as exc:
            self.extent_info.setText("")
            self.extent_warning.setObjectName("Error")
            self.extent_warning.setText(str(exc))
            self.extent_warning.setVisible(True)
            self._repolish(self.extent_warning)
            self._set_search_enabled(False)
            return

        if info.width_deg < 1:
            degrees = f"{info.width_deg:.4f}° × {info.height_deg:.4f}°"
        else:
            degrees = f"{info.width_deg:.2f}° × {info.height_deg:.2f}°"
        self.extent_info.setText(
            f"{degrees} · {geo.format_distance(info.km_width)} × "
            f"{geo.format_distance(info.km_height)} · z≈{info.zoom}"
        )
        self.extent_warning.setVisible(False)
        self._set_search_enabled(True)

    def _set_search_enabled(self, enabled: bool):
        self.search_btn.setEnabled(enabled and not self._searching)

    @staticmethod
    def _repolish(widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    # -------------------------------------------------------------- search
    def _start_search(self):
        if self.search_task is not None:
            self.status_label.setText("Останавливаю поиск…")
            self.search_task.cancel()
            return

        try:
            info = self._current_extent()
        except geo.ExtentError as exc:
            QMessageBox.warning(self, "Охват не подходит", str(exc))
            self._update_extent_info()
            return

        if info.width_deg <= 0 or info.height_deg <= 0:
            QMessageBox.warning(
                self, "Охват не подходит",
                "Охват вырожден. Приблизьте карту или выберите другой слой."
            )
            return

        year = year2 = None
        if self.year_check.isChecked():
            year = self.year_from.value()
            year2 = self.year_to.value()
            if year > year2:
                QMessageBox.warning(
                    self, "Проверьте годы",
                    "Год «с» не может быть больше года «по»."
                )
                return

        is_painting = bool(self.type_combo.currentData())
        client = PastVuClient()
        self.search_task = SearchTask(
            client, info.geometry, info.zoom,
            year=year, year2=year2, is_painting=is_painting,
        )
        self.search_task.taskCompleted.connect(self._on_search_done)
        self.search_task.taskTerminated.connect(self._on_search_done)
        self._set_searching(True)
        self.status_label.setText("Ищу фотографии на PastVu…")
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        QgsApplication.taskManager().addTask(self.search_task)

    def _set_searching(self, searching: bool):
        self._searching = searching
        for widget in (
            self.radio_canvas, self.radio_layer, self.layer_combo,
            self.refresh_layers_btn, self.type_combo, self.year_check,
        ):
            widget.setEnabled(not searching)
        if not searching:
            self.radio_layer.setEnabled(self.layer_combo.count() > 0)
            self.layer_combo.setEnabled(
                self.radio_layer.isChecked() and self.layer_combo.count() > 0
            )
        self._update_year_state()
        self.search_btn.setText("Остановить поиск" if searching else "  Найти фотографии")
        for button in (self.add_btn, self.download_btn, self.save_btn):
            button.setEnabled(False)
        if not searching:
            self._update_checked_count()

    def _on_search_done(self):
        task = self.search_task
        if task is None:
            return
        self.search_task = None
        self._set_searching(False)
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        if task.isCanceled():
            self.status_label.setText("Поиск отменён.")
            self._update_extent_info()
            return
        if task.error is not None:
            self.status_label.setText("Не удалось выполнить поиск.")
            message = str(task.error) or task.error.__class__.__name__
            QMessageBox.warning(self, "Ошибка PastVu", message)
            self._update_extent_info()
            return

        photos = task.photos
        if not photos:
            self._clear_results()
            self.status_label.setText(
                "Ничего не найдено. Попробуйте увеличить охват или снять фильтры."
            )
            self._update_extent_info()
            return

        self._set_results(photos)
        self.status_label.setText(
            f"Найдено {_count_text(len(photos))} фото. "
            "Отметьте нужные и добавьте в проект."
        )
        self._update_extent_info()

    # ------------------------------------------------------------- results
    def _set_results(self, photos):
        self.photos = list(photos)
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.photos))
        for row, photo in enumerate(self.photos):
            check_item = QTableWidgetItem()
            check_item.setFlags(CHECK_FLAGS)
            check_item.setCheckState(CHECKED_STATE)
            check_item.setData(USER_ROLE, photo)
            self.table.setItem(row, 0, check_item)

            year_item = QTableWidgetItem(_year_text(photo))
            year_item.setFlags(ITEM_FLAGS)
            year_item.setData(USER_ROLE, photo)
            self.table.setItem(row, 1, year_item)

            title = str(photo.get("title") or "Без названия")
            title_item = QTableWidgetItem(title)
            title_item.setFlags(ITEM_FLAGS)
            title_item.setToolTip(title)
            title_item.setData(USER_ROLE, photo)
            self.table.setItem(row, 2, title_item)

            dir_code = str(photo.get("dir") or "").lower()
            direction = DIRECTION_SHORT.get(dir_code, "—")
            direction_item = QTableWidgetItem(direction)
            direction_item.setFlags(ITEM_FLAGS)
            direction_item.setToolTip(DIRECTION_RU.get(dir_code, "не указано"))
            direction_item.setData(USER_ROLE, photo)
            self.table.setItem(row, 3, direction_item)

            cid_item = QTableWidgetItem(str(photo.get("cid") or ""))
            cid_item.setFlags(ITEM_FLAGS)
            cid_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cid_item.setData(USER_ROLE, photo)
            self.table.setItem(row, 4, cid_item)
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)

        self._update_checked_count()
        self.save_btn.setEnabled(self._has_valid_layer())
        if self.photos:
            self.table.selectRow(0)
        else:
            self._reset_preview()

    def _clear_results(self):
        self.photos = []
        self.table.setRowCount(0)
        self.count_label.setText("Найдено: 0")
        self.add_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self._reset_preview()

    def _photo_at_row(self, row):
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(USER_ROLE)

    def _checked_photos(self):
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            if item.checkState() == CHECKED_STATE:
                photo = item.data(USER_ROLE)
                if photo is not None:
                    result.append(photo)
        return result

    def _update_checked_count(self):
        checked = len(self._checked_photos())
        self.count_label.setText(
            f"Найдено: {_count_text(len(self.photos))} · отмечено: {checked}"
        )
        self.add_btn.setEnabled(checked > 0 and not self._searching)
        self.download_btn.setEnabled(
            not self._searching and (checked > 0 or self._has_valid_layer())
        )
        self.save_btn.setEnabled(not self._searching and self._has_valid_layer())

    def _on_item_changed(self, item):
        if item is not None and item.column() == 0:
            self._update_checked_count()

    def _set_all_checked(self, checked: bool):
        state = CHECKED_STATE if checked else UNCHECKED_STATE
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(state)
        self.table.blockSignals(False)
        self._update_checked_count()

    # ------------------------------------------------------------- preview
    def _on_selection_changed(self):
        row = self.table.currentRow()
        if row < 0:
            self._reset_preview()
            return
        photo = self._photo_at_row(row)
        if photo is not None:
            self._show_photo(photo)

    def _on_cell_double_clicked(self, row, column):
        photo = self._photo_at_row(row)
        if photo is not None:
            self._open_pastvu(photo)

    def _show_photo(self, photo):
        self._current_photo = photo
        cid = photo.get("cid")
        title = str(photo.get("title") or "Без названия")
        self.preview_title.setText(title)
        self.preview_title.setToolTip(title)

        year = _year_text(photo)
        dir_code = str(photo.get("dir") or "").lower()
        direction = DIRECTION_RU.get(dir_code, "направление не указано")
        azimuth = {"n": 0, "ne": 45, "e": 90, "se": 135, "s": 180,
                   "sw": 225, "w": 270, "nw": 315}.get(dir_code)
        meta = f"{year} · {direction}"
        if azimuth is not None:
            meta += f" · {azimuth}°"
        self.preview_meta.setText(meta)
        self.preview_cid.setText(f"CID {cid}" if cid is not None else "")
        self.preview_link.setEnabled(cid is not None)

        if cid in self._preview_cache:
            self._set_preview_pixmap(self._preview_cache[cid])
            return
        url = photo_url(photo.get("file"), "h")
        if not url:
            self.preview_image.setPixmap(QPixmap())
            self.preview_image.setText("Нет изображения")
            return
        self.preview_image.setPixmap(QPixmap())
        self.preview_image.setText("Загрузка…")
        self._request_preview(url, cid)

    def _request_preview(self, url, cid):
        try:
            url = validate_https_url(url, IMAGE_HOSTS)
        except ValueError:
            self.preview_image.setText("Недопустимый адрес изображения")
            return
        old_reply = self._preview_reply
        self._preview_reply = None
        if old_reply is not None:
            old_reply.abort()
            old_reply.deleteLater()

        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", config.USER_AGENT.encode("utf-8"))
        request.setRawHeader(b"Referer", config.REFERER.encode("utf-8"))
        reply = QgsNetworkAccessManager.instance().get(request)
        reply.setProperty("cid", cid)
        self._preview_reply = reply
        reply.finished.connect(self._on_preview_reply)

    def _on_preview_reply(self):
        reply = self.sender()
        if reply is None:
            return
        reply.deleteLater()
        if reply is not self._preview_reply:
            return
        self._preview_reply = None
        cid = reply.property("cid")
        if cid != (self._current_photo or {}).get("cid"):
            return
        no_error = getattr(
            getattr(QNetworkReply, "NetworkError", QNetworkReply), "NoError", 0
        )
        if reply.error() != no_error:
            self.preview_image.setText("Не удалось загрузить превью")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(bytes(reply.readAll())):
            self.preview_image.setText("Не удалось прочитать превью")
            return
        if len(self._preview_cache) > 150:
            self._preview_cache.clear()
        self._preview_cache[cid] = pixmap
        self._set_preview_pixmap(pixmap)

    def _set_preview_pixmap(self, pixmap: QPixmap):
        if pixmap is None or pixmap.isNull():
            return
        self.preview_image.setText("")
        self.preview_image.setPixmap(
            pixmap.scaled(
                self.preview_image.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )

    def _reset_preview(self):
        self._current_photo = None
        reply = self._preview_reply
        self._preview_reply = None
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        self.preview_image.setPixmap(QPixmap())
        self.preview_image.setText("Выберите фотографию")
        self.preview_title.clear()
        self.preview_meta.clear()
        self.preview_cid.clear()
        self.preview_link.setEnabled(False)

    def _open_current_pastvu(self):
        if self._current_photo is not None:
            self._open_pastvu(self._current_photo)

    @staticmethod
    def _open_pastvu(photo):
        cid = photo.get("cid")
        if cid is None:
            return
        QDesktopServices.openUrl(QUrl(f"https://pastvu.com/p/{cid}"))

    # -------------------------------------------------------------- layer
    def _has_valid_layer(self):
        return (
            self.layer is not None
            and QgsProject.instance().mapLayer(self.layer.id()) is not None
        )

    def _create_and_add_layer(self, photos):
        try:
            layer = create_layer(photos, config.DEFAULT_LAYER_NAME)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Не удалось создать слой", str(exc))
            return None
        add_layer_to_project(layer, config.GROUP_NAME)
        self.layer = layer
        self.save_btn.setEnabled(True)
        try:
            self.iface.setActiveLayer(layer)
        except (AttributeError, RuntimeError) as exc:
            QgsMessageLog.logMessage(
                f"Не удалось сделать слой активным: {exc}",
                config.PLUGIN_NAME, Qgis.MessageLevel.Info,
            )
        self.iface.mapCanvas().refresh()
        return layer

    def _add_to_project(self):
        photos = self._checked_photos()
        if not photos:
            QMessageBox.information(
                self, "Ничего не отмечено",
                "Отметьте фотографии, которые нужно добавить в проект."
            )
            return
        layer = self._create_and_add_layer(photos)
        if layer is None:
            return
        message = f"Добавлено {len(photos)} фото в слой «{layer.name()}»."
        self.status_label.setText(message)
        self._update_checked_count()
        try:
            self.iface.messageBar().pushInfo(
                config.PLUGIN_NAME, message, Qgis.MessageLevel.Info, 5
            )
        except (AttributeError, RuntimeError) as exc:
            QgsMessageLog.logMessage(
                f"Не удалось показать сообщение в QGIS: {exc}",
                config.PLUGIN_NAME, Qgis.MessageLevel.Info,
            )

    def _ensure_layer(self):
        if self._has_valid_layer():
            return self.layer
        photos = self._checked_photos()
        if not photos:
            QMessageBox.information(
                self, "Нет слоя",
                "Сначала найдите фотографии и добавьте их в проект."
            )
            return None
        return self._create_and_add_layer(photos)

    def _open_download(self):
        layer = self._ensure_layer()
        if layer is None:
            return
        if self.download_dialog is not None and self.download_dialog.isVisible():
            self.download_dialog.raise_()
            self.download_dialog.activateWindow()
            return
        self.download_dialog = DownloadDialog(self.iface, layer, self)
        self.download_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.download_dialog.pathsUpdated.connect(self._on_paths_updated)
        self.download_dialog.destroyed.connect(self._on_download_destroyed)
        self.download_dialog.show()
        self.download_dialog.raise_()
        self.download_dialog.activateWindow()

    def _on_download_destroyed(self, *_args):
        self.download_dialog = None

    def _on_paths_updated(self, count: int):
        if count:
            self.status_label.setText(
                f"Локальные пути записаны в слой: {count} фото."
            )

    def _save_layer(self):
        layer = self._ensure_layer()
        if layer is None:
            return
        if self.download_dialog is not None and self.download_dialog.task is not None:
            QMessageBox.information(
                self, "Скачивание ещё идёт",
                "Дождитесь окончания скачивания, затем сохраните слой."
            )
            return
        project_home = QgsProject.instance().homePath()
        folder = project_home or config.default_download_dir()
        default_path = os.path.join(folder, "Retro_Photo.gpkg")
        path, _selected_filter = QFileDialog.getSaveFileName(
            self, "Сохранить слой", default_path,
            "GeoPackage (*.gpkg);;GeoJSON (*.geojson);;Shapefile (*.shp)"
        )
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".gpkg"
        try:
            saved = save_layer_as(layer, path)
            new_layer = open_saved_layer(saved, layer.name(), layer)
            replace_layer_in_project(layer, new_layer)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Не удалось сохранить слой", str(exc))
            return

        self.layer = new_layer
        try:
            self.iface.setActiveLayer(new_layer)
        except (AttributeError, RuntimeError) as exc:
            QgsMessageLog.logMessage(
                f"Не удалось сделать сохранённый слой активным: {exc}",
                config.PLUGIN_NAME, Qgis.MessageLevel.Info,
            )
        if self.download_dialog is not None:
            self.download_dialog.set_layer(new_layer)
        self.save_btn.setEnabled(True)
        self.iface.mapCanvas().refresh()
        self.status_label.setText(
            f"Слой сохранён, временный слой заменён: {saved.path}"
        )
        answer = QMessageBox.question(
            self,
            "Слой сохранён",
            "Временный слой заменён файловым.\n\n"
            f"{saved.path}\n\nОткрыть папку?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.dirname(saved.path))
            )

    # -------------------------------------------------------------- window
    def _reset_search_state(self):
        """Очищает результаты предыдущего поиска при закрытии окна."""
        self._clear_results()
        self.layer = None
        self.save_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.search_btn.setText("Найти фотографии")
        self.status_label.setText("Задайте охват и нажмите «Найти фотографии».")
        self._preview_cache.clear()

    def _restore_window_state(self):
        settings = QgsSettings()
        geometry = settings.value(f"{config.PREFIX}/window_geometry")
        if geometry is not None:
            try:
                self.restoreGeometry(geometry)
            except (TypeError, ValueError, RuntimeError) as exc:
                QgsMessageLog.logMessage(
                    f"Не удалось восстановить размер окна: {exc}",
                    config.PLUGIN_NAME, Qgis.MessageLevel.Info,
                )
        state = settings.value(f"{config.PREFIX}/splitter_state")
        if state is not None:
            try:
                self.splitter.restoreState(state)
            except (TypeError, ValueError, RuntimeError) as exc:
                QgsMessageLog.logMessage(
                    f"Не удалось восстановить splitter: {exc}",
                    config.PLUGIN_NAME, Qgis.MessageLevel.Info,
                )

    def _save_window_state(self):
        settings = QgsSettings()
        settings.setValue(f"{config.PREFIX}/window_geometry", self.saveGeometry())
        settings.setValue(f"{config.PREFIX}/splitter_state", self.splitter.saveState())

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        # QSplitter иногда «теряет» каскад QSS у вложенных панелей до первого
        # показа окна; повторная установка гарантированно переполирует детей.
        if not self._style_refreshed:
            self.setStyleSheet(build_stylesheet(self.palette()))
            self._style_refreshed = True
        apply_theme_text(self)
        self._reload_layers()
        self._update_extent_info()

    def closeEvent(self, event):  # noqa: N802
        if self.search_task is not None:
            self.search_task.cancel()
            self.search_task = None
        if self._searching:
            self._set_searching(False)
        if self.download_dialog is not None and self.download_dialog.isVisible():
            self.download_dialog.close()
        self._reset_search_state()
        self._save_window_state()
        super().closeEvent(event)
