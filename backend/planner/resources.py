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
