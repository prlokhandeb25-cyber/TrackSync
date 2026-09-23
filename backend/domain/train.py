from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class TrainClass(str, Enum):
    SUBURBAN_LOCAL = "SUBURBAN_LOCAL"   # High frequency local service (non-reroutable, UP/DN track swap only)
    INTERCITY = "INTERCITY"             # Express/Mail (Rajdhani, Deccan Queen) - reroutable
    FREIGHT_MAIL = "FREIGHT_MAIL"       # Goods / Parcel - reroutable with large delay tolerance

class Stop(BaseModel):
    station_id: str
    arr_min: int                        # Arrival time in minutes from week start (0..10080)
    dep_min: int                        # Departure time in minutes from week start
    section_id_next: Optional[str] = None

class Train(BaseModel):
    id: str
    number: str
    name: str
    train_class: TrainClass
    origin: str
    destination: str
    days_of_week: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    stops: List[Stop]
    priority: int = 1                    # 1 (highest) to 5 (lowest)
    max_acceptable_delay_min: float = 30.0
    reroutable: bool = False             # True for INTERCITY/FREIGHT, False for SUBURBAN_LOCAL

    def model_post_init(self, __context):
        # Enforce domain assertion guardrail: Suburban local services MUST NEVER be marked reroutable
        if self.train_class == TrainClass.SUBURBAN_LOCAL:
            object.__setattr__(self, "reroutable", False)
        elif self.train_class in (TrainClass.INTERCITY, TrainClass.FREIGHT_MAIL):
            object.__setattr__(self, "reroutable", True)
