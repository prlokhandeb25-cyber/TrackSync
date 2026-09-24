"""The plan-quality endpoints and the assistant's plan-a-block answer, called as the API calls them.

A handler that is never invoked in a test can be wrong in ways the type checker cannot see: the
robustness endpoint once shipped with a stray variable that only failed at request time. These call the
real handlers on the real world (built once, about a minute).
"""

from __future__ import annotations


def test_verify_endpoint_reports_a_clean_plan():
    from backend.api.routes_quality import plan_verify
    d = plan_verify()
    assert {"ok", "n_violations", "total_checks", "checks"} <= set(d)
    assert d["ok"], d["violations"][:3]
    assert d["total_checks"] > 50


def test_robustness_endpoint_has_what_the_page_reads():
    from backend.api.routes_quality import plan_robustness
    d = plan_robustness()
    for key in ("plan", "before_centring", "centred_moves", "weakest", "ablation_status", "samples"):
        assert key in d
    assert 0.0 <= d["plan"]["mean"] <= 1.0
    if d["before_centring"]:
        assert d["plan"]["mean"] >= d["before_centring"]["mean"] - 1e-9     # centring never makes it worse


def test_the_assistant_answers_a_plan_a_block_question_with_a_picture():
    from backend.api.routes import chat
    d = chat({"q": "I need to plan a 90 minute PWI block on Kurla to Sion by Friday, where should I put it?", "at_s": 133200})
    assert d["intent"] == "planblock"
    assert d["visual"] and d["visual"]["type"] == "schedule"
    assert "new" in {b["kind"] for b in d["visual"]["blocks"]}
    assert "traffic block" in d["text"].lower()


def test_asking_a_what_if_never_changes_the_plan():
    from backend.api.routes import chat, plan
    before = [(a["task_id"], a["start_s"]) for a in plan()["assignments"]]
    chat({"q": "plan a 2 hour OHE block on Dadar to Matunga on 24 sep", "at_s": 133200})
    chat({"q": "what if Dadar to Matunga is closed at 14:00 for an hour?", "at_s": 133200})
    after = [(a["task_id"], a["start_s"]) for a in plan()["assignments"]]
    assert before == after
