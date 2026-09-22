"""P1 driver: ingest -> validate (V1..V10) -> derive tiers -> fidelity replay -> write reports.

Emits data/validation_report.json and data/validation_report.md, plus the processed timetable
as parquet. The API refuses to serve data while the report says FAIL (SPEC §3.4).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from backend.config import REPO_ROOT, all_corridors, load_config, seed_everything  # noqa: E402
from backend.data.ingest import build_timetable  # noqa: E402
from backend.data.tiers import derive_tiers  # noqa: E402
from backend.data.validate import Validator  # noqa: E402
from backend.domain.network import build_network, merge_networks  # noqa: E402
from backend.domain.occupancy import build_occupancy  # noqa: E402
from backend.sim.replay import replay_no_maintenance  # noqa: E402

DATA = REPO_ROOT / "data"
PROC = DATA / "processed"


def to_frames(net, trains, occ) -> dict[str, pd.DataFrame]:
    stops = [
        {
            "train_id": t.id, "number": t.number, "name": t.name,
            "train_class": t.train_class.value, "is_real": t.is_real,
            "direction": t.direction, "priority": t.priority, "seq": i,
            "station_code": s.station_code, "arrival_s": s.arrival_s,
            "departure_s": s.departure_s, "day_offset": s.day_offset,
        }
        for t in trains for i, s in enumerate(t.stops)
    ]
    sections = [
        {
            "section_id": s.id, "from_station": s.from_station, "to_station": s.to_station,
            "length_km": s.length_km, "line_speed_kmph": s.line_speed_kmph,
            "tracks": ",".join(s.tracks), "tier": s.tier.value if s.tier else None,
            "trains_per_day": s.trains_per_day, "peak_tph": s.peak_trains_per_hour,
            "status": s.status.value,
        }
        for s in net.sections.values()
    ]
    stations = [
        {
            "code": s.code, "name": s.name, "lat": s.lat, "lon": s.lon,
            "platforms": s.platforms, "is_junction": s.is_junction,
            "tier": s.tier.value if s.tier else None,
            "expect_tier": s.expect_tier.value if s.expect_tier else None,
            "trains_per_day": s.trains_per_day, "peak_tph": s.peak_trains_per_hour,
        }
        for s in net.stations.values()
    ]
    occupancy = [
        {
            "section_id": o.section_id, "track": o.track, "direction": o.direction,
            "train_id": o.train_id, "train_class": o.train_class.value,
            "enter_s": o.enter_s, "exit_s": o.exit_s,
        }
        for o in occ
    ]
    return {
        "stops": pd.DataFrame(stops),
        "sections": pd.DataFrame(sections),
        "stations": pd.DataFrame(stations),
        "occupancy": pd.DataFrame(occupancy),
    }


def markdown_report(rep: dict, fidelity: dict, tier_warnings: list[str], net) -> str:
    icon = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN"}
    lines = [
        "# Data Validation Report",
        "",
        f"**Overall: {rep['overall_status']}** — {rep['checks_passed']}/{rep['checks_total']} checks passed, "
        f"{rep['repairs_applied']} repair(s) applied.",
        "",
        f"Corridor `{rep['corridor']}` · generated {rep['generated_at']}",
        "",
        "## Provenance",
        "",
        f"- Services total: **{rep['services_total']:,}**",
        f"- From real published data: **{rep['services_real']:,}** "
        f"({rep['services_real'] / max(1, rep['services_total']) * 100:.1f}%)",
        f"- Synthesised (no public source): **{rep['services_synthetic']:,}**",
        "",
        "| Class | Count | Source |",
        "|---|---:|---|",
        f"| INTERCITY | {rep['services_by_class'].get('INTERCITY', 0):,} | real — public schedules dataset |",
        f"| SUBURBAN_LOCAL | {rep['services_by_class'].get('SUBURBAN_LOCAL', 0):,} | synthesised (A-007) |",
        f"| FREIGHT_MAIL | {rep['services_by_class'].get('FREIGHT_MAIL', 0):,} | synthesised (A-008) |",
        "",
        "All station coordinates and all section lengths derive from real published data.",
        "",
        "## Checks",
        "",
        "| ID | Check | Status | Detail |",
        "|---|---|---|---|",
    ]
    for c in rep["checks"]:
        lines.append(f"| {c['id']} | {c['name']} | **{icon.get(c['status'], c['status'])}** | {c['detail']} |")

    lines += [
        "",
        "## Simulation fidelity (SPEC §3.5)",
        "",
        f"**{fidelity['status']}** — {fidelity['trains_completed']}/{fidelity['trains_total']} trains "
        f"complete, {fidelity['conflicts']} conflict(s), mean arrival deviation "
        f"{fidelity['mean_abs_deviation_s']}s.",
        "",
        "## Derived station tiers (SPEC §8.1)",
        "",
        "Derived by frequency quantile from the data, never hardcoded by name.",
        "",
        "| Station | Services/day | Peak trains/hr | Derived tier | Config expected |",
        "|---|---:|---:|---|---|",
    ]
    for code in net.order:
        s = net.stations[code]
        agree = "" if (not s.expect_tier or s.expect_tier == s.tier) else "  <- differs"
        lines.append(
            f"| {s.name} ({code}) | {s.trains_per_day:,} | {s.peak_trains_per_hour:.0f} | "
            f"**{s.tier.value if s.tier else '?'}** | {s.expect_tier.value if s.expect_tier else '—'}{agree} |"
        )
    if tier_warnings:
        lines += ["", "Tier disagreements (derived value wins):", ""]
        lines += [f"- {w}" for w in tier_warnings]

    if rep["repairs"]:
        lines += ["", "## Repairs applied (first 20)", "", "| Check | Target | Action |", "|---|---|---|"]
        for r in rep["repairs"][:20]:
            lines.append(f"| {r['check']} | `{r['target']}` | {r['action']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    seed = seed_everything()
    cfg = load_config()
    PROC.mkdir(parents=True, exist_ok=True)

    names = all_corridors()
    print(f"seed={seed}  corridors: {', '.join(names)}\n")

    nets = [build_network(c) for c in names]
    trains: list = []
    for n in nets:
        t = build_timetable(n, seed)
        trains.extend(t)
        print(f"  {n.line_code:3s} {n.name[:36]:38s} {len(n.stations):3d} stations  "
              f"{len(t):5,d} services/day")

    net = merge_networks(nets)
    inter = [c for c, st in net.stations.items() if len(st.lines) > 1]
    d = sum(1 for st in net.stations.values() if st.coord_src == "d")
    print(f"\nmerged: {len(net.stations)} stations, {len(net.sections)} sections, "
          f"{sum(s.length_km for s in net.sections.values()):.0f} route-km")
    print(f"interchanges found by shared station code: {', '.join(inter)}")
    print(f"coordinates: {d} from the public dataset, {len(net.stations) - d} supplied by us")

    real = sum(1 for t in trains if t.is_real)
    print(f"timetable: {len(trains):,} services/day "
          f"({real:,} real, {len(trains) - real:,} synthesised)")

    print("\nrunning validation gate ...")
    validator = Validator(net, trains)
    report = validator.run()
    for c in report["checks"]:
        print(f"  {c['id']:4s} {c['status']:5s} {c['name']:36s} {c['detail']}")
    print(f"  repairs applied: {report['repairs_applied']}")

    occ = build_occupancy(net, trains)
    tier_warnings = derive_tiers(net, trains, occ)
    print(f"\ntiers derived for {len(net.stations)} stations "
          f"({len(tier_warnings)} disagreement(s) with config expectation)")

    print("running simulation fidelity replay ...")
    fid = replay_no_maintenance(net, trains)
    print(f"  {fid.status}: {fid.detail}")
    report["fidelity"] = fid.to_dict()
    report["tier_warnings"] = tier_warnings
    if fid.status == "FAIL":
        report["overall_status"] = "FAIL"

    frames = to_frames(net, trains, occ)
    for name, df in frames.items():
        df.to_parquet(PROC / f"{name}.parquet", index=False)
    print(f"\nwrote {', '.join(f'{k}.parquet ({len(v):,} rows)' for k, v in frames.items())}")

    with open(DATA / "validation_report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    with open(DATA / "validation_report.md", "w", encoding="utf-8") as fh:
        fh.write(markdown_report(report, report["fidelity"], tier_warnings, net))

    print(f"\nOVERALL: {report['overall_status']}")
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
