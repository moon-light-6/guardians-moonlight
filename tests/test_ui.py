import copy
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import COLOR_GOLD, PANEL_X, SCREEN_HEIGHT, SCREEN_WIDTH
from display.input_handler import InputHandler
from display.renderer import Renderer
from display.render_sizes import TOWER_BOTTOM_OFFSET, TOWER_LEVEL_GAP, TOWER_Y_OFFSETS
from game.actions import Action, ActionType
from game.engine import Game
from game.enemy import Enemy, EnemyType
from game.state import GamePhase
from game.tower import Tower
from game.wave import WaveManager
from main import _apply_action


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
        self.input = InputHandler(self.renderer.buttons, self.renderer.projection)

    def render(self, name=None):
        self.renderer.render(
            self.game.state,
            start_confirm=self.input.start_confirm,
            buy_confirm=self.input.buy_confirm,
            no_tower_warning=self.input.no_tower_warning,
            boss_warning=self.input.boss_warning,
        )
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

    def press(self, action_name):
        self.render()
        button = next(button for button in self.renderer.buttons.buttons if button.action == action_name)
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center)
        return self.input.handle_event(event, self.game.state)

    def click(self, action_name):
        if action_name == "START_WAVE":
            if not self.game.state.towers:
                # 사신이 없으면 화면이 경고 팝업을 띄워 막는다(별도 테스트에서 확인).
                # 사신 없이 시작하는 엔진 규칙이 필요한 테스트는 행동을 바로 보낸다.
                self.game.step(Action(ActionType.START_WAVE))
                return
            # 소동 시작 버튼은 확인 팝업을 한 번 거친 뒤 "예"를 눌러야 시작된다.
            self.assertIsNone(self.press("OPEN_START_CONFIRM"))
            action_name = "START_WAVE_YES"
        elif action_name == "BUY":
            # 랜덤 소환 버튼도 확인 팝업에서 "예"를 눌러야 소환된다.
            self.assertIsNone(self.press("OPEN_BUY_CONFIRM"))
            action_name = "BUY_YES"
        action = self.press(action_name)
        self.assertIsNotNone(action)
        _apply_action(self.game, self.renderer, action)

    def select_empty_slot(self, slot_id=0):
        self.game.step(Action(ActionType.SELECT_SLOT, slot_id=slot_id))

    def test_buy_asks_for_confirmation_first(self):
        self.select_empty_slot()
        gold = self.game.state.gold
        self.assertIsNone(self.press("OPEN_BUY_CONFIRM"))
        self.assertTrue(self.input.buy_confirm)
        self.assertEqual(self.game.state.gold, gold)
        self.assertFalse(self.game.state.towers)
        self.render("buy-confirm")
        actions = {button.action for button in self.renderer.buttons.buttons}
        self.assertEqual(actions, {"BUY_NO", "BUY_YES"})

    def test_buy_confirm_no_closes_popup_without_summoning(self):
        self.select_empty_slot()
        gold = self.game.state.gold
        self.press("OPEN_BUY_CONFIRM")
        self.assertIsNone(self.press("BUY_NO"))
        self.assertFalse(self.input.buy_confirm)
        self.assertEqual(self.game.state.gold, gold)
        self.assertFalse(self.game.state.towers)

    def test_buy_confirm_yes_summons_tower_in_selected_slot(self):
        self.select_empty_slot(2)
        gold = self.game.state.gold
        self.press("OPEN_BUY_CONFIRM")
        action = self.press("BUY_YES")
        self.assertEqual(action.action_type, ActionType.BUY)
        self.assertEqual(action.slot_id, 2)
        self.assertFalse(self.input.buy_confirm)
        self.game.step(action)
        self.assertIn(2, self.game.state.towers)
        self.assertEqual(self.game.state.gold, gold - 100)

    def test_escape_closes_buy_confirmation(self):
        self.select_empty_slot()
        self.press("OPEN_BUY_CONFIRM")
        escape = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        self.assertIsNone(self.input.handle_event(escape, self.game.state))
        self.assertFalse(self.input.buy_confirm)
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)

    def test_start_without_tower_shows_warning_instead_of_confirmation(self):
        self.assertFalse(self.game.state.towers)
        self.assertIsNone(self.press("OPEN_START_CONFIRM"))
        self.assertTrue(self.input.no_tower_warning)
        self.assertFalse(self.input.start_confirm)
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)
        self.render("no-tower-warning")
        actions = {button.action for button in self.renderer.buttons.buttons}
        self.assertEqual(actions, {"CLOSE_NO_TOWER_WARNING"})

    def test_no_tower_warning_button_closes_and_start_is_still_blocked(self):
        self.press("OPEN_START_CONFIRM")
        self.assertIsNone(self.press("CLOSE_NO_TOWER_WARNING"))
        self.assertFalse(self.input.no_tower_warning)
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)
        self.assertIsNone(self.press("OPEN_START_CONFIRM"))
        self.assertTrue(self.input.no_tower_warning)

    def test_no_tower_warning_blocks_board_clicks_and_keys_and_escape_closes(self):
        self.press("OPEN_START_CONFIRM")
        position = self.renderer.projection.game_to_pixel(self.game.map.get_slot_position(0))
        click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position)
        self.assertIsNone(self.input.handle_event(click, self.game.state))
        space = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
        self.assertIsNone(self.input.handle_event(space, self.game.state))
        self.assertTrue(self.input.no_tower_warning)
        self.assertFalse(self.input.start_confirm)
        escape = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        self.assertIsNone(self.input.handle_event(escape, self.game.state))
        self.assertFalse(self.input.no_tower_warning)
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)

    def test_space_without_tower_shows_warning(self):
        space = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
        self.assertIsNone(self.input.handle_event(space, self.game.state))
        self.assertTrue(self.input.no_tower_warning)
        self.assertFalse(self.input.start_confirm)

    def test_tower_being_summoned_counts_as_placed_for_start(self):
        self.select_empty_slot()
        self.click("BUY")  # 소환 연출 중에도 사신이 배치된 것으로 본다
        self.assertTrue(self.game.state.summons)
        self.assertIsNone(self.press("OPEN_START_CONFIRM"))
        self.assertTrue(self.input.start_confirm)
        self.assertFalse(self.input.no_tower_warning)

    def test_start_wave_asks_for_confirmation_first(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.assertIsNone(self.press("OPEN_START_CONFIRM"))
        self.assertTrue(self.input.start_confirm)
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)
        self.render("start-confirm")
        actions = {button.action for button in self.renderer.buttons.buttons}
        self.assertEqual(actions, {"START_WAVE_NO", "START_WAVE_YES"})

    def test_start_confirm_no_closes_popup_without_starting(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.press("OPEN_START_CONFIRM")
        self.assertIsNone(self.press("START_WAVE_NO"))
        self.assertFalse(self.input.start_confirm)
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)

    def test_start_confirm_yes_starts_wave(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.press("OPEN_START_CONFIRM")
        action = self.press("START_WAVE_YES")
        self.assertEqual(action.action_type, ActionType.START_WAVE)
        self.assertFalse(self.input.start_confirm)
        self.game.step(action)
        self.assertEqual(self.game.state.phase, GamePhase.WAVE_ACTIVE)

    def test_space_and_escape_use_start_confirmation(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        space = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
        self.assertIsNone(self.input.handle_event(space, self.game.state))
        self.assertTrue(self.input.start_confirm)
        escape = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        self.assertIsNone(self.input.handle_event(escape, self.game.state))
        self.assertFalse(self.input.start_confirm)
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)

    def test_guardian_level_labels_follow_visual_feet(self):
        position = self.renderer.projection.game_to_pixel(self.game.map.get_slot_position(0))
        for tower_type in self.renderer.tower_animator.SPRITE_CONFIG:
            with self.subTest(tower_type=tower_type):
                with patch.object(self.renderer, "screen", Mock()) as screen:
                    self.renderer._draw_tower(0, {"type": tower_type, "level": 1}, [])
                sprite, shadow, label = screen.blit.call_args_list
                feet = (position[0], position[1] + TOWER_Y_OFFSETS[tower_type] + TOWER_BOTTOM_OFFSET)
                self.assertEqual(sprite.args[1].midbottom, feet)
                self.assertEqual(label.args[1].midtop, (feet[0], feet[1] + TOWER_LEVEL_GAP))
                self.assertEqual(shadow.args[1], label.args[1].move(1, 1))

    def test_world_layers_and_ui_are_ordered_without_duplicate_effects(self):
        state = self.game.state
        state.towers = {slot: {"type": kind, "slot_id": slot, "level": 1}
                        for slot, kind in enumerate(TOWER_Y_OFFSETS)}
        state.selected_slot = 0
        state.enemies = [Enemy.create(EnemyType.BASIC, self.game.map.get_path(), 100)]
        state.effects = [
            {"kind": "slow_field", "cell": (2, 1), "age": 0.2, "ttl": 2},
            {"kind": "fire", "from": (0, 0), "to": (2, 1), "age": 0.2, "ttl": 1},
        ]
        order = []
        self.renderer.show_map_debug = False
        with patch.object(self.renderer, "_draw_slot_tile") as tiles, \
                patch.object(self.renderer, "_draw_projected_range", side_effect=lambda *a: order.append("range")), \
                patch.object(self.renderer, "_draw_enemy", side_effect=lambda *a: order.append("enemy")), \
                patch.object(self.renderer, "_draw_effect", side_effect=lambda e: order.append(e["kind"])), \
                patch.object(self.renderer, "_draw_upgrade_effects", side_effect=lambda *a: order.append("upgrade")), \
                patch.object(self.renderer, "_draw_tower", side_effect=lambda *a: order.append("tower")), \
                patch.object(self.renderer, "_render_hud", side_effect=lambda *a: order.append("hud")), \
                patch.object(self.renderer, "_render_side_panel", side_effect=lambda *a: order.append("panel")), \
                patch.object(self.renderer.buttons, "render", side_effect=lambda *a: order.append("buttons")):
            self.renderer._render_game(state)
        self.assertEqual(order, ["range", "enemy", "slow_field", "fire", "upgrade"]
                         + ["tower"] * 4 + ["hud", "panel", "buttons"])
        self.assertFalse(any(call.args[1] for call in tiles.call_args_list))

    def test_upgrade_success_only_emits_once_per_action_without_changing_logic(self):
        for kind in TOWER_Y_OFFSETS:
            for phase, level, gold, actions, success in (
                (GamePhase.PREPARATION, 1, 1000, 0, True),
                (GamePhase.WAVE_ACTIVE, 1, 1000, 20, True),
                (GamePhase.PREPARATION, 1, 0, 0, False),
                (GamePhase.PREPARATION, 5, 1000, 0, False),
                (GamePhase.PREPARATION, 1, 1000, 20, False),
                (GamePhase.SELL_CONFIRM, 1, 1000, 0, False),
            ):
                with self.subTest(kind=kind, phase=phase, level=level, gold=gold):
                    self.game.reset(start_at_title=False)
                    state = self.game.state
                    state.phase, state.gold = phase, gold
                    state.actions_taken_this_wave = actions
                    state.towers[0] = {"type": kind, "slot_id": 0, "level": level}
                    control = copy.deepcopy(self.game)
                    action = Action(ActionType.UPGRADE, slot_id=0)
                    control.step(action)
                    self.renderer._upgrade_effects.clear()
                    _apply_action(self.game, self.renderer, action)
                    self.assertEqual(state, control.state)
                    self.assertEqual(len(self.renderer._upgrade_effects), int(success))
                    with patch.object(self.renderer, "_draw_upgrade_glow"):
                        self.renderer._draw_upgrade_effects(state)
                        self.renderer._draw_upgrade_effects(state)
                    self.assertEqual(len(self.renderer._upgrade_effects), int(success))

    def test_upgrade_uses_wall_time_and_corrected_feet_then_expires(self):
        for kind in TOWER_Y_OFFSETS:
            with self.subTest(kind=kind), patch("display.renderer.perf_counter") as timer:
                self.renderer._upgrade_effects.clear()
                state = self.game.state
                state.gold = 1000
                state.towers[0] = {"type": kind, "slot_id": 0, "level": 1}
                timer.return_value = 10.0
                _apply_action(self.game, self.renderer, Action(ActionType.UPGRADE, slot_id=0))
                anchor = self.renderer.projection.game_to_pixel(self.game.map.get_slot_position(0))
                feet = (anchor[0], anchor[1] + TOWER_Y_OFFSETS[kind] + 7)
                with patch.object(self.renderer, "_draw_upgrade_glow") as glow, \
                        patch("display.renderer.TOWER_BOTTOM_OFFSET", 7):
                    for speed in (1, 5):
                        state.combat_speed = speed
                        timer.return_value = 10.35
                        self.renderer._draw_upgrade_effects(state)
                        self.assertEqual(glow.call_args.args[0], feet)
                        self.assertAlmostEqual(glow.call_args.args[1], 0.5)
                    timer.return_value = 10.71
                    glow.reset_mock()
                    self.renderer._draw_upgrade_effects(state)
                    self.renderer._draw_upgrade_effects(state)
                    glow.assert_not_called()
                    self.assertEqual(self.renderer._upgrade_effects, [])

    def test_rapid_upgrades_relocation_sale_and_restart_do_not_replay_effects(self):
        state = self.game.state
        state.gold = 10000
        state.towers[0] = {"type": "ARCHER", "slot_id": 0, "level": 1}
        action = Action(ActionType.UPGRADE, slot_id=0)
        with patch("display.renderer.perf_counter", return_value=10):
            _apply_action(self.game, self.renderer, action)
            _apply_action(self.game, self.renderer, action)
            self.assertEqual(len(self.renderer._upgrade_effects), 2)
            _apply_action(self.game, self.renderer, Action(ActionType.BEGIN_RELOCATE, slot_id=0))
            _apply_action(self.game, self.renderer, Action(ActionType.RELOCATE, from_slot_id=0, to_slot_id=1))
            with patch.object(self.renderer, "_draw_upgrade_glow") as glow:
                self.renderer._draw_upgrade_effects(state)
            self.assertEqual(glow.call_count, 2)
            self.assertEqual(glow.call_args.args[0], self.renderer._tower_pixel_position(1, "ARCHER"))
            state.selected_slot = 1
            _apply_action(self.game, self.renderer, Action(ActionType.SELL, slot_id=1))
            _apply_action(self.game, self.renderer, Action(ActionType.CONFIRM_SELL, slot_id=1))
            self.renderer._draw_upgrade_effects(state)
            self.assertEqual(self.renderer._upgrade_effects, [])
            state.towers[0] = {"type": "ICE", "slot_id": 0, "level": 1}
            _apply_action(self.game, self.renderer, action)
            _apply_action(self.game, self.renderer, Action(ActionType.RESTART))
            self.renderer._draw_upgrade_effects(self.game.state)
            self.assertEqual(self.renderer._upgrade_effects, [])

    def test_selected_range_uses_live_stats_and_logical_center_without_y_offset(self):
        state = self.game.state
        for slot, kind in enumerate(TOWER_Y_OFFSETS):
            state.towers[slot] = {"type": kind, "slot_id": slot, "level": 1}
        with patch.object(self.renderer, "_draw_tower"), \
                patch.object(self.renderer, "_draw_projected_range") as ring:
            for slot, data in state.towers.items():
                for level in (1, 5):
                    data["level"] = level
                    state.selected_slot = slot
                    self.renderer._render_board(state)
                    self.assertEqual(ring.call_args.args, (
                        self.renderer.projection.game_to_pixel(self.game.map.get_slot_position(slot)),
                        Tower.from_data(data).get_stats()["range"],
                    ))
            with patch("display.renderer.Tower.get_stats", return_value={"range": 4.25}):
                self.renderer._render_board(state)
                self.assertEqual(ring.call_args.args[1], 4.25)
            state.selected_slot = None
            ring.reset_mock()
            self.renderer._render_board(state)
            ring.assert_not_called()

    def test_overlapping_sprites_match_enemy_effect_tower_compositing(self):
        state = self.game.state
        self.renderer.show_map_debug = False
        origin = self.game.map.get_slot_position(7)
        target = (origin[0] + 0.1, origin[1] + 0.1)
        state.enemies = [Enemy.create(EnemyType.BASIC, [origin, target], 100)]
        field = {"kind": "slow_field", "cell": origin, "age": 0.2, "ttl": 2}
        for kind, config in self.renderer.tower_animator.SPRITE_CONFIG.items():
            state.towers = {7: {"type": kind, "slot_id": 7, "level": 1}}
            attack = {"kind": config["effect"], "from": origin, "to": target,
                      "points": [target], "age": 0.2, "ttl": 0.6}
            for effects in ([field], [field, attack]):
                with self.subTest(kind=kind, attacking=len(effects) == 2), \
                        patch("display.sprite_animation.pygame.time.get_ticks", return_value=0):
                    state.effects = effects
                    before = copy.deepcopy(state)
                    self.screen.fill((10, 20, 30))
                    self.renderer._draw_enemy(state.enemies[0], state.wave_elapsed)
                    for effect in effects:
                        self.renderer._draw_effect(effect)
                    self.renderer._draw_tower(7, state.towers[7], effects)
                    expected = pygame.image.tobytes(self.screen, "RGB")
                    self.screen.fill((10, 20, 30))
                    self.renderer._render_board(state)
                    self.assertEqual(pygame.image.tobytes(self.screen, "RGB"), expected)
                    self.assertEqual(state, before)

    def test_range_stroke_is_transparent_and_matches_projected_radius(self):
        center = (400, 350)
        logical_range = 3.5
        radius = round(self.renderer.projection.units_to_pixels(logical_range))
        with patch.object(self.renderer, "screen", Mock()) as screen, \
                patch("display.renderer.pygame.draw.circle", wraps=pygame.draw.circle) as circle:
            self.renderer._draw_projected_range(center, logical_range)
        image, pos = screen.blit.call_args.args
        self.assertEqual(image.get_at(image.get_rect().center).a, 0)
        self.assertEqual(circle.call_args.args[1:], (COLOR_GOLD, image.get_rect().center, radius, 2))
        self.assertEqual((pos[0] + image.get_width() // 2, pos[1] + image.get_height() // 2), center)

    def test_upgrade_glow_rises_and_fades_without_mutating_state(self):
        with patch.object(self.renderer, "screen", Mock()) as screen:
            images = []
            for progress in (0, 0.1, 0.35, 0.75, 0.99, 1):
                self.renderer._draw_upgrade_glow((400, 350), progress)
                images.append(screen.blit.call_args.args[0])
        masks = [pygame.mask.from_surface(image, threshold=0) for image in images]
        self.assertEqual(masks[0].count(), 0)
        self.assertEqual(masks[-1].count(), 0)
        early = images[1].get_bounding_rect(min_alpha=1)
        middle = images[2].get_bounding_rect(min_alpha=1)
        self.assertLess(middle.top, early.top)
        self.assertLess(max(pygame.image.tobytes(images[-2], "RGBA")[3::4]),
                        max(pygame.image.tobytes(images[2], "RGBA")[3::4]))
        self.game.state.towers[0] = {"type": "LIGHTNING", "slot_id": 0, "level": 1}
        _apply_action(self.game, self.renderer, Action(ActionType.UPGRADE, slot_id=0))
        before = copy.deepcopy(self.game.state)
        self.renderer.render(self.game.state)
        self.assertEqual(self.game.state, before)

    def test_sell_button_cancel_confirm_and_summon_again(self):
        position = self.renderer.projection.game_to_pixel(self.game.map.get_slot_position(0))
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

    def test_speed_button_cycle_and_back_to_title(self):
        self.click("START_WAVE")
        for index, speed in enumerate((1, 1.5, 2, 5, 1)):
            self.render(f"combat-speed-{index}")
            button = next(b for b in self.renderer.buttons.buttons if b.action == "CYCLE_SPEED")
            self.assertEqual(button.text, f"배속 ×{speed:g}")
            self.assertEqual(self.game.state.combat_speed, speed)
            self.click("CYCLE_SPEED")
        self.game.state.phase = GamePhase.GAME_OVER
        self.render("defeat")
        self.click_anywhere((640, 420))
        self.assertEqual(self.game.state.phase, GamePhase.TITLE)
        self.assertEqual(self.game.state.combat_speed, 1)

    def click_anywhere(self, pos):
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)
        action = self.input.handle_event(event, self.game.state)
        self.assertIsNotNone(action)
        _apply_action(self.game, self.renderer, action)

    def test_result_screens_show_image_and_any_click_returns_to_title(self):
        for phase, name in ((GamePhase.GAME_OVER, "defeat-image"), (GamePhase.VICTORY, "victory-image")):
            for pos in ((640, 340), (10, 10), (1200, 800)):
                with self.subTest(phase=phase, pos=pos):
                    self.game.reset(start_at_title=False)
                    self.game.state.phase = phase
                    with patch.object(self.renderer, "_blit_center", wraps=self.renderer._blit_center) as blit:
                        self.render(name)
                    self.assertIs(blit.call_args_list[0].args[0], self.renderer.result_images[phase])
                    self.assertEqual(self.renderer.buttons.buttons, [])
                    self.click_anywhere(pos)
                    self.assertEqual(self.game.state.phase, GamePhase.TITLE)

    def test_result_screen_click_is_ignored_while_quit_popup_is_open(self):
        self.game.state.phase = GamePhase.GAME_OVER
        self.input.quit_confirm = True
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(100, 100))
        self.assertIsNone(self.input.handle_event(event, self.game.state))
        self.assertEqual(self.game.state.phase, GamePhase.GAME_OVER)

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

    def go_to_boss_preparation(self, stage_before=4):
        state = self.game.state
        state.current_stage = stage_before
        state.phase = GamePhase.SETTLEMENT
        self.click("CONTINUE")

    def test_boss_warning_popup_shows_and_blocks_input_until_dismissed(self):
        self.go_to_boss_preparation()
        state = self.game.state
        self.assertTrue(self.input.boss_warning)
        self.render("boss-warning")
        actions = {button.action for button in self.renderer.buttons.buttons}
        self.assertEqual(actions, {"CLOSE_BOSS_WARNING"})
        position = self.renderer.projection.game_to_pixel(self.game.map.get_slot_position(0))
        click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position)
        self.assertIsNone(self.input.handle_event(click, state))
        for key in (pygame.K_SPACE, pygame.K_ESCAPE, pygame.K_RETURN):
            self.assertIsNone(self.input.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key), state))
        self.assertEqual(state.phase, GamePhase.PREPARATION)
        self.assertTrue(self.input.boss_warning)

    def test_boss_warning_button_dismisses_popup(self):
        self.go_to_boss_preparation()
        self.assertIsNone(self.press("CLOSE_BOSS_WARNING"))
        self.assertFalse(self.input.boss_warning)
        self.render()
        actions = {button.action for button in self.renderer.buttons.buttons}
        self.assertIn("OPEN_START_CONFIRM", actions)

    def test_boss_warning_opens_for_every_stage_before_a_boss(self):
        for before_boss in (4, 9, 14, 19, 24, 29):
            with self.subTest(stage=before_boss):
                self.input.boss_warning = False
                self.go_to_boss_preparation(stage_before=before_boss)
                self.assertEqual(self.game.state.current_stage, before_boss + 1)
                self.assertTrue(self.input.boss_warning)

    def test_enter_on_settlement_also_opens_boss_warning(self):
        state = self.game.state
        state.current_stage = 9
        state.phase = GamePhase.SETTLEMENT
        enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)
        action = self.input.handle_event(enter, state)
        self.assertEqual(action.action_type, ActionType.CONTINUE)
        self.assertTrue(self.input.boss_warning)
        self.game.step(action)
        self.assertEqual(state.current_stage, 10)

    def test_no_boss_warning_before_normal_stage(self):
        for before in (1, 3, 5, 10, 28):
            with self.subTest(stage=before):
                self.input.boss_warning = False
                self.go_to_boss_preparation(stage_before=before)
                self.assertFalse(self.input.boss_warning)

    def test_no_boss_warning_when_finishing_last_stage(self):
        self.go_to_boss_preparation(stage_before=30)
        self.assertEqual(self.game.state.phase, GamePhase.VICTORY)
        self.assertFalse(self.input.boss_warning)

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
        position = self.renderer.projection.game_to_pixel(self.game.map.get_slot_position(1))
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
        position = self.renderer.projection.game_to_pixel(self.game.map.get_slot_position(0))
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position)
        action = self.input.handle_event(event, state)
        self.assertEqual(action.action_type, ActionType.SELECT_SLOT)
        self.game.step(action)
        self.assertEqual(state.selected_slot, 0)
        self.render("combat-tower-selected")
        for name in ("OPEN_BUY_CONFIRM", "BEGIN_RELOCATE", "SELL"):
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
        empty_pos = self.renderer.projection.game_to_pixel(self.game.map.get_slot_position(1))
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

    def test_clicking_background_in_combat_deselects_tower_and_shows_boss(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.game.state.current_stage = 10
        self.click("START_WAVE")
        boss = Enemy.create(EnemyType.BOSS, self.game.map.get_path(), 2160, "철갓장군")
        self.game.state.enemies = [boss]
        state = self.game.state
        self.assertEqual(state.selected_slot, 0)  # 사신을 소환하면 그 슬롯이 선택된 상태다
        self.render("combat-tower-info")
        self.assertIn("UPGRADE", {b.action for b in self.renderer.buttons.buttons})

        # 사신이 없는 배경(판 바깥쪽 위쪽 모서리)을 누르면 선택이 풀리고 보스 정보가 나온다.
        background = (5, 400)
        self.assertIsNone(self.renderer.projection.pixel_to_slot(background))
        action = self.input.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=background), state)
        self.assertEqual(action.action_type, ActionType.SELECT_SLOT)
        self.assertIsNone(action.slot_id)
        self.game.step(action)
        self.assertIsNone(state.selected_slot)
        self.render("combat-boss-info")
        self.assertNotIn("UPGRADE", {b.action for b in self.renderer.buttons.buttons})

        # 사신을 다시 누르면 사신 정보가 그대로 보인다.
        position = self.renderer.projection.game_to_pixel(self.game.map.get_slot_position(0))
        action = self.input.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position), state)
        self.game.step(action)
        self.assertEqual(state.selected_slot, 0)

    def test_clicking_side_panel_background_in_combat_keeps_selected_tower(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.click("START_WAVE")
        self.render()
        panel_background = (PANEL_X + 150, 450)
        action = self.input.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=panel_background), self.game.state)
        self.assertIsNone(action)

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
        for value in ("일반 악귀 1마리 처치 보상", "보스 악귀 1마리 처치 보상", "5 G", "100 G", "225 G", "330 G"):
            self.assertIn(value, values)
        self.assertEqual(state.gold, 530)

    def test_ice_field_plays_twelve_frames_with_loop_then_disappears(self):
        animator = self.renderer.effect_animator
        frames = animator.frames["water"]
        self.assertEqual(len(frames), 12)
        field = {"kind": "slow_field", "cell": (10, 5), "factor": 0.7,
                 "age": 0, "slow_ttl": 2, "ttl": 2}
        center = self.renderer.projection.game_to_pixel(field["cell"])
        # 생성 0~3, 유지 4~7 반복, 소멸 8~11. 각 프레임 0.1초, 총 2초.
        timeline = ((0, 0), (0.099, 0), (0.1, 1), (0.2, 2), (0.3, 3),
                    (0.4, 4), (0.499, 4), (0.5, 5), (0.599, 5),
                    (0.6, 6), (0.7, 7), (0.8, 4), (0.9, 5),
                    (1, 6), (1.1, 7), (1.2, 4), (1.3, 5),
                    (1.4, 6), (1.5, 7), (1.599, 7), (1.6, 8), (1.7, 9),
                    (1.8, 10), (1.9, 11), (1.999, 11),
                    (2 - 1e-14, None), (2, None), (3, None))
        for age, index in timeline:
            with self.subTest(age=age, frame=index):
                self.screen.fill((10, 20, 30))
                expected = self.screen.copy()
                if index is not None:
                    image = frames[index].copy()
                    image.set_alpha(170)
                    expected.blit(image, (center[0] - animator.anchors["water"][0],
                                          center[1] - animator.anchors["water"][1]))
                field["age"] = age
                with patch.object(animator, "_draw_field_energy"):
                    animator.draw(self.screen, field, self.renderer.projection)
                self.assertTrue(pygame.image.tobytes(self.screen, "RGB") ==
                                pygame.image.tobytes(expected, "RGB"))

    def test_ice_field_is_drawn_once_without_attack_or_legacy_overlay(self):
        field = {"kind": "slow_field", "cell": (10, 5), "factor": 0.7,
                 "age": 0.2, "slow_ttl": 2, "ttl": 2}
        water = {"kind": "water", "from": (2, 0), "to": (10.25, 5),
                 "age": 0.2, "ttl": 0.6}
        for age in (0.2, 1, 1.6, 1.999, 2):
            with self.subTest(age=age):
                field["age"] = age
                self.game.state.effects = []
                self.renderer.render(self.game.state)
                expected = self.screen.copy()
                self.renderer.effect_animator.draw(expected, field, self.renderer.projection)
                self.game.state.effects = [water, field]
                with patch.object(self.renderer.effect_animator, "draw",
                                  wraps=self.renderer.effect_animator.draw) as draw_png:
                    self.renderer.render(self.game.state)
                self.assertEqual(draw_png.call_count, int(age < 2))
                if age < 2:
                    self.assertIs(draw_png.call_args.args[1], field)
                self.assertTrue(pygame.image.tobytes(self.screen, "RGB") ==
                                pygame.image.tobytes(expected, "RGB"))
        # 화면에서 숨긴 water 이벤트는 현무 본체의 공격 모션에 계속 사용됩니다.
        self.assertIs(self.renderer.tower_animator._active_attack("ICE", (2, 0), [water, field]), water)

    def test_missing_field_png_does_not_restore_legacy_overlay(self):
        self.renderer.render(self.game.state)
        background = pygame.image.tobytes(self.screen, "RGB")
        field = {"kind": "slow_field", "cell": (10, 5), "factor": 0.7,
                 "age": 1, "slow_ttl": 2, "ttl": 2}
        self.game.state.effects = [field]
        with patch.dict(self.renderer.effect_animator.frames, {"water": []}):
            self.renderer.render(self.game.state)
        self.assertTrue(pygame.image.tobytes(self.screen, "RGB") == background)

    def test_effect_alignment_ignores_padding_and_plume_size(self):
        animator = self.renderer.effect_animator
        # 실제 원본의 모든 프레임도 같은 캔버스 크기로 정렬됩니다.
        self.assertEqual(len({frame.get_size() for frame in animator.frames["water"]}), 1)
        frames, points = [], []
        for index in range(12):
            frame = pygame.Surface((100, 120), pygame.SRCALPHA)
            ring = pygame.Rect(15 + index, 60 + index * 2, 25, 12)
            pygame.draw.line(frame, (255, 0, 0), (ring.centerx, 5 + index), ring.midtop, 3)
            pygame.draw.ellipse(frame, (255, 255, 255), ring)
            frames.append(frame)
            points.append(ring.center)
        aligned, anchor = animator._align_frames(frames, points, (100, 120))
        self.assertEqual(len({frame.get_size() for frame in aligned}), 1)
        for frame in aligned:
            ring_pixels = pygame.mask.from_threshold(frame, (255, 255, 255, 255),
                                                    (30, 30, 30, 255))
            ring = ring_pixels.get_bounding_rects()[0]
            self.assertEqual(ring.center, anchor)
            self.assertEqual(ring.size, (25, 12))


    # ===== 게임 중 게임 방법 버튼(일시정지) =====

    def key(self, key):
        return self.input.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key), self.game.state)

    def test_in_game_help_button_opens_overlay_without_changing_phase(self):
        self.render()
        button = next(b for b in self.renderer.buttons.buttons if b.action == "OPEN_HELP")
        self.assertGreaterEqual(button.rect.left, PANEL_X)
        self.assertLess(button.rect.bottom, 126)
        self.input.help_page = 2
        self.assertIsNone(self.press("OPEN_HELP"))
        self.assertTrue(self.input.help_overlay)
        self.assertTrue(self.input.is_paused)
        self.assertEqual(self.input.help_page, 0)
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)

    def test_in_game_help_freezes_wave_until_closed(self):
        self.game.step(Action(ActionType.BUY, slot_id=0))
        self.game.step(Action(ActionType.START_WAVE))
        for _ in range(240):
            self.game.update(1 / 60)
        self.assertEqual(self.game.state.phase, GamePhase.WAVE_ACTIVE)
        self.assertIsNone(self.press("OPEN_HELP"))
        before = (self.game.state.wave_elapsed,
                  [enemy.distance_travelled for enemy in self.game.state.enemies])
        for _ in range(120):
            if not self.input.is_paused:  # main.py와 같은 조건
                self.game.update(1 / 60)
        self.assertEqual(before, (self.game.state.wave_elapsed,
                                  [enemy.distance_travelled for enemy in self.game.state.enemies]))

        self.renderer.render(self.game.state, help_page=0, help_overlay=True)
        close = next(b for b in self.renderer.buttons.buttons if b.action == "CLOSE_HELP")
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=close.rect.center)
        self.assertIsNone(self.input.handle_event(event, self.game.state))
        self.assertFalse(self.input.is_paused)
        self.game.update(1 / 60)
        self.assertGreater(self.game.state.wave_elapsed, before[0])

    def test_in_game_help_blocks_game_input_and_supports_keys(self):
        self.assertIsNone(self.press("OPEN_HELP"))
        self.assertIsNone(self.key(pygame.K_SPACE))
        self.assertFalse(self.input.start_confirm)
        slot_pos = self.renderer.projection.game_to_pixel(self.game.map.get_slot_position(0))
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=slot_pos)
        self.assertIsNone(self.input.handle_event(event, self.game.state))
        self.key(pygame.K_RIGHT)
        self.assertEqual(self.input.help_page, 1)
        self.key(pygame.K_LEFT)
        self.assertEqual(self.input.help_page, 0)
        self.assertIsNone(self.key(pygame.K_ESCAPE))
        self.assertFalse(self.input.help_overlay)
        self.assertEqual(self.game.state.phase, GamePhase.PREPARATION)

    def test_in_game_help_button_hidden_during_result_popups(self):
        for phase in (GamePhase.GAME_OVER, GamePhase.VICTORY):
            with self.subTest(phase=phase):
                self.game.state.phase = phase
                self.render()
                self.assertNotIn("OPEN_HELP", [b.action for b in self.renderer.buttons.buttons])


if __name__ == "__main__":
    unittest.main()
