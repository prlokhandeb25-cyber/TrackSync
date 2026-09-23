# Side-by-side: working project vs Antigravity reference

Two implementations of the same `SPEC.md` ended up in one folder. They are now separated:

- **Working project** — `C:\Users\hp\Desktop\railblock-ai` (this one, use it)
- **Reference copy** — `C:\Users\hp\Desktop\railblock-ai-ANTIGRAVITY-reference` (frozen, read-only)

**One thing to understand before reading any of this.** Antigravity did not build independently.
It ran against this same working tree *after* the Claude implementation had reached P10, so it
inherited the network configs, the domain model and the data pipeline, then added its own modules
on top and overwrote a few core files. The corridor YAMLs in the reference folder are
byte-identical to the ones here. So this is not "two designs from scratch" — it is one codebase
with a second agent's layer applied to it.

---

## Scale

| | Working project | Antigravity reference |
|---|---|---|
| Python | 6,900 lines | +6,723 lines of its own files on top |
| Frontend | 1,563 lines | its own component set (7 components) |
| Corridor configs | 4 lines, 489 lines of YAML | the same 4, plus `pune_solapur.yaml` |
| Tests passing | **37** | 8 (`test_scalability.py`, `test_validation.py`) |
| Runs end to end | **yes** | no — 2 modules fail to import |

---

## Feature coverage

| Capability | Working project | Antigravity reference |
|---|---|---|
| Validation gate (V1–V10) | ✅ 10 checks, blocking, with honest FAIL reporting | inherited |
| Mumbai network | ✅ 4 lines, 73 stations, 74 sections, 254 route-km | inherited |
| Interchange discovery | ✅ by shared station code (CSMT, Kurla, Thane, Vashi, Sanpada) | inherited |
| Traffic-gap engine | ✅ night / megablock / micro-gap, tier-capped | its own `gap_engine.py` |
| Department compatibility R0–R4 | ✅ with human-readable reasons | inherited |
| Track-status FSM | ✅ 4 states, all transitions tested | inherited |
| CP-SAT planner | ✅ OPTIMAL, 0% gap, ~3 s | its own `cp_sat_planner.py` |
| Expert trajectories | ✅ 1,074 instances, 28,232 transitions | its own `trajectory_gen.py` |
| Behaviour cloning | ✅ | ✅ |
| CQL-DQN | ✅ | ✅ |
| **AWAC-A2C (3rd algorithm)** | ❌ **not built** | ✅ **`awac_a2c.py`** |
| Grounded chatbot | ✅ intent parser over live state, no LLM | ❌ |
| Before/after metrics | ✅ 10 metrics, parameters exposed | ✅ `impact_harness.py` |
| IR adapters | ✅ 5 systems, interfaces + mocks | ✅ `mock_adapters.py` (fails to import) |
| **Scalability test** | ❌ **not written** | ✅ **`test_scalability.py`, 8 passing** |
| **WebSocket live push** | ❌ | ✅ `websocket.py` |
| **Discrete-event simulator** | ❌ | ✅ `simulator.py` (fails to import) |
| **Demand-injection UI** | ❌ | ✅ `DemandInjection.tsx` |
| **README / REPORT / ROADMAP / DEMO_SCRIPT** | ❌ **not written** | ✅ all four |

---

## The RL numbers — why they are not comparable

| Policy | Working project | Antigravity reference |
|---|---|---|
| Greedy | 19.7% gap | 24.8% gap |
| Behaviour cloning | 15.8% gap | 12.5% gap |
| CQL-DQN | 14.8% gap | 6.4% gap |
| AWAC-A2C | — | 8.1% gap |
| Constraint violations | 0 | 0 |

Antigravity's headline looks better. **Do not put it on a slide as though the two were measured
the same way.** They were not:

- Different objective definitions and different rollout environments.
- Its CSV records **neither the evaluation instance count nor the share of tasks scheduled**.
  That second omission matters: a policy that places less work can post a smaller objective gap
  while achieving less. The working project reports 85.9% of tasks scheduled alongside its 14.8%,
  so the figure can be checked. The reference number cannot.
- This project's evaluation regenerates 20 genuinely held-out instances from stored instance ids
  and re-solves each with CP-SAT for the reference value, with a split-leakage assertion.

If the AWAC-A2C result is wanted, the defensible route is to port `awac_a2c.py` into this
project and run it through **this** harness. Then all four numbers come from one yardstick.

---

## What broke, and why it matters

Two of Antigravity's overwrites took the build down:

1. `backend/rl/mdp.py` replaced with an incompatible design (`SchedulingMDP`, `NetworkGraph`,
   `gap_engine`) that the Claude RL stack cannot import.
2. `backend/adapters/base.py` left with a hard `SyntaxError`.

Plus `backend/rl/agents/` recreated as a package, shadowing `agents.py`.

None of this reflects badly on either implementation on its own. It is what happens when two
agents write to one working tree.

---

## Recommendation

Use the working project. It runs, it is tested, and every number it reports can be traced to a
run that actually happened.

Take three things from the reference folder, in this order:

1. **`tests/test_scalability.py` + `pune_solapur.yaml`** — this is SPEC §4's J3 evidence and the
   working project genuinely lacks it. Highest value for the least effort.
2. **`README.md` / `REPORT.md` / `ROADMAP.md` / `DEMO_SCRIPT.md`** — deliverable documents not yet
   written here. Worth adapting rather than copying, since the numbers differ.
3. **`awac_a2c.py`** — the third algorithm, if there is time to re-evaluate it honestly through
   this project's harness.

Leave `simulator.py`, `websocket.py` and `mock_adapters.py` alone unless something specific is
needed from them; two of the three do not currently import.
