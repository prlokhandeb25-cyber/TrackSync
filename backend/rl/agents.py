"""Dispatch policies, in the order they must be built (SPEC §12.1).

<!-- serves: J1 -->

  1. Greedy     - what a simple script does. The floor, and a sanity check on the environment.
  2. BC         - masked cross-entropy on expert actions. If this cannot beat greedy, the
                  state encoding is broken and no amount of Q-learning will rescue it.
  3. CQL-DQN    - the reference paper's approach: offline Q-learning with a conservative
                  penalty so Q-values do not extrapolate wildly on actions the dataset never
                  took. That extrapolation is the specific failure mode offline RL suffers,
                  and the reason plain DQN on logged data tends to look fine in training and
                  collapse in evaluation.

Every policy selects through the legality mask, so none of them can emit an illegal schedule.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn.functional as F

from backend.rl.dataset import Batch, OfflineDataset
from backend.rl.nets import PolicyNet, QNet, apply_mask, masked_log_softmax
# Greedy and random live in policies.py so they can be used without torch present.
from backend.rl.policies import GreedyPolicy, Policy, RandomPolicy  # noqa: F401


class TorchPolicy(Policy):
    def __init__(self, net, name: str):
        self.net = net
        self.name = name

    def act(self, state: np.ndarray, mask: np.ndarray) -> int:
        return int(self.net.act(state, mask))


@dataclass
class TrainLog:
    steps: list[int] = field(default_factory=list)
    loss: list[float] = field(default_factory=list)
    val: list[float] = field(default_factory=list)
    wall_s: float = 0.0
    best_val: float = float("-inf")
    best_step: int = 0


def train_bc(train: OfflineDataset, val: OfflineDataset, steps: int = 8000,
             lr: float = 3e-4, batch_size: int = 256, hidden: int = 256,
             seed: int = 0, log_every: int = 1000) -> tuple[PolicyNet, TrainLog]:
    """Behaviour cloning: masked cross-entropy against the expert's action."""
    torch.manual_seed(seed)
    g = torch.Generator().manual_seed(seed)
    net = PolicyNet(train.state_dim, train.action_dim, hidden)
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    log = TrainLog()
    best_state = None
    t0 = time.time()

    for step in range(1, steps + 1):
        b = train.sample(batch_size, g)
        logp = masked_log_softmax(net(b.state), b.mask)
        loss = F.nll_loss(logp, b.action)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        opt.step()

        if step % log_every == 0 or step == steps:
            acc = _action_accuracy(net, val)
            log.steps.append(step); log.loss.append(float(loss.detach())); log.val.append(acc)
            if acc > log.best_val:
                log.best_val, log.best_step = acc, step
                best_state = {k: v.clone() for k, v in net.state_dict().items()}

    if best_state is not None:
        net.load_state_dict(best_state)
    log.wall_s = time.time() - t0
    return net, log


@torch.no_grad()
def _action_accuracy(net, ds: OfflineDataset, cap: int = 6000) -> float:
    """Share of held-out states where the policy picks the expert's action."""
    n = min(cap, len(ds))
    s, m, a = ds.state[:n], ds.mask[:n], ds.action[:n]
    pred = apply_mask(net(s), m).argmax(dim=-1)
    return float((pred == a).float().mean())


def train_cql_dqn(train: OfflineDataset, val: OfflineDataset, steps: int = 12000,
                  lr: float = 3e-4, batch_size: int = 256, hidden: int = 256,
                  gamma: float = 0.99, alpha: float = 5.0, target_every: int = 500,
                  seed: int = 0, log_every: int = 1000) -> tuple[QNet, TrainLog]:
    """Offline DQN with a Conservative Q-Learning penalty.

    The CQL term pushes down the log-sum-exp of Q over all legal actions while pushing up Q on
    the action the dataset actually took. Without it, Q-values on actions never seen in the
    data drift upward unchecked - and since the policy is an argmax over Q, it then confidently
    selects exactly those unsupported actions at evaluation time.
    """
    torch.manual_seed(seed)
    g = torch.Generator().manual_seed(seed)
    q = QNet(train.state_dim, train.action_dim, hidden)
    q_target = QNet(train.state_dim, train.action_dim, hidden)
    q_target.load_state_dict(q.state_dict())
    opt = torch.optim.Adam(q.parameters(), lr=lr)
    log = TrainLog()
    best_state = None
    t0 = time.time()

    for step in range(1, steps + 1):
        b: Batch = train.sample(batch_size, g)

        with torch.no_grad():
            next_q = apply_mask(q_target(b.next_state), b.next_mask)
            next_v = next_q.max(dim=-1).values
            # A terminal state has no successor value; without this the bootstrap leaks
            # value backwards through the end of every episode.
            target = b.reward + gamma * (1.0 - b.done) * next_v

        all_q = q(b.state)
        taken = all_q.gather(1, b.action.unsqueeze(1)).squeeze(1)
        td_loss = F.smooth_l1_loss(taken, target)

        masked_q = apply_mask(all_q, b.mask)
        logsumexp = torch.logsumexp(masked_q, dim=-1)
        cql_loss = (logsumexp - taken).mean()

        loss = td_loss + alpha * cql_loss
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(q.parameters(), 1.0)
        opt.step()

        if step % target_every == 0:
            q_target.load_state_dict(q.state_dict())

        if step % log_every == 0 or step == steps:
            acc = _action_accuracy(q, val)
            log.steps.append(step); log.loss.append(float(loss.detach())); log.val.append(acc)
            if acc > log.best_val:
                log.best_val, log.best_step = acc, step
                best_state = {k: v.clone() for k, v in q.state_dict().items()}

    if best_state is not None:
        q.load_state_dict(best_state)
    log.wall_s = time.time() - t0
    return q, log
