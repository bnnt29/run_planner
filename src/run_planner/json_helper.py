"""JSON import/export helpers extracted from the original flow editor module."""

import importlib.util
import os
import sys
import sysconfig
import json as stdjson

from PyQt5.QtWidgets import QMessageBox

try:
    from .sat_validation import compute_sat_validation
except ImportError:
    from .sat_validation import compute_sat_validation

def _ui_types():
    try:
        from .items import AttributeItem, StationItem, TextBlockItem, ConnectionItem
    except ImportError:
        from .items import AttributeItem, StationItem, TextBlockItem, ConnectionItem
    return AttributeItem, StationItem, TextBlockItem, ConnectionItem


def _serialize_scene(window) -> dict:
    AttributeItem, StationItem, TextBlockItem, _ = _ui_types()

    stations = [i for i in window.scene.items() if isinstance(i, StationItem)]
    attributes = [i for i in window.scene.items() if isinstance(i, AttributeItem)]
    textblocks = [i for i in window.scene.items() if isinstance(i, TextBlockItem)]

    return {
        "version": 1,
        "attributes": [a.to_json() for a in attributes],
        "stations": [s.to_json() for s in stations],
        "textblocks": [
            {
                "node_id": t.node_id,
                "text": t._text,
                "x": float(t.pos().x()),
                "y": float(t.pos().y()),
                "linked_node_ids": sorted(list(getattr(t, "linked_node_ids", set()))),
            }
            for t in textblocks
        ],
        "connections": [c.to_json() for c in window.scene._connections if c.src_port and c.dst_port],
    }


def _build_stable_validation_snapshot(scene) -> dict | None:
    snapshot, _ = scene._build_validation_snapshot(changed_targets=None)
    if snapshot is None:
        return None

    flow_succs = snapshot.get("flow_succs", {})
    flow_conn_conditions = snapshot.get("flow_conn_conditions", {})
    flow_conn_keys = list(snapshot.get("flow_conn_keys", []))
    target_conn_keys = set(snapshot.get("target_conn_keys", flow_conn_keys))

    edge_refs = []
    for src_id, entries in flow_succs.items():
        for conn_key, dst_id in entries:
            edge_refs.append((str(src_id), str(dst_id), int(conn_key)))

    edge_refs.sort(key=lambda item: (item[0], item[1], item[2]))
    key_map = {old_key: idx + 1 for idx, (_, _, old_key) in enumerate(edge_refs)}

    stable_flow_succs = {sid: [] for sid in flow_succs.keys()}
    for src_id, entries in flow_succs.items():
        stable_entries = []
        for conn_key, dst_id in entries:
            if conn_key in key_map:
                stable_entries.append((key_map[conn_key], dst_id))
        stable_flow_succs[src_id] = stable_entries

    stable_flow_conn_conditions = {}
    for old_key, conds in flow_conn_conditions.items():
        if old_key in key_map:
            stable_flow_conn_conditions[key_map[old_key]] = conds

    stable_flow_conn_keys = [key_map[key] for key in flow_conn_keys if key in key_map]
    stable_target_conn_keys = [key_map[key] for key in flow_conn_keys if key in target_conn_keys and key in key_map]

    return {
        "station_data": snapshot.get("station_data", {}),
        "root_ids": list(snapshot.get("root_ids", [])),
        "checkpoint_ids": sorted(list(snapshot.get("checkpoint_ids", []))),
        "flow_succs": stable_flow_succs,
        "flow_conn_conditions": stable_flow_conn_conditions,
        "flow_conn_keys": stable_flow_conn_keys,
        "target_conn_keys": stable_target_conn_keys,
        "target_checkpoint_ids": sorted(list(snapshot.get("target_checkpoint_ids", snapshot.get("checkpoint_ids", [])))),
        "connection_kinds": {key_map[key]: "FLOW" for key in flow_conn_keys if key in key_map},
        "max_depth": int(snapshot.get("max_depth", 2000)),
    }


def export_json(window):
    path = window._choose_file(
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
        data = _serialize_scene(window)

        with open(path, "w", encoding="utf-8") as f:
            stdjson.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        QMessageBox.critical(window, "Speichern fehlgeschlagen", f"JSON konnte nicht gespeichert werden:\n{exc}")
        return
    window.statusBar().showMessage(f"JSON gespeichert: {path}")


def export_validation_case(window):
    path = window._choose_file(
        save=True,
        title="Testfall exportieren (Plan + Validierung)",
        default_name="validation_case.plan.json",
        name_filter="Plan-Dateien (*.plan.json);;JSON-Dateien (*.json)",
    )
    if not path:
        return

    base_path = path
    lower = base_path.lower()
    if lower.endswith(".expected.json"):
        base_path = base_path[: -len(".expected.json")]
    elif lower.endswith(".plan.json"):
        base_path = base_path[: -len(".plan.json")]
    elif lower.endswith(".json"):
        base_path = base_path[: -len(".json")]

    plan_path = f"{base_path}.plan.json"
    expected_path = f"{base_path}.expected.json"

    try:
        plan_data = _build_stable_validation_snapshot(window.scene)
        if plan_data is None:
            QMessageBox.warning(window, "Export abgebrochen", "Der aktuelle Plan enthält keine Stationen.")
            return

        validation_result = compute_sat_validation(plan_data)

        paths = {}
        for conn_key, payload in sorted(validation_result.get("best_states", {}).items()):
            state = payload[0]
            paths[str(conn_key)] = {
                "state": getattr(state, "name", str(state)),
            }

        stations = {}
        checkpoint_levels = validation_result.get("checkpoint_levels", {})
        for station_id in sorted(plan_data.get("checkpoint_ids", [])):
            stations[station_id] = {
                "levels": list(checkpoint_levels.get(station_id, [])),
            }

        expected_data = {
            "paths": paths,
            "stations": stations,
        }

        with open(plan_path, "w", encoding="utf-8") as f:
            stdjson.dump(plan_data, f, ensure_ascii=False, indent=2)
        with open(expected_path, "w", encoding="utf-8") as f:
            stdjson.dump(expected_data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        QMessageBox.critical(window, "Export fehlgeschlagen", f"Testfall konnte nicht exportiert werden:\n{exc}")
        return

    window.statusBar().showMessage(f"Testfall exportiert: {plan_path} + {expected_path}")


def import_json(window, json_file_path=None):
    if json_file_path:
        path = json_file_path
    else:
        path = window._choose_file(
            save=False,
            title="Konfiguration laden",
            default_name="",
            name_filter="JSON-Dateien (*.json)",
    )
    if not path:
        return False

    AttributeItem, StationItem, TextBlockItem, ConnectionItem = _ui_types()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = stdjson.load(f)
    except Exception as exc:
        QMessageBox.critical(window, "Laden fehlgeschlagen", f"JSON konnte nicht geladen werden:\n{exc}")
        return False

    window.scene.clear_all()
    window.palette.reset_templates()

    node_map = {}
    for a in data.get("attributes", []):
        item = AttributeItem.from_json(a)
        item.name = window.scene.make_unique_attribute_name(item.name)
        window.scene.addItem(item)
        window.scene._register_template(item)
        node_map[item.node_id] = item

    for s in data.get("stations", []):
        item = StationItem.from_json(s, node_map)
        window.scene.addItem(item)
        window.scene._register_template(item)
        node_map[item.node_id] = item

    for t in data.get("textblocks", []):
        item = TextBlockItem(t.get("text", ""))
        item.node_id = t.get("node_id") or item.node_id
        linked_ids = t.get("linked_node_ids", [])
        if isinstance(linked_ids, list):
            item.linked_node_ids = {str(node_id) for node_id in linked_ids if node_id}
        item._recalc_height()
        item.setPos(float(t.get("x", 0.0)), float(t.get("y", 0.0)))
        window.scene.addItem(item)
        node_map[item.node_id] = item

    valid_ids = set(node_map.keys())
    for item in [i for i in window.scene.items() if isinstance(i, TextBlockItem)]:
        item.linked_node_ids = {node_id for node_id in item.linked_node_ids if node_id in valid_ids and node_id != item.node_id}

    for c in data.get("connections", []):
        conn = ConnectionItem.from_json(c, node_map)
        if conn is None:
            continue
        window.scene._connections.append(conn)
        window.scene.addItem(conn)

    existing_attr_links = set()
    for conn in window.scene._connections:
        kind = window.scene._connection_kind(conn)
        if getattr(kind, "name", "") != "ATTRIBUTE":
            continue
        src_item = conn.src_port.parentItem() if conn.src_port else None
        dst_item = conn.dst_port.parentItem() if conn.dst_port else None
        if isinstance(src_item, AttributeItem) and isinstance(dst_item, StationItem):
            existing_attr_links.add((src_item.node_id, dst_item.node_id))

    touched_items = set()
    for station in [item for item in window.scene.items() if isinstance(item, StationItem)]:
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
            window.scene._connections.append(conn)
            window.scene.addItem(conn)
            existing_attr_links.add(link_key)
            touched_items.add(attribute)
            touched_items.add(station)

    for item in touched_items:
        window.scene.update_connections_for(item)

    if hasattr(window.scene, "rebuild_note_links"):
        window.scene.rebuild_note_links()

    window.scene.validate_all()
    window.statusBar().showMessage(f"JSON geladen: {path}")
    return True