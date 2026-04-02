#!/usr/bin/env python3
"""
Ablaufplan-Editor  –  PyQt5
============================
Erstellt Ablaufpläne mit Stationen, Bedingungen, Effekten und Verbindungen.

Starten:
    pip install PyQt5
    python flow_editor.py
"""

import sys
import math
import uuid
import json
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QAbstractItemView,
    QGraphicsScene, QGraphicsView, QGraphicsItem, QGraphicsEllipseItem,
    QGraphicsPathItem, QGraphicsRectItem, QFrame, QDialog, QDialogButtonBox,
    QLineEdit, QComboBox, QGroupBox, QScrollArea, QPlainTextEdit,
    QAction, QMessageBox, QColorDialog, QSizePolicy, QToolBar,
    QSpacerItem, QStatusBar, QFileDialog
)
from PyQt5.QtCore import (
    Qt, QRectF, QPointF, QLineF, QPoint, QRect, pyqtSignal, QMimeData,
    QSizeF
)
from PyQt5.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QLinearGradient, QRadialGradient,
    QPainterPath, QPolygonF, QPixmap, QDrag, QPalette, QKeyEvent, QTransform,
    QFontMetrics, QIcon, QCursor
)
from PyQt5.QtPrintSupport import QPrinter
from collections import deque


# ══════════════════════════════════════════════════════════════════════════════
#  DATENMODELLE
# ══════════════════════════════════════════════════════════════════════════════

class Condition:
    """Vorbedingung an einem Produktattribut."""
    SUBJECT_VALUE = "value"
    SUBJECT_COUNT = "count"

    OP_EXISTS     = "exists"
    OP_NOT_EXISTS = "not_exists"
    OP_EQUALS     = "equals"
    OP_NOT_EQUALS = "not_equals"
    OP_GREATER    = "greater"
    OP_GREATER_EQ = "greater_eq"
    OP_LESS       = "less"
    OP_LESS_EQ    = "less_eq"

    SUBJECT_LABELS = {
        SUBJECT_VALUE: "Attribut",
        SUBJECT_COUNT: "Anzahl",
    }

    OP_LABELS = {
        OP_EXISTS:     "existiert",
        OP_NOT_EXISTS: "existiert nicht",
        OP_EQUALS:     "= Eintrag",
        OP_NOT_EQUALS: "≠ Eintrag",
        OP_GREATER:    ">",
        OP_GREATER_EQ: ">=",
        OP_LESS:       "<",
        OP_LESS_EQ:    "<=",
    }

    def __init__(self, attribute="", subject=None, operator=None, value=""):
        self.attribute = attribute
        self.subject   = subject or self.SUBJECT_VALUE
        self.operator  = operator or self.OP_EXISTS
        self.value     = value

    @staticmethod
    def _state_for(attrs: dict, attribute: str):
        state = attrs.get(attribute)
        if isinstance(state, dict):
            return state
        if state is None:
            return None
        return {"value": state, "count": 1}

    def _as_number(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def check(self, attrs: dict) -> bool:
        state = self._state_for(attrs, self.attribute)
        if self.subject == self.SUBJECT_COUNT:
            count = 0 if state is None else self._as_number(state.get("count", 0))
            if self.operator == self.OP_EXISTS:
                return count > 0
            if self.operator == self.OP_NOT_EXISTS:
                return count <= 0
            target = self._as_number(self.value)
            if self.operator == self.OP_EQUALS:
                return count == target
            if self.operator == self.OP_NOT_EQUALS:
                return count != target
            if self.operator == self.OP_GREATER:
                return count > target
            if self.operator == self.OP_GREATER_EQ:
                return count >= target
            if self.operator == self.OP_LESS:
                return count < target
            if self.operator == self.OP_LESS_EQ:
                return count <= target
            return True

        if self.operator == self.OP_EXISTS:
            return state is not None
        if self.operator == self.OP_NOT_EXISTS:
            return state is None
        current = None if state is None else state.get("value")
        if self.operator == self.OP_EQUALS:
            return current == self.value
        if self.operator == self.OP_NOT_EQUALS:
            return current != self.value
        return True

    def __str__(self):
        a = self.attribute or "?"
        if self.subject == self.SUBJECT_COUNT:
            prefix = f"Anzahl(⟨{a}⟩)"
            if self.operator == self.OP_EXISTS:
                return f"{prefix} vorhanden"
            if self.operator == self.OP_NOT_EXISTS:
                return f"{prefix} fehlt"
            if self.operator in {self.OP_EQUALS, self.OP_NOT_EQUALS,
                                 self.OP_GREATER, self.OP_GREATER_EQ,
                                 self.OP_LESS, self.OP_LESS_EQ}:
                return f"{prefix} {self.OP_LABELS.get(self.operator, self.operator)} {self.value}"
            return prefix
        if self.operator == self.OP_EXISTS:
            return f"⟨{a}⟩ vorhanden"
        if self.operator == self.OP_NOT_EXISTS:
            return f"⟨{a}⟩ fehlt"
        if self.operator == self.OP_EQUALS:
            return f"⟨{a}⟩ = '{self.value}'"
        if self.operator == self.OP_NOT_EQUALS:
            return f"⟨{a}⟩ ≠ '{self.value}'"
        return ""


class Effect:
    """Ausgangseffekt auf ein Produktattribut."""
    ACT_ADD    = "add"
    ACT_REMOVE = "remove"
    ACT_SET    = "set"

    ACT_LABELS = {
        ACT_ADD:    "Hinzufügen",
        ACT_REMOVE: "Entfernen",
        ACT_SET:    "Setzen / Überschreiben",
    }

    def __init__(self, action=None, attribute="", value=""):
        self.action    = action or self.ACT_ADD
        self.attribute = attribute
        self.value     = value

    def apply(self, attrs: dict) -> dict:
        """Wendet den Effekt an und gibt ein neues dict zurück."""
        attrs = dict(attrs)
        if self.action in (self.ACT_ADD, self.ACT_SET):
            current = attrs.get(self.attribute)
            count = 1
            if isinstance(current, dict):
                count = max(1, int(current.get("count", 1)))
            attrs[self.attribute] = {"value": self.value, "count": count}
        elif self.action == self.ACT_REMOVE:
            attrs.pop(self.attribute, None)
        return attrs

    def __str__(self):
        a = self.attribute or "?"
        if self.action == self.ACT_ADD:
            return f"+ ⟨{a}⟩ = '{self.value}'"
        if self.action == self.ACT_REMOVE:
            return f"− ⟨{a}⟩"
        if self.action == self.ACT_SET:
            return f"~ ⟨{a}⟩ = '{self.value}'"
        return ""


# ══════════════════════════════════════════════════════════════════════════════
#  GRAFIK-KONSTANTEN
# ══════════════════════════════════════════════════════════════════════════════

PORT_R         = 7
STATION_W      = 200
STATION_H_MIN  = 72
HEADER_H       = 28
LINE_H         = 17

PALETTE_COLORS = [
    ("#2563EB", "Station  –  Blau"),
    ("#DC2626", "Station  –  Rot"),
    ("#16A34A", "Station  –  Grün"),
    ("#9333EA", "Station  –  Lila"),
    ("#EA580C", "Station  –  Orange"),
    ("#0891B2", "Station  –  Cyan"),
]


# ══════════════════════════════════════════════════════════════════════════════
#  PORT
# ══════════════════════════════════════════════════════════════════════════════

class Port(QGraphicsEllipseItem):
    INPUT  = "input"
    OUTPUT = "output"
    ATTR_INPUT  = "attr_input"
    ATTR_OUTPUT = "attr_output"

    def __init__(self, port_type: str, parent: QGraphicsItem):
        r = PORT_R
        super().__init__(-r, -r, r * 2, r * 2, parent)
        self.port_type   = port_type
        self.connections = []          # list[ConnectionItem]
        self._base_style()
        self.setAcceptHoverEvents(True)
        self.setZValue(20)
        self.setCursor(Qt.CrossCursor)

    def _base_style(self):
        if self.port_type == self.INPUT:
            self.setBrush(QBrush(QColor("#22C55E")))
            self.setPen(QPen(QColor("#15803D"), 1.5))
        elif self.port_type == self.ATTR_INPUT:
            self.setBrush(QBrush(QColor("#F59E0B")))
            self.setPen(QPen(QColor("#B45309"), 1.5))
        elif self.port_type == self.ATTR_OUTPUT:
            self.setBrush(QBrush(QColor("#FBBF24")))
            self.setPen(QPen(QColor("#B45309"), 1.5))
        else:
            self.setBrush(QBrush(QColor("#3B82F6")))
            self.setPen(QPen(QColor("#1D4ED8"), 1.5))

    def is_input(self) -> bool:
        return self.port_type in {self.INPUT, self.ATTR_INPUT}

    def is_output(self) -> bool:
        return self.port_type in {self.OUTPUT, self.ATTR_OUTPUT}

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor("#FCD34D")))
        self.setPen(QPen(QColor("#B45309"), 2))

    def hoverLeaveEvent(self, event):
        self._base_style()

    def scene_pos(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))


# ══════════════════════════════════════════════════════════════════════════════
#  STATIONSITEM
# ══════════════════════════════════════════════════════════════════════════════

class StationItem(QGraphicsItem):
    ItemType = QGraphicsItem.UserType + 1

    def __init__(self, name: str = "Station", color: QColor = None):
        super().__init__()
        self.station_name = name
        self.color        = color or QColor("#2563EB")
        self.node_id      = uuid.uuid4().hex
        self.conditions   = []   # list[Condition]
        self.effects      = []   # list[Effect]
        self.template_id  = uuid.uuid4().hex

        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

        self._w = STATION_W
        self._h = STATION_H_MIN

        self.in_port  = Port(Port.INPUT,  self)
        self.out_port = Port(Port.OUTPUT, self)
        self.attr_port = Port(Port.ATTR_INPUT, self)
        self._layout()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _layout(self):
        rows = len(self.conditions) + len(self.effects)
        extra = max(0, rows - 1) * LINE_H
        self._h = STATION_H_MIN + extra
        half_h = self._h / 2
        self.attr_port.setPos(0, HEADER_H / 2)
        self.in_port.setPos(0, half_h)
        self.out_port.setPos(self._w, half_h)
        self.prepareGeometryChange()

    def type(self):
        return self.ItemType

    # ── Bounding / Shape ──────────────────────────────────────────────────────

    def boundingRect(self) -> QRectF:
        m = PORT_R + 2
        return QRectF(-m, -m, self._w + m * 2, self._h + m * 2)

    def shape(self) -> QPainterPath:
        p = QPainterPath()
        p.addRoundedRect(QRectF(0, 0, self._w, self._h), 10, 10)
        return p

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self._w, self._h)

        # ── Drop shadow ──
        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(rect.adjusted(3, 4, 3, 4), 10, 10)
        painter.fillPath(shadow_path, QColor(0, 0, 0, 35))

        # ── Body gradient ──
        body_path = QPainterPath()
        body_path.addRoundedRect(rect, 10, 10)
        grad = QLinearGradient(0, 0, 0, self._h)
        c = QColor(self.color)
        grad.setColorAt(0.0, c.lighter(135))
        grad.setColorAt(0.5, c)
        grad.setColorAt(1.0, c.darker(115))
        painter.fillPath(body_path, QBrush(grad))

        # ── Border ──
        if self.isSelected():
            painter.setPen(QPen(QColor("#FCD34D"), 2.5))
        else:
            painter.setPen(QPen(c.darker(160), 1.2))
        painter.drawPath(body_path)

        # ── Header strip ──
        header_path = QPainterPath()
        header_path.addRoundedRect(QRectF(0, 0, self._w, HEADER_H), 10, 10)
        # Fill bottom portion to make it square-bottomed
        header_path.addRect(QRectF(0, 10, self._w, HEADER_H - 10))
        painter.setPen(Qt.NoPen)
        painter.fillPath(header_path, c.darker(145))

        # ── Title ──
        painter.setPen(QColor(255, 255, 255, 240))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(
            QRectF(10, 2, self._w - 20, HEADER_H - 4),
            Qt.AlignVCenter | Qt.AlignLeft,
            self.station_name
        )

        # ── Conditions ──
        y = HEADER_H + 5
        painter.setFont(QFont("Consolas", 7))

        if self.conditions:
            for cond in self.conditions:
                text = str(cond)
                painter.setPen(QColor("#FCA5A5"))
                painter.drawText(QRectF(8, y, self._w - 16, LINE_H),
                                 Qt.AlignVCenter | Qt.AlignLeft, text)
                y += LINE_H
        else:
            painter.setPen(QColor(255, 255, 255, 60))
            painter.drawText(QRectF(8, y, self._w - 16, LINE_H),
                             Qt.AlignVCenter, "keine Eingangsbedingungen")
            y += LINE_H

        # Divider
        if self.effects:
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
            painter.drawLine(QPointF(8, y), QPointF(self._w - 8, y))

        if self.effects:
            y += 2
            for eff in self.effects:
                text = str(eff)
                painter.setPen(QColor("#86EFAC"))
                painter.drawText(QRectF(8, y, self._w - 16, LINE_H),
                                 Qt.AlignVCenter | Qt.AlignLeft, text)
                y += LINE_H

    # ── Events ────────────────────────────────────────────────────────────────

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.scene().update_connections_for(self)
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        if self.scene():
            self.scene().open_station_editor(self)

    def all_connections(self):
        return list(self.in_port.connections) + list(self.out_port.connections) + list(self.attr_port.connections)

    def flow_connections(self):
        return list(self.in_port.connections) + list(self.out_port.connections)

    def clone(self):
        item = StationItem(self.station_name, QColor(self.color))
        item.conditions = [Condition(c.attribute, c.subject, c.operator, c.value) for c in self.conditions]
        item.effects = [Effect(e.action, e.attribute, e.value) for e in self.effects]
        item._layout()
        return item


class AttributeItem(QGraphicsItem):
    ItemType = QGraphicsItem.UserType + 4

    def __init__(self, name: str = "Attribut", count: int = 1, color: QColor = None):
        super().__init__()
        self.attribute_name = name
        self.attribute_count = count
        self.color           = color or QColor("#F59E0B")
        self.node_id         = uuid.uuid4().hex
        self.template_id     = uuid.uuid4().hex

        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

        self._w = 180
        self._h = 64
        self.out_port = Port(Port.ATTR_OUTPUT, self)
        self._layout()

    def _layout(self):
        self.out_port.setPos(self._w, self._h / 2)
        self.prepareGeometryChange()

    def type(self):
        return self.ItemType

    def boundingRect(self) -> QRectF:
        m = PORT_R + 2
        return QRectF(-m, -m, self._w + m * 2, self._h + m * 2)

    def shape(self) -> QPainterPath:
        p = QPainterPath()
        p.addRoundedRect(QRectF(0, 0, self._w, self._h), 12, 12)
        return p

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self._w, self._h)

        shadow = QPainterPath()
        shadow.addRoundedRect(rect.adjusted(2, 3, 2, 3), 8, 8)
        painter.fillPath(shadow, QColor(0, 0, 0, 28))

        body = QPainterPath()
        body.addRoundedRect(rect, 8, 8)
        grad = QLinearGradient(0, 0, 0, self._h)
        c = QColor(self.color)
        grad.setColorAt(0.0, c.lighter(140))
        grad.setColorAt(1.0, c.darker(115))
        painter.fillPath(body, QBrush(grad))

        if self.isSelected():
            painter.setPen(QPen(QColor("#FCD34D"), 2.5))
        else:
            painter.setPen(QPen(c.darker(160), 1.2))
        painter.drawPath(body)

        painter.setPen(QColor(255, 255, 255, 240))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(QRectF(10, 8, self._w - 20, 18), Qt.AlignLeft | Qt.AlignVCenter, self.attribute_name)

        painter.setFont(QFont("Consolas", 8))
        painter.drawText(QRectF(10, 42, self._w - 20, 16), Qt.AlignLeft | Qt.AlignVCenter,
                         f"Anzahl: {self.attribute_count}")

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.scene().update_connections_for(self)
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        if self.scene():
            self.scene().open_attribute_editor(self)

    def all_connections(self):
        return list(self.out_port.connections)

    def clone(self):
        item = AttributeItem(self.attribute_name, self.attribute_count, QColor(self.color))
        item._layout()
        return item


# ══════════════════════════════════════════════════════════════════════════════
#  TEXTBLOCKITEM
# ══════════════════════════════════════════════════════════════════════════════

class TextBlockItem(QGraphicsItem):
    ItemType = QGraphicsItem.UserType + 2

    def __init__(self, text: str = "Beschreibung ..."):
        super().__init__()
        self.node_id = uuid.uuid4().hex
        self._text = text
        self._w    = 180
        self._h    = 70
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )

    def type(self):
        return self.ItemType

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def _recalc_height(self):
        fm   = QFontMetrics(QFont("Segoe UI", 8))
        self._h = max(50, fm.boundingRect(
            QRect(0, 0, self._w - 16, 2000),
            Qt.TextWordWrap, self._text
        ).height() + 20)
        self.prepareGeometryChange()

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self._w, self._h)

        # Shadow
        shadow = QPainterPath()
        shadow.addRoundedRect(rect.adjusted(2, 3, 2, 3), 6, 6)
        painter.fillPath(shadow, QColor(0, 0, 0, 25))

        # Body
        body = QPainterPath()
        body.addRoundedRect(rect, 6, 6)
        painter.fillPath(body, QBrush(QColor(255, 252, 220, 235)))

        # Fold corner decoration
        fold = 14
        corner_pts = [
            QPointF(self._w - fold, 0),
            QPointF(self._w, fold),
            QPointF(self._w - fold, fold),
        ]
        fold_poly = QPolygonF(corner_pts + [QPointF(self._w - fold, 0)])
        painter.setBrush(QBrush(QColor(245, 200, 80, 180)))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(fold_poly)

        # Border
        if self.isSelected():
            painter.setPen(QPen(QColor("#F59E0B"), 2, Qt.DashLine))
        else:
            painter.setPen(QPen(QColor("#D97706"), 1.2))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(body)

        # Text
        painter.setPen(QColor("#44200A"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(
            QRectF(8, 6, self._w - 16 - fold, self._h - 12),
            Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
            self._text
        )

    def mouseDoubleClickEvent(self, event):
        if self.scene():
            self.scene().open_text_editor(self)


# ══════════════════════════════════════════════════════════════════════════════
#  VERBINDUNGS-ITEM
# ══════════════════════════════════════════════════════════════════════════════

class ConnectionItem(QGraphicsPathItem):
    ItemType = QGraphicsItem.UserType + 3

    STATE_UNKNOWN = None
    STATE_VALID   = True
    STATE_INVALID = False

    COLOR_UNKNOWN = QColor("#94A3B8")
    COLOR_VALID   = QColor("#22C55E")
    COLOR_INVALID = QColor("#EF4444")

    def __init__(self, src_port: Port, dst_port: Port = None):
        super().__init__()
        self.src_port   = src_port
        self.dst_port   = dst_port
        self.conditions = []
        self._invalid_reasons = []
        self._state     = self.STATE_UNKNOWN
        self._drag_end  = None
        self.setZValue(-5)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self._rebuild()

    # ── Path ──────────────────────────────────────────────────────────────────

    def _rebuild(self):
        if self.src_port is None:
            return
        start = self.src_port.scene_pos()
        end   = self._drag_end if self._drag_end else (
            self.dst_port.scene_pos() if self.dst_port else start
        )
        dx = end.x() - start.x()
        cp = max(abs(dx) * 0.55, 80)
        c1 = QPointF(start.x() + cp, start.y())
        c2 = QPointF(end.x()  - cp, end.y())
        path = QPainterPath(start)
        path.cubicTo(c1, c2, end)
        self.setPath(path)
        self._apply_style()

    def update_path(self):
        self._rebuild()

    def set_drag_end(self, pt: QPointF):
        self._drag_end = pt
        self._rebuild()

    def finalize(self, dst_port: Port):
        self.dst_port  = dst_port
        self._drag_end = None
        self._rebuild()

    # ── Style ─────────────────────────────────────────────────────────────────

    def _apply_style(self):
        if self._state is self.STATE_VALID:
            col = self.COLOR_VALID
        elif self._state is self.STATE_INVALID:
            col = self.COLOR_INVALID
        else:
            col = self.COLOR_UNKNOWN
        self.setPen(QPen(col, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def set_state(self, state):
        if self._state != state:
            self._state = state
            self._apply_style()

    def doubleClickTarget(self):
        return self.src_port.parentItem() if self.src_port else None

    # ── Paint (Pfeilspitze) ───────────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)

        if self.isSelected():
            sel_pen = QPen(QColor("#FCD34D"), 5, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.path())

        super().paint(painter, option, widget)

        # Arrow at endpoint
        path = self.path()
        if path.isEmpty():
            return
        end    = path.pointAtPercent(1.0)
        near   = path.pointAtPercent(0.97)
        angle  = math.atan2(-(end.y() - near.y()), end.x() - near.x())
        arr_sz = 10
        a1     = angle + math.radians(150)
        a2     = angle - math.radians(150)
        arrow  = QPolygonF([
            end,
            QPointF(end.x() + arr_sz * math.cos(a1),
                    end.y() - arr_sz * math.sin(a1)),
            QPointF(end.x() + arr_sz * math.cos(a2),
                    end.y() - arr_sz * math.sin(a2)),
        ])
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self.pen().color()))
        painter.drawPolygon(arrow)

        if self.conditions:
            # Ein Stern markiert Bedingungen direkt im Editor.
            mid = path.pointAtPercent(0.5)
            star_rect = QRectF(mid.x() - 9, mid.y() - 13, 18, 18)
            painter.setPen(QPen(QColor("#FCD34D"), 1.2))
            painter.setBrush(QBrush(QColor(15, 23, 42, 230)))
            painter.drawRoundedRect(star_rect, 4, 4)
            painter.setPen(QColor("#FCD34D"))
            painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
            painter.drawText(star_rect, Qt.AlignCenter, "*")

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(-15, -15, 15, 15)

    def mouseDoubleClickEvent(self, event):
        scene = self.scene()
        if scene and hasattr(scene, "open_connection_editor"):
            scene.open_connection_editor(self)


# ══════════════════════════════════════════════════════════════════════════════
#  DIALOGE
# ══════════════════════════════════════════════════════════════════════════════

DIALOG_STYLE = """
QDialog {
    background: #1E293B;
    color: #E2E8F0;
}
QLabel {
    color: #CBD5E1;
    font-size: 12px;
}
QGroupBox {
    color: #94A3B8;
    border: 1px solid #334155;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
    font-size: 11px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QLineEdit, QPlainTextEdit {
    background: #0F172A;
    border: 1px solid #334155;
    border-radius: 4px;
    color: #E2E8F0;
    padding: 3px 6px;
    font-size: 12px;
}
QLineEdit:focus, QPlainTextEdit:focus {
    border-color: #3B82F6;
}
QComboBox {
    background: #0F172A;
    border: 1px solid #334155;
    border-radius: 4px;
    color: #E2E8F0;
    padding: 3px 6px;
    font-size: 12px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: #1E293B;
    color: #E2E8F0;
    selection-background-color: #3B82F6;
}
QPushButton {
    background: #334155;
    border: 1px solid #475569;
    border-radius: 5px;
    color: #E2E8F0;
    padding: 4px 10px;
    font-size: 12px;
}
QPushButton:hover  { background: #475569; }
QPushButton:pressed { background: #1E40AF; }
QPushButton#ok_btn {
    background: #2563EB;
    border-color: #1D4ED8;
    font-weight: bold;
}
QPushButton#ok_btn:hover { background: #1D4ED8; }
QPushButton#add_btn {
    background: #064E3B;
    border-color: #065F46;
    color: #6EE7B7;
}
QPushButton#add_btn:hover { background: #065F46; }
QPushButton#del_btn {
    background: transparent;
    border: none;
    color: #94A3B8;
    font-size: 14px;
    padding: 0 4px;
}
QPushButton#del_btn:hover { color: #EF4444; }
QScrollArea { border: none; background: transparent; }
"""


class ConditionRow(QWidget):
    removed = pyqtSignal(object)

    def __init__(self, cond: Condition, attribute_options=None, parent=None):
        super().__init__(parent)
        self._cond = cond
        self._attribute_options = list(attribute_options or [])
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(4)

        self.subject = QComboBox()
        for key, label in Condition.SUBJECT_LABELS.items():
            self.subject.addItem(label, key)
        idx = self.subject.findData(cond.subject)
        self.subject.setCurrentIndex(max(idx, 0))
        self.subject.currentIndexChanged.connect(self._refresh_ops)

        self.attr = QComboBox()
        self.attr.setFixedWidth(160)
        self._fill_attribute_dropdown(cond.attribute)

        self.op = QComboBox()
        self.op.currentIndexChanged.connect(self._on_op)

        self.val = QLineEdit(cond.value)
        self.val.setPlaceholderText("Eintrag / Anzahl")
        self.val.setFixedWidth(90)
        self._refresh_ops()
        op_idx = self.op.findData(cond.operator)
        self.op.setCurrentIndex(max(op_idx, 0))
        self._on_op(self.op.currentIndex())

        btn = QPushButton("✕")
        btn.setObjectName("del_btn")
        btn.setFixedSize(22, 22)
        btn.clicked.connect(lambda: self.removed.emit(self))

        lo.addWidget(self.subject)
        lo.addWidget(self.attr)
        lo.addWidget(self.op)
        lo.addWidget(self.val)
        lo.addWidget(btn)

    def _ops_for_subject(self):
        subject = self.subject.currentData()
        if subject == Condition.SUBJECT_COUNT:
            return [
                Condition.OP_EXISTS,
                Condition.OP_NOT_EXISTS,
                Condition.OP_EQUALS,
                Condition.OP_NOT_EQUALS,
                Condition.OP_GREATER,
                Condition.OP_GREATER_EQ,
                Condition.OP_LESS,
                Condition.OP_LESS_EQ,
            ]
        return [
            Condition.OP_EXISTS,
            Condition.OP_NOT_EXISTS,
            Condition.OP_EQUALS,
            Condition.OP_NOT_EQUALS,
        ]

    def _refresh_ops(self, *args):
        current = self.op.currentData()
        self.op.blockSignals(True)
        self.op.clear()
        for op_key in self._ops_for_subject():
            self.op.addItem(Condition.OP_LABELS.get(op_key, op_key), op_key)
        idx = self.op.findData(current)
        self.op.setCurrentIndex(max(idx, 0))
        self.op.blockSignals(False)
        self._on_op(self.op.currentIndex())

    def _on_op(self, idx):
        op_key = self.op.itemData(idx)
        self.val.setVisible(op_key not in {Condition.OP_EXISTS, Condition.OP_NOT_EXISTS})

    def _fill_attribute_dropdown(self, selected_attr: str):
        seen = set()
        self.attr.clear()
        self.attr.addItem("(Attribut wählen)", "")
        seen.add("")
        for name in self._attribute_options:
            key = (name or "").strip()
            if key and key not in seen:
                self.attr.addItem(key, key)
                seen.add(key)
        selected = (selected_attr or "").strip()
        if selected and selected not in seen:
            self.attr.addItem(selected, selected)
            seen.add(selected)
        idx = self.attr.findData(selected)
        if idx < 0:
            idx = 0
        self.attr.setCurrentIndex(idx)

    def get(self) -> Condition:
        return Condition(
            self.attr.currentData() or "",
            self.subject.currentData(),
            self.op.currentData(),
            self.val.text()
        )


class EffectRow(QWidget):
    removed = pyqtSignal(object)

    def __init__(self, eff: Effect, attribute_options=None, parent=None):
        super().__init__(parent)
        self._eff = eff
        self._attribute_options = list(attribute_options or [])
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(4)

        self.act = QComboBox()
        self._acts = [Effect.ACT_ADD, Effect.ACT_REMOVE, Effect.ACT_SET]
        for lbl in Effect.ACT_LABELS.values():
            self.act.addItem(lbl)
        idx = self._acts.index(eff.action) if eff.action in self._acts else 0
        self.act.setCurrentIndex(idx)
        self.act.currentIndexChanged.connect(self._on_act)

        self.attr = QComboBox()
        self.attr.setFixedWidth(160)
        self._fill_attribute_dropdown(eff.attribute)

        self.val = QLineEdit(eff.value)
        self.val.setPlaceholderText("Anzahl")
        self.val.setFixedWidth(90)
        self.val.setVisible(idx != 1)

        btn = QPushButton("✕")
        btn.setObjectName("del_btn")
        btn.setFixedSize(22, 22)
        btn.clicked.connect(lambda: self.removed.emit(self))

        lo.addWidget(self.act)
        lo.addWidget(self.attr)
        lo.addWidget(self.val)
        lo.addWidget(btn)

    def _on_act(self, idx):
        self.val.setVisible(idx != 1)

    def _fill_attribute_dropdown(self, selected_attr: str):
        seen = set()
        self.attr.clear()
        self.attr.addItem("(Attribut wählen)", "")
        seen.add("")
        for name in self._attribute_options:
            key = (name or "").strip()
            if key and key not in seen:
                self.attr.addItem(key, key)
                seen.add(key)
        selected = (selected_attr or "").strip()
        if selected and selected not in seen:
            self.attr.addItem(selected, selected)
        idx = self.attr.findData(selected)
        if idx < 0:
            idx = 0
        self.attr.setCurrentIndex(idx)

    def get(self) -> Effect:
        return Effect(
            self._acts[self.act.currentIndex()],
            self.attr.currentData() or "",
            self.val.text()
        )


class StationDialog(QDialog):
    def __init__(self, item: StationItem, attribute_options=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Station bearbeiten")
        self.setMinimumWidth(530)
        self.setStyleSheet(DIALOG_STYLE)
        self._color = QColor(item.color)
        self._attribute_options = list(attribute_options or [])
        self._cond_rows: list[ConditionRow] = []
        self._eff_rows:  list[EffectRow]    = []
        self._build(item)

    @staticmethod
    def _copy_condition(cond: Condition) -> Condition:
        return Condition(cond.attribute, cond.subject, cond.operator, cond.value)

    def _build(self, item: StationItem):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── Name + Farbe ──
        row = QHBoxLayout()
        row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(item.station_name)
        row.addWidget(self.name_edit, 1)
        row.addWidget(QLabel("Farbe:"))
        self.col_btn = QPushButton()
        self.col_btn.setFixedSize(36, 26)
        self._refresh_color_btn()
        self.col_btn.clicked.connect(self._pick_color)
        row.addWidget(self.col_btn)
        root.addLayout(row)

        # ── Bedingungen ──
        cond_grp = QGroupBox("Eingangsbedingungen  (Produkt muss erfüllen, bevor es die Station durchläuft)")
        cg = QVBoxLayout(cond_grp)
        self._cond_scroll, self._cond_inner, self._cond_vbox = self._make_scroll()
        cg.addWidget(self._cond_scroll)
        for c in item.conditions:
            self._add_cond(self._copy_condition(c))
        btn_c = QPushButton("＋  Bedingung hinzufügen")
        btn_c.setObjectName("add_btn")
        btn_c.clicked.connect(lambda: self._add_cond(Condition()))
        cg.addWidget(btn_c)
        root.addWidget(cond_grp)

        # ── Effekte ──
        eff_grp = QGroupBox("Ausgangseffekte  (was passiert mit dem Produkt nach der Station)")
        eg = QVBoxLayout(eff_grp)
        self._eff_scroll, self._eff_inner, self._eff_vbox = self._make_scroll()
        eg.addWidget(self._eff_scroll)
        for e in item.effects:
            self._add_eff(Effect(e.action, e.attribute, e.value))
        btn_e = QPushButton("＋  Effekt hinzufügen")
        btn_e.setObjectName("add_btn")
        btn_e.clicked.connect(lambda: self._add_eff(Effect(Effect.ACT_ADD)))
        eg.addWidget(btn_e)
        root.addWidget(eff_grp)

        # ── Buttons ──
        btns = QDialogButtonBox()
        ok  = btns.addButton("Übernehmen", QDialogButtonBox.AcceptRole)
        ok.setObjectName("ok_btn")
        btns.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    @staticmethod
    def _make_scroll():
        scroll  = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(160)
        inner   = QWidget()
        inner.setStyleSheet("background: transparent;")
        vbox    = QVBoxLayout(inner)
        vbox.setAlignment(Qt.AlignTop)
        vbox.setSpacing(2)
        vbox.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(inner)
        return scroll, inner, vbox

    def _refresh_color_btn(self):
        self.col_btn.setStyleSheet(
            f"background:{self._color.name()}; border:1px solid #475569; border-radius:4px;"
        )

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self)
        if c.isValid():
            self._color = c
            self._refresh_color_btn()

    def _add_cond(self, cond: Condition):
        w = ConditionRow(cond, self._attribute_options)
        w.removed.connect(self._rm_cond)
        self._cond_rows.append(w)
        self._cond_vbox.addWidget(w)

    def _rm_cond(self, w: ConditionRow):
        self._cond_rows.remove(w)
        self._cond_vbox.removeWidget(w)
        w.deleteLater()

    def _add_eff(self, eff: Effect):
        w = EffectRow(eff, self._attribute_options)
        w.removed.connect(self._rm_eff)
        self._eff_rows.append(w)
        self._eff_vbox.addWidget(w)

    def _rm_eff(self, w: EffectRow):
        self._eff_rows.remove(w)
        self._eff_vbox.removeWidget(w)
        w.deleteLater()

    def result_data(self):
        return {
            "name":       self.name_edit.text().strip() or "Station",
            "color":      self._color,
            "conditions": [r.get() for r in self._cond_rows],
            "effects":    [r.get() for r in self._eff_rows],
        }


class AttributeDialog(QDialog):
    def __init__(self, item: AttributeItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Attribut bearbeiten")
        self.setMinimumWidth(400)
        self.setStyleSheet(DIALOG_STYLE)
        self._color = item.color

        lo = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(item.attribute_name)
        row.addWidget(self.name_edit, 1)
        lo.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Anzahl:"))
        self.count_edit = QLineEdit(str(item.attribute_count))
        self.count_edit.setFixedWidth(100)
        row2.addWidget(self.count_edit)
        row2.addWidget(QLabel("Farbe:"))
        self.col_btn = QPushButton()
        self.col_btn.setFixedSize(36, 26)
        self._refresh_color_btn()
        self.col_btn.clicked.connect(self._pick_color)
        row2.addWidget(self.col_btn)
        row2.addStretch(1)
        lo.addLayout(row2)

        btns = QDialogButtonBox()
        ok = btns.addButton("Übernehmen", QDialogButtonBox.AcceptRole)
        ok.setObjectName("ok_btn")
        btns.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lo.addWidget(btns)

    def _refresh_color_btn(self):
        self.col_btn.setStyleSheet(
            f"background:{QColor(self._color).name()}; border:1px solid #475569; border-radius:4px;"
        )

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._color), self)
        if c.isValid():
            self._color = c
            self._refresh_color_btn()

    def result_data(self):
        try:
            count = int(self.count_edit.text().strip() or "1")
        except ValueError:
            count = 1
        return {
            "name": self.name_edit.text().strip() or "Attribut",
            "count": max(0, count),
            "color": QColor(self._color),
        }


class ConnectionDialog(QDialog):
    def __init__(self, conn: ConnectionItem, attribute_options=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Verbindung bearbeiten")
        self.setMinimumWidth(520)
        self.setStyleSheet(DIALOG_STYLE)
        self._attribute_options = list(attribute_options or [])
        self._rows: list[ConditionRow] = []
        self._build(conn)

    @staticmethod
    def _copy_condition(cond: Condition) -> Condition:
        return Condition(cond.attribute, cond.subject, cond.operator, cond.value)

    def _build(self, conn: ConnectionItem):
        root = QVBoxLayout(self)
        src = conn.src_port.parentItem().station_name if isinstance(conn.src_port.parentItem(), StationItem) else getattr(conn.src_port.parentItem(), "attribute_name", "?")
        dst_parent = conn.dst_port.parentItem() if conn.dst_port else None
        dst = dst_parent.station_name if isinstance(dst_parent, StationItem) else getattr(dst_parent, "attribute_name", "?")

        info = QLabel(f"Von: {src}    Nach: {dst}")
        info.setWordWrap(True)
        root.addWidget(info)

        grp = QGroupBox("Bedingungen an dieser Verbindung")
        vg = QVBoxLayout(grp)
        self.scroll, self.inner, self.vbox = StationDialog._make_scroll()
        vg.addWidget(self.scroll)
        for cond in conn.conditions:
            self._add_cond(self._copy_condition(cond))
        add_btn = QPushButton("＋  Bedingung hinzufügen")
        add_btn.setObjectName("add_btn")
        add_btn.clicked.connect(lambda: self._add_cond(Condition()))
        vg.addWidget(add_btn)
        root.addWidget(grp)

        btns = QDialogButtonBox()
        ok = btns.addButton("Übernehmen", QDialogButtonBox.AcceptRole)
        ok.setObjectName("ok_btn")
        btns.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _add_cond(self, cond: Condition):
        row = ConditionRow(cond, self._attribute_options)
        row.removed.connect(self._rm_cond)
        self._rows.append(row)
        self.vbox.addWidget(row)

    def _rm_cond(self, row: ConditionRow):
        self._rows.remove(row)
        self.vbox.removeWidget(row)
        row.deleteLater()

    def result_data(self):
        return [row.get() for row in self._rows]


class TextDialog(QDialog):
    def __init__(self, item: TextBlockItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Textblock bearbeiten")
        self.setMinimumWidth(360)
        self.setStyleSheet(DIALOG_STYLE)
        lo = QVBoxLayout(self)
        lo.addWidget(QLabel("Text:"))
        self.editor = QPlainTextEdit(item._text)
        self.editor.setMinimumHeight(120)
        lo.addWidget(self.editor)
        btns = QDialogButtonBox()
        ok = btns.addButton("Übernehmen", QDialogButtonBox.AcceptRole)
        ok.setObjectName("ok_btn")
        btns.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lo.addWidget(btns)

    def get_text(self) -> str:
        return self.editor.toPlainText()


# ══════════════════════════════════════════════════════════════════════════════
#  SZENE
# ══════════════════════════════════════════════════════════════════════════════

class FlowScene(QGraphicsScene):
    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self._connections: list[ConnectionItem] = []
        self._wip_conn:    ConnectionItem | None = None
        self._wip_src:     Port | None           = None
        self.palette_widget = None

    def set_palette(self, palette_widget):
        self.palette_widget = palette_widget

    def _register_template(self, item):
        if self.palette_widget and hasattr(self.palette_widget, "register_item"):
            self.palette_widget.register_item(item)

    @staticmethod
    def _is_station(item) -> bool:
        return isinstance(item, StationItem)

    @staticmethod
    def _is_attribute(item) -> bool:
        return isinstance(item, AttributeItem)

    @staticmethod
    def _state_from_attribute(item: AttributeItem) -> dict:
        try:
            count = max(0, int(item.attribute_count))
        except (TypeError, ValueError):
            count = 0
        return {
            item.attribute_name: {
                "count": count,
            }
        }

    @staticmethod
    def _merge_states(base: dict, extra: dict) -> dict:
        merged = {key: (dict(value) if isinstance(value, dict) else {"value": value, "count": 1})
                  for key, value in base.items()}
        for key, value in extra.items():
            if not isinstance(value, dict):
                value = {"value": value, "count": 1}
            if key in merged:
                existing = merged[key]
                existing["count"] = max(0, int(existing.get("count", 0))) + max(0, int(value.get("count", 0)))
                if value.get("value") not in (None, ""):
                    existing["value"] = value.get("value")
            else:
                merged[key] = dict(value)
        return merged

    @staticmethod
    def _apply_effects(state: dict, effects: list[Effect]) -> dict:
        attrs = dict(state)
        for eff in effects:
            attrs = eff.apply(attrs)
        return attrs

    @staticmethod
    def _conditions_ok(conditions: list[Condition], state: dict) -> bool:
        return all(cond.check(state) for cond in conditions)

    def _station_items(self):
        return [i for i in self.items() if isinstance(i, StationItem)]

    def _attribute_items(self):
        return [i for i in self.items() if isinstance(i, AttributeItem)]

    def _all_attribute_names(self) -> list[str]:
        names = []
        seen = set()
        for item in self._attribute_items():
            name = (item.attribute_name or "").strip()
            if name and name not in seen:
                names.append(name)
                seen.add(name)
        return names

    def _connected_attribute_names(self, station: StationItem) -> list[str]:
        names = []
        seen = set()
        for conn in station.attr_port.connections:
            if conn.src_port and isinstance(conn.src_port.parentItem(), AttributeItem):
                name = (conn.src_port.parentItem().attribute_name or "").strip()
                if name and name not in seen:
                    names.append(name)
                    seen.add(name)
        return names

    def _rename_attribute_references(self, old_name: str, new_name: str) -> dict:
        old_key = (old_name or "").strip()
        new_key = (new_name or "").strip()
        if not old_key or not new_key or old_key == new_key:
            return {"conditions": 0, "effects": 0, "connections": 0}

        updates = {"conditions": 0, "effects": 0, "connections": 0}
        for station in self._station_items():
            changed = False
            for cond in station.conditions:
                if (cond.attribute or "").strip() == old_key:
                    cond.attribute = new_key
                    changed = True
                    updates["conditions"] += 1
            for eff in station.effects:
                if (eff.attribute or "").strip() == old_key:
                    eff.attribute = new_key
                    changed = True
                    updates["effects"] += 1
            if changed:
                station.update()
                self._refresh_template(station)

        for conn in self._connections:
            changed = False
            for cond in conn.conditions:
                if (cond.attribute or "").strip() == old_key:
                    cond.attribute = new_key
                    changed = True
                    updates["connections"] += 1
            if changed:
                conn.update()
        return updates

    def _connection_kind(self, conn: ConnectionItem):
        if not conn.src_port or not conn.dst_port:
            return None
        src = conn.src_port.parentItem()
        dst = conn.dst_port.parentItem()
        if isinstance(src, StationItem) and isinstance(dst, StationItem):
            if conn.src_port.port_type == Port.OUTPUT and conn.dst_port.port_type == Port.INPUT:
                return "flow"
        if isinstance(src, AttributeItem) and isinstance(dst, StationItem):
            if conn.src_port.port_type == Port.ATTR_OUTPUT and conn.dst_port.port_type == Port.ATTR_INPUT:
                return "attribute"
        return None

    def _can_connect(self, src_port: Port, dst_port: Port) -> bool:
        if src_port is None or dst_port is None:
            return False
        if not src_port.is_output() or not dst_port.is_input():
            return False
        if src_port == dst_port:
            return False
        src_item = src_port.parentItem()
        dst_item = dst_port.parentItem()
        if isinstance(src_item, StationItem) and isinstance(dst_item, StationItem):
            return src_port.port_type == Port.OUTPUT and dst_port.port_type == Port.INPUT
        if isinstance(src_item, AttributeItem) and isinstance(dst_item, StationItem):
            return src_port.port_type == Port.ATTR_OUTPUT and dst_port.port_type == Port.ATTR_INPUT
        return False

    def _resolve_drop_target(self, src_port: Port, item:ConnectionItem):
        if isinstance(item, Port):
            return item if self._can_connect(src_port, item) else None
        if isinstance(item, StationItem):
            if isinstance(src_port.parentItem(), AttributeItem):
                return item.attr_port if self._can_connect(src_port, item.attr_port) else None
            return item.in_port if self._can_connect(src_port, item.in_port) else None
        return None

    # ── Maus-Interaktion ─────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.scenePos(), QTransform())
            if isinstance(item, Port) and item.is_output():
                # Neue Verbindung beginnen
                self._wip_src  = item
                conn = ConnectionItem(item)
                conn.set_drag_end(event.scenePos())
                self.addItem(conn)
                self._wip_conn = conn
                if item.port_type == Port.ATTR_OUTPUT:
                    self.status_message.emit("Attributverbindung ziehen → auf den orangefarbenen Attribut-Eingang der Station loslassen.")
                else:
                    self.status_message.emit("Verbindung ziehen → auf den grünen Eingangs-Port der Ziel-Station loslassen.")
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._wip_conn:
            self._wip_conn.set_drag_end(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._wip_conn:
            self.removeItem(self._wip_conn)
            item = self.itemAt(event.scenePos(), QTransform())
            target_port = self._resolve_drop_target(self._wip_src, item)
            if target_port is not None:
                # Verbindung abschließen
                self._wip_conn.finalize(target_port)
                self._wip_src.connections.append(self._wip_conn)
                target_port.connections.append(self._wip_conn)
                self._connections.append(self._wip_conn)
                self.addItem(self._wip_conn)
                self.validate_all()
                self.status_message.emit("Verbindung erstellt. Doppelklick auf Station zum Bearbeiten.")
            else:
                self.status_message.emit("Verbindung abgebrochen.")
            self._wip_conn = None
            self._wip_src  = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            for item in self.selectedItems():
                if isinstance(item, ConnectionItem):
                    self._remove_conn(item)
                elif isinstance(item, StationItem):
                    for c in list(item.all_connections()):
                        self._remove_conn(c)
                    self.removeItem(item)
                elif isinstance(item, AttributeItem):
                    for c in list(item.all_connections()):
                        self._remove_conn(c)
                    self.removeItem(item)
                elif isinstance(item, TextBlockItem):
                    self.removeItem(item)
            self.validate_all()
        super().keyPressEvent(event)

    # ── Verbindungen ─────────────────────────────────────────────────────────

    def _remove_conn(self, conn: ConnectionItem):
        if conn.src_port and conn in conn.src_port.connections:
            conn.src_port.connections.remove(conn)
        if conn.dst_port and conn in conn.dst_port.connections:
            conn.dst_port.connections.remove(conn)
        if conn in self._connections:
            self._connections.remove(conn)
        self.removeItem(conn)

    def update_connections_for(self, item):
        for c in item.all_connections() if hasattr(item, "all_connections") else []:
            c.update_path()
        self.validate_all()

    # ── Editoren ─────────────────────────────────────────────────────────────

    def _refresh_template(self, item):
        self._register_template(item)

    def open_station_editor(self, item: StationItem):
        parent = self.views()[0] if self.views() else None
        dlg    = StationDialog(item, self._connected_attribute_names(item), parent)
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.result_data()
            item.station_name = d["name"]
            item.color        = d["color"]
            item.conditions   = d["conditions"]
            item.effects      = d["effects"]
            item._layout()
            item.update()
            self._refresh_template(item)
            self.validate_all()

    def open_attribute_editor(self, item: AttributeItem):
        parent = self.views()[0] if self.views() else None
        dlg    = AttributeDialog(item, parent)
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.result_data()
            old_name = item.attribute_name
            item.attribute_name  = d["name"]
            item.attribute_count = d["count"]
            item.color = d["color"]
            item._layout()
            item.update()
            renamed = self._rename_attribute_references(old_name, item.attribute_name)
            self._refresh_template(item)
            self.validate_all()
            total = renamed["conditions"] + renamed["effects"] + renamed["connections"]
            if total > 0:
                self.status_message.emit(
                    "Attribut umbenannt: "
                    f"{renamed['conditions']} Eingangsbedingung(en), "
                    f"{renamed['effects']} Ausgangseffekt(e), "
                    f"{renamed['connections']} Pfeilbedingung(en) aktualisiert."
                )

    def open_connection_editor(self, conn: ConnectionItem):
        parent = self.views()[0] if self.views() else None
        dlg    = ConnectionDialog(conn, self._all_attribute_names(), parent)
        if dlg.exec_() == QDialog.Accepted:
            conn.conditions = dlg.result_data()
            conn.update()
            self.validate_all()

    def open_text_editor(self, item: TextBlockItem):
        parent = self.views()[0] if self.views() else None
        dlg    = TextDialog(item, parent)
        if dlg.exec_() == QDialog.Accepted:
            item._text = dlg.get_text()
            item._recalc_height()
            item.update()

    # ── Validierung ──────────────────────────────────────────────────────────
    # Strategie: Nur Flow-Kanten bestimmen die Reihenfolge. Attribut-Kanten
    # liefern zusätzliche Zustände, die an der Station zusammengeführt werden.
    # Eine Verbindung wird nur dann grün, wenn alle Bedingungen an der
    # Verbindung, am Quellknoten und am Zielknoten für alle möglichen Zustände
    # erfüllt sind.

    def validate_all(self):
        stations = self._station_items()
        if not stations:
            return

        for conn in self._connections:
            conn._invalid_reasons = []

        flow_preds = {s: [] for s in stations}
        flow_succs = {s: [] for s in stations}
        attr_inputs = {s: [] for s in stations}

        for conn in self._connections:
            kind = self._connection_kind(conn)
            if kind == "flow":
                src = conn.src_port.parentItem()
                dst = conn.dst_port.parentItem()
                flow_preds[dst].append((conn, src))
                flow_succs[src].append((conn, dst))
            elif kind == "attribute":
                dst = conn.dst_port.parentItem()
                attr_inputs[dst].append(conn)

        in_deg = {s: len(flow_preds[s]) for s in stations}
        queue  = deque(s for s in stations if in_deg[s] == 0)
        order  = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for _, succ in flow_succs[node]:
                in_deg[succ] -= 1
                if in_deg[succ] == 0:
                    queue.append(succ)
        for s in stations:
            if s not in order:
                order.append(s)

        incoming: dict[StationItem, list[dict]] = {s: [] for s in stations}
        outputs: dict[StationItem, list[dict]] = {s: [] for s in stations}
        source_ok: dict[StationItem, bool] = {s: True for s in stations}
        attr_ok: dict[StationItem, bool] = {s: True for s in stations}

        for s in stations:
            if in_deg.get(s, 0) == 0:
                incoming[s] = [{}]

        for s in order:
            states_in = incoming[s] or [{}]
            attached_attrs = []
            attr_conn_ok = True
            for conn in attr_inputs[s]:
                src_item = conn.src_port.parentItem()
                if not isinstance(src_item, AttributeItem):
                    attr_conn_ok = False
                    conn.set_state(ConnectionItem.STATE_INVALID)
                    continue
                attr_state = self._state_from_attribute(src_item)
                conn_ok = self._conditions_ok(conn.conditions, attr_state)
                conn.set_state(ConnectionItem.STATE_VALID if conn_ok else ConnectionItem.STATE_INVALID)
                attr_conn_ok = attr_conn_ok and conn_ok
                if conn_ok:
                    attached_attrs.append(attr_state)

            combined_in = []
            for state in states_in:
                merged = dict(state)
                for attr_state in attached_attrs:
                    merged = self._merge_states(merged, attr_state)
                combined_in.append(merged)

            states_out = [self._apply_effects(state, s.effects) for state in combined_in]
            incoming_states = states_out or [{}]
            outputs[s] = incoming_states
            source_ok[s] = self._conditions_ok(s.conditions, {}) if not combined_in else all(
                self._conditions_ok(s.conditions, state) for state in combined_in
            )
            attr_ok[s] = attr_conn_ok

            for _, succ in flow_succs[s]:
                incoming[succ].extend(incoming_states)

        for conn in self._connections:
            if not conn.src_port or not conn.dst_port:
                conn._invalid_reasons = ["Die Verbindung hat keinen vollständigen Start-/Ziel-Port."]
                conn.set_state(ConnectionItem.STATE_UNKNOWN)
                continue
            kind = self._connection_kind(conn)
            src_item = conn.src_port.parentItem()
            dst_item = conn.dst_port.parentItem()

            if kind == "attribute" and isinstance(src_item, AttributeItem) and isinstance(dst_item, StationItem):
                source_state = self._state_from_attribute(src_item)
                ok = self._conditions_ok(conn.conditions, source_state)
                if not ok:
                    conn._invalid_reasons = [
                        "Mindestens eine Bedingung am Attribut-Pfeil ist für den aktuellen Attributzustand nicht erfüllt."
                    ]
                conn.set_state(ConnectionItem.STATE_VALID if ok else ConnectionItem.STATE_INVALID)
                continue

            if kind != "flow" or not isinstance(src_item, StationItem) or not isinstance(dst_item, StationItem):
                conn._invalid_reasons = ["Die Verbindungstypen passen nicht zusammen (nur Station→Station oder Attribut→Station)."]
                conn.set_state(ConnectionItem.STATE_UNKNOWN)
                continue

            states_after_src = outputs.get(src_item) or [{}]
            failed_conn_states = sum(1 for state in states_after_src if not self._conditions_ok(conn.conditions, state))
            failed_dst_states = sum(1 for state in states_after_src if not self._conditions_ok(dst_item.conditions, state))
            conn_ok = failed_conn_states == 0
            dst_ok = failed_dst_states == 0
            src_state_ok = source_ok.get(src_item, True)
            src_attr_ok = attr_ok.get(src_item, True)
            all_ok = conn_ok and dst_ok and src_state_ok and src_attr_ok
            if not all_ok:
                reasons = []
                if not src_state_ok:
                    reasons.append("Die Eingangsbedingungen der Quell-Station sind bereits vor diesem Pfeil nicht erfüllbar.")
                if not src_attr_ok:
                    reasons.append("Mindestens eine Attribut-Zuordnung an der Quell-Station ist ungültig.")
                if failed_conn_states > 0:
                    reasons.append(
                        f"{failed_conn_states} möglicher Zustand/Zustände verletzt/ verletzen die Bedingungen direkt auf diesem Pfeil."
                    )
                if failed_dst_states > 0:
                    reasons.append(
                        f"{failed_dst_states} möglicher Zustand/Zustände erfüllt/ erfüllen die Eingangsbedingungen der Ziel-Station nicht."
                    )
                conn._invalid_reasons = reasons
            conn.set_state(ConnectionItem.STATE_VALID if all_ok else ConnectionItem.STATE_INVALID)

        self.status_message.emit(
            f"{len(self._connections)} Verbindung(en) validiert  –  "
            f"{sum(1 for c in self._connections if c._state is True)} gültig  /  "
            f"{sum(1 for c in self._connections if c._state is False)} ungültig"
        )

    def clear_all(self):
        self._connections.clear()
        self.clear()


# ══════════════════════════════════════════════════════════════════════════════
#  CANVAS-VIEW
# ══════════════════════════════════════════════════════════════════════════════

class FlowView(QGraphicsView):
    def __init__(self, scene: FlowScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform |
            QPainter.TextAntialiasing
        )
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setAcceptDrops(True)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self._is_panning = False
        self._pan_start = QPoint()

    def drawBackground(self, painter: QPainter, rect):
        painter.fillRect(rect, QColor("#0F172A"))
        grid = 30
        left = int(rect.left()) - int(rect.left()) % grid
        top  = int(rect.top())  - int(rect.top())  % grid
        dots = []
        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                dots.append(QPointF(x, y))
                y += grid
            x += grid
        painter.setPen(QPen(QColor(51, 65, 85), 1))
        for d in dots:
            painter.drawPoint(d)

    def wheelEvent(self, event):
        f = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene_item = self.itemAt(event.pos())
            if scene_item is None:
                self._is_panning = True
                self._pan_start = event.pos()
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_panning and event.button() == Qt.LeftButton:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        mime = event.mimeData().text()
        pos  = self.mapToScene(event.pos())
        scene = self.scene()
        if mime.startswith("station:") or mime.startswith("attribute:"):
            kind, template_id = mime.split(":", 1)
            palette = getattr(scene, "palette_widget", None)
            item = palette.clone_template(kind, template_id) if palette else None
            if item is not None:
                scene.addItem(item)
                item.setPos(pos - QPointF(item.boundingRect().width() / 2, item.boundingRect().height() / 2))
                scene.clearSelection()
                item.setSelected(True)
                if hasattr(scene, "_register_template"):
                    scene._register_template(item)
                scene.validate_all()
        elif mime == "textblock":
            item = TextBlockItem("Notiz …")
            item.setPos(pos - QPointF(90, 35))
            scene.addItem(item)
        event.acceptProposedAction()


# ══════════════════════════════════════════════════════════════════════════════
#  PALETTE
# ══════════════════════════════════════════════════════════════════════════════

class TemplateListWidget(QListWidget):
    def __init__(self, palette_widget, kind: str, parent=None):
        super().__init__(parent)
        self.palette_widget = palette_widget
        self.kind = kind
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background: #273349;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #E2E8F0;
                padding: 6px 10px;
                margin: 2px 0;
                font-size: 12px;
            }
            QListWidget::item:hover     { background: #334155; }
            QListWidget::item:selected  { background: #1E40AF; border-color: #3B82F6; }
        """)
        self.setSpacing(2)

    def startDrag(self, actions):
        item = self.currentItem()
        if not item:
            return
        template_id = item.data(Qt.UserRole)
        mime_str = f"{self.kind}:{template_id}"

        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(mime_str)
        drag.setMimeData(mime)

        pix = item.icon().pixmap(130, 36)
        if pix.isNull():
            pix = QPixmap(130, 36)
            pix.fill(Qt.transparent)
        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(max(1, pix.width() // 2), max(1, pix.height() // 2)))
        drag.exec_(Qt.CopyAction)


class Palette(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240)
        self.setStyleSheet("background: #1E293B;")
        self.scene_widget = None
        self._station_items = {}
        self._attribute_items = {}
        self._station_templates = {}
        self._attribute_templates = {}

        lo = QVBoxLayout(self)
        lo.setContentsMargins(8, 12, 8, 12)
        lo.setSpacing(8)

        title = QLabel("BAUSTEINE")
        title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        title.setStyleSheet("color:#64748B; letter-spacing:2px;")
        lo.addWidget(title)

        station_hdr = QLabel("Stationen")
        station_hdr.setStyleSheet("color:#94A3B8; font-size:11px; font-weight:bold;")
        lo.addWidget(station_hdr)
        self.station_list = TemplateListWidget(self, "station")
        self.station_placeholder = QLabel("Noch keine Stationen angelegt")
        self.station_placeholder.setStyleSheet("color:#64748B; padding:4px 2px;")
        self.station_placeholder.setWordWrap(True)
        lo.addWidget(self.station_placeholder)
        lo.addWidget(self.station_list)

        attr_hdr = QLabel("Attribute")
        attr_hdr.setStyleSheet("color:#94A3B8; font-size:11px; font-weight:bold; margin-top:8px;")
        lo.addWidget(attr_hdr)
        self.attribute_list = TemplateListWidget(self, "attribute")
        self.attribute_placeholder = QLabel("Noch keine Attribute angelegt")
        self.attribute_placeholder.setStyleSheet("color:#64748B; padding:4px 2px;")
        self.attribute_placeholder.setWordWrap(True)
        lo.addWidget(self.attribute_placeholder)
        lo.addWidget(self.attribute_list)

        util_hdr = QLabel("Hilfen")
        util_hdr.setStyleSheet("color:#94A3B8; font-size:11px; font-weight:bold; margin-top:8px;")
        lo.addWidget(util_hdr)
        self.util_hdr = util_hdr
        self.textblock_btn = QPushButton("Textblock erstellen")
        self.textblock_btn.setStyleSheet("text-align:left; padding:6px 10px;")
        lo.addWidget(self.textblock_btn)

        # Hinweise
        self._default_help_text = (
            "Neue Stationen und Attribute werden unten links gesammelt und können erneut gezogen werden.\n\n"
            "Verbinden:\nStation-Ausgang (blau) → Station-Eingang (grün)\nAttribut-Ausgang (gelb) → Attribut-Eingang (orange)\n\n"
            "Doppelklick = bearbeiten\nEntf = löschen\n"
            "Scroll = zoom\n\n"
            "Linienfarbe:\n"
            "🟢 alle Pfade gültig\n"
            "🔴 mind. ein Pfad ungültig\n"
            "⚫ ungeprüft"
        )
        self.hints = QLabel(self._default_help_text)
        self.hints.setFont(QFont("Segoe UI", 8))
        self.hints.setStyleSheet("color:#475569; padding:6px 2px;")
        self.hints.setWordWrap(True)
        lo.addWidget(self.hints)
        lo.addStretch()

        self.station_list.itemDoubleClicked.connect(lambda item: self.add_template_to_scene("station", item.data(Qt.UserRole)))
        self.attribute_list.itemDoubleClicked.connect(lambda item: self.add_template_to_scene("attribute", item.data(Qt.UserRole)))

    def set_scene(self, scene):
        self.scene_widget = scene

    def _make_icon(self, color: QColor, label: str) -> QIcon:
        pix = QPixmap(130, 36)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, 130, 0)
        grad.setColorAt(0, color.lighter(120))
        grad.setColorAt(1, color)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(color.darker(150), 1))
        p.drawRoundedRect(1, 1, 128, 34, 8, 8)
        p.setPen(Qt.white)
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.drawText(QRect(0, 0, 130, 36), Qt.AlignCenter, label)
        p.end()
        return QIcon(pix)

    def _sync_placeholders(self):
        self.station_placeholder.setVisible(self.station_list.count() == 0)
        self.station_list.setVisible(self.station_list.count() > 0)
        self.attribute_placeholder.setVisible(self.attribute_list.count() == 0)
        self.attribute_list.setVisible(self.attribute_list.count() > 0)

    def show_default_help(self):
        self.util_hdr.setText("Hilfen")
        self.hints.setText(self._default_help_text)

    def show_invalid_connection_help(self, conn: ConnectionItem):
        self.util_hdr.setText("Pfeil-Analyse")
        reasons = list(getattr(conn, "_invalid_reasons", []) or [])
        if not reasons:
            reasons = ["Dieser Pfeil ist ungültig, es wurde jedoch keine Detailursache gefunden."]
        lines = ["Dieser Pfeil ist nicht korrekt, weil:", ""]
        for idx, reason in enumerate(reasons, start=1):
            lines.append(f"{idx}. {reason}")
        lines.append("")
        lines.append("Hinweis: Doppelklick auf den Pfeil öffnet den Bedingungseditor.")
        self.hints.setText("\n".join(lines))

    def reset_templates(self):
        self.station_list.clear()
        self.attribute_list.clear()
        self._station_items.clear()
        self._attribute_items.clear()
        self._station_templates.clear()
        self._attribute_templates.clear()
        self._sync_placeholders()
        self.show_default_help()

    def register_item(self, item):
        if isinstance(item, StationItem):
            template_id = item.template_id
            label = item.station_name
            self._station_templates[template_id] = item.clone()
            existing = self._station_items.get(template_id)
            if existing is None:
                li = QListWidgetItem(label)
                li.setData(Qt.UserRole, template_id)
                li.setIcon(self._make_icon(QColor(item.color), "Station"))
                self.station_list.addItem(li)
                self._station_items[template_id] = li
            else:
                existing.setText(label)
                existing.setIcon(self._make_icon(QColor(item.color), "Station"))
        elif isinstance(item, AttributeItem):
            template_id = item.template_id
            label = f"{item.attribute_name} · {item.attribute_count}"
            self._attribute_templates[template_id] = item.clone()
            existing = self._attribute_items.get(template_id)
            if existing is None:
                li = QListWidgetItem(label)
                li.setData(Qt.UserRole, template_id)
                li.setIcon(self._make_icon(QColor(item.color), "Attribut"))
                self.attribute_list.addItem(li)
                self._attribute_items[template_id] = li
            else:
                existing.setText(label)
                existing.setIcon(self._make_icon(QColor(item.color), "Attribut"))
        self._sync_placeholders()

    def clone_template(self, kind: str, template_id: str):
        if kind == "station":
            source_item = self._station_templates.get(template_id)
        elif kind == "attribute":
            source_item = self._attribute_templates.get(template_id)
        else:
            source_item = None
        return source_item.clone() if source_item else None

    def add_template_to_scene(self, kind: str, template_id: str):
        if self.scene_widget is None:
            return None
        item = self.clone_template(kind, template_id)
        if item is None:
            return None
        self.scene_widget.addItem(item)
        center = self.scene_widget.sceneRect().center()
        br = item.boundingRect()
        item.setPos(center - QPointF(br.width() / 2, br.height() / 2))
        self.scene_widget.clearSelection()
        item.setSelected(True)
        self.scene_widget._register_template(item)
        self.scene_widget.validate_all()
        return item


# ══════════════════════════════════════════════════════════════════════════════
#  HAUPTFENSTER
# ══════════════════════════════════════════════════════════════════════════════

APP_STYLE = """
QMainWindow, QWidget#central {
    background: #0F172A;
}
QMenuBar {
    background: #1E293B;
    color: #CBD5E1;
    font-size: 12px;
    border-bottom: 1px solid #334155;
}
QMenuBar::item:selected { background: #334155; }
QMenu {
    background: #1E293B;
    color: #E2E8F0;
    border: 1px solid #334155;
}
QMenu::item:selected { background: #2563EB; }
QToolBar {
    background: #1E293B;
    border-bottom: 1px solid #334155;
    spacing: 4px;
    padding: 2px 8px;
}
QToolBar QToolButton {
    background: #273349;
    border: 1px solid #334155;
    border-radius: 5px;
    color: #E2E8F0;
    padding: 4px 10px;
    font-size: 12px;
}
QToolBar QToolButton:hover  { background: #334155; }
QToolBar QToolButton:pressed { background: #1E40AF; }
QStatusBar {
    background: #1E293B;
    color: #64748B;
    font-size: 11px;
    border-top: 1px solid #334155;
}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ablaufplan-Editor")
        self.resize(1400, 840)
        self.setStyleSheet(APP_STYLE)

        self.scene = FlowScene()
        self.scene.status_message.connect(self._set_status)
        self.scene.selectionChanged.connect(self._on_scene_selection_changed)

        self._build_toolbar()
        self._build_central()
        self._build_menu()
        self._build_statusbar()

    # ── UI-Aufbau ─────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = self.addToolBar("Werkzeuge")
        tb.setMovable(False)

        for text, shortcut, slot in [
            ("Neu",             "Ctrl+N",        self._new),
            ("Laden (JSON)",    "Ctrl+O",        self._import_json),
            ("Speichern (JSON)","Ctrl+S",        self._export_json),
            ("Station",         "Ctrl+1",        self._new_station),
            ("Attribut",        "Ctrl+2",        self._new_attribute),
            ("Validieren",      "F5",            self.scene.validate_all),
            ("Als PDF exportieren", "Ctrl+P",     self._export_pdf),
            ("Alles einpassen", "Ctrl+Shift+F",  self._fit_all),
            ("Zoom 100%",       "Ctrl+0",        self._zoom_reset),
        ]:
            btn = QAction(text, self)
            btn.setShortcut(shortcut)
            btn.triggered.connect(slot)
            tb.addAction(btn)

        tb.addSeparator()
        lbl = QLabel("  Entf = ausgewählte Elemente löschen  │  "
                     "Doppelklick = bearbeiten  │  "
                     "Mausrad = Zoom")
        lbl.setStyleSheet("color:#475569; font-size:11px;")
        tb.addWidget(lbl)

    def _build_central(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self.palette = Palette()
        self.palette.set_scene(self.scene)
        h.addWidget(self.palette)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #334155;")
        h.addWidget(sep)

        self.view = FlowView(self.scene)
        h.addWidget(self.view, 1)

        self.scene.set_palette(self.palette)
        self.palette.textblock_btn.clicked.connect(self._new_textblock)

    def _build_menu(self):
        mb = self.menuBar()

        fm = mb.addMenu("Datei")
        a = QAction("Neu", self, shortcut="Ctrl+N")
        a.triggered.connect(self._new)
        fm.addAction(a)
        import_act = QAction("Laden (JSON)", self, shortcut="Ctrl+O")
        import_act.triggered.connect(self._import_json)
        fm.addAction(import_act)
        export_json_act = QAction("Speichern (JSON)", self, shortcut="Ctrl+S")
        export_json_act.triggered.connect(self._export_json)
        fm.addAction(export_json_act)
        export_act = QAction("Als PDF exportieren", self, shortcut="Ctrl+P")
        export_act.triggered.connect(self._export_pdf)
        fm.addAction(export_act)

        vm = mb.addMenu("Ansicht")
        for label, shortcut, slot in [
            ("Alles einpassen", "Ctrl+Shift+F", self._fit_all),
            ("Zoom 100%",       "Ctrl+0",       self._zoom_reset),
            ("Zoom +",          "Ctrl++",       lambda: self.view.scale(1.2, 1.2)),
            ("Zoom −",          "Ctrl+-",       lambda: self.view.scale(1/1.2, 1/1.2)),
        ]:
            act = QAction(label, self, shortcut=shortcut)
            act.triggered.connect(slot)
            vm.addAction(act)

        em = mb.addMenu("Bearbeiten")
        del_act = QAction("Ausgewählte löschen", self, shortcut="Del")
        del_act.triggered.connect(self._delete_selected)
        em.addAction(del_act)

        add_station = QAction("Station anlegen", self, shortcut="Ctrl+1")
        add_station.triggered.connect(self._new_station)
        em.addAction(add_station)

        add_attr = QAction("Attribut anlegen", self, shortcut="Ctrl+2")
        add_attr.triggered.connect(self._new_attribute)
        em.addAction(add_attr)

        val_act = QAction("Alle Verbindungen validieren", self, shortcut="F5")
        val_act.triggered.connect(self.scene.validate_all)
        em.addAction(val_act)

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage(
            "Bausteine per Drag & Drop auf die Fläche ziehen  –  "
            "Doppelklick auf Station zum Bearbeiten"
        )

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        self.statusBar().showMessage(msg)

    def _new(self):
        if QMessageBox.question(
            self, "Neues Diagramm",
            "Alle Elemente verwerfen und neu beginnen?",
            QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            self.scene.clear_all()
            self.palette.reset_templates()

    def _place_item_center(self, item):
        view_center = self.view.mapToScene(self.view.viewport().rect().center())
        br = item.boundingRect()
        item.setPos(view_center - QPointF(br.width() / 2, br.height() / 2))

    def _add_item_to_scene(self, item):
        self.scene.addItem(item)
        self._place_item_center(item)
        self.scene.clearSelection()
        item.setSelected(True)
        self.scene._register_template(item)
        self.scene.validate_all()

    def _new_station(self):
        item = StationItem("Neue Station")
        self._add_item_to_scene(item)

    def _new_attribute(self):
        item = AttributeItem("Neues Attribut", 1)
        self._add_item_to_scene(item)

    def _new_textblock(self):
        item = TextBlockItem("Notiz …")
        self.scene.addItem(item)
        self._place_item_center(item)
        self.scene.clearSelection()
        item.setSelected(True)

    def _fit_all(self):
        br = self.scene.itemsBoundingRect()
        if not br.isEmpty():
            self.view.fitInView(br.adjusted(-60, -60, 60, 60), Qt.KeepAspectRatio)

    def _zoom_reset(self):
        self.view.resetTransform()

    def _delete_selected(self):
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
        self.scene.keyPressEvent(ev)

    def _choose_file(self, save: bool, title: str, default_name: str, name_filter: str):
        start_dir = os.path.expanduser("~")
        start_path = os.path.join(start_dir, default_name) if default_name else start_dir
        options = QFileDialog.Options()

        if save:
            path, _ = QFileDialog.getSaveFileName(
                self,
                title,
                start_path,
                name_filter,
                options=options,
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                title,
                start_path,
                name_filter,
                options=options,
            )
        return path or ""

    def _on_scene_selection_changed(self):
        selected = self.scene.selectedItems()
        invalid_conn = next(
            (item for item in selected if isinstance(item, ConnectionItem) and item._state is ConnectionItem.STATE_INVALID),
            None,
        )
        if invalid_conn is not None:
            self.palette.show_invalid_connection_help(invalid_conn)
        else:
            self.palette.show_default_help()

    @staticmethod
    def _serialize_condition(cond: Condition) -> dict:
        return {
            "attribute": cond.attribute,
            "subject": cond.subject,
            "operator": cond.operator,
            "value": cond.value,
        }

    @staticmethod
    def _deserialize_condition(data: dict) -> Condition:
        return Condition(
            data.get("attribute", ""),
            data.get("subject") or Condition.SUBJECT_VALUE,
            data.get("operator") or Condition.OP_EXISTS,
            data.get("value", ""),
        )

    @staticmethod
    def _serialize_effect(eff: Effect) -> dict:
        return {
            "action": eff.action,
            "attribute": eff.attribute,
            "value": eff.value,
        }

    @staticmethod
    def _deserialize_effect(data: dict) -> Effect:
        return Effect(
            data.get("action") or Effect.ACT_ADD,
            data.get("attribute", ""),
            data.get("value", ""),
        )

    @staticmethod
    def _port_by_type(item, port_type: str):
        if isinstance(item, StationItem):
            if port_type == Port.INPUT:
                return item.in_port
            if port_type == Port.OUTPUT:
                return item.out_port
            if port_type == Port.ATTR_INPUT:
                return item.attr_port
        if isinstance(item, AttributeItem):
            if port_type == Port.ATTR_OUTPUT:
                return item.out_port
        return None

    def _export_json(self):
        path = self._choose_file(
            save=True,
            title="Konfiguration speichern",
            default_name="ablaufplan.json",
            name_filter="JSON-Dateien (*.json)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"

        def _safe_int(value, default=0):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        try:
            stations = [i for i in self.scene.items() if isinstance(i, StationItem)]
            attributes = [i for i in self.scene.items() if isinstance(i, AttributeItem)]
            textblocks = [i for i in self.scene.items() if isinstance(i, TextBlockItem)]

            data = {
                "version": 1,
                "stations": [
                    {
                        "node_id": s.node_id,
                        "template_id": s.template_id,
                        "name": s.station_name,
                        "color": QColor(s.color).name(),
                        "x": float(s.pos().x()),
                        "y": float(s.pos().y()),
                        "conditions": [self._serialize_condition(c) for c in s.conditions],
                        "effects": [self._serialize_effect(e) for e in s.effects],
                    }
                    for s in stations
                ],
                "attributes": [
                    {
                        "node_id": a.node_id,
                        "template_id": a.template_id,
                        "name": a.attribute_name,
                        "count": max(0, _safe_int(getattr(a, "attribute_count", 0), 0)),
                        "color": QColor(a.color).name(),
                        "x": float(a.pos().x()),
                        "y": float(a.pos().y()),
                    }
                    for a in attributes
                ],
                "textblocks": [
                    {
                        "node_id": t.node_id,
                        "text": t._text,
                        "x": float(t.pos().x()),
                        "y": float(t.pos().y()),
                    }
                    for t in textblocks
                ],
                "connections": [
                    {
                        "src_node_id": getattr(c.src_port.parentItem(), "node_id", None),
                        "src_port_type": c.src_port.port_type if c.src_port else None,
                        "dst_node_id": getattr(c.dst_port.parentItem(), "node_id", None),
                        "dst_port_type": c.dst_port.port_type if c.dst_port else None,
                        "conditions": [self._serialize_condition(cond) for cond in c.conditions],
                    }
                    for c in self.scene._connections
                    if c.src_port and c.dst_port
                ],
            }

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Speichern fehlgeschlagen", f"JSON konnte nicht gespeichert werden:\n{exc}")
            return
        self.statusBar().showMessage(f"JSON gespeichert: {path}")

    def _import_json(self):
        path = self._choose_file(
            save=False,
            title="Konfiguration laden",
            default_name="",
            name_filter="JSON-Dateien (*.json)",
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            QMessageBox.critical(self, "Laden fehlgeschlagen", f"JSON konnte nicht geladen werden:\n{exc}")
            return

        self.scene.clear_all()
        self.palette.reset_templates()

        node_map = {}

        for s in data.get("stations", []):
            item = StationItem(s.get("name", "Station"), QColor(s.get("color", "#2563EB")))
            item.node_id = s.get("node_id") or item.node_id
            item.template_id = s.get("template_id") or item.template_id
            item.conditions = [self._deserialize_condition(c) for c in s.get("conditions", [])]
            item.effects = [self._deserialize_effect(e) for e in s.get("effects", [])]
            item._layout()
            item.setPos(float(s.get("x", 0.0)), float(s.get("y", 0.0)))
            self.scene.addItem(item)
            self.scene._register_template(item)
            node_map[item.node_id] = item

        for a in data.get("attributes", []):
            item = AttributeItem(
                a.get("name", "Attribut"),
                int(a.get("count", 1) or 1),
                QColor(a.get("color", "#F59E0B")),
            )
            item.node_id = a.get("node_id") or item.node_id
            item.template_id = a.get("template_id") or item.template_id
            item._layout()
            item.setPos(float(a.get("x", 0.0)), float(a.get("y", 0.0)))
            self.scene.addItem(item)
            self.scene._register_template(item)
            node_map[item.node_id] = item

        for t in data.get("textblocks", []):
            item = TextBlockItem(t.get("text", ""))
            item.node_id = t.get("node_id") or item.node_id
            item._recalc_height()
            item.setPos(float(t.get("x", 0.0)), float(t.get("y", 0.0)))
            self.scene.addItem(item)
            node_map[item.node_id] = item

        for c in data.get("connections", []):
            src_item = node_map.get(c.get("src_node_id"))
            dst_item = node_map.get(c.get("dst_node_id"))
            if src_item is None or dst_item is None:
                continue
            src_port = self._port_by_type(src_item, c.get("src_port_type"))
            dst_port = self._port_by_type(dst_item, c.get("dst_port_type"))
            if src_port is None or dst_port is None:
                continue
            conn = ConnectionItem(src_port)
            conn.conditions = [self._deserialize_condition(cond) for cond in c.get("conditions", [])]
            conn.finalize(dst_port)
            src_port.connections.append(conn)
            dst_port.connections.append(conn)
            self.scene._connections.append(conn)
            self.scene.addItem(conn)

        self.scene.validate_all()
        self.statusBar().showMessage(f"JSON geladen: {path}")

    def _export_pdf(self):
        path = self._choose_file(
            save=True,
            title="Als PDF exportieren",
            default_name="ablaufplan.pdf",
            name_filter="PDF-Dateien (*.pdf)",
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageSize(QPrinter.A4)
        printer.setOrientation(QPrinter.Landscape)

        painter = QPainter(printer)
        if not painter.isActive():
            return

        try:
            self._paint_pdf_editor_page(painter, printer)
            printer.newPage()
            self._paint_pdf_flow_page(painter, printer)
            printer.newPage()
            self._paint_pdf_clean_flow_page(painter, printer)
        finally:
            painter.end()
        self.statusBar().showMessage(f"PDF exportiert: {path}")

    def _paint_pdf_editor_page(self, painter: QPainter, printer: QPrinter):
        page_rect = printer.pageRect(QPrinter.DevicePixel)
        painter.fillRect(page_rect, QColor("#0F172A"))
        painter.setPen(QColor("#E2E8F0"))
        painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
        painter.drawText(QRectF(40, 20, page_rect.width() - 80, 30), Qt.AlignLeft, "Editoransicht")
        source = self.scene.itemsBoundingRect().adjusted(-80, -80, 80, 80)
        if source.isEmpty():
            source = self.scene.sceneRect().adjusted(0, 0, -1, -1)
        target = QRectF(30, 60, page_rect.width() - 60, page_rect.height() - 90)
        self.scene.render(painter, target, source)

    def _paint_pdf_flow_page(self, painter: QPainter, printer: QPrinter):
        page_rect = printer.pageRect(QPrinter.DevicePixel)
        painter.fillRect(page_rect, QColor("#0F172A"))
        painter.setPen(QColor("#E2E8F0"))
        painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
        painter.drawText(QRectF(40, 20, page_rect.width() - 80, 30), Qt.AlignLeft, "Ablaufdiagramm")

        stations = [item for item in self.scene.items() if isinstance(item, StationItem)]
        if not stations:
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(QRectF(40, 70, page_rect.width() - 80, 40), Qt.AlignLeft, "Keine Stationen vorhanden.")
            return

        flow_edges = []
        preds = {station: [] for station in stations}
        succs = {station: [] for station in stations}
        for conn in self.scene._connections:
            if self.scene._connection_kind(conn) != "flow":
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
            painter.drawText(QRectF(rect.left() + 8, rect.top() + 8, rect.width() - 16, 18), Qt.AlignLeft, station.station_name)
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(QRectF(rect.left() + 8, rect.top() + 28, rect.width() - 16, 14), Qt.AlignLeft, f"Bedingungen: {len(station.conditions)}")
            painter.drawText(QRectF(rect.left() + 8, rect.top() + 42, rect.width() - 16, 14), Qt.AlignLeft, f"Effekte: {len(station.effects)}")

    def _paint_pdf_clean_flow_page(self, painter: QPainter, printer: QPrinter):
        page_rect = printer.pageRect(QPrinter.DevicePixel)
        painter.fillRect(page_rect, QColor("#FFFFFF"))
        painter.setPen(QColor("#111827"))
        painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
        painter.drawText(QRectF(36, 18, page_rect.width() - 72, 28), Qt.AlignLeft, "Aufgeraeumtes Ablaufdiagramm")

        stations = [item for item in self.scene.items() if isinstance(item, StationItem)]
        if not stations:
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(QRectF(36, 60, page_rect.width() - 72, 24), Qt.AlignLeft, "Keine Stationen vorhanden.")
            return

        succs = {station: [] for station in stations}
        preds = {station: [] for station in stations}
        for conn in self.scene._connections:
            if self.scene._connection_kind(conn) != "flow":
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
        # Kanten zuerst
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
                color = QColor("#16A34A") if conn._state is ConnectionItem.STATE_VALID else (
                    QColor("#DC2626") if conn._state is ConnectionItem.STATE_INVALID else QColor("#64748B")
                )
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

        # Knoten
        for node, rect in positions.items():
            color = QColor(node.color)
            painter.setPen(QPen(color.darker(160), 1.0))
            painter.setBrush(QBrush(color.lighter(145)))
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(QColor("#111827"))
            painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
            painter.drawText(QRectF(rect.left() + 8, rect.top() + 7, rect.width() - 16, 18), Qt.AlignLeft, node.station_name)
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(
                QRectF(rect.left() + 8, rect.top() + 26, rect.width() - 16, 16),
                Qt.AlignLeft,
                f"B:{len(node.conditions)}  E:{len(node.effects)}",
            )


# ══════════════════════════════════════════════════════════════════════════════
#  EINSTIEGSPUNKT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dunkle Fusion-Palette als Fallback
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor("#0F172A"))
    pal.setColor(QPalette.WindowText,      QColor("#E2E8F0"))
    pal.setColor(QPalette.Base,            QColor("#1E293B"))
    pal.setColor(QPalette.AlternateBase,   QColor("#273349"))
    pal.setColor(QPalette.Text,            QColor("#E2E8F0"))
    pal.setColor(QPalette.ButtonText,      QColor("#E2E8F0"))
    pal.setColor(QPalette.Button,          QColor("#334155"))
    pal.setColor(QPalette.Highlight,       QColor("#2563EB"))
    pal.setColor(QPalette.HighlightedText, Qt.white)
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
