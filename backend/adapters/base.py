from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BDMSAdapter(ABC):
    """Block Demand Management System Interface."""
    @abstractmethod
    def fetch_pending_block_demands((self) -> List[Dict[str, Any]]: pass

    @abstractmethod
    def submit_block_plan(self, plan: Dict[str, Any]) -> bool: pass

    @abstractmethod
    def fetch_sanction_status(self, block_id: str) -> Dict[str, Any]: pass

class COAAdapter(ABC):
    """Control Office Application Interface."""
    @abstractmethod
    def fetch_live_train_positions(self) -> List[Dict[str, Any]]: pass

    @abstractmethod
    def fetch_actual_running(self, date_str: str) -> List[Dict[str, Any]]: pass

    @abstractmethod
    def notify_block_impact(self, section_id: str, speed_cap_kmph: float) -> bool: pass

class TMSAdapter(ABC):
    """Track Management System Interface (PWI)."""
    @abstractmethod
    def fetch_track_defects(self) -> List[Dict[str, Any]]: pass

    @abstractmethod
    def post_work_completion(self, task_id: str, outcome_status: str) -> bool: pass

class SMMSAdapter(ABC):
    """Signalling Maintenance Management System Interface (S&T)."""
    @abstractmethod
    def fetch_signalling_tasks(self) -> List[Dict[str, Any]]: pass

    @abstractmethod
    def post_work_completion(self, task_id: str, outcome_status: str) -> bool: pass

class TDMSAdapter(ABC):
    """Traction Distribution Management System Interface (OWD)."""
    @abstractmethod
    def fetch_ohe_tasks(self) -> List[Dict[str, Any]]: pass

    @abstractmethod
    def fetch_power_block_constraints(self) -> List[Dict[str, Any]]: pass

    @abstractmethod
    def post_work_completion(self, task_id: str, outcome_status: str) -> bool: pass
