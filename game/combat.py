import math
from typing import Any, Dict, List, Optional

from game.enemy import Enemy
from game.tower import Tower, TowerType


class Combat:
    def get_target(self, tower_pos: tuple, tower_range: float, enemies: List[Enemy]) -> Optional[Enemy]:
        targets = [
            enemy for enemy in enemies
            if enemy.is_alive and self._calculate_distance(tower_pos, enemy.get_current_position()) <= tower_range
        ]
        return max(targets, key=lambda enemy: enemy.progress) if targets else None

    def attack(self, tower_data: Dict[str, Any], tower_pos: tuple, enemies: List[Enemy], elapsed: float) -> List[Dict[str, Any]]:
        tower = Tower.from_data(tower_data)
        stats = tower.get_stats()
        target = self.get_target(tower_pos, stats["range"], enemies)
        if target is None:
            tower_data["cooldown"] = tower.time_since_last_attack
            return []

        effects: List[Dict[str, Any]] = []
        tower_type = tower.tower_type

        if tower_type == TowerType.ARCHER:
            self.apply_damage(target, stats["damage"])
            effects.append({"kind": "claw", "from": tower_pos, "to": target.get_current_position(), "age": 0.0, "ttl": 0.18})
        elif tower_type == TowerType.CANNON:
            center = target.get_current_position()
            self.apply_splash_damage(center, stats["splash_radius"], stats["damage"], enemies)
            effects.append({"kind": "fire", "from": tower_pos, "to": center, "age": 0.0, "ttl": 0.32, "radius": stats["splash_radius"]})
        elif tower_type == TowerType.ICE:
            self.apply_damage(target, stats["damage"])
            target.apply_slow_effect(stats["slow_factor"], stats["slow_duration"], elapsed)
            effects.append({"kind": "water", "from": tower_pos, "to": target.get_current_position(), "age": 0.0, "ttl": 0.35})
        elif tower_type == TowerType.LIGHTNING:
            chain = self.apply_chain_damage(target, stats["damage"], stats["chain_count"], enemies)
            points = [enemy.get_current_position() for enemy in chain]
            effects.append({"kind": "lightning", "from": tower_pos, "points": points, "age": 0.0, "ttl": 0.22})

        tower.reset_attack_cooldown()
        tower_data["cooldown"] = tower.time_since_last_attack
        return effects

    def apply_damage(self, target: Enemy, damage: float) -> bool:
        return target.take_damage(damage)

    def apply_splash_damage(self, center_pos: tuple, splash_radius: float, damage: float, enemies: List[Enemy]) -> int:
        damaged = 0
        for enemy in enemies:
            if enemy.is_alive and self._calculate_distance(center_pos, enemy.get_current_position()) <= splash_radius:
                enemy.take_damage(damage)
                damaged += 1
        return damaged

    def apply_chain_damage(self, target: Enemy, damage: float, chain_count: int, enemies: List[Enemy]) -> List[Enemy]:
        chained: List[Enemy] = []
        current = target
        for _ in range(chain_count):
            if current is None or not current.is_alive:
                break
            current.take_damage(damage)
            chained.append(current)
            current = self._find_nearest_enemy(current.get_current_position(), enemies, {id(enemy) for enemy in chained})
        return chained

    @staticmethod
    def update_status_effects(enemies: List[Enemy], elapsed_time: float) -> None:
        for enemy in enemies:
            enemy.get_speed_modifier(elapsed_time)

    @staticmethod
    def _calculate_distance(pos1: tuple, pos2: tuple) -> float:
        return math.sqrt((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2)

    @classmethod
    def _find_nearest_enemy(cls, from_pos: tuple, enemies: List[Enemy], exclude: set) -> Optional[Enemy]:
        candidates = [enemy for enemy in enemies if enemy.is_alive and id(enemy) not in exclude]
        if not candidates:
            return None
        return min(candidates, key=lambda enemy: cls._calculate_distance(from_pos, enemy.get_current_position()))
