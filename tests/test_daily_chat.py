"""Daily routine jobs from 04:00, crew and cost what-ifs, slot questions, tasks in the chat, and tidy answers.

What has to hold: daily routine jobs never start before 04:00 or after their own day, sit in real gaps and pass the
rule engine against everything booked; more workers or machines never lengthen a job and never speed it up
beyond the cap; a time range parses both ways; a slot answer reports gap, usable minutes, who may use it and a
buffer that really reaches its target on the simulation; and answers are bullet lists that leave the live state alone.
"""

from __future__ import annotations

import pytest

from backend.chat.engine import answer
from backend.chat.features import sandbox_fingerprint
from backend.chat.ops import neaten, time_range
from backend.domain.scoring import pair_verdict
from backend.domain.compatibility import Verdict
from backend.planner import resources as RS


@pytest.fixture(scope="module")
def live():
    from backend.api.state import ensure_plan, ensure_world
    return ensure_world(), ensure_plan()


def test_daily_routine_jobs_start_from_0400_inside_their_day_and_pass_the_rules(live):
    from backend.api.routes_tasks import ensure_dayfill
    from backend.api.state import STATE
    w, _ = live
    d = ensure_dayfill()
    assert d["placed"] > 0 and d["placed"] + d["unplaced"] == d["per_day"] * 7
    booked = [t for t in w.tasks if t.scheduled_start_s is not None]
    for p in STATE.daily_state.placed:
        if not p.placed:
            continue
        day = p.task.id.split("-")[1]
        assert p.start_s // 86400 == int(day), "a daily job left its own day"
        assert (p.start_s % 86400) >= 4 * 3600, "a daily job started before 04:00"
        assert p.end_s <= (int(day) + 1) * 86400
        for b in booked:
            if b.scheduled_start_s < p.end_s and (b.scheduled_end_s or 0) > p.start_s and (b.zone.endpoints & p.task.zone.endpoints):
                assert pair_verdict(w.net, p.task, b).value is not Verdict.INCOMPATIBLE, (p.task.id, b.id)


def test_the_week_view_shows_daily_jobs_and_counts_them(live):
    from backend.api.routes_tasks import schedule_week
    sw = schedule_week()
    daily = [e for e in sw["entries"] if e["source"] == "DAILY"]
    assert len(daily) == sw["summary"]["daily_placed"] > 0
    assert all((e["start_s"] % 86400) >= 4 * 3600 for e in daily)


def test_more_workers_or_machines_never_lengthen_a_job_and_the_speedup_is_capped():
    for code in ("PWI_TAMPING", "OWD_MAST", "SNT_INTERLOCK"):
        base = RS.costed(code, 180)
        n0 = base["norm_workers"]
        times = [RS.costed(code, 180, workers=n)["work_min"] for n in (n0 // 2 or 1, n0, n0 + 2, 2 * n0, 4 * n0)]
        assert times == sorted(times, reverse=True), (code, times)
        assert times[-1] == times[-2]                                   # nothing beyond twice the norm crew
        assert RS.costed(code, 180)["block_min"] == 180 + base["overhead_min"]
    tamp = RS.costed("PWI_TAMPING", 180)
    assert RS.costed("PWI_TAMPING", 180, machines=2)["work_min"] < tamp["work_min"]
    assert RS.costed("PWI_TAMPING", 180)["cost"]["total"] == sum(RS.costed("PWI_TAMPING", 180)["cost"][k] for k in ("labour", "equipment", "materials"))


def test_time_ranges_parse_in_the_ways_people_write_them():
    assert time_range("between 14:00 and 15:30") == (14 * 3600, 15 * 3600 + 1800)
    assert time_range("2pm to 3pm") == (14 * 3600, 15 * 3600)
    assert time_range("is it free 14:00-15:00?") == (14 * 3600, 15 * 3600)
    assert time_range("no times here") is None


def test_neaten_makes_labelled_paragraphs_into_bullets_and_is_idempotent():
    t = "Lead line.\n\n**Why:** a\n\n**Where:** b\n\nPlain closing."
    n = neaten(t)
    assert n == "Lead line.\n\n- **Why:** a\n- **Where:** b\n\nPlain closing."
    assert neaten(n) == n


def test_slot_questions_tasks_and_crew_answers_are_structured_and_change_nothing(live):
    w, plan = live
    before = sandbox_fingerprint()
    slot = answer("is there a free gap on Kurla to Sion tomorrow between 14:00 and 15:00? can my PWI dept work there? what should the buffer be?",
                  w, plan, 9 * 3600)
    crew = answer("how long would a 3 hour tamping job take with 10 workers?", w, plan, 9 * 3600)
    cost = answer("how much will an OHE insulator replacement cost?", w, plan, 9 * 3600)
    tasks = answer("show the jobs for tuesday", w, plan, 9 * 3600)
    plain = answer("what if a 60 minute PWI job at Dadar to Matunga?", w, plan, 9 * 3600)
    assert sandbox_fingerprint() == before
    assert slot.intent == "slot" and slot.visual["type"] == "daystrip" and "Who can use it?" in slot.text and "Dynamic buffer" in slot.text
    assert slot.text.count("- **") >= 5
    assert crew.intent == "crew" and "**180 min** →" in crew.text and crew.visual["type"] == "crew" and crew.visuals[0]["type"] == "bars"
    assert cost.intent == "resources" and "₹" in cost.text and "**Cost:**" in cost.text
    assert tasks.intent == "tasks" and tasks.visual["type"] == "tasks" and tasks.visual["rows"]
    assert "\n- **" in plain.text                                      # the older plan-a-block answer is bulleted too


def test_the_dynamic_buffer_reaches_its_target_on_the_simulation(live):
    from backend.api import state as st
    from backend.chat.ops import _dynamic_buffer
    from backend.chat import whatif as W
    w, _ = live
    win = next(x for x in w.windows if x.raw_min >= 60 and x.zone_kind.value == "SECTION")
    tt = W._default_type(None, [], None)
    b = _dynamic_buffer(w, st, win, tt, win.start_s, 20)
    if b["spare_min"] is not None:
        assert dict(b["curve"])[b["spare_min"]] >= b["target"]
        assert all(p < b["target"] for sp, p in b["curve"] if sp < b["spare_min"])      # the smallest spare that works


def test_the_plan_summary_question_answers_instead_of_crashing(live):
    w, plan = live
    a = answer("how many blocks are planned this week?", w, plan, 9 * 3600)
    assert a.intent == "plan" and "jobs" in a.text
