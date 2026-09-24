"""FastAPI entrypoint.

<!-- serves: J2, J4 -->

The validation gate is enforced here: if data/validation_report.json reports FAIL and
validation.block_on_fail is true, every data-serving route returns 503. Scheduling results
computed on inconsistent timetable data are worthless (SPEC §3.4).
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.api.routes_tasks import router as tasks_router
from backend.api.routes_sudden import router as sudden_router
from backend.api.routes_quality import router as quality_router
from backend.api.routes_methods import router as methods_router
from backend.config import REPO_ROOT, load_config, seed_everything

app = FastAPI(title="RailBlock AI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(tasks_router)
app.include_router(sudden_router)
app.include_router(quality_router)
app.include_router(methods_router)

VALIDATION_REPORT = REPO_ROOT / "data" / "validation_report.json"


def validation_state() -> dict:
    if not VALIDATION_REPORT.exists():
        return {"status": "NOT_RUN", "detail": "scripts/01_validate.py has not been run"}
    with open(VALIDATION_REPORT, "r", encoding="utf-8") as fh:
        report = json.load(fh)
    return {
        "status": report.get("overall_status", "UNKNOWN"),
        "checks_passed": report.get("checks_passed"),
        "checks_total": report.get("checks_total"),
        "repairs": report.get("repairs_applied"),
        "generated_at": report.get("generated_at"),
    }


def require_valid_data() -> None:
    """Dependency for every data-serving route."""
    cfg = load_config()
    if not cfg.get_path("validation.block_on_fail", True):
        return
    state = validation_state()
    if state["status"] != "PASS":
        raise HTTPException(
            status_code=503,
            detail=(
                f"Validation gate: {state['status']}. "
                "Run scripts/01_validate.py. Scheduling on unvalidated timetable data is blocked "
                "(SPEC §3.4)."
            ),
        )


@app.on_event("startup")
def _startup() -> None:
    seed = seed_everything()
    app.state.seed = seed


@app.get("/api/health")
def health() -> dict:
    cfg = load_config()
    return {
        "service": "railblock-ai",
        "version": app.version,
        "seed": cfg["seed"],
        "corridors": cfg["corridors"],
        "adapters_mode": cfg.get_path("adapters.mode"),
        "validation": validation_state(),
    }


@app.get("/api/validation")
def validation() -> dict:
    if not VALIDATION_REPORT.exists():
        raise HTTPException(status_code=404, detail="No validation report. Run scripts/01_validate.py.")
    with open(VALIDATION_REPORT, "r", encoding="utf-8") as fh:
        return json.load(fh)


# Routes added in later phases: /api/network /api/trains /api/gaps /api/tasks
# /api/plan/* /api/compatibility/matrix /api/sim/control /api/work/complete
# /api/metrics/impact /api/rl/comparison /ws/state   (SPEC §17)
