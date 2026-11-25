# -*- coding: utf-8 -*-
"""Общее оформление окон плагина: светлая и тёмная темы, фирменный QSS."""

from __future__ import annotations

import os

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QLabel,
    QRadioButton,
    QWidget,
)


def theme_icon(name: str):
    """Иконка из текущей темы QGIS."""
    try:
        return QgsApplication.getThemeIcon(name)
    except Exception:  # noqa: BLE001
        return None


class ClickableLabel(QLabel):
    """QLabel с сигналом нажатия — для кликабельного логотипа."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


LIGHT = {
    "bg": "#eef1f4",
    "card": "#ffffff",
    "border": "#d9e0e8",
    "text": "#24303a",
    "title": "#1f2a33",
    "hint": "#77838f",
    "input": "#ffffff",
    "button": "#ffffff",
    "button_hover": "#f3f6f9",
    "button_pressed": "#e9eef3",
    "button_disabled": "#eef1f4",
    "disabled": "#aab4be",
    "accent": "#c8321a",
    "accent_hover": "#e03a22",
    "accent_disabled": "#e8b4aa",
    "header1": "#c8321a",
    "header2": "#c8321a",
    "grid": "#edf1f5",
    "selection": "#f7e3df",
    "header": "#f7f9fb",
    "preview_bg": "#f5f7f9",
    "error": "#c0392b",
    "warning": "#a86a12",
}

DARK = {
    "bg": "#1f2329",
    "card": "#2a2f37",
    "border": "#3b434d",
    "text": "#e5e9ed",
    "title": "#f2f5f7",
    "hint": "#97a3af",
    "input": "#23282f",
    "button": "#2f353e",
    "button_hover": "#39414b",
    "button_pressed": "#262c33",
    "button_disabled": "#2a2f37",
    "disabled": "#66717d",
    "accent": "#e03a22",
    "accent_hover": "#ff7455",
    "accent_disabled": "#6e2a22",
    "header1": "#c8321a",
    "header2": "#c8321a",
    "grid": "#343b45",
    "selection": "#4a211d",
    "header": "#30363f",
    "preview_bg": "#23282f",
    "error": "#e57373",
    "warning": "#e0a94a",
}


def is_dark_palette(palette: QPalette) -> bool:
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def apply_theme_text(widget: QWidget):
    """Явно задаёт цвет подписей групп/переключателей под тему QGIS."""
    app = QApplication.instance()
    dark = bool(app is not None and is_dark_palette(app.palette()))
    color = QColor("#e5e9ed" if dark else "#24303a")
    for child in widget.findChildren(QWidget):
        if not isinstance(child, (QGroupBox, QRadioButton, QCheckBox)):
            continue
        palette = child.palette()
        palette.setColor(QPalette.ColorRole.WindowText, color)
        palette.setColor(QPalette.ColorRole.Text, color)
        palette.setColor(QPalette.ColorRole.ButtonText, color)
        child.setPalette(palette)


def build_stylesheet(palette: QPalette = None) -> str:
    dark = bool(palette is not None and is_dark_palette(palette))
    c = dict(DARK if dark else LIGHT)
    arrow_name = "chevron_down_light.svg" if dark else "chevron_down.svg"
    arrow_path = os.path.join(os.path.dirname(__file__), "assets", arrow_name)
    c["combo_arrow"] = arrow_path.replace("\\", "/")
    return """
QDialog { background: %(bg)s; }
QWidget { color: %(text)s; }
QFrame#Header {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 %(header1)s, stop:1 %(header2)s);
    border-radius: 12px;
}
QLabel#HeaderTitle { color: #ffffff; font-size: 19px; font-weight: 700; }
QLabel#HeaderSubtitle { color: rgba(255, 255, 255, 0.86); font-size: 12px; }
QLabel#HeaderLink { color: rgba(255, 255, 255, 0.92); font-size: 11px; }
QLabel#Logo { background: transparent; }
QLabel#Footer { color: %(hint)s; font-size: 10px; }
QLabel#Hint { color: %(hint)s; font-size: 11px; }
QLabel#Error { color: %(error)s; font-size: 11px; }
QLabel#Warning { color: %(warning)s; font-size: 11px; }
QLabel#Count { font-weight: 600; font-size: 12px; }
QGroupBox {
    background: %(card)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
    margin-top: 16px;
    padding: 15px 12px 12px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 0 4px;
    color: %(title)s;
}
QRadioButton, QCheckBox { spacing: 8px; color: %(text)s; }
QLineEdit, QSpinBox {
    background: %(input)s;
    border: 1px solid %(border)s;
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 19px;
    selection-background-color: %(accent)s;
    selection-color: #ffffff;
}
QComboBox {
    background: %(input)s;
    border: 1px solid %(border)s;
    border-radius: 6px;
    padding: 5px 26px 5px 8px;
    min-height: 19px;
    selection-background-color: %(accent)s;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid %(accent)s; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border: 0;
    border-left: 1px solid %(border)s;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}
QComboBox::down-arrow {
    image: url("%(combo_arrow)s");
    width: 10px;
    height: 6px;
    subcontrol-position: center;
}
QPushButton {
    background: %(button)s;
    border: 1px solid %(border)s;
    border-radius: 6px;
    padding: 7px 14px;
}
QPushButton:hover { background: %(button_hover)s; }
QPushButton:pressed { background: %(button_pressed)s; }
QPushButton:disabled {
    color: %(disabled)s;
    background: %(button_disabled)s;
}
QPushButton#Primary {
    background: %(accent)s;
    color: #ffffff;
    border: 1px solid %(accent)s;
    font-weight: 600;
}
QPushButton#Primary:hover { background: %(accent_hover)s; }
QPushButton#Primary:disabled {
    background: %(accent_disabled)s;
    border-color: %(accent_disabled)s;
    color: #eef3ee;
}
QToolButton {
    background: transparent;
    border: 0;
    padding: 4px;
    border-radius: 6px;
}
QToolButton:hover { background: %(button_hover)s; }
QTableWidget {
    background: %(card)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
    gridline-color: %(grid)s;
    selection-background-color: %(selection)s;
    selection-color: %(text)s;
}
QTableWidget::item { padding: 5px 6px; border: 0; }
QHeaderView::section {
    background: %(header)s;
    color: %(hint)s;
    padding: 7px 8px;
    border: 0;
    border-bottom: 1px solid %(border)s;
    font-weight: 600;
}
QTableCornerButton::section { background: %(header)s; border: 0; }
QProgressBar {
    border: 1px solid %(border)s;
    border-radius: 5px;
    background: %(input)s;
    text-align: center;
    min-height: 16px;
    max-height: 16px;
}
QProgressBar::chunk { background: %(accent)s; border-radius: 4px; }
QPlainTextEdit {
    background: %(input)s;
    border: 1px solid %(border)s;
    border-radius: 6px;
}
QFrame#PreviewCard {
    background: %(card)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
}
QLabel#PreviewImage {
    background: %(preview_bg)s;
    border: 1px dashed %(border)s;
    border-radius: 8px;
    color: %(hint)s;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: %(border)s;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
""" % c
