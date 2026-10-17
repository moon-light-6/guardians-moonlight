import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import COLOR_GREEN, COLOR_RED, SCREEN_HEIGHT, SCREEN_WIDTH
from display.enemy_animation import EnemySpriteAnimator
from display.renderer import Renderer
from display.render_sizes import NORMAL_ENEMY_DIAMETER
from game.enemy import Enemy, EnemyType
from game.map import GameMap
from game.state import GamePhase, GameState


class TestEnemyAnimation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        cls.renderer = Renderer(cls.screen)
        cls.animator = cls.renderer.enemy_animator
        cls.path = GameMap().get_path()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def enemy(self, kind=EnemyType.BASIC, path=None):
        return Enemy.create(kind, path or self.path, 1000)

    def test_all_three_types_load_eight_unique_transparent_frames_per_direction(self):
        self.assertEqual(set(self.animator.ENEMY_FOLDERS),
                         {EnemyType.BASIC, EnemyType.FAST, EnemyType.TANK})
        for kind in self.animator.ENEMY_FOLDERS:
            sizes = set()
            for direction in self.animator.DIRECTIONS:
                with self.subTest(kind=kind, direction=direction):
                    frames = self.animator.frames[kind, direction]
                    self.assertEqual(len(frames), 8)
                    self.assertEqual(len({pygame.image.tobytes(f, "RGBA") for f in frames}), 8)
                    for frame in frames:
                        sizes.add(frame.get_size())
                        self.assertTrue(frame.get_flags() & pygame.SRCALPHA)
                        self.assertEqual(frame.get_at((0, 0)).a, 0)
                        self.assertEqual(max(frame.get_size()), NORMAL_ENEMY_DIAMETER)
            self.assertEqual(len(sizes), 1)

    def test_numeric_order_variable_counts_and_unused_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {"front": (1, 2, 10), "left": (5,), "right": (1, 3)}
            for direction, numbers in expected.items():
                folder = root / "sample" / direction
                folder.mkdir(parents=True)
                for number in reversed(numbers):
                    frame = pygame.Surface((80, 40), pygame.SRCALPHA)
                    frame.fill((20 + number * 20, 50, 100, 255), (10, 10, 60, 20))
                    pygame.image.save(frame, str(folder / f"{direction}_{number:02d}.png"))
                (folder / "notes.txt").write_text("ignored", encoding="utf-8")
            for name in ("preview", "sheets"):
                (root / "sample" / name).mkdir()
                (root / "sample" / name / "bad.png").write_bytes(b"not a PNG")
            with patch.object(EnemySpriteAnimator, "ENEMY_FOLDERS", {EnemyType.BASIC: "sample"}):
                animator = EnemySpriteAnimator(root)
            ends = {"front": (0, 1), "left": (-1, 0), "right": (1, 0)}
            for direction, numbers in expected.items():
                frames = animator.frames[EnemyType.BASIC, direction]
                # Downscaling can lose a few color levels through integer filtering.
                for frame, number in zip(frames, numbers):
                    self.assertAlmostEqual(frame.get_at(frame.get_rect().center).r,
                                           20 + number * 20, delta=3)
                self.assertAlmostEqual(frames[0].get_width() / frames[0].get_height(), 3, delta=0.2)
                enemy = self.enemy(path=[(0, 0), ends[direction]])
                for index in range(len(frames) * 2):
                    screen = Mock()
                    animator.draw(screen, enemy, (100, 120), index / animator.ANIMATION_FPS)
                    self.assertIs(screen.blit.call_args.args[0], frames[index % len(frames)])
            (root / "sample" / "left" / "left_05.png").unlink()
            with patch.object(EnemySpriteAnimator, "ENEMY_FOLDERS", {EnemyType.BASIC: "sample"}):
                with self.assertRaises(FileNotFoundError):
                    EnemySpriteAnimator(root)

    def test_different_source_canvases_and_moving_limbs_keep_the_same_anchor(self):
        first = pygame.Surface((100, 80), pygame.SRCALPHA)
        first.fill((255, 255, 255), (40, 30, 20, 20))
        first.fill((255, 0, 0), (48, 38, 4, 4))
        second = pygame.Surface((120, 100), pygame.SRCALPHA)
        second.blit(first, (10, 10))
        second.fill((255, 255, 0), (70, 40, 20, 4))
        aligned = self.animator._align_frames({"front": [first], "left": [second]})
        frames = [aligned["front"][0], aligned["left"][0]]
        self.assertEqual(frames[0].get_size(), frames[1].get_size())
        self.assertEqual(
            pygame.mask.from_threshold(frames[0], (255, 0, 0, 255), (5, 5, 5, 255)).centroid(),
            pygame.mask.from_threshold(frames[1], (255, 0, 0, 255), (5, 5, 5, 255)).centroid())

    def test_real_path_directions_and_upward_fallback(self):
        counts = {"left": 0, "right": 0, "front": 0}
        for kind in self.animator.ENEMY_FOLDERS:
            enemy = self.enemy(kind)
            for index, (start, end) in enumerate(zip(self.path, self.path[1:])):
                enemy.path_index = index
                expected = "left" if end[0] < start[0] else "right" if end[0] > start[0] else "front"
                self.assertEqual(self.animator.direction(enemy), expected)
                if kind == EnemyType.BASIC:
                    counts[expected] += 1
            enemy.path_index = len(self.path) - 1
            self.assertEqual(self.animator.direction(enemy), "right")
        # Hand-drawn bends use diagonal micro-segments; visual facing remains
        # derived from the horizontal component and needs both directions.
        self.assertGreater(counts["left"], 0)
        self.assertGreater(counts["right"], 0)
        self.assertEqual(counts["front"], 0)
        upward = self.enemy(path=[(0, 1), (0, 0)])
        screen = Mock()
        self.animator.draw(screen, upward, (100, 120), 0)
        self.assertIs(screen.blit.call_args.args[0], self.animator.frames[EnemyType.BASIC, "front"][0])
        self.assertEqual(self.animator.direction(self.enemy(path=[(0, 0)])), "front")

    def test_all_frames_loop_without_loading_or_changing_enemy_state(self):
        for kind in self.animator.ENEMY_FOLDERS:
            for direction, end in (("front", (0, 1)), ("left", (-1, 0)), ("right", (1, 0))):
                enemy = self.enemy(kind, [(0, 0), end])
                enemy.enemy_id = 123
                before = copy.deepcopy(vars(enemy))
                frames = self.animator.frames[kind, direction]
                with patch("pygame.image.load") as load:
                    for index in range(len(frames) * 2 + 1):
                        screen = Mock()
                        rect = self.animator.draw(screen, enemy, (100, 120), index / self.animator.ANIMATION_FPS)
                        self.assertIs(screen.blit.call_args.args[0], frames[index % len(frames)])
                        self.assertEqual(rect.midbottom, (100, 120))
                    load.assert_not_called()
                self.assertEqual(vars(enemy), before)

    def test_movement_and_slow_do_not_change_the_frame_clock(self):
        enemy = self.enemy()
        for speed in (0, 0.7, 1, 1.5, 5):
            enemy.speed = speed
            enemy.apply_slow_effect(0.7, 2, 0)
            for elapsed in (0, 0.125, 0.5, 1.125):
                screen = Mock()
                self.animator.draw(screen, enemy, (100, 120), elapsed)
                self.assertIs(screen.blit.call_args.args[0],
                              self.animator.frames[EnemyType.BASIC, "left"][int(elapsed * 8) % 8])

    def test_corner_movement_uses_new_direction_without_changing_position(self):
        enemy = self.enemy(path=[(1, 0), (0, 0), (0, 1)])
        self.assertEqual(self.animator.direction(enemy), "left")
        enemy.move(1 / enemy.speed)
        before = copy.deepcopy(vars(enemy))
        pos = self.renderer.map.grid_to_pixel(enemy.get_current_position())
        screen = Mock()
        rect = self.animator.draw(screen, enemy, pos, 0)
        self.assertEqual(rect.midbottom, pos)
        self.assertIs(screen.blit.call_args.args[0], self.animator.frames[EnemyType.BASIC, "front"][0])
        self.assertEqual(vars(enemy), before)

    def test_hp_bars_and_renderer_dispatch_keep_bosses_separate(self):
        for kind in self.animator.ENEMY_FOLDERS:
            enemy = self.enemy(kind)
            enemy.health = 500
            pos = self.renderer.map.grid_to_pixel(enemy.get_current_position())
            for index in range(8):
                self.screen.fill((0, 0, 0))
                with patch.object(self.animator, "draw", wraps=self.animator.draw) as normal, \
                        patch.object(self.renderer.boss_animator, "draw") as boss, \
                        patch("pygame.draw.circle") as circle:
                    self.renderer._draw_enemy(enemy, index / self.animator.ANIMATION_FPS)
                normal.assert_called_once()
                boss.assert_not_called()
                circle.assert_not_called()
                frame = self.animator.frames[kind, "left"][index]
                top = frame.get_rect(midbottom=pos).top
                self.assertEqual(self.screen.get_at((pos[0] - 18, top - 14))[:3], COLOR_GREEN)
                self.assertEqual(self.screen.get_at((pos[0], top - 14))[:3], COLOR_RED)
                self.assertLess(top - 14 + 4, top)
        enemy = self.enemy(EnemyType.BOSS)
        with patch.object(self.animator, "draw") as normal, \
                patch.object(self.renderer.boss_animator, "draw", wraps=self.renderer.boss_animator.draw) as boss:
            self.renderer._draw_enemy(enemy, 0.25)
        normal.assert_not_called()
        boss.assert_called_once()

    def test_renderer_passes_wave_time_and_keeps_ids_observations_and_effects_unchanged(self):
        state = GameState(phase=GamePhase.WAVE_ACTIVE, wave_elapsed=0.375)
        for index, kind in enumerate(self.animator.ENEMY_FOLDERS, start=1):
            enemy = self.enemy(kind)
            enemy.enemy_id = index
            state.enemies.append(enemy)
        state.effects = [{"kind": "claw", "from": (2, 0), "to": (0, 0),
                          "target_id": 1, "last_target_position": (0, 0), "age": 0.1, "ttl": 0.4}]
        before, observation = copy.deepcopy(state), copy.deepcopy(state.get_observation())
        with patch.object(self.animator, "draw", wraps=self.animator.draw) as normal:
            self.renderer.render(state)
        self.assertEqual(normal.call_count, 3)
        self.assertTrue(all(call.args[3] == state.wave_elapsed for call in normal.call_args_list))
        self.assertEqual(state, before)
        self.assertEqual([enemy.enemy_id for enemy in state.enemies], [1, 2, 3])
        self.assertEqual(state.get_observation(), observation)


if __name__ == "__main__":
    unittest.main()
