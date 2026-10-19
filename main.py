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


# 한 프레임에 반영할 최대 시간(초). 일시정지 직후나 창 끌기 같은 프레임 지연이
# 한꺼번에 계산되어 잡귀가 순간 이동하거나 공격이 몰아서 실행되는 일을 막는다.
MAX_FRAME_SECONDS = 0.1


def _advance_game(game, input_handler, dt):
    """팝업으로 멈춘 동안에는 게임 시간을 진행하지 않는다(재개하면 멈춘 시점부터 이어진다)."""
    if input_handler.paused:
        return
    game.update(min(dt, MAX_FRAME_SECONDS))


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

        _advance_game(game, input_handler, dt)
        state = game.get_state()
        renderer.render(
            state,
            input_handler.quit_confirm,
            input_handler.start_confirm,
            input_handler.buy_confirm,
            input_handler.no_tower_warning,
            input_handler.boss_warning,
            input_handler.board_view,
            input_handler.give_up_confirm,
        )
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
