"""Validation scene logic extracted from the editor UI.

This module is kept independent so the scene validation can be reused
without importing the full UI module.
"""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from PyQt5.QtCore import *  # noqa: F401,F403
from PyQt5.QtGui import *  # noqa: F401,F403
from PyQt5.QtPrintSupport import *  # noqa: F401,F403
from PyQt5.QtWidgets import *  # noqa: F401,F403

try:
    from .items import *  # noqa: F401,F403
    from .sat_validation import compute_sat_validation
except ImportError:
    from .items import *  # noqa: F401,F403
    from .sat_validation import compute_sat_validation

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

    def _cleanup_text_links_for_node(self, node_id: str):
        if not node_id:
            return
        for item in self.items():
            if isinstance(item, TextBlockItem) and node_id in item.linked_node_ids:
                item.linked_node_ids.discard(node_id)

    def _delete_scene_item(self, item):
        if isinstance(item, ConnectionItem):
            self._remove_conn(item)
        elif isinstance(item, StationItem):
            self._cleanup_text_links_for_node(item.node_id)
            for c in list(item.all_connections()):
                self._remove_conn(c)
            self.removeItem(item)
        elif isinstance(item, AttributeItem):
            self._cleanup_text_links_for_node(item.node_id)
            for station in self._station_items():
                self._remove_related_conditions_for_attribute(item, station)
            for c in list(item.all_connections()):
                self._remove_conn(c)
            self.removeItem(item)
        elif isinstance(item, TextBlockItem):
            self._cleanup_text_links_for_node(item.node_id)
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
                    self._cleanup_text_links_for_node(item.node_id)
                    for c in list(item.all_connections()):
                        self._remove_conn(c)
                    self.removeItem(item)
                elif isinstance(item, AttributeItem):
                    self._cleanup_text_links_for_node(item.node_id)
                    for c in list(item.all_connections()):
                        self._remove_conn(c)
                    self.removeItem(item)
                elif isinstance(item, TextBlockItem):
                    self._cleanup_text_links_for_node(item.node_id)
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
            from .ui import StationDialog
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
            from .ui import AttributeDialog
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
            from .ui import ConnectionDialog
        parent = self.views()[0] if self.views() else None
        previous_conditions = [Condition(c.attribute, c.operator, c.value, c.compare_attribute) for c in conn.conditions]
        previous_name = conn.name
        dlg    = ConnectionDialog(conn, self._attribute_items(), parent)

        def _preview_validate():
            data = dlg.result_data()
            if isinstance(data, dict):
                conn.name = data.get("name", "")
                conn.conditions = data.get("conditions", [])
            else:
                conn.conditions = data
            conn.update()
            self.validate_all(changed_targets=[conn])

        dlg.conditions_changed.connect(_preview_validate)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.result_data()
            if isinstance(data, dict):
                conn.name = data.get("name", "")
                conn.conditions = data.get("conditions", [])
            else:
                conn.conditions = data
            conn.update()
            self.validate_all(changed_targets=[conn])
        else:
            conn.name = previous_name
            conn.conditions = previous_conditions
            conn.update()
            self.validate_all(changed_targets=[conn])

    def open_text_editor(self, item: TextBlockItem):
        try:
            from .ui import TextDialog
        except ImportError:
            from .ui import TextDialog
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
    #

    @staticmethod
    def _snapshot_condition(cond: Condition) -> dict:
        attr = getattr(cond, "attribute", None)
        attr_name = getattr(attr, "name", str(attr)) if attr is not None else ""
        compare_attr = getattr(cond, "compare_attribute", None)
        compare_attr_name = getattr(compare_attr, "name", str(compare_attr)) if compare_attr is not None else ""
        return {
            "attr_id": getattr(attr, "node_id", None),
            "attr_name": attr_name,
            "compare_attr_id": getattr(compare_attr, "node_id", None),
            "compare_attr_name": compare_attr_name,
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
        compare_name = cond.get("compare_attr_name", "")
        op = cond.get("op", CONDITION_OP.EXISTS.value)
        value = cond.get("value", 0.0)
        prefix = f"⟨{name}⟩"
        if op == CONDITION_OP.EXISTS.value:
            return f"{prefix} vorhanden"
        if op == CONDITION_OP.NOT_EXISTS.value:
            return f"{prefix} fehlt"
        if compare_name:
            return f"{prefix} {op} ⟨{compare_name}⟩"
        return f"{prefix} {op} {value}"

    @staticmethod
    def _snapshot_check_condition(cond: dict, state: dict) -> bool:
        attr_id = cond.get("attr_id")
        compare_attr_id = cond.get("compare_attr_id")
        op = cond.get("op", CONDITION_OP.EXISTS.value)
        value = float(cond.get("value", 0.0))
        count = 0.0 if attr_id is None or attr_id not in state or state[attr_id] is None else state[attr_id]
        compare_count = 0.0 if compare_attr_id is None or compare_attr_id not in state or state[compare_attr_id] is None else state[compare_attr_id]
        rhs = compare_count if compare_attr_id is not None else value

        if op == CONDITION_OP.EXISTS.value:
            return count > 0
        if op == CONDITION_OP.NOT_EXISTS.value:
            return count == 0
        if op == CONDITION_OP.EQUALS.value:
            return count == rhs
        if op == CONDITION_OP.NOT_EQUALS.value:
            return count != rhs
        if op == CONDITION_OP.GREATER.value:
            return count > rhs
        if op == CONDITION_OP.GREATER_EQ.value:
            return count >= rhs
        if op == CONDITION_OP.LESS.value:
            return count < rhs
        if op == CONDITION_OP.LESS_EQ.value:
            return count <= rhs
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
            for idx, rule in enumerate(station.rules):
                rules.append({
                    "conditions": [self._snapshot_condition(cond) for cond in rule.conditions],
                    "effects": [self._snapshot_effect(eff) for eff in rule.effects],
                    "max_traversals": min(1000, max(1, int(getattr(rule, "max_traversals", 20) or 20))),
                    "group_number": max(1, int(getattr(rule, "group_number", idx + 1) or (idx + 1))),
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
            predecessors = {sid: [] for sid in flow_succs.keys()}
            for src_id, entries in flow_succs.items():
                for _, dst_id in entries:
                    predecessors.setdefault(dst_id, []).append(src_id)

            affected_nodes = set(changed_station_ids)
            queue = deque(changed_station_ids)
            while queue:
                node_id = queue.popleft()
                for _, succ_id in flow_succs.get(node_id, []):
                    if succ_id not in affected_nodes:
                        affected_nodes.add(succ_id)
                        queue.append(succ_id)
                for pred_id in predecessors.get(node_id, []):
                    if pred_id not in affected_nodes:
                        affected_nodes.add(pred_id)
                        queue.append(pred_id)

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
        return snapshot, {
            "conn_lookup": conn_lookup,
            "station_lookup": station_lookup,
            "connection_kinds": connection_kinds,
            "target_conn_keys": list(target_conn_keys),
            "target_checkpoint_ids": list(target_checkpoint_ids),
        }

    def _compute_validation_snapshot(self, snapshot: dict, cancel_event: Event, generation: int):
        def status_emit(msg: str):
            # Ignore stale worker updates from older generations.
            if generation != self._validation_generation:
                return
            if cancel_event.is_set():
                return
            self.status_message.emit(msg)

        status_emit("Validierung läuft ... SAT-BMC")
        return compute_sat_validation(
            snapshot=snapshot,
            cancel_event=cancel_event,
            status_emit=status_emit,
        )

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
            target_conn_keys = set(meta.get("target_conn_keys", []))
            target_checkpoint_ids = set(meta.get("target_checkpoint_ids", []))
            
            best_states = dict(self._validation_cache_best_states)
            # Inkrementelle Läufe müssen betroffene Keys zuerst invalidieren,
            # sonst bleiben alte Zustände beim "Zurückändern" hängen.
            for conn_key in target_conn_keys:
                best_states.pop(conn_key, None)
            best_states.update(result.get("best_states", {}))
            checkpoint_levels = dict(self._validation_cache_checkpoint_levels)
            for checkpoint_id in target_checkpoint_ids:
                checkpoint_levels.pop(checkpoint_id, None)

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

                # Für die Badge-Farbe zählt der beste erreichbare Level,
                # nicht die Menge aller beobachteten Levels.
                if levels:
                    best_level = min(levels)
                    if best_level == 0:
                        station.end_badge_text_color = QColor("#22C55E")
                    elif best_level == 1:
                        station.end_badge_text_color = QColor("#3B82F6")
                    else:
                        station.end_badge_text_color = QColor("#FFFFFF")
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


