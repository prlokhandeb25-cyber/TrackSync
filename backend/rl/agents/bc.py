import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from backend.rl.mdp import SchedulingMDP

class BehaviorCloningNet(nn.Module):
    def __init__(self, state_dim: int = SchedulingMDP.STATE_DIM, action_dim: int = SchedulingMDP.ACTION_DIM):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, 256),
            nn.ReLU(),
            nn.LayerNorm(256),
            nn.Linear(256, 256),
            nn.ReLU(),
            nn.LayerNorm(256),
            nn.Linear(256, action_dim)
        )

    def forward(self, state: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        logits = self.net(state)
        # Apply strict constraint masking: set invalid action logits to -inf
        masked_logits = torch.where(mask > 0.5, logits, torch.tensor(-1e9, device=logits.device))
        return masked_logits

class BehaviorCloningAgent:
    def __init__(self, state_dim: int = SchedulingMDP.STATE_DIM, action_dim: int = SchedulingMDP.ACTION_DIM, lr: float = 3e-4):
        self.model = BehaviorCloningNet(state_dim, action_dim)
        self.optimizer = optim.Adam(self.model.parameters(), lr=lr)
        self.criterion = nn.CrossEntropyLoss()

    def predict_action(self, state: np.ndarray, action_mask: np.ndarray) -> int:
        self.model.eval()
        with torch.no_grad():
            s_tensor = torch.tensor(state, dtype=torch.float32).unsqueeze(0)
            m_tensor = torch.tensor(action_mask, dtype=torch.float32).unsqueeze(0)
            logits = self.model(s_tensor, m_tensor)
            action = torch.argmax(logits, dim=1).item()
        return action

    def train_step(self, states: torch.Tensor, actions: torch.Tensor, masks: torch.Tensor) -> float:
        self.model.train()
        self.optimizer.zero_grad()
        logits = self.model(states, masks)
        loss = self.criterion(logits, actions)
        loss.backward()
        self.optimizer.step()
        return float(loss.item())
