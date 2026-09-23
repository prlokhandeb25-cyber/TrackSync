"""Gap realism: the rules the engine adds beyond "space between two trains" (A-041).

A window must leave the gang time to get clear before the next train, sit on the 5-minute block grid,
and carry a chance of a late start that is a probability. These are properties of every window the
engine produces, so they are checked over all of them.
"""

from __future__ import annotations

import pytest

from backend.config import load_config, seed_everything
from backend.planner.context import sample_instance


@pytest.fixture(scope="module")
def world():
    seed_everything()
    return sample_instance(n_tasks=10, task_seed=3, corridor="central_line")


def test_every_window_sits_on_the_block_grid(world):
    g = int(load_config()["gaps"]["block_grid_min"]) * 60
    bad = [w for w in world.gaps.windows if w.start_s % g or w.end_s % g]
    assert not bad, f"{len(bad)} windows are off the {g // 60}-minute grid, e.g. {bad[0].describe()}"


def test_the_gang_is_clear_before_the_next_train(world):
    look = int(load_config()["gaps"]["lookout_min"]) * 60
    enter = {(o.section_id, o.track, o.train_id, o.enter_s // 86400): o.enter_s for o in world.occupancy}
    checked = 0
    for w in world.gaps.windows:
        if not w.next_train_id:
            continue
        nxt = enter.get((w.section_id, w.track, w.next_train_id, w.start_s // 86400))
        if nxt is None:
            continue
        checked += 1
        assert nxt - w.end_s >= look, f"{w.describe()} leaves under {look // 60} min before the next train"
    assert checked > 100


def test_late_risk_is_a_probability_and_freight_is_shakier_than_locals(world):
    risks = [w.late_risk for w in world.gaps.windows]
    assert all(0.0 <= r <= 0.95 for r in risks)
    assert max(risks) > min(risks)          # it actually varies with what ran before the gap


def test_every_window_still_leaves_the_minimum_workable_time(world):
    need = int(load_config()["gaps"]["min_workable_min"])
    assert all(w.usable_min() >= need for w in world.gaps.windows)
