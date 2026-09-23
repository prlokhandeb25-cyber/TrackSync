"""Live rerouting around an active block (backend/planner/active_reroute.py)."""

from __future__ import annotations

import pytest

from backend.config import seed_everything
from backend.domain.models import SectionOccupancy, Stop, Train, TrainClass
from backend.domain.network import build_network, merge_networks
from backend.planner.active_reroute import plan_block_reroutes


@pytest.fixture(scope="module")
def net():
    seed_everything()
    return merge_networks([build_network(c) for c in
                           ("central_line", "western_line", "harbour_line", "trans_harbour")])


def _train(tid: str, cls: TrainClass) -> Train:
    return Train(
        id=tid, number=tid, name=tid, train_class=cls, corridor_id="mumbai",
        origin="CSTM", destination="KYN", direction="DN",
        stops=[Stop(station_code="CSTM", arrival_s=None, departure_s=0),
               Stop(station_code="KYN", arrival_s=3600, departure_s=None)],
    )


def _occ(train: Train, section_id: str) -> SectionOccupancy:
    return SectionOccupancy(section_id=section_id, track="DN_FAST", direction="DN",
                            train_id=train.id, train_class=train.train_class,
                            enter_s=100, exit_s=160)


def test_locals_are_never_rerouted_and_long_distance_trains_are(net):
    local = _train("LOCAL-1", TrainClass.SUBURBAN_LOCAL)
    express = _train("EXP-1", TrainClass.INTERCITY)
    freight = _train("FRT-1", TrainClass.FREIGHT_MAIL)
    section = net.sections["CLA-GC"]
    occ = [_occ(local, section.id), _occ(express, section.id), _occ(freight, section.id)]

    res = plan_block_reroutes(net, {t.id: t for t in (local, express, freight)},
                              occ, section, start_s=0, end_s=3600)

    moved = {r["train_id"] for r in res.reroutes} | set(res.no_path)
    assert "LOCAL-1" not in moved, "a suburban local must never be offered a reroute"
    assert moved == {"EXP-1", "FRT-1"}
    assert res.locals_in_window == 1


def test_every_reroute_actually_avoids_the_blocked_section(net):
    express = _train("EXP-1", TrainClass.INTERCITY)
    section = net.sections["CLA-GC"]
    res = plan_block_reroutes(net, {express.id: express}, [_occ(express, section.id)],
                              section, start_s=0, end_s=3600)
    assert res.reroutes, "the merged network has an alternate path around this section"
    for r in res.reroutes:
        assert section.id not in r["sections"]
        assert r["added_delay_min"] >= 0


def test_trains_outside_the_block_window_are_left_alone(net):
    express = _train("EXP-1", TrainClass.INTERCITY)
    section = net.sections["CLA-GC"]
    res = plan_block_reroutes(net, {express.id: express}, [_occ(express, section.id)],
                              section, start_s=10_000, end_s=12_000)
    assert res.reroutes == [] and res.no_path == []
