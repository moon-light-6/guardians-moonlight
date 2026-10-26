import unittest
from unittest.mock import patch

from config import (
    BOSS_KILL_GOLD, CLEAR_GOLD_BASE, CLEAR_GOLD_BONUS, CLEAR_GOLD_PER_STAGE, KILL_GOLD, SIMULATION_STEP,
    WAVE_CLEAR_DELAY,
)
from game.actions import Action, ActionType, ActionValidator
from game.engine import Game
from game.enemy import Enemy, EnemyType
from game.state import GamePhase
from game.tower import Tower
from game.wave import WaveManager

# 막타 공격 연출(청룡 연쇄 최대 약 1.5초)과 빈 게임판 대기가 모두 끝나 정산될 만큼의 시간
WAVE_CLEAR_WAIT = WAVE_CLEAR_DELAY + 2.0


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

    def test_final_attack_effects_are_cleared_before_settlement_and_next_wave(self):
        for tower_type in Tower.all_types():
            with self.subTest(tower_type=tower_type):
                self.state = self.game.reset(seed=42, start_at_title=False)
                self.game.step(Action(ActionType.BUY, slot_id=0))
                self.state.towers[0]["type"] = tower_type
                self.game.step(Action(ActionType.START_WAVE))
                position = self.game.map.get_slot_position(0)
                enemy = Enemy.create(EnemyType.BASIC, [position, (position[0] + 10, position[1])], 1)
                enemy.speed = 0
                self.state.enemies = [enemy]
                self.game.wave_manager.spawn_queue = []

                self.game.update(1 / 120)

                # 막타 직후에는 정산하지 않고 공격 연출을 남겨 둔다.
                self.assertEqual(self.state.phase, GamePhase.WAVE_ACTIVE)
                self.assertTrue(any(effect["kind"] != "slow_field" for effect in self.state.effects))
                gold = self.state.gold
                self.game.update(WAVE_CLEAR_WAIT)

                self.assertEqual(self.state.phase, GamePhase.SETTLEMENT)
                self.assertEqual(self.state.effects, [])
                self.assertGreater(self.state.gold, gold)  # 정산 보상은 마무리 시간이 끝난 뒤 한 번만
                cooldown = self.state.towers[0]["cooldown"]
                self.game.step(Action(ActionType.CONTINUE))
                self.assertEqual(self.state.effects, [])
                self.game.step(Action(ActionType.START_WAVE))
                self.assertEqual(self.state.effects, [])
                self.assertEqual(self.state.towers[0]["cooldown"], cooldown)

    def test_wave_clear_waits_for_attack_effects_then_empty_board_delay(self):
        self.game.step(Action(ActionType.START_WAVE))
        self.game.wave_manager.spawn_queue = []
        self.state.enemies = []
        self.state.effects = [
            {"kind": "claw", "from": (0, 0), "to": (1, 0), "age": 0.0, "ttl": 0.4},
            {"kind": "slow_field", "cell": (1, 0), "factor": 0.7, "age": 0.0, "ttl": 2.0, "slow_ttl": 2.0},
        ]
        life, gold = self.state.life, self.state.gold
        self.game.update(SIMULATION_STEP)
        self.assertEqual(self.state.phase, GamePhase.WAVE_ACTIVE)
        self.assertEqual(self.state.wave_clear_elapsed, 0.0)

        # 공격 연출이 남아 있는 동안에는 빈 판 대기 시간이 흐르지 않는다.
        self.game.update(0.39)
        self.assertEqual(self.state.wave_clear_elapsed, 0.0)
        # 공격 연출이 끝나면 현무 장판이 남아 있어도 대기 시간이 흐른다.
        self.game.update(0.02 + WAVE_CLEAR_DELAY - 0.05)
        self.assertEqual(self.state.phase, GamePhase.WAVE_ACTIVE)
        self.assertTrue(any(effect["kind"] == "slow_field" for effect in self.state.effects))
        self.assertEqual((self.state.life, self.state.gold), (life, gold))

        self.game.update(0.05)
        self.assertEqual(self.state.phase, GamePhase.SETTLEMENT)
        self.assertEqual(self.state.effects, [])
        self.assertIsNone(self.state.wave_clear_elapsed)
        self.game.step(Action(ActionType.CONTINUE))
        self.game.step(Action(ActionType.START_WAVE))
        self.assertIsNone(self.state.wave_clear_elapsed)

    def test_relocate_in_preparation_matches_valid_action_list(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        relocate = Action(ActionType.RELOCATE, from_slot_id=0, to_slot_id=1)
        self.assertTrue(any(
            (a.action_type, a.from_slot_id, a.to_slot_id) == (ActionType.RELOCATE, 0, 1)
            for a in ActionValidator.get_all_valid_actions(self.state)
        ))
        self.game.step(relocate)
        self.assertEqual(self.state.phase, GamePhase.PREPARATION)
        self.assertTrue(self.state.has_tower(1))
        self.assertTrue(self.state.is_slot_empty(0))
        self.assertEqual(self.state.actions_taken_this_wave, 2)
        # 같은 행동을 다시 보내면 옮길 사신이 없어 아무것도 바뀌지 않는다.
        self.game.step(relocate)
        self.assertTrue(self.state.has_tower(1))
        self.assertEqual(self.state.actions_taken_this_wave, 2)

    def test_restart_from_title(self):
        state = self.game.reset(seed=1)
        self.assertEqual(state.phase, GamePhase.TITLE)
        self.game.step(Action(ActionType.START_GAME))
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)

    def test_is_boss_stage_only_for_boss_stages(self):
        for stage in range(1, 31):
            with self.subTest(stage=stage):
                self.assertEqual(WaveManager.is_boss_stage(stage), stage % 5 == 0)
        self.assertFalse(WaveManager.is_boss_stage(31))

    def test_continue_moves_to_next_stage_without_any_popup_state(self):
        # 큰 소동 예고 팝업은 화면(입력 핸들러) 상태라서 엔진 상태에는 흔적이 없어야 한다.
        self.state.current_stage = 4
        self.state.phase = GamePhase.SETTLEMENT
        self.game.step(Action(ActionType.CONTINUE))
        self.assertEqual(self.state.current_stage, 5)
        self.assertEqual(self.state.phase, GamePhase.PREPARATION)
        self.assertFalse(hasattr(self.state, "boss_warning"))

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
                    expected_gold += (WaveManager.STAGE_COUNTS[stage] * KILL_GOLD
                                      + CLEAR_GOLD_BASE + stage * CLEAR_GOLD_PER_STAGE)
                    if stage % 5 == 0:
                        expected_gold += BOSS_KILL_GOLD  # 보스 악귀 처치 보상
                    if stage % 5 == 0 or 26 <= stage <= 29:
                        expected_gold += CLEAR_GOLD_BONUS  # 추가 클리어 보상
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
                game.update(WAVE_CLEAR_WAIT)
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
