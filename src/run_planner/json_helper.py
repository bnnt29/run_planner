"""JSON import/export helpers extracted from the original flow editor module."""

import importlib.util
import os
import sys
import sysconfig
import json as stdjson

from PyQt5.QtWidgets import QMessageBox

def _ui_types():
    try:
        from .items import AttributeItem, StationItem, TextBlockItem, ConnectionItem
    except ImportError:
        from items import AttributeItem, StationItem, TextBlockItem, ConnectionItem
    return AttributeItem, StationItem, TextBlockItem, ConnectionItem


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

    AttributeItem, StationItem, TextBlockItem, _ = _ui_types()

    try:
        stations = [i for i in window.scene.items() if isinstance(i, StationItem)]
        attributes = [i for i in window.scene.items() if isinstance(i, AttributeItem)]
        textblocks = [i for i in window.scene.items() if isinstance(i, TextBlockItem)]

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
            "connections": [c.to_json() for c in window.scene._connections if c.src_port and c.dst_port],
        }

        with open(path, "w", encoding="utf-8") as f:
            stdjson.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        QMessageBox.critical(window, "Speichern fehlgeschlagen", f"JSON konnte nicht gespeichert werden:\n{exc}")
        return
    window.statusBar().showMessage(f"JSON gespeichert: {path}")


def import_json(window):
    path = window._choose_file(
        save=False,
        title="Konfiguration laden",
        default_name="",
        name_filter="JSON-Dateien (*.json)",
    )
    if not path:
        return

    AttributeItem, StationItem, TextBlockItem, ConnectionItem = _ui_types()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = stdjson.load(f)
    except Exception as exc:
        QMessageBox.critical(window, "Laden fehlgeschlagen", f"JSON konnte nicht geladen werden:\n{exc}")
        return

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
        item._recalc_height()
        item.setPos(float(t.get("x", 0.0)), float(t.get("y", 0.0)))
        window.scene.addItem(item)
        node_map[item.node_id] = item

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

    window.scene.validate_all()
    window.statusBar().showMessage(f"JSON geladen: {path}")
