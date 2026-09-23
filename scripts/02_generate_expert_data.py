from backend.rl.trajectory_gen import ExpertTrajectoryGenerator

def main():
    print("Executing 02_generate_expert_data.py: Solving CP-SAT instances to generate expert trajectories...")
    config_path = "config/network/central_line.yaml"
    gen = ExpertTrajectoryGenerator(config_path, output_dir="data/expert")
    train_p, val_p, test_p = gen.generate_dataset(num_instances=20, seed=42)
    print(f"Expert trajectory dataset generated successfully:\n - {train_p}\n - {val_p}\n - {test_p}")

if __name__ == "__main__":
    main()
