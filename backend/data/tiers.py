"""Station tier derivation from observed train frequency.

<!-- serves: J1 -->

Tiers are derived by quantile from the data, never hardcoded by station name (SPEC §8.1).
The corridor config's `expect_tier` is a sanity check only: a disagreement is reported as a
warning, and the derived value always wins.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from backend.config import load_config
from backend.domain.models import SectionOccupancy, StationTier, Train
from backend.domain.network import Network
from backend.domain.occupancy import peak_trains_per_hour


def derive_tiers(net: Network, trains: list[Train], occ: list[SectionOccupancy]) -> list[str]:
    """Assign tiers in place. Returns a list of human-readable disagreement warnings."""
    cfg = load_config()["station_tiers"]

    station_counts: dict[str, int] = defaultdict(int)
    station_hour: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for tr in trains:
        for st in tr.stops:
            station_counts[st.station_code] += 1
            t = st.arrival_s if st.arrival_s is not None else st.departure_s
            if t is not None:
                station_hour[st.station_code][(t % 86400) // 3600] += 1

    counts = np.array([station_counts.get(c, 0) for c in net.order], dtype=float)
    q1 = float(np.quantile(counts, float(cfg["tier1_quantile"])))
    q3 = float(np.quantile(counts, float(cfg["tier3_quantile"])))

    warnings: list[str] = []
    for code in net.order:
        n = station_counts.get(code, 0)
        tier = StationTier.TIER_1 if n >= q1 else (StationTier.TIER_3 if n <= q3 else StationTier.TIER_2)
        st = net.stations[code]
        st.tier = tier
        st.trains_per_day = n
        st.peak_trains_per_hour = float(max(station_hour[code].values())) if station_hour[code] else 0.0
        if st.expect_tier and st.expect_tier != tier:
            warnings.append(
                f"{code} ({st.name}): derived {tier.value} but config expected "
                f"{st.expect_tier.value} — {n} services/day, thresholds q1={q1:.0f} q3={q3:.0f}"
            )

    # A section inherits the busier of its two endpoints: work there disturbs both.
    rank = {StationTier.TIER_1: 3, StationTier.TIER_2: 2, StationTier.TIER_3: 1}
    for sec in net.sections.values():
        a, b = net.stations[sec.from_station].tier, net.stations[sec.to_station].tier
        sec.tier = a if rank[a] >= rank[b] else b
        sec.trains_per_day = sum(1 for o in occ if o.section_id == sec.id)
        sec.peak_trains_per_hour = peak_trains_per_hour(occ, sec.id)

    return warnings
