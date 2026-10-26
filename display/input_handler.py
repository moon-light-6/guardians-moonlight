from typing import Optional

import pygame

from config import PANEL_X
from display.ui import HELP_PAGE_COUNT, ButtonLayer
from display.map_projection import MapProjection
from game.actions import Action, ActionType
from game.economy import Economy
from game.state import GamePhase, GameState
from game.wave import WaveManager

# 정산·패배·승리 때만 팝업을 잠시 치우고 게임판을 볼 수 있다(화면 표시 방식이라 엔진은 모른다).
_RESULT_PHASES = {GamePhase.SETTLEMENT, GamePhase.GAME_OVER, GamePhase.VICTORY}

# Esc로 나가기 전에 한 번 더 묻는 단계. 이동·판매 확인 중의 Esc는 기존처럼 그 동작을 취소한다.
_GIVE_UP_PHASES = {GamePhase.WAVE_ACTIVE, GamePhase.PREPARATION, GamePhase.SETTLEMENT}


class InputHandler:
    def __init__(self, buttons: ButtonLayer, projection: MapProjection):
        self.buttons = buttons
        self.economy = Economy()
        self.projection = projection
        self.quit_confirm = False
        self.start_confirm = False
        self.buy_confirm = False
        self.no_tower_warning = False
        self.boss_warning = False
        self.board_view = False
        self.give_up_confirm = False
        self.restart_confirm = False
        self.should_quit = False
        # 게임 방법 화면의 현재 페이지(화면 전용 상태라 게임 상태에 넣지 않습니다)
        self.help_page = 0
        # 게임 중 위에 겹쳐 연 게임 방법 창(열려 있는 동안 게임 진행을 멈춥니다)
        self.help_overlay = False

    @property
    def paused(self) -> bool:
        """종료·수호 포기·재시작 확인이나 게임 방법 창이 떠 있는 동안 화면 루프는 게임 시간을 진행시키지 않는다."""
        return self.quit_confirm or self.give_up_confirm or self.restart_confirm or self.help_overlay

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
            if action_name == "OPEN_HELP":
                self.help_overlay = True
                self.help_page = 0
                return None
            if action_name == "CLOSE_HELP":
                self.help_overlay = False
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
            if action_name == "GIVE_UP_NO":
                self.give_up_confirm = False  # 멈춘 시점부터 그대로 재개
                return None
            if action_name == "GIVE_UP_YES":
                self.give_up_confirm = False
                return Action(ActionType.BACK_TO_TITLE)
            if action_name == "OPEN_RESTART_CONFIRM":
                self.restart_confirm = state.phase == GamePhase.PREPARATION
                return None
            if action_name == "RESTART_NO":
                self.restart_confirm = False
                return None
            if action_name == "RESTART_YES":
                self.restart_confirm = False
                return Action(ActionType.RESTART)
            if action_name == "OPEN_BOARD_VIEW":
                self.board_view = state.phase in _RESULT_PHASES
                return None
            if action_name == "CLOSE_BOARD_VIEW":
                self.board_view = False
                return None
            if action_name == "BACK_TO_TITLE":
                self.board_view = False
                return Action(ActionType.BACK_TO_TITLE)
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
        if state.phase in {GamePhase.GAME_OVER, GamePhase.VICTORY} and not self.board_view:
            # 성공/실패 화면은 '배치 확인' 버튼 말고 아무 곳이나 누르면 시작 화면으로 돌아갑니다.
            # 배치 확인으로 게임판을 보는 중에는 실수로 나가지 않도록 '처음으로' 버튼만 씁니다.
            return Action(ActionType.BACK_TO_TITLE)
        slot_id = self.projection.pixel_to_slot(pos)
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
            if self.help_overlay:
                self.help_overlay = False
                return None
            if self.give_up_confirm:
                # 포기 확인 중 Esc는 '계속 수호하기'와 같다.
                self.give_up_confirm = False
                return None
            if self.restart_confirm:
                # 재시작 확인 중 Esc는 '계속 수호하기'와 같다.
                self.restart_confirm = False
                return None
            if self.start_confirm or self.buy_confirm or self.no_tower_warning:
                self.start_confirm = False
                self.buy_confirm = False
                self.no_tower_warning = False
                return None
            if self.boss_warning:
                return None
            if self.board_view:
                # 배치 확인 중 Esc는 타이틀로 나가지 않고 결과 팝업으로 돌아온다.
                self.board_view = False
                return None
            if state.phase in _GIVE_UP_PHASES:
                # 소동 도중·준비·정산 단계의 Esc는 바로 나가지 않고 포기 확인 팝업을 띄운다.
                # (소동 도중이면 화면 루프가 게임 시간도 멈춘다.)
                self.give_up_confirm = True
                return None
            return Action(ActionType.CANCEL if state.phase in {GamePhase.MOVING_TOWER, GamePhase.SELL_CONFIRM} else ActionType.BACK_TO_TITLE)
        if (state.phase == GamePhase.HELP or self.help_overlay) and not self.quit_confirm \
                and key in {pygame.K_LEFT, pygame.K_RIGHT}:
            self._turn_help_page(-1 if key == pygame.K_LEFT else 1)
            return None
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
            or self.no_tower_warning or self.boss_warning or self.give_up_confirm
            or self.restart_confirm or self.help_overlay
        )

    def _continue_action(self, state: GameState) -> Action:
        """정산에서 계속하기: 다음 소동이 보스 소동이면 넘어간 뒤 큰 소동 예고 팝업을 연다."""
        self.board_view = False
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

    def _turn_help_page(self, step: int) -> None:
        self.help_page = max(0, min(HELP_PAGE_COUNT - 1, self.help_page + step))
