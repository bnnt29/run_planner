import types
from threading import Event
from unittest.mock import Mock, patch
import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_planner.items import CONDITION_OP, EFFECT_OP, PORT_TYPE
from run_planner.validate_env import CONNECTION_KIND, FlowScene


class _DummyAttr:
    def __init__(self, node_id: str, name: str):
        self.node_id = node_id
        self.name = name


class _DummyCondition:
    def __init__(self, attribute=None, compare_attribute=None, operator=CONDITION_OP.EXISTS, value=0.0):
        self.attribute = attribute
        self.compare_attribute = compare_attribute
        self.operator = operator
        self.value = value


class _DummyEffect:
    def __init__(self, attribute=None, action=EFFECT_OP.SET, value=0.0):
        self.attribute = attribute
        self.action = action
        self.value = value


class TestValidateEnvSnapshotHelpers:
    def test_snapshot_condition_with_compare_attribute_and_enum(self):
        attr = _DummyAttr("a1", "Attr A")
        cmp_attr = _DummyAttr("a2", "Attr B")
        cond = _DummyCondition(attribute=attr, compare_attribute=cmp_attr, operator=CONDITION_OP.GREATER_EQ, value=7)

        snap = FlowScene._snapshot_condition(cond)

        assert snap["attr_id"] == "a1"
        assert snap["compare_attr_id"] == "a2"
        assert snap["op"] == CONDITION_OP.GREATER_EQ.value
        assert snap["value"] == 7.0

    def test_snapshot_condition_with_non_enum_operator(self):
        attr = _DummyAttr("a1", "Attr A")
        cond = _DummyCondition(attribute=attr, operator=">custom<", value=3)

        snap = FlowScene._snapshot_condition(cond)

        assert snap["op"] == ">custom<"

    def test_snapshot_effect_with_enum_and_string_action(self):
        attr = _DummyAttr("a1", "Attr A")

        snap_enum = FlowScene._snapshot_effect(_DummyEffect(attribute=attr, action=EFFECT_OP.ADD, value=5))
        snap_str = FlowScene._snapshot_effect(_DummyEffect(attribute=attr, action="++", value=2))

        assert snap_enum["action"] == EFFECT_OP.ADD.value
        assert snap_str["action"] == "++"

    def test_snapshot_cond_text_branches(self):
        exists_text = FlowScene._snapshot_cond_text({"attr_name": "A", "op": CONDITION_OP.EXISTS.value})
        missing_text = FlowScene._snapshot_cond_text({"attr_name": "A", "op": CONDITION_OP.NOT_EXISTS.value})
        compare_text = FlowScene._snapshot_cond_text(
            {
                "attr_name": "A",
                "compare_attr_name": "B",
                "op": CONDITION_OP.LESS_EQ.value,
            }
        )
        value_text = FlowScene._snapshot_cond_text(
            {
                "attr_name": "A",
                "op": CONDITION_OP.GREATER.value,
                "value": 3,
            }
        )

        assert "vorhanden" in exists_text
        assert "fehlt" in missing_text
        assert "⟨B⟩" in compare_text
        assert "3" in value_text

    @pytest.mark.parametrize(
        "cond,state,expected",
        [
            ({"attr_id": "x", "op": CONDITION_OP.EXISTS.value}, {"x": 1}, True),
            ({"attr_id": "x", "op": CONDITION_OP.NOT_EXISTS.value}, {"x": 0}, True),
            ({"attr_id": "x", "op": CONDITION_OP.EQUALS.value, "value": 2}, {"x": 2}, True),
            ({"attr_id": "x", "op": CONDITION_OP.NOT_EQUALS.value, "value": 2}, {"x": 3}, True),
            ({"attr_id": "x", "op": CONDITION_OP.GREATER.value, "value": 2}, {"x": 3}, True),
            ({"attr_id": "x", "op": CONDITION_OP.GREATER_EQ.value, "value": 2}, {"x": 2}, True),
            ({"attr_id": "x", "op": CONDITION_OP.LESS.value, "value": 2}, {"x": 1}, True),
            ({"attr_id": "x", "op": CONDITION_OP.LESS_EQ.value, "value": 2}, {"x": 2}, True),
            ({"attr_id": "x", "op": "UNKNOWN"}, {"x": 2}, False),
        ],
    )
    def test_snapshot_check_condition_operators(self, cond, state, expected):
        assert FlowScene._snapshot_check_condition(cond, state) is expected

    def test_snapshot_check_condition_compare_attribute_and_missing_values(self):
        cond = {
            "attr_id": "x",
            "compare_attr_id": "y",
            "op": CONDITION_OP.GREATER.value,
            "value": 999,
        }
        assert FlowScene._snapshot_check_condition(cond, {"x": 5, "y": 2}) is True
        assert FlowScene._snapshot_check_condition(cond, {"x": None, "y": 2}) is False
        assert FlowScene._snapshot_check_condition(cond, {"y": 2}) is False

    def test_snapshot_apply_effects_all_actions_present_and_missing(self):
        state = {"base": 10}
        effects = [
            {"attr_id": "add_missing", "action": EFFECT_OP.ADD.value, "value": 2},
            {"attr_id": "sub_missing", "action": EFFECT_OP.SUBTRACT.value, "value": 4},
            {"attr_id": "mul_missing", "action": EFFECT_OP.MULTIPLY.value, "value": 3},
            {"attr_id": "div_missing", "action": EFFECT_OP.DIVIDE.value, "value": 4},
            {"attr_id": "mod_missing", "action": EFFECT_OP.MOD.value, "value": 3},
            {"attr_id": "set_missing", "action": EFFECT_OP.SET.value, "value": 9},
            {"attr_id": None, "action": EFFECT_OP.SET.value, "value": 99},
            {"attr_id": "base", "action": EFFECT_OP.ADD.value, "value": 5},
            {"attr_id": "base", "action": EFFECT_OP.SUBTRACT.value, "value": 2},
            {"attr_id": "base", "action": EFFECT_OP.MULTIPLY.value, "value": 2},
            {"attr_id": "base", "action": EFFECT_OP.DIVIDE.value, "value": 13},
            {"attr_id": "base", "action": EFFECT_OP.MOD.value, "value": 5},
        ]

        result = FlowScene._snapshot_apply_effects(state, effects)

        assert result["add_missing"] == 2
        assert result["sub_missing"] == -4
        assert result["mul_missing"] == 3
        assert result["div_missing"] == 0.25
        assert result["mod_missing"] == (1 % 3)
        assert result["set_missing"] == 9
        assert "None" not in result
        assert result["base"] == (((10 + 5 - 2) * 2) / 13) % 5

    def test_snapshot_apply_effects_divide_and_mod_zero_raise(self):
        with pytest.raises(ZeroDivisionError):
            FlowScene._snapshot_apply_effects({}, [{"attr_id": "x", "action": EFFECT_OP.DIVIDE.value, "value": 0}])

        with pytest.raises(ZeroDivisionError):
            FlowScene._snapshot_apply_effects({}, [{"attr_id": "x", "action": EFFECT_OP.MOD.value, "value": 0}])


class TestValidateEnvComputeSnapshot:
    def _dummy_scene(self, generation=1):
        scene = types.SimpleNamespace()
        scene._validation_generation = generation
        scene.status_message = types.SimpleNamespace(emit=Mock())
        return scene

    def test_compute_validation_snapshot_emits_status_and_returns_result(self):
        scene = self._dummy_scene(generation=10)
        cancel_event = Event()

        def fake_compute(snapshot, cancel_event, status_emit):
            status_emit("inner")
            return {"ok": True, "snapshot": snapshot}

        with patch("run_planner.validate_env.compute_sat_validation", side_effect=fake_compute):
            result = FlowScene._compute_validation_snapshot(scene, {"a": 1}, cancel_event, generation=10)

        assert result["ok"] is True
        emitted = [call.args[0] for call in scene.status_message.emit.call_args_list]
        assert "Validierung läuft ... SAT-BMC" in emitted
        assert "inner" in emitted

    def test_compute_validation_snapshot_suppresses_stale_generation(self):
        scene = self._dummy_scene(generation=11)
        cancel_event = Event()

        def fake_compute(snapshot, cancel_event, status_emit):
            status_emit("inner")
            return {"ok": True}

        with patch("run_planner.validate_env.compute_sat_validation", side_effect=fake_compute):
            result = FlowScene._compute_validation_snapshot(scene, {"a": 1}, cancel_event, generation=10)

        assert result["ok"] is True
        scene.status_message.emit.assert_not_called()

    def test_compute_validation_snapshot_suppresses_cancelled(self):
        scene = self._dummy_scene(generation=20)
        cancel_event = Event()
        cancel_event.set()

        def fake_compute(snapshot, cancel_event, status_emit):
            status_emit("inner")
            return {"ok": True}

        with patch("run_planner.validate_env.compute_sat_validation", side_effect=fake_compute):
            result = FlowScene._compute_validation_snapshot(scene, {"a": 1}, cancel_event, generation=20)

        assert result["ok"] is True
        scene.status_message.emit.assert_not_called()

    def test_compute_validation_snapshot_cancel_during_compute(self):
        scene = self._dummy_scene(generation=30)
        cancel_event = Event()

        def fake_compute(snapshot, cancel_event, status_emit):
            status_emit("first")
            cancel_event.set()
            status_emit("second")
            return {"ok": True}

        with patch("run_planner.validate_env.compute_sat_validation", side_effect=fake_compute):
            result = FlowScene._compute_validation_snapshot(scene, {"a": 1}, cancel_event, generation=30)

        assert result["ok"] is True
        emitted = [call.args[0] for call in scene.status_message.emit.call_args_list]
        assert "Validierung läuft ... SAT-BMC" in emitted
        assert "first" in emitted
        assert "second" not in emitted


class TestValidateEnvCoreLogic:
    class _FakePort:
        def __init__(self, parent, port_type):
            self._parent = parent
            self.port_type = port_type
            self.connections = []

        def parentItem(self):
            return self._parent

        def is_output(self):
            return self.port_type in (PORT_TYPE.OUTPUT, PORT_TYPE.ATTR_OUTPUT)

        def is_input(self):
            return self.port_type in (PORT_TYPE.INPUT, PORT_TYPE.ATTR_INPUT)

    class _FakeStation:
        def __init__(self):
            self.in_port = TestValidateEnvCoreLogic._FakePort(self, PORT_TYPE.INPUT)
            self.out_port = TestValidateEnvCoreLogic._FakePort(self, PORT_TYPE.OUTPUT)
            self.attr_port = TestValidateEnvCoreLogic._FakePort(self, PORT_TYPE.ATTR_INPUT)

    class _FakeAttribute:
        def __init__(self, name="A"):
            self.name = name
            self.out_port = TestValidateEnvCoreLogic._FakePort(self, PORT_TYPE.ATTR_OUTPUT)

    class _FakeConnection:
        def __init__(self, src_port=None, dst_port=None):
            self.src_port = src_port
            self.dst_port = dst_port

    def test_attribute_name_helpers(self):
        scene = types.SimpleNamespace()
        attr_a = self._FakeAttribute(name="  Name  ")
        attr_b = self._FakeAttribute(name="name")
        scene._attribute_items = lambda: [attr_a, attr_b]
        scene._attribute_name_key = FlowScene._attribute_name_key
        scene.attribute_name_exists = lambda name, exclude_item=None: FlowScene.attribute_name_exists(scene, name, exclude_item)

        assert FlowScene._attribute_name_key("  XyZ ") == "xyz"
        assert FlowScene.attribute_name_exists(scene, " name ") is True
        assert FlowScene.attribute_name_exists(scene, " name ", exclude_item=attr_b) is True
        assert FlowScene.attribute_name_exists(scene, "", exclude_item=attr_b) is False
        assert FlowScene.make_unique_attribute_name(scene, "Name") == "Name (2)"
        assert FlowScene.make_unique_attribute_name(scene, "Unique") == "Unique"

    def test_connected_attributes_collects_unique_attribute_sources(self, monkeypatch):
        monkeypatch.setattr("run_planner.validate_env.AttributeItem", self._FakeAttribute)

        station = self._FakeStation()
        attr1 = self._FakeAttribute("A")
        attr2 = self._FakeAttribute("B")

        conn1 = self._FakeConnection(src_port=attr1.out_port, dst_port=station.attr_port)
        conn2 = self._FakeConnection(src_port=attr1.out_port, dst_port=station.attr_port)
        conn3 = self._FakeConnection(src_port=attr2.out_port, dst_port=station.attr_port)
        station.attr_port.connections = [conn1, conn2, conn3]

        scene = types.SimpleNamespace()
        connected = FlowScene._connected_attributes(scene, station)

        assert connected == [attr1, attr2]

    def test_connection_kind_branches(self, monkeypatch):
        monkeypatch.setattr("run_planner.validate_env.StationItem", self._FakeStation)
        monkeypatch.setattr("run_planner.validate_env.AttributeItem", self._FakeAttribute)

        scene = types.SimpleNamespace()
        s1 = self._FakeStation()
        s2 = self._FakeStation()
        a1 = self._FakeAttribute()

        flow = self._FakeConnection(src_port=s1.out_port, dst_port=s2.in_port)
        attr = self._FakeConnection(src_port=a1.out_port, dst_port=s2.attr_port)
        invalid = self._FakeConnection(src_port=s1.in_port, dst_port=s2.out_port)
        broken = self._FakeConnection(src_port=None, dst_port=s2.in_port)

        assert FlowScene._connection_kind(scene, flow) == CONNECTION_KIND.FLOW
        assert FlowScene._connection_kind(scene, attr) == CONNECTION_KIND.ATTRIBUTE
        assert FlowScene._connection_kind(scene, invalid) is None
        assert FlowScene._connection_kind(scene, broken) is None

    def test_can_connect_and_resolve_drop_target(self, monkeypatch):
        monkeypatch.setattr("run_planner.validate_env.StationItem", self._FakeStation)
        monkeypatch.setattr("run_planner.validate_env.AttributeItem", self._FakeAttribute)
        monkeypatch.setattr("run_planner.validate_env.Port", self._FakePort)

        scene = types.SimpleNamespace()
        scene._can_connect = lambda src, dst: FlowScene._can_connect(scene, src, dst)

        station_src = self._FakeStation()
        station_dst = self._FakeStation()
        attr_src = self._FakeAttribute()

        assert FlowScene._can_connect(scene, None, station_dst.in_port) is False
        assert FlowScene._can_connect(scene, station_src.out_port, station_src.out_port) is False
        assert FlowScene._can_connect(scene, station_src.out_port, station_dst.in_port) is True
        assert FlowScene._can_connect(scene, attr_src.out_port, station_dst.attr_port) is True
        assert FlowScene._can_connect(scene, station_src.in_port, station_dst.out_port) is False

        assert FlowScene._resolve_drop_target(scene, station_src.out_port, station_dst) is station_dst.in_port
        assert FlowScene._resolve_drop_target(scene, attr_src.out_port, station_dst) is station_dst.attr_port
        assert FlowScene._resolve_drop_target(scene, station_src.out_port, station_dst.in_port) is station_dst.in_port
        assert FlowScene._resolve_drop_target(scene, station_src.out_port, object()) is None
