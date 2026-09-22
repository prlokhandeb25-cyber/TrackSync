"""Adapters onto the Indian Railways systems this prototype would plug into.

<!-- serves: J4 -->

    PWI  track & gearing        <- TMS   Track Management System
    S&T  signalling & telecom   <- SMMS  Signalling Maintenance Management System
    OWD  overhead equipment     <- TDMS  Traction Distribution Management System

    plan  -> BDMS  Block Demand Management System   (our plan is submitted as block demands)
    live  <- COA   Control Office Application       (actual running closes the loop)

This system is the planning brain BETWEEN systems Indian Railways already runs. It is not a
replacement for any of them: the three departments whose coordination it automates map
one-to-one onto three systems that already hold their records.

IMPORTANT, and stated plainly because it would be easy to imply otherwise: these are internal
IR systems with no public API. Every payload shape below is our best-effort assumption pending
access, not documented interface. The mock implementations read this prototype's own data so
the boundary is real and exercised, and switching `adapters.mode` to "live" is the only change
a real integration would need on this side.
"""

from backend.adapters.base import (
    AdapterInfo,
    BDMSAdapter,
    COAAdapter,
    SMMSAdapter,
    TDMSAdapter,
    TMSAdapter,
    all_adapters,
    registry,
)

__all__ = [
    "AdapterInfo", "BDMSAdapter", "COAAdapter", "SMMSAdapter", "TDMSAdapter",
    "TMSAdapter", "all_adapters", "registry",
]
