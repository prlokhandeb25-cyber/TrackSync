"""Risk assessment for jobs that could share a place and time: hazards, likelihood x severity, controls, residual risk.

<!-- serves: J1, J5 -->

The compatibility verdict says whether two jobs MAY share a block. This says how risky it would be if they did, in the
form a safety officer expects: a list of hazards, each rated on a 5 x 5 matrix, the control that answers it, and what
risk is left once the control is applied.

    risk = likelihood (1 rare .. 5 almost certain) x severity (1 minor .. 5 fatal)
    band:  1-4 Low   5-9 Medium   10-16 High   17-25 Extreme

Two ratings are shown for every hazard: INHERENT (the two jobs worked together with nothing done about it) and
RESIDUAL (after the control the planner actually applies: kept at different times, a joint work permit, or work zones
that do not overlap). Likelihood comes from how the work zones sit (same zone / adjacent / apart), severity from the kind
of hazard, and the crowding hazard from the crews the two jobs need. All of these scales are rule-based assumptions (A-060):
the shape is standard, the numbers are judgement and are not calibrated to incident data.
"""

from __future__ import annotations

from backend.domain.compatibility import Verdict, ZoneRelation
from backend.domain.task import Department, Task

BANDS = ((17, "Extreme"), (10, "High"), (5, "Medium"), (1, "Low"))


def band(score: int) -> str:
    return next(name for lo, name in BANDS if score >= lo)


_BASE_L = {ZoneRelation.SAME_ZONE.value: 4, ZoneRelation.ADJACENT.value: 2, ZoneRelation.DISJOINT.value: 1}


def _crew(t: Task) -> int:
    try:
        from backend.planner.resources import costed
        return int(costed(t.type_def, t.duration_min)["norm_workers"])
    except Exception:
        return 6


def _hazard(hid: str, name: str, L: int, S: int, control: str, residual_L: int) -> dict:
    L, S = max(1, min(5, L)), max(1, min(5, S))
    rl = max(1, min(L, residual_L))
    return {"id": hid, "name": name, "likelihood": L, "severity": S, "inherent": L * S, "inherent_band": band(L * S),
            "control": control, "residual_likelihood": rl, "residual": rl * S, "residual_band": band(rl * S)}


def _residual_L(L: int, verdict: str) -> tuple[int, str]:
    """The likelihood left after the control the system applies for this verdict, and what that control is."""
    if verdict == Verdict.INCOMPATIBLE.value:
        return 1, "kept at different times (a hard rule, never worked together)"
    if verdict == Verdict.REQUIRES_IWP.value:
        return L - 2, "joint work permission signed by every department head"
    return (L - 1 if L > 1 else 1), "work zones do not overlap"


def assess_pair(a: Task, b: Task, verdict: str, relation: str) -> dict:
    """Hazards if these two jobs were worked at the same time, and the risk left after the planner's control."""
    L0 = _BASE_L.get(relation, 1)
    rL, ctl = _residual_L(L0, verdict)
    out: list[dict] = []
    depts = {a.department, b.department}
    if a.department != b.department and (a.requires_power_block or b.requires_power_block):
        out.append(_hazard("electrical", "Electric shock from live overhead wire", L0, 5,
                           ctl + "; power block with earthing confirmed before others enter", rL))
    if a.requires_traffic_block or b.requires_traffic_block:
        out.append(_hazard("on_track", "Struck by a train while working on or near the track", max(L0, 2), 5,
                           ctl + "; protected block with flagmen and lookouts", max(1, rL if L0 > 1 else 1)))
    if {Department.PWI, Department.S_AND_T} <= depts:
        out.append(_hazard("signal_fault", "Track work disturbs signalling (wrong-side failure)", L0, 4,
                           ctl + "; joint check of points and circuits before hand-back", rL))
    crowd = _crew(a) + _crew(b)
    if relation != ZoneRelation.DISJOINT.value:
        Lc = 4 if crowd >= 20 else 3 if crowd >= 14 else 2 if crowd >= 8 else 1
        out.append(_hazard("crowding", f"Crowded work site ({crowd} people between the two gangs)", Lc if relation == ZoneRelation.SAME_ZONE.value else Lc - 1, 3,
                           ctl + "; separate gangs under one site marshal", max(1, Lc - 2)))
    if verdict == Verdict.REQUIRES_IWP.value:
        out.append(_hazard("permit", "Permit or communication error between departments", 3, 4,
                           "one joint permit, read back by each department head", 2))
    return {"hazards": out, **_worst(out)}


def _worst(h: list[dict]) -> dict:
    if not h:
        return {"inherent": 0, "residual": 0, "inherent_band": "Low", "residual_band": "Low", "top": None}
    inh = max(h, key=lambda x: x["inherent"])
    res = max(h, key=lambda x: (x["residual"], x["inherent"]))
    return {"inherent": inh["inherent"], "inherent_band": inh["inherent_band"], "residual": res["residual"],
            "residual_band": res["residual_band"], "top": res["name"]}


def assess_job(task: Task, pair_risks: list[tuple[str, dict]]) -> dict:
    """One job's risk: its own hazards plus the worst each neighbouring job adds, with the controls that answer them."""
    own: list[dict] = []
    if task.requires_traffic_block:
        own.append(_hazard("on_track", "Struck by a train while working on or near the track", 2, 5,
                           "protected block with flagmen and lookouts", 1))
    if task.requires_power_block:
        own.append(_hazard("electrical", "Electric shock from live overhead wire", 2, 5,
                           "power block with earthing confirmed before work starts", 1))
    rows = [{**h, "with": None} for h in own]
    for other, pr in pair_risks:
        for h in pr["hazards"]:
            rows.append({**h, "with": other})
    rows.sort(key=lambda h: (-h["residual"], -h["inherent"]))
    worst = _worst(rows)
    cells: dict[tuple[int, int], int] = {}
    for h in rows:
        k = (h["residual_likelihood"], h["severity"])
        cells[k] = cells.get(k, 0) + 1
    controls: list[str] = []
    for h in rows:
        if h["control"] not in controls:
            controls.append(h["control"])
    return {**worst, "hazards": rows[:6], "n_hazards": len(rows), "controls": controls[:5],
            "cells": [[l, s, n] for (l, s), n in sorted(cells.items())]}
