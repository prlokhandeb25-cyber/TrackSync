"""P9 driver: the before/after impact study (SPEC §15.3).

Runs the manual baseline and this system over the SAME seeded instances and writes:

    artifacts/metrics.json             machine-readable
    artifacts/impact_comparison.csv    straight into the deck
    artifacts/charts/impact.png        one chart, if matplotlib is available

Averaging over several instances matters. A single week can flatter either side by luck -
the manual baseline can separate every department by chance and post a zero coordination
cost, which is exactly the artefact that made two of these metrics meaningless until it was
caught. Run it over enough instances and that noise averages out.

    .venv\\Scripts\\python.exe scripts\\07_impact_study.py 8
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from backend.config import REPO_ROOT, load_config, seed_everything  # noqa: E402
from backend.metrics.impact import compute  # noqa: E402
from backend.planner.context import sample_instance  # noqa: E402
from backend.planner.cpsat import solve_with_relaxation  # noqa: E402
from backend.rl.policies import load_best_policy  # noqa: E402

ART = REPO_ROOT / "artifacts"


def fmt(v: float, unit: str) -> str:
    if unit == "ms":
        if v >= 3_600_000:
            return f"{v / 3_600_000:.1f} h"
        if v >= 1000:
            return f"{v / 1000:.2f} s"
        return f"{v:.0f} ms"
    if unit == "%":
        return f"{v:.1f}%"
    if unit == "hours":
        return f"{v:.1f} h"
    return f"{v:.1f}"


def main() -> int:
    n_instances = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    seed = seed_everything()
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "charts").mkdir(exist_ok=True)

    policy, dispatcher_note = load_best_policy(quiet=False)
    print(f"dispatcher: {dispatcher_note}")
    print(f"averaging over {n_instances} seeded instances\n")

    runs: list[list] = []
    meta: dict = {}

    for i in range(n_instances):
        inst_seed = seed + i * 4409
        world = sample_instance(n_tasks=40, task_seed=inst_seed, base_seed=seed)
        plan = solve_with_relaxation(
            world.net, world.tasks, world.windows,
            time_limit_s=load_config()["planner"]["solve_time_s_instance"])
        if plan.status not in ("OPTIMAL", "FEASIBLE"):
            print(f"  instance {i + 1}: {plan.status}, skipped")
            continue
        rep = compute(world.net, world.tasks, world.windows, plan, policy)
        runs.append(rep.metrics)
        meta = rep.assumptions
        print(f"  instance {i + 1}/{n_instances} done ({plan.status}, "
              f"{len(plan.assignments)}/{plan.n_tasks} placed)", flush=True)

    if not runs:
        print("no instances solved - aborting")
        return 1

    # Average each metric across instances, keeping id/name/unit from the first run.
    template = runs[0]
    rows = []
    for k, m in enumerate(template):
        before = float(np.mean([r[k].before for r in runs]))
        after = float(np.mean([r[k].after for r in runs]))
        # A metric that starts at zero has no meaningful percentage improvement. Dividing by it
        # silently reported 0% for the metric that matters most here - work fitted into gaps
        # between trains, which goes from nothing to something. Those are reported as a new
        # capability with an absolute delta rather than a fabricated percentage.
        from_zero = abs(before) < 1e-9
        if from_zero:
            improvement = None
        elif m.better == "lower":
            improvement = (before - after) / abs(before) * 100
        else:
            improvement = (after - before) / abs(before) * 100

        rows.append({
            "id": m.id, "metric": m.name, "unit": m.unit,
            "before_manual": round(before, 2), "after_railblock": round(after, 2),
            "absolute_delta": round(after - before, 2),
            "improvement_pct": None if improvement is None else round(improvement, 1),
            "new_capability": bool(from_zero and after > 0),
            "better": m.better, "note": m.note,
        })

    print("\n" + "=" * 96)
    print(f"{'':5s}{'metric':46s}{'before':>15s}{'after':>15s}{'change':>13s}")
    print("-" * 96)
    for r in rows:
        # ASCII only in console output: the Windows console is cp1252 and an em dash here
        # raises UnicodeEncodeError, killing the run after all the work is done.
        change = ("new" if r["new_capability"]
                  else "-" if r["improvement_pct"] is None
                  else f"{r['improvement_pct']:.0f}%")
        print(f"{r['id']:5s}{r['metric'][:44]:46s}"
              f"{fmt(r['before_manual'], r['unit']):>15s}"
              f"{fmt(r['after_railblock'], r['unit']):>15s}"
              f"{change:>13s}")
    print("=" * 96)

    with open(ART / "impact_comparison.csv", "w", encoding="utf-8", newline="") as fh:
        fh.write("id,metric,unit,before_manual,after_railblock,absolute_delta,"
                 "improvement_pct,new_capability,better,note\n")
        for r in rows:
            note = r["note"].replace('"', "'")
            imp = "" if r["improvement_pct"] is None else r["improvement_pct"]
            fh.write(f'{r["id"]},"{r["metric"]}",{r["unit"]},{r["before_manual"]},'
                     f'{r["after_railblock"]},{r["absolute_delta"]},{imp},'
                     f'{r["new_capability"]},{r["better"]},"{note}"\n')

    with open(ART / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump({
            "instances": len(runs),
            "seed": seed,
            "dispatcher": dispatcher_note,
            "assumptions": meta,
            "metrics": rows,
        }, fh, indent=2)

    _chart(rows)

    print(f"\nwrote artifacts/impact_comparison.csv, artifacts/metrics.json")
    print(f"averaged over {len(runs)} instances, seed {seed}")
    return 0


def _chart(rows: list[dict]) -> None:
    """One chart: improvement per metric. Skipped silently if matplotlib is unavailable."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return

    # M1 is a factor of ~10^6 and would flatten everything else into a single pixel, so the
    # chart shows the metrics that share a scale and the text reports M1 on its own.
    shown = [r for r in rows if r["id"] != "M1" and r["improvement_pct"] is not None]
    labels = [f"{r['id']} {r['metric'][:30]}" for r in shown]
    vals = [max(-100, min(100, r["improvement_pct"])) for r in shown]
    colors = ["#35c27a" if v > 0 else "#f4523b" for v in vals]

    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=140)
    fig.patch.set_facecolor("#0b0f16")
    ax.set_facecolor("#0b0f16")
    ax.barh(labels, vals, color=colors, height=.62)
    ax.axvline(0, color="#3a4658", lw=1)
    ax.set_xlabel("improvement vs manual planning (%)", color="#9fb0c3", fontsize=9)
    ax.tick_params(colors="#9fb0c3", labelsize=8)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.invert_yaxis()
    ax.set_title("RailBlock AI vs manual, decentralised planning",
                 color="#eef3f8", fontsize=11, pad=12, loc="left")
    fig.tight_layout()
    fig.savefig(REPO_ROOT / "artifacts" / "charts" / "impact.png",
                facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
