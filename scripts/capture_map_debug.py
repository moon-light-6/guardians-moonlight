"""Capture the real pygame renderer's optional map-validation overlays."""

import os
from pathlib import Path
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pygame

from config import SCREEN_HEIGHT, SCREEN_WIDTH
from display.renderer import Renderer
from game.enemy import Enemy, EnemyType
from game.engine import Game


def capture() -> None:
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    renderer = Renderer(screen)
    renderer.show_map_debug = True
    game = Game()
    state = game.reset(seed=42, start_at_title=False)
    output = Path(__file__).resolve().parents[1] / "results"

    renderer.debug_show_slots = True
    renderer.debug_show_route = False
    renderer.render(state)
    pygame.image.save(screen, str(output / "map-platforms-debug.png"))

    renderer.debug_show_slots = False
    renderer.debug_show_route = True
    renderer.render(state)
    pygame.image.save(screen, str(output / "map-route-debug.png"))

    renderer.show_map_debug = False
    state.towers[0] = {"type": "ARCHER", "level": 1, "slot_id": 0, "cooldown": 999.0}
    state.selected_slot = 0
    state.enemies = [Enemy.create(EnemyType.BASIC, game.map.get_path(), 100)]
    renderer.render(state)
    pygame.image.save(screen, str(output / "map-runtime-anchors.png"))

    state.enemies = []
    state.towers = {}
    state.summons = [
        {"tower_type": tower_type, "slot_id": slot_id, "elapsed": 0.3}
        for slot_id, tower_type in enumerate(("ICE", "ARCHER", "LIGHTNING", "CANNON"))
    ]
    renderer.render(state)
    pygame.image.save(screen, str(output / "map-summon-origins.png"))
    pygame.quit()


if __name__ == "__main__":
    capture()
