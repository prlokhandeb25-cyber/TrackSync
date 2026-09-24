"""RailMitra: tasks on screen, crew and cost what-ifs, and "is this slot free, and who can use it?".

<!-- serves: J1, J5 -->

Every handler here works on copies and reads live state without writing to it (see `chat/features.py` for the
sandbox test). Answers are built as short bullet lists with the figures that matter in bold.
"""

from __future__ import annotations

import math
import re

from backend.chat import whatif as W
from backend.chat.engine import DAY_ABBR, DAY_S, Answer
from backend.config import load_config
from backend.domain.compatibility import Verdict, check_allotment
from backend.domain.models import WorkZoneKind, s_to_hhmm
from backend.domain.scoring import pair_verdict
from backend.domain.task import Department, WorkZone
from backend.planner import resources as RS

DEPT_NAME = {Department.PWI: "P.Way (PWI)", Department.OWD: "Overhead (OWD)", Department.S_AND_T: "Signal & Telecom (S&T)"}
INR = lambda v: f"₹{int(round(v)):,}"                                                                # noqa: E731


def neaten(text: str) -> str:
    """Turn '**Label:** ...' paragraphs into bullets, so every answer reads as a short list under one lead line."""
    paras = [p for p in text.split("\n\n")]
    out: list[str] = []
    for i, p in enumerate(paras):
        head = re.match(r"^\*\*[^*\n]{2,40}:\*\*", p) is not None
        if head and not p.startswith("- "):
            p = "- " + p
        if p.startswith("- ") and out and out[-1].startswith("- "):
            out[-1] += "\n" + p                              # consecutive bullets sit together
        else:
            out.append(p)
    return "\n\n".join(out)


# ------------------------------------------------------------------------------ parsing helpers


def _clock(h: str, m: str | None, ap: str | None) -> int:
    hh = int(h) % 12 + (12 if ap == "pm" else 0) if ap else int(h)
    return hh * 3600 + int(m or 0) * 60


def time_range(low: str) -> tuple[int, int] | None:
    """'between 14:00 and 15:30', '2pm to 3pm', '14:00-15:00' -> (seconds into the day, seconds into the day)."""
    m = re.search(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\s*(?:-|–|to|and|till|until)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?", low)
    if not m:
        return None
    ap1, ap2 = m.group(3), m.group(6)
    a = _clock(m.group(1), m.group(2), ap1 or ap2)
    b = _clock(m.group(4), m.group(5), ap2 or ap1)
    if b <= a:
        b += 12 * 3600 if b + 12 * 3600 > a and b < 12 * 3600 else 0
    return (a, b) if 0 <= a < b <= 24 * 3600 + 1 else None


def _workers(low: str) -> int | None:
    m = re.search(r"(\d+)\s*(?:more |extra |additional )?(?:workers?|people|men|staff|technicians?|maintainers?|persons?|gang members?)", low)
    return int(m.group(1)) if m else None


def _machines(low: str) -> int | None:
    m = re.search(r"(\d+)\s*(?:extra |more |additional )?(?:machines?|tampers?|tamping machines?|tower wagons?|wagons?)", low)
    return int(m.group(1)) if m else None


def _tt(s: W.Slots):
    return W._default_type(s.depts[0] if s.depts else None, s.types, s.zone)


# ------------------------------------------------------------------------------------ tasks on screen


def h_tasks(q: str, s: W.Slots, world, now_s: int) -> Answer:
    st = W._live()
    net = world.net
    rows = [t for t in W.booked_tasks(world) if t.scheduled_start_s is not None]
    scope = []
    if s.day is not None:
        rows = [t for t in rows if (t.scheduled_start_s // DAY_S) % 7 == s.day]
        scope.append(W._day_label(s.day))
    if s.depts:
        rows = [t for t in rows if t.department in s.depts]
        scope.append(", ".join(DEPT_NAME[d] for d in s.depts))
    if s.zone is not None:
        ends = {s.zone.ref} | ({x for sec in net.sections.values() if s.zone.ref in (sec.from_station, sec.to_station) for x in (sec.id,)}
                               if s.zone.kind is WorkZoneKind.STATION_NODE else set())
        rows = [t for t in rows if t.zone.ref in ends]
        scope.append(f"{net.stations[s.zone.ref].name} station" if s.zone.kind is WorkZoneKind.STATION_NODE else s.zone.ref)
    if not scope:                                            # nothing named: the next stretch of the clock
        rows = [t for t in rows if now_s <= t.scheduled_start_s < now_s + 24 * 3600]
        scope.append("the next 24 hours")
    rows.sort(key=lambda t: t.scheduled_start_s)
    by_dept: dict[str, int] = {}
    for t in rows:
        by_dept[t.department.value] = by_dept.get(t.department.value, 0) + 1
    where = " · ".join(scope)
    if not rows:
        return Answer(f"Nothing is booked for **{where}**.\n\n- Want me to find a slot for a job there?", [], ["booked jobs"], "tasks",
                      suggestions=["what if a 60 minute PWI job at Dadar to Matunga?"])
    first = rows[0]
    text = (f"Here's what is booked for **{where}**: **{len(rows)} job{'s' if len(rows) != 1 else ''}**.\n\n"
            + "\n".join(f"- **{DEPT_NAME[Department(k)].split(' (')[0]}:** {v}" for k, v in sorted(by_dept.items())) + "\n"
            + f"- **First up:** {first.label.lower()} on {first.zone.ref}, {W._date_label(first.scheduled_start_s)}\n"
            + f"- **Longest:** {max(rows, key=lambda t: t.duration_min).label.lower()} ({max(t.duration_min for t in rows)} min)")
    vis = {"type": "tasks", "title": f"Jobs booked: {where}", "day": (s.day if s.day is not None else None),
           "rows": [{"id": t.id, "dept": t.department.value, "label": t.label, "zone": t.zone.ref, "priority": t.priority,
                     "start_s": t.scheduled_start_s, "end_s": t.scheduled_end_s or t.scheduled_start_s + t.duration_min * 60,
                     "source": t.source} for t in rows[:14]]}
    a = Answer(text, [{"k": "jobs", "v": str(len(rows))}], ["booked jobs (planned, daily, live, sudden)", "nothing was changed"], "tasks",
               suggestions=[f"what does a {first.duration_min} minute {first.label.lower()} job need?", "is there a free gap tomorrow at 14:00?"])
    a.visual = vis
    a.action = {"label": "Show first on map", "section": first.zone.ref if first.zone.ref in net.sections else None, "start_s": first.scheduled_start_s}
    return a


# ------------------------------------------------------------------------------- resources, cost, crew


def _cost_visual(c: dict) -> dict:
    k = c["cost"]
    return {"type": "bars", "title": f"Cost split, total {INR(k['total'])} (assumed rates)",
            "items": [{"label": "People", "value": k["labour"], "best": False}, {"label": "Equipment", "value": k["equipment"], "best": False},
                      {"label": "Materials", "value": k["materials"], "best": False}]}


def h_resources(q: str, s: W.Slots, world, now_s: int) -> Answer:
    low = q.lower()
    tt = _tt(s)
    dur = s.duration_min or max(tt.min_duration_min, min(90, tt.max_duration_min))
    e = RS.estimate(tt, dur)
    c = RS.costed(tt, dur)
    crew = ", ".join(f"{r['n']} {r['role'].lower()}" for r in e["roles"])
    text = (f"For a **{dur}-minute {tt.label.lower()}** job, this is what you'd normally line up:\n\n"
            f"- **People:** **{e['people_per_shift']}** on site ({crew})\n"
            f"- **Equipment:** {', '.join(e['equipment']).lower()}\n"
            + (f"- **Materials:** {', '.join(e['materials']).lower()}\n" if e["materials"] else "")
            + f"- **Time on the track:** **{c['block_min']} min** in all ({c['overhead_min']} min set-up and hand-back around {dur} min of work)\n"
            + f"- **Cost:** about **{INR(c['cost']['total'])}** (people {INR(c['cost']['labour'])}, equipment {INR(c['cost']['equipment'])}, materials {INR(c['cost']['materials'])})")
    if e["shifts"] > 1:
        text += f"\n- **Shifts:** longer than one shift, so plan **{e['shifts']}** relief crews (about {e['people_total']} people over the job)"
    if e["power_block"]:
        text += "\n- **Power:** needs a power block, so a traction power controller and an earthing party are included"
    text += ("\n\n*These are typical planning norms and assumed rates, not measured figures. Treat them as a starting checklist.*"
             "\n\nWant to see how the time changes with more workers or a second machine?")
    a = Answer(text, [{"k": "people", "v": str(e["people_per_shift"])}, {"k": "block", "v": f"{c['block_min']} min"},
                      {"k": "cost", "v": INR(c["cost"]["total"])}], ["planning norms and rates (assumed)", "nothing was changed"], "resources",
               suggestions=[f"how long would it take with {c['norm_workers'] + 4} workers?", f"how long with 2 {'machines' if c['norm_machines'] else 'workers'}?",
                            f"best time for a {dur} minute {tt.department.value} job?"])
    a.visual = {"type": "bars", "title": f"People on site ({e['people_per_shift']} in all)",
                "items": [{"label": r["role"], "value": r["n"], "best": False} for r in e["roles"]]}
    a.visuals = [_cost_visual(c)]
    return a


def h_crew_whatif(q: str, s: W.Slots, world, now_s: int) -> Answer:
    low = q.lower()
    tt = _tt(s)
    dur = s.duration_min or max(tt.min_duration_min, min(120, tt.max_duration_min))
    n, m = _workers(low), _machines(low)
    base = RS.costed(tt, dur)
    if n is None and m is None:
        n = base["norm_workers"] + 4
    new = RS.costed(tt, dur, workers=n, machines=m)
    d_min = new["work_min"] - base["work_min"]
    d_cost = new["cost"]["total"] - base["cost"]["total"]
    verb = "shorter" if d_min < 0 else "longer" if d_min > 0 else "the same"
    text = (f"Here's how a **{dur}-minute {tt.label.lower()}** changes with a different crew:\n\n"
            f"- **Crew:** **{base['norm_workers']}** normally → **{new['workers']}** workers"
            + (f", machines {base['norm_machines']} → **{new['machines']}**" if base["norm_machines"] else "") + "\n"
            f"- **Work time:** **{base['work_min']} min** → **{new['work_min']} min** ({abs(d_min)} min {verb})\n"
            f"- **Block on the track:** **{base['block_min']} min** → **{new['block_min']} min** (includes {new['overhead_min']} min set-up and hand-back, which more people can't shorten)\n"
            f"- **Cost:** **{INR(base['cost']['total'])}** → **{INR(new['cost']['total'])}** ({'+' if d_cost >= 0 else '−'}{INR(abs(d_cost))})\n"
            f"- **Person-hours:** {base['person_hours']} → {new['person_hours']}")
    if n is not None and n > 2 * base["norm_workers"]:
        text += f"\n- **Note:** beyond about **{2 * base['norm_workers']}** workers a site is crowded, so I've counted no further speed-up"
    if s.zone is not None and s.zone.kind is WorkZoneKind.SECTION:
        st = W._live()
        idx = st.ensure_interval_index()
        probe = W._probe(world, s, "CREW-TRY", tt, 0)
        def n_windows(minutes: int) -> int:
            probe.duration_min = max(10, minutes)
            return len(idx.eligible(probe))
        a0, a1 = n_windows(base["work_min"]), n_windows(new["work_min"])
        text += f"\n- **Gaps that fit it on {s.zone.ref}:** **{a0}** → **{a1}** this week"
    text += ("\n\n*The speed-up follows a diminishing-returns rule (doubling the crew is not twice as fast), and the rates are assumed. It shows the shape of the trade-off, not a measured result.*")
    a = Answer(text, [{"k": "work time", "v": f"{new['work_min']} min"}, {"k": "cost", "v": INR(new["cost"]["total"])}],
               ["crew scaling model (assumed)", "planning rates (assumed)", "gap finder", "nothing was changed"], "crew",
               suggestions=[f"what does a {dur} minute {tt.label.lower()} need?", "is there a free gap tomorrow at 14:00?"])
    a.visual = {"type": "bars", "title": "Work time by crew size (minutes)",
                "items": [{"label": f"{r['workers']} workers", "value": r["work_min"], "best": r["workers"] == new["workers"]}
                          for r in RS.crew_curve(tt, dur, machines=m)]}
    a.visuals = [{"type": "bars", "title": "Cost by crew size (₹ thousand)",
                  "items": [{"label": f"{r['workers']} workers", "value": round(r["cost"]["total"] / 1000, 1), "best": r["workers"] == new["workers"]}
                            for r in RS.crew_curve(tt, dur, machines=m)]}]
    return a


# ---------------------------------------------------------------------- a slot: free? who can use it? buffer?


def _dynamic_buffer(world, st, w, tt, day_s: int, dur_min: int, target: float = 0.95) -> dict:
    """The smallest spare time to leave before the next train so that the block is handed back in time on at least
    `target` of simulated days, given this gap, this kind of work and the day's weather-driven crew overrun."""
    from backend.planner.cpsat import Assignment
    from backend.planner.crew_profile import true_mean
    from backend.planner.robustness import assess

    probe = W._probe(world, W.Slots(zone=WorkZone(kind=w.zone_kind, ref=w.zone_ref)), "BUF", tt, day_s)
    probe.duration_min = dur_min
    g = load_config()["gaps"]
    rel = (int(g["block_release_min"]) + (int(g["power_block_extra_min"]) if tt.requires_power_block else 0)) * 60
    occ = st.occupancy_by_section()
    curve = []
    pick = None
    for spare in range(0, 50, 5):
        end = w.end_s - rel - spare * 60
        start = end - dur_min * 60
        if start < w.start_s:
            break
        a = Assignment("BUF", w.id, w.section_id, w.zone_ref, w.track, start, end, w.gap_type.value, start // DAY_S)
        r = assess([a], {"BUF": probe}, occ, samples=300, over_mean=lambda t, a_: true_mean(tt.department.value, a_.start_s // DAY_S))
        p = r[0].p_clear if r else 1.0
        curve.append((spare, p))
        if pick is None and p >= target:
            pick = spare
    return {"spare_min": pick, "curve": curve, "target": target}


def h_slot_check(q: str, s: W.Slots, world, now_s: int) -> Answer:
    st = W._live()
    net = world.net
    low = q.lower()
    if s.zone is None:
        return W._need((s.note + " " if s.note else "") + "Which stretch? For example: *is there a free gap on Kurla to Sion tomorrow between 14:00 and 15:00?*",
                       "is there a free gap on Kurla to Sion tomorrow between 14:00 and 15:00?")
    if s.zone.kind is WorkZoneKind.STATION_NODE:
        secs = [x for x in net.sections.values() if s.zone.ref in (x.from_station, x.to_station)]
        sec = max(secs, key=lambda x: len(st.occupancy_by_section().get(x.id, []))) if secs else None
        if sec is None:
            return W._need("I couldn't find a section there.", "is there a free gap on Kurla to Sion tomorrow between 14:00 and 15:00?")
        zone = WorkZone(kind=WorkZoneKind.SECTION, ref=sec.id)
        near = f" (I used {sec.id}, the busiest section at {net.stations[s.zone.ref].name})"
    else:
        zone, near = s.zone, ""
    day = s.day if s.day is not None else (now_s // DAY_S) % 7
    tr = time_range(low)
    if tr is None:
        t0 = s.tod_s if s.tod_s is not None else 14 * 3600
        t1 = t0 + (s.duration_min or 60) * 60
    else:
        t0, t1 = tr
    a0, a1 = day * DAY_S + t0, day * DAY_S + t1
    g = load_config()["gaps"]
    setup, rel = int(g["block_setup_min"]) * 60, int(g["block_release_min"]) * 60
    wins = [w for w in world.windows if w.zone_ref == zone.ref and w.end_s > a0 and w.start_s < a1]
    label = f"{zone.ref} on {W._day_label(day)}, {s_to_hhmm(t0 % DAY_S)}–{s_to_hhmm(t1 % DAY_S)}"
    if not wins:
        text = (f"No, that slot is **not free**: **{label}** has a train running through it on every track, so there is no gap to work in.\n\n"
                f"- **Why:** the gap finder found no window there once set-up and hand-back are counted\n"
                f"- **Try:** ask *best time for a 45 minute job on {zone.ref}*")
        a = Answer(text, [{"k": "free", "v": "no"}], ["gap engine windows", "nothing was changed"], "slot",
                   suggestions=[f"best time for a 45 minute PWI job on {zone.ref}?"])
        a.visual = _day_visual(st, zone.ref, day, t0, t1, world)
        return a
    def usable(w):
        return max(0, (min(a1, w.end_s - rel) - max(a0, w.start_s + setup)) // 60)
    best = max(wins, key=usable)
    full = best.start_s <= a0 and best.end_s >= a1
    use = usable(best)
    depts = s.depts or [Department.PWI, Department.OWD, Department.S_AND_T]
    booked = [t for t in W.booked_tasks(world) if t.scheduled_start_s is not None and t.scheduled_start_s < a1
              and (t.scheduled_end_s or 0) > a0 and t.zone.ref in (zone.ref, net.sections[zone.ref].from_station, net.sections[zone.ref].to_station)]
    verdict_lines, ok_depts = [], []
    for d in Department:
        tt = W._default_type(d, [], zone)
        p = W._probe(world, W.Slots(zone=zone, duration_min=max(15, use)), "SLOT", tt, a0)
        p.scheduled_start_s, p.scheduled_end_s = a0, a1
        rej = check_allotment(net, p)
        if rej is not None:
            verdict_lines.append(f"- **{DEPT_NAME[d].split(' (')[0]}:** not allotted this stretch ({rej.rule_id})")
            continue
        worst, why = Verdict.COMPATIBLE, ""
        for b in booked:
            v = pair_verdict(net, p, b)
            if v.value is Verdict.INCOMPATIBLE and b.department != d:
                worst, why = Verdict.INCOMPATIBLE, f"blocked by {b.department.value} {b.label.lower()} ({b.id})"
                break
            if v.value is Verdict.INCOMPATIBLE and b.department == d:
                worst, why = Verdict.INCOMPATIBLE, f"its own department already has {b.label.lower()} booked then"
                break
            if v.value is Verdict.REQUIRES_IWP:
                worst, why = Verdict.REQUIRES_IWP, f"needs a joint permit with {b.department.value} {b.label.lower()}"
        if worst is Verdict.INCOMPATIBLE:
            verdict_lines.append(f"- **{DEPT_NAME[d].split(' (')[0]}:** no, {why}")
        elif worst is Verdict.REQUIRES_IWP:
            verdict_lines.append(f"- **{DEPT_NAME[d].split(' (')[0]}:** yes, but {why}")
            ok_depts.append(d)
        else:
            verdict_lines.append(f"- **{DEPT_NAME[d].split(' (')[0]}:** yes")
            ok_depts.append(d)
    mine = s.depts[0] if s.depts else (ok_depts[0] if ok_depts else Department.PWI)
    tt = W._default_type(mine, s.types, zone)
    dur = min(use, s.duration_min or use) if use >= 15 else 0
    buf = _dynamic_buffer(world, st, best, tt, a0, max(15, dur)) if dur >= 15 else None
    head = ("Yes, that slot is **free**" if full and use >= 15 else "Partly: a gap **overlaps** that slot" if use >= 15 else
            "There's a gap nearby but it's **too short** to do real work")
    text = (f"{head}: **{label}**.\n\n"
            f"- **The gap:** {W._date_label(best.start_s)}–{s_to_hhmm(best.end_s % DAY_S)} on **{best.track.replace('_', ' ')}**"
            f" ({best.raw_min} min between trains, {best.trains_within_60min_after} train(s) within the hour after)\n"
            f"- **Usable for work:** **{use} min** after {setup // 60} min set-up and {rel // 60} min hand-back\n"
            f"- **Reliability:** the train before it runs late enough to eat into it about **{round(best.late_risk * 100)}%** of the time\n"
            + (f"- **Already booked there:** {', '.join(f'{b.department.value} {b.label.lower()}' for b in booked[:3])}\n" if booked else "- **Already booked there:** nothing\n")
            + "\n**Who can use it?**\n\n" + "\n".join(verdict_lines))
    if buf is not None:
        if buf["spare_min"] is None:
            text += (f"\n\n**Dynamic buffer:** even leaving 45 min spare, a **{dur}-min** {tt.label.lower()} clears in time on fewer than "
                     f"{round(buf['target'] * 100)}% of simulated days here, so choose a shorter job or another gap.")
        else:
            have = max(0, (best.end_s - rel - (a0 + max(15, dur) * 60)) // 60) if full else 0
            text += (f"\n\n**Dynamic buffer** for a **{dur}-min** {tt.label.lower()}:\n\n"
                     f"- **Leave about {buf['spare_min']} min spare** before the next train's lookout margin (clears in time on at least {round(buf['target'] * 100)}% of simulated days)\n"
                     f"- **This slot leaves:** {have} min → **{'enough' if have >= buf['spare_min'] else 'tight, start earlier or shorten the job'}**\n"
                     f"- **Why that figure:** it uses this gap's lateness risk and how much {tt.department.value} crews tend to overrun on that day (wetter days need more)")
    text += "\n\n*Worked out from the real timetable and rules on a copy; nothing was booked.*"
    a = Answer(text, [{"k": "free", "v": "yes" if use >= 15 else "no"}, {"k": "usable", "v": f"{use} min"},
                      {"k": "buffer", "v": f"{buf['spare_min']} min" if buf and buf["spare_min"] is not None else "n/a"}],
               ["gap engine windows", "rule engine (per department)", "clearance simulation", "nothing was changed"], "slot",
               suggestions=[f"what does a {max(15, use)} minute {tt.label.lower()} need?", f"best time for a 45 minute {mine.value} job on {zone.ref}?"])
    a.visual = _day_visual(st, zone.ref, day, t0, t1, world)
    if buf and buf["curve"]:
        a.visuals = [{"type": "bars", "title": "Chance the block clears in time, by spare minutes (%)",
                      "items": [{"label": f"{sp} min spare", "value": round(p * 100), "best": sp == buf["spare_min"]} for sp, p in buf["curve"]]}]
    a.action = {"label": "Show on map", "section": zone.ref, "start_s": a0}
    return a


def _day_visual(st, section: str, day: int, t0: int, t1: int, world) -> dict:
    occ = [o for o in st.occupancy_by_section().get(section, []) if o.enter_s // DAY_S == day]
    tracks = sorted({o.track for o in occ})
    return {"type": "daystrip", "title": f"{section}: trains and gaps on {W._day_label(day)}",
            "range": [t0, t1], "tracks": [{"track": tk, "trains": [[o.enter_s % DAY_S, o.exit_s % DAY_S, o.train_class.value] for o in occ if o.track == tk]}
                                          for tk in tracks]}
