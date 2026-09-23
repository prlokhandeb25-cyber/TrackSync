"""Torch-free dispatch policies.

<!-- serves: J1, J2 -->

Separated from agents.py deliberately. The greedy and random baselines are pure numpy, and the
impact harness and API only need those; importing them should not drag in a deep-learning
framework. Beyond being tidy, this keeps the demo alive on a memory-constrained machine, where
torch can fail to initialise its DLLs entirely — the before/after numbers and the whole map
still work without it.

agents.py imports these and adds the torch-backed policies and the training loops on top.
"""

from __future__ import annotations

import numpy as np

from backend.rl.mdp import N_GAP_CHOICES, GapChoice, noop_index


class Policy:
    name = "policy"

    def act(self, state: np.ndarray, mask: np.ndarray) -> int:
        raise NotImplementedError


class GreedyPolicy(Policy):
    """Earliest feasible window, highest priority first.

    Task slots are already ranked by (priority, age, due date), so "highest priority first" is
    simply the lowest legal slot. Preferring EARLIEST within that slot is the naive choice a
    dispatcher without a model would make, which is exactly what makes it the right floor to
    measure the learned policies against.
    """

    name = "greedy"

    def act(self, state: np.ndarray, mask: np.ndarray) -> int:
        legal = np.flatnonzero(mask)
        legal = legal[legal != noop_index()]
        if legal.size == 0:
            return noop_index()
        best_slot = legal[0] // N_GAP_CHOICES
        same = legal[legal // N_GAP_CHOICES == best_slot]
        prefer = best_slot * N_GAP_CHOICES + int(GapChoice.EARLIEST)
        return int(prefer if prefer in same else same[0])


class RandomPolicy(Policy):
    """Uniform over legal actions. Not a serious contender - it is the zero point."""

    name = "random"

    def __init__(self, seed: int = 0):
        self.rng = np.random.default_rng(seed)

    def act(self, state: np.ndarray, mask: np.ndarray) -> int:
        legal = np.flatnonzero(mask)
        return int(self.rng.choice(legal)) if legal.size else noop_index()


_BEST: tuple[Policy, str] | None = None


def load_best_policy(quiet: bool = True) -> tuple[Policy, str]:
    """Cached: importing torch and loading weights costs seconds, and this is called per request."""
    global _BEST
    if _BEST is None:
        _BEST = _load_best_policy(quiet)
    return _BEST


def _load_best_policy(quiet: bool = True) -> tuple[Policy, str]:
    """The best dispatcher available right now, and a plain note about which one it is.

    Returns greedy when torch or the trained weights are unavailable, rather than failing.
    The caller shows the note, so a fallback is always visible rather than silently changing
    what the numbers mean.
    """
    from backend.config import REPO_ROOT

    path = REPO_ROOT / "artifacts" / "models" / "cql_dqn.pt"
    if not path.exists():
        return GreedyPolicy(), "greedy heuristic (no trained model found)"
    try:
        import torch

        from backend.rl.agents import TorchPolicy
        from backend.rl.nets import QNet

        blob = torch.load(path, map_location="cpu", weights_only=True)
        net = QNet(blob["state_dim"], blob["action_dim"], blob["hidden"])
        net.load_state_dict(blob["state_dict"])
        net.eval()
        return TorchPolicy(net, "CQL-DQN"), "CQL-DQN (trained offline on CP-SAT trajectories)"
    except Exception as exc:  # noqa: BLE001 - torch is optional at runtime
        if not quiet:
            print(f"  torch unavailable ({type(exc).__name__}); falling back to greedy")
        return GreedyPolicy(), "greedy heuristic (torch unavailable on this machine)"
