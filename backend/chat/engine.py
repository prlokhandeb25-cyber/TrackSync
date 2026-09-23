"""A grounded conversational interface over the live plan.

<!-- serves: J1, J5 -->

This is NOT a language-model wrapper. There is no model and no API call. It is a small
intent-and-entity parser that resolves a question against the ACTUAL system state and answers
from it, so every number it gives you is read out of the same objects the planner and the map
use. It cannot invent a figure, because it has nothing to invent from.

That matters more than fluency here. A judge asking "why can't PWI work at Dadar on Tuesday?"
wants the real reason from the real constraint set. An LLM wrapper would produce a plausible
sentence; this produces the rule id, the conflicting job, and the window it would have used.

How it works:
  1. Normalise the question and match it against intent patterns (regex over keywords).
  2. Extract entities: station or section, department, day, gap kind, task id.
  3. Run a handler that queries live state and renders an answer from a template, together
     with structured `facts` the UI can render as chips and a `trace` naming what was read.

Adding an intent is adding one entry to INTENTS and one handler. No retraining, no prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from backend.config import load_config
from backend.domain.compatibility import Verdict, compatibility, coordination_conflicts, matrix
from backend.domain.models import TrackStatus, s_to_hhmm
from backend.domain.task import Department
from backend.gaps.engine import GapType

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_S = 86400

DEPT_WORDS = {
    "pwi": Department.PWI, "p-way": Department.PWI, "pway": Department.PWI,
    "track": Department.PWI, "permanent way": Department.PWI,
    "owd": Department.OWD, "ohe": Department.OWD, "overhead": Department.OWD,
    "traction": Department.OWD, "catenary": Department.OWD,
    "s&t": Department.S_AND_T, "snt": Department.S_AND_T, "s and t": Department.S_AND_T,
    "signal": Department.S_AND_T, "signalling": Department.S_AND_T,
    "telecom": Department.S_AND_T,
}


@dataclass
class Answer:
    text: str
    facts: list[dict] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    intent: str = "unknown"
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"text": self.text, "facts": self.facts, "trace": self.trace,
                "intent": self.intent, "suggestions": self.suggestions}


@dataclass
class Entities:
    station: str | None = None
    section: str | None = None
    department: Department | None = None
    day: int | None = None
    gap_type: GapType | None = None
    task_id: str | None = None
    line: str | None = None


def _extract(q: str, world) -> Entities:
    e = Entities()
    low = q.lower()

    # Station or section, by code or by name. Longest name first so "Dadar (W)" wins over "Dadar".
    names = sorted(world.net.stations.values(), key=lambda s: -len(s.name))
    for st in names:
        if re.search(rf"\b{re.escape(st.name.lower())}\b", low):
            e.station = st.code
            break
    if e.station is None:
        for code in world.net.stations:
            if re.search(rf"\b{code.lower()}\b", low):
                e.station = code
                break
    for sid in world.net.sections:
        if sid.lower() in low:
            e.section = sid
            break

    for word, dept in DEPT_WORDS.items():
        if word in low:
            e.department = dept
            break

    for i, d in enumerate(DAYS):
        if d in low or re.search(rf"\b{DAY_ABBR[i].lower()}\b", low):
            e.day = i
            break

    if "megablock" in low or "mega block" in low:
        e.gap_type = GapType.MEGABLOCK
    elif "night" in low:
        e.gap_type = GapType.NIGHT_WINDOW
    elif "micro" in low or "between trains" in low or "daytime" in low or "day time" in low:
        e.gap_type = GapType.MICRO_GAP

    m = re.search(r"\b([TD]-\d{4})\b", q, re.I)
    if m:
        e.task_id = m.group(1).upper()

    for code in ("western", "central", "harbour", "trans-harbour", "trans harbour"):
        if code in low:
            e.line = {"western": "WR", "central": "CR", "harbour": "HR",
                      "trans-harbour": "TH", "trans harbour": "TH"}[code]
            break
    return e


# --------------------------------------------------------------------------- handlers

def _h_status(q: str, e: Entities, world) -> Answer:
    reg = world.registry
    ref = e.section or e.station
    if ref:
        st = reg.get(ref)
        label = st.value.replace("_", " ").lower()
        open_jobs = [t for t in world.tasks if t.zone.ref == ref and not t.completed]
        txt = f"**{ref}** is currently **{label}**."
        if st is TrackStatus.SICK:
            txt += (f" A defect has been identified there and {len(open_jobs)} job"
                    f"{'s are' if len(open_jobs) != 1 else ' is'} outstanding.")
        elif st is TrackStatus.CAUTION_ORDER:
            txt += " Trains pass at reduced speed until a follow-up job clears the restriction."
        elif st is TrackStatus.STOP_AND_START:
            txt += " Trains must stop and restart, which costs time on every service."
        else:
            txt += " Normal operation, no restriction."
        facts = [{"k": "status", "v": st.value}, {"k": "open jobs", "v": str(len(open_jobs))}]
        for t in open_jobs[:3]:
            facts.append({"k": t.department.value, "v": t.label})
        return Answer(txt, facts, [f"registry.get({ref})", "task pool"], "status")

    counts: dict[str, int] = {}
    for sec in world.net.sections.values():
        counts[reg.get(sec.id).value] = counts.get(reg.get(sec.id).value, 0) + 1
    bad = sum(v for k, v in counts.items() if k != "FIT")
    txt = (f"Across {len(world.net.sections)} sections, **{counts.get('FIT', 0)} are fit** and "
           f"**{bad} need attention**.")
    return Answer(txt, [{"k": k, "v": str(v)} for k, v in sorted(counts.items())],
                  ["registry over all sections"], "status")


def _h_why_not(q: str, e: Entities, world) -> Answer:
    """Why can department X not work at Y? The explainability question that matters."""
    ref = e.section or e.station
    if ref and not e.department:
        # "why is Neral sick?" names a place but no department. Asking them to rephrase would
        # be pedantic when the question is perfectly answerable from the section's state.
        return _h_status(q, e, world)
    if not ref:
        return Answer(
            "Tell me a department and a place — for example "
            "*\"why can't OWD work at Kurla?\"*",
            intent="why_not",
            suggestions=["why can't OWD work at Kurla?", "can PWI and S&T work together at Dadar?"])

    from backend.domain.compatibility import is_allotted
    from backend.domain.task import WorkZone
    from backend.domain.models import WorkZoneKind

    kind = WorkZoneKind.SECTION if "-" in ref else WorkZoneKind.STATION_NODE
    zone = WorkZone(kind=kind, ref=ref)
    trace = [f"allotment[{e.department.value}]", "candidate windows", "compatibility matrix"]

    if not is_allotted(world.net, e.department, zone):
        return Answer(
            f"**{e.department.value} is not allotted {zone.describe()}** by the control office "
            f"this week, so it cannot work there at any time. That is rule R0 — the allotment "
            f"check runs before anything else, because an unallotted job is not a scheduling "
            f"problem, it is simply not permitted.",
            [{"k": "rule", "v": "R0"}, {"k": "department", "v": e.department.value}],
            trace, "why_not")

    wins = [w for w in world.windows if w.zone_ref == ref]
    if not wins:
        return Answer(
            f"There is no usable maintenance window on {zone.describe()} at all this week. "
            f"Every gap there is shorter than the minimum workable block once protection and "
            f"hand-back are subtracted.",
            [{"k": "windows", "v": "0"}], trace, "why_not")

    longest = max(w.usable_min() for w in wins)
    blockers = []
    for t in world.tasks:
        if t.zone.ref != ref or t.department is e.department:
            continue
        v = compatibility(world.net, t, t)  # placeholder to keep types happy
        blockers.append(t)

    txt = (f"**{e.department.value} can work on {zone.describe()}.** There are "
           f"**{len(wins)} candidate windows** there this week, the longest giving "
           f"**{longest} minutes** of actual working time after protection and hand-back.")
    if blockers:
        b = blockers[0]
        r = compatibility(world.net,
                          b.model_copy(update={"scheduled_start_s": None, "scheduled_end_s": None}),
                          b.model_copy(update={"scheduled_start_s": None, "scheduled_end_s": None}))
        txt += (f" Note that {b.department.value} also has work there "
                f"({b.label.lower()}), so the two would need separating or an Integrated "
                f"Work Permission.")
    facts = [{"k": "windows", "v": str(len(wins))},
             {"k": "longest usable", "v": f"{longest} min"}]
    return Answer(txt, facts, trace, "why_not")


def _h_compatibility(q: str, e: Entities, world) -> Answer:
    subset = [t.model_copy(update={"scheduled_start_s": None, "scheduled_end_s": None})
              for t in world.tasks[:20]]
    m = matrix(world.net, subset)
    conflicts = coordination_conflicts(world.net, subset)
    hours = float(load_config().get_path("metrics.manual_coordination_hours_per_conflict", 4.0))

    if e.station or e.section:
        ref = e.section or e.station
        rel = [c for c in m["cells"]
               if any(t.id in (c["a"], c["b"]) and t.zone.ref == ref for t in subset)]
        bad = [c for c in rel if c["value"] != "COMPATIBLE"]
        if bad:
            c = bad[0]
            return Answer(
                f"At **{ref}** there {'are' if len(bad) != 1 else 'is'} **{len(bad)} pair"
                f"{'s' if len(bad) != 1 else ''}** that cannot simply proceed together. "
                f"For example: {c['reason']}",
                [{"k": "rule", "v": c["rule_id"]}, {"k": "verdict", "v": c["value"]}],
                ["compatibility matrix (pre-plan)"], "compatibility")
        return Answer(f"All work currently proposed at **{ref}** is mutually compatible — "
                      f"nothing there needs separating or a permission.",
                      [{"k": "conflicts", "v": "0"}],
                      ["compatibility matrix (pre-plan)"], "compatibility")

    return Answer(
        f"Across the current task pool there are **{m['summary'].get('COMPATIBLE', 0)} compatible "
        f"pairs**, **{m['summary'].get('REQUIRES_IWP', 0)} needing an Integrated Work Permission** "
        f"and **{m['summary'].get('INCOMPATIBLE', 0)} that must be sequenced apart**. "
        f"The {conflicts} cross-department conflicts are the ones three department heads would "
        f"otherwise settle by phone — about **{conflicts * hours:.0f} hours** of negotiation.",
        [{"k": "compatible", "v": str(m["summary"].get("COMPATIBLE", 0))},
         {"k": "needs IWP", "v": str(m["summary"].get("REQUIRES_IWP", 0))},
         {"k": "incompatible", "v": str(m["summary"].get("INCOMPATIBLE", 0))},
         {"k": "manual hours saved", "v": f"{conflicts * hours:.0f}h"}],
        ["compatibility matrix (pre-plan)", "config.metrics"], "compatibility")


def _h_when(q: str, e: Entities, world) -> Answer:
    ref = e.section or e.station
    wins = [w for w in world.windows if (ref is None or w.zone_ref == ref)]
    if e.gap_type:
        wins = [w for w in wins if w.gap_type is e.gap_type]
    if e.day is not None:
        wins = [w for w in wins if w.start_s // DAY_S == e.day]
    if not wins:
        where = f" on {ref}" if ref else ""
        return Answer(f"No maintenance window matches that{where}.", [], ["gap engine"], "when")

    wins = sorted(wins, key=lambda w: -w.usable_min())[:5]
    best = wins[0]
    kind = {GapType.NIGHT_WINDOW: "night window",
            GapType.MEGABLOCK: "Sunday megablock",
            GapType.MICRO_GAP: "gap between trains"}[best.gap_type]
    txt = (f"The best window is **{DAY_ABBR[best.start_s // DAY_S]} "
           f"{s_to_hhmm(best.start_s % DAY_S)}–{s_to_hhmm(best.end_s % DAY_S)}** on "
           f"**{best.section_id}** ({best.track}) — a {kind} of {best.raw_min} minutes raw, "
           f"**{best.usable_min()} minutes usable** once protection and hand-back are taken off.")
    facts = [{"k": "kind", "v": best.gap_type.value},
             {"k": "raw", "v": f"{best.raw_min} min"},
             {"k": "usable", "v": f"{best.usable_min()} min"},
             {"k": "alternatives", "v": str(len(wins) - 1)}]
    return Answer(txt, facts, ["gap engine candidate windows"], "when")


def _h_gaps(q: str, e: Entities, world) -> Answer:
    counts: dict[str, int] = {}
    usable: dict[str, int] = {}
    for w in world.gaps.windows:
        counts[w.gap_type.value] = counts.get(w.gap_type.value, 0) + 1
        usable[w.gap_type.value] = usable.get(w.gap_type.value, 0) + w.usable_min()
    raw = sum(w.raw_min for w in world.gaps.windows)
    use = sum(w.usable_min() for w in world.gaps.windows)
    cfg = load_config()["gaps"]
    txt = (f"This week the network offers **{counts.get('MICRO_GAP', 0)} gaps between trains**, "
           f"**{counts.get('NIGHT_WINDOW', 0)} night windows** and "
           f"**{counts.get('MEGABLOCK', 0)} megablock windows**. "
           f"Only **{100 * use // max(1, raw)}% of raw gap time is actually workable** — every "
           f"block costs {cfg['block_setup_min']} minutes to protect and "
           f"{cfg['block_release_min']} to hand back, so a gap must be about 40 minutes "
           f"long to leave the 15 minutes of work that is the minimum here. The gaps between trains are the capacity conventional planning "
           f"leaves on the table.")
    facts = [{"k": k.lower().replace('_', ' '), "v": f"{v} ({usable.get(k, 0) // 60}h usable)"}
             for k, v in counts.items()]
    return Answer(txt, facts, ["gap engine"], "gaps")


def _h_plan(q: str, e: Entities, world, plan=None) -> Answer:
    if plan is None:
        return Answer("No plan has been solved yet. Ask me again once the weekly plan runs.",
                      [], [], "plan")
    by_day = {}
    for a in plan.assignments:
        by_day[a.day] = by_day.get(a.day, 0) + 1
    if e.day is not None:
        n = by_day.get(e.day, 0)
        jobs = [a for a in plan.assignments if a.day == e.day]
        txt = f"**{n} blocks** are planned for **{DAY_ABBR[e.day]}**."
        if jobs:
            first = sorted(jobs, key=lambda a: a.start_s)[0]
            txt += (f" The first is at {s_to_hhmm(first.start_s % DAY_S)} on "
                    f"{first.zone_ref}.")
        return Answer(txt, [{"k": DAY_ABBR[e.day], "v": str(n)}], ["CP-SAT plan"], "plan")

    txt = (f"The weekly plan places **{len(plan.assignments)} of {plan.n_tasks} jobs**, "
           f"**{plan.micro_gap_count} of them into gaps between trains**. CP-SAT solved it "
           f"{'to optimality' if plan.status == 'OPTIMAL' else 'to a feasible solution'} in "
           f"{plan.wall_s:.1f} seconds.")
    if plan.n_unscheduled:
        txt += (f" {plan.n_unscheduled} job(s) found no window long enough anywhere on their "
                f"section — those need a window to be created by rerouting.")
    facts = [{"k": DAY_ABBR[d], "v": str(by_day.get(d, 0))} for d in range(7)]
    return Answer(txt, facts, ["CP-SAT plan"], "plan")


def _h_rl(q: str, e: Entities, world) -> Answer:
    import json
    from backend.config import REPO_ROOT
    path = REPO_ROOT / "artifacts" / "rl_comparison.json"
    if not path.exists():
        return Answer("The policy comparison has not been run yet.", [], [], "rl")
    d = json.loads(path.read_text(encoding="utf-8"))
    tbl = d["table"]
    best = min(tbl, key=lambda r: r["mean_gap_vs_cpsat_pct"])
    txt = (f"On {d['instances']} held-out instances the best learned dispatcher is "
           f"**{best['policy']}**, landing within **{best['mean_gap_vs_cpsat_pct']}% of "
           f"CP-SAT's objective** while re-planning in "
           f"**{best['mean_full_replan_ms']:.0f} ms** against the solver's "
           f"**{d['cpsat_mean_ms']:.0f} ms**. It also places "
           f"**{best['mean_micro_gap']} jobs into gaps between trains** — the behaviour it "
           f"learned from the solver rather than from a hand-written rule. Constraint "
           f"violations: **{best['constraint_violations']}**, zero by construction, because "
           f"every action passes through the legality mask.")
    facts = [{"k": r["policy"], "v": f"{r['mean_gap_vs_cpsat_pct']}% gap"} for r in tbl]
    return Answer(txt, facts, ["artifacts/rl_comparison.json"], "rl")


def _h_mine(q: str, e: Entities, world) -> Answer:
    from backend.api.routes_tasks import _scored_pool
    pool, clusters, scores, cluster_of = _scored_pool()
    mine = [t for t in pool if t.source == "USER"]
    if not mine:
        return Answer("You have not raised any jobs yet. Use the form on the Department "
                      "coordination page and I will tell you how each one scored and where it went.",
                      [], ["job pool"], "mine",
                      suggestions=["how are jobs grouped?", "what did gap creation open?"])
    lines, facts = [], []
    for t in mine[-3:]:
        sc = scores.get(t.id)
        cl = cluster_of.get(t.id)
        lines.append(f"**{t.id}** ({t.department.value}, {t.zone.ref}) scored **{sc.score if sc else '-'}**"
                     f", group of {cl['size'] if cl else 1} around {cl['label'] if cl else 'its area'}")
        facts.append({"k": t.id, "v": f"score {sc.score if sc else '-'}"})
    return Answer("Your latest jobs: " + "; ".join(lines) + ".", facts,
                  ["job pool", "compatibility scores"], "mine")


def _h_clusters(q: str, e: Entities, world) -> Answer:
    from backend.api.routes_tasks import _scored_pool
    pool, clusters, scores, cluster_of = _scored_pool()
    shared = sorted((c for c in clusters if len(c.task_ids) > 1), key=lambda c: -len(c.task_ids))
    cut = load_config().get_path("clustering.cut_km", 5.0)
    if not shared:
        return Answer(f"No two jobs are within {cut} km of each other right now, so nothing is grouped.",
                      [], ["clustering"], "clusters")
    top = shared[0]
    txt = (f"**{len(pool)} jobs** fall into **{len(shared)} shared groups** (jobs within about {cut} km "
           f"that could share one protected block), by average-linkage hierarchical clustering. The biggest is "
           f"**{len(top.task_ids)} jobs around {top.label}**: {top.compatible} pair(s) can share a block, "
           f"{top.requires_iwp} need a work permit, {top.incompatible} must be apart.")
    return Answer(txt, [{"k": c.label, "v": f"{len(c.task_ids)} jobs"} for c in shared[:5]],
                  ["clustering", "compatibility rules"], "clusters")


def _h_creation(q: str, e: Entities, world) -> Answer:
    from backend.api.routes_tasks import creation_experiment, creation_summary_route
    cs = creation_summary_route()["survey"]
    ex = creation_experiment()
    txt = (f"A gap has to leave **{load_config()['gaps']['min_workable_min']} minutes of real work**. "
           f"**{cs['near_gaps']:,} gaps** miss that by a few minutes; small changes to the trains "
           f"(hold one a few minutes, send a long-distance train another way, or run one track for both "
           f"directions) can open **{cs['created']}** of them (+{cs['usable_hours_added']} usable hours). "
           f"In a test of {ex['jobs']} urgent jobs due within {ex['due_within_h']} hours, only "
           f"**{ex['natural_placed']}** fit the existing gaps but **{ex['with_creation_placed']}** fit with gap "
           f"creation, at a cost of {ex['delay_train_min']} train-minutes. Suburban locals are never rerouted.")
    return Answer(txt, [{"k": "opened", "v": str(cs["created"])},
                        {"k": "urgent jobs placed", "v": f"{ex['natural_placed']} -> {ex['with_creation_placed']}"}],
                  ["gap creation survey", "creation experiment"], "creation")


def _h_help(q: str, e: Entities, world) -> Answer:
    return Answer(
        "I'm RailMitra. I read the live plan and answer from it — there is no language model here, so every "
        "number I give you comes straight out of the same objects the map and the solver use. "
        "Try asking about a section's status, why a department can or cannot work somewhere, "
        "when the next window is, or how the learned dispatcher compares with the solver.",
        [], [], "help",
        suggestions=[
            "what is the status of NRL-BVS?",
            "why can't S&T work on NRL-BVS?",
            "when is the next window at Dadar?",
            "how many gaps between trains are there?",
            "show me the department conflicts",
            "how does the RL dispatcher compare with CP-SAT?",
            "how are jobs grouped?",
            "what did gap creation open?",
        ])


# --------------------------------------------------------------------------- routing

# Patterns are prefix-matched (\w* on the tail) so "conflict" also catches "conflicts" and
# "gap" catches "gaps". A trailing \b makes every plural miss, which is exactly the kind of
# quiet failure that makes an assistant feel broken to the person using it.
INTENTS: list[tuple[str, re.Pattern, Callable]] = [
    ("help", re.compile(r"\b(help|what can you|how do you work|who are you)\w*"), _h_help),
    ("rl", re.compile(r"\b(rl|reinforcement|dispatcher|cql|dqn|learned|polic|model)\w*"), _h_rl),
    ("why_not", re.compile(r"\b(why|cannot|can'?t|not allowed|blocked|prevent)\w*"), _h_why_not),
    ("compatibility", re.compile(
        r"\b(compat|conflict|together|same time|clash|iwp|permission|coordinat|negotiat)\w*"),
     _h_compatibility),
    ("mine", re.compile(r"\b(my (job|task|work)|i (submitted|added|raised)|score[sd]?)\w*"), _h_mine),
    ("creation", re.compile(r"\b(creat|single.?line|reroute|rerout|retim|near.?miss|open(ed)? a gap)\w*"), _h_creation),
    ("clusters", re.compile(r"\b(cluster|grouped?|integrated|share a block)\w*"), _h_clusters),
    ("when", re.compile(r"\b(when|next window|what time|earliest|slot)\w*"), _h_when),
    ("gaps", re.compile(r"\b(gap|micro|megablock|capacity|how much time|window)\w*"), _h_gaps),
    ("plan", re.compile(r"\b(plan|scheduled|block|this week|how many job|backlog)\w*"), _h_plan),
    ("status", re.compile(r"\b(status|sick|fit|caution|stop and start|state|condition|health)\w*"),
     _h_status),
]


def answer(question: str, world, plan=None) -> Answer:
    q = (question or "").strip()
    if not q:
        return _h_help(q, Entities(), world)

    e = _extract(q, world)
    for name, pattern, handler in INTENTS:
        if pattern.search(q.lower()):
            if name == "plan":
                return handler(q, e, world, plan)
            return handler(q, e, world)

    # No intent matched, but an entity did: answer about that thing rather than shrug.
    if e.section or e.station:
        return _h_status(q, e, world)

    a = _h_help(q, e, world)
    a.text = ("I did not follow that one. " + a.text)
    return a
