import random
from typing import List, Dict
from backend.domain.network import NetworkGraph
from backend.domain.task import Task, TaskCategory, Department, WorkZoneType

class TaskGenerator:
    """
    Generates realistic maintenance tasks for PWI, OWD, and S&T departments.
    """

    TASK_TYPES = {
        Department.PWI: [
            ("rail_weld_renewal", 180, True, False, 1),
            ("tamping", 120, True, False, 2),
            ("ballast_screening", 240, True, False, 2),
            ("fishplate_joint_attention", 45, True, False, 3),
            ("points_crossings_attention", 90, True, False, 2),
            ("gauge_correction", 60, True, False, 3)
        ],
        Department.OWD: [
            ("ohe_tension_adjustment", 60, True, True, 2),
            ("insulator_replacement", 45, True, True, 3),
            ("dropper_jumper_repair", 30, True, True, 3),
            ("cantilever_attention", 90, True, True, 2),
            ("power_block_inspection", 120, True, True, 1)
        ],
        Department.S_AND_T: [
            ("point_machine_servicing", 45, True, False, 2),
            ("track_circuit_fault", 30, True, False, 1),
            ("signal_lamp_led_replacement", 20, False, False, 3),
            ("axle_counter_calibration", 40, True, False, 2),
            ("relay_room_interlocking_test", 60, False, False, 2)
        ]
    }

    @staticmethod
    def generate_weekly_planned_tasks(
        network: NetworkGraph,
        num_tasks: int = 40,
        seed: int = 42
    ) -> List[Task]:
        random.seed(seed)
        tasks: List[Task] = []
        sections = list(network.sections.keys())
        stations = list(network.stations.keys())

        for i in range(num_tasks):
            dept = random.choice([Department.PWI, Department.OWD, Department.S_AND_T])
            task_type, duration, req_tr, req_pw, prio = random.choice(TaskGenerator.TASK_TYPES[dept])

            # 80% section work, 20% station node work
            if random.random() < 0.8:
                sec_id = random.choice(sections)
                w_type = WorkZoneType.SECTION
                w_id = sec_id
            else:
                sec_id = random.choice(sections)
                w_type = WorkZoneType.STATION_NODE
                w_id = random.choice(stations)

            tasks.append(Task(
                id=f"TASK_PLN_{i+1:03d}",
                department=dept,
                task_type=task_type,
                section_id=sec_id,
                work_zone_type=w_type,
                work_zone_id=w_id,
                duration_min=duration,
                priority=prio,
                category=TaskCategory.PLANNED,
                requires_power_block=req_pw,
                requires_traffic_block=req_tr,
                released_at_min=0,
                due_by_min=10080
            ))

        return tasks

    @staticmethod
    def generate_demand_task(
        section_id: str,
        department: Department = Department.S_AND_T,
        current_time_min: int = 420
    ) -> Task:
        """Generates an unplanned DEMAND task for mid-schedule reactive injection."""
        return Task(
            id=f"TASK_DEM_{random.randint(1000, 9999)}",
            department=department,
            task_type="unplanned_defect_attention",
            section_id=section_id,
            work_zone_type=WorkZoneType.SECTION,
            work_zone_id=section_id,
            duration_min=35,
            priority=1,
            category=TaskCategory.DEMAND,
            requires_power_block=(department == Department.OWD),
            requires_traffic_block=True,
            released_at_min=current_time_min,
            due_by_min=current_time_min + 360
        )
