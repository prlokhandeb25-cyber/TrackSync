"""Early-finish reuse, priority-aware grouping with riders, resource norms, and the conversational chat.

What has to hold: time freed by an early finish is only ever given to jobs that fit it, on that block's own
section, priority first; grouping by urgency never mixes very urgent and very routine work more than grouping by
place alone; a rider is small, close in priority and allowed by the rules; resource estimates scale with length
and always include protection and, for a power block, the power staff; and the assistant answers in plain words
without touching the live state.
"""

from __future__ import annotations

import pytest

from backend.chat.engine import answer
from backend.chat.features import sandbox_fingerprint
from backend.domain.task import TASK_TYPES
from backend.planner import reclaim as R
from backend.planner.clustering import cluster_tasks, priority_effect
from backend.planner.resources import estimate


@pytest.fixture(scope="module")
def live():
    from backend.api.state import ensure_plan, ensure_world
    return ensure_world(), ensure_plan()


def test_freed_time_only_goes_to_jobs_that_fit_on_the_same_section(live):
    w, _ = live
    bk = R.make_backlog(w.net, 7, 200, 60)
    sec = next(iter(w.net.sections))
    ends = R._endpoints(w.net, sec)
    take = R.fill(w.net, sec, 90, bk, set())
    assert sum(j.duration_min for j in take) <= 90
    assert all(j.zone.ref in ends for j in take)
    assert [(j.priority, -j.duration_min) for j in take] == sorted((j.priority, -j.duration_min) for j in take)   # urgent first
    assert R.fill(w.net, sec, 5, bk, set()) == []                     # nothing is that short
    used = {j.id for j in take}
    assert not ({j.id for j in R.fill(w.net, sec, 90, bk, used)} & used)   # a job is used once


def test_reclaim_week_is_measured_and_reports_both_crew_assumptions(live):
    w, plan = live
    d = R.reclaim_week(w, plan)
    assert d["blocks"] == len(plan.assignments) and d["neutral"] is not None
    assert d["pulled_h"] <= d["freed_h"] + 1e-6                        # cannot use more time than was freed
    n = d["neutral"]
    assert n["pulled_h"] <= n["freed_h"] + 1e-6
    assert n["freed_h"] >= d["freed_h"]                                # crews that overrun give back less
    assert R.reclaim_week(w, plan)["pulled"] == d["pulled"]            # seeded: the same answer twice


def test_grouping_by_urgency_does_not_mix_urgent_and_routine_work_more_than_place_alone(live):
    w, _ = live
    from backend.api.routes import _cluster_pool
    pool = _cluster_pool()
    pe = priority_effect(w.net, pool)
    assert pe["place_and_urgency"]["mixed_urgency_groups"] <= pe["place_only"]["mixed_urgency_groups"]
    for c in cluster_tasks(w.net, pool):
        by = {t.id: t for t in pool}
        for r in c.riders:
            assert r["duration_min"] <= pe["small_job_min"]
            assert abs(r["priority"] - by[c.anchor_id].priority) <= 1
            assert by[c.anchor_id].duration_min > pe["small_job_min"]
        assert c.setup_saved_min == 25 * len(c.riders)                 # 15 min set-up + 10 min hand-back each


def test_resource_estimates_scale_with_length_and_include_protection_and_power_staff():
    for tt in TASK_TYPES:
        short, long_ = estimate(tt, 60), estimate(tt, 600)
        assert long_["people_total"] > short["people_total"] and long_["shifts"] > short["shifts"]
        roles = {r["role"] for r in short["roles"]}
        assert short["equipment"], tt.code
        if tt.requires_traffic_block:
            assert "Flagmen / lookout" in roles
        if tt.requires_power_block:
            assert "Earthing party" in roles and "Traction power controller (on call)" in roles
    assert "not a measured prediction" in estimate("PWI_TAMPING", 60)["basis"]


def test_the_assistant_talks_plainly_runs_the_new_features_and_changes_nothing(live):
    w, plan = live
    before = sandbox_fingerprint()
    qa = {q: answer(q, w, plan, 9 * 3600) for q in [
        "hi", "what does a 3 hour tamping job need?", "what if a 10 hour block on Kurla to Sion finishes in 8 hours?",
        "how much time does early finishing give back over a week?", "how do you group small jobs with big ones?",
        "can you predict failures?"]}
    assert sandbox_fingerprint() == before
    r = qa["what does a 3 hour tamping job need?"]
    assert r.intent == "resources" and "people" in r.text and "planning norms" in r.text and r.visual["type"] == "crew" and r.visuals[0]["type"] == "bars"
    e = qa["what if a 10 hour block on Kurla to Sion finishes in 8 hours?"]
    assert e.intent == "reclaim" and e.visual["type"] == "blockbar" and e.visual["planned_min"] == 600 and e.visual["actual_min"] == 480
    assert sum(j["min"] for j in e.visual["jobs"]) <= 120
    assert qa["how much time does early finishing give back over a week?"].intent == "reclaim"
    assert qa["how do you group small jobs with big ones?"].intent == "clusters"
    p = qa["can you predict failures?"]
    assert p.intent == "prediction" and "made up" in p.text            # honest about why it was removed
    assert qa["hi"].intent == "greeting"
