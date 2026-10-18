import pygame

from config import FPS, SCREEN_HEIGHT, SCREEN_WIDTH
from display.input_handler import InputHandler
from display.renderer import Renderer
from game.actions import ActionType
from game.engine import Game


def _apply_action(game, renderer, action):
    """Notify the view only after the engine actually upgrades a tower."""
    tower = game.state.towers.get(action.slot_id)
    previous_level = tower["level"] if tower is not None else None
    state = game.step(action)
    if (action.action_type == ActionType.UPGRADE
            and previous_level is not None
            and state.towers.get(action.slot_id) is tower
            and tower["level"] > previous_level):
        renderer.play_upgrade_effect(state, action.slot_id)
    return state


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("월하사신")
    clock = pygame.time.Clock()

    game = Game()
    renderer = Renderer(screen)
    input_handler = InputHandler(renderer.buttons, renderer.projection)
    state = game.reset(seed=42)

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                input_handler.quit_confirm = True
                continue
            if event.type == pygame.KEYDOWN and event.key == pygame.K_d:
                renderer.toggle_map_debug()
                continue
            action = input_handler.handle_event(event, state)
            if action:
                state = _apply_action(game, renderer, action)
        if input_handler.should_quit:
            running = False

        if not input_handler.quit_confirm:
            game.update(dt)
        state = game.get_state()
        renderer.render(state, input_handler.quit_confirm)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
