from enum import Enum
from typing import Any, Dict, List

from config import LEVEL_DAMAGE_MULTIPLIERS, UPGRADE_COSTS


class TowerType(Enum):
    LIGHTNING = "LIGHTNING"
    ARCHER = "ARCHER"
    CANNON = "CANNON"
    ICE = "ICE"


class Tower:
    BASE_STATS = {
        TowerType.LIGHTNING: {
            "guardian": "청룡",
            "damage": 25,
            "attack_interval": 1.5,
            "range": 2.5,
            "chain_count": 3,
            "description": "번개형 · 최대 3명 연쇄",
        },
        TowerType.ARCHER: {
            "guardian": "백호",
            "damage": 15,
            "attack_interval": 0.5,
            "range": 2.5,
            "description": "궁수형 · 빠른 단일 공격",
        },
        TowerType.CANNON: {
            "guardian": "주작",
            "damage": 40,
            "attack_interval": 2.0,
            "range": 2.5,
            "splash_radius": 2.0,
            "description": "대포형 · 반경 2칸 광역",
        },
        TowerType.ICE: {
            "guardian": "현무",
            "damage": 10,
            "attack_interval": 4.0,
            "range": 3.0,
            "slow_factor": 0.7,
            "slow_duration": 2.0,
            "description": "장판형 · 2초간 30% 둔화",
        },
    }

    def __init__(self, tower_type: TowerType, slot_id: int, level: int = 1):
        self.tower_type = tower_type
        self.slot_id = slot_id
        self.level = level
        self.time_since_last_attack = 999.0

    def get_stats(self) -> Dict[str, Any]:
        base = self.BASE_STATS[self.tower_type].copy()
        base["damage"] *= LEVEL_DAMAGE_MULTIPLIERS[self.level]
        return base

    def can_attack(self) -> bool:
        return self.time_since_last_attack + 1e-9 >= self.get_stats()["attack_interval"]

    def reset_attack_cooldown(self) -> None:
        self.time_since_last_attack = 0.0

    def update(self, dt: float) -> None:
        self.time_since_last_attack += dt

    @staticmethod
    def get_upgrade_cost(level: int) -> int:
        return UPGRADE_COSTS.get(level, 0)

    @staticmethod
    def from_data(data: Dict[str, Any]) -> "Tower":
        tower_type = data["type"]
        if isinstance(tower_type, str):
            tower_type = TowerType[tower_type]
        tower = Tower(tower_type, data["slot_id"], data.get("level", 1))
        tower.time_since_last_attack = data.get("cooldown", 999.0)
        return tower

    @staticmethod
    def display_name(tower_type: str) -> str:
        return Tower.BASE_STATS[TowerType[tower_type]]["guardian"]

    @staticmethod
    def all_types() -> List[str]:
        return [tower_type.name for tower_type in TowerType]
