import os
import torch
import pandas as pd
import numpy as np
from torch.utils.data import Dataset, DataLoader
from backend.rl.agents.bc import BehaviorCloningAgent
from backend.rl.agents.cql_dqn import CQLDQNAgent
from backend.rl.agents.awac_a2c import AdvantageWeightedA2CAgent

class ExpertDataset(Dataset):
    def __init__(self, parquet_path: str):
        df = pd.read_parquet(parquet_path)
        self.states = torch.tensor(np.array(df["state"].tolist()), dtype=torch.float32)
        self.actions = torch.tensor(df["action"].values, dtype=torch.long)
        self.rewards = torch.tensor(df["reward"].values, dtype=torch.float32)
        self.next_states = torch.tensor(np.array(df["next_state"].tolist()), dtype=torch.float32)
        self.masks = torch.tensor(np.array(df["mask"].tolist()), dtype=torch.float32)
        self.next_masks = torch.tensor(np.array(df["next_mask"].tolist()), dtype=torch.float32)
        self.dones = torch.tensor(df["done"].values, dtype=torch.bool)

    def __len__(self):
        return len(self.actions)

    def __getitem__(self, idx):
        return (
            self.states[idx],
            self.actions[idx],
            self.rewards[idx],
            self.next_states[idx],
            self.masks[idx],
            self.next_masks[idx],
            self.dones[idx]
        )

def train_all_agents(
    data_dir: str = "data/expert",
    checkpoint_dir: str = "artifacts/checkpoints",
    epochs: int = 10,
    batch_size: int = 128
):
    os.makedirs(checkpoint_dir, exist_ok=True)
    train_ds = ExpertDataset(os.path.join(data_dir, "train.parquet"))
    val_ds = ExpertDataset(os.path.join(data_dir, "val.parquet"))

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)

    bc_agent = BehaviorCloningAgent()
    cql_agent = CQLDQNAgent()
    awac_agent = AdvantageWeightedA2CAgent()

    print(f"Training RL Agents on {len(train_ds)} expert transitions...")

    for epoch in range(epochs):
        bc_losses, cql_losses, awac_losses = [], [], []

        for states, actions, rewards, next_states, masks, next_masks, dones in train_loader:
            bc_l = bc_agent.train_step(states, actions, masks)
            cql_l = cql_agent.train_step(states, actions, rewards, next_states, masks, next_masks, dones)
            awac_l = awac_agent.train_step(states, actions, rewards, next_states, masks, dones)

            bc_losses.append(bc_l)
            cql_losses.append(cql_l)
            awac_losses.append(awac_l)

        cql_agent.update_target_network()
        print(f"Epoch {epoch+1}/{epochs} | BC Loss: {np.mean(bc_losses):.4f} | CQL Loss: {np.mean(cql_losses):.4f} | AWAC Loss: {np.mean(awac_losses):.4f}")

    # Save model checkpoints
    torch.save(bc_agent.model.state_dict(), os.path.join(checkpoint_dir, "bc.pt"))
    torch.save(cql_agent.q_net.state_dict(), os.path.join(checkpoint_dir, "cql_dqn.pt"))
    torch.save(awac_agent.ac.state_dict(), os.path.join(checkpoint_dir, "awac_a2c.pt"))
    print("Model checkpoints saved to artifacts/checkpoints.")

if __name__ == "__main__":
    train_all_agents()
