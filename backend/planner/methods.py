"""Evaluations of the four proposed methods, each measured against the way it would have been done
without it. Everything here runs on copies and writes nothing back to the live plan.

<!-- serves: J1, J5 -->

    buffers_experiment      adaptive buffers learned from crew history  (crew_profile.py)
    bundling_experiment     multi-department bundling pass              (bundle.py)
    twin_experiment         digital-twin ripple of a closure, by policy (twin.py)
    predictive_experiment   early warning vs emergency response         (predictive.py)

Each returns plain numbers plus a `how` string. Where a result depends on an invented model the
`caveat` says so; the numbers describe the mechanism on this timetable, not a forecast.
"""

from __future__ import annotations

import copy

from backend.config import load_config
from backend.data.week import DAY_S
from backend.planner.bundle import bundle_plan
from backend.planner.cpsat import solve_with_relaxation
from backend.planner.crew_profile import CrewModel, rain_days, synthetic_history, true_mean
from backend.planner.robustness import assess, centre_plan
from backend.planner.verify import verify_plan


def _fresh(tasks):
    out = [t.model_copy(deep=True) for t in tasks]
    for t in out:
        t.scheduled_start_s = t.scheduled_end_s = None
        t.window_id = t.gap_type = None
    return out


def _stats(rows) -> dict:
    n = len(rows)
    return {"mean": round(sum(r.p_clear for r in rows) / n, 4) if n else 1.0,
            "fragile": sum(1 for r in rows if r.p_clear < 0.9),
            "expected_overruns": round(sum(1 - r.p_clear for r in rows), 2), "blocks": n}


def buffers_experiment(world, pax, occ, time_limit_s: float = 20.0) -> dict:
    """The same week planned twice - flat, and with buffers learned from history - then both scored
    against what the crews really do (the hidden table), not against what either plan assumed."""
    model = CrewModel(synthetic_history())
    truth = lambda t, a: true_mean(t.department.value, a.start_s // DAY_S)      # noqa: E731
    wet = rain_days()

    def run(buffered: bool) -> dict:
        tasks = _fresh(world.tasks)
        if buffered:
            for t in tasks:                       # the dry-weather buffer goes into the solve itself
                t.buffer_min = model.buffer_min(t.department.value, False, t.duration_min)
        res = solve_with_relaxation(world.net, tasks, world.windows, time_limit_s=time_limit_s, pax=pax)
        by = {t.id: t for t in tasks}
        assigns = [copy.copy(a) for a in res.assignments]
        topped = 0
        if buffered:
            # rain top-up: a job that landed on a wet day reserves the wet-weather buffer if the gap has room
            win = {w.id: w for w in world.windows}
            g = load_config()["gaps"]
            release = int(g["block_release_min"]) * 60 + (int(g["power_block_extra_min"]) * 60)
            for a in assigns:
                t = by[a.task_id]
                if (a.start_s // DAY_S) % 7 not in wet:
                    continue
                want = model.buffer_min(t.department.value, True, t.duration_min)
                extra = want - t.buffer_min
                w = win.get(a.window_id)
                if extra <= 0 or w is None:
                    continue
                rel = int(g["block_release_min"]) * 60 + (int(g["power_block_extra_min"]) * 60 if t.requires_power_block else 0)
                if a.end_s + extra * 60 + rel > w.end_s:
                    continue
                t.buffer_min, a.end_s = want, a.end_s + extra * 60
                if not verify_plan(world.net, tasks, assigns, world.windows, occ).ok:
                    t.buffer_min, a.end_s = want - extra, a.end_s - extra * 60      # roll back
                else:
                    topped += 1
        # both plans are centred with the SAME belief (no knowledge of the truth)
        centred, _ = centre_plan(world.net, tasks, assigns, world.windows, occ)
        ok = verify_plan(world.net, tasks, centred, world.windows, occ)
        rows = assess(centred, by, occ, over_mean=truth)
        reserved = sum((by[a.task_id].reserved_min for a in centred))
        work = sum((by[a.task_id].duration_min for a in centred))
        return {"placed": len(centred), "status": res.status, "referee_ok": ok.ok, **_stats(rows),
                "reserved_hours": round(reserved / 60, 1), "work_hours": round(work / 60, 1), "topped_up": topped}

    flat, adaptive = run(False), run(True)
    return {
        "flat": flat, "adaptive": adaptive, "learned": model.table(),
        "history_jobs": 600, "rain_days": sorted(wet),
        "how": "The same week solved twice: with no buffers, and with buffers learned from 600 synthetic past jobs "
               "(80th percentile of overrun by department and weather; a wet-day top-up when the gap has room). "
               "Both plans are then scored by simulating each block against the crews' hidden true overrun.",
        "caveat": "The crew history is synthetic (A-045): this shows the mechanism works, not that real crews behave this way.",
    }


def bundling_experiment(seeds=(11, 12, 13, 14, 15, 16, 17, 18), n_tasks: int = 40, time_limit_s: float = 10.0) -> dict:
    """The bundling pass on several independent weekly instances: blocks and held track-hours, before/after."""
    from backend.config import seed_everything
    from backend.planner.context import sample_instance

    seed_everything()
    rows = []
    for sd in seeds:
        w = sample_instance(n_tasks=n_tasks, task_seed=sd, corridor=str(load_config()["corridors"][0]))
        occ: dict = {}
        for o in w.occupancy:
            occ.setdefault(o.section_id, []).append(o)
        res = solve_with_relaxation(w.net, w.tasks, w.windows, time_limit_s=time_limit_s)
        new, rep = bundle_plan(w.net, w.tasks, res.assignments, w.windows, occ)
        ok = verify_plan(w.net, w.tasks, new, w.windows, occ).ok
        d = rep.to_dict()
        rows.append({"seed": sd, "placed": len(res.assignments), "solver_pairs": res.integrated_pairs,
                     "blocks_before": d["blocks_before"], "blocks_after": d["blocks_after"],
                     "held_before": d["held_hours_before"], "held_after": d["held_hours_after"],
                     "merges": len(d["merges"]), "referee_ok": ok})
    bb, ba = sum(r["blocks_before"] for r in rows), sum(r["blocks_after"] for r in rows)
    hb, ha = sum(r["held_before"] for r in rows), sum(r["held_after"] for r in rows)
    return {"instances": len(rows), "rows": rows, "blocks_before": bb, "blocks_after": ba,
            "held_before": round(hb, 1), "held_after": round(ha, 1),
            "merges": sum(r["merges"] for r in rows), "all_legal": all(r["referee_ok"] for r in rows),
            "how": f"The weekly solver's plan for {len(rows)} independent instances, then the bundling pass; blocks and "
                   "track-hours held closed counted before and after. Every result re-checked by the referee.",
            "caveat": "Instances are synthetic job pools on the first configured corridor (like the rest of the project's jobs)."}


def twin_experiment(world, rc, section_id: str, start_s: int, duration_min: int, scenarios: int | None = None) -> dict:
    """Replay a closure through the next twelve hours under each response and say which is best."""
    from backend.planner.rerouting import track_swap_opportunity
    from backend.planner.twin import Twin, closure_ripple

    sec = world.net.sections[section_id]
    swap = track_swap_opportunity(world.net, sec, 10.0)
    pair = (swap.blocked_track, swap.swap_to_track) if swap else None
    blocked = {pair[0]} if pair else {sec.tracks[0]}
    key = ("_twin", id(world))
    tw = getattr(world, "_twin_cache", None)
    if tw is None:
        tw = Twin(world.occupancy)
        try:
            world._twin_cache = tw          # type: ignore[attr-defined]
        except Exception:
            pass
    r = closure_ripple(tw, section_id, blocked, start_s, duration_min, lambda tid: rc.delay_min(tid, section_id),
                       pair, scenarios=scenarios)
    r.update({"section": section_id, "start_s": start_s, "duration_min": duration_min, "blocked_track": sorted(blocked),
              "how": "The real timetable replayed with the closure in it; delay carries along each train's route and pushes "
                     "the trains behind it on every track. Each response is run over the same random days and compared with "
                     "the same days without the closure.",
              "caveat": "Recovery per hop and single-line capacity are invented (A-046); the timetable, classes and reroute costs are real."})
    return r


def twin_grid(world, rc, cases=None) -> dict:
    """One closure at three times of day, on the busiest section that has a local track pair, so the page can
    show that the best response changes with the moment (the section is chosen from the data, not named)."""
    from backend.planner.rerouting import track_swap_opportunity

    if cases is None:
        counts: dict[str, int] = {}
        for o in world.occupancy:
            counts[o.section_id] = counts.get(o.section_id, 0) + 1
        paired = [sid for sid, sec in world.net.sections.items() if track_swap_opportunity(world.net, sec, 10.0) is not None]
        if not paired:
            return {"cases": []}
        sec = max(paired, key=lambda x: counts.get(x, 0))
        cases = [(sec, 2, 120, "night"), (sec, 14, 120, "midday"), (sec, 8, 90, "morning peak")]
    out = []
    for sec, hour, dur, label in cases:
        if sec not in world.net.sections:
            continue
        r = twin_experiment(world, rc, sec, 86400 + hour * 3600, dur, scenarios=20)
        out.append({"label": f"{sec} · {label} · {dur} min", "best": r["best"], "policies": r["policies"]})
    return {"cases": out}


def predictive_run(world, index, creator, pax) -> dict:
    from backend.planner.predictive import predictive_experiment
    return predictive_experiment(world.net, index, [t for t in world.tasks if t.scheduled_start_s is not None], creator, pax)
