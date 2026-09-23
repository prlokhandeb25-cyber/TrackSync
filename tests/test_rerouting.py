"""Rerouting and track-swap levers (SPEC §9), including the guardrail.

CLAUDE.md invariant: a SUBURBAN_LOCAL is never assigned an alternate route. This is the one
test file whose first job is proving that rule cannot be silently bypassed.
"""

from __future__ import annotations

import pytest

from backend.config import seed_everything
from backend.domain.models import Stop, Train, TrainClass
from backend.domain.network import build_network, merge_networks
from backend.planner.rerouting import (
    RerouteGuardrailError,
    k_shortest_paths,
    reroute_candidates,
    track_swap_opportunity,
)


@pytest.fixture(scope="module")
def net():
    seed_everything()
    return build_network("central_line")


@pytest.fixture(scope="module")
def meshed_net():
    """The merged network, which has real alternate routes via its interchanges.

    A single linear corridor genuinely has only one path between any two of its stations, so
    it cannot exercise rerouting - there is nothing to avoid a closed section WITH. The merged
    network is meshed through CSTM, Kurla, Thane, Vashi and Sanpada, which is where an
    alternate path actually exists.
    """
    seed_everything()
    return merge_networks([
        build_network(c) for c in
        ("central_line", "western_line", "harbour_line", "trans_harbour")
    ])


def _train(net, train_class: TrainClass, origin: str, destination: str) -> Train:
    return Train(
        id="T-TEST", number="1", name="test", train_class=train_class,
        corridor_id=net.corridor_id, origin=origin, destination=destination, direction="DN",
        stops=[Stop(station_code=origin, arrival_s=None, departure_s=0),
               Stop(station_code=destination, arrival_s=3600, departure_s=None)],
        priority=2,
    )


# --------------------------------------------------------------------------- the guardrail


def test_suburban_local_is_refused_outright(net):
    local = _train(net, TrainClass.SUBURBAN_LOCAL, "CSTM", "KYN")
    with pytest.raises(RerouteGuardrailError):
        reroute_candidates(net, local, avoid_section_id="DR-MTN")


def test_local_reroutable_property_is_false(net):
    local = _train(net, TrainClass.SUBURBAN_LOCAL, "CSTM", "KYN")
    assert local.reroutable is False


def test_intercity_reroutable_property_is_true(net):
    ic = _train(net, TrainClass.INTERCITY, "CSTM", "KYN")
    assert ic.reroutable is True


# ------------------------------------------------------------------- intercity/freight reroute


def test_a_single_linear_corridor_has_no_alternate_path(net):
    """One line, no branch: correctly reports no way to avoid a section in the middle."""
    ic = _train(net, TrainClass.INTERCITY, "CSTM", "KYN")
    paths = reroute_candidates(net, ic, avoid_section_id="DR-MTN", k=3)
    assert paths == []


def test_intercity_gets_alternate_paths_on_the_meshed_network(meshed_net):
    ic = _train(meshed_net, TrainClass.INTERCITY, "CSTM", "TNA")
    paths = reroute_candidates(meshed_net, ic, avoid_section_id="CLA-GC", k=3)
    assert paths, "CSTM-Thane should have an alternate via the Harbour/Trans-Harbour interchanges"
    for p in paths:
        assert "CLA-GC" not in p.sections, "an alternate path must actually avoid the closed section"


def test_freight_gets_alternate_paths_within_its_looser_limit(meshed_net):
    freight = _train(meshed_net, TrainClass.FREIGHT_MAIL, "CSTM", "TNA")
    paths = reroute_candidates(meshed_net, freight, avoid_section_id="CLA-GC", k=3)
    assert paths
    # Freight's acceptable delay (90 min) is looser than intercity's (30 min).
    assert any(p.within_limit for p in paths)


def test_delay_is_never_negative(meshed_net):
    ic = _train(meshed_net, TrainClass.INTERCITY, "CSTM", "TNA")
    for p in reroute_candidates(meshed_net, ic, avoid_section_id="CLA-GC", k=3):
        assert p.added_delay_min >= 0


def test_k_shortest_paths_respects_k(meshed_net):
    paths = k_shortest_paths(meshed_net, "CSTM", "TNA", k=2)
    assert 0 < len(paths) <= 2


def test_k_shortest_paths_empty_for_unknown_station(net):
    assert k_shortest_paths(net, "CSTM", "NOT_A_REAL_STATION", k=3) == []


# ---------------------------------------------------------------------------- local track swap


def test_track_swap_available_on_a_simple_two_track_section(net):
    sec = net.sections["NRL-BVS"]  # ghat branch: plain UP/DN
    opp = track_swap_opportunity(net, sec, occupancy_per_hour=5.0)
    assert opp is not None
    assert {opp.blocked_track, opp.swap_to_track} == {"DN", "UP"}


def test_track_swap_uses_only_the_slow_pair_on_a_four_track_section(net):
    sec = net.sections["CSTM-BY"]  # main line: fast + slow pairs
    opp = track_swap_opportunity(net, sec, occupancy_per_hour=20.0)
    assert opp is not None
    # The fast pair carries intercity/freight, not locals - it must never appear here.
    assert "FAST" not in opp.blocked_track
    assert "FAST" not in opp.swap_to_track
    assert {opp.blocked_track, opp.swap_to_track} == {"UP_SLOW", "DN_SLOW"}


def test_track_swap_carries_the_configured_single_line_cap(net):
    sec = net.sections["NRL-BVS"]
    opp = track_swap_opportunity(net, sec, occupancy_per_hour=5.0)
    assert opp.max_single_line_min > 0
