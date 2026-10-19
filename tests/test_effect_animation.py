import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import SIMULATION_STEP
from display.effect_animation import AttackEffectAnimator
from game.actions import Action, ActionType
from game.combat import Combat
from game.enemy import Enemy, EnemyType
from game.engine import Game


class TestEffectAnimation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))
        cls.animator = AttackEffectAnimator()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_all_replacement_sheets_load_twelve_aligned_frames(self):
        for kind, config in self.animator.EFFECT_CONFIG.items():
            with self.subTest(kind=kind):
                self.assertEqual((config["rows"], config["cols"], config["frame_count"]), (2, 6, 12))
                frames = self.animator.frames[kind]
                self.assertEqual(len(frames), 12)
                self.assertEqual(len(config["anchors"]), 12)
                self.assertEqual(len({frame.get_size() for frame in frames}), 1)
                self.assertTrue(frames[0].get_rect().collidepoint(self.animator.anchors[kind]))

    def test_sheet_split_preserves_row_order_and_odd_width_pixels(self):
        sheet = pygame.Surface((73, 25), pygame.SRCALPHA)
        colors = [(index * 20, 255 - index * 20, 100, 255) for index in range(12)]
        for index, color in enumerate(colors):
            left, right = round(index % 6 * 73 / 6), round((index % 6 + 1) * 73 / 6)
            top, bottom = round(index // 6 * 25 / 2), round((index // 6 + 1) * 25 / 2)
            sheet.fill(color, (left, top, right - left, bottom - top))
        frames = self.animator._slice_sheet(sheet, 2, 6, 12)
        self.assertEqual(sum(frame.get_width() * frame.get_height() for frame in frames), 73 * 25)
        for frame, color in zip(frames, colors):
            self.assertEqual(tuple(frame.get_at((0, 0))), color)
            self.assertEqual(tuple(frame.get_at((frame.get_width() - 1, frame.get_height() - 1))), color)

    def test_attack_effects_play_every_frame_at_fixed_targets_until_expiry(self):
        projection = Mock()
        projection.game_to_pixel.return_value = (100, 120)
        for kind in ("claw", "fire", "lightning"):
            ttl = Combat.EFFECT_TTL[kind]
            effect = {"kind": kind, "age": 0, "ttl": ttl, "to": (3, 4), "points": [(3, 4)]}
            for index in range(12):
                with self.subTest(kind=kind, frame=index):
                    screen = Mock()
                    effect["age"] = ttl * (index + 0.5) / 12
                    with patch.object(self.animator, "_draw_claw_motion"), patch.object(self.animator, "_draw_fire_wave"):
                        self.animator.draw(screen, effect, projection)
                    self.assertEqual(screen.blit.call_count, 1)
                    for call in screen.blit.call_args_list:
                        self.assertIs(call.args[0], self.animator.frames[kind][index])
                        anchor = self.animator.anchors[kind]
                        self.assertEqual(call.args[1], (100 - anchor[0], 120 - anchor[1]))
            effect["age"] = ttl
            screen = Mock()
            self.animator.draw(screen, effect, projection)
            screen.blit.assert_not_called()

    def test_chain_targets_start_in_order_and_each_plays_all_twelve_frames(self):
        projection = Mock()
        projection.game_to_pixel.side_effect = lambda point: point
        effect = {"kind": "lightning", "age": 0, "ttl": 1.24,
                  "from": (40, 210), "points": [(200, 210), (360, 210), (520, 210)],
                  "hit_ttl": 1.0, "hit_stagger": 0.12}
        anchor = self.animator.anchors["lightning"]
        with patch.object(self.animator, "_draw_chain_link") as link:
            for age, count in ((0, 1), (0.119, 1), (0.12, 2), (0.239, 2),
                               (0.24, 3), (0.999, 3), (1.0, 2), (1.12, 1), (1.24, 0)):
                with self.subTest(age=age):
                    effect["age"] = age
                    screen = Mock()
                    self.animator.draw(screen, effect, projection)
                    self.assertEqual(screen.blit.call_count, count)
            # 각 타겟은 자신의 시작 시각부터 0~11을 끝까지 재생합니다.
            for target_index, point in enumerate(effect["points"]):
                for frame in range(12):
                    effect["age"] = target_index * 0.12 + (frame + 0.5) / 12
                    screen = Mock()
                    self.animator.draw(screen, effect, projection)
                    destination = (point[0] - anchor[0], point[1] - anchor[1])
                    hits = [call for call in screen.blit.call_args_list if call.args[1] == destination]
                    self.assertEqual(len(hits), 1)
                    self.assertIs(hits[0].args[0], self.animator.frames["lightning"][frame])
            effect["age"] = 0.24
            link.reset_mock()
            self.animator.draw(Mock(), effect, projection)
            edges = [(call.args[1], call.args[2]) for call in link.call_args_list]
            self.assertEqual(edges, [((40, 210), (200, 210)), ((200, 210), (360, 210)),
                                     ((360, 210), (520, 210))])

    def test_claw_afterimage_follows_target_direction(self):
        projection = Mock()
        projection.game_to_pixel.side_effect = lambda point: point
        effect = {"kind": "claw", "to": (180, 160), "age": 0.1, "ttl": 0.4}
        centers = []
        for origin in ((40, 160), (320, 160)):
            screen = pygame.Surface((360, 300))
            screen.fill((7, 9, 18))
            effect["from"] = origin
            self.animator._draw_claw_motion(screen, effect, projection, 3)
            changed = pygame.mask.from_threshold(screen, (7, 9, 18, 255), (1, 1, 1, 255))
            changed.invert()
            centers.append(changed.centroid()[0])
        self.assertLess(centers[0], 180)
        self.assertGreater(centers[1], 180)

    def test_fire_embers_gather_before_expanding_outward(self):
        projection = Mock()
        projection.game_to_pixel.side_effect = lambda point: point
        effect = {"kind": "fire", "to": (180, 160), "age": 0, "ttl": 0.65, "radius": 1.0}
        widths = []
        for age in (0.03, 0.13, 0.5):
            screen = pygame.Surface((360, 300))
            screen.fill((7, 9, 18))
            effect["age"] = age
            self.animator._draw_fire_wave(screen, effect, projection)
            changed = pygame.mask.from_threshold(screen, (7, 9, 18, 255), (1, 1, 1, 255))
            changed.invert()
            bounds = changed.get_bounding_rects()
            widths.append(bounds[0].unionall(bounds[1:]).width)
        self.assertGreater(widths[0], widths[1] + 15)
        self.assertGreater(widths[2], widths[1] + 15)

    def test_field_energy_rises_after_base_and_circulates_while_anchored(self):
        tops, snapshots = [], []
        for age in (0.02, 0.25, 0.6, 0.8):
            screen = pygame.Surface((360, 300))
            screen.fill((7, 9, 18))
            self.animator._draw_field_energy(screen, (180, 160), age, 2)
            changed = pygame.mask.from_threshold(screen, (7, 9, 18, 255), (1, 1, 1, 255))
            changed.invert()
            bounds = changed.get_bounding_rects()
            bounds = bounds[0].unionall(bounds[1:])
            tops.append(bounds.top)
            snapshots.append(pygame.image.tobytes(screen, "RGB"))
            if age >= 0.4:
                self.assertAlmostEqual(bounds.centerx, 180, delta=2)
                self.assertAlmostEqual(bounds.centery, 160, delta=2)
        self.assertLess(tops[1], tops[0] - 10)
        self.assertNotEqual(snapshots[2], snapshots[3])

    def test_motion_accents_do_not_mutate_events_or_outlive_their_effects(self):
        projection = Mock()
        projection.game_to_pixel.side_effect = lambda point: point
        for kind, ttl in (("claw", 0.4), ("fire", 0.65), ("slow_field", 2.0)):
            with self.subTest(kind=kind):
                effect = {"kind": kind, "from": (40, 160), "to": (180, 160), "cell": (180, 160),
                          "age": 0.2, "ttl": ttl, "slow_ttl": 2.0, "radius": 1.0}
                before = dict(effect)
                screen = pygame.Surface((360, 300))
                screen.fill((7, 9, 18))
                self.animator.draw(screen, effect, projection)
                self.assertEqual(effect, before)
                for age in (ttl - 1e-14, ttl, ttl + 1):
                    screen.fill((7, 9, 18))
                    background = pygame.image.tobytes(screen, "RGB")
                    effect["age"] = age
                    self.animator.draw(screen, effect, projection)
                    self.assertTrue(pygame.image.tobytes(screen, "RGB") == background)

    def test_chain_connection_pixels_appear_sequentially_between_targets(self):
        projection = Mock()
        projection.game_to_pixel.side_effect = lambda point: point
        effect = {"kind": "lightning", "age": 0, "ttl": 1.24,
                  "from": (40, 210), "points": [(200, 210), (360, 210), (520, 210)],
                  "hit_ttl": 1.0, "hit_stagger": 0.12}
        screen = pygame.Surface((640, 320))
        regions = [pygame.Rect(90, 200, 30, 20), pygame.Rect(270, 200, 30, 20),
                   pygame.Rect(430, 200, 30, 20)]
        blank = pygame.Surface((30, 20))
        blank.fill((7, 9, 18))
        background = pygame.image.tobytes(blank, "RGB")
        for age, expected in ((0, (True, False, False)), (0.12, (True, True, False)),
                              (0.24, (True, True, True)), (1.24, (False, False, False))):
            with self.subTest(age=age):
                screen.fill((7, 9, 18))
                effect["age"] = age
                self.animator.draw(screen, effect, projection)
                visible = tuple(pygame.image.tobytes(screen.subsurface(region), "RGB") != background
                                for region in regions)
                self.assertEqual(visible, expected)

    def test_chain_damage_is_immediate_and_points_stay_fixed_after_targets_move(self):
        tower = {"type": "LIGHTNING", "slot_id": 0, "level": 1, "cooldown": 999.0}
        enemies = [Enemy.create(EnemyType.BASIC, [(x, 0), (20, 0)], hp)
                   for x, hp in ((1, 20), (3, 1000), (2, 1000))]
        effect = Combat().attack(tower, (0, 0), enemies, 0)[0]
        self.assertEqual([enemy.health for enemy in enemies], [-5, 975, 975])
        self.assertFalse(enemies[0].is_alive)
        self.assertEqual(effect["points"], [(1, 0), (2, 0), (3, 0)])
        self.assertEqual(effect["hit_stagger"], 0.12)
        self.assertEqual(effect["hit_ttl"], 1.0)
        self.assertAlmostEqual(effect["ttl"], 1.24)
        self.assertEqual(tower["cooldown"], 0)
        for enemy in enemies:
            enemy.move(1)
        self.assertEqual(effect["points"], [(1, 0), (2, 0), (3, 0)])

    def test_edge_bleed_is_removed_without_removing_main_effect_or_inner_particles(self):
        frame = pygame.Surface((50, 50), pygame.SRCALPHA)
        # 본체가 경계에 닿아 있어도 남기고, 분리된 이웃 프레임 잔상만 제거합니다.
        pygame.draw.rect(frame, (255, 255, 255, 255), (0, 15, 40, 30))
        pygame.draw.rect(frame, (255, 255, 255, 255), (15, 0, 20, 2))
        pygame.draw.rect(frame, (255, 255, 255, 255), (43, 8, 2, 2))
        cleaned = self.animator._remove_edge_bleed(frame)
        self.assertEqual(cleaned.get_at((20, 0)).a, 0)
        self.assertEqual(cleaned.get_at((0, 25)).a, 255)
        self.assertEqual(cleaned.get_at((44, 9)).a, 255)

    def test_lightning_stays_visible_without_changing_damage_or_attack_interval(self):
        game = Game()
        state = game.reset(seed=42, start_at_title=False)
        game.step(Action(ActionType.BUY, slot_id=0))
        state.towers[0]["type"] = "LIGHTNING"
        game.step(Action(ActionType.START_WAVE))
        game.wave_manager.spawn_queue = []
        position = game.map.get_slot_position(0)
        enemy = Enemy.create(EnemyType.BASIC, [position, (position[0] + 10, position[1])], 1000)
        enemy.speed = 0
        state.enemies = [enemy]
        game.update(SIMULATION_STEP)
        game.update(1 - SIMULATION_STEP)
        lightning = next(effect for effect in state.effects if effect["kind"] == "lightning")
        self.assertAlmostEqual(lightning["age"], 1 - SIMULATION_STEP)
        self.assertEqual(enemy.health, 975)
        game.update(SIMULATION_STEP)
        self.assertFalse(any(effect["kind"] == "lightning" for effect in state.effects))
        self.assertEqual(enemy.health, 975)
        game.update(0.5)
        self.assertEqual(enemy.health, 950)
