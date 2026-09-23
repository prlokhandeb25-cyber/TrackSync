from backend.rl.train import train_all_agents

def main():
    print("Executing 03_train_rl.py: Training BC, CQL-DQN, and AWAC-A2C agents...")
    train_all_agents(data_dir="data/expert", checkpoint_dir="artifacts/checkpoints", epochs=5)
    print("RL training completed.")

if __name__ == "__main__":
    main()
