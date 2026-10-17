import copy
from dataclasses import asdict
import json
import os
import pickle
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from config import SCREEN_HEIGHT, SCREEN_WIDTH, SIMULATION_STEP
from display.effect_animation import AttackEffectAnimator
from display.renderer import Renderer
from game.actions import Action, ActionType
from game.combat import Combat
from game.enemy import Enemy, EnemyType
from game.engine import Game
from game.state import GamePhase


class TestEffectTracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        cls.renderer = Renderer(cls.screen)
        cls.animator = cls.renderer.effect_animator

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def enemy(self, kind=EnemyType.BASIC, path=None, hp=1000):
        return Enemy.create(kind, path or [(2, 1), (1, 1), (1, 2), (10, 2)], hp)

    def battle(self, kind="ARCHER", enemies=None):
        game = Game()
        state = game.reset(seed=42, start_at_title=False)
        game.step(Action(ActionType.START_WAVE))
        # Keep combat active while verifying an effect after its last target leaves.
        game.wave_manager.spawn_queue = [
            {"spawn_time": 10000, "type": EnemyType.BASIC, "hp": 100}]
        state.towers = {0: {"type": kind, "level": 1, "slot_id": 0, "cooldown": 999}}
        state.enemies = enemies if enemies is not None else [self.enemy()]
        game.update(SIMULATION_STEP)
        return game

    @staticmethod
    def positions(state):
        return {enemy.enemy_id: enemy.get_current_position() for enemy in state.enemies}

    def visual(self, effect, state):
        return self.animator.resolve_targets(effect, self.positions(state))

    def test_ids_are_deterministic_unique_across_waves_and_reset_with_new_run(self):
        sequences = []
        for _ in range(2):
            game = Game()
            game.reset(seed=42, start_at_title=False)
            game.step(Action(ActionType.START_WAVE))
            game.update(2)
            first = [enemy.enemy_id for enemy in game.state.enemies]
            game.state.enemies = []
            game.wave_manager.spawn_queue = []
            game.update(SIMULATION_STEP)
            self.assertEqual(game.state.phase, GamePhase.SETTLEMENT)
            game.step(Action(ActionType.CONTINUE))
            game.step(Action(ActionType.START_WAVE))
            game.update(2)
            second = [enemy.enemy_id for enemy in game.state.enemies]
            self.assertTrue(all(type(value) is int for value in first + second))
            self.assertEqual(len(set(first + second)), len(first + second))
            self.assertGreater(min(second), max(first))
            sequences.append(first + second)
            game.step(Action(ActionType.RESTART))
            game.step(Action(ActionType.START_WAVE))
            game.update(2)
            self.assertEqual([enemy.enemy_id for enemy in game.state.enemies], first)
        self.assertEqual(sequences[0], sequences[1])

    def test_ids_survive_serialization_and_old_observation_shape_is_unchanged(self):
        game = self.battle()
        state = game.state
        observation = state.get_observation()
        self.assertNotIn("enemy_id", observation)
        self.assertEqual(set(observation), {"stage", "gold", "life", "phase", "actions",
                                            "towers", "enemy_count", "combat_speed"})
        self.assertEqual(asdict(state.enemies[0])["enemy_id"], state.enemies[0].enemy_id)
        restored = Game()
        restored.state = pickle.loads(pickle.dumps(state))
        restored.wave_manager.spawn_queue = copy.deepcopy(game.wave_manager.spawn_queue)
        new_enemy = self.enemy()
        restored.state.enemies.append(new_enemy)
        old_id = state.enemies[0].enemy_id
        restored.update(SIMULATION_STEP)
        self.assertGreater(new_enemy.enemy_id, old_id)
        self.assertEqual(restored.state.enemies[0].enemy_id, old_id)
        json.dumps(restored.state.effects)

    def test_restore_reserves_ids_referenced_only_by_departed_targets(self):
        game = self.battle()
        effect = game.state.effects[0]
        effect["target_id"] = 50
        game.state.enemies = [self.enemy()]
        game._next_enemy_id = 1
        game.update(SIMULATION_STEP)
        self.assertGreater(game.state.enemies[0].enemy_id, 50)

    def test_normal_and_boss_targets_move_pngs_and_motion_without_mutating_events(self):
        for enemy_kind in (EnemyType.BASIC, EnemyType.BOSS):
            for tower_kind, effect_kind in (("ARCHER", "claw"), ("CANNON", "fire")):
                with self.subTest(enemy=enemy_kind, tower=tower_kind):
                    game = self.battle(tower_kind, [self.enemy(enemy_kind)])
                    enemy = game.state.enemies[0]
                    original = game.state.effects[0]["to"]
                    game.update(0.2)
                    state = game.state
                    before = copy.deepcopy(state)
                    with patch.object(self.animator, "_draw_claw_motion") as claw, \
                            patch.object(self.animator, "_draw_fire_wave") as fire, \
                            patch.object(self.animator, "draw", wraps=self.animator.draw) as draw:
                        self.renderer.render(state)
                    visual = next(call.args[1] for call in draw.call_args_list
                                  if call.args[1]["kind"] == effect_kind)
                    self.assertEqual(visual["to"], enemy.get_current_position())
                    self.assertNotEqual(visual["to"], original)
                    motion = claw if tower_kind == "ARCHER" else fire
                    self.assertEqual(motion.call_args.args[1]["to"], enemy.get_current_position())
                    self.assertEqual(state.effects[0]["to"], original)
                    self.assertEqual(state, before)
                    target = self.visual(state.effects[0], state)
                    screen = Mock()
                    with patch.object(self.animator, "_draw_claw_motion"), \
                            patch.object(self.animator, "_draw_fire_wave"):
                        self.animator.draw(screen, target, self.renderer.map)
                    pixel = self.renderer.map.grid_to_pixel(enemy.get_current_position())
                    anchor = self.animator.anchors[effect_kind]
                    self.assertEqual(screen.blit.call_args.args[1],
                                     (pixel[0] - anchor[0], pixel[1] - anchor[1]))

    def test_tracking_follows_a_path_corner_and_updates_archer_facing(self):
        enemy = self.enemy(path=[(2, 1), (1, 1), (1, -1), (8, -1)])
        enemy.speed = 4
        game = self.battle(enemies=[enemy])
        game.update(0.3)
        self.assertEqual(enemy.path_index, 1)
        visual = self.visual(game.state.effects[0], game.state)
        self.assertEqual(visual["to"], enemy.get_current_position())
        self.assertEqual(visual["to"][0], 1)
        # Move across the tower's north/south boundary before the next attack.
        enemy.move(0.2)
        with patch.object(self.renderer.tower_animator, "draw",
                          wraps=self.renderer.tower_animator.draw) as tower:
            self.renderer.render(game.state)
        effects = tower.call_args.kwargs["effects"]
        self.assertEqual(effects[0]["to"], enemy.get_current_position())
        self.assertEqual(self.renderer.tower_animator.last_directions[0, "ARCHER"], "NW")

    def test_each_chain_target_and_link_tracks_its_own_id_in_original_order(self):
        enemies = [self.enemy(path=[(x, 1), (x, 5)]) for x in (2, 1, 3)]
        game = self.battle("LIGHTNING", enemies)
        effect = game.state.effects[0]
        self.assertEqual(effect["target_ids"], [enemy.enemy_id for enemy in enemies])
        for index, enemy in enumerate(enemies):
            enemy.speed = index + 1
        game.update(0.25)
        effect = game.state.effects[0]
        visual = self.visual(effect, game.state)
        points = [enemy.get_current_position() for enemy in enemies]
        self.assertEqual(visual["points"], points)
        self.assertNotEqual(effect["points"], points)
        self.assertEqual((effect["hit_ttl"], effect["hit_stagger"]), (1, 0.12))
        self.assertAlmostEqual(effect["ttl"], 1.24)
        with patch.object(self.animator, "_draw_chain_link") as link:
            screen = Mock()
            self.animator.draw(screen, visual, self.renderer.map)
        pixels = [self.renderer.map.grid_to_pixel(point) for point in points]
        origin = self.renderer.map.grid_to_pixel(effect["from"])
        self.assertEqual([(call.args[1], call.args[2]) for call in link.call_args_list],
                         list(zip([origin] + pixels[:-1], pixels)))
        anchor = self.animator.anchors["lightning"]
        self.assertEqual([call.args[1] for call in screen.blit.call_args_list],
                         [(x - anchor[0], y - anchor[1]) for x, y in pixels])

    def test_chain_keeps_a_dead_middle_target_and_continues_tracking_the_others(self):
        enemies = [self.enemy(path=[(x, 1), (x, 5)]) for x in (2, 1, 3)]
        game = self.battle("LIGHTNING", enemies)
        game.update(0.1)
        enemies[1].take_damage(10000)
        frozen = enemies[1].get_current_position()
        game.update(0.15)
        visual = self.visual(game.state.effects[0], game.state)
        self.assertEqual(visual["points"], [enemies[0].get_current_position(), frozen,
                                            enemies[2].get_current_position()])
        self.assertEqual(len(visual["points"]), 3)

    def test_death_before_any_render_finishes_at_last_position_and_does_not_retarget(self):
        game = self.battle()
        target = game.state.enemies[0]
        game.update(0.1)
        target.take_damage(10000)
        frozen = target.get_current_position()
        game.update(SIMULATION_STEP)
        self.assertNotIn(target, game.state.enemies)
        replacement = self.enemy(path=[(8, 1), (9, 1)])
        game.state.enemies.append(replacement)
        game.update(SIMULATION_STEP)
        effect = game.state.effects[0]
        self.assertNotEqual(target.enemy_id, replacement.enemy_id)
        self.assertEqual(self.visual(effect, game.state)["to"], frozen)
        self.assertEqual(effect["last_target_position"], frozen)
        self.renderer.render(game.state)
        game.update(0.4)
        self.assertFalse(any(e.get("target_id") == target.enemy_id for e in game.state.effects))

    def test_arrival_before_any_render_records_endpoint_and_effect_expires(self):
        target = self.enemy(path=[(2, 1), (2.1, 1)])
        game = self.battle(enemies=[target])
        game.update(0.15)
        self.assertTrue(target.reached_base)
        self.assertEqual(game.state.life, 19)
        self.assertEqual(game.state.gold, 200)
        self.assertEqual(game.state.enemies, [])
        effect = game.state.effects[0]
        self.assertEqual(self.visual(effect, game.state)["to"], (2.1, 1))
        self.renderer.render(game.state)
        game.update(0.3)
        self.assertEqual(game.state.effects, [])

    def test_lethal_first_hit_still_has_a_fallback_position(self):
        game = self.battle(enemies=[self.enemy(hp=1)])
        self.assertEqual(game.state.enemies, [])
        effect = game.state.effects[0]
        self.assertIsInstance(effect["target_id"], int)
        self.assertEqual(self.visual(effect, game.state)["to"], effect["to"])
        self.assertEqual(game.state.gold, 205)
        self.renderer.render(game.state)

    def test_multiple_towers_keep_independent_effects_on_the_same_target(self):
        game = self.battle()
        state = game.state
        target = state.enemies[0]
        state.towers[6] = {"type": "ARCHER", "level": 1, "slot_id": 6, "cooldown": 999}
        game.update(SIMULATION_STEP)
        self.assertEqual(len(state.effects), 2)
        self.assertEqual({e["target_id"] for e in state.effects}, {target.enemy_id})
        game.update(0.1)
        visuals = [self.visual(effect, state) for effect in state.effects]
        self.assertEqual([e["to"] for e in visuals], [target.get_current_position()] * 2)
        self.assertNotEqual(visuals[0]["from"], visuals[1]["from"])
        self.assertNotEqual(visuals[0]["age"], visuals[1]["age"])

    def test_splash_damage_remains_at_impact_and_visual_motion_never_deals_damage(self):
        target = self.enemy(path=[(2, 1), (2, 6)])
        near = self.enemy(path=[(2.5, 1), (2.5, 6)])
        far = self.enemy(path=[(2, 4), (2, 6)])
        game = self.battle("CANNON", [target, near, far])
        self.assertEqual([e.health for e in (target, near, far)], [960, 960, 1000])
        impact = game.state.effects[0]["to"]
        target.speed = 4
        game.update(0.5)
        effect = game.state.effects[0]
        self.assertEqual(effect["to"], impact)
        self.assertNotEqual(self.visual(effect, game.state)["to"], impact)
        before = [e.health for e in (target, near, far)]
        for _ in range(3):
            self.renderer.render(game.state)
        self.assertEqual([e.health for e in (target, near, far)], before)
        self.assertEqual(before, [960, 960, 1000])

    def test_ice_events_and_field_pixels_stay_fixed_while_target_moves(self):
        game = self.battle("ICE")
        original = copy.deepcopy(game.state.effects)
        game.update(0.3)
        water, field = game.state.effects
        self.assertEqual(water["to"], original[0]["to"])
        self.assertEqual(field["cell"], original[1]["cell"])
        self.assertNotIn("target_id", water)
        self.assertNotIn("target_id", field)
        self.assertIs(self.visual(water, game.state), water)
        self.assertIs(self.visual(field, game.state), field)
        current = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        previous = current.copy()
        expected = {**original[1], "age": field["age"]}
        self.animator.draw(current, field, self.renderer.map)
        self.animator.draw(previous, expected, self.renderer.map)
        self.assertEqual(pygame.image.tobytes(current, "RGBA"), pygame.image.tobytes(previous, "RGBA"))
        self.assertEqual((field["ttl"], field["slow_ttl"]), (2, 2))
        self.assertEqual(Combat.get_field_speed_modifier(field["cell"], [field]), 0.7)

    def test_legacy_coordinate_only_events_keep_their_original_locations(self):
        for effect in ({"kind": "claw", "to": (1, 2)},
                       {"kind": "fire", "to": (1, 2)},
                       {"kind": "lightning", "points": [(1, 2), (3, 4)]}):
            before = copy.deepcopy(effect)
            self.assertEqual(AttackEffectAnimator.resolve_targets(effect, {9: (8, 8)}), before)
            self.assertEqual(effect, before)


if __name__ == "__main__":
    unittest.main()
