# Data Validation Report

**Overall: FAIL** — 8/10 checks passed, 2035 repair(s) applied.

Corridor `central_line` · generated 2026-09-22T19:41:44+00:00

## Provenance

- Services total: **620**
- From real published data: **197** (31.8%)
- Synthesised (no public source): **423**

| Class | Count | Source |
|---|---:|---|
| INTERCITY | 197 | real — public schedules dataset |
| SUBURBAN_LOCAL | 374 | synthesised (A-007) |
| FREIGHT_MAIL | 49 | synthesised (A-008) |

All station coordinates and all section lengths derive from real published data.

## Checks

| ID | Check | Status | Detail |
|---|---|---|---|
| V1 | Monotonic stop times | **PASS** | 0 service(s) dropped as irreconcilable; 620 retained |
| V2 | Midnight wrap day-indexing | **PASS** | 17 service(s) cross midnight, all correctly day-indexed |
| V3 | Dwell time sanity | **PASS** | 1115 dwell(s) clipped into [20s, 1200s] |
| V4 | Implied run-time sanity | **WARN** | 8 section hop(s) imply an impossible speed |
| V5 | No impossible train overlaps | **FAIL** | 379 sub-headway conflict(s) at 120s minimum (6.62% of 5,727 traversals; WARN threshold 0.5%) |
| V6 | Referential integrity | **PASS** | 0 stop(s) reference an unknown station |
| V7 | Corridor coverage | **PASS** | 620 services/day across 16 sections |
| V8 | Section geometry present | **PASS** | 0 section(s) lack endpoint coordinates |
| V9 | Train origin/destination integrity | **PASS** | 0 train(s) lack a valid origin, destination or >=2 stops |
| V10 | Occupancy/gap conservation | **PASS** | 0 track-day(s) fail busy+idle==24h |

## Simulation fidelity (SPEC §3.5)

**FAIL** — 620/620 trains complete, 379 conflict(s), mean arrival deviation 0.0s.

## Derived station tiers (SPEC §8.1)

Derived by frequency quantile from the data, never hardcoded by name.

| Station | Services/day | Peak trains/hr | Derived tier | Config expected |
|---|---:|---:|---|---|
| Mumbai CSMT (CSTM) | 500 | 41 | **TIER_2** | TIER_1  <- differs |
| Byculla (BY) | 500 | 40 | **TIER_2** | TIER_2 |
| Dadar (DR) | 511 | 39 | **TIER_1** | TIER_1 |
| Matunga (MTN) | 511 | 40 | **TIER_1** | TIER_2  <- differs |
| Sion (SIN) | 511 | 39 | **TIER_1** | TIER_2  <- differs |
| Kurla Jn (CLA) | 511 | 37 | **TIER_1** | TIER_1 |
| Ghatkopar (GC) | 580 | 40 | **TIER_1** | TIER_2  <- differs |
| Thane (TNA) | 580 | 44 | **TIER_1** | TIER_1 |
| Dombivli (DI) | 516 | 37 | **TIER_1** | TIER_2  <- differs |
| Kalyan Jn (KYN) | 484 | 35 | **TIER_2** | TIER_1  <- differs |
| Ambernath (ABH) | 198 | 20 | **TIER_2** | TIER_2 |
| Badlapur (BUD) | 173 | 20 | **TIER_3** | TIER_2  <- differs |
| Vangani (VGI) | 155 | 18 | **TIER_3** | TIER_3 |
| Shelu (SHLU) | 155 | 18 | **TIER_3** | TIER_3 |
| Neral Jn (NRL) | 155 | 19 | **TIER_3** | TIER_3 |
| Bhivpuri Road (BVS) | 155 | 20 | **TIER_3** | TIER_3 |
| Karjat Jn (KJT) | 155 | 18 | **TIER_3** | TIER_2  <- differs |

Tier disagreements (derived value wins):

- CSTM (Mumbai CSMT): derived TIER_2 but config expected TIER_1 — 500 services/day, thresholds q1=511 q3=188
- MTN (Matunga): derived TIER_1 but config expected TIER_2 — 511 services/day, thresholds q1=511 q3=188
- SIN (Sion): derived TIER_1 but config expected TIER_2 — 511 services/day, thresholds q1=511 q3=188
- GC (Ghatkopar): derived TIER_1 but config expected TIER_2 — 580 services/day, thresholds q1=511 q3=188
- DI (Dombivli): derived TIER_1 but config expected TIER_2 — 516 services/day, thresholds q1=511 q3=188
- KYN (Kalyan Jn): derived TIER_2 but config expected TIER_1 — 484 services/day, thresholds q1=511 q3=188
- BUD (Badlapur): derived TIER_3 but config expected TIER_2 — 173 services/day, thresholds q1=511 q3=188
- KJT (Karjat Jn): derived TIER_3 but config expected TIER_2 — 155 services/day, thresholds q1=511 q3=188

## Repairs applied (first 20)

| Check | Target | Action |
|---|---|---|
| V3 | `R-12071@BY` | dwell 0s clipped up to 20s |
| V3 | `R-12071@MTN` | dwell 0s clipped up to 20s |
| V3 | `R-12071@SIN` | dwell 0s clipped up to 20s |
| V3 | `R-12071@CLA` | dwell 0s clipped up to 20s |
| V3 | `R-12071@GC` | dwell 0s clipped up to 20s |
| V3 | `R-12071@DI` | dwell 0s clipped up to 20s |
| V3 | `R-16381@BY` | dwell 0s clipped up to 20s |
| V3 | `R-16381@MTN` | dwell 0s clipped up to 20s |
| V3 | `R-16381@SIN` | dwell 0s clipped up to 20s |
| V3 | `R-16381@CLA` | dwell 0s clipped up to 20s |
| V3 | `R-16381@GC` | dwell 0s clipped up to 20s |
| V3 | `R-16381@TNA` | dwell 0s clipped up to 20s |
| V3 | `R-16381@DI` | dwell 0s clipped up to 20s |
| V3 | `R-16381@ABH` | dwell 0s clipped up to 20s |
| V3 | `R-16381@BUD` | dwell 0s clipped up to 20s |
| V3 | `R-16381@VGI` | dwell 0s clipped up to 20s |
| V3 | `R-16381@SHLU` | dwell 0s clipped up to 20s |
| V3 | `R-16381@NRL` | dwell 0s clipped up to 20s |
| V3 | `R-16381@BVS` | dwell 0s clipped up to 20s |
| V3 | `R-15102@BY` | dwell 0s clipped up to 20s |
