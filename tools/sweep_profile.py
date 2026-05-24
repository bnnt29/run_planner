#!/usr/bin/env python3
"""Automated parameter sweep for profile_sat.py.

Runs multiple trials per configuration and records median wall times.
"""
import subprocess
import time
import csv
import argparse
from statistics import median


def run_trial(branch, depth, workers, chunk, effect_chunk):
    cmd = [".venv/bin/python", "tools/profile_sat.py",
           "--branch", str(branch), "--depth", str(depth), "--top", "0",
           "--state-workers", str(workers),
           "--state-parallel-chunk-size", str(chunk),
           "--effect-parallel-chunk-size", str(effect_chunk)]
    t0 = time.time()
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t1 = time.time()
    return t1 - t0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--branch", type=int, default=3)
    p.add_argument("--depth", type=int, default=5)
    p.add_argument("--workers", nargs="+", type=int, default=[1,2,4,8])
    p.add_argument("--chunks", nargs="+", type=int, default=[16,64,256,512])
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--out", default="/tmp/sweep_results.csv")
    args = p.parse_args()

    rows = []
    for w in args.workers:
        for c in args.chunks:
            times = []
            for _ in range(args.trials):
                t = run_trial(args.branch, args.depth, w, c, c)
                times.append(t)
            rows.append((w, c, median(times)))

    with open(args.out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["workers", "chunk", "median_seconds"])
        for r in rows:
            writer.writerow(r)

    print("Wrote results to", args.out)


if __name__ == "__main__":
    main()
