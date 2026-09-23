import pytest
from backend.data.ingest import TimetableIngester
from backend.data.validate import ValidationGate

def test_validation_gate_v1_to_v10():
    ingester = TimetableIngester("config/network/central_line.yaml")
    trains = ingester.generate_synthetic_timetable(seed=42)
    gate = ValidationGate(ingester.network)
    is_valid, validated_trains = gate.validate(trains)

    assert is_valid == True
    assert gate.report["summary"]["passed_checks"] == 10
    assert gate.report["summary"]["failed_checks"] == 0
    assert len(validated_trains) > 200
