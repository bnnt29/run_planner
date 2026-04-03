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
import os
import time
import importlib.util
from pathlib import Path
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from threading import Event
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_SCALE_FACTOR"] = "1"
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QAbstractItemView,
    QGraphicsScene, QGraphicsView, QGraphicsItem, QGraphicsEllipseItem,
    QGraphicsPathItem, QGraphicsRectItem, QFrame, QDialog, QDialogButtonBox,
    QLineEdit, QComboBox, QGroupBox, QScrollArea, QPlainTextEdit,
    QAction, QMessageBox, QColorDialog, QSizePolicy, QToolBar, QMenu,
    QSpacerItem, QStatusBar, QFileDialog, QDoubleSpinBox, QRadioButton,
    QCheckBox, QSpinBox,
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
from enum import Enum

try:
    from .items import (
        PORT_R,
        STATION_W,
        STATION_H_MIN,
        HEADER_H,
        LINE_H,
        PORT_TYPE,
        Port,
        ObjectItem,
        STATION_TYPE,
        StationItem,
        AttributeItem,
        CONNECTION_STATE,
        CONNECTION_COLOR,
        ConnectionItem,
        CONDITION_OP,
        Condition,
        EFFECT_OP,
        Effect,
        StationRule,
        TextBlockItem,
    )
except ImportError:
    from items import (
        PORT_R,
        STATION_W,
        STATION_H_MIN,
        HEADER_H,
        LINE_H,
        PORT_TYPE,
        Port,
        ObjectItem,
        STATION_TYPE,
        StationItem,
        AttributeItem,
        CONNECTION_STATE,
        CONNECTION_COLOR,
        ConnectionItem,
        CONDITION_OP,
        Condition,
        EFFECT_OP,
        Effect,
        StationRule,
        TextBlockItem,
    )

try:
    from .validate import FlowScene as ValidationFlowScene
    from .validate import CONNECTION_KIND
except ImportError:
    from validate import FlowScene as ValidationFlowScene
    from validate import CONNECTION_KIND


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
QToolTip {
    background-color: #0F172A;
    color: #E2E8F0;
    border: 1px solid #475569;
    padding: 4px 6px;
}
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
        title_row.addWidget(title)
        title_row.addWidget(QLabel("Max. Traversierungen:"))
        self.max_traversals = QSpinBox()
        self.max_traversals.setRange(1, 1000)
        self.max_traversals.setValue(int(getattr(rule, "max_traversals", 20) or 20))
        self.max_traversals.setFixedWidth(88)
        self.max_traversals.setToolTip(
            "Wie oft diese Regel pro Pfadsegment bis zum nächsten Checkpoint maximal traversiert werden darf."
        )
        title_row.addWidget(self.max_traversals)
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setObjectName("del_btn")
        self.remove_btn.setFixedSize(22, 22)
        self.remove_btn.clicked.connect(lambda: self.removed.emit(self))
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
            max_traversals=self.max_traversals.value(),
            rule_id=getattr(self._rule, "rule_id", None),
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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            main_window = self.window()
            if main_window is not None and hasattr(main_window, "deselect_everything"):
                main_window.deselect_everything()
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)
        
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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            main_window = self.window()
            if main_window is not None and hasattr(main_window, "deselect_everything"):
                main_window.deselect_everything()
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)


# ══════════════════════════════════════════════════════════════════════════════
#  SZENE
# ══════════════════════════════════════════════════════════════════════════════

class FlowScene(ValidationFlowScene):
    status_message = pyqtSignal(str)
    validation_debug = pyqtSignal(str)
    validation_result_ready = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self._connections: list[ConnectionItem] = []
        self._wip_conn:    ConnectionItem | None = None
        self._wip_src:     Port | None           = None
        self.palette_widget = None
        self._validation_executor = ThreadPoolExecutor(max_workers=1)
        self._validation_future = None
        self._validation_generation = 0
        self._queued_validation = None
        self._validation_meta = {}
        self._validation_cancel_event = None
        self.auto_validate_enabled = True
        self._validation_cache_best_states = {}
        self._validation_cache_checkpoint_levels = {}
        self.validation_result_ready.connect(self._apply_validation_result)

        self.show_connection_hitboxes = False
        self.show_attribute_connections = True
    def set_palette(self, palette_widget):
        self.palette_widget = palette_widget

    def _set_connection_interactive(self, conn: ConnectionItem, interactive: bool):
        if conn is None:
            return
        conn.setFlag(QGraphicsItem.ItemIsSelectable, interactive)
        conn.setAcceptedMouseButtons(Qt.AllButtons if interactive else Qt.NoButton)
        if not interactive and conn.isSelected():
            conn.setSelected(False)

    def apply_connection_hitbox_mode(self):
        interactive = not self.show_connection_hitboxes
        for conn in self._connections:
            self._set_connection_interactive(conn, interactive)

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
        self.validate_all(changed_targets=[item])

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
                self._set_connection_interactive(self._wip_conn, not self.show_connection_hitboxes)
                src_item = self._wip_src.parentItem()
                dst_item = target_port.parentItem()
                if hasattr(src_item, "_layout"):
                    self.update_connections_for(src_item)
                if hasattr(dst_item, "_layout") and dst_item is not src_item:
                    self.update_connections_for(dst_item)
                self.validate_all(changed_targets=[src_item, dst_item, self._wip_conn])
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
            deleted_items = list(self.selectedItems())
            for item in deleted_items:
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
            self.validate_all(changed_targets=deleted_items)
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
        self.validate_all(changed_targets=[src_item, dst_item, conn])

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
        touched_connections = []

        for conn in self._connections:
            if self._connection_kind(conn) != CONNECTION_KIND.FLOW:
                continue
            old_conn_count = len(conn.conditions)
            conn.conditions = [
                cond for cond in conn.conditions
                if self._attribute_name_key(getattr(getattr(cond, "attribute", None), "name", "")) != name_key
            ]
            delta = old_conn_count - len(conn.conditions)
            removed += delta
            if delta > 0:
                touched_connections.append(conn)

        if removed > 0:
            self.validate_all(changed_targets=touched_connections)

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
            self.validate_all(changed_targets=[item])

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
            self.validate_all(changed_targets=[item])
            break

    def open_connection_editor(self, conn: ConnectionItem):
        parent = self.views()[0] if self.views() else None
        previous_conditions = [Condition(c.attribute, c.operator, c.value) for c in conn.conditions]
        dlg    = ConnectionDialog(conn, self._attribute_items(), parent)

        def _preview_validate():
            conn.conditions = dlg.result_data()
            conn.update()
            self.validate_all(changed_targets=[conn])

        dlg.conditions_changed.connect(_preview_validate)
        if dlg.exec_() == QDialog.Accepted:
            conn.conditions = dlg.result_data()
            conn.update()
            self.validate_all(changed_targets=[conn])
        else:
            conn.conditions = previous_conditions
            conn.update()
            self.validate_all(changed_targets=[conn])

    def open_text_editor(self, item: TextBlockItem):
        parent = self.views()[0] if self.views() else None
        dlg    = TextDialog(item, parent)
        if dlg.exec_() == QDialog.Accepted:
            item._text = dlg.get_text()
            item._recalc_height()
            item.update()

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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            main_window = self.window()
            if main_window is not None and hasattr(main_window, "handle_escape_action"):
                main_window.handle_escape_action()
                event.accept()
                return
        super().keyPressEvent(event)

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
                scene.validate_all(changed_targets=[item])
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
            if not conn._state == CONNECTION_STATE.ATTRIBUTE:
                reasons = ["Dieser Pfeil ist ungültig, es wurde jedoch keine Detailursache gefunden."]
            else:
                reasons = ["Dieser Pfeil ist gültig, befindet sich jedoch auf keinem Traversierungspfad."]
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
        self.scene_widget.validate_all(changed_targets=[item])
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
QToolBar QToolButton#validation_btn[validationBusy="true"] {
    background: #7C2D12;
    border-color: #EA580C;
    color: #FDBA74;
}
QToolBar QToolButton#validation_btn[validationBusy="true"]:disabled {
    background: #7C2D12;
    border-color: #EA580C;
    color: #FDBA74;
}
QStatusBar {
    background: #1E293B;
    color: #64748B;
    font-size: 11px;
    border-top: 1px solid #334155;
}
QToolTip {
    background-color: #0F172A;
    color: #E2E8F0;
    border: 1px solid #475569;
    padding: 4px 6px;
}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ablaufplan-Editor")
        self.resize(1400, 840)
        self.setStyleSheet(APP_STYLE)

        self.scene = FlowScene()
        self._auto_validation_actions = []
        self._validation_actions = []
        self._validation_toolbar_action = None
        self._validation_toolbar_button = None
        self._validation_running = False
        self._validation_pending = False
        self._validation_debug_actions = []
        self._validation_debug_enabled = False
        self._validation_debug_label = None
        self._show_connection_hitboxes_actions = []
        self._show_connection_hitboxes = False
        self._show_attribute_connections_actions = []
        self._show_attribute_connections = True
        self.scene.status_message.connect(self._set_status)
        self.scene.validation_debug.connect(self._set_validation_debug)
        self.scene.validation_state_changed.connect(self._set_validation_action_state)
        self.scene.selectionChanged.connect(self._on_scene_selection_changed)

        self._build_toolbar()
        self._build_central()
        self._build_menu()
        self._build_statusbar()
        self._set_validation_action_state(False, False)
        self._create_start_configuration()

    # ── UI-Aufbau ─────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = self.addToolBar("Werkzeuge")
        tb.setMovable(False)
        validation_action = None

        for text, shortcut, slot in [
            ("Neu",             "Ctrl+N",        self._new),
            ("Laden (JSON)",    "Ctrl+O",        self._import_json),
            ("Speichern (JSON)","Ctrl+S",        self._export_json),
            ("Station",         "Ctrl+1",        self._new_station),
            ("Attribut",        "Ctrl+2",        self._new_attribute),
            ("Validieren",      "F5",            self._trigger_validation),
            ("Als PDF exportieren", "Ctrl+P",     self._export_pdf),
            ("Alles einpassen", "Ctrl+Shift+F",  self._fit_all),
            ("Zoom 100%",       "Ctrl+0",        self._zoom_reset),
        ]:
            btn = QAction(text, self)
            btn.setShortcut(shortcut)
            btn.triggered.connect(slot)
            tb.addAction(btn)
            if text == "Validieren":
                validation_action = btn

        self._validation_toolbar_action = validation_action
        if validation_action is not None:
            self._validation_actions.append(validation_action)
            self._validation_toolbar_button = tb.widgetForAction(validation_action)
            if self._validation_toolbar_button is not None:
                self._validation_toolbar_button.setObjectName("validation_btn")
                self._validation_toolbar_button.setProperty("validationBusy", False)
                self._validation_toolbar_button.style().unpolish(self._validation_toolbar_button)
                self._validation_toolbar_button.style().polish(self._validation_toolbar_button)
                self._validation_toolbar_button.update()

        tb.addSeparator()
        auto_validate_switch = QCheckBox("Auto-Validierung")
        auto_validate_switch.setChecked(self.scene.auto_validate_enabled)
        auto_validate_switch.toggled.connect(self._set_auto_validation)
        auto_validate_switch.setStyleSheet(
            """
            QCheckBox {
                color: #E2E8F0;
                spacing: 8px;
                font-size: 12px;
            }
            QCheckBox::indicator {
                width: 34px;
                height: 18px;
                border-radius: 9px;
                background: #475569;
                border: 1px solid #334155;
            }
            QCheckBox::indicator:checked {
                background: #22C55E;
                border: 1px solid #16A34A;
            }
            """
        )
        tb.addWidget(auto_validate_switch)
        self._auto_validation_actions.append(auto_validate_switch)

        validation_debug_switch = QCheckBox("Validierungs-Debug")
        validation_debug_switch.setChecked(self._validation_debug_enabled)
        validation_debug_switch.toggled.connect(self._set_validation_debug_enabled)
        validation_debug_switch.setStyleSheet(
            """
            QCheckBox {
                color: #E2E8F0;
                spacing: 8px;
                font-size: 12px;
            }
            QCheckBox::indicator {
                width: 34px;
                height: 18px;
                border-radius: 9px;
                background: #475569;
                border: 1px solid #334155;
            }
            QCheckBox::indicator:checked {
                background: #22C55E;
                border: 1px solid #16A34A;
            }
            """
        )
        tb.addWidget(validation_debug_switch)
        self._validation_debug_actions.append(validation_debug_switch)

        connection_hitboxes_switch = QCheckBox("Verbindungs-Hitboxes deaktivieren")
        connection_hitboxes_switch.setChecked(self._show_connection_hitboxes)
        connection_hitboxes_switch.toggled.connect(self._set_show_connection_hitboxes)
        connection_hitboxes_switch.setStyleSheet(
            """
            QCheckBox {
                color: #E2E8F0;
                spacing: 8px;
                font-size: 12px;
            }
            QCheckBox::indicator {
                width: 34px;
                height: 18px;
                border-radius: 9px;
                background: #475569;
                border: 1px solid #334155;
            }
            QCheckBox::indicator:checked {
                background: #22C55E;
                border: 1px solid #16A34A;
            }
            """
        )
        tb.addWidget(connection_hitboxes_switch)
        self._show_connection_hitboxes_actions.append(connection_hitboxes_switch)

        attribute_connections_switch = QCheckBox("ATTRIBUTE-Verbindungen")
        attribute_connections_switch.setChecked(self._show_attribute_connections)
        attribute_connections_switch.toggled.connect(self._set_show_attribute_connections)
        attribute_connections_switch.setStyleSheet(
            """
            QCheckBox {
                color: #E2E8F0;
                spacing: 8px;
                font-size: 12px;
            }
            QCheckBox::indicator {
                width: 34px;
                height: 18px;
                border-radius: 9px;
                background: #475569;
                border: 1px solid #334155;
            }
            QCheckBox::indicator:checked {
                background: #22C55E;
                border: 1px solid #16A34A;
            }
            """
        )
        tb.addWidget(attribute_connections_switch)
        self._show_attribute_connections_actions.append(attribute_connections_switch)

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
        val_act.triggered.connect(self._trigger_validation)
        em.addAction(val_act)
        self._validation_actions.append(val_act)

        em.addSeparator()
        
        auto_validate_act = QAction("Auto-Validierung", self)
        auto_validate_act.setCheckable(True)
        auto_validate_act.setChecked(self.scene.auto_validate_enabled)
        auto_validate_act.toggled.connect(self._set_auto_validation)
        em.addAction(auto_validate_act)
        self._auto_validation_actions.append(auto_validate_act)

        debug_act = QAction("Validierungs-Debug anzeigen", self)
        debug_act.setCheckable(True)
        debug_act.setChecked(self._validation_debug_enabled)
        debug_act.toggled.connect(self._set_validation_debug_enabled)
        em.addAction(debug_act)
        self._validation_debug_actions.append(debug_act)

        em.addSeparator()

        hitbox_act = QAction("Verbindungs-Hitboxes deaktivieren", self)
        hitbox_act.setCheckable(True)
        hitbox_act.setChecked(self._show_connection_hitboxes)
        hitbox_act.toggled.connect(self._set_show_connection_hitboxes)
        em.addAction(hitbox_act)
        self._show_connection_hitboxes_actions.append(hitbox_act)

        attr_conn_act = QAction("ATTRIBUTE-Verbindungen anzeigen", self)
        attr_conn_act.setCheckable(True)
        attr_conn_act.setChecked(self._show_attribute_connections)
        attr_conn_act.toggled.connect(self._set_show_attribute_connections)
        em.addAction(attr_conn_act)
        self._show_attribute_connections_actions.append(attr_conn_act)

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage(
            "Bausteine per Drag & Drop auf die Fläche ziehen  –  "
            "Doppelklick auf Station zum Bearbeiten"
        )
        self._validation_debug_label = QLabel("")
        self._validation_debug_label.setStyleSheet("color:#94A3B8; font-size:10px; padding-right:6px;")
        self._validation_debug_label.setVisible(self._validation_debug_enabled)
        sb.addPermanentWidget(self._validation_debug_label)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        self.statusBar().showMessage(msg)

    def _set_auto_validation(self, enabled: bool):
        self.scene.auto_validate_enabled = enabled
        for action in self._auto_validation_actions:
            if action.isChecked() != enabled:
                action.blockSignals(True)
                action.setChecked(enabled)
                action.blockSignals(False)
        self.statusBar().showMessage(
            "Auto-Validierung aktiviert" if enabled else "Auto-Validierung deaktiviert (F5 für manuelle Validierung)"
        )

    def _set_validation_debug_enabled(self, enabled: bool):
        self._validation_debug_enabled = enabled
        for action in self._validation_debug_actions:
            if action.isChecked() != enabled:
                action.blockSignals(True)
                action.setChecked(enabled)
                action.blockSignals(False)
        if self._validation_debug_label is not None:
            self._validation_debug_label.setVisible(enabled)
            if not enabled:
                self._validation_debug_label.clear()

    def _set_validation_debug(self, msg: str):
        if self._validation_debug_label is None or not self._validation_debug_enabled:
            return
        self._validation_debug_label.setText(msg)

    def _trigger_validation(self):
        if self._validation_running or self._validation_pending:
            self.scene.cancel_validation()
            return
        self.scene.validate_all(force=True)

    def _set_validation_action_state(self, running: bool, pending: bool):
        self._validation_running = running
        self._validation_pending = pending
        busy = running or pending

        if self._validation_toolbar_button is not None:
            self._validation_toolbar_button.setProperty("validationBusy", busy)
            self._validation_toolbar_button.style().unpolish(self._validation_toolbar_button)
            self._validation_toolbar_button.style().polish(self._validation_toolbar_button)
            self._validation_toolbar_button.update()

        if busy:
            self.statusBar().showMessage(
                "Validierung läuft ..." if running else "Validierung ist eingeplant ..."
            )

    def _set_show_connection_hitboxes(self, enabled: bool):
        self._show_connection_hitboxes = enabled
        self.scene.show_connection_hitboxes = enabled
        for action in self._show_connection_hitboxes_actions:
            if action.isChecked() != enabled:
                action.blockSignals(True)
                action.setChecked(enabled)
                action.blockSignals(False)
        self.scene.apply_connection_hitbox_mode()
        self.view.viewport().update()
        self.statusBar().showMessage(
            "Verbindungs-Hitboxes deaktiviert" if enabled else "Verbindungs-Hitboxes aktiviert"
        )

    def _set_show_attribute_connections(self, enabled: bool):
        self._show_attribute_connections = enabled
        self.scene.show_attribute_connections = enabled
        for action in self._show_attribute_connections_actions:
            if action.isChecked() != enabled:
                action.blockSignals(True)
                action.setChecked(enabled)
                action.blockSignals(False)
        # Update visibility of all attribute connections
        for conn in self.scene._connections:
            if conn._state == CONNECTION_STATE.ATTRIBUTE:
                conn.setVisible(enabled)
        self.view.viewport().update()
        self.statusBar().showMessage(
            "ATTRIBUTE-Verbindungen angezeigt" if enabled else "ATTRIBUTE-Verbindungen verborgen"
        )


    def _new(self):
        if QMessageBox.question(
            self, "Neues Diagramm",
            "Alle Elemente verwerfen und neu beginnen?",
            QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            self.scene.clear_all()
            self.palette.reset_templates()
            self._create_start_configuration()

    def _connect_ports(self, src_port: Port, dst_port: Port) -> ConnectionItem:
        conn = ConnectionItem(src_port)
        conn.finalize(dst_port)
        src_port.connections.append(conn)
        dst_port.connections.append(conn)
        self.scene._connections.append(conn)
        self.scene.addItem(conn)
        self.scene._set_connection_interactive(conn, not self.scene.show_connection_hitboxes)
        return conn

    def _create_start_configuration(self):
        start_station = StationItem("Start", type=STATION_TYPE.START)
        end_station = StationItem("Ende", type=STATION_TYPE.END)
        attribute = AttributeItem("Attribut")

        self.scene.addItem(start_station)
        self.scene.addItem(end_station)
        self.scene.addItem(attribute)

        start_station.setPos(-260, -40)
        end_station.setPos(220, -40)
        attribute.setPos(-20, -220)

        self.scene._register_template(start_station)
        self.scene._register_template(end_station)
        self.scene._register_template(attribute)

        self._connect_ports(start_station.out_port, end_station.in_port)
        self._connect_ports(attribute.out_port, start_station.attr_port)
        self._connect_ports(attribute.out_port, end_station.attr_port)

        self.scene.update_connections_for(start_station)
        self.scene.update_connections_for(end_station)
        self.scene.update_connections_for(attribute)
        self.scene.clearSelection()
        self.scene.validate_all(changed_targets=[start_station, end_station, attribute])
        self._fit_all()

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
        self.scene.validate_all(changed_targets=[item])

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
        selected_stations = [item for item in selected if isinstance(item, StationItem)]
        highlighted_connections = set()
        for station in selected_stations:
            highlighted_connections.update(station.all_connections())
        for conn in self.scene._connections:
            conn.set_highlighted(conn in highlighted_connections)

        if invalid_conn is not None:
            self.palette.show_invalid_connection_help(invalid_conn)
        else:
            self.palette.show_default_help()

    def deselect_everything(self):
        self.scene.clearSelection()
        self.palette.station_list.clearSelection()
        self.palette.attribute_list.clearSelection()
        self.palette.show_default_help()

    def handle_escape_action(self):
        for widget in QApplication.topLevelWidgets():
            if not isinstance(widget, QDialog):
                continue
            if not widget.isVisible() or widget is self:
                continue
            widget.reject()
        self.deselect_everything()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.handle_escape_action()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.scene.cancel_validation()
        super().closeEvent(event)

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
        import run_planner.json_helper as json_helpers
        return json_helpers.export_json(self)

    def _import_json(self):
        import run_planner.json_helper as json_helpers
        return json_helpers.import_json(self)

    def _export_pdf(self):
        import run_planner.pdf_helper as pdf_helpers
        return pdf_helpers.export_pdf(self)

    def _paint_pdf_editor_page(self, painter: QPainter, printer: QPrinter):
        import run_planner.pdf_helper as pdf_helpers
        return pdf_helpers.paint_pdf_editor_page(self, painter, printer)

    def _paint_pdf_flow_page(self, painter: QPainter, printer: QPrinter):
        import run_planner.pdf_helper as pdf_helpers
        return pdf_helpers.paint_pdf_flow_page(self, painter, printer)

    def _paint_pdf_clean_flow_page(self, painter: QPainter, printer: QPrinter):
        import run_planner.pdf_helper as pdf_helpers
        return pdf_helpers.paint_pdf_clean_flow_page(self, painter, printer)
