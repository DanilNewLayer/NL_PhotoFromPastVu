# -*- coding: utf-8 -*-
"""Окно скачивания фотографий на компьютер."""

from __future__ import annotations

import os

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtCore import QUrl, Qt, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QPixmap
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from . import config
from .download_task import DownloadItem, DownloadTask
from .layer_builder import update_local_paths
from .ui import ClickableLabel, apply_theme_text, build_stylesheet, theme_icon


class DownloadDialog(QDialog):
    pathsUpdated = pyqtSignal(int)

    def __init__(self, iface, layer, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.layer = layer
        self.task = None
        self._closing = False
        self._style_refreshed = False
        self.setWindowTitle("Скачать фотографии PastVu")
        self.setModal(False)
        self.resize(760, 700)
        self.setMinimumWidth(680)
        self._build_ui()
        self.setStyleSheet(build_stylesheet(self.palette()))
        apply_theme_text(self)
        self._restore_defaults()
        self._connect_layer()
        self._update_counts()
        self._update_example()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("Header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        logo_path = os.path.join(
            os.path.dirname(__file__), "assets", "newlayer_logo.png"
        )
        if os.path.exists(logo_path):
            logo_pixmap = QPixmap(logo_path)
            if not logo_pixmap.isNull():
                logo_pixmap = logo_pixmap.scaledToHeight(38, Qt.SmoothTransformation)
                logo = ClickableLabel()
                logo.setObjectName("Logo")
                logo.setPixmap(logo_pixmap)
                logo.setFixedSize(logo_pixmap.size())
                logo.setCursor(Qt.PointingHandCursor)
                logo.setToolTip("newlayer.ru — градостроительная мастерская «Новый слой»")
                logo.clicked.connect(
                    lambda: QDesktopServices.openUrl(QUrl("https://newlayer.ru/"))
                )
                header_layout.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("Скачивание фотографий")
        title.setObjectName("HeaderTitle")
        subtitle = QLabel("Файлы сохранятся в папку, а путь запишется в поле local_path")
        subtitle.setObjectName("HeaderSubtitle")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header_layout.addLayout(titles, 1)
        layout.addWidget(header)

        scope_group = QGroupBox("Что скачивать")
        scope_layout = QVBoxLayout(scope_group)
        scope_layout.setSpacing(6)
        self.radio_all = QRadioButton("Все объекты слоя")
        self.radio_selected = QRadioButton("Только выделенные объекты")
        self.radio_all.setChecked(True)
        scope_layout.addWidget(self.radio_all)
        scope_layout.addWidget(self.radio_selected)
        self.scope_hint = QLabel()
        self.scope_hint.setObjectName("Hint")
        scope_layout.addWidget(self.scope_hint)
        layout.addWidget(scope_group)

        files_group = QGroupBox("Файлы")
        files_layout = QVBoxLayout(files_group)
        files_layout.setSpacing(8)

        size_row = QHBoxLayout()
        size_label = QLabel("Размер:")
        self.size_combo = QComboBox()
        self.size_combo.addItem("Оригинал — максимальное качество", config.SIZE_ORIGINAL)
        self.size_combo.addItem("Стандартный — для просмотра", config.SIZE_STANDARD)
        self.size_combo.addItem("Миниатюра — быстро и компактно", config.SIZE_THUMB)
        size_row.addWidget(size_label)
        size_row.addWidget(self.size_combo, 1)
        files_layout.addLayout(size_row)
        self.size_hint = QLabel()
        self.size_hint.setObjectName("Hint")
        files_layout.addWidget(self.size_hint)

        folder_row = QHBoxLayout()
        folder_label = QLabel("Папка:")
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Папка для фотографий")
        browse_button = QPushButton("Обзор…")
        browse_button.clicked.connect(self._browse_folder)
        folder_row.addWidget(folder_label)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse_button)
        files_layout.addLayout(folder_row)

        template_row = QHBoxLayout()
        template_label = QLabel("Имя файла:")
        self.template_edit = QLineEdit()
        self.template_edit.setPlaceholderText(config.DEFAULT_FILENAME_TEMPLATE)
        self.template_edit.textChanged.connect(self._update_example)
        template_row.addWidget(template_label)
        template_row.addWidget(self.template_edit, 1)
        files_layout.addLayout(template_row)
        self.template_hint = QLabel(
            "Подстановки: {cid}, {year}, {year2}, {title}, {dir}"
        )
        self.template_hint.setObjectName("Hint")
        self.template_hint.setWordWrap(True)
        files_layout.addWidget(self.template_hint)

        self.overwrite_check = QCheckBox("Перезаписывать уже существующие файлы")
        files_layout.addWidget(self.overwrite_check)
        layout.addWidget(files_group)

        progress_group = QGroupBox("Ход работы")
        progress_layout = QVBoxLayout(progress_group)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        progress_layout.addWidget(self.progress)
        self.status_label = QLabel("Готово к скачиванию.")
        self.status_label.setObjectName("Hint")
        self.status_label.setWordWrap(True)
        progress_layout.addWidget(self.status_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(400)
        self.log.setFixedHeight(100)
        progress_layout.addWidget(self.log)
        layout.addWidget(progress_group)

        signature = QLabel("разработано в градостроительной мастерской «Новый слой»")
        signature.setObjectName("Footer")
        signature.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(signature)

        buttons = QHBoxLayout()
        self.open_folder_button = QPushButton("Открыть папку")
        self.open_folder_button.setIcon(theme_icon("mActionFileOpen.svg") or self.open_folder_button.icon())
        self.open_folder_button.clicked.connect(self._open_folder)
        buttons.addWidget(self.open_folder_button)
        buttons.addStretch(1)
        self.close_button = QPushButton("Закрыть")
        self.close_button.clicked.connect(self.close)
        self.download_button = QPushButton("Скачать")
        self.download_button.setObjectName("Primary")
        self.download_button.setMinimumWidth(130)
        self.download_button.clicked.connect(self._start_or_stop)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.download_button)
        layout.addLayout(buttons)

        self.radio_all.toggled.connect(self._update_counts)
        self.size_combo.currentIndexChanged.connect(self._update_size_hint)

    def _restore_defaults(self):
        self.folder_edit.setText(config.download_dir())
        size = config.download_size()
        index = self.size_combo.findData(size)
        self.size_combo.setCurrentIndex(max(index, 0))
        self.template_edit.setText(config.filename_template())
        self.overwrite_check.setChecked(config.overwrite_existing())
        self._update_size_hint()

    def set_layer(self, layer):
        """Переключает окно на новый слой после сохранения."""
        self._disconnect_layer()
        self.layer = layer
        self._connect_layer()
        self._update_counts()

    def _connect_layer(self):
        if self.layer is None:
            return
        try:
            self.layer.selectionChanged.connect(self._on_layer_selection_changed)
        except Exception:  # noqa: BLE001
            pass

    def _disconnect_layer(self):
        if self.layer is None:
            return
        try:
            self.layer.selectionChanged.disconnect(self._on_layer_selection_changed)
        except Exception:  # noqa: BLE001
            pass

    def _on_layer_selection_changed(self):
        self._update_counts()
        if self.radio_selected.isEnabled() and not self.radio_selected.isChecked():
            self.scope_hint.setText(
                "Выделение обновлено: теперь можно выбрать «Только выделенные объекты»."
            )

    def _update_counts(self):
        total = 0
        try:
            total = self.layer.featureCount()
        except Exception:  # noqa: BLE001
            pass
        selected = 0
        if self.layer is not None:
            try:
                selected = self.layer.selectedFeatureCount()
            except Exception:  # noqa: BLE001
                selected = len(self.layer.selectedFeatureIds())
        self.radio_all.setText(f"Все объекты слоя — {total}")
        self.radio_selected.setText(f"Только выделенные объекты — {selected}")
        self.radio_selected.setEnabled(selected > 0)
        if selected <= 0:
            self.radio_selected.setChecked(False)
            self.radio_all.setChecked(True)
            self.scope_hint.setText(
                "В слое нет выделения: можно выделить объекты в QGIS или скачать все."
            )
        else:
            self.scope_hint.setText(
                "Выделение берётся из текущего слоя QGIS."
            )
        self._update_size_hint()

    def _update_size_hint(self):
        size = self.size_combo.currentData()
        if size == config.SIZE_ORIGINAL:
            text = "Оригиналы могут занимать десятки мегабайт — скачивание займёт время."
        elif size == config.SIZE_THUMB:
            text = "Миниатюры маленькие: удобно для быстрого просмотра."
        else:
            text = "Стандартный размер — оптимален для большинства задач."
        self.size_hint.setText(text)

    def _update_example(self):
        template = self.template_edit.text().strip() or config.DEFAULT_FILENAME_TEMPLATE
        values = {
            "cid": 123456, "year": 1987, "year2": 1987,
            "title": "Двор дома", "dir": "ne",
        }
        try:
            example = template.format(**values)
        except (KeyError, IndexError, ValueError):
            self.template_hint.setObjectName("Error")
            self.template_hint.setText(
                "Неизвестная подстановка. Доступно: {cid}, {year}, {year2}, {title}, {dir}"
            )
        else:
            self.template_hint.setObjectName("Hint")
            self.template_hint.setText(
                f"Например: {example}.jpg · подстановки: {{cid}}, {{year}}, {{year2}}, {{title}}, {{dir}}"
            )
        self.template_hint.style().unpolish(self.template_hint)
        self.template_hint.style().polish(self.template_hint)

    # --------------------------------------------------------------- data
    def _collect_items(self, selected_only: bool):
        items = []
        skipped = 0
        if self.layer is None:
            return items, skipped
        field_names = [field.name() for field in self.layer.fields()]

        def index_of(name):
            try:
                return field_names.index(name)
            except ValueError:
                return -1

        indexes = {name: index_of(name) for name in
                   ("cid", "file", "year", "year2", "title", "dir")}
        features = self.layer.selectedFeatures() if selected_only else self.layer.getFeatures()
        for feature in features:
            file_index = indexes["file"]
            file_value = feature.attribute(file_index) if file_index >= 0 else ""
            if not file_value:
                skipped += 1
                continue
            items.append(DownloadItem(
                fid=feature.id(),
                cid=_attr(feature, indexes["cid"]),
                file=str(file_value),
                year=_attr(feature, indexes["year"]),
                year2=_attr(feature, indexes["year2"]),
                title=str(_attr(feature, indexes["title"]) or ""),
                dir=str(_attr(feature, indexes["dir"]) or ""),
            ))
        return items, skipped

    # ------------------------------------------------------------- actions
    def _start_or_stop(self):
        if self.task is not None:
            self.status_label.setText("Останавливаю скачивание…")
            self.download_button.setEnabled(False)
            self.task.cancel()
            return

        selected_only = self.radio_selected.isChecked()
        items, skipped = self._collect_items(selected_only)
        if not items:
            QMessageBox.information(
                self, "Нечего скачивать",
                "В выбранных объектах нет поля file с адресом фотографии."
            )
            return

        folder = os.path.abspath(os.path.expanduser(self.folder_edit.text().strip()))
        if not folder:
            QMessageBox.warning(self, "Папка не задана", "Укажите папку для фотографий.")
            return
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(
                self, "Не удалось создать папку",
                f"{folder}\n\n{exc}"
            )
            return

        template = self.template_edit.text().strip() or config.DEFAULT_FILENAME_TEMPLATE
        size = self.size_combo.currentData()
        overwrite = self.overwrite_check.isChecked()

        config.set_value("download_dir", folder)
        config.set_value("download_size", size)
        config.set_value("filename_template", template)
        config.set_value("overwrite", overwrite)

        self.log.clear()
        if skipped:
            self.log.appendPlainText(f"Пропущено объектов без фото: {skipped}")
        self.log.appendPlainText(f"Папка: {folder}")
        self.log.appendPlainText(f"Файлов к обработке: {len(items)}")

        self.task = DownloadTask(items, folder, size, template, overwrite)
        self.task.progressChanged.connect(self._on_progress)
        self.task.statusText.connect(self._on_status)
        self.task.fileDone.connect(self._on_file_done)
        self.task.fileFailed.connect(self._on_file_failed)
        self.task.taskCompleted.connect(self._on_task_done)
        self.task.taskTerminated.connect(self._on_task_done)
        self._set_running(True)
        self.progress.setValue(0)
        QgsApplication.taskManager().addTask(self.task)

    def _browse_folder(self):
        start = self.folder_edit.text().strip() or config.default_download_dir()
        folder = QFileDialog.getExistingDirectory(self, "Папка для фотографий", start)
        if folder:
            self.folder_edit.setText(folder)

    def _open_folder(self):
        folder = self.folder_edit.text().strip()
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            QMessageBox.information(self, "Папка не найдена", "Папка ещё не создана.")

    def _set_running(self, running: bool):
        for widget in (
            self.radio_all, self.radio_selected, self.size_combo,
            self.folder_edit, self.template_edit, self.overwrite_check,
        ):
            widget.setEnabled(not running)
        self.close_button.setEnabled(not running)
        self.download_button.setEnabled(True)
        self.download_button.setText("Остановить" if running else "Скачать")
        if not running:
            self.radio_all.setEnabled(True)
            self.radio_selected.setEnabled(
                len(self.layer.selectedFeatureIds()) > 0 if self.layer else False
            )

    # -------------------------------------------------------------- signals
    def _on_progress(self, value):
        self.progress.setValue(int(value))

    def _on_status(self, text: str):
        self.status_label.setText(text)

    def _on_file_done(self, fid, path):
        self.log.appendPlainText(f"✓ {os.path.basename(path)}")

    def _on_file_failed(self, fid, error):
        self.log.appendPlainText(f"✗ объект {fid}: {error}")

    def _on_task_done(self):
        task = self.task
        if task is None:
            return
        self.task = None
        cancelled = task.isCanceled()
        paths = {fid: path for fid, path in task.results.items() if path}
        updated = 0
        if paths:
            if QgsProject.instance().mapLayer(self.layer.id()) is None:
                self.log.appendPlainText(
                    "Слой удалён из проекта — локальные пути не записаны."
                )
            else:
                updated = update_local_paths(self.layer, paths)
                self.pathsUpdated.emit(updated)

        failed = len(task.failures)
        skipped = task.skipped
        total = len(task.items)
        ready = len(task.results)
        if cancelled:
            self.status_label.setText(
                f"Скачивание остановлено. Файлов готово: {ready} из {total}."
            )
            self.log.appendPlainText("Скачивание остановлено пользователем.")
        else:
            self.progress.setValue(100)
            summary = f"Файлов готово: {ready} из {total}."
            if skipped:
                summary += f" Уже были на диске: {skipped}."
            if failed:
                summary += f" Ошибок: {failed}."
            if updated:
                summary += f" Путей записано: {updated}."
            self.status_label.setText(summary)
            self.log.appendPlainText(summary)
        self._set_running(False)
        self._update_counts()
        if self._closing:
            self._closing = False
            self.close()

    # ---------------------------------------------------------------- close
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._style_refreshed:
            self.setStyleSheet(build_stylesheet(self.palette()))
            self._style_refreshed = True
        apply_theme_text(self)

    def closeEvent(self, event):  # noqa: N802
        if self.task is not None:
            answer = QMessageBox.question(
                self, "Скачивание идёт",
                "Остановить скачивание и закрыть окно?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._closing = True
            self.status_label.setText("Останавливаю скачивание…")
            self.task.cancel()
            event.ignore()
            return
        self._disconnect_layer()
        super().closeEvent(event)


def _attr(feature, index):
    if index < 0:
        return None
    return feature.attribute(index)
