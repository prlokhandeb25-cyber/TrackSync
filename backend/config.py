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
    """Seed random and numpy. Deliberately does NOT touch torch — see seed_torch below."""
    if seed is None:
        seed = int(load_config()["seed"])
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))
    return seed


def seed_torch(seed: int | None = None) -> int:
    """Seed torch. Call this from RL code only, never from the shared pipeline.

    This used to live inside seed_everything, guarded by try/except. That guard was useless:
    on a memory-constrained Windows box torch's DLL initialisation does not raise a Python
    exception, it takes an ACCESS VIOLATION at the native level, which no `except` can catch.
    Every ingest, validation and planning run was therefore importing torch and quietly
    gambling on a hard crash, for a framework none of them use.

    Keeping torch out of the shared import path is the actual fix. RL modules already import
    it directly and seed it in their training loops, so nothing that needs the seed loses it.
    """
    if seed is None:
        seed = int(load_config()["seed"])
    import torch

    torch.manual_seed(seed)
    return seed


def load_network_config(corridor: str) -> dict:
    """Load one corridor definition. Adding a corridor = adding a file here (SPEC §4)."""
    with open(NETWORK_DIR / f"{corridor}.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def all_corridors() -> list[str]:
    return list(load_config()["corridors"])
