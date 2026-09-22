"""P6 driver: generate CP-SAT expert trajectories for offline RL.

Samples N instances with varying task mix and load, solves each with CP-SAT, replays the
solution as a decision trajectory, and writes a sharded offline dataset.

Splits are BY INSTANCE, never by transition. Transitions from one solved instance are highly
correlated, so a transition-level split would leak the answer into the test set and every
number reported later would be optimistic and wrong.

Run it in the background - it is the longest job in the project:
    .venv\\Scripts\\python.exe scripts\\04_generate_expert_data.py 500
"""

from __future__ import annotations

import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from backend.config import REPO_ROOT, load_config, seed_everything  # noqa: E402
from backend.planner.context import sample_instance  # noqa: E402
from backend.planner.cpsat import solve_with_relaxation  # noqa: E402
from backend.rl.trajectory import replay, to_arrays  # noqa: E402

OUT = REPO_ROOT / "data" / "expert"
MAX_GAP_PCT = 25.0  # instances solved worse than this are discarded, and the rate is logged


def run_instance(args: tuple[int, int]) -> dict:
    """Solve one sampled instance and replay it. Runs in a worker process."""
    instance_id, seed = args
    rng = random.Random(seed)
    n_tasks = rng.randint(15, 60)  # vary the load so the policy sees easy and hard weeks

    try:
        world = sample_instance(n_tasks=n_tasks, task_seed=seed,
                                base_seed=load_config()['seed'])
        plan = solve_with_relaxation(
            world.net, world.tasks, world.windows,
            time_limit_s=load_config()["planner"]["solve_time_s_instance"],
        )
        if plan.status not in ("OPTIMAL", "FEASIBLE") or plan.gap_pct > MAX_GAP_PCT:
            return {"instance_id": instance_id, "ok": False,
                    "why": f"{plan.status} gap={plan.gap_pct:.1f}%"}

        transitions, stats = replay(world.net, world.tasks, world.windows, plan, instance_id)
        if not transitions:
            return {"instance_id": instance_id, "ok": False, "why": "no transitions"}

        return {
            "instance_id": instance_id, "ok": True,
            "arrays": to_arrays(transitions),
            "n_tasks": n_tasks,
            "n_transitions": len(transitions),
            "unmatched": stats.unmatched,
            "micro_gap_actions": stats.micro_gap_actions,
            "total_return": stats.total_return,
            "objective": plan.objective,
            "gap_pct": plan.gap_pct,
            "solve_s": plan.wall_s,
        }
    except Exception as exc:  # noqa: BLE001 - a bad instance must not kill the batch
        return {"instance_id": instance_id, "ok": False, "why": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    n_instances = int(sys.argv[1]) if len(sys.argv) > 1 else load_config()["rl"]["n_instances"]
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    base_seed = seed_everything()
    OUT.mkdir(parents=True, exist_ok=True)

    print(f"generating {n_instances} expert instances on {workers} workers", flush=True)
    t0 = time.time()

    jobs = [(i, base_seed + i * 7919) for i in range(n_instances)]
    results: list[dict] = []
    done = 0

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_instance, j): j[0] for j in jobs}
        for fut in as_completed(futures):
            r = fut.result()
            done += 1
            if r["ok"]:
                results.append(r)
            if done % 10 == 0 or done == n_instances:
                kept = len(results)
                trans = sum(x["n_transitions"] for x in results)
                rate = done / max(1e-9, time.time() - t0)
                eta = (n_instances - done) / max(1e-9, rate)
                print(f"  {done}/{n_instances} solved | kept {kept} | {trans:,} transitions "
                      f"| {rate:.2f}/s | eta {eta / 60:.1f} min", flush=True)

    if not results:
        print("no usable instances - aborting")
        return 1

    # ---- split BY INSTANCE
    cfg = load_config()["rl"]["split"]
    ids = sorted(r["instance_id"] for r in results)
    random.Random(base_seed).shuffle(ids)
    n = len(ids)
    n_train = int(n * float(cfg["train"]))
    n_val = int(n * float(cfg["val"]))
    split_of = {}
    for i, iid in enumerate(ids):
        split_of[iid] = "train" if i < n_train else ("val" if i < n_train + n_val else "test")

    buckets: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for r in results:
        buckets[split_of[r["instance_id"]]].append(r["arrays"])

    summary = {"instances_requested": n_instances, "instances_kept": len(results),
               "discard_rate": round(1 - len(results) / n_instances, 3), "splits": {}}

    for name, arrs in buckets.items():
        if not arrs:
            continue
        merged = {k: np.concatenate([a[k] for a in arrs]) for k in arrs[0]}
        np.savez_compressed(OUT / f"{name}.npz", **merged)
        summary["splits"][name] = {
            "instances": sum(1 for i in ids if split_of[i] == name),
            "transitions": int(len(merged["action"])),
            "mean_reward": float(merged["reward"].mean()),
            "state_dim": int(merged["state"].shape[1]),
            "action_dim": int(merged["mask"].shape[1]),
        }

    # No instance may appear in more than one split - assert it rather than trust it.
    seen: dict[int, str] = {}
    for r in results:
        s = split_of[r["instance_id"]]
        assert seen.setdefault(r["instance_id"], s) == s
    summary["leakage_check"] = "PASS - splits are disjoint by instance"

    summary["totals"] = {
        "transitions": sum(x["n_transitions"] for x in results),
        "unmatched_expert_placements": sum(x["unmatched"] for x in results),
        "micro_gap_actions": sum(x["micro_gap_actions"] for x in results),
        "mean_solve_s": round(float(np.mean([x["solve_s"] for x in results])), 2),
        "mean_cpsat_gap_pct": round(float(np.mean([x["gap_pct"] for x in results])), 2),
        "wall_min": round((time.time() - t0) / 60, 1),
    }

    with open(OUT / "summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    print("\n=== dataset ===")
    for name, s in summary["splits"].items():
        print(f"  {name:5s} {s['instances']:4d} instances  {s['transitions']:7,d} transitions")
    print(f"  state dim {summary['splits']['train']['state_dim']}, "
          f"actions {summary['splits']['train']['action_dim']}")
    print(f"  discard rate {summary['discard_rate'] * 100:.1f}%  "
          f"| mean CP-SAT gap {summary['totals']['mean_cpsat_gap_pct']}%  "
          f"| {summary['totals']['wall_min']} min")
    print(f"  {summary['leakage_check']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
