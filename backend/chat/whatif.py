"""RailMitra's live analysis: questions and hypotheticals answered by running the real machinery.

<!-- serves: J1, J5 -->

There is no language model here. A question is parsed into slots (where, which department, how long,
how urgent, when) and then the SAME objects the planner uses are asked:

    what if a 60-minute PWI job at Dadar-Matunga on Tuesday night?   -> the gap engine's windows, the
                                                                       rule engine's verdicts, the
                                                                       passenger model, gap creation
    what if Dadar-Matunga is closed at 14:00 for an hour?            -> the occupancy, the reroute search
    can OHE insulator work and tamping share Kurla?                  -> pair_verdict, with its reason
    who is working on Kurla at 15:00?                                -> every booked job, whatever its origin
    how busy is Thane at 9am?                                        -> the passenger model

Hypotheticals run on COPIES of the schedule, so asking "what if" never changes the plan.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from backend.chat.engine import DAY_ABBR, DAYS, DEPT_WORDS, DAY_S, Answer
from backend.config import load_config
from backend.domain.compatibility import Verdict, check_allotment
from backend.domain.models import WorkZoneKind, s_to_hhmm
from backend.domain.scoring import pair_verdict
from backend.domain.task import (
    TASK_TYPES, Department, Task, TaskCategory, TaskType, WorkZone,
)
from backend.gaps.engine import GapType
from backend.planner.live_sim import LiveSimState, _overheads, rank_windows

# What the assistant remembers between turns, so "and at night?" works.
_CTX: dict = {}

HYPO = re.compile(r"\b(what if|what happens|suppose|assume|imagine|if (we|i|they|a|an|the)|how would|"
                  r"where would|when would|could we|can we|can i|should we|would it)\b")
BEST = re.compile(r"\b(best|earliest|quietest|least busy|fewest|least passengers|lowest|cheapest|"
                  r"when (should|can|could|is a good)|good time|find (me )?a|fit a|slot for|schedule a|"
                  r"add a|raise a|place a)\b")
CLOSE = re.compile(r"\b(clos(e|ed|ure)|block(ed|ade)?|shut|out of service|breakdown|broken down|derail\w*|"
                   r"flood\w*|collaps\w*|fail(s|ed|ure)?|under (block|maintenance))\b")
TOGETHER = re.compile(r"\b(together|simultaneous\w*|same time|alongside|at once|side by side|both|"
                      r"share (a|the) (block|zone|section|place)|concurrent\w*|in parallel)\b")


# ------------------------------------------------------------------------------ slot extraction


@dataclass
class Slots:
    zone: WorkZone | None = None
    zones: list[WorkZone] = field(default_factory=list)
    depts: list[Department] = field(default_factory=list)
    types: list[TaskType] = field(default_factory=list)
    duration_min: int | None = None
    priority: int | None = None
    day: int | None = None
    tod_s: int | None = None
    gap_kind: GapType | None = None
    task_id: str | None = None
    note: str = ""            # something the user said that we could not resolve

    @property
    def explicit_time(self) -> bool:
        return self.tod_s is not None


_ALIAS = {
    "Mumbai CSMT": ["csmt", "cst", "victoria terminus"], "Mumbai Central": ["bombay central"],
    "Belapur CBD": ["belapur", "cbd belapur"], "Vasai Road": ["vasai"], "Bhivpuri Road": ["bhivpuri"],
    "Seawoods-Darave": ["seawoods"], "Dadar (W)": ["dadar western", "dadar west"],
    "Ghatkopar": ["ghatkopar"], "Koparkhairane": ["kopar khairane"], "Lower Parel": ["parel"],
    "Prabhadevi": ["elphinstone", "elphinstone road"], "Mansarovar": ["mansarover"],
}


def _names_of(st) -> list[str]:
    base = st.name.lower()
    out = [base] + [a.lower() for a in _ALIAS.get(st.name, [])]
    if base.endswith(" jn"):
        out.append(base[:-3])
    return out


def _find(name: str, low: str):
    return re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", low)


def _stations_in(q: str, world) -> list[str]:
    low = q.lower()
    cands = sorted(((n, st.code) for st in world.net.stations.values() for n in _names_of(st)),
                   key=lambda x: -len(x[0]))
    hits: list[tuple[int, int, str]] = []
    for name, code in cands:
        m = _find(name, low)
        if m and not any(a < m.end() and m.start() < b for a, b, _ in hits):
            hits.append((m.start(), m.end(), code))
    for code in world.net.stations:
        m = _find(code.lower(), low)
        if m and len(code) >= 3 and not any(a < m.end() and m.start() < b for a, b, _ in hits):
            hits.append((m.start(), m.end(), code))
    return [c for _, _, c in sorted(hits)]


_NOT_PLACES = {"what", "which", "who", "when", "where", "why", "how", "suppose", "assume", "imagine", "can",
               "could", "should", "would", "show", "best", "find", "tell", "and", "the", "monday", "tuesday",
               "wednesday", "thursday", "friday", "saturday", "sunday", "tomorrow", "today", "tonight", "now",
               "railmitra", "pwi", "owd", "ohe", "s&t", "iwp", "cp", "sat", "rl", "there", "then", "please",
               "help", "hello", "thanks", "hi", "any", "are", "is", "if"}


def _unknown_places(q: str, world) -> list[str]:
    """Capitalised words that look like a place but match no station: say so rather than guess."""
    known = {w for st in world.net.stations.values() for n in _names_of(st) for w in re.findall(r"[a-z]+", n)}
    out = []
    for m in re.finditer(r"(?<![.?!]\s)(?<!^)\b([A-Z][a-z]{3,})\b", q):
        w = m.group(1).lower()
        if w not in known and w not in _NOT_PLACES and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _section_between(world, a: str, b: str) -> str | None:
    for sid, sec in world.net.sections.items():
        if {sec.from_station, sec.to_station} == {a, b}:
            return sid
    return None


def _zones_in(q: str, world) -> tuple[list[WorkZone], str]:
    """Places named in the question, in order. Two adjacent stations mean the section between them."""
    net = world.net
    low = q.lower()
    zones: list[WorkZone] = []
    note = ""
    for sid in net.sections:
        if re.search(rf"\b{re.escape(sid.lower())}\b", low):
            zones.append(WorkZone(kind=WorkZoneKind.SECTION, ref=sid))
    if zones:
        return zones, note
    codes = _stations_in(q, world)
    # pair up consecutive stations that share a section ("Dadar to Matunga", "between Kurla and Sion")
    i = 0
    while i < len(codes):
        if i + 1 < len(codes):
            sid = _section_between(world, codes[i], codes[i + 1])
            if sid:
                zones.append(WorkZone(kind=WorkZoneKind.SECTION, ref=sid))
                i += 2
                continue
        zones.append(WorkZone(kind=WorkZoneKind.STATION_NODE, ref=codes[i]))
        i += 1
    if len(codes) == 2 and len(zones) == 2 and all(z.kind is WorkZoneKind.STATION_NODE for z in zones):
        note = (f"{net.stations[codes[0]].name} and {net.stations[codes[1]].name} are not next to each other, "
                "so I treated them as two separate places.")
    return zones, note


def _duration(low: str) -> int | None:
    if re.search(r"\bhalf an? hour\b", low):
        return 30
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(hours?|hrs?|h)\b", low)
    if m:
        return int(float(m.group(1)) * 60)
    m = re.search(r"\b(\d+)\s*(minutes?|mins?|m)\b", low)
    if m:
        return int(m.group(1))
    if re.search(r"\ban hour\b", low):
        return 60
    return None


def _priority(low: str) -> int | None:
    m = re.search(r"\bp([1-5])\b", low)
    if m:
        return int(m.group(1))
    if re.search(r"\b(critical|emergency|urgent|life.?safety)\b", low):
        return 1
    if re.search(r"\bhigh( priority)?\b", low):
        return 2
    if re.search(r"\b(medium|normal|moderate)\b", low):
        return 3
    if re.search(r"\b(low( priority)?|routine|minor)\b", low):
        return 5
    return None


def _time_of_day(low: str) -> int | None:
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?\b", low)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if m.group(3) == "pm" and h < 12:
            h += 12
        if m.group(3) == "am" and h == 12:
            h = 0
        if h < 24 and mi < 60:
            return h * 3600 + mi * 60
    m = re.search(r"\b(?:at|around|by|from|after|before)?\s*(\d{1,2})\s*(am|pm)\b", low)
    if m:
        h = int(m.group(1)) % 12 + (12 if m.group(2) == "pm" else 0)
        return h * 3600
    for word, hh in (("midnight", 0), ("noon", 12), ("midday", 12), ("morning", 8), ("afternoon", 14),
                     ("evening", 18), ("rush hour", 9), ("peak", 9)):
        if re.search(rf"\b{word}\b", low):
            return hh * 3600
    return None


def parse(q: str, world, now_s: int) -> Slots:
    low = q.lower()
    s = Slots()
    s.zones, s.note = _zones_in(q, world)
    s.zone = s.zones[0] if s.zones else None
    if s.zone is None:
        unk = _unknown_places(q, world)
        if unk:
            s.note = (f"I don't have **{unk[0]}** on this network (it covers the Central, Western, Harbour and "
                      f"Trans-Harbour lines, 73 stations, e.g. Thane, Kurla, Dadar, Neral).")
    seen = []
    for word, dept in sorted(DEPT_WORDS.items(), key=lambda kv: low.find(kv[0]) if kv[0] in low else 10**6):
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", low) and dept not in seen:
            seen.append(dept)
    s.depts = seen
    # named work types ("tamping", "insulator", "track circuit"): more exact than a department
    for tt in TASK_TYPES:
        words = [w for w in re.findall(r"[a-z]{5,}", tt.label.lower()) if w not in ("attention", "replacement")]
        pos = [low.find(w) for w in words if w in low]
        if pos:
            s.types.append((min(pos), tt))  # type: ignore[arg-type]
    s.types = [tt for _, tt in sorted(s.types, key=lambda x: x[0])]   # type: ignore[misc]
    for tt in s.types:
        if tt.department not in s.depts:
            s.depts.append(tt.department)
    s.duration_min = _duration(low)
    s.priority = _priority(low)
    s.tod_s = _time_of_day(low)
    for i, d in enumerate(DAYS):
        if d in low or re.search(rf"\b{DAY_ABBR[i].lower()}\b", low):
            s.day = i
            break
    if s.day is None:
        if "tonight" in low:
            s.day = ((now_s // DAY_S) + 1) % 7            # the small hours that follow this evening
            if s.tod_s is None:
                s.tod_s = 1 * 3600 + 1800
        elif "tomorrow" in low:
            s.day = ((now_s // DAY_S) + 1) % 7
        elif re.search(r"\b(today|now)\b", low):
            s.day = (now_s // DAY_S) % 7
    if re.search(r"\b(at night|night window|overnight)\b", low):
        s.gap_kind = GapType.NIGHT_WINDOW
    elif re.search(r"\b(megablock|mega block|sunday block)\b", low):
        s.gap_kind = GapType.MEGABLOCK
    elif re.search(r"\b(between trains|daytime|day time|micro)\b", low):
        s.gap_kind = GapType.MICRO_GAP
    m = re.search(r"\b((?:SUD|SIM)-\d{3,5}|[TDU]-\d{3,5})\b", q, re.I)
    if m:
        s.task_id = m.group(1).upper()
    return s


def _remember(s: Slots) -> None:
    for key in ("zone", "duration_min", "priority"):
        if getattr(s, key):
            _CTX[key] = getattr(s, key)
    if s.depts:
        _CTX["depts"] = s.depts


def _fill_from_context(s: Slots, q: str) -> bool:
    """A follow-up ("and at night?", "what about P1?") inherits what the last question named."""
    low = q.lower().strip()
    follow = low.startswith(("and ", "what about", "how about", "same ", "now ", "instead", "but ", "then "))
    short_tweak = len(low.split()) <= 7 and bool(s.priority or s.gap_kind or s.tod_s is not None or s.duration_min)
    if not (follow or short_tweak):
        return False
    used = False
    if s.zone is None and _CTX.get("zone"):
        s.zone, used = _CTX["zone"], True
        s.zones = [s.zone]
    if not s.depts and _CTX.get("depts"):
        s.depts, used = list(_CTX["depts"]), True
    if s.duration_min is None and _CTX.get("duration_min"):
        s.duration_min, used = _CTX["duration_min"], True
    if s.priority is None and _CTX.get("priority"):
        s.priority, used = _CTX["priority"], True
    return used


# --------------------------------------------------------------------------- live state access


def _live():
    from backend.api import state as st
    return st


def _now_label(t: int) -> str:
    return f"{DAY_ABBR[(t // DAY_S) % 7]} {s_to_hhmm(t % DAY_S)}"


def booked_tasks(world) -> list[Task]:
    """Everything with a slot right now: planned, raised by a user, simulated, or sudden."""
    st = _live()
    out = [t for t in world.tasks if t.scheduled_start_s is not None]
    seen = {t.id for t in out}
    for p in list(st.STATE.live_sim.placed) + list(st.STATE.sudden_state.placed):
        if p.placed and p.task.id not in seen and p.task.scheduled_start_s is not None:
            out.append(p.task)
            seen.add(p.task.id)
    return out


def _copies(tasks: list[Task]) -> list[Task]:
    return [t.model_copy(deep=True) for t in tasks]


def _default_type(dept: Department | None, types: list[TaskType], zone: WorkZone | None) -> TaskType:
    if types:
        return types[0]
    dept = dept or Department.PWI
    pool = [t for t in TASK_TYPES if t.department is dept]
    return pool[min(3, len(pool) - 1)] if pool else TASK_TYPES[0]


def _probe(world, s: Slots, tid: str, tt: TaskType, start_from: int, priority: int | None = None) -> Task:
    from backend.planner.sudden import due_hours
    pr = priority or s.priority or 3
    dur = s.duration_min or max(tt.min_duration_min, min(60, tt.max_duration_min))
    return Task(
        id=tid, task_type=tt.code, department=tt.department, zone=s.zone, duration_min=max(10, min(360, dur)),
        priority=pr, category=TaskCategory.DEMAND, requires_power_block=tt.requires_power_block,
        requires_traffic_block=tt.requires_traffic_block, released_s=start_from,
        due_by_s=start_from + due_hours(pr) * 3600, source="WHATIF",
    )


def _lc(t: str) -> str:
    first = t.split(" ")[0]
    return t if ("_" in first or first.isupper()) else t[:1].lower() + t[1:]


def _need(msg: str, hint: str) -> Answer:
    return Answer(msg, [], [], "whatif", suggestions=[hint])


def _where(world, w) -> str:
    if w.zone_kind is WorkZoneKind.STATION_NODE:
        return f"{world.net.stations[w.zone_ref].name} station"
    return f"{w.section_id} ({w.track})"


def _dedupe(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        w = r["window"]
        key = (r["start"], w.zone_ref, w.gap_type) if w.zone_kind is WorkZoneKind.STATION_NODE \
            else (r["start"], w.section_id, w.track)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _kind_label(g: str) -> str:
    return {"NIGHT_WINDOW": "night window", "MEGABLOCK": "Sunday megablock",
            "MICRO_GAP": "gap between trains"}.get(g, g.lower())


# ----------------------------------------------------------------------------- what-if: add a job


def h_whatif_add(q: str, s: Slots, world, now_s: int) -> Answer:
    st = _live()
    net = world.net
    if s.zone is None:
        return _need((s.note + " " if s.note else "") + "Tell me where — a section like **Dadar to Matunga**, or a "
                     "station — and I'll work out where the job would fit.",
                     "what if a 60 minute PWI job at Dadar to Matunga?")
    dept = s.depts[0] if s.depts else None
    tt = _default_type(dept, s.types, s.zone)
    if dept is not None and tt.department is not dept:
        tt = next((t for t in TASK_TYPES if t.department is dept), tt)
    _remember(s)

    base = now_s
    if s.day is not None:
        base = s.day * DAY_S + (s.tod_s or 0)
        if base + DAY_S < now_s and s.tod_s is None:
            base = now_s
    task = _probe(world, s, "WHATIF-1", tt, now_s if not s.explicit_time else base)
    reject = check_allotment(net, task)
    if reject is not None:
        return Answer(f"**{tt.department.value} is not allotted {s.zone.describe()}** by the control office, so "
                      f"the job could never be booked there, whenever it ran. ({reject.reason})",
                      [{"k": "rule", "v": "R0"}], ["allotment check"], "whatif")

    pax = st.get_pax()
    index = st.ensure_interval_index()
    tasks = _copies(booked_tasks(world))
    setup, release = _overheads(task)
    dur_s = task.duration_min * 60
    facts = [{"k": "job", "v": f"{tt.label}, {task.duration_min} min"},
             {"k": "priority", "v": f"P{task.priority}"}]

    if s.explicit_time:
        return _at_time(q, s, world, task, base, index, pax, tasks, setup, release, dur_s, facts)

    # No time given: where would it go, and what would each choice cost the public?
    from backend.planner.sudden import place_sudden
    creator = st.make_creator()
    res = place_sudden(net, task, index, tasks, LiveSimState(), creator, now_s, pax, lambda b: False)
    windows = [w for w in index.eligible(task) if w.end_s > now_s
               and (s.gap_kind is None or w.gap_type is s.gap_kind)]
    ranked = _dedupe([r for r in rank_windows(net, task, windows, tasks, [], now_s, pax) if r["blocker"] is None])
    top = ranked[:3]

    lines = []
    for r in top:
        w, e = r["window"], r["exposure"]
        end = r["start"] + dur_s
        lines.append(f"**{_now_label(r['start'])}–{s_to_hhmm(end % DAY_S)}** at {_where(world, w)}, "
                     f"{_kind_label(w.gap_type.value)}: {e.trains_per_hour:.0f} trains/hour, about "
                     f"{e.passengers:,} passengers within reach, {round(100 * (1 - w.late_risk))}% reliable start")
    if not top:
        lines = []

    where = s.zone.describe()
    if s.note and not top:
        where += f" ({s.note})"
    if top:
        best = top[0]
        text = (f"A {task.duration_min}-minute {tt.label.lower()} on {where} (priority {task.priority}) "
                f"fits best here — {lines[0]}.")
        if len(lines) > 1:
            text += " Other good options: " + "; ".join(lines[1:]) + "."
        # the same job, same length, at the busiest hour of that day: an equal-terms comparison
        d = best["start"] // DAY_S
        sec_id = best["window"].section_id
        prof = pax.hour_profile(sec_id, d)
        busy = max(prof, key=lambda h: h["passengers"])
        busy_e = pax.exposure(sec_id, d * DAY_S + busy["hour"] * 3600, d * DAY_S + busy["hour"] * 3600 + dur_s)
        if busy_e.passengers > best["exposure"].passengers * 1.5:
            ratio = busy_e.passengers / max(1, best["exposure"].passengers)
            text += (f" The same job at {busy['hour']:02d}:00 would be within reach of {busy_e.trains} trains and about "
                     f"{busy_e.passengers:,} passengers"
                     + (f" — {ratio:.0f}x as many." if ratio < 50 else " — far more."))
        facts += [{"k": "best slot", "v": _now_label(best["start"])},
                  {"k": "trains/hour", "v": f"{best['exposure'].trains_per_hour:.0f}"},
                  {"k": "people within reach", "v": f"{best['exposure'].passengers:,}"},
                  {"k": "options", "v": str(len(ranked))}]
        action = {"label": "Show on map", "section": best["window"].section_id, "start_s": best["start"]}
    else:
        text = (f"No existing gap on {where} is long enough for a {task.duration_min}-minute job before its "
                f"{task.due_by_s and _now_label(task.due_by_s)} deadline.")
        action = None
    if res.method == "created" and res.placement is not None and res.placement.created is not None:
        c = res.placement.created
        text += (f" If it could not wait, I would open a gap by a small change to the trains: {_lc(c.note)}, "
                 f"costing {c.delay_min:.1f} train-minutes and about {c.pax_delay:,} passenger-minutes.")
        facts.append({"k": "gap creation", "v": c.lever.lower().replace("_", " ")})
    elif res.method == "bumped":
        text += (" Nothing free fits in time, so at this priority it would push aside "
                 + ", ".join(f"{m.task.id} (P{m.task.priority})" for m in res.moves) + ".")
    elif res.method == "late" and res.placement is not None:
        text += (f" Nothing meets the deadline; the earliest booking is {_now_label(res.placement.start_s or 0)}, "
                 "which would be late.")
    elif res.method == "none" and not top:
        text += " I could not find any slot in the coming days, even with gap creation."

    a = Answer(text, facts, ["gap engine windows", "rule engine (pair verdicts)", "passenger model",
                             "gap creation", "no schedule was changed"], "whatif",
               suggestions=[f"and at night?", f"what if it is P1?", f"who is working on {s.zone.ref} tomorrow?"])
    a.action = action if top else None
    return a


def _at_time(q, s, world, task, want, index, pax, tasks, setup, release, dur_s, facts) -> Answer:
    """Can this job run at exactly this time? If not, why not, and what is nearest?"""
    from backend.planner.sudden import _all_blockers
    st = _live()
    net = world.net
    lo, hi = want - setup, want + dur_s + release
    covering = [w for w in index.free_in(task.zone.ref, task.zone.kind, lo - 1, hi + 1)
                if w.start_s <= lo and w.end_s >= hi]
    blockers = _all_blockers(net, task, want, tasks)
    pax_e = pax.exposure(task.zone.ref, want, want + dur_s) if task.zone.kind is WorkZoneKind.SECTION else None
    label = f"{_now_label(want)}–{s_to_hhmm((want + dur_s) % DAY_S)}"
    if covering and not blockers:
        w = covering[0]
        text = (f"**Yes.** {label} works on {task.zone.describe()}. It sits inside a {_kind_label(w.gap_type.value)} "
                f"({w.track}, {w.raw_min} min raw, {w.usable_min()} usable), no booked job conflicts under the "
                f"rules, and the start is about {round(100 * (1 - w.late_risk))}% reliable.")
        if pax_e:
            text += (f" It would be within reach of {pax_e.trains} trains (~{pax_e.passengers:,} passengers), "
                     f"{pax_e.trains_per_hour:.0f} trains/hour.")
            facts += [{"k": "trains/hour", "v": f"{pax_e.trains_per_hour:.0f}"},
                      {"k": "people within reach", "v": f"{pax_e.passengers:,}"}]
        facts.append({"k": "verdict", "v": "fits"})
        a = Answer(text, facts, ["gap engine windows", "rule engine (pair verdicts)", "passenger model"], "whatif",
                   suggestions=["and at night?", "what if it is P1?"])
        a.action = {"label": "Show on map", "section": task.zone.ref, "start_s": want}
        return a

    # It does not fit. Say exactly why.
    why = []
    if not covering:
        occ = [o for o in st.occupancy_by_section().get(task.zone.ref, []) if o.enter_s < hi and o.exit_s > lo]
        occ.sort(key=lambda o: o.enter_s)
        if occ:
            first = occ[0]
            why.append(f"trains keep running through then: {len(occ)} movement(s) on the section between "
                       f"{s_to_hhmm((lo) % DAY_S)} and {s_to_hhmm(hi % DAY_S)}, the first at "
                       f"{s_to_hhmm(first.enter_s % DAY_S)} ({first.track})")
        else:
            why.append("no gap of the required length is open on that section then")
        why.append(f"the job needs {setup // 60} min to set up and {release // 60} min to hand back on top of its "
                   f"{task.duration_min} min, so it needs a clear stretch of {(setup + release) // 60 + task.duration_min} min")
    if blockers:
        b = blockers[0]
        r = pair_verdict(net, task.model_copy(update={"scheduled_start_s": want, "scheduled_end_s": want + dur_s}), b)
        why.append(f"it clashes with {b.id} ({b.department.value}, {b.label.lower()}): {r.reason} (rule {r.rule_id})")
    windows = [w for w in index.eligible(task) if abs(w.start_s - want) < 2 * DAY_S]
    near = _dedupe([r for r in rank_windows(net, task, windows, tasks, [], want, pax) if r["blocker"] is None])
    near.sort(key=lambda r: abs(r["start"] - want))
    text = f"**Not at {_now_label(want)}.** " + "; ".join(why[:3]) + "."
    if near:
        n = near[0]
        e = n["exposure"]
        text += (f" The nearest slot that works is **{_now_label(n['start'])}** at {_where(world, n['window'])} "
                 f"({_kind_label(n['window'].gap_type.value)}, {e.trains_per_hour:.0f} trains/hour).")
    creator = st.make_creator()
    opts = creator(task, want)[:1]
    if opts:
        o = opts[0]
        text += (f" Or I could open a gap for it there: {_lc(o.note)} ({o.delay_min:.1f} train-minutes, "
                 f"about {o.pax_delay:,} passenger-minutes).")
        facts.append({"k": "gap creation", "v": o.lever.lower().replace("_", " ")})
    facts.append({"k": "verdict", "v": "does not fit"})
    a = Answer(text, facts, ["gap engine windows", "rule engine (pair verdicts)", "gap creation"], "whatif",
               suggestions=["what is the best time for it?", "what if it is P1?"])
    if near:
        a.action = {"label": "Show nearest slot", "section": near[0]["window"].section_id,
                    "start_s": near[0]["start"]}
    return a


# ------------------------------------------------------------------------- what-if: a closure


def h_whatif_close(q: str, s: Slots, world, now_s: int) -> Answer:
    from backend.planner.active_reroute import plan_block_reroutes
    st = _live()
    net = world.net
    if s.zone is None:
        return _need((s.note + " " if s.note else "") + "Which section? For example **what if Dadar to Matunga is closed at 14:00 for an hour?**",
                     "what if Dadar to Matunga is closed for an hour?")
    _remember(s)
    if s.zone.kind is WorkZoneKind.STATION_NODE:
        secs = [sec for sec in net.sections.values() if s.zone.ref in (sec.from_station, sec.to_station)]
        sec = max(secs, key=lambda x: len(st.occupancy_by_section().get(x.id, []))) if secs else None
        note = f" (I used {sec.id}, the busiest section at {net.stations[s.zone.ref].name})" if sec else ""
    else:
        sec, note = net.sections[s.zone.ref], ""
    if sec is None:
        return _need("I could not find a section there.", "what if Dadar to Matunga is closed for an hour?")
    start = (s.day * DAY_S + (s.tod_s or 0)) if s.day is not None else (
        (now_s // DAY_S) * DAY_S + s.tod_s if s.tod_s is not None else now_s)
    dur = (s.duration_min or 60) * 60
    end = start + dur
    occ = st.occupancy_by_section().get(sec.id, [])
    b = plan_block_reroutes(net, st.week_by_id(), occ, sec, start, end)
    in_win = [o for o in occ if o.enter_s < end and o.exit_s > start]
    by_cls: dict[str, int] = {}
    for o in in_win:
        by_cls[o.train_class.value] = by_cls.get(o.train_class.value, 0) + 1
    pax = st.get_pax()
    e = pax.exposure(sec.id, start, end)
    from backend.domain.pax import train_pax
    people = int(sum(train_pax(o.train_class, o.enter_s) for o in in_win))
    locals_n = by_cls.get("SUBURBAN_LOCAL", 0)
    ld = by_cls.get("INTERCITY", 0) + by_cls.get("FREIGHT_MAIL", 0)
    text = (f"If **{sec.id}** ({net.stations[sec.from_station].name}–{net.stations[sec.to_station].name}) is closed "
            f"{_now_label(start)}–{s_to_hhmm(end % DAY_S)}, **{len(in_win)} train movements** are due through it "
            f"(about {people:,} passengers): {locals_n} suburban, {ld} long-distance/freight.")
    if b.reroutes:
        d = sum(r["added_delay_min"] for r in b.reroutes)
        text += (f" **{len(b.reroutes)} long-distance/freight train(s) would be diverted**: "
                 + ", ".join(f"{r['train_name'] or r['train_id']} (+{r['added_delay_min']:.0f} min)" for r in b.reroutes[:3])
                 + f", {d:.0f} train-minutes in all.")
    elif ld:
        text += f" The {ld} long-distance/freight train(s) have no detour inside their delay limit, so they would wait."
    if locals_n:
        text += (" Suburban locals are never rerouted — they serve fixed stations. "
                 + (f"{sec.id} has two local tracks, so they would run **single-line** on "
                    f"{b.track_swap['swap_to_track']}, one train at a time, while {b.track_swap['blocked_track']} is closed."
                    if b.track_swap else "This section has no second local track to swap to, so they would hold."))
    quiet = min(pax.hour_profile(sec.id, start // DAY_S), key=lambda h: h["passengers"])
    text += f" The quietest hour that day on this section is {quiet['hour']:02d}:00 ({quiet['trains']} trains)."
    facts = [{"k": "movements", "v": str(len(in_win))}, {"k": "diverted", "v": str(len(b.reroutes))},
             {"k": "locals", "v": str(locals_n)}, {"k": "passengers", "v": f"~{people:,}"}]
    a = Answer(text + note, facts, ["train occupancy", "reroute search (locals excluded)", "passenger model",
                                    "nothing was changed"], "whatif",
               suggestions=[f"how busy is {sec.id} at 9am?", f"best time for a 60 minute job on {sec.id}?"])
    a.action = {"label": "Show on map", "section": sec.id, "start_s": start}
    return a


# ------------------------------------------------------------- can two kinds of work share a place


def h_can_together(q: str, s: Slots, world, now_s: int) -> Answer:
    net = world.net
    if len(s.types) >= 2:
        tts = s.types[:2]
    elif len(s.depts) >= 2:
        tts = [_default_type(d, [t for t in s.types if t.department is d], s.zone) for d in s.depts[:2]]
    else:
        return _need("Name the two kinds of work — for example **can OHE insulator work and tamping happen "
                     "together at Kurla?** — or two departments.", "can PWI and S&T work together at Dadar?")
    if s.zone is None:
        return _need((s.note + " " if s.note else "") + "Where? Name a section or station.",
                     "can PWI and S&T work together at Dadar?")
    _remember(s)
    zones = s.zones if len(s.zones) >= 2 else [s.zone, s.zone]
    base = ((s.day or (now_s // DAY_S)) * DAY_S) + (s.tod_s or 2 * 3600)
    tasks = []
    for i, tt in enumerate(tts):
        t = Task(id=f"WHATIF-{i}", task_type=tt.code, department=tt.department, zone=zones[i],
                 duration_min=s.duration_min or 60, priority=3, category=TaskCategory.DEMAND,
                 requires_power_block=tt.requires_power_block, requires_traffic_block=tt.requires_traffic_block,
                 released_s=base, due_by_s=base + DAY_S, scheduled_start_s=base,
                 scheduled_end_s=base + (s.duration_min or 60) * 60, source="WHATIF")
        tasks.append(t)
    r = pair_verdict(net, tasks[0], tasks[1])
    verdict = r.value.value
    label = {"COMPATIBLE": "**Yes, they can share the block.**",
             "REQUIRES_IWP": "**Only with an Integrated Work Permission.**",
             "INCOMPATIBLE": "**No, they must be at different times.**"}[verdict]
    where = zones[0].describe() if zones[0] == zones[1] else f"{zones[0].describe()} and {zones[1].describe()}"
    text = (f"{label} {tts[0].label} ({tts[0].department.value}) with {tts[1].label} "
            f"({tts[1].department.value}) at {where}, same time: {r.reason}")
    facts = [{"k": "verdict", "v": verdict.replace("_", " ").lower()}, {"k": "rule", "v": r.rule_id or "-"}]
    if verdict == "INCOMPATIBLE":
        text += " Different times or different, non-overlapping places would be fine."
    elif verdict == "REQUIRES_IWP":
        text += " An IWP is a permit, not a free pass: it costs coordination and the daily quota is two."
    else:
        text += " Sharing saves one protected block, which is what the clustering looks for."
    return Answer(text, facts, ["rule engine (R0-R4)", "department declarations"], "together",
                  suggestions=["what if it is a 90 minute job?", f"who is working on {zones[0].ref} tomorrow?"])


# ------------------------------------------------------------------- who is working, and traffic


def h_whos_working(q: str, s: Slots, world, now_s: int) -> Answer:
    st = _live()
    _remember(s)
    ov = st.STATE.overrides
    booked = [x for x in booked_tasks(world) if x.id not in ov or ov[x.id] is not None]
    here = [x for x in booked if s.zone is None or (x.zone.endpoints & s.zone.endpoints)]
    where = f"on {s.zone.describe()}" if s.zone else "on the network"

    def sec_of(x: Task) -> str | None:
        if x.zone.kind is WorkZoneKind.SECTION:
            return x.zone.ref
        return next((sid for sid, sec in world.net.sections.items() if x.zone.ref in (sec.from_station, sec.to_station)), None)

    if s.day is not None and s.tod_s is None:                     # a whole day
        lo = s.day * DAY_S
        rows = sorted((x for x in here if x.scheduled_start_s < lo + DAY_S and (x.scheduled_end_s or 0) > lo),
                      key=lambda x: x.scheduled_start_s)
        if not rows:
            return Answer(f"Nothing is booked {where} on {DAY_ABBR[s.day]}.", [], ["every booked job"], "whos_working")
        parts = [f"**{x.id}** {x.department.value} {x.label.lower()} on {x.zone.ref} "
                 f"({s_to_hhmm(x.scheduled_start_s % DAY_S)}–{s_to_hhmm((x.scheduled_end_s or 0) % DAY_S)})" for x in rows[:6]]
        a = Answer(f"**{len(rows)} job(s)** {where} on {DAY_ABBR[s.day]}: " + "; ".join(parts) + (" …" if len(rows) > 6 else "."),
                   [{"k": "jobs", "v": str(len(rows))}], ["every booked job (planned, raised, simulated, sudden)"], "whos_working")
        a.action = {"label": "Show first on map", "section": sec_of(rows[0]), "start_s": rows[0].scheduled_start_s}
        return a

    t = s.day * DAY_S + s.tod_s if (s.day is not None and s.tod_s is not None) else (
        (now_s // DAY_S) * DAY_S + s.tod_s if s.tod_s is not None else now_s)
    rows = [x for x in here if x.scheduled_start_s <= t < (x.scheduled_end_s or 0)]
    if not rows:
        nxt = sorted((x for x in here if x.scheduled_start_s > t), key=lambda x: x.scheduled_start_s)
        text = f"Nobody is booked {where} at {_now_label(t)}."
        a = Answer(text, [], ["every booked job"], "whos_working")
        if nxt:
            x = nxt[0]
            a.text += (f" The next job is **{x.id}** ({x.department.value}, {x.label.lower()}) on {x.zone.ref} "
                       f"at {_now_label(x.scheduled_start_s)}.")
            a.action = {"label": "Show it on map", "section": sec_of(x), "start_s": x.scheduled_start_s}
        return a
    rows.sort(key=lambda x: x.scheduled_start_s)
    parts = [f"**{x.id}** {x.department.value} {x.label.lower()} on {x.zone.ref} "
             f"({s_to_hhmm(x.scheduled_start_s % DAY_S)}–{s_to_hhmm((x.scheduled_end_s or 0) % DAY_S)})" for x in rows[:5]]
    a = Answer(f"At {_now_label(t)} there {'are' if len(rows) != 1 else 'is'} **{len(rows)} job(s)** {where}: " + "; ".join(parts) + ".",
               [{"k": "jobs", "v": str(len(rows))}], ["every booked job (planned, raised, simulated, sudden)"], "whos_working")
    a.action = {"label": "Show on map", "section": sec_of(rows[0]), "start_s": rows[0].scheduled_start_s}
    return a


def h_traffic(q: str, s: Slots, world, now_s: int) -> Answer:
    st = _live()
    net = world.net
    if s.zone is None:
        return _need((s.note + " " if s.note else "") + "Which section or station? For example **how busy is Thane at 9am?**",
                     "how busy is Dadar to Matunga at 9am?")
    _remember(s)
    pax = st.get_pax()
    secs = ([s.zone.ref] if s.zone.kind is WorkZoneKind.SECTION else
            [sid for sid, sec in net.sections.items() if s.zone.ref in (sec.from_station, sec.to_station)])
    day = s.day if s.day is not None else (now_s // DAY_S) % 7
    hours = [{"hour": h, "trains": 0, "passengers": 0} for h in range(24)]
    for sid in secs:
        for row in pax.hour_profile(sid, day):
            hours[row["hour"]]["trains"] = max(hours[row["hour"]]["trains"], row["trains"])
            hours[row["hour"]]["passengers"] = max(hours[row["hour"]]["passengers"], row["passengers"])
    busy = max(hours, key=lambda h: h["passengers"])
    quiet = min(hours, key=lambda h: (h["passengers"], h["trains"]))
    tot = sum(h["trains"] for h in hours)
    label = s.zone.describe()
    if s.tod_s is not None:
        h = hours[s.tod_s // 3600]
        text = (f"At {h['hour']:02d}:00 on {DAY_ABBR[day]}, {label} sees **{h['trains']} trains an hour** carrying about "
                f"**{h['passengers']:,} passengers** (estimated, A-040). ")
    else:
        text = f"{label.capitalize()} carries **{tot} train movements on {DAY_ABBR[day]}**. "
    text += (f"Busiest hour {busy['hour']:02d}:00 ({busy['trains']} trains, ~{busy['passengers']:,} passengers); "
             f"quietest {quiet['hour']:02d}:00 ({quiet['trains']} trains, ~{quiet['passengers']:,}). "
             "This is where the scheduler prefers to place work.")
    facts = [{"k": "busiest", "v": f"{busy['hour']:02d}:00"}, {"k": "quietest", "v": f"{quiet['hour']:02d}:00"},
             {"k": "trains/day", "v": str(tot)}]
    return Answer(text, facts, ["train occupancy", "passenger model (estimated loads)"], "traffic",
                  suggestions=[f"best time for a 60 minute job on {s.zone.ref}?"])


def h_sudden_status(q: str, s: Slots, world, now_s: int) -> Answer:
    from backend.api.routes_sudden import sudden_metrics
    m = sudden_metrics()
    if not m.get("n"):
        return Answer("No sudden tasks have been injected yet. Use the **Sudden task** panel on Operations "
                      "(Low to Critical) and I'll report how each was handled.", [], ["sudden log"], "sudden")
    bm = m["by_method"]
    text = (f"**{m['n']} sudden task(s)** injected, **{m['placed']} placed**, {m['in_time']} inside their deadline. "
            f"Placed by: {bm['gap']} existing gap, {bm['created']} created gap, {bm['bumped']} pushing lower-priority "
            f"work aside, {bm['late']} late. Median response **{m['median_ms']} ms**"
            + (f" against {m['plan_resolve_ms'] / 1000:.0f} s to re-solve the week" if m.get("plan_resolve_ms") else "")
            + (f"; chosen sites average {m['site_tph']} trains/hour against {m['network_tph']} across the network."
               if m.get("site_tph") is not None else "."))
    return Answer(text, [{"k": "placed", "v": f"{m['placed']}/{m['n']}"}, {"k": "median", "v": f"{m['median_ms']} ms"}],
                  ["sudden log"], "sudden")


def h_explain_task(q: str, s: Slots, world, now_s: int) -> Answer:
    st = _live()
    tid = s.task_id
    e = next((x for x in st.STATE.sudden_log if x["id"] == tid), None)
    if e:
        steps = " ".join(f"({i + 1}) {t}" for i, t in enumerate(e["steps"][:6]))
        w = e["window"]
        text = (f"**{tid}** ({e['level']}, {e['task']['describe']}) — "
                + (f"placed {w['hhmm']} on {w['section_id']} ({e['method']}). " if w else "not placed. ")
                + steps)
        return Answer(text, [{"k": "response", "v": f"{e['response_ms']} ms"}], ["sudden log"], "explain")
    p = st.STATE.user_placements.get(tid)
    if p is not None:
        return Answer(f"**{tid}**: {p.reason}. " + " ".join(f"({i + 1}) {t}" for i, t in enumerate(p.steps[:6])),
                      [], ["your job's placement steps"], "explain")
    t = next((x for x in world.tasks if x.id == tid), None)
    if t is not None:
        if t.scheduled_start_s is None:
            return Answer(f"**{tid}** ({t.label}) is not booked: {st.STATE.user_unplaced.get(tid, 'no window long enough this week')}.",
                          [], ["task pool"], "explain")
        return Answer(f"**{tid}** ({t.department.value}, {t.label.lower()}) is booked {_now_label(t.scheduled_start_s)}–"
                      f"{s_to_hhmm((t.scheduled_end_s or 0) % DAY_S)} on {t.zone.ref} ({t.gap_type.lower().replace('_', ' ') if t.gap_type else 'window'}).",
                      [], ["weekly plan"], "explain")
    return Answer(f"I have no job called {tid}.", [], [], "explain")


# ------------------------------------------------------------------------------------- routing


def route(q: str, world, now_s: int) -> Answer | None:
    low = q.lower()
    s = parse(q, world, now_s)
    used_ctx = _fill_from_context(s, q)
    hypo, best = bool(HYPO.search(low)), bool(BEST.search(low))
    n_places = len(s.zones)

    if s.task_id and re.search(r"\b(why|explain|how|where|when|what happened|status)\b", low):
        return h_explain_task(q, s, world, now_s)
    if re.search(r"\bsudden\b", low) and re.search(r"\b(how many|status|metric|summary|stats?|placed|handled|proof)\b", low):
        return h_sudden_status(q, s, world, now_s)
    if CLOSE.search(low) and (hypo or re.search(r"\b(if|happens?)\b", low)) and s.zone is not None:
        return h_whatif_close(q, s, world, now_s)
    if TOGETHER.search(low) and (len(s.types) >= 2 or len(s.depts) >= 2 or re.search(r"\bcan\b", low)):
        if len(s.types) >= 2 or len(s.depts) >= 2:
            return h_can_together(q, s, world, now_s)
    if re.search(r"\b(who|what work|what is happening|what's happening|anyone|any work|being done|working)\b", low) \
            and re.search(r"\b(working|work|maintenance|job|jobs|booked|happening)\b", low):
        return h_whos_working(q, s, world, now_s)
    if re.search(r"\bhow (busy|crowded|many trains|many passengers|many people)\b|\btrains per hour\b|\bfrequency\b|"
                 r"\brush hour\b|\bfootfall\b|\bwhen is .* (busy|quiet)\b|\bquiet(est)?\b.*\b(hour|time)\b", low) \
            and not re.search(r"\b(job|task|work|block|fit|schedule)\b", low):
        return h_traffic(q, s, world, now_s)
    add_cue = bool(s.depts or s.types or s.duration_min or re.search(r"\b(job|task|work|block|maintenance)\b", low))
    if (hypo or best) and add_cue and (s.zone is not None or used_ctx):
        return h_whatif_add(q, s, world, now_s)
    if best and s.zone is not None and add_cue:
        return h_whatif_add(q, s, world, now_s)
    if used_ctx and s.zone is not None and (s.priority or s.gap_kind or s.tod_s is not None or s.duration_min):
        return h_whatif_add(q, s, world, now_s)
    return None
