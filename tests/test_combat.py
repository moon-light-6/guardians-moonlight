import unittest

from game.combat import Combat
from game.enemy import Enemy, EnemyType
from game.map import GameMap
from game.actions import Action, ActionType
from game.engine import Game
from game.state import GamePhase
from game.tower import Tower
from config import SIMULATION_STEP


class TestCombat(unittest.TestCase):
    def test_targets_frontmost_enemy_in_range(self):
        game_map = GameMap()
        enemy_a = Enemy.create(EnemyType.BASIC, game_map.get_path(), 40)
        enemy_b = Enemy.create(EnemyType.BASIC, game_map.get_path(), 40)
        enemy_a.distance_travelled = 3
        enemy_b.distance_travelled = 6
        enemy_a.path_index = 3
        enemy_b.path_index = 6

        # 맵 경로 변경과 무관하게 두 적을 모두 사거리 안에 두고 진행도를 비교합니다.
        tower_pos = (enemy_a.x, enemy_a.y - 1)
        target = Combat().get_target(tower_pos, 10.0, [enemy_a, enemy_b])
        self.assertIs(target, enemy_b)

    def test_ice_slow_reduces_speed_temporarily(self):
        game_map = GameMap()
        enemy = Enemy.create(EnemyType.BASIC, game_map.get_path(), 40)
        enemy.apply_slow_effect(0.7, 2.0, 1.0)
        self.assertEqual(enemy.get_speed_modifier(1.5), 0.7)
        self.assertEqual(enemy.get_speed_modifier(3.1), 1.0)

    def test_upgrade_changes_next_attack_without_resetting_or_pausing_combat(self):
        for kind, damage, interval, effect_kind in (
            ("ARCHER", 15, 0.5, "claw"), ("CANNON", 40, 2, "fire"),
            ("ICE", 10, 4, "water"), ("LIGHTNING", 25, 1.5, "lightning"),
        ):
            with self.subTest(tower=kind):
                game = Game()
                state = game.reset(start_at_title=False)
                game.step(Action(ActionType.BUY, slot_id=0))
                tower = state.towers[0]
                tower["type"] = kind
                state.gold = 1000
                game.step(Action(ActionType.START_WAVE))
                game.wave_manager.spawn_queue = []
                position = game.map.get_slot_position(0)
                enemy = Enemy.create(EnemyType.BASIC, [position, (position[0] + 10, position[1])], 10000)
                enemy.speed = 0.1
                state.enemies = [enemy]
                game.update(SIMULATION_STEP)
                self.assertEqual(enemy.health, 10000 - damage)
                self.assertEqual(state.effects[0]["kind"], effect_kind)
                before = (state.wave_elapsed, tower["cooldown"], enemy.distance_travelled,
                          [effect.copy() for effect in state.effects], state.actions_taken_this_wave)
                old_stats = Tower.from_data(tower).get_stats()
                game.step(Action(ActionType.UPGRADE, slot_id=0))
                self.assertEqual((state.wave_elapsed, tower["cooldown"], enemy.distance_travelled,
                                  state.effects, state.actions_taken_this_wave), before)
                self.assertEqual(state.phase, GamePhase.WAVE_ACTIVE)
                self.assertEqual(state.gold, 940)
                new_stats = Tower.from_data(tower).get_stats()
                self.assertEqual(new_stats["damage"], damage * 1.6)
                self.assertEqual(new_stats["range"], old_stats["range"])
                self.assertEqual(new_stats["attack_interval"], old_stats["attack_interval"])
                game.update(interval)
                self.assertEqual(enemy.health, 10000 - damage - damage * 1.6)
                self.assertGreater(enemy.distance_travelled, before[2])
                self.assertGreater(state.wave_elapsed, before[0])
                self.assertEqual([effect for effect in state.effects if effect["kind"] != "slow_field"][-1]["kind"], effect_kind)


if __name__ == "__main__":
    unittest.main()
