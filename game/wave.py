import json
from pathlib import Path
from typing import Any, Dict, List

from game.enemy import Enemy, EnemyType


_STAGES = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "stages.json").read_text(encoding="utf-8")
)["stages"]


class WaveManager:
    STAGE_HP = {int(stage): data["normal_hp"] for stage, data in _STAGES.items()}
    STAGE_COUNTS = {int(stage): data["normal_count"] for stage, data in _STAGES.items()}
    BOSSES = {int(stage): data["boss"] for stage, data in _STAGES.items() if "boss" in data}

    def __init__(self):
        self.spawn_queue: List[Dict[str, Any]] = []
        self.current_time = 0.0
        self.stage = 1

    def reset(self) -> None:
        self.spawn_queue = []
        self.current_time = 0.0
        self.stage = 1

    def start_wave(self, stage: int) -> None:
        if stage not in self.STAGE_HP:
            raise ValueError(f"Unknown stage: {stage}")
        self.stage = stage
        self.current_time = 0.0
        self.spawn_queue = self._build_spawn_queue(stage)

    def update(self, dt: float, path: List[tuple]) -> List[Enemy]:
        self.current_time += dt
        spawned = []
        remaining = []
        for item in self.spawn_queue:
            if self.current_time + 1e-9 >= item["spawn_time"]:
                enemy = Enemy.create(item["type"], path, item["hp"], item.get("name"))
                if item.get("life_damage"):
                    enemy.life_damage = item["life_damage"]
                spawned.append(enemy)
            else:
                remaining.append(item)
        self.spawn_queue = remaining
        return spawned

    def is_wave_complete(self, alive_enemies: List[Enemy]) -> bool:
        return not self.spawn_queue and not alive_enemies

    @classmethod
    def is_boss_stage(cls, stage: int) -> bool:
        return stage in cls.BOSSES

    def get_remaining_spawns(self) -> int:
        return len(self.spawn_queue)

    def describe_stage(self, stage: int) -> str:
        count = self.STAGE_COUNTS.get(stage, self.STAGE_COUNTS[30])
        boss = self.BOSSES.get(stage)
        if boss:
            return f"일반 악귀 {count}마리 · 보스 악귀 {boss['name']}"
        return f"일반 악귀 {count}마리"

    def _build_spawn_queue(self, stage: int) -> List[Dict[str, Any]]:
        hp = self.STAGE_HP.get(stage, self.STAGE_HP[30])
        count = self.STAGE_COUNTS.get(stage, self.STAGE_COUNTS[30])
        queue: List[Dict[str, Any]] = []

        for index in range(count):
            enemy_type = EnemyType.BASIC
            if stage >= 2 and index % 5 == 2:
                enemy_type = EnemyType.FAST
            if stage >= 3 and index % 6 == 4:
                enemy_type = EnemyType.TANK
            queue.append({"spawn_time": 0.7 + index * 0.65, "type": enemy_type, "hp": hp})

        if stage in self.BOSSES:
            boss = self.BOSSES[stage]
            queue.append({
                "spawn_time": 0.7 + count * 0.65 + 1.0,
                "type": EnemyType.BOSS,
                "hp": boss["hp"],
                "name": boss["name"],
                "life_damage": boss["life_damage"],
            })
        return queue
