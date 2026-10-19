from typing import Optional

import pygame

from display.ui import HELP_PAGE_COUNT, ButtonLayer
from game.actions import Action, ActionType
from game.map import GameMap
from game.state import GamePhase, GameState


class InputHandler:
    def __init__(self, buttons: ButtonLayer):
        self.buttons = buttons
        self.map = GameMap()
        self.quit_confirm = False
        self.should_quit = False
        # 게임 방법 화면의 현재 페이지(화면 전용 상태라 게임 상태에 넣지 않습니다)
        self.help_page = 0

    def handle_event(self, event: pygame.event.Event, state: GameState) -> Optional[Action]:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._handle_mouse_down(event.pos, state)
        if event.type == pygame.KEYDOWN:
            return self._handle_key_down(event.key, state)
        return None

    def _handle_mouse_down(self, pos: tuple, state: GameState) -> Optional[Action]:
        action_name = self.buttons.handle_click(pos)
        if action_name:
            if action_name == "QUIT":
                self.quit_confirm = True
                return None
            if action_name == "QUIT_NO":
                self.quit_confirm = False
                return None
            if action_name == "QUIT_YES":
                self.should_quit = True
                return None
            if action_name in {"HELP_PREV", "HELP_NEXT"}:
                self._turn_help_page(-1 if action_name == "HELP_PREV" else 1)
                return None
            if action_name == "SHOW_HELP":
                self.help_page = 0
            mapping = {
                "START_GAME": Action(ActionType.START_GAME),
                "SHOW_HELP": Action(ActionType.SHOW_HELP),
                "BACK_TO_TITLE": Action(ActionType.BACK_TO_TITLE),
                "CONTINUE": Action(ActionType.CONTINUE),
                "RESTART": Action(ActionType.RESTART),
                "CANCEL": Action(ActionType.CANCEL),
                "START_WAVE": Action(ActionType.START_WAVE),
                "CYCLE_SPEED": Action(ActionType.CYCLE_SPEED),
                "BUY": Action(ActionType.BUY, slot_id=state.selected_slot),
                "UPGRADE": Action(ActionType.UPGRADE, slot_id=state.selected_slot),
                "SELL": Action(ActionType.SELL, slot_id=state.selected_slot),
                "CONFIRM_SELL": Action(ActionType.CONFIRM_SELL, slot_id=state.pending_sell_slot),
                "BEGIN_RELOCATE": Action(ActionType.BEGIN_RELOCATE, slot_id=state.selected_slot),
            }
            return mapping.get(action_name)

        if self.quit_confirm:
            return None
        slot_id = self.map.pixel_to_slot(pos)
        if slot_id is None:
            return None
        if state.phase == GamePhase.MOVING_TOWER:
            return Action(ActionType.RELOCATE, from_slot_id=state.moving_from_slot, to_slot_id=slot_id)
        if state.phase == GamePhase.PREPARATION or (
            state.phase == GamePhase.WAVE_ACTIVE and state.has_tower(slot_id)
        ):
            return Action(ActionType.SELECT_SLOT, slot_id=slot_id)
        return None

    def _handle_key_down(self, key: int, state: GameState) -> Optional[Action]:
        if key == pygame.K_ESCAPE:
            if state.phase == GamePhase.TITLE or self.quit_confirm:
                self.quit_confirm = not self.quit_confirm
                return None
            return Action(ActionType.CANCEL if state.phase in {GamePhase.MOVING_TOWER, GamePhase.SELL_CONFIRM} else ActionType.BACK_TO_TITLE)
        if self.quit_confirm:
            return None
        if state.phase == GamePhase.HELP and key in {pygame.K_LEFT, pygame.K_RIGHT}:
            self._turn_help_page(-1 if key == pygame.K_LEFT else 1)
            return None
        if key == pygame.K_SPACE and state.phase == GamePhase.PREPARATION:
            return Action(ActionType.START_WAVE)
        if key == pygame.K_RETURN and state.phase == GamePhase.SETTLEMENT:
            return Action(ActionType.CONTINUE)
        return None

    def _turn_help_page(self, step: int) -> None:
        self.help_page = max(0, min(HELP_PAGE_COUNT - 1, self.help_page + step))
