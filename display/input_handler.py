from typing import Optional

import pygame

from config import PANEL_X
from display.ui import ButtonLayer
from game.actions import Action, ActionType
from game.map import GameMap
from game.state import GamePhase, GameState


class InputHandler:
    def __init__(self, buttons: ButtonLayer):
        self.buttons = buttons
        self.map = GameMap()
        self.quit_confirm = False
        self.start_confirm = False
        self.buy_confirm = False
        self.should_quit = False

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
            if action_name == "OPEN_START_CONFIRM":
                self.start_confirm = state.phase == GamePhase.PREPARATION
                return None
            if action_name == "START_WAVE_NO":
                self.start_confirm = False
                return None
            if action_name == "START_WAVE_YES":
                self.start_confirm = False
                return Action(ActionType.START_WAVE)
            if action_name == "OPEN_BUY_CONFIRM":
                self.buy_confirm = state.phase == GamePhase.PREPARATION and state.selected_slot is not None
                return None
            if action_name == "BUY_NO":
                self.buy_confirm = False
                return None
            if action_name == "BUY_YES":
                self.buy_confirm = False
                return Action(ActionType.BUY, slot_id=state.selected_slot)
            mapping = {
                "START_GAME": Action(ActionType.START_GAME),
                "SHOW_HELP": Action(ActionType.SHOW_HELP),
                "BACK_TO_TITLE": Action(ActionType.BACK_TO_TITLE),
                "CONTINUE": Action(ActionType.CONTINUE),
                "RESTART": Action(ActionType.RESTART),
                "CANCEL": Action(ActionType.CANCEL),
                "CYCLE_SPEED": Action(ActionType.CYCLE_SPEED),
                "DISMISS_BOSS_WARNING": Action(ActionType.DISMISS_BOSS_WARNING),
                "UPGRADE": Action(ActionType.UPGRADE, slot_id=state.selected_slot),
                "SELL": Action(ActionType.SELL, slot_id=state.selected_slot),
                "CONFIRM_SELL": Action(ActionType.CONFIRM_SELL, slot_id=state.pending_sell_slot),
                "BEGIN_RELOCATE": Action(ActionType.BEGIN_RELOCATE, slot_id=state.selected_slot),
            }
            return mapping.get(action_name)

        if self.quit_confirm or self.start_confirm or self.buy_confirm or state.boss_warning:
            return None
        slot_id = self.map.pixel_to_slot(pos)
        if state.phase == GamePhase.WAVE_ACTIVE and slot_id is None:
            # 전투 중 어떤 돌판도 아닌 배경(오른쪽 패널 제외)을 누르면 선택을 해제한다.
            return Action(ActionType.SELECT_SLOT, slot_id=None) if pos[0] < PANEL_X else None
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
            if self.start_confirm or self.buy_confirm:
                self.start_confirm = False
                self.buy_confirm = False
                return None
            if state.boss_warning:
                return None
            return Action(ActionType.CANCEL if state.phase in {GamePhase.MOVING_TOWER, GamePhase.SELL_CONFIRM} else ActionType.BACK_TO_TITLE)
        if self.quit_confirm or self.start_confirm or self.buy_confirm or state.boss_warning:
            return None
        if key == pygame.K_SPACE and state.phase == GamePhase.PREPARATION:
            self.start_confirm = True
            return None
        if key == pygame.K_RETURN and state.phase == GamePhase.SETTLEMENT:
            return Action(ActionType.CONTINUE)
        return None
