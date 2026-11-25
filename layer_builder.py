# -*- coding: utf-8 -*-
"""Создание и оформление слоя с фотографиями PastVu."""

from __future__ import annotations

import os
from dataclasses import dataclass

from qgis.core import (
    QgsAction,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMarkerSymbol,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsProperty,
    QgsSvgMarkerSymbolLayer,
    QgsSymbolLayer,
    QgsUnitTypes,
    QgsVectorDataProvider,
    QgsVectorFileWriter,
    QgsVectorLayer,
    Qgis,
)
from qgis.PyQt.QtCore import QPointF, QT_VERSION_STR, QVariant
from qgis.PyQt.QtGui import QColor

from .api import photo_url
from .config import GROUP_NAME

if QT_VERSION_STR.startswith("6"):  # pragma: no cover - задел на QGIS 4
    from qgis.PyQt.QtCore import QMetaType

    INT_TYPE = QMetaType.Type.Int
    STR_TYPE = QMetaType.Type.QString
else:
    INT_TYPE = QVariant.Int
    STR_TYPE = QVariant.String

OPEN_URL_ACTION = QgsAction.ActionType.OpenUrl


def _log_optional_error(label: str, exc: Exception):
    QgsMessageLog.logMessage(
        f"{label}: {exc}", "NL_PhotoFromPastVu", Qgis.MessageLevel.Info
    )

AZIMUTH = {
    "n": 0, "ne": 45, "e": 90, "se": 135,
    "s": 180, "sw": 225, "w": 270, "nw": 315,
}

DIRECTION_RU = {
    "n": "север",
    "ne": "северо-восток",
    "e": "восток",
    "se": "юго-восток",
    "s": "юг",
    "sw": "юго-запад",
    "w": "запад",
    "nw": "северо-запад",
    "aero": "аэрофото",
}

DIRECTION_SHORT = {
    "n": "С", "ne": "СВ", "e": "В", "se": "ЮВ",
    "s": "Ю", "sw": "ЮЗ", "w": "З", "nw": "СЗ",
    "aero": "Аэро",
}

FIELD_NAMES = [
    "cid", "title", "year", "year2", "dir", "azimuth", "direction",
    "file", "Path", "thumb_url", "local_path",
]


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value) -> str:
    return "" if value is None else str(value)


def direction_labels(dir_code) -> tuple:
    code = _text(dir_code).strip().lower()
    azimuth = AZIMUTH.get(code)
    direction = DIRECTION_RU.get(code, "не указано")
    return code, azimuth, direction


def _field(name: str, field_type, alias: str) -> QgsField:
    field = QgsField(name, field_type)
    field.setAlias(alias)
    return field


def _fields():
    return [
        _field("cid", INT_TYPE, "CID"),
        _field("title", STR_TYPE, "Название"),
        _field("year", INT_TYPE, "Год"),
        _field("year2", INT_TYPE, "Год по"),
        _field("dir", STR_TYPE, "Код направления"),
        _field("azimuth", INT_TYPE, "Азимут"),
        _field("direction", STR_TYPE, "Направление"),
        _field("file", STR_TYPE, "Файл PastVu"),
        _field("Path", STR_TYPE, "Ссылка на фото"),
        _field("thumb_url", STR_TYPE, "Миниатюра"),
        _field("local_path", STR_TYPE, "Локальный путь"),
    ]


def unique_layer_name(base_name: str) -> str:
    base_name = (base_name or "Retro_Photo").strip() or "Retro_Photo"
    names = {layer.name() for layer in QgsProject.instance().mapLayers().values()}
    if base_name not in names:
        return base_name
    index = 2
    while f"{base_name} ({index})" in names:
        index += 1
    return f"{base_name} ({index})"


def _marker_symbol():
    """Стиль точки из слоя «Образец стиля»: N_azimuth.svg, поворот по azimuth."""
    svg_path = os.path.join(os.path.dirname(__file__), "assets", "N_azimuth.svg")
    if os.path.exists(svg_path):
        symbol_layer = QgsSvgMarkerSymbolLayer(svg_path)
        symbol_layer.setSize(11.5)
        symbol_layer.setSizeUnit(QgsUnitTypes.RenderUnit.RenderMillimeters)
        symbol_layer.setFillColor(QColor(200, 50, 26))
        symbol_layer.setStrokeColor(QColor(255, 255, 255))
        try:
            symbol_layer.setStrokeWidth(0)
            symbol_layer.setStrokeWidthUnit(QgsUnitTypes.RenderUnit.RenderMillimeters)
        except AttributeError as exc:
            _log_optional_error("Ширина обводки маркера", exc)
        symbol_layer.setOffset(QPointF(0.0, -1.4))
        symbol_layer.setOffsetUnit(QgsUnitTypes.RenderUnit.RenderMillimeters)
        try:
            symbol_layer.setHorizontalAnchorPoint(1)  # center
            symbol_layer.setVerticalAnchorPoint(1)    # center
        except (AttributeError, TypeError) as exc:
            _log_optional_error("Якорь маркера", exc)
        try:
            symbol_layer.setDataDefinedProperty(
                QgsSymbolLayer.Property.PropertyAngle,
                QgsProperty.fromExpression('"azimuth"'),
            )
        except (AttributeError, TypeError, RuntimeError) as exc:
            _log_optional_error("Поворот маркера по азимуту", exc)
        symbol = QgsMarkerSymbol()
        symbol.changeSymbolLayer(0, symbol_layer)
        try:
            symbol.setSize(11.5)
            symbol.setSizeUnit(QgsUnitTypes.RenderUnit.RenderMillimeters)
        except AttributeError as exc:
            _log_optional_error("Размер маркера", exc)
        return symbol
    return QgsMarkerSymbol.createSimple({
        "name": "circle",
        "color": "#c8321a",
        "size": "2.4",
        "outline_color": "#ffffff",
        "outline_width": "0.3",
    })


def _attach_actions(layer: QgsVectorLayer):
    actions = layer.actions()
    try:
        actions.addAction(
            OPEN_URL_ACTION, "Открыть на PastVu",
            "https://pastvu.com/p/[%cid%]", False,
        )
        actions.addAction(
            OPEN_URL_ACTION, "Открыть локальную копию",
            "file:///[%local_path%]", False,
        )
    except (AttributeError, TypeError, RuntimeError) as exc:
        _log_optional_error("Действия слоя", exc)


def create_layer(photos, base_name: str = "Retro_Photo") -> QgsVectorLayer:
    """Создаёт memory-слой EPSG:4326 с точками и заполненными атрибутами."""
    layer = QgsVectorLayer("Point?crs=EPSG:4326", unique_layer_name(base_name), "memory")
    if not layer.isValid():
        raise RuntimeError("Не удалось создать временный слой QGIS.")

    provider = layer.dataProvider()
    provider.addAttributes(_fields())
    layer.updateFields()

    features = []
    for photo in photos:
        geo = photo.get("geo")
        if not isinstance(geo, (list, tuple)) or len(geo) < 2:
            continue
        try:
            lat, lon = float(geo[0]), float(geo[1])
        except (TypeError, ValueError):
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        dir_code, azimuth, direction = direction_labels(photo.get("dir"))
        file_value = _text(photo.get("file"))
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
        feature.setAttributes([
            _to_int(photo.get("cid")),
            _text(photo.get("title")),
            _to_int(photo.get("year")),
            _to_int(photo.get("year2")),
            dir_code,
            azimuth,
            direction,
            file_value,
            photo_url(file_value, "d"),
            photo_url(file_value, "h"),
            "",
        ])
        features.append(feature)

    if not features:
        raise RuntimeError("В ответе PastVu не оказалось фотографий с координатами.")

    provider.addFeatures(features)
    layer.updateExtents()
    layer.setCustomProperty("adm_photofrompastvu", "1")
    layer.renderer().setSymbol(_marker_symbol())
    _attach_actions(layer)
    layer.triggerRepaint()
    return layer


def add_layer_to_project(layer: QgsVectorLayer, group_name: str):
    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup(group_name)
    if group is None:
        group = root.insertGroup(0, group_name)
    QgsProject.instance().addMapLayer(layer, False)
    group.addLayer(layer)
    return group


def update_local_paths(layer, mapping: dict) -> int:
    """Пишет локальные пути в поле local_path по fid -> путь."""
    if layer is None or not layer.isValid():
        return 0
    field_index = layer.fields().indexOf("local_path")
    if field_index < 0 or not mapping:
        return 0

    changes = {int(fid): {field_index: str(path)} for fid, path in mapping.items() if path}
    if not changes:
        return 0

    provider = layer.dataProvider()
    change_capability = QgsVectorDataProvider.Capability.ChangeAttributeValues

    if provider.capabilities() & change_capability:
        if provider.changeAttributeValues(changes):
            layer.triggerRepaint()
            return len(changes)

    started = False
    if not layer.isEditable():
        if not layer.startEditing():
            return 0
        started = True
    try:
        for fid, attrs in changes.items():
            for index, value in attrs.items():
                layer.changeAttributeValue(fid, index, value)
    except Exception:  # noqa: BLE001
        if started:
            layer.rollBack()
        return 0
    if started:
        if not layer.commitChanges():
            return 0
    layer.triggerRepaint()
    return len(changes)


@dataclass
class SavedLayer:
    path: str
    uri: str
    layer_name: str
    driver: str


def save_layer_as(layer, path: str) -> SavedLayer:
    """Сохраняет слой в файл по расширению."""
    extension = os.path.splitext(path)[1].lower()
    drivers = {
        ".gpkg": "GPKG",
        ".geojson": "GeoJSON",
        ".json": "GeoJSON",
        ".shp": "ESRI Shapefile",
        ".kml": "KML",
    }
    driver = drivers.get(extension, "GPKG")
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.fileEncoding = "UTF-8"
    options.layerName = os.path.splitext(os.path.basename(path))[0]
    if driver == "GPKG" and os.path.exists(path):
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        )

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, QgsProject.instance().transformContext(), options
    )
    error_code, error_message = result[0], result[1]
    if error_code != QgsVectorFileWriter.WriterError.NoError:
        raise IOError(error_message or "Не удалось сохранить слой.")
    saved_path = result[2] if len(result) > 2 and result[2] else path
    saved_name = result[3] if len(result) > 3 and result[3] else options.layerName
    uri = f"{saved_path}|layername={saved_name}" if driver == "GPKG" else saved_path
    return SavedLayer(saved_path, uri, saved_name, driver)


def open_saved_layer(saved: SavedLayer, display_name: str, source_layer):
    """Открывает сохранённый файл и переносит оформление исходного слоя."""
    layer = QgsVectorLayer(saved.uri, display_name or saved.layer_name, "ogr")
    if not layer.isValid():
        raise IOError(f"Не удалось открыть сохранённый слой: {saved.path}")
    layer.setName(display_name or saved.layer_name)
    try:
        layer.setRenderer(source_layer.renderer().clone())
    except (AttributeError, RuntimeError, TypeError) as exc:
        _log_optional_error("Перенос рендерера", exc)
    aliases = {field.name(): field.alias() for field in source_layer.fields()}
    for field in layer.fields():
        alias = aliases.get(field.name())
        if alias:
            try:
                layer.setFieldAlias(field.name(), alias)
            except (AttributeError, RuntimeError, TypeError) as exc:
                _log_optional_error(f"Псевдоним поля {field.name()}", exc)
    try:
        layer.setOpacity(source_layer.opacity())
    except (AttributeError, RuntimeError, TypeError) as exc:
        _log_optional_error("Прозрачность слоя", exc)
    try:
        if source_layer.displayExpression():
            layer.setDisplayExpression(source_layer.displayExpression())
    except (AttributeError, RuntimeError, TypeError) as exc:
        _log_optional_error("Выражение отображения", exc)
    try:
        layer.setLabelsEnabled(source_layer.labelsEnabled())
        labeling = source_layer.labeling()
        if labeling is not None:
            layer.setLabeling(labeling.clone())
    except (AttributeError, RuntimeError, TypeError) as exc:
        _log_optional_error("Подписи слоя", exc)
    layer.setCustomProperty("adm_photofrompastvu", "1")
    _attach_actions(layer)
    return layer


def replace_layer_in_project(old_layer, new_layer):
    """Ставит файловый слой на место временного, сохраняя позицию в дереве."""
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    old_node = root.findLayer(old_layer.id())
    parent = old_node.parent() if old_node is not None else None
    index = -1
    if old_node is not None and parent is not None:
        for position, node in enumerate(parent.children()):
            if node is old_node or (
                hasattr(node, "layerId") and node.layerId() == old_layer.id()
            ):
                index = position
                break

    project.addMapLayer(new_layer, False)
    try:
        if parent is not None and index >= 0:
            parent.insertLayer(index, new_layer)
        else:
            group = root.findGroup(GROUP_NAME)
            if group is not None:
                group.addLayer(new_layer)
            else:
                root.insertLayer(0, new_layer)
        project.removeMapLayer(old_layer.id())
    except Exception:
        project.removeMapLayer(new_layer.id())
        raise
    return new_layer
