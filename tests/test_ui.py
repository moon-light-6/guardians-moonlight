import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import SCREEN_HEIGHT, SCREEN_WIDTH
from display.input_handler import InputHandler
from display.renderer import Renderer
from game.actions import Action, ActionType
from game.engine import Game
from game.enemy import Enemy, EnemyType
from game.state import GamePhase
from game.wave import WaveManager


class TestPygameUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.game = Game()
        self.game.reset(seed=42, start_at_title=False)
        self.renderer = Renderer(self.screen)
        self.input = InputHandler(self.renderer.buttons)

    def render(self, name=None):
        self.renderer.render(self.game.state)
        bounds = self.screen.get_rect()
        for button in self.renderer.buttons.buttons:
            self.assertTrue(bounds.contains(button.rect))
            text = self.renderer.font_small.render(button.text, True, (255, 255, 255))
            self.assertLessEqual(text.get_width(), button.rect.width - 8)
            self.assertLessEqual(text.get_height(), button.rect.height)
        output = os.environ.get("MOON_GUARDIANS_SCREENSHOT_DIR")
        if name and output:
            path = Path(output)
            path.mkdir(parents=True, exist_ok=True)
            pygame.image.save(self.screen, str(path / f"{name}.png"))

    def click(self, action_name):
        self.render()
        button = next(button for button in self.renderer.buttons.buttons if button.action == action_name)
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center)
        action = self.input.handle_event(event, self.game.state)
        self.assertIsNotNone(action)
        self.game.step(action)

    def test_sell_button_cancel_confirm_and_summon_again(self):
        position = self.game.map.grid_to_pixel(self.game.map.get_slot_position(0))
        self.render("preparation-empty")
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position)
        self.game.step(self.input.handle_event(event, self.game.state))
        self.click("BUY")
        self.render("preparation-tower")
        gold = self.game.state.gold
        self.click("SELL")
        self.assertEqual(self.game.state.phase, GamePhase.SELL_CONFIRM)
        self.render("sell-confirm")
        self.assertEqual({b.action for b in self.renderer.buttons.buttons}, {"CANCEL", "CONFIRM_SELL"})
        self.assertIsNone(self.input.handle_event(event, self.game.state))
        self.click("CANCEL")
        self.assertEqual(self.game.state.gold, gold)
        self.click("SELL")
        self.click("CONFIRM_SELL")
        self.render("sold-tower")
        self.assertEqual(self.game.state.gold, gold + 60)
        self.assertIsNone(self.game.state.selected_slot)
        self.assertTrue(self.game.state.is_slot_empty(0))
        self.game.step(self.input.handle_event(event, self.game.state))
        self.click("BUY")
        self.assertTrue(self.game.state.has_tower(0))

    def test_speed_button_cycle_and_restart(self):
        self.click("START_WAVE")
        for index, speed in enumerate((1, 1.5, 2, 5, 1)):
            self.render(f"combat-speed-{index}")
            button = next(b for b in self.renderer.buttons.buttons if b.action == "CYCLE_SPEED")
            self.assertEqual(button.text, f"배속 ×{speed:g}")
            self.assertEqual(self.game.state.combat_speed, speed)
            self.click("CYCLE_SPEED")
        self.game.state.phase = GamePhase.GAME_OVER
        self.render("defeat")
        self.click("RESTART")
        self.assertEqual(self.game.state.combat_speed, 1)

    def test_six_boss_screens_use_distinct_artwork(self):
        for stage in WaveManager.BOSSES:
            self.game.reset(start_at_title=False)
            self.game.state.current_stage = stage
            self.click("START_WAVE")
            self.game.state.enemies = self.game.wave_manager.update(100, self.game.map.get_path())
            boss = next(enemy for enemy in self.game.state.enemies if enemy.is_boss)
            boss.move(18)
            self.render(f"boss-{stage:02d}")
        portraits = [pygame.image.tostring(self.renderer.boss_portraits[name, 60], "RGBA")
                     for name in (boss["name"] for boss in WaveManager.BOSSES.values())]
        self.assertEqual(len(set(portraits)), 6)

    def test_title_help_final_settlement_and_victory(self):
        self.game.reset()
        self.render("title")
        self.click("SHOW_HELP")
        self.render("help")
        self.click("BACK_TO_TITLE")
        self.click("START_GAME")
        self.game.state.current_stage = 30
        self.game.state.wave_result.stage = 30
        self.game.state.wave_result.boss_name = "월식대왕"
        self.game.state.wave_result.boss_kills = 1
        self.game.state.wave_result.normal_kills = 35
        self.game.state.wave_result.boss_gold = 100
        self.game.state.wave_result.kill_gold = 175
        self.game.state.wave_result.clear_gold = 220
        self.game.state.wave_result.total_gold = 495
        self.game.state.wave_result.life_before = 20
        self.game.state.wave_result.life_after = 20
        self.game.state.phase = GamePhase.SETTLEMENT
        self.render("settlement-30")
        self.click("CONTINUE")
        self.assertEqual(self.game.state.phase, GamePhase.VICTORY)
        self.render("victory")

    def test_exhausted_preparation_actions_disable_sell(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.game.state.actions_taken_this_wave = 20
        self.render()
        button = next(b for b in self.renderer.buttons.buttons if b.action == "SELL")
        self.assertFalse(button.enabled)
        self.assertIsNone(self.input.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center), self.game.state))

    def test_move_button_and_slot_click_preserve_level(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.game.state.towers[0]["level"] = 3
        self.click("BEGIN_RELOCATE")
        self.render("move-tower")
        position = self.game.map.grid_to_pixel(self.game.map.get_slot_position(1))
        action = self.input.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position), self.game.state)
        self.game.step(action)
        self.assertEqual(self.game.state.towers[1]["level"], 3)
        self.assertTrue(self.game.state.is_slot_empty(0))
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)

    def test_combat_tower_click_upgrade_and_disabled_management_buttons(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        state = self.game.state
        state.gold = 1000
        state.selected_slot = None
        state.actions_taken_this_wave = 20
        self.click("START_WAVE")
        self.render()
        position = self.game.map.grid_to_pixel(self.game.map.get_slot_position(0))
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position)
        action = self.input.handle_event(event, state)
        self.assertEqual(action.action_type, ActionType.SELECT_SLOT)
        self.game.step(action)
        self.assertEqual(state.selected_slot, 0)
        self.render("combat-tower-selected")
        for name in ("BUY", "BEGIN_RELOCATE", "SELL"):
            button = next(b for b in self.renderer.buttons.buttons if b.action == name)
            self.assertFalse(button.enabled)
            self.assertIsNone(self.input.handle_event(
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center), state))
        self.click("UPGRADE")
        self.assertEqual(state.towers[0]["level"], 2)
        self.assertEqual(state.gold, 940)
        self.assertEqual(state.actions_taken_this_wave, 20)
        self.assertEqual(state.phase, GamePhase.WAVE_ACTIVE)
        self.game.update(1)
        self.assertGreater(state.wave_elapsed, 0)
        self.render("combat-tower-upgraded")
        empty_pos = self.game.map.grid_to_pixel(self.game.map.get_slot_position(1))
        self.assertIsNone(self.input.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=empty_pos), state))
        self.assertEqual(state.selected_slot, 0)

    def test_combat_upgrade_button_disables_for_gold_and_max_level(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.click("START_WAVE")
        for level, gold, enabled in ((1, 59, False), (1, 60, True), (5, 1000, False)):
            with self.subTest(level=level, gold=gold):
                self.game.state.towers[0]["level"] = level
                self.game.state.gold = gold
                self.render()
                button = next(b for b in self.renderer.buttons.buttons if b.action == "UPGRADE")
                self.assertEqual(button.enabled, enabled)
                if not enabled:
                    self.assertIsNone(self.input.handle_event(
                        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center), self.game.state))

    def test_boss_and_selected_tower_information_fit_in_combat_panel(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.game.state.current_stage = 30
        self.click("START_WAVE")
        self.game.state.enemies = [Enemy.create(EnemyType.BOSS, self.game.map.get_path(), 25000, "월식대왕")]
        self.render("combat-boss-tower-selected")
        buttons = self.renderer.buttons.buttons
        for index, button in enumerate(buttons):
            for other in buttons[index + 1:]:
                self.assertFalse(button.rect.colliderect(other.rect))

    def test_settlement_shows_callback_kill_counts_and_gold(self):
        state = self.game.state
        state.current_stage = 5
        self.click("START_WAVE")
        self.game.wave_manager.spawn_queue = []
        normal = Enemy.create(EnemyType.BASIC, self.game.map.get_path(), 100)
        boss = Enemy.create(EnemyType.BOSS, self.game.map.get_path(), 500, "먹그림자")
        normal.take_damage(100)
        boss.take_damage(500)
        state.enemies = [normal, boss]
        self.game.update(1 / 60)
        with patch.object(self.renderer, "_text", wraps=self.renderer._text) as draw_text:
            self.render("settlement-rewards-integrated")
        values = [call.args[0] for call in draw_text.call_args_list]
        for value in ("일반 적 처치 1마리", "보스 처치 1마리", "5 G", "100 G", "225 G", "330 G"):
            self.assertIn(value, values)
        self.assertEqual(state.gold, 530)

    def test_slow_field_color_is_visible_until_expiry(self):
        from config import CELL_SIZE
        field = {"kind": "slow_field", "cell": (10, 5), "factor": 0.7, "age": 1.9, "ttl": 2}
        self.game.state.effects = [field]
        cx, cy = self.game.map.grid_to_pixel(field["cell"])
        point = (cx - CELL_SIZE // 2 + 10, cy - CELL_SIZE // 2 + 10)
        self.renderer.render(self.game.state)
        self.assertEqual(self.screen.get_at(point)[:3], (235, 147, 46))
        field["age"] = 2
        self.renderer.render(self.game.state)
        self.assertEqual(self.screen.get_at(point)[:3], (48, 55, 78))


if __name__ == "__main__":
    unittest.main()
