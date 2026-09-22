"""Fetch public Indian Railways datasets. Idempotent; skips files already present.

Sources (SPEC §3.2). M-Indicator and RailOne are deliberately NOT attempted: no public API.

  github.com/anandology/railways  — stations (GeoJSON, real coordinates),
                                    trains (routes), schedules (station-by-station times)

What this gives us and what it does not:
  * REAL: station coordinates, and the mail/express timetable traversing the corridor.
  * NOT AVAILABLE: Mumbai suburban EMU timetables and freight paths are in no public source,
    so those layers are synthesised to published structural parameters (ASSUMPTIONS A-007/A-008).
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import REPO_ROOT  # noqa: E402

BASE = "https://raw.githubusercontent.com/anandology/railways/master"
FILES = ["stations.json", "trains.json", "schedules.json"]
RAW = REPO_ROOT / "data" / "raw"


def fetch(force: bool = False) -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for name in FILES:
        dest = RAW / name
        if dest.exists() and not force:
            print(f"  [skip] {name} ({dest.stat().st_size / 1e6:.1f} MB already present)")
            continue
        print(f"  [get ] {name} ...", end="", flush=True)
        try:
            urllib.request.urlretrieve(f"{BASE}/{name}", dest)
            print(f" {dest.stat().st_size / 1e6:.1f} MB")
        except Exception as exc:  # noqa: BLE001
            print(f" FAILED: {exc}")
            print("         Falling back to a fully synthetic timetable (SPEC §3.2). This is a")
            print("         pre-agreed fallback, not an error: run 01_validate.py as normal.")
            return 1
    print(f"\ndone in {time.time() - t0:.1f}s -> {RAW}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    raise SystemExit(fetch(ap.parse_args().force))
