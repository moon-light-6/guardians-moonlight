import unittest
from unittest.mock import patch

from game.actions import Action, ActionType
from game.engine import Game
from game.enemy import Enemy, EnemyType
from game.state import GamePhase
from game.tower import Tower
from game.wave import WaveManager


class TestGameEngine(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.state = self.game.reset(seed=42, start_at_title=False)

    def test_game_initialization(self):
        self.assertEqual(self.state.current_stage, 1)
        self.assertEqual(self.state.gold, 200)
        self.assertEqual(self.state.life, 20)
        self.assertEqual(self.state.phase, GamePhase.PREPARATION)

    def test_seeded_random_summon(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        first_type = self.state.towers[0]["type"]

        other = Game()
        other_state = other.reset(seed=42, start_at_title=False)
        other.step(Action(ActionType.BUY, slot_id=0))

        self.assertEqual(first_type, other_state.towers[0]["type"])
        self.assertEqual(self.state.gold, 100)

    def test_start_wave(self):
        self.game.step(Action(ActionType.START_WAVE))
        self.assertEqual(self.state.phase, GamePhase.WAVE_ACTIVE)

    def test_wave_can_finish_without_pygame(self):
        for slot in [6, 8]:
            self.game.step(Action(ActionType.BUY, slot_id=slot))
        self.game.step(Action(ActionType.START_WAVE))
        for _ in range(900):
            self.game.update(0.1)
            if self.state.phase != GamePhase.WAVE_ACTIVE:
                break
        self.assertIn(self.state.phase, {GamePhase.SETTLEMENT, GamePhase.GAME_OVER})

    def test_restart_from_title(self):
        state = self.game.reset(seed=1)
        self.assertEqual(state.phase, GamePhase.TITLE)
        self.game.step(Action(ActionType.START_GAME))
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)

    def test_stage_five_continues_and_preserves_resources(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.state.towers[0]["level"] = 3
        self.state.current_stage = 5
        self.state.combat_speed = 1.5
        self.state.life = 11
        self.state.phase = GamePhase.SETTLEMENT
        before = (self.state.towers.copy(), self.state.gold, self.state.life)
        self.game.step(Action(ActionType.CONTINUE))
        self.assertEqual(self.state.current_stage, 6)
        self.assertEqual(self.state.phase, GamePhase.PREPARATION)
        self.assertEqual((self.state.towers, self.state.gold, self.state.life), before)
        self.assertEqual(self.state.combat_speed, 1.5)
        self.assertEqual(self.state.actions_taken_this_wave, 0)

    def test_all_thirty_waves_settle_then_final_victory(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.state.towers[0]["type"] = "ARCHER"
        expected_gold = self.state.gold
        # A strong test-only tower isolates progression from the preset balance.
        with patch.object(Tower, "get_stats", return_value={"damage": 1000000, "range": 100, "attack_interval": 0.5}):
            for stage in range(1, 31):
                with self.subTest(stage=stage):
                    self.assertEqual(self.state.current_stage, stage)
                    self.assertEqual(self.state.phase, GamePhase.PREPARATION)
                    self.game.step(Action(ActionType.START_WAVE))
                    for _ in range(600):
                        self.game.update(0.1)
                        if self.state.phase != GamePhase.WAVE_ACTIVE:
                            break
                    self.assertEqual(self.state.phase, GamePhase.SETTLEMENT)
                    expected_gold += WaveManager.STAGE_COUNTS[stage] * 5 + 100 + stage * 5
                    if stage % 5 == 0:
                        expected_gold += 100  # 보스 처치 보상
                    if stage % 5 == 0 or 26 <= stage <= 29:
                        expected_gold += 100  # 추가 클리어 보상
                    self.assertEqual(self.state.gold, expected_gold)
                    self.assertEqual(self.state.wave_result.normal_kills, WaveManager.STAGE_COUNTS[stage])
                    self.assertEqual(self.state.wave_result.boss_kills, int(stage % 5 == 0))
                    self.assertEqual(self.state.life, 20)
                    self.game.step(Action(ActionType.CONTINUE))
        self.assertEqual(self.state.phase, GamePhase.VICTORY)
        self.assertEqual(self.state.current_stage, 30)
        self.game.step(Action(ActionType.CONTINUE))
        self.assertEqual(self.state.gold, expected_gold)

    def test_each_boss_escape_deducts_exact_life(self):
        for stage, boss_data in WaveManager.BOSSES.items():
            with self.subTest(stage=stage):
                game = Game()
                game.reset(start_at_title=False)
                game.state.current_stage = stage
                game.step(Action(ActionType.START_WAVE))
                boss = Enemy.create(EnemyType.BOSS, [(0, 0), (0.001, 0)], boss_data["hp"], boss_data["name"])
                boss.life_damage = boss_data["life_damage"]
                game.state.enemies = [boss]
                game.wave_manager.spawn_queue = []
                game.update(0.1)
                self.assertEqual(game.state.life, 20 - boss_data["life_damage"])
                self.assertEqual(game.state.wave_boss_gold, 0)
                expected_phase = GamePhase.GAME_OVER if stage == 30 else GamePhase.SETTLEMENT
                self.assertEqual(game.state.phase, expected_phase)

    def test_fatal_escape_stops_combat_immediately_without_clear_reward(self):
        self.game.step(Action(ActionType.START_WAVE))
        self.state.life = 1
        enemy = Enemy.create(EnemyType.BASIC, [(0, 0), (0.001, 0)], 40)
        self.state.enemies = [enemy]
        self.game.wave_manager.spawn_queue = []
        gold = self.state.gold
        self.game.update(5)
        self.assertEqual(self.state.phase, GamePhase.GAME_OVER)
        self.assertLessEqual(self.state.life, 0)
        self.assertLess(self.state.wave_elapsed, 0.02)
        self.assertEqual(self.state.gold, gold)
        self.game.step(Action(ActionType.CANCEL))
        self.assertEqual(self.state.phase, GamePhase.GAME_OVER)

    def test_final_boss_escape_is_defeat_even_at_full_life(self):
        for life in (20, 5):
            with self.subTest(life=life):
                game = Game()
                state = game.reset(start_at_title=False)
                state.current_stage = 30
                state.life = life
                game.step(Action(ActionType.START_WAVE))
                spawned = game.wave_manager.update(100, [(0, 0), (0.001, 0)])
                boss = next(enemy for enemy in spawned if enemy.is_boss)
                self.assertEqual(boss.life_damage, 20)
                state.enemies = [boss]
                gold_before = state.gold
                game.update(0.1)
                self.assertTrue(boss.reached_base)
                self.assertEqual(state.life, life - 20)
                self.assertEqual(state.phase, GamePhase.GAME_OVER)
                self.assertEqual(state.gold, gold_before)
                self.assertEqual(state.wave_clear_gold, 0)
                self.assertNotIn(30, state.clear_rewarded_stages)
                game.step(Action(ActionType.CONTINUE))
                self.assertEqual(state.phase, GamePhase.GAME_OVER)


if __name__ == "__main__":
    unittest.main()
