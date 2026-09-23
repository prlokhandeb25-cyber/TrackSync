import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from typing import Tuple
from backend.rl.mdp import SchedulingMDP

class ActorCriticNet(nn.Module):
    def __init__(self, state_dim: int = SchedulingMDP.STATE_DIM, action_dim: int = SchedulingMDP.ACTION_DIM):
        super().__init__()
        self.actor = nn.Sequential(
            nn.Linear(state_dim, 256),
            nn.ReLU(),
            nn.LayerNorm(256),
            nn.Linear(256, action_dim)
        )
        self.critic = nn.Sequential(
            nn.Linear(state_dim, 256),
            nn.ReLU(),
            nn.LayerNorm(256),
            nn.Linear(256, 1)
        )

    def forward(self, state: torch.Tensor, mask: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        logits = self.actor(state)
        masked_logits = torch.where(mask > 0.5, logits, torch.tensor(-1e9, device=logits.device))
        val = self.critic(state)
        return masked_logits, val

class AdvantageWeightedA2CAgent:
    """
    Offline-adapted Advantage-Weighted Actor-Critic (AWAC-A2C) agent.
    Learns state-value baseline and weights dataset action log-likelihoods by empirical advantage.
    """

    def __init__(self, state_dim: int = SchedulingMDP.STATE_DIM, action_dim: int = SchedulingMDP.ACTION_DIM, lr: float = 3e-4):
        self.ac = ActorCriticNet(state_dim, action_dim)
        self.optimizer = optim.Adam(self.ac.parameters(), lr=lr)

    def predict_action(self, state: np.ndarray, action_mask: np.ndarray) -> int:
        self.ac.eval()
        with torch.no_grad():
            s_tensor = torch.tensor(state, dtype=torch.float32).unsqueeze(0)
            m_tensor = torch.tensor(action_mask, dtype=torch.float32).unsqueeze(0)
            logits, _ = self.ac(s_tensor, m_tensor)
            action = torch.argmax(logits, dim=1).item()
        return action

    def train_step(self, states: torch.Tensor, actions: torch.Tensor, rewards: torch.Tensor, next_states: torch.Tensor, masks: torch.Tensor, dones: torch.Tensor) -> float:
        self.ac.train()
        self.optimizer.zero_grad()

        logits, values = self.ac(states, masks)
        _, next_values = self.ac(next_states, masks)

        values = values.squeeze(1)
        next_values = next_values.squeeze(1)

        targets = rewards + (1.0 - dones.float()) * 0.99 * next_values
        advantage = (targets - values).detach()

        dist = torch.distributions.Categorical(logits=logits)
        log_prob = dist.log_prob(actions)

        policy_loss = -(torch.exp(advantage.clamp(max=20.0) / 2.0) * log_prob).mean()
        value_loss = nn.functional.mse_loss(values, targets)

        total_loss = policy_loss + 0.5 * value_loss
        total_loss.backward()
        self.optimizer.step()

        return float(total_loss.item())
