#!/usr/bin/env python3
"""Profiling harness for compute_sat_validation.

Generates a synthetic snapshot with configurable branching and depth,
then runs compute_sat_validation under cProfile and prints top stats.
"""
import argparse
import cProfile
import pstats
import io
import os
import sys
from importlib import import_module

# ensure repo root is on sys.path so we can import src.run_planner
_THIS_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def make_snapshot(branch: int, depth: int):
    station_data = {}
    flow_succs = {}
    flow_conn_keys = []
    target_conn_keys = []
    connection_kinds = {}
    checkpoint_ids = []
    target_checkpoint_ids = []

    # Create nodes s0 .. sN
    def id_for(level, idx):
        return f"s{level}_{idx}"

    conn_id = 10
    for level in range(depth + 1):
        for idx in range(branch ** level):
            sid = id_for(level, idx)
            # simple rule that increments an attribute
            station_data[sid] = {"rules": [{"conditions": [], "effects": [{"attr_id": "x", "action": "+", "value": 1}]}]}

    # build edges
    for level in range(depth):
        for idx in range(branch ** level):
            src = id_for(level, idx)
            succs = []
            for b in range(branch):
                dst = id_for(level + 1, idx * branch + b)
                key = conn_id
                conn_id += 1
                flow_conn_keys.append(key)
                connection_kinds[key] = "FLOW"
                succs.append((key, dst))
            flow_succs[src] = succs

    # roots are level 0
    root_ids = [id_for(0, 0)]

    # checkpoints = last level
    for idx in range(branch ** depth):
        cid = id_for(depth, idx)
        checkpoint_ids.append(cid)
        target_checkpoint_ids.append(cid)

    # target conn keys = all
    target_conn_keys = list(flow_conn_keys)

    snapshot = {
        "station_data": station_data,
        "root_ids": root_ids,
        "flow_conn_keys": flow_conn_keys,
        "target_conn_keys": target_conn_keys,
        "checkpoint_ids": checkpoint_ids,
        "target_checkpoint_ids": target_checkpoint_ids,
        "flow_succs": flow_succs,
        "flow_conn_conditions": {},
        "connection_kinds": connection_kinds,
    }
    return snapshot


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--branch", type=int, default=2)
    p.add_argument("--depth", type=int, default=4)
    p.add_argument("--top", type=int, default=30, help="Top N pstats lines")
    p.add_argument("--state-workers", type=int, default=None)
    p.add_argument("--state-parallel-chunk-size", type=int, default=None)
    p.add_argument("--effect-parallel-chunk-size", type=int, default=None)
    args = p.parse_args()

    print(f"Generating snapshot: branch={args.branch} depth={args.depth}")
    snapshot = make_snapshot(args.branch, args.depth)

    mod = import_module("src.run_planner.sat_validation")
    compute = getattr(mod, "compute_sat_validation")

    # inject tuning parameters into snapshot if provided
    if args.state_workers is not None:
        snapshot["state_workers"] = args.state_workers
    if args.state_parallel_chunk_size is not None:
        snapshot["state_parallel_chunk_size"] = args.state_parallel_chunk_size
    if args.effect_parallel_chunk_size is not None:
        snapshot["effect_parallel_chunk_size"] = args.effect_parallel_chunk_size

    pr = cProfile.Profile()
    pr.enable()
    result = compute(snapshot)
    pr.disable()

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumtime")
    ps.print_stats(args.top)
    print(s.getvalue())
    # also print a small summary from result
    print("Result profiling summary keys:", list(result.get("profiling", {}).keys()))


if __name__ == "__main__":
    main()
