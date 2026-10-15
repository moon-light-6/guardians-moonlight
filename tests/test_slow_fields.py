import unittest

from config import SIMULATION_STEP
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
        state.enemies = [Enemy.create(EnemyType.BASIC, [(10, 1), (11, 1), (12, 1)], 1000)
                         for _ in range(2)]
        for enemy in state.enemies:
            enemy.speed = 0
        return game

    def test_creates_fixed_tile_and_only_direct_target_takes_damage(self):
        game = self.make_game()
        game.update(SIMULATION_STEP)
        fields = [effect for effect in game.state.effects if effect["kind"] == "slow_field"]
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]["cell"], (10, 1))
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

    def test_leave_expire_and_overlap_do_not_leave_a_debuff(self):
        field = {"kind": "slow_field", "cell": (10, 1), "factor": 0.7, "age": 0, "ttl": 2}
        effects = [field, dict(field)]
        self.assertEqual(Combat.get_field_speed_modifier((10, 1), effects), 0.7)
        self.assertEqual(Combat.get_field_speed_modifier((10.5, 1), effects), 1)
        for effect in effects:
            effect["age"] = 2
        self.assertEqual(Combat.get_field_speed_modifier((10, 1), effects), 1)

    def test_two_second_gap_before_next_shot(self):
        game = self.make_game()
        game.update(SIMULATION_STEP)
        game.update(2)
        self.assertFalse(any(effect["kind"] == "slow_field" for effect in game.state.effects))
        self.assertEqual(game.state.enemies[0].health, 990)
        game.update(1.9)
        self.assertFalse(any(effect["kind"] == "slow_field" for effect in game.state.effects))
        game.update(0.1)
        self.assertTrue(any(effect["kind"] == "slow_field" for effect in game.state.effects))
        self.assertEqual(game.state.enemies[0].health, 980)

    def test_field_duration_uses_combat_speed(self):
        for speed in (1, 1.5, 2, 5):
            game = self.make_game()
            game.update(SIMULATION_STEP)
            game.state.combat_speed = speed
            game.update(1 / speed)
            fields = [effect for effect in game.state.effects if effect["kind"] == "slow_field"]
            self.assertEqual(len(fields), 1)
            self.assertAlmostEqual(fields[0]["age"], 1)
            game.update(1 / speed)
            self.assertFalse(any(effect["kind"] == "slow_field" for effect in game.state.effects))

    def test_wave_end_clears_field(self):
        game = self.make_game()
        game.update(SIMULATION_STEP)
        for enemy in game.state.enemies:
            enemy.take_damage(10000)
        game.update(SIMULATION_STEP)
        self.assertEqual(game.state.phase, GamePhase.SETTLEMENT)
        self.assertFalse(any(effect["kind"] == "slow_field" for effect in game.state.effects))
