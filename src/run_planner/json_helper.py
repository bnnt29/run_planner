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
        "collect_checkpoint_paths": True,
    }


def _normalize_json_save_path(path: str | None) -> str | None:
    if not path:
        return None
    if not path.lower().endswith(".json"):
        path += ".json"
    return path


def _normalize_test_case_paths(path: str | None) -> tuple[str, str] | None:
    if not path:
        return None

    base_path = path
    lower = base_path.lower()
    if lower.endswith(".expected.json"):
        base_path = base_path[: -len(".expected.json")]
    elif lower.endswith(".plan.json"):
        base_path = base_path[: -len(".plan.json")]
    elif lower.endswith(".json"):
        base_path = base_path[: -len(".json")]

    return f"{base_path}.plan.json", f"{base_path}.expected.json"


def save_json(window, path: str | None = None, choose_path: bool = False) -> str | None:
    if choose_path or not path:
        path = window._choose_file(
            save=True,
            title="Konfiguration speichern",
            default_name="ablaufplan.json",
            name_filter="JSON-Dateien (*.json)",
        )
    path = _normalize_json_save_path(path)
    if not path:
        return None

    try:
        data = _serialize_scene(window)

        with open(path, "w", encoding="utf-8") as f:
            stdjson.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        QMessageBox.critical(window, "Speichern fehlgeschlagen", f"JSON konnte nicht gespeichert werden:\n{exc}")
        return None
    window.statusBar().showMessage(f"JSON gespeichert: {path}")
    return path


def save_validation_case(window, base_path: str | None = None, choose_path: bool = False) -> tuple[str, str] | None:
    path = base_path
    if choose_path or not path:
        path = window._choose_file(
            save=True,
            title="Testfall exportieren (Plan + Validierung)",
            default_name="validation_case.plan.json",
            name_filter="Plan-Dateien (*.plan.json);;JSON-Dateien (*.json)",
        )
    normalized_paths = _normalize_test_case_paths(path)
    if normalized_paths is None:
        return None
    plan_path, expected_path = normalized_paths

    try:
        # Export the scene normally (full structure with attributes, stations, connections)
        plan_data = _serialize_scene(window)
        
        if not plan_data.get("stations"):
            QMessageBox.warning(window, "Export abgebrochen", "Der aktuelle Plan enthält keine Stationen.")
            return

        # Save the plan with full scene structure
        with open(plan_path, "w", encoding="utf-8") as f:
            stdjson.dump(plan_data, f, ensure_ascii=False, indent=2)

        # Build the expected data strictly from the scene's current state, so
        # exports reflect what is actually shown in the editor (incl. markings
        # loaded from a previous expected file) rather than recomputing SAT.
        expected_data = _build_expected_payload_from_scene(window.scene)

        with open(expected_path, "w", encoding="utf-8") as f:
            stdjson.dump(expected_data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        QMessageBox.critical(window, "Export fehlgeschlagen", f"Testfall konnte nicht exportiert werden:\n{exc}")
        return None

    window.statusBar().showMessage(f"Testfall exportiert: {plan_path} + {expected_path}")
    return plan_path, expected_path


def export_json(window):
    return save_json(window, choose_path=True)


def export_validation_case(window):
    return save_validation_case(window, choose_path=True)


def _build_expected_payload_from_scene(scene) -> dict:
    """Build expected.json payload from the scene's currently displayed state.

    This intentionally does NOT re-run SAT validation; it serializes whatever
    is currently shown in the editor (connection states, reasons, checkpoint
    levels and witness paths), including markings that were loaded from a
    previously imported expected file.
    """
    try:
        from .items import STATION_TYPE
    except ImportError:
        from .items import STATION_TYPE

    _, StationItem, _, _ = _ui_types()

    stable_conn_map = _stable_flow_conn_map(scene)

    paths: dict[str, dict] = {}
    for stable_key in sorted(stable_conn_map.keys()):
        conn = stable_conn_map[stable_key]
        state = getattr(conn, "_state", None)
        state_name = getattr(state, "name", None) or "UNKNOWN"
        entry: dict = {"state": state_name}

        reasons = getattr(conn, "_invalid_reasons", []) or []
        reason_list = [str(reason) for reason in reasons if isinstance(reason, str)]
        if reason_list:
            entry["reason_contains"] = reason_list

        paths[str(stable_key)] = entry

    checkpoint_levels_raw = getattr(scene, "_validation_cache_checkpoint_levels", {}) or {}
    checkpoint_paths_raw = getattr(scene, "_validation_cache_checkpoint_paths", {}) or {}

    # Normalize cache keys to strings so station-id lookups are stable even if
    # upstream code mixed id types.
    checkpoint_levels = {
        str(station_id): list(levels) if isinstance(levels, list) else []
        for station_id, levels in checkpoint_levels_raw.items()
    }
    checkpoint_paths = {
        str(station_id): paths if isinstance(paths, list) else []
        for station_id, paths in checkpoint_paths_raw.items()
    }

    end_station_ids = []
    for item in scene.items():
        if not isinstance(item, StationItem):
            continue
        station_type = getattr(item, "type", None)
        is_end = station_type == STATION_TYPE.END or getattr(station_type, "name", "") == "END"
        if is_end:
            end_station_ids.append(str(item.node_id))

    stations: dict[str, dict] = {}
    for station_id in sorted(set(end_station_ids)):
        raw_levels = checkpoint_levels.get(station_id, [])
        station_entry: dict = {
            "level": _encode_expected_level(raw_levels),
        }

        normalized_witness_paths = []
        # Strictly use the witness paths currently held by the scene (i.e. what
        # is shown on the board). Do NOT regenerate via graph traversal here –
        # the export must reflect the board state 1:1.
        source_witness_paths = checkpoint_paths.get(station_id, [])
        for witness in source_witness_paths:
            if not isinstance(witness, dict):
                continue
            station_path = witness.get("station_path", [])
            if not isinstance(station_path, list):
                continue
            normalized_station_path = [str(node_id) for node_id in station_path if node_id is not None]
            if len(normalized_station_path) < 2:
                continue

            witness_entry = {
                "from_root": str(witness.get("from_root", normalized_station_path[0])),
                "station_path": normalized_station_path,
            }

            edge_path = witness.get("edge_path", [])
            if isinstance(edge_path, list):
                witness_entry["edge_path"] = list(edge_path)

            normalized_witness_paths.append(witness_entry)

        # Always emit witness_paths (possibly empty) so the export mirrors the
        # current board state exactly.
        station_entry["witness_paths"] = normalized_witness_paths
        stations[station_id] = station_entry

    return {
        "paths": paths,
        "stations": stations,
    }


def _encode_expected_level(levels: list[Any]) -> int:
    """Map internal checkpoint levels to expected.json single-level format.

    Expected format:
    -1 => white (unreachable)
     0 => orange
     1 => green
    """
    if not isinstance(levels, list) or not levels:
        return -1
    try:
        best_level = min(int(level) for level in levels)
    except Exception:
        return -1
    if best_level == 0:
        return 1
    if best_level == 1:
        return 0
    return -1


def _decode_expected_level_to_levels(station_payload: dict) -> list[int]:
    """Decode expected.json station level into internal checkpoint-level list.

    Supports both the new format (`level`: int) and legacy (`levels`: list).
    """
    if not isinstance(station_payload, dict):
        return []

    if "level" in station_payload:
        try:
            level_value = int(station_payload.get("level", -1))
        except Exception:
            level_value = -1
        if level_value == 1:
            return [0]
        if level_value == 0:
            return [1]
        return []

    levels = station_payload.get("levels", [])
    if isinstance(levels, list):
        # Legacy format compatibility: only the first array element is used.
        if not levels:
            return []
        try:
            return [int(levels[0])]
        except Exception:
            return []
    return []


def _derive_witness_paths_from_scene(scene, stable_conn_map: dict[int, Any]) -> dict[str, list[dict[str, Any]]]:
    """Derive witness paths from current FLOW graph as export fallback.

    This is used when checkpoint-path cache is empty/incomplete, but the editor
    still has a valid graph that can show reachability paths.
    """
    try:
        from .items import STATION_TYPE
    except ImportError:
        from .items import STATION_TYPE

    _, StationItem, _, _ = _ui_types()

    runtime_to_stable = {id(conn): stable_key for stable_key, conn in stable_conn_map.items()}

    succs: dict[str, list[tuple[str, int]]] = {}
    for conn in scene._connections:
        kind = scene._connection_kind(conn)
        kind_name = getattr(kind, "name", str(kind)).upper()
        if kind_name != "FLOW":
            continue

        src = conn.src_port.parentItem() if conn.src_port else None
        dst = conn.dst_port.parentItem() if conn.dst_port else None
        if not isinstance(src, StationItem) or not isinstance(dst, StationItem):
            continue

        stable_key = runtime_to_stable.get(id(conn))
        if stable_key is None:
            continue

        src_id = str(src.node_id)
        dst_id = str(dst.node_id)
        succs.setdefault(src_id, []).append((dst_id, int(stable_key)))

    for src_id in list(succs.keys()):
        succs[src_id].sort(key=lambda item: (item[0], item[1]))

    start_ids: list[str] = []
    end_ids: set[str] = set()
    for item in scene.items():
        if not isinstance(item, StationItem):
            continue
        station_type = getattr(item, "type", None)
        if station_type == STATION_TYPE.START or getattr(station_type, "name", "") == "START":
            start_ids.append(str(item.node_id))
        if station_type == STATION_TYPE.END or getattr(station_type, "name", "") == "END":
            end_ids.add(str(item.node_id))

    if not start_ids or not end_ids:
        return {}

    max_depth = max(10, len(succs) * 3)
    max_paths_per_checkpoint = 500
    paths_by_checkpoint: dict[str, list[dict[str, Any]]] = {checkpoint_id: [] for checkpoint_id in end_ids}

    for start_id in sorted(set(start_ids)):
        stack: list[tuple[str, list[str], list[int]]] = [(start_id, [start_id], [])]
        while stack:
            node_id, station_path, edge_path = stack.pop()
            if len(station_path) >= max_depth:
                continue

            for dst_id, stable_key in reversed(succs.get(node_id, [])):
                if dst_id in station_path:
                    continue
                next_station_path = station_path + [dst_id]
                next_edge_path = edge_path + [stable_key]

                if dst_id in end_ids and len(next_station_path) >= 2:
                    if len(paths_by_checkpoint[dst_id]) < max_paths_per_checkpoint:
                        paths_by_checkpoint[dst_id].append(
                            {
                                "from_root": start_id,
                                "station_path": next_station_path,
                                "edge_path": next_edge_path,
                            }
                        )

                stack.append((dst_id, next_station_path, next_edge_path))

    normalized: dict[str, list[dict[str, Any]]] = {}
    for checkpoint_id, entries in paths_by_checkpoint.items():
        if not entries:
            continue
        entries.sort(
            key=lambda witness: (
                str(witness.get("from_root", "")),
                tuple(str(node_id) for node_id in witness.get("station_path", [])),
                tuple(int(edge_id) for edge_id in witness.get("edge_path", [])),
            )
        )
        normalized[checkpoint_id] = entries

    return normalized


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
    checkpoint_paths_cache = {}

    # Build the set of station IDs that actually exist in the current scene
    # and the set of stable FLOW edge keys, so we can discard expected entries
    # that reference stations/edges which no longer exist on the board.
    existing_station_ids: set[str] = set()
    existing_end_station_ids: set[str] = set()
    for item in window.scene.items():
        if not isinstance(item, StationItem):
            continue
        station_id_str = str(item.node_id)
        existing_station_ids.add(station_id_str)
        station_type = getattr(item, "type", None)
        is_end = station_type == STATION_TYPE.END or getattr(station_type, "name", "") == "END"
        if is_end:
            existing_end_station_ids.add(station_id_str)
    existing_edge_keys: set[int] = set(stable_conn_map.keys())

    expected_stations = expected_data.get("stations", {}) or {}
    for station_id, payload in expected_stations.items():
        station_id_str = str(station_id)
        # Discard entries that reference stations which do not exist on the
        # board, or that exist but are not END stations.
        if station_id_str not in existing_end_station_ids:
            continue
        checkpoint_levels_cache[station_id_str] = _decode_expected_level_to_levels(payload if isinstance(payload, dict) else {})

        witness_paths = payload.get("witness_paths", []) if isinstance(payload, dict) else []
        if isinstance(witness_paths, list):
            normalized_paths = []
            for witness in witness_paths:
                if not isinstance(witness, dict):
                    continue
                station_path = witness.get("station_path", [])
                if not isinstance(station_path, list):
                    continue
                normalized_station_path = [str(node_id) for node_id in station_path if node_id is not None]
                if len(normalized_station_path) < 2:
                    continue
                # Discard witness paths that reference stations not present on
                # the board.
                if any(node_id not in existing_station_ids for node_id in normalized_station_path):
                    continue
                normalized_witness = {
                    "from_root": str(witness.get("from_root", normalized_station_path[0])),
                    "station_path": normalized_station_path,
                }
                edge_path = witness.get("edge_path", [])
                if isinstance(edge_path, list):
                    try:
                        edge_path_ints = [int(edge_id) for edge_id in edge_path]
                    except (TypeError, ValueError):
                        continue
                    # Discard witness paths whose edges no longer exist.
                    if any(edge_id not in existing_edge_keys for edge_id in edge_path_ints):
                        continue
                    normalized_witness["edge_path"] = edge_path_ints
                normalized_paths.append(normalized_witness)

            checkpoint_paths_cache[station_id_str] = normalized_paths

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
                item.end_badge_text_color = QColor("#E7F708")
            else:
                item.end_badge_text_color = QColor("#FFFFFF")
        else:
            item.end_badge_text_color = QColor("#FFFFFF")
        item.update()

    window.scene._validation_cache_best_states = best_states_cache
    window.scene._validation_cache_checkpoint_levels = checkpoint_levels_cache
    window.scene._validation_cache_checkpoint_paths = checkpoint_paths_cache


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

        window._loaded_json_path = str(plan_path)
        window._loaded_test_case_base_path = str(expected_path)[: -len(".expected.json")]
        if hasattr(window, "_update_save_target_hint"):
            window._update_save_target_hint()
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

    # Final reshape: Beim Laden werden Station-Layouts beim sukzessiven
    # Anlegen weiterer Verbindungen ggf. neu berechnet (z. B. Port-Positionen).
    # Damit alle Pfade ihre endgültige Form annehmen, hier einmal komplett
    # neu zeichnen.
    for item in window.scene.items():
        if isinstance(item, (StationItem, AttributeItem)) and hasattr(item, "_layout"):
            item._layout()
    for conn in window.scene._connections:
        try:
            conn.update_path()
        except Exception:
            pass

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
        window._loaded_test_case_base_path = str(expected_path)[: -len(".expected.json")]
        window.statusBar().showMessage(f"Testfall geladen: {path} + {expected_path}")
    else:
        if lower_path.endswith(".plan.json"):
            window._loaded_test_case_base_path = str(path)[: -len(".plan.json")]
        elif lower_path.endswith(".json"):
            window._loaded_test_case_base_path = None
        window.statusBar().showMessage(f"JSON geladen: {path}")
    window._loaded_json_path = str(path)
    if hasattr(window, "_update_save_target_hint"):
        window._update_save_target_hint()
    return True