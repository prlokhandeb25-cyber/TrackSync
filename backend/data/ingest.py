"""Timetable ingest: real long-distance layer + synthesised suburban and freight layers.

<!-- serves: J2 -->

All times are ABSOLUTE seconds from the start of the service week (see models.Stop).

Provenance is tracked per train (`is_real`). The national schedule dataset contains mail and
express services only — Mumbai suburban EMU timetables are not in any public source we found,
so the local layer is synthesised to published structural parameters (ASSUMPTIONS A-007).
Every train carries its provenance so the report can state exactly how much is real.
"""

from __future__ import annotations

import json
import random

from backend.config import REPO_ROOT, load_config
from backend.domain.models import Stop, Train, TrainClass, hhmmss_to_s
from backend.domain.network import Network

RAW = REPO_ROOT / "data" / "raw"


# --------------------------------------------------------------------------- real layer

def _running_days(number: str) -> list[int]:
    """Assign days of operation to a real long-distance service.

    The public dataset has no day-of-operation field, so every train in it looks daily. Running
    all of them on one service date puts a whole WEEKLY roster onto a single day, which both
    over-saturates the fast lines and produces impossible 60-second following moves between
    expresses that in reality never run on the same day.

    Roughly two thirds of Indian Railways mail/express services are daily and the rest run on
    two to four fixed days a week. The split here is deterministic in the train number, so it
    is stable across runs without needing to be stored. ASSUMPTIONS A-012.
    """
    h = 0
    for ch in str(number):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    if h % 100 < 66:  # daily
        return [0, 1, 2, 3, 4, 5, 6]
    n_days = 2 + (h // 100) % 3  # 2, 3 or 4 days a week
    start = (h // 1000) % 7
    return sorted({(start + i * 2) % 7 for i in range(n_days)})




def load_real_long_distance(net: Network) -> list[Train]:
    """Filter the national schedule dataset down to trains that traverse this corridor."""
    src = RAW / "schedules.json"
    if not src.exists():
        return []
    with open(src, "r", encoding="utf-8") as fh:
        rows = json.load(fh)

    min_hits = int(net.long_distance.get("min_corridor_stations", 4))
    corridor_codes = set(net.stations)

    by_train: dict[str, list[dict]] = {}
    for r in rows:
        if r["station_code"] in corridor_codes:
            by_train.setdefault(r["train_number"], [])
    for r in rows:
        if r["train_number"] in by_train:
            by_train[r["train_number"]].append(r)

    trains: list[Train] = []
    for number, stops_raw in by_train.items():
        on_corridor = [r for r in stops_raw if r["station_code"] in corridor_codes]
        if len({r["station_code"] for r in on_corridor}) < min_hits:
            continue
        days = _running_days(number)

        on_corridor.sort(key=lambda r: r["id"])  # dataset id preserves route order
        seen: set[str] = set()
        stops: list[Stop] = []
        cursor = -1  # running absolute time, forces monotonicity across midnight
        for r in on_corridor:
            code = r["station_code"]
            if code in seen:  # a few services reverse through a junction; keep the first visit
                continue
            seen.add(code)
            base = max(0, int(r.get("day") or 1) - 1) * 86400
            arr = hhmmss_to_s(r.get("arrival"))
            dep = hhmmss_to_s(r.get("departure"))

            def absolutise(t: int | None, cursor: int) -> int | None:
                if t is None:
                    return None
                a = base + t
                while a < cursor:  # the dataset's `day` is per-train, not per-corridor-entry
                    a += 86400
                return a

            arr_a = absolutise(arr, cursor)
            cursor = arr_a if arr_a is not None else cursor
            dep_a = absolutise(dep, cursor)
            cursor = dep_a if dep_a is not None else cursor
            stops.append(Stop(station_code=code, arrival_s=arr_a, departure_s=dep_a))

        if len(stops) < 2:
            continue

        idx = {c: i for i, c in enumerate(net.order)}
        direction = "UP" if idx.get(stops[-1].station_code, 0) < idx.get(stops[0].station_code, 0) else "DN"
        trains.append(
            Train(
                id=f"R-{net.line_code}-{number}",
                number=str(number),
                name=on_corridor[0]["train_name"],
                train_class=TrainClass.INTERCITY,
                corridor_id=net.corridor_id,
                origin=stops[0].station_code,
                destination=stops[-1].station_code,
                direction=direction,  # type: ignore[arg-type]
                stops=stops,
                priority=2,
                days_of_week=days,
                max_acceptable_delay_min=load_config().get_path("rerouting.max_delay_min.INTERCITY", 30),
                is_real=True,
            )
        )
    return trains


# ----------------------------------------------------------------------- synthetic layers


def _headway_at(second: int, sub: dict, rng: random.Random) -> int:
    peaks = [(hhmmss_to_s(a), hhmmss_to_s(b)) for a, b in sub.get("peak_windows", [])]
    in_peak = any(a is not None and b is not None and a <= (second % 86400) < b for a, b in peaks)
    lo, hi = sub["peak_headway_min"] if in_peak else sub["offpeak_headway_min"]
    return rng.randint(int(lo), int(hi)) * 60


def _emu_run_s(sec, dwell_s: int, include_dwell: bool) -> int:
    """EMU run time over a section. Locals average well below line speed (frequent stops)."""
    return int(sec.nominal_run_time_s(sec.line_speed_kmph * 0.62)) + (dwell_s if include_dwell else 0)


def synth_suburban(net: Network, rng: random.Random) -> list[Train]:
    """Generate the suburban EMU layer.

    Services are spaced at headway across a COMMON REFERENCE POINT (the corridor's terminus
    end), not at each service's own origin. Spacing trains at their individual origins is
    wrong: a Thane-starter and a Kalyan-starter leaving three minutes apart are nowhere near
    three minutes apart by the time they reach a shared section. Because every turn-back
    pattern here is a prefix of the same line at the same speed profile, spacing at one
    reference point preserves that spacing along the whole shared run.
    """
    sub = net.suburban
    if not sub.get("enabled", False):
        return []

    reference = net.order[0]  # the terminus every pattern touches
    first_up = hhmmss_to_s(sub["first_up"]) or 0
    last_down = hhmmss_to_s(sub["last_down"]) or 0
    if last_down < first_up:
        last_down += 86400
    dwell = int(sub.get("dwell_s", 25))

    patterns = sub["patterns"]
    weights = [p["share"] for p in patterns]

    trains: list[Train] = []
    seq = 0
    for direction in ("DN", "UP"):
        ref_t = first_up
        while ref_t < last_down:
            pat = rng.choices(patterns, weights=weights, k=1)[0]
            a, b = (pat["from"], pat["to"]) if direction == "DN" else (pat["to"], pat["from"])
            secs = net.path_sections(a, b)
            if not secs:
                ref_t += _headway_at(ref_t, sub, rng)
                continue

            seq += 1
            if direction == "DN":
                clock = ref_t  # departs the reference terminus at ref_t
            else:
                # Arrives at the reference terminus at ref_t: back-compute the origin departure.
                total = sum(_emu_run_s(s, dwell, s is not secs[-1]) for s in secs)
                clock = ref_t - total

            stops = [Stop(station_code=a, arrival_s=None, departure_s=clock)]
            for sec in secs:
                clock += _emu_run_s(sec, dwell, False)
                arr = clock
                nxt = sec.to_station if sec.from_station == stops[-1].station_code else sec.from_station
                is_last = sec is secs[-1]
                if not is_last:
                    clock += dwell
                stops.append(
                    Stop(station_code=nxt, arrival_s=arr, departure_s=None if is_last else clock)
                )

            if stops[0].departure_s is not None and stops[0].departure_s >= 0:
                trains.append(
                    Train(
                        id=f"S-{net.line_code}-{direction}-{seq:05d}",
                        number=f"9{seq:04d}",
                        name=f"{net.stations[a].name} – {net.stations[b].name} Local",
                        train_class=TrainClass.SUBURBAN_LOCAL,
                        corridor_id=net.corridor_id,
                        origin=a,
                        destination=b,
                        direction=direction,  # type: ignore[arg-type]
                        stops=stops,
                        priority=3,
                        max_acceptable_delay_min=0,  # never rerouted; see Train.reroutable
                        is_real=False,
                    )
                )
            ref_t += _headway_at(ref_t, sub, rng)
    return trains


def synth_freight(net: Network, n: int, rng: random.Random) -> list[Train]:
    """Freight paths are not published in any public dataset (A-008). Pathed in the night band."""
    trains: list[Train] = []
    ends = (net.order[0], net.order[-1])
    band = net.long_distance.get("freight_band", ["00:30", "04:30"])
    band_s = (hhmmss_to_s(band[0]) or 1800, hhmmss_to_s(band[1]) or 16200)
    for i in range(n):
        direction = "DN" if i % 2 == 0 else "UP"
        a, b = ends if direction == "DN" else ends[::-1]
        secs = net.path_sections(a, b)
        # Freight is slotted evenly across the night band, per direction. Drawing departure
        # times at random puts paths on top of each other; real freight is slotted.
        lo, hi = band_s
        per_dir = max(1, n // 2)
        slot = i // 2
        clock = lo + int((hi - lo) * (slot + 0.5) / per_dir) + rng.randint(-90, 90)
        stops = [Stop(station_code=a, arrival_s=None, departure_s=clock)]
        for sec in secs:
            clock += int(sec.nominal_run_time_s(min(sec.line_speed_kmph, 75) * 0.55))
            arr = clock
            nxt = sec.to_station if sec.from_station == stops[-1].station_code else sec.from_station
            is_last = sec is secs[-1]
            if not is_last:
                clock += rng.randint(60, 420)  # loop halts for crossings
            stops.append(Stop(station_code=nxt, arrival_s=arr, departure_s=None if is_last else clock))
        trains.append(
            Train(
                id=f"F-{net.line_code}-{i:03d}",
                number=f"F{net.line_code}{i:03d}",
                name=f"Freight {a}–{b} #{i:03d}",
                train_class=TrainClass.FREIGHT_MAIL,
                corridor_id=net.corridor_id,
                origin=a,
                destination=b,
                direction=direction,  # type: ignore[arg-type]
                stops=stops,
                priority=5,
                max_acceptable_delay_min=load_config().get_path("rerouting.max_delay_min.FREIGHT_MAIL", 90),
                is_real=False,
            )
        )
    return trains


def _service_weekday() -> int:
    """Weekday index (Mon=0) of the configured service date."""
    from datetime import date

    raw = str(load_config().get_path("data.service_date", "2026-09-21"))
    y, m, d = (int(x) for x in raw.split("-"))
    return date(y, m, d).weekday()


def build_timetable(net: Network, seed: int) -> list[Train]:
    rng = random.Random(seed)
    weekday = _service_weekday()
    real = [t for t in load_real_long_distance(net) if weekday in t.days_of_week]
    locals_ = synth_suburban(net, rng)
    n_freight = int(len(real) * float(net.long_distance.get("freight_share", 0.25)))
    freight = synth_freight(net, n_freight, rng)
    return real + locals_ + freight
