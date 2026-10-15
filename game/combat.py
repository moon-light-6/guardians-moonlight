import math
from typing import Any, Dict, List, Optional

from game.enemy import Enemy
from game.tower import Tower, TowerType


class Combat:
    # 화면 연출 전용 시간. 실제 공격 간격과 장판 지속시간에는 영향을 주지 않음.
    EFFECT_TTL = {
        "claw": 0.40,       # 백호: 공격 주기 0.5초보다 짧게
        "fire": 0.65,
        "water": 0.60,
        "lightning": 1.00,  # 청룡 12프레임을 끝까지 보여주는 화면 연출 전용 시간
    }
    LIGHTNING_HIT_STAGGER = 0.12  # 연쇄 타겟 사이 화면 연출만 지연합니다.

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
            effects.append({"kind": "claw", "from": tower_pos, "to": target.get_current_position(),
                            "age": 0.0, "ttl": self.EFFECT_TTL["claw"]})
        elif tower_type == TowerType.CANNON:
            center = target.get_current_position()
            self.apply_splash_damage(center, stats["splash_radius"], stats["damage"], enemies)
            effects.append({"kind": "fire", "from": tower_pos, "to": center,
                            "age": 0.0, "ttl": self.EFFECT_TTL["fire"], "radius": stats["splash_radius"]})
        elif tower_type == TowerType.ICE:
            self.apply_damage(target, stats["damage"])
            cell = tuple(math.floor(value + 0.5) for value in target.get_current_position())
            effects.append({"kind": "water", "from": tower_pos, "to": target.get_current_position(),
                            "age": 0.0, "ttl": self.EFFECT_TTL["water"]})
            # 실제 이동속도 30% 감소와 2초 유지: 기존 규칙 그대로
            effects.append({
                "kind": "slow_field",
                "cell": cell,
                "factor": stats["slow_factor"],
                "age": 0.0,

                # 장판 이미지는 2초 유지
                "ttl": 2.0,

                # 실제 이동속도 감소는 2초만 적용
                "slow_ttl": stats["slow_duration"],
            })

        elif tower_type == TowerType.LIGHTNING:
            chain = self.apply_chain_damage(target, stats["damage"], stats["chain_count"], enemies)
            points = [enemy.get_current_position() for enemy in chain]
            hit_ttl = self.EFFECT_TTL["lightning"]
            effects.append({"kind": "lightning", "from": tower_pos, "points": points,
                            "age": 0.0, "hit_ttl": hit_ttl,
                            "hit_stagger": self.LIGHTNING_HIT_STAGGER,
                            "ttl": hit_ttl + self.LIGHTNING_HIT_STAGGER * max(0, len(points) - 1)})

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
    def get_field_speed_modifier(position: tuple, effects: list) -> float:
        """장판 표시와 실제 둔화 모두 최초 2초 동안 유지합니다."""

        x, y = position
        factors = [1.0]

        for effect in effects:
            if effect["kind"] != "slow_field":
                continue

            # 실제 둔화 유효시간은 별도로 판단
            slow_ttl = effect.get("slow_ttl", effect["ttl"])

            # 엔진의 이펙트 만료와 같은 오차 허용값으로 2초 경계를 맞춥니다.
            if effect["age"] >= slow_ttl - 1e-9:
                continue

            cx, cy = effect["cell"]

            if (
                cx - 0.5 <= x < cx + 0.5
                and cy - 0.5 <= y < cy + 0.5
            ):
                factors.append(effect["factor"])

        return min(factors)


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
