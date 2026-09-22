"""P7 evaluation: every policy on held-out instances, scored against CP-SAT.

The test instances are regenerated from the instance ids stored in test.npz, using the same
seed formula the generator used. They were never in training, and the split assertion in
generation already guaranteed that, so this is a genuine held-out comparison rather than a
re-run of the training set.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from backend.config import REPO_ROOT, load_config, seed_everything  # noqa: E402
from backend.planner.context import sample_instance  # noqa: E402
from backend.planner.cpsat import solve_with_relaxation  # noqa: E402
from backend.rl.agents import GreedyPolicy, RandomPolicy, TorchPolicy  # noqa: E402
from backend.rl.env import evaluate  # noqa: E402
from backend.rl.nets import PolicyNet, QNet  # noqa: E402

MODELS = REPO_ROOT / "artifacts" / "models"
ART = REPO_ROOT / "artifacts"


def load_policy(kind: str):
    path = MODELS / f"{kind}.pt"
    blob = torch.load(path, map_location="cpu", weights_only=True)
    cls = PolicyNet if kind == "bc" else QNet
    net = cls(blob["state_dim"], blob["action_dim"], blob["hidden"])
    net.load_state_dict(blob["state_dict"])
    net.eval()
    return TorchPolicy(net, "behaviour cloning" if kind == "bc" else "CQL-DQN")


def main() -> int:
    seed = seed_everything()
    n_eval = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    ids = np.load(REPO_ROOT / "data" / "expert" / "test.npz")["instance_id"]
    test_ids = sorted(set(int(i) for i in ids))[:n_eval]
    print(f"evaluating on {len(test_ids)} held-out instances\n")

    policies = [RandomPolicy(seed), GreedyPolicy(), load_policy("bc"), load_policy("cql_dqn")]
    rows: dict[str, list] = {p.name: [] for p in policies}
    cpsat_times: list[float] = []

    import random as _r
    for k, iid in enumerate(test_ids, 1):
        inst_seed = seed + iid * 7919
        n_tasks = _r.Random(inst_seed).randint(15, 60)  # same draw the generator made
        world = sample_instance(n_tasks=n_tasks, task_seed=inst_seed, base_seed=seed)

        t0 = time.perf_counter()
        ref = solve_with_relaxation(world.net, world.tasks, world.windows,
                                    time_limit_s=load_config()["planner"]["solve_time_s_instance"])
        cpsat_times.append((time.perf_counter() - t0) * 1000)
        if ref.status not in ("OPTIMAL", "FEASIBLE"):
            continue

        for p in policies:
            rows[p.name].append(evaluate(p, world.net, world.tasks, world.windows, ref))
        if k % 5 == 0 or k == len(test_ids):
            print(f"  {k}/{len(test_ids)} instances", flush=True)

    def agg(name: str) -> dict:
        rs = rows[name]
        if not rs:
            return {}
        return {
            "policy": name,
            "instances": len(rs),
            "mean_gap_vs_cpsat_pct": round(float(np.mean([r.gap_pct for r in rs])), 2),
            "median_gap_pct": round(float(np.median([r.gap_pct for r in rs])), 2),
            "mean_scheduled_pct": round(float(np.mean(
                [100 * r.scheduled / max(1, r.n_tasks) for r in rs])), 1),
            "mean_micro_gap": round(float(np.mean([r.micro_gap for r in rs])), 1),
            "mean_decision_ms": round(float(np.mean([r.mean_latency_ms for r in rs])), 3),
            "p95_decision_ms": round(float(np.mean([r.p95_latency_ms for r in rs])), 3),
            "mean_full_replan_ms": round(float(np.mean([r.full_replan_ms for r in rs])), 1),
            "constraint_violations": int(sum(r.violations for r in rs)),
        }

    table = [agg(p.name) for p in policies if rows[p.name]]
    cpsat_ms = float(np.mean(cpsat_times))

    print("\n" + "=" * 104)
    print(f"{'policy':22s} {'gap vs CP-SAT':>14s} {'scheduled':>10s} {'micro-gap':>10s} "
          f"{'decision':>10s} {'re-plan':>10s} {'violations':>11s}")
    print("-" * 104)
    for r in table:
        print(f"{r['policy']:22s} {r['mean_gap_vs_cpsat_pct']:13.1f}% "
              f"{r['mean_scheduled_pct']:9.1f}% {r['mean_micro_gap']:10.1f} "
              f"{r['mean_decision_ms']:9.2f}ms {r['mean_full_replan_ms']:9.0f}ms "
              f"{r['constraint_violations']:11d}")
    print("-" * 104)
    print(f"{'CP-SAT (reference)':22s} {0.0:13.1f}% {'—':>10s} {'—':>10s} "
          f"{'—':>10s} {cpsat_ms:9.0f}ms {0:11d}")
    print("=" * 104)

    best = min(table, key=lambda r: r["mean_gap_vs_cpsat_pct"]) if table else None
    if best:
        speedup = cpsat_ms / max(1e-9, best["mean_full_replan_ms"])
        print(f"\nBest learned policy: {best['policy']} — within "
              f"{best['mean_gap_vs_cpsat_pct']:.1f}% of CP-SAT, re-planning "
              f"{speedup:.0f}x faster ({best['mean_full_replan_ms']:.0f}ms vs {cpsat_ms:.0f}ms).")
        print(f"Constraint violations across all policies and instances: "
              f"{sum(r['constraint_violations'] for r in table)} "
              f"(zero by construction — every action passes through the legality mask).")

    with open(ART / "rl_comparison.json", "w", encoding="utf-8") as fh:
        json.dump({"table": table, "cpsat_mean_ms": round(cpsat_ms, 1),
                   "instances": len(test_ids)}, fh, indent=2)
    with open(ART / "rl_comparison.csv", "w", encoding="utf-8") as fh:
        if table:
            fh.write(",".join(table[0].keys()) + "\n")
            for r in table:
                fh.write(",".join(str(v) for v in r.values()) + "\n")
    print(f"\nwrote artifacts/rl_comparison.json and .csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
