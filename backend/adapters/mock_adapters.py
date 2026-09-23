from typing import List, Dict, Any
from backend.adapters.base import (
    BDMSAdapter, COAAdapter, TMSAdapter, SMMSAdapter, TDMSAdapter
)

class MockBDMSAdapter(BDMSAdapter):
    def fetch_pending_block_demands(self) -> List[Dict[str, Any]]:
        return [
            {"demand_id": "BD_101", "department": "PWI", "section_id": "SEC_DR_CLA", "duration_min": 60, "status": "SANCTIONED"},
            {"demand_id": "BD_102", "department": "OWD", "section_id": "SEC_CLA_GC", "duration_min": 45, "status": "PENDING_SANCTION"}
        ]

    def submit_block_plan(self, plan: Dict[str, Any]) -> bool:
        print(f"[BDMS Mock] Submitted weekly block plan containing {len(plan.get('scheduled_tasks', {}))} sanctioned blocks.")
        return True

    def fetch_sanction_status(self, block_id: str) -> Dict[str, Any]:
        return {"block_id": block_id, "status": "SANCTIONED", "sanction_ref": "CR/OPT/2026/994"}

class MockCOAAdapter(COAAdapter):
    def fetch_live_train_positions(self) -> List[Dict[str, Any]]:
        return [{"train_id": "SUB_00001", "lat": 19.0178, "lon": 72.8478, "delay_min": 2.0}]

    def fetch_actual_running(self, date_str: str) -> List[Dict[str, Any]]:
        return [{"train_id": "SUB_00001", "punctuality_status": "ON_TIME"}]

    def notify_block_impact(self, section_id: str, speed_cap_kmph: float) -> bool:
        print(f"[COA Mock] Broadcast TSR notification for {section_id}: Speed capped at {speed_cap_kmph} km/h.")
        return True

class MockTMSAdapter(TMSAdapter):
    def fetch_track_defects(self) -> List[Dict[str, Any]]:
        return [{"defect_id": "DEF_PWI_01", "section_id": "SEC_VGI_SHLU", "severity": "HIGH", "recommended_speed": 30}]

    def post_work_completion(self, task_id: str, outcome_status: str) -> bool:
        print(f"[TMS Mock] Recorded PWI work completion for task {task_id}. Outcome: {outcome_status}.")
        return True

class MockSMMSAdapter(SMMSAdapter):
    def fetch_signalling_tasks(self) -> List[Dict[str, Any]]:
        return [{"task_id": "SNT_01", "section_id": "SEC_NRL_BVS", "equipment": "Axle Counter"}]

    def post_work_completion(self, task_id: str, outcome_status: str) -> bool:
        print(f"[SMMS Mock] Recorded S&T work completion for task {task_id}. Outcome: {outcome_status}.")
        return True

class MockTDMSAdapter(TDMSAdapter):
    def fetch_ohe_tasks(self) -> List[Dict[str, Any]]:
        return [{"task_id": "OWD_01", "section_id": "SEC_BYC_DR", "equipment": "Insulator String"}]

    def fetch_power_block_constraints(self) -> List[Dict[str, Any]]:
        return [{"feeder": "F_TNA_01", "isolation_time_min": 10}]

    def post_work_completion(self, task_id: str, outcome_status: str) -> bool:
        print(f"[TDMS Mock] Recorded OWD work completion for task {task_id}. Outcome: {outcome_status}.")
        return True
