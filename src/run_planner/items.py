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
import time
import numpy as np
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from threading import Event
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
    QCheckBox,
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

PORT_R         = 9
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
        parent_z = parent.zValue() if parent is not None else 0
        self.setZValue(parent_z + 1)
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
        # Calculate width from both rule text and title text.
        rule_font = QFont("Consolas", 7)
        rule_metrics = QFontMetrics(rule_font)
        title_font = QFont("Segoe UI", 9, QFont.Bold)
        title_metrics = QFontMetrics(title_font)

        max_rule_width = 0
        for rule in self.rules:
            max_rule_width = max(max_rule_width, rule_metrics.horizontalAdvance(str(rule)))

        # Rules are drawn with x=8 and right padding; keep extra headroom for anti-aliasing.
        rules_required_w = max_rule_width + 32

        # Title area reserves badge space and right gap in the header.
        badge_reserved_w = 58 + 24 if self.type != STATION_TYPE.NORMAL else 12
        title_required_w = title_metrics.horizontalAdvance(self.name or "") + 10 + badge_reserved_w

        self._w = min(max(STATION_W, rules_required_w, title_required_w), 1200)
        
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
        # Z-Layer pro Station: 1) Body, 2) Ports, 3) eingehende Pfeile.
        self.in_port.setZValue(self.zValue() + 1)
        self.out_port.setZValue(self.zValue() + 1)
        self.attr_port.setZValue(self.zValue() + 1)
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
        elif change == QGraphicsItem.ItemZValueHasChanged and self.scene():
            self.in_port.setZValue(self.zValue() + 1)
            self.out_port.setZValue(self.zValue() + 1)
            self.attr_port.setZValue(self.zValue() + 1)
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
            "compare_attribute": getattr(cond.compare_attribute, "node_id", None),
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
            node_map.get(data.get("compare_attribute")),
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
        self.out_port.setZValue(self.zValue() + 1)
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
        elif change == QGraphicsItem.ItemZValueHasChanged and self.scene():
            self.out_port.setZValue(self.zValue() + 1)
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
    CONDITIONAL_VALID = QColor("#D3FB24")
    CONDITIONAL_INVALID = QColor("#FB9724")
    ATTRIBUTE = QColor("#9A1DEE")

class ConnectionItem(QGraphicsPathItem):
    ItemType = QGraphicsItem.UserType + 3

    def __init__(self, src_port: Port, dst_port: Port = None, name: str = ""):
        super().__init__()
        self.src_port:Port   = src_port
        self.dst_port:Port   = dst_port
        self.conditions:list[Condition] = []
        self.name: str = (name or "").strip()
        self._invalid_reasons = []
        self._state:CONNECTION_STATE = CONNECTION_STATE.UNKNOWN
        self._highlighted = False
        self._drag_end  = None
        self._manual_z_override = False
        self._syncing_z = False
        self._sync_z_layer()
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self._rebuild()

    def _sync_z_layer(self):
        if self._manual_z_override:
            return
        # Eingehende Pfeile einer Station liegen über Body und Ports der Ziel-Station.
        dst_parent = self.dst_port.parentItem() if self.dst_port else None
        if dst_parent is not None:
            self._syncing_z = True
            self.setZValue(dst_parent.zValue() + 2)
            self._syncing_z = False
            return
        src_parent = self.src_port.parentItem() if self.src_port else None
        self._syncing_z = True
        self.setZValue((src_parent.zValue() + 2) if src_parent is not None else 2)
        self._syncing_z = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemZValueHasChanged and not self._syncing_z:
            self._manual_z_override = True
            self._sync_z_layer()
        return super().itemChange(change, value)

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
        self._sync_z_layer()

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

    def set_highlighted(self, highlighted: bool):
        highlighted = bool(highlighted)
        if self._highlighted != highlighted:
            self._highlighted = highlighted
            self.update()

    def doubleClickTarget(self):
        return self.src_port.parentItem() if self.src_port else None

    # ── Paint (Pfeilspitze) ───────────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)

        scene = self.scene()

        if self._highlighted:
            painter.setPen(QPen(QColor(252, 211, 77, 150), 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.path())

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

        if self.name:
            mid = path.pointAtPercent(0.5)
            text = self.name
            metrics = QFontMetrics(QFont("Segoe UI", 8, QFont.Bold))
            text_w = metrics.horizontalAdvance(text)
            text_h = max(14, metrics.height())
            label_rect = QRectF(mid.x() - (text_w / 2) - 6, mid.y() + 6, text_w + 12, text_h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(15, 23, 42, 220)))
            painter.drawRoundedRect(label_rect, 4, 4)
            painter.setPen(QColor("#E2E8F0"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.drawText(label_rect, Qt.AlignCenter, text)
        
        # ATTRIBUTE-Verbindungen optional verbergen
        if scene is not None and hasattr(scene, 'show_attribute_connections'):
            if not scene.show_attribute_connections and self._state == CONNECTION_STATE.ATTRIBUTE:
                self.setVisible(False)
            else:
                self.setVisible(True)
        else:
            self.setVisible(True)

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
        scene = self.scene()
        if scene is not None and hasattr(scene, 'show_connection_hitboxes') and scene.show_connection_hitboxes:
            # Toggle aktiv: Connection-Hitboxen deaktivieren (nicht anklickbar)
            return False

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
            "name": self.name,
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

        conn = cls(src_port, name=data.get("name", ""))
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


class NoteLinkItem(QGraphicsPathItem):
    ItemType = QGraphicsItem.UserType + 5

    def __init__(self, src_item: "TextBlockItem", dst_item: QGraphicsItem):
        super().__init__()
        self.src_item = src_item
        self.dst_item = dst_item
        self.setZValue(-20)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self._apply_style()
        self.update_path()

    def _apply_style(self):
        self.setPen(QPen(QColor("#94A3B8"), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    @staticmethod
    def _item_center(item: QGraphicsItem) -> QPointF:
        return item.mapToScene(item.boundingRect().center())

    def update_path(self):
        if self.src_item is None or self.dst_item is None:
            return
        start = self._item_center(self.src_item)
        end = self._item_center(self.dst_item)

        dx = end.x() - start.x()
        dy = end.y() - start.y()
        cp = max(30.0, min(160.0, math.hypot(dx, dy) * 0.35))
        c1 = QPointF(start.x() + cp, start.y())
        c2 = QPointF(end.x() - cp, end.y())

        path = QPainterPath(start)
        path.cubicTo(c1, c2, end)
        self.setPath(path)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        super().paint(painter, option, widget)

    @property
    def src_node_id(self) -> str | None:
        return getattr(self.src_item, "node_id", None)

    @property
    def dst_node_id(self) -> str | None:
        return getattr(self.dst_item, "node_id", None)

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

    def __init__(
        self,
        attribute: AttributeItem = None,
        operator: CONDITION_OP = CONDITION_OP.EXISTS,
        value: float = 0.0,
        compare_attribute: AttributeItem = None,
    ):
        self.attribute:AttributeItem = attribute
        self.operator:CONDITION_OP   = operator
        self.value:float     = value
        self.compare_attribute: AttributeItem = compare_attribute

    def _as_number(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def check(self, attrs: dict) -> bool:
        count = 0.0 if self.attribute not in attrs or attrs[self.attribute] is None else attrs[self.attribute]
        compare_count = (
            0.0
            if self.compare_attribute is None or self.compare_attribute not in attrs or attrs[self.compare_attribute] is None
            else attrs[self.compare_attribute]
        )
        rhs = compare_count if self.compare_attribute is not None else self._as_number(self.value)
        match(self.operator):
            case CONDITION_OP.EXISTS:
                return count > 0
            case CONDITION_OP.NOT_EXISTS:
                return count == 0
            case CONDITION_OP.EQUALS:
                return count == rhs
            case CONDITION_OP.NOT_EQUALS:
                return count != rhs
            case CONDITION_OP.GREATER:
                return count > rhs
            case CONDITION_OP.GREATER_EQ:
                return count >= rhs
            case CONDITION_OP.LESS:
                return count < rhs
            case CONDITION_OP.LESS_EQ:
                return count <= rhs

    def __str__(self):
        a = self.attribute.name if isinstance(self.attribute, AttributeItem) else str(self.attribute)
        prefix = f"⟨{a}⟩"
        match(self.operator):
            case CONDITION_OP.EXISTS:
                return f"{prefix} vorhanden"
            case CONDITION_OP.NOT_EXISTS:
                return f"{prefix} fehlt"
        if isinstance(self.compare_attribute, AttributeItem):
            return f"{prefix} {self.operator.value} ⟨{self.compare_attribute.name}⟩"
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
    _group_counter = 0

    conditions: list[Condition] = field(default_factory=list)
    effects: list[Effect] = field(default_factory=list)
    max_traversals: int = 20
    group_number: int | None = None
    rule_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @classmethod
    def _next_group_number(cls) -> int:
        cls._group_counter += 1
        return cls._group_counter

    def __post_init__(self):
        if not self.rule_id:
            self.rule_id = uuid.uuid4().hex
        if self.group_number is None:
            self.group_number = self._next_group_number()
        else:
            try:
                self.group_number = max(1, int(self.group_number))
                StationRule._group_counter = max(StationRule._group_counter, self.group_number)
            except (TypeError, ValueError):
                self.group_number = self._next_group_number()
        try:
            self.max_traversals = min(1000, max(1, int(self.max_traversals)))
        except (TypeError, ValueError):
            self.max_traversals = 20

    def clone(self) -> "StationRule":
        return StationRule(
            conditions=[Condition(c.attribute, c.operator, c.value, c.compare_attribute) for c in self.conditions],
            effects=[Effect(e.attribute, e.action, e.value) for e in self.effects],
            max_traversals=self.max_traversals,
            group_number=self.group_number,
            rule_id=self.rule_id,
        )

    def to_json(self) -> dict:
        return {
            "conditions": [StationItem._serialize_condition(cond) for cond in self.conditions],
            "effects": [StationItem._serialize_effect(eff) for eff in self.effects],
            "max_traversals": int(self.max_traversals),
            "group_number": int(self.group_number),
            "rule_id": self.rule_id,
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
        legacy_one_time = bool(data.get("one_time", False))
        max_traversals = data.get("max_traversals", 1 if legacy_one_time else 20)
        return StationRule(
            conditions=conditions,
            effects=effects,
            max_traversals=max_traversals,
            group_number=data.get("group_number"),
            rule_id=data.get("rule_id") or uuid.uuid4().hex,
        )

    def __str__(self) -> str:
        cond_text = " ∧ ".join(str(cond) for cond in self.conditions) if self.conditions else "immer"
        eff_text = ", ".join(str(eff) for eff in self.effects) if self.effects else "keine Effekte"
        traversal_text = f"[G{self.group_number} | {self.max_traversals}x]"
        return f"{traversal_text} {cond_text} → {eff_text}"


# ══════════════════════════════════════════════════════════════════════════════
#  TEXTBLOCKITEM
# ══════════════════════════════════════════════════════════════════════════════

class TextBlockItem(QGraphicsItem):
    ItemType = QGraphicsItem.UserType + 2

    def __init__(self, text: str = "Beschreibung ..."):
        super().__init__()
        self.node_id = uuid.uuid4().hex
        self._text = text
        self.linked_node_ids: set[str] = set()
        self._w    = 180
        self._h    = 70
        self.setZValue(5)
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
        painter.fillPath(body, QBrush(QColor(255, 252, 220, 255)))

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

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.scene().update_connections_for(self)
        return super().itemChange(change, value)


