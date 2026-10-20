import unittest
from unittest.mock import patch

from config import (
    BOSS_KILL_GOLD,
    CLEAR_GOLD_BASE,
    CLEAR_GOLD_BONUS,
    CLEAR_GOLD_BONUS_STAGES,
    CLEAR_GOLD_PER_STAGE,
    KILL_GOLD,
)
from game.actions import Action, ActionType
from game.economy import Economy
from game.enemy import Enemy, EnemyType
from game.engine import Game
from game.state import GamePhase, GameState


def clear_reward(stage):
    """config.py 보상 수치로 계산한 소동 해결 보상(수치를 조정해도 테스트가 따라간다)."""
    return CLEAR_GOLD_BASE + stage * CLEAR_GOLD_PER_STAGE + (CLEAR_GOLD_BONUS if stage in CLEAR_GOLD_BONUS_STAGES else 0)


class TestRewards(unittest.TestCase):
    def enemy(self, kind=EnemyType.BASIC, killed=True):
        enemy = Enemy.create(kind, [(0, 0), (1, 0)], 100)
        if killed:
            enemy.take_damage(100)
        return enemy

    def test_enemy_reward_matches_type(self):
        for kind in EnemyType:
            with self.subTest(kind=kind):
                self.assertEqual(self.enemy(kind).gold_reward, 100 if kind == EnemyType.BOSS else 5)

    def test_kill_callback_pays_each_enemy_once_and_tracks_normal_and_boss_totals(self):
        state = GameState(phase=GamePhase.WAVE_ACTIVE)
        economy = Economy()
        for kind in EnemyType:
            enemy = self.enemy(kind)
            self.assertTrue(economy.on_enemy_killed(state, enemy))
            self.assertFalse(Economy().on_enemy_killed(state, enemy))
            self.assertTrue(enemy.reward_paid)
        self.assertEqual(state.gold, 200 + 3 * 5 + 100)
        self.assertEqual((state.enemies_killed, state.bosses_killed), (3, 1))
        self.assertEqual((state.wave_kill_gold, state.wave_boss_gold), (15, 100))

    def test_alive_escaped_and_out_of_combat_enemies_do_not_pay(self):
        for kind in EnemyType:
            with self.subTest(kind=kind):
                state = GameState(phase=GamePhase.WAVE_ACTIVE)
                alive = self.enemy(kind, killed=False)
                escaped = self.enemy(kind, killed=False)
                escaped.move(10)
                self.assertTrue(escaped.reached_base)
                economy = Economy()
                self.assertFalse(economy.on_enemy_killed(state, alive))
                self.assertFalse(economy.on_enemy_killed(state, escaped))
                state.phase = GamePhase.SETTLEMENT
                self.assertFalse(economy.on_enemy_killed(state, self.enemy(kind)))
                self.assertEqual(state.gold, 200)
                self.assertEqual((state.enemies_killed, state.bosses_killed), (0, 0))

    def test_clear_callback_uses_current_stage_and_pays_once_without_advancing(self):
        # 5의 배수와 26~29소동만 추가 클리어 보상을 받는다(24소동은 받지 않음).
        self.assertEqual(CLEAR_GOLD_BONUS_STAGES, frozenset({5, 10, 15, 20, 25, 26, 27, 28, 29, 30}))
        for stage in (1, 5, 10, 15, 20, 24, 25, 26, 27, 28, 29, 30):
            reward = clear_reward(stage)
            with self.subTest(stage=stage):
                state = GameState(phase=GamePhase.WAVE_ACTIVE, current_stage=stage)
                self.assertTrue(Economy().on_stage_clear(state))
                self.assertFalse(Economy().on_stage_clear(state))
                self.assertEqual(state.gold, 200 + reward)
                self.assertEqual(state.wave_clear_gold, reward)
                self.assertEqual(state.current_stage, stage)
                self.assertEqual(state.clear_rewarded_stages, {stage})

    def test_clear_callback_rejects_defeat_active_enemies_and_wrong_phase(self):
        for phase, life, active_enemy in (
            (GamePhase.PREPARATION, 20, False), (GamePhase.SETTLEMENT, 20, False),
            (GamePhase.GAME_OVER, 0, False), (GamePhase.WAVE_ACTIVE, 0, False),
            (GamePhase.WAVE_ACTIVE, -3, False), (GamePhase.WAVE_ACTIVE, 20, True),
        ):
            with self.subTest(phase=phase, life=life, active_enemy=active_enemy):
                state = GameState(phase=phase, life=life)
                if active_enemy:
                    state.enemies = [self.enemy(killed=False)]
                self.assertFalse(Economy().on_stage_clear(state))
                self.assertEqual(state.gold, 200)
                self.assertEqual(state.wave_clear_gold, 0)
                self.assertEqual(state.clear_rewarded_stages, set())

    def test_engine_callbacks_drive_settlement_and_next_wave_rewards(self):
        game = Game()
        state = game.reset(start_at_title=False)
        state.current_stage = 5
        game.step(Action(ActionType.START_WAVE))
        game.wave_manager.spawn_queue = []
        normal, boss = self.enemy(), self.enemy(EnemyType.BOSS)
        state.enemies = [normal, boss, normal, boss]
        with patch.object(game.economy, "on_enemy_killed", wraps=game.economy.on_enemy_killed) as kill_callback:
            with patch.object(game.economy, "on_stage_clear", wraps=game.economy.on_stage_clear) as clear_callback:
                game.update(1 / 60)
                self.assertEqual(kill_callback.call_count, 4)
                clear_callback.assert_called_once_with(state)
        total = KILL_GOLD + BOSS_KILL_GOLD + clear_reward(5)
        self.assertEqual(state.phase, GamePhase.SETTLEMENT)
        self.assertEqual(state.gold, 200 + total)
        self.assertEqual((state.enemies_killed, state.bosses_killed), (1, 1))
        result = state.wave_result
        self.assertEqual((result.stage, result.normal_kills, result.boss_kills), (5, 1, 1))
        self.assertEqual((result.kill_gold, result.boss_gold, result.clear_gold, result.total_gold),
                         (KILL_GOLD, BOSS_KILL_GOLD, clear_reward(5), total))
        state.enemies = [normal, boss]
        game._collect_dead_enemies()
        game._transition_to_settlement()
        self.assertFalse(game.economy.on_stage_clear(state))
        self.assertEqual(state.gold, 200 + total)
        self.assertIs(state.wave_result, result)
        game.step(Action(ActionType.CONTINUE))
        self.assertEqual(state.current_stage, 6)
        self.assertEqual(state.gold, 200 + total)
        game.step(Action(ActionType.START_WAVE))
        self.assertEqual((state.wave_kill_gold, state.wave_boss_gold, state.wave_clear_gold), (0, 0, 0))
        game.wave_manager.spawn_queue = []
        game.update(1 / 60)
        self.assertEqual(state.phase, GamePhase.SETTLEMENT)
        self.assertEqual(state.gold, 200 + total + clear_reward(6))
        self.assertEqual(state.wave_result.clear_gold, clear_reward(6))
        self.assertEqual(state.clear_rewarded_stages, {5, 6})

    def test_engine_does_not_clear_before_pending_spawns(self):
        game = Game()
        state = game.reset(start_at_title=False)
        game.step(Action(ActionType.START_WAVE))
        game._transition_to_settlement()
        self.assertEqual(state.gold, 200)
        self.assertEqual(state.phase, GamePhase.WAVE_ACTIVE)
        self.assertEqual(state.clear_rewarded_stages, set())

    def test_new_run_resets_clear_reward_ledger(self):
        game = Game()
        game.reset(start_at_title=False)
        game.step(Action(ActionType.START_WAVE))
        game.wave_manager.spawn_queue = []
        game.update(1 / 60)
        self.assertEqual(game.state.gold, 200 + clear_reward(1))
        self.assertEqual(game.state.clear_rewarded_stages, {1})
        game.step(Action(ActionType.RESTART))
        self.assertEqual(game.state.clear_rewarded_stages, set())
        game.step(Action(ActionType.START_WAVE))
        game.wave_manager.spawn_queue = []
        game.update(1 / 60)
        self.assertEqual(game.state.gold, 200 + clear_reward(1))


if __name__ == "__main__":
    unittest.main()
