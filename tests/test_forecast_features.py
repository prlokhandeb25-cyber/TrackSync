"""Predictive blocks, the twin as adviser, K-Medoids, the reroute proof, and the assistant's sandbox.

What has to hold: warning early never makes a train pay for a block that may not be needed (proactive blocks
sit in existing gaps, capped per day and per section); acting early never costs more train-minutes than waiting;
K-Medoids really finds the groups and its centres are actual points; the twin can overrule a detour that costs
passengers more than waiting; suburban locals are never rerouted (CLAUDE.md invariant); and every question the
assistant runs leaves the live plan, bookings, log and forecast exactly as they were.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.chat.engine import answer
from backend.chat.features import FEATURES, sandbox_fingerprint
from backend.planner.clustering import kmedoids_auto, pam, silhouette
from backend.planner.forecast import Policy, _cfg, run_policy, watchlist


@pytest.fixture(scope="module")
def live():
    from backend.api.state import ensure_interval_index, ensure_plan, ensure_world, get_pax, make_creator
    w = ensure_world()
    plan = ensure_plan()
    return w, plan, ensure_interval_index(), get_pax(), make_creator()


# ------------------------------------------------------------------------------- predictive blocks


def test_proactive_blocks_never_change_a_train_and_stay_within_the_caps(live):
    w, _, idx, pax, creator = live
    warns = watchlist(w.net)
    thr = _cfg()["threshold"]
    react = run_policy(w.net, idx, list(w.tasks), creator, pax, warns, Policy("react", 2.0, False))
    act = run_policy(w.net, idx, list(w.tasks), creator, pax, warns, Policy("act", thr, False), with_rows=True)
    assert act["gaps_made_proactive"] == 0, "a proactive block made the trains change"
    assert act["peak_blocks_a_day"] <= _cfg()["max_per_day"]
    planned = [d for d in act["rows"] if d["decision"] == "planned"]
    assert len({(d["section"], d["start_s"] // 86400) for d in planned}) == len(planned), "two visits to one section in a day"
    assert act["blocks_added"] == len(planned) and act["blocks_added"] <= act["warnings"]
    assert act["train_min"] <= react["train_min"]                          # warning early never costs trains
    assert act["emergencies"] <= react["emergencies"]
    assert react["emergencies"] == react["failures"]                      # with no forecast, every failure is an emergency
    assert all(d["risk"] >= thr for d in planned), "a warning under the threshold was acted on"


def test_the_watch_list_is_deterministic_and_hides_the_truth_from_the_scheduler(live):
    w = live[0]
    a, b = watchlist(w.net), watchlist(w.net)
    assert [(x.id, x.risk, x.fail_s, x.fails) for x in a] == [(x.id, x.risk, x.fail_s, x.fails) for x in b]
    assert 0 < sum(x.fails for x in a) < len(a)
    from backend.planner.forecast import run_policy as rp
    rows = rp(w.net, live[2], list(w.tasks), live[4], live[3], a, Policy("act", 0.3, False), with_rows=True)["rows"]
    assert all("fails" not in r for r in rows), "the hidden outcome leaked into what the UI is shown"


# ------------------------------------------------------------------------------------ K-Medoids


def _blobs(seed=0):
    rng = np.random.default_rng(seed)
    centres = np.array([[0.0, 0.0], [30.0, 0.0], [15.0, 25.0]])
    pts = np.vstack([c + rng.normal(0, 1.2, (12, 2)) for c in centres])
    return pts, np.repeat([0, 1, 2], 12)


def test_kmedoids_recovers_separated_groups_and_centres_are_real_points():
    pts, truth = _blobs()
    labels, med, k = kmedoids_auto(pts)
    assert k == 3
    for g in range(3):                                                    # each true blob is exactly one found group
        assert len(set(labels[truth == g])) == 1
    assert len(set(labels)) == 3
    assert all(0 <= m < len(pts) for m in med) and len(set(med)) == 3     # a medoid is one of the points
    from backend.planner.clustering import _dist
    assert silhouette(_dist(pts), labels) > 0.8


def test_pam_swap_step_never_ends_worse_than_its_build():
    pts, _ = _blobs(3)
    from backend.planner.clustering import _dist
    D = _dist(pts)
    labels, med = pam(D, 3)
    cost = D[:, med].min(1).sum()
    rng = np.random.default_rng(1)
    for _ in range(20):                                                   # beats random medoid choices
        r = list(rng.choice(len(pts), 3, replace=False))
        assert cost <= D[:, r].min(1).sum() + 1e-9


# ----------------------------------------------------------------------------- the twin as adviser


def test_the_twin_overrules_a_detour_that_costs_more_than_waiting(monkeypatch):
    from backend.planner import advisor

    def fake(hold, div, single):
        pol = {"HOLD": {"pax_min": hold * 60, "train_min": 1, "label": "h"},
               "DIVERT": {"pax_min": div * 60, "train_min": 1, "label": "d"},
               "DIVERT_SINGLE": {"pax_min": single * 60, "train_min": 1, "label": "s"}}
        best = min(pol, key=lambda k: pol[k]["pax_min"])
        return lambda *a, **k: {"policies": pol, "best": best, "scenarios": 6, "horizon_h": 12}

    monkeypatch.setattr(advisor.M, "twin_experiment", fake(hold=10, div=500, single=900))
    advisor._CACHE.clear()
    out = advisor.response_now(None, None, "X-Y", 0, 3600, scenarios=6)
    assert out["best"] == "HOLD" and out["divert"] is False and out["single_line"] is False

    monkeypatch.setattr(advisor.M, "twin_experiment", fake(hold=800, div=100, single=50))
    advisor._CACHE.clear()
    out = advisor.response_now(None, None, "X-Y", 0, 3600, scenarios=6)
    assert out["divert"] is True and out["single_line"] is True

    monkeypatch.setattr(advisor.M, "twin_experiment", fake(hold=100, div=100, single=100))     # a tie keeps standing practice
    advisor._CACHE.clear()
    out = advisor.response_now(None, None, "X-Y", 0, 3600, scenarios=6)
    assert out["divert"] is True


def test_the_live_reroute_route_attaches_the_twin_response_and_honours_it(live, monkeypatch):
    from backend.api import routes
    from backend.planner import advisor

    from backend.api.routes import rerouting_proof
    ex = rerouting_proof()["examples"][0]           # a block that really has a train to send round
    monkeypatch.setattr(advisor, "response_for",
                        lambda *args, **kw: {"status": "ready", "best": "HOLD", "divert": False, "single_line": False,
                                             "pax_hours": {"HOLD": 1, "DIVERT": 9, "DIVERT_SINGLE": 9}, "scenarios": 6, "horizon_h": 12})
    routes._REROUTE_CACHE.clear()
    out = routes.rerouting_active(ex["block_start_s"] + 60)
    blk = next(b for b in out["blocks"] if b["section_id"] == ex["section_id"] and b["start_s"] == ex["block_start_s"])
    assert blk["response"]["best"] == "HOLD"
    assert blk["reroutes"] == [] and blk.get("track_swap") is None          # nothing shown as taken
    assert any(h["train_id"] == ex["train_id"] for h in blk["held"]), "the diverted train should be reported as held"
    routes._REROUTE_CACHE.clear()


# ------------------------------------------------------------------------------- the reroute proof


def test_reroute_proof_is_measured_and_never_reroutes_a_local(live):
    from backend.api.routes import rerouting_proof
    p = rerouting_proof()
    assert p["blocks"] > 0
    assert p["locals_rerouted"] == 0
    assert all(r["class"] != "SUBURBAN_LOCAL" for r in p["examples"])
    assert p["diverted"] >= len(p["examples"])
    assert abs(p["saved_min"] - (p["wait_min"] - p["added_min"])) < 0.6      # the headline is the difference of the two measured sums
    assert p["within_limit"] <= p["diverted"]


# --------------------------------------------------------------------------- the assistant's sandbox


QUESTIONS = [
    "what can you do?",
    "can you predict failures?",
    "what is the best response if Dadar to Matunga is closed at 9am?",
    "how are trains rerouted around a block?",
    "what if a critical S&T fault at Kurla right now?",
    "compare the two ways of grouping jobs",
    "which algorithms do you use, and is it optimal?",
    "how much buffer does an OHE job need in rain?",
    "explain the digital twin",
]


def test_every_feature_question_runs_on_a_copy_and_leaves_the_live_state_alone(live):
    w, plan = live[0], live[1]
    before = sandbox_fingerprint()
    seen = {}
    for q in QUESTIONS:
        a = answer(q, w, plan, 9 * 3600)
        assert a.text and len(a.text) > 40, q
        seen[q] = a
    assert sandbox_fingerprint() == before, "answering a question changed the live plan, bookings or forecast"
    assert seen[QUESTIONS[1]].intent == "prediction"                        # the warning feature was removed; the answer says why
    assert seen[QUESTIONS[3]].visual["type"] == "route"
    assert seen[QUESTIONS[5]].visual["type"] == "scatter"
    assert "none of the" in seen[QUESTIONS[3]].text and "rerouted" in seen[QUESTIONS[3]].text   # locals are never rerouted


def test_the_catalogue_covers_the_features_and_every_entry_has_a_way_to_try_it():
    ids = {f["id"] for f in FEATURES}
    assert {"plan", "sudden", "reclaim", "twin", "reroute", "clusters", "pax", "resources"} <= ids
    assert all(f["try"] and f["what"] and f["where"] and f["how"] for f in FEATURES)
