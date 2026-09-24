"""Will the block actually clear in time? Robust placement of a finished plan.

<!-- serves: J1, J2, J5 -->

An optimal plan is optimal for the timetable as printed. Real trains run late and real work
overruns, and a block that ends two minutes before the next train is a block that will, some days,
hold that train. Nothing in the weekly solver sees this: it puts a job anywhere inside its window
and only cares which day it lands on.

This module does two things with what the solver cannot see.

  1. MEASURE   For each block, sample the two things that go wrong - the train ahead running late
               (so the gang cannot start on time) and the work taking longer than planned - and
               count how often the line is handed back before the next train, with the lookout
               margin to spare. That fraction is the block's CLEARANCE PROBABILITY.
  2. CENTRE    Slide each job inside its own window to the start time that maximises that
               probability, on the same random draws, keeping it on the same day and accepting a
               move only if the independent referee (verify.py) still passes and no two jobs
               change whether they overlap (an integrated block stays integrated).

Nothing here changes which jobs are placed, on which day, or in which window: it only chooses the
minute a job starts. The gain is therefore measured, not assumed: same plan, before and after.
The delay model and the overrun spread are invented (ASSUMPTIONS.md A-043).
"""

from __future__ import annotations

import bisect
import random
from dataclasses import dataclass, field

from backend.config import load_config
from backend.data.week import DAY_S
from backend.domain.models import SectionOccupancy, TrainClass
from backend.domain.task import Task
from backend.planner.verify import verify_plan

_CLASS_KEY = {TrainClass.SUBURBAN_LOCAL: "suburban", TrainClass.INTERCITY: "intercity",
              TrainClass.FREIGHT_MAIL: "freight"}


@dataclass
class BlockRisk:
    task_id: str
    section_id: str
    track: str
    start_s: int
    end_s: int
    p_clear: float                    # chance the line is handed back before the next train
    slack_before_min: float           # room between the train ahead clearing and the gang starting
    slack_after_min: float            # room between hand-back and the next train (minus the lookout)
    prev_train: str | None = None
    next_train: str | None = None

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "section_id": self.section_id, "track": self.track,
                "start_s": self.start_s, "end_s": self.end_s, "p_clear": round(self.p_clear, 3),
                "slack_before_min": round(self.slack_before_min, 1),
                "slack_after_min": round(self.slack_after_min, 1),
                "prev_train": self.prev_train, "next_train": self.next_train}


@dataclass
class RobustnessReport:
    before: list[BlockRisk] = field(default_factory=list)
    after: list[BlockRisk] = field(default_factory=list)
    moved: int = 0
    samples: int = 0

    @staticmethod
    def _mean(rows: list[BlockRisk]) -> float:
        return sum(r.p_clear for r in rows) / len(rows) if rows else 1.0

    def to_dict(self) -> dict:
        b, a = self.before, self.after
        return {
            "samples": self.samples, "blocks": len(a), "moved": self.moved,
            "mean_before": round(self._mean(b), 4), "mean_after": round(self._mean(a), 4),
            "risky_before": sum(1 for r in b if r.p_clear < 0.9),
            "risky_after": sum(1 for r in a if r.p_clear < 0.9),
            "expected_overruns_before": round(sum(1 - r.p_clear for r in b), 2),
            "expected_overruns_after": round(sum(1 - r.p_clear for r in a), 2),
            "weakest": [r.to_dict() for r in sorted(a, key=lambda r: r.p_clear)[:6]],
            "rows": [r.to_dict() for r in a],
        }


class _Track:
    """One track's train movements, sorted, so 'the train before / after this time' is a bisect."""

    def __init__(self, items: list[SectionOccupancy]):
        rows = sorted(items, key=lambda o: o.enter_s)
        self.enters = [o.enter_s for o in rows]
        self.rows = rows

    def before(self, t: int) -> SectionOccupancy | None:
        """The last train that entered at or before t and has not exited later than t is treated as
        'ahead': we want the latest EXIT not after t."""
        best = None
        i = bisect.bisect_right(self.enters, t)
        for o in reversed(self.rows[max(0, i - 6):i]):
            if o.exit_s <= t and (best is None or o.exit_s > best.exit_s):
                best = o
        return best

    def after(self, t: int) -> SectionOccupancy | None:
        i = bisect.bisect_left(self.enters, t)
        return self.rows[i] if i < len(self.rows) else None


def _delay_draws(cls: TrainClass | None, at_s: int, n: int, rng: random.Random) -> list[float]:
    """Lateness of the train ahead, in seconds, from the configured gamma delay model."""
    if cls is None:
        return [0.0] * n
    cfg = load_config()["delays"]
    d = cfg[_CLASS_KEY.get(cls, "suburban")]
    mean, shape = float(d["mean_min"]), float(d["shape"])
    tod = at_s % DAY_S
    for a, b in cfg.get("peak_windows", []):
        h1, m1 = map(int, a.split(":")[:2])
        h2, m2 = map(int, b.split(":")[:2])
        if h1 * 3600 + m1 * 60 <= tod < h2 * 3600 + m2 * 60:
            mean *= float(cfg.get("peak_multiplier", 1.0))
            break
    scale = mean / shape
    return [rng.gammavariate(shape, scale) * 60.0 for _ in range(n)]


def _p_clear(start: int, dur_s: int, setup: int, release: int, buf: int, look: int,
             prev_exit: int | None, next_enter: int | None, late: list[float], over: list[float]) -> float:
    if next_enter is None:
        return 1.0
    ok = 0
    for d, m in zip(late, over):
        s = start if prev_exit is None else max(start, prev_exit + d + buf + setup)
        end = s + dur_s * m + release
        if end <= next_enter - look:
            ok += 1
    return ok / len(late)


def assess(assignments: list, tasks_by_id: dict[str, Task], occ_by_section: dict[str, list[SectionOccupancy]],
           samples: int = 400, seed: int | None = None, over_mean=None) -> list[BlockRisk]:
    """Clearance probability of every block in a plan, as it stands.

    `over_mean(task, assignment)` gives the average overrun multiplier for that block (1.0 if omitted);
    the crew-history experiment uses it to score a plan against the crews' real tendencies."""
    return _assess(assignments, tasks_by_id, occ_by_section, samples, seed, over_mean)[0]


def _setup_release(t: Task) -> tuple[int, int, int, int]:
    g = load_config()["gaps"]
    extra = int(g["power_block_extra_min"]) * 60 if t.requires_power_block else 0
    return (int(g["block_setup_min"]) * 60 + extra, int(g["block_release_min"]) * 60 + extra,
            int(g["headway_buffer_s"]), max(int(g["headway_buffer_s"]), int(g.get("lookout_min", 5)) * 60))


def _assess(assignments, tasks_by_id, occ_by_section, samples, seed, over_mean=None):
    seed = int(load_config()["seed"]) if seed is None else seed
    sigma = float(load_config().get_path("robustness.overrun_sigma", 0.15))
    tracks: dict[tuple[str, str], _Track] = {}
    out: list[BlockRisk] = []
    ctx: dict[str, tuple] = {}
    for k, a in enumerate(assignments):
        t = tasks_by_id.get(a.task_id)
        if t is None or a.zone_ref not in occ_by_section:
            continue
        key = (a.zone_ref, a.track)
        if key not in tracks:
            tracks[key] = _Track([o for o in occ_by_section[a.zone_ref] if o.track == a.track])
        tr = tracks[key]
        setup, release, buf, look = _setup_release(t)
        prev, nxt = tr.before(a.start_s), tr.after(a.end_s)
        rng = random.Random(seed * 1009 + k)           # the same draws for before and after
        late = _delay_draws(prev.train_class if prev else None, a.start_s, samples, rng)
        import math as _m
        m0 = float(over_mean(t, a)) if over_mean else 1.0
        mu = _m.log(max(1e-6, m0)) - sigma * sigma / 2
        over = [rng.lognormvariate(mu, sigma) for _ in range(samples)]
        ctx[a.task_id] = (tr, t, setup, release, buf, look, late, over)
        p = _p_clear(a.start_s, t.duration_min * 60, setup, release, buf, look,
                     prev.exit_s if prev else None, nxt.enter_s if nxt else None, late, over)
        out.append(BlockRisk(
            a.task_id, a.zone_ref, a.track, a.start_s, a.end_s, p,
            ((a.start_s - (prev.exit_s + buf + setup)) / 60) if prev else 999.0,
            ((nxt.enter_s - look - (a.end_s + release)) / 60) if nxt else 999.0,
            prev.train_id if prev else None, nxt.train_id if nxt else None))
    return out, ctx


def _overlap_pairs(placed: list[tuple[Task, object]]) -> set[tuple[str, str]]:
    s = set()
    for i, (ta, aa) in enumerate(placed):
        for tb, ab in placed[i + 1:]:
            if ta.zone.endpoints & tb.zone.endpoints and aa.start_s < ab.end_s and ab.start_s < aa.end_s:
                s.add((min(ta.id, tb.id), max(ta.id, tb.id)))
    return s


def centre_plan(net, tasks: list[Task], assignments: list, windows: list,
                occ_by_section: dict[str, list[SectionOccupancy]], samples: int = 400,
                only: set[str] | None = None, over_mean=None) -> tuple[list, RobustnessReport]:
    """Return a copy of the plan with each job slid to its most robust start, and the measurement.

    The input assignments are not modified. A move is kept only if the referee still passes and the
    set of overlapping job pairs is unchanged.
    """
    import copy

    by_id = {t.id: t for t in tasks}
    win = {w.id: w for w in windows}
    before, ctx = _assess(assignments, by_id, occ_by_section, samples, None, over_mean)
    new = [copy.copy(a) for a in assignments]
    rep = RobustnessReport(before=before, samples=samples)
    pairs0 = _overlap_pairs([(by_id[a.task_id], a) for a in new if a.task_id in by_id])
    idx = {a.task_id: i for i, a in enumerate(new)}

    for b in sorted(before, key=lambda r: r.p_clear):
        if only is not None and b.task_id not in only:
            continue                                    # e.g. the assistant centres just the new block
        a = new[idx[b.task_id]]
        w = win.get(a.window_id)
        if w is None or b.task_id not in ctx:
            continue                                    # created gaps are placed by their own logic
        tr, t, setup, release, buf, look, late, over = ctx[b.task_id]
        lo = w.start_s + setup
        resv = t.reserved_min * 60
        hi = w.end_s - release - resv
        day = a.start_s // DAY_S
        lo, hi = max(lo, day * DAY_S, t.released_s), min(hi, (day + 1) * DAY_S - resv)
        if hi < lo:
            continue
        dur = t.duration_min * 60
        prev, nxt = tr.before(a.start_s), tr.after(a.end_s)
        best_s, best_p = a.start_s, _p_clear(a.start_s, dur, setup, release, buf, look,
                                             prev.exit_s if prev else None, nxt.enter_s if nxt else None, late, over)
        step = 5 * 60
        s = lo
        while s <= hi:
            p = _p_clear(s, dur, setup, release, buf, look, prev.exit_s if prev else None,
                         nxt.enter_s if nxt else None, late, over)
            if p > best_p + 1e-9:
                best_s, best_p = s, p
            s += step
        if best_s == a.start_s:
            continue
        old = (a.start_s, a.end_s)
        a.start_s, a.end_s = best_s, best_s + resv
        placed = [(by_id[x.task_id], x) for x in new if x.task_id in by_id]
        ok = verify_plan(net, tasks, new, windows, occ_by_section).ok and _overlap_pairs(placed) == pairs0
        if ok:
            rep.moved += 1
        else:
            a.start_s, a.end_s = old
    rep.after = _assess(new, by_id, occ_by_section, samples, None, over_mean)[0]
    return new, rep
