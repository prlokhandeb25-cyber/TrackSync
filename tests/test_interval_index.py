"""The augmented interval tree must agree with the existing dict-bucket index exactly.

This is a pure performance upgrade (backend/planner/interval_index.py) sitting alongside the
existing WindowIndex (backend/planner/cpsat.py) — every call site of the old index is untouched.
The only thing worth testing is that the new index answers the same question with the same
answer, since disagreeing would silently change which windows a task is allowed to use.
"""

from __future__ import annotations

import pytest

from backend.config import seed_everything
from backend.domain.models import WorkZoneKind
from backend.planner.context import sample_instance
from backend.planner.cpsat import build_window_index, eligible_windows
from backend.planner.interval_index import build_interval_index


@pytest.fixture(scope="module")
def world():
    seed_everything()
    return sample_instance(n_tasks=40, task_seed=7, corridor="central_line")


def test_interval_index_matches_dict_index_for_every_task(world):
    dict_index = build_window_index(world.windows)
    tree_index = build_interval_index(world.windows)

    for t in world.tasks:
        dict_result = {w.id for w in eligible_windows(t, world.windows, dict_index)}
        tree_result = {w.id for w in tree_index.eligible(t)}
        assert tree_result == dict_result, f"mismatch for task {t.id}"


def test_free_in_returns_only_overlapping_windows_for_the_right_zone(world):
    tree_index = build_interval_index(world.windows)
    some_section = next(iter(world.net.sections))
    windows_here = [w for w in world.windows if w.zone_ref == some_section]
    assert windows_here, "fixture should have at least one window on this section"

    lo = min(w.start_s for w in windows_here)
    hi = max(w.end_s for w in windows_here)
    hits = tree_index.free_in(some_section, WorkZoneKind.SECTION, lo, hi)

    assert hits, "the query range was built from these windows, so it must find them"
    for w in hits:
        assert w.zone_ref == some_section
        assert w.start_s < hi and lo < w.end_s


def test_free_in_is_empty_outside_every_windows_range(world):
    tree_index = build_interval_index(world.windows)
    some_section = next(iter(world.net.sections))
    far_future = 10 ** 9
    assert tree_index.free_in(
        some_section, WorkZoneKind.SECTION, far_future, far_future + 3600
    ) == []
