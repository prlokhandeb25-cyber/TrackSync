"""What a job needs on site: people, equipment, materials - as planning norms, not a prediction.

<!-- serves: J1, J5 -->

There is no record here of real gang sizes or machine bookings, so this is a lookup of typical norms per kind of
work, scaled by how long the job runs. It does NOT claim to predict what a particular job will really use: it
gives a planner a starting bill of resources that a real works-management record would replace (ASSUMPTIONS.md
A-052). Nothing in the schedulers depends on it; it is shown next to a plan so the crew and machines can be lined
up as early as the slot is known.

Scaling: the standing crew is fixed; a job longer than one shift-block (4 h) needs a relief crew per extra block;
a job that needs a power block always has a traction-power officer and an earthing party on top.
"""

from __future__ import annotations

import math

from backend.domain.task import TASK_TYPES_BY_CODE, TaskType

SHIFT_MIN = 240

# code -> (crew by role, equipment, materials). Typical Indian Railways gang compositions, simplified.
NORMS: dict[str, tuple[list[tuple[str, int]], list[str], list[str]]] = {
    "PWI_RAIL_RENEWAL": ([("Section engineer (P.Way)", 1), ("Track maintainers", 8), ("Welder", 2)],
                         ["Rail cutting and welding set", "Rail tongs and jacks", "Tie-tamping hand tools"], ["Rails / welds", "Fish-plates", "Sleeper fittings"]),
    "PWI_TAMPING": ([("Junior engineer (P.Way)", 1), ("Machine operators", 2), ("Track maintainers", 4)],
                    ["Track tamping machine", "Track recording gauge"], ["Ballast (top-up)"]),
    "PWI_BALLAST": ([("Junior engineer (P.Way)", 1), ("Machine operators", 3), ("Track maintainers", 8)],
                    ["Ballast cleaning machine", "Ballast wagons"], ["Fresh ballast"]),
    "PWI_JOINT": ([("Track maintainer (mate)", 1), ("Track maintainers", 4)], ["Hand tools and jacks", "Gauge"], ["Fish-plates", "Bolts"]),
    "PWI_POINTS": ([("Junior engineer (P.Way)", 1), ("Track maintainers", 6)], ["Hand tools and jacks", "Gauge", "Point-setting gear"], ["Switch and crossing parts"]),
    "PWI_GAUGE": ([("Track maintainer (mate)", 1), ("Track maintainers", 5)], ["Gauge", "Hand tools and jacks"], ["Sleeper fittings"]),
    "OWD_TENSION": ([("Junior engineer (OHE)", 1), ("OHE technicians", 4)], ["Tower wagon", "Tensioning gear"], ["Wire clamps"]),
    "OWD_INSULATOR": ([("Junior engineer (OHE)", 1), ("OHE technicians", 3)], ["Tower wagon", "Insulator hoist"], ["Insulators"]),
    "OWD_DROPPER": ([("Junior engineer (OHE)", 1), ("OHE technicians", 3)], ["Tower wagon"], ["Droppers / jumpers"]),
    "OWD_MAST": ([("Junior engineer (OHE)", 1), ("OHE technicians", 5)], ["Tower wagon", "Mast alignment tools"], ["Cantilever parts"]),
    "SNT_POINT_MACHINE": ([("Signal maintainer (SSE)", 1), ("Signal technicians", 3)], ["Test set", "Hand tools"], ["Machine spares"]),
    "SNT_TRACK_CIRCUIT": ([("Signal maintainer (SSE)", 1), ("Signal technicians", 2)], ["Test set", "Multimeter"], ["Track-circuit spares"]),
    "SNT_SIGNAL_LAMP": ([("Signal technicians", 2)], ["Ladder", "Test lamp"], ["Signal lamps / LEDs"]),
    "SNT_AXLE_COUNTER": ([("Signal maintainer (SSE)", 1), ("Signal technicians", 2)], ["Test set", "Hand tools"], ["Counter head / cable spares"]),
    "SNT_CABLE_RELAY": ([("Signal maintainer (SSE)", 1), ("Signal technicians", 3)], ["Cable tester", "Hand tools"], ["Relays", "Cable"]),
    "SNT_INTERLOCK": ([("Signal inspector", 1), ("Signal maintainer (SSE)", 1), ("Signal technicians", 3)], ["Interlocking test set", "Panel logs"], []),
}

POWER = [("Traction power controller (on call)", 1), ("Earthing party", 2)]
PROTECTION = [("Flagmen / lookout", 2)]


def estimate(tt: TaskType | str, duration_min: int) -> dict:
    """A starting bill of resources for one job of this kind and length."""
    if isinstance(tt, str):
        tt = TASK_TYPES_BY_CODE[tt]
    crew, equip, mats = NORMS.get(tt.code, ([("Maintainers", 4)], ["Hand tools"], []))
    shifts = max(1, math.ceil(duration_min / SHIFT_MIN))
    roles = [(r, n) for r, n in crew]
    if tt.requires_traffic_block:
        roles += PROTECTION
    if tt.requires_power_block:
        roles += POWER
    per_shift = sum(n for _, n in roles)
    return {
        "task_type": tt.code, "label": tt.label, "department": tt.department.value, "duration_min": duration_min,
        "people_per_shift": per_shift, "shifts": shifts, "people_total": per_shift * shifts,
        "roles": [{"role": r, "n": n} for r, n in roles], "equipment": list(equip), "materials": list(mats),
        "power_block": tt.requires_power_block, "traffic_block": tt.requires_traffic_block,
        "basis": "planning norm (assumed, A-052), scaled by job length; not a measured prediction",
    }


def week_load(tasks_with_slots: list[tuple[str, int, int, int]]) -> dict:
    """People on site by day for a list of (task_type, duration_min, start_s, end_s): the peak a depot must staff."""
    per_day: dict[int, int] = {}
    for code, dur, s, e in tasks_with_slots:
        per_day[s // 86400] = per_day.get(s // 86400, 0) + estimate(code, dur)["people_per_shift"]
    return {"people_by_day": [per_day.get(d, 0) for d in range(7)], "peak": max(per_day.values(), default=0)}


# ---------------------------------------------------------------------------------- cost and crew what-ifs
# Planning rates in rupees, ASSUMED (A-056): a starting point for a costing sheet, not published tariffs.

ROLE_RATE = {   # rupees per person-hour
    "Section engineer (P.Way)": 1100, "Junior engineer (P.Way)": 900, "Junior engineer (OHE)": 900,
    "Signal inspector": 1100, "Signal maintainer (SSE)": 800, "Track maintainer (mate)": 500, "Track maintainers": 450,
    "Machine operators": 650, "Welder": 600, "OHE technicians": 500, "Signal technicians": 500,
    "Flagmen / lookout": 350, "Traction power controller (on call)": 700, "Earthing party": 450, "Maintainers": 450,
}
EQUIP_RATE = {  # rupees per hour of use
    "Track tamping machine": 6000, "Ballast cleaning machine": 9000, "Tower wagon": 3500, "Ballast wagons": 2500,
    "Rail cutting and welding set": 1200, "Interlocking test set": 400, "Test set": 200, "Cable tester": 200,
}
DEFAULT_EQUIP_RATE = 100
MATERIAL_COST = {   # rupees per job, typical
    "PWI_RAIL_RENEWAL": 60000, "PWI_TAMPING": 5000, "PWI_BALLAST": 40000, "PWI_JOINT": 3000, "PWI_POINTS": 25000, "PWI_GAUGE": 4000,
    "OWD_TENSION": 4000, "OWD_INSULATOR": 12000, "OWD_DROPPER": 3000, "OWD_MAST": 30000,
    "SNT_POINT_MACHINE": 15000, "SNT_TRACK_CIRCUIT": 8000, "SNT_SIGNAL_LAMP": 2000, "SNT_AXLE_COUNTER": 10000,
    "SNT_CABLE_RELAY": 12000, "SNT_INTERLOCK": 5000,
}
MACHINE_WORDS = ("machine", "wagon")
ALPHA_CREW, ALPHA_MACHINE, MAX_SCALE = 0.8, 0.9, 2.0     # diminishing returns; a site cannot use more than 2x the crew


def _is_protection(role: str) -> bool:
    return role in [r for r, _ in PROTECTION] or role in [r for r, _ in POWER]


def crew_core(est: dict) -> int:
    return sum(r["n"] for r in est["roles"] if not _is_protection(r["role"]))


def machines_of(est: dict) -> list[str]:
    return [e for e in est["equipment"] if any(w in e.lower() for w in MACHINE_WORDS)]


def _overhead_min(tt: TaskType) -> int:
    from backend.config import load_config
    g = load_config()["gaps"]
    extra = 2 * int(g["power_block_extra_min"]) if tt.requires_power_block else 0
    return int(g["block_setup_min"]) + int(g["block_release_min"]) + extra


def costed(tt: TaskType | str, duration_min: int, workers: int | None = None, machines: int | None = None) -> dict:
    """Duration, block length and cost for this job with `workers` core crew and `machines` machines.

    Work content is what the norm crew does in the stated duration. With more people it finishes sooner but with
    diminishing returns (speed-up = (n/n0)^0.8, machines (m/m0)^0.9, neither beyond 2x the norm): a crew cannot be
    doubled and still work twice as fast. Assumed shape (A-056), the same for every kind of work."""
    if isinstance(tt, str):
        tt = TASK_TYPES_BY_CODE[tt]
    base = estimate(tt, duration_min)
    n0 = max(1, crew_core(base))
    mach = machines_of(base)
    m0 = 1 if mach else 0
    n = n0 if workers is None else max(1, int(workers))
    m = m0 if machines is None else max(0, int(machines))
    speed = (min(n, MAX_SCALE * n0) / n0) ** ALPHA_CREW
    if m0:
        speed *= (max(1, min(m, MAX_SCALE * m0)) / m0) ** ALPHA_MACHINE
    dur = max(10.0, duration_min / speed)
    ovh = _overhead_min(tt)
    scale = n / n0
    labour = 0.0
    for r in base["roles"]:
        k = scale if not _is_protection(r["role"]) else 1.0
        labour += r["n"] * k * ROLE_RATE.get(r["role"], 450) * (dur + ovh) / 60.0
    equip = 0.0
    for e in base["equipment"]:
        units = m if any(w in e.lower() for w in MACHINE_WORDS) and m0 else 1
        equip += units * EQUIP_RATE.get(e, DEFAULT_EQUIP_RATE) * dur / 60.0
    mat = MATERIAL_COST.get(tt.code, 0)
    people = round(n + sum(r["n"] for r in base["roles"] if _is_protection(r["role"])))
    return {"task_type": tt.code, "label": tt.label, "workers": n, "machines": m, "norm_workers": n0, "norm_machines": m0,
            "machine_names": mach, "work_min": round(dur), "block_min": round(dur + ovh), "overhead_min": ovh, "people": people,
            "person_hours": round(people * (dur + ovh) / 60.0, 1),
            "cost": {"labour": round(labour), "equipment": round(equip), "materials": mat, "total": round(labour + equip + mat)},
            "basis": "assumed planning rates and a diminishing-returns speed-up (A-056), not measured"}


def crew_curve(tt: TaskType | str, duration_min: int, machines: int | None = None) -> list[dict]:
    base = costed(tt, duration_min)
    n0 = base["norm_workers"]
    return [costed(tt, duration_min, workers=n, machines=machines) for n in sorted({max(1, n0 - 2), n0, n0 + 2, n0 + 4, 2 * n0})]
