"""Asset availability: how much of the track is open to trains, and how many train movements meet no closed line.

<!-- serves: J5 -->

The project's purpose is to keep the track available to traffic while it is maintained. This measures that from the
plan that actually exists (every booked block: the weekly plan, daily routine jobs, jobs raised, sudden and simulated
arrivals) and the real timetable, with no invented inputs:

    line availability   = 1 - closed line-km-hours / all line-km-hours, over the 7-day week
                          (a "line" is one track of one section; a closed line counts for its section's length)
    in service hours    = the same, counting only 04:00 to 24:00, when trains actually run
    train availability  = 1 - train movements due on a line while it is closed / all train movements in the week

A block closes its line from the start of protection to the end of hand-back (the set-up and release times of
`gaps.*`, plus the extra power-block time for overhead work). Overlapping blocks on one line are counted once.
For contrast the same figures are computed as if each block had closed EVERY line of its section (how a plan that
ignores which line the work is on would count): the difference is what naming the line buys.

Station-only work is not counted: it does not close a line between stations. Nothing here is estimated or assumed
beyond the protection times already in `config.yaml` (A-061 for the line-by-line changeover).
"""

from __future__ import annotations

from bisect import bisect_left

from backend.config import load_config

DAY_S = 86400
SERVICE_FROM_S, SERVICE_TO_S = 4 * 3600, 24 * 3600


def _merge(iv: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _service_seconds(a: int, b: int) -> int:
    """Seconds of [a, b) that fall inside 04:00-24:00 of some day."""
    total = 0
    d = a // DAY_S
    while d * DAY_S < b:
        lo, hi = d * DAY_S + SERVICE_FROM_S, d * DAY_S + SERVICE_TO_S
        total += max(0, min(b, hi) - max(a, lo))
        d += 1
    return total


def collect_blocks(world, plan, state) -> list[tuple[str, str | None, int, int, bool]]:
    """(section, line or None, start, end, power block) for every booked block on a section."""
    by_id = {t.id: t for t in world.tasks}
    out = []
    if plan is not None:
        for a in plan.assignments:
            if a.zone_ref in world.net.sections:
                t = by_id.get(a.task_id)
                out.append((a.zone_ref, a.track, a.start_s, a.end_s, bool(t and t.requires_power_block)))
    for o in state.overrides.values():
        if o and o["zone_ref"] in world.net.sections:
            out.append((o["zone_ref"], o.get("track"), o["start_s"], o["end_s"], False))
    for group in (state.live_sim.placed, state.user_placements.values(), state.sudden_state.placed, state.daily_state.placed):
        for p in group:
            if p.placed and p.window is not None and p.window.zone_ref in world.net.sections and p.start_s is not None:
                out.append((p.window.zone_ref, p.window.track, p.start_s, p.end_s, bool(p.task.requires_power_block)))
    return out


def availability(world, blocks: list[tuple[str, str | None, int, int, bool]], occ_by_section: dict, horizon_days: int = 7) -> dict:
    g = load_config()["gaps"]
    setup, release, extra = int(g["block_setup_min"]) * 60, int(g["block_release_min"]) * 60, int(g["power_block_extra_min"]) * 60
    horizon = horizon_days * DAY_S
    net = world.net

    def closed_by_line(whole_section: bool) -> dict[tuple[str, str], list[tuple[int, int]]]:
        d: dict[tuple[str, str], list[tuple[int, int]]] = {}
        for sec, track, s, e, power in blocks:
            lo, hi = max(0, s - setup - (extra if power else 0)), min(horizon, e + release + (extra if power else 0))
            if hi <= lo:
                continue
            lines = net.sections[sec].tracks if (whole_section or track not in net.sections[sec].tracks) else [track]
            for tr in lines:
                d.setdefault((sec, tr), []).append((lo, hi))
        return {k: _merge(v) for k, v in d.items()}

    total_kmh = sum(s.length_km * len(s.tracks) for s in net.sections.values()) * horizon / 3600.0
    service_kmh = sum(s.length_km * len(s.tracks) for s in net.sections.values()) * (SERVICE_TO_S - SERVICE_FROM_S) * horizon_days / 3600.0
    passages = [(o.section_id, o.track, o.enter_s, o.exit_s) for occ in occ_by_section.values() for o in occ if o.enter_s < horizon]

    def measure(whole_section: bool) -> dict:
        closed = closed_by_line(whole_section)
        km_h = svc_km_h = 0.0
        for (sec, _), ivs in closed.items():
            L = net.sections[sec].length_km
            km_h += L * sum(b - a for a, b in ivs) / 3600.0
            svc_km_h += L * sum(_service_seconds(a, b) for a, b in ivs) / 3600.0
        starts = {k: [a for a, _ in v] for k, v in closed.items()}
        hit = 0
        for sec, tr, en, ex in passages:
            iv = closed.get((sec, tr))
            if not iv:
                continue
            i = bisect_left(starts[(sec, tr)], ex)               # blocks starting before the train leaves
            if any(a < ex and b > en for a, b in iv[:i]):
                hit += 1
        return {"line_pct": round(100 * (1 - km_h / total_kmh), 3), "service_pct": round(100 * (1 - svc_km_h / service_kmh), 3),
                "train_pct": round(100 * (1 - hit / max(1, len(passages))), 3), "closed_line_km_h": round(km_h, 1),
                "trains_meeting_a_closed_line": hit}

    named = measure(False)
    whole = measure(True)
    n_lines = sum(1 for _, t, *_ in blocks if t)
    return {
        "line_pct": named["line_pct"], "service_pct": named["service_pct"], "train_pct": named["train_pct"],
        "closed_line_km_h": named["closed_line_km_h"], "total_line_km_h": round(total_kmh, 1),
        "trains_meeting_a_closed_line": named["trains_meeting_a_closed_line"], "train_movements": len(passages),
        "blocks": len(blocks), "blocks_with_a_named_line": n_lines,
        "if_whole_section": {"line_pct": whole["line_pct"], "service_pct": whole["service_pct"], "train_pct": whole["train_pct"],
                             "trains_meeting_a_closed_line": whole["trains_meeting_a_closed_line"]},
        "how": ("Measured from every booked block and the real timetable: a line is closed from the start of protection to the end of "
                "hand-back; line availability weights each line by its length; train availability is the share of the week's train "
                "movements that were not due on a line while it was closed. The 'whole section' figures count each block as closing "
                "every line of its section, to show what naming the line saves."),
    }
