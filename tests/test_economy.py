import unittest

from game.actions import Action, ActionType, ActionValidator
from game.economy import Economy
from game.engine import Game
from game.enemy import Enemy, EnemyType
from game.state import GamePhase


class TestEconomy(unittest.TestCase):
    def make_tower(self, level=1):
        game = Game()
        game.reset(seed=4, start_at_title=False)
        game.step(Action(ActionType.BUY, slot_id=0))
        game.state.gold = 2000
        for _ in range(level - 1):
            game.step(Action(ActionType.UPGRADE, slot_id=0))
        return game

    def test_confirm_sell_refunds_each_level_once_and_clears_selection(self):
        for level, refund in enumerate((60, 96, 156, 252, 402), 1):
            with self.subTest(level=level):
                game = self.make_tower(level)
                state = game.state
                gold, actions = state.gold, state.actions_taken_this_wave
                game.step(Action(ActionType.SELL, slot_id=0))
                self.assertEqual(state.phase, GamePhase.SELL_CONFIRM)
                self.assertEqual(state.gold, gold)
                self.assertEqual(state.actions_taken_this_wave, actions)
                confirm = Action(ActionType.CONFIRM_SELL, slot_id=0)
                self.assertTrue(ActionValidator.is_valid_action(confirm, state))
                game.step(confirm)
                game.step(confirm)
                self.assertEqual(state.gold, gold + refund)
                self.assertEqual(state.actions_taken_this_wave, actions + 1)
                self.assertNotIn(0, state.towers)
                self.assertTrue(state.is_slot_empty(0))
                self.assertIsNone(state.selected_slot)
                self.assertIsNone(state.pending_sell_slot)
                self.assertEqual(state.phase, GamePhase.PREPARATION)
                game.step(Action(ActionType.BUY, slot_id=0))
                self.assertTrue(state.has_tower(0))
                self.assertEqual(state.towers[0]["level"], 1)
                self.assertEqual(state.gold, gold + refund - 100)

    def test_cancel_does_not_change_tower_gold_or_actions(self):
        game = self.make_tower(3)
        state = game.state
        before = (state.towers[0].copy(), state.gold, state.actions_taken_this_wave)
        game.step(Action(ActionType.SELL, slot_id=0))
        game.step(Action(ActionType.CANCEL))
        self.assertEqual((state.towers[0], state.gold, state.actions_taken_this_wave), before)
        self.assertEqual(state.selected_slot, 0)
        self.assertIsNone(state.pending_sell_slot)
        game.step(Action(ActionType.CONFIRM_SELL, slot_id=0))
        self.assertTrue(state.has_tower(0))

    def test_sell_requires_selected_occupied_slot_and_preparation_budget(self):
        for phase, selected, actions, slot in [
            (GamePhase.PREPARATION, None, 0, 0),
            (GamePhase.PREPARATION, 1, 0, 1),
            (GamePhase.PREPARATION, 0, 20, 0),
            (GamePhase.WAVE_ACTIVE, 0, 0, 0),
        ]:
            with self.subTest(phase=phase, selected=selected, actions=actions):
                game = self.make_tower()
                state = game.state
                state.phase, state.selected_slot, state.actions_taken_this_wave = phase, selected, actions
                gold = state.gold
                game.step(Action(ActionType.SELL, slot_id=slot))
                game.step(Action(ActionType.CONFIRM_SELL, slot_id=slot))
                self.assertTrue(state.has_tower(0))
                self.assertEqual(state.gold, gold)
                self.assertEqual(state.actions_taken_this_wave, actions)

    def test_confirmation_revalidates_budget_and_locks_selected_tower(self):
        game = self.make_tower()
        game.step(Action(ActionType.SELL, slot_id=0))
        game.step(Action(ActionType.SELECT_SLOT, slot_id=1))
        self.assertEqual(game.state.selected_slot, 0)
        game.state.actions_taken_this_wave = 20
        gold = game.state.gold
        game.step(Action(ActionType.CONFIRM_SELL, slot_id=0))
        self.assertEqual(game.state.gold, gold)
        self.assertTrue(game.state.has_tower(0))

    def test_sold_tower_does_not_attack_in_next_wave(self):
        game = self.make_tower()
        game.step(Action(ActionType.SELL, slot_id=0))
        game.step(Action(ActionType.CONFIRM_SELL, slot_id=0))
        game.step(Action(ActionType.START_WAVE))
        enemy = Enemy.create(EnemyType.BASIC, game.map.get_path(), 100)
        enemy.speed = 0
        game.state.enemies = [enemy]
        game.update(1)
        self.assertEqual(enemy.health, 100)
        self.assertEqual(game.state.effects, [])

    def test_sell_can_consume_twentieth_action(self):
        game = self.make_tower()
        game.state.actions_taken_this_wave = 19
        game.step(Action(ActionType.SELL, slot_id=0))
        game.step(Action(ActionType.CONFIRM_SELL, slot_id=0))
        self.assertEqual(game.state.actions_taken_this_wave, 20)
        self.assertTrue(game.state.is_slot_empty(0))
        game.step(Action(ActionType.BUY, slot_id=0))
        self.assertTrue(game.state.is_slot_empty(0))


    def test_move_confirmation_preserves_tower_and_consumes_one_action(self):
        game = self.make_tower(3)
        tower, gold, actions = game.state.towers[0], game.state.gold, game.state.actions_taken_this_wave
        game.step(Action(ActionType.BEGIN_RELOCATE, slot_id=0))
        game.step(Action(ActionType.RELOCATE, from_slot_id=0, to_slot_id=1))
        self.assertIs(game.state.towers[1], tower)
        self.assertEqual(tower["level"], 3)
        self.assertTrue(game.state.is_slot_empty(0))
        self.assertEqual(game.state.gold, gold)
        self.assertEqual(game.state.actions_taken_this_wave, actions + 1)
        self.assertEqual(game.state.phase, GamePhase.PREPARATION)

    def test_upgrade_costs_and_refund_match_plan(self):
        game = Game()
        state = game.reset(seed=4, start_at_title=False)
        game.step(Action(ActionType.BUY, slot_id=0))
        state.gold = 1000
        game.step(Action(ActionType.UPGRADE, slot_id=0))
        game.step(Action(ActionType.UPGRADE, slot_id=0))

        economy = Economy()
        self.assertEqual(state.towers[0]["level"], 3)
        self.assertEqual(economy.get_total_investment(state, 0), 260)
        self.assertEqual(economy.get_sell_refund(state, 0), 156)

    def test_combat_upgrades_keep_costs_and_do_not_consume_preparation_actions(self):
        game = self.make_tower()
        state = game.state
        state.actions_taken_this_wave = 20
        game.step(Action(ActionType.START_WAVE))
        for level, cost in enumerate((60, 100, 160, 250), 2):
            with self.subTest(level=level):
                gold = state.gold
                upgrade = Action(ActionType.UPGRADE, slot_id=0)
                self.assertTrue(ActionValidator.is_valid_action(upgrade, state))
                self.assertIn(upgrade, ActionValidator.get_all_valid_actions(state))
                game.step(upgrade)
                self.assertEqual(state.towers[0]["level"], level)
                self.assertEqual(state.gold, gold - cost)
                self.assertEqual(state.actions_taken_this_wave, 20)
                self.assertEqual(state.phase, GamePhase.WAVE_ACTIVE)
        gold = state.gold
        game.step(Action(ActionType.UPGRADE, slot_id=0))
        self.assertEqual(state.towers[0]["level"], 5)
        self.assertEqual(state.gold, gold)
        self.assertEqual(ActionValidator.get_all_valid_actions(state), [])

    def test_combat_upgrade_rejects_insufficient_gold_or_invalid_slot(self):
        for slot, gold in ((0, 59), (None, 1000), (1, 1000), (-1, 1000), (24, 1000)):
            with self.subTest(slot=slot, gold=gold):
                game = self.make_tower()
                game.step(Action(ActionType.START_WAVE))
                game.state.gold = gold
                before = game.state.towers[0].copy()
                upgrade = Action(ActionType.UPGRADE, slot_id=slot)
                self.assertFalse(ActionValidator.is_valid_action(upgrade, game.state))
                game.step(upgrade)
                self.assertEqual(game.state.gold, gold)
                self.assertEqual(game.state.towers[0], before)

    def test_combat_upgrade_accepts_exact_cost(self):
        game = self.make_tower()
        game.step(Action(ActionType.START_WAVE))
        game.state.gold = 60
        game.step(Action(ActionType.UPGRADE, slot_id=0))
        self.assertEqual(game.state.gold, 0)
        self.assertEqual(game.state.towers[0]["level"], 2)

    def test_combat_blocks_all_non_upgrade_tower_actions_in_engine_and_validator(self):
        forbidden = [
            Action(ActionType.BUY, slot_id=1),
            Action(ActionType.SELL, slot_id=0),
            Action(ActionType.CONFIRM_SELL, slot_id=0),
            Action(ActionType.BEGIN_RELOCATE, slot_id=0),
            Action(ActionType.RELOCATE, from_slot_id=0, to_slot_id=1),
        ]
        game = self.make_tower()
        game.step(Action(ActionType.START_WAVE))
        state = game.state
        before = (state.gold, state.towers[0].copy(), state.tower_slots.copy(), state.actions_taken_this_wave)
        self.assertEqual({action.action_type for action in ActionValidator.get_all_valid_actions(state)}, {ActionType.UPGRADE})
        for action in forbidden:
            with self.subTest(action=action.action_type):
                self.assertFalse(ActionValidator.is_valid_action(action, state))
                game.step(action)
                self.assertEqual((state.gold, state.towers[0], state.tower_slots, state.actions_taken_this_wave), before)
                self.assertEqual(state.phase, GamePhase.WAVE_ACTIVE)
                self.assertIsNone(state.pending_sell_slot)
                self.assertIsNone(state.moving_from_slot)

    def test_preparation_upgrade_still_counts_and_respects_action_limit(self):
        game = self.make_tower()
        game.state.actions_taken_this_wave = 19
        game.step(Action(ActionType.UPGRADE, slot_id=0))
        self.assertEqual(game.state.actions_taken_this_wave, 20)
        self.assertEqual(game.state.towers[0]["level"], 2)
        gold = game.state.gold
        game.step(Action(ActionType.UPGRADE, slot_id=0))
        self.assertEqual(game.state.gold, gold)
        self.assertEqual(game.state.towers[0]["level"], 2)

    def test_upgrade_blocked_outside_preparation_and_combat(self):
        for phase in (GamePhase.TITLE, GamePhase.HELP, GamePhase.SELL_CONFIRM,
                      GamePhase.MOVING_TOWER, GamePhase.SETTLEMENT, GamePhase.VICTORY, GamePhase.GAME_OVER):
            with self.subTest(phase=phase):
                game = self.make_tower()
                game.state.phase = phase
                gold = game.state.gold
                game.step(Action(ActionType.UPGRADE, slot_id=0))
                self.assertEqual(game.state.gold, gold)
                self.assertEqual(game.state.towers[0]["level"], 1)
                self.assertEqual(game.state.phase, phase)


if __name__ == "__main__":
    unittest.main()
