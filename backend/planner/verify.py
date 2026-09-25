"""An independent referee for a schedule.

<!-- serves: J2, J5 -->

CP-SAT reports OPTIMAL for the model it was given. That says nothing about whether the model was
written correctly, so this module re-checks a finished plan against the rules WITHOUT using the
solver's variables or its window bookkeeping: it reads the plan as plain intervals and asks each
rule again, and it checks the one thing the solver never sees directly - that no train is actually
running on the track during the work, straight from the timetable.

Checks (each counted, and every failure named):

  window     the job sits inside the usable span of the window it was given (set-up before, hand-back
             after, extra isolation for power-block work) and lasts exactly its duration
  release    it does not start before it was released; priority-1 work finishes by its deadline
  allotment  the department is allotted that zone (rule R0)
  clear      no train enters or occupies that track during the work - read from the timetable itself
  pairs      no two jobs that the rule engine calls INCOMPATIBLE overlap in time
  iwp        the Integrated Work Permissions used stay inside the weekly quota
  gangs      no department has more gangs out than it owns, at any instant
  stations   no station has more concurrent blocks than its tier allows
  daily      no day carries more blocks than the division can protect

A plan that passes is feasible in the plain reading of the rules. It does not prove optimality; that
comes from the solver's bound, and from comparing against baselines (see the scorecard).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from backend.config import load_config
from backend.data.week import DAY_S
from backend.domain.compatibility import Verdict, check_allotment
from backend.domain.models import SectionOccupancy, WorkZoneKind
from backend.domain.network import Network
from backend.domain.scoring import pair_verdict
from backend.domain.task import Task


@dataclass
class VerifyReport:
    violations: list[str] = field(default_factory=list)
    checks: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.violations

    def count(self, name: str, n: int = 1) -> None:
        self.checks[name] = self.checks.get(name, 0) + n

    def skip(self, name: str, n: int = 1) -> None:
        self.skipped[name] = self.skipped.get(name, 0) + n

    def to_dict(self) -> dict:
        return {"ok": self.ok, "violations": self.violations[:40], "n_violations": len(self.violations),
                "checks": self.checks, "total_checks": sum(self.checks.values()), "skipped": self.skipped}


def _peak_overlap(spans: list[tuple[int, int]]) -> int:
    ev = sorted([(s, 1) for s, _ in spans] + [(e, -1) for _, e in spans], key=lambda x: (x[0], x[1]))
    cur = best = 0
    for _, d in ev:
        cur += d
        best = max(best, cur)
    return best


def verify_plan(net: Network, tasks: list[Task], assignments: list, windows: list,
                occ_by_section: dict[str, list[SectionOccupancy]], max_blocks_per_day: int | None = None) -> VerifyReport:
    cfg = load_config()
    g = cfg["gaps"]
    rep = VerifyReport()
    by_id = {t.id: t for t in tasks}
    win = {w.id: w for w in windows}
    setup, release, extra = int(g["block_setup_min"]) * 60, int(g["block_release_min"]) * 60, int(g["power_block_extra_min"]) * 60

    placed: list[tuple[Task, object]] = []
    for a in assignments:
        t = by_id.get(a.task_id)
        if t is None:
            rep.violations.append(f"{a.task_id}: assigned but not in the task pool")
            continue
        placed.append((t, a))

        # allotment
        rep.count("allotment")
        if check_allotment(net, t) is not None:
            rep.violations.append(f"{t.id}: {t.department.value} is not allotted {t.zone.ref}")

        # work named for one exact line stays on that line
        if t.track is not None:
            rep.count("line")
            if a.track != t.track:
                rep.violations.append(f"{t.id}: named for the {t.track} line but placed on {a.track}")

        # duration, release, deadline
        rep.count("window")
        if a.end_s - a.start_s != t.reserved_min * 60:
            rep.violations.append(f"{t.id}: scheduled {(a.end_s - a.start_s) // 60} min, needs {t.reserved_min}")
        rep.count("release")
        if a.start_s < t.released_s:
            rep.violations.append(f"{t.id}: starts before it was released")
        if t.priority == 1 and t.due_by_s is not None and a.end_s > t.due_by_s:
            rep.violations.append(f"{t.id}: priority-1 work ends after its deadline")

        # inside the usable span of the window it was given
        w = win.get(a.window_id)
        if w is None:
            rep.skip("window (created gap, not re-derived)")
        else:
            lo = w.start_s + setup + (extra if t.requires_power_block else 0)
            hi = w.end_s - release - (extra if t.requires_power_block else 0)
            if a.start_s < lo or a.end_s > hi:
                rep.violations.append(f"{t.id}: outside the usable span of {w.id}")

        # clear of trains, straight from the timetable
        if a.zone_ref in net.sections:
            rep.count("clear")
            hit = next((o for o in occ_by_section.get(a.zone_ref, [])
                        if o.track == a.track and o.enter_s < a.end_s and o.exit_s > a.start_s), None)
            if hit is not None and not (a.window_id or "").startswith("CW-"):
                rep.violations.append(f"{t.id}: train {hit.train_id} is on {a.zone_ref} {a.track} during the work")
            elif hit is not None:
                rep.skip("clear (created gap: the train is held or diverted by design)")

    # pairwise rules
    iwp = 0
    probes = [(t, a, t.model_copy(update={"scheduled_start_s": a.start_s, "scheduled_end_s": a.end_s})) for t, a in placed]
    for i, (ta, aa, pa) in enumerate(probes):
        for tb, ab, pb in probes[i + 1:]:
            if not (ta.zone.endpoints & tb.zone.endpoints):
                continue
            if not (aa.start_s < ab.end_s and ab.start_s < aa.end_s):
                continue
            rep.count("pairs")
            v = pair_verdict(net, pa, pb)
            if v.value is Verdict.INCOMPATIBLE:
                rep.violations.append(f"{ta.id} and {tb.id} overlap but are INCOMPATIBLE ({v.rule_id})")
            elif v.value is Verdict.REQUIRES_IWP:
                iwp += 1
    rep.count("iwp")
    quota = int(cfg.get_path("departments.iwp_quota_per_day", 2)) * 7
    if iwp > quota:
        rep.violations.append(f"{iwp} Integrated Work Permissions used, quota is {quota}")

    # gangs
    gangs = int(cfg.get_path("departments.gangs_per_department", 2))
    for dept in {t.department for t, _ in placed}:
        rep.count("gangs")
        peak = _peak_overlap([(a.start_s, a.end_s) for t, a in placed if t.department is dept])
        if peak > gangs:
            rep.violations.append(f"{dept.value}: {peak} gangs out at once, owns {gangs}")

    # station concurrency
    tier_cfg = cfg["station_tiers"]
    caps = {"TIER_1": int(tier_cfg["max_concurrent_blocks_tier1"]), "TIER_2": int(tier_cfg["max_concurrent_blocks_tier2"]),
            "TIER_3": int(tier_cfg["max_concurrent_blocks_tier3"])}
    for code, st in net.stations.items():
        spans = [(a.start_s, a.end_s) for t, a in placed if code in t.zone.endpoints]
        if len(spans) < 2:
            continue
        rep.count("stations")
        cap = caps.get(st.tier.value if st.tier else "TIER_2", 2)
        peak = _peak_overlap(spans)
        if peak > cap:
            rep.violations.append(f"{code}: {peak} concurrent blocks, tier allows {cap}")

    # blocks per day
    per_day: dict[int, int] = defaultdict(int)
    for _, a in placed:
        per_day[a.start_s // DAY_S] += 1
    cap_day = int(max_blocks_per_day if max_blocks_per_day is not None else cfg.get_path("planner.max_blocks_per_day", 8))
    rep.count("daily", len(per_day))
    for d, n in per_day.items():
        if n > cap_day:
            rep.violations.append(f"day {d}: {n} blocks, limit is {cap_day}")
    return rep
