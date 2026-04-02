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
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QAbstractItemView,
    QGraphicsScene, QGraphicsView, QGraphicsItem, QGraphicsEllipseItem,
    QGraphicsPathItem, QGraphicsRectItem, QFrame, QDialog, QDialogButtonBox,
    QLineEdit, QComboBox, QGroupBox, QScrollArea, QPlainTextEdit,
    QAction, QMessageBox, QColorDialog, QSizePolicy, QToolBar,
    QSpacerItem, QStatusBar
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
from collections import deque


# ══════════════════════════════════════════════════════════════════════════════
#  DATENMODELLE
# ══════════════════════════════════════════════════════════════════════════════

class Condition:
    """Vorbedingung an einem Produktattribut."""
    OP_EXISTS     = "exists"
    OP_NOT_EXISTS = "not_exists"
    OP_EQUALS     = "equals"
    OP_NOT_EQUALS = "not_equals"

    OP_LABELS = {
        OP_EXISTS:     "existiert",
        OP_NOT_EXISTS: "existiert nicht",
        OP_EQUALS:     "= Wert",
        OP_NOT_EQUALS: "≠ Wert",
    }

    def __init__(self, attribute="", operator=None, value=""):
        self.attribute = attribute
        self.operator  = operator or self.OP_EXISTS
        self.value     = value

    def check(self, attrs: dict) -> bool:
        if self.operator == self.OP_EXISTS:
            return self.attribute in attrs
        if self.operator == self.OP_NOT_EXISTS:
            return self.attribute not in attrs
        if self.operator == self.OP_EQUALS:
            return attrs.get(self.attribute) == self.value
        if self.operator == self.OP_NOT_EQUALS:
            return attrs.get(self.attribute) != self.value
        return True

    def __str__(self):
        a = self.attribute or "?"
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
            attrs[self.attribute] = self.value
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
        else:
            self.setBrush(QBrush(QColor("#3B82F6")))
            self.setPen(QPen(QColor("#1D4ED8"), 1.5))

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
        self.conditions   = []   # list[Condition]
        self.effects      = []   # list[Effect]

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
        self._layout()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _layout(self):
        rows = len(self.conditions) + len(self.effects)
        extra = max(0, rows - 1) * LINE_H
        self._h = STATION_H_MIN + extra
        half_h = self._h / 2
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
        c = self.color
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
        painter.setFont(QFont("Consolas", 7.5))

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
        return list(self.in_port.connections) + list(self.out_port.connections)


# ══════════════════════════════════════════════════════════════════════════════
#  TEXTBLOCKITEM
# ══════════════════════════════════════════════════════════════════════════════

class TextBlockItem(QGraphicsItem):
    ItemType = QGraphicsItem.UserType + 2

    def __init__(self, text: str = "Beschreibung ..."):
        super().__init__()
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
        self._state     = self.STATE_UNKNOWN
        self._drag_end  = None
        self.setZValue(8)
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

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(-15, -15, 15, 15)


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

    def __init__(self, cond: Condition, parent=None):
        super().__init__(parent)
        self._cond = cond
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(4)

        self.attr = QLineEdit(cond.attribute)
        self.attr.setPlaceholderText("Attribut")
        self.attr.setFixedWidth(110)

        self.op = QComboBox()
        self._ops = [Condition.OP_EXISTS, Condition.OP_NOT_EXISTS,
                     Condition.OP_EQUALS, Condition.OP_NOT_EQUALS]
        for lbl in Condition.OP_LABELS.values():
            self.op.addItem(lbl)
        idx = self._ops.index(cond.operator) if cond.operator in self._ops else 0
        self.op.setCurrentIndex(idx)
        self.op.currentIndexChanged.connect(self._on_op)

        self.val = QLineEdit(cond.value)
        self.val.setPlaceholderText("Wert")
        self.val.setFixedWidth(90)
        self.val.setVisible(idx >= 2)

        btn = QPushButton("✕")
        btn.setObjectName("del_btn")
        btn.setFixedSize(22, 22)
        btn.clicked.connect(lambda: self.removed.emit(self))

        lo.addWidget(self.attr)
        lo.addWidget(self.op)
        lo.addWidget(self.val)
        lo.addWidget(btn)

    def _on_op(self, idx):
        self.val.setVisible(idx >= 2)

    def get(self) -> Condition:
        return Condition(
            self.attr.text(),
            self._ops[self.op.currentIndex()],
            self.val.text()
        )


class EffectRow(QWidget):
    removed = pyqtSignal(object)

    def __init__(self, eff: Effect, parent=None):
        super().__init__(parent)
        self._eff = eff
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

        self.attr = QLineEdit(eff.attribute)
        self.attr.setPlaceholderText("Attribut")
        self.attr.setFixedWidth(110)

        self.val = QLineEdit(eff.value)
        self.val.setPlaceholderText("Wert")
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

    def get(self) -> Effect:
        return Effect(
            self._acts[self.act.currentIndex()],
            self.attr.text(),
            self.val.text()
        )


class StationDialog(QDialog):
    def __init__(self, item: StationItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Station bearbeiten")
        self.setMinimumWidth(530)
        self.setStyleSheet(DIALOG_STYLE)
        self._color = item.color
        self._cond_rows: list[ConditionRow] = []
        self._eff_rows:  list[EffectRow]    = []
        self._build(item)

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
            self._add_cond(Condition(c.attribute, c.operator, c.value))
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
        w = ConditionRow(cond)
        w.removed.connect(self._rm_cond)
        self._cond_rows.append(w)
        self._cond_vbox.addWidget(w)

    def _rm_cond(self, w: ConditionRow):
        self._cond_rows.remove(w)
        self._cond_vbox.removeWidget(w)
        w.deleteLater()

    def _add_eff(self, eff: Effect):
        w = EffectRow(eff)
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

    # ── Maus-Interaktion ─────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.scenePos(), QTransform())
            if isinstance(item, Port) and item.port_type == Port.OUTPUT:
                # Neue Verbindung beginnen
                self._wip_src  = item
                conn = ConnectionItem(item)
                conn.set_drag_end(event.scenePos())
                self.addItem(conn)
                self._wip_conn = conn
                self.status_message.emit(
                    "Verbindung ziehen → auf grünen Eingangs-Port der Ziel-Station loslassen."
                )
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
            item = self.itemAt(event.scenePos(), QTransform())
            if (isinstance(item, Port)
                    and item.port_type == Port.INPUT
                    and item.parentItem() is not self._wip_src.parentItem()):
                # Verbindung abschließen
                self._wip_conn.finalize(item)
                self._wip_src.connections.append(self._wip_conn)
                item.connections.append(self._wip_conn)
                self._connections.append(self._wip_conn)
                self.validate_all()
                self.status_message.emit("Verbindung erstellt. Doppelklick auf Station zum Bearbeiten.")
            else:
                self.removeItem(self._wip_conn)
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

    def update_connections_for(self, item: StationItem):
        for c in item.all_connections():
            c.update_path()
        self.validate_all()

    # ── Editoren ─────────────────────────────────────────────────────────────

    def open_station_editor(self, item: StationItem):
        parent = self.views()[0] if self.views() else None
        dlg    = StationDialog(item, parent)
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.result_data()
            item.station_name = d["name"]
            item.color        = d["color"]
            item.conditions   = d["conditions"]
            item.effects      = d["effects"]
            item._layout()
            item.update()
            self.validate_all()

    def open_text_editor(self, item: TextBlockItem):
        parent = self.views()[0] if self.views() else None
        dlg    = TextDialog(item, parent)
        if dlg.exec_() == QDialog.Accepted:
            item._text = dlg.get_text()
            item._recalc_height()
            item.update()

    # ── Validierung ──────────────────────────────────────────────────────────
    # Strategie: Breitensuche von allen Startknoten (kein Eingangs-Port belegt).
    # Jedem Station-Knoten werden alle möglichen Produktzustände (frozenset der
    # Attribute) zugewiesen, die beim Eintreffen möglich sind.
    # Eine Verbindung A→B ist GRÜN, wenn nach Anwendung aller Effekte von A
    # jeder mögliche Produktzustand alle Bedingungen von B erfüllt.
    # Ist mindestens ein Zustand ungültig → ROT.

    def validate_all(self):
        stations: list[StationItem] = [
            i for i in self.items() if isinstance(i, StationItem)
        ]
        if not stations:
            return

        def successors(s: StationItem):
            res = []
            for c in s.out_port.connections:
                if c.dst_port and isinstance(c.dst_port.parentItem(), StationItem):
                    res.append((c, c.dst_port.parentItem()))
            return res

        def predecessors(s: StationItem):
            res = []
            for c in s.in_port.connections:
                if c.src_port and isinstance(c.src_port.parentItem(), StationItem):
                    res.append((c, c.src_port.parentItem()))
            return res

        # Topologische Reihenfolge (Kahn)
        in_deg = {s: len(predecessors(s)) for s in stations}
        queue  = deque(s for s in stations if in_deg[s] == 0)
        order  = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for _, succ in successors(node):
                in_deg[succ] -= 1
                if in_deg[succ] == 0:
                    queue.append(succ)
        # Restknoten (Zyklen) hinten anhängen
        for s in stations:
            if s not in order:
                order.append(s)

        # Mögliche Eingangs-Zustände je Station (list[frozenset])
        incoming: dict[StationItem, list[frozenset]] = {}
        for s in stations:
            incoming[s] = []

        # Startstationen erhalten leeres Produkt {}
        for s in stations:
            if in_deg.get(s, len(predecessors(s))) == 0 or not predecessors(s):
                incoming[s] = [frozenset()]

        # Vorwärts propagieren
        for s in order:
            states_in = incoming[s] or [frozenset()]
            # Nach Effekten
            states_out = []
            for frozen in states_in:
                attrs = dict(frozen)
                for eff in s.effects:
                    attrs = eff.apply(attrs)
                states_out.append(frozenset(attrs.items()))

            for _, succ in successors(s):
                incoming[succ].extend(states_out)

        # Verbindungen bewerten
        for conn in self._connections:
            if not conn.src_port or not conn.dst_port:
                conn.set_state(ConnectionItem.STATE_UNKNOWN)
                continue
            src: StationItem = conn.src_port.parentItem()
            dst: StationItem = conn.dst_port.parentItem()
            if not isinstance(src, StationItem) or not isinstance(dst, StationItem):
                conn.set_state(ConnectionItem.STATE_UNKNOWN)
                continue

            states_after_src = []
            for frozen in (incoming.get(src) or [frozenset()]):
                attrs = dict(frozen)
                for eff in src.effects:
                    attrs = eff.apply(attrs)
                states_after_src.append(attrs)

            if not states_after_src:
                states_after_src = [{}]

            all_ok = all(
                all(c.check(attrs) for c in dst.conditions)
                for attrs in states_after_src
            )
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

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        mime = event.mimeData().text()
        pos  = self.mapToScene(event.pos())
        if mime.startswith("station:"):
            hex_col = mime.split(":", 1)[1]
            item = StationItem("Neue Station", QColor(hex_col))
            item.setPos(pos - QPointF(STATION_W / 2, 40))
            self.scene().addItem(item)
            self.scene().clearSelection()
            item.setSelected(True)
            self.scene().validate_all()
        elif mime == "textblock":
            item = TextBlockItem("Notiz …")
            item.setPos(pos - QPointF(90, 35))
            self.scene().addItem(item)
        event.acceptProposedAction()


# ══════════════════════════════════════════════════════════════════════════════
#  PALETTE
# ══════════════════════════════════════════════════════════════════════════════

class Palette(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self.setStyleSheet("background: #1E293B;")

        lo = QVBoxLayout(self)
        lo.setContentsMargins(8, 12, 8, 12)
        lo.setSpacing(6)

        title = QLabel("BAUSTEINE")
        title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        title.setStyleSheet("color:#64748B; letter-spacing:2px;")
        lo.addWidget(title)

        # Station-Einträge
        self.list_widget = QListWidget()
        self.list_widget.setDragEnabled(True)
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.setStyleSheet("""
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
        self.list_widget.setSpacing(2)

        self._items: list[tuple[str, str | None]] = []  # (label, color_hex | None)
        for hex_col, label in PALETTE_COLORS:
            li = QListWidgetItem(label)
            li.setData(Qt.UserRole, f"station:{hex_col}")
            c = QColor(hex_col)
            pix = QPixmap(14, 14)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QBrush(c))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(1, 1, 12, 12, 3, 3)
            p.end()
            li.setIcon(QIcon(pix))
            self.list_widget.addItem(li)

        # Textblock
        li_txt = QListWidgetItem("📝  Textblock")
        li_txt.setData(Qt.UserRole, "textblock")
        self.list_widget.addItem(li_txt)

        lo.addWidget(self.list_widget)

        # Hinweise
        hints = QLabel(
            "Drag & Drop auf die Fläche\n\n"
            "Verbinden:\nAus-Port (blau) → Ein-Port (grün)\n\n"
            "Doppelklick = bearbeiten\nEntf = löschen\n"
            "Scroll = zoom\n\n"
            "Linienfarbe:\n"
            "🟢 alle Pfade gültig\n"
            "🔴 mind. ein Pfad ungültig\n"
            "⚫ ungeprüft"
        )
        hints.setFont(QFont("Segoe UI", 8))
        hints.setStyleSheet("color:#475569; padding:6px 2px;")
        hints.setWordWrap(True)
        lo.addWidget(hints)
        lo.addStretch()

        # Drag-Override
        self.list_widget.startDrag = self._start_drag

    def _start_drag(self, actions):
        item = self.list_widget.currentItem()
        if not item:
            return
        mime_str = item.data(Qt.UserRole)

        drag = QDrag(self.list_widget)
        mime = QMimeData()
        mime.setText(mime_str)
        drag.setMimeData(mime)

        pix = QPixmap(130, 36)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)

        if mime_str.startswith("station:"):
            col = QColor(mime_str.split(":", 1)[1])
            grad = QLinearGradient(0, 0, 130, 0)
            grad.setColorAt(0, col.lighter(120))
            grad.setColorAt(1, col)
            p.setBrush(QBrush(grad))
            p.setPen(QPen(col.darker(150), 1))
            p.drawRoundedRect(1, 1, 128, 34, 8, 8)
            p.setPen(Qt.white)
            p.setFont(QFont("Segoe UI", 8, QFont.Bold))
            p.drawText(QRect(0, 0, 130, 36), Qt.AlignCenter, "Station")
        else:
            p.setBrush(QBrush(QColor(255, 252, 220, 230)))
            p.setPen(QPen(QColor("#D97706"), 1))
            p.drawRoundedRect(1, 1, 128, 34, 6, 6)
            p.setPen(QColor("#44200A"))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(QRect(0, 0, 130, 36), Qt.AlignCenter, "Textblock")
        p.end()

        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(65, 18))
        drag.exec_(Qt.CopyAction)


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
            ("Validieren",      "F5",            self.scene.validate_all),
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
        h.addWidget(self.palette)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #334155;")
        h.addWidget(sep)

        self.view = FlowView(self.scene)
        h.addWidget(self.view, 1)

    def _build_menu(self):
        mb = self.menuBar()

        fm = mb.addMenu("Datei")
        a = QAction("Neu", self, shortcut="Ctrl+N")
        a.triggered.connect(self._new)
        fm.addAction(a)

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

    def _fit_all(self):
        br = self.scene.itemsBoundingRect()
        if not br.isEmpty():
            self.view.fitInView(br.adjusted(-60, -60, 60, 60), Qt.KeepAspectRatio)

    def _zoom_reset(self):
        self.view.resetTransform()

    def _delete_selected(self):
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
        self.scene.keyPressEvent(ev)


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
