"""Traffic-gap engine — where maintenance can actually go.

<!-- serves: J1, J5 -->

Most block planning uses two windows: the night gap and the Sunday megablock. This engine
finds those, and also the ordinary gaps BETWEEN CONSECUTIVE TRAINS during the working day.
That third category is the differentiating idea: at a low-frequency station like Neral there
are usable gaps in daylight, and at a high-frequency one like Dadar work should be dripped
into many short windows rather than queued up for a megablock that is weeks away.

Two things this engine insists on:

  1. The night window is DERIVED per section from the last and first train, never hardcoded.
     It comes out around 01:00-04:00 on the main line and materially longer on the outer
     sections - and showing that difference is a better argument than quoting a constant.

  2. A raw gap is not working time. Protection has to be set up and the line handed back:

         usable = raw - block_setup - block_release  (- power block isolation, for OHE work)

     A 40-minute gap yields about 15 minutes of actual work. Planning against raw gaps would
     overstate capacity everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from backend.config import load_config
from backend.data.week import DAY_S, SUNDAY, day_of, time_of_day
from backend.domain.models import SectionOccupancy, StationTier, WorkZoneKind, hhmmss_to_s, s_to_hhmm
from backend.domain.network import Network
from backend.domain.occupancy import group_by_track


class GapType(str, Enum):
    NIGHT_WINDOW = "NIGHT_WINDOW"
    MEGABLOCK = "MEGABLOCK"
    MICRO_GAP = "MICRO_GAP"


# A night window is the longest gap whose midpoint falls in this band. The band is only a
# search hint - the window's actual extent comes from the trains.
NIGHT_BAND = (21 * 3600, 8 * 3600)  # wraps midnight


def min_raw_gap_min() -> int:
    """Shortest raw gap worth keeping: one that still leaves the minimum workable time.

    A gap is not working time - protection has to be set up and the line handed back - so a gap
    only counts if, after those overheads, at least `gaps.min_workable_min` minutes of real work
    remain (15 by default). Everything below that is dropped at the source, so no window in the
    system, and nothing drawn from one, is shorter than 15 usable minutes.
    """
    cfg = load_config()["gaps"]
    overhead = int(cfg["block_setup_min"]) + int(cfg["block_release_min"])
    return max(int(cfg["min_usable_gap_min"]), overhead + int(cfg.get("min_workable_min", 15)))


def _late_risk(prev_class, start_s: int) -> float:
    """P(the train before the gap is >10 min late), so the window would open late.

    Straight from the configured delay model (`delays.*.p_gt_10min`, scaled up in the peaks). A
    gap that follows a freight or a long-distance train is a less dependable start than one that
    follows a suburban local, and the scheduler can see that.
    """
    if prev_class is None:
        return 0.0
    cfg = load_config()["delays"]
    key = {"SUBURBAN_LOCAL": "suburban", "INTERCITY": "intercity", "FREIGHT_MAIL": "freight"}.get(
        getattr(prev_class, "value", str(prev_class)), "suburban")
    p = float(cfg[key]["p_gt_10min"])
    tod = time_of_day(start_s)
    for a, b in cfg.get("peak_windows", []):
        if (hhmmss_to_s(a) or 0) <= tod < (hhmmss_to_s(b) or 0):
            p *= float(cfg.get("peak_multiplier", 1.0))
            break
    return min(0.95, p)


def _to_grid(start_s: int, end_s: int) -> tuple[int, int]:
    """Blocks are granted in whole steps (5 min by default): start rounds up, end rounds down."""
    g = int(load_config()["gaps"].get("block_grid_min", 5)) * 60
    return -(-start_s // g) * g, (end_s // g) * g


def _clip_to_night_band(start_s: int, end_s: int) -> tuple[int, int] | None:
    """Clip a gap to the night band it sits in.

    Without this, a sparsely used fast line reports a ten-hour "night window" running to
    mid-morning, because the longest gap happens to have its midpoint before 08:00. A night
    window has to be bounded by the night, not merely centred on it.
    """
    lo_t, hi_t = NIGHT_BAND
    day = start_s // DAY_S
    # The band runs from 21:00 on this day to 08:00 on the next.
    for base in (day - 1, day):
        lo = base * DAY_S + lo_t
        hi = (base + 1) * DAY_S + hi_t
        c_lo, c_hi = max(start_s, lo), min(end_s, hi)
        if c_hi - c_lo >= min_raw_gap_min() * 60:
            return c_lo, c_hi
    return None


def _tier_cap_min(tier: StationTier | None) -> int:
    """Longest block a station of this tier will grant during traffic hours (SPEC §8.2).

    A Tier-1 station cannot hand over the road for six hours in daylight however empty the
    graph looks, so daytime windows are capped and the work is dripped into many short ones
    instead of queued for a megablock. Outer stations can absorb much longer daytime blocks.
    """
    cfg = load_config()["station_tiers"]
    return int({
        StationTier.TIER_1: cfg["max_window_min_tier1"],
        StationTier.TIER_2: cfg["max_window_min_tier2"],
        StationTier.TIER_3: cfg["max_window_min_tier3"],
    }.get(tier, cfg["max_window_min_tier2"]))



@dataclass
class CandidateWindow:
    id: str
    section_id: str
    zone_ref: str
    zone_kind: WorkZoneKind
    track: str
    direction: str
    start_s: int
    end_s: int
    gap_type: GapType
    station_tier: StationTier | None
    prev_train_id: str | None = None
    next_train_id: str | None = None
    trains_within_60min_after: int = 0
    # Set only on windows that did not exist in the timetable and were created by a lever
    # (backend/gaps/creation.py): which lever, and what it costs the trains in train-minutes.
    created_by: str | None = None
    delay_cost_min: float = 0.0
    created_note: str = ""
    # Chance the train before the gap runs more than 10 minutes late and eats into the start of the
    # window (0 for a night window with no train before it). From the delay model, A-041.
    late_risk: float = 0.0

    @property
    def raw_min(self) -> int:
        return (self.end_s - self.start_s) // 60

    def usable_min(self, power_block: bool = False) -> int:
        cfg = load_config()["gaps"]
        overhead = int(cfg["block_setup_min"]) + int(cfg["block_release_min"])
        if power_block:
            overhead += 2 * int(cfg["power_block_extra_min"])  # isolate, then de-earth
        return max(0, self.raw_min - overhead)

    @property
    def day(self) -> int:
        return day_of(self.start_s)

    @property
    def extension_cost_min(self) -> float:
        """Cost of stealing another minute from the trains that bound this gap.

        Extending into a busy stretch delays every following service, so a window on a quiet
        outer section is far cheaper to lengthen than one at Dadar. This is what lets the
        planner CREATE a window rather than only consume existing ones.
        """
        return float(self.trains_within_60min_after)

    def describe(self) -> str:
        label = {
            GapType.NIGHT_WINDOW: "night window",
            GapType.MEGABLOCK: "Sunday megablock",
            GapType.MICRO_GAP: "gap between trains",
        }[self.gap_type]
        return (f"{s_to_hhmm(time_of_day(self.start_s))}-{s_to_hhmm(time_of_day(self.end_s))} "
                f"on {self.section_id} ({self.track}), {label}, "
                f"{self.raw_min} min raw / {self.usable_min()} min usable")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "section_id": self.section_id, "zone_ref": self.zone_ref,
            "zone_kind": self.zone_kind.value, "track": self.track, "direction": self.direction,
            "start_s": self.start_s, "end_s": self.end_s, "day": self.day,
            "start_hhmm": s_to_hhmm(time_of_day(self.start_s)),
            "end_hhmm": s_to_hhmm(time_of_day(self.end_s)),
            "gap_type": self.gap_type.value, "raw_min": self.raw_min,
            "usable_min": self.usable_min(),
            "usable_min_power_block": self.usable_min(power_block=True),
            "station_tier": self.station_tier.value if self.station_tier else None,
            "extension_cost_min": self.extension_cost_min,
            "prev_train_id": self.prev_train_id, "next_train_id": self.next_train_id,
            "created_by": self.created_by, "delay_cost_min": self.delay_cost_min,
            "created_note": self.created_note,
            "late_risk": round(self.late_risk, 3),
            "reliability_pct": round(100 * (1 - self.late_risk)),
        }


def _in_night_band(t_of_day: int) -> bool:
    lo, hi = NIGHT_BAND
    return t_of_day >= lo or t_of_day < hi


def _megablock_window(net: Network, day: int, section_id: str | None = None
                      ) -> tuple[int, int] | None:
    mb = net.megablock or {}
    if section_id and net.per_corridor:
        sec = net.sections.get(section_id)
        for cid, cfg in net.per_corridor.items():
            if sec is not None and sec.line_code == cfg.get("line_code"):
                mb = cfg.get("megablock") or mb
                break
    if not mb or day != SUNDAY:
        return None
    start = hhmmss_to_s(mb.get("start", "10:30")) or 0
    end = hhmmss_to_s(mb.get("end", "15:30")) or 0
    return day * DAY_S + start, day * DAY_S + end


@dataclass
class GapReport:
    windows: list[CandidateWindow] = field(default_factory=list)
    night_windows_by_section: dict[str, tuple[int, int]] = field(default_factory=dict)
    megablock_observed: dict[str, float] = field(default_factory=dict)

    def by_type(self, t: GapType) -> list[CandidateWindow]:
        return [w for w in self.windows if w.gap_type is t]


def find_gaps(net: Network, occ: list[SectionOccupancy], horizon_days: int = 7) -> GapReport:
    cfg = load_config()["gaps"]
    min_usable = min_raw_gap_min()
    buffer_s = int(cfg["headway_buffer_s"])
    # the gang has to be clear of the track before the next train, with room to spare
    lookout_s = max(buffer_s, int(cfg.get("lookout_min", 5)) * 60)

    report = GapReport()
    grouped = group_by_track(occ)
    wid = 0

    for (section_id, track), items in grouped.items():
        sec = net.sections.get(section_id)
        if sec is None:
            continue
        direction = items[0].direction if items else "UP"

        for day in range(horizon_days):
            day_lo, day_hi = day * DAY_S, (day + 1) * DAY_S
            todays = [o for o in items if day_lo <= o.enter_s < day_hi]
            todays.sort(key=lambda o: o.enter_s)

            # Raw gaps: between the exit of one movement and the entry of the next, with the
            # headway buffer removed from both ends so the window is genuinely free.
            raw: list[tuple[int, int, str | None, str | None]] = []
            prev_cls: dict[int, object] = {}   # raw-gap index -> class of the train before it
            if not todays:
                raw.append((day_lo, day_hi, None, None))
            else:
                if todays[0].enter_s - day_lo > 0:
                    raw.append((day_lo, todays[0].enter_s - lookout_s, None, todays[0].train_id))
                for a, b in zip(todays, todays[1:]):
                    start, end = a.exit_s + buffer_s, b.enter_s - lookout_s
                    if end > start:
                        prev_cls[len(raw)] = a.train_class
                        raw.append((start, end, a.train_id, b.train_id))
                if day_hi - todays[-1].exit_s > 0:
                    prev_cls[len(raw)] = todays[-1].train_class
                    raw.append((todays[-1].exit_s + buffer_s, day_hi, todays[-1].train_id, None))
            # blocks are asked for and granted on a 5-minute grid
            raw = [(*_to_grid(s_, e_), p_, n_) for (s_, e_, p_, n_) in raw]

            # The night window is the longest gap whose midpoint sits in the night band.
            night_idx = None
            best = 0
            for i, (s, e, _, _) in enumerate(raw):
                if _in_night_band(time_of_day((s + e) // 2)) and (e - s) > best:
                    best, night_idx = e - s, i

            mb = _megablock_window(net, day, section_id)

            for i, (s, e, prev_id, next_id) in enumerate(raw):
                dur_min = (e - s) // 60
                if dur_min < min_usable:
                    continue

                if mb and s < mb[1] and e > mb[0]:
                    gap_type = GapType.MEGABLOCK
                elif i == night_idx:
                    gap_type = GapType.NIGHT_WINDOW
                else:
                    gap_type = GapType.MICRO_GAP

                following = sum(1 for o in todays if e <= o.enter_s < e + 3600)

                # A night window is bounded by the night, not merely centred on it.
                if gap_type is GapType.NIGHT_WINDOW:
                    clipped = _clip_to_night_band(s, e)
                    if clipped is None:
                        gap_type = GapType.MICRO_GAP
                        spans = [(s, e)]
                    else:
                        spans = [clipped]
                else:
                    spans = [(s, e)]

                # Daytime windows are capped by station tier: a Tier-1 station will not hand
                # over the road for hours in traffic, so a long gap there becomes several
                # short workable windows rather than one implausible one.
                if gap_type is GapType.MICRO_GAP:
                    cap_s = _tier_cap_min(sec.tier) * 60
                    split: list[tuple[int, int]] = []
                    for a, b in spans:
                        cur = a
                        while b - cur >= min_usable * 60:
                            split.append((cur, min(cur + cap_s, b)))
                            cur += cap_s
                    spans = split

                for a, b in spans:
                    if (b - a) // 60 < min_usable:
                        continue
                    wid += 1
                    report.windows.append(
                        CandidateWindow(
                            id=f"W{wid:05d}",
                            section_id=section_id,
                            zone_ref=section_id,
                            zone_kind=WorkZoneKind.SECTION,
                            track=track,
                            direction=direction,
                            start_s=a,
                            end_s=b,
                            gap_type=gap_type,
                            station_tier=sec.tier,
                            prev_train_id=prev_id,
                            next_train_id=next_id,
                            trains_within_60min_after=following,
                            late_risk=_late_risk(prev_cls.get(i), a),
                        )
                    )

                    if gap_type is GapType.NIGHT_WINDOW and day == 0:
                        report.night_windows_by_section[f"{section_id}/{track}"] = (
                            time_of_day(a), time_of_day(b)
                        )

    # Verify the configured megablock against what the data actually shows: compare Sunday
    # traffic in the window against the same window on a weekday.
    mb = net.megablock or {}
    if mb:
        start = hhmmss_to_s(mb.get("start", "10:30")) or 0
        end = hhmmss_to_s(mb.get("end", "15:30")) or 0
        for section_id in net.sections:
            sun = sum(1 for o in occ if o.section_id == section_id
                      and day_of(o.enter_s) == SUNDAY
                      and start <= time_of_day(o.enter_s) < end)
            wk = sum(1 for o in occ if o.section_id == section_id
                     and day_of(o.enter_s) == 2
                     and start <= time_of_day(o.enter_s) < end)
            if wk:
                report.megablock_observed[section_id] = round(1.0 - sun / wk, 3)

    return report


def station_node_windows(net: Network, report: GapReport) -> list[CandidateWindow]:
    """Derive station-node windows from the sections that meet at each station.

    A station is workable when every section touching it is free, since work in the yard
    fouls the approaches. Taking the intersection is the conservative reading, and the
    conservative reading is the right default for a safety constraint.
    """
    out: list[CandidateWindow] = []
    wid = 0
    for code in net.order:
        touching = [s for s in net.sections.values()
                    if code in (s.from_station, s.to_station)]
        if not touching:
            continue
        per_section: list[list[CandidateWindow]] = []
        for sec in touching:
            per_section.append([w for w in report.windows if w.section_id == sec.id])
        if not all(per_section):
            continue

        # Re-label the first section's windows as station-node windows before intersecting.
        # Without this a terminus - which touches only one section - never enters the pairwise
        # loop below, so its windows keep the SECTION zone_ref and no work can be placed at
        # the station at all. CSTM had zero candidate windows because of exactly that.
        wid += 1
        current = [
            CandidateWindow(
                id=f"S{wid:05d}-{i}", section_id=a.section_id, zone_ref=code,
                zone_kind=WorkZoneKind.STATION_NODE, track=a.track, direction=a.direction,
                start_s=a.start_s, end_s=a.end_s, gap_type=a.gap_type,
                station_tier=net.stations[code].tier,
                trains_within_60min_after=a.trains_within_60min_after,
            )
            for i, a in enumerate(per_section[0])
        ]
        for nxt in per_section[1:]:
            merged: list[CandidateWindow] = []
            for a in current:
                for b in nxt:
                    lo, hi = max(a.start_s, b.start_s), min(a.end_s, b.end_s)
                    if hi - lo >= min_raw_gap_min() * 60:
                        wid += 1
                        merged.append(
                            CandidateWindow(
                                id=f"S{wid:05d}",
                                section_id=a.section_id,
                                zone_ref=code,
                                zone_kind=WorkZoneKind.STATION_NODE,
                                track=a.track,
                                direction=a.direction,
                                start_s=lo,
                                end_s=hi,
                                gap_type=a.gap_type,
                                station_tier=net.stations[code].tier,
                                trains_within_60min_after=max(
                                    a.trains_within_60min_after, b.trains_within_60min_after
                                ),
                            )
                        )
            current = merged
            if not current:
                break
        out.extend(current)
    return out
