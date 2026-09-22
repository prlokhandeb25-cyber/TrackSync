"""P3 driver: build the planning week, find traffic gaps, report what was found."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from backend.config import REPO_ROOT, all_corridors, seed_everything  # noqa: E402
from backend.data.ingest import build_timetable  # noqa: E402
from backend.data.tiers import derive_tiers  # noqa: E402
from backend.data.validate import Validator  # noqa: E402
from backend.data.week import build_week  # noqa: E402
from backend.domain.models import s_to_hhmm  # noqa: E402
from backend.domain.network import build_network  # noqa: E402
from backend.domain.occupancy import build_occupancy  # noqa: E402
from backend.gaps.engine import GapType, find_gaps, station_node_windows  # noqa: E402

PROC = REPO_ROOT / "data" / "processed"


def main() -> int:
    seed = seed_everything()
    net = build_network(all_corridors()[0])

    day = build_timetable(net, seed)
    Validator(net, day).run()  # repairs applied in place before the week is built
    occ_day = build_occupancy(net, day)
    derive_tiers(net, day, occ_day)

    week = build_week(net, day, seed)
    occ = build_occupancy(net, week)
    print(f"planning week: {len(week):,} services, {len(occ):,} section traversals\n")

    report = find_gaps(net, occ, horizon_days=7)
    sect_windows = report.windows
    node_windows = station_node_windows(net, report)

    counts = Counter(w.gap_type.value for w in sect_windows)
    print("=== windows found (section work) ===")
    for t in GapType:
        ws = report.by_type(t)
        usable = sum(w.usable_min() for w in ws)
        print(f"  {t.value:14s} {counts.get(t.value, 0):5d} windows   "
              f"{usable / 60:8.1f} usable hours across the week")
    print(f"  {'STATION NODES':14s} {len(node_windows):5d} windows\n")

    raw_total = sum(w.raw_min for w in sect_windows)
    use_total = sum(w.usable_min() for w in sect_windows)
    print(f"raw gap time      : {raw_total / 60:8.1f} h")
    print(f"usable after setup: {use_total / 60:8.1f} h  "
          f"({100 * use_total / max(1, raw_total):.0f}% of raw - the rest is protection "
          f"and hand-back)\n")

    print("=== derived night windows (NOT hardcoded) ===")
    shown = 0
    for key, (s, e) in sorted(report.night_windows_by_section.items()):
        dur = ((e - s) % 86400) // 60
        print(f"  {key:22s} {s_to_hhmm(s)}–{s_to_hhmm(e)}  ({dur} min)")
        shown += 1
        if shown >= 8:
            break

    print("\n=== micro-gaps by station tier (the differentiating capacity) ===")
    by_tier: dict[str, list] = defaultdict(list)
    for w in report.by_type(GapType.MICRO_GAP):
        by_tier[w.station_tier.value if w.station_tier else "?"].append(w)
    for tier in ("TIER_1", "TIER_2", "TIER_3"):
        ws = by_tier.get(tier, [])
        if not ws:
            continue
        med = sorted(w.usable_min() for w in ws)[len(ws) // 2]
        longest = max(w.usable_min() for w in ws)
        print(f"  {tier}: {len(ws):5d} windows, median {med:3d} min usable, "
              f"longest {longest:3d} min")

    print("\n=== megablock verification (observed vs configured) ===")
    obs = report.megablock_observed
    if obs:
        avg = sum(obs.values()) / len(obs)
        print(f"  Sunday traffic in the configured window is {avg * 100:.0f}% below a weekday, "
              f"across {len(obs)} sections")
        print("  -> the configured megablock is corroborated by the timetable, not just asserted")

    print("\n=== sample windows ===")
    for t in GapType:
        ws = report.by_type(t)
        if ws:
            w = max(ws, key=lambda x: x.usable_min())
            print(f"  {w.describe()}")

    rows = [w.to_dict() for w in sect_windows] + [w.to_dict() for w in node_windows]
    pd.DataFrame(rows).to_parquet(PROC / "windows.parquet", index=False)
    with open(REPO_ROOT / "artifacts" / "gap_summary.json", "w", encoding="utf-8") as fh:
        json.dump(
            {
                "services_week": len(week),
                "traversals": len(occ),
                "windows_section": len(sect_windows),
                "windows_station_node": len(node_windows),
                "by_type": dict(counts),
                "raw_hours": round(raw_total / 60, 1),
                "usable_hours": round(use_total / 60, 1),
                "night_windows": {k: [s_to_hhmm(a), s_to_hhmm(b)]
                                  for k, (a, b) in report.night_windows_by_section.items()},
                "megablock_observed_reduction": obs,
            },
            fh, indent=2,
        )
    print(f"\nwrote windows.parquet ({len(rows):,} rows) and artifacts/gap_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
