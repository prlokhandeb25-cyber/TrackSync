import sys
import argparse
from backend.data.ingest import TimetableIngester
from backend.data.validate import ValidationGate

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Force execution even if validation fails")
    args = parser.parse_args()

    print("Executing 01_validate.py: Running Validation Gate (V1-V10 checks)...")
    config_path = "config/network/central_line.yaml"
    ingester = TimetableIngester(config_path)
    trains = ingester.generate_synthetic_timetable(seed=42)

    gate = ValidationGate(ingester.network)
    is_valid, validated_trains = gate.validate(trains)

    gate.save_reports("data/validation_report.json", "data/validation_report.md")

    print(f"Validation Gate Complete: Passed {gate.report['summary']['passed_checks']}/10 checks.")
    print(f"Auto-Repairs Logged: {gate.report['summary']['repairs_made']}")

    if not is_valid and not args.force:
        print("ERROR: Validation Gate reported FAIL. Exiting script. Pass --force to bypass.")
        sys.exit(1)

if __name__ == "__main__":
    main()
