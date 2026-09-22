"""P7 driver: train the offline policies and save them."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch  # noqa: E402

from backend.config import REPO_ROOT, load_config, seed_everything  # noqa: E402
from backend.rl.agents import train_bc, train_cql_dqn  # noqa: E402
from backend.rl.dataset import OfflineDataset  # noqa: E402

OUT = REPO_ROOT / "artifacts" / "models"


def main() -> int:
    seed = seed_everything()
    cfg = load_config()["rl"]
    OUT.mkdir(parents=True, exist_ok=True)

    train = OfflineDataset("train")
    val = OfflineDataset("val")
    print(train.describe())
    print(val.describe())

    # Reward normalisation statistics come from TRAIN only, and the same numbers are applied
    # to val. Normalising each split by its own statistics would give them different scales.
    mean, std = train.reward_mean, train.reward_std
    train.normalise_with(mean, std)
    val.normalise_with(mean, std)
    print(f"reward normalised with train statistics: mean {mean:.2f}, std {std:.2f}\n")

    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    print("training behaviour cloning ...")
    bc, bc_log = train_bc(train, val, steps=steps, lr=float(cfg["lr"]),
                          batch_size=int(cfg["batch_size"]), hidden=int(cfg["hidden_dim"]),
                          seed=seed)
    print(f"  best expert-action agreement {bc_log.best_val:.3f} at step {bc_log.best_step} "
          f"({bc_log.wall_s:.0f}s)")
    torch.save({"state_dict": bc.state_dict(), "state_dim": train.state_dim,
                "action_dim": train.action_dim, "hidden": int(cfg["hidden_dim"])},
               OUT / "bc.pt")

    print("\ntraining CQL-DQN ...")
    q, q_log = train_cql_dqn(train, val, steps=int(steps * 1.5), lr=float(cfg["lr"]),
                             batch_size=int(cfg["batch_size"]), hidden=int(cfg["hidden_dim"]),
                             alpha=float(cfg["cql_alpha"]), seed=seed)
    print(f"  best expert-action agreement {q_log.best_val:.3f} at step {q_log.best_step} "
          f"({q_log.wall_s:.0f}s)")
    torch.save({"state_dict": q.state_dict(), "state_dim": train.state_dim,
                "action_dim": train.action_dim, "hidden": int(cfg["hidden_dim"])},
               OUT / "cql_dqn.pt")

    with open(OUT / "training_log.json", "w", encoding="utf-8") as fh:
        json.dump({
            "seed": seed,
            "train_transitions": len(train), "val_transitions": len(val),
            "reward_mean": mean, "reward_std": std,
            "bc": {"steps": bc_log.steps, "loss": bc_log.loss, "val_agreement": bc_log.val,
                   "best": bc_log.best_val, "best_step": bc_log.best_step,
                   "wall_s": round(bc_log.wall_s, 1)},
            "cql_dqn": {"steps": q_log.steps, "loss": q_log.loss, "val_agreement": q_log.val,
                        "best": q_log.best_val, "best_step": q_log.best_step,
                        "wall_s": round(q_log.wall_s, 1), "alpha": float(cfg["cql_alpha"])},
        }, fh, indent=2)
    print(f"\nsaved models and training_log.json to {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
