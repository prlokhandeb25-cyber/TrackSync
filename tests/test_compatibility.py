"""Compatibility rules R0-R4 (SPEC §7.2).

The canonical case is the one the domain brief gives verbatim: PWI working the Matunga-Dadar
section while OWD works Matunga station itself must come out COMPATIBLE.
"""

from __future__ import annotations

import pytest

from backend.domain.compatibility import (
    Verdict,
    ZoneRelation,
    compatibility,
    coordination_conflicts,
    matrix,
    zone_relation,
)
from backend.domain.models import WorkZoneKind
from backend.domain.network import build_network
from backend.domain.task import Department, Task, TaskCategory, WorkZone


@pytest.fixture(scope="module")
def net():
    return build_network("central_line")


def section(ref: str) -> WorkZone:
    return WorkZone(kind=WorkZoneKind.SECTION, ref=ref)


def station(ref: str) -> WorkZone:
    return WorkZone(kind=WorkZoneKind.STATION_NODE, ref=ref)


def task(tid: str, dept: Department, zone: WorkZone, ttype: str,
         start_s: int = 3600, dur_min: int = 60, **kw) -> Task:
    return Task(
        id=tid, task_type=ttype, department=dept, zone=zone, duration_min=dur_min,
        scheduled_start_s=start_s, scheduled_end_s=start_s + dur_min * 60, **kw
    )


# --------------------------------------------------------------------- zone geometry


def test_section_and_station_at_its_endpoint_are_adjacent_not_overlapping():
    assert zone_relation(section("DR-MTN"), station("MTN")) is ZoneRelation.ADJACENT


def test_same_zone_detected():
    assert zone_relation(section("DR-MTN"), section("DR-MTN")) is ZoneRelation.SAME_ZONE
    assert zone_relation(station("MTN"), station("MTN")) is ZoneRelation.SAME_ZONE


def test_distant_zones_are_disjoint():
    assert zone_relation(section("DR-MTN"), section("NRL-BVS")) is ZoneRelation.DISJOINT
    assert zone_relation(section("DR-MTN"), station("KJT")) is ZoneRelation.DISJOINT


def test_two_sections_sharing_a_station_are_adjacent():
    assert zone_relation(section("DR-MTN"), section("MTN-SIN")) is ZoneRelation.ADJACENT


# ------------------------------------------------------- R2: the canonical adjacency case


def test_canonical_pwi_section_owd_station_is_compatible(net):
    """PWI on Matunga-Dadar while OWD works Matunga station -> COMPATIBLE."""
    pwi = task("T-PWI", Department.PWI, section("DR-MTN"), "PWI_TAMPING")
    owd = task("T-OWD", Department.OWD, station("MTN"), "OWD_INSULATOR")

    r = compatibility(net, pwi, owd)

    assert r.value is Verdict.COMPATIBLE
    assert r.rule_id == "R2"
    assert r.zone_relation is ZoneRelation.ADJACENT
    assert "MTN" in r.reason and "not physically overlap" in r.reason


def test_canonical_case_is_order_independent(net):
    pwi = task("T-PWI", Department.PWI, section("DR-MTN"), "PWI_TAMPING")
    owd = task("T-OWD", Department.OWD, station("MTN"), "OWD_INSULATOR")
    assert compatibility(net, pwi, owd).value is compatibility(net, owd, pwi).value


def test_disjoint_zones_are_compatible(net):
    a = task("A", Department.PWI, section("CSTM-BY"), "PWI_JOINT")
    b = task("B", Department.S_AND_T, section("VGI-SHLU"), "SNT_TRACK_CIRCUIT")
    r = compatibility(net, a, b)
    assert r.value is Verdict.COMPATIBLE
    assert r.zone_relation is ZoneRelation.DISJOINT


# --------------------------------------------- R1: same zone needs an Integrated Work Permission


def test_same_zone_different_departments_requires_iwp(net):
    a = task("A", Department.PWI, section("GC-TNA"), "PWI_TAMPING")
    b = task("B", Department.OWD, section("GC-TNA"), "OWD_DROPPER")

    r = compatibility(net, a, b)

    assert r.value is Verdict.REQUIRES_IWP
    assert r.rule_id == "R1"
    assert "Integrated Work Permission" in r.reason


def test_requires_iwp_is_a_distinct_status_not_compatible_or_incompatible(net):
    a = task("A", Department.PWI, section("GC-TNA"), "PWI_TAMPING")
    b = task("B", Department.OWD, section("GC-TNA"), "OWD_DROPPER")
    v = compatibility(net, a, b).value
    assert v is not Verdict.COMPATIBLE
    assert v is not Verdict.INCOMPATIBLE


def test_same_zone_same_department_must_be_sequenced(net):
    a = task("A", Department.PWI, section("GC-TNA"), "PWI_TAMPING")
    b = task("B", Department.PWI, section("GC-TNA"), "PWI_BALLAST")
    r = compatibility(net, a, b)
    assert r.value is Verdict.INCOMPATIBLE
    assert "sequenced" in r.reason


# ------------------------------------------------------ R3: non-overlapping time never conflicts


def test_non_overlapping_times_are_compatible_even_in_the_same_zone(net):
    a = task("A", Department.PWI, section("GC-TNA"), "PWI_TAMPING", start_s=3600, dur_min=60)
    b = task("B", Department.OWD, section("GC-TNA"), "OWD_DROPPER", start_s=3600 + 7200, dur_min=60)
    r = compatibility(net, a, b)
    assert r.value is Verdict.COMPATIBLE
    assert "different time slots" in r.reason


def test_unscheduled_tasks_are_treated_as_potentially_overlapping(net):
    a = Task(id="A", task_type="PWI_TAMPING", department=Department.PWI,
             zone=section("GC-TNA"), duration_min=60)
    b = Task(id="B", task_type="OWD_DROPPER", department=Department.OWD,
             zone=section("GC-TNA"), duration_min=60)
    assert compatibility(net, a, b).value is Verdict.REQUIRES_IWP


# ------------------------------------------------------------------- R0: control office allotment


def test_work_outside_the_departments_allotment_is_rejected(net):
    """S&T is not allotted the ghat sections this week."""
    assert "NRL-BVS" not in net.allotments["S_AND_T"]
    snt = task("A", Department.S_AND_T, section("NRL-BVS"), "SNT_TRACK_CIRCUIT")
    other = task("B", Department.PWI, section("CSTM-BY"), "PWI_JOINT")

    r = compatibility(net, snt, other)

    assert r.value is Verdict.INCOMPATIBLE
    assert r.rule_id == "R0"
    assert "not allotted" in r.reason


def test_allotment_is_checked_before_geometry(net):
    """Even two disjoint zones must fail if one of them is outside the allotment."""
    snt = task("A", Department.S_AND_T, section("BVS-KJT"), "SNT_SIGNAL_LAMP")
    pwi = task("B", Department.PWI, section("CSTM-BY"), "PWI_JOINT")
    assert compatibility(net, snt, pwi).rule_id == "R0"


def test_station_node_is_allotted_when_a_touching_section_is(net):
    from backend.domain.compatibility import is_allotted
    assert is_allotted(net, Department.PWI, station("MTN"))


# ---------------------------------------------------------------------------- matrix output


def test_matrix_covers_every_pair_and_carries_reasons(net):
    tasks = [
        task("T1", Department.PWI, section("DR-MTN"), "PWI_TAMPING"),
        task("T2", Department.OWD, station("MTN"), "OWD_INSULATOR"),
        task("T3", Department.S_AND_T, section("DR-MTN"), "SNT_TRACK_CIRCUIT"),
    ]
    m = matrix(net, tasks)

    assert len(m["cells"]) == 3  # 3 choose 2
    assert sum(m["summary"].values()) == 3
    assert all(c["reason"] for c in m["cells"])
    assert all(c["rule_id"] for c in m["cells"])


def test_coordination_conflicts_counts_cross_department_negotiations(net):
    """The count the manual baseline multiplies by its per-conflict negotiation time."""
    tasks = [
        task("T1", Department.PWI, section("DR-MTN"), "PWI_TAMPING"),
        task("T2", Department.OWD, station("MTN"), "OWD_INSULATOR"),   # adjacent -> no conflict
        task("T3", Department.S_AND_T, section("DR-MTN"), "SNT_TRACK_CIRCUIT"),  # same zone as T1
    ]
    # T1xT3 same zone -> IWP; T1xT2 and T2xT3 adjacent -> compatible.
    assert coordination_conflicts(net, tasks) == 1
