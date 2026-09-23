import os
from backend.data.ingest import TimetableIngester

def main():
    print("Executing 00_fetch_data.py: Ingesting corridor topology and timetable data...")
    config_path = "config/network/central_line.yaml"
    ingester = TimetableIngester(config_path)
    trains = ingester.generate_synthetic_timetable(seed=42)

    os.makedirs("data/processed", exist_ok=True)
    out_path = "data/processed/timetable_central_line.parquet"
    ingester.save_timetable_to_parquet(trains, out_path)
    print(f"Successfully generated structurally faithful timetable with {len(trains)} services. Saved to {out_path}.")

if __name__ == "__main__":
    main()
