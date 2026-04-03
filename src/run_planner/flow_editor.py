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
sys.setrecursionlimit(10**6)
import math
import uuid
import json
import os
import numpy as np
from dataclasses import dataclass, field
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_SCALE_FACTOR"] = "1"
from enum import Enum
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QAbstractItemView,
    QGraphicsScene, QGraphicsView, QGraphicsItem, QGraphicsEllipseItem,
    QGraphicsPathItem, QGraphicsRectItem, QFrame, QDialog, QDialogButtonBox,
    QLineEdit, QComboBox, QGroupBox, QScrollArea, QPlainTextEdit,
    QAction, QMessageBox, QColorDialog, QSizePolicy, QToolBar, QMenu,
    QSpacerItem, QStatusBar, QFileDialog, QDoubleSpinBox, QRadioButton,
    QButtonGroup
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

class PORT_TYPE(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    ATTR_INPUT = "attr_input"
    ATTR_OUTPUT = "attr_output"

class Port(QGraphicsEllipseItem):

    def __init__(self, port_type: PORT_TYPE, parent: QGraphicsItem):
        r = PORT_R
        super().__init__(-r, -r, r * 2, r * 2, parent)
        self.port_type:PORT_TYPE   = port_type
        self.connections:list[ConnectionItem] = []
        self._base_style()
        self.setAcceptHoverEvents(True)
        self.setZValue(5)
        self.setCursor(Qt.CrossCursor)

    def _base_style(self):
        match(self.port_type):
            case PORT_TYPE.INPUT:
                self.setBrush(QBrush(QColor("#22C55E")))
                self.setPen(QPen(QColor("#15803D"), 1.5))
            case PORT_TYPE.ATTR_INPUT:
                self.setBrush(QBrush(QColor("#F59E0B")))
                self.setPen(QPen(QColor("#B45309"), 1.5))
            case PORT_TYPE.ATTR_OUTPUT:
                self.setBrush(QBrush(QColor("#FBBF24")))
                self.setPen(QPen(QColor("#B45309"), 1.5))
            case PORT_TYPE.OUTPUT:
                self.setBrush(QBrush(QColor("#3B82F6")))
                self.setPen(QPen(QColor("#1D4ED8"), 1.5))

    def is_input(self) -> bool:
        return self.port_type == PORT_TYPE.INPUT or self.port_type == PORT_TYPE.ATTR_INPUT

    def is_output(self) -> bool:
        return self.port_type == PORT_TYPE.OUTPUT or self.port_type == PORT_TYPE.ATTR_OUTPUT

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor("#FCD34D")))
        self.setPen(QPen(QColor("#B45309"), 2))

    def hoverLeaveEvent(self, event):
        self._base_style()

    def scene_pos(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))

    def side(self) -> str:
        parent = self.parentItem()
        if parent is None:
            return "right"

        width = getattr(parent, "_w", parent.boundingRect().width())
        height = getattr(parent, "_h", parent.boundingRect().height())
        p = self.pos()

        distances = {
            "left": abs(p.x() - 0.0),
            "right": abs(p.x() - width),
            "top": abs(p.y() - 0.0),
            "bottom": abs(p.y() - height),
        }
        return min(distances, key=distances.get)

    def connection_tangent(self, as_source: bool) -> QPointF:
        side = self.side()
        outward = {
            "left": QPointF(-1.0, 0.0),
            "right": QPointF(1.0, 0.0),
            "top": QPointF(0.0, -1.0),
            "bottom": QPointF(0.0, 1.0),
        }.get(side, QPointF(1.0, 0.0))

        if as_source:
            return outward
        return QPointF(-outward.x(), -outward.y())

class ObjectItem(QGraphicsItem):
    def __init__(self, name: str = "Object", color: QColor = None, w: int = 200, h: int = 72):
        super().__init__()
        
        self.name:str = name
        self.color:QColor           = color or QColor("#505050")
        self.node_id         = uuid.uuid4().hex
        self.template_id     = uuid.uuid4().hex

        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        
        self.setZValue(0)
        
        self._w = w
        self._h = h

    @staticmethod
    def _port_pos_for_side(side: str, width: float, height: float) -> QPointF:
        center_x = width / 2
        center_y = height / 2
        if side == "left":
            return QPointF(0, center_y)
        if side == "right":
            return QPointF(width, center_y)
        if side == "top":
            return QPointF(center_x, 0)
        if side == "bottom":
            return QPointF(center_x, height)
        return QPointF(0, center_y)

    @staticmethod
    def _port_pos_for_side_index(side: str, width: float, height: float, index: int, total: int) -> QPointF:
        if total <= 1:
            return ObjectItem._port_pos_for_side(side, width, height)

        spacing = 16
        offset = (index - (total - 1) / 2) * spacing
        center_x = width / 2
        center_y = height / 2

        if side == "left":
            return QPointF(0, center_y + offset)
        if side == "right":
            return QPointF(width, center_y + offset)
        if side == "top":
            return QPointF(center_x + offset, 0)
        if side == "bottom":
            return QPointF(center_x + offset, height)
        return QPointF(0, center_y + offset)

    @staticmethod
    def _dominant_side(origin: QPointF, points: list[QPointF], default_side: str) -> str:
        if not points:
            return default_side
        dx = sum(point.x() - origin.x() for point in points) / len(points)
        dy = sum(point.y() - origin.y() for point in points) / len(points)
        if abs(dx) >= abs(dy):
            return "right" if dx >= 0 else "left"
        return "bottom" if dy >= 0 else "top"

    def _side_for_connections(self, connections, default_side: str, source_side: bool) -> str:
        points = []
        for conn in connections:
            if source_side:
                other = conn.src_port.parentItem() if conn.src_port else None
            else:
                other = conn.dst_port.parentItem() if conn.dst_port else None
            if other is None or other is self:
                continue
            points.append(other.sceneBoundingRect().center())
        return self._dominant_side(self.sceneBoundingRect().center(), points, default_side)

    def _layout_ports(self, port_specs: list[tuple[Port, str]]):
        grouped: dict[str, list[Port]] = {"left": [], "right": [], "top": [], "bottom": []}
        for port, side in port_specs:
            grouped.setdefault(side, []).append(port)

        for side, ports in grouped.items():
            for index, port in enumerate(ports):
                port.setPos(self._port_pos_for_side_index(side, self._w, self._h, index, len(ports)))
        
# ══════════════════════════════════════════════════════════════════════════════
#  STATIONSITEM
# ══════════════════════════════════════════════════════════════════════════════

class STATION_TYPE(Enum):
    START = 0
    NORMAL = 1
    END = 2
    
class StationItem(ObjectItem):
    ItemType = QGraphicsItem.UserType + 1

    def __init__(self, name: str = "Station", color: QColor = None, type:STATION_TYPE = STATION_TYPE.NORMAL):
        super().__init__(name, color or QColor("#2563EB"), STATION_W, STATION_H_MIN)
        self.rules: list[StationRule] = []

        self.in_port  = Port(PORT_TYPE.INPUT,  self)
        self.out_port = Port(PORT_TYPE.OUTPUT, self)
        self.attr_port = Port(PORT_TYPE.ATTR_INPUT, self)
        self.type:STATION_TYPE = type
        self.end_badge_text_color = QColor("#FFFFFF")
        self._layout()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _layout(self):
        # Calculate size based on rules content
        font = QFont("Consolas", 7)
        metrics = QFontMetrics(font)
        
        # Measure max width needed for rule text
        max_width = 0
        if self.rules:
            for rule in self.rules:
                rule_text = str(rule)
                text_width = metrics.horizontalAdvance(rule_text)
                max_width = max(max_width, text_width)
        
        # Set width with padding (8px left + 8px right)
        padding_h = 16
        if self.rules and max_width > 0:
            self._w = min(max(max_width + padding_h, STATION_W), 600)  # max 600px width
        else:
            self._w = STATION_W
        
        # Calculate height based on number of rules
        rows = len(self.rules) if self.rules else 1
        content_height = rows * LINE_H + 5  # 5px after HEADER_H
        self._h = HEADER_H + content_height
        self._h = max(self._h, STATION_H_MIN)  # ensure minimum height
        
        self._layout_ports([
            (self.attr_port, self._side_for_connections(self.attr_port.connections, "top", True)),
            (self.in_port, self._side_for_connections(self.in_port.connections, "left", True)),
            (self.out_port, self._side_for_connections(self.out_port.connections, "right", False)),
        ])
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
        
        
        # ── Type badge ──
        badge_w = 58
        badge_h = 16
        if self.type != STATION_TYPE.NORMAL:
            match self.type:
                case STATION_TYPE.START:
                    badge_text = "START"
                    badge_color = QColor("#16A34A")
                case STATION_TYPE.END:
                    badge_text = "ENDE"
                    badge_color = QColor("#DC2626")
                case _:
                    badge_text = "NORMAL"
                    badge_color = QColor("#0EA5E9")

            
            badge_rect = QRectF(self._w - badge_w - 8, (HEADER_H - badge_h) / 2, badge_w, badge_h)
            painter.setBrush(QBrush(badge_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, 7, 7)
            badge_text_color = self.end_badge_text_color if self.type == STATION_TYPE.END else QColor("#FFFFFF")
            painter.setPen(badge_text_color)
            painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
            painter.drawText(badge_rect, Qt.AlignCenter, badge_text)

        # ── Title ──
        painter.setPen(QColor(255, 255, 255, 240))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(
            QRectF(10, 2, self._w - badge_w - 24, HEADER_H - 4),
            Qt.AlignVCenter | Qt.AlignLeft,
            self.name
        )

        # ── Rules ──
        y = HEADER_H + 5
        painter.setFont(QFont("Consolas", 7))

        if self.rules:
            for rule in self.rules:
                painter.setPen(QColor("#FCA5A5"))
                painter.drawText(QRectF(8, y, self._w - 16, LINE_H),
                                 Qt.AlignVCenter | Qt.AlignLeft, str(rule))
                y += LINE_H
        else:
            painter.setPen(QColor(255, 255, 255, 60))
            painter.drawText(QRectF(8, y, self._w - 16, LINE_H),
                             Qt.AlignVCenter, "keine Regeln")
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

    @property
    def conditions(self):
        return [cond for rule in self.rules for cond in rule.conditions]

    @property
    def effects(self):
        return [eff for rule in self.rules for eff in rule.effects]

    def clone(self):
        item = StationItem(self.name, QColor(self.color), self.type)
        item.rules = [rule.clone() for rule in self.rules]
        item.end_badge_text_color = QColor(self.end_badge_text_color)
        item._layout()
        return item

    @staticmethod
    def _serialize_condition(cond: "Condition") -> dict:
        return {
            "attribute": getattr(cond.attribute, "node_id", None),
            "operator": cond.operator.value if isinstance(cond.operator, CONDITION_OP) else str(cond.operator),
            "value": cond.value,
        }

    @staticmethod
    def _deserialize_condition(data: dict, node_map: dict) -> "Condition":
        operator_raw = data.get("operator", CONDITION_OP.EXISTS.value)
        try:
            operator = CONDITION_OP(operator_raw)
        except Exception:
            operator = CONDITION_OP.EXISTS
        
        attr = node_map.get(data.get("attribute"))
        if attr is None:
            return None
        return Condition(
            attr,
            operator,
            data.get("value", 0.0),
        )

    @staticmethod
    def _serialize_effect(eff: "Effect") -> dict:
        return {
            "attribute": getattr(eff.attribute, "node_id", None),
            "action": eff.action.value if isinstance(eff.action, EFFECT_OP) else str(eff.action),
            "value": eff.value,
        }

    @staticmethod
    def _deserialize_effect(data: dict, node_map: dict) -> "Effect":
        action_raw = data.get("action", EFFECT_OP.SET.value)
        try:
            action = EFFECT_OP(action_raw)
        except Exception:
            action = EFFECT_OP.SET
        attr = node_map.get(data.get("attribute"))
        if attr is None:
            return None
        return Effect(
            attr,
            action,
            data.get("value", 0.0),
        )

    def to_json(self) -> dict:
        return {
            "node_id": self.node_id,
            "template_id": self.template_id,
            "name": self.name,
            "color": QColor(self.color).name(),
            "type": getattr(self.type, "value", self.type),
            "x": float(self.pos().x()),
            "y": float(self.pos().y()),
            "rules": [rule.to_json() for rule in self.rules],
        }

    @classmethod
    def from_json(cls, data: dict, node_map: dict) -> "StationItem":
        item = cls(data.get("name", "Station"), QColor(data.get("color", "#2563EB")), STATION_TYPE(data.get("type", STATION_TYPE.NORMAL.value)))
        item.node_id = data.get("node_id") or item.node_id
        item.template_id = data.get("template_id") or item.template_id
        if data.get("rules"):
            item.rules = [StationRule.from_json(rule, node_map) for rule in data.get("rules", [])]
        else:
            conditions = [c for c in (cls._deserialize_condition(c, node_map) for c in data.get("conditions", [])) if c is not None]
            effects = [e for e in (cls._deserialize_effect(e, node_map) for e in data.get("effects", [])) if e is not None]
            item.rules = [StationRule(conditions=conditions, effects=effects)] if conditions or effects else []
        item._layout()
        item.setPos(float(data.get("x", 0.0)), float(data.get("y", 0.0)))
        return item
    
    def __str__(self):
        return self.name

class AttributeItem(ObjectItem):
    ItemType = QGraphicsItem.UserType + 4

    def __init__(self, name: str = "Attribut", color: QColor = None):
        super().__init__(name, color or QColor("#FBBF24"), 180, 64)
        self.out_port = Port(PORT_TYPE.ATTR_OUTPUT, self)
        self._layout()
    
    @staticmethod
    def Placeholder():
        item = AttributeItem("⟨Attribut⟩")
        item.setOpacity(0.6)
        return item
    
    def _layout(self):
        self._layout_ports([
            (self.out_port, self._side_for_connections(self.out_port.connections, "right", False)),
        ])
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
        painter.drawText(QRectF(10, 8, self._w - 20, 18), Qt.AlignLeft | Qt.AlignVCenter, self.name)

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
        item = AttributeItem(self.name, QColor(self.color))
        item._layout()
        return item

    def to_json(self) -> dict:
        return {
            "node_id": self.node_id,
            "template_id": self.template_id,
            "name": self.name,
            "color": QColor(self.color).name(),
            "x": float(self.pos().x()),
            "y": float(self.pos().y()),
        }

    @classmethod
    def from_json(cls, data: dict) -> "AttributeItem":
        item = cls(data.get("name", "Attribut"), QColor(data.get("color", "#FBBF24")))
        item.node_id = data.get("node_id") or item.node_id
        item.template_id = data.get("template_id") or item.template_id
        item._layout()
        item.setPos(float(data.get("x", 0.0)), float(data.get("y", 0.0)))
        return item
    
    def __str__(self):
        return self.name

# ══════════════════════════════════════════════════════════════════════════════
#  VERBINDUNGS-ITEM
# ══════════════════════════════════════════════════════════════════════════════

class CONNECTION_STATE(int, Enum):
    VALID   = 0
    CONDITIONAL_VALID = 1
    CONDITIONAL_INVALID = 2
    INVALID = 3
    ATTRIBUTE = 4
    UNKNOWN = 5
    
class CONNECTION_COLOR(Enum):
    UNKNOWN = QColor("#94A3B8")
    VALID   = QColor("#22C55E")
    INVALID = QColor("#EF4444")
    CONDITIONAL_VALID = QColor("#0B0EF5")
    CONDITIONAL_INVALID = QColor("#9A1DEE")
    ATTRIBUTE = QColor("#FBBF24")

class ConnectionItem(QGraphicsPathItem):
    ItemType = QGraphicsItem.UserType + 3

    def __init__(self, src_port: Port, dst_port: Port = None):
        super().__init__()
        self.src_port:Port   = src_port
        self.dst_port:Port   = dst_port
        self.conditions:list[Condition] = []
        self._invalid_reasons = []
        self._state:CONNECTION_STATE = CONNECTION_STATE.UNKNOWN
        self._drag_end  = None
        self.setZValue(10)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self._rebuild()

    # ── Path ──────────────────────────────────────────────────────────────────

    def _parallel_offset(self) -> float:
        if self.src_port is None or self.dst_port is None:
            return 0.0

        scene = self.scene()
        if scene is None or not hasattr(scene, "_connections"):
            return 0.0

        siblings = [
            conn for conn in scene._connections
            if conn.src_port is self.src_port and conn.dst_port is self.dst_port
        ]
        if self not in siblings:
            siblings.append(self)

        if len(siblings) <= 1:
            return 0.0

        try:
            index = siblings.index(self)
        except ValueError:
            siblings = sorted(siblings, key=id)
            index = siblings.index(self)

        spread = 24.0
        return (index - (len(siblings) - 1) / 2.0) * spread

    def _rebuild(self):
        if self.src_port is None:
            return
        start = self.src_port.scene_pos()
        end   = self._drag_end if self._drag_end else (
            self.dst_port.scene_pos() if self.dst_port else start
        )

        dx = end.x() - start.x()
        dy = end.y() - start.y()
        cp = max(60.0, min(220.0, math.hypot(dx, dy) * 0.45))

        start_tangent = self.src_port.connection_tangent(as_source=True)
        if self.dst_port:
            end_tangent = self.dst_port.connection_tangent(as_source=False)
        else:
            end_tangent = QPointF(1.0 if dx >= 0 else -1.0, 0.0)

        c1 = QPointF(
            start.x() + start_tangent.x() * cp,
            start.y() + start_tangent.y() * cp,
        )
        c2 = QPointF(
            end.x() - end_tangent.x() * cp,
            end.y() - end_tangent.y() * cp,
        )

        lateral_offset = self._parallel_offset()
        if abs(lateral_offset) > 0.001:
            length = math.hypot(dx, dy)
            if length > 1e-6:
                nx = -dy / length
                ny = dx / length
            else:
                tangent = QPointF(start_tangent.x() + end_tangent.x(), start_tangent.y() + end_tangent.y())
                tangent_len = math.hypot(tangent.x(), tangent.y())
                if tangent_len <= 1e-6:
                    nx, ny = 0.0, -1.0
                else:
                    nx = -tangent.y() / tangent_len
                    ny = tangent.x() / tangent_len

            c1 = QPointF(c1.x() + nx * lateral_offset, c1.y() + ny * lateral_offset)
            c2 = QPointF(c2.x() + nx * lateral_offset, c2.y() + ny * lateral_offset)

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
        match(self._state):
            case CONNECTION_STATE.VALID:
                col = CONNECTION_COLOR.VALID
            case CONNECTION_STATE.INVALID:
                col = CONNECTION_COLOR.INVALID
            case CONNECTION_STATE.CONDITIONAL_VALID:
                col = CONNECTION_COLOR.CONDITIONAL_VALID
            case CONNECTION_STATE.CONDITIONAL_INVALID:
                col = CONNECTION_COLOR.CONDITIONAL_INVALID
            case CONNECTION_STATE.ATTRIBUTE:
                col = CONNECTION_COLOR.ATTRIBUTE
            case CONNECTION_STATE.UNKNOWN:
                col = CONNECTION_COLOR.UNKNOWN
            case _:
                col = CONNECTION_COLOR.UNKNOWN
        self.setPen(QPen(col.value, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

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

    @staticmethod
    def _point_segment_distance_sq(point: QPointF, a: QPointF, b: QPointF) -> float:
        ax = point.x() - a.x()
        ay = point.y() - a.y()
        bx = b.x() - a.x()
        by = b.y() - a.y()
        denom = bx * bx + by * by
        if denom <= 1e-9:
            return ax * ax + ay * ay
        t = max(0.0, min(1.0, (ax * bx + ay * by) / denom))
        px = a.x() + t * bx
        py = a.y() + t * by
        dx = point.x() - px
        dy = point.y() - py
        return dx * dx + dy * dy

    def contains(self, point: QPointF) -> bool:
        path = self.path()
        if path.isEmpty():
            return False

        # Precise line hit test: accept only points close to the bezier curve.
        tolerance = max(3.0, self.pen().widthF() + 0.75)
        tol_sq = tolerance * tolerance
        samples = 64
        prev = path.pointAtPercent(0.0)
        for idx in range(1, samples + 1):
            cur = path.pointAtPercent(idx / samples)
            if self._point_segment_distance_sq(point, prev, cur) <= tol_sq:
                return True
            prev = cur

        # Keep arrow head easily clickable.
        end = path.pointAtPercent(1.0)
        near = path.pointAtPercent(0.97)
        angle = math.atan2(-(end.y() - near.y()), end.x() - near.x())
        arr_sz = 10
        a1 = angle + math.radians(150)
        a2 = angle - math.radians(150)
        arrow_poly = QPolygonF([
            end,
            QPointF(end.x() + arr_sz * math.cos(a1), end.y() - arr_sz * math.sin(a1)),
            QPointF(end.x() + arr_sz * math.cos(a2), end.y() - arr_sz * math.sin(a2)),
        ])
        arrow_path = QPainterPath()
        arrow_path.addPolygon(arrow_poly)
        return arrow_path.contains(point)

    def mouseDoubleClickEvent(self, event):
        scene = self.scene()
        if scene and hasattr(scene, "open_connection_editor"):
            scene.open_connection_editor(self)

    @staticmethod
    def _resolve_port(item, port_type_raw: str):
        try:
            port_type = PORT_TYPE(port_type_raw)
        except Exception:
            return None

        if isinstance(item, StationItem):
            if port_type == PORT_TYPE.INPUT:
                return item.in_port
            if port_type == PORT_TYPE.OUTPUT:
                return item.out_port
            if port_type == PORT_TYPE.ATTR_INPUT:
                return item.attr_port
        if isinstance(item, AttributeItem) and port_type == PORT_TYPE.ATTR_OUTPUT:
            return item.out_port
        return None

    def to_json(self) -> dict:
        return {
            "src_node_id": getattr(self.src_port.parentItem(), "node_id", None) if self.src_port else None,
            "src_port_type": self.src_port.port_type.value if self.src_port else None,
            "dst_node_id": getattr(self.dst_port.parentItem(), "node_id", None) if self.dst_port else None,
            "dst_port_type": self.dst_port.port_type.value if self.dst_port else None,
            "conditions": [StationItem._serialize_condition(cond) for cond in self.conditions],
        }

    @classmethod
    def from_json(cls, data: dict, node_map: dict):
        src_item = node_map.get(data.get("src_node_id"))
        dst_item = node_map.get(data.get("dst_node_id"))
        if src_item is None or dst_item is None:
            return None

        src_port = cls._resolve_port(src_item, data.get("src_port_type"))
        dst_port = cls._resolve_port(dst_item, data.get("dst_port_type"))
        if src_port is None or dst_port is None:
            return None

        conn = cls(src_port)
        conn.conditions = [cond for cond in (StationItem._deserialize_condition(cond, node_map) for cond in data.get("conditions", [])) if cond is not None]
        conn.finalize(dst_port)
        src_port.connections.append(conn)
        dst_port.connections.append(conn)
        if hasattr(src_item, "_layout"):
            src_item._layout()
        if hasattr(dst_item, "_layout"):
            dst_item._layout()
        conn.update_path()
        return conn

# ══════════════════════════════════════════════════════════════════════════════
#  DATENMODELLE
# ══════════════════════════════════════════════════════════════════════════════
class CONDITION_OP(str, Enum):
    EXISTS     = "> 0"
    NOT_EXISTS = "= 0"
    EQUALS     = "="
    NOT_EQUALS = "≠"
    GREATER    = ">"
    GREATER_EQ = ">="
    LESS       = "<"
    LESS_EQ    = "<="
    
class Condition:
    """Vorbedingung an einem Produktattribut."""

    def __init__(self, attribute:AttributeItem = None, operator:CONDITION_OP=CONDITION_OP.EXISTS, value:float=0.0):
        self.attribute:AttributeItem = attribute
        self.operator:CONDITION_OP   = operator
        self.value:float     = value

    def _as_number(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def check(self, attrs: dict) -> bool:
        count = 0.0 if self.attribute not in attrs or attrs[self.attribute] is None else attrs[self.attribute]
        match(self.operator):
            case CONDITION_OP.EXISTS:
                return count > 0
            case CONDITION_OP.NOT_EXISTS:
                return count == 0
            case CONDITION_OP.EQUALS:
                return count == self._as_number(self.value)
            case CONDITION_OP.NOT_EQUALS:
                return count != self._as_number(self.value)
            case CONDITION_OP.GREATER:
                return count > self._as_number(self.value)
            case CONDITION_OP.GREATER_EQ:
                return count >= self._as_number(self.value)
            case CONDITION_OP.LESS:
                return count < self._as_number(self.value)
            case CONDITION_OP.LESS_EQ:
                return count <= self._as_number(self.value)

    def __str__(self):
        a = self.attribute.name if isinstance(self.attribute, AttributeItem) else str(self.attribute)
        prefix = f"⟨{a}⟩"
        match(self.operator):
            case CONDITION_OP.EXISTS:
                return f"{prefix} vorhanden"
            case CONDITION_OP.NOT_EXISTS:
                return f"{prefix} fehlt"
        return f"{prefix} {self.operator.value} {self.value}"

class EFFECT_OP(str, Enum):
    ADD     = "+"
    SUBTRACT= "-"
    MULTIPLY= "*"
    DIVIDE  = "/"
    SET     = "="
    MOD     = "%"

class Effect:
    """Ausgangseffekt auf ein Produktattribut."""

    def __init__(self, attribute:AttributeItem = None, action:EFFECT_OP=EFFECT_OP.SET, value:float=0.0):
        self.action    = action or EFFECT_OP.ADD
        self.attribute = attribute
        self.value     = value

    def apply(self, attrs: dict) -> dict:
        """Wendet den Effekt an und gibt ein neues dict zurück."""
        attrs = dict(attrs)
        match(self.action):
            case EFFECT_OP.ADD:
                if not self.attribute in attrs or not attrs[self.attribute]:
                    attrs[self.attribute] = self.value
                else:
                    attrs[self.attribute] = attrs[self.attribute] + self.value
            case EFFECT_OP.SUBTRACT:
                if not self.attribute in attrs or not attrs[self.attribute]:
                    attrs[self.attribute] = - self.value
                else:
                    attrs[self.attribute] = attrs[self.attribute] - self.value
            case EFFECT_OP.MULTIPLY:
                if not self.attribute in attrs or not attrs[self.attribute]:
                    attrs[self.attribute] = self.value
                else:
                    count = int(attrs.get(self.attribute, 1))
                    attrs[self.attribute] = attrs[self.attribute] * self.value
            case EFFECT_OP.DIVIDE:
                if not self.attribute in attrs or not attrs[self.attribute]:
                    attrs[self.attribute] = 1 / self.value
                else:
                    count = int(attrs.get(self.attribute, 1))
                    attrs[self.attribute] = attrs[self.attribute] / self.value
            case EFFECT_OP.MOD:
                if not self.attribute in attrs or not attrs[self.attribute]:
                    attrs[self.attribute] = 1 % self.value
                else:
                    count = int(attrs.get(self.attribute, 1))
                    attrs[self.attribute] = attrs[self.attribute] % self.value
            case EFFECT_OP.SET:
                attrs[self.attribute] = self.value
        return attrs

    def __str__(self):
        a = self.attribute.name if isinstance(self.attribute, AttributeItem) else str(self.attribute)
        return f"⟨{a}⟩ {self.action.value} '{self.value}'"


@dataclass
class StationRule:
    conditions: list[Condition] = field(default_factory=list)
    effects: list[Effect] = field(default_factory=list)

    def clone(self) -> "StationRule":
        return StationRule(
            conditions=[Condition(c.attribute, c.operator, c.value) for c in self.conditions],
            effects=[Effect(e.attribute, e.action, e.value) for e in self.effects],
        )

    def to_json(self) -> dict:
        return {
            "conditions": [StationItem._serialize_condition(cond) for cond in self.conditions],
            "effects": [StationItem._serialize_effect(eff) for eff in self.effects],
        }

    @classmethod
    def from_json(cls, data: dict, node_map: dict) -> "StationRule":
        conditions = [
            cond for cond in (
                StationItem._deserialize_condition(cond, node_map)
                for cond in data.get("conditions", [])
            )
            if cond is not None
        ]
        effects = [
            eff for eff in (
                StationItem._deserialize_effect(eff, node_map)
                for eff in data.get("effects", [])
            )
            if eff is not None
        ]
        return StationRule(conditions=conditions, effects=effects)

    def __str__(self) -> str:
        cond_text = " ∧ ".join(str(cond) for cond in self.conditions) if self.conditions else "immer"
        eff_text = ", ".join(str(eff) for eff in self.effects) if self.effects else "keine Effekte"
        return f"{cond_text} → {eff_text}"


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
QRadioButton {
    color: #E2E8F0;
    font-size: 12px;
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

def fill_attribute_dropdown(dropdown:QComboBox, selected_attr: AttributeItem, options:list[AttributeItem]={}):
        seen = set()
        dropdown.clear()
        seen.add("")
        for item in options:
            name = item.name if isinstance(item, AttributeItem) else str(item)
            key = item
            if key and key not in seen:
                dropdown.addItem(name, key)
                seen.add(key)
        selected = selected_attr or None
        if selected and selected not in seen:
            name = selected.name if isinstance(selected, AttributeItem) else str(item)
            dropdown.addItem(name, selected)
            seen.add(selected)
        idx = dropdown.findData(selected)
        if idx < 0:
            idx = 0
        dropdown.setCurrentIndex(idx)
        
class ConditionRow(QWidget):
    removed = pyqtSignal(object)
    changed = pyqtSignal()

    def __init__(self, cond: Condition, attribute_options:list[AttributeItem]={}, parent=None):
        super().__init__(parent)
        self._cond = cond
        self._attribute_options = attribute_options
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(4)

        self.attr = QComboBox()
        self.attr.setFixedWidth(160)
        fill_attribute_dropdown(self.attr, cond.attribute, self._attribute_options)
        self.attr.currentIndexChanged.connect(lambda *_: self.changed.emit())

        self.op = QComboBox()
        self.op.currentIndexChanged.connect(self._on_op)
        self.op.currentIndexChanged.connect(lambda *_: self.changed.emit())

        self.val = QDoubleSpinBox()
        self.val.setRange(-float('inf'), float('inf'))
        self.val.setValue(cond.value)
        self.val.setFixedWidth(70)
        self.val.valueChanged.connect(lambda *_: self.changed.emit())
        self._refresh_ops()
        op_idx = self.op.findData(cond.operator)
        self.op.setCurrentIndex(max(op_idx, 0))
        self._on_op(self.op.currentIndex())

        btn = QPushButton("✕")
        btn.setObjectName("del_btn")
        btn.setFixedSize(22, 22)
        btn.clicked.connect(lambda: self.removed.emit(self))

        lo.addWidget(self.attr)
        lo.addWidget(self.op)
        lo.addWidget(self.val)
        lo.addWidget(btn)

    def _ops_for_subject(self):
        return [
            CONDITION_OP.EXISTS,
            CONDITION_OP.NOT_EXISTS,
            CONDITION_OP.EQUALS,
            CONDITION_OP.NOT_EQUALS,
            CONDITION_OP.GREATER,
            CONDITION_OP.GREATER_EQ,
            CONDITION_OP.LESS,
            CONDITION_OP.LESS_EQ,
            ]

    def _refresh_ops(self, *args):
        current = self.op.currentData()
        self.op.blockSignals(True)
        self.op.clear()
        for op_key in self._ops_for_subject():
            self.op.addItem(op_key.value, op_key)
        idx = self.op.findData(current)
        self.op.setCurrentIndex(max(idx, 0))
        self.op.blockSignals(False)
        self._on_op(self.op.currentIndex())

    def _on_op(self, idx):
        op_key = self.op.itemData(idx)
        self.val.setVisible(op_key not in {CONDITION_OP.EXISTS, CONDITION_OP.NOT_EXISTS})

    def get(self) -> Condition:
        return Condition(
            self.attr.currentData() or None,
            self._ops_for_subject()[self.op.currentIndex()],
            self.val.value()
        )


class EffectRow(QWidget):
    removed = pyqtSignal(object)

    def __init__(self, eff: Effect, attribute_options:list[AttributeItem]={}, parent=None):
        super().__init__(parent)
        self._eff = eff
        self._attribute_options = attribute_options
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(4)

        self.act = QComboBox()
        self._acts = [EFFECT_OP.ADD, EFFECT_OP.SUBTRACT, EFFECT_OP.SET, EFFECT_OP.MULTIPLY, EFFECT_OP.DIVIDE, EFFECT_OP.MOD]
        for lbl in self._acts:
            self.act.addItem(lbl.value, lbl)
        idx = self._acts.index(eff.action) if eff.action in self._acts else 0
        self.act.setCurrentIndex(idx)

        self.attr = QComboBox()
        self.attr.setFixedWidth(160)
        fill_attribute_dropdown(self.attr, eff.attribute, self._attribute_options)

        self.val = QDoubleSpinBox()
        self.val.setRange(-float('inf'), float('inf'))
        self.val.setValue(eff.value)
        self.val.setFixedWidth(70)

        btn = QPushButton("✕")
        btn.setObjectName("del_btn")
        btn.setFixedSize(22, 22)
        btn.clicked.connect(lambda: self.removed.emit(self))

        lo.addWidget(self.act)
        lo.addWidget(self.attr)
        lo.addWidget(self.val)
        lo.addWidget(btn)

    def get(self) -> Effect:
        return Effect(
            self.attr.currentData() or None,
            self._acts[self.act.currentIndex()],
            self.val.value()
        )


class RuleRow(QWidget):
    removed = pyqtSignal(object)

    def __init__(self, rule: StationRule, attribute_options:list[AttributeItem]=[], parent=None, allow_attribute_rules: bool = True):
        super().__init__(parent)
        self._rule = rule
        self._attribute_options = attribute_options or []
        self._allow_attribute_rules = allow_attribute_rules

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 6)
        root.setSpacing(6)

        title_row = QHBoxLayout()
        title = QLabel("Regel")
        title.setStyleSheet("color:#94A3B8; font-weight:bold;")
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setObjectName("del_btn")
        self.remove_btn.setFixedSize(22, 22)
        self.remove_btn.clicked.connect(lambda: self.removed.emit(self))
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.remove_btn)
        root.addLayout(title_row)

        self._cond_rows: list[ConditionRow] = []
        self._eff_rows: list[EffectRow] = []

        cond_grp = QGroupBox("Bedingungen")
        cg = QVBoxLayout(cond_grp)
        self._cond_scroll, self._cond_inner, self._cond_vbox = self._make_scroll()
        cg.addWidget(self._cond_scroll)
        for cond in rule.conditions:
            self._add_cond(self._copy_condition(cond))
        self._cond_add_btn = QPushButton("＋ Bedingung hinzufügen")
        self._cond_add_btn.setObjectName("add_btn")
        self._cond_add_btn.clicked.connect(lambda: self._add_cond(Condition()))
        if not self._allow_attribute_rules:
            self._cond_add_btn.setEnabled(False)
            self._cond_add_btn.setToolTip("Bedingungen können erst hinzugefügt werden, wenn eine Verbindung zum Attribut-Port besteht.")
        cg.addWidget(self._cond_add_btn)
        root.addWidget(cond_grp)

        eff_grp = QGroupBox("Effekte")
        eg = QVBoxLayout(eff_grp)
        self._eff_scroll, self._eff_inner, self._eff_vbox = self._make_scroll()
        eg.addWidget(self._eff_scroll)
        for eff in rule.effects:
            self._add_eff(Effect(eff.attribute, eff.action, eff.value))
        self._eff_add_btn = QPushButton("＋ Effekt hinzufügen")
        self._eff_add_btn.setObjectName("add_btn")
        self._eff_add_btn.clicked.connect(lambda: self._add_eff(Effect()))
        if not self._allow_attribute_rules:
            self._eff_add_btn.setEnabled(False)
            self._eff_add_btn.setToolTip("Effekte können erst hinzugefügt werden, wenn eine Verbindung zum Attribut-Port besteht.")
        eg.addWidget(self._eff_add_btn)
        root.addWidget(eff_grp)

    @staticmethod
    def _make_scroll():
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(inner)
        vbox.setAlignment(Qt.AlignTop)
        vbox.setSpacing(2)
        vbox.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(inner)
        return scroll, inner, vbox

    @staticmethod
    def _copy_condition(cond: Condition) -> Condition:
        return Condition(cond.attribute, cond.operator, cond.value)

    def _add_cond(self, cond: Condition):
        row = ConditionRow(cond, self._attribute_options)
        row.removed.connect(self._rm_cond)
        self._cond_rows.append(row)
        self._cond_vbox.addWidget(row)

    def _rm_cond(self, row: ConditionRow):
        self._cond_rows.remove(row)
        self._cond_vbox.removeWidget(row)
        row.deleteLater()

    def _add_eff(self, eff: Effect):
        row = EffectRow(eff, self._attribute_options)
        row.removed.connect(self._rm_eff)
        self._eff_rows.append(row)
        self._eff_vbox.addWidget(row)

    def _rm_eff(self, row: EffectRow):
        self._eff_rows.remove(row)
        self._eff_vbox.removeWidget(row)
        row.deleteLater()

    def result_data(self) -> StationRule:
        return StationRule(
            conditions=[row.get() for row in self._cond_rows],
            effects=[row.get() for row in self._eff_rows],
        )


class SettingsDialog(QDialog):
    def __init__(self, item: QGraphicsItem, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(530)
        self.setStyleSheet(DIALOG_STYLE)

    def _fit_to_content(self, width_margin: int = 24, height_margin: int = 24):
        self.adjustSize()
        hint = self.sizeHint()
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            max_w = int(available.width() * 0.9)
            max_h = int(available.height() * 0.9)
        else:
            max_w = hint.width() + width_margin
            max_h = hint.height() + height_margin

        target_w = min(max_w, hint.width() + width_margin)
        target_h = min(max_h, hint.height() + height_margin)
        self.resize(target_w, target_h)
        
class StationDialog(SettingsDialog):
    def __init__(self, item: StationItem, attribute_options:list[AttributeItem]=[], parent=None):
        super().__init__(item, parent)
        self.setWindowTitle(f"{item.name} bearbeiten")
        self._color = QColor(item.color)
        self._attribute_options = attribute_options or []
        self._rule_rows: list[RuleRow] = []
        self._build(item)
        self._fit_to_content(width_margin=36, height_margin=28)

    def _build(self, item: StationItem):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── Name + Farbe ──
        row = QHBoxLayout()
        row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(item.name)
        row.addWidget(self.name_edit, 1)
        row.addWidget(QLabel("Farbe:"))
        self.col_btn = QPushButton()
        self.col_btn.setFixedSize(36, 26)
        self._refresh_color_btn()
        self.col_btn.clicked.connect(self._pick_color)
        row.addWidget(self.col_btn)
        root.addLayout(row)

        # ── Typ ──
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Typ:"))
        self.type_group = QButtonGroup(self)
        self.type_group.setExclusive(True)
        self.type_buttons = {}
        for station_type, label in [
            (STATION_TYPE.START, "Start"),
            (STATION_TYPE.NORMAL, "Normal"),
            (STATION_TYPE.END, "Ende"),
        ]:
            btn = QRadioButton(label)
            btn.setChecked(item.type == station_type)
            self.type_group.addButton(btn, station_type.value)
            self.type_buttons[station_type] = btn
            type_row.addWidget(btn)
        type_row.addStretch(1)
        root.addLayout(type_row)

        # ── Regeln ──
        rule_grp = QGroupBox("Regeln  (Bedingungen und Effekte gehören zusammen)")
        rg = QVBoxLayout(rule_grp)
        self._rule_scroll, self._rule_inner, self._rule_vbox = self._make_scroll()
        rg.addWidget(self._rule_scroll)
        can_add_rule_parts = len(item.attr_port.connections) > 0
        if item.rules:
            for rule in item.rules:
                self._add_rule(rule.clone(), can_add_rule_parts)
        else:
            self._add_rule(StationRule(), can_add_rule_parts)
        btn_r = QPushButton("＋  Regel hinzufügen")
        btn_r.setObjectName("add_btn")
        btn_r.clicked.connect(lambda: self._add_rule(StationRule(), can_add_rule_parts))
        rg.addWidget(btn_r)
        root.addWidget(rule_grp)

        # ── Buttons ──
        btns = QDialogButtonBox()
        ok = btns.addButton("Übernehmen", QDialogButtonBox.AcceptRole)
        ok.setObjectName("ok_btn")
        btns.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    @staticmethod
    def _make_scroll():
        return RuleRow._make_scroll()

    def _refresh_color_btn(self):
        self.col_btn.setStyleSheet(
            f"background:{self._color.name()}; border:1px solid #475569; border-radius:4px;"
        )

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self)
        if c.isValid():
            self._color = c
            self._refresh_color_btn()

    def _add_rule(self, rule: StationRule, allow_attribute_rules: bool = True):
        row = RuleRow(rule, self._attribute_options, allow_attribute_rules=allow_attribute_rules)
        row.removed.connect(self._rm_rule)
        self._rule_rows.append(row)
        self._rule_vbox.addWidget(row)

    def _rm_rule(self, row: RuleRow):
        self._rule_rows.remove(row)
        self._rule_vbox.removeWidget(row)
        row.deleteLater()
        if not self._rule_rows:
            self._add_rule(StationRule())

    def result_data(self):
        selected_type = STATION_TYPE.NORMAL
        for station_type, btn in self.type_buttons.items():
            if btn.isChecked():
                selected_type = station_type
                break
        return {
            "name":       self.name_edit.text().strip() or "Station",
            "color":      self._color,
            "type":       selected_type,
            "rules":      [r.result_data() for r in self._rule_rows],
        }


class AttributeDialog(SettingsDialog):
    def __init__(self, item: AttributeItem, parent=None):
        super().__init__(item, parent)
        self.setWindowTitle(f"{item.name} bearbeiten")
        self._color = QColor(item.color)
        self._build(item)
        self._fit_to_content()
    
    def _build(self, item:AttributeItem):
        lo = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(item.name)
        row.addWidget(self.name_edit, 1)
        row.addWidget(QLabel("Farbe:"))
        self.col_btn = QPushButton()
        self.col_btn.setFixedSize(36, 26)
        self._refresh_color_btn()
        self.col_btn.clicked.connect(self._pick_color)
        row.addWidget(self.col_btn)
        lo.addLayout(row)

        btns = QDialogButtonBox()
        ok = btns.addButton("Übernehmen", QDialogButtonBox.AcceptRole)
        ok.setObjectName("ok_btn")
        btns.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lo.addWidget(btns)

    def _refresh_color_btn(self):
        self.col_btn.setStyleSheet(
            f"background:{self._color.name()}; border:1px solid #475569; border-radius:4px;"
        )

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self)
        if c.isValid():
            self._color = c
            self._refresh_color_btn()

    def result_data(self):
        return {
            "name": self.name_edit.text().strip() or "Attribut",
            "color": self._color,
        }


class ConnectionDialog(SettingsDialog):
    conditions_changed = pyqtSignal()

    def __init__(self, item: ConnectionItem, attribute_options:list[AttributeItem]=[], parent=None):
        super().__init__(item, parent)
        self.setWindowTitle(f"Verbindung bearbeiten")
        self._attribute_options = attribute_options or []
        self._cond_rows: list[ConditionRow] = []
        self._build(item)
        self._fit_to_content()

    @staticmethod
    def _copy_condition(cond: Condition) -> Condition:
        return Condition(cond.attribute, cond.operator, cond.value)

    def _build(self, conn: ConnectionItem):
        root = QVBoxLayout(self)
        src = conn.src_port.parentItem().name if isinstance(conn.src_port.parentItem(), StationItem) else conn.src_port.parentItem().name
        dst_parent = conn.dst_port.parentItem() if conn.dst_port else None
        dst = dst_parent.name if isinstance(dst_parent, StationItem) else dst_parent.name

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
        if isinstance(conn.src_port.parentItem(), AttributeItem):
            add_btn.setEnabled(False)
            add_btn.setToolTip("Bedingungen können nicht hinzugefügt werden, wenn die Verbindung direkt von einem Attribut ausgeht.")
        else:
            add_btn.setEnabled(True)
            add_btn.setToolTip("")
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
        row.changed.connect(self.conditions_changed.emit)
        self._cond_rows.append(row)
        self.vbox.addWidget(row)
        self.conditions_changed.emit()

    def _rm_cond(self, row: ConditionRow):
        self._cond_rows.remove(row)
        self.vbox.removeWidget(row)
        row.deleteLater()
        self.conditions_changed.emit()

    def result_data(self):
        return [row.get() for row in self._cond_rows]


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
        self.adjustSize()

    def get_text(self) -> str:
        return self.editor.toPlainText()


# ══════════════════════════════════════════════════════════════════════════════
#  SZENE
# ══════════════════════════════════════════════════════════════════════════════

class CONNECTION_KIND(Enum):
    FLOW = True,
    ATTRIBUTE = False
    
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
    def _apply_effects(state: dict, effects: list[Effect]) -> dict:
        attrs = dict(state)
        for effect in effects:
            attrs = effect.apply(attrs)
        return attrs

    @staticmethod
    def _conditions_ok(conditions: list[Condition], state: dict) -> list[Condition]:
        return [cond for cond in conditions if not cond.check(state)]

    def _station_items(self) -> list[StationItem]:
        return [i for i in self.items() if isinstance(i, StationItem)]

    def _attribute_items(self) -> list[AttributeItem]:
        return [i for i in self.items() if isinstance(i, AttributeItem)]

    @staticmethod
    def _attribute_name_key(name: str) -> str:
        return (name or "").strip().lower()

    def attribute_name_exists(self, name: str, exclude_item: AttributeItem = None) -> bool:
        key = self._attribute_name_key(name)
        if not key:
            return False
        for item in self._attribute_items():
            if item is exclude_item:
                continue
            if self._attribute_name_key(item.name) == key:
                return True
        return False

    def make_unique_attribute_name(self, base_name: str, exclude_item: AttributeItem = None) -> str:
        base = (base_name or "Attribut").strip() or "Attribut"
        if not self.attribute_name_exists(base, exclude_item):
            return base

        idx = 2
        while True:
            candidate = f"{base} ({idx})"
            if not self.attribute_name_exists(candidate, exclude_item):
                return candidate
            idx += 1

    def _connected_attributes(self, station: StationItem) -> list[AttributeItem]:
        attrs = []
        seen = set()
        for conn in station.attr_port.connections:
            if conn.src_port and isinstance(conn.src_port.parentItem(), AttributeItem):
                if conn.src_port.parentItem() and conn.src_port.parentItem() not in seen:
                    attrs.append(conn.src_port.parentItem())
                    seen.add(conn.src_port.parentItem())
        return attrs

    def _connection_kind(self, conn: ConnectionItem) -> CONNECTION_KIND:
        if not conn.src_port or not conn.dst_port:
            return None
        src = conn.src_port.parentItem()
        dst = conn.dst_port.parentItem()
        if isinstance(src, StationItem) and isinstance(dst, StationItem):
            if conn.src_port.port_type == PORT_TYPE.OUTPUT and conn.dst_port.port_type == PORT_TYPE.INPUT:
                return CONNECTION_KIND.FLOW
        if isinstance(src, AttributeItem) and isinstance(dst, StationItem):
            if conn.src_port.port_type == PORT_TYPE.ATTR_OUTPUT and conn.dst_port.port_type == PORT_TYPE.ATTR_INPUT:
                return CONNECTION_KIND.ATTRIBUTE
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
            return src_port.port_type == PORT_TYPE.OUTPUT and dst_port.port_type == PORT_TYPE.INPUT
        if isinstance(src_item, AttributeItem) and isinstance(dst_item, StationItem):
            return src_port.port_type == PORT_TYPE.ATTR_OUTPUT and dst_port.port_type == PORT_TYPE.ATTR_INPUT
        return False

    def _resolve_drop_target(self, src_port: Port, item:ConnectionItem):
        if isinstance(item, Port):
            return item if self._can_connect(src_port, item) else None
        if isinstance(item, StationItem):
            if isinstance(src_port.parentItem(), AttributeItem):
                return item.attr_port if self._can_connect(src_port, item.attr_port) else None
            return item.in_port if self._can_connect(src_port, item.in_port) else None
        return None

    def _delete_scene_item(self, item):
        if isinstance(item, ConnectionItem):
            self._remove_conn(item)
        elif isinstance(item, StationItem):
            for c in list(item.all_connections()):
                self._remove_conn(c)
            self.removeItem(item)
        elif isinstance(item, AttributeItem):
            for station in self._station_items():
                self._remove_related_conditions_for_attribute(item, station)
            for c in list(item.all_connections()):
                self._remove_conn(c)
            self.removeItem(item)
        elif isinstance(item, TextBlockItem):
            self.removeItem(item)
        self.validate_all()

    def contextMenuEvent(self, event):
        item = self.itemAt(event.scenePos(), QTransform())
        if item is None:
            super().contextMenuEvent(event)
            return

        if isinstance(item, Port):
            item = item.parentItem()

        if not isinstance(item, (ConnectionItem, StationItem, AttributeItem, TextBlockItem)):
            super().contextMenuEvent(event)
            return

        menu = QMenu()
        delete_action = menu.addAction("Löschen")
        chosen = menu.exec_(event.screenPos())
        if chosen == delete_action:
            self._delete_scene_item(item)
            event.accept()
            return
        super().contextMenuEvent(event)

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
                if item.port_type == PORT_TYPE.ATTR_OUTPUT:
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
                src_item = self._wip_src.parentItem()
                dst_item = target_port.parentItem()
                if hasattr(src_item, "_layout"):
                    self.update_connections_for(src_item)
                if hasattr(dst_item, "_layout") and dst_item is not src_item:
                    self.update_connections_for(dst_item)
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
        src_item = conn.src_port.parentItem() if conn.src_port else None
        dst_item = conn.dst_port.parentItem() if conn.dst_port else None
        kind = self._connection_kind(conn)

        if kind == CONNECTION_KIND.ATTRIBUTE and isinstance(src_item, AttributeItem) and isinstance(dst_item, StationItem):
            still_connected = any(
                other is not conn
                and other.src_port is not None
                and other.dst_port is not None
                and other.src_port.parentItem() is src_item
                and other.dst_port.parentItem() is dst_item
                for other in dst_item.attr_port.connections
            )
            if not still_connected:
                self._remove_related_conditions_for_attribute(src_item, dst_item)

        if conn.src_port and conn in conn.src_port.connections:
            conn.src_port.connections.remove(conn)
        if conn.dst_port and conn in conn.dst_port.connections:
            conn.dst_port.connections.remove(conn)
        if conn in self._connections:
            self._connections.remove(conn)
        self.removeItem(conn)
        if hasattr(src_item, "_layout"):
            self.update_connections_for(src_item)
        if hasattr(dst_item, "_layout") and dst_item is not src_item:
            self.update_connections_for(dst_item)
        self.validate_all()

    def _remove_related_conditions_for_attribute(self, attribute: AttributeItem, station: StationItem):
        if attribute is None or station is None:
            return 0

        removed = 0

        for rule in station.rules:
            old_station_count = len(rule.conditions)
            rule.conditions = [cond for cond in rule.conditions if cond.attribute is not attribute]
            removed += old_station_count - len(rule.conditions)

            old_effect_count = len(rule.effects)
            rule.effects = [eff for eff in rule.effects if eff.attribute is not attribute]
            removed += old_effect_count - len(rule.effects)

        for flow_conn in station.flow_connections():
            old_conn_count = len(flow_conn.conditions)
            flow_conn.conditions = [cond for cond in flow_conn.conditions if cond.attribute is not attribute]
            removed += old_conn_count - len(flow_conn.conditions)

        return removed

    def remove_arrow_conditions_for_attribute_name(self, attribute_name: str) -> int:
        name_key = self._attribute_name_key(attribute_name)
        if not name_key:
            return 0

        removed = 0

        for conn in self._connections:
            if self._connection_kind(conn) != CONNECTION_KIND.FLOW:
                continue
            old_conn_count = len(conn.conditions)
            conn.conditions = [
                cond for cond in conn.conditions
                if self._attribute_name_key(getattr(getattr(cond, "attribute", None), "name", "")) != name_key
            ]
            removed += old_conn_count - len(conn.conditions)

        if removed > 0:
            self.validate_all()

        return removed

    def update_connections_for(self, item):
        if item is None:
            return

        affected = []
        seen_items = set()
        stack = [item]
        while stack:
            current = stack.pop()
            if current in seen_items:
                continue
            seen_items.add(current)
            affected.append(current)
            for conn in current.all_connections() if hasattr(current, "all_connections") else []:
                src_parent = conn.src_port.parentItem() if conn.src_port else None
                dst_parent = conn.dst_port.parentItem() if conn.dst_port else None
                if src_parent is not None and src_parent not in seen_items:
                    stack.append(src_parent)
                if dst_parent is not None and dst_parent not in seen_items:
                    stack.append(dst_parent)

        for current in affected:
            if hasattr(current, "_layout"):
                current._layout()

        for current in affected:
            for conn in current.all_connections() if hasattr(current, "all_connections") else []:
                conn.update_path()

    # ── Editoren ─────────────────────────────────────────────────────────────

    def _refresh_template(self, item):
        self._register_template(item)

    def open_station_editor(self, item: StationItem):
        parent = self.views()[0] if self.views() else None
        dlg    = StationDialog(item, self._connected_attributes(item), parent)
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.result_data()
            item.name = d["name"]
            item.color        = d["color"]
            item.type         = d["type"]
            item.rules        = d["rules"]
            self._refresh_template(item)
            self.update_connections_for(item)
            self.validate_all()

    def open_attribute_editor(self, item: AttributeItem):
        parent = self.views()[0] if self.views() else None
        while True:
            dlg = AttributeDialog(item, parent)
            if dlg.exec_() != QDialog.Accepted:
                break
            d = dlg.result_data()
            if self.attribute_name_exists(d["name"], exclude_item=item):
                QMessageBox.warning(
                    parent,
                    "Attributname bereits vergeben",
                    "Jedes Attribut braucht einen eindeutigen Namen. Bitte einen anderen Namen wählen.",
                )
                continue
            item.name  = d["name"]
            item.color = d["color"]
            self._refresh_template(item)
            self.update_connections_for(item)
            self.validate_all()
            break

    def open_connection_editor(self, conn: ConnectionItem):
        parent = self.views()[0] if self.views() else None
        previous_conditions = [Condition(c.attribute, c.operator, c.value) for c in conn.conditions]
        dlg    = ConnectionDialog(conn, self._attribute_items(), parent)

        def _preview_validate():
            conn.conditions = dlg.result_data()
            conn.update()
            self.validate_all()

        dlg.conditions_changed.connect(_preview_validate)
        if dlg.exec_() == QDialog.Accepted:
            conn.conditions = dlg.result_data()
            conn.update()
            self.validate_all()
        else:
            conn.conditions = previous_conditions
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
    # Strategie: Tree Search von Root-Stationen (keine Eingabe-Verbindungen) zu
    # Leaf-Stationen (keine Ausgabe-Verbindungen). Bedingungen auf Pfeilen und
    # Stationen werden während der Traversierung überprüft. Effekte propagieren
    # den Zustand an Nachfolger-Stationen.

    def validate_all(self):
        stations = self._station_items()
        if not stations:
            return

        for item in self.selectedItems():
            if isinstance(item, ConnectionItem):
                item.setSelected(False)

        # Baue den Flow-Graph auf
        flow_preds:dict[StationItem, list] = {s: [] for s in stations}
        flow_succs:dict[StationItem, list] = {s: [] for s in stations}

        for conn in self._connections:
            conn._invalid_reasons = []
            conn.set_state(CONNECTION_STATE.UNKNOWN)
            kind = self._connection_kind(conn)

            if kind == CONNECTION_KIND.FLOW:
                src = conn.src_port.parentItem()
                dst = conn.dst_port.parentItem()
                if isinstance(src, StationItem) and isinstance(dst, StationItem):
                    flow_preds[dst].append((conn, src))
                    flow_succs[src].append((conn, dst))
            elif kind == CONNECTION_KIND.ATTRIBUTE:
                conn.set_state(CONNECTION_STATE.ATTRIBUTE)

        root_stations = [s for s in stations if s.type == STATION_TYPE.START]
        if not root_stations:
            self.status_message.emit("Keine Startstation gefunden (Typ Start fehlt)")
            return

        checkpoint_stations = {s for s in stations if s.type == STATION_TYPE.END}
        for station in checkpoint_stations:
            station.end_badge_text_color = QColor("#FFFFFF")
            station.update()

        def _apply_station_rule(rule: StationRule, incoming_state: dict) -> dict:
            output_state = dict(incoming_state)
            if all(cond.check(output_state) for cond in rule.conditions):
                output_state = self._apply_effects(output_state, rule.effects)
            return output_state

        def _transition_for(conn: ConnectionItem, station_name: str, station_conditions: list[Condition], incoming_state: dict):
            unmet_conn = self._conditions_ok(conn.conditions, incoming_state)
            unmet_station = self._conditions_ok(station_conditions, incoming_state)

            if not unmet_conn and not unmet_station:
                state = CONNECTION_STATE.VALID
            elif unmet_conn and not unmet_station:
                state = CONNECTION_STATE.CONDITIONAL_VALID
            elif not unmet_conn and unmet_station:
                state = CONNECTION_STATE.INVALID
            else:
                state = CONNECTION_STATE.CONDITIONAL_INVALID

            reasons = []
            if unmet_conn:
                conn_state_values = {cond.attribute.name: incoming_state.get(cond.attribute) for cond in unmet_conn}
                for cond in unmet_conn:
                    reasons.append(
                        f"Die Pfeil bedingung ist nicht erfüllt: {str(cond)} ({conn_state_values})"
                    )
            if unmet_station:
                station_state_values = {cond.attribute.name: incoming_state.get(cond.attribute) for cond in unmet_station}
                for cond in unmet_station:
                    reasons.append(
                        f"Die {station_name} bedingung ist nicht erfüllt: {str(cond)} ({station_state_values})"
                    )
            return state, reasons

        def _collect_connection_states(allow_conditional: bool):
            max_depth = max(5, len(self._connections) * max(5, len(stations)))
            conn_states = {conn: [] for conn in self._connections if self._connection_kind(conn) == CONNECTION_KIND.FLOW}

            def _state_key(state: dict):
                return tuple(sorted(
                    (
                        getattr(attr, "node_id", id(attr)),
                        state.get(attr),
                    )
                    for attr in state.keys()
                ))

            def _dfs(
                station: StationItem,
                incoming_state: dict,
                depth_left: int,
                reached_checkpoint: bool,
                cache: set,
            ):
                at_checkpoint = reached_checkpoint or (station in checkpoint_stations)
                cache_key = (station.node_id, depth_left, at_checkpoint, _state_key(incoming_state))
                if cache_key in cache:
                    return
                cache.add(cache_key)

                if depth_left <= 0:
                    return

                for conn, succ_station in flow_succs[station]:
                    # Stationen ohne Regeln dürfen trotzdem traversiert und validiert werden.
                    if not succ_station.rules:
                        transition_state, reasons = _transition_for(conn, succ_station.name, [], incoming_state)
                        if conn in conn_states:
                            conn_states[conn].append((transition_state, reasons))

                        if transition_state == CONNECTION_STATE.VALID:
                            pass
                        elif allow_conditional and transition_state == CONNECTION_STATE.CONDITIONAL_VALID:
                            pass
                        else:
                            continue

                        _dfs(
                            succ_station,
                            incoming_state,
                            depth_left - 1,
                            at_checkpoint,
                            cache,
                        )
                        continue

                    for rule in succ_station.rules:
                        # Bedingungen werden auf dem eingehenden Zustand geprüft;
                        # Effekte gelten erst danach, wenn die Regel wirklich passt.
                        transition_state, reasons = _transition_for(
                            conn,
                            succ_station.name,
                            rule.conditions,
                            incoming_state,
                        )
                        if conn in conn_states:
                            conn_states[conn].append((transition_state, reasons))

                        if transition_state == CONNECTION_STATE.VALID:
                            pass
                        elif allow_conditional and transition_state == CONNECTION_STATE.CONDITIONAL_VALID:
                            pass
                        else:
                            continue

                        current_state = _apply_station_rule(rule, incoming_state)

                        _dfs(
                            succ_station,
                            current_state,
                            depth_left - 1,
                            at_checkpoint,
                            cache,
                        )
            for depth in range(1, max_depth + 1):
                for root in root_stations:
                    _dfs(root, {}, depth, False, set())
            return conn_states

        strict_states = _collect_connection_states(allow_conditional=False)
        fallback_states = _collect_connection_states(allow_conditional=True)

        def _collect_checkpoint_path_levels():
            max_depth = max(5, len(self._connections) * max(5, len(stations)))
            checkpoint_levels = {station: set() for station in checkpoint_stations}

            def _state_key(state: dict):
                return tuple(sorted(
                    (
                        getattr(attr, "node_id", id(attr)),
                        state.get(attr),
                    )
                    for attr in state.keys()
                ))

            def _state_level(state: CONNECTION_STATE) -> int:
                if state == CONNECTION_STATE.VALID:
                    return 0
                if state == CONNECTION_STATE.CONDITIONAL_VALID:
                    return 1
                return 2

            def _dfs(station: StationItem, incoming_state: dict, depth_left: int, level: int, cache: set):
                cache_key = (station.node_id, depth_left, level, _state_key(incoming_state))
                if cache_key in cache:
                    return
                cache.add(cache_key)

                if depth_left <= 0:
                    return

                for conn, succ_station in flow_succs[station]:
                    if not succ_station.rules:
                        transition_state, _ = _transition_for(conn, succ_station.name, [], incoming_state)
                        next_level = max(level, _state_level(transition_state))
                        if succ_station in checkpoint_levels:
                            checkpoint_levels[succ_station].add(next_level)
                        _dfs(succ_station, incoming_state, depth_left - 1, next_level, cache)
                        continue

                    for rule in succ_station.rules:
                        transition_state, _ = _transition_for(conn, succ_station.name, rule.conditions, incoming_state)
                        next_level = max(level, _state_level(transition_state))
                        if succ_station in checkpoint_levels:
                            checkpoint_levels[succ_station].add(next_level)
                        current_state = _apply_station_rule(rule, incoming_state)
                        _dfs(succ_station, current_state, depth_left - 1, next_level, cache)

            for depth in range(1, max_depth + 1):
                for root in root_stations:
                    _dfs(root, {}, depth, 0, set())
            return checkpoint_levels

        checkpoint_levels = _collect_checkpoint_path_levels()

        priority = {
            CONNECTION_STATE.VALID: 0,
            CONNECTION_STATE.CONDITIONAL_VALID: 1,
            CONNECTION_STATE.CONDITIONAL_INVALID: 2,
            CONNECTION_STATE.INVALID: 3,
        }

        validated_flow = 0
        for conn in self._connections:
            kind = self._connection_kind(conn)
            if kind == CONNECTION_KIND.ATTRIBUTE:
                continue
            if kind != CONNECTION_KIND.FLOW:
                if not conn.src_port or not conn.dst_port:
                    conn._invalid_reasons = ["Die Verbindung hat keinen vollständigen Start-/Ziel-Port."]
                else:
                    conn._invalid_reasons = ["Die Verbindungstypen passen nicht zusammen."]
                continue

            candidates = strict_states.get(conn, [])
            if not any(state == CONNECTION_STATE.VALID for state, _ in candidates):
                candidates = fallback_states.get(conn, [])

            if candidates:
                best_state, best_reasons = min(candidates, key=lambda x: priority.get(x[0], 99))
                conn.set_state(best_state)
                conn._invalid_reasons = best_reasons
                validated_flow += 1
            else:
                conn.set_state(CONNECTION_STATE.UNKNOWN)
                conn._invalid_reasons = ["Keine erreichbare Validierungsroute von einer Startstation."]

        total_flow = sum(1 for conn in self._connections if self._connection_kind(conn) == CONNECTION_KIND.FLOW)
        valid_flow = sum(1 for conn in self._connections if conn._state == CONNECTION_STATE.VALID)
        conditional_flow = sum(1 for conn in self._connections if conn._state == CONNECTION_STATE.CONDITIONAL_VALID)
        invalid_flow = sum(
            1
            for conn in self._connections
            if conn._state in (CONNECTION_STATE.INVALID, CONNECTION_STATE.CONDITIONAL_INVALID)
        )

        self.status_message.emit(
            f"{validated_flow}/{total_flow} FLOW-Verbindungen validiert  |  "
            f"gültig: {valid_flow}, bedingt gültig: {conditional_flow}, ungültig: {invalid_flow}"
        )

        for station in checkpoint_stations:
            levels = checkpoint_levels.get(station, set())
            if levels and levels == {0}:
                station.end_badge_text_color = QColor("#22C55E")  # all fully valid
            elif 0 in levels:
                station.end_badge_text_color = QColor("#3B82F6")  # any fully valid
            elif 1 in levels:
                station.end_badge_text_color = QColor("#9A1DEE")  # any conditional valid
            else:
                station.end_badge_text_color = QColor("#FFFFFF")
            station.update()

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
                if isinstance(item, AttributeItem):
                    item.name = scene.make_unique_attribute_name(item.name)
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

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            item = self.currentItem()
            template_key = item.data(Qt.UserRole) if item is not None else None
            if template_key and self.palette_widget.can_remove_template(self.kind, template_key):
                self.palette_widget.remove_template(self.kind, template_key)
                event.accept()
                return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item is None:
            super().contextMenuEvent(event)
            return

        template_key = item.data(Qt.UserRole)
        menu = QMenu(self)
        can_delete = self.palette_widget.can_remove_template(self.kind, template_key)
        delete_action = menu.addAction("Aus Palette löschen")
        delete_action.setEnabled(can_delete)
        if not can_delete:
            delete_action.setToolTip("Nur möglich, wenn keine zugehörigen Objekte im Editor liegen.")
        chosen = menu.exec_(self.viewport().mapToGlobal(event.pos()))
        if chosen == delete_action and can_delete:
            self.palette_widget.remove_template(self.kind, template_key)
            event.accept()
            return
        super().contextMenuEvent(event)


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
        )
        self.hints = QLabel(self._default_help_text)
        self.hints.setFont(QFont("Segoe UI", 8))
        self.hints.setStyleSheet("color:#475569; padding:6px 2px;")
        self.hints.setWordWrap(True)
        lo.addWidget(self.hints)
        lo.addStretch()

        self.station_list.itemDoubleClicked.connect(lambda item: self.add_template_to_scene("station", item.data(Qt.UserRole)))
        self.attribute_list.itemDoubleClicked.connect(lambda item: self.add_template_to_scene("attribute", item.data(Qt.UserRole)))

    @staticmethod
    def _attribute_key(name: str) -> str:
        return (name or "").strip().lower()

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
        correctness = ""
        match(conn._state):
            case CONNECTION_STATE.VALID:
                correctness = "gültig"
            case CONNECTION_STATE.CONDITIONAL_VALID:
                correctness = "bedingt gültig"
            case CONNECTION_STATE.CONDITIONAL_INVALID:
                correctness = "bedingt ungültig"
            case CONNECTION_STATE.INVALID:
                correctness = "ungültig"
            case _:
                correctness = "ungeprüft" 
        lines = [f"Dieser Pfeil ist {correctness}, weil:", ""]
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
            label = item.name
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
            template_id = self._attribute_key(item.name)
            if not template_id:
                return

            stale_keys = [
                key for key, template in self._attribute_templates.items()
                if getattr(template, "template_id", None) == item.template_id and key != template_id
            ]
            for key in stale_keys:
                self._attribute_templates.pop(key, None)
                li_old = self._attribute_items.pop(key, None)
                if li_old is not None:
                    row_old = self.attribute_list.row(li_old)
                    if row_old >= 0:
                        self.attribute_list.takeItem(row_old)

            label = item.name
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

    def can_remove_template(self, kind: str, template_id: str) -> bool:
        if self.scene_widget is None:
            return True

        if kind == "station":
            return not any(
                isinstance(item, StationItem) and getattr(item, "template_id", None) == template_id
                for item in self.scene_widget.items()
            )

        if kind == "attribute":
            return not any(
                isinstance(item, AttributeItem) and self._attribute_key(item.name) == template_id
                for item in self.scene_widget.items()
            )

        return True

    def remove_template(self, kind: str, template_id: str):
        if kind == "station":
            self._station_templates.pop(template_id, None)
            li = self._station_items.pop(template_id, None)
            if li is not None:
                row = self.station_list.row(li)
                if row >= 0:
                    self.station_list.takeItem(row)
        elif kind == "attribute":
            template = self._attribute_templates.pop(template_id, None)
            attr_name = template.name if isinstance(template, AttributeItem) else ""
            li = self._attribute_items.pop(template_id, None)
            if li is not None:
                row = self.attribute_list.row(li)
                if row >= 0:
                    self.attribute_list.takeItem(row)
                attr_name = li.text() or attr_name

            if self.scene_widget is not None:
                removed = self.scene_widget.remove_arrow_conditions_for_attribute_name(attr_name)
                if removed > 0:
                    self.scene_widget.status_message.emit(
                        f"{removed} Pfeil-Bedingung(en) nach Attribut-Entfernung aus Palette gelöscht."
                    )

        self._sync_placeholders()

    def add_template_to_scene(self, kind: str, template_id: str):
        if self.scene_widget is None:
            return None
        item = self.clone_template(kind, template_id)
        if item is None:
            return None
        if isinstance(item, AttributeItem):
            item.name = self.scene_widget.make_unique_attribute_name(item.name)
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
        if isinstance(item, AttributeItem):
            item.name = self.scene.make_unique_attribute_name(item.name)
        self.scene.addItem(item)
        self._place_item_center(item)
        self.scene.clearSelection()
        item.setSelected(True)
        self.scene._register_template(item)
        self.scene.validate_all()

    def _new_station(self):
        item = StationItem("Neue Station", type = STATION_TYPE.START if len(self.scene._station_items()) <= 0 else (STATION_TYPE.END if len(self.scene._station_items()) == 1 else STATION_TYPE.NORMAL))
        self._add_item_to_scene(item)

    def _new_attribute(self):
        item = AttributeItem("Neues Attribut")
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
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                title,
                start_path,
                name_filter,
            )    
        return path or default_name

    def _on_scene_selection_changed(self):
        selected = self.scene.selectedItems()
        invalid_conn = next(
            (item for item in selected if isinstance(item, ConnectionItem) and item._state is not CONNECTION_STATE.VALID),
            None,
        )
        if invalid_conn is not None:
            self.palette.show_invalid_connection_help(invalid_conn)
        else:
            self.palette.show_default_help()

    @staticmethod
    def _serialize_condition(cond: Condition) -> dict:
        return StationItem._serialize_condition(cond)

    @staticmethod
    def _deserialize_condition(data: dict) -> Condition:
        return StationItem._deserialize_condition(data)

    @staticmethod
    def _serialize_effect(eff: Effect) -> dict:
        return StationItem._serialize_effect(eff)

    @staticmethod
    def _deserialize_effect(data: dict) -> Effect:
        return StationItem._deserialize_effect(data)

    @staticmethod
    def _port_by_type(item, port_type: str):
        return ConnectionItem._resolve_port(item, port_type)

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
            
        try:
            stations = [i for i in self.scene.items() if isinstance(i, StationItem)]
            attributes = [i for i in self.scene.items() if isinstance(i, AttributeItem)]
            textblocks = [i for i in self.scene.items() if isinstance(i, TextBlockItem)]

            data = {
                "version": 1,
                "attributes": [a.to_json() for a in attributes],
                "stations": [s.to_json() for s in stations],
                "textblocks": [
                    {
                        "node_id": t.node_id,
                        "text": t._text,
                        "x": float(t.pos().x()),
                        "y": float(t.pos().y()),
                    }
                    for t in textblocks
                ],
                "connections": [c.to_json() for c in self.scene._connections if c.src_port and c.dst_port],
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
        for a in data.get("attributes", []):
            item = AttributeItem.from_json(a)
            item.name = self.scene.make_unique_attribute_name(item.name)
            self.scene.addItem(item)
            self.scene._register_template(item)
            node_map[item.node_id] = item
            
        for s in data.get("stations", []):
            item = StationItem.from_json(s, node_map)
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
            conn = ConnectionItem.from_json(c, node_map)
            if conn is None:
                continue
            self.scene._connections.append(conn)
            self.scene.addItem(conn)

        # Ergänze fehlende Attribut-Verbindungen, wenn Regeln Attribute referenzieren.
        existing_attr_links = set()
        for conn in self.scene._connections:
            if self.scene._connection_kind(conn) != CONNECTION_KIND.ATTRIBUTE:
                continue
            src_item = conn.src_port.parentItem() if conn.src_port else None
            dst_item = conn.dst_port.parentItem() if conn.dst_port else None
            if isinstance(src_item, AttributeItem) and isinstance(dst_item, StationItem):
                existing_attr_links.add((src_item.node_id, dst_item.node_id))

        touched_items = set()
        for station in [item for item in self.scene.items() if isinstance(item, StationItem)]:
            required_attributes = set()
            for rule in station.rules:
                for cond in rule.conditions:
                    if isinstance(cond.attribute, AttributeItem):
                        required_attributes.add(cond.attribute)
                for eff in rule.effects:
                    if isinstance(eff.attribute, AttributeItem):
                        required_attributes.add(eff.attribute)

            for attribute in required_attributes:
                link_key = (attribute.node_id, station.node_id)
                if link_key in existing_attr_links:
                    continue

                conn = ConnectionItem(attribute.out_port)
                conn.finalize(station.attr_port)
                attribute.out_port.connections.append(conn)
                station.attr_port.connections.append(conn)
                self.scene._connections.append(conn)
                self.scene.addItem(conn)
                existing_attr_links.add(link_key)
                touched_items.add(attribute)
                touched_items.add(station)

        for item in touched_items:
            self.scene.update_connections_for(item)

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

        printer = QPrinter()
        printer.setResolution(125)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageSize(QPrinter.A4)
        printer.setOrientation(QPrinter.Landscape)
        printer.setFullPage(True)
        painter = QPainter(printer)
        if not painter.isActive():
            return
        try:
            self._paint_pdf_editor_page(painter, printer)
            printer.newPage()
            self._paint_pdf_clean_flow_page(painter, printer)
        finally:
            painter.end()
        self.statusBar().showMessage(f"PDF exportiert: {path}")

    def _paint_pdf_editor_page(self, painter: QPainter, printer: QPrinter):
        page_rect = printer.pageRect(QPrinter.DevicePixel)
        source = self.scene.itemsBoundingRect().adjusted(-100, -100, 100, 10)
        if source.isEmpty():
            source = self.scene.sceneRect().adjusted(0, 0, -1, -1)
        target = QRectF(30, 60, page_rect.width() - 60, page_rect.height() - 90)
        painter.translate(printer.pageRect().center())
        painter.scale(1.1, 1.1)
        painter.translate(-target.width()/2-15, -target.height()/2-15)
        self.scene.render(painter, target, source)

    def _paint_pdf_flow_page(self, painter: QPainter, printer: QPrinter):
        page_rect = printer.pageRect(QPrinter.DevicePixel)

        stations = [item for item in self.scene.items() if isinstance(item, StationItem)]
        if not stations:
            painter.setFont(QFont("Segoe UI", 4))
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
            painter.drawText(QRectF(rect.left() + 8, rect.top() + 8, rect.width() - 16, 18), Qt.AlignLeft, station.name)
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(QRectF(rect.left() + 8, rect.top() + 28, rect.width() - 16, 14), Qt.AlignLeft, f"Regeln: {len(station.rules)}")
            painter.drawText(QRectF(rect.left() + 8, rect.top() + 42, rect.width() - 16, 14), Qt.AlignLeft, f"Bedingungen: {len(station.conditions)}  /  Effekte: {len(station.effects)}")

    def _paint_pdf_clean_flow_page(self, painter: QPainter, printer: QPrinter):
        page_rect = printer.pageRect(QPrinter.DevicePixel)

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
        painter.setPen(QColor("#111827"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        painter.drawText(QRectF(36, 24, page_rect.width() - 72, 24), Qt.AlignLeft, "Flow-Ansicht (ohne Attribut-Verbindungen)")

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

        # Knoten
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
