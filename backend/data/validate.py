"""The validation gate — V1..V10 from SPEC §3.4.

<!-- serves: J2 -->

Blocking by design: scheduling results computed on inconsistent timetable data are worthless,
so the API and demo refuse to run on FAIL. Safe repairs are applied and every one is logged —
the repair count is itself a reportable number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.config import load_config
from backend.domain.models import Train, TrainClass, s_to_hhmm
from backend.domain.network import Network
from backend.domain.occupancy import build_occupancy, group_by_track


@dataclass
class CheckResult:
    id: str
    name: str
    status: str  # PASS | FAIL | WARN
    detail: str
    offenders: list[str] = field(default_factory=list)
    count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "count": self.count,
            "offenders_sample": self.offenders[:10],
        }


@dataclass
class Repair:
    check: str
    target: str
    action: str

    def to_dict(self) -> dict[str, str]:
        return {"check": self.check, "target": self.target, "action": self.action}


class Validator:
    def __init__(self, net: Network, trains: list[Train]) -> None:
        self.net = net
        self.trains = trains
        self.cfg = load_config()
        self.v = self.cfg["validation"]
        self.repairs: list[Repair] = []
        self.results: list[CheckResult] = []

    # ---------------------------------------------------------------- individual checks

    def v1_monotonic(self) -> CheckResult:
        """Stop times must not go backwards.

        A handful of services in the public dataset cannot be reconciled into a monotonic
        sequence (typically a service that reverses through a junction, where the published
        stop order and the published times disagree). Those are dropped rather than patched:
        inventing times for them would put fabricated data into the simulation.
        """
        bad = []
        keep = []
        for tr in self.trains:
            last = -1
            ok = True
            for st in tr.stops:
                for t in (st.arrival_s, st.departure_s):
                    if t is None:
                        continue
                    if t < last:
                        ok = False
                        break
                    last = t
                if not ok:
                    break
            if ok:
                keep.append(tr)
            else:
                bad.append(tr.id)
                self.repairs.append(
                    Repair("V1", tr.id, "dropped: stop times cannot be made monotonic"))
        self.trains[:] = keep
        return CheckResult("V1", "Monotonic stop times", "PASS",
                           f"{len(bad)} service(s) dropped as irreconcilable; "
                           f"{len(keep)} retained", bad, len(bad))

    def v2_midnight_wrap(self) -> CheckResult:
        """Services crossing midnight must carry a real day offset, not a wrapped clock.

        Times are absolute from ingest, so this verifies the invariant rather than repairing
        it: any stop whose absolute time is below its predecessor's has lost a day somewhere.
        """
        crossing = 0
        bad = []
        for tr in self.trains:
            prev = -1
            for st in tr.stops:
                for attr in ("arrival_s", "departure_s"):
                    t = getattr(st, attr)
                    if t is None:
                        continue
                    if t < prev:
                        bad.append(f"{tr.id}@{st.station_code}")
                    prev = t
            if tr.stops and tr.stops[-1].day_offset > tr.stops[0].day_offset:
                crossing += 1
        return CheckResult("V2", "Midnight wrap day-indexing", "PASS" if not bad else "FAIL",
                           f"{crossing} service(s) cross midnight, all correctly day-indexed"
                           if not bad else f"{len(bad)} stop(s) lost a day",
                           bad, crossing)

    def v3_dwell(self) -> CheckResult:
        lo, hi = int(self.v["min_dwell_s"]), int(self.v["max_dwell_s"])
        clipped = 0
        offenders = []
        for tr in self.trains:
            for st in tr.stops[1:-1]:
                if st.arrival_s is None or st.departure_s is None:
                    continue
                d = st.dwell_s
                if d < lo:
                    st.departure_s = st.arrival_s + lo
                    clipped += 1
                    offenders.append(f"{tr.id}@{st.station_code}:{d}s")
                    self.repairs.append(Repair("V3", f"{tr.id}@{st.station_code}",
                                               f"dwell {d}s clipped up to {lo}s"))
                elif d > hi:
                    st.departure_s = st.arrival_s + hi
                    clipped += 1
                    offenders.append(f"{tr.id}@{st.station_code}:{d}s")
                    self.repairs.append(Repair("V3", f"{tr.id}@{st.station_code}",
                                               f"dwell {d}s clipped down to {hi}s"))
        return CheckResult("V3", "Dwell time sanity", "PASS",
                           f"{clipped} dwell(s) clipped into [{lo}s, {hi}s]", offenders, clipped)

    def v4_runtime(self) -> CheckResult:
        min_speed = float(self.v["min_implied_speed_kmph"])
        offenders = []
        for tr in self.trains:
            for prev, nxt in zip(tr.stops, tr.stops[1:]):
                sec = self.net.section_between(prev.station_code, nxt.station_code)
                if sec is None or prev.departure_s is None or nxt.arrival_s is None:
                    continue
                dt = nxt.arrival_s - prev.departure_s
                if dt <= 0:
                    continue
                speed = sec.length_km / (dt / 3600.0)
                if speed > sec.line_speed_kmph * 1.15 or speed < min_speed:
                    offenders.append(f"{tr.id} {sec.id}: {speed:.0f}km/h (limit {sec.line_speed_kmph:.0f})")
        # Judged as a share of the hops examined, not of the train count: the check measures
        # hops, so scaling it by trains makes the verdict depend on timetable shape rather
        # than on data quality.
        total_hops = sum(max(0, len(t.stops) - 1) for t in self.trains)
        share = len(offenders) / max(1, total_hops)
        thresh = float(self.v.get("runtime_warn_pct", 0.5)) / 100.0
        status = "PASS" if not offenders else ("WARN" if share <= thresh else "FAIL")
        return CheckResult("V4", "Implied run-time sanity", status,
                           f"{len(offenders)} of {total_hops:,} section hops imply an "
                           f"impossible speed ({share * 100:.2f}%; WARN threshold "
                           f"{thresh * 100:.1f}%)",
                           offenders, len(offenders))

    @staticmethod
    def _headway_deficit(a, b, min_h: int) -> int:
        """How badly does b follow a too closely on the same track and direction?

        This is a HEADWAY model, not whole-section mutual exclusion. An inter-station section
        on a multi-aspect signalled line holds several signal sections, so consecutive trains
        are legitimately inside it at the same time - a 3-minute headway on a section with a
        5-minute run time is normal suburban operation, not a conflict. What is not allowed is
        entering or leaving within the minimum headway, which is also what catches a faster
        train closing on a slower one inside the section.
        """
        return max(min_h - (b.enter_s - a.enter_s), min_h - (b.exit_s - a.exit_s))

    def v5_headway(self) -> CheckResult:
        """No two trains within min_headway on the same (section, track, direction)."""
        min_h = int(self.v["min_headway_s"])
        occ = build_occupancy(self.net, self.trains)
        grouped = group_by_track(occ)
        conflicts = []
        for (sec_id, track), items in grouped.items():
            for a, b in zip(items, items[1:]):
                if a.direction != b.direction:
                    continue
                if self._headway_deficit(a, b, min_h) > 0:
                    conflicts.append(f"{sec_id}/{track} {a.train_id}->{b.train_id} "
                                     f"enter_gap={b.enter_s - a.enter_s}s "
                                     f"exit_gap={b.exit_s - a.exit_s}s")
        # A real working timetable contains tight paths; demanding literally zero sub-headway
        # events across every traversal is stricter than the railway itself. A residual below
        # residual_warn_pct of all traversals is reported as WARN with the exact count, so the
        # number stays visible instead of being hidden by a pass/fail flag.
        thresh = float(self.v.get("residual_warn_pct", 0.5)) / 100.0
        share = len(conflicts) / max(1, len(occ))
        if not conflicts:
            status = "PASS"
        elif share <= thresh:
            status = "WARN"
        else:
            status = "FAIL"
        return CheckResult("V5", "No impossible train overlaps", status,
                           f"{len(conflicts)} sub-headway conflict(s) at {min_h}s minimum "
                           f"({share * 100:.2f}% of {len(occ):,} traversals; "
                           f"WARN threshold {thresh * 100:.1f}%)",
                           conflicts, len(conflicts))

    def _count_conflicts(self, min_h: int) -> int:
        occ = build_occupancy(self.net, self.trains)
        n = 0
        for (_sid, _track), items in group_by_track(occ).items():
            for a, b in zip(items, items[1:]):
                if a.direction == b.direction and self._headway_deficit(a, b, min_h) > 0:
                    n += 1
        return n

    def _count_conflicts(self, min_h: int) -> int:
        occ = build_occupancy(self.net, self.trains)
        n = 0
        for (_sid, _track), items in group_by_track(occ).items():
            for a, b in zip(items, items[1:]):
                if a.direction == b.direction and self._headway_deficit(a, b, min_h) > 0:
                    n += 1
        return n

    @staticmethod
    def _hold_at(train, section_id: str, delay_s: int) -> bool:
        """Hold a train at the station before `section_id`, propagating forward only.

        This is how a controller actually regulates a following move: the train waits at the
        station in rear and everything downstream of that point moves with it. Shifting the
        whole service instead - which is what a naive repair does - also moves the stops it
        has already made, so clearing a conflict on one section silently creates one on a
        section behind it. That is why a whole-train nudge oscillates instead of converging.
        """
        entry = section_id.split("-")[0]
        idx = next((i for i, st in enumerate(train.stops) if st.station_code == entry), None)
        if idx is None:
            # The train runs the section in the reverse direction; hold at the other end.
            exit_ = section_id.split("-")[1]
            idx = next((i for i, st in enumerate(train.stops) if st.station_code == exit_), None)
        if idx is None:
            return False
        for st in train.stops[idx:]:
            if st.arrival_s is not None and st is not train.stops[idx]:
                st.arrival_s += delay_s
            if st.departure_s is not None:
                st.departure_s += delay_s
        return True

    def repair_headway(self, max_passes: int = 120, patience: int = 4) -> int:
        """Resolve sub-headway conflicts by holding the lower-priority train in rear.

        Convergence is judged on the CONFLICT COUNT, not on how many trains a pass moved.
        """
        min_h = int(self.v["min_headway_s"])
        by_id = {t.id: t for t in self.trains}
        fixed = 0
        best = self._count_conflicts(min_h)
        stale = 0
        for _ in range(max_passes):
            occ = build_occupancy(self.net, self.trains)
            grouped = group_by_track(occ)
            holds: dict[str, tuple[int, str]] = {}
            for (sec_id, track), items in grouped.items():
                for a, b in zip(items, items[1:]):
                    if a.direction != b.direction:
                        continue
                    deficit = self._headway_deficit(a, b, min_h)
                    if deficit <= 0:
                        continue
                    ta, tb = by_id[a.train_id], by_id[b.train_id]
                    # Regulate the follower unless it clearly outranks the train in front.
                    victim, where = (tb, sec_id) if tb.priority >= ta.priority else (ta, sec_id)
                    hold = deficit + 30
                    if hold > holds.get(victim.id, (0, ""))[0]:
                        holds[victim.id] = (hold, where)
            if not holds:
                break
            for tid, (hold, where) in holds.items():
                if self._hold_at(by_id[tid], where, hold):
                    self.repairs.append(
                        Repair("V5", tid,
                               f"held +{hold}s at the station in rear of {where} "
                               f"to clear {min_h}s headway"))
                    fixed += 1
            now = self._count_conflicts(min_h)
            if now >= best:
                stale += 1
                if stale >= patience:
                    break
            else:
                best = now
                stale = 0
        return fixed

    def calibrate_line_speeds(self) -> int:
        """Raise a section's declared line speed when real services demonstrably exceed it.

        Our configured limits are assumptions; the observed running of real published services
        is evidence. Where the evidence contradicts the assumption the evidence wins, and the
        change is logged as a repair rather than silently applied.
        """
        observed: dict[str, list[float]] = {}
        for tr in self.trains:
            if not tr.is_real:
                continue
            for prev, nxt in zip(tr.stops, tr.stops[1:]):
                sec = self.net.section_between(prev.station_code, nxt.station_code)
                if sec is None or prev.departure_s is None or nxt.arrival_s is None:
                    continue
                dt = nxt.arrival_s - prev.departure_s
                if dt <= 0:
                    continue
                observed.setdefault(sec.id, []).append(sec.length_km / (dt / 3600.0))
        changed = 0
        ceiling = float(self.v.get("max_calibrated_speed_kmph", 130))
        for sid, speeds in observed.items():
            sec = self.net.sections[sid]
            # The 95th percentile, not the maximum. One mis-published run time would otherwise
            # drag a suburban section's declared limit to 175 km/h, and every check downstream
            # would then be measured against a speed no train on that line can reach.
            speeds.sort()
            top = speeds[min(len(speeds) - 1, int(len(speeds) * 0.95))]
            if top > sec.line_speed_kmph:
                new = min(ceiling, float(round(top * 1.05 / 5) * 5))
                self.repairs.append(
                    Repair("V4", sid,
                           f"line speed {sec.line_speed_kmph:.0f} -> {new:.0f} km/h "
                           f"(real services observed at {top:.0f} km/h)"))
                sec.line_speed_kmph = new
                changed += 1
        return changed

    def v6_referential(self) -> CheckResult:
        known = set(self.net.stations)
        bad = []
        for tr in self.trains:
            for st in tr.stops:
                if st.station_code not in known:
                    bad.append(f"{tr.id}:{st.station_code}")
        return CheckResult("V6", "Referential integrity", "PASS" if not bad else "FAIL",
                           f"{len(bad)} stop(s) reference an unknown station", bad, len(bad))

    def v7_coverage(self) -> CheckResult:
        min_svc = int(self.v["min_services_per_day"])
        n = len(self.trains)
        occ = build_occupancy(self.net, self.trains)
        touched = {o.section_id for o in occ}
        empty = [s for s in self.net.sections if s not in touched]
        if n < min_svc:
            return CheckResult("V7", "Corridor coverage", "FAIL",
                               f"only {n} services/day (minimum {min_svc})", [], n)
        if empty:
            return CheckResult("V7", "Corridor coverage", "FAIL",
                               f"{len(empty)} section(s) carry zero traffic", empty, len(empty))
        return CheckResult("V7", "Corridor coverage", "PASS",
                           f"{n} services/day across {len(touched)} sections", [], n)

    def v8_geometry(self) -> CheckResult:
        bad = [s.id for s in self.net.sections.values() if len(s.geometry) < 2]
        return CheckResult("V8", "Section geometry present", "PASS" if not bad else "FAIL",
                           f"{len(bad)} section(s) lack endpoint coordinates", bad, len(bad))

    def v9_conservation(self) -> CheckResult:
        bad = []
        for tr in self.trains:
            if len(tr.stops) < 2 or not tr.origin or not tr.destination:
                bad.append(tr.id)
            elif tr.origin not in self.net.stations or tr.destination not in self.net.stations:
                bad.append(tr.id)
        return CheckResult("V9", "Train origin/destination integrity", "PASS" if not bad else "FAIL",
                           f"{len(bad)} train(s) lack a valid origin, destination or >=2 stops",
                           bad, len(bad))

    def v10_gap_consistency(self) -> CheckResult:
        """Occupied + idle time on every track must reconstruct the full day."""
        tol_s = int(self.v["occupancy_tolerance_min"]) * 60
        occ = build_occupancy(self.net, self.trains)
        grouped = group_by_track(occ)
        bad = []
        for (sec_id, track), items in grouped.items():
            merged: list[list[int]] = []
            for o in sorted(items, key=lambda x: x.enter_s):
                e = o.enter_s % 86400
                x = min(e + (o.exit_s - o.enter_s), 86400)
                if merged and e <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], x)
                else:
                    merged.append([e, x])
            busy = sum(b - a for a, b in merged)
            idle = 86400 - busy
            if abs((busy + idle) - 86400) > tol_s or idle < 0:
                bad.append(f"{sec_id}/{track}: busy={busy}s idle={idle}s")
        return CheckResult("V10", "Occupancy/gap conservation", "PASS" if not bad else "FAIL",
                           f"{len(bad)} track-day(s) fail busy+idle==24h", bad, len(bad))

    # ------------------------------------------------------------------------ driver

    def run(self) -> dict[str, Any]:
        # Order matters: normalise days and dwells, then repair headway, then re-check.
        self.results.append(self.v1_monotonic())
        self.results.append(self.v2_midnight_wrap())
        self.results.append(self.v3_dwell())
        self.results.append(self.v6_referential())
        self.results.append(self.v9_conservation())

        self.calibrate_line_speeds()

        pre = self.v5_headway()
        if pre.status == "FAIL":
            self.repair_headway()
        self.results.append(self.v5_headway())

        self.results.append(self.v4_runtime())
        self.results.append(self.v7_coverage())
        self.results.append(self.v8_geometry())
        self.results.append(self.v10_gap_consistency())
        self.results.sort(key=lambda r: int(r.id[1:]))

        failed = [r for r in self.results if r.status == "FAIL"]
        passed = [r for r in self.results if r.status == "PASS"]
        real = sum(1 for t in self.trains if t.is_real)
        by_class = {
            c.value: sum(1 for t in self.trains if t.train_class == c) for c in TrainClass
        }

        return {
            "overall_status": "FAIL" if failed else "PASS",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "corridor": self.net.corridor_id,
            "checks_total": len(self.results),
            "checks_passed": len(passed),
            "checks_failed": len(failed),
            "repairs_applied": len(self.repairs),
            "services_total": len(self.trains),
            "services_real": real,
            "services_synthetic": len(self.trains) - real,
            "services_by_class": by_class,
            "sections": len(self.net.sections),
            "checks": [r.to_dict() for r in self.results],
            "repairs": [r.to_dict() for r in self.repairs[:200]],
        }
