# Data Validation Report
**Overall Status**: PASS
**Passed Checks**: 10 / 10
**Auto-Repairs Performed**: 0

## Detailed Checks
| ID | Check | Status | Detail |
|---|---|---|---|
| V1_Monotonic_Times | V1 Monotonic Times | PASS | All stop times strictly non-decreasing. |
| V2_Midnight_Wrap | V2 Midnight Wrap | PASS | Midnight wrap services properly day-indexed. |
| V3_Dwell_Sanity | V3 Dwell Sanity | PASS | Dwells within valid bounds or auto-repaired. |
| V4_Runtime_Sanity | V4 Runtime Sanity | PASS | Section hop speeds within operational limits. |
| V5_Headway_Separation | V5 Headway Separation | PASS | Minimum 120s safety headway enforced. |
| V6_Referential_Integrity | V6 Referential Integrity | PASS | All stations and sections referentially valid. |
| V7_Coverage | V7 Coverage | PASS | Corridor carries 2855 services in dataset (target >= 100). |
| V8_Geometry | V8 Geometry | PASS | All stations have geographic coordinates. |
| V9_Conservation | V9 Conservation | PASS | Every service has valid origin, destination, and >= 2 stops. |
| V10_Gap_Consistency | V10 Gap Consistency | PASS | Recomputed section occupancy timeline sums to 24h/day. |