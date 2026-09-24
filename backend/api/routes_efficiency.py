"""Network efficiency: time given back by early finishes, small jobs riding in big blocks, resources on site.

<!-- serves: J1, J5 -->

    GET /api/reclaim                 what a week of early-finishing blocks hands back to waiting small jobs
    GET /api/resources/estimate      the people, equipment and materials a job of this kind and length usually needs
    GET /api/efficiency              the measured pieces together: reclaim, grouping by place and urgency, rerouting
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.state import ensure_plan, ensure_world
from backend.domain.task import TASK_TYPES_BY_CODE
from backend.planner import reclaim as R
from backend.planner import resources as RS

router = APIRouter()
_RECLAIM: dict | None = None


def reclaim_summary() -> dict:
    global _RECLAIM
    if _RECLAIM is None:
        _RECLAIM = R.reclaim_week(ensure_world(), ensure_plan())
    return _RECLAIM


@router.get("/api/reclaim")
def reclaim() -> dict:
    return reclaim_summary()


@router.get("/api/resources/estimate")
def resources_estimate(task_type: str, duration_min: int = 60) -> dict:
    if task_type not in TASK_TYPES_BY_CODE:
        raise HTTPException(status_code=404, detail="unknown task type")
    return RS.estimate(task_type, max(10, min(720, duration_min)))


@router.get("/api/resources/whatif")
def resources_whatif(task_type: str, duration_min: int = 120, workers: int | None = None, machines: int | None = None) -> dict:
    """The job with a different number of workers or machines: the same model the chatbot's written answer uses."""
    from backend.chat.ops import crew_whatif_payload
    if task_type not in TASK_TYPES_BY_CODE:
        raise HTTPException(status_code=404, detail="unknown task type")
    return crew_whatif_payload(task_type, max(10, min(720, duration_min)),
                               None if workers is None else max(1, min(60, workers)), None if machines is None else max(0, min(6, machines)))


@router.get("/api/efficiency")
def efficiency() -> dict:
    from backend.api.routes import _cluster_pool, rerouting_proof
    from backend.planner.clustering import priority_effect

    w = ensure_world()
    pool = _cluster_pool()
    return {"reclaim": reclaim_summary(), "grouping": {**priority_effect(w.net, pool), "jobs": len(pool)},
            "rerouting": rerouting_proof()}
