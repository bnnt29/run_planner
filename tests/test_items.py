import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_planner.items import CONDITION_OP, EFFECT_OP, Condition, ConnectionItem, Effect, StationItem, StationRule


class DummyAttr:
    def __init__(self, node_id: str, name: str):
        self.node_id = node_id
        self.name = name

def test_station_item_deserializers_ignore_missing_nodes():
    attr = DummyAttr("a1", "Attr A")
    cond_data = {"attribute": "a1", "compare_attribute": "a2", "operator": CONDITION_OP.EXISTS.value}
    eff_data = {"attribute": "a1", "action": EFFECT_OP.SET.value, "value": 7}

    cond = StationItem._deserialize_condition(cond_data, {"a1": attr})
    eff = StationItem._deserialize_effect(eff_data, {"a1": attr})

    assert cond is not None
    assert cond.attribute is attr
    assert StationItem._deserialize_condition({"attribute": "missing"}, {"a1": attr}) is None
    assert eff is not None
    assert eff.attribute is attr
    assert StationItem._deserialize_effect({"attribute": "missing"}, {"a1": attr}) is None


def test_station_display_name_appends_id_only_in_debug_mode():
    station = SimpleNamespace(name="Start", node_id="station-42", scene=lambda: None)

    assert StationItem._display_name(station) == "Start"

    station.scene = lambda: SimpleNamespace(show_debug_identifiers=True)
    assert StationItem._display_name(station) == "Start [station_id=station-42]"
    assert station.name == "Start"


def test_connection_display_name_appends_path_identifiers_only_for_debug_view():
    class _Conn:
        def __init__(self, name: str):
            self.name = name

        _debug_suffix = ConnectionItem._debug_suffix

    conn = _Conn("Pfad A")
    scene = SimpleNamespace(show_debug_identifiers=True, get_debug_path_number=lambda _conn: 7)

    label = ConnectionItem._display_name(conn, scene)

    assert label.startswith("Pfad A [path_id=")
    assert ", path_no=7]" in label
    assert conn.name == "Pfad A"


def test_connection_to_json_uses_raw_name_without_debug_suffix():
    src_parent = SimpleNamespace(node_id="src")
    dst_parent = SimpleNamespace(node_id="dst")
    src_port = SimpleNamespace(parentItem=lambda: src_parent, port_type=SimpleNamespace(value="output"))
    dst_port = SimpleNamespace(parentItem=lambda: dst_parent, port_type=SimpleNamespace(value="input"))
    conn = SimpleNamespace(src_port=src_port, dst_port=dst_port, name="NurName", conditions=[])

    payload = ConnectionItem.to_json(conn)

    assert payload["name"] == "NurName"
