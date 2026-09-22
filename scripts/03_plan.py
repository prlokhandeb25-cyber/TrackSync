"""P4 driver: build the world, run the CP-SAT weekly block plan, report it."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import REPO_ROOT, load_config  # noqa: E402
from backend.domain.compatibility import coordination_conflicts, matrix  # noqa: E402
from backend.domain.models import s_to_hhmm  # noqa: E402
from backend.planner.context import build_world  # noqa: E402
from backend.planner.cpsat import solve_with_relaxation  # noqa: E402

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def main() -> int:
    n_tasks = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    world = build_world(n_tasks=n_tasks, quiet=False)

    m = matrix(world.net, world.tasks)
    print(f"compatibility: {m['summary']}  "
          f"({coordination_conflicts(world.net, world.tasks)} cross-department negotiations "
          f"a human would currently run by phone)\n")

    print("solving weekly block plan ...")
    res = solve_with_relaxation(world.net, world.tasks, world.windows,
                                time_limit_s=load_config()["planner"]["solve_time_s_demo"])
    print(f"  {res.summary()}")
    if res.relaxations:
        print(f"  relaxations needed: {res.relaxations}")
    if res.rejected:
        print(f"  rejected on allotment (R0): {len(res.rejected)}")
        for tid, why in list(res.rejected.items())[:2]:
            print(f"    {tid}: {why}")

    by_type = Counter(a.gap_type for a in res.assignments)
    print(f"\n=== where the work was placed ===")
    total = max(1, len(res.assignments))
    for k in ("NIGHT_WINDOW", "MEGABLOCK", "MICRO_GAP"):
        n = by_type.get(k, 0)
        print(f"  {k:14s} {n:3d}  ({100 * n / total:.0f}%)")
    print(f"  IWP permissions consumed: {res.iwp_used}")

    by_day = Counter(a.day for a in res.assignments)
    print(f"\n=== spread across the week ===")
    for d in range(7):
        bar = "#" * by_day.get(d, 0)
        print(f"  {DAYS[d]}  {by_day.get(d, 0):3d}  {bar}")

    tasks_by_id = {t.id: t for t in world.tasks}
    print(f"\n=== sample of the plan ===")
    for a in sorted(res.assignments, key=lambda x: x.start_s)[:8]:
        t = tasks_by_id[a.task_id]
        print(f"  {DAYS[a.day]} {s_to_hhmm(a.start_s % 86400)}  "
              f"{t.department.value:8s} {t.label[:28]:30s} {a.zone_ref:10s} "
              f"{t.duration_min:3d}min  [{a.gap_type}]")

    if res.unscheduled:
        print(f"\n  {len(res.unscheduled)} task(s) left unplanned this week")

    out = REPO_ROOT / "artifacts" / "plan_cpsat.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res.to_dict(), fh, indent=2)
    print(f"\nwrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
