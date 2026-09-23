from backend.rl.evaluate import evaluate_agents

def main():
    print("Executing 04_evaluate_rl.py: Evaluating RL agents on held-out test data...")
    df_results = evaluate_agents(test_path="data/expert/test.parquet", checkpoint_dir="artifacts/checkpoints", output_csv="artifacts/rl_comparison.csv")
    print("RL evaluation completed. Output saved to artifacts/rl_comparison.csv.")

if __name__ == "__main__":
    main()
