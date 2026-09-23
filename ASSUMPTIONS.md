<!-- serves: J2, J4 -->
# RailBlock AI — Explicit Domain Assumptions

This document lists all explicit domain assumptions, heuristic parameters, operational durations, and baseline rules embedded in the prototype. Every assumption is structured with rationale and real-world data replacement pathways.

| ID | Assumption | Value | Why this value | How to replace with real data |
|---|---|---|---|---|
| A-01 | Block setup overhead | 15 minutes | Required for site protection, detonators/banner flags, caution order issuance, and placing men/materials on site. | Connect to TMS/TDMS site-clearance timestamps. |
| A-02 | Block release overhead | 10 minutes | Required for site clearance, joint inspection, line clear certificate, and speed restriction imposition. | Connect to TMS/COA block-closure logs. |
| A-03 | OWD Power block extra overhead | 10 minutes (each for isolation & earthing) | OHE power blocks require high-voltage isolation, earthing before work, and de-earthing after work. | Connect to TDMS power-block isolation logs. |
| A-04 | Minimum usable micro-gap | 20 minutes (raw duration ≥ 45 minutes) | Micro-gaps smaller than 45 min raw yield < 20 min usable work time after setup/release overheads. | Calibrate against field crew execution metrics. |
| A-05 | Headway safety buffer | 120 seconds | Standard safety buffer between consecutive trains on Central main line suburban corridor. | Read exact block-section signaling specs from COA/TMS. |
| A-06 | SICK track speed cap | 30 km/h | Temporary speed restriction (TSR) enforced when track defects are identified. | Query TMS defect severity rules. |
| A-07 | STOP_AND_START penalty | 240 seconds per train | Fixed time loss for a full train stop and cautious restart at a worksite. | Extract from COA control charts. |
| A-08 | Manual coordination delay | 4 hours per departmental conflict | Reflects telephone/meeting negotiations between S&T, OWD, and PWI section heads. | Measure historical BDMS block sanction lead times. |
| A-09 | IWP daily quota | 2 permissions per corridor per day | Integrated Work Permission is administratively heavy and constrained by supervisor availability. | Connect to Division Control Office sanction limits. |
| A-10 | Synthetic Suburban delay distribution | Gamma(shape=2.5, scale=1.0) (mean ~2.5 min) | Represents typical suburban local delays on CSMT–Kalyan section. | Fit parameters from COA historical running data. |
| A-11 | Synthetic Intercity delay distribution | Gamma(shape=1.5, scale=8.0) (mean ~12 min) | Reflects longer distance outer-zone accumulation of delays. | Fit parameters from COA passenger train reports. |
| A-12 | Task outcome degradation | 15% probability of CAUTION_ORDER on short-gap completion | Working under time pressure increases likelihood of temporary speed restriction post-work. | Historical TMS post-block speed restriction logs. |
| A-13 | Adjacent zone compatibility rule (R2) | PWI on section + OWD at adjacent station node = COMPATIBLE | PWI track work in section and OWD station yard work do not physically overlap geometrically. | Integrate IR Rulebook & Block Working Manual section guidelines. |
| A-14 | Department gang capacity | 2 concurrent gangs per department per corridor | Typical maintenance gang allocation per division section per shift. | Read from SMMS/TMS gang deployment rosters. |
