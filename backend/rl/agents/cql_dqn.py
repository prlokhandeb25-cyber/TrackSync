import copy
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from backend.rl.mdp import SchedulingMDP

class QNetwork(nn.Module):
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
        q_vals = self.net(state)
        # Apply strict constraint mask
        masked_q = torch.where(mask > 0.5, q_vals, torch.tensor(-1e9, device=q_vals.device))
        return masked_q

class CQLDQNAgent:
    """
    Offline Conservative Q-Learning (CQL-DQN) agent.
    Reduces overestimation bias on out-of-distribution actions using a logsumexp penalty term.
    """

    def __init__(
        self,
        state_dim: int = SchedulingMDP.STATE_DIM,
        action_dim: int = SchedulingMDP.ACTION_DIM,
        lr: float = 3e-4,
        gamma: float = 0.99,
        cql_alpha: float = 5.0
    ):
        self.q_net = QNetwork(state_dim, action_dim)
        self.target_net = copy.deepcopy(self.q_net)
        self.optimizer = optim.Adam(self.q_net.parameters(), lr=lr)
        self.gamma = gamma
        self.cql_alpha = cql_alpha

    def predict_action(self, state: np.ndarray, action_mask: np.ndarray) -> int:
        self.q_net.eval()
        with torch.no_grad():
            s_tensor = torch.tensor(state, dtype=torch.float32).unsqueeze(0)
            m_tensor = torch.tensor(action_mask, dtype=torch.float32).unsqueeze(0)
            q_vals = self.q_net(s_tensor, m_tensor)
            action = torch.argmax(q_vals, dim=1).item()
        return action

    def train_step(
        self,
        states: torch.Tensor,
        actions: torch.Tensor,
        rewards: torch.Tensor,
        next_states: torch.Tensor,
        masks: torch.Tensor,
        next_masks: torch.Tensor,
        dones: torch.Tensor
    ) -> float:
        self.q_net.train()
        self.optimizer.zero_grad()

        # Current Q values
        current_q = self.q_net(states, masks)
        q_action = current_q.gather(1, actions.unsqueeze(1)).squeeze(1)

        # Target Q values
        with torch.no_grad():
            next_q = self.target_net(next_states, next_masks)
            max_next_q = torch.max(next_q, dim=1)[0]
            target_q = rewards + (1.0 - dones.float()) * self.gamma * max_next_q

        # Standard Bellman TD Error
        td_loss = nn.functional.mse_loss(q_action, target_q)

        # Conservative Q-Learning (CQL) Penalty Term
        cql_penalty = torch.logsumexp(current_q, dim=1).mean() - q_action.mean()
        total_loss = td_loss + self.cql_alpha * cql_penalty

        total_loss.backward()
        self.optimizer.step()

        return float(total_loss.item())

    def update_target_network(self):
        self.target_net.load_state_dict(self.q_net.state_dict())
