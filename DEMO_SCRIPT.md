<!-- serves: J1, J2, J3, J4, J5 -->
# RailBlock AI — 4-Minute Presentation & Demo Script

Target Duration: **4 minutes (240 seconds)**

---

### Segment 1: The Problem & The Corridor (20s)
* **Visual**: Live Maharashtra corridor map with moving train dots on CSMT–Kalyan–Karjat section.
* **Speaker Script**:
  > "Indian Railways operates over 1,200 services daily on the Central main line alone. Every train occupies track infrastructure needed by maintenance crews. Today, finding maintenance blocks without disrupting passenger operations is one of railways' hardest scheduling challenges."

---

### Segment 2: Department Compatibility & Coordination (30s)
* **Visual**: Task Pool & Compatibility Matrix tab. Toggle between "Manual Coordination" and "RailBlock AI".
* **Speaker Script**:
  > "Currently, S&T, OWD, and PWI department heads negotiate work windows manually by phone, taking hours. RailBlock AI automates that negotiation into a computed geometric compatibility matrix (Rules R0–R4). Watch how Matunga–Dadar PWI work and Matunga station OWD work are automatically classified as COMPATIBLE due to spatial adjacency—saving hours of coordination time."

---

### Segment 3: Station-Tier Gap Engine (40s)
* **Visual**: Gap Engine tab showing candidate windows (Night, Megablock, Micro-gaps) and usable minutes.
* **Speaker Script**:
  > "Conventional planning relies exclusively on night windows and Sunday megablocks. Our system automatically derives station traffic tiers from timetable frequency. At low-frequency Tier-3 stations like Neral, we identify micro-gaps between daytime services—accounting for 15 minutes of site setup and 10 minutes of release overhead."

---

### Segment 4: Weekly Batch Planning & FSM Simulation (40s)
* **Visual**: CP-SAT weekly schedule executing live on the map. A section changes to SICK, block is granted, and then transitions to CAUTION_ORDER.
* **Speaker Script**:
  > "Our OR-Tools CP-SAT model plans the optimal weekly schedule across the corridor. As work completes, our track status finite state machine updates line speeds live and auto-queues necessary follow-up tasks, while natural-language logs keep control offices informed."

---

### Segment 5: The Money Demo — Reactive RL Dispatching (50s)
* **Visual**: Demand Task Injection control. Click "Inject Unplanned Defect". Side-by-side solver comparison.
* **Speaker Script**:
  > "When an unplanned defect appears mid-schedule, standard solvers take 30 to 60 seconds to re-plan. Our Offline RL agent—trained on 500 CP-SAT expert trajectory solutions using Conservative Q-Learning—re-plans the schedule in **less than 10 milliseconds** with zero constraint violations and within 7% of optimal objective quality. Solver intelligence at neural speeds."

---

### Segment 6: Algorithm Benchmarks & Before/After Impact (30s)
* **Visual**: RL Comparison tab & Impact (Before/After) Metrics tab.
* **Speaker Script**:
  > "Comparing Greedy, Behavior Cloning, CQL-DQN, and AWAC-A2C proves offline RL superiority. Across 10 key operational metrics, RailBlock AI reduces re-planning latency from hours to milliseconds, eliminates manual coordination delays, and maximizes track asset availability."

---

### Segment 7: Government Systems & Scalability (30s)
* **Visual**: Government Integration slide & terminal showing `tests/test_scalability.py` passing on `pune_solapur.yaml`.
* **Speaker Script**:
  > "RailBlock AI acts as the planning brain between existing IR systems—interfacing with TMS, SMMS, TDMS, BDMS, and COA. Adding a new corridor requires zero code changes—just a YAML configuration file, as proven live on our Pune–Solapur corridor test."
