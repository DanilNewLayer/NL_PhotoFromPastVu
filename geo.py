# -*- coding: utf-8 -*-
"""Перевод охвата карты в GeoJSON WGS84 для API PastVu.

Ключевая идея: охват всегда берётся в системе координат источника
(проект для окна карты, слой для его экстента), плотно пересчитывается
в EPSG:4326 и только потом отдаётся в API. Поэтому плагин не зависит
от того, в какой СК оформлен проект.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
)

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
MERCATOR_MAX_LAT = 85.05112878
SEGMENTS_PER_EDGE = 12


class ExtentError(Exception):
    """Охват нельзя использовать: пустой, слишком большой или вне проекции."""


@dataclass
class ExtentInfo:
    geometry: dict
    west: float
    south: float
    east: float
    north: float
    width_deg: float
    height_deg: float
    zoom: int
    km_width: float
    km_height: float


def _is_valid_rect(rect: QgsRectangle) -> bool:
    if rect is None or rect.isNull():
        return False
    values = (rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())
    if not all(math.isfinite(value) for value in values):
        return False
    return rect.width() > 0 and rect.height() > 0


def _rect_points(rect: QgsRectangle, segments: int = SEGMENTS_PER_EDGE):
    """Точки по периметру прямоугольника против часовой стрелки."""
    xmin, ymin = rect.xMinimum(), rect.yMinimum()
    xmax, ymax = rect.xMaximum(), rect.yMaximum()
    points = []

    def add_edge(x1, y1, x2, y2):
        for index in range(segments):
            t = index / float(segments)
            points.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))

    add_edge(xmin, ymin, xmax, ymin)
    add_edge(xmax, ymin, xmax, ymax)
    add_edge(xmax, ymax, xmin, ymax)
    add_edge(xmin, ymax, xmin, ymin)
    return points


def _transform_points(points, src_crs):
    """Пересчитывает точки в WGS84. При сбое возвращает None."""
    if src_crs.authid() == "EPSG:4326":
        return [(point[0], point[1]) for point in points]

    transform = QgsCoordinateTransform(
        src_crs, WGS84, QgsProject.instance().transformContext()
    )
    result = []
    for x, y in points:
        try:
            point = transform.transform(x, y)
        except Exception:  # noqa: BLE001 - QgsCsException не всегда ловится
            return None
        if not (math.isfinite(point.x()) and math.isfinite(point.y())):
            return None
        result.append((point.x(), point.y()))
    return result


def _bbox_fallback(rect: QgsRectangle, src_crs):
    """Запасной путь: bounding box проекции, если углы не пересчитались."""
    try:
        transform = QgsCoordinateTransform(
            src_crs, WGS84, QgsProject.instance().transformContext()
        )
        bbox = transform.transformBoundingBox(rect)
    except Exception as exc:  # noqa: BLE001
        raise ExtentError(
            "Не удалось пересчитать охват в WGS84. Проверьте систему координат."
        ) from exc
    if bbox is None or bbox.isNull():
        raise ExtentError("Не удалось пересчитать охват в WGS84.")
    xmin = max(-180.0, min(180.0, bbox.xMinimum()))
    xmax = max(-180.0, min(180.0, bbox.xMaximum()))
    ymin = max(-MERCATOR_MAX_LAT, min(MERCATOR_MAX_LAT, bbox.yMinimum()))
    ymax = max(-MERCATOR_MAX_LAT, min(MERCATOR_MAX_LAT, bbox.yMaximum()))
    if xmin >= xmax or ymin >= ymax:
        raise ExtentError("Охват выходит за допустимые пределы карты мира.")
    points = []
    segments = 8
    for index in range(segments):
        t = index / float(segments)
        points.append((xmin + (xmax - xmin) * t, ymin))
    for index in range(segments):
        t = index / float(segments)
        points.append((xmax, ymin + (ymax - ymin) * t))
    for index in range(segments):
        t = index / float(segments)
        points.append((xmax - (xmax - xmin) * t, ymax))
    for index in range(segments):
        t = index / float(segments)
        points.append((xmin, ymax - (ymax - ymin) * t))
    return points


def _unwrap_longitudes(ring):
    """Делает долготы непрерывными, чтобы кольцо не рвалось на 180°."""
    if not ring:
        return ring
    result = [ring[0]]
    for point in ring[1:]:
        lon, lat = point
        previous = result[-1][0]
        while lon - previous > 180.0:
            lon -= 360.0
        while lon - previous < -180.0:
            lon += 360.0
        result.append((lon, lat))
    # Замыкающее ребро тоже должно быть непрерывным.
    lon, lat = result[0]
    previous = result[-1][0]
    while lon - previous > 180.0:
        lon -= 360.0
    while lon - previous < -180.0:
        lon += 360.0
    result.append((lon, lat))
    return result[:-1]


def _signed_area(ring) -> float:
    area = 0.0
    count = len(ring)
    for index in range(count):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % count]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _clip_edge(poly, inside, intersect):
    if not poly:
        return []
    output = []
    previous = poly[-1]
    previous_inside = inside(previous)
    for current in poly:
        current_inside = inside(current)
        if current_inside:
            if not previous_inside:
                output.append(intersect(previous, current))
            output.append(current)
        elif previous_inside:
            output.append(intersect(previous, current))
        previous = current
        previous_inside = current_inside
    return output


def _intersect_x(p1, p2, x):
    x1, y1 = p1
    x2, y2 = p2
    if abs(x2 - x1) < 1e-15:
        return x, y1
    t = (x - x1) / (x2 - x1)
    return x, y1 + (y2 - y1) * t


def _intersect_y(p1, p2, y):
    x1, y1 = p1
    x2, y2 = p2
    if abs(y2 - y1) < 1e-15:
        return x1, y
    t = (y - y1) / (y2 - y1)
    return x1 + (x2 - x1) * t, y


def _clip_ring(ring, xmin, ymin, xmax, ymax):
    ring = _clip_edge(
        ring, lambda p: p[0] >= xmin, lambda a, b: _intersect_x(a, b, xmin)
    )
    ring = _clip_edge(
        ring, lambda p: p[0] <= xmax, lambda a, b: _intersect_x(a, b, xmax)
    )
    ring = _clip_edge(
        ring, lambda p: p[1] >= ymin, lambda a, b: _intersect_y(a, b, ymin)
    )
    ring = _clip_edge(
        ring, lambda p: p[1] <= ymax, lambda a, b: _intersect_y(a, b, ymax)
    )
    return ring


def _split_ring(ring, lat_min, lat_max):
    """Режет непрерывное кольцо по меридианам и возвращает куски в [-180,180]."""
    pieces = []
    for shift in (-720.0, -360.0, 0.0, 360.0, 720.0):
        shifted = [(x + shift, y) for x, y in ring]
        clipped = _clip_ring(shifted, -180.0, lat_min, 180.0, lat_max)
        if len(clipped) < 3:
            continue
        min_x = min(point[0] for point in clipped)
        max_x = max(point[0] for point in clipped)
        if min_x >= 180.0:
            delta = -360.0
        elif max_x <= -180.0:
            delta = 360.0
        else:
            delta = 0.0
        piece = [(x + delta, y) for x, y in clipped]
        if abs(_signed_area(piece)) < 1e-12:
            continue
        pieces.append(piece)
    return pieces


def _close_ring(ring):
    """Замкнутое кольцо без повторяющихся соседних точек."""
    closed = []
    for x, y in ring:
        point = [float(x), float(y)]
        if closed and closed[-1] == point:
            continue
        closed.append(point)
    if len(closed) >= 3 and closed[0] != closed[-1]:
        closed.append(list(closed[0]))
    return closed


def _geometry_from_ring(ring):
    lat_min, lat_max = -MERCATOR_MAX_LAT, MERCATOR_MAX_LAT
    unwrapped = _unwrap_longitudes(ring)
    pieces = _split_ring(unwrapped, lat_min, lat_max)
    if not pieces:
        raise ExtentError("Охват не пересекается с картой мира.")
    polygons = []
    for piece in pieces:
        ring_2d = _close_ring(piece)
        # GeoJSON: внешний контур должен быть против часовой стрелки.
        if _signed_area(ring_2d) < 0:
            ring_2d.reverse()
        polygons.append(ring_2d)
    if len(polygons) == 1:
        geometry = {"type": "Polygon", "coordinates": polygons}
    else:
        geometry = {"type": "MultiPolygon", "coordinates": [[ring] for ring in polygons]}
    return geometry, unwrapped


def estimate_zoom(width_deg: float, canvas_width_px: int) -> int:
    """Оценка масштаба PastVu по ширине охвата и ширине холста QGIS."""
    if width_deg <= 0 or canvas_width_px <= 0:
        return 17
    degrees_per_pixel = width_deg / float(canvas_width_px)
    world_pixels = 360.0 / degrees_per_pixel
    zoom = math.log(max(world_pixels, 1.0) / 256.0, 2)
    return max(1, min(21, int(round(zoom))))


def build_extent(rect: QgsRectangle, src_crs, canvas_width_px: int) -> ExtentInfo:
    if not _is_valid_rect(rect):
        raise ExtentError("Охват пустой. Приблизьте карту или выберите другой слой.")
    if src_crs is None or not src_crs.isValid():
        raise ExtentError("Не удалось определить систему координат охвата.")

    points = _rect_points(rect)
    transformed = _transform_points(points, src_crs)
    if transformed is None:
        transformed = _bbox_fallback(rect, src_crs)

    geometry, unwrapped = _geometry_from_ring(transformed)

    lons = [point[0] for point in unwrapped]
    lats = [point[1] for point in unwrapped]
    west = max(-180.0, min(lons))
    east = min(180.0, max(lons))
    south = max(-MERCATOR_MAX_LAT, min(lats))
    north = min(MERCATOR_MAX_LAT, max(lats))
    width_deg = max(lons) - min(lons)
    height_deg = max(lats) - min(lats)
    if width_deg <= 0 or height_deg <= 0:
        raise ExtentError("Охват вырожден в линию. Приблизьте карту.")

    mid_lat = (south + north) / 2.0
    km_width = width_deg * 111.32 * max(0.02, math.cos(math.radians(mid_lat)))
    km_height = height_deg * 110.57

    return ExtentInfo(
        geometry=geometry,
        west=west,
        south=south,
        east=east,
        north=north,
        width_deg=width_deg,
        height_deg=height_deg,
        zoom=estimate_zoom(width_deg, canvas_width_px),
        km_width=km_width,
        km_height=km_height,
    )


def extent_from_canvas(iface, canvas_width_px: int) -> ExtentInfo:
    canvas = iface.mapCanvas()
    return build_extent(
        canvas.extent(), QgsProject.instance().crs(), canvas_width_px
    )


def extent_from_layer(layer, canvas_width_px: int) -> ExtentInfo:
    if layer is None:
        raise ExtentError("Выберите слой для поиска.")
    crs = layer.crs()
    if crs is None or not crs.isValid():
        crs = QgsProject.instance().crs()
    # Не вызываем featureCount(): для больших БД-слоёв это дорогой запрос.
    # Пустой/неопределённый экстент отсечёт build_extent().
    return build_extent(layer.extent(), crs, canvas_width_px)


def format_distance(km: float) -> str:
    if km >= 10:
        return f"{km:.0f} км"
    if km >= 1:
        return f"{km:.1f} км"
    return f"{km * 1000:.0f} м"
