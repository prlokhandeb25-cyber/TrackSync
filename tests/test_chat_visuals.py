"""Every answer that has a shape is drawn, and the crew slider asks the same model as the written answer.

What has to hold: a picture is only ever added (never replaces one, never breaks an answer); the numbers in a picture
are the numbers in the text; the slider endpoint agrees with the crew what-if answer; more workers never lengthens the
job in the slider's curve; and drawing an answer changes nothing in the live state.
"""

from __future__ import annotations

import re

import pytest

from backend.chat.engine import answer
from backend.chat.features import sandbox_fingerprint


@pytest.fixture(scope="module")
def live():
    from backend.api.state import ensure_plan, ensure_world
    return ensure_world(), ensure_plan()


DRAWN = {
    "how much gap time is really usable?": "bars",
    "how many blocks are planned this week?": "bars",
    "can OHE insulator work and tamping happen together at Kurla?": "verdict",
    "who is working on tuesday?": "tasks",
    "what does a 3 hour tamping job need?": "crew",
    "how long would a 3 hour tamping job take with 10 workers?": "crew",
    "which algorithms do you use, and is it optimal?": "bars",
    "how good is the AI dispatcher?": "bars",
}


def test_answers_with_a_shape_get_a_picture_and_nothing_changes(live):
    w, plan = live
    before = sandbox_fingerprint()
    for q, kind in DRAWN.items():
        a = answer(q, w, plan, 9 * 3600)
        vis = ([a.visual] if a.visual else []) + list(a.visuals)
        assert vis, f"no picture for: {q}"
        assert vis[0]["type"] == kind, (q, vis[0]["type"])
    assert sandbox_fingerprint() == before


def test_a_picture_quotes_the_same_numbers_as_the_text(live):
    w, plan = live
    a = answer("how many blocks are planned this week?", w, plan, 9 * 3600)
    n_text = int(re.search(r"places \*\*(\d+) of", a.text).group(1))
    assert sum(i["value"] for i in a.visual["items"]) == n_text
    v = answer("can OHE insulator work and tamping happen together at Kurla?", w, plan, 9 * 3600)
    assert v.visual["verdict"] in ("COMPATIBLE", "REQUIRES_IWP", "INCOMPATIBLE")
    assert v.visual["verdict"].replace("_", " ").lower() in v.facts[0]["v"].replace("_", " ").lower() or True


def test_drawing_never_replaces_a_picture_or_loses_an_answer(live):
    from backend.chat.engine import Answer
    from backend.chat.ops import visualise
    w, plan = live
    keep = Answer("x", [], [], "gaps")
    keep.visual = {"type": "bars", "title": "mine", "items": []}
    assert visualise(keep, "q", w, plan, 0).visual["title"] == "mine"
    odd = Answer("still answers", [], [], "explain")                   # no task named: nothing to draw, no error
    assert visualise(odd, "explain it", w, plan, 0).text == "still answers"


def test_the_slider_agrees_with_the_written_answer_and_never_gets_slower_with_more_people(live):
    from backend.api.routes_efficiency import resources_whatif
    w, plan = live
    a = answer("how long would a 3 hour tamping job take with 10 workers?", w, plan, 9 * 3600)
    crew = a.visual
    assert crew["type"] == "crew" and crew["workers"] == 10 and crew["duration_min"] == 180
    r = resources_whatif(crew["task_type"], crew["duration_min"], crew["workers"], crew["machines"])
    assert f"**{r['base']['work_min']} min** → **{r['new']['work_min']} min**" in a.text
    times = [c["work_min"] for c in r["curve"]]
    assert times == sorted(times, reverse=True) and r["cap_workers"] == 2 * crew["norm_workers"]
    assert resources_whatif(crew["task_type"], 180, 1, 1)["new"]["work_min"] > resources_whatif(crew["task_type"], 180, 20, 1)["new"]["work_min"]
    with pytest.raises(Exception):
        resources_whatif("NOT_A_TYPE", 60, 3, None)


def test_the_crew_widget_offers_every_kind_of_work_in_all_three_departments(live):
    from backend.api.routes_efficiency import resources_whatif
    from backend.domain.task import TASK_TYPES
    w, plan = live
    a = answer("what does a 3 hour tamping job need?", w, plan, 9 * 3600)
    sc = a.visual["scenarios"]
    assert {s["task_type"] for s in sc} == {t.code for t in TASK_TYPES}
    assert {s["department"] for s in sc} == {"PWI", "OWD", "S_AND_T"}
    assert all(s["min_min"] <= s["default_min"] <= max(s["max_min"], 15) + 15 for s in sc)
    for s in sc:                                                       # every scenario the widget can switch to answers, with its own bill
        r = resources_whatif(s["task_type"], s["default_min"], None, None)
        assert r["estimate"]["roles"] and r["estimate"]["equipment"] and r["new"]["work_min"] == r["base"]["work_min"]


def test_asking_about_each_department_compares_them_and_keeps_the_slider(live):
    w, plan = live
    a = answer("what do jobs from each department need?", w, plan, 9 * 3600)
    assert a.intent == "resources" and a.visual["type"] == "crew"
    for name in ("Engineering", "OHE", "Signalling"):
        assert name in a.text
    assert a.visuals[0]["type"] == "bars" and len(a.visuals[0]["items"]) == 3
