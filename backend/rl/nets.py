"""Networks and masked action selection.

<!-- serves: J1 -->

Every head here applies the legality mask before softmax or argmax. Illegal actions are set
to -inf, so an illegal schedule is not merely discouraged, it is unrepresentable. That is what
makes the constraint-violation rate zero by construction rather than by training luck.
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

NEG_INF = -1e9


def mlp(in_dim: int, out_dim: int, hidden: int = 256, depth: int = 2) -> nn.Sequential:
    layers: list[nn.Module] = []
    d = in_dim
    for _ in range(depth):
        layers += [nn.Linear(d, hidden), nn.LayerNorm(hidden), nn.ReLU()]
        d = hidden
    layers.append(nn.Linear(d, out_dim))
    return nn.Sequential(*layers)


def apply_mask(logits: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Set illegal actions to -inf. `mask` is True where an action is legal."""
    return logits.masked_fill(~mask.bool(), NEG_INF)


def masked_argmax(logits: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return apply_mask(logits, mask).argmax(dim=-1)


def masked_log_softmax(logits: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return torch.log_softmax(apply_mask(logits, mask), dim=-1)


class PolicyNet(nn.Module):
    """Categorical policy over the masked action space (used for behaviour cloning)."""

    def __init__(self, state_dim: int, action_dim: int, hidden: int = 256):
        super().__init__()
        self.net = mlp(state_dim, action_dim, hidden)

    def forward(self, s: torch.Tensor) -> torch.Tensor:
        return self.net(s)

    @torch.no_grad()
    def act(self, state: np.ndarray, mask: np.ndarray) -> int:
        s = torch.as_tensor(state, dtype=torch.float32).unsqueeze(0)
        m = torch.as_tensor(mask, dtype=torch.bool).unsqueeze(0)
        return int(masked_argmax(self.forward(s), m).item())


class QNet(nn.Module):
    """Action-value network (used for CQL-regularised DQN)."""

    def __init__(self, state_dim: int, action_dim: int, hidden: int = 256):
        super().__init__()
        self.net = mlp(state_dim, action_dim, hidden)

    def forward(self, s: torch.Tensor) -> torch.Tensor:
        return self.net(s)

    @torch.no_grad()
    def act(self, state: np.ndarray, mask: np.ndarray) -> int:
        s = torch.as_tensor(state, dtype=torch.float32).unsqueeze(0)
        m = torch.as_tensor(mask, dtype=torch.bool).unsqueeze(0)
        return int(masked_argmax(self.forward(s), m).item())
