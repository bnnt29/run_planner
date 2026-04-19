"""SAT-based bounded model checking for flow validation.

This module provides a bounded model checking backend using z3. It encodes
node/edge transitions and rule-usage limits symbolically, then refines
candidates with exact condition/effect simulation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from collections import deque

from .items import CONDITION_OP, CONNECTION_STATE, EFFECT_OP

try:
    from z3 import And, Bool, If, Implies, Not, Or, Solver, Sum, sat
except Exception as exc:  # pragma: no cover
    raise ImportError("z3-solver is required for SAT validation") from exc


@dataclass
class _RuleRef:
    station_id: str
    index: int
    rule_id: str
    max_traversals: int
    group_number: int
    conditions: list[dict]
    effects: list[dict]


class SatValidationEngine:
    def __init__(self, snapshot: dict):
        self.snapshot = snapshot

        self.station_data = snapshot["station_data"]
        self.root_ids = list(snapshot.get("root_ids", []))
        self.checkpoint_ids = set(snapshot.get("checkpoint_ids", []))
        self.flow_succs = snapshot.get("flow_succs", {})
        self.flow_conn_conditions = snapshot.get("flow_conn_conditions", {})
        self.flow_conn_keys = list(snapshot.get("flow_conn_keys", []))
        self.target_conn_keys = set(snapshot.get("target_conn_keys", self.flow_conn_keys))
        self.target_checkpoint_ids = set(snapshot.get("target_checkpoint_ids", self.checkpoint_ids))

        self.station_ids = sorted(self.station_data.keys())
        self.station_idx = {station_id: idx for idx, station_id in enumerate(self.station_ids)}

        self.edge_tuples = []
        for src_id, successors in self.flow_succs.items():
            for conn_key, dst_id in successors:
                self.edge_tuples.append((conn_key, src_id, dst_id))
        self.edge_tuples.sort(key=lambda item: str(item[0]))
        self.edge_idx = {conn_key: idx for idx, (conn_key, _, _) in enumerate(self.edge_tuples)}
        self.edge_meta = {conn_key: (src_id, dst_id) for conn_key, src_id, dst_id in self.edge_tuples}

        self.rules = self._collect_rules()
        self.rules_by_station: dict[str, list[_RuleRef]] = {sid: [] for sid in self.station_ids}
        for rule in self.rules:
            self.rules_by_station.setdefault(rule.station_id, []).append(rule)

        limits_sum = sum(rule.max_traversals for rule in self.rules)
        fallback_bound = max(3, len(self.station_ids) + len(self.edge_tuples))
        self.max_bound = min(
            max(1, int(snapshot.get("max_depth", fallback_bound))),
            max(fallback_bound, limits_sum + len(self.station_ids)),
        )

        # Topological pre-analysis for fast impossible-query elimination and tighter k ranges.
        self._dist_from_roots = self._multi_source_bfs(
            starts=[sid for sid in self.root_ids if sid in self.station_idx],
            succs=self.flow_succs,
        )
        reverse_succs = self._build_reverse_succs()
        self._dist_to_checkpoint = self._multi_source_bfs(
            starts=[sid for sid in self.checkpoint_ids if sid in self.station_idx],
            succs=reverse_succs,
        )

        self._conn_min_k: dict[object, int] = {}
        for conn_key, src_id, dst_id in self.edge_tuples:
            dist_root_to_src = self._dist_from_roots.get(src_id)
            dist_dst_to_cp = self._dist_to_checkpoint.get(dst_id)
            if dist_root_to_src is None or dist_dst_to_cp is None:
                continue
            self._conn_min_k[conn_key] = int(dist_root_to_src + 1 + dist_dst_to_cp)

        self._checkpoint_min_k: dict[str, int] = {}
        for checkpoint_id in self.checkpoint_ids:
            dist = self._dist_from_roots.get(checkpoint_id)
            if dist is not None:
                self._checkpoint_min_k[checkpoint_id] = int(dist)

    def _build_reverse_succs(self) -> dict[str, list[tuple[object, str]]]:
        reverse: dict[str, list[tuple[object, str]]] = {sid: [] for sid in self.station_ids}
        for src_id, successors in self.flow_succs.items():
            for conn_key, dst_id in successors:
                reverse.setdefault(dst_id, []).append((conn_key, src_id))
        return reverse

    @staticmethod
    def _multi_source_bfs(starts: list[str], succs: dict[str, list[tuple[object, str]]]) -> dict[str, int]:
        if not starts:
            return {}
        dist: dict[str, int] = {}
        queue = deque()
        for sid in starts:
            if sid in dist:
                continue
            dist[sid] = 0
            queue.append(sid)

        while queue:
            cur = queue.popleft()
            cur_dist = dist[cur]
            for _, nxt in succs.get(cur, []):
                if nxt in dist:
                    continue
                dist[nxt] = cur_dist + 1
                queue.append(nxt)
        return dist

    def _collect_rules(self) -> list[_RuleRef]:
        refs: list[_RuleRef] = []
        for station_id, station in self.station_data.items():
            for idx, rule in enumerate(station.rules):
                rid = str(rule.get("rule_id") or f"{station_id}:{idx}")
                try:
                    limit = min(1000, max(1, int(rule.get("max_traversals", 20) or 20)))
                except (TypeError, ValueError):
                    limit = 20
                try:
                    group_num = int(rule.get("group_number", idx + 1))
                except (TypeError, ValueError):
                    group_num = idx + 1
                refs.append(
                    _RuleRef(
                        station_id=station_id,
                        index=idx,
                        rule_id=rid,
                        max_traversals=limit,
                        group_number=group_num,
                        conditions=list(rule.get("conditions", [])),
                        effects=list(rule.get("effects", [])),
                    )
                )
        return refs

    @staticmethod
    def _check_condition(cond: dict, state: dict) -> bool:
        attr_id = cond.get("attr_id")
        op = cond.get("op", CONDITION_OP.EXISTS.value)
        value = float(cond.get("value", 0.0))
        count = 0.0 if attr_id is None or state.get(attr_id) is None else float(state.get(attr_id, 0.0))

        if op == CONDITION_OP.EXISTS.value:
            return count > 0
        if op == CONDITION_OP.NOT_EXISTS.value:
            return count == 0
        if op == CONDITION_OP.EQUALS.value:
            return count == value
        if op == CONDITION_OP.NOT_EQUALS.value:
            return count != value
        if op == CONDITION_OP.GREATER.value:
            return count > value
        if op == CONDITION_OP.GREATER_EQ.value:
            return count >= value
        if op == CONDITION_OP.LESS.value:
            return count < value
        if op == CONDITION_OP.LESS_EQ.value:
            return count <= value
        return False

    @staticmethod
    def _apply_effects(state: dict, effects: list[dict]) -> dict:
        out = dict(state)
        for eff in effects:
            attr_id = eff.get("attr_id")
            if attr_id is None:
                continue
            action = eff.get("action", EFFECT_OP.SET.value)
            value = float(eff.get("value", 0.0))
            present = attr_id in out and out[attr_id] not in (None, 0)

            if action == EFFECT_OP.ADD.value:
                out[attr_id] = value if not present else out[attr_id] + value
            elif action == EFFECT_OP.SUBTRACT.value:
                out[attr_id] = -value if not present else out[attr_id] - value
            elif action == EFFECT_OP.MULTIPLY.value:
                out[attr_id] = value if not present else out[attr_id] * value
            elif action == EFFECT_OP.DIVIDE.value:
                out[attr_id] = (1 / value) if not present else out[attr_id] / value
            elif action == EFFECT_OP.MOD.value:
                out[attr_id] = (1 % value) if not present else out[attr_id] % value
            else:
                out[attr_id] = value
        return out

    @staticmethod
    def _exactly_one(solver: Solver, vars_list: list):
        if not vars_list:
            return
        solver.add(Or(*vars_list))
        for i in range(len(vars_list)):
            for j in range(i + 1, len(vars_list)):
                solver.add(Or(Not(vars_list[i]), Not(vars_list[j])))

    def _simulate_model(self, model_info: dict, relaxed: bool) -> bool:
        state = {}
        rule_use_counter = {rule.rule_id: 0 for rule in self.rules}

        node_sequence = model_info["node_sequence"]
        edge_sequence = model_info["edge_sequence"]
        selected_rules = model_info.get("selected_rules", {})
 
        for step, edge_info in enumerate(edge_sequence, start=1):
            conn_key, src_id, dst_id = edge_info
            if node_sequence[step - 1] != src_id or node_sequence[step] != dst_id:
                return False

            if not relaxed:
                for cond in self.flow_conn_conditions.get(conn_key, []):
                    if not self._check_condition(cond, state):
                        return False

            station_rules = self.rules_by_station.get(dst_id, [])
            if not station_rules:
                continue

            chosen_rule_id = selected_rules.get(step, {}).get(dst_id)
            if not chosen_rule_id:
                continue
            selected = next((rule for rule in station_rules if rule.rule_id == chosen_rule_id), None)
            if selected is None:
                return False
            if not relaxed and rule_use_counter[selected.rule_id] >= selected.max_traversals:
                return False
            ok = all(self._check_condition(cond, state) for cond in selected.conditions)
            if not relaxed and not ok:
                return False
            if ok:
                state = self._apply_effects(state, selected.effects)
            rule_use_counter[selected.rule_id] += 1

        return True

    def _build_solver(self, k: int, require_conn_key: int | None, require_checkpoint_id: str | None):
        solver = Solver()

        node_vars = {
            (station_id, t): Bool(f"n_{self.station_idx[station_id]}_{t}")
            for station_id in self.station_ids
            for t in range(k + 1)
        }
        edge_vars = {
            (edge_idx, t): Bool(f"e_{edge_idx}_{t}")
            for edge_idx in range(len(self.edge_tuples))
            for t in range(k)
        }

        for t in range(k + 1):
            row = [node_vars[(sid, t)] for sid in self.station_ids]
            self._exactly_one(solver, row)

        if self.root_ids:
            solver.add(Or(*[node_vars[(sid, 0)] for sid in self.root_ids if sid in self.station_idx]))

        end_targets = [require_checkpoint_id] if require_checkpoint_id else [sid for sid in self.checkpoint_ids if sid in self.station_idx]
        if end_targets:
            solver.add(Or(*[node_vars[(sid, k)] for sid in end_targets]))

        for t in range(k):
            out_vars_by_src: dict[str, list] = {sid: [] for sid in self.station_ids}
            for edge_idx, (_, src_id, dst_id) in enumerate(self.edge_tuples):
                ev = edge_vars[(edge_idx, t)]
                out_vars_by_src.setdefault(src_id, []).append(ev)
                solver.add(Implies(ev, node_vars[(src_id, t)]))
                solver.add(Implies(ev, node_vars[(dst_id, t + 1)]))

            all_edges_t = [edge_vars[(edge_idx, t)] for edge_idx in range(len(self.edge_tuples))]
            self._exactly_one(solver, all_edges_t)

            for src_id, out_vars in out_vars_by_src.items():
                if out_vars:
                    solver.add(Implies(node_vars[(src_id, t)], Or(*out_vars)))

        if require_conn_key is not None and require_conn_key in self.edge_idx:
            req_idx = self.edge_idx[require_conn_key]
            solver.add(Or(*[edge_vars[(req_idx, t)] for t in range(k)]))

        selected_rules: dict[tuple[str, int, str], object] = {}

        for t in range(1, k + 1):
            for station_id in self.station_ids:
                rules = self.rules_by_station.get(station_id, [])
                if not rules:
                    continue

                r_vars = []
                for rule in rules:
                    rv = Bool(f"r_{self.station_idx[station_id]}_{rule.index}_{t}")
                    selected_rules[(station_id, t, rule.rule_id)] = rv
                    r_vars.append(rv)

                solver.add(Implies(node_vars[(station_id, t)], Or(*r_vars)))
                for rv in r_vars:
                    solver.add(Implies(rv, node_vars[(station_id, t)]))
                for i in range(len(r_vars)):
                    for j in range(i + 1, len(r_vars)):
                        solver.add(Or(Not(r_vars[i]), Not(r_vars[j])))

        for rule in self.rules:
            uses = []
            for t in range(1, k + 1):
                var = selected_rules.get((rule.station_id, t, rule.rule_id))
                if var is not None:
                    uses.append(var)
            if uses:
                solver.add(Sum([If(v, 1, 0) for v in uses]) <= int(rule.max_traversals))

        return solver, node_vars, edge_vars, selected_rules

    def _extract_model(self, k: int, model, node_vars, edge_vars, selected_rules):
        node_sequence = []
        for t in range(k + 1):
            chosen = None
            for sid in self.station_ids:
                if bool(model.eval(node_vars[(sid, t)], model_completion=True)):
                    chosen = sid
                    break
            node_sequence.append(chosen)

        edge_sequence = []
        for t in range(k):
            chosen_idx = None
            for edge_idx, edge in enumerate(self.edge_tuples):
                if bool(model.eval(edge_vars[(edge_idx, t)], model_completion=True)):
                    chosen_idx = edge_idx
                    edge_sequence.append(edge)
                    break
            if chosen_idx is None:
                return None

        selected_rule_map: dict[int, dict[str, str]] = {}
        for (station_id, t, rule_id), var in selected_rules.items():
            if bool(model.eval(var, model_completion=True)):
                selected_rule_map.setdefault(t, {})[station_id] = rule_id

        return {
            "node_sequence": node_sequence,
            "edge_sequence": edge_sequence,
            "selected_rules": selected_rule_map,
        }

    def _query_exists(
        self,
        cancel_event,
        require_conn_key: int | None = None,
        require_checkpoint_id: str | None = None,
        relaxed: bool = False,
        progress_callback=None,
    ):
        # Fast impossible-query checks and lower bound for k.
        min_k = 1
        if require_conn_key is not None:
            if require_conn_key not in self.edge_idx:
                return False, None
            min_k = max(min_k, self._conn_min_k.get(require_conn_key, self.max_bound + 1))
            if min_k > self.max_bound:
                return False, None

        if require_checkpoint_id is not None:
            min_k = max(min_k, self._checkpoint_min_k.get(require_checkpoint_id, self.max_bound + 1))
            if min_k > self.max_bound:
                return False, None

        for k in range(min_k, self.max_bound + 1):
            if cancel_event.is_set():
                return False, None

            if progress_callback is not None:
                progress_callback(k, self.max_bound)

            solver, node_vars, edge_vars, selected_rules = self._build_solver(k, require_conn_key, require_checkpoint_id)
            solver.set("timeout", 2000)

            attempts = 0
            while attempts < 256:
                if progress_callback is not None:
                    progress_callback(k, self.max_bound, attempts)

                check_result = solver.check()
                if check_result != sat:
                    break

                attempts += 1
                model = solver.model()
                model_info = self._extract_model(k, model, node_vars, edge_vars, selected_rules)
                if model_info is None:
                    break

                if relaxed or self._simulate_model(model_info, relaxed=False):
                    return True, model_info

                block_literals = []
                for t, (conn_key, _, _) in enumerate(model_info["edge_sequence"]):
                    edge_idx = self.edge_idx.get(conn_key)
                    if edge_idx is not None:
                        block_literals.append(Not(edge_vars[(edge_idx, t)]))
                if block_literals:
                    solver.add(Or(*block_literals))
                else:
                    break

        return False, None

    def run(self, cancel_event, status_emit):
        started = time.perf_counter()
        last_progress_emit = 0.0
        last_progress_value = -1

        def emit_progress(progress_value: int):
            nonlocal last_progress_emit, last_progress_value
            progress_value = max(0, min(99, int(progress_value)))
            now = time.perf_counter()
            if progress_value == last_progress_value and (now - last_progress_emit) < 0.2:
                return
            last_progress_emit = now
            last_progress_value = progress_value
            status_emit(f"Validierung läuft ... {progress_value}%")

        if not self.root_ids:
            return {
                "best_states": {},
                "checkpoint_levels": {},
                "root_exists": False,
                "cancelled": False,
                "metrics": {
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "mode": "sat",
                    "target_flow": 0,
                    "total_flow": len(self.flow_conn_keys),
                    "target_checkpoints": 0,
                    "total_checkpoints": len(self.checkpoint_ids),
                    "cancelled": False,
                },
            }

        best_states = {}
        conn_ids = sorted(self.target_conn_keys)
        checkpoint_ids = sorted(self.target_checkpoint_ids)

        # Progress model:
        # - each connection has 2 slots (strict + relaxed)
        # - each checkpoint has 2 slots (strict + relaxed)
        # A slot is either fully executed, or resolved/skipped by previous result.
        total_slots = max(1, 2 * (len(conn_ids) + len(checkpoint_ids)))
        slot_index = 0

        def emit_slot_progress(current_slot: int, local_ratio: float = 1.0):
            ratio = (float(current_slot) + min(1.0, max(0.0, float(local_ratio)))) / float(total_slots)
            emit_progress(int(ratio * 99))

        def make_query_progress_callback(current_slot: int):
            def _cb(k: int, max_bound: int, attempts: int = 0):
                # Continuous local progress in [0, 1]:
                # base over k plus sub-progress inside current k via attempts.
                mb = float(max(1, max_bound))
                attempt_ratio = min(0.999, float(max(0, attempts)) / 256.0)
                local_ratio = ((float(max(1, k)) - 1.0) + attempt_ratio) / mb
                emit_slot_progress(current_slot, min(1.0, max(0.0, local_ratio)))

            return _cb

        for conn_key in conn_ids:
            if cancel_event.is_set():
                return {
                    "cancelled": True,
                    "metrics": {
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                        "mode": "sat",
                        "target_flow": len(self.target_conn_keys),
                        "total_flow": len(self.flow_conn_keys),
                        "target_checkpoints": len(self.target_checkpoint_ids),
                        "total_checkpoints": len(self.checkpoint_ids),
                        "cancelled": True,
                    },
                }

            # Topologically impossible to include this edge in any root->checkpoint path.
            if conn_key not in self._conn_min_k:
                best_states[conn_key] = (
                    CONNECTION_STATE.INVALID,
                    ["Keine topologische Route von Start zu Ende über diese Verbindung."],
                )
                slot_index += 2
                emit_slot_progress(slot_index, 0.0)
                continue

            strict_ok, _ = self._query_exists(
                cancel_event,
                require_conn_key=conn_key,
                relaxed=False,
                progress_callback=make_query_progress_callback(slot_index),
            )
            slot_index += 1
            emit_slot_progress(slot_index, 0.0)

            if strict_ok:
                best_states[conn_key] = (CONNECTION_STATE.VALID, [])
                # Relaxed slot resolved by strict success.
                slot_index += 1
                emit_slot_progress(slot_index, 0.0)
            else:
                relaxed_ok, _ = self._query_exists(
                    cancel_event,
                    require_conn_key=conn_key,
                    relaxed=True,
                    progress_callback=make_query_progress_callback(slot_index),
                )
                slot_index += 1
                emit_slot_progress(slot_index, 0.0)

                if relaxed_ok:
                    best_states[conn_key] = (
                        CONNECTION_STATE.CONDITIONAL_VALID,
                        ["Pfad topologisch erreichbar, aber Bedingungen/Effekte verhindern eine strikt gültige Belegung."],
                    )
                else:
                    best_states[conn_key] = (
                        CONNECTION_STATE.INVALID,
                        ["Kein SAT-Path innerhalb des Bounds gefunden."],
                    )

        checkpoint_levels = {}
        for checkpoint_id in checkpoint_ids:
            # Topologically unreachable checkpoint from any start node.
            if checkpoint_id not in self._checkpoint_min_k:
                slot_index += 2
                emit_slot_progress(slot_index, 0.0)
                continue

            strict_ok, _ = self._query_exists(
                cancel_event,
                require_checkpoint_id=checkpoint_id,
                relaxed=False,
                progress_callback=make_query_progress_callback(slot_index),
            )
            slot_index += 1
            emit_slot_progress(slot_index, 0.0)

            if strict_ok:
                checkpoint_levels[checkpoint_id] = [0]
                # Relaxed slot resolved by strict success.
                slot_index += 1
                emit_slot_progress(slot_index, 0.0)
            else:
                relaxed_ok, _ = self._query_exists(
                    cancel_event,
                    require_checkpoint_id=checkpoint_id,
                    relaxed=True,
                    progress_callback=make_query_progress_callback(slot_index),
                )
                slot_index += 1
                emit_slot_progress(slot_index, 0.0)
                if relaxed_ok:
                    checkpoint_levels[checkpoint_id] = [1]

        emit_slot_progress(total_slots, 0.0)

        return {
            "best_states": best_states,
            "checkpoint_levels": checkpoint_levels,
            "root_exists": bool(self.root_ids),
            "cancelled": False,
            "metrics": {
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "mode": "sat",
                "target_flow": len(self.target_conn_keys),
                "total_flow": len(self.flow_conn_keys),
                "target_checkpoints": len(self.target_checkpoint_ids),
                "total_checkpoints": len(self.checkpoint_ids),
                "cancelled": False,
            },
        }


def compute_sat_validation(snapshot: dict, cancel_event, status_emit) -> dict:
    engine = SatValidationEngine(snapshot=snapshot)
    return engine.run(cancel_event=cancel_event, status_emit=status_emit)
