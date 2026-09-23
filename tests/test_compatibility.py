import pytest
from backend.domain.network import NetworkGraph, Station, Section, StationTier
from backend.domain.task import Task, Department, TaskCategory, WorkZoneType
from backend.domain.compatibility import (
    DepartmentCompatibilityEngine,
    CompatibilityVerdictValue,
    ZoneRelation
)

@pytest.fixture
def sample_network():
    net = NetworkGraph()
    s1 = Station(id="Matunga", name="Matunga", code="MTN", lat=19.0270, lon=72.8550, tier=StationTier.TIER_1)
    s2 = Station(id="Dadar", name="Dadar", code="DR", lat=19.0178, lon=72.8478, tier=StationTier.TIER_1)
    sec = Section(id="SEC_MTN_DR", from_station="Matunga", to_station="Dadar", length_km=2.0, line_speed_kmph=80)
    net.add_station(s1)
    net.add_station(s2)
    net.add_section(sec)
    return net

def test_adjacent_zone_compatibility_matunga_dadar(sample_network):
    """
    Test Rule R2: Canonical test case.
    PWI working Matunga-Dadar section while OWD works Matunga station node -> COMPATIBLE.
    """
    engine = DepartmentCompatibilityEngine(sample_network, allotments=[])

    task_pwi = Task(
        id="TASK_PWI_1",
        department=Department.PWI,
        task_type="rail_renewal",
        section_id="SEC_MTN_DR",
        work_zone_type=WorkZoneType.SECTION,
        work_zone_id="SEC_MTN_DR",
        duration_min=60
    )

    task_owd = Task(
        id="TASK_OWD_1",
        department=Department.OWD,
        task_type="ohe_insulator",
        section_id="SEC_MTN_DR",
        work_zone_type=WorkZoneType.STATION_NODE,
        work_zone_id="Matunga",
        duration_min=45
    )

    verdict = engine.evaluate(task_pwi, task_owd)
    assert verdict.value == CompatibilityVerdictValue.COMPATIBLE
    assert verdict.rule_id == "R2"
    assert verdict.zone_relation == ZoneRelation.ADJACENT
    assert "adjacent zones" in verdict.reason

def test_same_zone_requires_iwp(sample_network):
    """
    Test Rule R1: Same section, PWI and OWD overlapping -> REQUIRES_IWP.
    """
    engine = DepartmentCompatibilityEngine(sample_network, allotments=[])

    task_pwi = Task(
        id="TASK_PWI_2",
        department=Department.PWI,
        task_type="tamping",
        section_id="SEC_MTN_DR",
        work_zone_type=WorkZoneType.SECTION,
        work_zone_id="SEC_MTN_DR",
        duration_min=60
    )

    task_owd = Task(
        id="TASK_OWD_2",
        department=Department.OWD,
        task_type="ohe_tension",
        section_id="SEC_MTN_DR",
        work_zone_type=WorkZoneType.SECTION,
        work_zone_id="SEC_MTN_DR",
        duration_min=60
    )

    verdict = engine.evaluate(task_pwi, task_owd)
    assert verdict.value == CompatibilityVerdictValue.REQUIRES_IWP
    assert verdict.rule_id == "R1"
    assert verdict.zone_relation == ZoneRelation.SAME_ZONE

def test_same_zone_incompatible(sample_network):
    """
    Test Rule R3: PWI and S_AND_T in same section -> INCOMPATIBLE.
    """
    engine = DepartmentCompatibilityEngine(sample_network, allotments=[])

    task_pwi = Task(
        id="TASK_PWI_3",
        department=Department.PWI,
        task_type="weld_renewal",
        section_id="SEC_MTN_DR",
        work_zone_type=WorkZoneType.SECTION,
        work_zone_id="SEC_MTN_DR",
        duration_min=60
    )

    task_snt = Task(
        id="TASK_SNT_1",
        department=Department.S_AND_T,
        task_type="axle_counter",
        section_id="SEC_MTN_DR",
        work_zone_type=WorkZoneType.SECTION,
        work_zone_id="SEC_MTN_DR",
        duration_min=40
    )

    verdict = engine.evaluate(task_pwi, task_snt)
    assert verdict.value == CompatibilityVerdictValue.INCOMPATIBLE
    assert verdict.rule_id == "R3"
