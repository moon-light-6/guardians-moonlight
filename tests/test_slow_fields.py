import unittest
import math

from config import SIMULATION_STEP, WAVE_CLEAR_DELAY
from game.actions import Action, ActionType
from game.combat import Combat
from game.enemy import Enemy, EnemyType
from game.engine import Game
from game.state import GamePhase


class TestSlowFields(unittest.TestCase):
    def make_game(self):
        game = Game()
        state = game.reset(seed=42, start_at_title=False)
        game.step(Action(ActionType.BUY, slot_id=9))
        state.towers[9]["type"] = "ICE"
        game.step(Action(ActionType.START_WAVE))
        game.wave_manager.spawn_queue = []
        position = game.map.get_slot_position(9)
        state.enemies = [Enemy.create(EnemyType.BASIC, [position, (position[0] + 1, position[1]),
                                                        (position[0] + 2, position[1])], 1000)
                         for _ in range(2)]
        for enemy in state.enemies:
            enemy.speed = 0
        return game

    @staticmethod
    def field_cell(game):
        position = game.map.get_slot_position(9)
        return tuple(math.floor(value + 0.5) for value in position)

    def test_creates_fixed_tile_and_only_direct_target_takes_damage(self):
        game = self.make_game()
        game.update(SIMULATION_STEP)
        fields = [effect for effect in game.state.effects if effect["kind"] == "slow_field"]
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]["cell"], self.field_cell(game))
        self.assertEqual(fields[0]["slow_ttl"], 2)
        self.assertEqual(fields[0]["ttl"], 2)
        self.assertEqual([enemy.health for enemy in game.state.enemies], [990, 1000])
        for enemy in game.state.enemies:
            self.assertEqual(Combat.get_field_speed_modifier(enemy.get_current_position(), fields), 0.7)
            self.assertNotIn("slow", enemy.status_effects)

    def test_actual_movement_is_slowed_for_all_enemies_in_tile(self):
        game = self.make_game()
        game.update(SIMULATION_STEP)
        for enemy in game.state.enemies:
            enemy.speed = 1
        game.update(0.25)
        for enemy in game.state.enemies:
            self.assertAlmostEqual(enemy.distance_travelled, 0.175)

    def test_field_position_stays_fixed_when_target_moves(self):
        game = self.make_game()
        game.update(SIMULATION_STEP)
        field = next(effect for effect in game.state.effects if effect["kind"] == "slow_field")
        for enemy in game.state.enemies:
            enemy.speed = 2
        game.update(1)
        self.assertEqual(field["cell"], self.field_cell(game))
        self.assertGreater(game.state.enemies[0].get_current_position()[0], 11)
        fields = [effect for effect in game.state.effects if effect["kind"] == "slow_field"]
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]["cell"], field["cell"])

    def test_leave_expire_and_overlap_do_not_leave_a_debuff(self):
        field = {"kind": "slow_field", "cell": (10, 1), "factor": 0.7, "age": 0, "ttl": 2}
        effects = [field, dict(field)]
        self.assertEqual(Combat.get_field_speed_modifier((10, 1), effects), 0.7)
        self.assertEqual(Combat.get_field_speed_modifier((10.5, 1), effects), 1)
        for effect in effects:
            effect["age"] = 2
        self.assertEqual(Combat.get_field_speed_modifier((10, 1), effects), 1)

    def test_slow_and_visual_expire_together_and_overlap_does_not_stack(self):
        field = {"kind": "slow_field", "cell": (10, 1), "factor": 0.7,
                 "age": 0, "ttl": 2, "slow_ttl": 2}
        for age, expected in ((0, 0.7), (1.6, 0.7), (1.999, 0.7), (2, 1), (3, 1)):
            with self.subTest(age=age):
                field["age"] = age
                self.assertEqual(Combat.get_field_speed_modifier((10, 1), [field, dict(field)]), expected)
        # 만료된 PNG와 새 장판이 겹치면 새 장판의 둔화만 적용됩니다.
        fresh = {**field, "age": 0}
        self.assertEqual(Combat.get_field_speed_modifier((10, 1), [field, fresh]), 0.7)

    def test_actual_movement_returns_to_normal_when_visual_expires(self):
        game = self.make_game()
        game.update(SIMULATION_STEP)
        game.state.towers.clear()  # 재공격 없이 최초 장판의 만료만 확인합니다.
        for enemy in game.state.enemies:
            enemy.speed = 0.1  # 검사 중 같은 타일 안에 머물게 합니다.
        game.update(2 - SIMULATION_STEP)
        for enemy in game.state.enemies:
            self.assertAlmostEqual(enemy.distance_travelled, 0.1 * 0.7 * (2 - SIMULATION_STEP))
        before = [enemy.distance_travelled for enemy in game.state.enemies]
        game.update(SIMULATION_STEP)
        fields = [effect for effect in game.state.effects if effect["kind"] == "slow_field"]
        self.assertEqual(fields, [])
        for enemy, distance in zip(game.state.enemies, before):
            self.assertEqual(Combat.get_field_speed_modifier(enemy.get_current_position(), fields), 1)
            self.assertAlmostEqual(enemy.distance_travelled - distance, 0.1 * SIMULATION_STEP)
        before = [enemy.distance_travelled for enemy in game.state.enemies]
        game.update(1)
        for enemy, distance in zip(game.state.enemies, before):
            self.assertAlmostEqual(enemy.distance_travelled - distance, 0.1)
        self.assertFalse(any(effect["kind"] == "slow_field" for effect in game.state.effects))

    def test_two_second_gap_before_next_shot(self):
        game = self.make_game()
        game.update(SIMULATION_STEP)
        game.update(2)
        fields = [effect for effect in game.state.effects if effect["kind"] == "slow_field"]
        self.assertEqual(fields, [])
        self.assertEqual(Combat.get_field_speed_modifier((10, 1), fields), 1)
        self.assertEqual(game.state.enemies[0].health, 990)
        game.update(1.9)
        fields = [effect for effect in game.state.effects if effect["kind"] == "slow_field"]
        self.assertEqual(fields, [])
        self.assertEqual(Combat.get_field_speed_modifier((10, 1), fields), 1)
        game.update(0.1)
        fields = [effect for effect in game.state.effects if effect["kind"] == "slow_field"]
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]["age"], 0)
        self.assertEqual(Combat.get_field_speed_modifier(self.field_cell(game), fields), 0.7)
        self.assertEqual(game.state.enemies[0].health, 980)

    def test_field_duration_uses_combat_speed(self):
        for speed in (1, 1.5, 2, 5):
            game = self.make_game()
            game.update(SIMULATION_STEP)
            game.state.towers.clear()
            game.state.combat_speed = speed
            game.update(1 / speed)
            fields = [effect for effect in game.state.effects if effect["kind"] == "slow_field"]
            self.assertEqual(len(fields), 1)
            self.assertAlmostEqual(fields[0]["age"], 1)
            game.update((1 - SIMULATION_STEP) / speed)
            self.assertTrue(any(effect["kind"] == "slow_field" for effect in game.state.effects))
            game.update(SIMULATION_STEP / speed)
            self.assertFalse(any(effect["kind"] == "slow_field" for effect in game.state.effects))
            self.assertEqual(Combat.get_field_speed_modifier((10, 1), game.state.effects), 1)

    def test_wave_end_clears_field(self):
        for age in (0, 1.8):
            with self.subTest(age=age):
                game = self.make_game()
                game.update(SIMULATION_STEP)
                game.update(age)
                for enemy in game.state.enemies:
                    enemy.take_damage(10000)
                game.update(SIMULATION_STEP)
                game.update(WAVE_CLEAR_DELAY + 2.0)  # 막타 연출과 빈 게임판 대기가 끝나야 정산된다
                self.assertEqual(game.state.phase, GamePhase.SETTLEMENT)
                self.assertFalse(any(effect["kind"] == "slow_field" for effect in game.state.effects))
