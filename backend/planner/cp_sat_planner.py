import time
from typing import List, Dict, Any, Tuple, Optional
from pydantic import BaseModel
from ortools.sat.python import cp_model
from backend.domain.network import NetworkGraph, StationTier
from backend.domain.train import Train, TrainClass
from backend.domain.task import Task, TaskCategory, Department
from backend.domain.compatibility import DepartmentCompatibilityEngine, CompatibilityVerdictValue
from backend.gaps.gap_engine import CandidateWindow, GapType

class ScheduleSolution(BaseModel):
    status: str                         # OPTIMAL | FEASIBLE | INFEASIBLE
    objective_value: float
    optimality_gap: float
    solve_time_ms: float
    scheduled_tasks: Dict[str, Dict[str, Any]]  # task_id -> {start_min, end_min, window_id, track, is_micro_gap}
    rerouted_trains: Dict[str, str]             # train_id -> alternate_path_info
    single_line_working_sections: List[str]
    iwp_used_count: int
    relaxation_applied: Optional[str] = None

class CPSatBlockPlanner:
    """
    OR-Tools CP-SAT Batch Scheduler for weekly PLANNED task scheduling.
    """

    def __init__(
        self,
        network: NetworkGraph,
        compatibility_engine: DepartmentCompatibilityEngine,
        max_time_in_seconds: int = 60,
        random_seed: int = 42,
        weights: Dict[str, float] = None
    ):
        self.network = network
        self.comp_engine = compatibility_engine
        self.max_time_in_seconds = max_time_in_seconds
        self.random_seed = random_seed
        self.weights = weights or {
            "w1_train_minutes_lost": 10.0,
            "w2_unscheduled_task_penalty": 50.0,
            "w3_degraded_status_section_hours": 15.0,
            "w4_rerouted_train_delay": 5.0,
            "w5_single_line_working_minutes": 8.0,
            "w6_iwp_usage": 20.0,
            "w7_micro_gap_utilisation_bonus": 30.0
        }

    def solve(
        self,
        tasks: List[Task],
        candidate_windows: List[CandidateWindow],
        iwp_quota_per_day: int = 2,
        relaxation_level: int = 0
    ) -> ScheduleSolution:
        start_wall_time = time.time()
        model = cp_model.CpModel()

        # Decision variables per task
        task_vars = {}
        window_assignment_vars = {}
        iwp_vars = {}

        # Filter candidate windows by task section
        windows_by_sec = {}
        for win in candidate_windows:
            if win.section_id not in windows_by_sec:
                windows_by_sec[win.section_id] = []
            windows_by_sec[win.section_id].append(win)

        for task in tasks:
            is_sched = model.NewBoolVar(f"sched_{task.id}")
            start_var = model.NewIntVar(0, 10080, f"start_{task.id}")
            end_var = model.NewIntVar(0, 10080, f"end_{task.id}")
            interval_var = model.NewOptionalIntervalVar(
                start_var, task.duration_min, end_var, is_sched, f"interval_{task.id}"
            )

            task_vars[task.id] = {
                "is_sched": is_sched,
                "start": start_var,
                "end": end_var,
                "interval": interval_var,
                "task": task
            }

            # Window presence variables
            sec_windows = windows_by_sec.get(task.section_id, [])
            window_assignment_vars[task.id] = {}

            if sec_windows:
                presences = []
                for win in sec_windows:
                    p = model.NewBoolVar(f"win_{task.id}_{win.id}")
                    window_assignment_vars[task.id][win.id] = p
                    presences.append(p)

                    # Window bounds constraint
                    model.Add(start_var >= win.start_min).OnlyEnforceIf(p)
                    model.Add(end_var <= win.end_min).OnlyEnforceIf(p)

                # Sum of presences == is_sched
                model.Add(sum(presences) == is_sched)
            else:
                if relaxation_level < 2:
                    model.Add(is_sched == 0)

        # Department Pair Compatibility Constraints (§7)
        task_list = list(tasks)
        for i in range(len(task_list)):
            for j in range(i + 1, len(task_list)):
                t1 = task_list[i]
                t2 = task_list[j]
                verdict = self.comp_engine.evaluate(t1, t2)

                if verdict.value == CompatibilityVerdictValue.INCOMPATIBLE:
                    # Hard NoOverlap disjunction
                    b_before = model.NewBoolVar(f"{t1.id}_before_{t2.id}")
                    model.Add(task_vars[t1.id]["end"] <= task_vars[t2.id]["start"]).OnlyEnforceIf([
                        task_vars[t1.id]["is_sched"], task_vars[t2.id]["is_sched"], b_before
                    ])
                    model.Add(task_vars[t2.id]["end"] <= task_vars[t1.id]["start"]).OnlyEnforceIf([
                        task_vars[t1.id]["is_sched"], task_vars[t2.id]["is_sched"], b_before.Not()
                    ])

                elif verdict.value == CompatibilityVerdictValue.REQUIRES_IWP:
                    # Either disjoint, OR co-scheduled with IWP quota consumption
                    iwp_used = model.NewBoolVar(f"iwp_{t1.id}_{t2.id}")
                    iwp_vars[(t1.id, t2.id)] = iwp_used

                    b_before = model.NewBoolVar(f"{t1.id}_before_{t2.id}")
                    model.Add(task_vars[t1.id]["end"] <= task_vars[t2.id]["start"]).OnlyEnforceIf([
                        task_vars[t1.id]["is_sched"], task_vars[t2.id]["is_sched"], b_before, iwp_used.Not()
                    ])
                    model.Add(task_vars[t2.id]["end"] <= task_vars[t1.id]["start"]).OnlyEnforceIf([
                        task_vars[t1.id]["is_sched"], task_vars[t2.id]["is_sched"], b_before.Not(), iwp_used.Not()
                    ])

        # Limit total daily IWP usage
        if iwp_vars:
            model.Add(sum(iwp_vars.values()) <= (iwp_quota_per_day * 7))

        # Station-tier block duration constraints (§8.2)
        if relaxation_level < 1:
            for task in tasks:
                st = self.network.stations.get(task.work_zone_id)
                if st and st.tier == StationTier.TIER_1:
                    # Tier-1 stations cap single block duration to 45 min
                    if task.duration_min > 45:
                        model.Add(task_vars[task.id]["is_sched"] == 0)

        # Objective Function
        obj_terms = []

        # 1. Unscheduled task penalty
        for task in tasks:
            penalty = int(self.weights["w2_unscheduled_task_penalty"] * (6 - task.priority) * 10)
            obj_terms.append((1 - task_vars[task.id]["is_sched"]) * penalty)

        # 2. Reward micro-gap utilization
        for task in tasks:
            for win_id, p in window_assignment_vars[task.id].items():
                win = next((w for w in candidate_windows if w.id == win_id), None)
                if win and win.gap_type == GapType.MICRO_GAP:
                    bonus = int(self.weights["w7_micro_gap_utilisation_bonus"] * 10)
                    obj_terms.append(-1 * p * bonus)

        # 3. IWP usage penalty
        for iwp_v in iwp_vars.values():
            penalty = int(self.weights["w6_iwp_usage"] * 10)
            obj_terms.append(iwp_v * penalty)

        model.Minimize(sum(obj_terms))

        # Solver config
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.max_time_in_seconds
        solver.parameters.num_search_workers = 8
        solver.parameters.random_seed = self.random_seed

        status = solver.Solve(model)
        solve_time = (time.time() - start_wall_time) * 1000.0

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            sched_tasks = {}
            micro_gap_count = 0

            for task in tasks:
                if solver.Value(task_vars[task.id]["is_sched"]) == 1:
                    st_val = solver.Value(task_vars[task.id]["start"])
                    end_val = solver.Value(task_vars[task.id]["end"])

                    chosen_win_id = None
                    is_micro = False
                    for w_id, p_var in window_assignment_vars[task.id].items():
                        if solver.Value(p_var) == 1:
                            chosen_win_id = w_id
                            win_obj = next((w for w in candidate_windows if w.id == w_id), None)
                            if win_obj and win_obj.gap_type == GapType.MICRO_GAP:
                                is_micro = True
                                micro_gap_count += 1

                    sched_tasks[task.id] = {
                        "start_min": st_val,
                        "end_min": end_val,
                        "window_id": chosen_win_id,
                        "track": "DN",
                        "is_micro_gap": is_micro
                    }

            iwp_count = sum(1 for v in iwp_vars.values() if solver.Value(v) == 1)
            gap = solver.UserTime() / max(0.1, solver.ObjectiveValue())

            return ScheduleSolution(
                status="OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
                objective_value=float(solver.ObjectiveValue()),
                optimality_gap=float(gap),
                solve_time_ms=solve_time,
                scheduled_tasks=sched_tasks,
                rerouted_trains={},
                single_line_working_sections=[],
                iwp_used_count=iwp_count,
                relaxation_applied=f"Level_{relaxation_level}" if relaxation_level > 0 else None
            )

        else:
            # Relaxation ladder on INFEASIBLE: Level 1 (drop tier caps) -> Level 2 (allow full task deferral)
            if relaxation_level < 2:
                return self.solve(tasks, candidate_windows, iwp_quota_per_day, relaxation_level=relaxation_level + 1)

            return ScheduleSolution(
                status="INFEASIBLE",
                objective_value=999999.0,
                optimality_gap=1.0,
                solve_time_ms=solve_time,
                scheduled_tasks={},
                rerouted_trains={},
                single_line_working_sections=[],
                iwp_used_count=0,
                relaxation_applied="Max_Relaxation_Failed"
            )
