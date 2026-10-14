import unittest

from game.actions import Action, ActionType
from game.enemy import Enemy, EnemyType
from game.engine import Game
from game.state import GamePhase
from game.tower import Tower


class TestCombatSpeed(unittest.TestCase):
    def stationary_target_game(self):
        game = Game()
        game.reset(seed=42, start_at_title=False)
        game.step(Action(ActionType.BUY, slot_id=0))
        game.state.towers[0]["type"] = "ARCHER"
        game.state.towers[0]["cooldown"] = 0
        game.step(Action(ActionType.START_WAVE))
        position = game.map.get_slot_position(0)
        enemy = Enemy.create(EnemyType.BASIC, [position, (position[0] + 10, position[1])], 10000)
        enemy.speed = 0
        game.state.enemies = [enemy]
        game.wave_manager.spawn_queue = []
        return game, enemy

    def test_cycle_and_restart_reset(self):
        game = Game()
        game.reset(start_at_title=False)
        game.step(Action(ActionType.CYCLE_SPEED))
        self.assertEqual(game.state.combat_speed, 1)
        game.step(Action(ActionType.START_WAVE))
        for speed in (1.5, 2, 5, 1, 1.5, 2, 5):
            game.step(Action(ActionType.CYCLE_SPEED))
            self.assertEqual(game.state.combat_speed, speed)
        game.step(Action(ActionType.RESTART))
        self.assertEqual(game.state.combat_speed, 1)
        game.step(Action(ActionType.START_WAVE))
        for _ in range(3):
            game.step(Action(ActionType.CYCLE_SPEED))
        self.assertEqual(game.state.combat_speed, 5)
        game.step(Action(ActionType.BACK_TO_TITLE))
        self.assertEqual(game.state.combat_speed, 1)
        game.step(Action(ActionType.START_GAME))
        self.assertEqual(game.state.combat_speed, 1)

    def test_equal_game_time_has_identical_damage_and_cooldown(self):
        for speed, frames in ((1, 120), (1.5, 80), (2, 60), (5, 24)):
            with self.subTest(speed=speed):
                game, enemy = self.stationary_target_game()
                stats = Tower.from_data(game.state.towers[0]).get_stats()
                game.state.combat_speed = speed
                for _ in range(frames):
                    game.update(1 / 60)
                self.assertAlmostEqual(game.state.wave_elapsed, 2)
                self.assertEqual(enemy.health, 10000 - 4 * 15)
                self.assertAlmostEqual(game.state.towers[0]["cooldown"], 0)
                self.assertEqual(Tower.from_data(game.state.towers[0]).get_stats(), stats)

    def test_large_frame_uses_substeps_without_missing_attacks(self):
        for speed, attacks in ((2, 8), (5, 20)):
            with self.subTest(speed=speed):
                game, enemy = self.stationary_target_game()
                game.state.combat_speed = speed
                game.update(2)
                self.assertEqual(enemy.health, 10000 - attacks * 15)
                self.assertAlmostEqual(game.state.wave_elapsed, 2 * speed)

    def test_effect_age_and_slow_expiry_use_scaled_time(self):
        for speed in (1, 1.5, 2, 5):
            with self.subTest(speed=speed):
                game, enemy = self.stationary_target_game()
                game.state.towers.clear()
                game.state.combat_speed = speed
                enemy.speed = 1
                enemy.apply_slow_effect(0.7, 2, 0)
                game.state.effects = [{"kind": "water", "age": 0, "ttl": 1}]
                game.update(0.4 / speed)
                self.assertAlmostEqual(game.state.effects[0]["age"], 0.4)
                self.assertAlmostEqual(enemy.distance_travelled, 0.28)
                game.update(1.62 / speed)
                self.assertNotIn("slow", enemy.status_effects)
                self.assertEqual(game.state.effects, [])

    def battle_game(self, speed):
        game = Game()
        game.reset(seed=42, start_at_title=False)
        game.state.current_stage = 5
        for slot in range(24):
            game.state.towers[slot] = {"type": Tower.all_types()[slot % 4], "level": 3, "slot_id": slot, "cooldown": 0}
            game.state.tower_slots[slot] = True
        game.state.combat_speed = speed
        game.step(Action(ActionType.START_WAVE))
        return game

    def snapshot(self, game):
        state = game.state
        return (state.phase, state.gold, state.life, state.wave_result,
                [(enemy.health, enemy.distance_travelled, enemy.status_effects) for enemy in state.enemies],
                state.effects, [tower["cooldown"] for tower in state.towers.values()],
                game.wave_manager.spawn_queue)

    def test_full_wave_rewards_and_damage_identical_at_every_speed(self):
        results = []
        for speed in (1, 1.5, 2, 5):
            game = self.battle_game(speed)
            for _ in range(7200):
                game.update(1 / 60)
                if game.state.phase != GamePhase.WAVE_ACTIVE:
                    break
            self.assertEqual(game.state.phase, GamePhase.SETTLEMENT)
            self.assertEqual(game.state.wave_boss_gold, 100)
            results.append(self.snapshot(game))
        for result in results[1:]:
            self.assertEqual(results[0], result)

    def test_mid_wave_speed_changes_and_frame_sizes_preserve_simulation(self):
        baseline = self.battle_game(1)
        baseline.update(10)
        changing = self.battle_game(1)
        changing.update(2)
        changing.step(Action(ActionType.CYCLE_SPEED))
        changing.update(2)
        changing.step(Action(ActionType.CYCLE_SPEED))
        changing.update(0.5)
        changing.step(Action(ActionType.CYCLE_SPEED))
        for _ in range(80):
            changing.update(0.01)
        self.assertEqual(self.snapshot(baseline), self.snapshot(changing))
        self.assertAlmostEqual(changing.state.wave_elapsed, 10)

    def test_negative_dt_is_ignored(self):
        game, _ = self.stationary_target_game()
        game.update(-1)
        self.assertEqual(game.state.wave_elapsed, 0)

    def test_spawn_interval_uses_scaled_time(self):
        for speed, expected_count in ((1, 0), (1.5, 0), (2, 1), (5, 3)):
            with self.subTest(speed=speed):
                game = Game()
                game.reset(start_at_title=False)
                game.step(Action(ActionType.START_WAVE))
                game.state.combat_speed = speed
                game.update(0.4)
                self.assertAlmostEqual(game.wave_manager.current_time, 0.4 * speed)
                self.assertEqual(len(game.state.enemies), expected_count)

    def test_switching_to_five_preserves_existing_wave_and_towers(self):
        game = self.battle_game(1)
        game.update(3)
        state = game.state
        state.selected_slot = 0
        before = self.snapshot(game)
        elapsed, spawn_time = state.wave_elapsed, game.wave_manager.current_time
        towers = state.towers
        for _ in range(3):
            game.step(Action(ActionType.CYCLE_SPEED))
        self.assertEqual(state.combat_speed, 5)
        self.assertIs(game.state, state)
        self.assertIs(state.towers, towers)
        self.assertEqual(self.snapshot(game), before)
        self.assertEqual((state.current_stage, state.selected_slot), (5, 0))
        self.assertEqual((state.wave_elapsed, game.wave_manager.current_time), (elapsed, spawn_time))

    def test_five_speed_wave_completion_and_next_wave_preserve_resources(self):
        game = self.battle_game(5)
        for _ in range(1440):
            game.update(1 / 60)
            if game.state.phase != GamePhase.WAVE_ACTIVE:
                break
        state = game.state
        self.assertEqual(state.phase, GamePhase.SETTLEMENT)
        before = (state.gold, state.life, {slot: tower.copy() for slot, tower in state.towers.items()})
        game.step(Action(ActionType.CONTINUE))
        self.assertEqual((state.phase, state.current_stage, state.combat_speed), (GamePhase.PREPARATION, 6, 5))
        self.assertEqual((state.gold, state.life, state.towers), before)
        game.step(Action(ActionType.START_WAVE))
        self.assertEqual(state.combat_speed, 5)
        self.assertEqual(state.phase, GamePhase.WAVE_ACTIVE)
        game.update(0.2)
        self.assertAlmostEqual(state.wave_elapsed, 1)
        self.assertTrue(state.enemies)

    def test_five_speed_enemies_follow_path_through_turns_to_base(self):
        game = Game()
        game.reset(start_at_title=False)
        game.step(Action(ActionType.START_WAVE))
        game.state.combat_speed = 5
        path = game.map.get_path()
        for _ in range(1200):
            game.update(1 / 60)
            for enemy in game.state.enemies:
                start = path[enemy.path_index]
                end = path[min(enemy.path_index + 1, len(path) - 1)]
                x, y = enemy.get_current_position()
                self.assertTrue(min(start[0], end[0]) <= x <= max(start[0], end[0]))
                self.assertTrue(min(start[1], end[1]) <= y <= max(start[1], end[1]))
            if game.state.phase != GamePhase.WAVE_ACTIVE:
                break
        self.assertEqual(game.state.phase, GamePhase.SETTLEMENT)
        self.assertEqual(game.state.wave_result.reached_base, 8)
        self.assertEqual(game.state.life, 12)

