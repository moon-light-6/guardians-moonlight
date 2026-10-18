import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import COLOR_GREEN, COLOR_RED, COMBAT_SPEEDS, SCREEN_HEIGHT, SCREEN_WIDTH
from display.boss_animation import BossSpriteAnimator
from display.renderer import Renderer
from game.actions import Action, ActionType
from game.enemy import Enemy, EnemyType
from game.engine import Game
from game.map import GameMap
from game.state import GamePhase, GameState
from game.wave import WaveManager


class TestBossAnimation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        cls.renderer = Renderer(cls.screen)
        cls.animator = cls.renderer.boss_animator
        cls.path = GameMap().get_path()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def boss(self, name="먹그림자", path=None):
        return Enemy.create(EnemyType.BOSS, path or self.path, 500, name)

    def test_all_six_bosses_have_eight_alpha_frames_in_each_direction(self):
        names = {boss["name"] for boss in WaveManager.BOSSES.values()}
        expected_sizes = {
            "먹그림자": (64, 55), "철갓장군": (64, 55), "서리석귀": (64, 61),
            "홍염귀왕": (89, 90), "흑운이무기": (90, 90), "월식대왕": (90, 90),
        }
        self.assertEqual(set(self.animator.BOSS_FOLDERS), names)
        for name in names:
            sizes = set()
            for direction in self.animator.DIRECTIONS:
                with self.subTest(name=name, direction=direction):
                    frames = self.animator.frames[name, direction]
                    self.assertEqual(len(frames), 8)
                    self.assertEqual(len({pygame.image.tobytes(f, "RGBA") for f in frames}), 8)
                    for frame in frames:
                        sizes.add(frame.get_size())
                        self.assertTrue(frame.get_flags() & pygame.SRCALPHA)
                        self.assertTrue(any(frame.get_at(point).a == 0 for point in (
                            (0, 0), (frame.get_width() - 1, 0),
                            (0, frame.get_height() - 1))))
                        self.assertEqual(frame.get_size(), expected_sizes[name])
            self.assertEqual(len(sizes), 1)

    def test_numeric_sort_and_different_frame_counts_ignore_preview_and_sheets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for direction, numbers in (("down", (10, 2, 1)), ("left", (4,)),
                                       ("right", (3, 1))):
                folder = root / "sample" / direction
                folder.mkdir(parents=True)
                for number in numbers:
                    image = pygame.Surface((40, 20), pygame.SRCALPHA)
                    image.fill((number, 50, 100, 255), (5, 5, 30, 10))
                    pygame.image.save(image, str(folder / f"{direction}_{number}.png"))
                (folder / "notes.txt").write_text("ignored", encoding="utf-8")
            # These are deliberately invalid images and must never be loaded.
            for folder in ("preview", "sheets"):
                (root / "sample" / folder).mkdir()
                (root / "sample" / folder / "test.png").write_bytes(b"not a PNG")
            with patch.object(BossSpriteAnimator, "BOSS_FOLDERS", {"sample": "sample"}):
                animator = BossSpriteAnimator(root)
            for direction, expected in (("down", (1, 2, 10)), ("left", (4,)),
                                        ("right", (1, 3))):
                frames = animator.frames["sample", direction]
                self.assertEqual([f.get_at(f.get_rect().center).r for f in frames], list(expected))
                # Shared crop is 30x10: uniform scaling preserves its 3:1 ratio.
                self.assertAlmostEqual(frames[0].get_width() / frames[0].get_height(), 3, delta=0.1)
                enemy = self.boss("sample", [(0, 0), {
                    "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[direction]])
                for index in range(len(frames) * 2):
                    screen = Mock()
                    animator.draw(screen, enemy, (100, 120), index / animator.ANIMATION_FPS)
                    self.assertIs(screen.blit.call_args.args[0], frames[index % len(frames)])
            (root / "sample" / "left" / "left_4.png").unlink()
            with patch.object(BossSpriteAnimator, "BOSS_FOLDERS", {"sample": "sample"}):
                with self.assertRaises(FileNotFoundError):
                    BossSpriteAnimator(root)

    def test_shared_canvas_preserves_anchor_when_limbs_change_bounds(self):
        first = pygame.Surface((100, 80), pygame.SRCALPHA)
        first.fill((255, 255, 255), (40, 30, 20, 20))
        first.fill((255, 0, 0), (48, 38, 4, 4))
        second = first.copy()
        second.fill((255, 255, 0), (60, 30, 20, 4))
        aligned = self.animator._align_frames({"down": [first, second]})["down"]
        anchors = []
        for frame in aligned:
            red = pygame.mask.from_threshold(frame, (255, 0, 0, 255), (5, 5, 5, 255))
            anchors.append(red.centroid())
        self.assertEqual(anchors[0], anchors[1])
        self.assertEqual(aligned[0].get_size(), aligned[1].get_size())

    def test_real_path_has_only_left_right_down_and_switches_at_all_corners(self):
        directions = []
        for start, end in zip(self.path, self.path[1:]):
            dx, dy = end[0] - start[0], end[1] - start[1]
            directions.append("right" if dx > 0 else "left" if dx < 0 else "down")
        self.assertIn("left", directions)
        self.assertIn("right", directions)
        for name in self.animator.BOSS_FOLDERS:
            enemy = self.boss(name)
            for index, direction in enumerate(directions):
                enemy.path_index = index
                enemy.progress_in_segment = 0.75
                screen = Mock()
                self.animator.draw(screen, enemy, (100, 120), 0)
                self.assertIs(screen.blit.call_args.args[0], self.animator.frames[name, direction][0])
            enemy.path_index = len(self.path) - 1
            self.assertEqual(self.animator.direction(enemy), "right")

    def test_actual_move_switches_to_down_at_corner_and_up_uses_unflipped_down(self):
        enemy = self.boss(path=[(1, 0), (0, 0), (0, 1)])
        self.assertEqual(self.animator.direction(enemy), "left")
        enemy.move(1 / enemy.speed)
        self.assertEqual(self.animator.direction(enemy), "down")
        enemy = self.boss(path=[(0, 1), (0, 0)])
        screen = Mock()
        self.animator.draw(screen, enemy, (100, 120), 0)
        self.assertIs(screen.blit.call_args.args[0], self.animator.frames[enemy.name, "down"][0])
        self.assertEqual(self.animator.direction(self.boss(path=[(0, 0)])), "down")

    def test_all_frames_loop_and_stay_centered_for_every_boss_direction(self):
        for name in self.animator.BOSS_FOLDERS:
            for direction, end in (("down", (0, 1)), ("left", (-1, 0)), ("right", (1, 0))):
                enemy = self.boss(name, [(0, 0), end])
                frames = self.animator.frames[name, direction]
                for index in range(len(frames) * 2 + 1):
                    with self.subTest(name=name, direction=direction, index=index):
                        screen = Mock()
                        rect = self.animator.draw(screen, enemy, (100, 120),
                                                  index / self.animator.ANIMATION_FPS)
                        self.assertIs(screen.blit.call_args.args[0], frames[index % len(frames)])
                        self.assertEqual(rect.midbottom, (100, 120))

    def test_frame_clock_is_independent_of_movement_speed_slow_and_render_count(self):
        enemy = self.boss()
        frames = self.animator.frames[enemy.name, "left"]
        for speed in (0, 0.55, 100):
            enemy.speed = speed
            enemy.apply_slow_effect(0.1, 10, 0)
            for elapsed in (0.01, 0.124, 0.125, 0.999, 1, 1.125):
                screen = Mock()
                self.animator.draw(screen, enemy, (100, 120), elapsed)
                expected = frames[int(elapsed * self.animator.ANIMATION_FPS) % len(frames)]
                self.assertIs(screen.blit.call_args.args[0], expected)
                self.animator.draw(screen, enemy, (100, 120), elapsed)
                self.assertIs(screen.blit.call_args.args[0], expected)

    def test_renderer_uses_simulation_time_at_each_combat_speed_without_mutating_state(self):
        for speed in COMBAT_SPEEDS:
            game = Game()
            state = game.reset(start_at_title=False)
            game.step(Action(ActionType.START_WAVE))
            game.wave_manager.spawn_queue = []
            state.enemies = [self.boss()]
            state.combat_speed = speed
            game.update(0.25)
            before = copy.deepcopy(state)
            with patch.object(self.animator, "draw", wraps=self.animator.draw) as draw:
                self.renderer.render(state)
            self.assertAlmostEqual(state.wave_elapsed, 0.25 * speed)
            self.assertEqual(draw.call_args.args[3], state.wave_elapsed)
            self.assertEqual(state, before)

    def test_hp_bar_stays_above_each_frame_and_keeps_health_ratio(self):
        for name in self.animator.BOSS_FOLDERS:
            enemy = self.boss(name)
            enemy.health = 250
            for index in range(8):
                with patch.object(self.animator, "draw", wraps=self.animator.draw) as draw:
                    self.screen.fill((0, 0, 0))
                    self.renderer._draw_enemy(enemy, index / self.animator.ANIMATION_FPS)
                image = self.animator.frames[name, "left"][index]
                pos = draw.call_args.args[2]
                top = image.get_rect(midbottom=pos).top
                self.assertEqual(self.screen.get_at((pos[0] - 18, top - 14))[:3], COLOR_GREEN)
                self.assertEqual(self.screen.get_at((pos[0], top - 14))[:3], COLOR_RED)
                self.assertLess(top - 14 + 4, top)

    def test_board_uses_animation_and_information_panel_keeps_original_portrait(self):
        for name in self.animator.BOSS_FOLDERS:
            portraits = MagicMock()
            portraits.__getitem__.side_effect = self.renderer.boss_portraits.__getitem__
            state = GameState(phase=GamePhase.WAVE_ACTIVE, enemies=[self.boss(name)])
            with patch.object(self.renderer, "boss_portraits", portraits):
                self.renderer._draw_enemy(state.enemies[0])
                portraits.__getitem__.assert_not_called()
                self.renderer._render_side_panel(state)
                portraits.__getitem__.assert_called_once_with((name, 130))


if __name__ == "__main__":
    unittest.main()
