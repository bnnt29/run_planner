"""
Comprehensive test framework for sat_validation.py

Tests cover:
1. Helper functions (_check_condition, condition compilation, etc.)
2. Core validation logic (state transitions, reachability)
3. Condition evaluation (all operators)
4. Edge cases and error handling
5. CONNECTION_STATE classification logic
6. Performance and memory optimizations
"""

import pytest
import sys
import os
from pathlib import Path
from collections import deque
from unittest.mock import Mock, patch, MagicMock

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_planner.sat_validation import (
    _is_cancelled,
    _safe_status_emit,
    _to_float,
    _check_condition,
    _compile_condition,
    _check_condition_compiled,
    _condition_implies_condition,
    _apply_effects_compiled,
    _apply_effects,
    _graph_reverse,
    _graph_can_reach_checkpoint,
    _graph_strongly_connected_components,
    _graph_nodes_in_cycles,
    _sanitize_symbol,
    _build_nusmv_model,
    _write_nusmv_file,
    _find_nusmv_binary,
    _run_single_nusmv_reachability,
    _run_nusmv_reachability,
    compute_sat_validation,
)
from run_planner.items import CONNECTION_STATE, CONDITION_OP


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Helper Function Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestHelperFunctions:
    """Test basic utility functions"""

    def test_is_cancelled_with_none_event(self):
        """None event should not be cancelled"""
        assert _is_cancelled(None) is False

    def test_is_cancelled_with_set_event(self):
        """Set event should return True"""
        event = Mock()
        event.is_set.return_value = True
        assert _is_cancelled(event) is True

    def test_is_cancelled_with_unset_event(self):
        """Unset event should return False"""
        event = Mock()
        event.is_set.return_value = False
        assert _is_cancelled(event) is False

    def test_safe_status_emit_with_none(self):
        """None emit should not raise"""
        _safe_status_emit(None, "test message")  # Should not raise

    def test_safe_status_emit_with_callable(self):
        """Callable should be invoked"""
        emit = Mock()
        _safe_status_emit(emit, "test message")
        emit.assert_called_once_with("test message")

    def test_safe_status_emit_with_exception(self):
        """Exception in emit should be caught"""
        emit = Mock(side_effect=Exception("Test error"))
        _safe_status_emit(emit, "test message")  # Should not raise

    def test_to_float_with_valid_number(self):
        """Valid numbers should convert correctly"""
        assert _to_float(42) == 42.0
        assert _to_float("3.14") == 3.14
        assert _to_float(0) == 0.0

    def test_to_float_with_invalid_input(self):
        """Invalid inputs should return 0.0"""
        assert _to_float("invalid") == 0.0
        assert _to_float(None) == 0.0
        assert _to_float({}) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Condition Evaluation Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestConditionEvaluation:
    """Test condition checking logic"""

    def test_condition_exists_true(self):
        """EXISTS operator should return True when attribute > 0"""
        cond = {"attr_id": "attr1", "op": CONDITION_OP.EXISTS.value}
        state = {"attr1": 5.0}
        assert _check_condition(cond, state) is True

    def test_condition_exists_false(self):
        """EXISTS operator should return False when attribute == 0"""
        cond = {"attr_id": "attr1", "op": CONDITION_OP.EXISTS.value}
        state = {"attr1": 0.0}
        assert _check_condition(cond, state) is False

    def test_condition_not_exists_true(self):
        """NOT_EXISTS operator should return True when attribute == 0"""
        cond = {"attr_id": "attr1", "op": CONDITION_OP.NOT_EXISTS.value}
        state = {"attr1": 0.0}
        assert _check_condition(cond, state) is True

    def test_condition_not_exists_false(self):
        """NOT_EXISTS operator should return False when attribute > 0"""
        cond = {"attr_id": "attr1", "op": CONDITION_OP.NOT_EXISTS.value}
        state = {"attr1": 5.0}
        assert _check_condition(cond, state) is False

    def test_condition_equals_true(self):
        """EQUALS operator should match exact values"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.EQUALS.value}
        state = {"attr1": 5.0}
        assert _check_condition(cond, state) is True

    def test_condition_equals_false(self):
        """EQUALS operator should not match different values"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.EQUALS.value}
        state = {"attr1": 3.0}
        assert _check_condition(cond, state) is False

    def test_condition_not_equals_true(self):
        """NOT_EQUALS operator should return True for different values"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.NOT_EQUALS.value}
        state = {"attr1": 3.0}
        assert _check_condition(cond, state) is True

    def test_condition_not_equals_false(self):
        """NOT_EQUALS operator should return False for equal values"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.NOT_EQUALS.value}
        state = {"attr1": 5.0}
        assert _check_condition(cond, state) is False

    def test_condition_greater_true(self):
        """GREATER operator should correctly compare"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.GREATER.value}
        state = {"attr1": 10.0}
        assert _check_condition(cond, state) is True

    def test_condition_greater_false(self):
        """GREATER operator should return False when not greater"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.GREATER.value}
        state = {"attr1": 3.0}
        assert _check_condition(cond, state) is False

    def test_condition_greater_eq_equal(self):
        """GREATER_EQ operator should return True when equal"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.GREATER_EQ.value}
        state = {"attr1": 5.0}
        assert _check_condition(cond, state) is True

    def test_condition_greater_eq_greater(self):
        """GREATER_EQ operator should return True when greater"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.GREATER_EQ.value}
        state = {"attr1": 10.0}
        assert _check_condition(cond, state) is True

    def test_condition_less_true(self):
        """LESS operator should correctly compare"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.LESS.value}
        state = {"attr1": 3.0}
        assert _check_condition(cond, state) is True

    def test_condition_less_false(self):
        """LESS operator should return False when not less"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.LESS.value}
        state = {"attr1": 10.0}
        assert _check_condition(cond, state) is False

    def test_condition_less_eq_equal(self):
        """LESS_EQ operator should return True when equal"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.LESS_EQ.value}
        state = {"attr1": 5.0}
        assert _check_condition(cond, state) is True

    def test_condition_less_eq_less(self):
        """LESS_EQ operator should return True when less"""
        cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.LESS_EQ.value}
        state = {"attr1": 3.0}
        assert _check_condition(cond, state) is True

    def test_condition_compare_attribute_exists(self):
        """Conditions can compare two attributes"""
        cond = {
            "attr_id": "attr1",
            "compare_attr_id": "attr2",
            "op": CONDITION_OP.EQUALS.value,
        }
        state = {"attr1": 5.0, "attr2": 5.0}
        assert _check_condition(cond, state) is True

    def test_condition_compare_attribute_not_equal(self):
        """Conditions should correctly compare different attributes"""
        cond = {
            "attr_id": "attr1",
            "compare_attr_id": "attr2",
            "op": CONDITION_OP.EQUALS.value,
        }
        state = {"attr1": 5.0, "attr2": 3.0}
        assert _check_condition(cond, state) is False

    def test_condition_missing_attribute(self):
        """Missing attributes should default to 0.0"""
        cond = {"attr_id": "missing", "op": CONDITION_OP.EXISTS.value}
        state = {"other": 5.0}
        assert _check_condition(cond, state) is False

    def test_condition_unknown_operator(self):
        """Unknown operators should return False"""
        cond = {"attr_id": "attr1", "op": "UNKNOWN_OP"}
        state = {"attr1": 5.0}
        assert _check_condition(cond, state) is False

    def test_condition_default_operator(self):
        """Missing operator should default to EXISTS"""
        cond = {"attr_id": "attr1"}
        state = {"attr1": 5.0}
        assert _check_condition(cond, state) is True


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Condition Compilation Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestConditionCompilation:
    """Test condition compilation and compiled evaluation"""

    def test_compile_condition_basic(self):
        """Conditions should compile correctly"""
        cond = {
            "attr_id": "attr1",
            "compare_attr_id": "attr2",
            "op": CONDITION_OP.GREATER.value,
            "value": 5.0,
        }
        compiled = _compile_condition(cond)
        assert compiled == ("attr1", "attr2", CONDITION_OP.GREATER.value, 5.0)

    def test_compile_condition_missing_fields(self):
        """Compilation should handle missing fields"""
        cond = {"attr_id": "attr1"}
        compiled = _compile_condition(cond)
        assert compiled == ("attr1", None, CONDITION_OP.EXISTS.value, 0.0)

    def test_compiled_condition_evaluation_matches_original(self):
        """Compiled and original evaluation should match"""
        cond = {
            "attr_id": "attr1",
            "value": 5.0,
            "op": CONDITION_OP.GREATER.value,
        }
        compiled = _compile_condition(cond)
        state = {"attr1": 10.0}

        original_result = _check_condition(cond, state)
        compiled_result = _check_condition_compiled(compiled, state)

        assert original_result == compiled_result

    def test_compiled_all_operators(self):
        """All operators should work with compiled evaluation"""
        operators = [
            CONDITION_OP.EXISTS.value,
            CONDITION_OP.NOT_EXISTS.value,
            CONDITION_OP.EQUALS.value,
            CONDITION_OP.NOT_EQUALS.value,
            CONDITION_OP.GREATER.value,
            CONDITION_OP.GREATER_EQ.value,
            CONDITION_OP.LESS.value,
            CONDITION_OP.LESS_EQ.value,
        ]

        for op in operators:
            cond = {
                "attr_id": "attr1",
                "value": 5.0,
                "op": op,
            }
            compiled = _compile_condition(cond)
            state = {"attr1": 10.0}

            # Both should work without raising
            _check_condition(cond, state)
            _check_condition_compiled(compiled, state)

    def test_compiled_condition_with_compare_attribute_greater(self):
        """Compiled conditions should honor compare_attr_id on greater-than checks"""
        cond = {
            "attr_id": "source",
            "compare_attr_id": "threshold",
            "op": CONDITION_OP.GREATER.value,
        }
        compiled = _compile_condition(cond)
        state = {"source": 7.5, "threshold": 4.0}

        assert _check_condition(cond, state) is True
        assert _check_condition_compiled(compiled, state) is True

    def test_compiled_condition_unknown_operator_false(self):
        """Compiled conditions should reject unknown operators"""
        cond = {"attr_id": "attr1", "op": "DOES_NOT_EXIST"}
        compiled = _compile_condition(cond)
        state = {"attr1": 99.0}

        assert _check_condition(cond, state) is False
        assert _check_condition_compiled(compiled, state) is False


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3B: Internal Helper Coverage Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestInternalHelperCoverage:
    """Test internal helper logic that is otherwise only hit in complex runtime paths"""

    def test_condition_implies_condition_with_compare_attribute_is_false(self):
        """Any comparison involving compare_attr_id should be rejected by the conservative collapse logic"""
        source = _compile_condition({
            "attr_id": "a",
            "compare_attr_id": "b",
            "op": CONDITION_OP.GREATER.value,
            "value": 1,
        })
        target = _compile_condition({
            "attr_id": "a",
            "op": CONDITION_OP.EXISTS.value,
        })

        assert _condition_implies_condition(source, target) is False

    def test_condition_implies_condition_supported_paths(self):
        """Exercise the positive implication branches for the supported comparisons"""
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.GREATER.value, "value": 2}),
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.EXISTS.value}),
        ) is True
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.GREATER_EQ.value, "value": 1}),
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.EXISTS.value}),
        ) is True
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.EQUALS.value, "value": 5}),
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.GREATER.value, "value": 4}),
        ) is True
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.EQUALS.value, "value": 5}),
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.GREATER_EQ.value, "value": 5}),
        ) is True
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.EQUALS.value, "value": 2}),
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.LESS.value, "value": 3}),
        ) is True
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.EQUALS.value, "value": 2}),
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.LESS_EQ.value, "value": 2}),
        ) is True
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.EQUALS.value, "value": 5}),
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.NOT_EQUALS.value, "value": 4}),
        ) is True
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.EQUALS.value, "value": 0}),
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.NOT_EXISTS.value}),
        ) is True

    def test_condition_implies_condition_negative_paths(self):
        """Exercise the conservative false branches for implication checks"""
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.LESS.value, "value": 2}),
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.EXISTS.value}),
        ) is False
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.GREATER.value, "value": 2}),
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.NOT_EQUALS.value, "value": 2}),
        ) is False
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.NOT_EQUALS.value, "value": 5}),
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.EXISTS.value}),
        ) is False
        assert _condition_implies_condition(
            _compile_condition({"attr_id": "a", "op": CONDITION_OP.EXISTS.value}),
            _compile_condition({"attr_id": "b", "op": CONDITION_OP.EXISTS.value}),
        ) is False

    def test_apply_effects_compiled_all_arithmetic_branches(self):
        """Compiled effects should cover all arithmetic and default branches"""
        base = {"x": 10.0}
        effects = [
            ("x", "+", 5.0),
            ("x", "-", 3.0),
            ("x", "*", 2.0),
            ("x", "/", 4.0),
            ("x", "%", 2.0),
            ("y", "=", 7.0),
            (None, "+", 1.0),
        ]

        result = _apply_effects_compiled(base, effects)
        assert result["x"] == 0.0
        assert result["y"] == 7.0
        assert base == {"x": 10.0}

    def test_apply_effects_compiled_skip_zero_division(self):
        """Division and modulo by zero should leave the current value untouched"""
        result = _apply_effects_compiled({"x": 9.0}, [("x", "/", 0.0), ("x", "%", 0.0)])
        assert result["x"] == 9.0

    def test_apply_effects_dict_version(self):
        """The dictionary-based effect helper should follow the same update branches"""
        result = _apply_effects(
            {"x": 2.0},
            [
                {"attr_id": "x", "action": "+", "value": 3},
                {"attr_id": "x", "action": "-", "value": 1},
                {"attr_id": "x", "action": "*", "value": 4},
                {"attr_id": "x", "action": "/", "value": 2},
                {"attr_id": "x", "action": "%", "value": 3},
                {"attr_id": "y", "action": "=", "value": 8},
                {"attr_id": None, "action": "=", "value": 1},
            ],
        )
        assert result["x"] == 2.0
        assert result["y"] == 8.0

    def test_graph_reverse_and_reachability(self):
        """Graph reverse and checkpoint reachability should follow the backward closure"""
        flow_succs = {
            "a": [(1, "b")],
            "b": [(2, "c")],
            "d": [(3, "c")],
        }
        reversed_graph = _graph_reverse(flow_succs)
        reachable = _graph_can_reach_checkpoint(flow_succs, {"c"})

        assert reversed_graph["b"] == ["a"]
        assert set(reversed_graph["c"]) == {"b", "d"}
        assert reachable == {"a", "b", "c", "d"}

    def test_graph_nodes_in_cycles_detects_scc_and_self_loop(self):
        """Cycle detection should include SCC members and explicit self-loops only."""
        flow_succs = {
            "a": [(1, "b")],
            "b": [(2, "c")],
            "c": [(3, "a")],  # SCC a-b-c
            "d": [(4, "d")],  # self loop
            "e": [(5, "f")],  # acyclic chain
        }

        cycles = _graph_nodes_in_cycles(flow_succs)

        assert {"a", "b", "c", "d"}.issubset(cycles)
        assert "e" not in cycles
        assert "f" not in cycles

    def test_graph_strongly_connected_components_returns_component_ids(self):
        """SCC analysis should group cyclic nodes and keep acyclic nodes separate."""
        flow_succs = {
            "a": [(1, "b")],
            "b": [(2, "a")],
            "c": [(3, "d")],
            "d": [],
        }

        component_by_node, components, cyclic_component_ids = _graph_strongly_connected_components(flow_succs)

        assert component_by_node["a"] == component_by_node["b"]
        assert component_by_node["c"] != component_by_node["d"]
        assert any(set(components[cid]) == {"a", "b"} for cid in cyclic_component_ids)
        assert all("c" not in components[cid] for cid in cyclic_component_ids)

    def test_sanitize_symbol_and_nusmv_model(self):
        """Sanitizing symbols and building the NuSMV model should cover the model text path"""
        assert _sanitize_symbol("hello world!") == "hello_world"
        assert _sanitize_symbol("!!!") == "id"

        snapshot = {
            "station_data": {"start node": {"rules": []}, "end-node": {"rules": []}},
            "root_ids": ["start node"],
            "checkpoint_ids": ["end-node"],
            "flow_succs": {"start node": [(1, "end-node")]},
        }
        model = _build_nusmv_model(snapshot)
        assert "MODULE main" in model
        assert "DEFINE end_end_node" in model
        assert "n_start_node" in model

    def test_build_nusmv_model_without_station_data(self):
        """An empty snapshot should still generate a minimal dead-state model"""
        model = _build_nusmv_model({})
        assert "n_dead" in model
        assert "init(node) := {n_dead}" in model

    def test_write_nusmv_file_and_find_binary(self):
        """Writing the model file should yield a readable temp path and binary lookup should be harmless"""
        snapshot = {
            "station_data": {"s": {"rules": []}},
            "root_ids": ["s"],
            "checkpoint_ids": ["s"],
            "flow_succs": {},
        }
        path = _write_nusmv_file(snapshot)
        assert path is not None
        assert os.path.exists(path)
        assert _find_nusmv_binary() is None or isinstance(_find_nusmv_binary(), str)
        os.remove(path)

    def test_find_nusmv_binary_prefers_local_repo_path(self):
        """The repository-local ./NuSVm/bin/NuSVM should be preferred over PATH binaries."""
        local_path = "/repo/NuSVm/bin/NuSVM"
        with patch("run_planner.sat_validation.os.getcwd", return_value="/repo"):
            with patch("run_planner.sat_validation.os.path.dirname", return_value="/repo/src/run_planner"):
                with patch("run_planner.sat_validation.os.path.abspath", side_effect=lambda value: value):
                    with patch("run_planner.sat_validation.os.path.isfile", side_effect=lambda value: value == local_path):
                        with patch("run_planner.sat_validation.shutil.which", return_value="/usr/bin/nusmv"):
                            found = _find_nusmv_binary()
        assert found == local_path

    def test_run_single_nusmv_reachability_true_and_false_outputs(self):
        """The single-check helper should parse true/false outputs correctly"""

        class DummyResult:
            def __init__(self, stdout: str, stderr: str = ""):
                self.stdout = stdout
                self.stderr = stderr

        with patch("run_planner.sat_validation.subprocess.run", return_value=DummyResult("is true")):
            assert _run_single_nusmv_reachability("/bin/echo", "/tmp/model.smv", "c1") == ("c1", True)

        with patch("run_planner.sat_validation.subprocess.run", return_value=DummyResult("is false")):
            assert _run_single_nusmv_reachability("/bin/echo", "/tmp/model.smv", "c1") == ("c1", False)

    def test_run_single_nusmv_reachability_exception_branch(self):
        """Exception handling in the single-check helper should return None"""
        with patch("run_planner.sat_validation.subprocess.run", side_effect=RuntimeError("boom")):
            assert _run_single_nusmv_reachability("/bin/echo", "/tmp/model.smv", "c1") is None

    def test_run_nusmv_reachability_empty_inputs(self):
        """Empty checkpoint lists should short-circuit the reachability helper"""
        assert _run_nusmv_reachability("/tmp/does-not-matter.smv", []) == {}

    def test_run_nusmv_reachability_sequential_and_parallel_branches(self):
        """Both sequential and threaded reachability paths should be exercised"""
        with patch("run_planner.sat_validation._find_nusmv_binary", return_value="/bin/echo"):
            with patch("run_planner.sat_validation._run_single_nusmv_reachability", side_effect=[("a", True), ("b", False)]):
                sequential = _run_nusmv_reachability("/tmp/model.smv", ["a", "b"], max_workers=1)
                assert sequential == {"a": True, "b": False}

        with patch("run_planner.sat_validation._find_nusmv_binary", return_value="/bin/echo"):
            with patch("run_planner.sat_validation._run_single_nusmv_reachability", side_effect=[("a", True), ("b", True)]):
                parallel = _run_nusmv_reachability("/tmp/model.smv", ["a", "b"], max_workers=2)
                assert parallel == {"a": True, "b": True}

    def test_run_nusmv_reachability_cancelled_before_iteration(self):
        """A cancelled event should stop the reachability scan early"""
        cancel_event = Mock()
        cancel_event.is_set.return_value = True
        with patch("run_planner.sat_validation._find_nusmv_binary", return_value="/bin/echo"):
            with patch("run_planner.sat_validation._run_single_nusmv_reachability", return_value=("a", True)):
                result = _run_nusmv_reachability("/tmp/model.smv", ["a", "b"], cancel_event=cancel_event, max_workers=1)
                assert result == {}

    def test_run_nusmv_reachability_binary_missing(self):
        """Missing NuSMV binaries should return an empty result set"""
        with patch("run_planner.sat_validation._find_nusmv_binary", return_value=None):
            assert _run_nusmv_reachability("/tmp/model.smv", ["a"]) == {}

    def test_compute_sat_validation_with_nusmv_metrics(self):
        """A mocked NuSMV path should reach the metrics code that records binary availability"""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [90],
            "target_conn_keys": [90],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(90, "end")]},
            "flow_conn_conditions": {},
            "connection_kinds": {90: "FLOW"},
            "keep_smv_file": True,
        }
        with patch("run_planner.sat_validation._find_nusmv_binary", return_value="/bin/echo"):
            with patch("run_planner.sat_validation._write_nusmv_file", return_value="/tmp/fake_model.smv"):
                with patch("run_planner.sat_validation._run_nusmv_reachability", return_value={"end": True}):
                    result = compute_sat_validation(snapshot)

        assert result["metrics"]["nusmv_available"] is True
        assert result["metrics"]["nusmv_checkpoint_reachable"] == 1
        assert result["metrics"]["smv_file"] == "/tmp/fake_model.smv"
        assert result["best_states"][90][0] == CONNECTION_STATE.VALID

    def test_run_single_nusmv_reachability_failure_path(self):
        """An invalid binary path should fall back to None and exercise the exception handler"""
        assert _run_single_nusmv_reachability("/definitely/not/a/binary", "/tmp/nope.smv", "c1") is None


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Core Validation Logic Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoreValidationLogic:
    """Test the main validation computation"""

    def test_empty_snapshot(self):
        """Empty snapshot should return valid structure"""
        snapshot = {
            "station_data": {},
            "root_ids": [],
            "flow_conn_keys": [],
            "target_conn_keys": [],
            "checkpoint_ids": [],
            "target_checkpoint_ids": [],
            "flow_succs": {},
            "flow_conn_conditions": {},
        }
        result = compute_sat_validation(snapshot)

        assert isinstance(result, dict)
        assert "best_states" in result
        assert "checkpoint_levels" in result
        assert "metrics" in result
        assert result["best_states"] == {}

    def test_no_root_stations(self):
        """No root stations should return empty result"""
        snapshot = {
            "station_data": {"s1": {"rules": []}},
            "root_ids": [],  # No roots
            "flow_conn_keys": [],
            "target_conn_keys": [],
            "checkpoint_ids": [],
            "target_checkpoint_ids": [],
            "flow_succs": {},
            "flow_conn_conditions": {},
        }
        result = compute_sat_validation(snapshot)

        assert result["best_states"] == {}

    def test_single_connection_valid_path(self):
        """Simple valid path from root to checkpoint"""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [0],
            "target_conn_keys": [0],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(0, "end")]},
            "flow_conn_conditions": {0: []},
            "connection_kinds": {0: "FLOW"},
            "max_depth": 200,
        }
        result = compute_sat_validation(snapshot)

        assert "best_states" in result
        assert 0 in result["best_states"]
        state, reasons = result["best_states"][0]
        assert state == CONNECTION_STATE.VALID
        assert isinstance(reasons, list)
        assert len(reasons) > 0

    def test_ruleless_static_graph_mode_handles_large_chain(self):
        """Ruleless graphs should use the static fast path and still classify paths correctly."""
        n = 120
        station_data = {f"s{i}": {"rules": []} for i in range(n)}
        flow_conn_keys = list(range(n - 1))
        flow_succs = {f"s{i}": [(i, f"s{i + 1}")] for i in range(n - 1)}

        snapshot = {
            "station_data": station_data,
            "root_ids": ["s0"],
            "flow_conn_keys": flow_conn_keys,
            "target_conn_keys": flow_conn_keys,
            "checkpoint_ids": [f"s{n - 1}"],
            "target_checkpoint_ids": [f"s{n - 1}"],
            "flow_succs": flow_succs,
            "flow_conn_conditions": {},
            "connection_kinds": {k: "FLOW" for k in flow_conn_keys},
        }

        result = compute_sat_validation(snapshot)

        assert result["metrics"]["mode"] == "nu-smv+static-graph"
        assert all(result["best_states"][k][0] == CONNECTION_STATE.VALID for k in flow_conn_keys)
        assert result["checkpoint_levels"][f"s{n - 1}"] == [0]

    def test_ruleless_static_graph_respects_unsatisfied_conditions(self):
        """Ruleless static path must mark condition-failed edges as INVALID."""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [101],
            "target_conn_keys": [101],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(101, "end")]},
            "flow_conn_conditions": {
                101: [
                    {
                        "attr_id": "missing_attr",
                        "op": CONDITION_OP.EXISTS.value,
                    }
                ]
            },
            "connection_kinds": {101: "FLOW"},
        }

        result = compute_sat_validation(snapshot)

        assert result["metrics"]["mode"] == "nu-smv+static-graph"
        assert result["best_states"][101][0] == CONNECTION_STATE.INVALID
        assert any("bedingungen" in reason.lower() for reason in result["best_states"][101][1])

    def test_connection_with_conditions(self):
        """Connection with unsatisfiable conditions should be INVALID or CONDITIONAL_INVALID"""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [0],
            "target_conn_keys": [0],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(0, "end")]},
            "flow_conn_conditions": {
                0: [
                    {
                        "attr_id": "attr1",
                        "op": CONDITION_OP.EXISTS.value,
                    }
                ]
            },
            "connection_kinds": {0: "FLOW"},
            "max_depth": 200,
        }
        result = compute_sat_validation(snapshot)

        assert "best_states" in result
        # Connection with unsatisfied conditions on unreachable attributes
        # should be classified as INVALID since the condition cannot be met
        if 0 in result["best_states"]:
            state, reasons = result["best_states"][0]
            # With no rules providing attr1, condition cannot be satisfied
            assert state == CONNECTION_STATE.INVALID

    def test_cancelled_validation(self):
        """Cancelled validation should return early"""
        cancel_event = Mock()
        cancel_event.is_set.return_value = True

        snapshot = {
            "station_data": {"start": {"rules": []}},
            "root_ids": ["start"],
            "flow_conn_keys": [],
            "target_conn_keys": [],
            "checkpoint_ids": [],
            "target_checkpoint_ids": [],
            "flow_succs": {},
            "flow_conn_conditions": {},
        }

        result = compute_sat_validation(snapshot, cancel_event=cancel_event)
        assert result.get("cancelled") is True

    def test_metrics_in_result(self):
        """Result should include validation metrics"""
        snapshot = {
            "station_data": {"s1": {"rules": []}},
            "root_ids": ["s1"],
            "flow_conn_keys": [1, 2, 3],
            "target_conn_keys": [1, 2],
            "checkpoint_ids": ["c1", "c2"],
            "target_checkpoint_ids": ["c1"],
            "flow_succs": {},
            "flow_conn_conditions": {},
        }
        result = compute_sat_validation(snapshot)

        metrics = result.get("metrics", {})
        assert "duration_ms" in metrics
        assert metrics["total_flow"] == 3
        assert metrics["target_flow"] == 2
        assert metrics["total_checkpoints"] == 2
        assert metrics["target_checkpoints"] == 1

    def test_rule_effect_enables_connection_condition(self):
        """A station rule should activate a connection condition via its effect"""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "gate_open", "action": "=", "value": 1},
                            ],
                        }
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [10],
            "target_conn_keys": [10],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(10, "end")]},
            "flow_conn_conditions": {
                10: [
                    {
                        "attr_id": "gate_open",
                        "op": CONDITION_OP.EXISTS.value,
                    }
                ]
            },
            "connection_kinds": {10: "FLOW"},
        }
        result = compute_sat_validation(snapshot)

        assert 10 in result["best_states"]
        state, reasons = result["best_states"][10]
        assert state == CONNECTION_STATE.CONDITIONAL_VALID
        assert reasons
        assert any("bedingungenabhängig" in reason.lower() for reason in reasons)

    def test_rule_effect_with_arithmetic_update(self):
        """Arithmetic effects should be visible to downstream connection checks"""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "score", "action": "+", "value": 2},
                            ],
                        }
                    ]
                },
                "mid": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [11],
            "target_conn_keys": [11],
            "checkpoint_ids": ["mid"],
            "target_checkpoint_ids": ["mid"],
            "flow_succs": {"start": [(11, "mid")]},
            "flow_conn_conditions": {
                11: [
                    {
                        "attr_id": "score",
                        "value": 2,
                        "op": CONDITION_OP.EQUALS.value,
                    }
                ]
            },
            "connection_kinds": {11: "FLOW"},
        }
        result = compute_sat_validation(snapshot)

        assert 11 in result["best_states"]
        state, reasons = result["best_states"][11]
        assert state == CONNECTION_STATE.CONDITIONAL_VALID
        assert reasons
        assert any("gültigen pfad" in reason.lower() for reason in reasons)

    def test_multi_rule_branching_with_multiple_effect_types(self):
        """Multiple rules with different effect types should produce a stable combined result"""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "power", "action": "=", "value": 3},
                                {"attr_id": "shield", "action": "+", "value": 1},
                            ],
                        },
                        {
                            "conditions": [
                                {"attr_id": "power", "op": CONDITION_OP.GREATER_EQ.value, "value": 3},
                            ],
                            "effects": [
                                {"attr_id": "power", "action": "*", "value": 2},
                            ],
                        },
                    ]
                },
                "mid": {
                    "rules": [
                        {
                            "conditions": [
                                {"attr_id": "shield", "op": CONDITION_OP.EXISTS.value},
                            ],
                            "effects": [
                                {"attr_id": "gate", "action": "=", "value": 1},
                            ],
                        }
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [40, 41],
            "target_conn_keys": [40, 41],
            "checkpoint_ids": ["mid", "end"],
            "target_checkpoint_ids": ["mid", "end"],
            "flow_succs": {
                "start": [(40, "mid")],
                "mid": [(41, "end")],
            },
            "flow_conn_conditions": {
                40: [
                    {
                        "attr_id": "power",
                        "op": CONDITION_OP.GREATER_EQ.value,
                        "value": 3,
                    }
                ],
                41: [
                    {
                        "attr_id": "gate",
                        "op": CONDITION_OP.EXISTS.value,
                    }
                ],
            },
            "connection_kinds": {40: "FLOW", 41: "FLOW"},
            "apply_all_rule_sets": True,
        }
        result = compute_sat_validation(snapshot)

        assert result["best_states"][40][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert result["best_states"][41][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert result["best_states"][40][1]
        assert result["best_states"][41][1]

    def test_wide_branching_with_conflicting_rules(self):
        """Conflicting rule branches should still resolve to a consistent classification"""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "mode", "action": "=", "value": 1},
                            ],
                        },
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "mode", "action": "=", "value": 2},
                            ],
                        },
                    ]
                },
                "branch_a": {"rules": []},
                "branch_b": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [42, 43, 44],
            "target_conn_keys": [42, 43, 44],
            "checkpoint_ids": ["branch_a", "branch_b", "end"],
            "target_checkpoint_ids": ["branch_a", "branch_b", "end"],
            "flow_succs": {
                "start": [(42, "branch_a"), (43, "branch_b")],
                "branch_a": [(44, "end")],
                "branch_b": [(44, "end")],
            },
            "flow_conn_conditions": {
                42: [
                    {"attr_id": "mode", "op": CONDITION_OP.EQUALS.value, "value": 1},
                ],
                43: [
                    {"attr_id": "mode", "op": CONDITION_OP.EQUALS.value, "value": 2},
                ],
                44: [],
            },
            "connection_kinds": {42: "FLOW", 43: "FLOW", 44: "FLOW"},
            "apply_all_rule_sets": False,
        }
        result = compute_sat_validation(snapshot)

        assert result["best_states"][42][0] == CONNECTION_STATE.CONDITIONAL_VALID
        assert result["best_states"][43][0] == CONNECTION_STATE.CONDITIONAL_VALID
        assert result["best_states"][44][0] == CONNECTION_STATE.VALID
        assert all(result["best_states"][key][1] for key in (42, 43, 44))

    def test_rule_chain_updates_attributes_across_multiple_stations(self):
        """Attribute updates should propagate across several stations in sequence"""
        snapshot = {
            "station_data": {
                "s0": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "a", "action": "=", "value": 1},
                            ],
                        }
                    ]
                },
                "s1": {
                    "rules": [
                        {
                            "conditions": [
                                {"attr_id": "a", "op": CONDITION_OP.EXISTS.value},
                            ],
                            "effects": [
                                {"attr_id": "b", "action": "+", "value": 4},
                            ],
                        }
                    ]
                },
                "s2": {
                    "rules": [
                        {
                            "conditions": [
                                {"attr_id": "b", "op": CONDITION_OP.GREATER_EQ.value, "value": 4},
                            ],
                            "effects": [
                                {"attr_id": "c", "action": "=", "value": 1},
                            ],
                        }
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["s0"],
            "flow_conn_keys": [45, 46, 47],
            "target_conn_keys": [45, 46, 47],
            "checkpoint_ids": ["s1", "s2", "end"],
            "target_checkpoint_ids": ["s1", "s2", "end"],
            "flow_succs": {
                "s0": [(45, "s1")],
                "s1": [(46, "s2")],
                "s2": [(47, "end")],
            },
            "flow_conn_conditions": {
                45: [
                    {"attr_id": "a", "op": CONDITION_OP.EXISTS.value},
                ],
                46: [
                    {"attr_id": "b", "op": CONDITION_OP.GREATER_EQ.value, "value": 4},
                ],
                47: [
                    {"attr_id": "c", "op": CONDITION_OP.EXISTS.value},
                ],
            },
            "connection_kinds": {45: "FLOW", 46: "FLOW", 47: "FLOW"},
            "apply_all_rule_sets": True,
        }
        result = compute_sat_validation(snapshot)

        assert result["best_states"][45][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert result["best_states"][46][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert result["best_states"][47][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert all(result["best_states"][key][1] for key in (45, 46, 47))


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Edge Cases and Error Handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error conditions"""

    def test_invalid_station_in_root_ids(self):
        """Invalid stations in root_ids should be filtered"""
        snapshot = {
            "station_data": {"valid": {"rules": []}},
            "root_ids": ["valid", "invalid"],
            "flow_conn_keys": [],
            "target_conn_keys": [],
            "checkpoint_ids": [],
            "target_checkpoint_ids": [],
            "flow_succs": {},
            "flow_conn_conditions": {},
        }
        result = compute_sat_validation(snapshot)
        # Should not raise, should handle gracefully
        assert isinstance(result, dict)

    def test_connection_key_not_in_flow_conn_conditions(self):
        """Missing connection condition should use empty list"""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [0],
            "target_conn_keys": [0],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(0, "end")]},
            "flow_conn_conditions": {},  # Missing condition for key 0
            "connection_kinds": {0: "FLOW"},
        }
        result = compute_sat_validation(snapshot)
        # Should handle missing condition gracefully
        assert isinstance(result, dict)

    def test_state_limit_respected(self):
        """Validation should respect max_states limit"""
        snapshot = {
            "station_data": {"s1": {"rules": []}},
            "root_ids": ["s1"],
            "flow_conn_keys": [],
            "target_conn_keys": [],
            "checkpoint_ids": [],
            "target_checkpoint_ids": [],
            "flow_succs": {},
            "flow_conn_conditions": {},
            "max_states": 10,
        }
        result = compute_sat_validation(snapshot)
        # Should complete without crashing
        assert isinstance(result, dict)

    def test_very_deep_flow(self):
        """Very deep flow graph should respect max_depth"""
        snapshot = {
            "station_data": {"s1": {"rules": []}},
            "root_ids": ["s1"],
            "flow_conn_keys": [],
            "target_conn_keys": [],
            "checkpoint_ids": [],
            "target_checkpoint_ids": [],
            "flow_succs": {},
            "flow_conn_conditions": {},
            "max_depth": 5,
        }
        result = compute_sat_validation(snapshot)
        assert isinstance(result, dict)

    def test_circular_flow_graph(self):
        """Circular references should not cause infinite loops"""
        snapshot = {
            "station_data": {
                "s1": {"rules": []},
                "s2": {"rules": []},
            },
            "root_ids": ["s1"],
            "flow_conn_keys": [0, 1],
            "target_conn_keys": [0, 1],
            "checkpoint_ids": ["s2"],
            "target_checkpoint_ids": ["s2"],
            "flow_succs": {
                "s1": [(0, "s2")],
                "s2": [(1, "s1")],  # Cycle back
            },
            "flow_conn_conditions": {},
            "connection_kinds": {0: "FLOW", 1: "FLOW"},
            "max_depth": 10,  # Limit depth to prevent infinite loops
        }
        result = compute_sat_validation(snapshot)
        # Should complete without crashing
        assert isinstance(result, dict)
        assert "best_states" in result

    def test_truncated_analysis_marks_connection_unknown(self):
        """A very low max_states limit should downgrade unresolved connections to UNKNOWN"""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "marker", "action": "+", "value": 1},
                            ],
                        }
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [20],
            "target_conn_keys": [20],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(20, "end")]},
            "flow_conn_conditions": {20: []},
            "connection_kinds": {20: "FLOW"},
            "max_states": 1,
        }
        result = compute_sat_validation(snapshot)

        assert 20 in result["best_states"]
        state, reasons = result["best_states"][20]
        assert state == CONNECTION_STATE.UNKNOWN
        assert any("zustandslimit" in reason.lower() for reason in reasons)

    def test_max_traversals_zero_blocks_rule_in_cycle(self):
        """Rules with max_traversals=0 must be disabled even on cyclic stations."""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "gate", "action": "=", "value": 1},
                            ],
                            "max_traversals": 0,
                        }
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [200, 201],
            "target_conn_keys": [200, 201],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {
                "start": [(200, "start"), (201, "end")],
            },
            "flow_conn_conditions": {
                200: [{"attr_id": "gate", "op": CONDITION_OP.EXISTS.value}],
                201: [{"attr_id": "gate", "op": CONDITION_OP.EXISTS.value}],
            },
            "connection_kinds": {200: "FLOW", 201: "FLOW"},
            "max_depth": 15,
        }

        result = compute_sat_validation(snapshot)

        assert result["best_states"][200][0] == CONNECTION_STATE.INVALID
        assert result["best_states"][201][0] == CONNECTION_STATE.INVALID
        assert result["best_states"][201][1]

    def test_dominance_prunes_weaker_join_state(self):
        """A weaker duplicate state at a join node should be pruned even if the join is acyclic."""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "loop": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [],
                        }
                    ]
                },
                "join": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [210, 211, 212],
            "target_conn_keys": [210, 211, 212],
            "checkpoint_ids": ["join", "end"],
            "target_checkpoint_ids": ["join", "end"],
            "flow_succs": {
                "start": [(210, "join"), (211, "loop")],
                "loop": [(212, "join")],
            },
            "flow_conn_conditions": {
                210: [],
                211: [],
                212: [],
            },
            "connection_kinds": {210: "FLOW", 211: "FLOW", 212: "FLOW"},
            "max_depth": 10,
        }

        result = compute_sat_validation(snapshot)

        profiling = result["metrics"]["profiling"]
        assert profiling["state_count"] == 3
        assert profiling["queue_peak"] <= 3
        assert result["best_states"][210][0] == CONNECTION_STATE.VALID
        assert result["best_states"][211][0] == CONNECTION_STATE.VALID
        assert result["best_states"][212][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}

    def test_irrelevant_global_attribute_does_not_expand_loop_branch(self):
        """A globally relevant attribute should still be dropped when no reachable successor can observe it."""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "loop": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "noise", "action": "+", "value": 1},
                            ],
                        }
                    ]
                },
                "join": {"rules": []},
                "sensor": {
                    "rules": [
                        {
                            "conditions": [
                                {"attr_id": "noise", "op": CONDITION_OP.GREATER.value, "value": 0},
                            ],
                            "effects": [],
                        }
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [220, 221, 222, 223],
            "target_conn_keys": [220, 221, 222, 223],
            "checkpoint_ids": ["join", "end"],
            "target_checkpoint_ids": ["join", "end"],
            "flow_succs": {
                "start": [(220, "loop")],
                "loop": [(221, "loop"), (222, "join")],
                "join": [(223, "end")],
            },
            "flow_conn_conditions": {
                220: [],
                221: [],
                222: [],
                223: [],
            },
            "connection_kinds": {220: "FLOW", 221: "FLOW", 222: "FLOW", 223: "FLOW"},
            "max_depth": 12,
        }

        result = compute_sat_validation(snapshot)

        profiling = result["metrics"]["profiling"]
        assert profiling["state_count"] <= 4
        assert profiling["queue_peak"] <= 3
        assert profiling["dedup_rule_tasks_skipped"] >= 0
        assert profiling["dedup_branch_payloads_skipped"] >= 0
        assert profiling["dedup_next_candidates_skipped"] >= 0
        assert profiling["state_reuse_hits"] >= 0
        assert profiling["dominance_pruned_states"] >= 0
        assert result["best_states"][220][0] == CONNECTION_STATE.VALID
        assert result["best_states"][221][0] == CONNECTION_STATE.CONDITIONAL_INVALID
        assert result["best_states"][222][0] == CONNECTION_STATE.VALID
        assert result["best_states"][223][0] == CONNECTION_STATE.VALID

    def test_dead_end_observable_edges_do_not_inflate_relevance(self):
        """Conditions on dead-end successors should not keep attributes relevant for live paths."""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "loop": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "noise", "action": "+", "value": 1},
                            ],
                        }
                    ]
                },
                "dead": {
                    "rules": [
                        {
                            "conditions": [
                                {"attr_id": "noise", "op": CONDITION_OP.GREATER.value, "value": 0},
                            ],
                            "effects": [],
                        }
                    ]
                },
                "join": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [230, 231, 232, 233, 234],
            "target_conn_keys": [230, 231, 232, 233, 234],
            "checkpoint_ids": ["join", "end"],
            "target_checkpoint_ids": ["join", "end"],
            "flow_succs": {
                "start": [(230, "loop")],
                "loop": [(231, "loop"), (232, "join"), (233, "dead")],
                "join": [(234, "end")],
            },
            "flow_conn_conditions": {
                230: [],
                231: [],
                232: [],
                233: [],
                234: [],
            },
            "connection_kinds": {230: "FLOW", 231: "FLOW", 232: "FLOW", 233: "FLOW", 234: "FLOW"},
            "max_depth": 12,
        }

        result = compute_sat_validation(snapshot)

        profiling = result["metrics"]["profiling"]
        assert profiling["future_observable_edges_skipped"] >= 1
        assert profiling["state_count"] <= 4
        assert result["best_states"][230][0] == CONNECTION_STATE.VALID
        assert result["best_states"][231][0] == CONNECTION_STATE.CONDITIONAL_INVALID
        assert result["best_states"][232][0] == CONNECTION_STATE.VALID

    def test_max_traversals_zero_blocks_rule_non_cyclic(self):
        """Rules with max_traversals=0 must also be disabled on acyclic stations."""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "x", "action": "=", "value": 1},
                            ],
                            "max_traversals": 0,
                        }
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [202],
            "target_conn_keys": [202],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(202, "end")]},
            "flow_conn_conditions": {
                202: [{"attr_id": "x", "op": CONDITION_OP.EXISTS.value}],
            },
            "connection_kinds": {202: "FLOW"},
        }

        result = compute_sat_validation(snapshot)

        assert result["best_states"][202][0] == CONNECTION_STATE.INVALID
        assert result["best_states"][202][1]

    def test_unfulfillable_rule_condition_blocks_transition(self):
        """A rule whose condition cannot be satisfied must not create a transition."""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [
                                {"attr_id": "x", "op": CONDITION_OP.GREATER.value, "value": 0},
                            ],
                            "effects": [],
                        }
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [203],
            "target_conn_keys": [203],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(203, "end")]},
            "flow_conn_conditions": {203: []},
            "connection_kinds": {203: "FLOW"},
            "max_depth": 4,
        }

        result = compute_sat_validation(snapshot)

        assert result["best_states"][203][0] == CONNECTION_STATE.INVALID
        assert result["best_states"][203][1]

    def test_max_traversals_one_still_allows_unrelated_end_path(self):
        """A loop rule limited to one traversal must not block a separate end edge."""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "gate", "action": "=", "value": 1},
                            ],
                            "max_traversals": 1,
                        }
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [204, 205],
            "target_conn_keys": [204, 205],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {
                "start": [(204, "start"), (205, "end")],
            },
            "flow_conn_conditions": {
                204: [{"attr_id": "gate", "op": CONDITION_OP.EXISTS.value}],
                205: [{"attr_id": "gate", "op": CONDITION_OP.EXISTS.value}],
            },
            "connection_kinds": {204: "FLOW", 205: "FLOW"},
            "max_depth": 6,
        }

        result = compute_sat_validation(snapshot)

        assert result["best_states"][204][0] == CONNECTION_STATE.CONDITIONAL_INVALID
        assert result["best_states"][205][0] == CONNECTION_STATE.CONDITIONAL_VALID
        assert result["metrics"]["profiling"]["state_count"] <= 3

    def test_max_traversals_applies_to_second_rule_index_in_cycle(self):
        """Regression: in cyclic stations every rule index must be tracked, not only the first one."""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [{"attr_id": "noise", "action": "+", "value": 1}],
                            "max_traversals": 5,
                        },
                        {
                            "conditions": [],
                            "effects": [{"attr_id": "gate", "action": "=", "value": 1}],
                            "max_traversals": 0,
                        },
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [210, 211],
            "target_conn_keys": [210, 211],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {
                "start": [(210, "start"), (211, "end")],
            },
            "flow_conn_conditions": {
                210: [],
                211: [{"attr_id": "gate", "op": CONDITION_OP.EXISTS.value}],
            },
            "connection_kinds": {210: "FLOW", 211: "FLOW"},
            "max_depth": 20,
        }

        result = compute_sat_validation(snapshot)

        # If the second rule were untracked, gate would be set and edge 211 could become valid.
        assert result["best_states"][211][0] == CONNECTION_STATE.INVALID
        assert result["best_states"][211][1]

    def test_disconnected_source_is_conditional_invalid(self):
        """A reachable edge that never reaches a checkpoint should be CONDITIONAL_INVALID"""
        snapshot = {
            "station_data": {
                "root": {"rules": []},
                "isolated": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["root"],
            "flow_conn_keys": [21],
            "target_conn_keys": [21],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {
                "root": [(21, "isolated")],
            },
            "flow_conn_conditions": {21: []},
            "connection_kinds": {21: "FLOW"},
        }
        result = compute_sat_validation(snapshot)

        assert 21 in result["best_states"]
        state, reasons = result["best_states"][21]
        assert state == CONNECTION_STATE.CONDITIONAL_INVALID
        assert any("endstation" in reason.lower() for reason in reasons)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: CONNECTION_STATE Classification Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestConnectionStateClassification:
    """Test that connections are correctly classified"""

    def test_valid_state_has_reasons(self):
        """VALID connections should have reason strings"""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [0],
            "target_conn_keys": [0],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(0, "end")]},
            "flow_conn_conditions": {},
            "connection_kinds": {0: "FLOW"},
        }
        result = compute_sat_validation(snapshot)

        if 0 in result.get("best_states", {}):
            state, reasons = result["best_states"][0]
            # Verify structure regardless of state type
            assert reasons is not None
            assert isinstance(reasons, list)
            if len(reasons) > 0:
                # Check for German reason strings
                assert all(isinstance(r, str) for r in reasons)

    def test_all_states_have_reasons(self):
        """All classified connections should have reason lists"""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [0],
            "target_conn_keys": [0],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(0, "end")]},
            "flow_conn_conditions": {},
            "connection_kinds": {0: "FLOW"},
        }
        result = compute_sat_validation(snapshot)

        for conn_key, (state, reasons) in result.get("best_states", {}).items():
            # state is CONNECTION_STATE enum, not string
            assert isinstance(state, CONNECTION_STATE) or isinstance(state, str)
            assert isinstance(reasons, list)
            for reason in reasons:
                assert isinstance(reason, str)

    def test_valid_and_conditional_valid_classification(self):
        """Connections should distinguish unconditional and conditional validity"""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "flag", "action": "=", "value": 1},
                            ],
                        }
                    ]
                },
                "mid": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [30, 31],
            "target_conn_keys": [30, 31],
            "checkpoint_ids": ["mid", "end"],
            "target_checkpoint_ids": ["mid", "end"],
            "flow_succs": {
                "start": [(30, "mid"), (31, "end")],
            },
            "flow_conn_conditions": {
                30: [],
                31: [
                    {
                        "attr_id": "flag",
                        "op": CONDITION_OP.EXISTS.value,
                    }
                ],
            },
            "connection_kinds": {30: "FLOW", 31: "FLOW"},
        }
        result = compute_sat_validation(snapshot)

        assert result["best_states"][30][0] == CONNECTION_STATE.VALID
        assert result["best_states"][31][0] == CONNECTION_STATE.CONDITIONAL_VALID
        assert any("gültigen pfad" in reason.lower() for reason in result["best_states"][30][1])
        assert any("bedingungenabhängig" in reason.lower() for reason in result["best_states"][31][1])

    def test_conditional_invalid_classification_has_failed_condition_reason(self):
        """Failed edge conditions should be reported as INVALID with a condition reason"""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [32],
            "target_conn_keys": [32],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(32, "end")]},
            "flow_conn_conditions": {
                32: [
                    {
                        "attr_id": "never_set",
                        "op": CONDITION_OP.EXISTS.value,
                    }
                ]
            },
            "connection_kinds": {32: "FLOW"},
        }
        result = compute_sat_validation(snapshot)

        assert result["best_states"][32][0] == CONNECTION_STATE.INVALID
        assert any("bedingungen" in reason.lower() for reason in result["best_states"][32][1])

    def test_state_limit_triggers_unknown_classification(self):
        """Truncated analyses should surface UNKNOWN classifications"""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "flag", "action": "+", "value": 1},
                            ],
                        }
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [33],
            "target_conn_keys": [33],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(33, "end")]},
            "flow_conn_conditions": {33: []},
            "connection_kinds": {33: "FLOW"},
            "max_states": 1,
        }
        result = compute_sat_validation(snapshot)

        assert result["best_states"][33][0] == CONNECTION_STATE.UNKNOWN
        assert any("zustandslimit" in reason.lower() for reason in result["best_states"][33][1])


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7: Regression Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegressionCases:
    """Test cases that caught previous bugs"""

    def test_no_early_termination_with_multiple_paths(self):
        """Validation should explore all paths, not terminate early"""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "mid": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [0, 1, 2],
            "target_conn_keys": [0, 1, 2],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {
                "start": [(0, "mid"), (1, "end")],
                "mid": [(2, "end")],
            },
            "flow_conn_conditions": {},
            "connection_kinds": {0: "FLOW", 1: "FLOW", 2: "FLOW"},
        }
        result = compute_sat_validation(snapshot)

        # Both connections to end should be analyzed
        assert isinstance(result, dict)
        assert "best_states" in result

    def test_no_aggressive_state_pruning(self):
        """Validation should not prune states too aggressively"""
        snapshot = {
            "station_data": {
                "s1": {"rules": []},
                "s2": {"rules": []},
            },
            "root_ids": ["s1"],
            "flow_conn_keys": [0],
            "target_conn_keys": [0],
            "checkpoint_ids": ["s2"],
            "target_checkpoint_ids": ["s2"],
            "flow_succs": {"s1": [(0, "s2")]},
            "flow_conn_conditions": {},
            "connection_kinds": {0: "FLOW"},
            "max_states": 100,
        }
        result = compute_sat_validation(snapshot)

        # Should complete successfully with valid result
        assert "best_states" in result
        assert isinstance(result["best_states"], dict)

    def test_no_unstable_hash_caching(self):
        """Same snapshot should produce same results consistently"""
        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [0],
            "target_conn_keys": [0],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(0, "end")]},
            "flow_conn_conditions": {},
            "connection_kinds": {0: "FLOW"},
        }

        # Run validation twice
        result1 = compute_sat_validation(snapshot.copy())
        result2 = compute_sat_validation(snapshot.copy())

        # Results should be identical
        assert result1.get("best_states") == result2.get("best_states")

    def test_intertwined_cycles_with_exit_path(self):
        """Two intersecting cycles with an exit path should terminate and keep the exit reachable"""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "loop_seed", "action": "=", "value": 1},
                            ],
                        }
                    ]
                },
                "loop_a": {
                    "rules": [
                        {
                            "conditions": [
                                {"attr_id": "loop_seed", "op": CONDITION_OP.EXISTS.value},
                            ],
                            "effects": [
                                {"attr_id": "loop_a_hits", "action": "+", "value": 1},
                            ],
                        }
                    ]
                },
                "loop_b": {
                    "rules": [
                        {
                            "conditions": [
                                {"attr_id": "loop_a_hits", "op": CONDITION_OP.GREATER_EQ.value, "value": 1},
                            ],
                            "effects": [
                                {"attr_id": "loop_b_hits", "action": "+", "value": 1},
                            ],
                        }
                    ]
                },
                "exit": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [50, 51, 52, 53],
            "target_conn_keys": [50, 51, 52, 53],
            "checkpoint_ids": ["loop_a", "loop_b", "exit"],
            "target_checkpoint_ids": ["loop_a", "loop_b", "exit"],
            "flow_succs": {
                "start": [(50, "loop_a")],
                "loop_a": [(51, "loop_b"), (52, "exit")],
                "loop_b": [(53, "loop_a")],
            },
            "flow_conn_conditions": {
                50: [],
                51: [
                    {"attr_id": "loop_seed", "op": CONDITION_OP.EXISTS.value},
                ],
                52: [
                    {"attr_id": "loop_seed", "op": CONDITION_OP.EXISTS.value},
                ],
                53: [
                    {"attr_id": "loop_a_hits", "op": CONDITION_OP.GREATER_EQ.value, "value": 1},
                ],
            },
            "connection_kinds": {50: "FLOW", 51: "FLOW", 52: "FLOW", 53: "FLOW"},
            "max_depth": 30,
            "max_states": 500,
            "apply_all_rule_sets": True,
        }
        result = compute_sat_validation(snapshot)

        assert result["best_states"][50][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert result["best_states"][51][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert result["best_states"][52][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert result["best_states"][53][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert any("gültigen pfad" in reason.lower() or "bedingungenabhängig" in reason.lower() for reason in result["best_states"][52][1])

    def test_self_loop_with_exit_and_condition_progression(self):
        """A self-loop that increases an attribute should not block the exit path"""
        snapshot = {
            "station_data": {
                "start": {
                    "rules": [
                        {
                            "conditions": [],
                            "effects": [
                                {"attr_id": "ticks", "action": "=", "value": 0},
                            ],
                        }
                    ]
                },
                "spinner": {
                    "rules": [
                        {
                            "conditions": [
                                {"attr_id": "ticks", "op": CONDITION_OP.LESS.value, "value": 3},
                            ],
                            "effects": [
                                {"attr_id": "ticks", "action": "+", "value": 1},
                                {"attr_id": "seen", "action": "+", "value": 1},
                            ],
                        }
                    ]
                },
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [54, 55, 56],
            "target_conn_keys": [54, 55, 56],
            "checkpoint_ids": ["spinner", "end"],
            "target_checkpoint_ids": ["spinner", "end"],
            "flow_succs": {
                "start": [(54, "spinner")],
                "spinner": [(55, "spinner"), (56, "end")],
            },
            "flow_conn_conditions": {
                54: [],
                55: [
                    {"attr_id": "ticks", "op": CONDITION_OP.LESS.value, "value": 3},
                ],
                56: [
                    {"attr_id": "seen", "op": CONDITION_OP.GREATER_EQ.value, "value": 1},
                ],
            },
            "connection_kinds": {54: "FLOW", 55: "FLOW", 56: "FLOW"},
            "max_depth": 25,
            "max_states": 500,
            "apply_all_rule_sets": True,
        }
        result = compute_sat_validation(snapshot)

        assert result["best_states"][54][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert result["best_states"][55][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert result["best_states"][56][0] in {CONNECTION_STATE.VALID, CONNECTION_STATE.CONDITIONAL_VALID}
        assert any("gültigen pfad" in reason.lower() or "bedingungenabhängig" in reason.lower() for reason in result["best_states"][56][1])


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8: Logic Error Detection Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogicErrorDetection:
    """Tests designed to catch logical errors"""

    def test_condition_evaluation_symmetry(self):
        """GREATER and LESS should be opposite operations"""
        state = {"attr1": 10.0}

        greater_cond = {
            "attr_id": "attr1",
            "value": 5.0,
            "op": CONDITION_OP.GREATER.value,
        }
        less_cond = {
            "attr_id": "attr1",
            "value": 5.0,
            "op": CONDITION_OP.LESS.value,
        }

        # With state[attr1]=10 and value=5:
        # GREATER(10 > 5) should be True
        # LESS(10 < 5) should be False
        assert _check_condition(greater_cond, state) is True
        assert _check_condition(less_cond, state) is False

    def test_condition_evaluation_with_zero(self):
        """Special handling of zero values"""
        state = {"attr1": 0.0}

        exists_cond = {"attr_id": "attr1", "op": CONDITION_OP.EXISTS.value}
        not_exists_cond = {
            "attr_id": "attr1",
            "op": CONDITION_OP.NOT_EXISTS.value,
        }

        # Zero should mean not exists
        assert _check_condition(exists_cond, state) is False
        assert _check_condition(not_exists_cond, state) is True

    def test_condition_evaluation_with_negative_values(self):
        """EXISTS checks if value > 0, so negative values are treated as not existing"""
        state = {"attr1": -5.0}

        exists_cond = {"attr_id": "attr1", "op": CONDITION_OP.EXISTS.value}

        # Negative values are NOT > 0, so EXISTS returns False
        assert _check_condition(exists_cond, state) is False

    def test_invalid_operator_always_false(self):
        """Invalid operators should always return False"""
        state = {"attr1": 100.0}
        cond = {"attr_id": "attr1", "op": "INVALID_OPERATOR"}

        assert _check_condition(cond, state) is False

    def test_result_structure_consistency(self):
        """Validation results should have consistent structure"""
        snapshot = {
            "station_data": {"s1": {"rules": []}},
            "root_ids": ["s1"],
            "flow_conn_keys": [],
            "target_conn_keys": [],
            "checkpoint_ids": [],
            "target_checkpoint_ids": [],
            "flow_succs": {},
            "flow_conn_conditions": {},
        }
        result = compute_sat_validation(snapshot)

        # Check structure
        assert "best_states" in result
        assert "checkpoint_levels" in result
        assert "metrics" in result

        # Check best_states structure
        for conn_key, (state, reasons) in result["best_states"].items():
            # state is CONNECTION_STATE enum or str
            assert state is not None
            assert isinstance(reasons, list)

        # Check metrics structure
        metrics = result["metrics"]
        assert "duration_ms" in metrics
        assert isinstance(metrics["duration_ms"], (int, float))


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9: Performance and Memory Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPerformanceAndMemory:
    """Test performance and memory efficiency"""

    def test_validation_completes_in_reasonable_time(self):
        """Validation should complete quickly for simple cases"""
        import time

        snapshot = {
            "station_data": {
                "start": {"rules": []},
                "end": {"rules": []},
            },
            "root_ids": ["start"],
            "flow_conn_keys": [0],
            "target_conn_keys": [0],
            "checkpoint_ids": ["end"],
            "target_checkpoint_ids": ["end"],
            "flow_succs": {"start": [(0, "end")]},
            "flow_conn_conditions": {},
            "connection_kinds": {0: "FLOW"},
        }

        start = time.time()
        result = compute_sat_validation(snapshot)
        elapsed = time.time() - start

        # Should complete in less than 5 seconds
        assert elapsed < 5.0
        assert isinstance(result, dict)

    def test_cache_clearing_enabled(self):
        """Validation should automatically manage caches"""
        snapshot = {
            "station_data": {"s1": {"rules": []}},
            "root_ids": ["s1"],
            "flow_conn_keys": [],
            "target_conn_keys": [],
            "checkpoint_ids": [],
            "target_checkpoint_ids": [],
            "flow_succs": {},
            "flow_conn_conditions": {},
            "validation_cache_limit": 1000,
        }
        result = compute_sat_validation(snapshot)
        # Should complete without memory issues
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Test Execution
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
