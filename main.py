import pygame

from config import FPS, SCREEN_HEIGHT, SCREEN_WIDTH
from display.input_handler import InputHandler
from display.renderer import Renderer
from game.engine import Game


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("월하사신")
    clock = pygame.time.Clock()

    game = Game()
    renderer = Renderer(screen)
    input_handler = InputHandler(renderer.buttons)
    state = game.reset(seed=42)

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                input_handler.quit_confirm = True
                continue
            action = input_handler.handle_event(event, state)
            if action:
                state = game.step(action)
        if input_handler.should_quit:
            running = False

        if not input_handler.quit_confirm:
            game.update(dt)
        state = game.get_state()
        renderer.render(
            state,
            input_handler.quit_confirm,
            input_handler.start_confirm,
            input_handler.buy_confirm,
            input_handler.no_tower_warning,
        )
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
