# Data Validation Report

**Overall: FAIL** — 8/10 checks passed, 5065 repair(s) applied.

Corridor `mumbai` · generated 2026-09-22T21:14:41+00:00

## Provenance

- Services total: **1,640**
- From real published data: **429** (26.2%)
- Synthesised (no public source): **1,211**

| Class | Count | Source |
|---|---:|---|
| INTERCITY | 429 | real — public schedules dataset |
| SUBURBAN_LOCAL | 1,112 | synthesised (A-007) |
| FREIGHT_MAIL | 99 | synthesised (A-008) |

All station coordinates and all section lengths derive from real published data.

## Checks

| ID | Check | Status | Detail |
|---|---|---|---|
| V1 | Monotonic stop times | **PASS** | 0 service(s) dropped as irreconcilable; 1640 retained |
| V2 | Midnight wrap day-indexing | **PASS** | 48 service(s) cross midnight, all correctly day-indexed |
| V3 | Dwell time sanity | **PASS** | 2892 dwell(s) clipped into [20s, 1200s] |
| V4 | Implied run-time sanity | **FAIL** | 135 of 22,207 section hops imply an impossible speed (0.61%; WARN threshold 0.5%) |
| V5 | No impossible train overlaps | **FAIL** | 1050 sub-headway conflict(s) at 120s minimum (4.60% of 22,821 traversals; WARN threshold 0.5%) |
| V6 | Referential integrity | **PASS** | 0 stop(s) reference an unknown station |
| V7 | Corridor coverage | **PASS** | 1640 services/day across 74 sections |
| V8 | Section geometry present | **PASS** | 0 section(s) lack endpoint coordinates |
| V9 | Train origin/destination integrity | **PASS** | 0 train(s) lack a valid origin, destination or >=2 stops |
| V10 | Occupancy/gap conservation | **PASS** | 0 track-day(s) fail busy+idle==24h |

## Simulation fidelity (SPEC §3.5)

**FAIL** — 1640/1640 trains complete, 1050 conflict(s), mean arrival deviation 0.0s.

## Derived station tiers (SPEC §8.1)

Derived by frequency quantile from the data, never hardcoded by name.

| Station | Services/day | Peak trains/hr | Derived tier | Config expected |
|---|---:|---:|---|---|
| Mumbai CSMT (CSTM) | 825 | 62 | **TIER_1** | TIER_1 |
| Byculla (BY) | 500 | 40 | **TIER_1** | TIER_2  <- differs |
| Dadar (DR) | 511 | 39 | **TIER_1** | TIER_1 |
| Matunga (MTN) | 511 | 40 | **TIER_1** | TIER_2  <- differs |
| Sion (SIN) | 511 | 39 | **TIER_1** | TIER_2  <- differs |
| Kurla Jn (CLA) | 836 | 59 | **TIER_1** | TIER_1 |
| Ghatkopar (GC) | 580 | 40 | **TIER_1** | TIER_2  <- differs |
| Thane (TNA) | 705 | 54 | **TIER_1** | TIER_1 |
| Dombivli (DI) | 516 | 37 | **TIER_1** | TIER_2  <- differs |
| Kalyan Jn (KYN) | 484 | 35 | **TIER_1** | TIER_1 |
| Ambernath (ABH) | 198 | 20 | **TIER_3** | TIER_2  <- differs |
| Badlapur (BUD) | 173 | 20 | **TIER_3** | TIER_2  <- differs |
| Vangani (VGI) | 155 | 18 | **TIER_3** | TIER_3 |
| Shelu (SHLU) | 155 | 18 | **TIER_3** | TIER_3 |
| Neral Jn (NRL) | 155 | 19 | **TIER_3** | TIER_3 |
| Bhivpuri Road (BVS) | 155 | 20 | **TIER_3** | TIER_3 |
| Karjat Jn (KJT) | 155 | 18 | **TIER_3** | TIER_2  <- differs |
| Churchgate (CCG) | 415 | 32 | **TIER_2** | TIER_1  <- differs |
| Marine Lines (MEL) | 415 | 32 | **TIER_2** | TIER_2 |
| Charni Road (CYR) | 415 | 32 | **TIER_2** | TIER_2 |
| Grant Road (GTR) | 415 | 32 | **TIER_2** | TIER_2 |
| Mumbai Central (BCT) | 457 | 35 | **TIER_2** | TIER_1  <- differs |
| Mahalaxmi (MX) | 457 | 33 | **TIER_2** | TIER_2 |
| Lower Parel (PL) | 457 | 34 | **TIER_2** | TIER_2 |
| Prabhadevi (EPR) | 457 | 33 | **TIER_2** | TIER_2 |
| Dadar (W) (DDR) | 462 | 33 | **TIER_1** | TIER_1 |
| Matunga Road (MRU) | 462 | 34 | **TIER_1** | TIER_2  <- differs |
| Mahim Jn (MM) | 462 | 34 | **TIER_1** | TIER_2  <- differs |
| Bandra (BA) | 462 | 33 | **TIER_1** | TIER_1 |
| Khar Road (KHAR) | 472 | 33 | **TIER_1** | TIER_2  <- differs |
| Santacruz (STC) | 476 | 32 | **TIER_1** | TIER_2  <- differs |
| Vile Parle (VLP) | 476 | 33 | **TIER_1** | TIER_2  <- differs |
| Andheri (ADH) | 476 | 32 | **TIER_1** | TIER_1 |
| Jogeshwari (JOS) | 388 | 28 | **TIER_2** | TIER_2 |
| Goregaon (GMN) | 388 | 30 | **TIER_2** | TIER_2 |
| Malad (MDD) | 388 | 29 | **TIER_2** | TIER_2 |
| Kandivali (KILE) | 388 | 29 | **TIER_2** | TIER_2 |
| Borivali (BVI) | 389 | 27 | **TIER_2** | TIER_1  <- differs |
| Dahisar (DIC) | 264 | 17 | **TIER_2** | TIER_2 |
| Mira Road (MIRA) | 264 | 16 | **TIER_2** | TIER_2 |
| Bhayandar (BYR) | 264 | 16 | **TIER_2** | TIER_2 |
| Naigaon (NIG) | 227 | 13 | **TIER_3** | TIER_3 |
| Vasai Road (BSR) | 285 | 20 | **TIER_2** | TIER_2 |
| Nalasopara (NSP) | 259 | 18 | **TIER_2** | TIER_3  <- differs |
| Virar (VR) | 259 | 19 | **TIER_2** | TIER_2 |
| Masjid (MSD) | 325 | 26 | **TIER_2** | TIER_2 |
| Sandhurst Road (SNRD) | 325 | 23 | **TIER_2** | TIER_2 |
| Dockyard Road (DKRD) | 248 | 18 | **TIER_3** | TIER_3 |
| Reay Road (RRD) | 248 | 18 | **TIER_3** | TIER_3 |
| Cotton Green (CTGN) | 248 | 18 | **TIER_3** | TIER_3 |
| Sewri (SVE) | 248 | 18 | **TIER_3** | TIER_3 |
| Vadala Road (VDLR) | 248 | 18 | **TIER_3** | TIER_2  <- differs |
| GTB Nagar (GTBN) | 248 | 18 | **TIER_3** | TIER_3 |
| Chunabhatti (CHF) | 248 | 18 | **TIER_3** | TIER_3 |
| Tilak Nagar (TNR) | 248 | 17 | **TIER_3** | TIER_3 |
| Chembur (CMBR) | 248 | 17 | **TIER_3** | TIER_2  <- differs |
| Govandi (GV) | 248 | 18 | **TIER_3** | TIER_2  <- differs |
| Mankhurd (MNKD) | 248 | 18 | **TIER_3** | TIER_2  <- differs |
| Vashi (VSH) | 320 | 25 | **TIER_2** | TIER_1  <- differs |
| Sanpada (SNPD) | 262 | 20 | **TIER_2** | TIER_2 |
| Juinagar (JNJ) | 162 | 11 | **TIER_3** | TIER_3 |
| Nerul (NEU) | 162 | 12 | **TIER_3** | TIER_2  <- differs |
| Seawoods-Darave (SWDW) | 162 | 11 | **TIER_3** | TIER_3 |
| Belapur CBD (BEPR) | 162 | 12 | **TIER_3** | TIER_2  <- differs |
| Kharghar (KHAG) | 121 | 10 | **TIER_3** | TIER_3 |
| Mansarovar (MSRV) | 121 | 9 | **TIER_3** | TIER_3 |
| Khandeshwar (KNDS) | 121 | 9 | **TIER_3** | TIER_3 |
| Panvel (PNVL) | 127 | 10 | **TIER_3** | TIER_1  <- differs |
| Airoli (AROL) | 125 | 11 | **TIER_3** | TIER_2  <- differs |
| Rabale (RABL) | 125 | 10 | **TIER_3** | TIER_3 |
| Ghansoli (GNSL) | 125 | 12 | **TIER_3** | TIER_3 |
| Koparkhairane (KPKN) | 125 | 11 | **TIER_3** | TIER_3 |
| Turbhe (TBE) | 125 | 11 | **TIER_3** | TIER_2  <- differs |

Tier disagreements (derived value wins):

- BY (Byculla): derived TIER_1 but config expected TIER_2 — 500 services/day, thresholds q1=462 q3=248
- MTN (Matunga): derived TIER_1 but config expected TIER_2 — 511 services/day, thresholds q1=462 q3=248
- SIN (Sion): derived TIER_1 but config expected TIER_2 — 511 services/day, thresholds q1=462 q3=248
- GC (Ghatkopar): derived TIER_1 but config expected TIER_2 — 580 services/day, thresholds q1=462 q3=248
- DI (Dombivli): derived TIER_1 but config expected TIER_2 — 516 services/day, thresholds q1=462 q3=248
- ABH (Ambernath): derived TIER_3 but config expected TIER_2 — 198 services/day, thresholds q1=462 q3=248
- BUD (Badlapur): derived TIER_3 but config expected TIER_2 — 173 services/day, thresholds q1=462 q3=248
- KJT (Karjat Jn): derived TIER_3 but config expected TIER_2 — 155 services/day, thresholds q1=462 q3=248
- CCG (Churchgate): derived TIER_2 but config expected TIER_1 — 415 services/day, thresholds q1=462 q3=248
- BCT (Mumbai Central): derived TIER_2 but config expected TIER_1 — 457 services/day, thresholds q1=462 q3=248
- MRU (Matunga Road): derived TIER_1 but config expected TIER_2 — 462 services/day, thresholds q1=462 q3=248
- MM (Mahim Jn): derived TIER_1 but config expected TIER_2 — 462 services/day, thresholds q1=462 q3=248
- KHAR (Khar Road): derived TIER_1 but config expected TIER_2 — 472 services/day, thresholds q1=462 q3=248
- STC (Santacruz): derived TIER_1 but config expected TIER_2 — 476 services/day, thresholds q1=462 q3=248
- VLP (Vile Parle): derived TIER_1 but config expected TIER_2 — 476 services/day, thresholds q1=462 q3=248
- BVI (Borivali): derived TIER_2 but config expected TIER_1 — 389 services/day, thresholds q1=462 q3=248
- NSP (Nalasopara): derived TIER_2 but config expected TIER_3 — 259 services/day, thresholds q1=462 q3=248
- VDLR (Vadala Road): derived TIER_3 but config expected TIER_2 — 248 services/day, thresholds q1=462 q3=248
- CMBR (Chembur): derived TIER_3 but config expected TIER_2 — 248 services/day, thresholds q1=462 q3=248
- GV (Govandi): derived TIER_3 but config expected TIER_2 — 248 services/day, thresholds q1=462 q3=248
- MNKD (Mankhurd): derived TIER_3 but config expected TIER_2 — 248 services/day, thresholds q1=462 q3=248
- VSH (Vashi): derived TIER_2 but config expected TIER_1 — 320 services/day, thresholds q1=462 q3=248
- NEU (Nerul): derived TIER_3 but config expected TIER_2 — 162 services/day, thresholds q1=462 q3=248
- BEPR (Belapur CBD): derived TIER_3 but config expected TIER_2 — 162 services/day, thresholds q1=462 q3=248
- PNVL (Panvel): derived TIER_3 but config expected TIER_1 — 127 services/day, thresholds q1=462 q3=248
- AROL (Airoli): derived TIER_3 but config expected TIER_2 — 125 services/day, thresholds q1=462 q3=248
- TBE (Turbhe): derived TIER_3 but config expected TIER_2 — 125 services/day, thresholds q1=462 q3=248

## Repairs applied (first 20)

| Check | Target | Action |
|---|---|---|
| V3 | `R-CR-12071@BY` | dwell 0s clipped up to 20s |
| V3 | `R-CR-12071@MTN` | dwell 0s clipped up to 20s |
| V3 | `R-CR-12071@SIN` | dwell 0s clipped up to 20s |
| V3 | `R-CR-12071@CLA` | dwell 0s clipped up to 20s |
| V3 | `R-CR-12071@GC` | dwell 0s clipped up to 20s |
| V3 | `R-CR-12071@DI` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@BY` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@MTN` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@SIN` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@CLA` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@GC` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@TNA` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@DI` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@ABH` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@BUD` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@VGI` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@SHLU` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@NRL` | dwell 0s clipped up to 20s |
| V3 | `R-CR-16381@BVS` | dwell 0s clipped up to 20s |
| V3 | `R-CR-15102@BY` | dwell 0s clipped up to 20s |
