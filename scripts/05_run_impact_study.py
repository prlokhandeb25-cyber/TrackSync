from backend.data.ingest import TimetableIngester
from backend.data.synth_tasks import TaskGenerator
from backend.gaps.gap_engine import TrafficGapEngine
from backend.metrics.impact_harness import ImpactMetricsHarness

def main():
    print("Executing 05_run_impact_study.py: Running Before/After operational impact study...")
    config_path = "config/network/central_line.yaml"
    ingester = TimetableIngester(config_path)
    trains = ingester.generate_synthetic_timetable(seed=42)
    tasks = TaskGenerator.generate_weekly_planned_tasks(ingester.network, num_tasks=35, seed=42)

    gap_engine = TrafficGapEngine(ingester.network)
    windows = gap_engine.find_candidate_windows(trains)

    harness = ImpactMetricsHarness(ingester.network)
    metrics = harness.run_impact_study(tasks, windows, output_dir="artifacts")

    print("Impact study complete. Emitted artifacts/metrics.json and artifacts/impact_comparison.csv.")

if __name__ == "__main__":
    main()
