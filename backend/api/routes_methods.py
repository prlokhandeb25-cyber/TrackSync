"""The four proposed methods, each measured.

<!-- serves: J1, J5 -->

    GET /api/methods/summary   predictive, digital twin, bundling and adaptive buffers, computed once in the
                               background (the slow ones take a minute or two) and served as each finishes
    GET /api/methods/twin      one closure replayed under each response (used by the assistant)

Every result carries how it was measured and, where it rests on an invented model, a caveat, and a
`verdict` derived from the numbers by fixed thresholds rather than written by hand.
"""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException

from backend.api.state import (
    STATE, ensure_interval_index, ensure_plan, ensure_world, get_pax, make_creator, occupancy_by_section,
    reroute_cache,
)
from backend.planner import methods as M

router = APIRouter()

_S: dict = {"status": "idle", "done": {}, "error": None}
_LOCK = threading.Lock()


def _verdict(gain_pct: float, cost: str | None = None) -> str:
    if cost:
        return "trade-off"
    return "helps" if gain_pct >= 10 else "marginal" if gain_pct >= 1 else "no gain"


def _put(key: str, val: dict) -> None:
    with _LOCK:
        _S["done"][key] = val


def _worker() -> None:
    try:
        w = ensure_world()
        ensure_plan()
        pax = get_pax()
        occ = occupancy_by_section()

        p = M.predictive_run(w, ensure_interval_index(), make_creator(), pax)
        r0, r8 = p["reactive"], next(x for x in p["predictive"] if abs(x["p_detect"] - 0.8) < 1e-9)
        p["verdict"] = _verdict(100.0 * (r0["train_min"] - r8["train_min"]) / max(1.0, r0["train_min"]))
        _put("predictive", p)

        g = M.twin_grid(w, reroute_cache())
        for c in g["cases"]:
            pol = c["policies"]
            worst = max(v["pax_min"] for v in pol.values())
            best = pol[c["best"]]["pax_min"]
            c["spread_x"] = round(worst / best, 1) if best >= 600 else None      # a ratio against ~0 says nothing
        g["verdict"] = "helps" if len({c["best"] for c in g["cases"]}) > 1 else "marginal"
        g["how"] = ("Three closures replayed through the next 12 hours of the real timetable under each response, "
                    "20 random days each, delay measured against the same days without the closure.")
        g["caveat"] = "Recovery per hop and single-line capacity are invented (A-046); the timetable, classes and reroute costs are real."
        _put("twin", g)

        b = M.bundling_experiment(seeds=(11, 12, 13, 14, 15, 16), time_limit_s=8.0)
        b["verdict"] = _verdict(100.0 * (b["blocks_before"] - b["blocks_after"]) / max(1, b["blocks_before"]))
        _put("bundling", b)

        f = M.buffers_experiment(w, pax, occ, time_limit_s=20.0)
        lost = f["flat"]["placed"] - f["adaptive"]["placed"]
        gain = 100.0 * (f["adaptive"]["mean"] - f["flat"]["mean"]) / max(1e-9, f["flat"]["mean"])
        f["verdict"] = _verdict(gain, cost=("fewer jobs placed" if lost > 0 else None))
        f["jobs_lost"] = lost
        _put("buffers", f)
        with _LOCK:
            _S["status"] = "done"
    except Exception as e:                                        # shown on the page, not swallowed
        with _LOCK:
            _S.update(status="error", error=repr(e))


@router.get("/api/methods/summary")
def methods_summary() -> dict:
    with _LOCK:
        if _S["status"] == "idle":
            _S["status"] = "running"
            threading.Thread(target=_worker, daemon=True).start()
        return {"status": _S["status"], "error": _S["error"], "results": dict(_S["done"])}


@router.get("/api/methods/twin")
def methods_twin(section: str, start_s: int = 0, duration_min: int = 120, scenarios: int = 20) -> dict:
    w = ensure_world()
    if section not in w.net.sections:
        raise HTTPException(status_code=404, detail="unknown section")
    return M.twin_experiment(w, reroute_cache(), section, start_s, duration_min, scenarios=max(4, min(60, scenarios)))
