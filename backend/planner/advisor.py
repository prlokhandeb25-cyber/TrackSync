"""The digital twin as the live response adviser: for a closure, what should happen to the trains?

<!-- serves: J1, J5 -->

`twin.py` replays the next twelve hours under three responses (hold everything, divert long-distance and
freight, divert and run locals single-line). This module puts that in the loop: each closure in force on
the Operations map is sent to the twin, in the background, and the answer decides what the map and the
Rerouting panel do with it:

  - divert long-distance/freight only when diverting is not worse than holding (a detour that costs more
    passenger-hours than waiting is not taken);
  - run locals single-line on the open track only when that is not worse than holding them.

Until the twin has answered, the default is the standing practice (divert, single-line) and the block is
marked "checking". Results are cached per closure, so each is replayed once. Suburban locals are still never
rerouted: that is enforced in the twin and in the reroute search, not here.
"""

from __future__ import annotations

import threading

from backend.planner import methods as M

_LOCK = threading.Lock()
_CACHE: dict[tuple, dict] = {}
_PENDING: set[tuple] = set()
MARGIN_PAX_MIN = 60.0          # a response must beat another by an hour of passenger delay to overrule it


def _key(section_id: str, start_s: int, end_s: int) -> tuple:
    return (section_id, int(start_s), int(end_s))


def _run(world, rc, key: tuple, scenarios: int) -> None:
    section_id, start_s, end_s = key
    try:
        r = M.twin_experiment(world, rc, section_id, start_s, max(15, (end_s - start_s) // 60), scenarios=scenarios)
        pol = r["policies"]
        hold, div, single = pol["HOLD"]["pax_min"], pol["DIVERT"]["pax_min"], pol["DIVERT_SINGLE"]["pax_min"]
        out = {"status": "ready", "best": r["best"], "label": pol[r["best"]]["label"],
               "divert": not (hold + MARGIN_PAX_MIN < div),
               "single_line": not (hold + MARGIN_PAX_MIN < single) and not (div + MARGIN_PAX_MIN < single),
               "pax_hours": {k: round(v["pax_min"] / 60) for k, v in pol.items()},
               "train_min": {k: round(v["train_min"]) for k, v in pol.items()},
               "scenarios": r["scenarios"], "horizon_h": r["horizon_h"]}
    except Exception as e:                                            # the map falls back to standing practice
        out = {"status": "error", "error": repr(e), "divert": True, "single_line": True}
    with _LOCK:
        _CACHE[key] = out
        _PENDING.discard(key)


def response_for(world, rc, section_id: str, start_s: int, end_s: int, scenarios: int = 6) -> dict:
    """The twin's answer for this closure if it has one; otherwise start it and say it is being checked."""
    k = _key(section_id, start_s, end_s)
    with _LOCK:
        if k in _CACHE:
            return dict(_CACHE[k])
        if k not in _PENDING:
            _PENDING.add(k)
            threading.Thread(target=_run, args=(world, rc, k, scenarios), daemon=True).start()
    return {"status": "checking", "divert": True, "single_line": True}


def response_now(world, rc, section_id: str, start_s: int, end_s: int, scenarios: int = 12) -> dict:
    """The same answer, computed here and now (the assistant and the closure form wait for it)."""
    k = _key(section_id, start_s, end_s)
    with _LOCK:
        if k in _CACHE and _CACHE[k].get("scenarios", 0) >= scenarios:
            return dict(_CACHE[k])
    _run(world, rc, k, scenarios)
    with _LOCK:
        return dict(_CACHE[k])
