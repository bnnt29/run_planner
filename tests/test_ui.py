import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_planner import ui


class _FakeAttr:
    def __init__(self, node_id: str, name: str):
        self.node_id = node_id
        self.name = name


class _FakeDropdown:
    def __init__(self):
        self.entries = []
        self.current_index = 0

    def clear(self):
        self.entries.clear()

    def addItem(self, text, data):
        self.entries.append((text, data))

    def findData(self, data):
        for idx, (_, value) in enumerate(self.entries):
            if value is data:
                return idx
        return -1

    def setCurrentIndex(self, index):
        self.current_index = index

    def count(self):
        return len(self.entries)

    def itemText(self, index):
        return self.entries[index][0]

    def currentData(self):
        return self.entries[self.current_index][1]


def test_fill_attribute_dropdown_deduplicates_and_selects_existing(monkeypatch):
    monkeypatch.setattr(ui, "AttributeItem", _FakeAttr)

    dropdown = _FakeDropdown()
    attr_a = _FakeAttr("a1", "Alpha")
    attr_b = _FakeAttr("a2", "Beta")

    ui.fill_attribute_dropdown(dropdown, attr_b, [attr_a, attr_b, attr_b])

    assert dropdown.count() == 2
    assert dropdown.currentData() is attr_b
    assert dropdown.itemText(0) == "Alpha"
    assert dropdown.itemText(1) == "Beta"


def test_fill_attribute_dropdown_adds_selected_when_missing(monkeypatch):
    monkeypatch.setattr(ui, "AttributeItem", _FakeAttr)

    dropdown = _FakeDropdown()
    attr_a = _FakeAttr("a1", "Alpha")
    selected = _FakeAttr("a9", "Selected")

    ui.fill_attribute_dropdown(dropdown, selected, [attr_a])

    assert dropdown.count() == 2
    assert dropdown.currentData() is selected


def test_get_debug_path_number_matches_stable_sorted_order():
    class _Node:
        def __init__(self, node_id: str):
            self.node_id = node_id

    class _Port:
        def __init__(self, node_id: str):
            self._node = _Node(node_id)

        def parentItem(self):
            return self._node

    class _Conn:
        def __init__(self, src_id: str, dst_id: str):
            self.src_port = _Port(src_id)
            self.dst_port = _Port(dst_id)

    flow_first = _Conn("A", "B")
    flow_second = _Conn("A", "C")
    attr_conn = _Conn("X", "Y")

    fake_scene = SimpleNamespace(
        _connections=[flow_second, attr_conn, flow_first],
        _connection_kind=lambda conn: ui.CONNECTION_KIND.FLOW if conn is not attr_conn else ui.CONNECTION_KIND.ATTRIBUTE,
    )

    assert ui.FlowScene.get_debug_path_number(fake_scene, flow_first) == 1
    assert ui.FlowScene.get_debug_path_number(fake_scene, flow_second) == 2
    assert ui.FlowScene.get_debug_path_number(fake_scene, attr_conn) is None


def test_set_show_debug_identifiers_syncs_actions_and_scene_state():
    class _Action:
        def __init__(self):
            self._checked = False
            self._blocked = False

        def isChecked(self):
            return self._checked

        def blockSignals(self, value):
            self._blocked = bool(value)

        def setChecked(self, value):
            self._checked = bool(value)

    class _Station:
        def __init__(self):
            self.layout_calls = 0
            self.update_calls = 0

        def _layout(self):
            self.layout_calls += 1

        def update(self):
            self.update_calls += 1

    class _Connection:
        def __init__(self):
            self.update_calls = 0

        def update(self):
            self.update_calls += 1

    class _Viewport:
        def __init__(self):
            self.update_calls = 0

        def update(self):
            self.update_calls += 1

    class _View:
        def __init__(self):
            self._viewport = _Viewport()

        def viewport(self):
            return self._viewport

    class _StatusBar:
        def __init__(self):
            self.messages = []

        def showMessage(self, message):
            self.messages.append(message)

    station = _Station()
    conn = _Connection()
    scene = SimpleNamespace(
        show_debug_identifiers=False,
        _connections=[conn],
        _station_items=lambda: [station],
        update_connections_for=lambda _item: None,
    )
    action = _Action()
    status = _StatusBar()
    fake_window = SimpleNamespace(
        _show_debug_identifiers=False,
        _show_debug_identifiers_actions=[action],
        scene=scene,
        view=_View(),
        statusBar=lambda: status,
    )

    ui.MainWindow._set_show_debug_identifiers(fake_window, True)

    assert fake_window._show_debug_identifiers is True
    assert scene.show_debug_identifiers is True
    assert action.isChecked() is True
    assert station.layout_calls == 1
    assert station.update_calls == 1
    assert conn.update_calls == 1
    assert status.messages[-1] == "ID-Debug aktiviert"
