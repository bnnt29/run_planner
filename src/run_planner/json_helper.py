"""JSON import/export helpers extracted from the original flow editor module."""

import importlib.util
import os
import sys
import sysconfig
import json as stdjson
from pathlib import Path
from typing import Any

from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtGui import QColor

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
        # Export the scene normally (full structure with attributes, stations, connections)
        plan_data = _serialize_scene(window)
        
        if not plan_data.get("stations"):
            QMessageBox.warning(window, "Export abgebrochen", "Der aktuelle Plan enthält keine Stationen.")
            return

        # Save the plan with full scene structure
        with open(plan_path, "w", encoding="utf-8") as f:
            stdjson.dump(plan_data, f, ensure_ascii=False, indent=2)

        # Build validation snapshot and compute validation for expected data
        snapshot = _build_stable_validation_snapshot(window.scene)
        if snapshot is not None:
            validation_result = compute_sat_validation(snapshot)

            paths = {}
            for conn_key, payload in sorted(validation_result.get("best_states", {}).items()):
                state = payload[0]
                paths[str(conn_key)] = {
                    "state": getattr(state, "name", str(state)),
                }

            stations = {}
            checkpoint_levels = validation_result.get("checkpoint_levels", {})
            for station_id in sorted(snapshot.get("checkpoint_ids", [])):
                stations[station_id] = {
                    "levels": list(checkpoint_levels.get(station_id, [])),
                }

            expected_data = {
                "paths": paths,
                "stations": stations,
            }

            with open(expected_path, "w", encoding="utf-8") as f:
                stdjson.dump(expected_data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        QMessageBox.critical(window, "Export fehlgeschlagen", f"Testfall konnte nicht exportiert werden:\n{exc}")
        return

    window.statusBar().showMessage(f"Testfall exportiert: {plan_path} + {expected_path}")


def _stable_flow_conn_map(scene) -> dict[int, Any]:
    """Map deterministic/stable FLOW connection keys to live ConnectionItem instances."""
    AttributeItem, StationItem, _, _ = _ui_types()

    edge_refs = []
    conn_by_runtime_id = {}
    for conn in scene._connections:
        runtime_id = id(conn)
        conn_by_runtime_id[runtime_id] = conn

        kind = scene._connection_kind(conn)
        kind_name = getattr(kind, "name", str(kind)).upper()
        if kind_name != "FLOW":
            continue

        src = conn.src_port.parentItem() if conn.src_port else None
        dst = conn.dst_port.parentItem() if conn.dst_port else None
        if not isinstance(src, StationItem) or not isinstance(dst, StationItem):
            continue

        edge_refs.append((str(src.node_id), str(dst.node_id), runtime_id))

    edge_refs.sort(key=lambda item: (item[0], item[1], item[2]))

    stable_map = {}
    for stable_key, (_, _, runtime_id) in enumerate(edge_refs, start=1):
        stable_map[stable_key] = conn_by_runtime_id[runtime_id]
    return stable_map


def _apply_expected_markings(window, expected_data: dict):
    try:
        from .items import CONNECTION_STATE, STATION_TYPE
    except ImportError:
        from .items import CONNECTION_STATE, STATION_TYPE

    _, StationItem, _, _ = _ui_types()

    stable_conn_map = _stable_flow_conn_map(window.scene)

    best_states_cache = {}
    for conn in window.scene._connections:
        conn._invalid_reasons = []
        kind = window.scene._connection_kind(conn)
        kind_name = getattr(kind, "name", str(kind)).upper()
        if kind_name == "ATTRIBUTE":
            conn.set_state(CONNECTION_STATE.ATTRIBUTE)
        elif kind_name == "FLOW":
            conn.set_state(CONNECTION_STATE.UNKNOWN)
        else:
            conn.set_state(CONNECTION_STATE.INVALID)

    for conn_key_str, payload in (expected_data.get("paths", {}) or {}).items():
        try:
            conn_key = int(conn_key_str)
        except (TypeError, ValueError):
            continue
        conn = stable_conn_map.get(conn_key)
        if conn is None:
            continue

        state_name = str(payload.get("state", "UNKNOWN"))
        state = CONNECTION_STATE.__members__.get(state_name, CONNECTION_STATE.UNKNOWN)
        reasons = []
        reason_contains = payload.get("reason_contains", []) or []
        for reason in reason_contains:
            if isinstance(reason, str):
                reasons.append(reason)

        conn.set_state(state)
        conn._invalid_reasons = reasons
        best_states_cache[id(conn)] = (state, reasons)

    checkpoint_levels_cache = {}
    expected_stations = expected_data.get("stations", {}) or {}
    for station_id, payload in expected_stations.items():
        levels = payload.get("levels", []) if isinstance(payload, dict) else []
        if isinstance(levels, list):
            checkpoint_levels_cache[str(station_id)] = list(levels)

    for item in window.scene.items():
        if not isinstance(item, StationItem):
            continue
        station_type = getattr(item, "type", None)
        is_end = station_type == STATION_TYPE.END or getattr(station_type, "name", "") == "END"
        if not is_end:
            continue

        levels = set(checkpoint_levels_cache.get(str(item.node_id), []))
        if levels:
            best_level = min(levels)
            if best_level == 0:
                item.end_badge_text_color = QColor("#22C55E")
            elif best_level == 1:
                item.end_badge_text_color = QColor("#3B82F6")
            else:
                item.end_badge_text_color = QColor("#FFFFFF")
        else:
            item.end_badge_text_color = QColor("#FFFFFF")
        item.update()

    window.scene._validation_cache_best_states = best_states_cache
    window.scene._validation_cache_checkpoint_levels = checkpoint_levels_cache


def import_json(
    window,
    json_file_path=None,
    _skip_expected_autoload: bool = False,
    _skip_validation: bool = False,
):
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

    lower_path = path.lower()
    if lower_path.endswith(".expected.json"):
        expected_path = Path(path)
        plan_path = expected_path.with_name(expected_path.name[: -len(".expected.json")] + ".plan.json")
        if not plan_path.exists():
            QMessageBox.critical(
                window,
                "Laden fehlgeschlagen",
                f"Passende Plan-Datei wurde nicht gefunden:\n{plan_path}",
            )
            return False

        try:
            expected_data = stdjson.loads(expected_path.read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.critical(window, "Laden fehlgeschlagen", f"Expected-JSON konnte nicht geladen werden:\n{exc}")
            return False

        loaded = import_json(
            window,
            str(plan_path),
            _skip_expected_autoload=True,
            _skip_validation=True,
        )
        if not loaded:
            return False

        try:
            _apply_expected_markings(window, expected_data)
        except Exception as exc:
            QMessageBox.critical(window, "Laden fehlgeschlagen", f"Markierungen konnten nicht angewendet werden:\n{exc}")
            return False

        window.scene.validate_all(force=True)
        window.statusBar().showMessage(f"Testfall geladen: {plan_path} + {expected_path}")
        return True

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

    expected_applied = False
    expected_path = None
    scene_auto_validation = bool(getattr(window.scene, "auto_validate_enabled", True))
    if not _skip_expected_autoload and (not scene_auto_validation) and lower_path.endswith(".plan.json"):
        plan_path_obj = Path(path)
        expected_path = plan_path_obj.with_name(plan_path_obj.name[: -len(".plan.json")] + ".expected.json")
        if expected_path.exists():
            try:
                expected_data = stdjson.loads(expected_path.read_text(encoding="utf-8"))
                _apply_expected_markings(window, expected_data)
                expected_applied = True
            except Exception as exc:
                QMessageBox.warning(
                    window,
                    "Expected-Validierung nicht angewendet",
                    f"Die Plan-Datei wurde geladen, aber die Expected-Markierungen konnten nicht angewendet werden:\n{exc}",
                )

    if not _skip_validation:
        window.scene.validate_all()
    if expected_applied and expected_path is not None:
        window.statusBar().showMessage(f"Testfall geladen: {path} + {expected_path}")
    else:
        window.statusBar().showMessage(f"JSON geladen: {path}")
    return True