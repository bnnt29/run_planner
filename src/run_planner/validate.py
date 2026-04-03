"""Validation scene logic extracted from the editor UI.

This module is kept independent so the scene validation can be reused
without importing the full UI module.
"""

import math
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from PyQt5.QtCore import *  # noqa: F401,F403
from PyQt5.QtGui import *  # noqa: F401,F403
from PyQt5.QtPrintSupport import *  # noqa: F401,F403
from PyQt5.QtWidgets import *  # noqa: F401,F403

try:
    from .items import *  # noqa: F401,F403
except ImportError:
    from items import *  # type: ignore # noqa: F401,F403

# ══════════════════════════════════════════════════════════════════════════════
#  SZENE
# ══════════════════════════════════════════════════════════════════════════════

class CONNECTION_KIND(Enum):
    FLOW = True,
    ATTRIBUTE = False
    
class FlowScene(QGraphicsScene):
    status_message = pyqtSignal(str)
    validation_debug = pyqtSignal(str)
    validation_result_ready = pyqtSignal(int, object)
    validation_state_changed = pyqtSignal(bool, bool)

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
        self.validation_profiling_enabled = False
        self._validation_cache_best_states = {}
        self._validation_cache_checkpoint_levels = {}
        self.validation_result_ready.connect(self._apply_validation_result)

    def _emit_validation_state(self):
        running = self._validation_future is not None and not self._validation_future.done()
        pending = self._queued_validation is not None
        self.validation_state_changed.emit(running, pending)

    def set_palette(self, palette_widget):
        self.palette_widget = palette_widget

    def set_validation_profiling_enabled(self, enabled: bool):
        self.validation_profiling_enabled = bool(enabled)

    def cancel_validation(self):
        if self._queued_validation is not None:
            self._queued_validation = None
        if self._validation_cancel_event is not None:
            self._validation_cancel_event.set()
        self.status_message.emit("Validierung wird abgebrochen ...")
        self._emit_validation_state()

    def _register_template(self, item):
        if self.palette_widget and hasattr(self.palette_widget, "register_item"):
            self.palette_widget.register_item(item)

    @staticmethod
    def _is_station(item) -> bool:
        return isinstance(item, StationItem)

    @staticmethod
    def _is_attribute(item) -> bool:
        return isinstance(item, AttributeItem)

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
        try:
            from .ui import StationDialog
        except ImportError:
            from ui import StationDialog  # type: ignore
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
        try:
            from .ui import AttributeDialog
        except ImportError:
            from ui import AttributeDialog  # type: ignore
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
        try:
            from .ui import ConnectionDialog
        except ImportError:
            from ui import ConnectionDialog  # type: ignore
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
        try:
            from .ui import TextDialog
        except ImportError:
            from ui import TextDialog  # type: ignore
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

    @staticmethod
    def _snapshot_condition(cond: Condition) -> dict:
        attr = getattr(cond, "attribute", None)
        attr_name = getattr(attr, "name", str(attr)) if attr is not None else ""
        return {
            "attr_id": getattr(attr, "node_id", None),
            "attr_name": attr_name,
            "op": cond.operator.value if isinstance(cond.operator, CONDITION_OP) else str(cond.operator),
            "value": float(getattr(cond, "value", 0.0)),
        }

    @staticmethod
    def _snapshot_effect(eff: Effect) -> dict:
        attr = getattr(eff, "attribute", None)
        return {
            "attr_id": getattr(attr, "node_id", None),
            "action": eff.action.value if isinstance(eff.action, EFFECT_OP) else str(eff.action),
            "value": float(getattr(eff, "value", 0.0)),
        }

    @staticmethod
    def _snapshot_cond_text(cond: dict) -> str:
        name = cond.get("attr_name", "")
        op = cond.get("op", CONDITION_OP.EXISTS.value)
        value = cond.get("value", 0.0)
        prefix = f"⟨{name}⟩"
        if op == CONDITION_OP.EXISTS.value:
            return f"{prefix} vorhanden"
        if op == CONDITION_OP.NOT_EXISTS.value:
            return f"{prefix} fehlt"
        return f"{prefix} {op} {value}"

    @staticmethod
    def _snapshot_check_condition(cond: dict, state: dict) -> bool:
        attr_id = cond.get("attr_id")
        op = cond.get("op", CONDITION_OP.EXISTS.value)
        value = float(cond.get("value", 0.0))
        count = 0.0 if attr_id is None or attr_id not in state or state[attr_id] is None else state[attr_id]

        if op == CONDITION_OP.EXISTS.value:
            return count > 0
        if op == CONDITION_OP.NOT_EXISTS.value:
            return count == 0
        if op == CONDITION_OP.EQUALS.value:
            return count == value
        if op == CONDITION_OP.NOT_EQUALS.value:
            return count != value
        if op == CONDITION_OP.GREATER.value:
            return count > value
        if op == CONDITION_OP.GREATER_EQ.value:
            return count >= value
        if op == CONDITION_OP.LESS.value:
            return count < value
        if op == CONDITION_OP.LESS_EQ.value:
            return count <= value
        return False

    @staticmethod
    def _snapshot_apply_effects(state: dict, effects: list[dict]) -> dict:
        out = dict(state)
        for eff in effects:
            attr_id = eff.get("attr_id")
            if attr_id is None:
                continue
            action = eff.get("action", EFFECT_OP.SET.value)
            value = float(eff.get("value", 0.0))
            present = attr_id in out and out[attr_id] not in (None, 0)

            if action == EFFECT_OP.ADD.value:
                out[attr_id] = value if not present else out[attr_id] + value
            elif action == EFFECT_OP.SUBTRACT.value:
                out[attr_id] = -value if not present else out[attr_id] - value
            elif action == EFFECT_OP.MULTIPLY.value:
                out[attr_id] = value if not present else out[attr_id] * value
            elif action == EFFECT_OP.DIVIDE.value:
                out[attr_id] = (1 / value) if not present else out[attr_id] / value
            elif action == EFFECT_OP.MOD.value:
                out[attr_id] = (1 % value) if not present else out[attr_id] % value
            else:
                out[attr_id] = value
        return out

    def _build_validation_snapshot(self, changed_targets=None):
        stations = self._station_items()
        if not stations:
            return None, None

        conn_lookup = {id(conn): conn for conn in self._connections}
        connection_kinds = {}
        station_lookup = {station.node_id: station for station in stations}

        station_data = {}
        root_ids = []
        checkpoint_ids = set()
        for station in stations:
            rules = []
            for rule in station.rules:
                rules.append({
                    "conditions": [self._snapshot_condition(cond) for cond in rule.conditions],
                    "effects": [self._snapshot_effect(eff) for eff in rule.effects],
                    "max_traversals": min(1000, max(1, int(getattr(rule, "max_traversals", 20) or 20))),
                    "rule_id": getattr(rule, "rule_id", None),
                })
            station_data[station.node_id] = {
                "id": station.node_id,
                "name": station.name,
                "type": station.type.value if isinstance(station.type, STATION_TYPE) else int(station.type),
                "rules": rules,
            }
            if station.type == STATION_TYPE.START:
                root_ids.append(station.node_id)
            if station.type == STATION_TYPE.END:
                checkpoint_ids.add(station.node_id)

        flow_succs = {sid: [] for sid in station_data.keys()}
        flow_conn_conditions = {}
        flow_conn_keys = []
        flow_conn_srcdst = {}
        attribute_conn_keys = []
        invalid_conn_keys = []

        for conn in self._connections:
            key = id(conn)
            kind = self._connection_kind(conn)
            connection_kinds[key] = kind
            if kind == CONNECTION_KIND.ATTRIBUTE:
                attribute_conn_keys.append(key)
                continue
            if kind != CONNECTION_KIND.FLOW:
                invalid_conn_keys.append(key)
                continue

            src = conn.src_port.parentItem() if conn.src_port else None
            dst = conn.dst_port.parentItem() if conn.dst_port else None
            if not isinstance(src, StationItem) or not isinstance(dst, StationItem):
                invalid_conn_keys.append(key)
                continue

            if src.node_id not in flow_succs:
                flow_succs[src.node_id] = []
            flow_succs[src.node_id].append((key, dst.node_id))
            flow_conn_srcdst[key] = (src.node_id, dst.node_id)
            flow_conn_conditions[key] = [self._snapshot_condition(cond) for cond in conn.conditions]
            flow_conn_keys.append(key)

        changed_station_ids = set()
        changed_conn_keys = set()
        for target in changed_targets or []:
            if isinstance(target, StationItem):
                changed_station_ids.add(target.node_id)
            elif isinstance(target, ConnectionItem):
                changed_conn_keys.add(id(target))
                src = target.src_port.parentItem() if target.src_port else None
                dst = target.dst_port.parentItem() if target.dst_port else None
                if isinstance(src, StationItem):
                    changed_station_ids.add(src.node_id)
                if isinstance(dst, StationItem):
                    changed_station_ids.add(dst.node_id)
            elif isinstance(target, AttributeItem):
                for conn in target.out_port.connections:
                    if self._connection_kind(conn) != CONNECTION_KIND.ATTRIBUTE:
                        continue
                    dst = conn.dst_port.parentItem() if conn.dst_port else None
                    if isinstance(dst, StationItem):
                        changed_station_ids.add(dst.node_id)

        if not self._validation_cache_best_states or (not changed_station_ids and not changed_conn_keys):
            target_conn_keys = set(flow_conn_keys)
            target_checkpoint_ids = set(checkpoint_ids)
        else:
            affected_nodes = set(changed_station_ids)
            queue = deque(changed_station_ids)
            while queue:
                node_id = queue.popleft()
                for _, succ_id in flow_succs.get(node_id, []):
                    if succ_id not in affected_nodes:
                        affected_nodes.add(succ_id)
                        queue.append(succ_id)

            for conn_key in changed_conn_keys:
                srcdst = flow_conn_srcdst.get(conn_key)
                if srcdst is None:
                    continue
                src_id, dst_id = srcdst
                affected_nodes.add(src_id)
                affected_nodes.add(dst_id)

            target_conn_keys = {
                conn_key
                for conn_key, (src_id, dst_id) in flow_conn_srcdst.items()
                if src_id in affected_nodes or dst_id in affected_nodes
            }
            target_checkpoint_ids = {sid for sid in checkpoint_ids if sid in affected_nodes}

        snapshot = {
            "station_data": station_data,
            "root_ids": root_ids,
            "checkpoint_ids": checkpoint_ids,
            "flow_succs": flow_succs,
            "flow_conn_conditions": flow_conn_conditions,
            "flow_conn_keys": flow_conn_keys,
            "target_conn_keys": list(target_conn_keys),
            "target_checkpoint_ids": list(target_checkpoint_ids),
            "attribute_conn_keys": attribute_conn_keys,
            "invalid_conn_keys": invalid_conn_keys,
            "connection_kinds": connection_kinds,
            "max_depth": max(5, len(self._connections) * max(5, len(stations))),
        }
        return snapshot, {"conn_lookup": conn_lookup, "station_lookup": station_lookup}

    def _compute_validation_snapshot(self, snapshot: dict, cancel_event: Event, generation: int):
        started = time.perf_counter()
        profile_enabled = bool(getattr(self, "validation_profiling_enabled", False))
        station_data = snapshot["station_data"]
        root_ids = snapshot["root_ids"]
        checkpoint_ids = snapshot["checkpoint_ids"]
        flow_succs = snapshot["flow_succs"]
        flow_conn_conditions = snapshot["flow_conn_conditions"]
        target_conn_keys = set(snapshot.get("target_conn_keys", snapshot["flow_conn_keys"]))
        target_checkpoint_ids = set(snapshot.get("target_checkpoint_ids", snapshot["checkpoint_ids"]))
        total_flow_conn_keys = set(snapshot["flow_conn_keys"])
        max_depth = snapshot["max_depth"]
        station_rules_by_id = {station_id: data.get("rules", []) for station_id, data in station_data.items()}

        profile = {
            "state_signatures": 0,
            "count_signatures": 0,
            "condition_hits": 0,
            "condition_misses": 0,
            "transition_hits": 0,
            "transition_misses": 0,
            "transition_hash_collisions": 0,
            "apply_hits": 0,
            "apply_misses": 0,
            "dfs_calls": 0,
            "dfs_pruned": 0,
            "dominance_pruned": 0,
            "reason_materializations": 0,
            "t_state_signature_ms": 0,
            "t_count_signature_ms": 0,
            "t_condition_eval_ms": 0,
            "t_transition_ms": 0,
            "t_apply_rule_ms": 0,
            "t_reason_materialize_ms": 0,
            "t_collect_states_ms": 0,
            "t_best_pick_ms": 0,
        }

        def build_metrics(cancelled: bool = False) -> dict:
            metrics = {
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "mode": "inkrementell" if target_conn_keys != total_flow_conn_keys else "voll",
                "target_flow": len(target_conn_keys),
                "total_flow": len(total_flow_conn_keys),
                "target_checkpoints": len(target_checkpoint_ids),
                "total_checkpoints": len(checkpoint_ids),
                "cancelled": cancelled,
            }
            if profile_enabled:
                profiling = {}
                for key, value in profile.items():
                    profiling[key] = round(value, 3) if key.startswith("t_") else value
                metrics["profiling"] = profiling
            return metrics

        def rule_key(station_id: str, rule: dict) -> str | None:
            key = rule.get("rule_id")
            if not key:
                return None
            return f"{station_id}:{key}"

        def state_signature(state: dict) -> tuple:
            ts = time.perf_counter()
            result = tuple(sorted(state.items()))
            profile["state_signatures"] += 1
            profile["t_state_signature_ms"] += (time.perf_counter() - ts) * 1000
            return result

        def counts_signature(active_rule_counts: dict[str, int]) -> tuple:
            ts = time.perf_counter()
            result = tuple(sorted(active_rule_counts.items()))
            profile["count_signatures"] += 1
            profile["t_count_signature_ms"] += (time.perf_counter() - ts) * 1000
            return result

        apply_rule_cache = {}

        def apply_station_rule(rule: dict, incoming_state: dict, incoming_signature: tuple | None = None) -> dict:
            rule_token = rule.get("rule_id") or id(rule)
            signature = incoming_signature if incoming_signature is not None else state_signature(incoming_state)
            cache_key = (rule_token, signature)
            cached = apply_rule_cache.get(cache_key)
            if cached is not None:
                profile["apply_hits"] += 1
                return cached

            profile["apply_misses"] += 1
            ts = time.perf_counter()
            out = dict(incoming_state)
            if all(check_condition_cached(cond, incoming_state) for cond in rule["conditions"]):
                out = self._snapshot_apply_effects(out, rule["effects"])
            apply_rule_cache[cache_key] = out
            profile["t_apply_rule_ms"] += (time.perf_counter() - ts) * 1000
            return out

        transition_cache = {}
        condition_eval_cache = {}

        def check_condition_cached(cond: dict, state: dict) -> bool:
            attr_id = cond.get("attr_id")
            op = cond.get("op", CONDITION_OP.EXISTS.value)
            cmp_value = float(cond.get("value", 0.0))
            if attr_id is None:
                count = 0.0
            else:
                raw = state.get(attr_id)
                count = 0.0 if raw is None else raw
            key = (attr_id, op, cmp_value, count)
            if key in condition_eval_cache:
                profile["condition_hits"] += 1
                return condition_eval_cache[key]
            profile["condition_misses"] += 1
            ts = time.perf_counter()
            result = self._snapshot_check_condition(cond, state)
            condition_eval_cache[key] = result
            profile["t_condition_eval_ms"] += (time.perf_counter() - ts) * 1000
            return result

        def materialize_reasons(reason_payload: dict) -> list[str]:
            ts = time.perf_counter()
            profile["reason_materializations"] += 1
            unmet_conn = reason_payload.get("unmet_conn", [])
            unmet_station = reason_payload.get("unmet_station", [])
            blocked_limit = bool(reason_payload.get("blocked_limit", False))
            if not unmet_conn and not unmet_station and not blocked_limit:
                profile["t_reason_materialize_ms"] += (time.perf_counter() - ts) * 1000
                return []

            state_map = dict(reason_payload.get("state_key", ()))
            station_name = reason_payload.get("station_name", "")
            max_traversals = int(reason_payload.get("max_traversals", 20) or 20)
            reasons = []

            if unmet_conn:
                conn_state_values = {
                    cond.get("attr_name", ""): state_map.get(cond.get("attr_id"))
                    for cond in unmet_conn
                }
                for cond in unmet_conn:
                    reasons.append(
                        f"Die Pfeil bedingung ist nicht erfüllt: {self._snapshot_cond_text(cond)} ({conn_state_values})"
                    )

            if unmet_station:
                station_state_values = {
                    cond.get("attr_name", ""): state_map.get(cond.get("attr_id"))
                    for cond in unmet_station
                }
                for cond in unmet_station:
                    reasons.append(
                        f"Die {station_name} bedingung ist nicht erfüllt: {self._snapshot_cond_text(cond)} ({station_state_values})"
                    )

            if blocked_limit:
                reasons.append(
                    f"Die {station_name} Regel hat das Traversierungs-Limit ({max_traversals}) seit dem letzten Checkpoint erreicht."
                )

            profile["t_reason_materialize_ms"] += (time.perf_counter() - ts) * 1000
            return reasons

        def transition_for(
            conn_key: int,
            station_id: str,
            station_name: str,
            rule: dict,
            incoming_state: dict,
            active_rule_counts: dict[str, int],
            incoming_signature: tuple | None = None,
            counts_key: tuple | None = None,
        ):
            rule_token = rule.get("rule_id") or id(rule)
            state_key = incoming_signature if incoming_signature is not None else state_signature(incoming_state)
            rule_counts_key = counts_key if counts_key is not None else counts_signature(active_rule_counts)
            cache_key = (conn_key, rule_token, state_key, hash(rule_counts_key))
            bucket = transition_cache.get(cache_key)
            if bucket is not None:
                for cached_counts_key, cached_result in bucket:
                    if cached_counts_key == rule_counts_key:
                        profile["transition_hits"] += 1
                        return cached_result
                profile["transition_hash_collisions"] += 1

            profile["transition_misses"] += 1
            ts = time.perf_counter()
            conn_conditions = flow_conn_conditions.get(conn_key, [])
            station_conditions = rule.get("conditions", [])
            unmet_conn = [
                cond for cond in conn_conditions
                if not check_condition_cached(cond, incoming_state)
            ]
            unmet_station = [
                cond for cond in station_conditions
                if not check_condition_cached(cond, incoming_state)
            ]
            key = rule_key(station_id, rule)
            max_traversals = min(1000, max(1, int(rule.get("max_traversals", 20) or 20)))
            current_count = 0 if key is None else active_rule_counts.get(key, 0)
            blocked_limit = bool(key is not None and current_count >= max_traversals)

            if not unmet_conn and not unmet_station and not blocked_limit:
                state = CONNECTION_STATE.VALID
            elif unmet_conn and not unmet_station:
                state = CONNECTION_STATE.CONDITIONAL_VALID
            elif not unmet_conn and unmet_station:
                state = CONNECTION_STATE.INVALID
            else:
                state = CONNECTION_STATE.CONDITIONAL_INVALID

            reason_payload = {
                "station_name": station_name,
                "unmet_conn": unmet_conn,
                "unmet_station": unmet_station,
                "blocked_limit": blocked_limit,
                "max_traversals": max_traversals,
                "state_key": state_key,
            }
            result = (state, reason_payload, blocked_limit, key)
            if bucket is None:
                transition_cache[cache_key] = [(rule_counts_key, result)]
            else:
                bucket.append((rule_counts_key, result))
            profile["t_transition_ms"] += (time.perf_counter() - ts) * 1000
            return result
        
        def collect_states (allow_conditional: bool):
            conn_states_valid = {conn_key: [] for conn_key in target_conn_keys}
            conn_states_conditional_valid = {conn_key: [] for conn_key in target_conn_keys}
            checkpoint_levels = {sid: set() for sid in target_checkpoint_ids}
            dominance_best = {}
            
            def state_level(state: CONNECTION_STATE) -> int:
                if state == CONNECTION_STATE.VALID:
                    return 0
                if state == CONNECTION_STATE.CONDITIONAL_VALID:
                    return 1
                return 2
            
            def dfs(
                station_id: str,
                incoming_state: dict,
                depth_left: int,
                level: int,
                reached_checkpoint: bool,
                active_rule_counts: dict[str, int],
                cache: set,
                conn_state_con_val:bool = False,
            ):
                profile["dfs_calls"] += 1
                at_checkpoint = reached_checkpoint or (station_id in checkpoint_ids)
                segment_rule_counts = {} if station_id in checkpoint_ids else active_rule_counts
                incoming_signature = state_signature(incoming_state)
                counts_key = counts_signature(segment_rule_counts)

                dominance_key = (station_id, at_checkpoint, incoming_signature, counts_key, conn_state_con_val)
                previous_best = dominance_best.get(dominance_key)
                if previous_best is not None:
                    best_depth, best_level = previous_best
                    if best_depth >= depth_left and best_level <= level:
                        profile["dominance_pruned"] += 1
                        return
                    dominance_best[dominance_key] = (max(best_depth, depth_left), min(best_level, level))
                else:
                    dominance_best[dominance_key] = (depth_left, level)

                cache_key = (station_id, depth_left, at_checkpoint, incoming_signature, counts_key)
                if cache_key in cache:
                    profile["dfs_pruned"] += 1
                    return
                cache.add(cache_key)

                if depth_left <= 0:
                    return

                for conn_key, succ_id in flow_succs.get(station_id, []):
                    succ = station_data.get(succ_id)
                    if succ is None:
                        continue

                    rules = station_rules_by_id.get(succ_id, [])
                    if not rules:
                        transition_state, reasons, _, _ = transition_for(
                            conn_key,
                            succ_id,
                            succ["name"],
                            {},
                            incoming_state,
                            segment_rule_counts,
                            incoming_signature,
                            counts_key,
                        )
                        state_cont = False
                        next_level = level
                        if transition_state in (CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID):
                            next_level = max(level, state_level(transition_state))
                            if succ_id in checkpoint_levels:
                                checkpoint_levels[succ_id].add(next_level)
                            state_cont = True
                        if conn_state_con_val:
                            if conn_key in conn_states_conditional_valid:
                                conn_states_conditional_valid[conn_key].append((transition_state, reasons))
                        else:
                            if conn_key in conn_states_valid:
                                conn_states_valid[conn_key].append((transition_state, reasons))
                        if transition_state == CONNECTION_STATE.VALID and not conn_state_con_val:
                            dfs(succ_id, incoming_state, depth_left - 1, next_level, at_checkpoint, segment_rule_counts, cache)
                        elif allow_conditional and transition_state == CONNECTION_STATE.CONDITIONAL_VALID and not conn_state_con_val:
                            conn_states_conditional_valid = conn_states_valid
                            dfs(succ_id, incoming_state, depth_left - 1, next_level, at_checkpoint, segment_rule_counts, cache, True)
                        elif conn_state_con_val:
                            dfs(succ_id, incoming_state, depth_left - 1, next_level, at_checkpoint, segment_rule_counts, cache, True)
                        elif state_cont:
                            dfs(succ_id, incoming_state, depth_left - 1, next_level, at_checkpoint, segment_rule_counts, cache)

                    for rule in rules:
                        transition_state, reasons, blocked_limit, key = transition_for(
                            conn_key,
                            succ_id,
                            succ["name"],
                            rule,
                            incoming_state,
                            segment_rule_counts,
                            incoming_signature,
                            counts_key,
                        )
                        state_cont = False
                        next_level = level
                        if conn_state_con_val:
                            if conn_key in conn_states_conditional_valid:
                                conn_states_conditional_valid[conn_key].append((transition_state, reasons))
                        else:
                            if conn_key in conn_states_valid:
                                conn_states_valid[conn_key].append((transition_state, reasons))
                        if transition_state in (CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID):
                            next_level = max(level, state_level(transition_state))
                            if succ_id in checkpoint_levels:
                                checkpoint_levels[succ_id].add(next_level)
                            state_cont = True                            
                        if transition_state == CONNECTION_STATE.VALID and not conn_state_con_val:
                            current_state = apply_station_rule(rule, incoming_state, incoming_signature)
                            next_rule_counts = dict(segment_rule_counts)
                            if key and not blocked_limit:
                                next_rule_counts[key] = next_rule_counts.get(key, 0) + 1
                            dfs(succ_id, current_state, depth_left - 1, next_level, at_checkpoint, next_rule_counts, cache)
                        elif allow_conditional and transition_state == CONNECTION_STATE.CONDITIONAL_VALID and not conn_state_con_val:
                            conn_states_conditional_valid = conn_states_valid
                            current_state = apply_station_rule(rule, incoming_state, incoming_signature)
                            next_rule_counts = dict(segment_rule_counts)
                            if key and not blocked_limit:
                                next_rule_counts[key] = next_rule_counts.get(key, 0) + 1
                            dfs(succ_id, current_state, depth_left - 1, next_level, at_checkpoint, next_rule_counts, cache, True)
                        elif conn_state_con_val:
                            current_state = apply_station_rule(rule, incoming_state, incoming_signature)
                            next_rule_counts = dict(segment_rule_counts)
                            if key and not blocked_limit:
                                next_rule_counts[key] = next_rule_counts.get(key, 0) + 1
                            dfs(succ_id, current_state, depth_left - 1, next_level, at_checkpoint, next_rule_counts, cache, True)
                        elif state_cont:
                            current_state = apply_station_rule(rule, incoming_state, incoming_signature)
                            next_rule_counts = dict(segment_rule_counts)
                            if key and not blocked_limit:
                                next_rule_counts[key] = next_rule_counts.get(key, 0) + 1
                            dfs(succ_id, current_state, depth_left - 1, next_level, at_checkpoint, next_rule_counts, cache)
            collect_started = time.perf_counter()
            last_progress_emit = 0.0
            last_progress_value = -1
            for depth in range(1, max_depth + 1):
                if cancel_event.is_set():
                    profile["t_collect_states_ms"] += (time.perf_counter() - collect_started) * 1000
                    return None
                if depth % max(1, max_depth // 10) == 0:
                    progress_value = 67 + int(depth * 32 / max_depth)
                    now = time.perf_counter()
                    if progress_value != last_progress_value and (now - last_progress_emit) >= 0.1:
                        self.status_message.emit(f"Validierung läuft ... {progress_value}%")
                        last_progress_emit = now
                        last_progress_value = progress_value
                depth_cache = set()
                for root_id in root_ids:
                    root_rules = station_rules_by_id.get(root_id, [])
                    if not root_rules:
                        dfs(root_id, {}, depth, False, False, {}, depth_cache)
                    for rule in root_rules:
                        current_state = apply_station_rule(rule, {}, ())
                        dfs(root_id, current_state, depth, False, False, {}, depth_cache)
            profile["t_collect_states_ms"] += (time.perf_counter() - collect_started) * 1000
            return checkpoint_levels, conn_states_valid, conn_states_conditional_valid
        checkpoint_levels, strict_states, fallback_states = collect_states(True)
        if strict_states is None:
            return {
                "cancelled": True,
                "metrics": build_metrics(cancelled=True),
            }
        if fallback_states is None:
            return {
                "cancelled": True,
                "metrics": build_metrics(cancelled=True),
            }
        if checkpoint_levels is None:
            return {
                "cancelled": True,
                "metrics": build_metrics(cancelled=True),
            }

        priority = {
            CONNECTION_STATE.VALID: 0,
            CONNECTION_STATE.CONDITIONAL_VALID: 1,
            CONNECTION_STATE.CONDITIONAL_INVALID: 2,
            CONNECTION_STATE.INVALID: 3,
        }

        pick_started = time.perf_counter()
        best_states = {}
        for conn_key in target_conn_keys:
            candidates = strict_states.get(conn_key, [])
            if not any(state == CONNECTION_STATE.VALID for state, _ in candidates):
                candidates = fallback_states.get(conn_key, [])
            if candidates:
                best_states[conn_key] = min(candidates, key=lambda x: priority.get(x[0], 99))

        materialized_best_states = {}
        for conn_key, payload in best_states.items():
            state, reason_payload = payload
            reasons = [] if state == CONNECTION_STATE.VALID else materialize_reasons(reason_payload)
            materialized_best_states[conn_key] = (state, reasons)
        profile["t_best_pick_ms"] += (time.perf_counter() - pick_started) * 1000

        self.status_message.emit("Validierung läuft ... 100%")

        return {
            "best_states": materialized_best_states,
            "checkpoint_levels": {sid: list(levels) for sid, levels in checkpoint_levels.items()},
            "root_exists": bool(root_ids),
            "cancelled": False,
            "metrics": build_metrics(cancelled=False),
        }

    def _launch_validation_job(self, generation: int, snapshot: dict):
        cancel_event = Event()
        self._validation_cancel_event = cancel_event
        self._validation_future = self._validation_executor.submit(
            self._compute_validation_snapshot,
            snapshot,
            cancel_event,
            generation,
        )

        def _done(fut):
            try:
                result = fut.result()
            except Exception as exc:
                result = {"error": str(exc)}
            self.validation_result_ready.emit(generation, result)

        self._validation_future.add_done_callback(_done)
        self._emit_validation_state()

    def _apply_validation_result(self, generation: int, result: dict):
        meta = self._validation_meta.pop(generation, None)
        is_latest = generation == self._validation_generation
        metrics = result.get("metrics", {})

        def emit_validation_debug(state: str):
            if not metrics:
                return
            profiling = metrics.get("profiling", {})
            message = (
                f"{state} | {metrics.get('mode', '-')}, "
                f"Flow {metrics.get('target_flow', 0)}/{metrics.get('total_flow', 0)}, "
                f"Checkpoints {metrics.get('target_checkpoints', 0)}/{metrics.get('total_checkpoints', 0)}, "
                f"{metrics.get('duration_ms', 0)} ms"
            )
            if self.validation_profiling_enabled and profiling:
                message += (
                    f" | DFS {profiling.get('dfs_calls', 0)} ({profiling.get('dfs_pruned', 0)} pruned), "
                    f"Cond H/M {profiling.get('condition_hits', 0)}/{profiling.get('condition_misses', 0)}, "
                    f"Tr H/M {profiling.get('transition_hits', 0)}/{profiling.get('transition_misses', 0)}"
                )
            self.validation_debug.emit(message)

        if meta is not None and is_latest and "error" not in result and not result.get("cancelled", False):
            conn_lookup = meta["conn_lookup"]
            station_lookup = meta["station_lookup"]
            connection_kinds = meta.get("connection_kinds", {})
            best_states = dict(self._validation_cache_best_states)
            best_states.update(result.get("best_states", {}))
            checkpoint_levels = dict(self._validation_cache_checkpoint_levels)
            checkpoint_levels.update(result.get("checkpoint_levels", {}))
            self._validation_cache_best_states = best_states
            self._validation_cache_checkpoint_levels = checkpoint_levels

            for item in self.selectedItems():
                if isinstance(item, ConnectionItem):
                    item.setSelected(False)

            for conn in self._connections:
                conn._invalid_reasons = []
                conn.set_state(CONNECTION_STATE.UNKNOWN)
                kind = connection_kinds.get(id(conn))
                if kind is None:
                    kind = self._connection_kind(conn)
                if kind == CONNECTION_KIND.ATTRIBUTE:
                    conn.set_state(CONNECTION_STATE.ATTRIBUTE)

            for conn_key, payload in best_states.items():
                conn = conn_lookup.get(conn_key)
                if conn is None:
                    continue
                if conn not in self._connections:
                    continue
                state, reasons = payload
                conn.set_state(state)
                conn._invalid_reasons = reasons

            for conn in self._connections:
                kind = connection_kinds.get(id(conn))
                if kind is None:
                    kind = self._connection_kind(conn)
                if kind == CONNECTION_KIND.ATTRIBUTE:
                    continue
                if kind != CONNECTION_KIND.FLOW:
                    if not conn.src_port or not conn.dst_port:
                        conn._invalid_reasons = ["Die Verbindung hat keinen vollständigen Start-/Ziel-Port."]
                    else:
                        conn._invalid_reasons = ["Die Verbindungstypen passen nicht zusammen."]
                    continue
                if conn._state == CONNECTION_STATE.UNKNOWN:
                    conn._invalid_reasons = ["Keine erreichbare Validierungsroute von einer Startstation."]

            total_flow = 0
            validated_flow = 0
            valid_flow = 0
            conditional_flow = 0
            invalid_flow = 0
            for conn in self._connections:
                kind = connection_kinds.get(id(conn))
                if kind is None:
                    kind = self._connection_kind(conn)
                if kind != CONNECTION_KIND.FLOW:
                    continue
                total_flow += 1
                if conn._state != CONNECTION_STATE.UNKNOWN:
                    validated_flow += 1
                if conn._state == CONNECTION_STATE.VALID:
                    valid_flow += 1
                elif conn._state == CONNECTION_STATE.CONDITIONAL_VALID:
                    conditional_flow += 1
                elif conn._state in (CONNECTION_STATE.INVALID, CONNECTION_STATE.CONDITIONAL_INVALID):
                    invalid_flow += 1

            self.status_message.emit(
                f"{validated_flow}/{total_flow} FLOW-Verbindungen validiert  |  "
                f"gültig: {valid_flow}, bedingt gültig: {conditional_flow}, ungültig: {invalid_flow}"
            )
            emit_validation_debug("ok")

            for station in station_lookup.values():
                if station.type != STATION_TYPE.END:
                    continue
                levels = set(checkpoint_levels.get(station.node_id, []))
                if levels and levels == {0}:
                    station.end_badge_text_color = QColor("#22C55E")
                elif 0 in levels:
                    station.end_badge_text_color = QColor("#3B82F6")
                elif 1 in levels:
                    station.end_badge_text_color = QColor("#9A1DEE")
                else:
                    station.end_badge_text_color = QColor("#FFFFFF")
                station.update()

        if meta is not None and is_latest and "error" in result:
            self.status_message.emit(f"Validierungsfehler: {result['error']}")
            emit_validation_debug("fehler")
        elif meta is not None and is_latest and result.get("cancelled", False):
            self.status_message.emit("Validierung abgebrochen")
            emit_validation_debug("abbruch")

        if self._queued_validation is not None:
            queued_generation, queued_snapshot = self._queued_validation
            self._queued_validation = None
            if queued_generation > generation:
                self._launch_validation_job(queued_generation, queued_snapshot)
                return

        self._validation_future = None
        self._validation_cancel_event = None
        self._emit_validation_state()

    def validate_all(self, changed_targets=None, force: bool = False):
        if not self.auto_validate_enabled and not force:
            return

        self._validation_generation += 1
        generation = self._validation_generation

        snapshot, meta = self._build_validation_snapshot(changed_targets=changed_targets)
        if snapshot is None or meta is None:
            return

        if not snapshot.get("root_ids"):
            self.status_message.emit("Keine Startstation gefunden (Typ Start fehlt)")
            return

        for station in meta["station_lookup"].values():
            if station.type == STATION_TYPE.END:
                station.end_badge_text_color = QColor("#FFFFFF")
                station.update()

        self._validation_meta[generation] = meta
        self._queued_validation = (generation, snapshot)
        self._emit_validation_state()

        if self._validation_cancel_event is not None:
            self._validation_cancel_event.set()

        if self._validation_future is not None and not self._validation_future.done():
            self.status_message.emit("Validierung läuft ...")
            return
        queued_generation, queued_snapshot = self._queued_validation
        self._queued_validation = None
        self._launch_validation_job(queued_generation, queued_snapshot)

    def clear_all(self):
        if self._validation_cancel_event is not None:
            self._validation_cancel_event.set()
        self._connections.clear()
        self._validation_meta.clear()
        self._queued_validation = None
        self._validation_cache_best_states = {}
        self._validation_cache_checkpoint_levels = {}
        self._emit_validation_state()
        self.clear()


