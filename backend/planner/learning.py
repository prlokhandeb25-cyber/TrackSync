"""Closed-loop learning: planned versus actual duration, logged as jobs finish, updates the crew timing estimate.

<!-- serves: J1, J5 -->

Every completed job is one record: department, whether it rained, planned minutes, actual minutes. The estimate for
each (department, weather) group starts from a NEUTRAL prior (crews take exactly the planned time, weighted as
`learning.prior_weight` past jobs) and moves toward what the log shows:

    mean  = (prior_weight x 1.0 + sum of actual/planned) / (prior_weight + n)
    p80   = the 80th percentile of the logged ratios (once a group has `learning.min_n` records, else the pooled
            spread of all records), shifted to sit on the posterior mean

and the buffer is then the same rule the planner already uses (p80 overrun, capped at half the job, rounded up to
5 minutes). With no records the buffer is zero, not an invented one; with records it is theirs.

Real completions are stored in `artifacts/execution_log.jsonl`. A separate SIMULATED stream (drawn from the hidden
crew table used elsewhere, A-045) can be switched on to watch the estimate converge; it is labelled and never
mixed into the real log.
"""

from __future__ import annotations

import json
import math
import random
import threading

from backend.config import REPO_ROOT, load_config
from backend.planner.crew_profile import TRUE_MEAN, _draw

LOG_PATH = REPO_ROOT / "artifacts" / "execution_log.jsonl"
_LOCK = threading.Lock()
_REAL: list[dict] | None = None
_SIM: list[dict] = []
DEPTS = ("PWI", "OWD", "S_AND_T")


def _cfg() -> dict:
    c = load_config().get_path("learning", {}) or {}
    return {"k0": float(c.get("prior_weight", 5)), "min_n": int(c.get("min_n", 10))}


def _real() -> list[dict]:
    global _REAL
    if _REAL is None:
        _REAL = []
        if LOG_PATH.exists():
            for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        _REAL.append(json.loads(line))
                    except ValueError:
                        pass
    return _REAL


def log_completion(task_id: str, department: str, rain: bool, planned_min: int, actual_min: int, note: str = "") -> dict:
    if department not in DEPTS:
        raise ValueError("unknown department")
    if planned_min <= 0 or actual_min <= 0:
        raise ValueError("minutes must be positive")
    rec = {"task_id": task_id, "department": department, "rain": bool(rain), "planned_min": int(planned_min),
           "actual_min": int(actual_min), "ratio": round(actual_min / planned_min, 4), "note": note[:200]}
    with _LOCK:
        _real().append(rec)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    return rec


def simulate(n: int, seed: int = 0) -> int:
    """Add `n` SIMULATED completions drawn from the hidden crew table (not real data, kept separate)."""
    rng = random.Random(seed + len(_SIM))
    keys = list(TRUE_MEAN)
    with _LOCK:
        for _ in range(n):
            d, wet = rng.choice(keys)
            planned = rng.choice([45, 60, 90, 120])
            r = _draw(TRUE_MEAN[(d, wet)], rng)
            _SIM.append({"task_id": f"SIM-{len(_SIM) + 1}", "department": d, "rain": wet, "planned_min": planned,
                         "actual_min": max(1, round(planned * r)), "ratio": round(r, 4), "simulated": True})
    return len(_SIM)


def reset_simulated() -> None:
    with _LOCK:
        _SIM.clear()


def records(source: str) -> list[dict]:
    return list(_SIM) if source == "simulated" else list(_real())


def estimate(source: str = "real") -> list[dict]:
    """Per (department, weather): how many records, the learned mean and p80, and the buffer for a 120-minute job."""
    c = _cfg()
    recs = records(source)
    pooled = sorted(r["ratio"] for r in recs)
    out = []
    for d in DEPTS:
        for wet in (False, True):
            rows = sorted(r["ratio"] for r in recs if r["department"] == d and r["rain"] == wet)
            n = len(rows)
            mean = (c["k0"] * 1.0 + sum(rows)) / (c["k0"] + n)
            src = rows if n >= c["min_n"] else pooled
            if src:
                raw_mean = sum(src) / len(src)
                p80 = src[min(len(src) - 1, int(0.8 * len(src)))] * (mean / raw_mean if raw_mean else 1.0)
            else:
                p80 = mean
            extra = min(max(0.0, p80 - 1.0) * 120, 0.5 * 120)
            out.append({"department": d, "rain": wet, "n": n, "mean": round(mean, 3), "p80": round(p80, 3),
                        "buffer_min_120": int(math.ceil(extra / 5.0) * 5) if extra > 0 else 0,
                        "prior": 1.0, "hidden_true_mean": TRUE_MEAN[(d, wet)] if source == "simulated" else None})
    return out


def buffer_min(department: str, rain: bool, duration_min: int, source: str = "real") -> int:
    row = next(r for r in estimate(source) if r["department"] == department and r["rain"] == bool(rain))
    extra = min(max(0.0, row["p80"] - 1.0) * duration_min, 0.5 * duration_min)
    return int(math.ceil(extra / 5.0) * 5) if extra > 0 else 0


def convergence(source: str = "simulated", steps: int = 12) -> list[dict]:
    """The estimate's mean error against the hidden truth as records accumulate (simulated stream only)."""
    recs = records(source)
    if not recs:
        return []
    out = []
    for k in range(1, steps + 1):
        m = max(1, len(recs) * k // steps)
        sub = recs[:m]
        errs = []
        for d in DEPTS:
            for wet in (False, True):
                rows = [r["ratio"] for r in sub if r["department"] == d and r["rain"] == wet]
                mean = (_cfg()["k0"] + sum(rows)) / (_cfg()["k0"] + len(rows))
                errs.append(abs(mean - TRUE_MEAN[(d, wet)]))
        out.append({"n": m, "mean_abs_error": round(sum(errs) / len(errs), 4)})
    return out
