from typing import Optional

import pygame

from config import PANEL_X
from display.ui import ButtonLayer
from game.actions import Action, ActionType
from game.economy import Economy
from game.map import GameMap
from game.state import GamePhase, GameState
from game.wave import WaveManager


class InputHandler:
    def __init__(self, buttons: ButtonLayer):
        self.buttons = buttons
        self.map = GameMap()
        self.economy = Economy()
        self.quit_confirm = False
        self.start_confirm = False
        self.buy_confirm = False
        self.no_tower_warning = False
        self.boss_warning = False
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
                self._open_start_flow(state)
                return None
            if action_name == "CLOSE_NO_TOWER_WARNING":
                self.no_tower_warning = False
                return None
            if action_name == "CLOSE_BOSS_WARNING":
                self.boss_warning = False
                return None
            if action_name == "CONTINUE":
                return self._continue_action(state)
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
                "RESTART": Action(ActionType.RESTART),
                "CANCEL": Action(ActionType.CANCEL),
                "CYCLE_SPEED": Action(ActionType.CYCLE_SPEED),
                "UPGRADE": Action(ActionType.UPGRADE, slot_id=state.selected_slot),
                "SELL": Action(ActionType.SELL, slot_id=state.selected_slot),
                "CONFIRM_SELL": Action(ActionType.CONFIRM_SELL, slot_id=state.pending_sell_slot),
                "BEGIN_RELOCATE": Action(ActionType.BEGIN_RELOCATE, slot_id=state.selected_slot),
            }
            return mapping.get(action_name)

        if self._popup_open(state):
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
            if self.start_confirm or self.buy_confirm or self.no_tower_warning:
                self.start_confirm = False
                self.buy_confirm = False
                self.no_tower_warning = False
                return None
            if self.boss_warning:
                return None
            return Action(ActionType.CANCEL if state.phase in {GamePhase.MOVING_TOWER, GamePhase.SELL_CONFIRM} else ActionType.BACK_TO_TITLE)
        if self._popup_open(state):
            return None
        if key == pygame.K_SPACE and state.phase == GamePhase.PREPARATION:
            self._open_start_flow(state)
            return None
        if key == pygame.K_RETURN and state.phase == GamePhase.SETTLEMENT:
            return self._continue_action(state)
        return None

    def _popup_open(self, state: GameState) -> bool:
        return (
            self.quit_confirm or self.start_confirm or self.buy_confirm
            or self.no_tower_warning or self.boss_warning
        )

    def _continue_action(self, state: GameState) -> Action:
        """정산에서 계속하기: 다음 소동이 보스 소동이면 넘어간 뒤 큰 소동 예고 팝업을 연다."""
        if state.phase == GamePhase.SETTLEMENT and WaveManager.is_boss_stage(state.current_stage + 1):
            self.boss_warning = True
        return Action(ActionType.CONTINUE)

    def _open_start_flow(self, state: GameState) -> None:
        """시작 버튼: 사신이 없으면 경고, 있으면 시작 확인 팝업을 연다(규칙 판단은 Economy)."""
        if state.phase != GamePhase.PREPARATION:
            return
        if self.economy.has_defender(state):
            self.start_confirm = True
        else:
            self.no_tower_warning = True
