"""The gap engine's working, laid out as steps for one track on one day.

<!-- serves: J1, J5 -->

`find_gaps` (engine.py) is the algorithm. This replays the same arithmetic row by row for a single
track-day so a person can watch it: list the trains, take the space between each pair, take off the
safety buffer at both ends, take off the time to set up and hand the line back, and keep the gap
only if 15 minutes of real work is left. Near misses are handed to gap creation (creation.py) to
see whether a small change to the trains would make them long enough.

It does not re-implement the engine's later steps (clipping night windows, splitting long
daytime gaps by station tier), so `windows` - what the engine really produced for this track-day -
is returned next to the rows as the ground truth.
"""

from __future__ import annotations

from backend.config import load_config
from backend.data.week import DAY_S
from backend.domain.models import Section, SectionOccupancy
from backend.gaps.creation import (
    RerouteCache, _cfg, _reroute_options, _retime_option, sequences,
)
from backend.gaps.engine import CandidateWindow, _late_risk, _to_grid, min_raw_gap_min


def trace_track_day(section: Section, track: str, day: int, occ: list[SectionOccupancy],
                    windows: list[CandidateWindow], rc: RerouteCache,
                    hour_from: float = 5.0, hour_to: float = 9.0) -> dict:
    cfg = load_config()["gaps"]
    buf = int(cfg["headway_buffer_s"])
    look = max(buf, int(cfg.get("lookout_min", 5)) * 60)   # clear of the track this long before the next train
    overhead = int(cfg["block_setup_min"]) + int(cfg["block_release_min"])
    min_workable = int(cfg.get("min_workable_min", 15))
    need_s = min_raw_gap_min() * 60
    c = _cfg()

    seq = sequences(occ).get((track, day), [])
    lo_s, hi_s = day * DAY_S + int(hour_from * 3600), day * DAY_S + int(hour_to * 3600)

    rows, kept, dropped, near = [], 0, 0, 0
    for i in range(len(seq) - 1):
        a, b = seq[i], seq[i + 1]
        if b.enter < lo_s or a.exit > hi_s:
            continue
        gap = b.enter - a.exit
        if gap <= 0:
            continue  # two services overlap on this track: there is no gap to measure
        # the same arithmetic as the engine: safety at the front, a lookout margin at the back, then the
        # 5-minute block grid (start rounds up, end rounds down)
        g0, g1 = _to_grid(a.exit + buf, b.enter - look)
        after_buf = max(0, g1 - g0)
        usable = after_buf / 60 - overhead
        keep = after_buf >= need_s
        row = {
            "prev": {"train_id": a.train_id, "class": a.cls.value, "enter_s": a.enter, "exit_s": a.exit},
            "next": {"train_id": b.train_id, "class": b.cls.value, "enter_s": b.enter, "exit_s": b.exit},
            "gap_min": round(gap / 60, 1),
            "after_buffers_min": round(after_buf / 60, 1),
            "usable_min": round(max(0.0, usable), 1),
            "keep": keep, "creation": None,
            "reliability_pct": round(100 * (1 - _late_risk(a.cls, a.exit))),
        }
        if keep:
            kept += 1
            row["reason"] = f"{row['usable_min']:.0f} min of real work fits, so this gap is kept."
        else:
            dropped += 1
            if usable <= -overhead:
                row["reason"] = "Once the safety gap either side is taken off, almost nothing is left."
            elif usable < 0:
                row["reason"] = (f"The {overhead} min needed to set up and hand back the line is longer "
                                 f"than this gap.")
            else:
                row["reason"] = (f"Only {usable:.0f} min of real work would be left; "
                                 f"{min_workable} min is the minimum.")
            deficit = need_s - after_buf
            if 0 < deficit <= int(load_config()["gap_creation"]["survey_max_deficit_min"]) * 60:
                near += 1
                opt = _retime_option(section, track, day, seq, i, need_s, c)
                if opt is None:
                    ro = _reroute_options(section, track, day, seq[max(0, i - 3):i + 5], need_s, c, rc)
                    opt = ro[0] if ro else None
                if opt is not None:
                    row["creation"] = opt.to_dict()
        rows.append(row)

    return {
        "section_id": section.id, "track": track, "day": day,
        "hour_from": hour_from, "hour_to": hour_to,
        "buffer_min": round((buf + look) / 60, 1), "overhead_min": overhead, "min_workable_min": min_workable,
        "min_raw_min": need_s // 60,
        "n_trains": len(seq), "rows": rows,
        "kept": kept, "dropped": dropped, "near_misses": near,
        "windows": [
            {"id": w.id, "start_s": w.start_s, "end_s": w.end_s, "gap_type": w.gap_type.value,
             "usable_min": w.usable_min()}
            for w in windows
            if w.section_id == section.id and w.track == track
            and w.start_s // DAY_S == day and w.end_s > lo_s and w.start_s < hi_s
        ],
    }
