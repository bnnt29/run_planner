"""SAT/NuSMV assisted validation backend for flow graphs.

The scene creates a compact snapshot in ``validate.py`` and delegates the
heavy validation work to ``compute_sat_validation``.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import bisect
import os
import shutil
import subprocess
import tempfile
import time

try:
	from .items import CONNECTION_STATE, CONDITION_OP
except ImportError:
	from items import CONNECTION_STATE, CONDITION_OP  # type: ignore

# ══════════════════════════════════════════════════════════════════════════════
# Helper functions for validation
# ══════════════════════════════════════════════════════════════════════════════


def _is_cancelled(cancel_event) -> bool:
	return bool(cancel_event is not None and cancel_event.is_set())


def _safe_status_emit(status_emit, message: str):
	if callable(status_emit):
		try:
			status_emit(message)
		except Exception:
			pass


def _to_float(value) -> float:
	try:
		return float(value)
	except (TypeError, ValueError):
		return 0.0


def _default_parallel_workers(cap: int | None = None, reserve_cores: int = 0) -> int:
	"""Compute a practical default worker count close to available CPU cores."""
	cpu_count = max(1, os.cpu_count() or 1)
	workers = max(1, cpu_count - max(0, reserve_cores))
	if cap is not None:
		workers = min(workers, max(1, int(cap)))
	return workers


def _check_condition(cond: dict, state: dict[str, float]) -> bool:
	attr_id = cond.get("attr_id")
	compare_attr_id = cond.get("compare_attr_id")
	op = cond.get("op", CONDITION_OP.EXISTS.value)
	count = _to_float(state.get(attr_id, 0.0)) if attr_id is not None else 0.0
	rhs = _to_float(cond.get("value", 0.0))
	if compare_attr_id is not None:
		rhs = _to_float(state.get(compare_attr_id, 0.0))

	if op == CONDITION_OP.EXISTS.value:
		return count > 0.0
	if op == CONDITION_OP.NOT_EXISTS.value:
		return count == 0.0
	if op == CONDITION_OP.EQUALS.value:
		return count == rhs
	if op == CONDITION_OP.NOT_EQUALS.value:
		return count != rhs
	if op == CONDITION_OP.GREATER.value:
		return count > rhs
	if op == CONDITION_OP.GREATER_EQ.value:
		return count >= rhs
	if op == CONDITION_OP.LESS.value:
		return count < rhs
	if op == CONDITION_OP.LESS_EQ.value:
		return count <= rhs
	return False


def _compile_condition(cond: dict) -> tuple[str | None, str | None, str, float]:
	return (
		cond.get("attr_id"),
		cond.get("compare_attr_id"),
		cond.get("op", CONDITION_OP.EXISTS.value),
		_to_float(cond.get("value", 0.0)),
	)


def _check_condition_compiled(cond: tuple[str | None, str | None, str, float], state: dict[str, float]) -> bool:
	attr_id, compare_attr_id, op, rhs_value = cond
	count = _to_float(state.get(attr_id, 0.0)) if attr_id is not None else 0.0
	rhs = rhs_value
	if compare_attr_id is not None:
		rhs = _to_float(state.get(compare_attr_id, 0.0))

	if op == CONDITION_OP.EXISTS.value:
		return count > 0.0
	if op == CONDITION_OP.NOT_EXISTS.value:
		return count == 0.0
	if op == CONDITION_OP.EQUALS.value:
		return count == rhs
	if op == CONDITION_OP.NOT_EQUALS.value:
		return count != rhs
	if op == CONDITION_OP.GREATER.value:
		return count > rhs
	if op == CONDITION_OP.GREATER_EQ.value:
		return count >= rhs
	if op == CONDITION_OP.LESS.value:
		return count < rhs
	if op == CONDITION_OP.LESS_EQ.value:
		return count <= rhs
	return False


def _condition_implies_condition(
	source_cond: tuple[str | None, str | None, str, float],
	target_cond: tuple[str | None, str | None, str, float],
) -> bool:
	s_attr, s_cmp_attr, s_op, s_rhs = source_cond
	t_attr, t_cmp_attr, t_op, t_rhs = target_cond

	# Keep collapse logic conservative: only direct, literal same-attribute comparisons.
	if s_cmp_attr is not None or t_cmp_attr is not None:
		return False
	if s_attr is None or t_attr is None or s_attr != t_attr:
		return False

	if t_op == CONDITION_OP.EXISTS.value:
		if s_op == CONDITION_OP.GREATER.value:
			return s_rhs >= 0.0
		if s_op == CONDITION_OP.GREATER_EQ.value:
			return s_rhs > 0.0
		if s_op == CONDITION_OP.EQUALS.value:
			return s_rhs > 0.0
		return False

	if t_op == CONDITION_OP.GREATER.value:
		if s_op == CONDITION_OP.GREATER.value:
			return s_rhs >= t_rhs
		if s_op == CONDITION_OP.GREATER_EQ.value:
			return s_rhs > t_rhs
		if s_op == CONDITION_OP.EQUALS.value:
			return s_rhs > t_rhs
		return False

	if t_op == CONDITION_OP.GREATER_EQ.value:
		if s_op == CONDITION_OP.GREATER.value:
			return s_rhs >= t_rhs
		if s_op == CONDITION_OP.GREATER_EQ.value:
			return s_rhs >= t_rhs
		if s_op == CONDITION_OP.EQUALS.value:
			return s_rhs >= t_rhs
		return False

	if t_op == CONDITION_OP.LESS.value:
		if s_op == CONDITION_OP.LESS.value:
			return s_rhs <= t_rhs
		if s_op == CONDITION_OP.LESS_EQ.value:
			return s_rhs < t_rhs
		if s_op == CONDITION_OP.EQUALS.value:
			return s_rhs < t_rhs
		return False

	if t_op == CONDITION_OP.LESS_EQ.value:
		if s_op == CONDITION_OP.LESS.value:
			return s_rhs <= t_rhs
		if s_op == CONDITION_OP.LESS_EQ.value:
			return s_rhs <= t_rhs
		if s_op == CONDITION_OP.EQUALS.value:
			return s_rhs <= t_rhs
		return False

	if t_op == CONDITION_OP.EQUALS.value:
		return s_op == CONDITION_OP.EQUALS.value and s_rhs == t_rhs

	if t_op == CONDITION_OP.NOT_EQUALS.value:
		return s_op == CONDITION_OP.EQUALS.value and s_rhs != t_rhs

	if t_op == CONDITION_OP.NOT_EXISTS.value:
		return s_op == CONDITION_OP.EQUALS.value and s_rhs == 0.0

	return False


def _compile_effect(eff: dict) -> tuple[str | None, str, float]:
	return (
		eff.get("attr_id"),
		eff.get("action", "="),
		_to_float(eff.get("value", 0.0)),
	)


def _apply_effects_compiled(
	state: dict[str, float],
	effects: list[tuple[str | None, str, float]],
) -> dict[str, float]:
	if not effects:
		return state
	out = dict(state)
	for attr_id, action, value in effects:
		if attr_id is None:
			continue
		current = _to_float(out.get(attr_id, 0.0))
		if action == "+":
			out[attr_id] = current + value
		elif action == "-":
			out[attr_id] = current - value
		elif action == "*":
			out[attr_id] = current * value
		elif action == "/":
			if value != 0.0:
				out[attr_id] = current / value
		elif action == "%":
			if value != 0.0:
				out[attr_id] = current % value
		else:
			out[attr_id] = value
	return out


def _apply_effects(state: dict[str, float], effects: list[dict]) -> dict[str, float]:
	out = dict(state)
	for eff in effects:
		attr_id = eff.get("attr_id")
		if attr_id is None:
			continue

		action = eff.get("action", "=")
		value = _to_float(eff.get("value", 0.0))
		current = _to_float(out.get(attr_id, 0.0))

		if action == "+":
			out[attr_id] = current + value
		elif action == "-":
			out[attr_id] = current - value
		elif action == "*":
			out[attr_id] = current * value
		elif action == "/":
			if value != 0.0:
				out[attr_id] = current / value
		elif action == "%":
			if value != 0.0:
				out[attr_id] = current % value
		else:
			out[attr_id] = value
	return out


def _canonical_attrs(attrs: dict[str, float]) -> tuple[tuple[str, float], ...]:
	# Rounded values prevent tiny float drift from exploding the state space.
	return tuple(sorted((str(k), round(_to_float(v), 8)) for k, v in attrs.items()))


def _collect_condition_attr_metadata(
	station_data: dict,
	flow_conn_conditions: dict[int, list[dict]],
) -> tuple[set[str], set[str], dict[str, tuple[float, ...]]]:
	relevant_attrs: set[str] = set()
	compare_attrs: set[str] = set()
	attr_thresholds: dict[str, set[float]] = {}

	def _register_cond(cond: dict):
		attr_id = cond.get("attr_id")
		compare_attr_id = cond.get("compare_attr_id")
		op = cond.get("op", CONDITION_OP.EXISTS.value)
		value = _to_float(cond.get("value", 0.0))

		if attr_id is None:
			return

		relevant_attrs.add(attr_id)
		if compare_attr_id is not None:
			relevant_attrs.add(compare_attr_id)
			compare_attrs.add(attr_id)
			compare_attrs.add(compare_attr_id)
			return

		thresholds = attr_thresholds.setdefault(attr_id, set())
		if op in (
			CONDITION_OP.EXISTS.value,
			CONDITION_OP.NOT_EXISTS.value,
			CONDITION_OP.EQUALS.value,
			CONDITION_OP.NOT_EQUALS.value,
			CONDITION_OP.GREATER.value,
			CONDITION_OP.GREATER_EQ.value,
			CONDITION_OP.LESS.value,
			CONDITION_OP.LESS_EQ.value,
		):
			thresholds.add(value if op not in (CONDITION_OP.EXISTS.value, CONDITION_OP.NOT_EXISTS.value) else 0.0)

	for station in station_data.values():
		for rule in station.get("rules", []):
			for cond in rule.get("conditions", []):
				_register_cond(cond)

	for conds in flow_conn_conditions.values():
		for cond in conds:
			_register_cond(cond)

	# Arithmetic/set effects can shift values across buckets in non-equivalent ways.
	# Only attributes that participate in attribute-vs-attribute comparisons need
	# exact values. Effect-touched attributes still get threshold bucketing unless
	# they are referenced by such a comparison.

	frozen_thresholds = {
		attr_id: tuple(sorted(values))
		for attr_id, values in attr_thresholds.items()
	}
	return relevant_attrs, compare_attrs, frozen_thresholds


def _normalize_attr_value(
	attr_id: str,
	value: float,
	compare_attrs: set[str],
	attr_thresholds: dict[str, tuple[float, ...]],
):
	# Attributes involved in attribute-vs-attribute comparisons keep numeric precision.
	if attr_id in compare_attrs:
		return round(value, 8)

	thresholds = attr_thresholds.get(attr_id, ())
	if not thresholds:
		return round(value, 8)

	for pivot in thresholds:
		if abs(value - pivot) <= 1e-8:
			return round(pivot, 8)

	if value < thresholds[0]:
		return round(value, 8)

	# Bucket values by interval between known condition pivots.
	idx = bisect.bisect_left(thresholds, value)
	if idx <= 0:
		return round(thresholds[0] - 1.0, 8)
	if idx >= len(thresholds):
		return round(thresholds[-1] + 1.0, 8)
	left = thresholds[idx - 1]
	right = thresholds[idx]
	return round((left + right) / 2.0, 8)


def _canonical_attrs_condition_aware(
	attrs: dict[str, float],
	relevant_attrs: set[str],
	compare_attrs: set[str],
	attr_thresholds: dict[str, tuple[float, ...]],
) -> tuple[tuple[str, float], ...]:
	if not relevant_attrs:
		return tuple()

	filtered: list[tuple[str, float]] = []
	for attr_id in relevant_attrs:
		value = _to_float(attrs.get(attr_id, 0.0))
		filtered.append((attr_id, _normalize_attr_value(attr_id, value, compare_attrs, attr_thresholds)))
	return tuple(sorted(filtered))


def _graph_reverse(flow_succs: dict[str, list[tuple[int, str]]]) -> dict[str, list[str]]:
	rev: dict[str, list[str]] = {sid: [] for sid in flow_succs.keys()}
	for src, entries in flow_succs.items():
		for _, dst in entries:
			rev.setdefault(dst, []).append(src)
	return rev


def _graph_can_reach_checkpoint(
	flow_succs: dict[str, list[tuple[int, str]]],
	checkpoint_ids: set[str],
) -> set[str]:
	rev = _graph_reverse(flow_succs)
	seen = set(checkpoint_ids)
	queue = deque(checkpoint_ids)
	while queue:
		node = queue.popleft()
		for pred in rev.get(node, []):
			if pred in seen:
				continue
			seen.add(pred)
			queue.append(pred)
	return seen


def _graph_strongly_connected_components(
	flow_succs: dict[str, list[tuple[int, str]]],
) -> tuple[dict[str, int], list[tuple[str, ...]], set[int]]:
	"""Return SCC ids per station, the SCC members, and cyclic SCC ids."""
	index = 0
	stack: list[str] = []
	on_stack: set[str] = set()
	indices: dict[str, int] = {}
	lowlinks: dict[str, int] = {}
	component_by_node: dict[str, int] = {}
	components: list[tuple[str, ...]] = []
	cyclic_component_ids: set[int] = set()

	all_nodes: set[str] = set(flow_succs.keys())
	for entries in flow_succs.values():
		for _, dst in entries:
			all_nodes.add(dst)

	def strongconnect(node: str):
		nonlocal index
		indices[node] = index
		lowlinks[node] = index
		index += 1
		stack.append(node)
		on_stack.add(node)

		for _, dst in flow_succs.get(node, []):
			if dst not in indices:
				strongconnect(dst)
				lowlinks[node] = min(lowlinks[node], lowlinks[dst])
			elif dst in on_stack:
				lowlinks[node] = min(lowlinks[node], indices[dst])

		if lowlinks[node] == indices[node]:
			component: list[str] = []
			while True:
				top = stack.pop()
				on_stack.remove(top)
				component.append(top)
				if top == node:
					break

			component_id = len(components)
			components.append(tuple(component))
			for member in component:
				component_by_node[member] = component_id

			if len(component) > 1:
				cyclic_component_ids.add(component_id)
			else:
				only = component[0]
				if any(dst == only for _, dst in flow_succs.get(only, [])):
					cyclic_component_ids.add(component_id)

	for node in all_nodes:
		if node not in indices:
			strongconnect(node)

	return component_by_node, components, cyclic_component_ids



def _graph_nodes_in_cycles(flow_succs: dict[str, list[tuple[int, str]]]) -> set[str]:
	"""Return station ids that belong to at least one directed cycle."""
	component_by_node, _, cyclic_component_ids = _graph_strongly_connected_components(flow_succs)
	return {
		node
		for node, component_id in component_by_node.items()
		if component_id in cyclic_component_ids
	}


def _graph_reachable_from_roots(
	flow_succs: dict[str, list[tuple[int, str]]],
	root_ids: list[str],
) -> set[str]:
	seen = set(root_ids)
	queue = deque(root_ids)
	while queue:
		node = queue.popleft()
		for _, dst in flow_succs.get(node, []):
			if dst in seen:
				continue
			seen.add(dst)
			queue.append(dst)
	return seen


def _compute_ruleless_static_validation(
	station_data: dict,
	root_ids: list[str],
	flow_succs: dict[str, list[tuple[int, str]]],
	flow_conn_conditions: dict[int, list[dict]],
	target_conn_keys: set[int],
	checkpoint_ids: set[str],
	target_checkpoint_ids: set[str],
) -> tuple[dict[int, tuple[CONNECTION_STATE, list[str]]], dict[str, list[int]], dict[str, int]]:
	# Without station rules, attribute state is constant (empty), so condition checks are static.
	empty_state: dict[str, float] = {}
	active_succs: dict[str, list[tuple[int, str]]] = {sid: [] for sid in station_data.keys()}
	edge_src_reachable: set[int] = set()
	edge_taken: set[int] = set()
	edge_condition_failed: set[int] = set()

	reachable_nodes = _graph_reachable_from_roots(flow_succs, root_ids)
	for src_id in reachable_nodes:
		for conn_key, dst_id in flow_succs.get(src_id, []):
			if conn_key in target_conn_keys:
				edge_src_reachable.add(conn_key)
			conds = flow_conn_conditions.get(conn_key, [])
			if all(_check_condition(cond, empty_state) for cond in conds):
				active_succs.setdefault(src_id, []).append((conn_key, dst_id))
				if conn_key in target_conn_keys:
					edge_taken.add(conn_key)
			elif conn_key in target_conn_keys:
				edge_condition_failed.add(conn_key)

	active_reachable = _graph_reachable_from_roots(active_succs, root_ids)
	active_can_reach_checkpoint = _graph_can_reach_checkpoint(active_succs, checkpoint_ids)

	success_edges: set[int] = set()
	for src_id in active_reachable:
		for conn_key, dst_id in active_succs.get(src_id, []):
			if dst_id in active_can_reach_checkpoint:
				success_edges.add(conn_key)

	best_states: dict[int, tuple[CONNECTION_STATE, list[str]]] = {}
	for conn_key in target_conn_keys:
		reasons: list[str] = []
		if conn_key in success_edges:
			state = CONNECTION_STATE.VALID
			reasons.append("Die Verbindung liegt auf einem gültigen Pfad von Start zu Endstation.")
		elif conn_key in edge_taken:
			state = CONNECTION_STATE.CONDITIONAL_INVALID
			reasons.append("Die Verbindung ist erreichbar, führt jedoch in keiner verfolgten Konfiguration zu einer Endstation.")
		elif conn_key in edge_src_reachable:
			state = CONNECTION_STATE.INVALID
			if conn_key in edge_condition_failed:
				reasons.append("Die Bedingungen der Verbindung sind in den erreichbaren Zuständen nicht erfüllbar.")
			else:
				reasons.append("Keine aktivierbare Regel erzeugt einen Übergang über diese Verbindung.")
		else:
			state = CONNECTION_STATE.INVALID
			reasons.append("Keine erreichbare Route von einer Startstation zum Quellknoten dieser Verbindung.")
		best_states[conn_key] = (state, reasons)

	out_checkpoint_levels: dict[str, list[int]] = {}
	for checkpoint_id in target_checkpoint_ids:
		if checkpoint_id in active_reachable:
			out_checkpoint_levels[checkpoint_id] = [0]

	profiling = {
		"state_count": len(active_reachable),
		"transition_count": sum(len(v) for v in active_succs.values()),
		"collapsed_conditions": 0,
	}
	return best_states, out_checkpoint_levels, profiling


def _sanitize_symbol(raw: str) -> str:
	out = []
	for ch in str(raw):
		if ch.isalnum() or ch == "_":
			out.append(ch)
		else:
			out.append("_")
	value = "".join(out).strip("_")
	return value or "id"


def _build_nusmv_model(snapshot: dict) -> str:
	station_ids = list(snapshot.get("station_data", {}).keys())
	if not station_ids:
		station_ids = ["dead"]

	node_symbols = {sid: f"n_{_sanitize_symbol(sid)}" for sid in station_ids}
	node_values = ", ".join(node_symbols[sid] for sid in station_ids)
	root_ids = [sid for sid in snapshot.get("root_ids", []) if sid in node_symbols]
	if not root_ids:
		root_ids = station_ids[:1]

	init_nodes = ", ".join(node_symbols[sid] for sid in root_ids)

	transitions = []
	for src, entries in snapshot.get("flow_succs", {}).items():
		src_symbol = node_symbols.get(src)
		if src_symbol is None or not entries:
			continue
		dst_symbols = [node_symbols.get(dst) for _, dst in entries if dst in node_symbols]
		dst_symbols = [dst for dst in dst_symbols if dst is not None]
		if not dst_symbols:
			continue
		if len(dst_symbols) == 1:
			rhs = dst_symbols[0]
		else:
			rhs = "{" + ", ".join(dst_symbols) + "}"
		transitions.append((src_symbol, rhs))

	lines = [
		"MODULE main",
		"VAR",
		f"  node : {{{node_values}}};",
		"ASSIGN",
		f"  init(node) := {{{init_nodes}}};",
		"  next(node) := case",
	]

	for src_symbol, rhs in transitions:
		lines.append(f"    node = {src_symbol} : {rhs};")
	lines.append("    TRUE : node;")
	lines.append("  esac;")

	for checkpoint_id in snapshot.get("checkpoint_ids", []):
		if checkpoint_id not in node_symbols:
			continue
		lines.append(f"DEFINE end_{_sanitize_symbol(checkpoint_id)} := (node = {node_symbols[checkpoint_id]});")

	return "\n".join(lines) + "\n"


def _write_nusmv_file(snapshot: dict) -> str | None:
	try:
		fd, path = tempfile.mkstemp(prefix="run_planner_", suffix=".smv")
		with os.fdopen(fd, "w", encoding="utf-8") as handle:
			handle.write(_build_nusmv_model(snapshot))
		return path
	except Exception:
		return None


def _find_nusmv_binary() -> str | None:
	local_candidates = [
		os.path.join(os.getcwd(), "NuSVm", "bin", "NuSVM"),
		os.path.join(os.path.dirname(__file__), "..", "..", "NuSVm", "bin", "NuSVM"),
	]
	for candidate in local_candidates:
		abs_candidate = os.path.abspath(candidate)
		if os.path.isfile(abs_candidate):
			return abs_candidate

	for name in ("NuSMV", "nusmv", "nuXmv"):
		found = shutil.which(name)
		if found:
			return found
	return None


def _run_single_nusmv_reachability(binary: str, smv_path: str, checkpoint_id: str) -> tuple[str, bool] | None:
	symbol = f"end_{_sanitize_symbol(checkpoint_id)}"
	cmd_path = None
	try:
		fd, cmd_path = tempfile.mkstemp(prefix="run_planner_", suffix=".nusmv")
		with os.fdopen(fd, "w", encoding="utf-8") as handle:
			handle.write("go\n")
			handle.write(f"check_ctl_spec -p \"EF {symbol}\"\n")
			handle.write("quit\n")

		proc = subprocess.run(
			[binary, "-source", cmd_path, smv_path],
			capture_output=True,
			text=True,
			timeout=15,
			check=False,
		)
		output = (proc.stdout or "") + "\n" + (proc.stderr or "")
		text = output.lower()
		if "is true" in text:
			return (checkpoint_id, True)
		if "is false" in text:
			return (checkpoint_id, False)
	except Exception:
		# Optional optimization only; silently ignore failures.
		return None
	finally:
		if cmd_path and os.path.exists(cmd_path):
			try:
				os.remove(cmd_path)
			except OSError:
				pass

	return None


def _run_nusmv_reachability(
	smv_path: str,
	checkpoint_ids: list[str],
	cancel_event=None,
	max_workers: int | None = None,
) -> dict[str, bool]:
	binary = _find_nusmv_binary()
	if binary is None:
		return {}

	checkpoint_ids = [cid for cid in checkpoint_ids if cid]
	if not checkpoint_ids:
		return {}

	if max_workers is None:
		max_workers = min(len(checkpoint_ids), max(1, os.cpu_count() or 1), 8)
	else:
		max_workers = max(1, min(int(max_workers), len(checkpoint_ids)))

	if max_workers <= 1 or len(checkpoint_ids) <= 1:
		results = {}
		for checkpoint_id in checkpoint_ids:
			if _is_cancelled(cancel_event):
				break
			item = _run_single_nusmv_reachability(binary, smv_path, checkpoint_id)
			if item is not None:
				results[item[0]] = item[1]
		return results

	results: dict[str, bool] = {}
	with ThreadPoolExecutor(max_workers=max_workers) as pool:
		future_to_checkpoint = {
			pool.submit(_run_single_nusmv_reachability, binary, smv_path, checkpoint_id): checkpoint_id
			for checkpoint_id in checkpoint_ids
		}
		for future in as_completed(future_to_checkpoint):
			if _is_cancelled(cancel_event):
				for pending in future_to_checkpoint.keys():
					pending.cancel()
				break
			try:
				item = future.result()
			except Exception:
				item = None
			if item is not None:
				results[item[0]] = item[1]

	return results


def compute_sat_validation(snapshot: dict, cancel_event=None, status_emit=None) -> dict:
	start_time = time.perf_counter()
	_safe_status_emit(status_emit, "Validierung: NuSMV-Modell wird erzeugt ...")

	if _is_cancelled(cancel_event):
		return {"cancelled": True}

	station_data = snapshot.get("station_data", {})
	flow_succs = snapshot.get("flow_succs", {})
	flow_conn_conditions = snapshot.get("flow_conn_conditions", {})
	flow_conn_keys = list(snapshot.get("flow_conn_keys", []))
	target_conn_keys = set(snapshot.get("target_conn_keys", flow_conn_keys))
	checkpoint_ids = set(snapshot.get("checkpoint_ids", []))
	target_checkpoint_ids = set(snapshot.get("target_checkpoint_ids", checkpoint_ids))
	nusmv_max_workers = snapshot.get("nusmv_max_workers")
	compile_workers = max(1, int(snapshot.get("compile_workers", _default_parallel_workers(cap=8))))
	cache_limit = int(snapshot.get("validation_cache_limit", 250000))
	state_workers = max(1, int(snapshot.get("state_workers", _default_parallel_workers(cap=16))))
	state_parallel_min_branches = max(
		2,
		int(snapshot.get("state_parallel_min_branches", min(4, max(2, state_workers // 2)))),
	)
	state_parallel_chunk_size = max(
		state_parallel_min_branches,
		int(snapshot.get("state_parallel_chunk_size", max(32, state_workers * 16))),
	)
	effect_parallel_min_rules = max(
		2,
		int(snapshot.get("effect_parallel_min_rules", min(4, max(2, state_workers // 2)))),
	)
	effect_parallel_chunk_size = max(
		effect_parallel_min_rules,
		int(snapshot.get("effect_parallel_chunk_size", max(32, state_workers * 16))),
	)
	queue_backpressure_start = max(1, int(snapshot.get("queue_backpressure_start", max(2000, state_workers * 256))))
	queue_backpressure_step = max(1, int(snapshot.get("queue_backpressure_step", max(500, state_workers * 64))))
	queue_backpressure_parallel_scale = max(
		1,
		int(snapshot.get("queue_backpressure_parallel_scale", 2)),
	)
	# 0 disables state limiting; limits can be provided explicitly via snapshot.
	max_states = int(snapshot.get("max_states", 0))
	root_ids = [sid for sid in snapshot.get("root_ids", []) if sid in station_data]
	max_depth = int(snapshot.get("max_depth", 2000))
	apply_all_rules = bool(snapshot.get("apply_all_rule_sets", False))
	ruleless_mode = all(not station.get("rules", []) for station in station_data.values())
	relevant_attrs, compare_attrs, attr_thresholds = _collect_condition_attr_metadata(
		station_data=station_data,
		flow_conn_conditions=flow_conn_conditions,
	)
	_safe_status_emit(
		status_emit,
		f"Validierung: SAT-BMC Vorbereitung ({len(station_data)} Stationen, {len(flow_conn_keys)} Verbindungen) ...",
	)

	if not station_data or not root_ids:
		duration_ms = round((time.perf_counter() - start_time) * 1000)
		return {
			"best_states": {},
			"checkpoint_levels": {},
			"metrics": {
				"mode": "nu-smv+state",
				"total_flow": len(flow_conn_keys),
				"target_flow": len(target_conn_keys),
				"total_checkpoints": len(checkpoint_ids),
				"target_checkpoints": len(target_checkpoint_ids),
				"duration_ms": duration_ms,
			},
		}

	if ruleless_mode:
		_safe_status_emit(status_emit, "Validierung: statische Graph-Analyse ...")
		_safe_status_emit(status_emit, "Validierung läuft ... SAT-BMC (statischer Modus) ...")
		best_states, out_checkpoint_levels, static_profiling = _compute_ruleless_static_validation(
			station_data=station_data,
			root_ids=root_ids,
			flow_succs=flow_succs,
			flow_conn_conditions=flow_conn_conditions,
			target_conn_keys=target_conn_keys,
			checkpoint_ids=checkpoint_ids,
			target_checkpoint_ids=target_checkpoint_ids,
		)

		smv_path = _write_nusmv_file(snapshot)
		nusmv_checkpoint_reachability: dict[str, bool] = {}
		if smv_path:
			_safe_status_emit(status_emit, "Validierung: NuSMV-Reichweitencheck ...")
			nusmv_checkpoint_reachability = _run_nusmv_reachability(
				smv_path=smv_path,
				checkpoint_ids=list(target_checkpoint_ids),
				cancel_event=cancel_event,
				max_workers=nusmv_max_workers,
			)

		nusmv_reachable = sum(1 for v in nusmv_checkpoint_reachability.values() if v)
		duration_ms = round((time.perf_counter() - start_time) * 1000)

		smv_file_metric = smv_path
		if smv_path and not bool(snapshot.get("keep_smv_file", False)):
			try:
				os.remove(smv_path)
				smv_file_metric = None
			except OSError:
				pass

		_safe_status_emit(
			status_emit,
			(
				"Validierung abgeschlossen "
				f"({static_profiling.get('state_count', 0)} Knoten, "
				f"{static_profiling.get('transition_count', 0)} Kanten, {duration_ms} ms)."
			),
		)

		return {
			"best_states": best_states,
			"checkpoint_levels": out_checkpoint_levels,
			"metrics": {
				"mode": "nu-smv+static-graph",
				"total_flow": len(flow_conn_keys),
				"target_flow": len(target_conn_keys),
				"total_checkpoints": len(checkpoint_ids),
				"target_checkpoints": len(target_checkpoint_ids),
				"duration_ms": duration_ms,
				"smv_file": smv_file_metric,
				"nusmv_available": _find_nusmv_binary() is not None,
				"nusmv_checkpoint_reachable": nusmv_reachable,
				"graph_checkpoint_reachable": len(out_checkpoint_levels),
				"profiling": {
					"state_count": static_profiling.get("state_count", 0),
					"transition_count": static_profiling.get("transition_count", 0),
					"state_workers": 1,
					"state_parallel_min_branches": 0,
					"state_parallel_chunk_size": 0,
					"effect_parallel_min_rules": 0,
					"effect_parallel_chunk_size": 0,
					"state_limit": max_states,
					"state_limit_reached": False,
					"analysis_truncated": False,
					"collapsed_conditions": static_profiling.get("collapsed_conditions", 0),
					"future_observable_edges_skipped": 0,
					"dedup_rule_tasks_skipped": 0,
					"dedup_branch_payloads_skipped": 0,
					"dedup_next_candidates_skipped": 0,
					"state_reuse_hits": 0,
					"dominance_pruned_states": 0,
					"local_dominance_pruned_candidates": 0,
				},
			},
		}

	smv_path = _write_nusmv_file(snapshot)
	nusmv_checkpoint_reachability: dict[str, bool] = {}
	if smv_path:
		_safe_status_emit(status_emit, "Validierung: NuSMV-Reichweitencheck ...")
		nusmv_checkpoint_reachability = _run_nusmv_reachability(
			smv_path=smv_path,
			checkpoint_ids=list(target_checkpoint_ids),
			cancel_event=cancel_event,
			max_workers=nusmv_max_workers,
		)

	can_reach_checkpoint_graph = _graph_can_reach_checkpoint(flow_succs, checkpoint_ids)
	cyclic_nodes = _graph_nodes_in_cycles(flow_succs)
	station_component_by_id, _, cyclic_component_ids = _graph_strongly_connected_components(flow_succs)
	station_idx_to_id = list(station_data.keys())
	station_id_to_idx = {sid: idx for idx, sid in enumerate(station_idx_to_id)}
	station_component_ids = [station_component_by_id.get(station_id, -1) for station_id in station_idx_to_id]

	# Precompute shortest distance (in edges) from each station to any checkpoint
	# If a station cannot reach any checkpoint, distance is a large sentinel.
	_rev = _graph_reverse(flow_succs)
	_dist_queue = deque()
	station_distance: dict[str, int] = {sid: 10**9 for sid in station_idx_to_id}
	for cid in checkpoint_ids:
		if cid in station_distance:
			station_distance[cid] = 0
			_dist_queue.append(cid)
	while _dist_queue:
		cur = _dist_queue.popleft()
		curd = station_distance.get(cur, 10**9)
		for pred in _rev.get(cur, []):
			if station_distance.get(pred, 10**9) > curd + 1:
				station_distance[pred] = curd + 1
				_dist_queue.append(pred)
	_safe_status_emit(status_emit, "Validierung: Regeln und Bedingungen werden kompiliert ...")

	rule_limits: list[int] = []
	tracked_rule_indices: set[int] = set()
	rule_entries: dict[
		str,
		list[
			tuple[
				int,
				tuple[tuple[str | None, str | None, str, float], ...],
				list[tuple[str | None, str, float]],
				set[str],
			]
		],
	] = {}
	station_rule_spans: dict[str, tuple[int, int, list[dict]]] = {}
	global_rule_idx = 0
	for station_id, station in station_data.items():
		rules = station.get("rules", [])
		count = len(rules)
		station_rule_spans[station_id] = (global_rule_idx, count, rules)
		for offset, rule in enumerate(rules):
			limit = max(0, int(rule.get("max_traversals", 20)))
			rule_limits.append(limit)
			# Counter dimensions are expensive. Track only where the limit can actually bind:
			# cycle stations can revisit rules; one-shot limits must be respected everywhere.
			if station_id in cyclic_nodes or limit <= 1:
				tracked_rule_indices.add(global_rule_idx + offset)
		global_rule_idx += count

	def _compile_station_rules(station_item: tuple[str, tuple[int, int, list[dict]]]):
		station_id, (start_idx, _, rules) = station_item
		compiled_rules: list[
			tuple[
				int,
				tuple[tuple[str | None, str | None, str, float], ...],
				list[tuple[str | None, str, float]],
				set[str],
			]
		] = []
		for offset, rule in enumerate(rules):
			compiled_conds = tuple(_compile_condition(cond) for cond in rule.get("conditions", []))
			compiled_effects = [_compile_effect(eff) for eff in rule.get("effects", [])]
			touched_attrs = {attr_id for attr_id, _, _ in compiled_effects if attr_id is not None}
			compiled_rules.append((start_idx + offset, compiled_conds, compiled_effects, touched_attrs))
		return station_id, compiled_rules

	if compile_workers > 1 and len(station_rule_spans) > 1:
		with ThreadPoolExecutor(max_workers=min(compile_workers, len(station_rule_spans))) as compile_pool:
			for station_id, compiled_rules in compile_pool.map(_compile_station_rules, station_rule_spans.items()):
				rule_entries[station_id] = list(compiled_rules)
	else:
		for station_item in station_rule_spans.items():
			station_id, compiled_rules = _compile_station_rules(station_item)
			rule_entries[station_id] = list(compiled_rules)

	def _compile_conn_conditions(conn_item: tuple[int, list[dict]]):
		conn_key, conds = conn_item
		return conn_key, tuple(_compile_condition(cond) for cond in conds)

	if compile_workers > 1 and len(flow_conn_conditions) > 1:
		compiled_flow_conn_conditions: dict[int, tuple[tuple[str | None, str | None, str, float], ...]] = {}
		with ThreadPoolExecutor(max_workers=min(compile_workers, len(flow_conn_conditions))) as compile_pool:
			for conn_key, compiled_conds in compile_pool.map(_compile_conn_conditions, flow_conn_conditions.items()):
				compiled_flow_conn_conditions[conn_key] = compiled_conds
	else:
		compiled_flow_conn_conditions = {}
		for conn_key, conds in flow_conn_conditions.items():
			_, compiled = _compile_conn_conditions((conn_key, conds))
			compiled_flow_conn_conditions[conn_key] = compiled
	
	conn_has_conditions = {conn_key: bool(conds) for conn_key, conds in compiled_flow_conn_conditions.items()}

	station_relevant_attrs_by_idx: list[set[str]] = [set() for _ in station_idx_to_id]
	future_observable_edges_skipped = 0

	def _cond_attrs_from_compiled(conds: tuple[tuple[str | None, str | None, str, float], ...]) -> set[str]:
		attrs: set[str] = set()
		for attr_id, compare_attr_id, _, _ in conds:
			if attr_id is not None:
				attrs.add(attr_id)
			if compare_attr_id is not None:
				attrs.add(compare_attr_id)
		return attrs

	station_direct_relevant_attrs: list[set[str]] = [set() for _ in station_idx_to_id]
	for station_id, compiled_rules in rule_entries.items():
		if station_id not in can_reach_checkpoint_graph:
			continue
		station_idx = station_id_to_idx.get(station_id)
		if station_idx is None:
			continue
		direct_attrs = station_direct_relevant_attrs[station_idx]
		for _, conds, _, _ in compiled_rules:
			direct_attrs.update(_cond_attrs_from_compiled(conds))
		for conn_key, dst_id in flow_succs.get(station_id, []):
			if dst_id not in can_reach_checkpoint_graph:
				future_observable_edges_skipped += 1
				continue
			direct_attrs.update(_cond_attrs_from_compiled(compiled_flow_conn_conditions.get(conn_key, ())))

	reverse_succs: dict[str, list[str]] = {sid: [] for sid in can_reach_checkpoint_graph}
	for src_id, entries in flow_succs.items():
		if src_id not in can_reach_checkpoint_graph:
			continue
		for _, dst_id in entries:
			if dst_id not in can_reach_checkpoint_graph:
				continue
			reverse_succs.setdefault(dst_id, []).append(src_id)

	station_relevant_attrs_by_id: dict[str, set[str]] = {
		station_id: set(station_direct_relevant_attrs[station_id_to_idx[station_id]])
		for station_id in can_reach_checkpoint_graph
	}
	changed = True
	while changed:
		changed = False
		for station_id in can_reach_checkpoint_graph:
			current = station_relevant_attrs_by_id[station_id]
			for pred_id in reverse_succs.get(station_id, []):
				pred_attrs = station_relevant_attrs_by_id[pred_id]
				before = len(pred_attrs)
				pred_attrs.update(current)
				if len(pred_attrs) != before:
					changed = True

	for station_id, station_idx in station_id_to_idx.items():
		station_relevant_attrs_by_idx[station_idx] = station_relevant_attrs_by_id.get(station_id, set())

	rule_collapse_map: dict[tuple[str, int, int], tuple[int, ...]] = {}
	rule_collapse_by_station_rule: dict[tuple[str, int], dict[int, tuple[int, ...]]] = {}
	collapsed_condition_count = 0
	for station_id, compiled_rules in rule_entries.items():
		outgoing_edges = flow_succs.get(station_id, [])
		if not outgoing_edges:
			continue
		for global_idx, rule_conds, _, touched_attrs in compiled_rules:
			if len(rule_conds) != 1:
				continue
			rule_cond = rule_conds[0]
			rule_attr = rule_cond[0]
			if rule_attr is None or rule_attr in touched_attrs:
				continue
			for conn_key, _ in outgoing_edges:
				conn_conds = compiled_flow_conn_conditions.get(conn_key, ())
				if not conn_conds:
					continue
				collapsed_indices = []
				for idx, conn_cond in enumerate(conn_conds):
					conn_attr = conn_cond[0]
					conn_cmp_attr = conn_cond[1]
					if conn_attr is not None and conn_attr in touched_attrs:
						continue
					if conn_cmp_attr is not None and conn_cmp_attr in touched_attrs:
						continue
					if _condition_implies_condition(rule_cond, conn_cond):
						collapsed_indices.append(idx)
				if collapsed_indices:
					collapsed_tuple = tuple(collapsed_indices)
					rule_collapse_map[(station_id, global_idx, conn_key)] = collapsed_tuple
					rule_collapses = rule_collapse_by_station_rule.get((station_id, global_idx))
					if rule_collapses is None:
						rule_collapses = {}
						rule_collapse_by_station_rule[(station_id, global_idx)] = rule_collapses
					rule_collapses[conn_key] = collapsed_tuple
					collapsed_condition_count += len(collapsed_tuple)

	_safe_status_emit(
		status_emit,
		f"Validierung: Kompilierung abgeschlossen ({len(rule_limits)} Regeln, {len(compiled_flow_conn_conditions)} Verbindungs-Bedingungssets).",
	)

	initial_used_counts: tuple[tuple[int, int], ...] = tuple()
	attrs_pool: dict[tuple[tuple[str, float], ...], int] = {tuple(): 0}
	attrs_values: list[tuple[tuple[str, float], ...]] = [tuple()]
	counters_pool: dict[tuple[tuple[int, int], ...], int] = {initial_used_counts: 0}
	counters_values: list[tuple[tuple[int, int], ...]] = [initial_used_counts]

	def _intern_attrs(attrs_key: tuple[tuple[str, float], ...]) -> int:
		cached = attrs_pool.get(attrs_key)
		if cached is not None:
			return cached
		idx = len(attrs_values)
		attrs_pool[attrs_key] = idx
		attrs_values.append(attrs_key)
		return idx

	def _intern_counters(counters: tuple[tuple[int, int], ...]) -> int:
		cached = counters_pool.get(counters)
		if cached is not None:
			return cached
		idx = len(counters_values)
		counters_pool[counters] = idx
		counters_values.append(counters)
		return idx

	def _increment_used_counts(
		used_counts_id: int,
		used_counts: dict[int, int],
		increment_indices: list[int],
	) -> int:
		tracked_increment_indices = [idx for idx in increment_indices if idx in tracked_rule_indices]
		if not tracked_increment_indices:
			return used_counts_id
		updated = dict(used_counts)
		for gidx in tracked_increment_indices:
			updated[gidx] = int(updated.get(gidx, 0)) + 1
		counters_key = tuple(sorted((idx, val) for idx, val in updated.items() if val > 0))
		return _intern_counters(counters_key)

	# Reuse computed condition matches per (station, canonical attrs).
	eligible_rules_cache: dict[
		tuple[str, tuple[tuple[str, float], ...]],
		list[tuple[int, list[tuple[str | None, str, float]]]],
	] = {}

	def _get_eligible_rules(station_id: str, attrs_key: tuple[tuple[str, float], ...], attrs: dict[str, float]):
		if cache_limit > 0 and len(eligible_rules_cache) > cache_limit:
			eligible_rules_cache.clear()
		cache_key = (station_id, attrs_key)
		cached = eligible_rules_cache.get(cache_key)
		if cached is not None:
			return cached

		rules = rule_entries.get(station_id, [])
		eligible: list[tuple[int, list[tuple[str | None, str, float]]]] = []
		for global_idx, conds, effects, _ in rules:
			if all(_check_condition_compiled(cond, attrs) for cond in conds):
				eligible.append((global_idx, effects))

		eligible_rules_cache[cache_key] = eligible
		return eligible

	queue = deque()
	component_queues: dict[int, deque[int]] = {}
	active_component_ids = deque()
	active_component_set: set[int] = set()
	state_station_idx: list[int] = []
	state_attrs_id: list[int] = []
	state_counters_id: list[int] = []
	key_to_state_id: dict[tuple[int, int, int], int] = {}
	dominance_frontier: dict[tuple[int, int], list[int]] = {}
	predecessor_states: dict[int, int | tuple[int, ...] | list[int]] = {}
	incoming_target_edges: dict[int, int | tuple[int, ...] | set[int]] = {}
	transition_count = 0
	successful_state_ids: set[int] = set()
	state_depth: list[int] = []

	edge_src_reachable: set[int] = set()
	edge_taken: set[int] = set()
	edge_condition_failed: set[int] = set()
	checkpoint_levels: dict[str, set[int]] = {cid: set() for cid in target_checkpoint_ids}
	attrs_dict_cache: dict[int, dict[str, float]] = {}
	conn_condition_cache: dict[tuple[int, int, int], bool] = {}
	counters_dict_cache: dict[int, dict[int, int]] = {}
	state_limit_reached = False
	pending_state_count = 0
	queue_peak = 0
	queue_enqueued_total = 0
	queue_dequeued_total = 0
	queue_window_enqueued = 0
	queue_window_dequeued = 0
	queue_last_window_enqueued = 0
	queue_last_window_dequeued = 0
	# Track which state ids are currently enqueued (pending) to avoid duplicates
	pending_state_ids: set[int] = set()
	empty_collapse_map: dict[int, tuple[int, ...]] = {}
	dedup_rule_tasks_skipped = 0
	dedup_branch_payloads_skipped = 0
	dedup_next_candidates_skipped = 0
	state_reuse_hits = 0
	dominance_pruned_states = 0
	local_dominance_pruned_candidates = 0
	skipped_no_rule_applied = 0
	branch_enqueues_pruned_by_budget = 0
	branch_enqueues_allowed = 0
	
	# Early termination tracking removed - can cause incomplete results

	def _enqueue_state(state_id: int, station_idx: int):
		nonlocal pending_state_count, queue_peak, queue_enqueued_total, queue_window_enqueued
		# Do not enqueue if traversal/state limit already reached
		if state_limit_reached:
			return
		# Avoid enqueueing the same state multiple times
		if state_id in pending_state_ids:
			return
		component_id = station_component_ids[station_idx]
		if component_id in cyclic_component_ids:
			component_queue = component_queues.get(component_id)
			if component_queue is None:
				component_queue = deque()
				component_queues[component_id] = component_queue
			was_empty = not component_queue
			component_queue.append(state_id)
			pending_state_ids.add(state_id)
			if was_empty and component_id not in active_component_set:
				active_component_set.add(component_id)
				active_component_ids.append(component_id)
		else:
			queue.append(state_id)
			pending_state_ids.add(state_id)
		pending_state_count += 1
		queue_enqueued_total += 1
		queue_window_enqueued += 1
		if pending_state_count > queue_peak:
			queue_peak = pending_state_count

	def _pop_next_state() -> int | None:
		nonlocal pending_state_count, queue_dequeued_total, queue_window_dequeued
		while active_component_ids:
			component_id = active_component_ids[0]
			component_queue = component_queues.get(component_id)
			if component_queue:
				state_id = component_queue.pop()
				# mark dequeued
				pending_state_ids.discard(state_id)
				pending_state_count -= 1
				queue_dequeued_total += 1
				queue_window_dequeued += 1
				if not component_queue:
					active_component_ids.popleft()
					active_component_set.discard(component_id)
				return state_id
			active_component_ids.popleft()
			active_component_set.discard(component_id)
		if queue:
			state_id = queue.pop()
			# mark dequeued
			pending_state_ids.discard(state_id)
			pending_state_count -= 1
			queue_dequeued_total += 1
			queue_window_dequeued += 1
			return state_id
		return None

	def _counters_leq(left_id: int, right_id: int) -> bool:
		"""Return true iff counters(left) <= counters(right) component-wise."""
		left = counters_dict_cache.get(left_id)
		if left is None:
			if cache_limit > 0 and len(counters_dict_cache) > cache_limit:
				counters_dict_cache.clear()
			left = {idx: val for idx, val in counters_values[left_id]}
			counters_dict_cache[left_id] = left

		right = counters_dict_cache.get(right_id)
		if right is None:
			if cache_limit > 0 and len(counters_dict_cache) > cache_limit:
				counters_dict_cache.clear()
			right = {idx: val for idx, val in counters_values[right_id]}
			counters_dict_cache[right_id] = right

		for idx, left_val in left.items():
			if left_val > int(right.get(idx, 0)):
				return False
		return True

	def _append_predecessor(state_id: int, pred_state_id: int):
		existing = predecessor_states.get(state_id)
		if existing is None:
			predecessor_states[state_id] = pred_state_id
			return
		if isinstance(existing, int):
			predecessor_states[state_id] = (existing, pred_state_id)
			return
		if isinstance(existing, tuple):
			if len(existing) < 8:
				predecessor_states[state_id] = existing + (pred_state_id,)
			else:
				predecessor_states[state_id] = [*existing, pred_state_id]
			return
		existing.append(pred_state_id)

	def _iter_predecessors(state_id: int):
		existing = predecessor_states.get(state_id)
		if existing is None:
			return ()
		if isinstance(existing, int):
			return (existing,)
		return existing

	def _append_target_edge(state_id: int, conn_key: int):
		existing = incoming_target_edges.get(state_id)
		if existing is None:
			incoming_target_edges[state_id] = conn_key
			return
		if isinstance(existing, int):
			incoming_target_edges[state_id] = (existing, conn_key)
			return
		if isinstance(existing, tuple):
			if len(existing) < 8:
				incoming_target_edges[state_id] = existing + (conn_key,)
			else:
				incoming_target_edges[state_id] = set(existing)
				incoming_target_edges[state_id].add(conn_key)
			return
		existing.add(conn_key)

	def _iter_target_edges(state_id: int):
		existing = incoming_target_edges.get(state_id)
		if existing is None:
			return ()
		if isinstance(existing, int):
			return (existing,)
		return existing

	def _expand_branch(
		post_attrs: dict[str, float],
		post_counters_id: int,
		rule_global_idx: int | None,
		rule_collapsed_by_conn: dict[int, tuple[int, ...]],
		outgoing_edges: list[tuple[int, str]],
	):
		branch_src_reachable: set[int] = set()
		branch_taken: set[int] = set()
		branch_condition_failed: set[int] = set()
		next_candidates: list[tuple[int, str, int, int]] = []

		for conn_key, dst_id in outgoing_edges:
			if conn_key in target_conn_keys:
				branch_src_reachable.add(conn_key)

			conds = compiled_flow_conn_conditions.get(conn_key, ())
			collapsed_indices = ()
			if rule_global_idx is not None:
				collapsed_indices = rule_collapsed_by_conn.get(conn_key, ())
			rule_cache_key = -1 if rule_global_idx is None else int(rule_global_idx)
			conn_conds_ok = None
			if state_workers <= 1:
				cond_cache_key = (conn_key, id(post_attrs), rule_cache_key)
				conn_conds_ok = conn_condition_cache.get(cond_cache_key)
				if conn_conds_ok is None:
					if cache_limit > 0 and len(conn_condition_cache) > cache_limit:
						conn_condition_cache.clear()
					if not conds:
						conn_conds_ok = True
					elif not collapsed_indices:
						if len(conds) == 1:
							conn_conds_ok = _check_condition_compiled(conds[0], post_attrs)
						else:
							conn_conds_ok = all(_check_condition_compiled(cond, post_attrs) for cond in conds)
					elif len(collapsed_indices) >= len(conds):
						conn_conds_ok = True
					else:
						collapsed_lookup = set(collapsed_indices)
						conn_conds_ok = all(
							_check_condition_compiled(cond, post_attrs)
							for idx, cond in enumerate(conds)
							if idx not in collapsed_lookup
						)
					conn_condition_cache[cond_cache_key] = conn_conds_ok
			else:
				# Threaded path: lock-free, no shared cache
				if not conds:
					conn_conds_ok = True
				elif not collapsed_indices:
					if len(conds) == 1:
						conn_conds_ok = _check_condition_compiled(conds[0], post_attrs)
					else:
						conn_conds_ok = all(_check_condition_compiled(cond, post_attrs) for cond in conds)
				elif len(collapsed_indices) >= len(conds):
					conn_conds_ok = True
				else:
					collapsed_lookup = set(collapsed_indices)
					conn_conds_ok = all(
						_check_condition_compiled(cond, post_attrs)
						for idx, cond in enumerate(conds)
						if idx not in collapsed_lookup
					)

			if not conn_conds_ok:
				if conn_key in target_conn_keys:
					branch_condition_failed.add(conn_key)
				continue

			if conn_key in target_conn_keys:
				branch_taken.add(conn_key)

			if dst_id not in can_reach_checkpoint_graph:
				continue

			# Include which rule (if any) produced this post-state and whether
			# the source station actually has rules. Consumers will use this to
			# avoid enqueuing states created without applying any rule when the
			# source station does define rules.
			source_has_rules = bool(rule_entries.get(station_id))
			next_candidates.append((conn_key, dst_id, post_attrs, post_counters_id, rule_global_idx, source_has_rules))

		return branch_src_reachable, branch_taken, branch_condition_failed, next_candidates

	def _register_state(station_idx: int, attrs_id: int, counters_id: int, depth: int) -> int:
		nonlocal state_limit_reached, state_reuse_hits, dominance_pruned_states
		if depth > max_depth:
			return -1
		state_key = (station_idx, attrs_id, counters_id)
		sid = key_to_state_id.get(state_key)
		if sid is not None:
			state_reuse_hits += 1
			if depth < state_depth[sid]:
				state_depth[sid] = depth
			return sid

		# A state with the same station and attribute snapshot but higher used-rule
		# counters is always weaker: it can only have fewer remaining traversals.
		frontier_key = (station_idx, attrs_id)
		frontier = dominance_frontier.get(frontier_key, [])
		for existing_counters_id in frontier:
			if _counters_leq(existing_counters_id, counters_id):
				dominance_pruned_states += 1
				return -1

		if frontier:
			next_frontier = [cid for cid in frontier if not _counters_leq(counters_id, cid)]
			next_frontier.append(counters_id)
			dominance_frontier[frontier_key] = next_frontier
		else:
			dominance_frontier[frontier_key] = [counters_id]

		if max_states > 0 and len(key_to_state_id) >= max_states:
			state_limit_reached = True
			return -1
		sid = len(key_to_state_id)
		key_to_state_id[state_key] = sid
		state_station_idx.append(station_idx)
		state_attrs_id.append(attrs_id)
		state_counters_id.append(counters_id)
		state_depth.append(depth)
		_enqueue_state(sid, station_idx)
		return sid

	for root_id in root_ids:
		_register_state(station_id_to_idx[root_id], 0, 0, 0)

	_safe_status_emit(status_emit, "Validierung: Zustandsraum wird analysiert ...")
	cancelled = False
	state_pool = ThreadPoolExecutor(max_workers=max(1, state_workers)) if state_workers > 1 else None
	progress_every_states = max(1000, int(snapshot.get("progress_every_states", 5000)))
	progress_last_emit_count = 0
	progress_last_emit_time = start_time

	try:
		while True:
			src_state_id = _pop_next_state()
			# If the queue is temporarily empty, wait a short time for any
			# in-flight tasks to produce more states before deciding to finish.
			if src_state_id is None:
				# small backoff loop: wait up to 100ms in 10ms steps
				wait_start = time.perf_counter()
				waited = False
				while time.perf_counter() - wait_start < 0.1:
					if _is_cancelled(cancel_event):
						cancelled = True
						break
					# try to pop again; if a new state was enqueued, continue processing
					src_state_id = _pop_next_state()
					if src_state_id is not None:
						waited = True
						break
					# brief sleep to yield to background threads
					time.sleep(0.01)
				if src_state_id is None and not waited:
					# still empty after waiting -> done
					break
			if _is_cancelled(cancel_event):
				cancelled = True
				break
			if state_limit_reached:
				_safe_status_emit(status_emit, "Validierung: Zustandslimit erreicht, Teilergebnis wird erstellt ...")
				break

			processed_states = len(state_depth) - pending_state_count
			now = time.perf_counter()
			if (
				processed_states - progress_last_emit_count >= progress_every_states
				or (now - progress_last_emit_time >= 1.5 and processed_states > progress_last_emit_count)
			):
				queue_window_net = queue_window_enqueued - queue_window_dequeued
				queue_last_window_enqueued = queue_window_enqueued
				queue_last_window_dequeued = queue_window_dequeued
				queue_window_enqueued = 0
				queue_window_dequeued = 0
				progress_last_emit_count = processed_states
				progress_last_emit_time = now
				_safe_status_emit(
					status_emit,
					(
						"Validierung läuft ... SAT-BMC "
						f"(Zustände verarbeitet: {processed_states}, "
						f"Queue: {pending_state_count}, "
						f"QueuePeak: {queue_peak}, "
						f"QueueΔFenster: {queue_window_net} "
						f"(in: {queue_last_window_enqueued}, out: {queue_last_window_dequeued}), "
						f"Übergänge: {transition_count})"
					),
				)
			
			# Automatic cache management: periodically clear based on memory pressure
			queue_progress = len(state_depth)
			if queue_progress > 0 and queue_progress % 5000 == 0:
				if cache_limit > 0 and len(attrs_dict_cache) > cache_limit * 0.8:
					attrs_dict_cache.clear()
				if cache_limit > 0 and len(conn_condition_cache) > cache_limit * 0.8:
					conn_condition_cache.clear()
				if cache_limit > 0 and len(eligible_rules_cache) > cache_limit * 0.8:
					eligible_rules_cache.clear()

			# Depth-first traversal keeps the live frontier much smaller than BFS.
			depth = state_depth[src_state_id]
			if depth > max_depth:
				continue

			station_idx = state_station_idx[src_state_id]
			attrs_id = state_attrs_id[src_state_id]
			counters_id = state_counters_id[src_state_id]
			station_id = station_idx_to_id[station_idx]
			attrs = attrs_dict_cache.get(attrs_id)
			if attrs is None:
				if cache_limit > 0 and len(attrs_dict_cache) > cache_limit:
					attrs_dict_cache.clear()
				attrs_key = attrs_values[attrs_id]
				attrs = {k: v for k, v in attrs_key}
				attrs_dict_cache[attrs_id] = attrs
			else:
				attrs_key = attrs_values[attrs_id]
			used_counts = counters_dict_cache.get(counters_id)
			if used_counts is None:
				if cache_limit > 0 and len(counters_dict_cache) > cache_limit:
					counters_dict_cache.clear()
				used_counts = {idx: val for idx, val in counters_values[counters_id]}
				counters_dict_cache[counters_id] = used_counts

			if station_id in checkpoint_ids:
				successful_state_ids.add(src_state_id)
				if station_id in checkpoint_levels:
					checkpoint_levels[station_id].add(0)

			eligible = _get_eligible_rules(station_id, attrs_key, attrs)
			enabled = []
			for gidx, effects in eligible:
				if gidx in tracked_rule_indices and used_counts.get(gidx, 0) >= rule_limits[gidx]:
					continue
				enabled.append((gidx, effects))
			if not enabled and not rule_entries.get(station_id):
				enabled = [(None, [])]

			outgoing_edges = flow_succs.get(station_id, [])
			if not outgoing_edges:
				continue

			branch_effects = []
			queue_pressure_level = 0
			if pending_state_count > queue_backpressure_start:
				queue_pressure_level = (pending_state_count - queue_backpressure_start) // queue_backpressure_step + 1
			dynamic_effect_parallel_min_rules = effect_parallel_min_rules + (
				queue_pressure_level * queue_backpressure_parallel_scale
			)
			dynamic_state_parallel_min_branches = state_parallel_min_branches + (
				queue_pressure_level * queue_backpressure_parallel_scale
			)
			if enabled:
				if apply_all_rules:
					effects: list[tuple[str | None, str, float]] = []
					inc_indices: list[int] = []
					for gidx, compiled_effects in enabled:
						effects.extend(compiled_effects)
						if gidx is not None:
							inc_indices.append(gidx)
					new_counters_id = _increment_used_counts(counters_id, used_counts, inc_indices)
					# mark combined-apply as rule-applied with sentinel -1
					branch_effects.append((_apply_effects_compiled(attrs, effects), new_counters_id, -1, {}))
				else:
					rule_tasks: list[tuple[list[tuple[str | None, str, float]], int, int | None, dict[int, tuple[int, ...]]]] = []
					seen_rule_task_keys: set[tuple[tuple[tuple[str | None, str, float], ...], int, tuple[tuple[int, tuple[int, ...]], ...]]] = set()
					for gidx, compiled_effects in enabled:
						new_counters_id = _increment_used_counts(counters_id, used_counts, [gidx] if gidx is not None else [])
						rule_collapsed_by_conn = (
							rule_collapse_by_station_rule.get((station_id, gidx), empty_collapse_map)
							if gidx is not None
							else empty_collapse_map
						)
						rule_task_key = (
							tuple(compiled_effects),
							new_counters_id,
							tuple(sorted((conn_key, idxs) for conn_key, idxs in rule_collapsed_by_conn.items())),
						)
						if rule_task_key in seen_rule_task_keys:
							dedup_rule_tasks_skipped += 1
							continue
						seen_rule_task_keys.add(rule_task_key)
						rule_tasks.append((compiled_effects, new_counters_id, gidx, rule_collapsed_by_conn))

					if state_pool is not None and len(rule_tasks) >= dynamic_effect_parallel_min_rules:
						for chunk_start in range(0, len(rule_tasks), effect_parallel_chunk_size):
							chunk = rule_tasks[chunk_start : chunk_start + effect_parallel_chunk_size]
							future_to_meta = {
								state_pool.submit(_apply_effects_compiled, attrs, compiled_effects): (new_counters_id, gidx, rule_collapsed_by_conn)
								for compiled_effects, new_counters_id, gidx, rule_collapsed_by_conn in chunk
							}
							for future in as_completed(future_to_meta):
								if _is_cancelled(cancel_event):
									cancelled = True
									break
								try:
									post_attrs = future.result()
								except Exception:
									continue
								new_counters_id, gidx, rule_collapsed_by_conn = future_to_meta[future]
								branch_effects.append((post_attrs, new_counters_id, gidx, rule_collapsed_by_conn))
							if cancelled:
								break
					else:
						for compiled_effects, new_counters_id, gidx, rule_collapsed_by_conn in rule_tasks:
							branch_effects.append((_apply_effects_compiled(attrs, compiled_effects), new_counters_id, gidx, rule_collapsed_by_conn))
			else:
				# No rule enabled means no outgoing transition from this state.
				continue

			if cancelled:
				break

			branch_payloads = []
			seen_branch_payloads: dict[tuple[int, int], int] = {}
			post_attrs_obj_cache: dict[int, int] = {}
			station_payload_relevant_attrs = station_relevant_attrs_by_idx[station_idx]
			for post_attrs, post_counters_id, rule_global_idx, rule_collapsed_by_conn in branch_effects:
				obj_id = id(post_attrs)
				post_attrs_id = post_attrs_obj_cache.get(obj_id)
				if post_attrs_id is None:
					post_attrs_id = _intern_attrs(
						_canonical_attrs_condition_aware(
							post_attrs,
							station_payload_relevant_attrs,
							compare_attrs,
							attr_thresholds,
						)
					)
					post_attrs_obj_cache[obj_id] = post_attrs_id
				payload_key = (post_attrs_id, post_counters_id)
				existing_idx = seen_branch_payloads.get(payload_key)
				if existing_idx is not None:
					dedup_branch_payloads_skipped += 1
					existing = branch_payloads[existing_idx]
					existing_rule_idx = existing[3]
					existing_collapses = existing[4]
					if existing_rule_idx != rule_global_idx or existing_collapses != rule_collapsed_by_conn:
						# Merge equivalent payloads conservatively: disable collapse shortcuts.
						branch_payloads[existing_idx] = (
							existing[0],
							existing[1],
							existing[2],
							None,
							empty_collapse_map,
						)
					continue
				seen_branch_payloads[payload_key] = len(branch_payloads)
				branch_payloads.append((post_attrs, post_attrs_id, post_counters_id, rule_global_idx, rule_collapsed_by_conn))

			dst_attrs_id_cache: dict[tuple[int, int], int] = {}
			expansion_seen_states: set[tuple[int, int, int]] = set()
			expansion_local_frontier: dict[tuple[int, int], list[int]] = {}

			def _consume_branch_result(branch_result) -> bool:
				nonlocal transition_count, dedup_next_candidates_skipped, local_dominance_pruned_candidates, skipped_no_rule_applied, future_observable_edges_skipped, branch_enqueues_pruned_by_budget, branch_enqueues_allowed
				branch_src_reachable, branch_taken, branch_condition_failed, next_candidates = branch_result
				edge_src_reachable.update(branch_src_reachable)
				edge_taken.update(branch_taken)
				edge_condition_failed.update(branch_condition_failed)

				seen_next_candidates: set[tuple[int, int, int, int]] = set()
				candidates_list: list[tuple[tuple[int, int, int], tuple[int, int, dict, int, int, bool]]] = []
				# Collect candidates first, apply budgeted pruning/sorting below.
				for item in next_candidates:
					# support both old and new tuple shapes for safety
					if len(item) >= 6:
						conn_key, dst_id, post_attrs, post_counters_id, branch_rule_idx, branch_source_has_rules = item
					else:
						conn_key, dst_id, post_attrs, post_counters_id = item
						branch_rule_idx = None
						branch_source_has_rules = False
					dst_station_idx = station_id_to_idx[dst_id]
					dst_cache_key = (id(post_attrs), dst_station_idx)
					dst_attrs_id = dst_attrs_id_cache.get(dst_cache_key)
					if dst_attrs_id is None:
						dst_attrs_id = _intern_attrs(
							_canonical_attrs_condition_aware(
								post_attrs,
								station_relevant_attrs_by_idx[dst_station_idx],
								compare_attrs,
								attr_thresholds,
							)
						)
						dst_attrs_id_cache[dst_cache_key] = dst_attrs_id
					next_key = (conn_key, dst_station_idx, dst_attrs_id, post_counters_id)
					if next_key in seen_next_candidates:
						dedup_next_candidates_skipped += 1
						continue
					seen_next_candidates.add(next_key)
					local_frontier_key = (dst_station_idx, dst_attrs_id)
					local_frontier = expansion_local_frontier.get(local_frontier_key, [])
					if any(_counters_leq(existing_counters_id, post_counters_id) for existing_counters_id in local_frontier):
						local_dominance_pruned_candidates += 1
						continue
					if local_frontier:
						expansion_local_frontier[local_frontier_key] = [
							existing_counters_id
							for existing_counters_id in local_frontier
							if not _counters_leq(post_counters_id, existing_counters_id)
						] + [post_counters_id]
					else:
						expansion_local_frontier[local_frontier_key] = [post_counters_id]
					state_frontier_key = (dst_station_idx, dst_attrs_id, post_counters_id)
					if state_frontier_key in expansion_seen_states:
						dedup_next_candidates_skipped += 1
						continue
					expansion_seen_states.add(state_frontier_key)
					# compute distance heuristic and other flags
					src_dist = station_distance.get(station_id, 10**9)
					dst_dist = station_distance.get(dst_id, 10**9)
					is_target_edge = conn_key in target_conn_keys
					rule_applied_flag = branch_rule_idx is not None
					# Early skip: if no rule applied but source has rules, tentatively skip
					# (store skipped candidates so we can reinstate one if pruning would
					# otherwise remove the entire branch). This avoids emptying the
					# global queue by aggressive rule-less pruning.
					if not rule_applied_flag and branch_source_has_rules:
						# store skipped candidate for potential reinstatement
						skipped_no_rule_candidates.append((sort_key, (conn_key, dst_id, post_attrs, post_counters_id, dst_station_idx, dst_attrs_id)))
						continue
					# Backpressure check will be applied via budget selection below.
					# Candidate sorting key: prefer target edges, then smaller dst_dist, then rule_applied
					sort_key = (0 if is_target_edge else 1, dst_dist, 0 if rule_applied_flag else 1)
					candidates_list.append((sort_key, (conn_key, dst_id, post_attrs, post_counters_id, dst_station_idx, dst_attrs_id)))

				# If no candidates after filtering, but we had candidates skipped due to
				# 'no rule applied', reinstate the best skipped candidate so the branch
				# still progresses. This prevents aggressive pruning from emptying the
				# global queue and causing premature termination.
				if not candidates_list:
					if skipped_no_rule_candidates:
						# pick best by sort_key (lowest)
						skipped_no_rule_candidates.sort(key=lambda x: x[0])
						candidates_list.append(skipped_no_rule_candidates[0])
						# account for metrics: one earlier increment was not recorded,
						# so do not modify skipped_no_rule_applied here (it remains a
						# count of truly skipped candidates)
					else:
						return state_limit_reached

				# Decide per-branch enqueue budget based on queue pressure
				queue_pressure_level = 0
				if pending_state_count > queue_backpressure_start:
					queue_pressure_level = (pending_state_count - queue_backpressure_start) // queue_backpressure_step + 1
				if queue_pressure_level >= 4:
					budget = 1
				elif queue_pressure_level >= 2:
					budget = 2
				elif queue_pressure_level >= 1:
					budget = 4
				else:
					budget = None

				# Select candidates according to budget and sort key
				if budget is not None:
					candidates_list.sort(key=lambda x: x[0])
					selected = [c[1] for c in candidates_list[:budget]]
					branch_enqueues_pruned_by_budget += len(candidates_list) - len(selected)
				else:
					selected = [c[1] for c in candidates_list]

				# Register selected candidates
				for conn_key, dst_id, post_attrs, post_counters_id, dst_station_idx, dst_attrs_id in selected:
					dst_state_id = _register_state(dst_station_idx, dst_attrs_id, post_counters_id, depth + 1)
					if dst_state_id < 0:
						continue
					_append_predecessor(dst_state_id, src_state_id)
					if conn_key in target_conn_keys:
						_append_target_edge(dst_state_id, conn_key)
					transition_count += 1
					branch_enqueues_allowed += 1

				return state_limit_reached

			if state_pool is not None and len(branch_payloads) >= dynamic_state_parallel_min_branches:
				for chunk_start in range(0, len(branch_payloads), state_parallel_chunk_size):
					chunk = branch_payloads[chunk_start : chunk_start + state_parallel_chunk_size]
					futures = [
						state_pool.submit(
							_expand_branch,
							post_attrs,
							post_counters_id,
							rule_global_idx,
							rule_collapsed_by_conn,
							outgoing_edges,
						)
						for post_attrs, post_attrs_id, post_counters_id, rule_global_idx, rule_collapsed_by_conn in chunk
					]
					for future in as_completed(futures):
						if _is_cancelled(cancel_event):
							cancelled = True
							break
						try:
							branch_result = future.result()
						except Exception:
							continue
						if _consume_branch_result(branch_result):
							break
					if cancelled or state_limit_reached:
						break
				if cancelled:
					break
			else:
				for post_attrs, post_attrs_id, post_counters_id, rule_global_idx, rule_collapsed_by_conn in branch_payloads:
					branch_result = _expand_branch(
						post_attrs,
						post_counters_id,
						rule_global_idx,
						rule_collapsed_by_conn,
						outgoing_edges,
					)
					if _consume_branch_result(branch_result):
						break

			if state_limit_reached:
				break
	finally:
		if state_pool is not None:
			state_pool.shutdown(wait=False)

	if cancelled:
		return {"cancelled": True}

	_safe_status_emit(status_emit, "Validierung: Rückwärtsanalyse und Klassifizierung ...")

	analysis_truncated = state_limit_reached
	state_count_metric = len(state_depth)
	if queue_window_enqueued or queue_window_dequeued:
		queue_last_window_enqueued = queue_window_enqueued
		queue_last_window_dequeued = queue_window_dequeued
	queue_last_window_net = queue_last_window_enqueued - queue_last_window_dequeued

	success_edges: set[int] = set()
	if successful_state_ids:
		rev_queue = deque(successful_state_ids)
		rev_seen = set(successful_state_ids)
		while rev_queue:
			state_id = rev_queue.popleft()
			for conn_key in _iter_target_edges(state_id):
				success_edges.add(conn_key)
			for pred_state_id in _iter_predecessors(state_id):
				if pred_state_id not in rev_seen:
					rev_seen.add(pred_state_id)
					rev_queue.append(pred_state_id)

	# Drop large temporary state-space structures before final classification.
	queue.clear()
	component_queues.clear()
	active_component_ids.clear()
	active_component_set.clear()
	state_station_idx.clear()
	state_attrs_id.clear()
	state_counters_id.clear()
	state_depth.clear()
	pending_state_count = 0
	key_to_state_id.clear()
	dominance_frontier.clear()
	predecessor_states.clear()
	incoming_target_edges.clear()
	successful_state_ids.clear()
	attrs_dict_cache.clear()
	counters_dict_cache.clear()
	conn_condition_cache.clear()
	eligible_rules_cache.clear()
	attrs_pool.clear()
	attrs_values.clear()
	counters_pool.clear()
	counters_values.clear()
	rule_entries.clear()
	rule_limits.clear()
	compiled_flow_conn_conditions.clear()
	rule_collapse_map.clear()
	rule_collapse_by_station_rule.clear()
	# Clear pending IDs tracked for deduplication
	pending_state_ids.clear()

	best_states = {}
	for conn_key in target_conn_keys:
		has_conds = conn_has_conditions.get(conn_key, False)
		reasons: list[str] = []

		if analysis_truncated and conn_key not in success_edges:
			state = CONNECTION_STATE.UNKNOWN
			reasons.append("Analyse unvollständig: Zustandslimit erreicht, Ergebnis für diese Verbindung ist offen.")
		elif conn_key in success_edges:
			if has_conds:
				state = CONNECTION_STATE.CONDITIONAL_VALID
				reasons.append("Die Verbindung ist auf mindestens einem gültigen Pfad erreichbar (bedingungenabhängig).")
			else:
				state = CONNECTION_STATE.VALID
				reasons.append("Die Verbindung liegt auf einem gültigen Pfad von Start zu Endstation.")
		elif conn_key in edge_taken:
			state = CONNECTION_STATE.CONDITIONAL_INVALID
			reasons.append("Die Verbindung ist erreichbar, führt jedoch in keiner verfolgten Konfiguration zu einer Endstation.")
		elif conn_key in edge_src_reachable:
			state = CONNECTION_STATE.INVALID
			if conn_key in edge_condition_failed:
				reasons.append("Die Bedingungen der Verbindung sind in den erreichbaren Zuständen nicht erfüllbar.")
			else:
				reasons.append("Keine aktivierbare Regel erzeugt einen Übergang über diese Verbindung.")
		else:
			state = CONNECTION_STATE.INVALID
			reasons.append("Keine erreichbare Route von einer Startstation zum Quellknoten dieser Verbindung.")

		best_states[conn_key] = (state, reasons)

	out_checkpoint_levels = {
		checkpoint_id: sorted(levels)
		for checkpoint_id, levels in checkpoint_levels.items()
		if levels and checkpoint_id in target_checkpoint_ids
	}

	# Optional NuSMV result can downgrade unreachable targets early in metrics.
	nusmv_reachable = sum(1 for v in nusmv_checkpoint_reachability.values() if v)
	duration_ms = round((time.perf_counter() - start_time) * 1000)

	# Keep temp model only on explicit request.
	smv_file_metric = smv_path
	if smv_path and not bool(snapshot.get("keep_smv_file", False)):
		try:
			os.remove(smv_path)
			smv_file_metric = None
		except OSError:
			pass

	_safe_status_emit(
		status_emit,
		(
			"Validierung abgeschlossen "
			f"({state_count_metric} Zustände, {transition_count} Übergänge, "
			f"QueuePeak: {queue_peak}, QueueNetto: {queue_enqueued_total - queue_dequeued_total}, {duration_ms} ms)."
		),
	)

	return {
		"best_states": best_states,
		"checkpoint_levels": out_checkpoint_levels,
		"metrics": {
			"mode": "nu-smv+state",
			"total_flow": len(flow_conn_keys),
			"target_flow": len(target_conn_keys),
			"total_checkpoints": len(checkpoint_ids),
			"target_checkpoints": len(target_checkpoint_ids),
			"duration_ms": duration_ms,
			"smv_file": smv_file_metric,
			"nusmv_available": _find_nusmv_binary() is not None,
			"nusmv_checkpoint_reachable": nusmv_reachable,
			"graph_checkpoint_reachable": len(can_reach_checkpoint_graph & checkpoint_ids),
			"profiling": {
				"state_count": state_count_metric,
				"transition_count": transition_count,
				"queue_peak": queue_peak,
				"queue_enqueued_total": queue_enqueued_total,
				"queue_dequeued_total": queue_dequeued_total,
				"queue_net_total": queue_enqueued_total - queue_dequeued_total,
				"queue_window_enqueued": queue_last_window_enqueued,
				"queue_window_dequeued": queue_last_window_dequeued,
				"queue_window_net": queue_last_window_net,
				"state_workers": max(1, state_workers),
				"state_parallel_min_branches": state_parallel_min_branches,
				"state_parallel_chunk_size": state_parallel_chunk_size,
				"effect_parallel_min_rules": effect_parallel_min_rules,
				"effect_parallel_chunk_size": effect_parallel_chunk_size,
				"state_limit": max_states,
				"state_limit_reached": state_limit_reached,
				"analysis_truncated": analysis_truncated,
				"collapsed_conditions": collapsed_condition_count,
				"future_observable_edges_skipped": future_observable_edges_skipped,
				"dedup_rule_tasks_skipped": dedup_rule_tasks_skipped,
				"dedup_branch_payloads_skipped": dedup_branch_payloads_skipped,
				"dedup_next_candidates_skipped": dedup_next_candidates_skipped,
				"state_reuse_hits": state_reuse_hits,
				"dominance_pruned_states": dominance_pruned_states,
					"local_dominance_pruned_candidates": local_dominance_pruned_candidates,
					"skipped_no_rule_applied": skipped_no_rule_applied,
					"branch_enqueues_pruned_by_budget": branch_enqueues_pruned_by_budget,
					"branch_enqueues_allowed": branch_enqueues_allowed,
			},
		},
	}
