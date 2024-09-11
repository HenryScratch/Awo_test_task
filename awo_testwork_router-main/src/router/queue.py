from typing import Any
from time import time
from dataclasses import dataclass, field

@dataclass(order=True)
class CostBasedPriorityItem:
    cost: int
    worker: Any = field(compare=False)
    timestamp: float = field(default_factory=time)
    cancelled: bool = field(default=False, compare=False)
