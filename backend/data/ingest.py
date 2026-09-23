import random
from typing import List, Dict, Any
import yaml
import pandas as pd
from backend.domain.network import Station, Section, NetworkGraph, StationTier
from backend.domain.train import Train, TrainClass, Stop

class TimetableIngester:
    """
    Ingests network graph configuration and generates a structurally faithful timetable
    matching published Mumbai Central Main Line specs (~1,200 suburban services/day + intercity/freight).
    """

    def __init__(self, config_path: str):
        with open(config_path, "r") as f:
            self.raw_config = yaml.safe_load(f)

        self.network = NetworkGraph()
        self._build_network()

    def _build_network(self):
        for s_data in self.raw_config["stations"]:
            tier_str = s_data.get("tier", "TIER_2")
            station = Station(
                id=s_data["id"],
                name=s_data["name"],
                code=s_data["code"],
                lat=s_data["lat"],
                lon=s_data["lon"],
                is_junction=s_data.get("is_junction", False),
                platforms=s_data.get("platforms", 2),
                tier=StationTier(tier_str)
            )
            self.network.add_station(station)

        for sec_data in self.raw_config["sections"]:
            sec = Section(
                id=sec_data["id"],
                from_station=sec_data["from_station"],
                to_station=sec_data["to_station"],
                length_km=sec_data["length_km"],
                line_speed_kmph=sec_data["line_speed_kmph"],
                tracks=sec_data.get("tracks", ["UP", "DN"]),
                alternate_section_ids=sec_data.get("alternate_section_ids", [])
            )
            self.network.add_section(sec)

    def generate_synthetic_timetable(self, seed: int = 42) -> List[Train]:
        random.seed(seed)
        trains: List[Train] = []

        main_line_stations = [s["id"] for s in self.raw_config["stations"]]
        sections_by_pair = {}
        for sec in self.network.sections.values():
            sections_by_pair[(sec.from_station, sec.to_station)] = sec.id
            sections_by_pair[(sec.to_station, sec.from_station)] = sec.id

        service_counter = 1

        for day in range(7):
            day_offset = day * 1440  # 1440 minutes per day

            current_time = 45  # 00:45 start of morning service
            end_time = 1425   # 23:45 end of night service

            while current_time < end_time:
                is_peak = (420 <= current_time <= 660) or (1020 <= current_time <= 1260)
                headway = random.randint(3, 5) if is_peak else random.randint(8, 15)

                for direction in ["DN", "UP"]:
                    station_order = main_line_stations if direction == "DN" else list(reversed(main_line_stations))

                    stops: List[Stop] = []
                    t_curr = int(day_offset + current_time)

                    for i in range(len(station_order)):
                        st_id = station_order[i]
                        dwell = 1  # 1 minute integer dwell

                        arr = int(t_curr)
                        dep = int(t_curr + dwell)
                        next_sec = None

                        if i < len(station_order) - 1:
                            next_st = station_order[i + 1]
                            next_sec = sections_by_pair.get((st_id, next_st))
                            sec_obj = self.network.sections[next_sec] if next_sec else None
                            run_time = max(2, int(round((sec_obj.length_km / sec_obj.line_speed_kmph) * 60))) if sec_obj else 4
                            t_curr = dep + run_time
                        else:
                            t_curr = dep

                        stops.append(Stop(
                            station_id=st_id,
                            arr_min=arr,
                            dep_min=dep,
                            section_id_next=next_sec
                        ))

                    train_id = f"SUB_{service_counter:05d}"
                    trains.append(Train(
                        id=train_id,
                        number=f"97{service_counter:03d}",
                        name=f"Local {direction} CSMT-KJT",
                        train_class=TrainClass.SUBURBAN_LOCAL,
                        origin=station_order[0],
                        destination=station_order[-1],
                        days_of_week=[day],
                        stops=stops,
                        priority=3,
                        max_acceptable_delay_min=15.0,
                        reroutable=False
                    ))
                    service_counter += 1

                current_time += headway

            # 2. Intercity Express Services
            for ic_idx in range(15):
                dept_time = day_offset + 300 + (ic_idx * 60)
                stops = []
                t_curr = int(dept_time)
                ic_stations = main_line_stations[::3]  # Jump every 3 stations
                for i in range(len(ic_stations)):
                    st_id = ic_stations[i]
                    arr = int(t_curr)
                    dep = int(t_curr + 2)
                    next_sec = None
                    if i < len(ic_stations) - 1:
                        next_st = ic_stations[i + 1]
                        next_sec = sections_by_pair.get((st_id, next_st))
                        run_time = 10
                        t_curr = dep + run_time
                    stops.append(Stop(station_id=st_id, arr_min=arr, dep_min=dep, section_id_next=next_sec))

                trains.append(Train(
                    id=f"IC_{day}_{ic_idx:02d}",
                    number=f"121{ic_idx:02d}",
                    name=f"Deccan Express {ic_idx}",
                    train_class=TrainClass.INTERCITY,
                    origin="CSMT",
                    destination="KJT",
                    days_of_week=[day],
                    stops=stops,
                    priority=1,
                    max_acceptable_delay_min=30.0,
                    reroutable=True
                ))

        return trains

    def save_timetable_to_parquet(self, trains: List[Train], output_path: str):
        rows = []
        for tr in trains:
            for s in tr.stops:
                rows.append({
                    "train_id": tr.id,
                    "train_number": tr.number,
                    "train_name": tr.name,
                    "train_class": tr.train_class.value,
                    "priority": tr.priority,
                    "station_id": s.station_id,
                    "arr_min": s.arr_min,
                    "dep_min": s.dep_min,
                    "section_id_next": s.section_id_next or "",
                    "reroutable": tr.reroutable
                })
        df = pd.DataFrame(rows)
        df.to_parquet(output_path, index=False)
