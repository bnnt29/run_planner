import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_planner import json_helper


class _FakePos:
    def __init__(self, x: float, y: float):
        self._x = x
        self._y = y

    def x(self):
        return self._x

    def y(self):
        return self._y


class _FakePort:
    def __init__(self, parent):
        self._parent = parent
        self.connections = []

    def parentItem(self):
        return self._parent


class _FakeAttribute:
    def __init__(self, node_id="attr-1", name="Attribute"):
        self.node_id = node_id
        self.name = name
        self.out_port = _FakePort(self)

    def to_json(self):
        return {"node_id": self.node_id, "name": self.name}

    @classmethod
    def from_json(cls, data):
        return cls(data.get("node_id", "attr-1"), data.get("name", "Attribute"))


class _FakeTextBlock:
    def __init__(self, text="Text"):
        self.node_id = "text-1"
        self._text = text
        self.linked_node_ids = set()
        self._pos = _FakePos(1.0, 2.0)

    def pos(self):
        return self._pos

    def _recalc_height(self):
        self.recalc_called = True

    def setPos(self, x, y):
        self._pos = _FakePos(x, y)


class _FakeStation:
    def __init__(self, node_id="station-1", name="Station", attr=None):
        self.node_id = node_id
        self.name = name
        self.rules = []
        self.attr_port = _FakePort(self)
        self.in_port = _FakePort(self)
        self.type = SimpleNamespace(value=1)
        if attr is not None:
            self.rules = [SimpleNamespace(conditions=[SimpleNamespace(attribute=attr)], effects=[SimpleNamespace(attribute=attr)])]

    def to_json(self):
        return {"node_id": self.node_id, "name": self.name, "rules": []}

    @classmethod
    def from_json(cls, data, node_map):
        attr = node_map.get("attr-1")
        return cls(data.get("node_id", "station-1"), data.get("name", "Station"), attr=attr)


class _FakeConnection:
    def __init__(self, src_port=None, dst_port=None, payload=None):
        self.src_port = src_port
        self.dst_port = dst_port
        self._payload = payload or {"kind": "flow"}

    def finalize(self, dst_port):
        self.dst_port = dst_port

    def to_json(self):
        return dict(self._payload)


class _FakeScene:
    def __init__(self, items=None, connections=None):
        self._items = list(items or [])
        self._connections = list(connections or [])
        self.registered = []
        self.updated = []
        self.validated = False
        self.rebuilt = False
        self.unique_calls = []
        self._validation_cache_best_states = {1: True}

    def items(self):
        return list(self._items)

    def clear_all(self):
        self._items.clear()
        self._connections.clear()

    def addItem(self, item):
        self._items.append(item)

    def _register_template(self, item):
        self.registered.append(item)

    def make_unique_attribute_name(self, name):
        self.unique_calls.append(name)
        return f"{name} (unique)"

    def update_connections_for(self, item):
        self.updated.append(item)

    def validate_all(self):
        self.validated = True

    def rebuild_note_links(self):
        self.rebuilt = True

    def _connection_kind(self, conn):
        return conn._payload.get("kind", "flow")


class _FakeStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message):
        self.messages.append(message)


class _FakeWindow:
    def __init__(self, scene, chosen_path):
        self.scene = scene
        self.palette = SimpleNamespace(reset_templates=Mock())
        self._status_bar = _FakeStatusBar()
        self._chosen_path = chosen_path

    def _choose_file(self, save, title, default_name, name_filter):
        return self._chosen_path

    def statusBar(self):
        return self._status_bar


def test_export_json_writes_expected_payload(tmp_path, monkeypatch):
    attr = _FakeAttribute()
    station = _FakeStation(attr=attr)
    text = _FakeTextBlock("Info")
    connection = _FakeConnection(attr.out_port, station.attr_port, payload={"kind": "flow", "src": "a", "dst": "b"})
    scene = _FakeScene([attr, station, text], [connection])
    window = _FakeWindow(scene, str(tmp_path / "export"))

    monkeypatch.setattr(json_helper, "_ui_types", lambda: (_FakeAttribute, _FakeStation, _FakeTextBlock, _FakeConnection))

    json_helper.export_json(window)

    exported = json.loads((tmp_path / "export.json").read_text(encoding="utf-8"))
    assert exported["version"] == 1
    assert exported["attributes"][0]["node_id"] == "attr-1"
    assert exported["stations"][0]["node_id"] == "station-1"
    assert exported["textblocks"][0]["text"] == "Info"
    assert exported["connections"][0]["kind"] == "flow"
    assert window.statusBar().messages[-1].startswith("JSON gespeichert:")


def test_import_json_recreates_items_and_links(tmp_path, monkeypatch):
    data = {
        "attributes": [{"node_id": "attr-1", "name": "Attr", "x": 1, "y": 2}],
        "stations": [{"node_id": "station-1", "name": "Station", "x": 3, "y": 4, "rules": []}],
        "textblocks": [{"node_id": "text-1", "text": "Note", "x": 5, "y": 6, "linked_node_ids": ["attr-1", "station-1"]}],
        "connections": [],
    }
    json_path = tmp_path / "input.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    scene = _FakeScene()
    window = _FakeWindow(scene, str(json_path))

    monkeypatch.setattr(json_helper, "_ui_types", lambda: (_FakeAttribute, _FakeStation, _FakeTextBlock, _FakeConnection))

    ok = json_helper.import_json(window, str(json_path))

    assert ok is True
    assert any(isinstance(item, _FakeAttribute) for item in scene._items)
    assert any(isinstance(item, _FakeStation) for item in scene._items)
    assert any(isinstance(item, _FakeTextBlock) for item in scene._items)
    assert len(scene._connections) == 1
    assert scene.rebuilt is True
    assert scene.validated is True
    assert window.palette.reset_templates.called
    assert window.statusBar().messages[-1].startswith("JSON geladen:")
