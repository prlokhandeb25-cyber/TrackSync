"""Propose, approve or reject, apply, revert - and remember why.

<!-- serves: J1, J4, J5 -->

A coordinator should be able to overrule the system and have that remembered. A proposal is a whole alternative plan
(from the Pareto explorer, or a constrained-by-machines plan) with what it changes against the plan in force. It
moves through:

    proposed -> approved | rejected -> (approved only) applied -> reverted

Approving or rejecting needs a reason in words; every step is written, with who and when, to
`artifacts/audit_log.jsonl` (append-only). Applying swaps the plan in force and keeps a snapshot, so a revert restores
it exactly. Applying is refused while sudden tasks are booked against the current plan (they were placed around it;
clear them first), so the live state can never be left half-consistent.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import threading

from backend.config import REPO_ROOT

AUDIT_PATH = REPO_ROOT / "artifacts" / "audit_log.jsonl"
_LOCK = threading.Lock()
_PROPOSALS: dict[str, dict] = {}
_AUDIT: list[dict] = []
_SNAPSHOT: dict = {}
_SEQ = 0


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _audit(event: str, proposal_id: str | None, by: str, detail: dict | str) -> dict:
    rec = {"seq": len(_AUDIT) + 1, "at": _now(), "event": event, "proposal": proposal_id, "by": by, "detail": detail}
    _AUDIT.append(rec)
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass                                                   # the in-memory trail still stands
    return rec


def load_audit() -> None:
    if _AUDIT or not AUDIT_PATH.exists():
        return
    for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                _AUDIT.append(json.loads(line))
            except ValueError:
                pass


def audit(limit: int = 60) -> list[dict]:
    load_audit()
    return list(reversed(_AUDIT[-limit:]))


def _public(p: dict) -> dict:
    return {k: v for k, v in p.items() if k != "assignments"}


def proposals() -> list[dict]:
    return [_public(p) for p in sorted(_PROPOSALS.values(), key=lambda x: -x["n"])]


def propose(kind: str, title: str, by: str, assignments: list, summary: dict, diff: dict, extra: dict | None = None) -> dict:
    global _SEQ
    load_audit()
    with _LOCK:
        _SEQ += 1
        pid = f"PR-{_SEQ:03d}"
        p = {"id": pid, "n": _SEQ, "kind": kind, "title": title, "status": "proposed", "created_at": _now(), "created_by": by or "system",
             "summary": summary, "diff": {"moved": diff.get("moved", [])[:30], "added": diff.get("added", [])[:30],
                                          "dropped": diff.get("dropped", [])[:30], "unchanged": diff.get("unchanged", 0),
                                          "n_moved": len(diff.get("moved", [])), "n_added": len(diff.get("added", [])),
                                          "n_dropped": len(diff.get("dropped", []))},
             "reason": "", "decided_by": None, "decided_at": None, "assignments": assignments, "extra": extra or {}}
        _PROPOSALS[pid] = p
        _audit("proposed", pid, by or "system", {"title": title, "summary": summary, "moves": p["diff"]["n_moved"]})
        return _public(p)


def decide(pid: str, approve: bool, reason: str, by: str) -> dict:
    with _LOCK:
        p = _PROPOSALS.get(pid)
        if p is None:
            raise KeyError("unknown proposal")
        if p["status"] != "proposed":
            raise ValueError(f"already {p['status']}")
        if not reason.strip():
            raise ValueError("a reason is required")
        p.update(status="approved" if approve else "rejected", reason=reason.strip()[:400], decided_by=by or "coordinator", decided_at=_now())
        _audit("approved" if approve else "rejected", pid, p["decided_by"], {"reason": p["reason"], "title": p["title"]})
        return _public(p)


def _clear_caches() -> None:
    from backend.api import routes, routes_efficiency
    from backend.api.state import STATE
    from backend.planner import advisor
    from backend.planner.live_sim import LiveSimState

    routes._REROUTE_CACHE.clear()
    routes._REROUTE_SEEN.clear()
    routes._REROUTE_PROOF_WEEK = None
    routes_efficiency._RECLAIM = None
    routes._IMPACT_CACHE.clear()
    advisor._CACHE.clear()
    STATE.daily_state = LiveSimState()          # routine daily jobs are placed against the plan in force: redo them
    STATE.daily_summary = {}


def apply(pid: str, by: str) -> dict:
    from backend.api.state import STATE, ensure_plan, ensure_world

    w = ensure_world()
    cur = ensure_plan()
    with _LOCK:
        p = _PROPOSALS.get(pid)
        if p is None:
            raise KeyError("unknown proposal")
        if p["status"] != "approved":
            raise ValueError("only an approved proposal can be applied")
        if STATE.overrides or STATE.sudden_state.placed:
            raise ValueError("sudden tasks are booked against the current plan; clear them first")
        _SNAPSHOT.clear()
        _SNAPSHOT.update(pid=pid, plan=cur, natural=STATE.plan_natural, used=list(STATE.creation_used),
                         sched={t.id: (t.scheduled_start_s, t.scheduled_end_s, t.window_id, t.gap_type) for t in w.tasks})
        new = list(p["assignments"])
        placed = {a.task_id for a in new}
        for t in w.tasks:
            t.scheduled_start_s = t.scheduled_end_s = None
            t.window_id = t.gap_type = None
        by_id = {t.id: t for t in w.tasks}
        for a in new:
            t = by_id.get(a.task_id)
            if t is not None:
                t.scheduled_start_s, t.scheduled_end_s, t.window_id, t.gap_type = a.start_s, a.end_s, a.window_id, a.gap_type
        s = p["summary"]
        plan = dataclasses.replace(cur, assignments=new, unscheduled=[t.id for t in w.tasks if t.id not in placed],
                                   status=s.get("status", cur.status), gap_pct=s.get("gap_pct", cur.gap_pct),
                                   objective=s.get("objective", cur.objective), pax_exposed=s.get("passengers", cur.pax_exposed))
        STATE.plan, STATE.plan_natural, STATE.creation_used = plan, plan, []
        p["status"] = "applied"
        _clear_caches()
        _audit("applied", pid, by or "coordinator", {"title": p["title"], "jobs_placed": len(new)})
        return _public(p)


def revert(by: str) -> dict:
    from backend.api.state import STATE, ensure_world

    w = ensure_world()
    with _LOCK:
        if not _SNAPSHOT:
            raise ValueError("nothing to revert")
        pid = _SNAPSHOT["pid"]
        STATE.plan, STATE.plan_natural, STATE.creation_used = _SNAPSHOT["plan"], _SNAPSHOT["natural"], _SNAPSHOT["used"]
        for t in w.tasks:
            t.scheduled_start_s, t.scheduled_end_s, t.window_id, t.gap_type = _SNAPSHOT["sched"].get(t.id, (None, None, None, None))
        p = _PROPOSALS.get(pid)
        if p is not None:
            p["status"] = "reverted"
        _SNAPSHOT.clear()
        _clear_caches()
        _audit("reverted", pid, by or "coordinator", {"restored": "the plan in force before it was applied"})
        return _public(p) if p else {"id": pid, "status": "reverted"}


def can_revert() -> str | None:
    return _SNAPSHOT.get("pid")
