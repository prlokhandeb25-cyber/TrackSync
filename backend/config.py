"""Configuration loading and global seeding.

One SEED, threaded everywhere (CLAUDE.md invariant: reproducibility).
"""

from __future__ import annotations

import random
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"
NETWORK_DIR = REPO_ROOT / "config" / "network"


class Config(dict):
    """dict with dotted access: cfg.get_path('gaps.block_setup_min')."""

    def get_path(self, dotted: str, default: Any = None) -> Any:
        node: Any = self
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, dotted: str) -> Path:
        """Resolve a config value that names a repo-relative directory."""
        return REPO_ROOT / str(self.get_path(dotted))


@lru_cache(maxsize=1)
def load_config(path: Path | None = None) -> Config:
    with open(path or CONFIG_PATH, "r", encoding="utf-8") as fh:
        return Config(yaml.safe_load(fh))


def seed_everything(seed: int | None = None) -> int:
    """Seed random and numpy. torch is seeded in backend/rl once it is installed (P7)."""
    if seed is None:
        seed = int(load_config()["seed"])
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))
    # Torch seeding is best-effort. It is absent before P7, and on Windows it can also fail
    # to initialise its DLLs under memory pressure. Neither should be able to take down the
    # data pipeline, which does not need torch at all.
    try:
        import torch

        torch.manual_seed(seed)
    except Exception:  # noqa: BLE001 - deliberately broad; torch is optional here
        pass
    return seed


def load_network_config(corridor: str) -> dict:
    """Load one corridor definition. Adding a corridor = adding a file here (SPEC §4)."""
    with open(NETWORK_DIR / f"{corridor}.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def all_corridors() -> list[str]:
    return list(load_config()["corridors"])
