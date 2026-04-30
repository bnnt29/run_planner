import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import run_planner.validate_env as validate_env_module

from run_planner.items import CONDITION_OP, EFFECT_OP, STATION_TYPE, Condition, Effect, StationRule
from run_planner.validate_env import CONNECTION_KIND, FlowScene


class _FakePort:
    def __init__(self, parent):
        self._parent = parent
        self.connections = []

    def parentItem(self):
        return self._parent


class _FakeStation:
    def __init__(self, node_id: str, name: str, station_type=STATION_TYPE.NORMAL, rules=None):
        self.node_id = node_id
        self.name = name
        self.type = station_type
        self.rules = list(rules or [])
        self.attr_port = _FakePort(self)
        self.in_port = _FakePort(self)
        self.out_port = _FakePort(self)

    def all_connections(self):
        return list(self.attr_port.connections + self.in_port.connections + self.out_port.connections)

    def _layout(self):
        self.layout_called = getattr(self, "layout_called", 0) + 1


class _FakeAttribute:
    def __init__(self, node_id: str, name: str):
        self.node_id = node_id
        self.name = name
        self.out_port = _FakePort(self)

    def all_connections(self):
        return list(self.out_port.connections)

    def _layout(self):
        self.layout_called = getattr(self, "layout_called", 0) + 1


class _FakeConnection:
    def __init__(self, src_parent, dst_parent, conditions=None, kind=CONNECTION_KIND.FLOW):
        self.src_port = _FakePort(src_parent)
        self.dst_port = _FakePort(dst_parent)
        self.conditions = list(conditions or [])
        self.kind = kind
        self.update_path = Mock()


def test_build_validation_snapshot_uses_changed_targets_for_incremental_updates(monkeypatch):
    attr = _FakeAttribute("attr-1", "Noise")
    start = _FakeStation("start", "Start", STATION_TYPE.START)
    mid = _FakeStation("mid", "Mid")
    end = _FakeStation("end", "End", STATION_TYPE.END)
    mid.rules = [StationRule([Condition(attr, CONDITION_OP.GREATER, 0)], [Effect(attr, EFFECT_OP.ADD, 1)])]

    c1 = _FakeConnection(start, mid)
    c2 = _FakeConnection(mid, end)
    start.out_port.connections = [c1]
    mid.in_port.connections = [c1]
    mid.out_port.connections = [c2]
    end.in_port.connections = [c2]

    monkeypatch.setattr(validate_env_module, "StationItem", _FakeStation)
    monkeypatch.setattr(validate_env_module, "AttributeItem", _FakeAttribute)
    monkeypatch.setattr(validate_env_module, "ConnectionItem", _FakeConnection)

    scene = SimpleNamespace(
        _station_items=lambda: [start, mid, end],
        _connections=[c1, c2],
        _validation_cache_best_states={1: True},
        _connection_kind=lambda conn: conn.kind,
            _snapshot_condition=FlowScene._snapshot_condition,
            _snapshot_effect=FlowScene._snapshot_effect,
    )

    snapshot, meta = FlowScene._build_validation_snapshot(scene, changed_targets=[mid])

    assert snapshot is not None
    assert meta is not None
    assert set(snapshot["root_ids"]) == {"start"}
    assert set(snapshot["checkpoint_ids"]) == {"end"}
    assert set(snapshot["target_conn_keys"]) == {id(c1), id(c2)}
    assert set(snapshot["target_checkpoint_ids"]) == {"end"}


def test_remove_arrow_conditions_for_attribute_name_filters_matching_connections():
    attr = _FakeAttribute("attr-1", "Noise")
    other = _FakeAttribute("attr-2", "Other")
    c1 = _FakeConnection(SimpleNamespace(), SimpleNamespace(), [Condition(attr, CONDITION_OP.EXISTS)])
    c2 = _FakeConnection(SimpleNamespace(), SimpleNamespace(), [Condition(other, CONDITION_OP.EXISTS)])
    c1.dst_port._parent = SimpleNamespace(attr_port=SimpleNamespace(connections=[]), in_port=SimpleNamespace(connections=[]), out_port=SimpleNamespace(connections=[]))
    c2.dst_port._parent = SimpleNamespace(attr_port=SimpleNamespace(connections=[]), in_port=SimpleNamespace(connections=[]), out_port=SimpleNamespace(connections=[]))
    scene = SimpleNamespace(
        _connections=[c1, c2],
        _connection_kind=lambda conn: CONNECTION_KIND.FLOW,
        _attribute_name_key=FlowScene._attribute_name_key,
        validate_all=Mock(),
    )

    removed = FlowScene.remove_arrow_conditions_for_attribute_name(scene, "noise")

    assert removed == 1
    assert len(c1.conditions) == 0
    assert len(c2.conditions) == 1
    scene.validate_all.assert_called_once()


def test_update_connections_for_traverses_related_items_once():
    a = _FakeStation("a", "A")
    b = _FakeStation("b", "B")
    conn = _FakeConnection(a, b)
    a.out_port.connections = [conn]
    b.in_port.connections = [conn]

    scene = SimpleNamespace()

    FlowScene.update_connections_for(scene, a)

    assert getattr(a, "layout_called", 0) == 1
    assert getattr(b, "layout_called", 0) == 1
    assert conn.update_path.call_count >= 1


def test_clear_all_resets_validation_state_and_clears_scene():
    cancel_event = Event()
    scene = SimpleNamespace(
        _validation_cancel_event=cancel_event,
        _connections=[1, 2],
        _validation_meta={1: "x"},
        _queued_validation=(1, {"a": 1}),
        _validation_cache_best_states={1: 2},
        _validation_cache_checkpoint_levels={2: 3},
        _emit_validation_state=Mock(),
        clear=Mock(),
    )

    FlowScene.clear_all(scene)

    assert cancel_event.is_set() is True
    assert scene._connections == []
    assert scene._validation_meta == {}
    assert scene._queued_validation is None
    assert scene._validation_cache_best_states == {}
    assert scene._validation_cache_checkpoint_levels == {}
    scene.clear.assert_called_once()
    scene._emit_validation_state.assert_called_once()
