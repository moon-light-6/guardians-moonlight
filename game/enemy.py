from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

from config import BOSS_KILL_GOLD, KILL_GOLD


class EnemyType(Enum):
    BASIC = "BASIC"
    FAST = "FAST"
    TANK = "TANK"
    BOSS = "BOSS"


@dataclass
class Enemy:
    enemy_type: EnemyType
    path: List[tuple]
    max_health: int
    speed: float
    life_damage: int
    name: str
    is_boss: bool = False
    health: float = 0
    distance_travelled: float = 0.0
    path_index: int = 0
    progress_in_segment: float = 0.0
    is_alive: bool = True
    reached_base: bool = False
    status_effects: Dict[str, Dict[str, float]] = field(default_factory=dict)
    reward_paid: bool = field(default=False, init=False, repr=False)

    VISUALS = {
        EnemyType.BASIC: {"name": "갓귀", "speed": 1.0, "life_damage": 1},
        EnemyType.FAST: {"name": "질풍귀", "speed": 1.5, "life_damage": 1},
        EnemyType.TANK: {"name": "철갑귀", "speed": 0.7, "life_damage": 2},
        EnemyType.BOSS: {"name": "먹그림자", "speed": 0.55, "life_damage": 3},
    }

    def __post_init__(self) -> None:
        if self.health <= 0:
            self.health = float(self.max_health)

    @classmethod
    def create(cls, enemy_type: EnemyType, path: List[tuple], hp: int, boss_name: str | None = None) -> "Enemy":
        visual = cls.VISUALS[enemy_type]
        return cls(
            enemy_type=enemy_type,
            path=path,
            max_health=hp,
            speed=visual["speed"],
            life_damage=visual["life_damage"],
            name=boss_name or visual["name"],
            is_boss=enemy_type == EnemyType.BOSS,
        )

    def get_current_position(self) -> tuple:
        if self.path_index >= len(self.path) - 1:
            return self.path[-1]
        current = self.path[self.path_index]
        next_pos = self.path[self.path_index + 1]
        x = current[0] + (next_pos[0] - current[0]) * self.progress_in_segment
        y = current[1] + (next_pos[1] - current[1]) * self.progress_in_segment
        return (x, y)

    def move(self, dt: float, speed_modifier: float = 1.0) -> bool:
        if not self.is_alive:
            return False

        distance = self.speed * speed_modifier * dt
        while distance > 0:
            if self.path_index >= len(self.path) - 1:
                self.reached_base = True
                self.is_alive = False
                return True

            current = self.path[self.path_index]
            next_pos = self.path[self.path_index + 1]
            segment_length = self._calculate_distance(current, next_pos)
            if segment_length == 0:
                self.path_index += 1
                continue

            remaining_distance = segment_length * (1.0 - self.progress_in_segment)
            if distance >= remaining_distance:
                distance -= remaining_distance
                self.distance_travelled += remaining_distance
                self.path_index += 1
                self.progress_in_segment = 0.0
            else:
                self.progress_in_segment += distance / segment_length
                self.distance_travelled += distance
                distance = 0

        return False

    def take_damage(self, damage: float) -> bool:
        if not self.is_alive:
            return False
        self.health -= damage
        if self.health <= 0:
            self.is_alive = False
            return True
        return False

    def apply_slow_effect(self, slow_factor: float, duration: float, current_time: float) -> None:
        self.status_effects["slow"] = {"factor": slow_factor, "end_time": current_time + duration}

    def get_speed_modifier(self, current_time: float) -> float:
        expired = [
            key for key, value in self.status_effects.items()
            if value.get("end_time", 0) <= current_time
        ]
        for key in expired:
            del self.status_effects[key]
        return self.status_effects.get("slow", {}).get("factor", 1.0)

    def has_reached_base(self) -> bool:
        return self.reached_base

    @property
    def gold_reward(self) -> int:
        return BOSS_KILL_GOLD if self.is_boss else KILL_GOLD

    @property
    def progress(self) -> float:
        return self.distance_travelled

    @property
    def x(self) -> float:
        return self.get_current_position()[0]

    @property
    def y(self) -> float:
        return self.get_current_position()[1]

    @staticmethod
    def _calculate_distance(pos1: tuple, pos2: tuple) -> float:
        return ((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2) ** 0.5
