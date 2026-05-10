"""PDF export helpers extracted from the original flow editor module."""

import math
from collections import deque

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QLinearGradient, QPainterPath, QPolygonF, QFontMetrics
from PyQt5.QtPrintSupport import QPrinter


def _ui_types():
    try:
        from .items import StationItem, CONNECTION_STATE
    except ImportError:
        from .items import StationItem, CONNECTION_STATE
    return StationItem, CONNECTION_STATE


def export_pdf(window):
    path = window._choose_file(
        save=True,
        title="Als PDF exportieren",
        default_name="ablaufplan.pdf",
        name_filter="PDF-Dateien (*.pdf)",
    )
    if not path:
        return
    if not path.lower().endswith(".pdf"):
        path += ".pdf"

    printer = QPrinter()
    printer.setResolution(90)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    printer.setPageSize(QPrinter.A4)
    printer.setOrientation(QPrinter.Landscape)
    printer.setFullPage(True)
    painter = QPainter(printer)
    if not painter.isActive():
        return
    try:
        paint_pdf_editor_page(window, painter, printer)
        printer.newPage()
        paint_pdf_clean_editor_page(window, painter, printer)
        #paint_pdf_clean_flow_page(window, painter, printer)
    finally:
        painter.end()
    window.statusBar().showMessage(f"PDF exportiert: {path}")


def paint_pdf_editor_page(window, painter: QPainter, printer: QPrinter):
    page_rect = printer.pageRect(QPrinter.DevicePixel)
    source = window.scene.itemsBoundingRect().adjusted(-100, -100, 100, 10)
    if source.isEmpty():
        source = window.scene.sceneRect().adjusted(0, 0, -1, -1)
    target = QRectF(30, 60, page_rect.width() - 60, page_rect.height() - 90)
    painter.translate(printer.pageRect().center())
    painter.scale(1.05, 1.05)
    painter.translate(-target.width()/2-15, -target.height()/2-15)
    window.scene.render(painter, target, source)

def paint_pdf_clean_editor_page(window, painter: QPainter, printer: QPrinter):
    from .items import ConnectionItem as ConnectionItem
    from .items import CONNECTION_STATE as CONNECTION_STATE
    page_rect = printer.pageRect(QPrinter.DevicePixel)
    for item in window.scene.items():
        if isinstance(item, ConnectionItem) and item._state==CONNECTION_STATE.ATTRIBUTE:
            item.setVisible(not item.isVisible())
    source = window.scene.itemsBoundingRect().adjusted(-100, -100, 100, 10)
    if source.isEmpty():
        source = window.scene.sceneRect().adjusted(0, 0, -1, -1)
    target = QRectF(30, 60, page_rect.width() - 60, page_rect.height() - 90)
    painter.translate(printer.pageRect().center())
    painter.scale(0.95, 0.95)
    painter.translate(-target.width()/2-15, -target.height()/2-15)
    window.scene.render(painter, target, source)
    for item in window.scene.items():
        if isinstance(item, ConnectionItem) and item._state==CONNECTION_STATE.ATTRIBUTE:
            item.setVisible(not item.isVisible())
def paint_pdf_flow_page(window, painter: QPainter, printer: QPrinter):
    StationItem, _ = _ui_types()
    page_rect = printer.pageRect(QPrinter.DevicePixel)

    stations = [item for item in window.scene.items() if isinstance(item, StationItem)]
    if not stations:
        painter.setFont(QFont("Segoe UI", 4))
        painter.drawText(QRectF(40, 70, page_rect.width() - 80, 40), Qt.AlignLeft, "Keine Stationen vorhanden.")
        return

    flow_edges = []
    preds = {station: [] for station in stations}
    succs = {station: [] for station in stations}
    for conn in window.scene._connections:
        if window.scene._connection_kind(conn) != "flow":
            continue
        src = conn.src_port.parentItem()
        dst = conn.dst_port.parentItem()
        if isinstance(src, StationItem) and isinstance(dst, StationItem):
            flow_edges.append(conn)
            preds[dst].append(src)
            succs[src].append(dst)

    in_deg = {station: len(preds[station]) for station in stations}
    queue = deque(station for station in stations if in_deg[station] == 0)
    order = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for succ in succs[node]:
            in_deg[succ] -= 1
            if in_deg[succ] == 0:
                queue.append(succ)
    for station in stations:
        if station not in order:
            order.append(station)

    left = 60
    right = page_rect.width() - 60
    top = 90
    available_width = max(200, right - left)
    step = available_width / max(1, len(order))
    node_w = min(170, max(120, step - 28))
    node_h = 74
    y = page_rect.height() / 2 - node_h / 2 + 20
    positions = {}
    for index, station in enumerate(order):
        x = left + index * step + (step - node_w) / 2
        positions[station] = QRectF(x, y, node_w, node_h)

    painter.setRenderHint(QPainter.Antialiasing)
    for conn in flow_edges:
        src = conn.src_port.parentItem()
        dst = conn.dst_port.parentItem()
        if src not in positions or dst not in positions:
            continue
        src_rect = positions[src]
        dst_rect = positions[dst]
        start = QPointF(src_rect.right(), src_rect.center().y())
        end = QPointF(dst_rect.left(), dst_rect.center().y())
        dx = max(80, (end.x() - start.x()) * 0.45)
        path = QPainterPath(start)
        path.cubicTo(QPointF(start.x() + dx, start.y()), QPointF(end.x() - dx, end.y()), end)
        pen = QPen(conn.pen().color() if conn.pen().color().isValid() else QColor("#94A3B8"), 2.3)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        arrow_end = path.pointAtPercent(1.0)
        arrow_prev = path.pointAtPercent(0.97)
        angle = math.atan2(-(arrow_end.y() - arrow_prev.y()), arrow_end.x() - arrow_prev.x())
        arr_sz = 9
        a1 = angle + math.radians(150)
        a2 = angle - math.radians(150)
        arrow = QPolygonF([
            arrow_end,
            QPointF(arrow_end.x() + arr_sz * math.cos(a1), arrow_end.y() - arr_sz * math.sin(a1)),
            QPointF(arrow_end.x() + arr_sz * math.cos(a2), arrow_end.y() - arr_sz * math.sin(a2)),
        ])
        painter.setBrush(QBrush(pen.color()))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(arrow)
        if conn.conditions:
            mid = path.pointAtPercent(0.5)
            label = f"{len(conn.conditions)} Bedingung(en)"
            fm = QFontMetrics(QFont("Segoe UI", 8))
            bounds = fm.boundingRect(label)
            box = QRectF(mid.x() - bounds.width() / 2 - 6, mid.y() - 14, bounds.width() + 12, 18)
            painter.setPen(QPen(QColor("#E2E8F0"), 1))
            painter.setBrush(QBrush(QColor(15, 23, 42, 220)))
            painter.drawRoundedRect(box, 5, 5)
            painter.drawText(box, Qt.AlignCenter, label)

    for station, rect in positions.items():
        c = QColor(station.color)
        body = QPainterPath()
        body.addRoundedRect(rect, 10, 10)
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, c.lighter(135))
        grad.setColorAt(1.0, c.darker(120))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(c.darker(160), 1.2))
        painter.drawPath(body)
        painter.setPen(QColor(255, 255, 255, 242))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(QRectF(rect.left() + 8, rect.top() + 8, rect.width() - 16, 18), Qt.AlignLeft, station.name)
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(QRectF(rect.left() + 8, rect.top() + 28, rect.width() - 16, 14), Qt.AlignLeft, f"Regeln: {len(station.rules)}")
        painter.drawText(QRectF(rect.left() + 8, rect.top() + 42, rect.width() - 16, 14), Qt.AlignLeft, f"Bedingungen: {len(station.conditions)}  /  Effekte: {len(station.effects)}")


def paint_pdf_clean_flow_page(window, painter: QPainter, printer: QPrinter):
    StationItem, CONNECTION_STATE = _ui_types()
    page_rect = printer.pageRect(QPrinter.DevicePixel)

    stations = [item for item in window.scene.items() if isinstance(item, StationItem)]
    if not stations:
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(QRectF(36, 60, page_rect.width() - 72, 24), Qt.AlignLeft, "Keine Stationen vorhanden.")
        return

    succs = {station: [] for station in stations}
    preds = {station: [] for station in stations}
    for conn in window.scene._connections:
        if window.scene._connection_kind(conn) != "flow":
            continue
        src = conn.src_port.parentItem()
        dst = conn.dst_port.parentItem()
        if isinstance(src, StationItem) and isinstance(dst, StationItem):
            succs[src].append((dst, conn))
            preds[dst].append((src, conn))

    indeg = {station: len(preds[station]) for station in stations}
    queue = deque(station for station in stations if indeg[station] == 0)
    order = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for succ, _ in succs[node]:
            indeg[succ] -= 1
            if indeg[succ] == 0:
                queue.append(succ)
    for station in stations:
        if station not in order:
            order.append(station)

    level = {station: 0 for station in stations}
    for node in order:
        for succ, _ in succs[node]:
            level[succ] = max(level[succ], level[node] + 1)

    layers = {}
    for station in order:
        layers.setdefault(level[station], []).append(station)

    left = 48
    top = 72
    right = page_rect.width() - 48
    bottom = page_rect.height() - 44
    layer_count = max(1, len(layers))
    col_w = (right - left) / layer_count
    box_w = min(170, col_w - 24)
    box_h = 52

    positions = {}
    for lv in sorted(layers.keys()):
        nodes = layers[lv]
        step_y = (bottom - top) / (len(nodes) + 1)
        x = left + lv * col_w + (col_w - box_w) / 2
        for idx, node in enumerate(nodes, start=1):
            y = top + idx * step_y - box_h / 2
            positions[node] = QRectF(x, y, box_w, box_h)

    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor("#111827"))
    painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
    painter.drawText(QRectF(36, 24, page_rect.width() - 72, 24), Qt.AlignLeft, "Flow-Ansicht (ohne Attribut-Verbindungen)")

    for src in order:
        for dst, conn in succs[src]:
            if src not in positions or dst not in positions:
                continue
            r1 = positions[src]
            r2 = positions[dst]
            start = QPointF(r1.right(), r1.center().y())
            end = QPointF(r2.left(), r2.center().y())
            mid_x = (start.x() + end.x()) / 2
            path = QPainterPath(start)
            path.lineTo(mid_x, start.y())
            path.lineTo(mid_x, end.y())
            path.lineTo(end)
            if conn._state == CONNECTION_STATE.VALID:
                color = QColor("#16A34A")
            elif conn._state in (CONNECTION_STATE.INVALID, CONNECTION_STATE.CONDITIONAL_INVALID):
                color = QColor("#DC2626")
            elif conn._state == CONNECTION_STATE.CONDITIONAL_VALID:
                color = QColor("#9A1DEE")
            else:
                color = QColor("#64748B")
            pen = QPen(color, 1.8)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            arrow = QPolygonF([
                QPointF(end.x(), end.y()),
                QPointF(end.x() - 7, end.y() - 4),
                QPointF(end.x() - 7, end.y() + 4),
            ])
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawPolygon(arrow)

    for node, rect in positions.items():
        color = QColor(node.color)
        painter.setPen(QPen(color.darker(160), 1.0))
        painter.setBrush(QBrush(color.lighter(145)))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor("#111827"))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(QRectF(rect.left() + 8, rect.top() + 7, rect.width() - 16, 18), Qt.AlignLeft, node.name)
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(
            QRectF(rect.left() + 8, rect.top() + 26, rect.width() - 16, 16),
            Qt.AlignLeft,
            f"B:{len(node.conditions)}  E:{len(node.effects)}",
        )
