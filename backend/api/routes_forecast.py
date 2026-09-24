"""Predictive blocks: the watch list, the proactive blocks booked from it, and the over-prediction check.

<!-- serves: J1, J5 -->

    GET /api/forecast    the simulated warnings, what was decided for each, and (as it finishes) the policy sweep

The watch list is simulated (ASSUMPTIONS.md A-048). Booking is the real scheduler working on it: a warning
at or above the action threshold becomes an ordinary block in a gap that already exists, one crew visit per
section per day, capped per day; nothing is held, retimed or rerouted for a block that may not be needed.
"""

from __future__ import annotations

import threading

from fastapi import APIRouter

from backend.api.state import (
    STATE, ensure_interval_index, ensure_plan, ensure_world, get_pax, make_creator,
)
from backend.planner import forecast as F
from backend.planner.live_sim import LiveSimState

router = APIRouter()
_LOCK = threading.Lock()
_SWEEP: dict = {"status": "idle", "data": None, "error": None}


def live_forecast() -> dict:
    """Book the live proactive blocks once (against everything already booked) and return the summary."""
    w = ensure_world()
    ensure_plan()
    with _LOCK:
        if STATE.forecast_summary:
            return STATE.forecast_summary
        warns = F.watchlist(w.net)
        thr = F._cfg()["threshold"]
        committed = list(w.tasks) + [x.task for x in STATE.live_sim.placed if x.placed]
        STATE.forecast_state = LiveSimState()
        r = F.run_policy(w.net, ensure_interval_index(), committed, None, get_pax(), warns,
                         F.Policy("Live", thr, False), with_rows=True, state=STATE.forecast_state, play_failures=False)
        rows = sorted(r.pop("rows"), key=lambda d: d["warn_s"])
        by = {}
        for d in rows:
            by[d["decision"]] = by.get(d["decision"], 0) + 1
        STATE.forecast_rows = rows
        STATE.forecast_summary = {
            "threshold": thr, "warnings": len(rows), "planned": by.get("planned", 0), "watch": by.get("watch", 0),
            "covered": by.get("covered", 0), "budget": by.get("budget", 0), "no_gap": by.get("no gap", 0),
            "block_hours": r["block_hours"], "gaps_made": r["gaps_made_proactive"],
            "train_min": r["train_min"], "peak_blocks_a_day": r["peak_blocks_a_day"],
            "max_per_day": F._cfg()["max_per_day"],
        }
        STATE.log(0, (f"Early warnings: {len(rows)} on the watch list, {by.get('planned', 0)} planned ahead "
                      f"in existing gaps, none by changing trains."), "plan")
        return STATE.forecast_summary


def _sweep_worker() -> None:
    try:
        w = ensure_world()
        ensure_plan()
        data = F.policy_sweep(w.net, ensure_interval_index(), list(w.tasks), make_creator(), get_pax())
        with _LOCK:
            _SWEEP.update(status="done", data=data)
    except Exception as e:                                            # shown on the page, not swallowed
        with _LOCK:
            _SWEEP.update(status="error", error=repr(e))


@router.get("/api/forecast")
def forecast() -> dict:
    summary = live_forecast()
    with _LOCK:
        if _SWEEP["status"] == "idle":
            _SWEEP["status"] = "running"
            threading.Thread(target=_sweep_worker, daemon=True).start()
        sweep = dict(_SWEEP)
    return {"summary": summary, "rows": STATE.forecast_rows, "sweep": sweep["data"],
            "sweep_status": sweep["status"], "sweep_error": sweep["error"],
            "feed": "simulated: no camera or sensor data exists here (A-048)"}
