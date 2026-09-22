"""Offline dataset loading.

<!-- serves: J1 -->
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from backend.config import REPO_ROOT

EXPERT = REPO_ROOT / "data" / "expert"


@dataclass
class Batch:
    state: torch.Tensor
    action: torch.Tensor
    reward: torch.Tensor
    next_state: torch.Tensor
    mask: torch.Tensor
    next_mask: torch.Tensor
    done: torch.Tensor


class OfflineDataset:
    def __init__(self, split: str):
        path = EXPERT / f"{split}.npz"
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found - run scripts/04_generate_expert_data.py first")
        d = np.load(path)
        self.state = torch.as_tensor(d["state"], dtype=torch.float32)
        self.action = torch.as_tensor(d["action"], dtype=torch.long)
        self.reward = torch.as_tensor(d["reward"], dtype=torch.float32)
        self.next_state = torch.as_tensor(d["next_state"], dtype=torch.float32)
        self.mask = torch.as_tensor(d["mask"], dtype=torch.bool)
        self.next_mask = torch.as_tensor(d["next_mask"], dtype=torch.bool)
        self.done = torch.as_tensor(d["done"], dtype=torch.float32)
        self.instance_id = torch.as_tensor(d["instance_id"], dtype=torch.long)
        self.split = split

        # Normalise rewards to keep the value scale sane for Q-learning. The statistics come
        # from TRAIN only and are reused elsewhere - computing them per split would give each
        # split a different scale and make the numbers incomparable.
        self.reward_mean = float(self.reward.mean())
        self.reward_std = float(self.reward.std().clamp(min=1e-6))

    def __len__(self) -> int:
        return int(self.state.shape[0])

    @property
    def state_dim(self) -> int:
        return int(self.state.shape[1])

    @property
    def action_dim(self) -> int:
        return int(self.mask.shape[1])

    def normalise_with(self, mean: float, std: float) -> None:
        self.reward = (self.reward - mean) / std

    def sample(self, batch_size: int, generator: torch.Generator | None = None) -> Batch:
        idx = torch.randint(0, len(self), (batch_size,), generator=generator)
        return Batch(
            self.state[idx], self.action[idx], self.reward[idx], self.next_state[idx],
            self.mask[idx], self.next_mask[idx], self.done[idx],
        )

    def full(self) -> Batch:
        return Batch(self.state, self.action, self.reward, self.next_state,
                     self.mask, self.next_mask, self.done)

    def describe(self) -> str:
        n_inst = int(self.instance_id.unique().numel())
        return (f"{self.split}: {len(self):,} transitions from {n_inst} instances, "
                f"state {self.state_dim}, actions {self.action_dim}")
